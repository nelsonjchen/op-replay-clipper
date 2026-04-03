from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import textwrap
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

DEFAULT_RUNWARE_MODEL = "runware:106@1"
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
DEFAULT_STEPS = 24
DEFAULT_CFG_SCALE = 2.5
RUNWARE_API_URL = "https://api.runware.ai/v1"


@dataclass(frozen=True)
class DonorSpec:
    donor_id: str
    image: str
    label: str
    role: str
    presentation: str
    tone_band: str
    age_band: str
    facial_hair: str
    glasses: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a balanced driver face donor bank via Runware.")
    parser.add_argument("--spec", default="./assets/driver-face-donors/base-spec.json")
    parser.add_argument("--donor-bank-dir", default="./assets/driver-face-donors")
    parser.add_argument("--manifest", default="./assets/driver-face-donors/manifest.json")
    parser.add_argument("--contact-sheet", default="./assets/driver-face-donors/contact-sheet.png")
    parser.add_argument("--runware-model", default=DEFAULT_RUNWARE_MODEL)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    parser.add_argument("--cfg-scale", type=float, default=DEFAULT_CFG_SCALE)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--api-key")
    return parser


def _load_spec(path: Path) -> list[DonorSpec]:
    payload = json.loads(path.read_text())
    specs: list[DonorSpec] = []
    for role_key, role_name in (("base_donors", "base"), ("variant_donors", "variant")):
        for row in payload.get(role_key, []):
            specs.append(
                DonorSpec(
                    donor_id=str(row["id"]),
                    image=str(row["image"]),
                    label=str(row["label"]),
                    role=role_name,
                    presentation=str(row["presentation"]),
                    tone_band=str(row["tone_band"]),
                    age_band=str(row["age_band"]),
                    facial_hair=str(row.get("facial_hair", "none")),
                    glasses=str(row.get("glasses", "no")),
                )
            )
    return specs


def _seed_for_donor(donor_id: str) -> int:
    digest = hashlib.sha256(donor_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _tone_phrase(tone_band: str) -> str:
    return {
        "light": "light skin tone",
        "medium": "medium olive-to-brown skin tone",
        "dark": "dark brown skin tone",
    }[tone_band]


def _age_phrase(age_band: str) -> str:
    return {
        "younger": "younger adult",
        "older": "older adult with subtle mature features",
    }[age_band]


def _presentation_phrase(presentation: str) -> tuple[str, str]:
    if presentation == "masc":
        return "man", "clean-shaven"
    if presentation == "fem":
        return "woman", "no facial hair"
    raise ValueError(f"Unsupported presentation: {presentation}")


def _prompt_for_spec(spec: DonorSpec) -> str:
    noun, hair_phrase = _presentation_phrase(spec.presentation)
    glasses_phrase = "thin understated eyeglasses" if spec.glasses == "yes" else "no glasses"
    return textwrap.dedent(
        f"""
        Photorealistic studio portrait of a {noun}, { _age_phrase(spec.age_band) }, { _tone_phrase(spec.tone_band) }.
        Head and shoulders only, front-facing, centered, neutral expression, direct eye contact, realistic skin texture.
        Natural hairstyle, soft even studio lighting, plain neutral gray background, documentary portrait feel.
        {hair_phrase}, {glasses_phrase}, no hat, no jewelry, no watermark, no text, no dramatic makeup, no extreme shadows.
        """
    ).strip().replace("\n", " ")


def _prompt_variants_for_spec(spec: DonorSpec) -> list[str]:
    noun, hair_phrase = _presentation_phrase(spec.presentation)
    glasses_phrase = "wearing thin understated eyeglasses" if spec.glasses == "yes" else "no glasses"
    return [
        _prompt_for_spec(spec),
        (
            f"Photorealistic studio portrait of a {noun}, {_tone_phrase(spec.tone_band)}, {_age_phrase(spec.age_band)}. "
            f"Head and shoulders, front-facing, centered, neutral expression, plain gray background, soft studio light, "
            f"{hair_phrase}, {glasses_phrase}, no hat, no jewelry."
        ),
        (
            f"Photorealistic head-and-shoulders portrait of a {noun} with {_tone_phrase(spec.tone_band)}, "
            f"neutral expression, centered, plain gray background, {glasses_phrase}."
        ),
    ]


def _generate_image_bytes(*, api_key: str, model: str, spec: DonorSpec, width: int, height: int, steps: int, cfg_scale: float) -> bytes:
    last_error: str | None = None
    for prompt in _prompt_variants_for_spec(spec):
        payload = [
            {
                "taskType": "imageInference",
                "taskUUID": str(uuid.uuid4()),
                "model": model,
                "positivePrompt": prompt,
                "negativePrompt": (
                    "sunglasses, hat, text, watermark, extra face, side profile, smile, open mouth, heavy shadows, stylized illustration, cartoon"
                    if spec.glasses == "yes"
                    else "glasses, sunglasses, hat, text, watermark, extra face, side profile, smile, open mouth, heavy shadows, stylized illustration, cartoon"
                ),
                "width": width,
                "height": height,
                "numberResults": 1,
                "outputType": "URL",
                "steps": steps,
                "CFGScale": cfg_scale,
                "seed": _seed_for_donor(spec.donor_id),
            }
        ]
        response = requests.post(
            RUNWARE_API_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=240,
        )
        if not response.ok:
            last_error = response.text
            if "invalidBFLContent" in response.text:
                continue
            raise RuntimeError(
                f"Runware request failed for {spec.donor_id} with HTTP {response.status_code}: {response.text}"
            )
        payload = response.json()
        data = payload.get("data", [])
        if not data:
            last_error = json.dumps(payload)
            continue
        image_url = data[0]["imageURL"]
        with urlopen(image_url) as image_response:
            return image_response.read()
    raise RuntimeError(f"Runware request failed for {spec.donor_id} after prompt fallbacks: {last_error}")


def _cheek_patch_lab(image_path: Path) -> list[float]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"Failed to load generated donor image: {image_path}")
    image_lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    height, width = image_lab.shape[:2]
    patches = [
        image_lab[int(height * 0.38):int(height * 0.55), int(width * 0.28):int(width * 0.40)],
        image_lab[int(height * 0.38):int(height * 0.55), int(width * 0.60):int(width * 0.72)],
    ]
    pixels = [patch.reshape(-1, 3) for patch in patches if patch.size > 0]
    if not pixels:
        pixels = [image_lab.reshape(-1, 3)]
    stacked = np.concatenate(pixels, axis=0)
    mean = stacked.mean(axis=0)
    return [round(float(value), 2) for value in mean.tolist()]


