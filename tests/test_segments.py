from __future__ import annotations

from app.core.models import TranscriptSegment
from app.core.segments import merge_segments_by_sentence


def _seg(start: float, end: float, text: str, speaker: str | None = None) -> TranscriptSegment:
    return TranscriptSegment(start_seconds=start, end_seconds=end, text=text, speaker=speaker)


def test_merges_fragments_until_sentence_end_japanese() -> None:
    # Fragments split mid-sentence by the recognizer, no large gaps.
    segments = [
        _seg(0.0, 1.0, "本日の"),
        _seg(1.0, 2.0, "議題は"),
        _seg(2.0, 3.0, "予算です。"),
        _seg(3.0, 4.0, "次に"),
        _seg(4.0, 5.0, "日程を決めます。"),
    ]
    merged = merge_segments_by_sentence(segments, language="ja-JP")
    assert [s.text for s in merged] == ["本日の議題は予算です。", "次に日程を決めます。"]
    assert merged[0].start_seconds == 0.0
    assert merged[0].end_seconds == 3.0
    assert merged[1].start_seconds == 3.0
    assert merged[1].end_seconds == 5.0


def test_splits_on_large_silence_gap() -> None:
    segments = [
        _seg(0.0, 1.0, "ええと"),
        _seg(5.0, 6.0, "始めましょう"),  # 4s gap, no punctuation
    ]
    merged = merge_segments_by_sentence(segments, language="ja-JP", silence_gap_sec=0.8)
    assert [s.text for s in merged] == ["ええと", "始めましょう"]


def test_comma_pause_does_not_break_line() -> None:
    # Speaker pauses after a comma; the gap should NOT split the line because
    # the clause is clearly unfinished. It joins through to the sentence end.
    segments = [
        _seg(0.0, 1.0, "本日はお忙しい中、"),
        _seg(3.0, 4.0, "お集まりいただき"),  # 2s gap after a comma
        _seg(4.0, 5.0, "ありがとうございます。"),
    ]
    merged = merge_segments_by_sentence(segments, language="ja-JP", silence_gap_sec=0.8)
    assert [s.text for s in merged] == ["本日はお忙しい中、お集まりいただきありがとうございます。"]


def test_comma_split_still_capped_by_max_block() -> None:
    # Even mid-clause, a runaway block is still capped so it cannot grow forever.
    segments = [
        _seg(0.0, 40.0, "とても長い前置きがあって、"),
        _seg(40.0, 41.0, "続きます。"),
    ]
    merged = merge_segments_by_sentence(
        segments, language="ja-JP", silence_gap_sec=0.8, max_block_sec=30.0
    )
    assert [s.text for s in merged] == ["とても長い前置きがあって、", "続きます。"]


def test_english_joins_with_space() -> None:
    segments = [
        _seg(0.0, 1.0, "Good"),
        _seg(1.0, 2.0, "morning."),
        _seg(2.0, 3.0, "Let's"),
        _seg(3.0, 4.0, "begin."),
    ]
    merged = merge_segments_by_sentence(segments, language="en-US")
    assert [s.text for s in merged] == ["Good morning.", "Let's begin."]


def test_speaker_change_starts_new_block() -> None:
    segments = [
        _seg(0.0, 1.0, "はい", speaker="A"),
        _seg(1.0, 2.0, "そうですね", speaker="B"),
    ]
    merged = merge_segments_by_sentence(segments, language="ja-JP")
    assert [s.text for s in merged] == ["はい", "そうですね"]
    assert [s.speaker for s in merged] == ["A", "B"]


def test_empty_and_whitespace_segments_dropped() -> None:
    segments = [
        _seg(0.0, 1.0, "  "),
        _seg(1.0, 2.0, "おはよう。"),
        _seg(2.0, 3.0, ""),
    ]
    merged = merge_segments_by_sentence(segments, language="ja-JP")
    assert [s.text for s in merged] == ["おはよう。"]


def test_empty_input_returns_empty() -> None:
    assert merge_segments_by_sentence([], language="ja-JP") == []


def test_already_sentence_aligned_is_idempotent() -> None:
    segments = [
        _seg(0.0, 3.0, "おはようございます。"),
        _seg(3.0, 6.0, "本日の議題は予算です。"),
    ]
    merged = merge_segments_by_sentence(segments, language="ja-JP")
    assert [s.text for s in merged] == [s.text for s in segments]
