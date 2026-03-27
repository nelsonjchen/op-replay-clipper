from __future__ import annotations

"""
Minimal runtime patch layer for openpilot integration.

Most of the patches here are simple source rewrites because we know the exact
upstream snippets we need to adjust. The one exception is framereader
compatibility, where the surrounding code shape has drifted enough across
upstream revisions that a small AST-guided patch is still the least brittle
option.
"""

import ast
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OpenpilotPatchReport:
    framereader_compat: bool = False
    ui_recording: bool = False
    ui_null_egl: bool = False
    augmented_road_fill: bool = False
    model_renderer_lead_position: bool = False

    @property
    def changed(self) -> bool:
        return any(
            (
                self.framereader_compat,
                self.ui_recording,
                self.ui_null_egl,
                self.augmented_road_fill,
                self.model_renderer_lead_position,
            )
        )


def build_openpilot_compatible_data_dir(route: str, downloader_data_dir: Path) -> Path:
    route_date = route.split("|", 1)[1]
    compat_root = Path("./shared/openpilot_data_dir").resolve()
    route_root = compat_root / route
    route_root.mkdir(parents=True, exist_ok=True)

    seg_pattern = re.compile(rf"^{re.escape(route_date)}--(\d+)$")
    for entry in downloader_data_dir.iterdir():
        if not entry.is_dir():
            continue
        match = seg_pattern.match(entry.name)
        if not match:
            continue
        seg_dir = route_root / match.group(1)
        if seg_dir.exists() or seg_dir.is_symlink():
            if seg_dir.is_symlink() and seg_dir.resolve() == entry.resolve():
                continue
            if seg_dir.is_symlink() or seg_dir.is_file():
                seg_dir.unlink()
            else:
                continue
        seg_dir.symlink_to(entry.resolve(), target_is_directory=True)
    return compat_root


