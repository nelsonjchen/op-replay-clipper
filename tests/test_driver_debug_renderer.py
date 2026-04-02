from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.driver_face_swap import DriverFaceSwapOptions
from renderers import driver_debug_renderer
from renderers import ui_renderer


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
    monkeypatch.setattr(
        driver_debug_renderer,
        "configure_ui_environment",
        lambda *args, **kwargs: {"RECORD_CODEC": "libx264"},
    )
    monkeypatch.setattr(driver_debug_renderer, "_configure_ui_recording_encoder", lambda env, _, __="auto": "cpu")
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
            route_or_url="dongle|route",
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


def test_render_driver_debug_clip_can_feed_backing_video(tmp_path, monkeypatch) -> None:
    openpilot_dir = tmp_path / "openpilot"
    openpilot_dir.mkdir()
    output_path = tmp_path / "out.mp4"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    backing_video = tmp_path / "backing.mp4"
    backing_video.write_bytes(b"fake")

    monkeypatch.setattr(driver_debug_renderer, "_has_modern_openpilot", lambda _: True)
    monkeypatch.setattr(driver_debug_renderer, "apply_openpilot_runtime_patches", lambda _: SimpleNamespace(changed=False))
    monkeypatch.setattr(driver_debug_renderer, "_ensure_fonts", lambda _: None)
    monkeypatch.setattr(driver_debug_renderer, "configure_ui_environment", lambda: {"RECORD_CODEC": "libx264"})
    monkeypatch.setattr(driver_debug_renderer, "_configure_ui_recording_encoder", lambda env, _: "cpu")
    monkeypatch.setattr(driver_debug_renderer, "_compute_ui_render_window", lambda **_: (84, 110, 1, 5))
    monkeypatch.setattr(driver_debug_renderer, "_openpilot_python_cmd", lambda _: ["python"])
    monkeypatch.setattr(driver_debug_renderer, "build_openpilot_compatible_data_dir", lambda route, path: path)
    monkeypatch.setattr(driver_debug_renderer, "render_anonymized_driver_backing_video", lambda **kwargs: backing_video)

    @contextmanager
    def _fake_headless(env, *, enabled):
        yield env

    monkeypatch.setattr(driver_debug_renderer, "temporary_headless_display", _fake_headless)
    captured: dict[str, object] = {}

    def _fake_run(cmd, *, cwd=None, env=None):
        captured["cmd"] = cmd
        output_path.write_bytes(b"fake mp4")

    monkeypatch.setattr(driver_debug_renderer, "_run", _fake_run)

    driver_debug_renderer.render_driver_debug_clip(
        driver_debug_renderer.DriverDebugRenderOptions(
            route="dongle|route",
            route_or_url="dongle|route",
            start_seconds=90,
            length_seconds=20,
            smear_seconds=5,
            target_mb=9,
            file_format="h264",
            output_path=str(output_path),
            data_dir=str(data_dir),
            openpilot_dir=str(openpilot_dir),
            headless=True,
            driver_face_swap=DriverFaceSwapOptions(mode="facefusion"),
        )
    )

    assert "--backing-video" in captured["cmd"]
    assert str(backing_video) in captured["cmd"]


