#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Sequence

from core.openpilot_config import default_local_openpilot_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run benchmark candidates over prepared driver-face evaluation samples.")
    parser.add_argument("--eval-root", default="./shared/driver-face-eval")
    parser.add_argument("--openpilot-dir", default=default_local_openpilot_root())
    parser.add_argument("--candidate-id", default="dm-box-pixelize")
    parser.add_argument("--pixel-block-size", type=int, default=18)
    parser.add_argument("--facefusion-root", default="./.cache/facefusion")
    parser.add_argument("--facefusion-source-image", default="./shared/driver-face-eval/generic-donor.jpg")
    parser.add_argument("--facefusion-model", default="hyperswap_1b_256")
    parser.add_argument("--driver-face-donor-bank-dir", default="./shared/driver-face-eval/donors")
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
    openpilot_dir = Path(args.openpilot_dir).expanduser().resolve()
    facefusion_root = Path(args.facefusion_root).expanduser().resolve()
    facefusion_source_image = Path(args.facefusion_source_image).expanduser().resolve()
    worker_python = openpilot_dir / ".venv/bin/python"
    if not worker_python.exists():
        raise SystemExit(f"Openpilot worker interpreter not found at {worker_python}")

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
        ]
        subprocess.run(worker_cmd, check=True)
        print(f"Benchmarked {sample_dir.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
