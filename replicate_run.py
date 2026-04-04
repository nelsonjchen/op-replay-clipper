from __future__ import annotations

import argparse
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import replicate
from core import route_inputs

DEFAULT_MODEL = "nelsonjchen/op-replay-clipper-beta"
DEFAULT_URL = "https://connect.comma.ai/5beb9b58bd12b691/0000010a--a51155e496/90/105"
DEFAULT_OUTPUT = Path("./shared/replicate-run-output.mp4")
_ANONYMIZATION_PROFILE_LABEL_ALIASES = {
    "driver unchanged, passenger pixelize": "driver unchanged, passenger hidden",
    "driver face swap, passenger pixelize": "driver face swap, passenger hidden",
}


def normalize_anonymization_profile_label(value: str) -> str:
    cleaned = value.strip().lower()
    return _ANONYMIZATION_PROFILE_LABEL_ALIASES.get(cleaned, cleaned)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the hosted Replicate clipper and save the returned video locally.")
    parser.add_argument("--model", default="", help="Replicate model ref. Defaults to the latest beta alias when omitted.")
    parser.add_argument("--url", default=DEFAULT_URL, help="connect.comma.ai clip URL.")
    parser.add_argument(
        "--render-type",
        choices=["ui", "ui-alt", "driver-debug", "forward", "wide", "driver", "360", "forward_upon_wide", "360_forward_upon_wide"],
        default="ui",
        help="Clip render type.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Where to write the returned MP4.")
    parser.add_argument("--smear-amount", type=int, default=3, help="UI smear amount.")
    parser.add_argument("--file-size", type=int, default=9, help="Target output size in MB.")
    parser.add_argument("--file-format", choices=["auto", "h264", "hevc"], default="auto")
    parser.add_argument("--jwt-token", default="", help="Optional comma JWT token for private routes.")
    parser.add_argument(
        "--anonymization-profile",
        choices=[
            "none",
            "driver unchanged, passenger hidden",
            "driver unchanged, passenger face swap",
            "driver face swap, passenger hidden",
            "driver face swap, passenger face swap",
        ],
        type=normalize_anonymization_profile_label,
        default="none",
        help="Seat anonymization strategy for driver-camera renders on the hosted model.",
    )
    parser.add_argument(
        "--passenger-redaction-style",
        choices=["blur", "silhouette"],
        default="blur",
        help="How to hide the passenger when the selected anonymization profile uses passenger hidden mode.",
    )
    parser.add_argument("--notes", default="", help="Optional notes string.")
    return parser


def validate_connect_url(url: str) -> str:
    try:
        route_inputs.validate_connect_url(url)
        return url
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def build_input(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "notes": args.notes,
        "route": encode_replicate_route_input(args.url),
        "fileSize": args.file_size,
        "jwtToken": args.jwt_token,
        "fileFormat": args.file_format,
        "renderType": args.render_type,
        "smearAmount": args.smear_amount,
        "anonymizationProfile": args.anonymization_profile,
        "passengerRedactionStyle": args.passenger_redaction_style,
    }


def require_api_token() -> str:
    load_dotenv()
    token = os.environ.get("REPLICATE_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("REPLICATE_API_TOKEN is not set. Put it in .env or export it before running this script.")
    return token


def encode_replicate_route_input(url: str) -> str:
    return route_inputs.validate_connect_url(url)


def resolve_model(model: str) -> tuple[str, bool]:
    cleaned = model.strip()
    if cleaned:
        return cleaned, True
    return DEFAULT_MODEL, False


def unwrap_file_output(output: Any) -> Any:
    if hasattr(output, "read"):
        return output
    if isinstance(output, Iterable) and not isinstance(output, (str, bytes, dict)):
        items = list(output)
        if len(items) != 1:
            raise ValueError(f"Expected a single file output, got {len(items)} items.")
        return unwrap_file_output(items[0])
    raise TypeError(f"Expected a file-like Replicate output, got {type(output).__name__}.")


def save_file_output(output: Any, output_path: Path) -> Path:
    file_output = unwrap_file_output(output)
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(file_output.read())
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    require_api_token()
    args.url = validate_connect_url(args.url)
    args.model, model_was_explicit = resolve_model(args.model)
    payload = build_input(args)

    if not model_was_explicit:
        print(f"Warning: --model was not set; using latest beta alias {args.model}", flush=True)
    print(f"Running {args.model}", flush=True)
    print(f"Saving output to {args.output}", flush=True)
    output = replicate.run(args.model, input=payload)

    output_url = getattr(output, "url", None)
    if output_url:
        print(f"Remote output URL: {output_url}", flush=True)

    written_path = save_file_output(output, args.output)
    print(f"Wrote output to {written_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
