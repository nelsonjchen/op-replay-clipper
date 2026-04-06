from __future__ import annotations

import os
import json
import bz2
import hashlib
import shutil
import subprocess
import tempfile
import time
import platform
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from renderers import video_renderer


DriverFaceAnonymizationMode = Literal["none", "facefusion"]
DriverFaceAnonymizationProfile = Literal[
    "driver_unchanged_passenger_hidden",
    "driver_unchanged_passenger_face_swap",
    "driver_unchanged_passenger_pixelize",
    "driver_face_swap_passenger_hidden",
    "driver_face_swap_passenger_face_swap",
    "driver_face_swap_passenger_pixelize",
]
DriverFaceSwapPreset = Literal["fast", "quality"]
DriverFaceSelectionMode = Literal["manual", "auto_best_match"]
PassengerRedactionStyle = Literal["blur", "silhouette"]
SeatAnonymizationMode = Literal["none", "facefusion", "hidden"]

DEFAULT_FACEFUSION_ROOT = "./.cache/facefusion"
DEFAULT_DRIVER_FACE_SOURCE_IMAGE = "./assets/driver-face-donors/generic-donor-clean-shaven.jpg"
DEFAULT_FACEFUSION_MODEL = "hyperswap_1b_256"
DEFAULT_DRIVER_FACE_DONOR_BANK_DIR = "./assets/driver-face-donors"
BACKING_CACHE_SCHEMA_VERSION = "driver-face-cache-v5"
_CUDA_LIBRARY_SUBDIRS = (
    "cublas/lib",
    "cudnn/lib",
    "cuda_runtime/lib",
    "cuda_nvrtc/lib",
    "curand/lib",
    "cufft/lib",
    "nvjitlink/lib",
)
_SYSTEM_CUDA_LIBRARY_DIRS = (
    "/usr/local/cuda-12.4/targets/x86_64-linux/lib",
    "/usr/local/cuda/targets/x86_64-linux/lib",
    "/usr/local/nvidia/lib64",
    "/usr/local/nvidia/lib",
    "/usr/lib/x86_64-linux-gnu",
)
_PROFILE_COMPAT_ALIASES: dict[str, str] = {
    "driver_unchanged_passenger_pixelize": "driver_unchanged_passenger_hidden",
    "driver_face_swap_passenger_pixelize": "driver_face_swap_passenger_hidden",
}


@dataclass(frozen=True)
class DriverFaceSwapOptions:
    mode: DriverFaceAnonymizationMode = "none"
    profile: DriverFaceAnonymizationProfile = "driver_face_swap_passenger_face_swap"
    passenger_redaction_style: PassengerRedactionStyle = "blur"
    source_image: str = DEFAULT_DRIVER_FACE_SOURCE_IMAGE
    facefusion_root: str = DEFAULT_FACEFUSION_ROOT
    facefusion_model: str = DEFAULT_FACEFUSION_MODEL
    preset: DriverFaceSwapPreset = "fast"
    selection_mode: DriverFaceSelectionMode = "manual"
    donor_bank_dir: str = DEFAULT_DRIVER_FACE_DONOR_BANK_DIR


@dataclass(frozen=True)
class PreparedSeatArtifacts:
    seat_side: Literal["left", "right"]
    seat_role: Literal["driver", "passenger"]
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


def canonical_driver_face_profile(profile: str) -> DriverFaceAnonymizationProfile:
    normalized = _PROFILE_COMPAT_ALIASES.get(profile, profile)
    return normalized  # type: ignore[return-value]


@lru_cache(maxsize=1)
def _ffmpeg_encoder_names() -> frozenset[str]:
    try:
        completed = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return frozenset()

    encoders: set[str] = set()
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            encoders.add(parts[1])
    return frozenset(encoders)


def _ffmpeg_encoder_available(name: str) -> bool:
    return name in _ffmpeg_encoder_names()


