from __future__ import annotations

from types import SimpleNamespace

import replicate_remote


class FakeFileOutput:
    def __init__(self, payload: bytes, url: str = "https://example.com/test.mp4") -> None:
        self._payload = payload
        self.url = url

    def read(self) -> bytes:
        return self._payload


def test_build_input_uses_cog_field_names() -> None:
    args = SimpleNamespace(
        notes="",
        route="a2a0ccea32023010|2023-07-27--13-01-19",
        metric=False,
        file_size=9,
        jwt_token="",
        file_format="auto",
        render_type="ui",
        smear_amount=5,
        start_seconds=50,
        length_seconds=20,
        speedhack_ratio=1.0,
        forward_upon_wide_h=2.2,
    )
    payload = replicate_remote.build_input(args)
    assert payload["renderType"] == "ui"
    assert payload["fileSize"] == 9
    assert payload["startSeconds"] == 50


def test_save_file_output_writes_single_file(tmp_path) -> None:
    output_path = tmp_path / "clip.mp4"
    written = replicate_remote.save_file_output(FakeFileOutput(b"video-bytes"), output_path)
    assert written == output_path.resolve()
    assert output_path.read_bytes() == b"video-bytes"


def test_save_file_output_accepts_single_item_iterable(tmp_path) -> None:
    output_path = tmp_path / "clip.mp4"
    written = replicate_remote.save_file_output([FakeFileOutput(b"video-bytes")], output_path)
    assert written == output_path.resolve()
    assert output_path.read_bytes() == b"video-bytes"
