from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.driver_face_donor_sweep import (  # noqa: E402
    _cosine_similarity,
    _extract_primary_embedding,
    _init_facefusion_modules,
    _lab_distance,
    _mean_lab_for_rect,
    _read_video_frame,
    _rect_from_box,
    _run_facefusion_fast_swap,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auto-select the best same-tone donor from a bank for a target face crop.")
    parser.add_argument("--target-video", required=True)
    parser.add_argument("--donor-bank-dir", required=True)
    parser.add_argument("--facefusion-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--frame-number", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--tone-margin-lab", type=float, default=12.0)
    parser.add_argument("--include-preview", action="store_true")
    return parser


def _donor_images(donor_bank_dir: Path, *, include_preview: bool) -> list[Path]:
    images: list[Path] = []
    for path in sorted(donor_bank_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        lower_name = path.name.lower()
        if "contact-sheet" in lower_name:
            continue
        if not include_preview and "preview" in lower_name:
            continue
        images.append(path)
    return images


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    target_video = Path(args.target_video).expanduser().resolve()
    donor_bank_dir = Path(args.donor_bank_dir).expanduser().resolve()
    facefusion_root = Path(args.facefusion_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not target_video.exists():
        raise SystemExit(f"Missing target video: {target_video}")
    if not donor_bank_dir.exists():
        raise SystemExit(f"Missing donor bank dir: {donor_bank_dir}")

    donor_images = _donor_images(donor_bank_dir, include_preview=args.include_preview)
    if not donor_images:
        raise SystemExit(f"No donor images found under {donor_bank_dir}")

    _, detect_faces, calculate_face_embedding = _init_facefusion_modules(facefusion_root)
    original_frame = _read_video_frame(target_video, args.frame_number)
    original_embedding = _extract_primary_embedding(
        original_frame,
        detect_faces=detect_faces,
        calculate_face_embedding=calculate_face_embedding,
    )
    if original_embedding is None:
        raise SystemExit("Failed to extract a reference embedding from the selection clip.")
    original_lab = _mean_lab_for_rect(original_frame, _rect_from_box(original_embedding.bounding_box))

    donor_candidates: list[dict[str, Any]] = []
    for donor_path in donor_images:
        import cv2

        donor_frame = cv2.imread(str(donor_path))
        if donor_frame is None:
            continue
        donor_embedding = _extract_primary_embedding(
            donor_frame,
            detect_faces=detect_faces,
            calculate_face_embedding=calculate_face_embedding,
        )
        if donor_embedding is None:
            continue
        donor_lab = _mean_lab_for_rect(donor_frame, _rect_from_box(donor_embedding.bounding_box))
        donor_candidates.append(
            {
                "donor_path": donor_path,
                "donor_lab": donor_lab,
                "donor_embedding": donor_embedding.embedding_norm,
                "donor_tone_distance_lab": _lab_distance(original_lab, donor_lab),
            }
        )

    if not donor_candidates:
        raise SystemExit("No donors produced usable face detections.")

    donor_candidates.sort(key=lambda row: float(row["donor_tone_distance_lab"]))
    nearest_distance = float(donor_candidates[0]["donor_tone_distance_lab"])
    tone_threshold = nearest_distance + max(0.0, float(args.tone_margin_lab))
    prefiltered = [row for row in donor_candidates if float(row["donor_tone_distance_lab"]) <= tone_threshold]
    if not prefiltered:
        prefiltered = donor_candidates[: max(1, args.top_k)]
    selected_candidates = prefiltered[: max(1, args.top_k)]

    results: list[dict[str, Any]] = []
    for row in selected_candidates:
        donor_path = Path(row["donor_path"])
        swap_output = output_dir / f"{donor_path.stem}-auto-select.mp4"
        _run_facefusion_fast_swap(
            facefusion_root=facefusion_root,
            donor_image=donor_path,
            target_video=target_video,
            output_video=swap_output,
        )

        swap_frame = _read_video_frame(swap_output, args.frame_number)
        swapped_embedding = _extract_primary_embedding(
            swap_frame,
            detect_faces=detect_faces,
            calculate_face_embedding=calculate_face_embedding,
        )
        if swapped_embedding is None:
            continue

        swap_lab = _mean_lab_for_rect(swap_frame, _rect_from_box(swapped_embedding.bounding_box))
        original_vs_swapped = _cosine_similarity(original_embedding.embedding_norm, swapped_embedding.embedding_norm)
        donor_vs_swapped = _cosine_similarity(row["donor_embedding"], swapped_embedding.embedding_norm)
        swap_tone_distance = _lab_distance(original_lab, swap_lab)
        score = (
            (donor_vs_swapped or 0.0) * 1.45
            - (original_vs_swapped or 0.0) * 1.9
            - float(row["donor_tone_distance_lab"]) * 0.03
            - swap_tone_distance * 0.03
            + swapped_embedding.detector_score * 0.15
        )
        results.append(
            {
                "donor_image": str(donor_path),
                "swap_video": str(swap_output),
                "donor_tone_distance_lab": float(row["donor_tone_distance_lab"]),
                "swap_tone_distance_lab": swap_tone_distance,
                "original_vs_swapped_cosine": original_vs_swapped,
                "donor_vs_swapped_cosine": donor_vs_swapped,
                "swap_detector_score": swapped_embedding.detector_score,
                "ranking_score": score,
            }
        )

    if not results:
        raise SystemExit("Auto donor selection could not produce any valid swap candidates.")

    results.sort(key=lambda row: float(row["ranking_score"]), reverse=True)
    report = {
        "target_video": str(target_video),
        "frame_number": args.frame_number,
        "top_k": args.top_k,
        "tone_margin_lab": args.tone_margin_lab,
        "selected_donor_image": results[0]["donor_image"],
        "results": results,
    }
    report_path = output_dir / "auto-select-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"selected_donor_image": results[0]["donor_image"], "report_path": str(report_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
