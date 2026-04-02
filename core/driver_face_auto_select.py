from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DONOR_MANIFEST_NAME = "manifest.json"
DEFAULT_TOP_K = 3
DEFAULT_TONE_MARGIN_LAB = 12.0
DEFAULT_REPRESENTATIVE_FRAMES = 3
UNKNOWN = "uncertain"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auto-select the best same-tone donor from a bank for a target face crop."
    )
    parser.add_argument("--target-video", required=True)
    parser.add_argument("--track-metadata")
    parser.add_argument("--donor-bank-dir", required=True)
    parser.add_argument("--facefusion-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--tone-margin-lab", type=float, default=DEFAULT_TONE_MARGIN_LAB)
    parser.add_argument("--representative-frames", type=int, default=DEFAULT_REPRESENTATIVE_FRAMES)
    parser.add_argument("--include-preview", action="store_true")
    parser.add_argument("--facefusion-model", default="hyperswap_1b_256")
    return parser


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _lab_distance(a: list[float], b: list[float]) -> float:
    return float(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))))


def _cosine_similarity(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> float:
    numerator = sum(x * y for x, y in zip(a, b))
    denom_a = math.sqrt(sum(x * x for x in a))
    denom_b = math.sqrt(sum(y * y for y in b))
    if denom_a <= 0.0 or denom_b <= 0.0:
        return 0.0
    return float(numerator / (denom_a * denom_b))


def _face_frame_score(frame_row: dict[str, Any]) -> float:
    face_prob = float(frame_row.get("face_prob", 0.0) or 0.0)
    held_penalty = 0.08 if int(frame_row.get("held_without_detection", 0) or 0) else 0.0
    missing_penalty = 0.6 if frame_row.get("padded_box") is None else 0.0
    return face_prob - held_penalty - missing_penalty


def select_representative_frame_indices(track: dict[str, Any], *, count: int = DEFAULT_REPRESENTATIVE_FRAMES) -> list[int]:
    frames = list(track.get("frames", []))
    if not frames:
        return []
    count = max(1, min(count, len(frames)))
    chosen: list[int] = []
    segment_size = max(1, len(frames) // count)
    for segment_index in range(count):
        start = segment_index * segment_size
        end = len(frames) if segment_index == count - 1 else min(len(frames), start + segment_size)
        segment = list(range(start, end))
        if not segment:
            continue
        best_index = max(segment, key=lambda idx: (_face_frame_score(frames[idx]), -abs(idx - ((start + end - 1) / 2.0))))
        if best_index not in chosen:
            chosen.append(best_index)
    if len(chosen) < count:
        remaining = [idx for idx in range(len(frames)) if idx not in chosen]
        remaining.sort(key=lambda idx: _face_frame_score(frames[idx]), reverse=True)
        for idx in remaining:
            chosen.append(idx)
            if len(chosen) >= count:
                break
    chosen.sort()
    return chosen


def _fallback_frame_indices(total_frames: int, *, count: int) -> list[int]:
    if total_frames <= 0:
        return []
    count = max(1, min(count, total_frames))
    if count == 1:
        return [max(0, total_frames // 2)]
    last_index = max(0, total_frames - 1)
    return sorted({round(last_index * (idx / (count - 1))) for idx in range(count)})


def _majority_label(values: list[str], *, default: str = UNKNOWN) -> str:
    filtered = [value for value in values if value and value != UNKNOWN]
    if not filtered:
        return default
    counter = Counter(filtered)
    [(label, label_count)] = counter.most_common(1)
    ties = [other_label for other_label, other_count in counter.items() if other_count == label_count]
    if len(ties) > 1:
        return default
    return label


def _presentation_from_gender(gender: str | None) -> str:
    if gender == "male":
        return "masc"
    if gender == "female":
        return "fem"
    return UNKNOWN


def _presentation_is_compatible(source_presentation: str, donor_presentation: str) -> bool:
    if source_presentation == UNKNOWN:
        return donor_presentation == UNKNOWN
    return donor_presentation == source_presentation


def _has_facial_hair(label: str) -> bool | None:
    if label == UNKNOWN:
        return None
    return label != "none"


def _beard_rank(label: str) -> int:
    return {
        "none": 0,
        "stubble": 1,
        "short_beard": 2,
        "full_beard": 3,
        UNKNOWN: -1,
    }.get(label, -1)


def _facial_hair_change_score(source_facial_hair: str, donor_facial_hair: str) -> float:
    source_has_hair = _has_facial_hair(source_facial_hair)
    donor_has_hair = _has_facial_hair(donor_facial_hair)
    if source_has_hair is None or donor_has_hair is None:
        return 0.0
    if source_has_hair == donor_has_hair:
        return -0.18
    return 0.18


def _infer_facial_hair_label(frame: Any, bounding_box: list[float]) -> str:
    import cv2
    import numpy as np

    x1, y1, x2, y2 = [int(round(value)) for value in bounding_box]
    x1 = max(0, min(x1, frame.shape[1] - 2))
    y1 = max(0, min(y1, frame.shape[0] - 2))
    x2 = max(x1 + 2, min(x2, frame.shape[1]))
    y2 = max(y1 + 2, min(y2, frame.shape[0]))
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return UNKNOWN
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    if width < 40 or height < 40:
        return UNKNOWN
    upper = gray[int(height * 0.22):int(height * 0.44), int(width * 0.22):int(width * 0.78)]
    lower = gray[int(height * 0.60):int(height * 0.92), int(width * 0.20):int(width * 0.80)]
    mustache = gray[int(height * 0.48):int(height * 0.62), int(width * 0.30):int(width * 0.70)]
    if upper.size == 0 or lower.size == 0 or mustache.size == 0:
        return UNKNOWN
    upper_mean = float(np.mean(upper))
    lower_mean = float(np.mean(lower))
    mustache_mean = float(np.mean(mustache))
    lower_std = float(np.std(lower))
    upper_std = float(np.std(upper))
    beard_score = (upper_mean - lower_mean) + max(0.0, lower_std - upper_std) * 0.45
    mustache_score = max(0.0, upper_mean - mustache_mean)
    combined_score = beard_score + (mustache_score * 0.35)
    if combined_score >= 28.0:
        return "full_beard"
    if combined_score >= 18.0:
        return "short_beard"
    if combined_score >= 10.0:
        return "stubble"
    return "none"


def _infer_glasses_label(frame: Any, bounding_box: list[float]) -> str:
    import cv2
    import numpy as np

    x1, y1, x2, y2 = [int(round(value)) for value in bounding_box]
    x1 = max(0, min(x1, frame.shape[1] - 2))
    y1 = max(0, min(y1, frame.shape[0] - 2))
    x2 = max(x1 + 2, min(x2, frame.shape[1]))
    y2 = max(y1 + 2, min(y2, frame.shape[0]))
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return UNKNOWN
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    if width < 50 or height < 50:
        return UNKNOWN
    eye_band = gray[int(height * 0.22):int(height * 0.48), int(width * 0.14):int(width * 0.86)]
    if eye_band.size == 0:
        return UNKNOWN
    edges = cv2.Canny(eye_band, 40, 120)
    edge_density = float(np.mean(edges > 0))
    dark_ratio = float(np.mean(eye_band < 60))
    if edge_density > 0.15 and dark_ratio > 0.10:
        return "yes"
    if edge_density < 0.08 and dark_ratio < 0.07:
        return "no"
    return UNKNOWN


def _load_track(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"frames": []}
    return json.loads(path.read_text())


def _donor_manifest_path(donor_bank_dir: Path) -> Path:
    return donor_bank_dir / DONOR_MANIFEST_NAME


def _donor_images_fallback(donor_bank_dir: Path, *, include_preview: bool) -> list[Path]:
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


def _load_donor_manifest(donor_bank_dir: Path, *, include_preview: bool) -> list[dict[str, Any]]:
    manifest_path = _donor_manifest_path(donor_bank_dir)
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text())
        donors: list[dict[str, Any]] = []
        for row in payload.get("donors", []):
            image_path = (donor_bank_dir / row["image"]).resolve()
            if not image_path.exists():
                continue
            if not include_preview and "preview" in image_path.name.lower():
                continue
            donors.append(
                {
                    "donor_id": row["id"],
                    "donor_name": row.get("label", row["id"]),
                    "image_path": image_path,
                    "tone_lab": [float(value) for value in row["tone_lab"]],
                    "presentation": row.get("presentation", UNKNOWN),
                    "facial_hair": row.get("facial_hair", UNKNOWN),
                    "glasses": row.get("glasses", UNKNOWN),
                }
            )
        return donors

    fallback = []
    for path in _donor_images_fallback(donor_bank_dir, include_preview=include_preview):
        fallback.append(
            {
                "donor_id": path.stem,
                "donor_name": path.stem,
                "image_path": path.resolve(),
                "tone_lab": [],
                "presentation": UNKNOWN,
                "facial_hair": UNKNOWN,
                "glasses": UNKNOWN,
            }
        )
    return fallback


def _select_prefiltered_candidates(
    donors: list[dict[str, Any]],
    *,
    source_lab: list[float],
    source_presentation: str,
    source_facial_hair: str,
    source_glasses: str,
    top_k: int,
    tone_margin_lab: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    compatible = []
    incompatible = []
    for donor in donors:
        if _presentation_is_compatible(source_presentation, str(donor.get("presentation", UNKNOWN))):
            compatible.append(donor)
        else:
            incompatible.append(
                {
                    "donor_id": donor["donor_id"],
                    "reason": "presentation_mismatch",
                    "presentation": donor.get("presentation", UNKNOWN),
                }
            )

    if not compatible and source_presentation == UNKNOWN:
        compatible = donors[:]
    if not compatible:
        raise RuntimeError("No presentation-compatible donors are available in the bank.")

    if source_glasses != UNKNOWN:
        same_glasses = [row for row in compatible if row.get("glasses", UNKNOWN) == source_glasses]
        if same_glasses:
            for donor in compatible:
                if donor not in same_glasses:
                    incompatible.append(
                        {
                            "donor_id": donor["donor_id"],
                            "reason": "glasses_mismatch",
                            "glasses": donor.get("glasses", UNKNOWN),
                        }
                    )
            compatible = same_glasses

    for donor in compatible:
        donor["donor_tone_distance_lab"] = _lab_distance(source_lab, list(donor.get("tone_lab") or source_lab))
    compatible.sort(key=lambda row: float(row["donor_tone_distance_lab"]))
    nearest = float(compatible[0]["donor_tone_distance_lab"])
    tone_threshold = nearest + max(0.0, tone_margin_lab)
    tone_filtered = [row for row in compatible if float(row["donor_tone_distance_lab"]) <= tone_threshold]
    if not tone_filtered:
        tone_filtered = compatible[: max(1, top_k)]

    selected_pool = tone_filtered
    hair_strategy = "tone_only"
    source_has_hair = _has_facial_hair(source_facial_hair)
    if source_has_hair is not None:
        if source_has_hair:
            clean_shaven = [row for row in tone_filtered if str(row.get("facial_hair", UNKNOWN)) == "none"]
            if clean_shaven:
                selected_pool = clean_shaven
                hair_strategy = "prefer_clean_shaven_extreme"
        else:
            hairy = [row for row in tone_filtered if _has_facial_hair(str(row.get("facial_hair", UNKNOWN))) is True]
            if hairy:
                max_rank = max(_beard_rank(str(row.get("facial_hair", UNKNOWN))) for row in hairy)
                selected_pool = [
                    row for row in hairy if _beard_rank(str(row.get("facial_hair", UNKNOWN))) == max_rank
                ]
                hair_strategy = "prefer_most_facial_hair_extreme"

    selected = selected_pool[: max(1, top_k)]

    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in selected:
        donor_id = str(row["donor_id"])
        if donor_id in seen_ids:
            continue
        seen_ids.add(donor_id)
        deduped.append(row)

    return deduped, {
        "nearest_tone_distance_lab": nearest,
        "tone_threshold_lab": tone_threshold,
        "excluded": incompatible,
        "compatible_count": len(compatible),
        "tone_filtered_count": len(tone_filtered),
        "hair_strategy": hair_strategy,
        "selected_pool_count": len(selected_pool),
    }


def _score_candidate(
    *,
    source_presentation: str,
    source_facial_hair: str,
    source_glasses: str,
    donor_presentation: str,
    donor_facial_hair: str,
    donor_glasses: str,
    donor_tone_distance_lab: float,
    swap_tone_distance_lab: float,
    original_vs_swapped_cosine: float,
    donor_vs_swapped_cosine: float,
    swap_detector_score: float,
) -> tuple[float, dict[str, float]]:
    if source_presentation != UNKNOWN and donor_presentation != source_presentation:
        return -1e9, {"presentation_penalty": -1e9}

    components = {
        "identity_alignment": donor_vs_swapped_cosine * 1.45,
        "identity_distance": -original_vs_swapped_cosine * 1.9,
        "donor_tone_penalty": -donor_tone_distance_lab * 0.03,
        "swap_tone_penalty": -swap_tone_distance_lab * 0.03,
        "detector_bonus": swap_detector_score * 0.15,
        "facial_hair_bonus": 0.0,
        "glasses_penalty": 0.0,
        "presentation_penalty": 0.0,
    }

    if source_facial_hair != UNKNOWN and donor_facial_hair != UNKNOWN:
        components["facial_hair_bonus"] += _facial_hair_change_score(source_facial_hair, donor_facial_hair)

    if source_glasses != UNKNOWN and donor_glasses != UNKNOWN and source_glasses != donor_glasses:
        components["glasses_penalty"] -= 0.2

    score = sum(components.values())
    return score, components


def _init_facefusion_runtime(facefusion_root: Path, *, facefusion_model: str) -> dict[str, Any]:
    root_str = str(facefusion_root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from facefusion import face_classifier, face_detector, face_landmarker, face_masker, face_recognizer, state_manager
    from facefusion.face_analyser import get_many_faces, get_one_face
    from facefusion.face_selector import sort_faces_by_order
    from facefusion.processors.modules.face_swapper import core as face_swapper

    state_manager.init_item("execution_device_ids", [0])
    state_manager.init_item("execution_providers", ["coreml", "cpu"])
    state_manager.init_item("execution_thread_count", 4)
    state_manager.init_item("download_providers", ["github", "huggingface"])
    state_manager.init_item("face_detector_model", "yunet")
    state_manager.init_item("face_detector_size", "640x640")
    state_manager.init_item("face_detector_margin", [0, 0, 0, 0])
    state_manager.init_item("face_detector_score", 0.35)
    state_manager.init_item("face_detector_angles", [0])
    state_manager.init_item("face_landmarker_model", "2dfan4")
    state_manager.init_item("face_landmarker_score", 0.5)
    state_manager.init_item("face_selector_mode", "one")
    state_manager.init_item("face_selector_order", "large-small")
    state_manager.init_item("face_selector_gender", None)
    state_manager.init_item("face_selector_race", None)
    state_manager.init_item("face_selector_age_start", None)
    state_manager.init_item("face_selector_age_end", None)
    state_manager.init_item("reference_face_position", 0)
    state_manager.init_item("reference_face_distance", 0.3)
    state_manager.init_item("face_mask_types", ["box"])
    state_manager.init_item("face_mask_blur", 0.1)
    state_manager.init_item("face_mask_padding", [8, 8, 8, 8])
    state_manager.init_item("face_mask_areas", [])
    state_manager.init_item("face_mask_regions", [])
    state_manager.init_item("face_occluder_model", "xseg_1")
    state_manager.init_item("face_parser_model", "bisenet_resnet_34")
    state_manager.init_item("face_swapper_model", facefusion_model)
    state_manager.init_item("face_swapper_pixel_boost", "256x256")
    state_manager.init_item("face_swapper_weight", 1.0)
    state_manager.init_item("video_memory_strategy", "tolerant")
    state_manager.init_item("system_memory_limit", 0)
    state_manager.init_item("source_paths", [])

    face_detector.pre_check()
    face_recognizer.pre_check()
    face_classifier.pre_check()
    face_landmarker.pre_check()
    face_masker.pre_check()
    face_swapper.pre_check()

    return {
        "state_manager": state_manager,
        "get_many_faces": get_many_faces,
        "get_one_face": get_one_face,
        "sort_faces_by_order": sort_faces_by_order,
        "face_swapper": face_swapper,
    }


def _read_video_frame(video_path: Path, frame_number: int) -> Any:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")
    try:
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        target_frame = max(0, min(frame_number, max(0, total_frames - 1)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok, frame = capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"Failed to read frame {frame_number} from {video_path}")
        return frame
    finally:
        capture.release()


def _extract_primary_face(frame: Any, *, runtime: dict[str, Any]) -> Any | None:
    faces = runtime["get_many_faces"]([frame])
    faces = runtime["sort_faces_by_order"](faces, "large-small")
    return runtime["get_one_face"](faces)


def _mean_lab_for_bounding_box(frame: Any, bounding_box: list[float]) -> list[float]:
    import cv2

    x1, y1, x2, y2 = [int(round(value)) for value in bounding_box]
    x1 = max(0, min(x1, frame.shape[1] - 2))
    y1 = max(0, min(y1, frame.shape[0] - 2))
    x2 = max(x1 + 2, min(x2, frame.shape[1]))
    y2 = max(y1 + 2, min(y2, frame.shape[0]))
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        roi = frame
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
    mean = lab.reshape(-1, 3).mean(axis=0)
    return [float(value) for value in mean.tolist()]


def _swap_target_frame(*, runtime: dict[str, Any], donor_frame: Any, donor_path: Path, target_frame: Any) -> Any:
    import numpy as np

    runtime["state_manager"].set_item("source_paths", [str(donor_path)])
    swapped_frame, _ = runtime["face_swapper"].process_frame(
        {
            "reference_vision_frame": target_frame,
            "source_vision_frames": [donor_frame],
            "target_vision_frame": target_frame,
            "temp_vision_frame": target_frame.copy(),
            "temp_vision_mask": np.ones(target_frame.shape[:2], dtype=np.float32),
        }
    )
    return swapped_frame


def _load_source_snapshots(
    *,
    target_video: Path,
    track: dict[str, Any],
    representative_frames: int,
    runtime: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    frames = list(track.get("frames", []))
    indices = select_representative_frame_indices(track, count=representative_frames)
    if not indices:
        import cv2

        capture = cv2.VideoCapture(str(target_video))
        total_frames = 0
        if capture.isOpened():
            total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        capture.release()
        indices = _fallback_frame_indices(total_frames, count=representative_frames)

    snapshots: list[dict[str, Any]] = []
    for frame_index in indices:
        frame = _read_video_frame(target_video, frame_index)
        face = _extract_primary_face(frame, runtime=runtime)
        if face is None:
            continue
        snapshots.append(
            {
                "frame_index": frame_index,
                "frame": frame,
                "embedding_norm": [float(value) for value in face.embedding_norm.tolist()],
                "detector_score": float(face.score_set.get("detector", 0.0)),
                "bounding_box": [float(value) for value in face.bounding_box.tolist()],
                "tone_lab": _mean_lab_for_bounding_box(frame, face.bounding_box.tolist()),
                "presentation": _presentation_from_gender(getattr(face, "gender", None)),
                "facial_hair": _infer_facial_hair_label(frame, face.bounding_box.tolist()),
                "glasses": _infer_glasses_label(frame, face.bounding_box.tolist()),
                "track_face_prob": float(frames[frame_index].get("face_prob", 0.0) or 0.0) if 0 <= frame_index < len(frames) else 0.0,
            }
        )
    if not snapshots:
        raise RuntimeError("Failed to extract any valid representative faces from the target crop.")
    timings = {
        "representative_frame_selection_seconds": time.perf_counter() - started,
    }
    return snapshots, timings


def _summarize_source_attributes(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    tone_vectors = [snapshot["tone_lab"] for snapshot in snapshots]
    source_lab = [
        float(sum(vector[index] for vector in tone_vectors) / len(tone_vectors))
        for index in range(3)
    ]
    return {
        "presentation": _majority_label([str(snapshot["presentation"]) for snapshot in snapshots]),
        "facial_hair": _majority_label([str(snapshot["facial_hair"]) for snapshot in snapshots]),
        "glasses": _majority_label([str(snapshot["glasses"]) for snapshot in snapshots]),
        "tone_lab": source_lab,
        "representative_frames": [int(snapshot["frame_index"]) for snapshot in snapshots],
    }


def _score_donor_candidates(
    *,
    runtime: dict[str, Any],
    donor_candidates: list[dict[str, Any]],
    source_snapshots: list[dict[str, Any]],
    source_attributes: dict[str, Any],
) -> list[dict[str, Any]]:
    import cv2

    results: list[dict[str, Any]] = []
    for donor in donor_candidates:
        donor_path = Path(donor["image_path"])
        donor_frame = cv2.imread(str(donor_path))
        if donor_frame is None:
            continue
        donor_face = _extract_primary_face(donor_frame, runtime=runtime)
        if donor_face is None:
            continue
        donor_embedding = [float(value) for value in donor_face.embedding_norm.tolist()]
        donor_tone = list(donor.get("tone_lab") or _mean_lab_for_bounding_box(donor_frame, donor_face.bounding_box.tolist()))
        donor_started = time.perf_counter()
        frame_scores: list[dict[str, Any]] = []
        for source_snapshot in source_snapshots:
            swapped_frame = _swap_target_frame(
                runtime=runtime,
                donor_frame=donor_frame,
                donor_path=donor_path,
                target_frame=source_snapshot["frame"],
            )
            swapped_face = _extract_primary_face(swapped_frame, runtime=runtime)
            if swapped_face is None:
                continue
            swapped_tone = _mean_lab_for_bounding_box(swapped_frame, swapped_face.bounding_box.tolist())
            frame_scores.append(
                {
                    "frame_index": int(source_snapshot["frame_index"]),
                    "original_vs_swapped_cosine": _cosine_similarity(
                        source_snapshot["embedding_norm"],
                        [float(value) for value in swapped_face.embedding_norm.tolist()],
                    ),
                    "donor_vs_swapped_cosine": _cosine_similarity(
                        donor_embedding,
                        [float(value) for value in swapped_face.embedding_norm.tolist()],
                    ),
                    "swap_tone_distance_lab": _lab_distance(source_snapshot["tone_lab"], swapped_tone),
                    "swap_detector_score": float(swapped_face.score_set.get("detector", 0.0)),
                }
            )
        if not frame_scores:
            continue
        frame_count = len(frame_scores)
        averaged = {
            "original_vs_swapped_cosine": sum(item["original_vs_swapped_cosine"] for item in frame_scores) / frame_count,
            "donor_vs_swapped_cosine": sum(item["donor_vs_swapped_cosine"] for item in frame_scores) / frame_count,
            "swap_tone_distance_lab": sum(item["swap_tone_distance_lab"] for item in frame_scores) / frame_count,
            "swap_detector_score": sum(item["swap_detector_score"] for item in frame_scores) / frame_count,
        }
        ranking_score, components = _score_candidate(
            source_presentation=str(source_attributes["presentation"]),
            source_facial_hair=str(source_attributes["facial_hair"]),
            source_glasses=str(source_attributes["glasses"]),
            donor_presentation=str(donor.get("presentation", UNKNOWN)),
            donor_facial_hair=str(donor.get("facial_hair", UNKNOWN)),
            donor_glasses=str(donor.get("glasses", UNKNOWN)),
            donor_tone_distance_lab=float(donor["donor_tone_distance_lab"]),
            swap_tone_distance_lab=float(averaged["swap_tone_distance_lab"]),
            original_vs_swapped_cosine=float(averaged["original_vs_swapped_cosine"]),
            donor_vs_swapped_cosine=float(averaged["donor_vs_swapped_cosine"]),
            swap_detector_score=float(averaged["swap_detector_score"]),
        )
        results.append(
            {
                "donor_id": donor["donor_id"],
                "donor_name": donor.get("donor_name", donor["donor_id"]),
                "donor_image": str(donor_path),
                "presentation": donor.get("presentation", UNKNOWN),
                "facial_hair": donor.get("facial_hair", UNKNOWN),
                "glasses": donor.get("glasses", UNKNOWN),
                "donor_tone_distance_lab": float(donor["donor_tone_distance_lab"]),
                "original_vs_swapped_cosine": float(averaged["original_vs_swapped_cosine"]),
                "donor_vs_swapped_cosine": float(averaged["donor_vs_swapped_cosine"]),
                "swap_tone_distance_lab": float(averaged["swap_tone_distance_lab"]),
                "swap_detector_score": float(averaged["swap_detector_score"]),
                "frame_scores": frame_scores,
                "ranking_score": float(ranking_score),
                "ranking_components": components,
                "timings": {
                    "image_scoring_seconds": time.perf_counter() - donor_started,
                },
            }
        )
    return results


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    overall_started = time.perf_counter()
    target_video = Path(args.target_video).expanduser().resolve()
    track_metadata = Path(args.track_metadata).expanduser().resolve() if args.track_metadata else None
    donor_bank_dir = Path(args.donor_bank_dir).expanduser().resolve()
    facefusion_root = Path(args.facefusion_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not target_video.exists():
        raise SystemExit(f"Missing target video: {target_video}")
    if not donor_bank_dir.exists():
        raise SystemExit(f"Missing donor bank dir: {donor_bank_dir}")

    timings: dict[str, float] = {}

    manifest_started = time.perf_counter()
    donor_candidates = _load_donor_manifest(donor_bank_dir, include_preview=args.include_preview)
    timings["donor_manifest_load_seconds"] = time.perf_counter() - manifest_started
    if not donor_candidates:
        raise SystemExit(f"No donor images found under {donor_bank_dir}")

    runtime_started = time.perf_counter()
    runtime = _init_facefusion_runtime(facefusion_root, facefusion_model=args.facefusion_model)
    timings["facefusion_runtime_init_seconds"] = time.perf_counter() - runtime_started

    track = _load_track(track_metadata)
    source_snapshots, snapshot_timings = _load_source_snapshots(
        target_video=target_video,
        track=track,
        representative_frames=max(1, args.representative_frames),
        runtime=runtime,
    )
    timings.update(snapshot_timings)
    source_attributes = _summarize_source_attributes(source_snapshots)

    prefilter_started = time.perf_counter()
    selected_candidates, prefilter_summary = _select_prefiltered_candidates(
        donor_candidates,
        source_lab=list(source_attributes["tone_lab"]),
        source_presentation=str(source_attributes["presentation"]),
        source_facial_hair=str(source_attributes["facial_hair"]),
        source_glasses=str(source_attributes["glasses"]),
        top_k=max(1, args.top_k),
        tone_margin_lab=float(args.tone_margin_lab),
    )
    timings["prefilter_seconds"] = time.perf_counter() - prefilter_started

    scoring_started = time.perf_counter()
    results = _score_donor_candidates(
        runtime=runtime,
        donor_candidates=selected_candidates,
        source_snapshots=source_snapshots,
        source_attributes=source_attributes,
    )
    timings["candidate_scoring_seconds"] = time.perf_counter() - scoring_started
    timings["total_selection_seconds"] = time.perf_counter() - overall_started

    runtime["face_swapper"].post_process()

    if not results:
        raise SystemExit("Auto donor selection could not produce any valid swap candidates.")

    results.sort(key=lambda row: float(row["ranking_score"]), reverse=True)
    selected = results[0]
    report = {
        "target_video": str(target_video),
        "track_metadata": str(track_metadata) if track_metadata else None,
        "top_k": max(1, args.top_k),
        "tone_margin_lab": float(args.tone_margin_lab),
        "representative_frames": list(source_attributes["representative_frames"]),
        "source_attributes": source_attributes,
        "prefilter_summary": prefilter_summary,
        "selected_donor_image": selected["donor_image"],
        "selected_donor_id": selected["donor_id"],
        "timings": timings,
        "results": results,
    }
    report_path = output_dir / "auto-select-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "selected_donor_image": selected["donor_image"],
                "report_path": str(report_path),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
