"""Output path resolution and the Writers facade used by the pipeline."""

from __future__ import annotations

from pathlib import Path

from app.core.models import MeetingMinutes, Transcript
from app.io import jsonl, markdown

SAME_AS_AUDIO = "same_as_audio"


class Writers:
    """Write transcript/minutes artifacts next to the audio (or a fixed dir).

    The transcript is always written first, so we cache it to derive the output
    directory, the file stem, and the transcript-link used by the minutes file.
    """

    def __init__(self, output_directory: str = SAME_AS_AUDIO) -> None:
        self._output_directory = output_directory
        self._transcript: Transcript | None = None
        self._dir: Path | None = None
        self._stem: str = "transcript"
        self._transcript_md_name: str = "transcript.md"

    def _resolve_dir(self, transcript: Transcript) -> Path:
        if self._output_directory and self._output_directory != SAME_AS_AUDIO:
            target = Path(self._output_directory).expanduser()
        else:
            target = transcript.source_audio_path.parent
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _prepare(self, transcript: Transcript) -> None:
        self._transcript = transcript
        self._dir = self._resolve_dir(transcript)
        self._stem = transcript.source_audio_path.stem or "transcript"
        self._transcript_md_name = f"{self._stem}.transcript.md"

    def write_transcript_json(self, transcript: Transcript) -> Path:
        self._prepare(transcript)
        assert self._dir is not None
        path = self._dir / f"{self._stem}.transcript.json"
        return jsonl.write_transcript_json(transcript, path)

    def write_transcript_markdown(self, transcript: Transcript) -> Path:
        if self._transcript is None:
            self._prepare(transcript)
        assert self._dir is not None
        path = self._dir / f"{self._stem}.transcript.md"
        path.write_text(markdown.build_transcript_markdown(transcript), encoding="utf-8")
        return path

    def write_minutes_json(self, minutes: MeetingMinutes) -> Path:
        assert self._dir is not None, "write a transcript before minutes"
        path = self._dir / f"{self._stem}.minutes.json"
        return jsonl.write_minutes_json(minutes, path)

    def write_minutes_markdown(self, minutes: MeetingMinutes, transcript_md_path: Path) -> Path:
        assert self._dir is not None and self._transcript is not None
        path = self._dir / f"{self._stem}.minutes.md"
        content = markdown.build_minutes_markdown(
            minutes, self._transcript, transcript_md_path.name
        )
        path.write_text(content, encoding="utf-8")
        return path
