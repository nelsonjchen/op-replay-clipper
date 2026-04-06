from __future__ import annotations

import argparse
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
    assert telemetry.other_side == "left"
    assert telemetry.face_detected is True
    assert telemetry.is_distracted is True
    assert telemetry.face_prob == 0.91
    assert telemetry.other_face_prob == 0.1
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
    assert telemetry.other_side == "left"
    assert telemetry.face_prob == 0.7
    assert telemetry.other_face_prob == 0.2


def test_driver_camera_dialog_module_uses_mici_variant_for_mici_routes() -> None:
    assert driver_debug_engine._driver_camera_dialog_module(device_type="mici") == "openpilot.selfdrive.ui.mici.onroad.driver_camera_dialog"
    assert driver_debug_engine._driver_camera_dialog_module(device_type="tici") == "openpilot.selfdrive.ui.onroad.driver_camera_dialog"


def test_normalize_cli_paths_resolves_relative_paths_against_original_cwd(tmp_path) -> None:
    args = argparse.Namespace(
        openpilot_dir="openpilot",
        output="shared/out.mp4",
        data_dir="shared/data_dir",
        backing_video="shared/backing.mp4",
    )

    normalized = driver_debug_engine._normalize_cli_paths(args, cwd=tmp_path)

    assert normalized.openpilot_dir == str((tmp_path / "openpilot").resolve())
    assert normalized.output == str((tmp_path / "shared/out.mp4").resolve())
    assert normalized.data_dir == str((tmp_path / "shared/data_dir").resolve())
    assert normalized.backing_video == str((tmp_path / "shared/backing.mp4").resolve())


def test_humanize_platform_preserves_raw_platform_text() -> None:
    assert driver_debug_engine._humanize_platform("FORD_BRONCO_SPORT_MK1") == "FORD_BRONCO_SPORT_MK1"
    assert driver_debug_engine._humanize_platform("") == "unknown"


def test_humanize_git_remote_and_git_metadata_text_compact_openpilot_repo_info() -> None:
    assert driver_debug_engine._humanize_git_remote("https://github.com/commaai/openpilot.git") == "commaai/openpilot"
    assert driver_debug_engine._humanize_git_remote("git@github.com:commaai/openpilot.git") == "commaai/openpilot"
    assert (
        driver_debug_engine._git_metadata_text(
            {
                "remote": "https://github.com/commaai/openpilot.git",
                "branch": "release3-staging",
                "commit": "deadbeef",
                "dirty": "false",
            }
        )
        == "commaai/openpilot  •  release3-staging  •  deadbeef  •  dirty false"
    )


def test_driver_face_anchor_uses_upstream_style_projection_for_unmirrored_mici_view() -> None:
    class Rect:
        x = 0.0
        y = 0.0
        width = 1910.0
        height = 1080.0

    anchor_x, anchor_y = driver_debug_engine._driver_face_anchor(
        Rect(), face_x=0.19, face_y=0.16, device_type="mici"
    )

    assert round(anchor_x, 2) == 1314.96
    assert round(anchor_y, 2) == 566.34


def test_compute_driver_monitoring_input_quad_matches_tici_dm_crop() -> None:
    class Rect:
        x = 0.0
        y = 0.0
        width = 1928.0
        height = 1208.0

    quad = driver_debug_engine.compute_driver_monitoring_input_quad(
        Rect(),
        frame_width=1928.0,
        frame_height=1208.0,
    )

    assert quad is not None
    assert quad[0] == (244.0, 248.0)
    assert quad[1] == (1683.0, 248.0)
    assert quad[2] == (1683.0, 1207.0)
    assert quad[3] == (244.0, 1207.0)


def test_compute_driver_monitoring_input_quad_matches_mici_dm_crop_and_bottom_overhang() -> None:
    class Rect:
        x = 0.0
        y = 0.0
        width = 1344.0
        height = 760.0

    quad = driver_debug_engine.compute_driver_monitoring_input_quad(
        Rect(),
        frame_width=1344.0,
        frame_height=760.0,
    )

    assert quad is not None
    assert round(quad[0][0], 2) == 132.0
    assert round(quad[0][1], 2) == 113.0
    assert round(quad[1][0], 2) == 1211.25
    assert round(quad[1][1], 2) == 113.0
    assert round(quad[3][0], 2) == 132.0
    assert quad[2][1] > Rect.height


def test_compute_driver_face_box_rect_stays_close_to_anchor_while_expanding_for_yaw() -> None:
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
    assert box_center_x > anchor_x
    assert (box_center_x - anchor_x) < 90


