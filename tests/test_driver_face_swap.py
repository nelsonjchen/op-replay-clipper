from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core import driver_face_swap


def test_driver_unchanged_passenger_hidden_profile_maps_to_expected_seat_modes() -> None:
    driver_mode, passenger_mode = driver_face_swap._seat_modes_for_profile("driver_unchanged_passenger_hidden")

    assert driver_mode == "none"
    assert passenger_mode == "hidden"


def test_driver_unchanged_passenger_pixelize_alias_maps_to_hidden_seat_mode() -> None:
    driver_mode, passenger_mode = driver_face_swap._seat_modes_for_profile("driver_unchanged_passenger_pixelize")

    assert driver_mode == "none"
    assert passenger_mode == "hidden"


def test_driver_unchanged_passenger_face_swap_profile_maps_to_expected_seat_modes() -> None:
    driver_mode, passenger_mode = driver_face_swap._seat_modes_for_profile("driver_unchanged_passenger_face_swap")

    assert driver_mode == "none"
    assert passenger_mode == "facefusion"


def test_driver_face_swap_passenger_hidden_profile_maps_to_expected_seat_modes() -> None:
    driver_mode, passenger_mode = driver_face_swap._seat_modes_for_profile("driver_face_swap_passenger_hidden")

    assert driver_mode == "facefusion"
    assert passenger_mode == "hidden"


def test_driver_face_swap_passenger_pixelize_alias_maps_to_hidden_seat_mode() -> None:
    driver_mode, passenger_mode = driver_face_swap._seat_modes_for_profile("driver_face_swap_passenger_pixelize")

    assert driver_mode == "facefusion"
    assert passenger_mode == "hidden"


def test_seat_mode_counts_reflect_mixed_profile(tmp_path: Path) -> None:
    active_seats = [
        driver_face_swap.PreparedSeatArtifacts(
            seat_side="left",
            seat_role="driver",
            crop_clip=tmp_path / "left.mp4",
            track_metadata=tmp_path / "left.json",
        ),
        driver_face_swap.PreparedSeatArtifacts(
            seat_side="right",
            seat_role="passenger",
            crop_clip=tmp_path / "right.mp4",
            track_metadata=tmp_path / "right.json",
        ),
    ]

    counts = driver_face_swap._seat_mode_counts(
        active_seats,
        driver_face_swap.DriverFaceSwapOptions(
            mode="facefusion",
            profile="driver_face_swap_passenger_hidden",
        ),
    )

    assert counts == {
        "none": 0,
        "facefusion": 1,
        "hidden": 1,
    }


def test_canonical_driver_face_profile_normalizes_pixelize_aliases() -> None:
    assert driver_face_swap.canonical_driver_face_profile("driver_unchanged_passenger_pixelize") == "driver_unchanged_passenger_hidden"
    assert driver_face_swap.canonical_driver_face_profile("driver_face_swap_passenger_pixelize") == "driver_face_swap_passenger_hidden"


def test_hidden_passenger_redaction_preserves_startup_frames_for_backing_video(monkeypatch, tmp_path: Path) -> None:
    track_path = tmp_path / "passenger-face-track.json"
    track_path.write_text(json.dumps({"frames": []}))
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source")
    output_path = tmp_path / "output.mp4"
    captured: dict[str, object] = {}

    def _fake_render_rf_detr_redacted_clip(**kwargs):
        captured.update(kwargs)
        return {"rf_detr_device": "cuda", "rf_detr_model_id": "rfdetr-seg-preview"}

    monkeypatch.setattr(
        "core.driver_face_benchmark_worker.render_rf_detr_redacted_clip",
        _fake_render_rf_detr_redacted_clip,
    )

    result_path, elapsed, report = driver_face_swap._run_hidden_passenger_redaction(
        sample_dir=tmp_path,
        source_path=source_path,
        output_path=output_path,
        track_metadata=track_path,
        options=driver_face_swap.DriverFaceSwapOptions(
            mode="facefusion",
            profile="driver_unchanged_passenger_hidden",
            passenger_redaction_style="blur",
        ),
        banner_text="PASSENGER BLURRED",
    )

    assert result_path == output_path
    assert elapsed >= 0
    assert report["rf_detr_device"] == "cuda"
    assert captured["trim_startup_from_output"] is False
    assert captured["effect"] == "blur"
    assert captured["banner_text"] == "PASSENGER BLURRED"


