from pathlib import Path

from app.models.types import TranscriptionResult


def format_time(sec: float) -> str:
    total_ms = round(sec * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, ms = divmod(remainder, 1_000)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"
    return f"{minutes:02d}:{seconds:02d}.{ms:03d}"


def build_markdown(result: TranscriptionResult) -> str:
    lines = [
        "---",
        f"language: {result.language}",
        f"model: {result.model}",
        "---",
        "",
        "## Transcript",
        "",
    ]
    for seg in result.segments:
        start = format_time(seg.start_sec)
        end = format_time(seg.end_sec)
        lines.append(f"- [{start} - {end}] {seg.text}")
    return "\n".join(lines) + "\n"


def write(result: TranscriptionResult, output_path: Path) -> None:
    content = build_markdown(result)
    output_path.write_text(content, encoding="utf-8")
