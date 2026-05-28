"""Pytest fixtures/stubs.

On machines without the macOS-only ML dependencies installed (e.g. CI on Linux)
we install lightweight stubs so pure-Python tests can still import modules that
transitively pull in `mlx_whisper`. On a real install the real modules are used.
"""

from __future__ import annotations

import importlib
import json
import stat
import sys
import types
from pathlib import Path

import pytest


def _ensure_stub(name: str) -> None:
    try:
        importlib.import_module(name)
    except Exception:
        sys.modules[name] = types.ModuleType(name)


_ensure_stub("mlx_whisper")

# `tqdm` is pulled in by app.services.transcriber; provide a minimal stub so
# tests that import cli/transcriber transitively can still collect.
if "tqdm" not in sys.modules:
    try:
        importlib.import_module("tqdm")
    except Exception:
        _tqdm_stub = types.ModuleType("tqdm")

        class _Tqdm:  # pragma: no cover - only used if real tqdm missing
            def __init__(self, *args, **kwargs):
                pass

            def update(self, n=1):
                pass

            def close(self):
                pass

        _tqdm_stub.tqdm = _Tqdm
        sys.modules["tqdm"] = _tqdm_stub


_FAKE_HELPER_TEMPLATE = """#!/usr/bin/env python3
import json
import sys

CHECK = {check!r}
MAIN = {main!r}

argv = sys.argv[1:]
if "--check" in argv:
    sys.stdout.write(CHECK)
    sys.exit(0)
if "--stdin" in argv:
    sys.stdin.read()
sys.stdout.write(MAIN)
sys.exit(0 if MAIN.strip().startswith('{{') and '"ok": true' in MAIN else 0)
"""


@pytest.fixture
def make_fake_helper(tmp_path: Path):
    """Build an executable stub that mimics a Swift helper's JSON protocol.

    Returns the path; point config.advanced.apple_*_path at it.
    """

    def _make(name: str, *, check: dict, main: dict) -> Path:
        script = tmp_path / name
        script.write_text(
            _FAKE_HELPER_TEMPLATE.format(check=json.dumps(check), main=json.dumps(main)),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return script

    return _make
