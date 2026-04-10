from __future__ import annotations

from pathlib import Path

import pytest

from renderers import ui_renderer


def test_render_ui_clip_rejects_ui_alt_variant_for_default_layout(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui_renderer, "_has_modern_openpilot", lambda _path: True)

    with pytest.raises(ValueError, match="ui_alt_variant"):
        ui_renderer.render_ui_clip(
            ui_renderer.UIRenderOptions(
                route="a2a0ccea32023010|2023-07-27--13-01-19",
                start_seconds=0,
                length_seconds=5,
                smear_seconds=3,
                target_mb=9,
                file_format="h264",
                output_path=str(tmp_path / "out.mp4"),
                openpilot_dir=str(Path(tmp_path)),
                layout_mode="default",
                ui_alt_variant="device",
            )
        )


def test_render_ui_clip_rejects_stacked_ui_alt_variant_with_qcam(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui_renderer, "_has_modern_openpilot", lambda _path: True)

    with pytest.raises(ValueError, match="qcam"):
        ui_renderer.render_ui_clip(
            ui_renderer.UIRenderOptions(
                route="a2a0ccea32023010|2023-07-27--13-01-19",
                start_seconds=0,
                length_seconds=5,
                smear_seconds=3,
                target_mb=9,
                file_format="h264",
                output_path=str(tmp_path / "out.mp4"),
                openpilot_dir=str(Path(tmp_path)),
                layout_mode="alt",
                ui_alt_variant="stacked_forward_over_wide",
                qcam=True,
            )
        )
