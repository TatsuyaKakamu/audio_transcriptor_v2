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

# Sentence-final punctuation that marks a natural block boundary. Kept identical
# to the legacy merger so both pipelines split text the same way.
_SENTENCE_END = frozenset("。！？.!?")

# Languages that do not separate words with spaces; their segments are joined
# with no separator. Matched as a BCP-47 prefix (e.g. "ja-JP" → "ja").
_NO_SPACE_PREFIXES = ("ja", "zh", "yue")


def _joiner_for(language: str) -> str:
    lang = language.lower().replace("_", "-")
    return "" if any(lang == p or lang.startswith(p + "-") for p in _NO_SPACE_PREFIXES) else " "


def merge_segments_by_sentence(
    segments: list[TranscriptSegment],
    *,
    language: str = "ja-JP",
    silence_gap_sec: float = 0.8,
    max_block_sec: float = 30.0,
) -> list[TranscriptSegment]:
    """Merge fragmented segments into sentence-aligned blocks.

    A block is flushed (and a new one started) when the previous segment ends
    with sentence-final punctuation, when the silent gap to the next segment is
    at least ``silence_gap_sec``, when the block would grow longer than
    ``max_block_sec``, or when the speaker changes. Timestamps span the merged
    fragments; per-fragment ``confidence`` is dropped since it no longer applies
    to the combined text.
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
    result: list[TranscriptSegment] = []
    block_start = stripped[0].start_seconds
    block_end = stripped[0].end_seconds
    block_texts = [stripped[0].text]
    block_speaker = stripped[0].speaker

    for prev, curr in zip(stripped, stripped[1:]):
        block_len = curr.end_seconds - block_start
        gap = curr.start_seconds - prev.end_seconds
        ends_sentence = prev.text[-1] in _SENTENCE_END
        speaker_changed = curr.speaker != block_speaker

        if ends_sentence or gap >= silence_gap_sec or block_len > max_block_sec or speaker_changed:
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
