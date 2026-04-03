from __future__ import annotations

import subprocess

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
