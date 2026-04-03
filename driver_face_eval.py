#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from core.driver_face_eval import DriverFaceEvalSeed, default_driver_face_eval_seeds, materialize_eval_sample, materialize_seed_set
from core.openpilot_config import default_local_openpilot_root, default_openpilot_branch, default_openpilot_repo_url
from core.route_inputs import parseRouteOrUrl
from core import driver_face_eval
from core.openpilot_bootstrap import bootstrap_openpilot, ensure_openpilot_checkout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Internal local evaluation harness for benchmarking face replacement approaches on comma driver-camera clips."
    )
    parser.add_argument("--output-root", default="./shared/driver-face-eval")
    parser.add_argument("--data-root", default="./shared/data_dir")
    parser.add_argument("--data-dir", default="", help="Explicit data dir. If unset, uses --data-root/<dongle-id>.")
    parser.add_argument("--openpilot-dir", default=default_local_openpilot_root())
    parser.add_argument("--openpilot-branch", default=default_openpilot_branch())
    parser.add_argument("--openpilot-repo-url", default=default_openpilot_repo_url())
    parser.add_argument("--skip-openpilot-update", action="store_true")
    parser.add_argument("--skip-openpilot-bootstrap", action="store_true")
    parser.add_argument("--skip-download", action="store_true", help="Reuse already-downloaded route data.")
    parser.add_argument("--include-driver-debug", action="store_true", help="Also render an analysis-oriented driver-debug clip.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite sample artifacts if they already exist.")
    parser.add_argument("--accel", choices=["auto", "cpu", "videotoolbox", "nvidia"], default="auto")
    parser.add_argument("--jwt-token", default="", help="Optional JWT token. If unset, COMMA_JWT from .env or the shell is used.")

    subparsers = parser.add_subparsers(dest="command")

    seed_set = subparsers.add_parser("seed-set", help="Materialize the default benchmark seed set.")
    seed_set.add_argument("--seeds", nargs="*", default=None, help="Subset of seed ids to materialize. Defaults to all seeds.")

    sample = subparsers.add_parser("sample", help="Materialize one custom evaluation sample.")
    sample.add_argument("sample_id")
    sample.add_argument("route")
    sample.add_argument("--start-seconds", type=int, required=True)
    sample.add_argument("--length-seconds", type=int, required=True)
    sample.add_argument("--category", default="custom sample")
    sample.add_argument("--notes", default="Custom driver-camera evaluation sample.")

    return parser


def _prepare_openpilot(args: argparse.Namespace) -> str:
    openpilot_path = Path(args.openpilot_dir).expanduser().resolve()
    if args.skip_openpilot_update and not openpilot_path.exists():
        raise SystemExit(
            f"Openpilot checkout not found at {openpilot_path}. Remove --skip-openpilot-update or point --openpilot-dir at an existing checkout."
        )
    if not args.skip_openpilot_update:
        ensure_openpilot_checkout(
            openpilot_path,
            branch=args.openpilot_branch,
            repo_url=args.openpilot_repo_url,
        )
    if not args.skip_openpilot_bootstrap:
        bootstrap_openpilot(openpilot_path)
    elif not (openpilot_path / ".venv/bin/python").exists():
        raise SystemExit(
            f"Openpilot is not bootstrapped at {openpilot_path}. Remove --skip-openpilot-bootstrap or run bootstrap first."
        )
    return str(openpilot_path)


def _selected_seeds(seed_ids: list[str] | None) -> list[DriverFaceEvalSeed]:
    seeds = list(default_driver_face_eval_seeds())
    if not seed_ids:
        return seeds
    selected: list[DriverFaceEvalSeed] = []
    for seed_id in seed_ids:
        selected.append(driver_face_eval.seed_by_id(seed_id))
    return selected


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    output_root = Path(args.output_root).expanduser().resolve()
    openpilot_dir = _prepare_openpilot(args)
    jwt_token = (args.jwt_token or os.environ.get("COMMA_JWT", "")).strip() or None

    if args.command in (None, "seed-set"):
        artifacts = materialize_seed_set(
            output_root=output_root,
            seeds=_selected_seeds(getattr(args, "seeds", None)),
            data_root=args.data_root,
            explicit_data_dir=args.data_dir or None,
            openpilot_dir=openpilot_dir,
            skip_download=args.skip_download,
            include_driver_debug=args.include_driver_debug,
            overwrite=args.overwrite,
            acceleration=args.accel,
            jwt_token=jwt_token,
        )
        print(f"Wrote benchmark set to: {output_root}")
        for artifact in artifacts:
            print(f"- {artifact.sample_id}: {artifact.output_dir}")
        return 0

    if args.command == "sample":
        parseRouteOrUrl(
            route_or_url=args.route,
            start_seconds=args.start_seconds,
            length_seconds=args.length_seconds,
            jwt_token=jwt_token,
        )
        seed = DriverFaceEvalSeed(
            sample_id=args.sample_id,
            category=args.category,
            route_or_url=args.route,
            start_seconds=args.start_seconds,
            length_seconds=args.length_seconds,
            notes=args.notes,
        )
        artifact = materialize_eval_sample(
            seed=seed,
            output_root=output_root,
            data_root=args.data_root,
            explicit_data_dir=args.data_dir or None,
            openpilot_dir=openpilot_dir,
            skip_download=args.skip_download,
            include_driver_debug=args.include_driver_debug,
            overwrite=args.overwrite,
            acceleration=args.accel,
            jwt_token=jwt_token,
        )
        print(f"Wrote sample: {artifact.output_dir}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
