from __future__ import annotations

import platform
import shutil
import subprocess
import os
import sys
from pathlib import Path

from core.openpilot_config import DEFAULT_OPENPILOT_REPO_URL, default_local_openpilot_root


GIT_CLONE_FLAGS = [
    "--depth",
    "1",
    "--filter=blob:none",
    "--recurse-submodules",
    "--shallow-submodules",
    "--single-branch",
]
GIT_FETCH_FLAGS = [
    "--depth",
    "1",
    "--filter=blob:none",
]
GIT_SUBMODULE_UPDATE_FLAGS = [
    "--init",
    "--recursive",
    "--depth",
    "1",
    "--jobs",
    "8",
]


def _uv_cmd() -> str:
    explicit = os.environ.get("UV_BIN")
    if explicit:
        return explicit
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (
        Path.home() / ".local/bin/uv",
        Path("/usr/local/bin/uv"),
    ):
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("Could not find uv; set UV_BIN or install uv on PATH")


def _run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(cmd)}")
    run_env = dict(os.environ)
    if env is not None:
        run_env.update(env)
    if cwd:
        run_env["PWD"] = str(cwd)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=run_env, check=True)


def _capture(cmd: list[str], cwd: Path | None = None) -> str:
    run_env = dict(os.environ)
    if cwd:
        run_env["PWD"] = str(cwd)
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=run_env,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def _read_python_version(openpilot_dir: Path) -> str | None:
    version_file = openpilot_dir / ".python-version"
    if not version_file.exists():
        return None
    version = version_file.read_text().strip()
    return version or None


def _resolve_openpilot_python(openpilot_dir: Path) -> str | None:
    requested_version = _read_python_version(openpilot_dir)
    if not requested_version:
        return None

    uv_bin = _uv_cmd()
    try:
        return _capture([uv_bin, "python", "find", requested_version], cwd=openpilot_dir)
    except subprocess.CalledProcessError:
        major_minor = ".".join(requested_version.split(".")[:2])
        if not major_minor:
            raise
        print(
            f"Exact Python {requested_version} is unavailable here, "
            f"falling back to a compatible {major_minor}.x interpreter for local bootstrap."
        )
        try:
            _run([uv_bin, "python", "install", major_minor], cwd=openpilot_dir)
        except subprocess.CalledProcessError:
            pass
        return _capture([uv_bin, "python", "find", major_minor], cwd=openpilot_dir)


def _ensure_git_lfs_cli(cwd: Path | None = None) -> None:
    # We explicitly run `git lfs pull` after checkout/update, so we only need
    # the CLI to exist here; mutating user git hooks via `git lfs install`
    # breaks local dev setups that already customize post-checkout hooks.
    _run(["git", "lfs", "version"], cwd=cwd)


def _clone_checkout(openpilot_dir: Path, branch: str, repo_url: str) -> None:
    openpilot_dir.parent.mkdir(parents=True, exist_ok=True)
    _ensure_git_lfs_cli()
    _run(
        [
            "git",
            "clone",
            *GIT_CLONE_FLAGS,
            "--branch",
            branch,
            repo_url,
            str(openpilot_dir),
        ]
    )
    _run(["git", "lfs", "pull"], cwd=openpilot_dir)


def _is_managed_local_checkout(openpilot_dir: Path) -> bool:
    managed_root = Path(default_local_openpilot_root()).expanduser()
    return openpilot_dir == managed_root.resolve()


def ensure_openpilot_checkout(
    openpilot_dir: Path,
    branch: str = "master",
    repo_url: str = DEFAULT_OPENPILOT_REPO_URL,
) -> None:
    if not openpilot_dir.exists():
        _clone_checkout(openpilot_dir, branch, repo_url)
        return

    try:
        _ensure_git_lfs_cli(openpilot_dir)
        _run(["git", "remote", "set-url", "origin", repo_url], cwd=openpilot_dir)
        _run(["git", "fetch", *GIT_FETCH_FLAGS, "origin", branch], cwd=openpilot_dir)
        _run(["git", "checkout", branch], cwd=openpilot_dir)
        _run(["git", "pull", "--ff-only", "--recurse-submodules", "origin", branch], cwd=openpilot_dir)
        _run(["git", "submodule", "sync", "--recursive"], cwd=openpilot_dir)
        _run(["git", "submodule", "update", *GIT_SUBMODULE_UPDATE_FLAGS], cwd=openpilot_dir)
        _run(["git", "lfs", "pull"], cwd=openpilot_dir)
    except subprocess.CalledProcessError:
        if not _is_managed_local_checkout(openpilot_dir):
            raise
        print(f"Managed openpilot cache at {openpilot_dir} drifted; recloning a fresh checkout.")
        shutil.rmtree(openpilot_dir)
        _clone_checkout(openpilot_dir, branch, repo_url)


def ensure_macos_env_fix(openpilot_dir: Path) -> None:
    if platform.system() != "Darwin":
        return

    env_file = openpilot_dir / ".env"
    line = "export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES"
    existing = env_file.read_text() if env_file.exists() else ""
    if line not in existing:
        with env_file.open("a") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(f"{line}\n")


def bootstrap_openpilot(openpilot_dir: Path) -> None:
    python_executable = _resolve_openpilot_python(openpilot_dir)
    uv_bin = _uv_cmd()
    sync_cmd = [uv_bin, "sync", "--frozen", "--all-extras"]
    if python_executable:
        sync_cmd.extend(["--python", python_executable])
    _run(sync_cmd, cwd=openpilot_dir)
    ensure_macos_env_fix(openpilot_dir)

    scons_targets = [
        "msgq_repo/msgq/ipc_pyx.so",
        "msgq_repo/msgq/visionipc/visionipc_pyx.so",
        "common/params_pyx.so",
        "selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so",
        "selfdrive/controls/lib/lateral_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so",
    ]
    scons_cmd = [uv_bin, "run", "--no-sync"]
    if python_executable:
        scons_cmd.extend(["--python", python_executable])
    scons_cmd.extend(["scons", "-j8", *scons_targets])
    _run(scons_cmd, cwd=openpilot_dir)
    install_accelerated_linux_pyray(openpilot_dir)


def install_accelerated_linux_pyray(openpilot_dir: Path) -> None:
    if platform.system() != "Linux":
        return
    venv_python = openpilot_dir / ".venv/bin/python"
    if not venv_python.exists():
        return
    helper = Path(__file__).resolve().parents[1] / "common/build_linux_pyray_null_egl.py"
    if not helper.exists():
        raise FileNotFoundError(f"Missing Linux pyray builder at {helper}")
    _run([sys.executable, str(helper), "--python-bin", str(venv_python)], cwd=openpilot_dir)
