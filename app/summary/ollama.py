"""Structured meeting-minutes generation via a local Ollama server."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from http.client import HTTPException

from app.config import Config
from app.core.errors import SummaryFailedError
from app.core.models import MeetingMinutes, Transcript, minutes_from_dict
from app.summary import prompts
from app.summary.base import SummaryBackend, SummaryOptions

logger = logging.getLogger(__name__)


def _strip_json_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _http_post_json(url: str, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class OllamaSummaryBackend(SummaryBackend):
    name = "ollama"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._ollama = config.summary.ollama

    def is_available(self) -> bool:
        host = self._ollama.host.rstrip("/")
        try:
            req = urllib.request.Request(f"{host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                json.loads(resp.read().decode("utf-8"))
            return True
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return False

    def summarize(self, transcript: Transcript, options: SummaryOptions) -> MeetingMinutes:
        system_prompt = prompts.system_prompt(options.language)
        user_prompt = prompts.build_user_prompt(
            transcript, max_input_chars=options.max_input_chars
        )

        url = self._ollama.host.rstrip("/") + "/api/generate"
        request_options: dict[str, object] = {"temperature": 0.2}
        if self._ollama.num_ctx > 0:
            request_options["num_ctx"] = self._ollama.num_ctx
        payload = {
            "model": self._ollama.model,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
            "format": "json",
            "options": request_options,
        }

        try:
            response = _http_post_json(url, payload, options.timeout_seconds)
        except (urllib.error.URLError, TimeoutError, OSError, HTTPException) as e:
            raise SummaryFailedError(f"Ollama request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise SummaryFailedError(f"Ollama returned non-JSON envelope: {e}") from e

        raw = response.get("response")
        if not isinstance(raw, str) or not raw.strip():
            raise SummaryFailedError("Ollama response missing 'response' field")

        try:
            parsed = json.loads(_strip_json_fence(raw))
        except json.JSONDecodeError as e:
            raise SummaryFailedError(f"Ollama 'response' is not valid JSON: {e}") from e
        if not isinstance(parsed, dict):
            raise SummaryFailedError("Ollama 'response' is not a JSON object")

        return minutes_from_dict(parsed, backend=self.name)
