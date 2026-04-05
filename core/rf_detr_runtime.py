from __future__ import annotations

import os
import warnings
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
import site

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RF_DETR_MODEL_ID = "rfdetr-seg-preview"

_MODEL_SPECS = {
    "rfdetr-seg-preview": ("RFDETRSegPreview", "rf-detr-seg-preview.pt"),
    "rfdetr-seg-nano": ("RFDETRSegNano", "rf-detr-seg-nano.pt"),
    "rfdetr-seg-small": ("RFDETRSegSmall", "rf-detr-seg-small.pt"),
    "rfdetr-seg-medium": ("RFDETRSegMedium", "rf-detr-seg-medium.pt"),
    "rfdetr-seg-large": ("RFDETRSegLarge", "rf-detr-seg-large.pt"),
    "rfdetr-seg-xlarge": ("RFDETRSegXLarge", "rf-detr-seg-xlarge.pt"),
    "rfdetr-seg-2xlarge": ("RFDETRSeg2XLarge", "rf-detr-seg-xxlarge.pt"),
    "rfdetr-seg-xxlarge": ("RFDETRSeg2XLarge", "rf-detr-seg-xxlarge.pt"),
}


def rf_detr_weights_dir() -> Path:
    weights_dir = REPO_ROOT / ".cache/rfdetr"
    weights_dir.mkdir(parents=True, exist_ok=True)
    return weights_dir


def rf_detr_weights_path(model_id: str) -> Path:
    try:
        _model_class_name, weight_filename = _MODEL_SPECS[model_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported RF-DETR segmentation model id: {model_id}") from exc
    return rf_detr_weights_dir() / weight_filename


def prewarm_rf_detr_weights(model_ids: Iterable[str], *, device: str = "cpu") -> tuple[Path, ...]:
    warmed_paths: list[Path] = []
    for model_id in model_ids:
        load_rf_detr_model(model_id, device=device)
        weights_path = rf_detr_weights_path(model_id)
        if not weights_path.exists():
            raise FileNotFoundError(f"RF-DETR weights were not materialized for {model_id}: {weights_path}")
        warmed_paths.append(weights_path)
    return tuple(warmed_paths)


def _python_nvidia_lib_dirs() -> tuple[str, ...]:
    lib_dirs: list[str] = []
    for root in site.getsitepackages():
        nvidia_root = Path(root) / "nvidia"
        if not nvidia_root.exists():
            continue
        for child in sorted(nvidia_root.iterdir()):
            lib_dir = child / "lib"
            if lib_dir.exists():
                lib_dirs.append(str(lib_dir.resolve()))
    return tuple(lib_dirs)


def ensure_python_nvidia_libs_preferred() -> tuple[str, ...]:
    if os.name != "posix":
        return ()
    lib_dirs = _python_nvidia_lib_dirs()
    if not lib_dirs:
        return ()
    existing_parts = [part for part in os.environ.get("LD_LIBRARY_PATH", "").split(":") if part]
    preferred = list(lib_dirs)
    for part in existing_parts:
        if part not in preferred:
            preferred.append(part)
    os.environ["LD_LIBRARY_PATH"] = ":".join(preferred)
    return lib_dirs


ensure_python_nvidia_libs_preferred()


def sync_python_nvidia_runtime_libs_to_system(system_lib_dir: str = "/usr/lib/x86_64-linux-gnu") -> tuple[str, ...]:
    target_root = Path(system_lib_dir)
    if os.name != "posix" or not target_root.exists():
        return ()
    linked: list[str] = []
    for lib_dir in _python_nvidia_lib_dirs():
        for lib_file in sorted(Path(lib_dir).glob("lib*.so*")):
            if lib_file.is_dir():
                continue
            target = target_root / lib_file.name
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(lib_file)
            linked.append(str(target))
    return tuple(linked)


def default_rf_detr_device(env_var: str = "DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE") -> str:
    override = os.environ.get(env_var, "").strip().lower()
    if override and override != "auto":
        return override
    try:
        import torch
    except Exception:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    mps_backend = getattr(torch.backends, "mps", None)
    if mps_backend is not None and mps_backend.is_available():
        return "mps"
    return "cpu"


def resolve_rf_detr_device(requested_device: str = "auto") -> str:
    cleaned = requested_device.strip().lower()
    if not cleaned or cleaned == "auto":
        return default_rf_detr_device()
    if cleaned not in {"cpu", "cuda", "mps"}:
        raise ValueError(f"Unsupported RF-DETR device: {requested_device}")
    return cleaned


def supported_rf_detr_model_ids() -> tuple[str, ...]:
    return tuple(_MODEL_SPECS.keys())


@lru_cache(maxsize=16)
def load_rf_detr_model(model_id: str, device: str = "auto"):
    from rfdetr import (
        RFDETRSeg2XLarge,
        RFDETRSegLarge,
        RFDETRSegMedium,
        RFDETRSegNano,
        RFDETRSegPreview,
        RFDETRSegSmall,
        RFDETRSegXLarge,
    )

    model_classes = {
        "RFDETRSegPreview": RFDETRSegPreview,
        "RFDETRSegNano": RFDETRSegNano,
        "RFDETRSegSmall": RFDETRSegSmall,
        "RFDETRSegMedium": RFDETRSegMedium,
        "RFDETRSegLarge": RFDETRSegLarge,
        "RFDETRSegXLarge": RFDETRSegXLarge,
        "RFDETRSeg2XLarge": RFDETRSeg2XLarge,
    }
    try:
        model_class_name, weight_filename = _MODEL_SPECS[model_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported RF-DETR segmentation model id: {model_id}") from exc

    resolved_device = resolve_rf_detr_device(device)
    weights_dir = rf_detr_weights_dir()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r"`use_return_dict` is deprecated! Use `return_dict` instead!")
        model = model_classes[model_class_name](
            pretrain_weights=str((weights_dir / weight_filename).resolve()),
            device=resolved_device,
        )
        optimize = getattr(model, "optimize_for_inference", None)
        if callable(optimize):
            optimize(compile=False)
    return model


def predict_rf_detr(model, rgb_frame: np.ndarray, *, threshold: float):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r"`use_return_dict` is deprecated! Use `return_dict` instead!")
        return model.predict(rgb_frame, threshold=threshold)


def model_device(model) -> str:
    model_obj = getattr(model, "model", model)
    device = getattr(model_obj, "device", None)
    if device is None:
        return "unknown"
    return str(device)


def detections_masks(detections) -> np.ndarray | None:
    mask = getattr(detections, "mask", None)
    if mask is None:
        data = getattr(detections, "data", None)
        if isinstance(data, dict):
            mask = data.get("mask")
    if mask is None:
        return None
    return np.asarray(mask)


def detections_xyxy(detections) -> np.ndarray:
    xyxy = getattr(detections, "xyxy", None)
    if xyxy is None:
        raise RuntimeError("RF-DETR detections object does not expose xyxy boxes")
    return np.asarray(xyxy)


def detections_class_id(detections) -> np.ndarray | None:
    class_id = getattr(detections, "class_id", None)
    if class_id is None:
        return None
    return np.asarray(class_id)


def detections_confidence(detections) -> np.ndarray | None:
    confidence = getattr(detections, "confidence", None)
    if confidence is None:
        return None
    return np.asarray(confidence)
