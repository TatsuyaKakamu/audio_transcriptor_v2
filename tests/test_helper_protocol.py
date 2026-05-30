from __future__ import annotations

import stat
from pathlib import Path

import pytest

from app.core import helper as helper_mod
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


def test_run_json_helper_tolerates_progress_lines_without_callback(tmp_path) -> None:
    # Even without a callback, leading progress notices must not break parsing.
    helper = _write_exec(
        tmp_path / "apple-transcribe",
        "#!/usr/bin/env python3\n"
        "import sys\n"
        'sys.stdout.write(\'{"progress": {"fraction": 0.5}}\\n\')\n'
        'sys.stdout.write(\'{"ok": true, "transcript": {"backend": "apple_speech"}}\\n\')\n',
    )
    out = run_json_helper(name="apple-transcribe", args=["--input", "x"], explicit_path=str(helper))
    assert out["ok"] is True
    assert out["transcript"]["backend"] == "apple_speech"


def test_run_json_helper_streams_progress_to_callback(tmp_path) -> None:
    helper = _write_exec(
        tmp_path / "apple-transcribe",
        "#!/usr/bin/env python3\n"
        "import sys\n"
        'sys.stdout.write(\'{"progress": {"fraction": 0.25}}\\n\')\n'
        'sys.stdout.write(\'{"progress": {"fraction": 0.75}}\\n\')\n'
        'sys.stdout.write(\'{"ok": true, "transcript": {"backend": "apple_speech"}}\\n\')\n',
    )
    seen: list[dict] = []
    out = run_json_helper(
        name="apple-transcribe",
        args=["--input", "x"],
        explicit_path=str(helper),
        progress_callback=seen.append,
    )
    assert out["ok"] is True
    assert [p["fraction"] for p in seen] == [0.25, 0.75]


def test_run_json_helper_streaming_no_envelope_raises(tmp_path) -> None:
    helper = _write_exec(
        tmp_path / "apple-transcribe",
        "#!/usr/bin/env python3\n"
        "import sys\n"
        'sys.stdout.write(\'{"progress": {"fraction": 0.5}}\\n\')\n',
    )
    with pytest.raises(HelperProtocolError):
        run_json_helper(
            name="apple-transcribe",
            args=["--input", "x"],
            explicit_path=str(helper),
            progress_callback=lambda _p: None,
        )


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


def test_built_binary_used_when_fresh(monkeypatch, tmp_path) -> None:
    binary = tmp_path / "apple-transcribe"
    binary.write_text("bin")
    monkeypatch.setattr(helper_mod, "_built_binary", lambda name: binary)
    monkeypatch.setattr(helper_mod, "_built_binary_is_stale", lambda name, b: False)
    rebuilt: list = []
    monkeypatch.setattr(helper_mod, "_maybe_build_helper", lambda name: rebuilt.append(name))
    assert resolve_helper_path("apple-transcribe") == binary
    assert rebuilt == []  # fresh binary -> no rebuild


def test_stale_binary_triggers_rebuild(monkeypatch, tmp_path) -> None:
    stale = tmp_path / "old-apple-transcribe"
    stale.write_text("old")
    fresh = tmp_path / "new-apple-transcribe"
    fresh.write_text("new")
    monkeypatch.setattr(helper_mod, "_built_binary", lambda name: stale)
    monkeypatch.setattr(helper_mod, "_built_binary_is_stale", lambda name, b: True)
    monkeypatch.setattr(helper_mod, "_maybe_build_helper", lambda name: fresh)
    # Stale cache must be rebuilt and the fresh binary returned.
    assert resolve_helper_path("apple-transcribe") == fresh


def test_stale_binary_falls_back_when_rebuild_unavailable(monkeypatch, tmp_path) -> None:
    stale = tmp_path / "apple-transcribe"
    stale.write_text("old")
    monkeypatch.setattr(helper_mod, "_built_binary", lambda name: stale)
    monkeypatch.setattr(helper_mod, "_built_binary_is_stale", lambda name, b: True)
    monkeypatch.setattr(helper_mod, "_maybe_build_helper", lambda name: None)
    # Build skipped (e.g. non-macOS): keep using the cached binary, don't break.
    assert resolve_helper_path("apple-transcribe") == stale


def _no_build_called(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(helper_mod, "_build_attempted", set())
    monkeypatch.setattr(
        helper_mod.subprocess, "run", lambda *a, **k: calls.append(a) or None
    )
    return calls


def test_auto_build_skipped_when_opted_out(monkeypatch) -> None:
    calls = _no_build_called(monkeypatch)
    monkeypatch.setenv("AUDIO_TRANSCRIPTOR_NO_HELPER_BUILD", "1")
    monkeypatch.setattr(helper_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(helper_mod.platform, "mac_ver", lambda: ("26.0", ("", "", ""), ""))
    monkeypatch.setattr(helper_mod.shutil, "which", lambda _: "/usr/bin/swift")
    assert helper_mod._maybe_build_helper("apple-summarize") is None
    assert calls == []  # no swift build attempted


def test_auto_build_skipped_on_non_macos(monkeypatch) -> None:
    calls = _no_build_called(monkeypatch)
    monkeypatch.delenv("AUDIO_TRANSCRIPTOR_NO_HELPER_BUILD", raising=False)
    monkeypatch.setattr(helper_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(helper_mod.shutil, "which", lambda _: "/usr/bin/swift")
    assert helper_mod._maybe_build_helper("apple-summarize") is None
    assert calls == []


def test_auto_build_skipped_on_old_macos(monkeypatch) -> None:
    calls = _no_build_called(monkeypatch)
    monkeypatch.delenv("AUDIO_TRANSCRIPTOR_NO_HELPER_BUILD", raising=False)
    monkeypatch.setattr(helper_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(helper_mod.platform, "mac_ver", lambda: ("15.4", ("", "", ""), ""))
    monkeypatch.setattr(helper_mod.shutil, "which", lambda _: "/usr/bin/swift")
    assert helper_mod._maybe_build_helper("apple-summarize") is None
    assert calls == []


def test_auto_build_attempted_once_per_process(monkeypatch) -> None:
    calls = _no_build_called(monkeypatch)
    monkeypatch.delenv("AUDIO_TRANSCRIPTOR_NO_HELPER_BUILD", raising=False)
    monkeypatch.setattr(helper_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(helper_mod.platform, "mac_ver", lambda: ("26.0", ("", "", ""), ""))
    monkeypatch.setattr(helper_mod.shutil, "which", lambda _: "/usr/bin/swift")

    def fake_run(*a, **k):
        calls.append(a)

        class _R:
            returncode = 1
            stderr = "boom"

        return _R()

    monkeypatch.setattr(helper_mod.subprocess, "run", fake_run)
    assert helper_mod._maybe_build_helper("apple-summarize") is None
    assert helper_mod._maybe_build_helper("apple-summarize") is None
    assert len(calls) == 1  # second call short-circuits via _build_attempted