def test_render_driver_debug_clip_copies_backing_selection_report(tmp_path, monkeypatch) -> None:
    openpilot_dir = tmp_path / "openpilot"
    openpilot_dir.mkdir()
    output_path = tmp_path / "out.mp4"
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(driver_debug_renderer, "_has_modern_openpilot", lambda _: True)
    monkeypatch.setattr(driver_debug_renderer, "apply_openpilot_runtime_patches", lambda _: SimpleNamespace(changed=False))
    monkeypatch.setattr(driver_debug_renderer, "_ensure_fonts", lambda _: None)
    monkeypatch.setattr(driver_debug_renderer, "configure_ui_environment", lambda: {"RECORD_CODEC": "libx264"})
    monkeypatch.setattr(driver_debug_renderer, "_configure_ui_recording_encoder", lambda env, _: "cpu")
    monkeypatch.setattr(driver_debug_renderer, "_compute_ui_render_window", lambda **_: (84, 110, 1, 5))
    monkeypatch.setattr(driver_debug_renderer, "_openpilot_python_cmd", lambda _: ["python"])
    monkeypatch.setattr(driver_debug_renderer, "build_openpilot_compatible_data_dir", lambda route, path: path)

    def _fake_render_anonymized_driver_backing_video(**kwargs):
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake backing")
        output.with_name(f"{output.stem}.driver-face-selection.json").write_text('{"selected":"donor"}\n')
        return output

    monkeypatch.setattr(
        driver_debug_renderer,
        "render_anonymized_driver_backing_video",
        _fake_render_anonymized_driver_backing_video,
    )

    @contextmanager
    def _fake_headless(env, *, enabled):
        yield env

    monkeypatch.setattr(driver_debug_renderer, "temporary_headless_display", _fake_headless)

    def _fake_run(cmd, *, cwd=None, env=None):
        output_path.write_bytes(b"fake mp4")

    monkeypatch.setattr(driver_debug_renderer, "_run", _fake_run)

    driver_debug_renderer.render_driver_debug_clip(
        driver_debug_renderer.DriverDebugRenderOptions(
            route="dongle|route",
            route_or_url="dongle|route",
            start_seconds=90,
            length_seconds=20,
            smear_seconds=5,
            target_mb=9,
            file_format="h264",
            output_path=str(output_path),
            data_dir=str(data_dir),
            openpilot_dir=str(openpilot_dir),
            headless=True,
            driver_face_swap=DriverFaceSwapOptions(mode="facefusion"),
        )
    )

    selection_report_path = output_path.with_name(f"{output_path.stem}.driver-face-selection.json")
    assert selection_report_path.read_text() == '{"selected":"donor"}\n'