def test_hidden_passenger_redaction_report_keeps_output_encoder(monkeypatch, tmp_path: Path) -> None:
    track_path = tmp_path / "passenger-face-track.json"
    track_path.write_text(json.dumps({"frames": []}))
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source")
    output_path = tmp_path / "output.mp4"

    monkeypatch.setattr(
        "core.driver_face_benchmark_worker.render_rf_detr_redacted_clip",
        lambda **kwargs: {
            "rf_detr_device": "cuda",
            "rf_detr_model_id": "rfdetr-seg-preview",
            "output_video_encoder": "h264_nvenc",
        },
    )

    _, _, report = driver_face_swap._run_hidden_passenger_redaction(
        sample_dir=tmp_path,
        source_path=source_path,
        output_path=output_path,
        track_metadata=track_path,
        options=driver_face_swap.DriverFaceSwapOptions(
            mode="facefusion",
            profile="driver_unchanged_passenger_hidden",
            passenger_redaction_style="blur",
        ),
        banner_text="PASSENGER BLURRED",
    )

    assert report["output_video_encoder"] == "h264_nvenc"


def test_facefusion_command_swaps_all_faces_in_crop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(driver_face_swap, "default_facefusion_output_video_encoder", lambda: "libx264")
    monkeypatch.setattr(driver_face_swap, "default_facefusion_execution_providers", lambda: ["cpu"])

    command = driver_face_swap._facefusion_swap_command(
        facefusion_root=tmp_path / "facefusion",
        source_image=tmp_path / "source.jpg",
        target_video=tmp_path / "target.mp4",
        output_video=tmp_path / "output.mp4",
        model_name="hyperswap_1b_256",
        preset="fast",
    )

    selector_index = command.index("--face-selector-mode")
    assert command[selector_index + 1] == "many"
    assert command[1].endswith("driver_facefusion_headless.py")
    root_index = command.index("--facefusion-root")
    assert command[root_index + 1] == str(tmp_path / "facefusion")


def test_intermediate_encoder_falls_back_to_libx264(monkeypatch) -> None:
    driver_face_swap._ffmpeg_encoder_names.cache_clear()
    monkeypatch.delenv("DRIVER_FACEFUSION_OUTPUT_VIDEO_ENCODER", raising=False)
    monkeypatch.setattr(driver_face_swap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(driver_face_swap, "_has_nvidia", lambda: False)
    monkeypatch.setattr(
        driver_face_swap.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="Encoders:\n"),
    )

    assert driver_face_swap.default_facefusion_output_video_encoder() == "libx264"
    assert driver_face_swap.intermediate_video_encoder_args() == ["-c:v", "libx264"]


def test_intermediate_encoder_prefers_hevc_videotoolbox(monkeypatch) -> None:
    driver_face_swap._ffmpeg_encoder_names.cache_clear()
    monkeypatch.delenv("DRIVER_FACEFUSION_OUTPUT_VIDEO_ENCODER", raising=False)
    monkeypatch.setattr(driver_face_swap.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        driver_face_swap.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=" V..... hevc_videotoolbox\n"),
    )

    assert driver_face_swap.default_facefusion_output_video_encoder() == "hevc_videotoolbox"
    assert driver_face_swap.intermediate_video_encoder_args() == ["-c:v", "hevc_videotoolbox", "-vtag", "hvc1"]


