from __future__ import annotations

import numpy as np

from core import driver_face_reintegrate


def test_bridge_spans_only_include_short_interior_runs() -> None:
    spans = driver_face_reintegrate._bridge_spans(
        [False, True, False, False, True, True, False, False],
        max_gap=2,
    )

    assert spans == [
        {"start": 1, "end": 1, "previous_good": 0, "next_good": 2},
        {"start": 4, "end": 5, "previous_good": 3, "next_good": 6},
    ]


def test_bridge_spans_respect_gap_limit() -> None:
    spans = driver_face_reintegrate._bridge_spans(
        [False, True, True, False],
        max_gap=1,
    )

    assert spans == []


def test_collect_bridge_entries_maps_each_frame_to_neighbors() -> None:
    entries = driver_face_reintegrate._collect_bridge_entries(
        [{"start": 4, "end": 5, "previous_good": 3, "next_good": 6}]
    )

    assert entries == {
        4: (3, 6),
        5: (3, 6),
    }


def test_apply_preroll_entries_copies_first_good_future_frame() -> None:
    entries, report = driver_face_reintegrate._apply_preroll_entries(
        {},
        [False, False, False],
        preroll_frames=1,
    )

    assert entries == {
        0: (None, 1),
    }
    assert report == {
        "requested_frames": 1,
        "applied_frames": 1,
        "anchor_frame": 1,
    }


def test_apply_preroll_entries_skips_bad_future_frames_until_good_anchor() -> None:
    entries, report = driver_face_reintegrate._apply_preroll_entries(
        {},
        [False, True, False, False],
        preroll_frames=1,
    )

    assert entries == {
        0: (None, 2),
    }
    assert report == {
        "requested_frames": 1,
        "applied_frames": 1,
        "anchor_frame": 2,
    }


def test_bridge_spans_include_leading_gap_when_next_good_exists() -> None:
    spans = driver_face_reintegrate._bridge_spans(
        [True, False, False],
        max_gap=2,
    )

    assert spans == [
        {"start": 0, "end": 0, "previous_good": None, "next_good": 1},
    ]


def test_bridge_spans_include_trailing_gap_when_previous_good_exists() -> None:
    spans = driver_face_reintegrate._bridge_spans(
        [False, False, True],
        max_gap=2,
    )

    assert spans == [
        {"start": 2, "end": 2, "previous_good": 1, "next_good": None},
    ]


def test_adaptive_gap_limit_grows_for_missing_and_prefail_runs() -> None:
    limit = driver_face_reintegrate._adaptive_gap_limit(
        [
            {"prefail_extended": True, "target_missing": False, "swapped_missing": False, "swapped_landmark_jump": 5.5, "swapped_delta_mean": 1.5},
            {"target_missing": True, "swapped_missing": False, "swapped_landmark_jump": 6.0, "swapped_delta_mean": 2.0},
            {"target_missing": False, "swapped_missing": False, "swapped_landmark_jump": 5.8, "swapped_delta_mean": 1.8},
        ],
        start_index=0,
        end_index=2,
        max_gap=6,
    )

    assert limit == 11


def test_adaptive_bridge_spans_can_bridge_longer_dynamic_run() -> None:
    flags = [False] + ([True] * 8) + [False]
    metric_rows = [{"target_missing": False, "swapped_missing": False, "swapped_landmark_jump": None, "swapped_delta_mean": 0.0}]
    metric_rows.extend(
        [
            {"prefail_extended": True, "target_missing": False, "swapped_missing": False, "swapped_landmark_jump": 5.5, "swapped_delta_mean": 1.5},
            {"target_missing": False, "swapped_missing": False, "swapped_landmark_jump": 5.6, "swapped_delta_mean": 1.5},
            {"target_missing": False, "swapped_missing": False, "swapped_landmark_jump": 5.7, "swapped_delta_mean": 1.5},
            {"target_missing": True, "swapped_missing": False, "swapped_landmark_jump": 6.0, "swapped_delta_mean": 2.0},
            {"target_missing": True, "swapped_missing": False, "swapped_landmark_jump": 6.0, "swapped_delta_mean": 2.0},
            {"target_missing": False, "swapped_missing": False, "swapped_landmark_jump": 5.8, "swapped_delta_mean": 1.8},
            {"target_missing": False, "swapped_missing": False, "swapped_landmark_jump": 5.9, "swapped_delta_mean": 1.8},
            {"target_missing": False, "swapped_missing": False, "swapped_landmark_jump": 5.2, "swapped_delta_mean": 1.3},
        ]
    )
    metric_rows.append({"target_missing": False, "swapped_missing": False, "swapped_landmark_jump": None, "swapped_delta_mean": 0.0})

    spans = driver_face_reintegrate._adaptive_bridge_spans(flags, metric_rows, max_gap=6)

    assert spans == [
        {"start": 1, "end": 8, "previous_good": 0, "next_good": 9, "gap_limit": 12},
    ]


def test_interpolate_frame_blends_neighboring_frames() -> None:
    previous = np.zeros((2, 2, 3), dtype=np.uint8)
    next_frame = np.full((2, 2, 3), 90, dtype=np.uint8)

    blended = driver_face_reintegrate._interpolate_frame(previous, next_frame, weight=1 / 3)

    assert blended.shape == previous.shape
    assert int(blended[0, 0, 0]) == 30


