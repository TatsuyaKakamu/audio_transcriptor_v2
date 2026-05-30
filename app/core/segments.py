"""Backend-agnostic post-processing for transcript segments.

Streaming recognizers such as Apple's ``SpeechTranscriber`` finalize their
results at internal boundaries that often fall in the middle of a sentence, so
the raw segments break at arbitrary points rather than at punctuation. This
module re-merges those fragments into sentence-aligned blocks, mirroring the
legacy ``segment_merger.merge_by_conversation`` behaviour but operating on the
v2 ``TranscriptSegment`` model.
"""

from __future__ import annotations

from app.core.models import TranscriptSegment

# Sentence-final punctuation that marks a natural block boundary, by script.
# CJK text omits the ASCII period "." because there it is almost always a
# decimal point, abbreviation, or URL ("3.5", "U.S.", "example.com") rather than
# a sentence end. Latin text keeps "." but also accepts full-width marks.
_SENTENCE_END_CJK = frozenset("。！？!?")
_SENTENCE_END_LATIN = frozenset(".!?。！？")

# Mid-clause punctuation. A fragment ending here is clearly unfinished, so we
# keep accumulating across a pause instead of breaking the line at a comma.
_CONTINUATION = frozenset("、，,；;：:")

# Languages that do not separate words with spaces; their segments are joined
# with no separator. Matched as a BCP-47 prefix (e.g. "ja-JP" → "ja").
_NO_SPACE_PREFIXES = ("ja", "zh", "yue")


def _is_no_space_language(language: str) -> bool:
    lang = language.lower().replace("_", "-")
    return any(lang == p or lang.startswith(p + "-") for p in _NO_SPACE_PREFIXES)


def _joiner_for(language: str) -> str:
    return "" if _is_no_space_language(language) else " "


def _sentence_end_for(language: str) -> frozenset:
    return _SENTENCE_END_CJK if _is_no_space_language(language) else _SENTENCE_END_LATIN


def merge_segments_by_sentence(
    segments: list[TranscriptSegment],
    *,
    language: str = "ja-JP",
    silence_gap_sec: float | None = None,
    max_block_sec: float | None = None,
    max_speech_sec: float | None = 60.0,
) -> list[TranscriptSegment]:
    """Merge fragmented segments into sentence-aligned blocks.

    By default a block is flushed (and a new one started) only at a real
    sentence boundary: when the previous segment ends with sentence-final
    punctuation (``。！？`` for CJK, ``.!?`` for Latin) or when the speaker
    changes. A mid-sentence pause does **not** break the line, since speakers
    routinely pause to breathe or hesitate — breaking there produced line breaks
    at non-punctuation points.

    To keep a single line from growing unbounded when a speaker talks for a long
    time without sentence-final punctuation, ``max_speech_sec`` (default 60s) is
    a safety valve: once a block accumulates that much *spoken* time it is
    force-flushed. Crucially this counts only fragment durations (``end-start``),
    not silence, so long pauses never inflate it and trigger a split at a
    non-punctuation point.

    Two more safety valves are off by default:

    - ``silence_gap_sec``: when set, a silent gap of at least that many seconds
      also breaks the block, except when the previous fragment ends mid-clause
      (e.g. on a "、" comma).
    - ``max_block_sec``: when set, caps the wall-clock span (including silence)
      of a block before it is force-flushed.

    Set ``max_speech_sec`` to ``None`` as well to break on punctuation (and
    speaker) only. Timestamps span the merged fragments; per-fragment
    ``confidence`` is dropped since it no longer applies to the combined text.
    """
    stripped = [
        TranscriptSegment(
            start_seconds=s.start_seconds,
            end_seconds=s.end_seconds,
            text=s.text.strip(),
            speaker=s.speaker,
            confidence=s.confidence,
        )
        for s in segments
    ]
    stripped = [s for s in stripped if s.text]
    if not stripped:
        return []

    joiner = _joiner_for(language)
    sentence_end = _sentence_end_for(language)
    result: list[TranscriptSegment] = []
    block_start = stripped[0].start_seconds
    block_end = stripped[0].end_seconds
    block_texts = [stripped[0].text]
    block_speaker = stripped[0].speaker
    # Spoken time accumulated in the current block (silence excluded).
    block_speech = max(0.0, stripped[0].end_seconds - stripped[0].start_seconds)

    for prev, curr in zip(stripped, stripped[1:]):
        block_len = curr.end_seconds - block_start
        gap = curr.start_seconds - prev.end_seconds
        last_char = prev.text[-1]
        ends_sentence = last_char in sentence_end
        mid_clause = last_char in _CONTINUATION
        speaker_changed = curr.speaker != block_speaker
        # Gap-based splitting is opt-in. Even when enabled, a pause at a comma is
        # just a breath, not a sentence boundary, so it never breaks the line.
        gap_breaks = (
            silence_gap_sec is not None and gap >= silence_gap_sec and not mid_clause
        )
        too_long_wall = max_block_sec is not None and block_len > max_block_sec
        too_long_speech = max_speech_sec is not None and block_speech > max_speech_sec

        if ends_sentence or speaker_changed or too_long_wall or too_long_speech or gap_breaks:
            result.append(
                TranscriptSegment(
                    start_seconds=block_start,
                    end_seconds=block_end,
                    text=joiner.join(block_texts),
                    speaker=block_speaker,
                )
            )
            block_start = curr.start_seconds
            block_texts = [curr.text]
            block_speaker = curr.speaker
            block_speech = max(0.0, curr.end_seconds - curr.start_seconds)
        else:
            block_texts.append(curr.text)
            block_speech += max(0.0, curr.end_seconds - curr.start_seconds)

        block_end = curr.end_seconds

    result.append(
        TranscriptSegment(
            start_seconds=block_start,
            end_seconds=block_end,
            text=joiner.join(block_texts),
            speaker=block_speaker,
        )
    )
    # A fragment's terminal punctuation is only checked at its last character, so
    # a sentence end that lands *inside* a fragment ("はい。それでは…") would not
    # trigger a break above. Split each merged block on every sentence-final mark
    # so the line always breaks at 。！？ regardless of fragment boundaries.
    return [
        out
        for block in result
        for out in _split_block_on_sentence_end(block, sentence_end)
    ]


def _split_block_on_sentence_end(
    block: TranscriptSegment, sentence_end: frozenset
) -> list[TranscriptSegment]:
    text = block.text
    pieces: list[str] = []
    start = 0
    for i, ch in enumerate(text):
        if ch in sentence_end:
            pieces.append(text[start : i + 1])
            start = i + 1
    if start < len(text):
        pieces.append(text[start:])
    pieces = [p.strip() for p in pieces if p.strip()]
    if len(pieces) <= 1:
        return [block]
    # Distribute the block's time span across the resulting sentences in
    # proportion to their character length; exact per-sentence timing is lost
    # once fragments are merged, so this keeps timestamps monotonic and plausible.
    total_chars = sum(len(p) for p in pieces)
    span = block.end_seconds - block.start_seconds
    out: list[TranscriptSegment] = []
    cursor = block.start_seconds
    consumed = 0
    for idx, piece in enumerate(pieces):
        consumed += len(piece)
        end = (
            block.end_seconds
            if idx == len(pieces) - 1
            else block.start_seconds + span * (consumed / total_chars)
        )
        out.append(
            TranscriptSegment(
                start_seconds=cursor,
                end_seconds=end,
                text=piece,
                speaker=block.speaker,
            )
        )
        cursor = end
    return out
