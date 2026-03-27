from __future__ import annotations

from types import SimpleNamespace

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


def test_build_layout_rects_default_uses_full_canvas() -> None:
    rects = big_ui_engine.build_layout_rects(width=1920, height=1080, layout_mode="default")

    assert rects.road_rect == (0, 0, 1920, 1080)
    assert rects.footer_rect is None


def test_build_layout_rects_alt_reserves_footer() -> None:
    rects = big_ui_engine.build_layout_rects(width=1920, height=1080, layout_mode="alt")

    assert rects.road_rect == (0, 0, 1920, 810)
    assert rects.footer_rect == (0, 810, 1920, 270)


def test_extract_steering_angle_deg_uses_car_state_when_present() -> None:
    state = {
        "carState": FakeMsg("carState", 0, SimpleNamespace(steeringAngleDeg=12.5)),
    }

    assert big_ui_engine.extract_steering_angle_deg(state) == 12.5


def test_extract_steering_angle_deg_defaults_to_zero_when_missing() -> None:
    assert big_ui_engine.extract_steering_angle_deg({}) == 0.0


def test_extract_footer_telemetry_reads_driver_and_op_inputs() -> None:
    state = {
        "carState": FakeMsg(
            "carState",
            0,
            SimpleNamespace(
                steeringAngleDeg=12.5,
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
                actuators=SimpleNamespace(accel=1.2),
            ),
        ),
        "carOutput": FakeMsg(
            "carOutput",
            0,
            SimpleNamespace(
                actuatorsOutput=SimpleNamespace(accel=1.1),
            ),
        ),
        "longitudinalPlan": FakeMsg(
            "longitudinalPlan",
            0,
            SimpleNamespace(aTarget=0.6, accels=[0.7]),
        ),
    }

    telemetry = big_ui_engine.extract_footer_telemetry(state)

    assert telemetry.steering_angle_deg == 12.5
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

    report = openpilot_integration.apply_openpilot_runtime_patches(openpilot_dir)

    assert report.changed is True
    assert report.framereader_compat is True
    assert report.ui_recording is True
    assert report.ui_null_egl is True
    assert report.augmented_road_fill is True


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
            gui_app.width - (len("01:30") * 8) - big_ui_engine.TEXT_BOX_PADDING_X - 10,
            big_ui_engine.TEXT_BOX_PADDING_Y + 10,
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