def _module_has_os_import(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Import):
            if any(alias.name == "os" for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            return True
    return False


def _ensure_os_import(tree: ast.Module) -> bool:
    if _module_has_os_import(tree):
        return False
    insert_at = 0
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        insert_at = 1
    tree.body.insert(insert_at, ast.Import(names=[ast.alias(name="os")]))
    return True


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_os_path_exists_call(node: ast.AST, arg_name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exists"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "path"
        and _is_name(node.func.value.value, "os")
        and len(node.args) == 1
        and _is_name(node.args[0], arg_name)
    )


def _is_os_getenv_call(node: ast.AST, env_name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "getenv"
        and _is_name(node.func.value, "os")
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == env_name
    )


def _replace_source_range(lines: list[str], start_line: int, end_line: int, new_lines: list[str]) -> list[str]:
    return [*lines[: start_line - 1], *new_lines, *lines[end_line:]]


def _indent(width: int) -> str:
    return " " * width


def _patch_framereader_ast(path: Path) -> bool:
    # This patch touches multiple statements whose exact line structure has
    # drifted across upstream revisions. We keep the AST-guided approach here
    # because it is more resilient than raw string replacement for this file.
    original_src = path.read_text()
    lines = original_src.splitlines(keepends=True)
    tree = ast.parse(original_src)
    modified = _ensure_os_import(tree)
    if modified:
        insert_at = 0
        while insert_at < len(tree.body) and isinstance(tree.body[insert_at], (ast.Import, ast.ImportFrom)):
            insert_at += 1
        if insert_at == 0 and tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
            insert_at = 1
            while insert_at < len(tree.body) and isinstance(tree.body[insert_at], (ast.Import, ast.ImportFrom)):
                insert_at += 1
        line_idx = 0 if insert_at == 0 else tree.body[insert_at - 1].end_lineno
        lines = [*lines[:line_idx], "import os\n", *lines[line_idx:]]

    tree = ast.parse("".join(lines))

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name == "decompress_video_data":
            if not any(_is_os_getenv_call(inner, "FFMPEG_HWACCEL") for inner in ast.walk(node)):
                threads_stmt = next(
                    (stmt for stmt in node.body if isinstance(stmt, ast.Assign) and any(_is_name(target, "threads") for target in stmt.targets)),
                    None,
                )
                if threads_stmt is not None:
                    lines = [
                        *lines[: threads_stmt.end_lineno],
                        f"{_indent(threads_stmt.col_offset)}hwaccel = os.getenv(\"FFMPEG_HWACCEL\", hwaccel)\n",
                        *lines[threads_stmt.end_lineno :],
                    ]
                    modified = True
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and any(_is_name(target, "args") for target in stmt.targets):
                    segment = "".join(lines[stmt.lineno - 1 : stmt.end_lineno])
                    replaced = segment.replace('"-i", "-"', '"-i", "pipe:0"').replace("'-i', '-'", "'-i', 'pipe:0'")
                    if replaced != segment:
                        lines = _replace_source_range(lines, stmt.lineno, stmt.end_lineno, replaced.splitlines(keepends=True))
                        modified = True
                    break

    tree = ast.parse("".join(lines))

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "ffprobe":
            continue
        cmd_stmt = next(
            (stmt for stmt in node.body if isinstance(stmt, ast.AugAssign) and _is_name(stmt.target, "cmd")),
            None,
        )
        if cmd_stmt is not None:
            segment = "".join(lines[cmd_stmt.lineno - 1 : cmd_stmt.end_lineno])
            replaced = segment.replace('"-i", "-"', '"-i", "pipe:0"').replace("'-i', '-'", "'-i', 'pipe:0'")
            if replaced != segment:
                lines = _replace_source_range(lines, cmd_stmt.lineno, cmd_stmt.end_lineno, replaced.splitlines(keepends=True))
                modified = True

        if any(_is_os_path_exists_call(inner, "fn") for inner in ast.walk(node)):
            break

        cmd_stmt = next(
            (stmt for stmt in node.body if isinstance(stmt, ast.AugAssign) and _is_name(stmt.target, "cmd")),
            None,
        )
        try_stmt = next((stmt for stmt in node.body if isinstance(stmt, ast.Try)), None)
        if cmd_stmt is None or try_stmt is None:
            break

        unit = _indent((try_stmt.body[0].col_offset - try_stmt.col_offset) if try_stmt.body else 2)
        lines = [
            *lines[: cmd_stmt.lineno - 1],
            f"{_indent(cmd_stmt.col_offset)}local_cmd = list(cmd)\n",
            f"{_indent(cmd_stmt.col_offset)}local_cmd += ['-i', fn]\n",
            *lines[cmd_stmt.lineno - 1 :],
        ]
        try_block = [
            f"{_indent(try_stmt.col_offset)}try:\n",
            f"{_indent(try_stmt.col_offset)}{unit}if os.path.exists(fn):\n",
            f"{_indent(try_stmt.col_offset)}{unit}{unit}ffprobe_output = subprocess.check_output(local_cmd)\n",
            f"{_indent(try_stmt.col_offset)}{unit}else:\n",
            f"{_indent(try_stmt.col_offset)}{unit}{unit}with FileReader(fn) as handle:\n",
            f"{_indent(try_stmt.col_offset)}{unit}{unit}{unit}ffprobe_output = subprocess.check_output(cmd, input=handle.read(4096))\n",
            f"{_indent(try_stmt.col_offset)}except subprocess.CalledProcessError as error:\n",
            f"{_indent(try_stmt.col_offset)}{unit}raise DataUnreadableError(fn) from error\n",
        ]
        lines = _replace_source_range(lines, try_stmt.lineno + 2, try_stmt.end_lineno + 2, try_block)
        modified = True
        break

    if modified:
        path.write_text("".join(lines))
    return modified


def _patch_ui_application_record_skip(path: Path) -> bool:
    source = path.read_text()
    updated = source

    record_speed_line = 'RECORD_SPEED = int(os.getenv("RECORD_SPEED", "1"))  # Speed multiplier\n'
    record_skip_line = 'RECORD_SKIP_FRAMES = int(os.getenv("RECORD_SKIP_FRAMES", "0"))  # Warmup frames to drop before recording\n'
    record_codec_line = 'RECORD_CODEC = os.getenv("RECORD_CODEC", "libx264")  # ffmpeg video encoder\n'
    record_preset_line = 'RECORD_PRESET = os.getenv("RECORD_PRESET", "veryfast")  # ffmpeg encoder preset\n'
    record_tag_line = 'RECORD_TAG = os.getenv("RECORD_TAG", "")  # Optional ffmpeg codec tag\n'
    if record_skip_line not in updated and record_speed_line in updated:
        updated = updated.replace(record_speed_line, record_speed_line + record_skip_line, 1)
    if record_codec_line not in updated and record_skip_line in updated:
        updated = updated.replace(record_skip_line, record_skip_line + record_codec_line + record_preset_line + record_tag_line, 1)

    old_block = """        if RECORD:\n          image = rl.load_image_from_texture(self._render_texture.texture)\n          data_size = image.width * image.height * 4\n          data = bytes(rl.ffi.buffer(image.data, data_size))\n          self._ffmpeg_queue.put(data)  # Async write via background thread\n          rl.unload_image(image)\n"""
    new_block = """        if RECORD and self._frame >= RECORD_SKIP_FRAMES:\n          image = rl.load_image_from_texture(self._render_texture.texture)\n          data_size = image.width * image.height * 4\n          data = bytes(rl.ffi.buffer(image.data, data_size))\n          self._ffmpeg_queue.put(data)  # Async write via background thread\n          rl.unload_image(image)\n"""
    if old_block in updated:
        updated = updated.replace(old_block, new_block, 1)

    old_ffmpeg_block = """        ffmpeg_args = [\n          'ffmpeg',\n          '-v', 'warning',          # Reduce ffmpeg log spam\n          '-nostats',               # Suppress encoding progress\n          '-f', 'rawvideo',         # Input format\n          '-pix_fmt', 'rgba',       # Input pixel format\n          '-s', f'{self._scaled_width}x{self._scaled_height}',  # Input resolution\n          '-r', str(fps),           # Input frame rate\n          '-i', 'pipe:0',           # Input from stdin\n          '-vf', 'vflip,format=yuv420p',  # Flip vertically and convert to yuv420p\n          '-r', str(output_fps),    # Output frame rate (for speed multiplier)\n          '-c:v', 'libx264',\n          '-preset', 'veryfast',\n          '-crf', str(RECORD_QUALITY)\n        ]\n        if RECORD_BITRATE:\n          # NOTE: custom bitrate overrides crf setting\n          ffmpeg_args += ['-b:v', RECORD_BITRATE, '-maxrate', RECORD_BITRATE, '-bufsize', RECORD_BITRATE]\n        ffmpeg_args += [\n          '-y',                     # Overwrite existing file\n          '-f', 'mp4',              # Output format\n          RECORD_OUTPUT,            # Output file path\n        ]\n"""
    new_ffmpeg_block = """        ffmpeg_args = [\n          'ffmpeg',\n          '-v', 'warning',          # Reduce ffmpeg log spam\n          '-nostats',               # Suppress encoding progress\n          '-f', 'rawvideo',         # Input format\n          '-pix_fmt', 'rgba',       # Input pixel format\n          '-s', f'{self._scaled_width}x{self._scaled_height}',  # Input resolution\n          '-r', str(fps),           # Input frame rate\n          '-i', 'pipe:0',           # Input from stdin\n          '-vf', 'vflip,format=yuv420p',  # Flip vertically and convert to yuv420p\n          '-r', str(output_fps),    # Output frame rate (for speed multiplier)\n          '-c:v', RECORD_CODEC,\n          '-preset', RECORD_PRESET,\n        ]\n        if RECORD_CODEC.startswith('libx'):\n          ffmpeg_args += ['-crf', str(RECORD_QUALITY)]\n        if RECORD_BITRATE:\n          # NOTE: custom bitrate overrides crf setting\n          ffmpeg_args += ['-b:v', RECORD_BITRATE, '-maxrate', RECORD_BITRATE, '-bufsize', RECORD_BITRATE]\n        if RECORD_TAG:\n          ffmpeg_args += ['-tag:v', RECORD_TAG]\n        ffmpeg_args += [\n          '-y',                     # Overwrite existing file\n          '-f', 'mp4',              # Output format\n          RECORD_OUTPUT,            # Output file path\n        ]\n"""
    if old_ffmpeg_block in updated:
        updated = updated.replace(old_ffmpeg_block, new_ffmpeg_block, 1)

    if updated != source:
        path.write_text(updated)
        return True
    return False


def _patch_ui_application_null_egl(path: Path) -> bool:
    source = path.read_text()
    updated = source

    old_flags = """      flags = rl.ConfigFlags.FLAG_MSAA_4X_HINT\n      if ENABLE_VSYNC:\n        flags |= rl.ConfigFlags.FLAG_VSYNC_HINT\n      rl.set_config_flags(flags)\n\n      rl.init_window(self._scaled_width, self._scaled_height, title)\n"""
    wrong_flags = """      flags = rl.ConfigFlags.FLAG_MSAA_4X_HINT\n      if ENABLE_VSYNC:\n        flags |= rl.ConfigFlags.FLAG_VSYNC_HINT\n      if os.getenv(\"OPENPILOT_UI_NULL_EGL\"):\n        rl.glfwInitHint(rl.GLFW_PLATFORM, rl.GLFW_PLATFORM_NULL)\n        rl.glfwInitHint(rl.GLFW_CONTEXT_CREATION_API, rl.GLFW_EGL_CONTEXT_API)\n        flags |= rl.ConfigFlags.FLAG_WINDOW_HIDDEN\n      rl.set_config_flags(flags)\n\n      rl.init_window(self._scaled_width, self._scaled_height, title)\n"""
    new_flags = """      flags = rl.ConfigFlags.FLAG_MSAA_4X_HINT\n      if ENABLE_VSYNC:\n        flags |= rl.ConfigFlags.FLAG_VSYNC_HINT\n      if os.getenv(\"OPENPILOT_UI_NULL_EGL\"):\n        rl.rl.glfwInitHint(rl.GLFW_PLATFORM, rl.GLFW_PLATFORM_NULL)\n        rl.rl.glfwInitHint(rl.GLFW_CONTEXT_CREATION_API, rl.GLFW_EGL_CONTEXT_API)\n        flags |= rl.ConfigFlags.FLAG_WINDOW_HIDDEN\n      rl.set_config_flags(flags)\n\n      rl.init_window(self._scaled_width, self._scaled_height, title)\n"""
    if old_flags in updated:
        updated = updated.replace(old_flags, new_flags, 1)
    if wrong_flags in updated:
        updated = updated.replace(wrong_flags, new_flags, 1)

    if updated != source:
        path.write_text(updated)
        return True
    return False


def _patch_augmented_road_view_fill(path: Path) -> bool:
    source = path.read_text()
    updated = source

    zoom_guard = """    # Ensure zoom views the whole area\n    zoom = max(zoom, w / (2 * cx), h / (2 * cy))\n\n"""
    if zoom_guard not in updated:
        needle = """    # Calculate max allowed offsets with margins\n"""
        if needle in updated:
            updated = updated.replace(needle, zoom_guard + needle, 1)

    updated = updated.replace(
        "    max_x_offset = cx * zoom - w / 2 - margin\n",
        "    max_x_offset = max(0.0, cx * zoom - w / 2 - margin)\n",
        1,
    )
    updated = updated.replace(
        "    max_y_offset = cy * zoom - h / 2 - margin\n",
        "    max_y_offset = max(0.0, cy * zoom - h / 2 - margin)\n",
        1,
    )
    updated = updated.replace("    super()._render(rect)\n", "    super()._render(self._content_rect)\n", 1)
    mask_comment = "    # Fake a rounded clip mask so the rectangular camera viewport does not peek past the curved frame\n"
    known_mask_lines = (
        "    rl.draw_rectangle_rounded_lines_ex(self._content_rect, 0.12 * 1.02, 10, UI_BORDER_SIZE * 2, rl.BLACK)\n",
        "    rl.draw_rectangle_rounded_lines_ex(self._content_rect, 0.2 * 1.02, 10, 50, rl.BLACK)\n",
    )
    for mask_line in known_mask_lines:
        updated = updated.replace(mask_comment + mask_line + "\n", "")
        updated = updated.replace(mask_comment + mask_line, "")

    if updated != source:
        path.write_text(updated)
        return True
    return False


def _patch_model_renderer_lead_position(path: Path) -> bool:
    source = path.read_text()
    updated = source

    updated = updated.replace(
        "    x = np.clip(point[0], 0.0, rect.width - sz / 2)\n",
        "    x = np.clip(point[0], rect.x, rect.x + rect.width - sz / 2)\n",
        1,
    )
    updated = updated.replace(
        "    y = min(point[1], rect.height - sz * 0.6)\n",
        "    y = np.clip(point[1], rect.y, rect.y + rect.height - sz * 0.6)\n",
        1,
    )

    if updated != source:
        path.write_text(updated)
        return True
    return False


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def patch_openpilot_framereader_compat(openpilot_dir: Path) -> bool:
    framereader = _first_existing(
        openpilot_dir / "tools/lib/framereader.py",
        openpilot_dir / "openpilot/tools/lib/framereader.py",
    )
    if framereader is None:
        return False
    return _patch_framereader_ast(framereader)


def patch_openpilot_ui_record_skip(openpilot_dir: Path) -> tuple[bool, bool]:
    application = _first_existing(
        openpilot_dir / "system/ui/lib/application.py",
        openpilot_dir / "openpilot/system/ui/lib/application.py",
    )
    if application is None:
        return False, False
    return (
        _patch_ui_application_record_skip(application),
        _patch_ui_application_null_egl(application),
    )


def patch_openpilot_augmented_road_view_fill(openpilot_dir: Path) -> bool:
    candidates = (
        openpilot_dir / "selfdrive/ui/onroad/augmented_road_view.py",
        openpilot_dir / "openpilot/selfdrive/ui/onroad/augmented_road_view.py",
        openpilot_dir / "selfdrive/ui/mici/onroad/augmented_road_view.py",
        openpilot_dir / "openpilot/selfdrive/ui/mici/onroad/augmented_road_view.py",
    )
    for path in candidates:
        if path.exists():
            return _patch_augmented_road_view_fill(path)
    return False


def patch_openpilot_model_renderer_lead_position(openpilot_dir: Path) -> bool:
    candidates = (
        openpilot_dir / "selfdrive/ui/onroad/model_renderer.py",
        openpilot_dir / "openpilot/selfdrive/ui/onroad/model_renderer.py",
        openpilot_dir / "selfdrive/ui/mici/onroad/model_renderer.py",
        openpilot_dir / "openpilot/selfdrive/ui/mici/onroad/model_renderer.py",
    )
    patched = False
    for path in candidates:
        if not path.exists():
            continue
        patched = _patch_model_renderer_lead_position(path) or patched
    return patched


def apply_openpilot_runtime_patches(openpilot_dir: Path) -> OpenpilotPatchReport:
    framereader_compat = patch_openpilot_framereader_compat(openpilot_dir)
    ui_recording, ui_null_egl = patch_openpilot_ui_record_skip(openpilot_dir)
    augmented_road_fill = patch_openpilot_augmented_road_view_fill(openpilot_dir)
    model_renderer_lead_position = patch_openpilot_model_renderer_lead_position(openpilot_dir)
    return OpenpilotPatchReport(
        framereader_compat=framereader_compat,
        ui_recording=ui_recording,
        ui_null_egl=ui_null_egl,
        augmented_road_fill=augmented_road_fill,
        model_renderer_lead_position=model_renderer_lead_position,
    )
