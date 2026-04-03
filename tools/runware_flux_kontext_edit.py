#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from pathlib import Path

import requests
from PIL import Image


RUNWARE_API_URL = "https://api.runware.ai/v1"
DEFAULT_MODEL = "runware:106@1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Edit a donor image with Runware FLUX.1 Kontext [dev].")
    parser.add_argument("input_image", help="Path to the input donor image.")
    parser.add_argument("output_image", help="Path to save the edited output image.")
    parser.add_argument("prompt", help="Edit instruction for FLUX.1 Kontext [dev].")
    parser.add_argument("--api-key", default="", help="Runware API key. Defaults to RUNWARE_API_KEY env var.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Runware model identifier.")
    parser.add_argument("--strength", type=float, default=0.35, help="Image-to-image strength.")
    parser.add_argument("--steps", type=int, default=28, help="Inference steps.")
    parser.add_argument("--guidance-scale", type=float, default=2.5, help="Prompt guidance scale.")
    parser.add_argument("--negative-prompt", default="", help="Optional negative prompt.")
    parser.add_argument("--width", type=int, default=0, help="Override output width. Defaults to input width.")
    parser.add_argument("--height", type=int, default=0, help="Override output height. Defaults to input height.")
    parser.add_argument("--seed", type=int, default=0, help="Optional explicit seed.")
    parser.add_argument("--timeout", type=int, default=300, help="HTTP timeout in seconds.")
    return parser


def _read_image_data_uri(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".") or "png"
    media_type = "jpeg" if suffix == "jpg" else suffix
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{media_type};base64,{encoded}"


def _post_tasks(api_key: str, tasks: list[dict[str, object]], *, timeout: int) -> dict[str, object]:
    response = requests.post(
        RUNWARE_API_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json=tasks,
        timeout=timeout,
    )
    if not response.ok:
        details = response.text
        raise RuntimeError(f"Runware request failed with HTTP {response.status_code}: {details}")
    payload = response.json()
    if "errors" in payload:
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    if "error" in payload:
        raise RuntimeError(json.dumps(payload["error"], indent=2))
    if "data" not in payload:
        raise RuntimeError(f"Runware response missing data: {json.dumps(payload, indent=2)}")
    return payload


def _normalize_dimension(value: int) -> int:
    clamped = max(128, min(2048, value))
    return max(128, (clamped // 64) * 64)


def _uploaded_image_uuid(api_key: str, *, input_image: Path, timeout: int) -> str:
    task_uuid = str(uuid.uuid4())
    payload = _post_tasks(
        api_key,
        [
            {
                "taskType": "imageUpload",
                "taskUUID": task_uuid,
                "image": _read_image_data_uri(input_image),
            }
        ],
        timeout=timeout,
    )
    for item in payload["data"]:
        if item.get("taskType") == "imageUpload" and item.get("taskUUID") == task_uuid:
            image_uuid = item.get("imageUUID")
            if image_uuid:
                return str(image_uuid)
    raise RuntimeError(f"Runware upload response missing imageUUID: {json.dumps(payload, indent=2)}")


def _inference_image_url(
    api_key: str,
    *,
    seed_image_uuid: str,
    prompt: str,
    model: str,
    width: int,
    height: int,
    strength: float,
    steps: int,
    guidance_scale: float,
    negative_prompt: str,
    seed: int,
    timeout: int,
) -> str:
    task_uuid = str(uuid.uuid4())
    task: dict[str, object] = {
        "taskType": "imageInference",
        "taskUUID": task_uuid,
        "model": model,
        "positivePrompt": prompt,
        "seedImage": seed_image_uuid,
        "strength": strength,
        "steps": steps,
        "width": width,
        "height": height,
        "numberResults": 1,
        "outputType": "URL",
        "CFGScale": guidance_scale,
    }
    if negative_prompt:
        task["negativePrompt"] = negative_prompt
    if seed:
        task["seed"] = seed

    payload = _post_tasks(api_key, [task], timeout=timeout)
    for item in payload["data"]:
        if item.get("taskType") == "imageInference" and item.get("taskUUID") == task_uuid:
            image_url = item.get("imageURL")
            if image_url:
                return str(image_url)
    raise RuntimeError(f"Runware inference response missing imageURL: {json.dumps(payload, indent=2)}")


def _download_image(url: str, output_path: Path, *, timeout: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    output_path.write_bytes(response.content)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    api_key = args.api_key or os.environ.get("RUNWARE_API_KEY", "")
    if not api_key:
        print("Missing Runware API key. Pass --api-key or set RUNWARE_API_KEY.", file=sys.stderr)
        return 2

    input_image = Path(args.input_image).expanduser().resolve()
    output_image = Path(args.output_image).expanduser().resolve()
    if not input_image.exists():
        print(f"Input image not found: {input_image}", file=sys.stderr)
        return 2

    with Image.open(input_image) as image:
        width = _normalize_dimension(args.width or image.width)
        height = _normalize_dimension(args.height or image.height)

    seed_image_uuid = _uploaded_image_uuid(api_key, input_image=input_image, timeout=args.timeout)
    image_url = _inference_image_url(
        api_key,
        seed_image_uuid=seed_image_uuid,
        prompt=args.prompt,
        model=args.model,
        width=width,
        height=height,
        strength=args.strength,
        steps=args.steps,
        guidance_scale=args.guidance_scale,
        negative_prompt=args.negative_prompt,
        seed=args.seed,
        timeout=args.timeout,
    )
    _download_image(image_url, output_image, timeout=args.timeout)

    print(json.dumps({"output_image": str(output_image), "image_url": image_url, "seed_image_uuid": seed_image_uuid}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