def _load_existing_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    return list(payload.get("donors", []))


def _merge_manifest(existing: list[dict[str, Any]], generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    generated_by_id = {row["id"]: row for row in generated}
    merged: list[dict[str, Any]] = []
    for row in existing:
        donor_id = str(row["id"])
        if donor_id in generated_by_id:
            continue
        if "role" not in row:
            row = {
                **row,
                "role": "variant",
                "source": "legacy",
            }
        merged.append(row)
    merged.extend(generated)
    merged.sort(key=lambda row: (row.get("role") != "base", row["id"]))
    return merged


def _build_contact_sheet(manifest_rows: list[dict[str, Any]], donor_bank_dir: Path, output_path: Path) -> None:
    rows = []
    for row in manifest_rows:
        image_path = donor_bank_dir / row["image"]
        if image_path.exists():
            rows.append((row["label"], image_path))
    if not rows:
        return

    thumb_size = (256, 256)
    columns = 3
    gutter = 16
    label_height = 52
    sheet_rows = (len(rows) + columns - 1) // columns
    width = (thumb_size[0] * columns) + (gutter * (columns + 1))
    height = (thumb_size[1] + label_height) * sheet_rows + (gutter * (sheet_rows + 1))
    canvas = Image.new("RGB", (width, height), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    for index, (label, image_path) in enumerate(rows):
        row = index // columns
        col = index % columns
        x = gutter + col * (thumb_size[0] + gutter)
        y = gutter + row * (thumb_size[1] + label_height + gutter)
        image = Image.open(image_path).convert("RGB")
        image.thumbnail(thumb_size, Image.Resampling.LANCZOS)
        image_x = x + (thumb_size[0] - image.width) // 2
        image_y = y + (thumb_size[1] - image.height) // 2
        canvas.paste(image, (image_x, image_y))
        draw.text((x, y + thumb_size[1] + 8), label, fill=(240, 240, 240), font=font)

    canvas.save(output_path)


def main() -> int:
    args = build_parser().parse_args()
    donor_bank_dir = Path(args.donor_bank_dir).expanduser().resolve()
    donor_bank_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest).expanduser().resolve()
    spec_path = Path(args.spec).expanduser().resolve()
    contact_sheet_path = Path(args.contact_sheet).expanduser().resolve()
    api_key = args.api_key or os.environ.get("RUNWARE_API_KEY")
    if not api_key:
        raise SystemExit("Missing RUNWARE_API_KEY / --api-key")

    specs = _load_spec(spec_path)
    generated_rows: list[dict[str, Any]] = []

    for spec in specs:
        image_path = donor_bank_dir / spec.image
        print(f"Generating {spec.donor_id} -> {image_path.name}", flush=True)
        if image_path.exists() and args.skip_existing and not args.overwrite:
            tone_lab = _cheek_patch_lab(image_path)
        else:
            image_bytes = _generate_image_bytes(
                api_key=api_key,
                model=args.runware_model,
                spec=spec,
                width=args.width,
                height=args.height,
                steps=args.steps,
                cfg_scale=args.cfg_scale,
            )
            image_path.write_bytes(image_bytes)
            tone_lab = _cheek_patch_lab(image_path)

        generated_rows.append(
            {
                "id": spec.donor_id,
                "image": spec.image,
                "label": spec.label,
                "presentation": spec.presentation,
                "tone_band": spec.tone_band,
                "age_band": spec.age_band,
                "facial_hair": spec.facial_hair,
                "glasses": spec.glasses,
                "tone_lab": tone_lab,
                "role": spec.role,
                "source": "runware_flux_kontext_dev",
                "seed": _seed_for_donor(spec.donor_id),
            }
        )

    merged_rows = _merge_manifest(_load_existing_manifest(manifest_path), generated_rows)
    manifest_path.write_text(json.dumps({"donors": merged_rows}, indent=2) + "\n")
    _build_contact_sheet(merged_rows, donor_bank_dir, contact_sheet_path)
    generated_base = sum(1 for row in generated_rows if row.get("role") == "base")
    generated_variant = sum(1 for row in generated_rows if row.get("role") == "variant")
    print(f"Wrote manifest: {manifest_path}")
    print(f"Wrote contact sheet: {contact_sheet_path}")
    print(
        f"Generated/updated {generated_base} base donors and {generated_variant} variants in {donor_bank_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
