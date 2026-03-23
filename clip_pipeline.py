from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import ffmpeg_clip
import route_or_url
import ui_clip


RenderType = Literal[
    "ui",
    "forward",
    "wide",
    "driver",
    "360",
    "forward_upon_wide",
    "360_forward_upon_wide",
]
OutputFormatInput = Literal["auto", "h264", "hevc"]
OutputFormat = Literal["h264", "hevc"]
ExecutionContext = Literal["cog", "local"]
UIBackend = Literal["auto", "modern", "legacy"]
UIMode = Literal["auto", "c3", "c3x", "big", "c4"]
LocalAccel = Literal["auto", "cpu", "videotoolbox", "nvidia"]

RENDER_TYPE_FILE_TYPES: dict[RenderType, tuple[str, ...]] = {
    "ui": ("cameras", "logs"),
    "forward": ("cameras",),
    "wide": ("ecameras",),
    "driver": ("dcameras",),
    "360": ("ecameras", "dcameras"),
    "forward_upon_wide": ("ecameras", "cameras"),
    "360_forward_upon_wide": ("ecameras", "dcameras", "cameras"),
}


@dataclass(frozen=True)
class ClipRequest:
    render_type: RenderType
    route_or_url: str
    start_seconds: int
    length_seconds: int
    target_mb: int
    file_format: OutputFormatInput = "auto"
    output_path: str = "./shared/cog-clip.mp4"
    smear_seconds: int = 0
    jwt_token: str | None = None
    metric: bool = False
    ui_mode: UIMode = "auto"
    ui_backend: UIBackend = "modern"
    speedhack_ratio: float = 1.0
    forward_upon_wide_h: float = 2.2
    explicit_data_dir: str | None = None
    data_root: str = "./shared/data_dir"
    execution_context: ExecutionContext = "local"
    minimum_length_seconds: int = 1
    maximum_length_seconds: int = 300
    local_acceleration: LocalAccel = "auto"
    openpilot_dir: str = "/home/batman/openpilot"
    qcam: bool = False
    headless: bool = True
    skip_download: bool = False


@dataclass(frozen=True)
class ClipPlan:
    render_type: RenderType
    route: str
    start_seconds: int
    length_seconds: int
    target_mb: int
    file_format: OutputFormat
    output_path: Path
    data_dir: Path
    download_file_types: tuple[str, ...]
    decompress_logs: bool
    smear_seconds: int
    ui_mode: Literal["big"]
    ui_backend: Literal["modern"]
    local_acceleration: LocalAccel
    forward_upon_wide_h: float
    jwt_token: str | None
    metric: bool
    openpilot_dir: str
    headless: bool
    qcam: bool


@dataclass(frozen=True)
class ClipResult:
    output_path: Path
    route: str
    render_type: RenderType
    data_dir: Path
    file_format: OutputFormat
    ui_mode: str | None = None
    acceleration: str | None = None


def normalize_output_format(render_type: RenderType, requested_format: OutputFormatInput) -> OutputFormat:
    if requested_format in ("h264", "hevc"):
        return requested_format
    if render_type in ("360", "360_forward_upon_wide"):
        return "hevc"
    return "h264"


def normalize_target_mb(target_mb: int, execution_context: ExecutionContext) -> int:
    if execution_context == "cog":
        return max(1, target_mb - 1)
    return max(1, target_mb)


def normalize_ui_mode(ui_mode: UIMode) -> Literal["big"]:
    if ui_mode in ("auto", "c3", "c3x", "big"):
        return "big"
    raise ValueError("comma 4 / non-BIG UI mode is deferred in this cleanup phase; use BIG, c3, or c3x")


def normalize_ui_backend(ui_backend: UIBackend) -> Literal["modern"]:
    if ui_backend == "legacy":
        print("warning: legacy UI backend is deprecated; using modern backend")
    return "modern"


def select_download_file_types(render_type: RenderType, *, qcam: bool) -> tuple[str, ...]:
    if render_type == "ui" and qcam:
        return ("qcameras", "logs")
    return RENDER_TYPE_FILE_TYPES[render_type]


def resolve_data_dir(route: str, data_root: str, explicit_data_dir: str | None) -> Path:
    if explicit_data_dir:
        return Path(explicit_data_dir).expanduser().resolve()
    dongle_id = route.split("|", 1)[0]
    return (Path(data_root) / dongle_id).expanduser().resolve()


