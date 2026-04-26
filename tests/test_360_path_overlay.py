from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from renderers import path_overlay_360, ui_360_renderer
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


def test_spill_panel_footprint_keeps_ui_content_aligned_and_expands_outside_frame() -> None:
    content_rect = path_overlay_360.FloatRect(100.0, 50.0, 800.0, 400.0)
    source_crop = path_overlay_360.FloatRect(312.5, 112.5, 500.0, 250.0)
    spill_px = 160.0

    normal_footprint = path_overlay_360.compute_ui_panel_footprint(
        panel_width=1000,
        panel_height=500,
        content_rect=content_rect,
        source_crop=source_crop,
    )
    spill_content_rect = path_overlay_360.FloatRect(
        content_rect.x + spill_px,
        content_rect.y + spill_px,
        content_rect.width,
        content_rect.height,
    )
    spill_footprint = path_overlay_360.compute_ui_panel_footprint(
        panel_width=int(1000 + (2 * spill_px)),
        panel_height=int(500 + (2 * spill_px)),
        content_rect=spill_content_rect,
        source_crop=source_crop,
    )

    scale_x = spill_footprint.width / (1000 + (2 * spill_px))
    scale_y = spill_footprint.height / (500 + (2 * spill_px))
    mapped_spill_content = path_overlay_360.FloatRect(
        spill_footprint.x + (spill_content_rect.x * scale_x),
        spill_footprint.y + (spill_content_rect.y * scale_y),
        spill_content_rect.width * scale_x,
        spill_content_rect.height * scale_y,
    )

    assert mapped_spill_content.x == pytest.approx(source_crop.x)
    assert mapped_spill_content.y == pytest.approx(source_crop.y)
    assert mapped_spill_content.width == pytest.approx(source_crop.width)
    assert mapped_spill_content.height == pytest.approx(source_crop.height)
    assert spill_footprint.x < normal_footprint.x
    assert spill_footprint.y < normal_footprint.y
    assert spill_footprint.width > normal_footprint.width
    assert spill_footprint.height > normal_footprint.height


def test_render_model_with_standard_path_style_restores_experimental_mode() -> None:
    calls = []
    selfdrive_state = SimpleNamespace(experimentalMode=True)
    ui_state = SimpleNamespace(sm=SimpleNamespace(data={"selfdriveState": selfdrive_state}))
    view = SimpleNamespace(model_renderer=SimpleNamespace(render=lambda rect: calls.append((rect, selfdrive_state.experimentalMode))))

    path_overlay_360.render_model_with_standard_path_style(view, "content-rect", ui_state)

    assert calls == [("content-rect", False)]
    assert selfdrive_state.experimentalMode is True


def test_unpremultiply_rgba_restores_straight_color() -> None:
    rgba = np.array(
        [
            [[10, 50, 20, 128], [9, 9, 9, 0]],
        ],
        dtype=np.uint8,
    )

    result = path_overlay_360._unpremultiply_rgba(rgba)

    assert result[0, 0].tolist() == [19, 99, 39, 128]
    assert result[0, 1].tolist() == [0, 0, 0, 0]


def test_strengthen_ui_path_pixels_boosts_only_path_like_pixels() -> None:
    bgra = np.array(
        [
            [[120, 220, 20, 80], [20, 240, 20, 255], [255, 255, 255, 120], [20, 20, 220, 120]],
        ],
        dtype=np.uint8,
    )

    result = path_overlay_360.strengthen_ui_path_pixels(bgra)

    assert result[0, 0, 1] > bgra[0, 0, 1]
    assert result[0, 0, 3] > bgra[0, 0, 3]
    assert result[0, 1].tolist() == bgra[0, 1].tolist()
    assert result[0, 2].tolist() == bgra[0, 2].tolist()
    assert result[0, 3].tolist() == bgra[0, 3].tolist()


