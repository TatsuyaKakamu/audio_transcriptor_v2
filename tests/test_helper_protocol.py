from __future__ import annotations

import stat
from pathlib import Path

import pytest

from app.core.errors import HelperProtocolError
from app.core.helper import resolve_helper_path, run_helper_check, run_json_helper


def _write_exec(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_run_helper_check_ok(make_fake_helper) -> None:
    helper = make_fake_helper(
        "apple-summarize",
        check={"ok": True, "backend": "apple_foundation", "version": "0.1.0"},
        main={"ok": True},
    )
    assert run_helper_check("apple-summarize", str(helper)) is True


def test_run_helper_check_unavailable(make_fake_helper) -> None:
    helper = make_fake_helper(
        "apple-summarize",
        check={"ok": False, "error": {"code": "UNAVAILABLE", "message": "no"}},
        main={"ok": True},
    )
    assert run_helper_check("apple-summarize", str(helper)) is False


def test_run_helper_check_missing() -> None:
    assert run_helper_check("apple-summarize", "/nonexistent/path/helper") is False


def test_run_json_helper_returns_envelope(make_fake_helper) -> None:
    helper = make_fake_helper(
        "apple-summarize",
        check={"ok": True},
        main={"ok": True, "minutes": {"title": "x"}},
    )
    out = run_json_helper(
        name="apple-summarize",
        args=["--stdin"],
        input_json={"hello": "world"},
        explicit_path=str(helper),
    )
    assert out["ok"] is True
    assert out["minutes"]["title"] == "x"


def test_run_json_helper_ok_false_raises(make_fake_helper) -> None:
    helper = make_fake_helper(
        "apple-summarize",
        check={"ok": True},
        main={"ok": False, "error": {"code": "MODEL_UNAVAILABLE", "message": "down"}},
    )
    with pytest.raises(HelperProtocolError) as exc:
        run_json_helper(name="apple-summarize", args=["--stdin"], explicit_path=str(helper))
    assert "MODEL_UNAVAILABLE" in str(exc.value)


def test_run_json_helper_non_json_raises(tmp_path) -> None:
    helper = _write_exec(
        tmp_path / "apple-summarize",
        "#!/usr/bin/env python3\nimport sys\nsys.stdout.write('this is not json')\n",
    )
    with pytest.raises(HelperProtocolError):
        run_json_helper(name="apple-summarize", args=["--stdin"], explicit_path=str(helper))


def test_run_json_helper_missing_raises() -> None:
    with pytest.raises(HelperProtocolError):
        run_json_helper(name="apple-summarize", args=[], explicit_path="/no/such/helper")


def test_resolve_helper_path_prefers_explicit(make_fake_helper) -> None:
    helper = make_fake_helper("apple-summarize", check={"ok": True}, main={"ok": True})
    assert resolve_helper_path("apple-summarize", str(helper)) == helper
    assert resolve_helper_path("apple-summarize", "/missing") is None
