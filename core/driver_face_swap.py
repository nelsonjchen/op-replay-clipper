from __future__ import annotations

import os
import json
import bz2
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from renderers import video_renderer


DriverFaceAnonymizationMode = Literal["none", "facefusion"]
DriverFaceSwapPreset = Literal["fast", "quality"]
DriverFaceSelectionMode = Literal["manual", "auto_best_match"]

DEFAULT_FACEFUSION_ROOT = "./.cache/facefusion"
DEFAULT_DRIVER_FACE_SOURCE_IMAGE = "./assets/driver-face-donors/generic-donor-clean-shaven.jpg"
DEFAULT_FACEFUSION_MODEL = "hyperswap_1b_256"
DEFAULT_DRIVER_FACE_DONOR_BANK_DIR = "./assets/driver-face-donors"


@dataclass(frozen=True)
class DriverFaceSwapOptions:
    mode: DriverFaceAnonymizationMode = "none"
    source_image: str = DEFAULT_DRIVER_FACE_SOURCE_IMAGE
    facefusion_root: str = DEFAULT_FACEFUSION_ROOT
    facefusion_model: str = DEFAULT_FACEFUSION_MODEL
    preset: DriverFaceSwapPreset = "fast"
    selection_mode: DriverFaceSelectionMode = "manual"
    donor_bank_dir: str = DEFAULT_DRIVER_FACE_DONOR_BANK_DIR


@dataclass(frozen=True)
class PreparedSeatArtifacts:
    seat_side: Literal["left", "right"]
    crop_clip: Path
    track_metadata: Path


def default_facefusion_root() -> str:
    return os.environ.get("FACEFUSION_ROOT", DEFAULT_FACEFUSION_ROOT)


def default_driver_face_source_image() -> str:
    return os.environ.get("DRIVER_FACE_SOURCE_IMAGE", DEFAULT_DRIVER_FACE_SOURCE_IMAGE)


def default_facefusion_model() -> str:
    return os.environ.get("DRIVER_FACEFUSION_MODEL", DEFAULT_FACEFUSION_MODEL)


def default_driver_face_donor_bank_dir() -> str:
    return os.environ.get("DRIVER_FACE_DONOR_BANK_DIR", DEFAULT_DRIVER_FACE_DONOR_BANK_DIR)


def has_driver_face_anonymization(opts: DriverFaceSwapOptions) -> bool:
    return opts.mode != "none"


def _facefusion_swap_command(
    *,
    facefusion_root: Path,
    source_image: Path,
    target_video: Path,
    output_video: Path,
    model_name: str,
    preset: DriverFaceSwapPreset,
) -> list[str]:
    base_command = [
        str(facefusion_root / ".venv/bin/python"),
        str(facefusion_root / "facefusion.py"),
        "headless-run",
        "--jobs-path",
        str(facefusion_root / "jobs"),
        "--temp-path",
        str(facefusion_root / "temp"),
        "--processors",
        "face_swapper",
        "--face-swapper-model",
        model_name,
        "--face-swapper-weight",
        "1.0",
        "--face-selector-mode",
        "one",
        "--face-detector-model",
        "yunet",
        "--face-detector-score",
        "0.35",
        "--face-mask-padding",
        "8",
        "8",
        "8",
        "8",
        "--execution-providers",
        "coreml",
        "cpu",
        "--video-memory-strategy",
        "tolerant",
        "--system-memory-limit",
        "0",
        "-s",
        str(source_image),
        "-t",
        str(target_video),
        "-o",
        str(output_video),
        "--log-level",
        "info",
    ]
    if preset == "quality":
        return [
            *base_command,
            "--face-swapper-pixel-boost",
            "512x512",
            "--face-mask-types",
            "box",
            "occlusion",
            "--face-mask-blur",
            "0.15",
            "--execution-thread-count",
            "1",
            "--output-video-encoder",
            "h264_videotoolbox",
            "--output-video-quality",
            "85",
            "--output-video-preset",
            "fast",
            "--temp-frame-format",
            "png",
        ]
    return [
        *base_command,
        "--face-swapper-pixel-boost",
        "256x256",
        "--face-mask-types",
        "box",
        "--face-mask-blur",
        "0.1",
        "--execution-thread-count",
        "4",
        "--output-video-encoder",
        "h264_videotoolbox",
        "--output-video-quality",
        "75",
        "--output-video-preset",
        "veryfast",
        "--temp-frame-format",
        "jpeg",
    ]


