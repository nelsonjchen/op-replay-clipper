from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from core import openpilot_integration, render_runtime
from renderers import big_ui_engine, ui_renderer


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


def test_build_render_steps_future_backfills_car_params_for_early_frames() -> None:
    car_params = FakeMsg("carParams", 40_000_000, SimpleNamespace(openpilotLongitudinalControl=True))
    segments = [
        [
            FakeMsg("roadEncodeIdx", 0, SimpleNamespace(frameId=10, timestampSof=1_000, timestampEof=2_000)),
            FakeMsg("roadCameraState", 10_000_000, SimpleNamespace(frameId=10, timestampEof=2_000)),
            FakeMsg("modelV2", 30_000_000, SimpleNamespace(frameId=10, timestampEof=2_000)),
            car_params,
        ]
    ]

    steps = big_ui_engine.build_render_steps(segments, seg_start=0, start=0, end=1)

    assert len(steps) == 1
    assert steps[0].state["carParams"] is car_params
    assert steps[0].state["carParams"].carParams.openpilotLongitudinalControl is True


def test_build_layout_rects_default_uses_full_canvas() -> None:
    rects = big_ui_engine.build_layout_rects(width=1920, height=1080, layout_mode="default")

    assert rects.road_rect == (0, 0, 1920, 1080)
    assert rects.footer_rect is None


def test_reapply_hidden_window_flag_sets_hidden_state(monkeypatch) -> None:
    called: list[int] = []
    fake_pyray = SimpleNamespace(
        rl=SimpleNamespace(SetWindowState=lambda value: called.append(value)),
        ConfigFlags=SimpleNamespace(FLAG_WINDOW_HIDDEN=0x80),
    )
    monkeypatch.setitem(sys.modules, "pyray", fake_pyray)

    big_ui_engine._reapply_hidden_window_flag(headless=True)

    assert called == [0x80]


def test_build_layout_rects_alt_reserves_footer() -> None:
    rects = big_ui_engine.build_layout_rects(width=1920, height=1080, layout_mode="alt")

    assert rects.road_rect == (0, 0, 1920, 810)
    assert rects.wide_rect is None
    assert rects.footer_rect == (0, 810, 1920, 270)


def test_build_layout_rects_alt_with_wide_splits_camera_area() -> None:
    rects = big_ui_engine.build_layout_rects(width=1920, height=1080, layout_mode="alt", show_wide_panel=True)

    assert rects.road_rect == (0, 0, 1920, 405)
    assert rects.wide_rect == (0, 405, 1920, 405)
    assert rects.footer_rect == (0, 810, 1920, 270)


def test_compute_ui_alt_dual_canvas_height_preserves_full_height_views() -> None:
    assert big_ui_engine.compute_ui_alt_footer_height(1080) == 270
    assert big_ui_engine.compute_ui_alt_dual_canvas_height(1080) == 2430


def test_build_layout_rects_alt_with_wide_can_keep_footer_as_addon() -> None:
    rects = big_ui_engine.build_layout_rects(
        width=2160,
        height=2430,
        layout_mode="alt",
        show_wide_panel=True,
        footer_height_override=270,
    )

    assert rects.road_rect == (0, 0, 2160, 1080)
    assert rects.wide_rect == (0, 1080, 2160, 1080)
    assert rects.footer_rect == (0, 2160, 2160, 270)


def test_compute_ui_alt_panel_label_position_uses_safe_inset() -> None:
    assert big_ui_engine.compute_ui_alt_panel_label_position((0, 0, 2160, 1080)) == (32, 28)
    assert big_ui_engine.compute_ui_alt_panel_label_position((0, 1080, 2160, 1080)) == (32, 1108)


