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
        return {}

    monkeypatch.setattr(
        "core.driver_face_benchmark_worker.render_rf_detr_redacted_clip",
        _fake_render_rf_detr_redacted_clip,
    )

    result_path, elapsed = driver_face_swap._run_hidden_passenger_redaction(
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
    assert captured["trim_startup_from_output"] is False
    assert captured["effect"] == "blur"
    assert captured["banner_text"] == "PASSENGER BLURRED"


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
