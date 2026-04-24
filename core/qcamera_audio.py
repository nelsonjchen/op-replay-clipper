from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


AUDIO_TIMING_TOLERANCE_SECONDS = 0.1
AUDIO_UNAVAILABLE_GUIDANCE = (
    "Audio was requested, but usable qcamera AAC audio is unavailable for this clip. "
    "Enable openpilot audio recording for future drives, or disable include audio for video-only output."
)


class QCameraAudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class QCameraAudioProbe:
    input_spec: str
    codec_name: str
    sample_rate: int | None
    channels: int | None


@dataclass(frozen=True)
class QCameraAudioClip:
    path: Path
    probe: QCameraAudioProbe
    duration_seconds: float


def _route_date(route: str) -> str:
    return route.split("|", 1)[1]


def _normalize_route(route_or_segment: str) -> str:
    return re.sub(r"--\d{1,4}$", "", route_or_segment)


def _segment_numbers(start_seconds: int, length_seconds: int) -> list[int]:
    end_seconds_exclusive = start_seconds + length_seconds
    last_included_second = max(start_seconds, end_seconds_exclusive - 1)
    return list(range(start_seconds // 60, last_included_second // 60 + 1))


def qcamera_segment_paths(data_dir: str | Path, route_or_segment: str, start_seconds: int, length_seconds: int) -> list[Path]:
    route = _normalize_route(route_or_segment)
    route_date = _route_date(route)
    root = Path(data_dir)
    return [root / f"{route_date}--{segment}" / "qcamera.ts" for segment in _segment_numbers(start_seconds, length_seconds)]


def qcamera_concat_input(paths: list[Path]) -> str:
    return f"concat:{'|'.join(str(path) for path in paths)}"


def _audio_error(message: str) -> QCameraAudioError:
    return QCameraAudioError(f"{message} {AUDIO_UNAVAILABLE_GUIDANCE}")


def _run_json(command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise _audio_error(f"qcamera audio probe failed: {detail}.")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise _audio_error(f"qcamera audio probe returned invalid JSON: {exc}.") from exc
    if not isinstance(payload, dict):
        raise _audio_error("qcamera audio probe returned an unexpected response.")
    return payload


def probe_qcamera_audio(data_dir: str | Path, route_or_segment: str, start_seconds: int, length_seconds: int) -> QCameraAudioProbe:
    paths = qcamera_segment_paths(data_dir, route_or_segment, start_seconds, length_seconds)
    missing = [path for path in paths if not path.exists()]
    if missing:
        missing_names = ", ".join(str(path) for path in missing)
        raise _audio_error(f"Missing qcamera file(s): {missing_names}.")

    input_spec = qcamera_concat_input(paths)
    payload = _run_json(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            input_spec,
        ]
    )
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        raise _audio_error("qcamera does not contain an audio stream.")
    stream = streams[0]
    if not isinstance(stream, dict):
        raise _audio_error("qcamera audio stream metadata is malformed.")
    codec_name = str(stream.get("codec_name") or "")
    if codec_name != "aac":
        raise _audio_error(f"qcamera audio stream uses unsupported codec {codec_name or 'unknown'}; expected AAC.")
    sample_rate = _optional_int(stream.get("sample_rate"))
    channels = _optional_int(stream.get("channels"))
    return QCameraAudioProbe(
        input_spec=input_spec,
        codec_name=codec_name,
        sample_rate=sample_rate,
        channels=channels,
    )


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _probe_media_duration(path: Path) -> float:
    payload = _run_json(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
    )
    try:
        return float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _audio_error(f"Extracted qcamera audio did not report a usable duration: {path}.") from exc


def extract_qcamera_audio(
    probe: QCameraAudioProbe,
    *,
    start_seconds: int,
    length_seconds: int,
    output_path: str | Path,
) -> QCameraAudioClip:
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    start_seconds_relative = start_seconds % 60
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-probesize",
        "100M",
        "-i",
        probe.input_spec,
        "-ss",
        str(start_seconds_relative),
        "-t",
        str(length_seconds),
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise _audio_error(f"qcamera audio copy extraction failed: {detail}.")
    duration = _probe_media_duration(output)
    if abs(duration - float(length_seconds)) > AUDIO_TIMING_TOLERANCE_SECONDS:
        raise _audio_error(
            f"Extracted qcamera audio duration {duration:.3f}s does not match requested {length_seconds:.3f}s."
        )
    return QCameraAudioClip(path=output, probe=probe, duration_seconds=duration)


def extract_visible_qcamera_audio(
    *,
    data_dir: str | Path,
    route_or_segment: str,
    start_seconds: int,
    length_seconds: int,
    output_path: str | Path,
) -> QCameraAudioClip:
    probe = probe_qcamera_audio(data_dir, route_or_segment, start_seconds, length_seconds)
    return extract_qcamera_audio(
        probe,
        start_seconds=start_seconds,
        length_seconds=length_seconds,
        output_path=output_path,
    )


def mux_audio_into_video(video_path: str | Path, audio_path: str | Path, output_path: str | Path | None = None) -> Path:
    video = Path(video_path).expanduser().resolve()
    audio = Path(audio_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve() if output_path is not None else video
    temp_output = output.with_name(f"{output.stem}.audio-mux.tmp{output.suffix}")
    if temp_output.exists():
        temp_output.unlink()
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(temp_output),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise _audio_error(f"Audio mux failed: {detail}.")
    temp_output.replace(output)
    return output