def test_redraw_ui_alt_dual_view_borders_redraws_both_panels(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    fake_rl = SimpleNamespace(Rectangle=lambda x, y, width, height: (x, y, width, height))
    monkeypatch.setitem(sys.modules, "pyray", fake_rl)

    road_view = SimpleNamespace(_draw_border=lambda rect: calls.append(("road", rect)))
    wide_view = SimpleNamespace(_draw_border=lambda rect: calls.append(("wide", rect)))
    layout_rects = big_ui_engine.LayoutRects(
        road_rect=(0, 0, 2160, 1080),
        wide_rect=(0, 1080, 2160, 1080),
    )

    big_ui_engine.redraw_ui_alt_dual_view_borders(road_view, wide_view, layout_rects)

    assert calls == [
        ("road", (0, 0, 2160, 1080)),
        ("wide", (0, 1080, 2160, 1080)),
    ]


def test_extract_steering_angle_deg_uses_car_state_when_present() -> None:
    state = {
        "carState": FakeMsg("carState", 0, SimpleNamespace(steeringAngleDeg=12.5)),
    }

    assert big_ui_engine.extract_steering_angle_deg(state) == 12.5


def test_extract_steering_angle_deg_defaults_to_zero_when_missing() -> None:
    assert big_ui_engine.extract_steering_angle_deg({}) == 0.0


def test_draw_current_speed_overlay_is_noop_without_required_hud_fields() -> None:
    view = SimpleNamespace(
        _content_rect="content-rect",
        _hud_renderer=SimpleNamespace(),
    )

    big_ui_engine.draw_current_speed_overlay(view)


def test_redraw_ui_alt_dual_view_overlays_redraws_both_huds(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    road_view = object()
    wide_view = object()
    state = {"modelV2": object()}

    monkeypatch.setattr(
        big_ui_engine,
        "draw_ui_alt_model_input_overlays",
        lambda road, wide, current_state: calls.append(("model", (road, wide, current_state))),
    )
    monkeypatch.setattr(big_ui_engine, "redraw_hud_overlay", lambda view: calls.append(("hud", view)))

    big_ui_engine.redraw_ui_alt_dual_view_overlays(road_view, wide_view, state)

    assert calls == [
        ("model", (road_view, wide_view, state)),
        ("hud", road_view),
        ("hud", wide_view),
    ]


def test_project_model_input_quad_projects_corners_to_screen() -> None:
    quad = big_ui_engine.project_model_input_quad(
        model_size=(4, 3),
        warp_matrix=(
            (2.0, 0.0, 10.0),
            (0.0, 2.0, 20.0),
            (0.0, 0.0, 1.0),
        ),
        video_transform=(
            (1.0, 0.0, 5.0),
            (0.0, 1.0, 7.0),
            (0.0, 0.0, 1.0),
        ),
    )

    assert quad == ((15.0, 27.0), (21.0, 27.0), (21.0, 31.0), (15.0, 31.0))


def test_compute_model_input_overlay_quad_uses_requested_camera_geometry(monkeypatch) -> None:
    fake_model_module = SimpleNamespace(
        MEDMODEL_INPUT_SIZE=(4, 3),
        SBIGMODEL_INPUT_SIZE=(8, 5),
        get_warp_matrix=lambda *_args, **_kwargs: (
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
    )
    monkeypatch.setitem(sys.modules, "openpilot", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "openpilot.common", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "openpilot.common.transformations", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "openpilot.common.transformations.model", fake_model_module)
    monkeypatch.setattr(
        big_ui_engine,
        "compute_camera_view_video_transform",
        lambda *_args, **_kwargs: (
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ),
    )

    view = SimpleNamespace(
        device_camera=SimpleNamespace(
            fcam=SimpleNamespace(intrinsics=((1.0, 0.0, 2.0), (0.0, 1.0, 1.0), (0.0, 0.0, 1.0))),
            ecam=SimpleNamespace(intrinsics=((1.0, 0.0, 4.0), (0.0, 1.0, 2.0), (0.0, 0.0, 1.0))),
        )
    )
    state = {
        "liveCalibration": FakeMsg("liveCalibration", 0, SimpleNamespace(rpyCalib=[0.0, 0.0, 0.0])),
    }

    road_quad = big_ui_engine.compute_model_input_overlay_quad(
        view,
        state,
        use_wide_camera=False,
        bigmodel_frame=False,
    )
    wide_quad = big_ui_engine.compute_model_input_overlay_quad(
        view,
        state,
        use_wide_camera=True,
        bigmodel_frame=True,
    )

    assert road_quad == ((0.0, 0.0), (3.0, 0.0), (3.0, 2.0), (0.0, 2.0))
    assert wide_quad == ((0.0, 0.0), (7.0, 0.0), (7.0, 4.0), (0.0, 4.0))


def test_compute_model_input_overlay_quad_returns_none_without_live_calibration() -> None:
    view = SimpleNamespace()

    quad = big_ui_engine.compute_model_input_overlay_quad(
        view,
        {},
        use_wide_camera=False,
        bigmodel_frame=False,
    )

    assert quad is None


def test_draw_ui_alt_model_input_overlays_draws_road_and_wide(monkeypatch) -> None:
    calls: list[tuple[bool, bool]] = []
    drawn: list[tuple[tuple[tuple[float, float], ...], object]] = []

    def fake_compute(_view, _state, *, use_wide_camera: bool, bigmodel_frame: bool):
        calls.append((use_wide_camera, bigmodel_frame))
        return ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))

    monkeypatch.setattr(big_ui_engine, "compute_model_input_overlay_quad", fake_compute)
    monkeypatch.setattr(
        big_ui_engine,
        "draw_model_input_overlay",
        lambda quad, *, clip_rect=None: drawn.append((quad, clip_rect)),
    )

    road_rect = SimpleNamespace(x=1, y=2, width=3, height=4)
    wide_rect = SimpleNamespace(x=5, y=6, width=7, height=8)
    big_ui_engine.draw_ui_alt_model_input_overlays(
        SimpleNamespace(_content_rect=road_rect),
        SimpleNamespace(_content_rect=wide_rect),
        {},
    )

    assert calls == [(False, False), (True, True)]
    assert drawn == [
        (((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), road_rect),
        (((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), wide_rect),
    ]


def test_draw_model_input_overlay_scissors_to_clip_rect(monkeypatch) -> None:
    events: list[tuple] = []

    fake_rl = SimpleNamespace(
        Color=lambda *args: ("color", args),
        Vector2=lambda x, y: (x, y),
        begin_scissor_mode=lambda x, y, w, h: events.append(("begin", x, y, w, h)),
        draw_line_ex=lambda start, end, width, color: events.append(("line", start, end, width, color)),
        end_scissor_mode=lambda: events.append(("end",)),
    )
    monkeypatch.setitem(sys.modules, "pyray", fake_rl)

    big_ui_engine.draw_model_input_overlay(
        ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        clip_rect=SimpleNamespace(x=11, y=12, width=13, height=14),
    )

    assert events[0] == ("begin", 11, 12, 13, 14)
    assert events[-1] == ("end",)


def test_compute_shader_gradient_vectors_uses_view_rect_not_full_canvas() -> None:
    origin_rect = SimpleNamespace(x=0.0, y=1080.0, width=2160.0, height=1080.0)
    gradient = SimpleNamespace(start=(0.0, 1.0), end=(0.0, 0.0))

    start_xy, end_xy = big_ui_engine.compute_shader_gradient_vectors(origin_rect, gradient, screen_height=2430.0)

    assert start_xy == (0.0, 1350.0)
    assert end_xy == (0.0, 270.0)


def test_extract_footer_telemetry_reads_driver_and_op_inputs() -> None:
    state = {
        "carState": FakeMsg(
            "carState",
            0,
            SimpleNamespace(
                steeringAngleDeg=12.5,
                steeringPressed=True,
                leftBlinker=True,
                rightBlinker=False,
                gasDEPRECATED=0.25,
                brake=0.1,
                gasPressed=True,
                brakePressed=False,
                aEgo=0.4,
            ),
        ),
        "carControl": FakeMsg(
            "carControl",
            0,
            SimpleNamespace(
                actuators=SimpleNamespace(accel=1.2, steeringAngleDeg=10.0),
            ),
        ),
        "carOutput": FakeMsg(
            "carOutput",
            0,
            SimpleNamespace(
                actuatorsOutput=SimpleNamespace(accel=1.1, steeringAngleDeg=10.4),
            ),
        ),
        "longitudinalPlan": FakeMsg(
            "longitudinalPlan",
            0,
            SimpleNamespace(aTarget=0.6, accels=[0.7]),
        ),
        "modelV2": FakeMsg(
            "modelV2",
            0,
            SimpleNamespace(
                meta=SimpleNamespace(
                    disengagePredictions=SimpleNamespace(
                        brakeDisengageProbs=[0.1, 0.2],
                        steerOverrideProbs=[0.3],
                    )
                )
            ),
        ),
        "selfdriveState": FakeMsg(
            "selfdriveState",
            0,
            SimpleNamespace(enabled=True, state="enabled"),
        ),
    }

    telemetry = big_ui_engine.extract_footer_telemetry(state)

    assert telemetry.steering_angle_deg == 12.5
    assert telemetry.steering_target_deg == 10.0
    assert telemetry.steering_applied_deg == 10.4
    assert telemetry.steering_pressed is True
    assert telemetry.left_blinker is True
    assert telemetry.right_blinker is False
    assert telemetry.driver_gas == 0.25
    assert telemetry.driver_brake == 0.1
    assert telemetry.driver_gas_pressed is True
    assert telemetry.driver_brake_pressed is False
    assert telemetry.op_gas == 0.3
    assert telemetry.op_brake == 0.0
    assert telemetry.accel_cmd == 1.2
    assert telemetry.accel_out == 1.1
    assert telemetry.a_ego == 0.4
    assert telemetry.a_target == 0.6
    assert telemetry.confidence == pytest.approx(0.56)
    assert telemetry.ui_status == "engaged"


def test_extract_footer_telemetry_uses_controls_state_as_steering_target_fallback() -> None:
    state = {
        "carState": FakeMsg(
            "carState",
            0,
            SimpleNamespace(
                steeringAngleDeg=-5.2,
                steeringPressed=False,
            ),
        ),
        "controlsState": FakeMsg(
            "controlsState",
            0,
            SimpleNamespace(
                lateralControlState=SimpleNamespace(
                    angleState=SimpleNamespace(steeringAngleDesiredDeg=-5.5),
                )
            ),
        ),
    }

    telemetry = big_ui_engine.extract_footer_telemetry(state)

    assert telemetry.steering_angle_deg == -5.2
    assert telemetry.steering_target_deg == -5.5
    assert telemetry.steering_applied_deg is None
    assert telemetry.steering_pressed is False


def test_extract_footer_telemetry_falls_back_to_plan_accels_and_brake_command() -> None:
    state = {
        "carControl": FakeMsg(
            "carControl",
            0,
            SimpleNamespace(
                actuators=SimpleNamespace(accel=-2.0),
            ),
        ),
        "longitudinalPlan": FakeMsg(
            "longitudinalPlan",
            0,
            SimpleNamespace(accels=[-1.5]),
        ),
    }

    telemetry = big_ui_engine.extract_footer_telemetry(state)

    assert telemetry.op_gas == 0.0
    assert telemetry.op_brake == 0.5
    assert telemetry.a_target == -1.5
    assert telemetry.confidence == 0.0
    assert telemetry.ui_status == "disengaged"


def test_extract_footer_telemetry_maps_preenabled_to_override() -> None:
    state = {
        "modelV2": FakeMsg(
            "modelV2",
            0,
            SimpleNamespace(
                meta=SimpleNamespace(
                    disengagePredictions=SimpleNamespace(
                        brakeDisengageProbs=[0.1],
                        steerOverrideProbs=[0.2],
                    )
                )
            ),
        ),
        "selfdriveState": FakeMsg(
            "selfdriveState",
            0,
            SimpleNamespace(
                enabled=False,
                state="preEnabled",
            ),
        ),
    }

    telemetry = big_ui_engine.extract_footer_telemetry(state)

    assert telemetry.confidence == pytest.approx(0.72)
    assert telemetry.ui_status == "override"


def test_build_footer_panel_layout_reserves_confidence_rail() -> None:
    layout = big_ui_engine.build_footer_panel_layout(SimpleNamespace(x=0.0, y=810.0, width=1920.0, height=270.0))

    assert layout.meter_w > 120.0
    assert layout.confidence_rect == pytest.approx((1802.0, 834.0, 84.0, 222.0))
    assert layout.accel_rect == pytest.approx((763.6, 1024.0, 1014.4, 54.0))


def test_footer_confidence_target_value_uses_hidden_disengaged_target() -> None:
    assert big_ui_engine.footer_confidence_target_value(status="disengaged", confidence=0.9) == -0.5
    assert big_ui_engine.footer_confidence_target_value(status="engaged", confidence=0.9) == 0.9


def test_footer_confidence_colors_match_mici_thresholds() -> None:
    assert big_ui_engine.footer_confidence_colors(status="engaged", confidence_value=0.7) == (
        (0, 255, 204, 255),
        (0, 255, 38, 255),
    )
    assert big_ui_engine.footer_confidence_colors(status="engaged", confidence_value=0.3) == (
        (255, 200, 0, 255),
        (255, 115, 0, 255),
    )
    assert big_ui_engine.footer_confidence_colors(status="engaged", confidence_value=0.1) == (
        (255, 0, 21, 255),
        (255, 0, 89, 255),
    )
    assert big_ui_engine.footer_confidence_colors(status="override", confidence_value=0.9) == (
        (255, 255, 255, 255),
        (82, 82, 82, 255),
    )
    assert big_ui_engine.footer_confidence_colors(status="disengaged", confidence_value=-0.5) == (
        (50, 50, 50, 255),
        (13, 13, 13, 255),
    )


def test_build_render_steps_tracks_matching_wide_camera_frames() -> None:
    segments = [
        [
            FakeMsg("roadEncodeIdx", 0, SimpleNamespace(frameId=10, timestampSof=1_000, timestampEof=2_000)),
            FakeMsg("wideRoadEncodeIdx", 1, SimpleNamespace(frameId=10, timestampSof=1_010, timestampEof=2_010)),
            FakeMsg("roadCameraState", 10_000_000, SimpleNamespace(frameId=10, timestampEof=2_000)),
            FakeMsg("wideRoadCameraState", 10_500_000, SimpleNamespace(frameId=10, timestampEof=2_010)),
            FakeMsg("modelV2", 30_000_000, SimpleNamespace(frameId=10, timestampEof=2_000)),
        ]
    ]

    steps = big_ui_engine.build_render_steps(segments, seg_start=0, start=0, end=1)

    assert len(steps) == 1
    assert steps[0].camera_ref.route_frame_id == 10
    assert steps[0].wide_camera_ref is not None
    assert steps[0].wide_camera_ref.route_frame_id == 10


def test_ui_environment_forces_scale_one() -> None:
    env = render_runtime.configure_ui_environment({})
    assert env["SCALE"] == "1"


def test_find_metric_source_log_prefers_lowest_segment(tmp_path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "2023-07-27--13-01-19--2").mkdir(parents=True)
    (data_dir / "2023-07-27--13-01-19--2" / "rlog.zst").write_bytes(b"")
    (data_dir / "2023-07-27--13-01-19--0").mkdir(parents=True)
    (data_dir / "2023-07-27--13-01-19--0" / "rlog.bz2").write_bytes(b"")

    found = ui_renderer._find_metric_source_log("dongle|2023-07-27--13-01-19", str(data_dir))

    assert found == (data_dir / "2023-07-27--13-01-19--0" / "rlog.bz2")


def test_detect_logged_metric_defaults_to_imperial_when_key_missing(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    openpilot_dir = tmp_path / "openpilot"
    openpilot_dir.mkdir()
    segment_dir = data_dir / "2023-07-27--13-01-19--0"
    segment_dir.mkdir(parents=True)
    (segment_dir / "rlog.zst").write_bytes(b"")

    monkeypatch.setattr(
        ui_renderer.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="missing\n", stderr=""),
    )

    assert ui_renderer.detect_logged_metric(
        "dongle|2023-07-27--13-01-19",
        data_dir=str(data_dir),
        openpilot_dir=openpilot_dir,
    ) is False


def test_detect_logged_metric_reads_metric_from_openpilot_helper(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    openpilot_dir = tmp_path / "openpilot"
    openpilot_dir.mkdir()
    segment_dir = data_dir / "2023-07-27--13-01-19--0"
    segment_dir.mkdir(parents=True)
    (segment_dir / "rlog.zst").write_bytes(b"")

    monkeypatch.setattr(
        ui_renderer.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="1\n", stderr=""),
    )

    assert ui_renderer.detect_logged_metric(
        "dongle|2023-07-27--13-01-19",
        data_dir=str(data_dir),
        openpilot_dir=openpilot_dir,
    ) is True


def test_compute_ui_render_window_clamps_trim_near_route_start() -> None:
    assert ui_renderer._compute_ui_render_window(start_seconds=0, length_seconds=5, smear_seconds=5) == (0, 5, 0, 0)
    assert ui_renderer._compute_ui_render_window(start_seconds=3, length_seconds=5, smear_seconds=5) == (0, 8, 0, 3)
    assert ui_renderer._compute_ui_render_window(start_seconds=62, length_seconds=5, smear_seconds=5) == (56, 67, 1, 5)


def test_patch_ui_application_record_skip_inserts_skip_logic(tmp_path) -> None:
    app = tmp_path / "application.py"
    app.write_text(
        'RECORD_SPEED = int(os.getenv("RECORD_SPEED", "1"))  # Speed multiplier\n'
        '        ffmpeg_args = [\n'
        "          'ffmpeg',\n"
        "          '-v', 'warning',          # Reduce ffmpeg log spam\n"
        "          '-nostats',               # Suppress encoding progress\n"
        "          '-f', 'rawvideo',         # Input format\n"
        "          '-pix_fmt', 'rgba',       # Input pixel format\n"
        "          '-s', f'{self._scaled_width}x{self._scaled_height}',  # Input resolution\n"
        "          '-r', str(fps),           # Input frame rate\n"
        "          '-i', 'pipe:0',           # Input from stdin\n"
        "          '-vf', 'vflip,format=yuv420p',  # Flip vertically and convert to yuv420p\n"
        "          '-r', str(output_fps),    # Output frame rate (for speed multiplier)\n"
        "          '-c:v', 'libx264',\n"
        "          '-preset', 'veryfast',\n"
        "          '-crf', str(RECORD_QUALITY)\n"
        "        ]\n"
        "        if RECORD_BITRATE:\n"
        "          # NOTE: custom bitrate overrides crf setting\n"
        "          ffmpeg_args += ['-b:v', RECORD_BITRATE, '-maxrate', RECORD_BITRATE, '-bufsize', RECORD_BITRATE]\n"
        "        ffmpeg_args += [\n"
        "          '-y',                     # Overwrite existing file\n"
        "          '-f', 'mp4',              # Output format\n"
        "          RECORD_OUTPUT,            # Output file path\n"
        "        ]\n"
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
    assert 'RECORD_CODEC = os.getenv("RECORD_CODEC", "libx264")' in updated
    assert "'-c:v', RECORD_CODEC" in updated
    assert "if RECORD_CODEC.startswith('libx'):" in updated
    assert "if RECORD_TAG:" in updated
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


def test_patch_model_renderer_lead_position_uses_absolute_rect_bounds(tmp_path) -> None:
    model_renderer = tmp_path / "model_renderer.py"
    model_renderer.write_text(
        "    x = np.clip(point[0], 0.0, rect.width - sz / 2)\n"
        "    y = min(point[1], rect.height - sz * 0.6)\n"
    )

    changed = openpilot_integration._patch_model_renderer_lead_position(model_renderer)
    updated = model_renderer.read_text()

    assert changed is True
    assert "x = np.clip(point[0], rect.x, rect.x + rect.width - sz / 2)" in updated
    assert "y = np.clip(point[1], rect.y, rect.y + rect.height - sz * 0.6)" in updated


def test_apply_openpilot_runtime_patches_reports_changed_files(tmp_path) -> None:
    openpilot_dir = tmp_path / "openpilot"
    (openpilot_dir / "tools/lib").mkdir(parents=True)
    (openpilot_dir / "system/ui/lib").mkdir(parents=True)
    (openpilot_dir / "selfdrive/ui/onroad").mkdir(parents=True)

    (openpilot_dir / "tools/lib/framereader.py").write_text(
        "def decompress_video_data(fn, fmt, threads=0, hwaccel=None):\n"
        "    threads = threads or 0\n"
        "    args = ['ffmpeg', '-i', '-', 'x']\n"
        "def ffprobe(fn):\n"
        "    cmd += ['-i', '-']\n"
        "    try:\n"
        "      ffprobe_output = subprocess.check_output(cmd, input=FileReader(fn).read(4096))\n"
        "    except subprocess.CalledProcessError as error:\n"
        "      raise DataUnreadableError(fn) from error\n"
    )
    (openpilot_dir / "system/ui/lib/application.py").write_text(
        'RECORD_SPEED = int(os.getenv("RECORD_SPEED", "1"))  # Speed multiplier\n'
        '      flags = rl.ConfigFlags.FLAG_MSAA_4X_HINT\n'
        '      if ENABLE_VSYNC:\n'
        '        flags |= rl.ConfigFlags.FLAG_VSYNC_HINT\n'
        '      rl.set_config_flags(flags)\n\n'
        '      rl.init_window(self._scaled_width, self._scaled_height, title)\n'
        "        ffmpeg_args = [\n"
        "          'ffmpeg',\n"
        "          '-v', 'warning',\n"
        "          '-nostats',\n"
        "          '-f', 'rawvideo',\n"
        "          '-pix_fmt', 'rgba',\n"
        "          '-s', f'{self._scaled_width}x{self._scaled_height}',\n"
        "          '-r', str(fps),\n"
        "          '-i', 'pipe:0',\n"
        "          '-vf', 'vflip,format=yuv420p',\n"
        "          '-r', str(output_fps),\n"
        "          '-c:v', 'libx264',\n"
        "          '-preset', 'veryfast',\n"
        "          '-crf', str(RECORD_QUALITY)\n"
        "        ]\n"
        "        if RECORD_BITRATE:\n"
        "          ffmpeg_args += ['-b:v', RECORD_BITRATE, '-maxrate', RECORD_BITRATE, '-bufsize', RECORD_BITRATE]\n"
        "        ffmpeg_args += ['-y', '-f', 'mp4', RECORD_OUTPUT]\n"
        "        if RECORD:\n"
        "          image = rl.load_image_from_texture(self._render_texture.texture)\n"
        "          data_size = image.width * image.height * 4\n"
        "          data = bytes(rl.ffi.buffer(image.data, data_size))\n"
        "          self._ffmpeg_queue.put(data)  # Async write via background thread\n"
        "          rl.unload_image(image)\n"
    )
    (openpilot_dir / "selfdrive/ui/onroad/augmented_road_view.py").write_text(
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
    (openpilot_dir / "selfdrive/ui/onroad/model_renderer.py").write_text(
        "    x = np.clip(point[0], 0.0, rect.width - sz / 2)\n"
        "    y = min(point[1], rect.height - sz * 0.6)\n"
    )

    report = openpilot_integration.apply_openpilot_runtime_patches(openpilot_dir)

    assert report.changed is True
    assert report.framereader_compat is True
    assert report.ui_recording is True
    assert report.ui_null_egl is True
    assert report.augmented_road_fill is True
    assert report.model_renderer_lead_position is True


def test_render_overlays_includes_device_type_in_metadata(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(big_ui_engine, "draw_text_box", lambda text, *args, **kwargs: calls.append(text))

    def fake_measure(_font, text, _size):
        return SimpleNamespace(x=len(text) * 8, y=16)

    def fake_wrap(_font, text, _size, _max_width):
        return [text]

    monkeypatch.setitem(__import__("sys").modules, "openpilot.system.ui.lib.text_measure", SimpleNamespace(measure_text_cached=fake_measure))
    monkeypatch.setitem(__import__("sys").modules, "openpilot.system.ui.lib.wrap_text", SimpleNamespace(wrap_text=fake_wrap))

    metadata = {
        "route": "dongle|route",
        "device_type": "mici",
        "platform": "FORD_BRONCO_SPORT_MK1",
        "remote": "commaai",
        "branch": "master",
        "commit": "deadbeef",
        "dirty": "false",
    }

    big_ui_engine.render_overlays(
        SimpleNamespace(width=2160),
        font=object(),
        big=True,
        metadata=metadata,
        title=None,
        route_seconds=90,
        show_metadata=True,
        show_time=False,
    )

    assert any("mici" in text for text in calls)


def test_render_overlays_insets_timer_inside_video_frame(monkeypatch) -> None:
    calls: list[tuple[str, int, int, int]] = []

    monkeypatch.setattr(
        big_ui_engine,
        "draw_text_box",
        lambda text, x, y, size, *args, **kwargs: calls.append((text, x, y, size)),
    )

    def fake_measure(_font, text, _size):
        return SimpleNamespace(x=len(text) * 8, y=16)

    monkeypatch.setitem(__import__("sys").modules, "openpilot.system.ui.lib.text_measure", SimpleNamespace(measure_text_cached=fake_measure))
    monkeypatch.setitem(__import__("sys").modules, "openpilot.system.ui.lib.wrap_text", SimpleNamespace(wrap_text=lambda *_args: []))

    gui_app = SimpleNamespace(width=2160)
    big_ui_engine.render_overlays(
        gui_app,
        font=object(),
        big=True,
        metadata=None,
        title=None,
        route_seconds=90,
        show_metadata=False,
        show_time=True,
    )

    assert calls == [
        (
            "01:30",
            gui_app.width - (len("01:30") * 8) - big_ui_engine.TEXT_BOX_PADDING_X - big_ui_engine.TIME_OVERLAY_EDGE_MARGIN_BIG,
            big_ui_engine.TEXT_BOX_PADDING_Y + big_ui_engine.TIME_OVERLAY_EDGE_MARGIN_BIG,
            24,
        )
    ]


def test_ui_recording_encoder_prefers_nvidia(monkeypatch) -> None:
    env: dict[str, str] = {}
    monkeypatch.setattr(ui_renderer, "_has_nvidia", lambda: True)

    acceleration = ui_renderer._configure_ui_recording_encoder(env, "hevc")

    assert acceleration == "nvidia"
    assert env["RECORD_CODEC"] == "hevc_nvenc"
    assert env["RECORD_PRESET"] == "p4"
    assert env["RECORD_TAG"] == "hvc1"


def test_ui_recording_encoder_falls_back_to_cpu(monkeypatch) -> None:
    env: dict[str, str] = {}
    monkeypatch.setattr(ui_renderer, "_has_nvidia", lambda: False)

    acceleration = ui_renderer._configure_ui_recording_encoder(env, "h264")

    assert acceleration == "cpu"
    assert env["RECORD_CODEC"] == "libx264"
    assert env["RECORD_PRESET"] == "veryfast"
    assert "RECORD_TAG" not in env
