from __future__ import annotations

from core import render_runtime


def test_configure_ui_environment_prefers_videotoolbox_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(render_runtime.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(render_runtime, "_ffmpeg_hwaccels", lambda: frozenset({"videotoolbox"}))

    env = render_runtime.configure_ui_environment({}, acceleration="auto")

    assert env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] == "YES"
    assert env["FFMPEG_HWACCEL"] == "videotoolbox"


def test_configure_ui_environment_respects_cpu_request_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(render_runtime.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(render_runtime, "_ffmpeg_hwaccels", lambda: frozenset({"videotoolbox"}))

    env = render_runtime.configure_ui_environment({}, acceleration="cpu")

    assert env["FFMPEG_HWACCEL"] == "none"


def test_configure_ui_environment_handles_missing_ffmpeg_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(render_runtime.platform, "system", lambda: "Darwin")
    render_runtime._ffmpeg_hwaccels.cache_clear()

    def _missing_ffmpeg(*_args, **_kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(render_runtime.subprocess, "run", _missing_ffmpeg)

    env = render_runtime.configure_ui_environment({}, acceleration="auto")

    assert env["FFMPEG_HWACCEL"] == "auto"
    assert env["SCALE"] == "1"
