from pathlib import Path


def resolve_output_path(source_path: Path) -> Path:
    stem = source_path.stem
    parent = source_path.parent
    candidate = parent / f"{stem}.transcript.md"
    if not candidate.exists():
        return candidate
    n = 1
    while True:
        candidate = parent / f"{stem}.transcript.{n}.md"
        if not candidate.exists():
            return candidate
        n += 1
