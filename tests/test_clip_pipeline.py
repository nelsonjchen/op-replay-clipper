from __future__ import annotations

from unittest import mock

import pytest

import clip_pipeline
import ffmpeg_clip
import local_clip


def test_auto_file_format_prefers_hevc_for_360() -> None:
    assert clip_pipeline.normalize_output_format("360", "auto") == "hevc"
    assert clip_pipeline.normalize_output_format("forward", "auto") == "h264"


def test_cog_target_mb_keeps_margin() -> None:
    assert clip_pipeline.normalize_target_mb(9, "cog") == 8
    assert clip_pipeline.normalize_target_mb(1, "cog") == 1


def test_download_file_type_mapping() -> None:
    assert clip_pipeline.select_download_file_types("forward", qcam=False) == ("cameras",)
    assert clip_pipeline.select_download_file_types("ui", qcam=True) == ("qcameras", "logs")


def test_build_plan_parses_route_for_ui_requests() -> None:
    plan = clip_pipeline.build_clip_plan(
        clip_pipeline.ClipRequest(
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


@mock.patch("ffmpeg_clip.platform.system", return_value="Darwin")
def test_auto_acceleration_prefers_videotoolbox_on_macos(_: mock.Mock) -> None:
    accel = ffmpeg_clip.select_video_acceleration("auto", "h264")
    assert accel.name == "videotoolbox"


def test_demo_defaults_and_overrides_are_explicit() -> None:
    parser = local_clip.build_parser()
    default_demo_args = parser.parse_args(["forward", "--demo"])
    assert local_clip._resolve_route_and_timing(default_demo_args) == (local_clip.DEMO_ROUTE, 90, 15)

    overridden_demo_args = parser.parse_args(["forward", "--demo", "--start-seconds", "12", "--length-seconds", "3"])
    assert local_clip._resolve_route_and_timing(overridden_demo_args) == (local_clip.DEMO_ROUTE, 12, 3)


def test_skip_bootstrap_requires_existing_openpilot_checkout(tmp_path) -> None:
    parser = local_clip.build_parser()
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
        local_clip._prepare_openpilot_if_needed(args)


@mock.patch("local_clip.run_clip")
@mock.patch("local_clip.bootstrap_openpilot")
@mock.patch("local_clip.ensure_openpilot_checkout")
def test_ui_command_prepares_openpilot(ensure_checkout: mock.Mock, bootstrap: mock.Mock, run_clip: mock.Mock) -> None:
    run_clip.return_value = mock.Mock(output_path="shared/out.mp4", acceleration=None)
    exit_code = local_clip.main(["ui", "--demo"])
    assert exit_code == 0
    ensure_checkout.assert_called_once()
    bootstrap.assert_called_once()
    request = run_clip.call_args.args[0]
    assert request.render_type == "ui"


@mock.patch("local_clip.run_clip")
@mock.patch("local_clip.bootstrap_openpilot")
@mock.patch("local_clip.ensure_openpilot_checkout")
def test_non_ui_command_uses_requested_accel(ensure_checkout: mock.Mock, bootstrap: mock.Mock, run_clip: mock.Mock) -> None:
    run_clip.return_value = mock.Mock(output_path="shared/out.mp4", acceleration="videotoolbox")
    exit_code = local_clip.main(["forward", "--demo", "--accel", "videotoolbox"])
    assert exit_code == 0
    ensure_checkout.assert_not_called()
    bootstrap.assert_not_called()
    request = run_clip.call_args.args[0]
    assert request.local_acceleration == "videotoolbox"
