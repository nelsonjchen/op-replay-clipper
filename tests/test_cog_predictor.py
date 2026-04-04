from __future__ import annotations

import os
from pathlib import Path
import sys
import types


def _load_cog_predictor():
    fake_cog = types.ModuleType("cog")
    fake_cog.BasePredictor = object
    fake_cog.Input = lambda *args, **kwargs: None
    fake_cog.Path = Path
    sys.modules["cog"] = fake_cog
    import cog_predictor

    return cog_predictor


def test_default_facefusion_root_prefers_repo_checkout(tmp_path, monkeypatch) -> None:
    cog_predictor = _load_cog_predictor()
    repo_root = tmp_path / "repo"
    repo_facefusion = repo_root / ".cache/facefusion"
    repo_facefusion.mkdir(parents=True)
    monkeypatch.delenv("FACEFUSION_ROOT", raising=False)

    assert cog_predictor.default_facefusion_root(repo_root) == repo_facefusion.resolve()


def test_default_facefusion_root_prefers_explicit_env(tmp_path, monkeypatch) -> None:
    cog_predictor = _load_cog_predictor()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    explicit = tmp_path / "explicit-facefusion"
    explicit.mkdir()
    monkeypatch.setenv("FACEFUSION_ROOT", str(explicit))

    assert cog_predictor.default_facefusion_root(repo_root) == explicit.resolve()


def test_gui_anonymization_profile_map_includes_hidden_profiles() -> None:
    cog_predictor = _load_cog_predictor()

    assert cog_predictor.GUI_ANONYMIZATION_PROFILE_MAP["driver unchanged, passenger hidden"] == (
        "facefusion",
        "driver_unchanged_passenger_hidden",
    )
    assert cog_predictor.GUI_ANONYMIZATION_PROFILE_MAP["driver face swap, passenger hidden"] == (
        "facefusion",
        "driver_face_swap_passenger_hidden",
    )


def test_gui_anonymization_profile_map_keeps_pixelize_aliases() -> None:
    cog_predictor = _load_cog_predictor()

    assert cog_predictor.GUI_ANONYMIZATION_PROFILE_MAP["driver unchanged, passenger pixelize"] == (
        "facefusion",
        "driver_unchanged_passenger_pixelize",
    )
    assert cog_predictor.GUI_ANONYMIZATION_PROFILE_MAP["driver face swap, passenger pixelize"] == (
        "facefusion",
        "driver_face_swap_passenger_pixelize",
    )


def test_hosted_anonymization_profile_choices_are_canonical() -> None:
    cog_predictor = _load_cog_predictor()

    assert cog_predictor.HOSTED_ANONYMIZATION_PROFILE_CHOICES == [
        "none",
        "driver unchanged, passenger hidden",
        "driver unchanged, passenger face swap",
        "driver face swap, passenger hidden",
        "driver face swap, passenger face swap",
    ]


def test_predictor_setup_defaults_rf_detr_device_to_auto(monkeypatch) -> None:
    cog_predictor = _load_cog_predictor()
    monkeypatch.delenv("DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE", raising=False)
    monkeypatch.delenv("DRIVER_FACE_SOURCE_IMAGE", raising=False)
    monkeypatch.delenv("DRIVER_FACE_DONOR_BANK_DIR", raising=False)
    predictor = cog_predictor.Predictor()

    predictor.setup()

    assert os.environ["DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE"] == "auto"
