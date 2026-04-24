from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from core import qcamera_audio


ROUTE = "dongle|2026-04-08--22-15-52"


def _qcamera_path(tmp_path: Path, segment: int = 1) -> Path:
    path = tmp_path / f"2026-04-08--22-15-52--{segment}" / "qcamera.ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"qcamera")
    return path


def _completed(returncode: int = 0, stdout: str = "{}", stderr: str = "") -> mock.Mock:
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


def test_extract_visible_qcamera_audio_copies_aac_with_valid_timing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _qcamera_path(tmp_path)
    calls: list[list[str]] = []

    def _fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "ffprobe" and "stream=codec_name,sample_rate,channels" in command:
            return _completed(stdout='{"streams":[{"codec_name":"aac","sample_rate":"16000","channels":1}]}')
        if command[0] == "ffmpeg":
            return _completed()
        if command[0] == "ffprobe" and "format=duration" in command:
            return _completed(stdout='{"format":{"duration":"4.050"}}')
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(qcamera_audio.subprocess, "run", _fake_run)

    clip = qcamera_audio.extract_visible_qcamera_audio(
        data_dir=tmp_path,
        route_or_segment=ROUTE,
        start_seconds=61,
        length_seconds=4,
        output_path=tmp_path / "audio.m4a",
    )

    assert clip.probe.codec_name == "aac"
    assert clip.probe.sample_rate == 16000
    assert clip.probe.channels == 1
    assert clip.duration_seconds == 4.05
    ffmpeg_call = next(command for command in calls if command[0] == "ffmpeg")
    assert ffmpeg_call[ffmpeg_call.index("-c:a") + 1] == "copy"
    assert ffmpeg_call[ffmpeg_call.index("-ss") + 1] == "1"
    assert ffmpeg_call[ffmpeg_call.index("-t") + 1] == "4"


def test_qcamera_segment_paths_do_not_require_next_segment_at_exact_boundary(tmp_path: Path) -> None:
    assert qcamera_audio.qcamera_segment_paths(tmp_path, ROUTE, 0, 60) == [
        tmp_path / "2026-04-08--22-15-52--0" / "qcamera.ts"
    ]


def test_probe_qcamera_audio_fails_when_qcamera_is_missing(tmp_path: Path) -> None:
    with pytest.raises(qcamera_audio.QCameraAudioError, match="Missing qcamera"):
        qcamera_audio.probe_qcamera_audio(tmp_path, ROUTE, 61, 4)


def test_probe_qcamera_audio_fails_without_audio_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _qcamera_path(tmp_path)
    monkeypatch.setattr(
        qcamera_audio.subprocess,
        "run",
        lambda *args, **kwargs: _completed(stdout='{"streams":[]}'),
    )

    with pytest.raises(qcamera_audio.QCameraAudioError, match="does not contain an audio stream"):
        qcamera_audio.probe_qcamera_audio(tmp_path, ROUTE, 61, 4)


def test_extract_qcamera_audio_fails_on_ffmpeg_copy_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _qcamera_path(tmp_path)

    def _fake_run(command, **kwargs):
        if command[0] == "ffprobe":
            return _completed(stdout='{"streams":[{"codec_name":"aac"}]}')
        return _completed(returncode=1, stderr="copy failed")

    monkeypatch.setattr(qcamera_audio.subprocess, "run", _fake_run)

    with pytest.raises(qcamera_audio.QCameraAudioError, match="copy extraction failed"):
        qcamera_audio.extract_visible_qcamera_audio(
            data_dir=tmp_path,
            route_or_segment=ROUTE,
            start_seconds=61,
            length_seconds=4,
            output_path=tmp_path / "audio.m4a",
        )


def test_extract_qcamera_audio_fails_on_bad_timing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _qcamera_path(tmp_path)

    def _fake_run(command, **kwargs):
        if command[0] == "ffprobe" and "stream=codec_name,sample_rate,channels" in command:
            return _completed(stdout='{"streams":[{"codec_name":"aac"}]}')
        if command[0] == "ffmpeg":
            return _completed()
        if command[0] == "ffprobe" and "format=duration" in command:
            return _completed(stdout='{"format":{"duration":"4.250"}}')
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(qcamera_audio.subprocess, "run", _fake_run)

    with pytest.raises(qcamera_audio.QCameraAudioError, match="does not match requested"):
        qcamera_audio.extract_visible_qcamera_audio(
            data_dir=tmp_path,
            route_or_segment=ROUTE,
            start_seconds=61,
            length_seconds=4,
            output_path=tmp_path / "audio.m4a",
        )


def test_mux_audio_into_video_stream_copies_audio_and_video(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.m4a"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    commands: list[list[str]] = []

    def _fake_run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"muxed")
        return _completed()

    monkeypatch.setattr(qcamera_audio.subprocess, "run", _fake_run)

    result = qcamera_audio.mux_audio_into_video(video, audio)

    assert result == video.resolve()
    assert video.read_bytes() == b"muxed"
    command = commands[0]
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "copy"
