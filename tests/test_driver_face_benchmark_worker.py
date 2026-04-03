from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from core import driver_face_benchmark_worker


def test_passenger_side_matches_selected_side_for_mirrored_driver_view() -> None:
    assert driver_face_benchmark_worker._passenger_side_for_frame({"selected_side": "left"}) == "left"
    assert driver_face_benchmark_worker._passenger_side_for_frame({"selected_side": "right"}) == "right"


def test_choose_passenger_mask_prefers_person_on_passenger_side() -> None:
    left_mask = np.zeros((8, 8), dtype=bool)
    left_mask[1:5, 0:3] = True
    right_mask = np.zeros((8, 8), dtype=bool)
    right_mask[2:7, 5:8] = True

    detections = SimpleNamespace(
        xyxy=np.array(
            [
                [0.0, 1.0, 3.0, 5.0],
                [5.0, 2.0, 8.0, 7.0],
            ]
        ),
        class_id=np.array([0, 0]),
        confidence=np.array([0.88, 0.76]),
        mask=np.stack([left_mask, right_mask]),
    )

    selected_mask, report = driver_face_benchmark_worker._choose_passenger_mask(
        detections,
        frame_row={"selected_side": "right"},
        frame_width=8,
        frame_height=8,
    )

    assert selected_mask is not None
    assert bool(selected_mask[4, 6]) is True
    assert report["passenger_side"] == "right"
    assert report["reason"] == "selected"


def test_passenger_crop_rect_targets_selected_half_with_overlap() -> None:
    left_crop = driver_face_benchmark_worker._passenger_crop_rect(
        frame_row={"selected_side": "left"},
        frame_width=1000,
        frame_height=600,
        margin_ratio=0.1,
    )
    right_crop = driver_face_benchmark_worker._passenger_crop_rect(
        frame_row={"selected_side": "right"},
        frame_width=1000,
        frame_height=600,
        margin_ratio=0.1,
    )

    assert left_crop == (0, 0, 600, 600)
    assert right_crop == (400, 0, 600, 600)


def test_expand_crop_detections_to_full_frame_offsets_boxes_and_masks() -> None:
    crop_detections = SimpleNamespace(
        xyxy=np.array([[10.0, 20.0, 30.0, 50.0]]),
        class_id=np.array([0]),
        confidence=np.array([0.9]),
        mask=np.array([[[False, True], [False, False]]]),
        data={},
    )

    expanded = driver_face_benchmark_worker._expand_crop_detections_to_full_frame(
        crop_detections,
        crop_rect=(100, 200, 2, 2),
        frame_width=400,
        frame_height=500,
    )

    assert expanded.xyxy.tolist() == [[110.0, 220.0, 130.0, 250.0]]
    assert expanded.mask.shape == (1, 500, 400)
    assert bool(expanded.mask[0, 200, 101]) is True


def test_choose_passenger_mask_uses_anchor_rect_to_reject_stray_blob() -> None:
    stray_mask = np.zeros((10, 10), dtype=bool)
    stray_mask[3:8, 0:3] = True
    passenger_mask = np.zeros((10, 10), dtype=bool)
    passenger_mask[2:9, 4:8] = True

    detections = SimpleNamespace(
        xyxy=np.array(
            [
                [0.0, 3.0, 3.0, 8.0],
                [4.0, 2.0, 8.0, 9.0],
            ]
        ),
        class_id=np.array([1, 1]),
        confidence=np.array([0.95, 0.4]),
        mask=np.stack([stray_mask, passenger_mask]),
        data={},
    )

    selected_mask, report = driver_face_benchmark_worker._choose_passenger_mask(
        detections,
        frame_row={"selected_side": "right"},
        frame_width=10,
        frame_height=10,
        anchor_rect=(4, 1, 4, 8),
    )

    assert selected_mask is not None
    assert bool(selected_mask[5, 5]) is True
    assert report["mask_box"] == {"x": 4, "y": 2, "width": 4, "height": 7}


def test_rf_detr_effect_for_candidate_maps_expected_styles() -> None:
    assert driver_face_benchmark_worker._rf_detr_effect_for_candidate("rf-detr-passenger-blackout") == "blackout"
    assert driver_face_benchmark_worker._rf_detr_effect_for_candidate("rf-detr-passenger-blur") == "blur"
    assert driver_face_benchmark_worker._rf_detr_effect_for_candidate("rf-detr-passenger-white-static") == "white-silhouette"


def test_white_static_mask_replaces_masked_region_with_bright_silhouette() -> None:
    frame = np.zeros((25, 25, 3), dtype=np.uint8)
    mask = np.zeros((25, 25), dtype=bool)
    mask[10:15, 10:15] = True

    driver_face_benchmark_worker._white_static_mask(frame, mask, frame_index=7)

    assert np.all(frame[mask] >= 200)
    assert np.any(frame[~mask] > 0)
