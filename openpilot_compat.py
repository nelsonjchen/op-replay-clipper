from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path


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


def _patch_clip_run_ast(path: Path) -> bool:
    original_src = path.read_text()
    lines = original_src.splitlines(keepends=True)
    tree = ast.parse(original_src)
    modified = False

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "iter_segment_frames":
            continue
        use_qcam_if = next((stmt for stmt in node.body if isinstance(stmt, ast.For)), None)
        if use_qcam_if is None:
            continue
        for inner in ast.walk(use_qcam_if):
            if isinstance(inner, ast.If) and _is_name(inner.test, "use_qcam"):
                if any(_is_os_path_exists_call(desc, "path") for desc in ast.walk(inner)):
                    return False
                decode_stmt = next((stmt for stmt in inner.body if isinstance(stmt, ast.With)), None)
                if decode_stmt is None:
                    return False
                unit = _indent((decode_stmt.body[0].col_offset - decode_stmt.col_offset) if decode_stmt.body else 2)
                replacement = [
                    f"{_indent(decode_stmt.col_offset)}if os.path.exists(path):\n",
                    f"{_indent(decode_stmt.col_offset)}{unit}result = subprocess.run([\"ffmpeg\", \"-v\", \"quiet\", \"-i\", path, \"-f\", \"rawvideo\", \"-pix_fmt\", \"nv12\", \"-\"],\n",
                    f"{_indent(decode_stmt.col_offset)}{unit}{unit}capture_output=True)\n",
                    f"{_indent(decode_stmt.col_offset)}else:\n",
                    f"{_indent(decode_stmt.col_offset)}{unit}with FileReader(path) as handle:\n",
                    f"{_indent(decode_stmt.col_offset)}{unit}{unit}result = subprocess.run([\"ffmpeg\", \"-v\", \"quiet\", \"-i\", \"-\", \"-f\", \"rawvideo\", \"-pix_fmt\", \"nv12\", \"-\"],\n",
                    f"{_indent(decode_stmt.col_offset)}{unit}{unit}{unit}input=handle.read(), capture_output=True)\n",
                ]
                lines = _replace_source_range(lines, decode_stmt.lineno, decode_stmt.end_lineno, replacement)
                modified = True
                break

    if modified:
        path.write_text("".join(lines))
    return modified


def patch_openpilot_framereader_compat(openpilot_dir: Path) -> None:
    framereader = openpilot_dir / "tools/lib/framereader.py"
    if not framereader.exists():
        framereader = openpilot_dir / "openpilot/tools/lib/framereader.py"
    if framereader.exists():
        _patch_framereader_ast(framereader)


def patch_openpilot_qcam_local_decode(openpilot_dir: Path) -> None:
    clip_run = openpilot_dir / "tools/clip/run.py"
    if clip_run.exists():
        _patch_clip_run_ast(clip_run)
