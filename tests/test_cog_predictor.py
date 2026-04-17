from __future__ import annotations

import json
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
    assert cog_predictor.GUI_ANONYMIZATION_PROFILE_MAP["driver face swap, passenger unchanged"] == (
        "facefusion",
        "driver_face_swap_passenger_unchanged",
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
        "driver face swap, passenger unchanged",
        "driver face swap, passenger hidden",
        "driver face swap, passenger face swap",
    ]


def test_passenger_redaction_style_choices_include_new_variants() -> None:
    cog_predictor = _load_cog_predictor()

    assert cog_predictor.PASSENGER_REDACTION_STYLE_CHOICES == [
        "blur",
        "silhouette",
        "black_silhouette",
        "ir_tint",
    ]


def test_predictor_setup_defaults_rf_detr_device_to_auto(monkeypatch) -> None:
    cog_predictor = _load_cog_predictor()
    monkeypatch.delenv("DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE", raising=False)
    monkeypatch.delenv("DRIVER_FACE_SOURCE_IMAGE", raising=False)
    monkeypatch.delenv("DRIVER_FACE_DONOR_BANK_DIR", raising=False)
    predictor = cog_predictor.Predictor()

    predictor.setup()

    assert os.environ["DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE"] == "auto"


def test_predictor_logs_hidden_redaction_summary_for_360_render(tmp_path, monkeypatch, capsys) -> None:
    cog_predictor = _load_cog_predictor()
    output_path = tmp_path / "out.mp4"
    output_path.write_bytes(b"video")
    selection_report_path = output_path.with_name(f"{output_path.stem}.driver-face-selection.json")
    selection_report_path.write_text(json.dumps({"seat_reports": [{"hidden_redaction": {"effect": "blur"}}]}) + "\n")

    monkeypatch.setattr(
        cog_predictor,
        "run_clip",
        lambda request: types.SimpleNamespace(output_path=output_path),
    )

    predictor = cog_predictor.Predictor()
    result = predictor.predict(
        renderType="360",
        route="https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488151496",
        smearAmount=3,
        uiAltVariant=None,
        fileSize=9,
        fileFormat="auto",
        jwtToken="",
        anonymizationProfile="driver unchanged, passenger hidden",
        passengerRedactionStyle="blur",
        notes="",
    )

    captured = capsys.readouterr()
    assert result == output_path
    assert "HIDDEN_REDACTION_SUMMARY:" in captured.out
    assert '"effect": "blur"' in captured.out


def test_predictor_rejects_ui_alt_variant_for_ui_render() -> None:
    cog_predictor = _load_cog_predictor()
    predictor = cog_predictor.Predictor()

    try:
        predictor.predict(
            renderType="ui",
            route="https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488151496",
            smearAmount=3,
            uiAltVariant="device",
            fileSize=9,
            fileFormat="auto",
            jwtToken="",
            anonymizationProfile="none",
            passengerRedactionStyle="blur",
            notes="",
        )
    except ValueError as exc:
        assert "uiAltVariant" in str(exc)
    else:
        raise AssertionError("expected ValueError")
