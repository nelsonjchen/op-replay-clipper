from __future__ import annotations

import numpy as np

from core import driver_face_pose_debug


def test_eye_angle_degrees_handles_horizontal_segment() -> None:
    points = np.array([[10.0, 10.0], [20.0, 10.0]], dtype=np.float32)

    angle = driver_face_pose_debug._eye_angle_degrees(points)

    assert angle == 0.0


def test_landmark_jump_averages_point_motion() -> None:
    previous = np.array([[0.0, 0.0], [10.0, 0.0]], dtype=np.float32)
    current = np.array([[3.0, 4.0], [10.0, 0.0]], dtype=np.float32)

    jump = driver_face_pose_debug._landmark_jump(previous, current)

    assert jump == 2.5


def test_delta_heatmap_reports_zero_for_first_frame() -> None:
    frame = np.zeros((4, 4, 3), dtype=np.uint8)

    heatmap, delta = driver_face_pose_debug._delta_heatmap(None, frame)

    assert heatmap.shape == frame.shape
    assert delta == 0.0


def test_draw_panel_title_preserves_frame_shape() -> None:
    frame = np.zeros((24, 32, 3), dtype=np.uint8)

    titled = driver_face_pose_debug._draw_panel_title(frame, "Panel", "Subtitle")

    assert titled.shape == frame.shape
