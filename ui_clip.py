from __future__ import annotations

import ast
import contextlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


UIBackend = Literal["auto", "modern", "legacy"]
UIMode = Literal["auto", "c3", "c3x", "big", "c4"]


@dataclass
class UIRenderOptions:
    route: str
    start_seconds: int
    length_seconds: int
    smear_seconds: int
    target_mb: int
    file_format: str
    speedhack_ratio: float
    metric: bool
    output_path: str
    data_dir: str | None = None
    jwt_token: str | None = None
    openpilot_dir: str = "/home/batman/openpilot"
    backend: UIBackend = "auto"
    ui_mode: UIMode = "auto"
    headless: bool = True


def _run(cmd: list[str], cwd: str | Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def _has_modern_openpilot(openpilot_dir: Path) -> bool:
    return (openpilot_dir / "tools/clip/run.py").exists()


def _has_legacy_clip_script() -> bool:
    return Path("./clip.sh").exists()


def _choose_backend(opts: UIRenderOptions) -> UIBackend:
    if opts.backend != "auto":
        return opts.backend
    if _has_modern_openpilot(Path(opts.openpilot_dir)):
        return "modern"
    return "legacy"


def _ui_mode_to_modern_flags(ui_mode: UIMode) -> list[str]:
    # openpilot tools/clip/run.py exposes only --big; default path is the current "mici"/C4 style.
    if ui_mode in ("c3", "c3x", "big"):
        return ["--big"]
    return []


def _openpilot_python_cmd(openpilot_dir: Path) -> list[str]:
    venv_python = openpilot_dir / ".venv/bin/python"
    if venv_python.exists():
        return [str(venv_python)]
    return ["uv", "run", "python"]


def _build_openpilot_compatible_data_dir(route: str, downloader_data_dir: Path) -> Path:
    route_date = route.split("|", 1)[1]
    compat_root = Path("./shared/openpilot_data_dir").resolve()
    route_root = compat_root / route
    route_root.mkdir(parents=True, exist_ok=True)

    seg_pattern = re.compile(rf"^{re.escape(route_date)}--(\d+)$")
    for entry in downloader_data_dir.iterdir():
        if not entry.is_dir():
            continue
        m = seg_pattern.match(entry.name)
        if not m:
            continue
        seg_dir = route_root / m.group(1)
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


def _name_expr(name: str, ctx: ast.expr_context = ast.Load()) -> ast.Name:
    return ast.Name(id=name, ctx=ctx)


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
                    lines = [*lines[: threads_stmt.end_lineno], f"{_indent(threads_stmt.col_offset)}hwaccel = os.getenv(\"FFMPEG_HWACCEL\", hwaccel)\n", *lines[threads_stmt.end_lineno :]]
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
        lines = [*lines[: cmd_stmt.lineno - 1], f"{_indent(cmd_stmt.col_offset)}local_cmd = list(cmd)\n", f"{_indent(cmd_stmt.col_offset)}local_cmd += ['-i', fn]\n", *lines[cmd_stmt.lineno - 1 :]]
        try_block = [
            f"{_indent(try_stmt.col_offset)}try:\n",
            f"{_indent(try_stmt.col_offset)}{unit}if os.path.exists(fn):\n",
            f"{_indent(try_stmt.col_offset)}{unit}{unit}ffprobe_output = subprocess.check_output(local_cmd)\n",
            f"{_indent(try_stmt.col_offset)}{unit}else:\n",
            f"{_indent(try_stmt.col_offset)}{unit}{unit}with FileReader(fn) as f:\n",
            f"{_indent(try_stmt.col_offset)}{unit}{unit}{unit}ffprobe_output = subprocess.check_output(cmd, input=f.read(4096))\n",
            f"{_indent(try_stmt.col_offset)}except subprocess.CalledProcessError as e:\n",
            f"{_indent(try_stmt.col_offset)}{unit}raise DataUnreadableError(fn) from e\n",
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
                    f"{_indent(decode_stmt.col_offset)}{unit}with FileReader(path) as f:\n",
                    f"{_indent(decode_stmt.col_offset)}{unit}{unit}result = subprocess.run([\"ffmpeg\", \"-v\", \"quiet\", \"-i\", \"-\", \"-f\", \"rawvideo\", \"-pix_fmt\", \"nv12\", \"-\"],\n",
                    f"{_indent(decode_stmt.col_offset)}{unit}{unit}{unit}input=f.read(), capture_output=True)\n",
                ]
                lines = _replace_source_range(lines, decode_stmt.lineno, decode_stmt.end_lineno, replacement)
                modified = True
                break

    if modified:
        path.write_text("".join(lines))
    return modified


def _patch_openpilot_framereader_compat(openpilot_dir: Path) -> None:
    framereader = openpilot_dir / "tools/lib/framereader.py"
    if not framereader.exists():
        framereader = openpilot_dir / "openpilot/tools/lib/framereader.py"
    if not framereader.exists():
        return
    _patch_framereader_ast(framereader)


def _patch_openpilot_qcam_local_decode(openpilot_dir: Path) -> None:
    clip_run = openpilot_dir / "tools/clip/run.py"
    if not clip_run.exists():
        return
    _patch_clip_run_ast(clip_run)


def _ensure_fonts(openpilot_dir: Path) -> None:
    fonts_dir = None
    for p in [
        openpilot_dir / "selfdrive/assets/fonts",
        openpilot_dir / "openpilot/selfdrive/assets/fonts",
    ]:
        if p.exists():
            fonts_dir = p
            break
    if fonts_dir is None:
        return
    needed = ["Inter-Light.fnt", "Inter-Medium.fnt", "Inter-Bold.fnt", "Inter-SemiBold.fnt", "Inter-Regular.fnt", "unifont.fnt"]
    if all((fonts_dir / f).exists() for f in needed):
        return
    _run([*_openpilot_python_cmd(openpilot_dir), "selfdrive/assets/fonts/process.py"], cwd=openpilot_dir)


def _trim_mp4_in_place(path: Path, trim_start_seconds: int) -> None:
    if trim_start_seconds <= 0:
        return
    tmp = path.with_suffix(".tmp.mp4")
    _run(["ffmpeg", "-y", "-ss", str(trim_start_seconds), "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(tmp)])
    tmp.replace(path)


@contextlib.contextmanager
def _temporary_headless_display(env: dict[str, str], enabled: bool):
    if not enabled:
        yield env
        return

    env = env.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("SCALE", "1")

    if shutil.which("Xtigervnc") is None:
        raise RuntimeError("Headless modern UI render requires Xtigervnc in the container")

    with tempfile.NamedTemporaryFile(prefix="xtigervnc-", suffix=".log", delete=False) as log_file:
        log_path = Path(log_file.name)

    log_handle = log_path.open("wb")
    proc = subprocess.Popen(
        [
            "Xtigervnc",
            env["DISPLAY"],
            "-geometry",
            "1920x1080",
            "-depth",
            "24",
            "-SecurityTypes",
            "None",
            "-rfbport",
            "-1",
        ],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
    )
    try:
        for _ in range(50):
            if proc.poll() is not None:
                log_tail = log_path.read_text(errors="replace")
                raise RuntimeError(f"Xtigervnc exited before startup:\n{log_tail}")
            if Path("/tmp/.X11-unix/X0").exists():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(f"Xtigervnc did not create {env['DISPLAY']} in time")
        yield env
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log_handle.close()
        log_path.unlink(missing_ok=True)


def _render_modern(opts: UIRenderOptions) -> None:
    openpilot_dir = Path(opts.openpilot_dir).resolve()
    if not _has_modern_openpilot(openpilot_dir):
        raise FileNotFoundError(f"Modern clip tool not found at {openpilot_dir}/tools/clip/run.py")

    _patch_openpilot_framereader_compat(openpilot_dir)
    _patch_openpilot_qcam_local_decode(openpilot_dir)
    _ensure_fonts(openpilot_dir)

    env = os.environ.copy()
    if platform.system() == "Darwin":
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        env.setdefault("FFMPEG_HWACCEL", "none")

    render_start = max(0, opts.start_seconds - max(0, opts.smear_seconds))
    render_end = opts.start_seconds + opts.length_seconds
    trim_front = opts.start_seconds - render_start

    clip_cmd = [
        *_openpilot_python_cmd(openpilot_dir), "tools/clip/run.py",
        opts.route.replace("|", "/"),
        "-s", str(render_start),
        "-e", str(render_end),
        "-o", str(Path(opts.output_path).resolve()),
        "-f", str(opts.target_mb),
        # Upstream tool expects integer speed. Preserve speedhack by clamping.
        "-x", str(max(1, int(round(opts.speedhack_ratio)))),
    ]
    if opts.data_dir:
        compat_root = _build_openpilot_compatible_data_dir(opts.route, Path(opts.data_dir))
        clip_cmd += ["-d", str(compat_root)]
    clip_cmd += _ui_mode_to_modern_flags(opts.ui_mode)
    if not opts.headless:
        clip_cmd.append("--windowed")
    if opts.metric:
        # No direct flag in upstream clip tool currently.
        print("warning: modern backend does not expose metric toggle; ignoring")

    use_headless_display = opts.headless and platform.system() == "Linux" and not env.get("DISPLAY")
    with _temporary_headless_display(env, enabled=use_headless_display) as render_env:
        _run(clip_cmd, cwd=openpilot_dir, env=render_env)
    _trim_mp4_in_place(Path(opts.output_path), trim_front)


def _render_legacy(opts: UIRenderOptions) -> None:
    command = [
        "./clip.sh",
        opts.route,
        f"--start-seconds={opts.start_seconds}",
        f"--length-seconds={opts.length_seconds}",
        f"--smear-amount={opts.smear_seconds}",
        f"--speedhack-ratio={opts.speedhack_ratio}",
        f"--target-mb={opts.target_mb}",
        f"--format={opts.file_format}",
        f"--data-dir={os.path.abspath(opts.data_dir)}" if opts.data_dir else "",
        f"--output={Path(opts.output_path).name}",
    ]
    command = [c for c in command if c]
    if opts.metric:
        command.append("--metric")
    if opts.jwt_token:
        command.append(f"--jwt-token={opts.jwt_token}")
    env = os.environ.copy()
    env.update({"DISPLAY": ":0", "SCALE": "1"})
    if opts.ui_mode in ("c3", "c3x", "big"):
        env["BIG"] = "1"
    elif opts.ui_mode == "c4":
        env.pop("BIG", None)
    _run(command, env=env)

    # clip.sh writes into ./shared by basename; move to requested path if needed
    desired = Path(opts.output_path).resolve()
    default_out = Path("./shared") / Path(opts.output_path).name
    if default_out.resolve() != desired and default_out.exists():
        desired.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(default_out), str(desired))


def render_ui_clip(opts: UIRenderOptions) -> None:
    backend = _choose_backend(opts)
    if backend == "modern":
        try:
            _render_modern(opts)
            return
        except Exception as e:
            if opts.backend == "modern":
                raise
            print(f"warning: modern UI render backend failed, falling back to legacy: {e}")
    if not _has_legacy_clip_script():
        raise RuntimeError("Legacy backend unavailable (missing ./clip.sh) and modern backend failed/unavailable")
    _render_legacy(opts)
