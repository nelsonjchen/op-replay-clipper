from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from core.driver_face_swap import default_facefusion_output_video_encoder


DEFAULT_NEGATIVE_PROMPT = (
    "different person, different skin tone, cartoon, illustration, painted, "
    "extreme edit, text, watermark, blurry, deformed face, low quality"
)


@dataclass(frozen=True)
class DonorVariantSpec:
    variant_id: str
    label: str
    prompt: str
    strength: float = 0.82


VARIANT_SPECS: tuple[DonorVariantSpec, ...] = (
    DonorVariantSpec(
        variant_id="stubble",
        label="Stubble",
        prompt=(
            "Edit this realistic studio portrait photo of the same adult man. Add subtle short dark stubble "
            "across the jaw and upper lip. Keep the same person, same skin tone, same approximate age, "
            "same head shape, same camera angle, same neutral expression, same lighting style, same plain "
            "background, and photorealistic texture. Keep it looking like the same portrait, just with realistic "
            "light facial hair."
        ),
    ),
    DonorVariantSpec(
        variant_id="short-beard",
        label="Short Beard",
        prompt=(
            "Edit this realistic studio portrait photo of the same adult man. Add a short natural dark beard and "
            "a subtle light mustache. Keep the same person, same skin tone, same approximate age, same head shape, "
            "same camera angle, same neutral expression, same lighting style, same plain background, and "
            "photorealistic texture. Keep it looking like the same portrait, just with realistic facial hair."
        ),
    ),
    DonorVariantSpec(
        variant_id="fuller-beard",
        label="Fuller Beard",
        prompt=(
            "Edit this realistic studio portrait photo of the same adult man. Add a neatly trimmed full dark beard "
            "and mustache, fuller than short stubble but still natural and professional. Keep the same person, "
            "same skin tone, same approximate age, same head shape, same camera angle, same neutral expression, "
            "same lighting style, same plain background, and photorealistic texture. Keep it looking like the "
            "same portrait, just with realistic fuller facial hair."
        ),
        strength=0.84,
    ),
    DonorVariantSpec(
        variant_id="glasses",
        label="Glasses",
        prompt=(
            "Edit this realistic studio portrait photo of the same adult man. Add subtle realistic dark rectangular "
            "eyeglasses with thin frames. Keep the same person, same skin tone, same approximate age, same head "
            "shape, same camera angle, same neutral expression, same lighting style, same plain background, and "
            "photorealistic texture. Keep the eyes clearly visible and keep it looking like the same portrait."
        ),
        strength=0.8,
    ),
    DonorVariantSpec(
        variant_id="older",
        label="Slightly Older",
        prompt=(
            "Edit this realistic studio portrait photo of the same adult man. Make him look modestly older, about "
            "five to ten years older, with slightly more mature facial structure and subtle smile lines. Keep the "
            "same person, same skin tone, same general hairstyle, same head shape, same camera angle, same neutral "
            "expression, same lighting style, same plain background, and photorealistic texture."
        ),
        strength=0.78,
    ),
)


@dataclass
class EmbeddingResult:
    embedding_norm: np.ndarray
    detector_score: float
    bounding_box: list[float]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and score donor variants against a driver-camera face crop.")
    parser.add_argument("--sample-dir", default="./shared/driver-face-eval/tici-baseline")
    parser.add_argument("--base-donor", default="./assets/driver-face-donors/generic-donor-clean-shaven.jpg")
    parser.add_argument("--donors-dir", default="./assets/driver-face-donors")
    parser.add_argument("--facefusion-root", default="./.cache/facefusion")
    parser.add_argument("--runware-python", default="./.cache/flux-kontext/bin/python")
    parser.add_argument("--frame-number", type=int, default=20)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument("--variants", nargs="*", help="Optional subset of variant ids to run.")
    return parser


def _variant_specs(selected: list[str] | None) -> list[DonorVariantSpec]:
    if not selected:
        return list(VARIANT_SPECS)
    wanted = set(selected)
    variants = [spec for spec in VARIANT_SPECS if spec.variant_id in wanted]
    missing = sorted(wanted - {spec.variant_id for spec in variants})
    if missing:
        raise SystemExit(f"Unknown variant ids: {', '.join(missing)}")
    return variants


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _absolute_path(path: str | Path, *, root: Path) -> Path:
    raw = Path(path).expanduser()
    if raw.is_absolute():
        return raw
    return Path(os.path.abspath(root / raw))


