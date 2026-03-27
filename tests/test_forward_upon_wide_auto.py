from __future__ import annotations

from pathlib import Path

from core import clip_orchestrator, forward_upon_wide
from renderers import video_renderer


def test_select_download_file_types_adds_qlogs_for_auto_forward_upon_wide() -> None:
    assert clip_orchestrator.select_download_file_types(
        "forward_upon_wide",
        qcam=False,
        forward_upon_wide_h="auto",
    ) == ("ecameras", "cameras", "qlogs", "logs")


def test_find_route_log_prefers_qlog(tmp_path: Path) -> None:
    segment_dir = tmp_path / "2025-02-25--route--1"
    segment_dir.mkdir(parents=True)
    (segment_dir / "rlog.bz2").write_bytes(b"")
    (segment_dir / "qlog.bz2").write_bytes(b"")

    found = forward_upon_wide.find_route_log("dongle|2025-02-25--route", tmp_path)

    assert found == segment_dir / "qlog.bz2"


def test_resolve_auto_forward_upon_wide_layout_uses_logged_camera_config(monkeypatch) -> None:
    monkeypatch.setattr(
        forward_upon_wide,
        "inspect_logged_camera_alignment",
        lambda *args, **kwargs: forward_upon_wide.LoggedCameraAlignment(
            device_type="mici",
            road_sensor="os04c10",
            wide_sensor="os04c10",
            wide_from_device_euler=(0.0, 0.0, 0.0),
        ),
    )

    layout = forward_upon_wide.resolve_auto_forward_upon_wide_layout(
        "dongle|2025-02-25--route",
        data_dir="/tmp/data",
        openpilot_dir="/tmp/openpilot",
        forward_dimensions=(1344, 760),
        wide_dimensions=(1344, 760),
    )

    assert layout is not None
    assert layout.overlay_width == 501
    assert layout.overlay_height == 283
    assert layout.x == 422
    assert layout.y == 238
    assert layout.source == "mici/os04c10"


def test_render_video_clip_auto_forward_upon_wide_prefers_warp(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "2025-02-25--route--1").mkdir(parents=True)
    output_path = tmp_path / "out.mp4"

    commands: list[list[str]] = []

    def fake_probe(path: Path) -> tuple[int, int]:
        if path.name == "fcamera.hevc":
            return (1344, 760)
        return (1344, 760)

    monkeypatch.setattr(video_renderer, "_probe_video_dimensions", fake_probe)
    monkeypatch.setattr(
        video_renderer,
        "resolve_auto_forward_upon_wide_warp",
        lambda *args, **kwargs: forward_upon_wide.ForwardUponWideWarp(
            canvas_width=1344,
            canvas_height=760,
            x0=10.0,
            y0=20.0,
            x1=1200.0,
            y1=18.0,
            x2=50.0,
            y2=700.0,
            x3=1240.0,
            y3=710.0,
            source="test",
        ),
    )
    monkeypatch.setattr(video_renderer, "_run_logged", lambda command: commands.append(command))

    video_renderer.render_video_clip(
        video_renderer.VideoRenderOptions(
            render_type="forward_upon_wide",
            data_dir=str(data_dir),
            route_or_segment="dongle|2025-02-25--route",
            start_seconds=90,
            length_seconds=15,
            target_mb=9,
            file_format="h264",
            acceleration="cpu",
            forward_upon_wide_h="auto",
            openpilot_dir="/tmp/openpilot",
            output_path=str(output_path),
        )
    )

    filter_index = commands[0].index("-filter_complex") + 1
    assert "perspective=" in commands[0][filter_index]
    assert "sense=destination" in commands[0][filter_index]
    assert "overlay=0:0" in commands[0][filter_index]


def test_render_video_clip_auto_forward_upon_wide_falls_back_to_layout(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "2025-02-25--route--1").mkdir(parents=True)
    output_path = tmp_path / "out.mp4"

    commands: list[list[str]] = []

    monkeypatch.setattr(video_renderer, "_probe_video_dimensions", lambda path: (1344, 760))
    monkeypatch.setattr(video_renderer, "resolve_auto_forward_upon_wide_warp", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        video_renderer,
        "resolve_auto_forward_upon_wide_layout",
        lambda *args, **kwargs: forward_upon_wide.ForwardUponWideLayout(
            overlay_width=501,
            overlay_height=283,
            x=422,
            y=238,
            source="test",
        ),
    )
    monkeypatch.setattr(video_renderer, "_run_logged", lambda command: commands.append(command))

    video_renderer.render_video_clip(
        video_renderer.VideoRenderOptions(
            render_type="forward_upon_wide",
            data_dir=str(data_dir),
            route_or_segment="dongle|2025-02-25--route",
            start_seconds=90,
            length_seconds=15,
            target_mb=9,
            file_format="h264",
            acceleration="cpu",
            forward_upon_wide_h="auto",
            openpilot_dir="/tmp/openpilot",
            output_path=str(output_path),
        )
    )

    filter_index = commands[0].index("-filter_complex") + 1
    assert "scale=501:283" in commands[0][filter_index]
    assert "overlay=422:238" in commands[0][filter_index]
