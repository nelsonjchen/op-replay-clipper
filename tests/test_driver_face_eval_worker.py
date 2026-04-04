from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from core import driver_face_eval_worker


class _FakeFrameQueue:
    frame_w = 1928
    frame_h = 1208

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def test_worker_skips_crop_clip_encode_when_manifest_has_no_active_crop(monkeypatch, tmp_path: Path) -> None:
    track_metadata = tmp_path / "right-face-track.json"
    crop_clip = tmp_path / "right-face-crop.mp4"
    source_clip = tmp_path / "driver-source.mp4"
    source_clip.write_bytes(b"source")

    args = SimpleNamespace(
        route="dongle|route",
        route_or_url="https://connect.comma.ai/dongle/route/0/1",
        start_seconds=0,
        length_seconds=1,
        data_dir=str(tmp_path / "data"),
        openpilot_dir=str(tmp_path / "openpilot"),
        sample_id="sample",
        category="test",
        notes="notes",
        track_metadata=str(track_metadata),
        crop_clip=str(crop_clip),
        source_clip=str(source_clip),
        seat_side="right",
        crop_target_mb=4,
        accel="cpu",
    )

    monkeypatch.setattr(driver_face_eval_worker, "parse_args", lambda: args)
    monkeypatch.setattr(
        driver_face_eval_worker,
        "apply_openpilot_runtime_patches",
        lambda _path: SimpleNamespace(changed=False),
    )
    monkeypatch.setattr(driver_face_eval_worker, "_add_openpilot_to_sys_path", lambda _path: None)
    monkeypatch.setattr(driver_face_eval_worker, "build_openpilot_compatible_data_dir", lambda _route, path: path)

    fake_route_module = types.ModuleType("openpilot.tools.lib.route")

    class _FakeRoute:
        def __init__(self, route: str, data_dir: str) -> None:
            self.route = route
            self.data_dir = data_dir

        def dcamera_paths(self) -> list[str]:
            return ["dcamera.hevc"]

    fake_route_module.Route = _FakeRoute
    monkeypatch.setitem(sys.modules, "openpilot.tools.lib.route", fake_route_module)

    monkeypatch.setattr(driver_face_eval_worker, "load_route_metadata", lambda _route: {"device_type": "mici"})
    monkeypatch.setattr(driver_face_eval_worker, "load_segment_messages", lambda _route, **_kwargs: {})
    monkeypatch.setattr(
        driver_face_eval_worker,
        "build_driver_render_steps",
        lambda _messages, **_kwargs: [SimpleNamespace(camera_ref=0, route_seconds=0.0, route_frame_id=0, state={})],
    )

    frame_queue = _FakeFrameQueue()
    monkeypatch.setattr(driver_face_eval_worker, "IndexedFrameQueue", lambda *_args, **_kwargs: frame_queue)

    manifest = {
        "frame_width": 1928,
        "frame_height": 1208,
        "device_type": "mici",
        "seat_side": "right",
        "framerate": 20,
        "crop_side": 256,
        "output_resolution": 256,
        "config": {},
        "frames": [
            {
                "frame_index": 0,
                "crop_rect": None,
            }
        ],
    }
    monkeypatch.setattr(driver_face_eval_worker, "build_face_track_manifest", lambda *_args, **_kwargs: dict(manifest))

    crop_write_calls: list[dict[str, object]] = []

    def _fake_write_face_crop_video(**kwargs) -> None:
        crop_write_calls.append(kwargs)

    monkeypatch.setattr(driver_face_eval_worker, "write_face_crop_video", _fake_write_face_crop_video)

    exit_code = driver_face_eval_worker.main()

    assert exit_code == 0
    assert crop_write_calls == []
    assert frame_queue.stopped is True
    assert crop_clip.exists() is False

    written_manifest = json.loads(track_metadata.read_text())
    assert written_manifest["has_active_crop"] is False

