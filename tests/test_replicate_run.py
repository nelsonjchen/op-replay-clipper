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


class FakePrediction:
    def __init__(self, output=None, status: str = "succeeded", logs: str = "", error: str | None = None, web_url: str = "https://replicate.com/p/test") -> None:
        self.output = output
        self.status = status
        self.logs = logs
        self.error = error
        self.urls = SimpleNamespace(web=web_url)
        self.reload = Mock()


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
        smear_amount=3,
        anonymization_profile="none",
        passenger_redaction_style="blur",
    )
    payload = replicate_run.build_input(args)
    assert payload["renderType"] == "ui"
    assert payload["fileSize"] == 9
    assert payload["anonymizationProfile"] == "none"
    assert payload["passengerRedactionStyle"] == "blur"
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
        smear_amount=3,
        anonymization_profile="none",
        passenger_redaction_style="blur",
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
        smear_amount=3,
        forward_upon_wide_h=2.2,
        anonymization_profile="driver unchanged, passenger hidden",
        passenger_redaction_style="silhouette",
    )

    payload = replicate_run.build_input(args)
    assert payload["renderType"] == "driver-debug"
    assert payload["anonymizationProfile"] == "driver unchanged, passenger hidden"
    assert payload["passengerRedactionStyle"] == "silhouette"


def test_encode_replicate_route_input_preserves_existing_literal_prefix() -> None:
    url = "literal:https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496"
    assert replicate_run.encode_replicate_route_input(url) == url.removeprefix("literal:")


def test_encode_replicate_route_input_wraps_plain_connect_url() -> None:
    url = "https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496"
    assert replicate_run.encode_replicate_route_input(url) == url


def test_normalize_anonymization_profile_label_maps_pixelize_aliases() -> None:
    assert replicate_run.normalize_anonymization_profile_label("driver unchanged, passenger pixelize") == "driver unchanged, passenger hidden"
    assert replicate_run.normalize_anonymization_profile_label("driver face swap, passenger pixelize") == "driver face swap, passenger hidden"


def test_resolve_model_defaults_to_latest_beta_alias() -> None:
    model, explicit = replicate_run.resolve_model("")
    assert model == replicate_run.DEFAULT_MODEL
    assert explicit is False


def test_resolve_model_preserves_explicit_model() -> None:
    model, explicit = replicate_run.resolve_model("nelsonjchen/op-replay-clipper-beta:abc123")
    assert model == "nelsonjchen/op-replay-clipper-beta:abc123"
    assert explicit is True


def test_create_prediction_uses_model_alias_when_version_not_pinned(monkeypatch) -> None:
    create = Mock(return_value="prediction")
    monkeypatch.setattr(replicate_run.replicate.predictions, "create", create)
    prediction = replicate_run.create_prediction("nelsonjchen/op-replay-clipper-beta", {"route": "x"})
    assert prediction == "prediction"
    create.assert_called_once_with(model="nelsonjchen/op-replay-clipper-beta", input={"route": "x"})


def test_create_prediction_uses_version_hash_when_model_is_pinned(monkeypatch) -> None:
    create = Mock(return_value="prediction")
    monkeypatch.setattr(replicate_run.replicate.predictions, "create", create)
    prediction = replicate_run.create_prediction("nelsonjchen/op-replay-clipper-beta:abc123", {"route": "x"})
    assert prediction == "prediction"
    create.assert_called_once_with(version="abc123", input={"route": "x"})


def test_wait_for_prediction_returns_succeeded_prediction(capsys) -> None:
    prediction = FakePrediction(output=FakeFileOutput(b"video"), status="succeeded", logs="done\n")
    result = replicate_run.wait_for_prediction(prediction, poll_interval_seconds=0)
    assert result is prediction
    captured = capsys.readouterr()
    assert "Prediction URL:" in captured.out
    assert "Final status: succeeded" in captured.out


