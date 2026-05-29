"""Run Swift helper CLIs and exchange JSON over stdin/stdout.

Apple-specific frameworks live entirely inside Swift helper executables
(`apple-transcribe`, `apple-summarize`). Python talks to them only through this
module: locate the binary, run it, parse the JSON envelope, raise on protocol
violations.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from app.core.errors import HelperProtocolError

logger = logging.getLogger(__name__)

# Repo-root-relative Swift packages for the helpers.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER_PACKAGES = {
    "apple-transcribe": _REPO_ROOT / "helpers" / "apple-transcribe",
    "apple-summarize": _REPO_ROOT / "helpers" / "apple-summarize",
}

# Set this env var to skip the automatic `swift build` (e.g. CI, metered links).
_NO_BUILD_ENV = "AUDIO_TRANSCRIPTOR_NO_HELPER_BUILD"

# One build attempt per helper per process, so a failure isn't retried forever.
_build_attempted: set[str] = set()


def _built_binary(name: str) -> Path | None:
    pkg = _HELPER_PACKAGES.get(name)
    if pkg is None:
        return None
    candidate = pkg / ".build" / "release" / name
    return candidate if candidate.exists() else None


def _macos_supports_helpers() -> bool:
    if platform.system() != "Darwin":
        return False
    version = platform.mac_ver()[0]
    try:
        return int(version.split(".")[0]) >= 26
    except (ValueError, IndexError):
        return False


def _maybe_build_helper(name: str) -> Path | None:
    """Build the Swift helper on first use; cached for subsequent runs.

    Guarded so it only ever runs where it can succeed and help: macOS 26+,
    a `swift` toolchain present, the package sources exist, and not opted out.
    """
    if name in _build_attempted or os.environ.get(_NO_BUILD_ENV):
        return None
    _build_attempted.add(name)

    pkg = _HELPER_PACKAGES.get(name)
    if pkg is None or not (pkg / "Package.swift").exists():
        return None
    if not _macos_supports_helpers() or shutil.which("swift") is None:
        return None

    logger.info("Building Apple helper %s (first run; this may take a minute)...", name)
    try:
        proc = subprocess.run(
            ["swift", "build", "-c", "release"],
            cwd=str(pkg),
            capture_output=True,
            text=True,
            timeout=900.0,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("auto-build of helper %s failed: %s", name, e)
        return None
    if proc.returncode != 0:
        logger.warning(
            "auto-build of helper %s failed (exit %s): %s",
            name,
            proc.returncode,
            (proc.stderr or "").strip()[:300],
        )
        return None

    built = _built_binary(name)
    if built is not None:
        logger.info("Built Apple helper %s -> %s", name, built)
    return built


def resolve_helper_path(name: str, explicit_path: str | None = None) -> Path | None:
    """Find a helper executable.

    Order: explicit config path -> repo build directory -> PATH -> auto-build.
    Returns None when the helper cannot be located or built.
    """
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        return candidate if candidate.exists() else None

    built = _built_binary(name)
    if built is not None:
        return built

    found = shutil.which(name)
    if found:
        return Path(found)

    return _maybe_build_helper(name)


def _run(path: Path, args: list[str], input_text: str | None, timeout: float | None) -> str:
    try:
        proc = subprocess.run(
            [str(path), *args],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise HelperProtocolError(f"helper {path.name} timed out after {timeout}s") from e
    except OSError as e:
        raise HelperProtocolError(f"failed to execute helper {path}: {e}") from e

    if proc.returncode != 0 and not proc.stdout.strip():
        stderr = (proc.stderr or "").strip()
        raise HelperProtocolError(
            f"helper {path.name} exited {proc.returncode}: {stderr[:200]}"
        )
    return proc.stdout


def _parse_envelope(stdout: str, helper_name: str) -> dict:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise HelperProtocolError(f"helper {helper_name} returned non-JSON output: {e}") from e
    if not isinstance(envelope, dict):
        raise HelperProtocolError(f"helper {helper_name} returned a non-object JSON value")
    return envelope


def _extract_envelope(
    lines: Iterable[str],
    helper_name: str,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    """Pick the result envelope out of a helper's newline-delimited JSON output.

    Helpers may interleave progress notices (``{"progress": {...}}``) before the
    final result envelope (the object carrying ``"ok"``). Progress objects are
    dispatched to ``progress_callback`` as they arrive; the last envelope wins.
    Lines that are not JSON objects are ignored so a single-line response (the
    common case) and a streamed multi-line response are both handled.
    """
    envelope: dict | None = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if "ok" not in obj and isinstance(obj.get("progress"), dict):
            if progress_callback is not None:
                progress_callback(obj["progress"])
            continue
        envelope = obj
    if envelope is None:
        raise HelperProtocolError(f"helper {helper_name} returned no JSON envelope")
    return envelope


def _stream_lines(
    path: Path, args: list[str], input_text: str | None, timeout: float | None
) -> Iterator[str]:
    """Run a helper and yield its stdout lines as they arrive.

    Used when a progress callback is supplied so notices reach the UI live
    instead of all at once after the process exits. Enforces ``timeout`` with a
    watchdog that kills the process; surfaces stderr only when nothing was
    written to stdout (parity with the buffered ``_run``).
    """
    try:
        proc = subprocess.Popen(
            [str(path), *args],
            stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as e:
        raise HelperProtocolError(f"failed to execute helper {path}: {e}") from e

    timed_out = False
    timer: threading.Timer | None = None
    if timeout is not None:

        def _kill() -> None:
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(timeout, _kill)
        timer.start()

    yielded = 0
    try:
        if input_text is not None and proc.stdin is not None:
            proc.stdin.write(input_text)
            proc.stdin.close()
        assert proc.stdout is not None
        for line in proc.stdout:
            yielded += 1
            yield line
        proc.wait()
    finally:
        if timer is not None:
            timer.cancel()

    if timed_out:
        raise HelperProtocolError(f"helper {path.name} timed out after {timeout}s")
    if yielded == 0 and proc.returncode not in (0, None):
        stderr = (proc.stderr.read() if proc.stderr is not None else "").strip()
        raise HelperProtocolError(f"helper {path.name} exited {proc.returncode}: {stderr[:200]}")


def run_helper_check(name: str, explicit_path: str | None = None) -> bool:
    """Return True iff `<helper> --check` reports availability."""
    path = resolve_helper_path(name, explicit_path)
    if path is None:
        return False
    try:
        stdout = _run(path, ["--check"], input_text=None, timeout=20.0)
        envelope = _parse_envelope(stdout, name)
    except HelperProtocolError as e:
        logger.info("helper %s --check failed: %s", name, e)
        return False
    return bool(envelope.get("ok"))


def run_json_helper(
    *,
    name: str,
    args: list[str],
    input_json: dict | None = None,
    timeout: float | None = None,
    explicit_path: str | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    """Run a helper, returning the inner payload of an `{"ok": true, ...}` envelope.

    When ``progress_callback`` is given the helper is run in streaming mode and
    any ``{"progress": {...}}`` notices it emits before the final envelope are
    forwarded live. Without it the helper is run buffered (the common case).

    Raises HelperProtocolError when the helper is missing, crashes, returns
    malformed JSON, or reports `ok: false`.
    """
    path = resolve_helper_path(name, explicit_path)
    if path is None:
        raise HelperProtocolError(f"helper {name} not found")

    input_text = json.dumps(input_json) if input_json is not None else None
    if progress_callback is not None:
        envelope = _extract_envelope(
            _stream_lines(path, args, input_text, timeout), name, progress_callback
        )
    else:
        stdout = _run(path, args, input_text=input_text, timeout=timeout)
        envelope = _extract_envelope(stdout.splitlines(), name)

    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        code = error.get("code", "UNKNOWN") if isinstance(error, dict) else "UNKNOWN"
        message = error.get("message", "") if isinstance(error, dict) else str(error)
        raise HelperProtocolError(f"helper {name} error [{code}]: {message}")

    return envelope
