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

    assert plan.download_file_types == ("cameras", "logs")
    assert plan.decompress_logs is False


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
def test_non_ui_command_uses_requested_accel(ensure_checkout: mock.Mock, bootstrap: mock.Mock, run_clip: mock.Mock) -> None:
    run_clip.return_value = mock.Mock(output_path="shared/out.mp4", acceleration="videotoolbox")
    exit_code = clip.main(["forward", "--demo", "--accel", "videotoolbox"])
    assert exit_code == 0
    ensure_checkout.assert_not_called()
    bootstrap.assert_not_called()
    request = run_clip.call_args.args[0]
    assert request.local_acceleration == "videotoolbox"


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
    assert "crop=iw:760[driver]" in commands[0][filter_index]


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
    assert "crop=iw:1520[driver]" in commands[0][filter_index]