def test_wait_for_prediction_raises_on_failure(capsys) -> None:
    prediction = FakePrediction(status="failed", error="boom")
    try:
        replicate_run.wait_for_prediction(prediction, poll_interval_seconds=0)
    except SystemExit as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("wait_for_prediction should fail failed predictions")
    captured = capsys.readouterr()
    assert "Final status: failed" in captured.out


def test_wait_for_prediction_times_out(monkeypatch) -> None:
    prediction = FakePrediction(status="starting")
    monkeypatch.setattr(replicate_run.time, "sleep", lambda _: None)
    times = iter([0.0, 10.0])
    monkeypatch.setattr(replicate_run.time, "monotonic", lambda: next(times))
    try:
        replicate_run.wait_for_prediction(prediction, poll_interval_seconds=0, timeout_seconds=5)
    except SystemExit as exc:
        assert str(exc) == "Timed out waiting for Replicate prediction after 5s."
    else:
        raise AssertionError("wait_for_prediction should time out")


def test_is_retryable_prediction_error_matches_transient_platform_failure() -> None:
    assert replicate_run.is_retryable_prediction_error("Prediction interrupted; please retry (code: PA)")
    assert replicate_run.is_retryable_prediction_error("Director: unexpected error handling prediction (E8765)")
    assert not replicate_run.is_retryable_prediction_error("validation failed")


def test_run_prediction_with_retries_retries_transient_failure(monkeypatch, capsys) -> None:
    first_prediction = FakePrediction(status="failed", error="Prediction interrupted; please retry (code: PA)")
    second_prediction = FakePrediction(output=FakeFileOutput(b"video"), status="succeeded")
    create_prediction = Mock(side_effect=[first_prediction, second_prediction])
    wait_for_prediction = Mock(side_effect=[SystemExit("Prediction interrupted; please retry (code: PA)"), second_prediction])
    monkeypatch.setattr(replicate_run, "create_prediction", create_prediction)
    monkeypatch.setattr(replicate_run, "wait_for_prediction", wait_for_prediction)

    result = replicate_run.run_prediction_with_retries(
        "nelsonjchen/op-replay-clipper-beta:abc123",
        {"route": "x"},
        retries=2,
        poll_interval_seconds=1,
        timeout_seconds=10,
    )

    assert result is second_prediction
    assert create_prediction.call_count == 2
    assert wait_for_prediction.call_count == 2
    captured = capsys.readouterr()
    assert "Transient hosted failure on attempt 1/3" in captured.out


def test_run_prediction_with_retries_does_not_retry_permanent_failure(monkeypatch) -> None:
    create_prediction = Mock(return_value=FakePrediction(status="failed", error="validation failed"))
    wait_for_prediction = Mock(side_effect=SystemExit("validation failed"))
    monkeypatch.setattr(replicate_run, "create_prediction", create_prediction)
    monkeypatch.setattr(replicate_run, "wait_for_prediction", wait_for_prediction)

    try:
        replicate_run.run_prediction_with_retries(
            "nelsonjchen/op-replay-clipper-beta:abc123",
            {"route": "x"},
            retries=2,
            poll_interval_seconds=1,
            timeout_seconds=10,
        )
    except SystemExit as exc:
        assert str(exc) == "validation failed"
    else:
        raise AssertionError("run_prediction_with_retries should not retry permanent failures")


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
    create_prediction = Mock(return_value=FakePrediction(output=FakeFileOutput(b"video-bytes")))
    run_prediction_with_retries = Mock(return_value=FakePrediction(output=FakeFileOutput(b"video-bytes")))
    monkeypatch.setattr(replicate_run, "run_prediction_with_retries", run_prediction_with_retries)

    output_path = tmp_path / "clip.mp4"
    exit_code = replicate_run.main(["--url", "https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496", "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.read_bytes() == b"video-bytes"
    run_prediction_with_retries.assert_called_once()
    captured = capsys.readouterr()
    assert "Warning: --model was not set; using latest beta alias" in captured.out
    assert replicate_run.DEFAULT_MODEL in captured.out
