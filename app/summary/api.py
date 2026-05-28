"""Meeting-minutes generation via an external, OpenAI-compatible chat API."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from http.client import HTTPException

from app.config import Config
from app.core.errors import SummaryFailedError
from app.core.models import MeetingMinutes, Transcript, minutes_from_dict
from app.summary import prompts
from app.summary.base import SummaryBackend, SummaryOptions

logger = logging.getLogger(__name__)


def _http_post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class ApiSummaryBackend(SummaryBackend):
    name = "api"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._api = config.summary.api

    def _api_key(self) -> str | None:
        return os.environ.get(self._api.api_key_env) if self._api.api_key_env else None

    def is_available(self) -> bool:
        return bool(self._api_key())

    def summarize(self, transcript: Transcript, options: SummaryOptions) -> MeetingMinutes:
        api_key = self._api_key()
        if not api_key:
            raise SummaryFailedError(
                f"API key env var {self._api.api_key_env!r} is not set"
            )

        system_prompt = prompts.system_prompt(options.language)
        user_prompt = prompts.build_user_prompt(
            transcript, max_input_chars=options.max_input_chars
        )
        url = self._api.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self._api.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        try:
            response = _http_post_json(url, payload, headers, options.timeout_seconds)
        except (urllib.error.URLError, TimeoutError, OSError, HTTPException) as e:
            raise SummaryFailedError(f"API request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise SummaryFailedError(f"API returned non-JSON envelope: {e}") from e

        try:
            content = response["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise SummaryFailedError(f"API response could not be parsed: {e}") from e
        if not isinstance(parsed, dict):
            raise SummaryFailedError("API content is not a JSON object")

        return minutes_from_dict(parsed, backend=self.name)
