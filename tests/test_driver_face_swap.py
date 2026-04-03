from __future__ import annotations

import subprocess
from pathlib import Path

from core import driver_face_swap


def test_driver_unchanged_passenger_pixelize_profile_maps_to_expected_seat_modes() -> None:
    driver_mode, passenger_mode = driver_face_swap._seat_modes_for_profile("driver_unchanged_passenger_pixelize")

    assert driver_mode == "none"
    assert passenger_mode == "pixelize"


def test_driver_unchanged_passenger_face_swap_profile_maps_to_expected_seat_modes() -> None:
    driver_mode, passenger_mode = driver_face_swap._seat_modes_for_profile("driver_unchanged_passenger_face_swap")

    assert driver_mode == "none"
    assert passenger_mode == "facefusion"


def test_driver_face_swap_passenger_pixelize_profile_maps_to_expected_seat_modes() -> None:
    driver_mode, passenger_mode = driver_face_swap._seat_modes_for_profile("driver_face_swap_passenger_pixelize")

    assert driver_mode == "facefusion"
    assert passenger_mode == "pixelize"


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

    site_packages = tmp_path / ".venv/lib/python3.12/site-packages/nvidia"
    cublas_lib = site_packages / "cublas/lib"
    cudnn_lib = site_packages / "cudnn/lib"
    cublas_lib.mkdir(parents=True)
    cudnn_lib.mkdir(parents=True)

    env = driver_face_swap.facefusion_runtime_env(tmp_path, base_env={"LD_LIBRARY_PATH": "/existing"})

    assert env["SYSTEM_VERSION_COMPAT"] == "0"
    assert env["LD_LIBRARY_PATH"] == f"{cublas_lib}:{cudnn_lib}:/existing"


def test_facefusion_runtime_env_leaves_ld_library_path_alone_without_cuda(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DRIVER_FACEFUSION_EXECUTION_PROVIDERS", raising=False)
    monkeypatch.setattr(driver_face_swap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(driver_face_swap, "_has_nvidia", lambda: False)

    env = driver_face_swap.facefusion_runtime_env(tmp_path, base_env={"LD_LIBRARY_PATH": "/existing"})

    assert env["SYSTEM_VERSION_COMPAT"] == "0"
    assert env["LD_LIBRARY_PATH"] == "/existing"
