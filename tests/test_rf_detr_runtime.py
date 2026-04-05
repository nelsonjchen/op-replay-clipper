from __future__ import annotations

from pathlib import Path

from core import rf_detr_runtime


def test_default_rf_detr_device_honors_override(monkeypatch) -> None:
    monkeypatch.setenv("DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE", "cpu")

    assert rf_detr_runtime.default_rf_detr_device() == "cpu"


def test_resolve_rf_detr_device_accepts_auto(monkeypatch) -> None:
    monkeypatch.setenv("DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE", "cpu")

    assert rf_detr_runtime.resolve_rf_detr_device("auto") == "cpu"


def test_supported_model_ids_include_preview() -> None:
    assert "rfdetr-seg-preview" in rf_detr_runtime.supported_rf_detr_model_ids()


def test_rf_detr_weights_path_points_into_repo_cache() -> None:
    path = rf_detr_runtime.rf_detr_weights_path("rfdetr-seg-preview")

    assert path.name == "rf-detr-seg-preview.pt"
    assert ".cache/rfdetr" in str(path)


def test_prewarm_rf_detr_weights_materializes_expected_paths(monkeypatch, tmp_path: Path) -> None:
    warmed: list[tuple[str, str]] = []
    monkeypatch.setattr(rf_detr_runtime, "rf_detr_weights_dir", lambda: tmp_path)

    def _fake_load(model_id: str, device: str = "auto"):
        warmed.append((model_id, device))
        rf_detr_runtime.rf_detr_weights_path(model_id).write_text("weights")
        return object()

    monkeypatch.setattr(rf_detr_runtime, "load_rf_detr_model", _fake_load)

    paths = rf_detr_runtime.prewarm_rf_detr_weights(["rfdetr-seg-preview"], device="cpu")

    assert warmed == [("rfdetr-seg-preview", "cpu")]
    assert paths == (tmp_path / "rf-detr-seg-preview.pt",)
    assert paths[0].exists()


def test_ensure_python_nvidia_libs_preferred_prepends_package_dirs(monkeypatch, tmp_path: Path) -> None:
    site_root = tmp_path / "site-packages"
    cudnn_lib = site_root / "nvidia" / "cudnn" / "lib"
    cublas_lib = site_root / "nvidia" / "cu13" / "lib"
    cudnn_lib.mkdir(parents=True)
    cublas_lib.mkdir(parents=True)
    monkeypatch.setattr(rf_detr_runtime.site, "getsitepackages", lambda: [str(site_root)])
    monkeypatch.setenv("LD_LIBRARY_PATH", "/usr/lib/x86_64-linux-gnu:/usr/local/nvidia/lib64")

    preferred = rf_detr_runtime.ensure_python_nvidia_libs_preferred()

    assert preferred == (str(cublas_lib.resolve()), str(cudnn_lib.resolve()))
    assert rf_detr_runtime.os.environ["LD_LIBRARY_PATH"].startswith(
        f"{cublas_lib.resolve()}:{cudnn_lib.resolve()}:"
    )


def test_sync_python_nvidia_runtime_libs_to_system_links_shared_objects(monkeypatch, tmp_path: Path) -> None:
    site_root = tmp_path / "site-packages"
    cudnn_lib = site_root / "nvidia" / "cudnn" / "lib"
    cudnn_lib.mkdir(parents=True)
    libcudnn = cudnn_lib / "libcudnn.so.9"
    libcudnn.write_text("placeholder")
    system_root = tmp_path / "system-lib"
    system_root.mkdir()
    monkeypatch.setattr(rf_detr_runtime.site, "getsitepackages", lambda: [str(site_root)])

    linked = rf_detr_runtime.sync_python_nvidia_runtime_libs_to_system(str(system_root))

    target = system_root / "libcudnn.so.9"
    assert linked == (str(target),)
    assert target.is_symlink()
    assert target.resolve() == libcudnn.resolve()
