from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from replicate_run import (
    require_api_token,
    run_prediction_with_retries,
    save_file_output,
)

DEFAULT_MODEL = "nelsonjchen/op-replay-clipper-rfdetr-repro-beta"
DEFAULT_INPUT = Path("./shared/rf-detr-repro-inputs/tiny-clip.mp4")
DEFAULT_OUTPUT = Path("./shared/rf-detr-repro-hosted-artifacts.zip")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the hosted RF-DETR-only repro model and save the artifact bundle locally.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Replicate model ref.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Local image or short video to upload.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Where to write the returned artifact bundle.")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda", "mps"], default="auto")
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument("--max-frames", type=int, default=8)
    parser.add_argument("--crop-mode", choices=["full", "left_half", "right_half", "center_square"], default="full")
    parser.add_argument("--write-overlay-video", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--retries", type=int, default=2)
    return parser


def build_input(args: argparse.Namespace, media_handle) -> dict[str, Any]:
    return {
        "media": media_handle,
        "device": args.device,
        "threshold": args.threshold,
        "maxFrames": args.max_frames,
        "cropMode": args.crop_mode,
        "writeOverlayVideo": args.write_overlay_video,
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    require_api_token()
    input_path = args.input.expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input path does not exist: {input_path}")
    print(f"Running {args.model}", flush=True)
    print(f"Uploading {input_path}", flush=True)
    with input_path.open("rb") as handle:
        payload = build_input(args, handle)
        prediction = run_prediction_with_retries(
            args.model,
            payload,
            retries=args.retries,
            poll_interval_seconds=args.poll_interval,
            timeout_seconds=args.timeout_seconds,
        )
    written_path = save_file_output(prediction.output, args.output)
    print(f"Wrote output to {written_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
