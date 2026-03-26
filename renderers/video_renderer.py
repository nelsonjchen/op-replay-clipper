from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    forward_upon_wide_h: float = 2.2
    output_path: str = "./shared/cog-clip.mp4"


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


def _complex_render_command(opts: VideoRenderOptions, accel: VideoAcceleration, inputs: list[str], filter_complex: str) -> list[str]:
    start_seconds_relative = opts.start_seconds % 60
    target_bps = _target_bitrate(opts.target_mb, opts.length_seconds)
    command = ["ffmpeg", "-y"]
    for ffmpeg_input in inputs:
        command.extend([*accel.decoder_args, "-probesize", "100M", "-r", "20", "-i", ffmpeg_input])
    command.extend(
        [
            "-t",
            str(opts.length_seconds),
            "-ss",
            str(start_seconds_relative),
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            *(_encoder_output_args(accel, target_bps, opts.output_path)),
        ]
    )
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
    driver_input = _concat_string(opts.data_dir, route, segments, "dcamera.hevc")
    first_segment = segments[0]
    wide_dimensions = _probe_video_dimensions(_segment_file_path(opts.data_dir, route, first_segment, "ecamera.hevc"))
    wide_height = wide_dimensions[1] if wide_dimensions is not None else 1208

    if opts.render_type == "forward":
        command = _simple_render_command(opts, accel, forward_input)
    elif opts.render_type == "wide":
        command = _simple_render_command(opts, accel, wide_input)
    elif opts.render_type == "driver":
        command = _simple_render_command(opts, accel, driver_input)
    elif opts.render_type == "forward_upon_wide":
        command = _complex_render_command(
            opts,
            accel,
            [wide_input, forward_input],
            f"[1:v]scale=iw/4.5:ih/4.5,format=yuva420p,colorchannelmixer=aa=1[front];[0:v][front]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/{opts.forward_upon_wide_h}[vout]",
        )
    elif opts.render_type == "360":
        command = _complex_render_command(
            opts,
            accel,
            [driver_input, wide_input],
            f"[0:v]pad=iw:ih+290:0:290:color=#160000,crop=iw:{wide_height}[driver];[driver][1:v]hstack=inputs=2[v];[v]v360=dfisheye:equirect:ih_fov=195:iv_fov=122[vout]",
        )
    elif opts.render_type == "360_forward_upon_wide":
        command = _complex_render_command(
            opts,
            accel,
            [driver_input, wide_input, forward_input],
            f"[2:v]scale=iw/2.25:ih/2.25,format=yuva420p,colorchannelmixer=aa=1[front];[1:v]scale=iw*2:ih*2[wide];[wide][front]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/{opts.forward_upon_wide_h}[fuw];[0:v]scale=iw*2:ih*2,pad=iw:ih+290:0:290:color=#160000,crop=iw:{wide_height * 2}[driver];[driver][fuw]hstack=inputs=2[v];[v]v360=dfisheye:equirect:ih_fov=195:iv_fov=122[vout]",
        )
    else:
        raise ValueError(f"Invalid render_type: {opts.render_type}")

    _run_logged(command)

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
    parser.add_argument("route_or_segment")
    parser.add_argument("start_seconds", type=int)
    parser.add_argument("length_seconds", type=int)
    parser.add_argument("--file-size-mb", type=int, default=25)
    parser.add_argument("--forward-upon-wide-h", type=float, default=2.2)
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
            output_path=args.output,
        )
    )
