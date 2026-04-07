from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

import clip
from core import clip_orchestrator
from renderers import video_renderer


def test_auto_file_format_prefers_hevc_for_360() -> None:
    assert clip_orchestrator.normalize_output_format("360", "auto") == "hevc"
    assert clip_orchestrator.normalize_output_format("forward", "auto") == "h264"


def test_cog_target_mb_keeps_margin() -> None:
    assert clip_orchestrator.normalize_target_mb(9, "cog") == 8
    assert clip_orchestrator.normalize_target_mb(1, "cog") == 1


def test_download_file_type_mapping() -> None:
    assert clip_orchestrator.select_download_file_types("forward", qcam=False) == ("cameras",)
    assert clip_orchestrator.select_download_file_types("ui", qcam=True) == ("qcameras", "logs")
    assert clip_orchestrator.select_download_file_types("ui-alt", qcam=True) == ("qcameras", "logs")
    assert clip_orchestrator.select_download_file_types("driver-debug", qcam=False) == ("dcameras", "logs")
    assert clip_orchestrator.select_download_file_types("driver", qcam=False, driver_face_anonymization="facefusion") == (
        "dcameras",
        "logs",
    )
    assert clip_orchestrator.select_download_file_types("360", qcam=False, driver_face_anonymization="facefusion") == (
        "ecameras",
        "dcameras",
        "logs",
    )
    assert clip_orchestrator.select_download_file_types(
        "360_forward_upon_wide",
        qcam=False,
        forward_upon_wide_h="auto",
        driver_face_anonymization="facefusion",
    ) == ("ecameras", "dcameras", "cameras", "qlogs", "logs")
    assert clip_orchestrator.select_download_file_types("ui", qcam=False) == ("cameras", "ecameras", "logs")
    assert clip_orchestrator.select_download_file_types("ui-alt", qcam=False) == ("cameras", "ecameras", "logs")


def test_build_plan_parses_route_for_ui_requests() -> None:
    plan = clip_orchestrator.build_clip_plan(
        clip_orchestrator.ClipRequest(
            render_type="ui",
            route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
            start_seconds=90,
            length_seconds=5,
            target_mb=9,
            execution_context="cog",
        )
    )
    assert plan.route == "a2a0ccea32023010|2023-07-27--13-01-19"
    assert plan.target_mb == 8


def test_build_plan_treats_ui_alt_as_ui_render() -> None:
    plan = clip_orchestrator.build_clip_plan(
        clip_orchestrator.ClipRequest(
            render_type="ui-alt",
            route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
            start_seconds=90,
            length_seconds=5,
            target_mb=9,
            execution_context="local",
        )
    )

    assert plan.download_file_types == ("cameras", "ecameras", "logs")
    assert plan.decompress_logs is False


def test_build_plan_treats_driver_debug_as_openpilot_render() -> None:
    plan = clip_orchestrator.build_clip_plan(
        clip_orchestrator.ClipRequest(
            render_type="driver-debug",
            route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
            start_seconds=90,
            length_seconds=5,
            target_mb=9,
            execution_context="local",
        )
    )

    assert plan.download_file_types == ("dcameras", "logs")
    assert plan.decompress_logs is False


def test_build_plan_rejects_driver_face_anonymization_for_non_driver_renders() -> None:
    with pytest.raises(ValueError, match="only supported"):
        clip_orchestrator.build_clip_plan(
            clip_orchestrator.ClipRequest(
                render_type="forward",
                route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
                start_seconds=90,
                length_seconds=5,
                target_mb=9,
                driver_face_anonymization="facefusion",
            )
        )


@pytest.mark.parametrize("render_type", ["360", "360_forward_upon_wide"])
def test_build_plan_accepts_driver_face_anonymization_for_360_renders(render_type: str) -> None:
    plan = clip_orchestrator.build_clip_plan(
        clip_orchestrator.ClipRequest(
            render_type=render_type,  # type: ignore[arg-type]
            route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
            start_seconds=90,
            length_seconds=5,
            target_mb=9,
            driver_face_anonymization="facefusion",
        )
    )

    assert plan.render_type == render_type
    assert plan.driver_face_swap.mode == "facefusion"
    assert "logs" in plan.download_file_types


