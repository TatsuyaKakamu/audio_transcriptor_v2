"""Detect which backends are usable in the current environment.

Each probe is a module-level function so tests can monkeypatch them
individually. `detect_capabilities` simply composes the probes.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import Config
from app.core.helper import run_helper_check

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Capabilities:
    macos_version: str | None
    apple_silicon: bool
    apple_speech_available: bool
    apple_foundation_available: bool
    mlx_whisper_available: bool
    ollama_available: bool
    ffmpeg_available: bool


def detect_macos_version() -> str | None:
    version = platform.mac_ver()[0]
    return version or None


def detect_apple_silicon() -> bool:
    return platform.machine() == "arm64"


def detect_apple_speech(config: Config) -> bool:
    return run_helper_check("apple-transcribe", config.advanced.apple_transcribe_path or None)


def detect_apple_foundation(config: Config) -> bool:
    return run_helper_check("apple-summarize", config.advanced.apple_summarize_path or None)


def detect_mlx_whisper() -> bool:
    return importlib.util.find_spec("mlx_whisper") is not None


def detect_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def detect_ollama(config: Config) -> bool:
    host = config.summary.ollama.host.rstrip("/")
    try:
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            json.loads(resp.read().decode("utf-8"))
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass
    ollama_bin = shutil.which("ollama")
    if ollama_bin is None:
        return False
    try:
        proc = subprocess.run(
            [ollama_bin, "list"], capture_output=True, text=True, timeout=5.0
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def detect_capabilities(config: Config | None = None) -> Capabilities:
    config = config or Config()
    caps = Capabilities(
        macos_version=detect_macos_version(),
        apple_silicon=detect_apple_silicon(),
        apple_speech_available=detect_apple_speech(config),
        apple_foundation_available=detect_apple_foundation(config),
        mlx_whisper_available=detect_mlx_whisper(),
        ollama_available=detect_ollama(config),
        ffmpeg_available=detect_ffmpeg(),
    )
    logger.info(
        "Capabilities: apple_speech=%s apple_foundation=%s mlx_whisper=%s ollama=%s ffmpeg=%s",
        caps.apple_speech_available,
        caps.apple_foundation_available,
        caps.mlx_whisper_available,
        caps.ollama_available,
        caps.ffmpeg_available,
    )
    return caps
