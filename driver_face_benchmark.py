#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from core.openpilot_config import default_local_openpilot_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run benchmark candidates over prepared driver-face evaluation samples.")
    parser.add_argument("--eval-root", default="./shared/driver-face-eval")
    parser.add_argument("--openpilot-dir", default=default_local_openpilot_root())
    parser.add_argument("--worker-python", default="", help="Python interpreter for the benchmark worker. Defaults to the current interpreter.")
    parser.add_argument("--candidate-id", default="dm-box-pixelize")
    parser.add_argument("--pixel-block-size", type=int, default=18)
    parser.add_argument("--facefusion-root", default="./.cache/facefusion")
    parser.add_argument("--facefusion-source-image", default="./assets/driver-face-donors/generic-donor-clean-shaven.jpg")
    parser.add_argument("--facefusion-model", default="hyperswap_1b_256")
    parser.add_argument("--driver-face-donor-bank-dir", default="./assets/driver-face-donors")
    parser.add_argument("--rf-detr-model-id", default="rfdetr-seg-preview")
    parser.add_argument("--rf-detr-threshold", type=float, default=0.4)
    parser.add_argument("--rf-detr-frame-stride", type=int, default=5)
    parser.add_argument("--rf-detr-mask-dilate", type=int, default=15)
    parser.add_argument("--rf-detr-startup-hold-frames", type=int, default=6)
    parser.add_argument("--rf-detr-passenger-crop-margin-ratio", type=float, default=0.10)
    parser.add_argument("--rf-detr-missing-hold-frames", type=int, default=10)
    parser.add_argument("samples", nargs="*", help="Optional sample ids. Defaults to all samples under the eval root.")
    return parser


def _sample_dirs(eval_root: Path, sample_ids: list[str]) -> list[Path]:
    if sample_ids:
        return [eval_root / sample_id for sample_id in sample_ids]
    return sorted(path for path in eval_root.iterdir() if path.is_dir())


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    eval_root = Path(args.eval_root).expanduser().resolve()
    facefusion_root = Path(args.facefusion_root).expanduser().resolve()
    facefusion_source_image = Path(args.facefusion_source_image).expanduser().resolve()
    worker_python = Path(args.worker_python).expanduser().resolve() if args.worker_python else Path(sys.executable).resolve()
    if not worker_python.exists():
        raise SystemExit(f"Benchmark worker interpreter not found at {worker_python}")

    sample_dirs = _sample_dirs(eval_root, list(args.samples))
    for sample_dir in sample_dirs:
        if not sample_dir.exists():
            raise SystemExit(f"Missing sample dir: {sample_dir}")
        worker_cmd = [
            str(worker_python),
            str((Path(__file__).resolve().parent / "core/driver_face_benchmark_worker.py").resolve()),
            "--sample-dir",
            str(sample_dir),
            "--candidate-id",
            args.candidate_id,
            "--pixel-block-size",
            str(args.pixel_block_size),
            "--facefusion-root",
            str(facefusion_root),
            "--facefusion-source-image",
            str(facefusion_source_image),
            "--facefusion-model",
            args.facefusion_model,
            "--driver-face-donor-bank-dir",
            args.driver_face_donor_bank_dir,
            "--rf-detr-model-id",
            args.rf_detr_model_id,
            "--rf-detr-threshold",
            str(args.rf_detr_threshold),
            "--rf-detr-frame-stride",
            str(args.rf_detr_frame_stride),
            "--rf-detr-mask-dilate",
            str(args.rf_detr_mask_dilate),
            "--rf-detr-startup-hold-frames",
            str(args.rf_detr_startup_hold_frames),
            "--rf-detr-passenger-crop-margin-ratio",
            str(args.rf_detr_passenger_crop_margin_ratio),
            "--rf-detr-missing-hold-frames",
            str(args.rf_detr_missing_hold_frames),
        ]
        subprocess.run(worker_cmd, check=True)
        print(f"Benchmarked {sample_dir.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