def _run_subprocess(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _generate_variant(
    *,
    repo_root: Path,
    runware_python: Path,
    input_image: Path,
    output_image: Path,
    spec: DonorVariantSpec,
) -> None:
    command = [
        str(runware_python),
        str((repo_root / "tools/runware_flux_kontext_edit.py").resolve()),
        str(input_image),
        str(output_image),
        spec.prompt,
        "--negative-prompt",
        DEFAULT_NEGATIVE_PROMPT,
        "--strength",
        str(spec.strength),
        "--steps",
        "28",
        "--guidance-scale",
        "2.5",
        "--width",
        "1024",
        "--height",
        "1024",
    ]
    _run_subprocess(command, cwd=repo_root)


def _run_facefusion_fast_swap(
    *,
    facefusion_root: Path,
    donor_image: Path,
    target_video: Path,
    output_video: Path,
) -> None:
    output_video_encoder = default_facefusion_output_video_encoder()
    jobs_path = output_video.parent / "facefusion-jobs"
    temp_path = output_video.parent / "facefusion-temp"
    jobs_path.mkdir(parents=True, exist_ok=True)
    temp_path.mkdir(parents=True, exist_ok=True)
    command = [
        str(facefusion_root / ".venv/bin/python"),
        str(facefusion_root / "facefusion.py"),
        "headless-run",
        "--jobs-path",
        str(jobs_path),
        "--temp-path",
        str(temp_path),
        "--processors",
        "face_swapper",
        "--face-swapper-model",
        "hyperswap_1b_256",
        "--face-swapper-pixel-boost",
        "256x256",
        "--face-swapper-weight",
        "1.0",
        "--face-selector-mode",
        "one",
        "--face-detector-model",
        "yunet",
        "--face-detector-score",
        "0.35",
        "--face-mask-types",
        "box",
        "--face-mask-blur",
        "0.1",
        "--face-mask-padding",
        "8",
        "8",
        "8",
        "8",
        "--execution-providers",
        "coreml",
        "cpu",
        "--execution-thread-count",
        "4",
        "--video-memory-strategy",
        "tolerant",
        "--system-memory-limit",
        "0",
        "--output-video-encoder",
        output_video_encoder,
        "--output-video-quality",
        "75",
        "--output-video-preset",
        "veryfast",
        "--temp-frame-format",
        "jpeg",
        "-s",
        str(donor_image),
        "-t",
        str(target_video),
        "-o",
        str(output_video),
        "--log-level",
        "warn",
    ]
    env = dict(os.environ)
    env["SYSTEM_VERSION_COMPAT"] = "0"
    _run_subprocess(command, cwd=facefusion_root, env=env)


def _read_video_frame(video_path: Path, frame_number: int) -> np.ndarray:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        target = max(0, min(frame_number, max(0, total - 1)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"Failed to read frame {frame_number} from {video_path}")
        return frame
    finally:
        capture.release()


def _write_frame(path: Path, frame: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"Failed to write image: {path}")


def _mean_lab_for_rect(frame: np.ndarray, rect: tuple[int, int, int, int] | None) -> list[float]:
    if rect is None:
        rect = (0, 0, frame.shape[1], frame.shape[0])
    x, y, w, h = rect
    roi = frame[y:y + h, x:x + w]
    if roi.size == 0:
        roi = frame
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
    mean = lab.reshape(-1, 3).mean(axis=0)
    return [float(value) for value in mean.tolist()]


def _lab_distance(a: list[float], b: list[float]) -> float:
    return float(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))))


