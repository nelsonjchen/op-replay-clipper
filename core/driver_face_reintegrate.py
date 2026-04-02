from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Composite a swapped face-crop video back into the full driver clip.")
    parser.add_argument("--sample-dir", required=True)
    parser.add_argument("--swapped-crop", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--mask-box", choices=("padded_box", "raw_box", "crop_rect"), default="padded_box")
    parser.add_argument("--mask-expand", type=float, default=1.12)
    parser.add_argument("--feather-ratio", type=float, default=0.18)
    parser.add_argument("--banner-text", default="DRIVER FACE ANONYMIZED")
    return parser


def _box(frame_row: dict[str, object], key: str) -> tuple[int, int, int, int] | None:
    value = frame_row.get(key)
    if not isinstance(value, dict):
        return None
    return int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"])


def _pick_mask_box(frame_row: dict[str, object], preferred: str) -> tuple[int, int, int, int] | None:
    for key in (preferred, "padded_box", "raw_box", "crop_rect"):
        rect = _box(frame_row, key)
        if rect is not None:
            return rect
    return None


def _clamp_rect(rect: tuple[float, float, float, float], *, width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    x1 = max(0, min(width, int(round(x))))
    y1 = max(0, min(height, int(round(y))))
    x2 = max(x1, min(width, int(round(x + w))))
    y2 = max(y1, min(height, int(round(y + h))))
    return x1, y1, max(0, x2 - x1), max(0, y2 - y1)


def _expand_rect(rect: tuple[int, int, int, int], *, scale: float, bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    bx, by, bw, bh = bounds
    x, y, w, h = rect
    center_x = x + (w / 2.0)
    center_y = y + (h / 2.0)
    expanded_w = w * scale
    expanded_h = h * scale
    local_x = center_x - (expanded_w / 2.0) - bx
    local_y = center_y - (expanded_h / 2.0) - by
    return _clamp_rect((local_x, local_y, expanded_w, expanded_h), width=bw, height=bh)


def _project_to_crop(mask_rect: tuple[int, int, int, int], crop_rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    mx, my, mw, mh = mask_rect
    cx, cy, cw, ch = crop_rect
    return mx - cx, my - cy, mw, mh


def _mask_for_crop(
    crop_size: tuple[int, int],
    crop_rect: tuple[int, int, int, int],
    mask_rect_frame: tuple[int, int, int, int] | None,
    *,
    mask_expand: float,
    feather_ratio: float,
) -> np.ndarray:
    crop_w, crop_h = crop_size
    if mask_rect_frame is None:
        return np.ones((crop_h, crop_w), dtype=np.float32)

    local_rect = _project_to_crop(mask_rect_frame, crop_rect)
    expanded_local = _expand_rect(local_rect, scale=mask_expand, bounds=(0, 0, crop_w, crop_h))
    mx, my, mw, mh = expanded_local
    if mw <= 0 or mh <= 0:
        return np.ones((crop_h, crop_w), dtype=np.float32)

    mask = np.zeros((crop_h, crop_w), dtype=np.float32)
    cv2.rectangle(mask, (mx, my), (mx + mw, my + mh), 1.0, thickness=-1)
    blur_size = max(3, int(round(min(mw, mh) * feather_ratio)))
    if blur_size % 2 == 0:
        blur_size += 1
    if blur_size > 1:
        mask = cv2.GaussianBlur(mask, (blur_size, blur_size), 0)
    return np.clip(mask, 0.0, 1.0)


def _draw_banner(frame, text: str) -> None:
    if not text:
        return
    height, width = frame.shape[:2]
    pad_x = max(18, width // 50)
    pad_y = max(18, height // 40)
    font = cv2.FONT_HERSHEY_DUPLEX
    font_scale = max(0.75, min(1.6, width / 900.0))
    thickness = max(2, int(round(width / 640)))
    (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    box_x1 = pad_x
    box_y1 = pad_y
    box_x2 = min(width - pad_x, box_x1 + text_w + 28)
    box_y2 = min(height - pad_y, box_y1 + text_h + baseline + 26)
    cv2.rectangle(frame, (box_x1, box_y1), (box_x2, box_y2), (0, 235, 255), thickness=-1)
    cv2.rectangle(frame, (box_x1, box_y1), (box_x2, box_y2), (0, 0, 0), thickness=max(2, thickness))
    text_origin = (box_x1 + 14, box_y2 - baseline - 10)
    cv2.putText(frame, text, text_origin, font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)


def composite_sample(
    *,
    sample_dir: Path,
    swapped_crop_path: Path,
    output_path: Path,
    mask_box: str,
    mask_expand: float,
    feather_ratio: float,
    banner_text: str,
) -> Path:
    track_path = sample_dir / "face-track.json"
    source_path = sample_dir / "driver-source.mp4"
    manifest = json.loads(track_path.read_text())
    frame_rows = list(manifest["frames"])

    source_capture = cv2.VideoCapture(str(source_path))
    swapped_capture = cv2.VideoCapture(str(swapped_crop_path))
    if not source_capture.isOpened():
        raise RuntimeError(f"Failed to open source clip: {source_path}")
    if not swapped_capture.isOpened():
        raise RuntimeError(f"Failed to open swapped crop clip: {swapped_crop_path}")

    width = int(source_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(source_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(source_capture.get(cv2.CAP_PROP_FPS) or manifest.get("framerate") or 20.0)
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Failed to create output clip: {output_path}")

    try:
        for row in frame_rows:
            ok_source, source_frame = source_capture.read()
            ok_swap, swap_frame = swapped_capture.read()
            if not ok_source or not ok_swap:
                raise RuntimeError("Source and swapped crop videos must have matching frame counts")

            crop_rect = _box(row, "crop_rect")
            if crop_rect is None:
                _draw_banner(source_frame, banner_text)
                writer.write(source_frame)
                continue

            crop_x, crop_y, crop_w, crop_h = crop_rect
            if crop_w <= 0 or crop_h <= 0:
                _draw_banner(source_frame, banner_text)
                writer.write(source_frame)
                continue

            resized_swap = cv2.resize(swap_frame, (crop_w, crop_h), interpolation=cv2.INTER_LANCZOS4)
            mask_rect = _pick_mask_box(row, mask_box)
            alpha = _mask_for_crop(
                (crop_w, crop_h),
                crop_rect,
                mask_rect,
                mask_expand=mask_expand,
                feather_ratio=feather_ratio,
            )
            alpha = alpha[:, :, None]
            source_roi = source_frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w].astype(np.float32)
            swap_roi = resized_swap.astype(np.float32)
            blended = (alpha * swap_roi) + ((1.0 - alpha) * source_roi)
            source_frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w] = np.clip(blended, 0, 255).astype(np.uint8)
            _draw_banner(source_frame, banner_text)
            writer.write(source_frame)
    finally:
        source_capture.release()
        swapped_capture.release()
        writer.release()

    return output_path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    composite_sample(
        sample_dir=Path(args.sample_dir).resolve(),
        swapped_crop_path=Path(args.swapped_crop).resolve(),
        output_path=Path(args.output_path).resolve(),
        mask_box=args.mask_box,
        mask_expand=args.mask_expand,
        feather_ratio=args.feather_ratio,
        banner_text=args.banner_text,
    )
    print(Path(args.output_path).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
