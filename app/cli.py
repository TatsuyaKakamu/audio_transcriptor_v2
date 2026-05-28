from __future__ import annotations

import argparse
import fcntl
import logging
import sys
import time
from pathlib import Path

import send2trash

from app.config import AppConfig, load_config
from app.services import (
    auto_pr,
    file_naming,
    markdown_writer,
    minutes,
    minutes_generator,
    notifier,
    progress,
    transcriber,
)

logger = logging.getLogger("mlx_audio_transcriptor.cli")

_LOCK_PATH = Path.home() / ".cache" / "mlx-audio-transcriptor" / "scan.lock"
_LOG_DIR = Path.home() / "Library" / "Logs" / "mlx-audio-transcriptor"
_CLI_LOG_PATH = _LOG_DIR / "cli.log"
_STABILITY_TIMEOUT_SEC = 120.0
_STABILITY_POLL_SEC = 1.0
_RESCAN_MAX_PASSES = 100


def _already_transcribed(source: Path) -> bool:
    parent = source.parent
    stem = source.stem
    if (parent / f"{stem}.transcript.md").exists():
        return True
    for sibling in parent.glob(f"{stem}.transcript.*.md"):
        if sibling.is_file():
            return True
    return False


def _wait_until_stable(path: Path, stability_seconds: float) -> bool:
    if stability_seconds <= 0:
        return path.exists()

    deadline = time.monotonic() + _STABILITY_TIMEOUT_SEC
    last_size = -1
    last_mtime = -1.0
    last_change = time.monotonic()

    while time.monotonic() < deadline:
        try:
            st = path.stat()
        except FileNotFoundError:
            return False
        if st.st_size != last_size or st.st_mtime != last_mtime:
            last_size = st.st_size
            last_mtime = st.st_mtime
            last_change = time.monotonic()
        elif time.monotonic() - last_change >= stability_seconds:
            return True
        time.sleep(_STABILITY_POLL_SEC)

    logger.warning("stability timeout for %s; will retry on next event", path)
    return False


def _transcribe_one(path: Path, cfg: AppConfig) -> None:
    logger.info("transcribing: %s", path)
    notifier.notify("文字起こし開始", path.name)
    callback = progress.make_milestone_callback(path.name)
    result = transcriber.transcribe(path, cfg.model, cfg.language, progress_callback=callback)
    output_path = file_naming.resolve_output_path(path)
    markdown_writer.write(result, output_path)
    notifier.notify("文字起こし完了", f"{path.name} → {output_path.name}")
    logger.info("wrote markdown: %s", output_path)

    minutes_result = None
    if cfg.minutes.enabled:
        minutes_result = minutes.run_for(
            transcript_path=output_path,
            audio_path=path,
            transcript_text=minutes_generator.transcript_plain_text(result),
            language=cfg.language,
            whisper_model=cfg.model,
            cfg=cfg.minutes,
            notify=notifier.notify,
        )

    pr_ok = True
    if cfg.auto_pr.enabled:
        pr_ok = auto_pr.publish_pair(
            transcript_path=output_path,
            minutes_path=minutes_result.output_path if minutes_result else None,
            audio_path=path,
            cfg=cfg.auto_pr,
        )

    if cfg.trash_source_after_success and pr_ok:
        try:
            send2trash.send2trash(str(path))
            logger.info("moved to Trash: %s", path)
        except Exception as e:
            logger.warning("trash failed for %s: %s", path, e)