@mock.patch("renderers.video_renderer.platform.system", return_value="Darwin")
def test_auto_acceleration_prefers_videotoolbox_on_macos(_: mock.Mock) -> None:
    accel = video_renderer.select_video_acceleration("auto", "h264")
    assert accel.name == "videotoolbox"


def test_demo_defaults_and_overrides_are_explicit() -> None:
    parser = clip.build_parser()
    default_demo_args = parser.parse_args(["forward", "--demo"])
    assert clip._resolve_route_and_timing(default_demo_args) == (clip.DEMO_ROUTE, 90, 15)

    overridden_demo_args = parser.parse_args(["forward", "--demo", "--start-seconds", "12", "--length-seconds", "3"])
    assert clip._resolve_route_and_timing(overridden_demo_args) == (clip.DEMO_ROUTE, 12, 3)


def test_skip_bootstrap_requires_existing_openpilot_checkout(tmp_path) -> None:
    parser = clip.build_parser()
    missing_checkout = tmp_path / "missing-openpilot"
    args = parser.parse_args(
        [
            "ui",
            "--demo",
            "--openpilot-dir",
            str(missing_checkout),
            "--skip-openpilot-update",
            "--skip-openpilot-bootstrap",
        ]
    )
    with pytest.raises(SystemExit, match="Openpilot checkout not found"):
        clip._prepare_openpilot_if_needed(args)


@mock.patch("clip.run_clip")
@mock.patch("clip.bootstrap_openpilot")
@mock.patch("clip.ensure_openpilot_checkout")
def test_ui_command_prepares_openpilot(ensure_checkout: mock.Mock, bootstrap: mock.Mock, run_clip: mock.Mock) -> None:
    run_clip.return_value = mock.Mock(output_path="shared/out.mp4", acceleration=None)
    exit_code = clip.main(["ui", "--demo"])
    assert exit_code == 0
    ensure_checkout.assert_called_once()
    bootstrap.assert_called_once()
    request = run_clip.call_args.args[0]
    assert request.render_type == "ui"


@mock.patch("clip.run_clip")
@mock.patch("clip.bootstrap_openpilot")
@mock.patch("clip.ensure_openpilot_checkout")
def test_ui_alt_command_prepares_openpilot(ensure_checkout: mock.Mock, bootstrap: mock.Mock, run_clip: mock.Mock) -> None:
    run_clip.return_value = mock.Mock(output_path="shared/out.mp4", acceleration=None)
    exit_code = clip.main(["ui-alt", "--demo"])
    assert exit_code == 0
    ensure_checkout.assert_called_once()
    bootstrap.assert_called_once()
    request = run_clip.call_args.args[0]
    assert request.render_type == "ui-alt"


@mock.patch("clip.run_clip")
@mock.patch("clip.bootstrap_openpilot")
@mock.patch("clip.ensure_openpilot_checkout")
def test_driver_debug_command_prepares_openpilot(ensure_checkout: mock.Mock, bootstrap: mock.Mock, run_clip: mock.Mock) -> None:
    run_clip.return_value = mock.Mock(output_path="shared/out.mp4", acceleration=None)
    exit_code = clip.main(["driver-debug", "--demo"])
    assert exit_code == 0
    ensure_checkout.assert_called_once()
    bootstrap.assert_called_once()
    request = run_clip.call_args.args[0]
    assert request.render_type == "driver-debug"


@mock.patch("clip.run_clip")
@mock.patch("clip.bootstrap_openpilot")
@mock.patch("clip.ensure_openpilot_checkout")
def test_non_ui_command_uses_requested_accel(ensure_checkout: mock.Mock, bootstrap: mock.Mock, run_clip: mock.Mock) -> None:
    run_clip.return_value = mock.Mock(output_path="shared/out.mp4", acceleration="videotoolbox")
    exit_code = clip.main(["forward", "--demo", "--accel", "videotoolbox"])
    assert exit_code == 0
    ensure_checkout.assert_not_called()
    bootstrap.assert_not_called()
    request = run_clip.call_args.args[0]
    assert request.local_acceleration == "videotoolbox"


