from app.models.types import Segment

_SENTENCE_END = frozenset("。！？.!?")


def merge_by_conversation(
    segments: list[Segment],
    *,
    silence_gap_sec: float = 0.8,
    max_block_sec: float = 30.0,
    language: str = "ja",
) -> list[Segment]:
    if not segments:
        return []

    joiner = "" if language == "ja" else " "
    result: list[Segment] = []
    block_start = segments[0].start_sec
    block_texts: list[str] = [segments[0].text.strip()]
    block_end = segments[0].end_sec

    for prev, curr in zip(segments, segments[1:]):
        block_len = curr.end_sec - block_start
        gap = curr.start_sec - prev.end_sec
        ends_sentence = bool(prev.text.strip()) and prev.text.strip()[-1] in _SENTENCE_END

        if ends_sentence or gap >= silence_gap_sec or block_len > max_block_sec:
            result.append(Segment(block_start, block_end, joiner.join(block_texts)))
            block_start = curr.start_sec
            block_texts = [curr.text.strip()]
        else:
            block_texts.append(curr.text.strip())

        block_end = curr.end_sec

    result.append(Segment(block_start, block_end, joiner.join(block_texts)))
    return result
