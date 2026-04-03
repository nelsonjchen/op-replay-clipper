from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import driver_face_eval as driver_face_eval_cli
from core import driver_face_eval


class FakeMsg:
    def __init__(self, which: str, payload: object) -> None:
        self._which = which
        setattr(self, which, payload)

    def which(self) -> str:
        return self._which


def test_default_seed_ids_are_stable() -> None:
    assert [seed.sample_id for seed in driver_face_eval.default_driver_face_eval_seeds()] == [
        "mici-baseline",
        "tici-baseline",
        "tici-occlusion",
    ]


def test_expand_face_box_adds_padding_and_keeps_box_in_frame() -> None:
    padded = driver_face_eval.expand_face_box(
        (100.0, 120.0, 80.0, 100.0),
        frame_width=640,
        frame_height=480,
        config=driver_face_eval.FaceTrackConfig(),
    )

    assert padded[2] > 80.0
    assert padded[3] > 100.0
    assert padded[0] >= 0.0
    assert padded[1] >= 0.0
    assert padded[0] + padded[2] <= 640.0
    assert padded[1] + padded[3] <= 480.0


def test_square_crop_rect_clamps_and_even_aligns() -> None:
    crop = driver_face_eval.square_crop_rect(
        center_x=18.0,
        center_y=15.0,
        side=101,
        frame_width=120,
        frame_height=80,
    )

    assert crop == (0, 0, 80, 80)


def test_crop_nv12_frame_extracts_expected_planes() -> None:
    frame_width = 4
    frame_height = 4
    y_plane = bytes(range(16))
    uv_plane = bytes(range(100, 108))
    frame = y_plane + uv_plane

    cropped = driver_face_eval.crop_nv12_frame(
        frame,
        frame_width=frame_width,
        frame_height=frame_height,
        crop_rect=(2, 0, 2, 2),
    )

    assert cropped == bytes([2, 3, 6, 7, 102, 103])


def test_build_face_track_manifest_holds_last_crop_when_detection_drops() -> None:
    driver_data = SimpleNamespace(
        faceProb=0.92,
        leftEyeProb=0.7,
        rightEyeProb=0.72,
        leftBlinkProb=0.1,
        rightBlinkProb=0.11,
        sunglassesProb=0.0,
        phoneProb=0.0,
        faceOrientation=[0.0, 0.0, 0.0],
        facePosition=[0.18, 0.12],
        faceOrientationStd=[0.05, 0.05, 0.03],
        facePositionStd=[0.01, 0.01],
    )
    low_prob_data = SimpleNamespace(**{**driver_data.__dict__, "faceProb": 0.1})
    steps = [
        SimpleNamespace(
            route_seconds=0.0,
            route_frame_id=0,
            state={
                "driverMonitoringState": FakeMsg("driverMonitoringState", SimpleNamespace(faceDetected=True, isRHD=False)),
                "driverStateV2": FakeMsg("driverStateV2", SimpleNamespace(leftDriverData=driver_data, rightDriverData=None, wheelOnRightProb=0.2)),
            },
        ),
        SimpleNamespace(
            route_seconds=0.05,
            route_frame_id=1,
            state={
                "driverMonitoringState": FakeMsg("driverMonitoringState", SimpleNamespace(faceDetected=False, isRHD=False)),
                "driverStateV2": FakeMsg("driverStateV2", SimpleNamespace(leftDriverData=low_prob_data, rightDriverData=None, wheelOnRightProb=0.2)),
            },
        ),
        SimpleNamespace(
            route_seconds=0.1,
            route_frame_id=2,
            state={
                "driverMonitoringState": FakeMsg("driverMonitoringState", SimpleNamespace(faceDetected=False, isRHD=False)),
            },
        ),
    ]

    manifest = driver_face_eval.build_face_track_manifest(
        steps,
        frame_width=1928,
        frame_height=1208,
        device_type="tici",
        config=driver_face_eval.FaceTrackConfig(missing_hold_frames=3),
    )

    assert manifest["crop_side"] >= 192
    assert manifest["frames"][0]["crop_rect"] is not None
    assert manifest["frames"][1]["crop_rect"] is not None
    assert manifest["frames"][1]["held_without_detection"] == 1
    assert manifest["frames"][2]["crop_rect"] is not None
    assert manifest["frames"][2]["held_without_detection"] == 2


def test_build_face_track_manifest_supports_explicit_left_and_right_seats() -> None:
    left_driver = SimpleNamespace(
        faceProb=0.91,
        leftEyeProb=0.7,
        rightEyeProb=0.72,
        leftBlinkProb=0.1,
        rightBlinkProb=0.11,
        sunglassesProb=0.0,
        phoneProb=0.0,
        faceOrientation=[0.0, 0.0, 0.0],
        facePosition=[-0.22, 0.10],
        faceOrientationStd=[0.05, 0.05, 0.03],
        facePositionStd=[0.01, 0.01],
    )
    right_driver = SimpleNamespace(
        faceProb=0.88,
        leftEyeProb=0.6,
        rightEyeProb=0.61,
        leftBlinkProb=0.12,
        rightBlinkProb=0.09,
        sunglassesProb=0.0,
        phoneProb=0.0,
        faceOrientation=[0.0, 0.0, 0.0],
        facePosition=[0.24, 0.08],
        faceOrientationStd=[0.05, 0.05, 0.03],
        facePositionStd=[0.01, 0.01],
    )
    step = SimpleNamespace(
        route_seconds=0.0,
        route_frame_id=0,
        state={
            "driverMonitoringState": FakeMsg("driverMonitoringState", SimpleNamespace(faceDetected=True, isRHD=False)),
            "driverStateV2": FakeMsg("driverStateV2", SimpleNamespace(leftDriverData=left_driver, rightDriverData=right_driver, wheelOnRightProb=0.2)),
        },
    )

    left_manifest = driver_face_eval.build_face_track_manifest(
        [step],
        frame_width=1928,
        frame_height=1208,
        device_type="tici",
        config=driver_face_eval.FaceTrackConfig(),
        seat_side="left",
    )
    right_manifest = driver_face_eval.build_face_track_manifest(
        [step],
        frame_width=1928,
        frame_height=1208,
        device_type="tici",
        config=driver_face_eval.FaceTrackConfig(),
        seat_side="right",
    )

    assert left_manifest["seat_side"] == "left"
    assert right_manifest["seat_side"] == "right"
    assert left_manifest["frames"][0]["seat_side"] == "left"
    assert right_manifest["frames"][0]["seat_side"] == "right"
    assert left_manifest["frames"][0]["crop_rect"] != right_manifest["frames"][0]["crop_rect"]
    assert left_manifest["frames"][0]["is_selected_side"] is True
    assert right_manifest["frames"][0]["is_selected_side"] is False