def test_facefusion_execution_providers_prefer_cuda_on_nvidia_linux(monkeypatch) -> None:
    monkeypatch.delenv("DRIVER_FACEFUSION_EXECUTION_PROVIDERS", raising=False)
    monkeypatch.setattr(driver_face_swap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(driver_face_swap, "_has_nvidia", lambda: True)

    assert driver_face_swap.default_facefusion_execution_providers() == ["cuda", "cpu"]


def test_facefusion_execution_providers_prefer_coreml_on_macos(monkeypatch) -> None:
    monkeypatch.delenv("DRIVER_FACEFUSION_EXECUTION_PROVIDERS", raising=False)
    monkeypatch.setattr(driver_face_swap.platform, "system", lambda: "Darwin")

    assert driver_face_swap.default_facefusion_execution_providers() == ["coreml", "cpu"]


def test_facefusion_runtime_env_adds_cuda_library_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DRIVER_FACEFUSION_EXECUTION_PROVIDERS", raising=False)
    monkeypatch.setattr(driver_face_swap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(driver_face_swap, "_has_nvidia", lambda: True)

    system_cuda_lib = tmp_path / "system-cuda-lib"
    system_cuda_lib.mkdir()
    monkeypatch.setattr(driver_face_swap, "_SYSTEM_CUDA_LIBRARY_DIRS", (str(system_cuda_lib),))

    site_packages = tmp_path / ".venv/lib/python3.12/site-packages/nvidia"
    cublas_lib = site_packages / "cublas/lib"
    cudnn_lib = site_packages / "cudnn/lib"
    cublas_lib.mkdir(parents=True)
    cudnn_lib.mkdir(parents=True)

    env = driver_face_swap.facefusion_runtime_env(tmp_path, base_env={"LD_LIBRARY_PATH": "/existing"})

    assert env["SYSTEM_VERSION_COMPAT"] == "0"
    assert env["LD_LIBRARY_PATH"] == f"{system_cuda_lib}:{cublas_lib}:{cudnn_lib}:/existing"


def test_facefusion_runtime_env_leaves_ld_library_path_alone_without_cuda(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DRIVER_FACEFUSION_EXECUTION_PROVIDERS", raising=False)
    monkeypatch.setattr(driver_face_swap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(driver_face_swap, "_has_nvidia", lambda: False)

    env = driver_face_swap.facefusion_runtime_env(tmp_path, base_env={"LD_LIBRARY_PATH": "/existing"})

    assert env["SYSTEM_VERSION_COMPAT"] == "0"
    assert env["LD_LIBRARY_PATH"] == "/existing"


def test_prepare_face_crop_artifacts_only_runs_full_worker_for_active_facefusion_seats(monkeypatch, tmp_path: Path) -> None:
    sample_dir = tmp_path / "sample"
    sample_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    openpilot_dir = tmp_path / "openpilot"
    worker_python = openpilot_dir / ".venv/bin/python"
    worker_python.parent.mkdir(parents=True)
    worker_python.write_text("")

    source_clip = sample_dir / "driver-source.mp4"

    monkeypatch.setattr("core.route_downloader.downloadSegments", lambda **_kwargs: None)
    monkeypatch.setattr(
        driver_face_swap.video_renderer,
        "render_video_clip",
        lambda _opts: source_clip.write_bytes(b"source"),
    )

    calls: list[tuple[str, bool]] = []

    def _fake_run_face_eval_worker(worker_cmd: list[str], *, acceleration: str) -> dict[str, object]:
        del acceleration
        seat_side = worker_cmd[worker_cmd.index("--seat-side") + 1]
        manifest_only = "--manifest-only" in worker_cmd
        calls.append((seat_side, manifest_only))
        track_metadata = Path(worker_cmd[worker_cmd.index("--track-metadata") + 1])
        crop_clip = Path(worker_cmd[worker_cmd.index("--crop-clip") + 1])
        selected_side = "left"
        seat_role = "driver" if seat_side == selected_side else "passenger"
        has_active_crop = seat_role == "driver"
        track_metadata.write_text(
            json.dumps(
                {
                    "frames": [
                        {
                            "frame_index": 0,
                            "selected_side": selected_side,
                            "crop_rect": {"x": 0, "y": 0, "width": 10, "height": 10} if has_active_crop else None,
                        }
                    ]
                }
            )
        )
        if not manifest_only and has_active_crop:
            crop_clip.write_bytes(b"crop")
        return {"has_active_crop": has_active_crop, "crop_clip_written": bool(has_active_crop and not manifest_only)}

    monkeypatch.setattr(driver_face_swap, "_run_face_eval_worker", _fake_run_face_eval_worker)

    source_path, seat_artifacts = driver_face_swap._prepare_face_crop_artifacts(
        sample_dir=sample_dir,
        route="dongle|route",
        route_or_url="https://connect.comma.ai/dongle/route/0/1",
        start_seconds=0,
        length_seconds=1,
        data_dir=data_dir,
        openpilot_dir=openpilot_dir,
        acceleration="cpu",
        backing_target_mb=12,
        options=driver_face_swap.DriverFaceSwapOptions(
            mode="facefusion",
            profile="driver_face_swap_passenger_hidden",
        ),
        jwt_token=None,
    )

    assert source_path == source_clip
    assert [(artifact.seat_side, artifact.seat_role) for artifact in seat_artifacts] == [
        ("left", "driver"),
        ("right", "passenger"),
    ]
    assert calls == [
        ("left", True),
        ("left", False),
        ("right", True),
    ]
    assert (sample_dir / "left-face-crop.mp4").exists() is True
    assert (sample_dir / "right-face-crop.mp4").exists() is False
