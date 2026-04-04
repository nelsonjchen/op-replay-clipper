from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from core import rf_detr_repro


def _write_test_video(path: Path) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48))
    for index in range(2):
        frame = np.full((48, 64, 3), fill_value=40 + (index * 20), dtype=np.uint8)
        writer.write(frame)
    writer.release()


def _fake_model():
    return SimpleNamespace(model=SimpleNamespace(device="cpu"))


def _fake_detections():
    return SimpleNamespace(
        xyxy=np.asarray([[4.0, 6.0, 24.0, 30.0]], dtype=np.float32),
        confidence=np.asarray([0.91], dtype=np.float32),
        class_id=np.asarray([1], dtype=np.int64),
        mask=np.asarray([np.ones((24, 20), dtype=np.uint8)]),
    )


def test_run_rf_detr_repro_on_image(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "still.png"
    cv2.imwrite(str(input_path), np.full((48, 64, 3), 90, dtype=np.uint8))
    output_dir = tmp_path / "artifacts"
    monkeypatch.setattr(rf_detr_repro, "load_rf_detr_model", lambda *args, **kwargs: _fake_model())
    monkeypatch.setattr(rf_detr_repro, "predict_rf_detr", lambda *args, **kwargs: _fake_detections())

    report = rf_detr_repro.run_rf_detr_repro(
        input_path=input_path,
        output_dir=output_dir,
        requested_device="cpu",
        write_overlay_video=False,
    )

    assert report["actual_model_device"] == "cpu"
    assert report["frames_processed"] == 1
    assert report["first_frame_detections"] == 1
    assert report["total_detections"] == 1
    assert report["exception"] is None
    assert (output_dir / "report.json").exists()
    assert (output_dir / "frame-000-overlay.png").exists()


def test_run_rf_detr_repro_on_video(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "tiny.mp4"
    _write_test_video(input_path)
    output_dir = tmp_path / "artifacts"
    monkeypatch.setattr(rf_detr_repro, "load_rf_detr_model", lambda *args, **kwargs: _fake_model())
    monkeypatch.setattr(rf_detr_repro, "predict_rf_detr", lambda *args, **kwargs: _fake_detections())

    report = rf_detr_repro.run_rf_detr_repro(
        input_path=input_path,
        output_dir=output_dir,
        requested_device="cpu",
        max_frames=2,
        write_overlay_video=False,
    )

    assert report["input_kind"] == "video"
    assert report["frames_processed"] == 2
    assert report["first_frame_detections"] == 1
    assert report["second_frame_detections"] == 1
    assert report["total_detections"] == 2
    assert (output_dir / "frame-001-overlay.png").exists()


def test_bundle_repro_artifacts(tmp_path) -> None:
    output_dir = tmp_path / "artifacts"
    output_dir.mkdir()
    (output_dir / "report.json").write_text(json.dumps({"ok": True}))

    bundle_path = tmp_path / "bundle.zip"
    written = rf_detr_repro.bundle_repro_artifacts(output_dir, bundle_path)

    assert written == bundle_path
    assert bundle_path.exists()
