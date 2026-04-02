from __future__ import annotations

from core import driver_face_swap


def test_driver_unchanged_passenger_pixelize_profile_maps_to_expected_seat_modes() -> None:
    driver_mode, passenger_mode = driver_face_swap._seat_modes_for_profile("driver_unchanged_passenger_pixelize")

    assert driver_mode == "none"
    assert passenger_mode == "pixelize"


def test_driver_face_swap_passenger_pixelize_profile_maps_to_expected_seat_modes() -> None:
    driver_mode, passenger_mode = driver_face_swap._seat_modes_for_profile("driver_face_swap_passenger_pixelize")

    assert driver_mode == "facefusion"
    assert passenger_mode == "pixelize"
