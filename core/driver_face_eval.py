from __future__ import annotations

import json
import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.openpilot_integration import apply_openpilot_runtime_patches
from renderers import driver_debug_renderer, video_renderer
from renderers.big_ui_engine import FRAMERATE, IndexedFrameQueue
from renderers.driver_debug_engine import compute_driver_face_box_rect, extract_driver_debug_telemetry


@dataclass(frozen=True)
class DriverFaceEvalSeed:
    sample_id: str
    category: str
    route_or_url: str
    start_seconds: int
    length_seconds: int
    notes: str


@dataclass(frozen=True)
class FaceTrackConfig:
    minimum_face_prob: float = 0.5
    padding_scale: float = 2.0
    padding_y_scale: float = 2.2
    upward_bias_ratio: float = 0.12
    smoothing_alpha: float = 0.38
    missing_hold_frames: int = 6
    minimum_crop_size: int = 192
    crop_size_quantile: float = 0.95
    output_resolution: int = 512


@dataclass(frozen=True)
class EvalSampleArtifacts:
    sample_id: str
    category: str
    route: str
    route_or_url: str
    start_seconds: int
    length_seconds: int
    data_dir: str
    output_dir: str
    device_type: str
    source_clip: str
    crop_clip: str
    track_metadata: str
    evaluation_template: str
    analysis_clip: str | None = None


@dataclass(frozen=True)
class _FrameRect:
    x: float
    y: float
    width: float
    height: float


DEFAULT_DRIVER_FACE_EVAL_SEEDS: tuple[DriverFaceEvalSeed, ...] = (
    DriverFaceEvalSeed(
        sample_id="mici-baseline",
        category="mici baseline clean clip",
        route_or_url="https://connect.comma.ai/5beb9b58bd12b691/0000010a--a51155e496/90/92",
        start_seconds=90,
        length_seconds=2,
        notes="Newer mici route with smaller and farther-away face under strong magenta cabin cast.",
    ),
    DriverFaceEvalSeed(
        sample_id="tici-baseline",
        category="tici baseline clean clip",
        route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
        start_seconds=110,
        length_seconds=2,
        notes="Public tici route with a centered face and lower occlusion than the earlier sample.",
    ),
    DriverFaceEvalSeed(
        sample_id="tici-occlusion",
        category="tici occlusion stress clip",
        route_or_url="a2a0ccea32023010|2023-07-27--13-01-19",
        start_seconds=90,
        length_seconds=2,
        notes="Public tici route with a near-lens hand occlusion that stresses tracking and temporal stability.",
    ),
)


def default_driver_face_eval_seeds() -> tuple[DriverFaceEvalSeed, ...]:
    return DEFAULT_DRIVER_FACE_EVAL_SEEDS


def seed_by_id(sample_id: str) -> DriverFaceEvalSeed:
    for seed in DEFAULT_DRIVER_FACE_EVAL_SEEDS:
        if seed.sample_id == sample_id:
            return seed
    raise KeyError(f"Unknown driver face eval seed: {sample_id}")


def _round_even(value: float, *, mode: str = "nearest") -> int:
    if mode == "floor":
        rounded = math.floor(value)
    elif mode == "ceil":
        rounded = math.ceil(value)
    else:
        rounded = round(value)
    rounded = int(rounded)
    if rounded % 2:
        if mode == "ceil":
            rounded += 1
        else:
            rounded -= 1
    return max(0, rounded)


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _quantile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    q = _clip(quantile, 0.0, 1.0)
    idx = int(round((len(ordered) - 1) * q))
    return ordered[idx]


def expand_face_box(
    box: tuple[float, float, float, float],
    *,
    frame_width: int,
    frame_height: int,
    config: FaceTrackConfig,
) -> tuple[float, float, float, float]:
    box_x, box_y, box_w, box_h = box
    center_x = box_x + (box_w / 2.0)
    center_y = box_y + (box_h / 2.0) - (box_h * config.upward_bias_ratio)
    padded_w = box_w * config.padding_scale
    padded_h = box_h * config.padding_y_scale
    max_w = float(max(2, _round_even(frame_width, mode="floor")))
    max_h = float(max(2, _round_even(frame_height, mode="floor")))
    padded_w = min(padded_w, max_w)
    padded_h = min(padded_h, max_h)
    padded_x = _clip(center_x - (padded_w / 2.0), 0.0, max(0.0, frame_width - padded_w))
    padded_y = _clip(center_y - (padded_h / 2.0), 0.0, max(0.0, frame_height - padded_h))
    return padded_x, padded_y, padded_w, padded_h