def test_compute_driver_face_box_rect_biases_center_in_yaw_direction() -> None:
    class Rect:
        x = 0.0
        y = 0.0
        width = 1920.0
        height = 1080.0

    neutral_driver_data = SimpleNamespace(
        facePosition=[0.19, 0.16],
        facePositionStd=[0.0, 0.01],
        faceOrientation=[0.09, 0.0, 0.0],
        faceOrientationStd=[0.06, 0.06, 0.04],
    )
    yawed_driver_data = SimpleNamespace(
        facePosition=[0.19, 0.16],
        facePositionStd=[0.0, 0.01],
        faceOrientation=[0.09, 0.49, 0.0],
        faceOrientationStd=[0.06, 0.06, 0.04],
    )

    neutral_box = driver_debug_engine.compute_driver_face_box_rect(
        Rect(), driver_data=neutral_driver_data, device_type="mici"
    )
    yawed_box = driver_debug_engine.compute_driver_face_box_rect(
        Rect(), driver_data=yawed_driver_data, device_type="mici"
    )

    assert neutral_box is not None
    assert yawed_box is not None

    neutral_center_x = neutral_box[0] + (neutral_box[2] / 2)
    yawed_center_x = yawed_box[0] + (yawed_box[2] / 2)

    assert yawed_center_x > neutral_center_x
    assert yawed_box[2] > neutral_box[2]


def test_compute_driver_face_box_rect_preserves_tici_yaw_behavior_without_leaving_frame() -> None:
    class Rect:
        x = 0.0
        y = 0.0
        width = 1920.0
        height = 1080.0

    neutral_driver_data = SimpleNamespace(
        facePosition=[0.03, 0.12],
        facePositionStd=[0.005, 0.01],
        faceOrientation=[0.02, 0.0, 0.0],
        faceOrientationStd=[0.05, 0.06, 0.02],
    )
    yawed_driver_data = SimpleNamespace(
        facePosition=[0.03, 0.12],
        facePositionStd=[0.005, 0.01],
        faceOrientation=[0.02, 0.45, 0.0],
        faceOrientationStd=[0.05, 0.06, 0.02],
    )

    neutral_box = driver_debug_engine.compute_driver_face_box_rect(
        Rect(), driver_data=neutral_driver_data, device_type="tici"
    )
    yawed_box = driver_debug_engine.compute_driver_face_box_rect(
        Rect(), driver_data=yawed_driver_data, device_type="tici"
    )

    assert neutral_box is not None
    assert yawed_box is not None

    neutral_center_x = neutral_box[0] + (neutral_box[2] / 2)
    yawed_center_x = yawed_box[0] + (yawed_box[2] / 2)

    assert yawed_center_x > neutral_center_x
    assert yawed_box[2] > neutral_box[2]
    assert 0.0 <= yawed_box[0] <= Rect.width - yawed_box[2]
    assert 0.0 <= yawed_box[1] <= Rect.height - yawed_box[3]


def test_compute_driver_face_box_rect_clamps_extreme_positions_to_visible_rect() -> None:
    class Rect:
        x = 0.0
        y = 0.0
        width = 1920.0
        height = 1080.0

    driver_data = SimpleNamespace(
        facePosition=[-0.85, 0.05],
        facePositionStd=[0.04, 0.03],
        faceOrientation=[0.0, -0.6, 0.0],
        faceOrientationStd=[0.08, 0.09, 0.02],
    )

    box = driver_debug_engine.compute_driver_face_box_rect(Rect(), driver_data=driver_data, device_type="mici")

    assert box is not None
    box_x, box_y, box_w, box_h = box
    assert 0.0 <= box_x <= Rect.width - box_w
    assert 0.0 <= box_y <= Rect.height - box_h


def test_install_unmirrored_driver_camera_patches_nested_camera_view() -> None:
    original_render = lambda rect: None
    camera_view = SimpleNamespace(_render=original_render)
    driver_view = SimpleNamespace(_camera_view=camera_view)

    driver_debug_engine._install_unmirrored_driver_camera(driver_view, device_type="tici")

    assert camera_view._render is not original_render
    assert getattr(camera_view._render, "__self__", None) is camera_view


def test_driver_debug_timer_text_uses_shared_total_seconds_format() -> None:
    assert driver_debug_engine.format_route_timer_text(90.95, prefix="T+") == "T+01:30 • 90s"
