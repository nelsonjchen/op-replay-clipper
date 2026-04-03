from __future__ import annotations
from types import SimpleNamespace

import numpy as np

from core import driver_face_benchmark_worker


def test_passenger_side_matches_selected_side_for_mirrored_driver_view() -> None:
    assert driver_face_benchmark_worker._passenger_side_for_frame({"selected_side": "left"}) == "left"
    assert driver_face_benchmark_worker._passenger_side_for_frame({"selected_side": "right"}) == "right"


def test_normalize_driver_monitoring_device_type_maps_tizi_to_tici() -> None:
    assert (
        driver_face_benchmark_worker._normalize_driver_monitoring_device_type(
            "tizi",
            frame_width=1928,
            frame_height=1208,
        )
        == "tici"
    )
    assert (
        driver_face_benchmark_worker._normalize_driver_monitoring_device_type(
            "mici",
            frame_width=1344,
            frame_height=760,
        )
        == "mici"
    )


def test_parse_args_defaults_to_tighter_rf_detr_passenger_crop_margin() -> None:
    import sys

    argv = sys.argv
    try:
        sys.argv = [
            "driver_face_benchmark_worker.py",
            "--sample-dir",
            "sample",
            "--candidate-id",
            "rf-detr-passenger-silhouette",
        ]
        args = driver_face_benchmark_worker.parse_args()
    finally:
        sys.argv = argv

    assert args.rf_detr_frame_stride == 5
    assert args.rf_detr_passenger_crop_margin_ratio == 0.10
    assert args.rf_detr_missing_hold_frames == 10


def test_driver_monitoring_input_crop_rect_matches_driver_debug_tici_crop() -> None:
    crop = driver_face_benchmark_worker._driver_monitoring_input_crop_rect(
        frame_width=1928,
        frame_height=1208,
        device_type="tizi",
    )

    assert crop == (244, 248, 1440, 960)


def test_driver_monitoring_input_crop_rect_matches_driver_debug_mici_crop() -> None:
    crop = driver_face_benchmark_worker._driver_monitoring_input_crop_rect(
        frame_width=1344,
        frame_height=760,
        device_type="mici",
    )

    assert crop[0] == 132
    assert crop[1] == 113
    assert crop[2] == 1081
    assert crop[3] == 647


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


def test_passenger_crop_rect_uses_dm_style_crop_for_tici_like_frames() -> None:
    left_crop = driver_face_benchmark_worker._passenger_crop_rect(
        frame_row={"selected_side": "left"},
        frame_width=1928,
        frame_height=1208,
        margin_ratio=0.18,
        device_type="tizi",
    )
    right_crop = driver_face_benchmark_worker._passenger_crop_rect(
        frame_row={"selected_side": "right"},
        frame_width=1928,
        frame_height=1208,
        margin_ratio=0.18,
        device_type="tizi",
    )

    assert left_crop == (244, 248, 979, 960)
    assert right_crop == (705, 248, 979, 960)


def test_passenger_crop_rect_uses_dm_style_crop_for_mici_frames() -> None:
    left_crop = driver_face_benchmark_worker._passenger_crop_rect(
        frame_row={"selected_side": "left"},
        frame_width=1344,
        frame_height=760,
        margin_ratio=0.18,
        device_type="mici",
    )
    right_crop = driver_face_benchmark_worker._passenger_crop_rect(
        frame_row={"selected_side": "right"},
        frame_width=1344,
        frame_height=760,
        margin_ratio=0.18,
        device_type="mici",
    )

    assert left_crop == (132, 113, 735, 647)
    assert right_crop == (477, 113, 736, 647)


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


def test_choose_passenger_mask_rejects_crop_filling_mask() -> None:
    full_crop_mask = np.ones((10, 10), dtype=bool)
    passenger_mask = np.zeros((10, 10), dtype=bool)
    passenger_mask[2:9, 4:8] = True

    detections = SimpleNamespace(
        xyxy=np.array(
            [
                [0.0, 0.0, 10.0, 10.0],
                [4.0, 2.0, 8.0, 9.0],
            ]
        ),
        class_id=np.array([3, 1]),
        confidence=np.array([0.55, 0.42]),
        mask=np.stack([full_crop_mask, passenger_mask]),
        data={},
    )

    selected_mask, report = driver_face_benchmark_worker._choose_passenger_mask(
        detections,
        frame_row={"selected_side": "right"},
        frame_width=10,
        frame_height=10,
        anchor_rect=(4, 1, 4, 8),
        crop_rect=(0, 0, 10, 10),
    )

    assert selected_mask is not None
    assert bool(selected_mask[5, 5]) is True
    assert report["mask_box"] == {"x": 4, "y": 2, "width": 4, "height": 7}
    assert report["mask_crop_area_fraction"] < 0.82


def test_rf_detr_effect_for_candidate_maps_expected_styles() -> None:
    assert driver_face_benchmark_worker._rf_detr_effect_for_candidate("rf-detr-passenger-blur") == "blur"
    assert driver_face_benchmark_worker._rf_detr_effect_for_candidate("rf-detr-passenger-silhouette") == "silhouette"


def test_shareable_h264_encoder_args_prefers_videotoolbox_on_macos(monkeypatch) -> None:
    monkeypatch.delenv("DRIVER_FACE_BENCHMARK_OUTPUT_VIDEO_ENCODER", raising=False)
    monkeypatch.setattr(driver_face_benchmark_worker.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(driver_face_benchmark_worker, "_ffmpeg_encoder_available", lambda name: name == "h264_videotoolbox")
    monkeypatch.setattr(driver_face_benchmark_worker, "_has_nvidia", lambda: False)

    args = driver_face_benchmark_worker._shareable_h264_encoder_args()

    assert args[:2] == ["-c:v", "h264_videotoolbox"]
    assert "-realtime" in args


def test_shareable_h264_encoder_args_honors_override(monkeypatch) -> None:
    monkeypatch.setenv("DRIVER_FACE_BENCHMARK_OUTPUT_VIDEO_ENCODER", "libx264")

    args = driver_face_benchmark_worker._shareable_h264_encoder_args()

    assert args[:4] == ["-c:v", "libx264", "-preset", "veryfast"]


def test_default_rf_detr_device_honors_override(monkeypatch) -> None:
    monkeypatch.setenv("DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE", "cpu")

    assert driver_face_benchmark_worker._default_rf_detr_device() == "cpu"


def test_silhouette_mask_replaces_masked_region_with_bright_silhouette() -> None:
    frame = np.zeros((25, 25, 3), dtype=np.uint8)
    mask = np.zeros((25, 25), dtype=bool)
    mask[10:15, 10:15] = True

    driver_face_benchmark_worker._silhouette_mask(frame, mask, frame_index=7)

    assert np.all(frame[mask] >= 200)
    assert np.any(frame[~mask] > 0)


def test_silhouette_mask_border_is_static_for_cutout_effect() -> None:
    mask = np.zeros((25, 25), dtype=bool)
    mask[10:15, 10:15] = True
    frame_a = np.zeros((25, 25, 3), dtype=np.uint8)
    frame_b = np.zeros((25, 25, 3), dtype=np.uint8)

    driver_face_benchmark_worker._silhouette_mask(frame_a, mask, frame_index=0)
    driver_face_benchmark_worker._silhouette_mask(frame_b, mask, frame_index=4)

    border_alpha = driver_face_benchmark_worker._dashed_contour_alpha(mask, offset_kernel=7, dash_length=12.0, gap_length=7.0, thickness=2, scale=3)
    border = border_alpha > 0.05
    assert np.any(border)
    assert np.all(frame_a[border] == frame_b[border])