def fixed_crop_side_from_boxes(
    padded_boxes: list[tuple[float, float, float, float] | None],
    *,
    frame_width: int,
    frame_height: int,
    config: FaceTrackConfig,
) -> int:
    sides = [max(box[2], box[3]) for box in padded_boxes if box is not None]
    quantile_value = _quantile(sides, config.crop_size_quantile)
    base_side = quantile_value if quantile_value is not None else float(config.minimum_crop_size)
    max_side = float(min(frame_width, frame_height))
    aligned_min = max(2, _round_even(config.minimum_crop_size, mode="ceil"))
    return max(aligned_min, min(_round_even(base_side, mode="ceil"), _round_even(max_side, mode="floor")))


def square_crop_rect(
    *,
    center_x: float,
    center_y: float,
    side: int,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int]:
    side = max(2, min(_round_even(side, mode="ceil"), _round_even(min(frame_width, frame_height), mode="floor")))
    max_x = max(0, frame_width - side)
    max_y = max(0, frame_height - side)
    crop_x = _clip(center_x - (side / 2.0), 0.0, float(max_x))
    crop_y = _clip(center_y - (side / 2.0), 0.0, float(max_y))
    crop_x = min(_round_even(crop_x, mode="floor"), max_x)
    crop_y = min(_round_even(crop_y, mode="floor"), max_y)
    return crop_x, crop_y, side, side


