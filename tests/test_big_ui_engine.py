from __future__ import annotations

from types import SimpleNamespace

from core import openpilot_integration, render_runtime
from renderers import big_ui_engine


class FakeMsg:
    def __init__(self, which: str, log_mono_time: int, payload: object) -> None:
        self._which = which
        self.logMonoTime = log_mono_time
        setattr(self, which, payload)

    def which(self) -> str:
        return self._which


def test_build_camera_frame_refs_tracks_local_indexes_per_segment() -> None:
    segments = [
        [
            FakeMsg("roadEncodeIdx", 0, SimpleNamespace(frameId=10, timestampSof=100, timestampEof=110)),
            FakeMsg("roadEncodeIdx", 1, SimpleNamespace(frameId=11, timestampSof=200, timestampEof=210)),
        ],
        [
            FakeMsg("roadEncodeIdx", 2, SimpleNamespace(frameId=12, timestampSof=300, timestampEof=310)),
        ],
    ]

    refs_by_frame_id, refs_by_timestamp = big_ui_engine.build_camera_frame_refs(segments)

    assert refs_by_frame_id[10].segment_index == 0
    assert refs_by_frame_id[10].local_index == 0
    assert refs_by_frame_id[11].local_index == 1
    assert refs_by_frame_id[12].segment_index == 1
    assert refs_by_frame_id[12].local_index == 0
    assert refs_by_timestamp[310].route_frame_id == 12


def test_build_render_steps_uses_exact_model_frame_mapping() -> None:
    segments = [
        [
            FakeMsg("roadEncodeIdx", 0, SimpleNamespace(frameId=10, timestampSof=1_000, timestampEof=2_000)),
            FakeMsg("roadCameraState", 10_000_000, SimpleNamespace(frameId=10, timestampEof=2_000)),
            FakeMsg("modelV2", 30_000_000, SimpleNamespace(frameId=10, timestampEof=2_000)),
        ]
    ]

    steps = big_ui_engine.build_render_steps(segments, seg_start=0, start=0, end=1)

    assert len(steps) == 1
    step = steps[0]
    assert step.route_frame_id == 10
    assert step.camera_ref.local_index == 0
    assert step.camera_ref.route_frame_id == 10
    assert step.state["roadCameraState"].roadCameraState.frameId == 10
    assert step.state["modelV2"].modelV2.frameId == 10
    assert step.route_seconds == 0.5


def test_build_render_steps_uses_frame_ids_instead_of_log_mono_time() -> None:
    segments = [
        [
            FakeMsg("roadEncodeIdx", 0, SimpleNamespace(frameId=1202, timestampSof=1_000, timestampEof=2_000)),
            FakeMsg("roadCameraState", 61_000_000_000, SimpleNamespace(frameId=1202, timestampEof=2_000)),
            FakeMsg("modelV2", 61_001_000_000, SimpleNamespace(frameId=1202, timestampEof=2_000)),
        ]
    ]

    steps = big_ui_engine.build_render_steps(segments, seg_start=1, start=60, end=61)

    assert len(steps) == 1
    assert steps[0].route_seconds == 60.1


def test_ui_environment_forces_scale_one() -> None:
    env = render_runtime.configure_ui_environment({})
    assert env["SCALE"] == "1"


def test_patch_ui_application_record_skip_inserts_skip_logic(tmp_path) -> None:
    app = tmp_path / "application.py"
    app.write_text(
        'RECORD_SPEED = int(os.getenv("RECORD_SPEED", "1"))  # Speed multiplier\n'
        "        if RECORD:\n"
        "          image = rl.load_image_from_texture(self._render_texture.texture)\n"
        "          data_size = image.width * image.height * 4\n"
        "          data = bytes(rl.ffi.buffer(image.data, data_size))\n"
        "          self._ffmpeg_queue.put(data)  # Async write via background thread\n"
        "          rl.unload_image(image)\n"
    )

    changed = openpilot_integration._patch_ui_application_record_skip(app)
    updated = app.read_text()

    assert changed is True
    assert 'RECORD_SKIP_FRAMES = int(os.getenv("RECORD_SKIP_FRAMES", "0"))' in updated
    assert "if RECORD and self._frame >= RECORD_SKIP_FRAMES:" in updated


def test_patch_augmented_road_view_fill_applies_upstream_zoom_fix(tmp_path) -> None:
    view = tmp_path / "augmented_road_view.py"
    view.write_text(
        "    # Calculate center points and dimensions\n"
        "    x, y = self._content_rect.x, self._content_rect.y\n"
        "    w, h = self._content_rect.width, self._content_rect.height\n"
        "    cx, cy = intrinsic[0, 2], intrinsic[1, 2]\n"
        "    # Calculate max allowed offsets with margins\n"
        "    margin = 5\n"
        "    max_x_offset = cx * zoom - w / 2 - margin\n"
        "    max_y_offset = cy * zoom - h / 2 - margin\n"
        "    super()._render(rect)\n"
    )

    changed = openpilot_integration._patch_augmented_road_view_fill(view)
    updated = view.read_text()

    assert changed is True
    assert "zoom = max(zoom, w / (2 * cx), h / (2 * cy))" in updated
    assert "max_x_offset = max(0.0, cx * zoom - w / 2 - margin)" in updated
    assert "max_y_offset = max(0.0, cy * zoom - h / 2 - margin)" in updated
    assert "super()._render(self._content_rect)" in updated