def _scan_once(cfg: AppConfig) -> tuple[int, int]:
    processed = 0
    errors = 0
    for path in sorted(cfg.watch_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in cfg.extensions:
            continue
        if _already_transcribed(path):
            continue
        if not _wait_until_stable(path, cfg.file_stability_seconds):
            continue
        try:
            _transcribe_one(path, cfg)
            processed += 1
        except Exception as e:
            errors += 1
            logger.error("failed to transcribe %s: %s", path, e, exc_info=True)
    return processed, errors


def _process_pending(cfg: AppConfig) -> int:
    if not cfg.watch_dir.is_dir():
        logger.warning("watch_dir does not exist: %s", cfg.watch_dir)
        return 0

    total_processed = 0
    total_errors = 0
    for pass_index in range(1, _RESCAN_MAX_PASSES + 1):
        processed, errors = _scan_once(cfg)
        total_processed += processed
        total_errors += errors
        if processed == 0:
            break
        logger.info(
            "rescan pass %d: processed=%d errors=%d; re-checking watch_dir for new files",
            pass_index,
            processed,
            errors,
        )
    else:
        logger.warning("rescan pass cap reached (%d); stopping", _RESCAN_MAX_PASSES)

    logger.info("scan done: processed=%d errors=%d", total_processed, total_errors)
    return 1 if total_errors else 0


def cmd_scan(cfg: AppConfig | None = None, lock_path: Path | None = None) -> int:
    cfg = cfg or load_config()
    lock_path = lock_path or _LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with open(lock_path, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info("another scan is running, exiting")
            return 0
        return _process_pending(cfg)


def cmd_capabilities() -> int:
    """Detect environment capabilities and print the auto-selected backends."""
    from app.config import load_full_config
    from app.core.capabilities import detect_capabilities
    from app.core.pipeline import build_pipeline, describe_selection

    cfg = load_full_config()
    caps = detect_capabilities(cfg)
    print(
        "Capabilities:\n"
        f"  macOS version:        {caps.macos_version or 'n/a'}\n"
        f"  Apple Silicon:        {caps.apple_silicon}\n"
        f"  Apple Speech:         {caps.apple_speech_available}\n"
        f"  Apple Foundation:     {caps.apple_foundation_available}\n"
        f"  mlx-whisper:          {caps.mlx_whisper_available}\n"
        f"  Ollama:               {caps.ollama_available}\n"
        f"  ffmpeg:               {caps.ffmpeg_available}\n"
        f"  API key:              {caps.api_key_available}\n"
    )
    try:
        _, selection = build_pipeline(cfg, caps)
        print(describe_selection(cfg, selection))
    except Exception as e:  # noqa: BLE001 — informational command
        print(f"No usable pipeline for this environment: {e}")
        return 1
    return 0


def cmd_transcribe(paths: list[str]) -> int:
    """Run the auto-selected pipeline over one or more audio files."""
    from app.config import load_full_config
    from app.core.pipeline import PipelineOptions, build_pipeline, describe_selection
    from app.summary.base import SummaryOptions
    from app.transcription.base import TranscriptionOptions

    cfg = load_full_config()
    try:
        pipeline, selection = build_pipeline(cfg)
    except Exception as e:  # noqa: BLE001
        logger.error("could not build pipeline: %s", e)
        return 1
    print(describe_selection(cfg, selection))

    options = PipelineOptions(
        transcription=TranscriptionOptions(
            language=cfg.app.language,
            model=cfg.transcription.model,
            vad_enabled=cfg.transcription.vad_enabled,
        ),
        summary=SummaryOptions(
            language=cfg.summary.output_language,
            max_input_chars=cfg.summary.max_input_chars,
            include_evidence=cfg.summary.include_evidence,
            timeout_seconds=cfg.summary.request_timeout_seconds,
        ),
    )

    errors = 0
    for raw in paths:
        path = Path(raw).expanduser()
        try:
            result = pipeline.run(path, options)
            logger.info(
                "done %s: transcript=%s minutes=%s elapsed=%.1fs",
                path.name,
                result.transcript_md_path,
                result.minutes_md_path,
                result.elapsed_seconds,
            )
        except Exception as e:  # noqa: BLE001
            errors += 1
            logger.error("failed to process %s: %s", path, e, exc_info=True)
    return 1 if errors else 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="app.cli", description="mlx-audio-transcriptor headless CLI")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="scan watch_dir for pending audio files and transcribe them")
    sub.add_parser("capabilities", help="show detected backends and the auto selection")
    tr = sub.add_parser("transcribe", help="transcribe + summarize specific audio files")
    tr.add_argument("paths", nargs="+", help="audio file paths to process")
    return p


def _setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_h = logging.FileHandler(_CLI_LOG_PATH, mode="a", encoding="utf-8")
        file_h.setFormatter(fmt)
        root.addHandler(file_h)
    except OSError as e:
        root.warning("could not open cli log file %s: %s", _CLI_LOG_PATH, e)


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    args = _build_parser().parse_args(argv)
    if args.command == "scan":
        return cmd_scan()
    if args.command == "capabilities":
        return cmd_capabilities()
    if args.command == "transcribe":
        return cmd_transcribe(args.paths)
    return 2


if __name__ == "__main__":
    sys.exit(main())