def _run_facefusion_swap(
    *,
    working_dir: Path,
    target_path: Path,
    output_path: Path,
    options: DriverFaceSwapOptions,
) -> Path:
    facefusion_root = Path(options.facefusion_root).expanduser().resolve()
    source_image = Path(options.source_image).expanduser().resolve()
    facefusion_python = facefusion_root / ".venv/bin/python"
    facefusion_entry = facefusion_root / "facefusion.py"

    if not facefusion_python.exists():
        raise FileNotFoundError(f"FaceFusion interpreter not found at {facefusion_python}")
    if not facefusion_entry.exists():
        raise FileNotFoundError(f"FaceFusion entry point not found at {facefusion_entry}")
    if not source_image.exists():
        raise FileNotFoundError(f"Driver face source image not found at {source_image}")
    if not target_path.exists():
        raise FileNotFoundError(f"Prepared driver face crop clip not found at {target_path}")

    output_path.unlink(missing_ok=True)
    jobs_path = working_dir / "facefusion-jobs"
    temp_path = working_dir / "facefusion-temp"
    jobs_path.mkdir(parents=True, exist_ok=True)
    temp_path.mkdir(parents=True, exist_ok=True)
    command = _facefusion_swap_command(
        facefusion_root=facefusion_root,
        source_image=source_image,
        target_video=target_path,
        output_video=output_path,
        model_name=options.facefusion_model,
        preset=options.preset,
    )
    command[command.index("--jobs-path") + 1] = str(jobs_path)
    command[command.index("--temp-path") + 1] = str(temp_path)
    env = dict(os.environ)
    env["SYSTEM_VERSION_COMPAT"] = "0"
    subprocess.run(command, cwd=facefusion_root, env=env, check=True)
    return output_path


def _selection_window(manifest_path: Path, *, max_selection_seconds: float = 2.0) -> tuple[int, int, int]:
    manifest = json.loads(manifest_path.read_text())
    frames = list(manifest.get("frames", []))
    framerate = int(manifest.get("framerate", 20) or 20)
    total_frames = len(frames)
    if total_frames <= 0:
        return 0, 0, framerate
    window_frames = max(1, min(total_frames, int(round(max_selection_seconds * framerate))))
    best_start = 0
    best_score = float("-inf")
    for start_index in range(0, max(1, total_frames - window_frames + 1)):
        window = frames[start_index:start_index + window_frames]
        mean_face_prob = sum(float(frame.get("face_prob", 0.0) or 0.0) for frame in window) / len(window)
        held_penalty = sum(int(frame.get("held_without_detection", 0) or 0) for frame in window) / len(window)
        missing_penalty = sum(1 for frame in window if frame.get("padded_box") is None) / len(window)
        score = mean_face_prob - (held_penalty * 0.08) - (missing_penalty * 0.6)
        if score > best_score:
            best_score = score
            best_start = start_index
    return best_start, window_frames, framerate


