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
    silence_gap_sec: float = 0.8,
    max_block_sec: float = 30.0,
) -> list[TranscriptSegment]:
    """Merge fragmented segments into sentence-aligned blocks.

    A block is flushed (and a new one started) when the previous segment ends
    with sentence-final punctuation, when the speaker changes, when the block
    would grow longer than ``max_block_sec``, or when the silent gap to the next
    segment is at least ``silence_gap_sec`` *and* the previous fragment does not
    end mid-clause (e.g. on a "、" comma). Keeping commas from triggering a gap
    split avoids breaking a line in the middle of a sentence. Timestamps span
    the merged fragments; per-fragment ``confidence`` is dropped since it no
    longer applies to the combined text.
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

    for prev, curr in zip(stripped, stripped[1:]):
        block_len = curr.end_seconds - block_start
        gap = curr.start_seconds - prev.end_seconds
        last_char = prev.text[-1]
        ends_sentence = last_char in sentence_end
        mid_clause = last_char in _CONTINUATION
        speaker_changed = curr.speaker != block_speaker
        # A pause at a comma is just a breath, not a sentence boundary — don't
        # let it break the line. ``max_block_sec`` still caps runaway blocks.
        gap_breaks = gap >= silence_gap_sec and not mid_clause

        if ends_sentence or speaker_changed or block_len > max_block_sec or gap_breaks:
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
        else:
            block_texts.append(curr.text)

        block_end = curr.end_seconds

    result.append(
        TranscriptSegment(
            start_seconds=block_start,
            end_seconds=block_end,
            text=joiner.join(block_texts),
            speaker=block_speaker,
        )
    )
    return result
