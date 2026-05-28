"""Run Swift helper CLIs and exchange JSON over stdin/stdout.

Apple-specific frameworks live entirely inside Swift helper executables
(`apple-transcribe`, `apple-summarize`). Python talks to them only through this
module: locate the binary, run it, parse the JSON envelope, raise on protocol
violations.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from app.core.errors import HelperProtocolError

logger = logging.getLogger(__name__)

# Repo-root-relative location where `swift build` drops the release binaries.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER_DIRS = {
    "apple-transcribe": _REPO_ROOT / "helpers" / "apple-transcribe" / ".build" / "release",
    "apple-summarize": _REPO_ROOT / "helpers" / "apple-summarize" / ".build" / "release",
}


def resolve_helper_path(name: str, explicit_path: str | None = None) -> Path | None:
    """Find a helper executable.

    Order: explicit config path -> repo build directory -> PATH.
    Returns None when the helper cannot be located.
    """
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        return candidate if candidate.exists() else None

    build_dir = _HELPER_DIRS.get(name)
    if build_dir is not None:
        candidate = build_dir / name
        if candidate.exists():
            return candidate

    found = shutil.which(name)
    return Path(found) if found else None


def _run(path: Path, args: list[str], input_text: str | None, timeout: float | None) -> str:
    try:
        proc = subprocess.run(
            [str(path), *args],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise HelperProtocolError(f"helper {path.name} timed out after {timeout}s") from e
    except OSError as e:
        raise HelperProtocolError(f"failed to execute helper {path}: {e}") from e

    if proc.returncode != 0 and not proc.stdout.strip():
        stderr = (proc.stderr or "").strip()
        raise HelperProtocolError(
            f"helper {path.name} exited {proc.returncode}: {stderr[:200]}"
        )
    return proc.stdout


def _parse_envelope(stdout: str, helper_name: str) -> dict:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise HelperProtocolError(f"helper {helper_name} returned non-JSON output: {e}") from e
    if not isinstance(envelope, dict):
        raise HelperProtocolError(f"helper {helper_name} returned a non-object JSON value")
    return envelope


def run_helper_check(name: str, explicit_path: str | None = None) -> bool:
    """Return True iff `<helper> --check` reports availability."""
    path = resolve_helper_path(name, explicit_path)
    if path is None:
        return False
    try:
        stdout = _run(path, ["--check"], input_text=None, timeout=20.0)
        envelope = _parse_envelope(stdout, name)
    except HelperProtocolError as e:
        logger.info("helper %s --check failed: %s", name, e)
        return False
    return bool(envelope.get("ok"))


def run_json_helper(
    *,
    name: str,
    args: list[str],
    input_json: dict | None = None,
    timeout: float | None = None,
    explicit_path: str | None = None,
) -> dict:
    """Run a helper, returning the inner payload of an `{"ok": true, ...}` envelope.

    Raises HelperProtocolError when the helper is missing, crashes, returns
    malformed JSON, or reports `ok: false`.
    """
    path = resolve_helper_path(name, explicit_path)
    if path is None:
        raise HelperProtocolError(f"helper {name} not found")

    input_text = json.dumps(input_json) if input_json is not None else None
    stdout = _run(path, args, input_text=input_text, timeout=timeout)
    envelope = _parse_envelope(stdout, name)

    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        code = error.get("code", "UNKNOWN") if isinstance(error, dict) else "UNKNOWN"
        message = error.get("message", "") if isinstance(error, dict) else str(error)
        raise HelperProtocolError(f"helper {name} error [{code}]: {message}")

    return envelope
