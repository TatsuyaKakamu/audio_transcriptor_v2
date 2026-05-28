"""Shared prompt text and JSON schema for structured meeting-minutes generation.

The same instructions and schema are used by every LLM-backed summary backend
(Ollama, external API) and mirror what the Swift `apple-summarize` helper uses,
so output is interchangeable regardless of which backend ran.
"""

from __future__ import annotations

from app.core.models import Transcript

MINUTES_JSON_SCHEMA = {
    "title": "string",
    "date": "string|null",
    "summary": "string",
    "decisions": ["string"],
    "action_items": [
        {
            "task": "string",
            "owner": "string|null",
            "due_date": "string|null",
            "evidence": "string|null",
        }
    ],
    "open_questions": ["string"],
    "risks": ["string"],
    "topics": ["string"],
}

SYSTEM_PROMPT_JA = """あなたは会議議事録作成アシスタントです。
以下の文字起こしを読み、指定された JSON schema に沿って議事録を作成してください。

要件:
- 出力言語は日本語。
- 事実と推測を混ぜない。
- 決定事項、アクションアイテム、未解決事項を分離する。
- アクションアイテムには担当者と期限が明示されている場合のみ入れる。
- 不明な担当者や期限は null にする。
- transcript に根拠がない内容を補完しない。

出力は必ず次の JSON schema に厳密に従った JSON のみとする:
{
  "title": "string",
  "date": "string|null",
  "summary": "string",
  "decisions": ["string"],
  "action_items": [
    {"task": "string", "owner": "string|null", "due_date": "string|null", "evidence": "string|null"}
  ],
  "open_questions": ["string"],
  "risks": ["string"],
  "topics": ["string"]
}"""

SYSTEM_PROMPT_EN = """You are a meeting-minutes assistant.
Read the transcript below and produce minutes that strictly follow the given JSON schema.

Requirements:
- Output language: English.
- Do not mix facts with speculation.
- Separate decisions, action items, and open questions.
- Only include an action item when an owner and due date are explicit; otherwise use null.
- Do not invent content that the transcript does not support.

Output ONLY JSON strictly conforming to this schema:
{
  "title": "string",
  "date": "string|null",
  "summary": "string",
  "decisions": ["string"],
  "action_items": [
    {"task": "string", "owner": "string|null", "due_date": "string|null", "evidence": "string|null"}
  ],
  "open_questions": ["string"],
  "risks": ["string"],
  "topics": ["string"]
}"""

_USER_PROMPT = """----- TRANSCRIPT BEGIN -----
{transcript}
----- TRANSCRIPT END -----"""


def system_prompt(language: str) -> str:
    return SYSTEM_PROMPT_EN if language.lower().startswith("en") else SYSTEM_PROMPT_JA


def build_user_prompt(transcript: Transcript, *, max_input_chars: int) -> str:
    text = transcript.raw_text or "\n".join(seg.text for seg in transcript.segments if seg.text)
    if len(text) > max_input_chars:
        text = text[:max_input_chars]
    return _USER_PROMPT.format(transcript=text)