def build_clip_plan(request: ClipRequest) -> ClipPlan:
    parsed = route_or_url.parseRouteOrUrl(
        route_or_url=request.route_or_url,
        start_seconds=request.start_seconds,
        length_seconds=request.length_seconds,
        jwt_token=request.jwt_token,
    )
    if parsed.length_seconds < request.minimum_length_seconds:
        raise ValueError(
            f"Length must be at least {request.minimum_length_seconds} seconds. Got {parsed.length_seconds} seconds."
        )
    if parsed.length_seconds > request.maximum_length_seconds:
        raise ValueError(
            f"Length must be at most {request.maximum_length_seconds} seconds. Got {parsed.length_seconds} seconds."
        )

    ui_mode = normalize_ui_mode(request.ui_mode) if request.render_type == "ui" else "big"
    ui_backend = normalize_ui_backend(request.ui_backend) if request.render_type == "ui" else "modern"
    return ClipPlan(
        render_type=request.render_type,
        route=parsed.route,
        start_seconds=parsed.start_seconds,
        length_seconds=parsed.length_seconds,
        target_mb=normalize_target_mb(request.target_mb, request.execution_context),
        file_format=normalize_output_format(request.render_type, request.file_format),
        output_path=Path(request.output_path).expanduser().resolve(),
        data_dir=resolve_data_dir(parsed.route, request.data_root, request.explicit_data_dir),
        download_file_types=select_download_file_types(request.render_type, qcam=request.qcam),
        decompress_logs=request.render_type != "ui",
        smear_seconds=max(0, request.smear_seconds),
        ui_mode=ui_mode,
        ui_backend=ui_backend,
        local_acceleration=request.local_acceleration,
        forward_upon_wide_h=request.forward_upon_wide_h,
        jwt_token=request.jwt_token or None,
        metric=request.metric,
        openpilot_dir=request.openpilot_dir,
        headless=request.headless,
        qcam=request.qcam,
    )


def run_clip(request: ClipRequest) -> ClipResult:
    plan = build_clip_plan(request)
    plan.output_path.parent.mkdir(parents=True, exist_ok=True)
    if plan.output_path.exists():
        plan.output_path.unlink()

    if not request.skip_download:
        import downloader

        downloader.downloadSegments(
            route_or_segment=plan.route,
            start_seconds=plan.start_seconds,
            length=plan.length_seconds,
            smear_seconds=plan.smear_seconds,
            data_dir=plan.data_dir,
            file_types=list(plan.download_file_types),
            jwt_token=plan.jwt_token,
            decompress_logs=plan.decompress_logs,
        )

    if plan.render_type == "ui":
        ui_result = ui_clip.render_ui_clip(
            ui_clip.UIRenderOptions(
                route=plan.route,
                start_seconds=plan.start_seconds,
                length_seconds=plan.length_seconds,
                smear_seconds=plan.smear_seconds,
                target_mb=plan.target_mb,
                file_format=plan.file_format,
                speedhack_ratio=request.speedhack_ratio,
                metric=plan.metric,
                output_path=str(plan.output_path),
                data_dir=str(plan.data_dir),
                jwt_token=plan.jwt_token,
                openpilot_dir=plan.openpilot_dir,
                backend=plan.ui_backend,
                ui_mode=plan.ui_mode,
                headless=plan.headless,
            )
        )
        return ClipResult(
            output_path=ui_result.output_path,
            route=plan.route,
            render_type=plan.render_type,
            data_dir=plan.data_dir,
            file_format=plan.file_format,
            ui_mode=ui_result.ui_mode,
        )

    video_result = ffmpeg_clip.render_video_clip(
        ffmpeg_clip.VideoRenderOptions(
            render_type=plan.render_type,
            data_dir=str(plan.data_dir),
            route_or_segment=plan.route,
            start_seconds=plan.start_seconds,
            length_seconds=plan.length_seconds,
            target_mb=plan.target_mb,
            file_format=plan.file_format,
            acceleration=request.local_acceleration,
            forward_upon_wide_h=plan.forward_upon_wide_h,
            output_path=str(plan.output_path),
        )
    )
    return ClipResult(
        output_path=video_result.output_path,
        route=plan.route,
        render_type=plan.render_type,
        data_dir=plan.data_dir,
        file_format=plan.file_format,
        acceleration=video_result.acceleration,
    )