def test_render_ui_clip_passes_qcam_to_big_ui_engine(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    openpilot_dir = tmp_path / "openpilot"
    openpilot_dir.mkdir()
    output_path = tmp_path / "out.mp4"
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(ui_renderer, "_has_modern_openpilot", lambda _: True)
    monkeypatch.setattr(
        ui_renderer,
        "apply_openpilot_runtime_patches",
        lambda _: SimpleNamespace(changed=False),
    )
    monkeypatch.setattr(ui_renderer, "_ensure_fonts", lambda _: None)
    monkeypatch.setattr(
        ui_renderer,
        "configure_ui_environment",
        lambda *args, **kwargs: {"RECORD_CODEC": "libx264"},
    )
    monkeypatch.setattr(ui_renderer, "_configure_ui_recording_encoder", lambda env, _, __="auto": "cpu")
    monkeypatch.setattr(ui_renderer, "detect_logged_metric", lambda *args, **kwargs: False)
    monkeypatch.setattr(ui_renderer, "_compute_ui_render_window", lambda **_: (89, 92, 0, 0))
    monkeypatch.setattr(ui_renderer, "_openpilot_python_cmd", lambda _: ["python"])
    monkeypatch.setattr(ui_renderer, "build_openpilot_compatible_data_dir", lambda route, path: path)
    monkeypatch.setattr(ui_renderer, "_trim_mp4_in_place", lambda path, trim_start_seconds: None)

    @contextmanager
    def _fake_headless(env, *, enabled):
        yield env

    monkeypatch.setattr(ui_renderer, "temporary_headless_display", _fake_headless)
    monkeypatch.setattr(ui_renderer, "_seed_ui_metric_param", lambda *args, **kwargs: None)

    captured: dict[str, object] = {}

    def _fake_run(cmd, *, cwd=None, env=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = dict(env or {})
        output_path.write_bytes(b"fake mp4")

    monkeypatch.setattr(ui_renderer, "_run", _fake_run)

    result = ui_renderer.render_ui_clip(
        ui_renderer.UIRenderOptions(
            route="dongle|route",
            start_seconds=90,
            length_seconds=2,
            smear_seconds=0,
            target_mb=9,
            file_format="h264",
            output_path=str(output_path),
            data_dir=str(data_dir),
            openpilot_dir=str(openpilot_dir),
            headless=True,
            qcam=True,
        )
    )

    assert result.output_path == output_path.resolve()
    assert "--qcam" in captured["cmd"]


def test_render_ui_clip_passes_requested_acceleration(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    openpilot_dir = tmp_path / "openpilot"
    openpilot_dir.mkdir()
    output_path = tmp_path / "out.mp4"
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(ui_renderer, "_has_modern_openpilot", lambda _: True)
    monkeypatch.setattr(
        ui_renderer,
        "apply_openpilot_runtime_patches",
        lambda _: SimpleNamespace(changed=False),
    )
    monkeypatch.setattr(ui_renderer, "_ensure_fonts", lambda _: None)
    monkeypatch.setattr(
        ui_renderer,
        "configure_ui_environment",
        lambda *args, **kwargs: {"RECORD_CODEC": "libx264"},
    )
    seen: dict[str, str] = {}

    def _fake_configure(env, _file_format, acceleration="auto"):
        seen["acceleration"] = acceleration
        return "videotoolbox"

    monkeypatch.setattr(ui_renderer, "_configure_ui_recording_encoder", _fake_configure)
    monkeypatch.setattr(ui_renderer, "detect_logged_metric", lambda *args, **kwargs: False)
    monkeypatch.setattr(ui_renderer, "_compute_ui_render_window", lambda **_: (89, 92, 0, 0))
    monkeypatch.setattr(ui_renderer, "_openpilot_python_cmd", lambda _: ["python"])
    monkeypatch.setattr(ui_renderer, "build_openpilot_compatible_data_dir", lambda route, path: path)
    monkeypatch.setattr(ui_renderer, "_trim_mp4_in_place", lambda path, trim_start_seconds: None)

    @contextmanager
    def _fake_headless(env, *, enabled):
        yield env

    monkeypatch.setattr(ui_renderer, "temporary_headless_display", _fake_headless)
    monkeypatch.setattr(ui_renderer, "_seed_ui_metric_param", lambda *args, **kwargs: None)

    def _fake_run(cmd, *, cwd=None, env=None):
        output_path.write_bytes(b"fake mp4")

    monkeypatch.setattr(ui_renderer, "_run", _fake_run)

    ui_renderer.render_ui_clip(
        ui_renderer.UIRenderOptions(
            route="dongle|route",
            start_seconds=90,
            length_seconds=2,
            smear_seconds=0,
            target_mb=9,
            file_format="h264",
            output_path=str(output_path),
            data_dir=str(data_dir),
            openpilot_dir=str(openpilot_dir),
            headless=True,
            acceleration="videotoolbox",
        )
    )

    assert seen["acceleration"] == "videotoolbox"


def test_render_driver_debug_clip_passes_requested_acceleration(tmp_path, monkeypatch) -> None:
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
    monkeypatch.setattr(
        driver_debug_renderer,
        "configure_ui_environment",
        lambda *args, **kwargs: {"RECORD_CODEC": "libx264"},
    )
    seen: dict[str, str] = {}

    def _fake_configure(env, _file_format, acceleration="auto"):
        seen["acceleration"] = acceleration
        return "videotoolbox"

    monkeypatch.setattr(driver_debug_renderer, "_configure_ui_recording_encoder", _fake_configure)
    monkeypatch.setattr(driver_debug_renderer, "_compute_ui_render_window", lambda **_: (84, 110, 1, 5))
    monkeypatch.setattr(driver_debug_renderer, "_openpilot_python_cmd", lambda _: ["python"])
    monkeypatch.setattr(driver_debug_renderer, "build_openpilot_compatible_data_dir", lambda route, path: path)

    @contextmanager
    def _fake_headless(env, *, enabled):
        yield env

    monkeypatch.setattr(driver_debug_renderer, "temporary_headless_display", _fake_headless)

    def _fake_run(cmd, *, cwd=None, env=None):
        output_path.write_bytes(b"fake mp4")

    monkeypatch.setattr(driver_debug_renderer, "_run", _fake_run)

    driver_debug_renderer.render_driver_debug_clip(
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
            acceleration="videotoolbox",
        )
    )

    assert seen["acceleration"] == "videotoolbox"