@mock.patch("clip.run_clip")
@mock.patch("clip.bootstrap_openpilot")
@mock.patch("clip.ensure_openpilot_checkout")
def test_driver_face_anonymization_flags_flow_into_clip_request(
    ensure_checkout: mock.Mock,
    bootstrap: mock.Mock,
    run_clip: mock.Mock,
) -> None:
    run_clip.return_value = mock.Mock(output_path="shared/out.mp4", acceleration=None)
    exit_code = clip.main(
        [
            "driver",
            "--demo",
            "--driver-face-anonymization",
            "facefusion",
            "--driver-face-profile",
            "driver_face_swap_passenger_hidden",
            "--passenger-redaction-style",
            "silhouette",
            "--driver-face-source-image",
            "/tmp/donor.png",
            "--driver-face-selection",
            "auto_best_match",
            "--driver-face-donor-bank-dir",
            "/tmp/donor-bank",
            "--driver-face-preset",
            "quality",
            "--facefusion-root",
            "/tmp/facefusion",
            "--facefusion-model",
            "hyperswap_1b_256",
        ]
    )
    assert exit_code == 0
    ensure_checkout.assert_called_once()
    bootstrap.assert_called_once()
    request = run_clip.call_args.args[0]
    assert request.render_type == "driver"
    assert request.driver_face_anonymization == "facefusion"
    assert request.driver_face_profile == "driver_face_swap_passenger_hidden"
    assert request.passenger_redaction_style == "silhouette"
    assert request.driver_face_source_image == "/tmp/donor.png"
    assert request.driver_face_selection == "auto_best_match"
    assert request.driver_face_donor_bank_dir == "/tmp/donor-bank"
    assert request.driver_face_preset == "quality"
    assert request.facefusion_root == "/tmp/facefusion"
    assert request.facefusion_model == "hyperswap_1b_256"


@mock.patch("clip.run_clip")
@mock.patch("clip.bootstrap_openpilot")
@mock.patch("clip.ensure_openpilot_checkout")
def test_360_anonymization_prepares_openpilot(ensure_checkout: mock.Mock, bootstrap: mock.Mock, run_clip: mock.Mock) -> None:
    run_clip.return_value = mock.Mock(output_path="shared/out.mp4", acceleration=None)
    exit_code = clip.main(["360", "--demo", "--driver-face-anonymization", "facefusion"])
    assert exit_code == 0
    ensure_checkout.assert_called_once()
    bootstrap.assert_called_once()
    request = run_clip.call_args.args[0]
    assert request.render_type == "360"
    assert request.driver_face_anonymization == "facefusion"


def test_build_plan_preserves_driver_face_profile() -> None:
    plan = clip_orchestrator.build_clip_plan(
        clip_orchestrator.ClipRequest(
            render_type="driver",
            route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
            start_seconds=90,
            length_seconds=5,
            target_mb=9,
            driver_face_anonymization="facefusion",
            driver_face_profile="driver_face_swap_passenger_hidden",
            passenger_redaction_style="silhouette",
        )
    )

    assert plan.driver_face_swap.mode == "facefusion"
    assert plan.driver_face_swap.profile == "driver_face_swap_passenger_hidden"
    assert plan.driver_face_swap.passenger_redaction_style == "silhouette"


def test_build_plan_preserves_driver_unchanged_passenger_pixelize_profile() -> None:
    plan = clip_orchestrator.build_clip_plan(
        clip_orchestrator.ClipRequest(
            render_type="driver",
            route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
            start_seconds=90,
            length_seconds=5,
            target_mb=9,
            driver_face_anonymization="facefusion",
            driver_face_profile="driver_unchanged_passenger_pixelize",
        )
    )

    assert plan.driver_face_swap.mode == "facefusion"
    assert plan.driver_face_swap.profile == "driver_unchanged_passenger_hidden"


def test_build_plan_preserves_driver_unchanged_passenger_face_swap_profile() -> None:
    plan = clip_orchestrator.build_clip_plan(
        clip_orchestrator.ClipRequest(
            render_type="driver",
            route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
            start_seconds=90,
            length_seconds=5,
            target_mb=9,
            driver_face_anonymization="facefusion",
            driver_face_profile="driver_unchanged_passenger_face_swap",
        )
    )

    assert plan.driver_face_swap.mode == "facefusion"
    assert plan.driver_face_swap.profile == "driver_unchanged_passenger_face_swap"


