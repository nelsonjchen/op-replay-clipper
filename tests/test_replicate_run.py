from __future__ import annotations

from types import SimpleNamespace

from core import route_inputs
import replicate_run


class FakeFileOutput:
    def __init__(self, payload: bytes, url: str = "https://example.com/test.mp4") -> None:
        self._payload = payload
        self.url = url

    def read(self) -> bytes:
        return self._payload


class FakeSourcePath:
    def __init__(self, source: str, rendered_path: str = "/tmp/cog-input") -> None:
        self.source = source
        self._rendered_path = rendered_path

    def __fspath__(self) -> str:
        return self._rendered_path

    def __str__(self) -> str:
        return self._rendered_path


def test_build_input_uses_cog_field_names() -> None:
    args = SimpleNamespace(
        notes="",
        url="https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496",
        file_size=9,
        jwt_token="",
        file_format="auto",
        render_type="ui",
        smear_amount=5,
    )
    payload = replicate_run.build_input(args)
    assert payload["renderType"] == "ui"
    assert payload["fileSize"] == 9
    assert payload["route"].startswith("literal:https://connect.comma.ai/")
    assert "metric" not in payload


def test_build_input_allows_ui_alt_render_type() -> None:
    args = SimpleNamespace(
        notes="",
        url="https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496",
        file_size=9,
        jwt_token="",
        file_format="auto",
        render_type="ui-alt",
        smear_amount=5,
    )

    payload = replicate_run.build_input(args)
    assert payload["renderType"] == "ui-alt"


def test_encode_replicate_route_input_preserves_existing_literal_prefix() -> None:
    url = "literal:https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496"
    assert replicate_run.encode_replicate_route_input(url) == url


def test_encode_replicate_route_input_wraps_plain_connect_url() -> None:
    url = "https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496"
    assert replicate_run.encode_replicate_route_input(url) == f"literal:{url}"


def test_validate_connect_url_rejects_non_connect_hosts() -> None:
    try:
        replicate_run.validate_connect_url("https://example.com/not-connect")
    except SystemExit as exc:
        assert str(exc) == "Expected a full https://connect.comma.ai/... clip URL."
    else:
        raise AssertionError("validate_connect_url should reject non-connect URLs")


def test_route_validator_accepts_connect_url() -> None:
    url = "https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496"
    assert route_inputs.validate_connect_url(url) == url


def test_route_validator_accepts_literal_prefixed_connect_url() -> None:
    url = "literal:https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496"
    assert route_inputs.validate_connect_url(url) == url.removeprefix("literal:")


def test_route_validator_prefers_source_url_over_rendered_path() -> None:
    url = "https://connect.comma.ai/5beb9b58bd12b691/0000010a--a51155e496/90/105"
    assert route_inputs.validate_connect_url(FakeSourcePath(url)) == url


def test_save_file_output_writes_single_file(tmp_path) -> None:
    output_path = tmp_path / "clip.mp4"
    written = replicate_run.save_file_output(FakeFileOutput(b"video-bytes"), output_path)
    assert written == output_path.resolve()
    assert output_path.read_bytes() == b"video-bytes"


def test_save_file_output_accepts_single_item_iterable(tmp_path) -> None:
    output_path = tmp_path / "clip.mp4"
    written = replicate_run.save_file_output([FakeFileOutput(b"video-bytes")], output_path)
    assert written == output_path.resolve()
    assert output_path.read_bytes() == b"video-bytes"
