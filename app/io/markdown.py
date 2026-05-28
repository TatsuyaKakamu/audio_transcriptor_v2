"""Render Transcript / MeetingMinutes to Markdown per the output spec."""

from __future__ import annotations

import datetime as _dt

from app.core.models import MeetingMinutes, Transcript


def format_time(sec: float) -> str:
    total_ms = round(sec * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, ms = divmod(remainder, 1_000)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"
    return f"{minutes:02d}:{seconds:02d}.{ms:03d}"


def build_transcript_markdown(transcript: Transcript) -> str:
    created_at = transcript.metadata.get("created_at") or _dt.datetime.now(
        _dt.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        f"source_audio: {transcript.source_audio_path.name}",
        f"language: {transcript.language}",
        f"transcription_backend: {transcript.backend}",
        f"created_at: {created_at}",
        "---",
        "",
        "# Transcript",
        "",
    ]
    for seg in transcript.segments:
        start = format_time(seg.start_seconds)
        end = format_time(seg.end_seconds)
        lines.append(f"- [{start} - {end}] {seg.text}")
    return "\n".join(lines) + "\n"


def _section(title: str, items: list[str]) -> list[str]:
    lines = [f"## {title}", ""]
    if items:
        lines.extend(f"- {item}" for item in items)
    else:
        lines.append("- なし")
    lines.append("")
    return lines


def build_minutes_markdown(
    minutes: MeetingMinutes,
    transcript: Transcript,
    transcript_md_name: str,
) -> str:
    lines = [
        "---",
        f"title: {minutes.title}",
        f"date: {minutes.date or ''}",
        f"source_audio: {transcript.source_audio_path.name}",
        f"transcript: {transcript_md_name}",
        f"summary_backend: {minutes.backend}",
        "---",
        "",
        f"# {minutes.title}",
        "",
        "## 概要",
        "",
        minutes.summary or "（概要なし）",
        "",
    ]

    lines.extend(_section("決定事項", minutes.decisions))

    lines.append("## アクションアイテム")
    lines.append("")
    if minutes.action_items:
        lines.append("| 担当 | タスク | 期限 |")
        lines.append("|---|---|---|")
        for item in minutes.action_items:
            owner = item.owner or ""
            due = item.due_date or ""
            lines.append(f"| {owner} | {item.task} | {due} |")
    else:
        lines.append("- なし")
    lines.append("")

    lines.extend(_section("未解決事項", minutes.open_questions))
    lines.extend(_section("リスク", minutes.risks))

    lines.append("---")
    lines.append(f"原文書き起こし: [{transcript_md_name}]({transcript_md_name})")
    return "\n".join(lines) + "\n"
