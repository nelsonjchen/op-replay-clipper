from __future__ import annotations

import numpy as np

from core import driver_face_bridge_debug


def test_project_points_to_full_frame_scales_from_crop_space() -> None:
    points = np.array([[0.0, 0.0], [50.0, 25.0], [100.0, 50.0]], dtype=np.float32)

    projected = driver_face_bridge_debug._project_points_to_full_frame(
        points,
        (100, 200, 400, 200),
        (100, 50),
    )

    assert projected is not None
    np.testing.assert_allclose(
        projected,
        np.array([[100.0, 200.0], [300.0, 300.0], [500.0, 400.0]], dtype=np.float32),
    )


def test_project_points_to_full_frame_returns_none_without_crop_rect() -> None:
    points = np.array([[5.0, 5.0]], dtype=np.float32)

    projected = driver_face_bridge_debug._project_points_to_full_frame(points, None, (100, 50))

    assert projected is None
