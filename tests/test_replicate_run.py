from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import Mock

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
    assert payload["route"].startswith("https://connect.comma.ai/")
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


def test_build_input_allows_driver_debug_render_type() -> None:
    args = SimpleNamespace(
        notes="",
        url="https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496",
        file_size=9,
        jwt_token="",
        file_format="auto",
        render_type="driver-debug",
        smear_amount=5,
        forward_upon_wide_h=2.2,
    )

    payload = replicate_run.build_input(args)
    assert payload["renderType"] == "driver-debug"


def test_encode_replicate_route_input_preserves_existing_literal_prefix() -> None:
    url = "literal:https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496"
    assert replicate_run.encode_replicate_route_input(url) == url.removeprefix("literal:")


def test_encode_replicate_route_input_wraps_plain_connect_url() -> None:
    url = "https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496"
    assert replicate_run.encode_replicate_route_input(url) == url


def test_resolve_model_defaults_to_latest_beta_alias() -> None:
    model, explicit = replicate_run.resolve_model("")
    assert model == replicate_run.DEFAULT_MODEL
    assert explicit is False


def test_resolve_model_preserves_explicit_model() -> None:
    model, explicit = replicate_run.resolve_model("nelsonjchen/op-replay-clipper-beta:abc123")
    assert model == "nelsonjchen/op-replay-clipper-beta:abc123"
    assert explicit is True


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


def test_main_warns_when_model_is_not_explicit(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(replicate_run, "require_api_token", lambda: "token")
    monkeypatch.setattr(replicate_run, "validate_connect_url", lambda url: url)
    replicate_run_call = Mock(return_value=FakeFileOutput(b"video-bytes"))
    monkeypatch.setattr(replicate_run.replicate, "run", replicate_run_call)

    output_path = tmp_path / "clip.mp4"
    exit_code = replicate_run.main(["--url", "https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496", "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.read_bytes() == b"video-bytes"
    replicate_run_call.assert_called_once()
    captured = capsys.readouterr()
    assert "Warning: --model was not set; using latest beta alias" in captured.out
    assert replicate_run.DEFAULT_MODEL in captured.out