def test_bridge_flags_mark_large_swapped_jump_without_fallback() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": 8.0,
                "swapped_landmark_jump": 30.0,
                "pose_gap": 2.0,
                "swapped_delta_mean": 2.5,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 1,
        "geometry_mismatch_frames": 0,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 0,
    }


def test_bridge_flags_mark_moderate_swap_jump_when_target_is_stable() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": 2.0,
                "swapped_landmark_jump": 16.0,
                "pose_gap": 2.0,
                "swapped_delta_mean": 1.6,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 1,
        "geometry_mismatch_frames": 0,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 0,
    }


def test_bridge_flags_mark_lower_swap_jump_when_target_is_very_stable() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": 2.8,
                "swapped_landmark_jump": 9.1,
                "pose_gap": 0.5,
                "swapped_delta_mean": 1.4,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 1,
        "geometry_mismatch_frames": 0,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 0,
    }


def test_bridge_flags_mark_visible_swap_trail_even_without_other_failures() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": 4.8,
                "swapped_landmark_jump": 5.2,
                "pose_gap": 1.0,
                "swapped_delta_mean": 1.3,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 1,
        "geometry_mismatch_frames": 0,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 0,
    }


def test_bridge_flags_ignore_small_motion() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": 10.0,
                "swapped_landmark_jump": 14.0,
                "pose_gap": 2.0,
                "swapped_delta_mean": 0.6,
            }
        ]
    )

    assert flags == [False]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 0,
        "geometry_mismatch_frames": 0,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 0,
    }


def test_bridge_flags_mark_moderate_swap_jump_when_visible_swap_trail_exists() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": 7.0,
                "swapped_landmark_jump": 16.0,
                "pose_gap": 2.0,
                "swapped_delta_mean": 1.6,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 1,
        "geometry_mismatch_frames": 0,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 0,
    }


def test_bridge_flags_mark_lower_swap_jump_when_visible_swap_trail_exists() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": 3.6,
                "swapped_landmark_jump": 9.5,
                "pose_gap": 0.5,
                "swapped_delta_mean": 1.4,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 1,
        "geometry_mismatch_frames": 0,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 0,
    }


def test_bridge_flags_mark_missing_target_face() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": True,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": None,
                "swapped_landmark_jump": 29.0,
                "pose_gap": None,
                "swapped_delta_mean": 3.2,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 1,
        "geometry_mismatch_frames": 0,
        "pose_gap_frames": 0,
        "target_missing_frames": 1,
        "swapped_missing_frames": 0,
    }


def test_bridge_flags_mark_missing_swapped_face() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": True,
                "target_fallback": False,
                "target_landmark_jump": 4.0,
                "swapped_landmark_jump": None,
                "pose_gap": None,
                "swapped_delta_mean": 0.0,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 0,
        "geometry_mismatch_frames": 0,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 1,
    }


def test_bridge_flags_mark_tiny_swapped_face_with_stable_target() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": 3.8,
                "swapped_landmark_jump": 6.9,
                "pose_gap": 0.1,
                "swapped_delta_mean": 1.6,
                "swapped_target_area_ratio": 0.58,
                "swapped_target_center_offset_ratio": 0.08,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 1,
        "geometry_mismatch_frames": 1,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 0,
    }


def test_bridge_flags_mark_borderline_tiny_face_when_target_is_still_stable() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": 3.8,
                "swapped_landmark_jump": 6.9,
                "pose_gap": 0.0,
                "swapped_delta_mean": 1.5,
                "swapped_target_area_ratio": 0.795,
                "swapped_target_center_offset_ratio": 0.05,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 1,
        "geometry_mismatch_frames": 1,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 0,
    }


def test_bridge_flags_mark_displaced_swapped_face() -> None:
    flags, counts = driver_face_reintegrate._bridge_flags_from_metrics(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_fallback": False,
                "target_landmark_jump": 2.4,
                "swapped_landmark_jump": 8.2,
                "pose_gap": 1.5,
                "swapped_delta_mean": 1.3,
                "swapped_target_area_ratio": 0.94,
                "swapped_target_center_offset_ratio": 0.22,
            }
        ]
    )

    assert flags == [True]
    assert counts == {
        "fallback_frames": 0,
        "jump_frames": 1,
        "geometry_mismatch_frames": 1,
        "pose_gap_frames": 0,
        "target_missing_frames": 0,
        "swapped_missing_frames": 0,
    }


def test_extend_prefail_flags_marks_frame_before_missing_target() -> None:
    flags, prefail_frames = driver_face_reintegrate._extend_prefail_flags(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_landmark_jump": 1.2,
                "swapped_delta_mean": 1.6,
            },
            {
                "target_missing": True,
                "swapped_missing": False,
                "target_landmark_jump": None,
                "swapped_delta_mean": 2.2,
            },
        ],
        [False, True],
    )

    assert flags == [True, True]
    assert prefail_frames == 1


def test_extend_prefail_flags_ignores_stable_frame_without_next_missing() -> None:
    flags, prefail_frames = driver_face_reintegrate._extend_prefail_flags(
        [
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_landmark_jump": 1.2,
                "swapped_delta_mean": 1.6,
            },
            {
                "target_missing": False,
                "swapped_missing": False,
                "target_landmark_jump": 0.9,
                "swapped_delta_mean": 1.0,
            },
        ],
        [False, False],
    )

    assert flags == [False, False]
    assert prefail_frames == 0
