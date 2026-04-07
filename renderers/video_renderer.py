from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np

from core.forward_upon_wide import (
    DEFAULT_FORWARD_UPON_WIDE_H,
    DEFAULT_FORWARD_UPON_WIDE_SCALE,
    ForwardUponWideHInput,
    ForwardUponWideLayout,
    ForwardUponWideWarp,
    is_auto_forward_upon_wide,
    parse_forward_upon_wide_h,
    resolve_auto_forward_upon_wide_layout,
    resolve_auto_forward_upon_wide_warp,
)

RenderType = Literal[
    "forward",
    "wide",
    "driver",
    "360",
    "forward_upon_wide",
    "360_forward_upon_wide",
]
OutputFormat = Literal["h264", "hevc"]
AccelerationPolicy = Literal["auto", "cpu", "videotoolbox", "nvidia"]


@dataclass(frozen=True)
class VideoRenderOptions:
    render_type: RenderType
    data_dir: str
    route_or_segment: str
    start_seconds: int
    length_seconds: int
    target_mb: int
    file_format: OutputFormat
    acceleration: AccelerationPolicy = "auto"
    forward_upon_wide_h: ForwardUponWideHInput = DEFAULT_FORWARD_UPON_WIDE_H
    openpilot_dir: str = ""
    output_path: str = "./shared/cog-clip.mp4"
    driver_input_path: str | None = None
    driver_watermark_text: str = ""
    driver_watermark_track: dict[str, Any] | None = None


@dataclass(frozen=True)
class VideoAcceleration:
    name: AccelerationPolicy
    decoder_args: tuple[str, ...]
    encoder_args: tuple[str, ...]


@dataclass(frozen=True)
class VideoRenderResult:
    output_path: Path
    acceleration: AccelerationPolicy


def _normalize_route(route_or_segment: str) -> str:
    return re.sub(r"--\d{1,4}$", "", route_or_segment)


def _route_date(route: str) -> str:
    return route.split("|", 1)[1]