def _init_facefusion_modules(facefusion_root: Path) -> tuple[Any, Any, Any]:
    root_str = str(facefusion_root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from facefusion import state_manager  # type: ignore
    from facefusion.face_detector import detect_faces, pre_check as face_detector_pre_check  # type: ignore
    from facefusion.face_recognizer import calculate_face_embedding, pre_check as face_recognizer_pre_check  # type: ignore

    state_manager.init_item("execution_device_ids", [0])
    state_manager.init_item("execution_providers", ["cpu"])
    state_manager.init_item("download_providers", ["github", "huggingface"])
    state_manager.init_item("face_detector_model", "yunet")
    state_manager.init_item("face_detector_size", "640x640")
    state_manager.init_item("face_detector_margin", [0, 0, 0, 0])
    state_manager.init_item("face_detector_score", 0.35)
    state_manager.init_item("face_detector_angles", [0])
    face_detector_pre_check()
    face_recognizer_pre_check()
    return state_manager, detect_faces, calculate_face_embedding


def _extract_primary_embedding(
    frame: np.ndarray,
    *,
    detect_faces: Any,
    calculate_face_embedding: Any,
) -> EmbeddingResult | None:
    bounding_boxes, face_scores, face_landmarks_5 = detect_faces(frame)
    if not bounding_boxes:
        return None

    def score_key(index: int) -> tuple[float, float]:
        box = bounding_boxes[index]
        width = float(box[2] - box[0])
        height = float(box[3] - box[1])
        area = max(0.0, width * height)
        return area, float(face_scores[index])

    best_index = max(range(len(bounding_boxes)), key=score_key)
    embedding, embedding_norm = calculate_face_embedding(frame, face_landmarks_5[best_index])
    box = bounding_boxes[best_index]
    return EmbeddingResult(
        embedding_norm=embedding_norm,
        detector_score=float(face_scores[best_index]),
        bounding_box=[float(value) for value in box.tolist()],
    )


def _cosine_similarity(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    if a is None or b is None:
        return None
    return float(np.dot(a, b))


def _contact_sheet(
    *,
    originals: list[tuple[str, Path]],
    swaps: list[tuple[str, Path]],
    output_path: Path,
) -> None:
    thumb_w = 256
    thumb_h = 256
    label_h = 36
    pad = 16
    columns = len(originals)
    canvas = Image.new(
        "RGB",
        (pad + columns * (thumb_w + pad), pad * 3 + (thumb_h + label_h) * 2),
        (18, 18, 18),
    )
    draw = ImageDraw.Draw(canvas)

    for row, items in enumerate((originals, swaps)):
        y_offset = pad + row * (thumb_h + label_h + pad)
        for column, (label, path) in enumerate(items):
            image = Image.open(path).convert("RGB")
            thumb = ImageOps.fit(image, (thumb_w, thumb_h), method=Image.Resampling.LANCZOS)
            x_offset = pad + column * (thumb_w + pad)
            canvas.paste(thumb, (x_offset, y_offset))
            draw.rectangle(
                (x_offset, y_offset + thumb_h, x_offset + thumb_w, y_offset + thumb_h + label_h),
                fill=(28, 28, 28),
            )
            draw.text((x_offset + 8, y_offset + thumb_h + 10), label, fill=(235, 235, 235))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    sample_dir = _absolute_path(args.sample_dir, root=repo_root)
    base_donor = _absolute_path(args.base_donor, root=repo_root)
    donors_dir = _ensure_dir(_absolute_path(args.donors_dir, root=repo_root))
    facefusion_root = _absolute_path(args.facefusion_root, root=repo_root)
    runware_python = _absolute_path(args.runware_python, root=repo_root)

    if not sample_dir.exists():
        raise SystemExit(f"Missing sample dir: {sample_dir}")
    if not base_donor.exists():
        raise SystemExit(f"Missing base donor image: {base_donor}")

    sweep_dir = _ensure_dir(sample_dir / "donor-sweep")
    donors_out_dir = _ensure_dir(donors_dir / "sweep")
    target_video = sample_dir / "face-crop.mp4"
    original_frame = _read_video_frame(target_video, args.frame_number)
    original_frame_path = sweep_dir / "original-frame.png"
    _write_frame(original_frame_path, original_frame)

    variant_specs = _variant_specs(args.variants)
    donor_images: list[tuple[str, Path]] = [("Base Donor", base_donor)]

    if not args.skip_generate:
        if not os.environ.get("RUNWARE_API_KEY"):
            raise SystemExit("RUNWARE_API_KEY is required unless --skip-generate is used.")
        for spec in variant_specs:
            output_path = donors_out_dir / f"{base_donor.stem}-{spec.variant_id}.png"
            if args.overwrite or not output_path.exists():
                _generate_variant(
                    repo_root=repo_root,
                    runware_python=runware_python,
                    input_image=base_donor,
                    output_image=output_path,
                    spec=spec,
                )
            donor_images.append((spec.label, output_path))
    else:
        for spec in variant_specs:
            output_path = donors_out_dir / f"{base_donor.stem}-{spec.variant_id}.png"
            if output_path.exists():
                donor_images.append((spec.label, output_path))

    _, detect_faces, calculate_face_embedding = _init_facefusion_modules(facefusion_root)

    original_embedding = _extract_primary_embedding(
        original_frame,
        detect_faces=detect_faces,
        calculate_face_embedding=calculate_face_embedding,
    )
    if original_embedding is None:
        raise SystemExit("Failed to extract a reference embedding from the original crop frame.")
    original_lab = _mean_lab_for_rect(
        original_frame,
        _rect_from_box(original_embedding.bounding_box),
    )

    report_rows: list[dict[str, Any]] = []
    donor_sheet_items: list[tuple[str, Path]] = []
    swap_sheet_items: list[tuple[str, Path]] = []

    for label, donor_path in donor_images:
        donor_frame = cv2.imread(str(donor_path))
        if donor_frame is None:
            raise RuntimeError(f"Failed to load donor image: {donor_path}")
        donor_embedding = _extract_primary_embedding(
            donor_frame,
            detect_faces=detect_faces,
            calculate_face_embedding=calculate_face_embedding,
        )
        if donor_embedding is None:
            continue

        variant_slug = donor_path.stem
        swap_output = sweep_dir / f"{variant_slug}-swap.mp4"
        if args.overwrite or not swap_output.exists():
            _run_facefusion_fast_swap(
                facefusion_root=facefusion_root,
                donor_image=donor_path,
                target_video=target_video,
                output_video=swap_output,
            )

        swap_frame = _read_video_frame(swap_output, args.frame_number)
        swap_frame_path = sweep_dir / f"{variant_slug}-frame{args.frame_number}.png"
        _write_frame(swap_frame_path, swap_frame)
        swapped_embedding = _extract_primary_embedding(
            swap_frame,
            detect_faces=detect_faces,
            calculate_face_embedding=calculate_face_embedding,
        )
        if swapped_embedding is None:
            continue

        donor_lab = _mean_lab_for_rect(donor_frame, _rect_from_box(donor_embedding.bounding_box))
        swap_lab = _mean_lab_for_rect(swap_frame, _rect_from_box(swapped_embedding.bounding_box))
        original_vs_swapped = _cosine_similarity(original_embedding.embedding_norm, swapped_embedding.embedding_norm)
        donor_vs_swapped = _cosine_similarity(donor_embedding.embedding_norm, swapped_embedding.embedding_norm)
        donor_tone_distance = _lab_distance(original_lab, donor_lab)
        swap_tone_distance = _lab_distance(original_lab, swap_lab)
        score = (
            (donor_vs_swapped or 0.0) * 1.4
            - (original_vs_swapped or 0.0) * 1.6
            - donor_tone_distance * 0.01
            - swap_tone_distance * 0.02
            + swapped_embedding.detector_score * 0.15
        )

        report_rows.append(
            {
                "label": label,
                "donor_image": str(donor_path),
                "swap_video": str(swap_output),
                "swap_frame": str(swap_frame_path),
                "original_vs_swapped_cosine": original_vs_swapped,
                "donor_vs_swapped_cosine": donor_vs_swapped,
                "donor_tone_distance_lab": donor_tone_distance,
                "swap_tone_distance_lab": swap_tone_distance,
                "swap_detector_score": swapped_embedding.detector_score,
                "ranking_score": score,
            }
        )
        donor_sheet_items.append((label, donor_path))
        swap_sheet_items.append((label, swap_frame_path))

    report_rows.sort(key=lambda row: row["ranking_score"], reverse=True)
    report = {
        "sample_dir": str(sample_dir),
        "frame_number": args.frame_number,
        "original_frame": str(original_frame_path),
        "variants": [asdict(spec) for spec in variant_specs],
        "results": report_rows,
    }
    report_path = sweep_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    contact_sheet_path = sweep_dir / "contact-sheet.png"
    if donor_sheet_items and swap_sheet_items:
        _contact_sheet(originals=donor_sheet_items, swaps=swap_sheet_items, output_path=contact_sheet_path)

    print(json.dumps({"report": str(report_path), "contact_sheet": str(contact_sheet_path)}))
    return 0


def _rect_from_box(box: list[float]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    x = int(round(x1))
    y = int(round(y1))
    w = int(round(x2 - x1))
    h = int(round(y2 - y1))
    return x, y, max(1, w), max(1, h)
