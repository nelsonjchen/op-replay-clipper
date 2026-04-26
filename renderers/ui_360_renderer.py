from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path

from core.openpilot_integration import apply_openpilot_runtime_patches
from core.render_runtime import configure_ui_environment, temporary_headless_display
from renderers import path_overlay_360, ui_renderer, video_renderer


REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY_WORKER = REPO_ROOT / "scripts/render_360_ui_overlay_worker.py"


def _video_dimensions_or_fail(path: Path, label: str) -> tuple[int, int]:
    dimensions = video_renderer._probe_video_dimensions(path)
    if dimensions is None:
        raise RuntimeError(f"Could not probe {label} dimensions from {path}")
    return dimensions


def _qcamera_audio_input(data_dir: Path, route: str, segments: list[int]) -> str | None:
    qcamera_paths = [path_overlay_360.segment_file_path(data_dir, route, segment, "qcamera.ts") for segment in segments]
    if not all(path.exists() for path in qcamera_paths):
        return None
    return path_overlay_360.concat_string(data_dir, route, segments, "qcamera.ts")


def _run_worker(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print(f"+ {' '.join(command)}")
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    try:
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
    except KeyboardInterrupt:
        process.kill()
        raise
    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)


def _generate_ui_overlay_sequence(
    *,
    route: str,
    start_seconds: int,
    length_seconds: int,
    data_dir: Path,
    openpilot_dir: Path,
    overlay_dir: Path,
    frame_width: int,
    frame_height: int,
    acceleration: video_renderer.AccelerationPolicy,
) -> str:
    print("360-ui: loading route logs and rendering openpilot HUD/path overlays...")
    env = configure_ui_environment(acceleration=acceleration)
    use_headless_display = os.name != "nt" and "DISPLAY" not in env
    command = [
        *ui_renderer._openpilot_python_cmd(openpilot_dir),
        str(OVERLAY_WORKER),
        route,
        str(start_seconds),
        str(length_seconds),
        "--data-dir",
        str(data_dir),
        "--openpilot-dir",
        str(openpilot_dir),
        "--output-dir",
        str(overlay_dir),
        "--frame-width",
        str(frame_width),
        "--frame-height",
        str(frame_height),
    ]
    with temporary_headless_display(env, enabled=use_headless_display) as render_env:
        _run_worker(command, cwd=REPO_ROOT, env=render_env)
    return str((overlay_dir / "overlay-%05d.png").resolve())


def build_360_ui_filter_complex(
    *,
    start_seconds: int,
    length_seconds: int,
    wide_height: int,
    driver_input_is_pretrimmed: bool = False,
    has_driver_watermark: bool = False,
) -> str:
    start_offset = start_seconds % 60
    driver_start = 0 if driver_input_is_pretrimmed else start_offset
    driver_chain = (
        f"[0:v]trim=start={driver_start}:duration={length_seconds},setpts=PTS-STARTPTS,"
        f"pad=iw:ih+290:0:290:color=#160000,crop=iw:{wide_height}[driver_raw]"
    )
    driver_label = "[driver_raw][3:v]overlay=0:0[driver]" if has_driver_watermark else "[driver_raw]copy[driver]"
    return (
        f"{driver_chain};"
        f"{driver_label};"
        f"[1:v]trim=start={start_offset}:duration={length_seconds},setpts=PTS-STARTPTS[wide];"
        "[2:v]format=rgba,setpts=PTS-STARTPTS[ui];"
        "[wide][ui]overlay=0:0:format=auto[wide_ui];"
        "[driver][wide_ui]hstack=inputs=2[v];"
        "[v]v360=dfisheye:equirect:ih_fov=195:iv_fov=122[vout]"
    )


def build_360_ui_ffmpeg_command(
    *,
    driver_input: str,
    wide_input: str,
    overlay_pattern: str,
    watermark_pattern: str | None,
    audio_input: str | None,
    start_seconds: int,
    filter_complex: str,
    accel: video_renderer.VideoAcceleration,
    target_mb: int,
    length_seconds: int,
    output_path: str,
) -> list[str]:
    target_bps = video_renderer._target_bitrate(target_mb, length_seconds)
    command = [
        "ffmpeg",
        "-y",
        *accel.decoder_args,
        "-probesize",
        "100M",
        "-r",
        str(path_overlay_360.FRAMERATE),
        "-i",
        driver_input,
        *accel.decoder_args,
        "-probesize",
        "100M",
        "-r",
        str(path_overlay_360.FRAMERATE),
        "-i",
        wide_input,
        "-framerate",
        str(path_overlay_360.FRAMERATE),
        "-i",
        overlay_pattern,
    ]
    if watermark_pattern is not None:
        command.extend(["-framerate", str(path_overlay_360.FRAMERATE), "-i", watermark_pattern])
    audio_input_index = None
    if audio_input is not None:
        audio_input_index = 4 if watermark_pattern is not None else 3
        command.extend(["-ss", str(start_seconds % 60), "-t", str(length_seconds), "-i", audio_input])
    command.extend(
        [
            "-t",
            str(length_seconds),
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
        ]
    )
    if audio_input_index is not None:
        command.extend(["-map", f"{audio_input_index}:a:0?", "-c:a", "aac", "-b:a", "64k", "-shortest"])
    command.extend(video_renderer._encoder_output_args(accel, target_bps, output_path))
    return command


