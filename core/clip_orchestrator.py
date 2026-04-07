from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from core import route_downloader, route_inputs
from core.driver_face_swap import (
    DriverFaceAnonymizationMode,
    DriverFaceAnonymizationProfile,
    PassengerRedactionStyle,
    DriverFaceSelectionMode,
    DriverFaceSwapOptions,
    DriverFaceSwapPreset,
    canonical_driver_face_profile,
    default_driver_face_donor_bank_dir,
    default_driver_face_source_image,
    default_facefusion_model,
    default_facefusion_root,
    has_driver_face_anonymization,
    render_anonymized_driver_backing_video,
)
from core.forward_upon_wide import ForwardUponWideHInput, is_auto_forward_upon_wide
from core.openpilot_config import default_image_openpilot_root
from renderers import driver_debug_renderer, ui_renderer, video_renderer


RenderType = Literal[
    "ui",
    "ui-alt",
    "driver-debug",
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
LocalAccel = Literal["auto", "cpu", "videotoolbox", "nvidia"]

RENDER_TYPE_FILE_TYPES: dict[RenderType, tuple[str, ...]] = {
    "ui": ("cameras", "ecameras", "logs"),
    "ui-alt": ("cameras", "ecameras", "logs"),
    "driver-debug": ("dcameras", "logs"),
    "forward": ("cameras",),
    "wide": ("ecameras",),
    "driver": ("dcameras",),
    "360": ("ecameras", "dcameras"),
    "forward_upon_wide": ("ecameras", "cameras"),
    "360_forward_upon_wide": ("ecameras", "dcameras", "cameras"),
}

DRIVER_FACE_ANONYMIZATION_RENDER_TYPES: tuple[RenderType, ...] = (
    "driver",
    "driver-debug",
    "360",
    "360_forward_upon_wide",
)


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
    forward_upon_wide_h: ForwardUponWideHInput = 2.2
    explicit_data_dir: str | None = None
    data_root: str = "./shared/data_dir"
    execution_context: ExecutionContext = "local"
    minimum_length_seconds: int = 1
    maximum_length_seconds: int = 300
    local_acceleration: LocalAccel = "auto"
    openpilot_dir: str = field(default_factory=default_image_openpilot_root)
    qcam: bool = False
    headless: bool = True
    skip_download: bool = False
    driver_face_anonymization: DriverFaceAnonymizationMode = "none"
    driver_face_profile: DriverFaceAnonymizationProfile = "driver_face_swap_passenger_face_swap"
    passenger_redaction_style: PassengerRedactionStyle = "blur"
    driver_face_source_image: str = field(default_factory=default_driver_face_source_image)
    driver_face_preset: DriverFaceSwapPreset = "fast"
    facefusion_root: str = field(default_factory=default_facefusion_root)
    facefusion_model: str = field(default_factory=default_facefusion_model)
    driver_face_selection: DriverFaceSelectionMode = "manual"
    driver_face_donor_bank_dir: str = field(default_factory=default_driver_face_donor_bank_dir)


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
    local_acceleration: LocalAccel
    forward_upon_wide_h: ForwardUponWideHInput
    jwt_token: str | None
    openpilot_dir: str
    headless: bool
    qcam: bool
    driver_face_swap: DriverFaceSwapOptions


@dataclass(frozen=True)
class ClipResult:
    output_path: Path
    route: str
    render_type: RenderType
    data_dir: Path
    file_format: OutputFormat
    acceleration: str | None = None


def is_ui_render_type(render_type: RenderType) -> bool:
    return render_type in ("ui", "ui-alt")


def is_openpilot_render_type(render_type: RenderType) -> bool:
    return render_type in ("ui", "ui-alt", "driver-debug")


def is_smear_render_type(render_type: RenderType) -> bool:
    return render_type in ("ui", "ui-alt", "driver-debug")


def supports_driver_face_anonymization(render_type: RenderType | str) -> bool:
    return render_type in DRIVER_FACE_ANONYMIZATION_RENDER_TYPES


def _append_unique_file_types(file_types: tuple[str, ...], *extras: str) -> tuple[str, ...]:
    result = list(file_types)
    for extra in extras:
        if extra not in result:
            result.append(extra)
    return tuple(result)


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


def select_download_file_types(
    render_type: RenderType,
    *,
    qcam: bool,
    forward_upon_wide_h: ForwardUponWideHInput = 2.2,
    driver_face_anonymization: DriverFaceAnonymizationMode = "none",
) -> tuple[str, ...]:
    if is_ui_render_type(render_type) and qcam:
        return ("qcameras", "logs")
    file_types = RENDER_TYPE_FILE_TYPES[render_type]
    extra_file_types: list[str] = []
    if render_type in ("forward_upon_wide", "360_forward_upon_wide") and is_auto_forward_upon_wide(forward_upon_wide_h):
        extra_file_types.extend(("qlogs", "logs"))
    if supports_driver_face_anonymization(render_type) and driver_face_anonymization != "none":
        extra_file_types.append("logs")
    return _append_unique_file_types(file_types, *extra_file_types)


def resolve_data_dir(route: str, data_root: str, explicit_data_dir: str | None) -> Path:
    if explicit_data_dir:
        return Path(explicit_data_dir).expanduser().resolve()
    dongle_id = route.split("|", 1)[0]
    return (Path(data_root) / dongle_id).expanduser().resolve()


def build_clip_plan(request: ClipRequest) -> ClipPlan:
    parsed = route_inputs.parseRouteOrUrl(
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

    driver_face_swap = DriverFaceSwapOptions(
        mode=request.driver_face_anonymization,
        profile=canonical_driver_face_profile(request.driver_face_profile),
        passenger_redaction_style=request.passenger_redaction_style,
        source_image=request.driver_face_source_image,
        facefusion_root=request.facefusion_root,
        facefusion_model=request.facefusion_model,
        preset=request.driver_face_preset,
        selection_mode=request.driver_face_selection,
        donor_bank_dir=request.driver_face_donor_bank_dir,
    )
    if has_driver_face_anonymization(driver_face_swap) and not supports_driver_face_anonymization(request.render_type):
        raise ValueError(
            "Driver face anonymization is only supported for `driver`, `driver-debug`, `360`, and `360_forward_upon_wide` renders."
        )

    return ClipPlan(
        render_type=request.render_type,
        route=parsed.route,
        start_seconds=parsed.start_seconds,
        length_seconds=parsed.length_seconds,
        target_mb=normalize_target_mb(request.target_mb, request.execution_context),
        file_format=normalize_output_format(request.render_type, request.file_format),
        output_path=Path(request.output_path).expanduser().resolve(),
        data_dir=resolve_data_dir(parsed.route, request.data_root, request.explicit_data_dir),
        download_file_types=select_download_file_types(
            request.render_type,
            qcam=request.qcam,
            forward_upon_wide_h=request.forward_upon_wide_h,
            driver_face_anonymization=request.driver_face_anonymization,
        ),
        decompress_logs=not is_openpilot_render_type(request.render_type),
        smear_seconds=max(0, request.smear_seconds),
        local_acceleration=request.local_acceleration,
        forward_upon_wide_h=request.forward_upon_wide_h,
        jwt_token=request.jwt_token or None,
        openpilot_dir=request.openpilot_dir,
        headless=request.headless,
        qcam=request.qcam,
        driver_face_swap=driver_face_swap,
    )


def run_clip(request: ClipRequest) -> ClipResult:
    plan = build_clip_plan(request)
    plan.output_path.parent.mkdir(parents=True, exist_ok=True)
    if plan.output_path.exists():
        plan.output_path.unlink()

    if not request.skip_download:
        route_downloader.downloadSegments(
            route_or_segment=plan.route,
            start_seconds=plan.start_seconds,
            length=plan.length_seconds,
            smear_seconds=plan.smear_seconds,
            data_dir=plan.data_dir,
            file_types=list(plan.download_file_types),
            jwt_token=plan.jwt_token,
            decompress_logs=plan.decompress_logs,
        )

    if is_ui_render_type(plan.render_type):
        ui_result = ui_renderer.render_ui_clip(
            ui_renderer.UIRenderOptions(
                route=plan.route,
                start_seconds=plan.start_seconds,
                length_seconds=plan.length_seconds,
                smear_seconds=plan.smear_seconds,
                target_mb=plan.target_mb,
                file_format=plan.file_format,
                output_path=str(plan.output_path),
                data_dir=str(plan.data_dir),
                jwt_token=plan.jwt_token,
                openpilot_dir=plan.openpilot_dir,
                headless=plan.headless,
                layout_mode="alt" if plan.render_type == "ui-alt" else "default",
                qcam=plan.qcam,
                acceleration=plan.local_acceleration,
            )
        )
        return ClipResult(
            output_path=ui_result.output_path,
            route=plan.route,
            render_type=plan.render_type,
            data_dir=plan.data_dir,
            file_format=plan.file_format,
        )

    if plan.render_type == "driver-debug":
        driver_debug_result = driver_debug_renderer.render_driver_debug_clip(
            driver_debug_renderer.DriverDebugRenderOptions(
                route=plan.route,
                start_seconds=plan.start_seconds,
                length_seconds=plan.length_seconds,
                smear_seconds=plan.smear_seconds,
                target_mb=plan.target_mb,
                file_format=plan.file_format,
                output_path=str(plan.output_path),
                data_dir=str(plan.data_dir),
                jwt_token=plan.jwt_token,
                openpilot_dir=plan.openpilot_dir,
                headless=plan.headless,
                route_or_url=request.route_or_url,
                acceleration=plan.local_acceleration,
                driver_face_swap=plan.driver_face_swap,
            )
        )
        return ClipResult(
            output_path=driver_debug_result.output_path,
            route=plan.route,
            render_type=plan.render_type,
            data_dir=plan.data_dir,
            file_format=plan.file_format,
        )

    if plan.render_type == "driver" and has_driver_face_anonymization(plan.driver_face_swap):
        output_path = render_anonymized_driver_backing_video(
            route=plan.route,
            route_or_url=request.route_or_url,
            start_seconds=plan.start_seconds,
            length_seconds=plan.length_seconds,
            data_dir=str(plan.data_dir),
            openpilot_dir=plan.openpilot_dir,
            acceleration=plan.local_acceleration,
            output_path=str(plan.output_path),
            options=plan.driver_face_swap,
            jwt_token=plan.jwt_token,
        )
        return ClipResult(
            output_path=output_path,
            route=plan.route,
            render_type=plan.render_type,
            data_dir=plan.data_dir,
            file_format="h264",
            acceleration="facefusion",
        )

    if plan.render_type in ("360", "360_forward_upon_wide") and has_driver_face_anonymization(plan.driver_face_swap):
        with tempfile.TemporaryDirectory(prefix="driver-face-360-backing-") as backing_root:
            backing_output_path = Path(backing_root) / "driver-backing.mp4"
            backing_video_path = render_anonymized_driver_backing_video(
                route=plan.route,
                route_or_url=request.route_or_url,
                start_seconds=plan.start_seconds,
                length_seconds=plan.length_seconds,
                data_dir=str(plan.data_dir),
                openpilot_dir=plan.openpilot_dir,
                acceleration=plan.local_acceleration,
                output_path=str(backing_output_path),
                options=plan.driver_face_swap,
                jwt_token=plan.jwt_token,
                render_banner=False,
            )
            backing_selection_report_path = backing_video_path.with_name(f"{backing_video_path.stem}.driver-face-selection.json")
            equirect_banner_text = ""
            driver_watermark_track: dict[str, object] | None = None
            if backing_selection_report_path.exists():
                try:
                    selection_report = json.loads(backing_selection_report_path.read_text())
                    equirect_banner_text = str(selection_report.get("banner_text") or "")
                    seats = selection_report.get("seats")
                    if isinstance(seats, dict):
                        for seat_report in seats.values():
                            if isinstance(seat_report, dict) and seat_report.get("seat_role") == "driver":
                                overlay_track = seat_report.get("overlay_track")
                                if isinstance(overlay_track, dict):
                                    driver_watermark_track = overlay_track
                                    break
                except (json.JSONDecodeError, OSError, TypeError, ValueError):
                    equirect_banner_text = ""
                    driver_watermark_track = None
            video_result = video_renderer.render_video_clip(
                video_renderer.VideoRenderOptions(
                    render_type=plan.render_type,
                    data_dir=str(plan.data_dir),
                    route_or_segment=plan.route,
                    start_seconds=plan.start_seconds,
                    length_seconds=plan.length_seconds,
                    target_mb=plan.target_mb,
                    file_format=plan.file_format,
                    acceleration=plan.local_acceleration,
                    forward_upon_wide_h=plan.forward_upon_wide_h,
                    openpilot_dir=plan.openpilot_dir,
                    output_path=str(plan.output_path),
                    driver_input_path=str(backing_video_path),
                    driver_watermark_text=equirect_banner_text,
                    driver_watermark_track=driver_watermark_track,
                )
            )
            final_selection_report_path = video_result.output_path.with_name(
                f"{video_result.output_path.stem}.driver-face-selection.json"
            )
            if backing_selection_report_path.exists():
                if final_selection_report_path.exists():
                    final_selection_report_path.unlink()
                shutil.copy2(backing_selection_report_path, final_selection_report_path)
            elif final_selection_report_path.exists():
                final_selection_report_path.unlink()
        return ClipResult(
            output_path=video_result.output_path,
            route=plan.route,
            render_type=plan.render_type,
            data_dir=plan.data_dir,
            file_format=plan.file_format,
            acceleration=video_result.acceleration,
        )

    video_result = video_renderer.render_video_clip(
        video_renderer.VideoRenderOptions(
            render_type=plan.render_type,
            data_dir=str(plan.data_dir),
            route_or_segment=plan.route,
            start_seconds=plan.start_seconds,
            length_seconds=plan.length_seconds,
            target_mb=plan.target_mb,
            file_format=plan.file_format,
            acceleration=plan.local_acceleration,
            forward_upon_wide_h=plan.forward_upon_wide_h,
            openpilot_dir=plan.openpilot_dir,
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