def _build_selection_clip(
    *,
    source_clip: Path,
    manifest_path: Path,
    output_path: Path,
) -> tuple[Path, int]:
    start_frame, window_frames, framerate = _selection_window(manifest_path)
    if window_frames <= 0:
        raise RuntimeError(f"Cannot build a selection clip from empty manifest: {manifest_path}")
    selection_seconds = window_frames / framerate
    selection_start_seconds = start_frame / framerate
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{selection_start_seconds:.3f}",
        "-i",
        str(source_clip),
        "-t",
        f"{selection_seconds:.3f}",
        "-c:v",
        "h264_videotoolbox",
        "-an",
        str(output_path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path, min(window_frames - 1, max(0, framerate))


def _auto_select_source_image(
    *,
    sample_dir: Path,
    target_video: Path,
    track_metadata: Path,
    options: DriverFaceSwapOptions,
    output_path: Path,
) -> tuple[Path, Path]:
    facefusion_root = Path(options.facefusion_root).expanduser().resolve()
    facefusion_python = facefusion_root / ".venv/bin/python"
    if not facefusion_python.exists():
        raise FileNotFoundError(f"FaceFusion interpreter not found at {facefusion_python}")

    selection_dir = sample_dir / "auto-select"
    selection_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(facefusion_python),
        str((Path(__file__).resolve().parent / "driver_face_auto_select.py").resolve()),
        "--target-video",
        str(target_video),
        "--track-metadata",
        str(track_metadata),
        "--donor-bank-dir",
        str(Path(options.donor_bank_dir).expanduser().resolve()),
        "--facefusion-root",
        str(facefusion_root),
        "--output-dir",
        str(selection_dir),
        "--facefusion-model",
        str(options.facefusion_model),
        "--top-k",
        "3",
        "--tone-margin-lab",
        "12.0",
        "--representative-frames",
        "3",
    ]
    proc = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads((proc.stdout or "").strip().splitlines()[-1])
    selected_donor = Path(payload["selected_donor_image"]).resolve()
    report_path = Path(payload["report_path"]).resolve()
    output_path.write_text(report_path.read_text())
    return selected_donor, report_path


def _prepare_face_crop_artifacts(
    *,
    sample_dir: Path,
    route: str,
    route_or_url: str,
    start_seconds: int,
    length_seconds: int,
    data_dir: Path,
    openpilot_dir: Path,
    acceleration: video_renderer.AccelerationPolicy,
    backing_target_mb: int,
    jwt_token: str | None = None,
) -> tuple[Path, list[PreparedSeatArtifacts]]:
    source_clip = sample_dir / "driver-source.mp4"

    from core import route_downloader

    route_date = route.split("|", 1)[1]
    seg_start = start_seconds // 60
    seg_end = ((start_seconds + length_seconds) - 1) // 60 + 1
    for segment in range(seg_start, seg_end):
        segment_dir = data_dir / f"{route_date}--{segment}"
        plain_rlog = segment_dir / "rlog"
        bz2_rlog = segment_dir / "rlog.bz2"
        zst_rlog = segment_dir / "rlog.zst"
        if plain_rlog.exists() and not bz2_rlog.exists() and not zst_rlog.exists():
            bz2_rlog.write_bytes(bz2.compress(plain_rlog.read_bytes()))

    route_downloader.downloadSegments(
        route_or_segment=route,
        start_seconds=start_seconds,
        length=length_seconds,
        smear_seconds=0,
        data_dir=data_dir,
        file_types=["logs"],
        jwt_token=jwt_token,
        decompress_logs=True,
    )

    video_renderer.render_video_clip(
        video_renderer.VideoRenderOptions(
            render_type="driver",
            data_dir=str(data_dir),
            route_or_segment=route,
            start_seconds=start_seconds,
            length_seconds=length_seconds,
            target_mb=backing_target_mb,
            file_format="h264",
            acceleration=acceleration,
            openpilot_dir=str(openpilot_dir),
            output_path=str(source_clip),
        )
    )

    worker_python = openpilot_dir / ".venv/bin/python"
    if not worker_python.exists():
        raise FileNotFoundError(f"Openpilot worker interpreter not found at {worker_python}")
    seat_artifacts: list[PreparedSeatArtifacts] = []
    for seat_side in ("left", "right"):
        crop_clip = sample_dir / f"{seat_side}-face-crop.mp4"
        track_metadata = sample_dir / f"{seat_side}-face-track.json"
        worker_cmd = [
            str(worker_python),
            str((Path(__file__).resolve().parent / "driver_face_eval_worker.py").resolve()),
            "--route",
            route,
            "--route-or-url",
            route_or_url,
            "--start-seconds",
            str(start_seconds),
            "--length-seconds",
            str(length_seconds),
            "--data-dir",
            str(data_dir),
            "--openpilot-dir",
            str(openpilot_dir),
            "--sample-id",
            "driver-face-swap",
            "--category",
            "driver face swap backing clip",
            "--notes",
            "Temporary backing clip artifacts for driver face anonymization.",
            "--track-metadata",
            str(track_metadata),
            "--crop-clip",
            str(crop_clip),
            "--source-clip",
            str(source_clip),
            "--seat-side",
            seat_side,
            "--crop-target-mb",
            str(max(4, min(12, backing_target_mb))),
            "--accel",
            acceleration,
        ]
        subprocess.run(worker_cmd, check=True)
        seat_artifacts.append(
            PreparedSeatArtifacts(
                seat_side=seat_side,
                crop_clip=crop_clip,
                track_metadata=track_metadata,
            )
        )
    return source_clip, seat_artifacts