def test_build_face_track_manifest_requires_strong_non_selected_seat_detection() -> None:
    left_driver = SimpleNamespace(
        faceProb=0.92,
        leftEyeProb=0.7,
        rightEyeProb=0.72,
        leftBlinkProb=0.1,
        rightBlinkProb=0.11,
        sunglassesProb=0.0,
        phoneProb=0.0,
        faceOrientation=[0.0, 0.0, 0.0],
        facePosition=[-0.22, 0.10],
        faceOrientationStd=[0.05, 0.05, 0.03],
        facePositionStd=[0.01, 0.01],
    )
    weak_right_driver = SimpleNamespace(
        faceProb=0.02,
        leftEyeProb=0.0,
        rightEyeProb=0.0,
        leftBlinkProb=0.0,
        rightBlinkProb=0.0,
        sunglassesProb=0.0,
        phoneProb=0.0,
        faceOrientation=[0.0, 0.0, 0.0],
        facePosition=[0.24, 0.08],
        faceOrientationStd=[0.05, 0.05, 0.03],
        facePositionStd=[0.01, 0.01],
    )
    step = SimpleNamespace(
        route_seconds=0.0,
        route_frame_id=0,
        state={
            "driverMonitoringState": FakeMsg("driverMonitoringState", SimpleNamespace(faceDetected=True, isRHD=False)),
            "driverStateV2": FakeMsg("driverStateV2", SimpleNamespace(leftDriverData=left_driver, rightDriverData=weak_right_driver, wheelOnRightProb=0.2)),
        },
    )

    right_manifest = driver_face_eval.build_face_track_manifest(
        [step],
        frame_width=1928,
        frame_height=1208,
        device_type="tici",
        config=driver_face_eval.FaceTrackConfig(),
        seat_side="right",
    )

    assert right_manifest["frames"][0]["face_prob"] == 0.02
    assert right_manifest["frames"][0]["face_detected"] is False
    assert right_manifest["frames"][0]["crop_rect"] is None


@mock.patch("driver_face_eval.materialize_seed_set")
@mock.patch("driver_face_eval._prepare_openpilot")
def test_cli_defaults_to_seed_set(prepare_openpilot: mock.Mock, materialize_seed_set: mock.Mock, tmp_path) -> None:
    prepare_openpilot.return_value = str(tmp_path / "openpilot")
    materialize_seed_set.return_value = []

    exit_code = driver_face_eval_cli.main(["--output-root", str(tmp_path)])

    assert exit_code == 0
    prepare_openpilot.assert_called_once()
    materialize_seed_set.assert_called_once()


@mock.patch("driver_face_eval.load_dotenv")
@mock.patch("driver_face_eval.materialize_seed_set")
@mock.patch("driver_face_eval._prepare_openpilot")
def test_cli_seed_set_uses_comma_jwt_from_env(
    prepare_openpilot: mock.Mock,
    materialize_seed_set: mock.Mock,
    load_dotenv: mock.Mock,
    monkeypatch,
    tmp_path,
) -> None:
    prepare_openpilot.return_value = str(tmp_path / "openpilot")
    materialize_seed_set.return_value = []
    monkeypatch.setenv("COMMA_JWT", "env-jwt-token")

    exit_code = driver_face_eval_cli.main(["--output-root", str(tmp_path), "seed-set"])

    assert exit_code == 0
    load_dotenv.assert_called_once()
    assert materialize_seed_set.call_args.kwargs["jwt_token"] == "env-jwt-token"


@mock.patch("driver_face_eval.materialize_eval_sample")
@mock.patch("driver_face_eval.parseRouteOrUrl")
@mock.patch("driver_face_eval._prepare_openpilot")
def test_cli_sample_allows_explicit_jwt_token_override(
    prepare_openpilot: mock.Mock,
    parse_route_or_url: mock.Mock,
    materialize_eval_sample: mock.Mock,
    tmp_path,
) -> None:
    prepare_openpilot.return_value = str(tmp_path / "openpilot")
    parse_route_or_url.return_value = None
    materialize_eval_sample.return_value = SimpleNamespace(output_dir=str(tmp_path / "sample"))

    exit_code = driver_face_eval_cli.main(
        [
            "--output-root",
            str(tmp_path),
            "--jwt-token",
            "cli-jwt-token",
            "sample",
            "custom-sample",
            "https://connect.comma.ai/fde53c3c109fb4c0/0000026f--c5469f881d/289/315",
            "--start-seconds",
            "289",
            "--length-seconds",
            "26",
        ]
    )

    assert exit_code == 0
    assert parse_route_or_url.call_args.kwargs["jwt_token"] == "cli-jwt-token"
    assert materialize_eval_sample.call_args.kwargs["jwt_token"] == "cli-jwt-token"