def test_run_clip_uses_anonymized_backing_pipeline_for_driver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plan = clip_orchestrator.build_clip_plan(
        clip_orchestrator.ClipRequest(
            render_type="driver",
            route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
            start_seconds=90,
            length_seconds=5,
            target_mb=9,
            output_path=str(tmp_path / "out.mp4"),
            explicit_data_dir=str(tmp_path / "data"),
            driver_face_anonymization="facefusion",
            driver_face_source_image="/tmp/donor.png",
            facefusion_root="/tmp/facefusion",
            facefusion_model="hyperswap_1b_256",
        )
    )

    monkeypatch.setattr(clip_orchestrator, "build_clip_plan", lambda request: plan)
    monkeypatch.setattr(clip_orchestrator.route_downloader, "downloadSegments", lambda **kwargs: None)
    called: dict[str, object] = {}

    def _fake_render(**kwargs):
        called.update(kwargs)
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake")
        return output

    monkeypatch.setattr(clip_orchestrator, "render_anonymized_driver_backing_video", _fake_render)

    result = clip_orchestrator.run_clip(
        clip_orchestrator.ClipRequest(
            render_type="driver",
            route_or_url="ignored",
            start_seconds=0,
            length_seconds=1,
            target_mb=1,
        )
    )

    assert result.output_path == (tmp_path / "out.mp4").resolve()
    assert called["route"] == plan.route
    assert called["start_seconds"] == 90
    assert called["length_seconds"] == 5
    assert called["options"].mode == "facefusion"


