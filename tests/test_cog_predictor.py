from __future__ import annotations

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