def test_alpha_over_bgra_composites_overlay_without_overwriting_transparent_pixels() -> None:
    base = np.array([[[10, 20, 30, 255], [80, 90, 100, 128]]], dtype=np.uint8)
    overlay = np.array([[[200, 100, 50, 128], [1, 2, 3, 0]]], dtype=np.uint8)

    result = path_overlay_360._alpha_over_bgra(base, overlay)

    assert result[0, 0, 3] == 255
    assert result[0, 0, 0] > base[0, 0, 0]
    assert result[0, 0, 1] > base[0, 0, 1]
    assert result[0, 0, 2] > base[0, 0, 2]
    assert result[0, 1].tolist() == base[0, 1].tolist()


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


def test_360_ui_filter_overlays_ui_before_hstack_and_v360() -> None:
    filter_complex = ui_360_renderer.build_360_ui_filter_complex(
        start_seconds=995,
        length_seconds=12,
        wide_height=760,
    )

    assert "[wide][ui]overlay=0:0:format=auto[wide_ui]" in filter_complex
    assert filter_complex.index("[wide][ui]overlay") < filter_complex.index("[driver][wide_ui]hstack")
    assert filter_complex.index("[driver][wide_ui]hstack") < filter_complex.index("v360=dfisheye:equirect")
    assert "trim=start=35:duration=12" in filter_complex
    assert "crop=iw:760[driver_raw]" in filter_complex


def test_360_ui_filter_uses_pretrimmed_driver_and_watermark_input() -> None:
    filter_complex = ui_360_renderer.build_360_ui_filter_complex(
        start_seconds=995,
        length_seconds=12,
        wide_height=760,
        driver_input_is_pretrimmed=True,
        has_driver_watermark=True,
    )

    assert "trim=start=0:duration=12" in filter_complex
    assert "trim=start=35:duration=12" in filter_complex
    assert "[driver_raw][3:v]overlay=0:0[driver]" in filter_complex


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


def test_360_ui_ffmpeg_command_uses_ui_overlay_and_watermark_sequences() -> None:
    accel = VideoAcceleration(name="cpu", decoder_args=(), encoder_args=("-c:v", "libx265", "-vtag", "hvc1"))

    command = ui_360_renderer.build_360_ui_ffmpeg_command(
        driver_input="/tmp/driver.mp4",
        wide_input="concat:/tmp/e/0.hevc",
        overlay_pattern="/tmp/ui-%05d.png",
        watermark_pattern="/tmp/watermark-%05d.png",
        audio_input=None,
        start_seconds=995,
        filter_complex="[vout]",
        accel=accel,
        target_mb=200,
        length_seconds=30,
        output_path="/tmp/out.mp4",
    )

    input_indices = [index for index, token in enumerate(command) if token == "-i"]
    assert command[0] == "ffmpeg"
    assert command[input_indices[0] + 1] == "/tmp/driver.mp4"
    assert command[input_indices[1] + 1] == "concat:/tmp/e/0.hevc"
    assert command[input_indices[2] + 1] == "/tmp/ui-%05d.png"
    assert command[input_indices[3] + 1] == "/tmp/watermark-%05d.png"
    assert command.index("/tmp/ui-%05d.png") < command.index("-filter_complex")
    assert command[command.index("-map") + 1] == "[vout]"
    assert command[-1] == "/tmp/out.mp4"


def test_360_ui_ffmpeg_command_can_mux_qcamera_audio() -> None:
    accel = VideoAcceleration(name="cpu", decoder_args=(), encoder_args=("-c:v", "libx265", "-vtag", "hvc1"))

    command = ui_360_renderer.build_360_ui_ffmpeg_command(
        driver_input="/tmp/driver.mp4",
        wide_input="concat:/tmp/e/0.hevc",
        overlay_pattern="/tmp/ui-%05d.png",
        watermark_pattern=None,
        audio_input="concat:/tmp/q/0.ts",
        start_seconds=995,
        filter_complex="[vout]",
        accel=accel,
        target_mb=200,
        length_seconds=30,
        output_path="/tmp/out.mp4",
    )

    input_indices = [index for index, token in enumerate(command) if token == "-i"]
    assert command[input_indices[2] + 1] == "/tmp/ui-%05d.png"
    assert command[input_indices[3] + 1] == "concat:/tmp/q/0.ts"
    assert command[command.index("-ss") + 1] == "35"
    assert "-map" in command
    assert "3:a:0?" in command
    assert "-c:a" in command
    assert "aac" in command
    assert "-shortest" in command