def _segment_numbers(start_seconds: int, length_seconds: int) -> list[int]:
    return list(range(start_seconds // 60, (start_seconds + length_seconds) // 60 + 1))


def _concat_string(data_dir: str, route: str, segments: list[int], filename: str) -> str:
    route_date = _route_date(route)
    inputs = [f"{data_dir}/{route_date}--{segment}/{filename}" for segment in segments]
    return f"concat:{'|'.join(inputs)}"


def _segment_file_path(data_dir: str, route: str, segment: int, filename: str) -> Path:
    return Path(data_dir) / f"{_route_date(route)}--{segment}" / filename


def _probe_video_dimensions(path: Path) -> tuple[int, int] | None:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
        stream = data["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _manual_forward_upon_wide_layout(
    *,
    forward_dimensions: tuple[int, int],
    wide_dimensions: tuple[int, int],
    output_scale: int,
    forward_upon_wide_h: float,
) -> ForwardUponWideLayout:
    wide_width = wide_dimensions[0] * output_scale
    wide_height = wide_dimensions[1] * output_scale
    overlay_width = max(1, int(round(forward_dimensions[0] * DEFAULT_FORWARD_UPON_WIDE_SCALE * output_scale)))
    overlay_height = max(1, int(round(forward_dimensions[1] * DEFAULT_FORWARD_UPON_WIDE_SCALE * output_scale)))
    x = max(0, min(wide_width - overlay_width, int(round((wide_width - overlay_width) / 2))))
    y = max(0, min(wide_height - overlay_height, int(round((wide_height - overlay_height) / forward_upon_wide_h))))
    return ForwardUponWideLayout(
        overlay_width=overlay_width,
        overlay_height=overlay_height,
        x=x,
        y=y,
        source=f"manual/{forward_upon_wide_h}",
    )


def _resolve_forward_upon_wide_layout(
    opts: VideoRenderOptions,
    *,
    route: str,
    forward_dimensions: tuple[int, int],
    wide_dimensions: tuple[int, int],
    output_scale: int,
) -> ForwardUponWideLayout:
    if is_auto_forward_upon_wide(opts.forward_upon_wide_h):
        layout = resolve_auto_forward_upon_wide_layout(
            route,
            data_dir=opts.data_dir,
            openpilot_dir=opts.openpilot_dir,
            forward_dimensions=forward_dimensions,
            wide_dimensions=wide_dimensions,
            output_scale=output_scale,
        )
        if layout is not None:
            return layout
        return _manual_forward_upon_wide_layout(
            forward_dimensions=forward_dimensions,
            wide_dimensions=wide_dimensions,
            output_scale=output_scale,
            forward_upon_wide_h=DEFAULT_FORWARD_UPON_WIDE_H,
        )

    return _manual_forward_upon_wide_layout(
        forward_dimensions=forward_dimensions,
        wide_dimensions=wide_dimensions,
        output_scale=output_scale,
        forward_upon_wide_h=float(opts.forward_upon_wide_h),
    )


def _forward_upon_wide_filter(layout: ForwardUponWideLayout) -> str:
    return (
        f"[1:v]scale={layout.overlay_width}:{layout.overlay_height},format=yuva420p,"
        f"colorchannelmixer=aa=1[front];[0:v][front]overlay={layout.x}:{layout.y}[vout]"
    )


def _format_filter_float(value: float) -> str:
    text = f"{value:.6f}"
    text = text.rstrip("0").rstrip(".")
    return text if text else "0"


def _forward_upon_wide_warp_options(warp: ForwardUponWideWarp) -> str:
    return (
        f"x0={_format_filter_float(warp.x0)}:y0={_format_filter_float(warp.y0)}:"
        f"x1={_format_filter_float(warp.x1)}:y1={_format_filter_float(warp.y1)}:"
        f"x2={_format_filter_float(warp.x2)}:y2={_format_filter_float(warp.y2)}:"
        f"x3={_format_filter_float(warp.x3)}:y3={_format_filter_float(warp.y3)}:"
        "sense=destination:interpolation=cubic"
    )


def _forward_upon_wide_warp_chain(warp: ForwardUponWideWarp, *, source_stream_label: str, output_label: str) -> str:
    perspective = _forward_upon_wide_warp_options(warp)
    return (
        f"color=white:size={warp.canvas_width}x{warp.canvas_height}[masksrc];"
        f"{source_stream_label}scale={warp.canvas_width}:{warp.canvas_height},format=rgba,"
        f"perspective={perspective}[front_rgb];"
        f"[masksrc]format=gray,drawbox=x=0:y=0:w=iw:h=ih:color=black:t=2,"
        f"perspective={perspective}[front_a];"
        f"[front_rgb][front_a]alphamerge[{output_label}]"
    )


def _target_bitrate(target_mb: int, length_seconds: int) -> int:
    return target_mb * 8 * 1024 * 1024 // length_seconds


def _run_logged(command: list[str]) -> None:
    print(f"+ {' '.join(command)}")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    try:
        for line in process.stdout:
            print(line.rstrip())
    except KeyboardInterrupt:
        process.kill()
        raise
    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)


def _has_nvidia() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False
    return subprocess.run([nvidia_smi, "-L"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def select_video_acceleration(policy: AccelerationPolicy, file_format: OutputFormat) -> VideoAcceleration:
    if policy == "auto":
        if platform.system() == "Darwin":
            policy = "videotoolbox"
        elif _has_nvidia():
            policy = "nvidia"
        else:
            policy = "cpu"

    if policy == "nvidia":
        encoder = ("-c:v", "h264_nvenc") if file_format == "h264" else ("-c:v", "hevc_nvenc", "-vtag", "hvc1")
        return VideoAcceleration(name="nvidia", decoder_args=("-hwaccel", "auto"), encoder_args=encoder)

    if policy == "videotoolbox":
        encoder = ("-c:v", "h264_videotoolbox") if file_format == "h264" else ("-c:v", "hevc_videotoolbox", "-vtag", "hvc1")
        return VideoAcceleration(name="videotoolbox", decoder_args=(), encoder_args=encoder)

    if policy == "cpu":
        encoder = ("-c:v", "libx264") if file_format == "h264" else ("-c:v", "libx265", "-vtag", "hvc1")
        return VideoAcceleration(name="cpu", decoder_args=(), encoder_args=encoder)

    raise ValueError(f"Unsupported acceleration policy: {policy}")


def _encoder_output_args(accel: VideoAcceleration, target_bps: int, output_path: str) -> list[str]:
    return [
        *accel.encoder_args,
        "-b:v",
        str(target_bps),
        "-maxrate",
        str(target_bps),
        "-bufsize",
        str(target_bps * 2),
        "-movflags",
        "+faststart",
        output_path,
    ]


def _dict_box_to_int_tuple(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        return int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"])
    except (KeyError, TypeError, ValueError):
        return None


def _driver_watermark_lines(text: str) -> list[str]:
    words = text.split()
    if len(words) <= 2:
        return [text]
    midpoint = max(1, len(words) // 2)
    return [" ".join(words[:midpoint]), " ".join(words[midpoint:])]


def _write_driver_watermark_frames(
    output_dir: Path,
    text: str,
    *,
    frame_width: int,
    frame_height: int,
    frame_count: int,
    track: dict[str, Any],
) -> str:
    font = cv2.FONT_HERSHEY_DUPLEX
    font_scale = max(0.9, min(1.45, frame_height / 540.0))
    thickness = max(2, int(round(frame_height / 260.0)))
    lines = _driver_watermark_lines(text)
    metrics = [cv2.getTextSize(line, font, font_scale, thickness) for line in lines]
    text_w = max(size[0] for size, _baseline in metrics)
    text_h = max(size[1] for size, _baseline in metrics)
    baseline = max(line_baseline for _size, line_baseline in metrics)
    line_gap = max(6, int(round(frame_height / 120.0))) if len(lines) > 1 else 0
    total_text_h = (text_h * len(lines)) + (line_gap * max(0, len(lines) - 1))
    frames = list(track.get("frames", []))
    output_dir.mkdir(parents=True, exist_ok=True)

    for frame_index in range(frame_count):
        frame = np.zeros((frame_height, frame_width, 4), dtype=np.uint8)
        row = frames[min(frame_index, len(frames) - 1)] if frames else {}
        rect = _dict_box_to_int_tuple(row.get("crop_rect")) or _dict_box_to_int_tuple(row.get("padded_box"))
        if rect is not None:
            x, y, w, _h = rect
            pad_x = max(12, int(round(frame_width / 96.0)))
            pad_y = max(8, int(round(frame_height / 120.0)))
            box_w = text_w + (pad_x * 2)
            box_h = total_text_h + baseline + (pad_y * 2)
            box_x = max(10, min(frame_width - box_w - 10, x + max(0, (w - box_w) // 2)))
            preferred_box_y = y - box_h - 12
            if preferred_box_y < 10:
                box_y = min(frame_height - box_h - 10, y + _h + 12)
            else:
                box_y = preferred_box_y
            overlay = frame.copy()
            cv2.rectangle(overlay, (box_x, box_y), (box_x + box_w, box_y + box_h), (0, 235, 255, 196), thickness=-1)
            cv2.rectangle(overlay, (box_x, box_y), (box_x + box_w, box_y + box_h), (0, 0, 0, 228), thickness=max(2, thickness))
            frame = cv2.addWeighted(overlay, 1.0, frame, 1.0, 0.0)
            current_y = box_y + pad_y + text_h
            for line in lines:
                line_w = cv2.getTextSize(line, font, font_scale, thickness)[0][0]
                text_x = box_x + max(pad_x, (box_w - line_w) // 2)
                cv2.putText(frame, line, (text_x, current_y), font, font_scale, (0, 0, 0, 255), thickness, cv2.LINE_AA)
                current_y += text_h + line_gap
        frame_path = output_dir / f"watermark-{frame_index:05d}.png"
        if not cv2.imwrite(str(frame_path), frame):
            raise RuntimeError(f"Failed to write driver watermark frame to {frame_path}")

    return str((output_dir / "watermark-%05d.png").resolve())


def _simple_render_command(opts: VideoRenderOptions, accel: VideoAcceleration, ffmpeg_input: str) -> list[str]:
    start_seconds_relative = opts.start_seconds % 60
    target_bps = _target_bitrate(opts.target_mb, opts.length_seconds)
    return [
        "ffmpeg",
        "-y",
        *accel.decoder_args,
        "-probesize",
        "100M",
        "-r",
        "20",
        "-vsync",
        "0",
        "-i",
        ffmpeg_input,
        "-t",
        str(opts.length_seconds),
        "-ss",
        str(start_seconds_relative),
        *(_encoder_output_args(accel, target_bps, opts.output_path)),
    ]


def _complex_render_command(
    opts: VideoRenderOptions,
    accel: VideoAcceleration,
    inputs: list[str],
    filter_complex: str,
    *,
    apply_output_seek: bool = True,
) -> list[str]:
    start_seconds_relative = opts.start_seconds % 60
    target_bps = _target_bitrate(opts.target_mb, opts.length_seconds)
    command = ["ffmpeg", "-y"]
    for ffmpeg_input in inputs:
        command.extend([*accel.decoder_args, "-probesize", "100M", "-r", "20", "-i", ffmpeg_input])
    command.extend(["-t", str(opts.length_seconds), "-filter_complex", filter_complex, "-map", "[vout]"])
    if apply_output_seek:
        command.extend(["-ss", str(start_seconds_relative)])
    command.extend(_encoder_output_args(accel, target_bps, opts.output_path))
    return command


def _complex_render_command_with_watermark(
    opts: VideoRenderOptions,
    accel: VideoAcceleration,
    inputs: list[str],
    watermark_pattern: str,
    filter_complex: str,
    *,
    apply_output_seek: bool = True,
) -> list[str]:
    start_seconds_relative = opts.start_seconds % 60
    target_bps = _target_bitrate(opts.target_mb, opts.length_seconds)
    command = ["ffmpeg", "-y"]
    for ffmpeg_input in inputs:
        command.extend([*accel.decoder_args, "-probesize", "100M", "-r", "20", "-i", ffmpeg_input])
    command.extend(["-framerate", "20", "-i", watermark_pattern])
    command.extend(["-t", str(opts.length_seconds), "-filter_complex", filter_complex, "-map", "[vout]"])
    if apply_output_seek:
        command.extend(["-ss", str(start_seconds_relative)])
    command.extend(_encoder_output_args(accel, target_bps, opts.output_path))
    return command


def _inject_360_metadata(output_path: Path) -> None:
    import spatialmedia

    temp_output = output_path.with_suffix(".temp.mp4")
    if temp_output.exists():
        temp_output.unlink()
    output_path.rename(temp_output)
    metadata = spatialmedia.metadata_utils.Metadata()
    metadata.video = spatialmedia.metadata_utils.generate_spherical_xml("none", None)
    spatialmedia.metadata_utils.inject_metadata(str(temp_output), str(output_path), metadata, print)
    temp_output.unlink()


def render_video_clip(opts: VideoRenderOptions) -> VideoRenderResult:
    if not os.path.exists(opts.data_dir):
        raise ValueError(f"Invalid data_dir: {opts.data_dir}")

    route = _normalize_route(opts.route_or_segment)
    segments = _segment_numbers(opts.start_seconds, opts.length_seconds)
    accel = select_video_acceleration(opts.acceleration, opts.file_format)

    forward_input = _concat_string(opts.data_dir, route, segments, "fcamera.hevc")
    wide_input = _concat_string(opts.data_dir, route, segments, "ecamera.hevc")
    driver_input = str(Path(opts.driver_input_path).expanduser().resolve()) if opts.driver_input_path else _concat_string(
        opts.data_dir, route, segments, "dcamera.hevc"
    )
    first_segment = segments[0]
    driver_probe_path = (
        Path(opts.driver_input_path).expanduser().resolve()
        if opts.driver_input_path
        else _segment_file_path(opts.data_dir, route, first_segment, "dcamera.hevc")
    )
    driver_dimensions = _probe_video_dimensions(driver_probe_path)
    forward_dimensions = _probe_video_dimensions(_segment_file_path(opts.data_dir, route, first_segment, "fcamera.hevc"))
    wide_dimensions = _probe_video_dimensions(_segment_file_path(opts.data_dir, route, first_segment, "ecamera.hevc"))
    if wide_dimensions is None:
        wide_dimensions = (1928, 1208)
    if driver_dimensions is None:
        driver_dimensions = wide_dimensions
    if forward_dimensions is None:
        forward_dimensions = wide_dimensions
    driver_width = driver_dimensions[0] if driver_dimensions is not None else wide_dimensions[0]
    wide_height = wide_dimensions[1] if wide_dimensions is not None else 1208
    watermark_pattern: str | None = None
    watermark_root: Path | None = None
    if (
        opts.driver_watermark_text
        and opts.driver_watermark_track
        and opts.render_type in ("360", "360_forward_upon_wide")
    ):
        temp_root = Path(tempfile.mkdtemp(prefix="driver-watermark-"))
        watermark_root = temp_root
        watermark_width = driver_width * (2 if opts.render_type == "360_forward_upon_wide" else 1)
        watermark_height = wide_height * (2 if opts.render_type == "360_forward_upon_wide" else 1)
        watermark_pattern = _write_driver_watermark_frames(
            temp_root,
            opts.driver_watermark_text,
            frame_width=watermark_width,
            frame_height=watermark_height,
            frame_count=max(1, int(round(opts.length_seconds * 20))),
            track=opts.driver_watermark_track,
        )

    try:
        if opts.render_type == "forward":
            command = _simple_render_command(opts, accel, forward_input)
        elif opts.render_type == "wide":
            command = _simple_render_command(opts, accel, wide_input)
        elif opts.render_type == "driver":
            command = _simple_render_command(opts, accel, driver_input)
        elif opts.render_type == "forward_upon_wide":
            warp = None
            if is_auto_forward_upon_wide(opts.forward_upon_wide_h):
                warp = resolve_auto_forward_upon_wide_warp(
                    route,
                    data_dir=opts.data_dir,
                    openpilot_dir=opts.openpilot_dir,
                    forward_dimensions=forward_dimensions,
                    wide_dimensions=wide_dimensions,
                    output_scale=1,
                )
            if warp is not None:
                filter_complex = f"{_forward_upon_wide_warp_chain(warp, source_stream_label='[1:v]', output_label='front')};[0:v][front]overlay=0:0[vout]"
            else:
                layout = _resolve_forward_upon_wide_layout(
                    opts,
                    route=route,
                    forward_dimensions=forward_dimensions,
                    wide_dimensions=wide_dimensions,
                    output_scale=1,
                )
                filter_complex = _forward_upon_wide_filter(layout)
            command = _complex_render_command(
                opts,
                accel,
                [wide_input, forward_input],
                filter_complex,
            )
        elif opts.render_type == "360":
            if opts.driver_input_path:
                driver_chain = (
                    f"[0:v]trim=start=0:duration={opts.length_seconds},setpts=PTS-STARTPTS,"
                    f"pad=iw:ih+290:0:290:color=#160000,crop=iw:{wide_height}[driver_raw]"
                )
                apply_output_seek = False
            else:
                driver_chain = f"[0:v]pad=iw:ih+290:0:290:color=#160000,crop=iw:{wide_height}[driver_raw]"
                apply_output_seek = True
            if watermark_pattern is not None:
                driver_chain = f"{driver_chain};[driver_raw][2:v]overlay=0:0[driver]"
            else:
                driver_chain = f"{driver_chain};[driver_raw]copy[driver]"
            filter_complex = (
                f"{driver_chain};"
                f"[1:v]trim=start={opts.start_seconds % 60}:duration={opts.length_seconds},setpts=PTS-STARTPTS[wide];"
                f"[driver][wide]hstack=inputs=2[v];"
                "[v]v360=dfisheye:equirect:ih_fov=195:iv_fov=122[vout]"
                if opts.driver_input_path
                else f"{driver_chain};[driver][1:v]hstack=inputs=2[v];[v]v360=dfisheye:equirect:ih_fov=195:iv_fov=122[vout]"
            )
            if watermark_pattern is not None:
                command = _complex_render_command_with_watermark(
                    opts,
                    accel,
                    [driver_input, wide_input],
                    watermark_pattern,
                    filter_complex,
                    apply_output_seek=apply_output_seek,
                )
            else:
                command = _complex_render_command(
                    opts,
                    accel,
                    [driver_input, wide_input],
                    filter_complex,
                    apply_output_seek=apply_output_seek,
                )
        elif opts.render_type == "360_forward_upon_wide":
            warp = None
            if is_auto_forward_upon_wide(opts.forward_upon_wide_h):
                warp = resolve_auto_forward_upon_wide_warp(
                    route,
                    data_dir=opts.data_dir,
                    openpilot_dir=opts.openpilot_dir,
                    forward_dimensions=forward_dimensions,
                    wide_dimensions=wide_dimensions,
                    output_scale=2,
                )
            if opts.driver_input_path:
                driver_chain = (
                    f"[0:v]trim=start=0:duration={opts.length_seconds},setpts=PTS-STARTPTS,"
                    f"scale=iw*2:ih*2,pad=iw:ih+290:0:290:color=#160000,crop=iw:{wide_height * 2}[driver_raw]"
                )
                apply_output_seek = False
            else:
                driver_chain = (
                    f"[0:v]scale=iw*2:ih*2,pad=iw:ih+290:0:290:color=#160000,crop=iw:{wide_height * 2}[driver_raw]"
                )
                apply_output_seek = True
            if watermark_pattern is not None:
                watermark_input_label = "[3:v]"
                driver_chain = f"{driver_chain};[driver_raw]{watermark_input_label}overlay=0:0[driver]"
            else:
                driver_chain = f"{driver_chain};[driver_raw]copy[driver]"
            if warp is not None:
                if opts.driver_input_path:
                    fuw_chain = (
                        f"[1:v]trim=start={opts.start_seconds % 60}:duration={opts.length_seconds},setpts=PTS-STARTPTS,"
                        "scale=iw*2:ih*2[wide];"
                        f"[2:v]trim=start={opts.start_seconds % 60}:duration={opts.length_seconds},setpts=PTS-STARTPTS[forward];"
                        f"{_forward_upon_wide_warp_chain(warp, source_stream_label='[forward]', output_label='front')};"
                        "[wide][front]overlay=0:0[fuw]"
                    )
                else:
                    fuw_chain = (
                        "[1:v]scale=iw*2:ih*2[wide];"
                        f"{_forward_upon_wide_warp_chain(warp, source_stream_label='[2:v]', output_label='front')};"
                        "[wide][front]overlay=0:0[fuw]"
                    )
            else:
                layout = _resolve_forward_upon_wide_layout(
                    opts,
                    route=route,
                    forward_dimensions=forward_dimensions,
                    wide_dimensions=wide_dimensions,
                    output_scale=2,
                )
                if opts.driver_input_path:
                    fuw_chain = (
                        f"[2:v]trim=start={opts.start_seconds % 60}:duration={opts.length_seconds},setpts=PTS-STARTPTS,"
                        f"scale={layout.overlay_width}:{layout.overlay_height},format=yuva420p,colorchannelmixer=aa=1[front];"
                        f"[1:v]trim=start={opts.start_seconds % 60}:duration={opts.length_seconds},setpts=PTS-STARTPTS,"
                        "scale=iw*2:ih*2[wide];"
                        f"[wide][front]overlay={layout.x}:{layout.y}[fuw]"
                    )
                else:
                    fuw_chain = (
                        f"[2:v]scale={layout.overlay_width}:{layout.overlay_height},format=yuva420p,colorchannelmixer=aa=1[front];"
                        "[1:v]scale=iw*2:ih*2[wide];"
                        f"[wide][front]overlay={layout.x}:{layout.y}[fuw]"
                    )
            filter_complex = (
                f"{fuw_chain};{driver_chain};"
                "[driver][fuw]hstack=inputs=2[v];"
                "[v]v360=dfisheye:equirect:ih_fov=195:iv_fov=122[vout]"
            )
            if watermark_pattern is not None:
                command = _complex_render_command_with_watermark(
                    opts,
                    accel,
                    [driver_input, wide_input, forward_input],
                    watermark_pattern,
                    filter_complex,
                    apply_output_seek=apply_output_seek,
                )
            else:
                command = _complex_render_command(
                    opts,
                    accel,
                    [driver_input, wide_input, forward_input],
                    filter_complex,
                    apply_output_seek=apply_output_seek,
                )
        else:
            raise ValueError(f"Invalid render_type: {opts.render_type}")

        _run_logged(command)
    finally:
        if watermark_root is not None and watermark_root.exists():
            shutil.rmtree(watermark_root, ignore_errors=True)

    output_path = Path(opts.output_path).resolve()
    if opts.render_type in ("360", "360_forward_upon_wide"):
        _inject_360_metadata(output_path)
    return VideoRenderResult(output_path=output_path, acceleration=accel.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render non-UI clips with ffmpeg")
    parser.add_argument("--render-type", "-t", choices=[
        "forward",
        "wide",
        "driver",
        "360",
        "forward_upon_wide",
        "360_forward_upon_wide",
    ], default="forward")
    parser.add_argument("--data-dir", default="shared/data_dir")
    parser.add_argument("--openpilot-dir", default="")
    parser.add_argument("route_or_segment")
    parser.add_argument("start_seconds", type=int)
    parser.add_argument("length_seconds", type=int)
    parser.add_argument("--file-size-mb", type=int, default=25)
    parser.add_argument("--forward-upon-wide-h", type=parse_forward_upon_wide_h, default=DEFAULT_FORWARD_UPON_WIDE_H)
    parser.add_argument("--accel", choices=["auto", "cpu", "videotoolbox", "nvidia"], default="auto")
    parser.add_argument("--format", choices=["h264", "hevc"], default="h264")
    parser.add_argument("--output", default="./shared/cog-clip.mp4")
    args = parser.parse_args()

    render_video_clip(
        VideoRenderOptions(
            render_type=args.render_type,
            data_dir=args.data_dir,
            route_or_segment=args.route_or_segment,
            start_seconds=args.start_seconds,
            length_seconds=args.length_seconds,
            target_mb=args.file_size_mb,
            file_format=args.format,
            acceleration=args.accel,
            forward_upon_wide_h=args.forward_upon_wide_h,
            openpilot_dir=args.openpilot_dir,
            output_path=args.output,
        )
    )
