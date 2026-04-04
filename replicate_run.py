from __future__ import annotations

import argparse
import os
import time
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
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between hosted prediction status polls.")
    parser.add_argument("--timeout-seconds", type=float, default=1800.0, help="Maximum time to wait for the hosted prediction before failing.")
    parser.add_argument("--retries", type=int, default=2, help="How many times to retry transient hosted prediction failures.")
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


def create_prediction(model_ref: str, payload: dict[str, Any]) -> Any:
    if ":" in model_ref:
        _, version = model_ref.rsplit(":", 1)
        return replicate.predictions.create(version=version, input=payload)
    return replicate.predictions.create(model=model_ref, input=payload)


def wait_for_prediction(prediction: Any, poll_interval_seconds: float = 5.0, timeout_seconds: float | None = 1800.0) -> Any:
    terminal_statuses = {"succeeded", "failed", "canceled"}
    last_status: str | None = None
    last_logs = ""
    started_at = time.monotonic()

    web_url = getattr(getattr(prediction, "urls", None), "web", None)
    if web_url:
        print(f"Prediction URL: {web_url}", flush=True)

    while prediction.status not in terminal_statuses:
        if prediction.status != last_status:
            print(f"Status: {prediction.status}", flush=True)
            last_status = prediction.status
        if timeout_seconds is not None and time.monotonic() - started_at > timeout_seconds:
            raise SystemExit(f"Timed out waiting for Replicate prediction after {timeout_seconds:.0f}s.")
        time.sleep(poll_interval_seconds)
        prediction.reload()
        logs = getattr(prediction, "logs", "") or ""
        if len(logs) > len(last_logs):
            print(logs[len(last_logs):], end="", flush=True)
            last_logs = logs

    logs = getattr(prediction, "logs", "") or ""
    if len(logs) > len(last_logs):
        print(logs[len(last_logs):], end="", flush=True)

    print(f"Final status: {prediction.status}", flush=True)
    if prediction.status != "succeeded":
        error = getattr(prediction, "error", None) or "Replicate prediction did not succeed."
        raise SystemExit(error)
    return prediction


def is_retryable_prediction_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "code: pa" in lowered
        or "prediction interrupted" in lowered
        or "please retry" in lowered
        or "director: unexpected error handling prediction" in lowered
    )


def run_prediction_with_retries(
    model_ref: str,
    payload: dict[str, Any],
    *,
    retries: int,
    poll_interval_seconds: float,
    timeout_seconds: float | None,
) -> Any:
    attempts = retries + 1
    for attempt_index in range(attempts):
        prediction = create_prediction(model_ref, payload)
        try:
            return wait_for_prediction(
                prediction,
                poll_interval_seconds=poll_interval_seconds,
                timeout_seconds=timeout_seconds,
            )
        except SystemExit as exc:
            message = str(exc)
            is_last_attempt = attempt_index >= attempts - 1
            if is_last_attempt or not is_retryable_prediction_error(message):
                raise
            print(
                f"Transient hosted failure on attempt {attempt_index + 1}/{attempts}: {message}. "
                f"Retrying attempt {attempt_index + 2}/{attempts}...",
                flush=True,
            )
    raise SystemExit("Replicate prediction retry loop exhausted unexpectedly.")


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
    prediction = run_prediction_with_retries(
        args.model,
        payload,
        retries=args.retries,
        poll_interval_seconds=args.poll_interval,
        timeout_seconds=args.timeout_seconds,
    )
    output = prediction.output

    output_url = getattr(output, "url", None)
    if output_url:
        print(f"Remote output URL: {output_url}", flush=True)

    written_path = save_file_output(output, args.output)
    print(f"Wrote output to {written_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