@pytest.mark.parametrize("render_type", ["360", "360_forward_upon_wide"])
def test_run_clip_uses_anonymized_backing_pipeline_for_360(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, render_type: str
) -> None:
    plan = clip_orchestrator.build_clip_plan(
        clip_orchestrator.ClipRequest(
            render_type=render_type,  # type: ignore[arg-type]
            route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
            start_seconds=90,
            length_seconds=5,
            target_mb=9,
            output_path=str(tmp_path / f"{render_type}.mp4"),
            explicit_data_dir=str(tmp_path / "data"),
            driver_face_anonymization="facefusion",
            driver_face_source_image="/tmp/donor.png",
            facefusion_root="/tmp/facefusion",
            facefusion_model="hyperswap_1b_256",
        )
    )

    monkeypatch.setattr(clip_orchestrator, "build_clip_plan", lambda request: plan)
    monkeypatch.setattr(clip_orchestrator.route_downloader, "downloadSegments", lambda **kwargs: None)
    backing_call: dict[str, object] = {}
    video_call: dict[str, object] = {}

    def _fake_render_backing(**kwargs):
        backing_call.update(kwargs)
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake backing")
        output.with_name(f"{output.stem}.driver-face-selection.json").write_text(
            '{"selected":"donor","banner_text":"DRIVER FACE SWAPPED","seats":{"left":{"seat_role":"driver","overlay_track":{"frames":[{"crop_rect":{"x":10,"y":20,"width":30,"height":40}}]}}}}\n'
        )
        return output

    def _fake_render_video(opts: video_renderer.VideoRenderOptions):
        video_call["opts"] = opts
        output = Path(opts.output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake video")
        return video_renderer.VideoRenderResult(output_path=output, acceleration="cpu")

    monkeypatch.setattr(clip_orchestrator, "render_anonymized_driver_backing_video", _fake_render_backing)
    monkeypatch.setattr(clip_orchestrator.video_renderer, "render_video_clip", _fake_render_video)

    result = clip_orchestrator.run_clip(
        clip_orchestrator.ClipRequest(
            render_type="driver",
            route_or_url="ignored",
            start_seconds=0,
            length_seconds=1,
            target_mb=1,
        )
    )

    assert result.output_path == Path(plan.output_path).resolve()
    assert backing_call["route"] == plan.route
    assert backing_call["options"].mode == "facefusion"
    assert backing_call["render_banner"] is False
    opts = video_call["opts"]
    assert opts.render_type == render_type
    assert opts.driver_input_path is not None
    assert opts.driver_watermark_text == "DRIVER FACE SWAPPED"
    assert opts.driver_watermark_track == {"frames": [{"crop_rect": {"x": 10, "y": 20, "width": 30, "height": 40}}]}
    selection_report_path = result.output_path.with_name(f"{result.output_path.stem}.driver-face-selection.json")
    assert (
        selection_report_path.read_text()
        == '{"selected":"donor","banner_text":"DRIVER FACE SWAPPED","seats":{"left":{"seat_role":"driver","overlay_track":{"frames":[{"crop_rect":{"x":10,"y":20,"width":30,"height":40}}]}}}}\n'
    )


def test_probe_video_dimensions_reads_ffprobe_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    video_path = tmp_path / "ecamera.hevc"
    video_path.write_bytes(b"")

    monkeypatch.setattr(
        video_renderer.subprocess,
        "run",
        lambda *args, **kwargs: mock.Mock(returncode=0, stdout='{"streams":[{"width":1344,"height":760}]}'),
    )

    assert video_renderer._probe_video_dimensions(video_path) == (1344, 760)


def test_360_render_uses_probed_wide_height(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "2025-02-25--route--1").mkdir(parents=True)
    output_path = tmp_path / "out.mp4"

    commands: list[list[str]] = []
    monkeypatch.setattr(video_renderer, "_probe_video_dimensions", lambda path: (1344, 760))
    monkeypatch.setattr(video_renderer, "_run_logged", lambda command: commands.append(command))
    monkeypatch.setattr(video_renderer, "_inject_360_metadata", lambda path: None)

    video_renderer.render_video_clip(
        video_renderer.VideoRenderOptions(
            render_type="360",
            data_dir=str(data_dir),
            route_or_segment="dongle|2025-02-25--route",
            start_seconds=90,
            length_seconds=15,
            target_mb=9,
            file_format="hevc",
            acceleration="cpu",
            output_path=str(output_path),
        )
    )

    filter_index = commands[0].index("-filter_complex") + 1
    assert "crop=iw:760[driver_raw]" in commands[0][filter_index]


def test_360_render_uses_driver_input_override_when_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "2025-02-25--route--1").mkdir(parents=True)
    driver_override = tmp_path / "driver-backing.mp4"
    driver_override.write_bytes(b"fake")
    output_path = tmp_path / "out.mp4"

    commands: list[list[str]] = []
    monkeypatch.setattr(video_renderer, "_probe_video_dimensions", lambda path: (1344, 760))
    monkeypatch.setattr(video_renderer, "_run_logged", lambda command: commands.append(command))
    watermark_calls: list[tuple[Path, str, int, int, int, dict[str, object]]] = []
    monkeypatch.setattr(
        video_renderer,
        "_write_driver_watermark_frames",
        lambda output_dir, text, *, frame_width, frame_height, frame_count, track: (
            watermark_calls.append((output_dir, text, frame_width, frame_height, frame_count, track)),
            str((output_dir / "watermark-%05d.png").resolve()),
        )[1],
    )
    monkeypatch.setattr(video_renderer, "_inject_360_metadata", lambda path: None)

    video_renderer.render_video_clip(
        video_renderer.VideoRenderOptions(
            render_type="360",
            data_dir=str(data_dir),
            route_or_segment="dongle|2025-02-25--route",
            start_seconds=90,
            length_seconds=15,
            target_mb=9,
            file_format="hevc",
            acceleration="cpu",
            output_path=str(output_path),
            driver_input_path=str(driver_override),
            driver_watermark_text="DRIVER FACE SWAPPED",
            driver_watermark_track={"frames": []},
        )
    )

    input_indices = [i for i, token in enumerate(commands[0]) if token == "-i"]
    seek_indices = [i for i, token in enumerate(commands[0]) if token == "-ss"]
    filter_index = commands[0].index("-filter_complex") + 1
    assert commands[0][input_indices[0] + 1] == str(driver_override.resolve())
    assert commands[0][input_indices[1] + 1].startswith("concat:")
    assert not seek_indices
    assert "trim=start=0:duration=15" in commands[0][filter_index]
    assert "trim=start=30:duration=15" in commands[0][filter_index]
    assert "[driver_raw][2:v]overlay=0:0[driver]" in commands[0][filter_index]
    assert commands[0][commands[0].index("-framerate") + 1] == "20"
    assert len(watermark_calls) == 1
    assert watermark_calls[0][1:] == ("DRIVER FACE SWAPPED", 1344, 760, 300, {"frames": []})