def test_render_360_ui_clip_runs_overlay_encode_and_metadata_steps(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "2025-02-25--route--16").mkdir(parents=True)
    (data_dir / "2025-02-25--route--16" / "qcamera.ts").write_bytes(b"fake")
    output_path = tmp_path / "out.mp4"
    driver_input = tmp_path / "driver-backing.mp4"
    openpilot_dir = tmp_path / "openpilot"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ui_360_renderer,
        "apply_openpilot_runtime_patches",
        lambda openpilot_dir: SimpleNamespace(changed=False),
    )
    monkeypatch.setattr(ui_360_renderer.ui_renderer, "_ensure_fonts", lambda openpilot_dir: None)
    monkeypatch.setattr(
        ui_360_renderer,
        "_video_dimensions_or_fail",
        lambda path, label: (1344, 760) if "wide" in label else (1344, 480),
    )
    def _fake_generate_ui_overlay_sequence(**kwargs):
        calls["overlay_kwargs"] = kwargs
        return "/tmp/ui-%05d.png"

    monkeypatch.setattr(ui_360_renderer, "_generate_ui_overlay_sequence", _fake_generate_ui_overlay_sequence)
    accel = VideoAcceleration(name="cpu", decoder_args=(), encoder_args=("-c:v", "libx265", "-vtag", "hvc1"))
    monkeypatch.setattr(ui_360_renderer.video_renderer, "select_video_acceleration", lambda *_args: accel)
    def _fake_write_driver_watermark_frames(output_dir, text, *, frame_width, frame_height, frame_count, track):
        calls["watermark"] = (output_dir, text, frame_width, frame_height, frame_count, track)
        return "/tmp/watermark-%05d.png"

    monkeypatch.setattr(
        ui_360_renderer.video_renderer,
        "_write_driver_watermark_frames",
        _fake_write_driver_watermark_frames,
    )
    monkeypatch.setattr(ui_360_renderer.video_renderer, "_run_logged", lambda command: calls.setdefault("command", command))
    monkeypatch.setattr(
        ui_360_renderer.video_renderer,
        "_inject_360_metadata",
        lambda output: calls.setdefault("metadata_output", output),
    )
    monkeypatch.setattr(ui_360_renderer.video_renderer, "_probe_video_dimensions", lambda output: (2688, 760))

    result = ui_360_renderer.render_360_ui_clip(
        ui_360_renderer.video_renderer.VideoRenderOptions(
            render_type="360-ui",
            data_dir=str(data_dir),
            route_or_segment="dongle|2025-02-25--route",
            start_seconds=995,
            length_seconds=12,
            target_mb=200,
            file_format="hevc",
            acceleration="cpu",
            output_path=str(output_path),
            openpilot_dir=str(openpilot_dir),
            driver_input_path=str(driver_input),
            driver_watermark_text="DRIVER FACE SWAPPED",
            driver_watermark_track={"frames": []},
        )
    )

    overlay_kwargs = calls["overlay_kwargs"]
    assert overlay_kwargs["frame_width"] == 1344
    assert overlay_kwargs["frame_height"] == 760
    assert calls["watermark"][1:] == ("DRIVER FACE SWAPPED", 1344, 760, 240, {"frames": []})
    command = calls["command"]
    input_indices = [index for index, token in enumerate(command) if token == "-i"]
    assert command[input_indices[0] + 1] == str(driver_input.resolve())
    assert command[input_indices[-1] + 1].endswith("qcamera.ts")
    filter_complex = command[command.index("-filter_complex") + 1]
    assert filter_complex.index("[wide][ui]overlay") < filter_complex.index("[driver][wide_ui]hstack")
    assert filter_complex.index("[driver][wide_ui]hstack") < filter_complex.index("v360=dfisheye:equirect")
    assert "3:a:0?" not in command
    assert "4:a:0?" in command
    assert calls["metadata_output"] == output_path.resolve()
    assert result.output_path == output_path.resolve()