def crop_nv12_frame(
    frame_bytes: bytes,
    *,
    frame_width: int,
    frame_height: int,
    crop_rect: tuple[int, int, int, int],
) -> bytes:
    crop_x, crop_y, crop_w, crop_h = crop_rect
    if any(value % 2 for value in (crop_x, crop_y, crop_w, crop_h)):
        raise ValueError(f"NV12 crop rect must be even-aligned. Got {crop_rect}")
    if crop_x < 0 or crop_y < 0 or crop_w <= 0 or crop_h <= 0:
        raise ValueError(f"Invalid crop rect: {crop_rect}")
    if crop_x + crop_w > frame_width or crop_y + crop_h > frame_height:
        raise ValueError(f"Crop rect {crop_rect} exceeds frame bounds {frame_width}x{frame_height}")

    y_plane_size = frame_width * frame_height
    expected_size = y_plane_size + (y_plane_size // 2)
    if len(frame_bytes) != expected_size:
        raise ValueError(f"Unexpected NV12 frame size. Expected {expected_size}, got {len(frame_bytes)}")

    source = memoryview(frame_bytes)
    y_plane = source[:y_plane_size]
    uv_plane = source[y_plane_size:]
    output = bytearray(crop_w * crop_h * 3 // 2)
    out_offset = 0

    for row in range(crop_y, crop_y + crop_h):
        start = (row * frame_width) + crop_x
        end = start + crop_w
        chunk = y_plane[start:end]
        output[out_offset: out_offset + crop_w] = chunk
        out_offset += crop_w

    uv_start_row = crop_y // 2
    uv_row_count = crop_h // 2
    for row in range(uv_start_row, uv_start_row + uv_row_count):
        start = (row * frame_width) + crop_x
        end = start + crop_w
        chunk = uv_plane[start:end]
        output[out_offset: out_offset + crop_w] = chunk
        out_offset += crop_w

    return bytes(output)


def _selected_driver_data(state: dict[str, object]) -> tuple[object | None, bool, float | None]:
    dm_state_msg = state.get("driverMonitoringState")
    driver_state_msg = state.get("driverStateV2")
    dm_state = getattr(dm_state_msg, "driverMonitoringState", None) if dm_state_msg is not None else None
    driver_state = getattr(driver_state_msg, "driverStateV2", None) if driver_state_msg is not None else None

    is_rhd = bool(getattr(dm_state, "isRHD", False))
    wheel_on_right_prob = getattr(driver_state, "wheelOnRightProb", None)
    if dm_state is None and wheel_on_right_prob is not None:
        is_rhd = float(wheel_on_right_prob) > 0.5

    driver_data = None
    if driver_state is not None:
        driver_data = getattr(driver_state, "rightDriverData", None) if is_rhd else getattr(driver_state, "leftDriverData", None)
    return driver_data, is_rhd, float(wheel_on_right_prob) if wheel_on_right_prob is not None else None


def build_face_track_manifest(
    render_steps: list[Any],
    *,
    frame_width: int,
    frame_height: int,
    device_type: str,
    config: FaceTrackConfig,
) -> dict[str, Any]:
    frame_rect = _FrameRect(x=0.0, y=0.0, width=float(frame_width), height=float(frame_height))
    frame_rows: list[dict[str, Any]] = []
    usable_boxes: list[tuple[float, float, float, float] | None] = []

    for frame_index, step in enumerate(render_steps):
        telemetry = extract_driver_debug_telemetry(step.state)
        driver_data, is_rhd, wheel_on_right_prob = _selected_driver_data(step.state)
        raw_box = None
        if driver_data is not None:
            raw_box = compute_driver_face_box_rect(frame_rect, driver_data=driver_data, device_type=device_type)

        face_prob = telemetry.face_prob if telemetry.face_prob is not None else 0.0
        trusted = raw_box is not None and (
            telemetry.face_detected
            or face_prob >= config.minimum_face_prob
            or frame_index == 0
        )
        padded_box = (
            expand_face_box(raw_box, frame_width=frame_width, frame_height=frame_height, config=config)
            if trusted and raw_box is not None
            else None
        )
        usable_boxes.append(padded_box)
        frame_rows.append(
            {
                "frame_index": frame_index,
                "route_seconds": round(float(step.route_seconds), 3),
                "route_frame_id": int(step.route_frame_id),
                "face_detected": bool(telemetry.face_detected),
                "face_prob": round(face_prob, 4),
                "selected_side": telemetry.selected_side,
                "is_rhd": bool(is_rhd),
                "wheel_on_right_prob": round(wheel_on_right_prob, 4) if wheel_on_right_prob is not None else None,
                "telemetry": {
                    "left_eye_prob": telemetry.left_eye_prob,
                    "right_eye_prob": telemetry.right_eye_prob,
                    "left_blink_prob": telemetry.left_blink_prob,
                    "right_blink_prob": telemetry.right_blink_prob,
                    "sunglasses_prob": telemetry.sunglasses_prob,
                    "phone_prob": telemetry.phone_prob,
                    "face_orientation": list(telemetry.face_orientation),
                    "face_position": list(telemetry.face_position),
                    "face_orientation_std": list(telemetry.face_orientation_std),
                    "face_position_std": list(telemetry.face_position_std),
                },
                "raw_box": _box_dict(raw_box),
                "padded_box": _box_dict(padded_box),
            }
        )

    crop_side = fixed_crop_side_from_boxes(usable_boxes, frame_width=frame_width, frame_height=frame_height, config=config)
    smoothed_center_x: float | None = None
    smoothed_center_y: float | None = None
    held_frames = 0

    for row in frame_rows:
        padded_box = _dict_box_tuple(row["padded_box"])
        if padded_box is not None:
            center_x = padded_box[0] + (padded_box[2] / 2.0)
            center_y = padded_box[1] + (padded_box[3] / 2.0)
            if smoothed_center_x is None or smoothed_center_y is None:
                smoothed_center_x = center_x
                smoothed_center_y = center_y
            else:
                alpha = config.smoothing_alpha
                smoothed_center_x = ((1.0 - alpha) * smoothed_center_x) + (alpha * center_x)
                smoothed_center_y = ((1.0 - alpha) * smoothed_center_y) + (alpha * center_y)
            held_frames = 0
        elif smoothed_center_x is not None and smoothed_center_y is not None and held_frames < config.missing_hold_frames:
            held_frames += 1
        else:
            smoothed_center_x = None
            smoothed_center_y = None

        if smoothed_center_x is None or smoothed_center_y is None:
            crop_rect = None
        else:
            crop_rect = square_crop_rect(
                center_x=smoothed_center_x,
                center_y=smoothed_center_y,
                side=crop_side,
                frame_width=frame_width,
                frame_height=frame_height,
            )

        row["crop_rect"] = _box_dict(crop_rect)
        row["smoothed_center"] = (
            {"x": round(smoothed_center_x, 3), "y": round(smoothed_center_y, 3)}
            if smoothed_center_x is not None and smoothed_center_y is not None
            else None
        )
        row["held_without_detection"] = held_frames if padded_box is None and crop_rect is not None else 0

    return {
        "frame_width": frame_width,
        "frame_height": frame_height,
        "device_type": device_type,
        "framerate": FRAMERATE,
        "crop_side": crop_side,
        "output_resolution": config.output_resolution,
        "config": asdict(config),
        "frames": frame_rows,
    }


def _box_dict(box: tuple[float, float, float, float] | tuple[int, int, int, int] | None) -> dict[str, float | int] | None:
    if box is None:
        return None
    return {
        "x": round(float(box[0]), 3) if isinstance(box[0], float) else int(box[0]),
        "y": round(float(box[1]), 3) if isinstance(box[1], float) else int(box[1]),
        "width": round(float(box[2]), 3) if isinstance(box[2], float) else int(box[2]),
        "height": round(float(box[3]), 3) if isinstance(box[3], float) else int(box[3]),
    }


def _dict_box_tuple(box: dict[str, float | int] | None) -> tuple[float, float, float, float] | None:
    if box is None:
        return None
    return float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])