def test_360_forward_upon_wide_uses_scaled_wide_height(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "2025-02-25--route--1").mkdir(parents=True)
    output_path = tmp_path / "out.mp4"

    commands: list[list[str]] = []
    monkeypatch.setattr(video_renderer, "_probe_video_dimensions", lambda path: (1344, 760))
    monkeypatch.setattr(video_renderer, "_run_logged", lambda command: commands.append(command))
    monkeypatch.setattr(video_renderer, "_inject_360_metadata", lambda path: None)

    video_renderer.render_video_clip(
        video_renderer.VideoRenderOptions(
            render_type="360_forward_upon_wide",
            data_dir=str(data_dir),
            route_or_segment="dongle|2025-02-25--route",
            start_seconds=90,
            length_seconds=15,
            target_mb=9,
            file_format="hevc",
            acceleration="cpu",
            output_path=str(output_path),
        )
    )

    filter_index = commands[0].index("-filter_complex") + 1
    assert "crop=iw:1520[driver_raw]" in commands[0][filter_index]


def test_360_forward_upon_wide_uses_driver_input_override_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "2025-02-25--route--1").mkdir(parents=True)
    driver_override = tmp_path / "driver-backing.mp4"
    driver_override.write_bytes(b"fake")
    output_path = tmp_path / "out.mp4"

    commands: list[list[str]] = []
    monkeypatch.setattr(video_renderer, "_probe_video_dimensions", lambda path: (1344, 760))
    monkeypatch.setattr(video_renderer, "_run_logged", lambda command: commands.append(command))
    watermark_calls: list[tuple[Path, str, int, int, int, dict[str, object]]] = []
    monkeypatch.setattr(
        video_renderer,
        "_write_driver_watermark_frames",
        lambda output_dir, text, *, frame_width, frame_height, frame_count, track: (
            watermark_calls.append((output_dir, text, frame_width, frame_height, frame_count, track)),
            str((output_dir / "watermark-%05d.png").resolve()),
        )[1],
    )
    monkeypatch.setattr(video_renderer, "_inject_360_metadata", lambda path: None)

    video_renderer.render_video_clip(
        video_renderer.VideoRenderOptions(
            render_type="360_forward_upon_wide",
            data_dir=str(data_dir),
            route_or_segment="dongle|2025-02-25--route",
            start_seconds=90,
            length_seconds=15,
            target_mb=9,
            file_format="hevc",
            acceleration="cpu",
            output_path=str(output_path),
            driver_input_path=str(driver_override),
            driver_watermark_text="DRIVER SWAPPED, PASSENGER BLURRED",
            driver_watermark_track={"frames": []},
        )
    )

    input_indices = [i for i, token in enumerate(commands[0]) if token == "-i"]
    seek_indices = [i for i, token in enumerate(commands[0]) if token == "-ss"]
    filter_index = commands[0].index("-filter_complex") + 1
    assert commands[0][input_indices[0] + 1] == str(driver_override.resolve())
    assert commands[0][input_indices[1] + 1].startswith("concat:")
    assert commands[0][input_indices[2] + 1].startswith("concat:")
    assert not seek_indices
    assert commands[0][filter_index].count("trim=start=30:duration=15") == 2
    assert "trim=start=0:duration=15" in commands[0][filter_index]
    assert "[driver_raw][3:v]overlay=0:0[driver]" in commands[0][filter_index]
    assert commands[0][commands[0].index("-framerate") + 1] == "20"
    assert len(watermark_calls) == 1
    assert watermark_calls[0][1:] == (
        "DRIVER SWAPPED, PASSENGER BLURRED",
        2688,
        1520,
        300,
        {"frames": []},
    )


def test_360_render_without_driver_override_keeps_output_seek(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "2025-02-25--route--1").mkdir(parents=True)
    output_path = tmp_path / "out.mp4"

    commands: list[list[str]] = []
    monkeypatch.setattr(video_renderer, "_probe_video_dimensions", lambda path: (1344, 760))
    monkeypatch.setattr(video_renderer, "_run_logged", lambda command: commands.append(command))
    monkeypatch.setattr(video_renderer, "_inject_360_metadata", lambda path: None)

    video_renderer.render_video_clip(
        video_renderer.VideoRenderOptions(
            render_type="360",
            data_dir=str(data_dir),
            route_or_segment="dongle|2025-02-25--route",
            start_seconds=90,
            length_seconds=15,
            target_mb=9,
            file_format="hevc",
            acceleration="cpu",
            output_path=str(output_path),
        )
    )

    seek_indices = [i for i, token in enumerate(commands[0]) if token == "-ss"]
    assert len(seek_indices) == 1
    assert commands[0][seek_indices[0] + 1] == "30"
    assert seek_indices[0] > commands[0].index("-t")
