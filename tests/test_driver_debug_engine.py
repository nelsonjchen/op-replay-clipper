from __future__ import annotations

from types import SimpleNamespace

from renderers import driver_debug_engine


class FakeMsg:
    def __init__(self, which: str, log_mono_time: int, payload: object) -> None:
        self._which = which
        self.logMonoTime = log_mono_time
        setattr(self, which, payload)

    def which(self) -> str:
        return self._which


def test_build_driver_render_steps_uses_driver_camera_state_and_encode_index() -> None:
    segments = [
        [
            FakeMsg("driverEncodeIdx", 0, SimpleNamespace(frameId=40, timestampSof=4_000, timestampEof=4_050)),
            FakeMsg("driverStateV2", 1, SimpleNamespace()),
            FakeMsg("driverCameraState", 2, SimpleNamespace(frameId=40, timestampEof=4_050)),
        ]
    ]

    steps = driver_debug_engine.build_driver_render_steps(segments, start=1, end=3)

    assert len(steps) == 1
    assert steps[0].route_frame_id == 40
    assert steps[0].camera_ref.route_frame_id == 40
    assert steps[0].state["driverCameraState"].driverCameraState.frameId == 40


def test_build_driver_render_steps_can_fall_back_to_timestamp_match() -> None:
    segments = [
        [
            FakeMsg("driverEncodeIdx", 0, SimpleNamespace(frameId=41, timestampSof=4_100, timestampEof=4_150)),
            FakeMsg("driverCameraState", 2, SimpleNamespace(frameId=9999, timestampEof=4_150)),
        ]
    ]

    steps = driver_debug_engine.build_driver_render_steps(segments, start=1, end=3)

    assert len(steps) == 1
    assert steps[0].camera_ref.route_frame_id == 41


def test_extract_driver_debug_telemetry_prefers_dm_side_and_exposes_key_metrics() -> None:
    dm_state = SimpleNamespace(
        faceDetected=True,
        isDistracted=True,
        distractedType=3,
        awarenessStatus=0.42,
        awarenessActive=0.5,
        awarenessPassive=0.9,
        stepChange=0.01,
        hiStdCount=7,
        uncertainCount=2,
        isLowStd=False,
        isActiveMode=True,
        isRHD=True,
        posePitchOffset=0.12,
        posePitchValidCount=33,
        poseYawOffset=-0.04,
        poseYawValidCount=44,
        events=[SimpleNamespace(name="promptDriverDistracted")],
    )
    left_driver = SimpleNamespace(faceProb=0.1)
    right_driver = SimpleNamespace(
        faceProb=0.91,
        leftEyeProb=0.82,
        rightEyeProb=0.77,
        leftBlinkProb=0.22,
        rightBlinkProb=0.44,
        sunglassesProb=0.31,
        phoneProb=0.66,
        faceOrientation=[1.0, 2.0, 3.0],
        facePosition=[0.1, -0.2],
        faceOrientationStd=[0.11, 0.12, 0.13],
        facePositionStd=[0.21, 0.22],
    )
    driver_state = SimpleNamespace(
        wheelOnRightProb=0.88,
        modelExecutionTime=0.023,
        gpuExecutionTime=0.004,
        leftDriverData=left_driver,
        rightDriverData=right_driver,
    )
    car_state = SimpleNamespace(steeringPressed=True, gasPressed=False, standstill=False, vEgo=13.4)
    selfdrive_state = SimpleNamespace(enabled=True)

    telemetry = driver_debug_engine.extract_driver_debug_telemetry(
        {
            "driverMonitoringState": FakeMsg("driverMonitoringState", 0, dm_state),
            "driverStateV2": FakeMsg("driverStateV2", 0, driver_state),
            "carState": FakeMsg("carState", 0, car_state),
            "selfdriveState": FakeMsg("selfdriveState", 0, selfdrive_state),
        }
    )

    assert telemetry.alert_name == "promptDriverDistracted"
    assert telemetry.selected_side == "right"
    assert telemetry.face_detected is True
    assert telemetry.is_distracted is True
    assert telemetry.face_prob == 0.91
    assert telemetry.phone_prob == 0.66
    assert telemetry.face_orientation == (1.0, 2.0, 3.0)
    assert telemetry.pitch_valid_count == 33
    assert telemetry.engaged is True
    assert telemetry.steering_pressed is True
    assert telemetry.v_ego == 13.4


def test_extract_driver_debug_telemetry_falls_back_to_wheel_probability_when_dm_missing() -> None:
    left_driver = SimpleNamespace(faceProb=0.2)
    right_driver = SimpleNamespace(faceProb=0.7)
    driver_state = SimpleNamespace(
        wheelOnRightProb=0.75,
        leftDriverData=left_driver,
        rightDriverData=right_driver,
    )

    telemetry = driver_debug_engine.extract_driver_debug_telemetry(
        {
            "driverStateV2": FakeMsg("driverStateV2", 0, driver_state),
        }
    )

    assert telemetry.is_rhd is True
    assert telemetry.selected_side == "right"
    assert telemetry.face_prob == 0.7


def test_driver_camera_dialog_module_uses_mici_variant_for_mici_routes() -> None:
    assert driver_debug_engine._driver_camera_dialog_module(device_type="mici") == "openpilot.selfdrive.ui.mici.onroad.driver_camera_dialog"
    assert driver_debug_engine._driver_camera_dialog_module(device_type="tici") == "openpilot.selfdrive.ui.onroad.driver_camera_dialog"


def test_compute_driver_face_box_rect_expands_and_biases_estimate_for_yaw() -> None:
    class Rect:
        x = 0.0
        y = 0.0
        width = 1920.0
        height = 1080.0

    driver_data = SimpleNamespace(
        facePosition=[0.197, 0.158],
        facePositionStd=[0.0026, 0.0067],
        faceOrientation=[-0.011, 0.726, -0.039],
        faceOrientationStd=[0.097, 0.086, 0.076],
    )

    box = driver_debug_engine.compute_driver_face_box_rect(Rect(), driver_data=driver_data, device_type="mici")

    assert box is not None
    box_x, box_y, box_w, box_h = box
    assert box_w > 150
    assert box_h > box_w

    anchor_x, _ = driver_debug_engine._driver_face_anchor(Rect(), face_x=0.197, face_y=0.158, device_type="mici")
    box_center_x = box_x + (box_w / 2)
    assert box_center_x < anchor_x