def _has_nvidia() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False
    return subprocess.run([nvidia_smi, "-L"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def default_facefusion_output_video_encoder() -> str:
    override = os.environ.get("DRIVER_FACEFUSION_OUTPUT_VIDEO_ENCODER")
    if override:
        return override
    if platform.system() == "Darwin" and _ffmpeg_encoder_available("hevc_videotoolbox"):
        return "hevc_videotoolbox"
    if _has_nvidia() and _ffmpeg_encoder_available("hevc_nvenc"):
        return "hevc_nvenc"
    return "libx264"


def default_facefusion_execution_providers() -> list[str]:
    override = os.environ.get("DRIVER_FACEFUSION_EXECUTION_PROVIDERS")
    if override:
        providers = [provider.strip() for provider in override.split(",") if provider.strip()]
        if providers:
            return providers
    if platform.system() == "Darwin":
        return ["coreml", "cpu"]
    if _has_nvidia():
        return ["cuda", "cpu"]
    return ["cpu"]


def _facefusion_python_site_packages_dir(facefusion_root: Path) -> Path | None:
    venv_lib = facefusion_root / ".venv/lib"
    if not venv_lib.exists():
        return None
    for candidate in sorted(venv_lib.glob("python*/site-packages")):
        if candidate.exists():
            return candidate
    return None


def _facefusion_cuda_library_dirs(facefusion_root: Path) -> list[Path]:
    library_dirs: list[Path] = []
    for system_dir in _SYSTEM_CUDA_LIBRARY_DIRS:
        candidate = Path(system_dir)
        if candidate.exists():
            library_dirs.append(candidate)

    site_packages = _facefusion_python_site_packages_dir(facefusion_root)
    if site_packages is None:
        return library_dirs

    nvidia_root = site_packages / "nvidia"
    for subdir in _CUDA_LIBRARY_SUBDIRS:
        candidate = nvidia_root / subdir
        if candidate.exists():
            library_dirs.append(candidate)
    return library_dirs


def facefusion_runtime_env(
    facefusion_root: Path,
    *,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env["SYSTEM_VERSION_COMPAT"] = "0"
    if "cuda" not in default_facefusion_execution_providers():
        return env

    cuda_library_dirs = [str(path) for path in _facefusion_cuda_library_dirs(facefusion_root)]
    if not cuda_library_dirs:
        return env

    existing = env.get("LD_LIBRARY_PATH", "")
    existing_parts = [part for part in existing.split(":") if part]
    combined_parts: list[str] = []
    for path in [*cuda_library_dirs, *existing_parts]:
        if path not in combined_parts:
            combined_parts.append(path)
    env["LD_LIBRARY_PATH"] = ":".join(combined_parts)
    return env


def apply_facefusion_runtime_env(facefusion_root: Path) -> None:
    updated = facefusion_runtime_env(facefusion_root, base_env=dict(os.environ))
    for key, value in updated.items():
        os.environ[key] = value


def _run_logged_subprocess(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    output_lines: list[str] = []
    for line in process.stdout:
        print(line, end="")
        output_lines.append(line)
    return_code = process.wait()
    if return_code != 0:
        combined_output = "".join(output_lines)
        raise subprocess.CalledProcessError(return_code, command, output=combined_output)


def intermediate_video_encoder_args() -> list[str]:
    encoder = default_facefusion_output_video_encoder()
    if encoder.startswith("hevc_"):
        return ["-c:v", encoder, "-vtag", "hvc1"]
    return ["-c:v", encoder]


def intermediate_video_file_format() -> Literal["h264", "hevc"]:
    return "hevc" if default_facefusion_output_video_encoder().startswith("hevc_") else "h264"


def has_driver_face_anonymization(opts: DriverFaceSwapOptions) -> bool:
    return opts.mode != "none"


def _seat_modes_for_profile(profile: DriverFaceAnonymizationProfile) -> tuple[SeatAnonymizationMode, SeatAnonymizationMode]:
    if profile == "driver_unchanged_passenger_face_swap":
        return "none", "facefusion"
    if profile in {"driver_unchanged_passenger_hidden", "driver_unchanged_passenger_pixelize"}:
        return "none", "hidden"
    if profile in {"driver_face_swap_passenger_hidden", "driver_face_swap_passenger_pixelize"}:
        return "facefusion", "hidden"
    return "facefusion", "facefusion"


def _path_fingerprint(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    payload: dict[str, Any] = {"path": str(resolved)}
    if resolved.exists():
        stat = resolved.stat()
        payload["size"] = stat.st_size
        payload["mtime_ns"] = stat.st_mtime_ns
    return payload


def _cache_paths(
    *,
    data_dir: Path,
    route: str,
    start_seconds: int,
    length_seconds: int,
    options: DriverFaceSwapOptions,
) -> tuple[Path, Path]:
    cache_root = data_dir.parent / "driver_face_swap_cache"
    cache_root.mkdir(parents=True, exist_ok=True)

    donor_manifest = Path(options.donor_bank_dir).expanduser().resolve() / "manifest.json"
    cache_descriptor = {
        "schema": BACKING_CACHE_SCHEMA_VERSION,
        "route": route,
        "start_seconds": start_seconds,
        "length_seconds": length_seconds,
        "mode": options.mode,
        "profile": options.profile,
        "passenger_redaction_style": options.passenger_redaction_style,
        "selection_mode": options.selection_mode,
        "preset": options.preset,
        "facefusion_model": options.facefusion_model,
        "source_image": _path_fingerprint(Path(options.source_image)),
        "donor_manifest": _path_fingerprint(donor_manifest),
    }
    cache_key = hashlib.sha256(json.dumps(cache_descriptor, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    route_slug = route.replace("|", "__").replace("/", "_")
    cache_video = cache_root / f"{route_slug}-{start_seconds}-{length_seconds}-{cache_key}.mp4"
    cache_report = cache_root / f"{route_slug}-{start_seconds}-{length_seconds}-{cache_key}.driver-face-selection.json"
    return cache_video, cache_report


def _seat_mode_for_role(
    options: DriverFaceSwapOptions,
    seat_role: Literal["driver", "passenger"],
) -> SeatAnonymizationMode:
    if not has_driver_face_anonymization(options):
        return "none"
    driver_mode, passenger_mode = _seat_modes_for_profile(options.profile)
    return driver_mode if seat_role == "driver" else passenger_mode


def _seat_mode_counts(
    active_seats: list[PreparedSeatArtifacts],
    options: DriverFaceSwapOptions,
) -> dict[SeatAnonymizationMode, int]:
    counts: dict[SeatAnonymizationMode, int] = {
        "none": 0,
        "facefusion": 0,
        "hidden": 0,
    }
    for artifact in active_seats:
        counts[_seat_mode_for_role(options, artifact.seat_role)] += 1
    return counts


def _banner_text_for_active_seats(
    active_seats: list[PreparedSeatArtifacts],
    options: DriverFaceSwapOptions,
) -> str:
    active_driver_mode: SeatAnonymizationMode | None = None
    active_passenger_mode: SeatAnonymizationMode | None = None
    for artifact in active_seats:
        seat_mode = _seat_mode_for_role(options, artifact.seat_role)
        if artifact.seat_role == "driver":
            active_driver_mode = seat_mode
        else:
            active_passenger_mode = seat_mode

    hidden_label = "BLURRED" if options.passenger_redaction_style == "blur" else "SILHOUETTED"

    if active_driver_mode == "facefusion" and active_passenger_mode == "facefusion":
        return "DRIVER/PASSENGER FACE SWAPPED"
    if active_driver_mode == "facefusion" and active_passenger_mode == "hidden":
        return f"DRIVER SWAPPED, PASSENGER {hidden_label}"
    if active_driver_mode == "none" and active_passenger_mode == "hidden":
        return f"PASSENGER {hidden_label}"
    if active_driver_mode == "facefusion":
        return "DRIVER FACE SWAPPED"
    if active_passenger_mode == "facefusion":
        return "PASSENGER FACE SWAPPED"
    if active_passenger_mode == "hidden":
        return f"PASSENGER {hidden_label}"
    return "FACE ANONYMIZED"


def _facefusion_swap_command(
    *,
    facefusion_root: Path,
    source_image: Path,
    target_video: Path,
    output_video: Path,
    model_name: str,
    preset: DriverFaceSwapPreset,
) -> list[str]:
    output_video_encoder = default_facefusion_output_video_encoder()
    execution_providers = default_facefusion_execution_providers()
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
        "many",
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
        *execution_providers,
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
            output_video_encoder,
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
        output_video_encoder,
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
    env = facefusion_runtime_env(facefusion_root)
    _run_logged_subprocess(command, cwd=facefusion_root, env=env)
    return output_path


def _run_pixelize_swap(
    *,
    target_path: Path,
    output_path: Path,
) -> Path:
    probe = subprocess.run(
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
            str(target_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(probe.stdout)
    stream = payload["streams"][0]
    width = int(stream["width"])
    height = int(stream["height"])
    shrink_w = max(18, width // 14)
    shrink_h = max(18, height // 14)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(target_path),
            "-vf",
            f"scale={shrink_w}:{shrink_h}:flags=neighbor,scale={width}:{height}:flags=neighbor",
            "-an",
            "-c:v",
            "mpeg4",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
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
        *intermediate_video_encoder_args(),
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
    env = facefusion_runtime_env(facefusion_root)
    proc = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
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
    options: DriverFaceSwapOptions,
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
            file_format=intermediate_video_file_format(),
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
        manifest_payload = _run_face_eval_worker([*worker_cmd, "--manifest-only"], acceleration=acceleration)
        seat_role = _seat_role_from_manifest(track_metadata, seat_side=seat_side)
        seat_mode = _seat_mode_for_role(options, seat_role)
        has_active_crop = bool(manifest_payload.get("has_active_crop"))
        if seat_mode == "facefusion" and has_active_crop:
            _run_face_eval_worker(worker_cmd, acceleration=acceleration)
        seat_artifacts.append(
            PreparedSeatArtifacts(
                seat_side=seat_side,
                seat_role=seat_role,
                crop_clip=crop_clip,
                track_metadata=track_metadata,
            )
        )
    return source_clip, seat_artifacts


def _run_face_eval_worker(worker_cmd: list[str], *, acceleration: video_renderer.AccelerationPolicy) -> dict[str, Any]:
    accel_index = worker_cmd.index("--accel") + 1
    attempts: list[video_renderer.AccelerationPolicy] = [acceleration]
    if acceleration in ("auto", "nvidia"):
        attempts.append("cpu")
    last_error: subprocess.CalledProcessError | None = None
    for attempt_accel in attempts:
        cmd = list(worker_cmd)
        cmd[accel_index] = attempt_accel
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode == 0:
            stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
            if stdout_lines:
                try:
                    return json.loads(stdout_lines[-1])
                except json.JSONDecodeError:
                    pass
            return {}
        if completed.stdout.strip():
            print(completed.stdout.rstrip())
        if completed.stderr.strip():
            print(completed.stderr.rstrip())
        print(f"Driver face eval worker failed (accel={attempt_accel}, returncode={completed.returncode})")
        last_error = subprocess.CalledProcessError(
            completed.returncode,
            cmd,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    if last_error is not None:
        raise last_error
    return {}


def _seat_role_from_manifest(
    track_metadata: Path,
    *,
    seat_side: Literal["left", "right"],
) -> Literal["driver", "passenger"]:
    manifest = json.loads(track_metadata.read_text())
    selected_side = None
    for frame in manifest.get("frames", []):
        frame_selected_side = frame.get("selected_side")
        if frame_selected_side in {"left", "right"}:
            selected_side = frame_selected_side
            break
    if selected_side is None:
        selected_side = "left"
    return "driver" if seat_side == selected_side else "passenger"


def _manifest_has_active_crop(track_metadata: Path) -> bool:
    manifest = json.loads(track_metadata.read_text())
    for frame in manifest.get("frames", []):
        if frame.get("crop_rect") is not None:
            return True
    return False


def _seat_processing_order(
    artifact: PreparedSeatArtifacts,
    *,
    options: DriverFaceSwapOptions,
) -> tuple[int, int]:
    seat_mode = _seat_mode_for_role(options, artifact.seat_role)
    if seat_mode == "hidden":
        return (1, 0)
    if artifact.seat_role == "driver":
        return (0, 0)
    return (0, 1)


def _write_track_aliases(sample_dir: Path, seat_artifacts: list[PreparedSeatArtifacts]) -> None:
    for artifact in seat_artifacts:
        if artifact.seat_role == "driver":
            shutil.copy2(artifact.track_metadata, sample_dir / "face-track.json")
        elif artifact.seat_role == "passenger":
            shutil.copy2(artifact.track_metadata, sample_dir / "passenger-face-track.json")


def _run_hidden_passenger_redaction(
    *,
    sample_dir: Path,
    source_path: Path,
    output_path: Path,
    track_metadata: Path,
    options: DriverFaceSwapOptions,
    banner_text: str,
) -> tuple[Path, float]:
    from core import driver_face_benchmark_worker

    track = json.loads(track_metadata.read_text())
    started = time.perf_counter()
    report = driver_face_benchmark_worker.render_rf_detr_redacted_clip(
        sample_dir=sample_dir,
        output_path=output_path,
        source_path=source_path,
        source_kind="driver_face_swap_backing_video",
        track=track,
        model_id=driver_face_benchmark_worker.DEFAULT_RF_DETR_MODEL_ID,
        threshold=driver_face_benchmark_worker.DEFAULT_RF_DETR_THRESHOLD,
        frame_stride=driver_face_benchmark_worker.DEFAULT_RF_DETR_FRAME_STRIDE,
        mask_dilate=driver_face_benchmark_worker.DEFAULT_RF_DETR_MASK_DILATE,
        startup_hold_frames=driver_face_benchmark_worker.DEFAULT_RF_DETR_STARTUP_HOLD_FRAMES,
        passenger_crop_margin_ratio=driver_face_benchmark_worker.DEFAULT_RF_DETR_PASSENGER_CROP_MARGIN_RATIO,
        missing_hold_frames=driver_face_benchmark_worker.DEFAULT_RF_DETR_MISSING_HOLD_FRAMES,
        target_side="passenger",
        effect=options.passenger_redaction_style,
        banner_text=banner_text,
        source_clip_description="driver_face_swap_backing_video",
        trim_startup_from_output=False,
    )
    return output_path, time.perf_counter() - started, report


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
    selection_report_path = output.with_name(f"{output.stem}.driver-face-selection.json")
    cache_video_path, cache_report_path = _cache_paths(
        data_dir=data_root,
        route=route,
        start_seconds=start_seconds,
        length_seconds=length_seconds,
        options=options,
    )

    if cache_video_path.exists():
        shutil.copy2(cache_video_path, output)
        if cache_report_path.exists():
            if selection_report_path.exists():
                selection_report_path.unlink()
            shutil.copy2(cache_report_path, selection_report_path)
        elif selection_report_path.exists():
            selection_report_path.unlink()
        print(f"Reusing cached driver face anonymization backing video: {cache_video_path}")
        return output

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
            options=options,
            jwt_token=jwt_token,
        )
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

        active_seats = [
            artifact
            for artifact in seat_artifacts
            if _manifest_has_active_crop(artifact.track_metadata)
            and _seat_mode_for_role(options, artifact.seat_role) != "none"
        ]
        if not active_seats:
            output.write_bytes(source_clip.read_bytes())
            shutil.copy2(output, cache_video_path)
            return output
        _write_track_aliases(sample_dir, seat_artifacts)
        active_seats = sorted(active_seats, key=lambda artifact: _seat_processing_order(artifact, options=options))
        seat_mode_counts = _seat_mode_counts(active_seats, options)
        banner_text = _banner_text_for_active_seats(active_seats, options)

        facefusion_python = Path(options.facefusion_root).expanduser().resolve() / ".venv/bin/python"
        current_source = source_clip
        total_transform_seconds = 0.0
        total_facefusion_seconds = 0.0
        total_hidden_seconds = 0.0
        total_reintegrate_seconds = 0.0

        for seat_index, artifact in enumerate(active_seats):
            seat_key = artifact.seat_side
            seat_mode = _seat_mode_for_role(options, artifact.seat_role)
            seat_report: dict[str, Any] = {
                "seat_side": seat_key,
                "seat_role": artifact.seat_role,
                "seat_mode": seat_mode,
                "track_metadata": str(artifact.track_metadata),
                "crop_clip": str(artifact.crop_clip),
            }
            selected_source_image = Path(options.source_image).expanduser().resolve()
            if seat_mode == "facefusion" and options.selection_mode == "auto_best_match":
                selection_started = time.perf_counter()
                seat_report_path = sample_dir / f"{seat_key}-driver-face-selection.json"
                selected_source_image, _selection_report = _auto_select_source_image(
                    sample_dir=sample_dir / f"{seat_key}-auto-select",
                    target_video=artifact.crop_clip,
                    track_metadata=artifact.track_metadata,
                    options=options,
                    output_path=seat_report_path,
                )
                seat_report["selection"] = json.loads(seat_report_path.read_text())
                seat_report.setdefault("timings", {})
                seat_report["timings"]["selection_handoff_seconds"] = time.perf_counter() - selection_started
            elif seat_mode == "facefusion":
                seat_report["selected_donor_image"] = str(selected_source_image)

            swap_started = time.perf_counter()
            if seat_mode == "none":
                swapped_crop = artifact.crop_clip
            elif seat_mode == "hidden":
                swapped_crop = current_source
            else:
                swapped_crop = _run_facefusion_swap(
                    working_dir=sample_dir / f"{seat_key}-facefusion",
                    target_path=artifact.crop_clip,
                    output_path=sample_dir / f"{seat_key}-facefusion-{options.preset}.mp4",
                    options=DriverFaceSwapOptions(
                        mode=options.mode,
                        profile=options.profile,
                        source_image=str(selected_source_image),
                        facefusion_root=options.facefusion_root,
                        facefusion_model=options.facefusion_model,
                        preset=options.preset,
                        selection_mode=options.selection_mode,
                        donor_bank_dir=options.donor_bank_dir,
                    ),
                )
            seat_swap_seconds = time.perf_counter() - swap_started
            total_transform_seconds += seat_swap_seconds
            if seat_mode == "facefusion":
                total_facefusion_seconds += seat_swap_seconds
            intermediate_output = output if seat_index == len(active_seats) - 1 else sample_dir / f"composited-{seat_key}.mp4"
            if seat_mode == "hidden":
                current_source, seat_reintegrate_seconds, hidden_report = _run_hidden_passenger_redaction(
                    sample_dir=sample_dir,
                    source_path=current_source,
                    output_path=intermediate_output,
                    track_metadata=artifact.track_metadata,
                    options=options,
                    banner_text=banner_text if seat_index == len(active_seats) - 1 else "",
                )
                total_hidden_seconds += seat_reintegrate_seconds
                total_transform_seconds += seat_reintegrate_seconds
                seat_report["hidden_redaction"] = {
                    "candidate_id": hidden_report.get("candidate_id"),
                    "rf_detr_device": hidden_report.get("rf_detr_device"),
                    "rf_detr_requested_device": hidden_report.get("rf_detr_requested_device"),
                    "rf_detr_model_id": hidden_report.get("rf_detr_model_id"),
                    "rf_detr_threshold": hidden_report.get("rf_detr_threshold"),
                    "rf_detr_frame_stride": hidden_report.get("rf_detr_frame_stride"),
                    "rf_detr_effect": hidden_report.get("rf_detr_effect"),
                    "output_video_encoder": hidden_report.get("output_video_encoder"),
                    "source_clip_kind": hidden_report.get("source_clip_kind"),
                    "source_frames_processed": hidden_report.get("source_frames_processed"),
                    "frames_processed": hidden_report.get("frames_processed"),
                    "redacted_frames": hidden_report.get("redacted_frames"),
                    "detector_frames": hidden_report.get("detector_frames"),
                    "runtime_seconds": hidden_report.get("runtime_seconds"),
                    "runtime_breakdown": hidden_report.get("runtime_breakdown"),
                    "startup_mask_source_frame_index": hidden_report.get("startup_mask_source_frame_index"),
                }
            else:
                reintegrate_started = time.perf_counter()
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
                    banner_text if seat_index == len(active_seats) - 1 else "",
                ]
                subprocess.run(reintegrate_cmd, check=True)
                seat_reintegrate_seconds = time.perf_counter() - reintegrate_started
                current_source = intermediate_output
            total_reintegrate_seconds += seat_reintegrate_seconds

            timings = seat_report.setdefault("timings", {})
            assert isinstance(timings, dict)
            timings["final_video_swap_seconds"] = seat_swap_seconds
            timings["reintegrate_seconds"] = seat_reintegrate_seconds
            if seat_mode == "hidden":
                timings["hidden_redaction_seconds"] = seat_reintegrate_seconds
            if seat_mode == "facefusion":
                seat_report["selected_donor_image"] = str(selected_source_image)
            seat_report["output_video"] = str(current_source)
            selection_report["seats"][seat_key] = seat_report

        total_seconds = time.perf_counter() - overall_started
        timings = selection_report.setdefault("timings", {})
        assert isinstance(timings, dict)
        timings["active_seats"] = len(active_seats)
        timings["facefusion_seats"] = seat_mode_counts["facefusion"]
        timings["hidden_seats"] = seat_mode_counts["hidden"]
        timings["unchanged_seats"] = seat_mode_counts["none"]
        timings["transform_seconds"] = total_transform_seconds
        timings["facefusion_seconds"] = total_facefusion_seconds
        timings["hidden_seconds"] = total_hidden_seconds
        timings["final_video_swap_seconds"] = total_facefusion_seconds
        timings["reintegrate_seconds"] = total_reintegrate_seconds
        timings["total_request_seconds"] = total_seconds
        selection_report_path.write_text(json.dumps(selection_report, indent=2, sort_keys=True) + "\n")
        shutil.copy2(output, cache_video_path)
        shutil.copy2(selection_report_path, cache_report_path)
        print(
            "Driver face anonymization timings: "
            f"active_seats={len(active_seats)}, "
            f"swapped_seats={seat_mode_counts['facefusion']}, "
            f"hidden_seats={seat_mode_counts['hidden']}, "
            f"unchanged_seats={seat_mode_counts['none']}, "
            f"face_swap={total_facefusion_seconds:.2f}s, "
            f"hidden={total_hidden_seconds:.2f}s, "
            f"reintegrate={total_reintegrate_seconds:.2f}s, "
            f"total={total_seconds:.2f}s"
        )
    return output