def _manifest_has_active_crop(track_metadata: Path) -> bool:
    manifest = json.loads(track_metadata.read_text())
    for frame in manifest.get("frames", []):
        if frame.get("crop_rect") is not None:
            return True
    return False


def render_anonymized_driver_backing_video(
    *,
    route: str,
    route_or_url: str,
    start_seconds: int,
    length_seconds: int,
    data_dir: str,
    openpilot_dir: str,
    acceleration: video_renderer.AccelerationPolicy,
    output_path: str,
    options: DriverFaceSwapOptions,
    jwt_token: str | None = None,
) -> Path:
    if not has_driver_face_anonymization(options):
        raise ValueError("Driver face anonymization is disabled")

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    data_root = Path(data_dir).expanduser().resolve()
    openpilot_root = Path(openpilot_dir).expanduser().resolve()
    backing_target_mb = max(12, length_seconds)

    with tempfile.TemporaryDirectory(prefix="driver-face-swap-") as temp_dir:
        overall_started = time.perf_counter()
        sample_dir = Path(temp_dir).resolve()
        source_clip, seat_artifacts = _prepare_face_crop_artifacts(
            sample_dir=sample_dir,
            route=route,
            route_or_url=route_or_url,
            start_seconds=start_seconds,
            length_seconds=length_seconds,
            data_dir=data_root,
            openpilot_dir=openpilot_root,
            acceleration=acceleration,
            backing_target_mb=backing_target_mb,
            jwt_token=jwt_token,
        )
        selection_report_path = output.with_name(f"{output.stem}.driver-face-selection.json")
        selection_report: dict[str, Any] = {
            "mode": options.mode,
            "selection_mode": options.selection_mode,
            "route": route,
            "route_or_url": route_or_url,
            "start_seconds": start_seconds,
            "length_seconds": length_seconds,
            "output_video": str(output),
            "seats": {},
            "timings": {},
        }
        if selection_report_path.exists():
            selection_report_path.unlink()

        active_seats = [artifact for artifact in seat_artifacts if _manifest_has_active_crop(artifact.track_metadata)]
        if not active_seats:
            output.write_bytes(source_clip.read_bytes())
            return output

        facefusion_python = Path(options.facefusion_root).expanduser().resolve() / ".venv/bin/python"
        if not facefusion_python.exists():
            raise FileNotFoundError(f"FaceFusion interpreter not found at {facefusion_python}")
        current_source = source_clip
        total_swap_seconds = 0.0
        total_reintegrate_seconds = 0.0

        for seat_index, artifact in enumerate(active_seats):
            seat_key = artifact.seat_side
            seat_report: dict[str, Any] = {
                "seat_side": seat_key,
                "track_metadata": str(artifact.track_metadata),
                "crop_clip": str(artifact.crop_clip),
            }
            selected_source_image = Path(options.source_image).expanduser().resolve()
            if options.selection_mode == "auto_best_match":
                selection_started = time.perf_counter()
                seat_report_path = sample_dir / f"{seat_key}-driver-face-selection.json"
                selected_source_image, _selection_report = _auto_select_source_image(
                    sample_dir=sample_dir / f"{seat_key}-auto-select",
                    target_video=artifact.crop_clip,
                    track_metadata=artifact.track_metadata,
                    options=options,
                    output_path=seat_report_path,
                )
                seat_report = json.loads(seat_report_path.read_text())
                seat_report.setdefault("timings", {})
                seat_report["timings"]["selection_handoff_seconds"] = time.perf_counter() - selection_started
            else:
                seat_report["selected_donor_image"] = str(selected_source_image)

            swap_started = time.perf_counter()
            swapped_crop = _run_facefusion_swap(
                working_dir=sample_dir / f"{seat_key}-facefusion",
                target_path=artifact.crop_clip,
                output_path=sample_dir / f"{seat_key}-facefusion-{options.preset}.mp4",
                options=DriverFaceSwapOptions(
                    mode=options.mode,
                    source_image=str(selected_source_image),
                    facefusion_root=options.facefusion_root,
                    facefusion_model=options.facefusion_model,
                    preset=options.preset,
                    selection_mode=options.selection_mode,
                    donor_bank_dir=options.donor_bank_dir,
                ),
            )
            seat_swap_seconds = time.perf_counter() - swap_started
            total_swap_seconds += seat_swap_seconds

            reintegrate_started = time.perf_counter()
            intermediate_output = output if seat_index == len(active_seats) - 1 else sample_dir / f"composited-{seat_key}.mp4"
            reintegrate_cmd = [
                str(facefusion_python),
                str((Path(__file__).resolve().parent / "driver_face_reintegrate.py").resolve()),
                "--sample-dir",
                str(sample_dir),
                "--source-video",
                str(current_source),
                "--track-metadata",
                str(artifact.track_metadata),
                "--swapped-crop",
                str(swapped_crop),
                "--output-path",
                str(intermediate_output),
                "--mask-box",
                "padded_box",
                "--mask-expand",
                "1.12",
                "--feather-ratio",
                "0.18",
                "--banner-text",
                "FACE ANONYMIZED" if seat_index == len(active_seats) - 1 else "",
            ]
            subprocess.run(reintegrate_cmd, check=True)
            seat_reintegrate_seconds = time.perf_counter() - reintegrate_started
            total_reintegrate_seconds += seat_reintegrate_seconds
            current_source = intermediate_output

            timings = seat_report.setdefault("timings", {})
            assert isinstance(timings, dict)
            timings["final_video_swap_seconds"] = seat_swap_seconds
            timings["reintegrate_seconds"] = seat_reintegrate_seconds
            seat_report["selected_donor_image"] = str(selected_source_image)
            seat_report["output_video"] = str(current_source)
            selection_report["seats"][seat_key] = seat_report

        total_seconds = time.perf_counter() - overall_started
        timings = selection_report.setdefault("timings", {})
        assert isinstance(timings, dict)
        timings["active_seats"] = len(active_seats)
        timings["final_video_swap_seconds"] = total_swap_seconds
        timings["reintegrate_seconds"] = total_reintegrate_seconds
        timings["total_request_seconds"] = total_seconds
        selection_report_path.write_text(json.dumps(selection_report, indent=2, sort_keys=True) + "\n")
        print(
            "Driver face anonymization timings: "
            f"seats={len(active_seats)}, "
            f"swap={total_swap_seconds:.2f}s, "
            f"reintegrate={total_reintegrate_seconds:.2f}s, "
            f"total={total_seconds:.2f}s"
        )
    return output
