from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from renderers import path_overlay_360
from renderers.video_renderer import VideoAcceleration


class FakeMsg:
    def __init__(self, which: str, payload: object) -> None:
        self._which = which
        setattr(self, which, payload)

    def which(self) -> str:
        return self._which


def test_project_path_polygon_uses_forward_depth_and_road_height() -> None:
    raw_points = np.array(
        [
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
            [20.0, 0.0, 0.0],
            [40.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    projection = np.array(
        [
            [320.0, 100.0, 0.0],
            [240.0, 0.0, 100.0],
            [1.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )

    polygon = path_overlay_360.project_path_polygon(
        raw_points,
        projection,
        frame_width=640,
        frame_height=480,
        z_offset=1.2,
    )

    assert polygon.shape[1] == 2
    assert polygon.shape[0] >= 4
    assert np.all(polygon[:, 0] >= 0)
    assert np.all(polygon[:, 0] <= 640)
    assert np.all(polygon[:, 1] >= 0)
    assert np.all(polygon[:, 1] <= 480)


def test_build_path_overlay_frames_aligns_to_wide_frame_id(monkeypatch: pytest.MonkeyPatch) -> None:
    projection = np.array(
        [
            [320.0, 100.0, 0.0],
            [240.0, 0.0, 100.0],
            [1.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    monkeypatch.setattr(path_overlay_360, "wide_camera_projection_matrix", lambda _state: projection)
    monkeypatch.setattr(path_overlay_360, "_path_height_meters", lambda _state: 1.2)

    position = SimpleNamespace(
        x=[0.0, 10.0, 20.0, 40.0],
        y=[0.0, 0.0, 0.0, 0.0],
        z=[0.0, 0.0, 0.0, 0.0],
    )
    messages = [
        FakeMsg("liveCalibration", SimpleNamespace()),
        FakeMsg("roadCameraState", SimpleNamespace()),
        FakeMsg("deviceState", SimpleNamespace()),
        FakeMsg("wideRoadEncodeIdx", SimpleNamespace(frameId=2000, timestampSof=10, timestampEof=20)),
        FakeMsg("modelV2", SimpleNamespace(frameId=123, timestampEof=20, position=position)),
    ]

    overlays = path_overlay_360.build_path_overlay_frames(
        [messages],
        start_seconds=100,
        length_seconds=1,
        frame_width=640,
        frame_height=480,
    )

    assert 0 in overlays
    assert overlays[0].route_seconds == 100.0


def test_build_openpilot_ui_overlay_steps_aligns_to_wide_frame_id() -> None:
    position = SimpleNamespace(
        x=[0.0, 10.0, 20.0, 40.0],
        y=[0.0, 0.0, 0.0, 0.0],
        z=[0.0, 0.0, 0.0, 0.0],
    )
    messages = [
        FakeMsg("liveCalibration", SimpleNamespace()),
        FakeMsg("roadCameraState", SimpleNamespace()),
        FakeMsg("deviceState", SimpleNamespace()),
        FakeMsg("wideRoadEncodeIdx", SimpleNamespace(frameId=4000, timestampSof=10, timestampEof=20)),
        FakeMsg("modelV2", SimpleNamespace(frameId=123, timestampEof=20, position=position)),
    ]

    steps = path_overlay_360.build_openpilot_ui_overlay_steps(
        [messages],
        start_seconds=200,
        length_seconds=1,
    )

    assert 0 in steps
    assert steps[0].route_seconds == 200.0
    assert steps[0].camera_ref.route_frame_id == 4000
    assert steps[0].wide_camera_ref == steps[0].camera_ref


def test_compute_ui_camera_source_crop_inverts_camera_view_mapping() -> None:
    content_rect = path_overlay_360.FloatRect(100.0, 50.0, 800.0, 400.0)
    camera_transform = np.array(
        [
            [2.0, 0.0, -0.25],
            [0.0, 2.0, 0.1],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )

    source_crop = path_overlay_360.compute_ui_camera_source_crop(
        frame_width=1000,
        frame_height=500,
        content_rect=content_rect,
        camera_transform=camera_transform,
    )

    assert source_crop.x == pytest.approx(312.5)
    assert source_crop.y == pytest.approx(112.5)
    assert source_crop.width == pytest.approx(500.0)
    assert source_crop.height == pytest.approx(250.0)
    assert 0 <= source_crop.x <= 1000
    assert 0 <= source_crop.y <= 500
    assert source_crop.x + source_crop.width <= 1000
    assert source_crop.y + source_crop.height <= 500


def test_compute_ui_panel_footprint_maps_content_to_source_crop() -> None:
    content_rect = path_overlay_360.FloatRect(100.0, 50.0, 800.0, 400.0)
    source_crop = path_overlay_360.FloatRect(312.5, 112.5, 500.0, 250.0)

    footprint = path_overlay_360.compute_ui_panel_footprint(
        panel_width=1000,
        panel_height=500,
        content_rect=content_rect,
        source_crop=source_crop,
    )

    scale_x = footprint.width / 1000.0
    scale_y = footprint.height / 500.0
    mapped_content = path_overlay_360.FloatRect(
        footprint.x + (content_rect.x * scale_x),
        footprint.y + (content_rect.y * scale_y),
        content_rect.width * scale_x,
        content_rect.height * scale_y,
    )
    assert mapped_content.x == pytest.approx(source_crop.x)
    assert mapped_content.y == pytest.approx(source_crop.y)
    assert mapped_content.width == pytest.approx(source_crop.width)
    assert mapped_content.height == pytest.approx(source_crop.height)


def test_render_path_overlay_frame_writes_alpha() -> None:
    polygon = np.array(
        [
            [300.0, 460.0],
            [310.0, 300.0],
            [330.0, 300.0],
            [340.0, 460.0],
        ],
        dtype=np.float32,
    )

    frame = path_overlay_360.render_path_overlay_frame(640, 480, polygon)

    assert frame.shape == (480, 640, 4)
    assert frame[:, :, 3].max() > 0


def test_360_path_filter_overlays_path_before_hstack_and_v360() -> None:
    filter_complex = path_overlay_360.build_360_path_filter_complex(
        start_seconds=93,
        length_seconds=4,
        wide_height=1208,
    )

    assert "[wide][path]overlay=0:0:format=auto[wide_path]" in filter_complex
    assert filter_complex.index("[wide][path]overlay") < filter_complex.index("[driver][wide_path]hstack")
    assert filter_complex.index("[driver][wide_path]hstack") < filter_complex.index("v360=dfisheye:equirect")
    assert "trim=start=33:duration=4" in filter_complex
    assert "crop=iw:1208[driver]" in filter_complex


def test_360_path_ffmpeg_command_uses_overlay_png_sequence() -> None:
    accel = VideoAcceleration(name="cpu", decoder_args=(), encoder_args=("-c:v", "libx265", "-vtag", "hvc1"))

    command = path_overlay_360.build_360_path_ffmpeg_command(
        driver_input="concat:/tmp/d/0.hevc",
        wide_input="concat:/tmp/e/0.hevc",
        overlay_pattern="/tmp/overlay-%05d.png",
        filter_complex="[vout]",
        accel=accel,
        target_mb=8,
        length_seconds=4,
        output_path="/tmp/out.mp4",
    )

    assert command[0] == "ffmpeg"
    assert "-framerate" in command
    assert "/tmp/overlay-%05d.png" in command
    assert command[command.index("-map") + 1] == "[vout]"
    assert command[-1] == "/tmp/out.mp4"