def _raw_crop_encode_command(
    *,
    crop_side: int,
    output_resolution: int,
    framerate: int,
    target_mb: int,
    length_seconds: int,
    acceleration: video_renderer.AccelerationPolicy,
    output_path: Path,
) -> list[str]:
    accel = video_renderer.select_video_acceleration(acceleration, "h264")
    target_bps = max(1, target_mb * 8 * 1024 * 1024 // max(1, length_seconds))
    return [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "nv12",
        "-s:v",
        f"{crop_side}x{crop_side}",
        "-r",
        str(framerate),
        "-i",
        "pipe:0",
        "-vf",
        f"scale={output_resolution}:{output_resolution}:flags=lanczos",
        *accel.encoder_args,
        "-b:v",
        str(target_bps),
        "-maxrate",
        str(target_bps),
        "-bufsize",
        str(target_bps * 2),
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def write_face_crop_video(
    *,
    frame_queue: IndexedFrameQueue,
    manifest: dict[str, Any],
    output_path: Path,
    target_mb: int,
    length_seconds: int,
    acceleration: video_renderer.AccelerationPolicy,
) -> None:
    crop_side = int(manifest["crop_side"])
    output_resolution = int(manifest["output_resolution"])
    command = _raw_crop_encode_command(
        crop_side=crop_side,
        output_resolution=output_resolution,
        framerate=int(manifest["framerate"]),
        target_mb=target_mb,
        length_seconds=length_seconds,
        acceleration=acceleration,
        output_path=output_path,
    )
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False)
    assert process.stdin is not None
    try:
        for row in manifest["frames"]:
            _camera_ref, frame_bytes = frame_queue.get()
            crop_rect = _dict_box_int_tuple(row["crop_rect"])
            if crop_rect is None:
                process.stdin.write(bytes(crop_side * crop_side * 3 // 2))
                continue
            cropped = crop_nv12_frame(
                frame_bytes,
                frame_width=int(manifest["frame_width"]),
                frame_height=int(manifest["frame_height"]),
                crop_rect=crop_rect,
            )
            process.stdin.write(cropped)
    finally:
        process.stdin.close()
    process.wait()
    if process.returncode != 0:
        output = b""
        if process.stdout is not None:
            output = process.stdout.read() or b""
        raise subprocess.CalledProcessError(process.returncode, command, output=output)


def _dict_box_int_tuple(box: dict[str, float | int] | None) -> tuple[int, int, int, int] | None:
    if box is None:
        return None
    return int(box["x"]), int(box["y"]), int(box["width"]), int(box["height"])


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def evaluation_template_markdown(*, seed: DriverFaceEvalSeed, artifacts: EvalSampleArtifacts) -> str:
    return (
        f"# Driver Face Evaluation: {seed.sample_id}\n\n"
        f"- Category: {seed.category}\n"
        f"- Route input: `{seed.route_or_url}`\n"
        f"- Route: `{artifacts.route}`\n"
        f"- Window: `{artifacts.start_seconds}s` to `{artifacts.start_seconds + artifacts.length_seconds}s`\n"
        f"- Device type: `{artifacts.device_type}`\n"
        f"- Notes: {seed.notes}\n\n"
        "## Artifacts\n\n"
        f"- Clean driver clip: `{Path(artifacts.source_clip).name}`\n"
        f"- Face crop clip: `{Path(artifacts.crop_clip).name}`\n"
        f"- Track metadata: `{Path(artifacts.track_metadata).name}`\n"
        + (f"- Driver-debug analysis clip: `{Path(artifacts.analysis_clip).name}`\n" if artifacts.analysis_clip else "")
        + "\n## Candidate Buckets\n\n"
        "- DM-box-only baseline: pending\n"
        "- Bundled surrogate / portrait replacement baseline: pending\n"
        "- Creator-stack practical candidate: pending\n"
        "- Research-heavy video-native candidate: pending\n\n"
        "## Rubric\n\n"
        "| Candidate | Identity leakage | Temporal stability | Gaze / eye-state readability | Pose preservation | Occlusion robustness | Runtime / complexity | Notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| TBD |  |  |  |  |  |  |  |\n"
    )


def ensure_driver_face_eval_inputs(
    *,
    route: str,
    start_seconds: int,
    length_seconds: int,
    data_dir: Path,
    skip_download: bool,
) -> None:
    from core import route_downloader

    if skip_download:
        return
    route_downloader.downloadSegments(
        route_or_segment=route,
        start_seconds=start_seconds,
        length=length_seconds,
        smear_seconds=0,
        data_dir=data_dir,
        file_types=["dcameras", "logs"],
        jwt_token=None,
        decompress_logs=False,
    )


def materialize_eval_sample(
    *,
    seed: DriverFaceEvalSeed,
    output_root: Path,
    data_root: str,
    explicit_data_dir: str | None,
    openpilot_dir: str,
    skip_download: bool,
    include_driver_debug: bool,
    overwrite: bool,
    acceleration: video_renderer.AccelerationPolicy,
    source_target_mb: int = 3,
    crop_target_mb: int = 4,
    analysis_target_mb: int = 6,
    config: FaceTrackConfig | None = None,
) -> EvalSampleArtifacts:
    from core import route_inputs
    from core.clip_orchestrator import resolve_data_dir

    parsed = route_inputs.parseRouteOrUrl(
        route_or_url=seed.route_or_url,
        start_seconds=seed.start_seconds,
        length_seconds=seed.length_seconds,
        jwt_token=None,
    )
    data_dir = resolve_data_dir(parsed.route, data_root, explicit_data_dir)
    ensure_driver_face_eval_inputs(
        route=parsed.route,
        start_seconds=parsed.start_seconds,
        length_seconds=parsed.length_seconds,
        data_dir=data_dir,
        skip_download=skip_download,
    )

    sample_dir = output_root / seed.sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    source_clip = sample_dir / "driver-source.mp4"
    crop_clip = sample_dir / "face-crop.mp4"
    track_metadata = sample_dir / "face-track.json"
    evaluation_template = sample_dir / "evaluation.md"
    analysis_clip = sample_dir / "driver-debug-analysis.mp4" if include_driver_debug else None

    if overwrite or not source_clip.exists():
        video_renderer.render_video_clip(
            video_renderer.VideoRenderOptions(
                render_type="driver",
                data_dir=str(data_dir),
                route_or_segment=parsed.route,
                start_seconds=parsed.start_seconds,
                length_seconds=parsed.length_seconds,
                target_mb=source_target_mb,
                file_format="h264",
                acceleration=acceleration,
                output_path=str(source_clip),
            )
        )

    openpilot_path = Path(openpilot_dir).resolve()
    patch_report = apply_openpilot_runtime_patches(openpilot_path)
    if patch_report.changed:
        print(f"Applied openpilot runtime patches for eval: {patch_report}")
    worker_python = openpilot_path / ".venv/bin/python"
    if not worker_python.exists():
        raise FileNotFoundError(f"Openpilot worker interpreter not found at {worker_python}")
    face_track_config = config or FaceTrackConfig()
    if face_track_config != FaceTrackConfig():
        raise ValueError("Non-default FaceTrackConfig is not yet supported by the eval worker subprocess")
    worker_cmd = [
        str(worker_python),
        str((Path(__file__).resolve().parent / "driver_face_eval_worker.py").resolve()),
        "--route",
        parsed.route,
        "--route-or-url",
        seed.route_or_url,
        "--start-seconds",
        str(parsed.start_seconds),
        "--length-seconds",
        str(parsed.length_seconds),
        "--data-dir",
        str(data_dir),
        "--openpilot-dir",
        str(openpilot_path),
        "--sample-id",
        seed.sample_id,
        "--category",
        seed.category,
        "--notes",
        seed.notes,
        "--track-metadata",
        str(track_metadata),
        "--crop-clip",
        str(crop_clip),
        "--source-clip",
        str(source_clip),
        "--crop-target-mb",
        str(crop_target_mb),
        "--accel",
        acceleration,
    ]
    subprocess.run(worker_cmd, check=True)
    manifest = json.loads(track_metadata.read_text())
    metadata_device_type = str(manifest.get("device_type", "unknown"))

    if analysis_clip is not None and (overwrite or not analysis_clip.exists()):
        driver_debug_renderer.render_driver_debug_clip(
            driver_debug_renderer.DriverDebugRenderOptions(
                route=parsed.route,
                route_or_url=seed.route_or_url,
                start_seconds=parsed.start_seconds,
                length_seconds=parsed.length_seconds,
                smear_seconds=0,
                target_mb=analysis_target_mb,
                file_format="h264",
                output_path=str(analysis_clip),
                data_dir=str(data_dir),
                openpilot_dir=str(openpilot_path),
                headless=True,
                acceleration=acceleration,
            )
        )

    artifacts = EvalSampleArtifacts(
        sample_id=seed.sample_id,
        category=seed.category,
        route=parsed.route,
        route_or_url=seed.route_or_url,
        start_seconds=parsed.start_seconds,
        length_seconds=parsed.length_seconds,
        data_dir=str(data_dir),
        output_dir=str(sample_dir),
        device_type=metadata_device_type,
        source_clip=str(source_clip),
        crop_clip=str(crop_clip),
        track_metadata=str(track_metadata),
        evaluation_template=str(evaluation_template),
        analysis_clip=str(analysis_clip) if analysis_clip is not None else None,
    )
    evaluation_template.write_text(evaluation_template_markdown(seed=seed, artifacts=artifacts))
    return artifacts


def materialize_seed_set(
    *,
    output_root: Path,
    seeds: list[DriverFaceEvalSeed],
    data_root: str,
    explicit_data_dir: str | None,
    openpilot_dir: str,
    skip_download: bool,
    include_driver_debug: bool,
    overwrite: bool,
    acceleration: video_renderer.AccelerationPolicy,
) -> list[EvalSampleArtifacts]:
    artifacts = [
        materialize_eval_sample(
            seed=seed,
            output_root=output_root,
            data_root=data_root,
            explicit_data_dir=explicit_data_dir,
            openpilot_dir=openpilot_dir,
            skip_download=skip_download,
            include_driver_debug=include_driver_debug,
            overwrite=overwrite,
            acceleration=acceleration,
        )
        for seed in seeds
    ]
    manifest = {
        "samples": [asdict(item) for item in artifacts],
        "seed_ids": [seed.sample_id for seed in seeds],
    }
    write_json(output_root / "manifest.json", manifest)
    return artifacts
