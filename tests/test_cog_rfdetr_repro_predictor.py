from __future__ import annotations

from pathlib import Path
import sys
import types


def _load_predictor_module():
    fake_cog = types.ModuleType("cog")
    fake_cog.BasePredictor = object
    fake_cog.Input = lambda *args, **kwargs: None
    fake_cog.Path = Path
    sys.modules["cog"] = fake_cog
    import cog_rfdetr_repro_predictor

    return cog_rfdetr_repro_predictor


def test_predictor_returns_bundle(monkeypatch, tmp_path) -> None:
    predictor_module = _load_predictor_module()
    input_path = tmp_path / "still.png"
    input_path.write_bytes(b"fake")
    expected_bundle = tmp_path / "bundle.zip"

    def fake_run(**kwargs):
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.json").write_text("{}")

    monkeypatch.setattr(predictor_module, "run_rf_detr_repro", fake_run)
    monkeypatch.setattr(predictor_module, "bundle_repro_artifacts", lambda output_dir, bundle_path: expected_bundle)

    predictor = predictor_module.Predictor()
    result = predictor.predict(media=input_path)

    assert result == expected_bundle