def render_360_ui_clip(opts: video_renderer.VideoRenderOptions) -> video_renderer.VideoRenderResult:
    openpilot_dir = Path(opts.openpilot_dir).expanduser().resolve()
    data_dir = Path(opts.data_dir).expanduser().resolve()
    output_path = Path(opts.output_path).expanduser().resolve()
    route = video_renderer._normalize_route(opts.route_or_segment)
    segments = path_overlay_360.segment_numbers(opts.start_seconds, opts.length_seconds)
    first_segment = segments[0]

    patch_report = apply_openpilot_runtime_patches(openpilot_dir)
    if patch_report.changed:
        print(f"Applied openpilot runtime patches: {patch_report}")
    ui_renderer._ensure_fonts(openpilot_dir)

    wide_probe = path_overlay_360.segment_file_path(data_dir, route, first_segment, "ecamera.hevc")
    wide_width, wide_height = _video_dimensions_or_fail(wide_probe, "wide road camera")
    if opts.driver_input_path:
        driver_input = str(Path(opts.driver_input_path).expanduser().resolve())
        driver_width, _driver_height = _video_dimensions_or_fail(Path(driver_input), "driver backing video")
    else:
        driver_probe = path_overlay_360.segment_file_path(data_dir, route, first_segment, "dcamera.hevc")
        driver_width, _driver_height = _video_dimensions_or_fail(driver_probe, "driver camera")
        driver_input = path_overlay_360.concat_string(data_dir, route, segments, "dcamera.hevc")
    wide_input = path_overlay_360.concat_string(data_dir, route, segments, "ecamera.hevc")
    audio_input = _qcamera_audio_input(data_dir, route, segments)
    if audio_input is not None:
        print("360-ui: muxing qcamera audio track")
    else:
        print("360-ui: no qcamera audio track found; output will be silent")
    accel = video_renderer.select_video_acceleration(opts.acceleration, opts.file_format)

    keep_overlay_artifacts = os.environ.get("OP_REPLAY_KEEP_360_UI_OVERLAYS") == "1"
    temp_context = (
        nullcontext(tempfile.mkdtemp(prefix="360-ui-keep-"))
        if keep_overlay_artifacts
        else tempfile.TemporaryDirectory(prefix="360-ui-")
    )
    with temp_context as temp_root_raw:
        temp_root = Path(temp_root_raw)
        if keep_overlay_artifacts:
            print(f"360-ui: retaining overlay artifacts in {temp_root}")
        overlay_pattern = _generate_ui_overlay_sequence(
            route=route,
            start_seconds=opts.start_seconds,
            length_seconds=opts.length_seconds,
            data_dir=data_dir,
            openpilot_dir=openpilot_dir,
            overlay_dir=temp_root / "overlays",
            frame_width=wide_width,
            frame_height=wide_height,
            acceleration=opts.acceleration,
        )
        watermark_pattern = None
        if opts.driver_watermark_text and opts.driver_watermark_track:
            watermark_pattern = video_renderer._write_driver_watermark_frames(
                temp_root / "driver-watermark",
                opts.driver_watermark_text,
                frame_width=driver_width,
                frame_height=wide_height,
                frame_count=max(1, int(round(opts.length_seconds * path_overlay_360.FRAMERATE))),
                track=opts.driver_watermark_track,
            )

        filter_complex = build_360_ui_filter_complex(
            start_seconds=opts.start_seconds,
            length_seconds=opts.length_seconds,
            wide_height=wide_height,
            driver_input_is_pretrimmed=opts.driver_input_path is not None,
            has_driver_watermark=watermark_pattern is not None,
        )
        command = build_360_ui_ffmpeg_command(
            driver_input=driver_input,
            wide_input=wide_input,
            overlay_pattern=overlay_pattern,
            watermark_pattern=watermark_pattern,
            audio_input=audio_input,
            start_seconds=opts.start_seconds,
            filter_complex=filter_complex,
            accel=accel,
            target_mb=opts.target_mb,
            length_seconds=opts.length_seconds,
            output_path=str(output_path),
        )
        print("360-ui: encoding spherical video...")
        video_renderer._run_logged(command)

    print("360-ui: injecting spherical metadata...")
    video_renderer._inject_360_metadata(output_path)
    output_dimensions = video_renderer._probe_video_dimensions(output_path)
    if output_dimensions is not None:
        print(f"360-ui: output dimensions {output_dimensions[0]}x{output_dimensions[1]}")
    print(f"360-ui: wrote {output_path}")
    return video_renderer.VideoRenderResult(output_path=output_path, acceleration=accel.name)
