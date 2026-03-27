from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from renderers import driver_debug_renderer


def test_driver_debug_recording_skip_seconds_uses_full_hidden_preroll() -> None:
    assert driver_debug_renderer._driver_debug_recording_skip_seconds(start_seconds=90, render_start=84) == 6
    assert driver_debug_renderer._driver_debug_recording_skip_seconds(start_seconds=3, render_start=0) == 3
    assert driver_debug_renderer._driver_debug_recording_skip_seconds(start_seconds=0, render_start=0) == 0


def test_render_driver_debug_clip_skips_full_preroll_before_recording(tmp_path, monkeypatch) -> None:
    openpilot_dir = tmp_path / "openpilot"
    openpilot_dir.mkdir()
    output_path = tmp_path / "out.mp4"
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(driver_debug_renderer, "_has_modern_openpilot", lambda _: True)
    monkeypatch.setattr(
        driver_debug_renderer,
        "apply_openpilot_runtime_patches",
        lambda _: SimpleNamespace(changed=False),
    )
    monkeypatch.setattr(driver_debug_renderer, "_ensure_fonts", lambda _: None)
    monkeypatch.setattr(driver_debug_renderer, "configure_ui_environment", lambda: {"RECORD_CODEC": "libx264"})
    monkeypatch.setattr(driver_debug_renderer, "_configure_ui_recording_encoder", lambda env, _: "cpu")
    monkeypatch.setattr(driver_debug_renderer, "_compute_ui_render_window", lambda **_: (84, 110, 1, 5))
    monkeypatch.setattr(driver_debug_renderer, "_openpilot_python_cmd", lambda _: ["python"])
    monkeypatch.setattr(driver_debug_renderer, "build_openpilot_compatible_data_dir", lambda route, path: path)

    @contextmanager
    def _fake_headless(env, *, enabled):
        yield env

    monkeypatch.setattr(driver_debug_renderer, "temporary_headless_display", _fake_headless)

    captured: dict[str, object] = {}

    def _fake_run(cmd, *, cwd=None, env=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = dict(env or {})
        output_path.write_bytes(b"fake mp4")

    monkeypatch.setattr(driver_debug_renderer, "_run", _fake_run)

    result = driver_debug_renderer.render_driver_debug_clip(
        driver_debug_renderer.DriverDebugRenderOptions(
            route="dongle|route",
            start_seconds=90,
            length_seconds=20,
            smear_seconds=5,
            target_mb=9,
            file_format="h264",
            output_path=str(output_path),
            data_dir=str(data_dir),
            openpilot_dir=str(openpilot_dir),
            headless=True,
        )
    )

    assert result.output_path == output_path.resolve()
    assert captured["env"]["RECORD_SKIP_FRAMES"] == str(6 * driver_debug_renderer.UI_FRAMERATE)
    assert captured["cmd"][captured["cmd"].index("-s") + 1] == "84"
    assert captured["cmd"][captured["cmd"].index("-e") + 1] == "110"
