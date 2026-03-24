from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from openpilot_defaults import DEFAULT_OPENPILOT_REPO_URL


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


def _run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(cmd)}")
    run_env = None if env is None else dict(env)
    if cwd:
        run_env = dict(run_env or {})
        run_env["PWD"] = str(cwd)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=run_env, check=True)


def _capture(cmd: list[str], cwd: Path | None = None) -> str:
    run_env = None
    if cwd:
        run_env = {"PWD": str(cwd)}
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

    try:
        return _capture(["uv", "python", "find", requested_version], cwd=openpilot_dir)
    except subprocess.CalledProcessError:
        major_minor = ".".join(requested_version.split(".")[:2])
        if not major_minor:
            raise
        print(
            f"Exact Python {requested_version} is unavailable here, "
            f"falling back to a compatible {major_minor}.x interpreter for local bootstrap."
        )
        try:
            _run(["uv", "python", "install", major_minor], cwd=openpilot_dir)
        except subprocess.CalledProcessError:
            pass
        return _capture(["uv", "python", "find", major_minor], cwd=openpilot_dir)


def ensure_openpilot_checkout(
    openpilot_dir: Path,
    branch: str = "master",
    repo_url: str = DEFAULT_OPENPILOT_REPO_URL,
) -> None:
    if not openpilot_dir.exists():
        openpilot_dir.parent.mkdir(parents=True, exist_ok=True)
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
        return

    _run(["git", "remote", "set-url", "origin", repo_url], cwd=openpilot_dir)
    _run(["git", "fetch", *GIT_FETCH_FLAGS, "origin", branch], cwd=openpilot_dir)
    _run(["git", "checkout", branch], cwd=openpilot_dir)
    _run(["git", "pull", "--ff-only", "--recurse-submodules", "origin", branch], cwd=openpilot_dir)
    _run(["git", "submodule", "sync", "--recursive"], cwd=openpilot_dir)
    _run(["git", "submodule", "update", *GIT_SUBMODULE_UPDATE_FLAGS], cwd=openpilot_dir)


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
    sync_cmd = ["uv", "sync", "--frozen", "--all-extras"]
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
    scons_cmd = ["uv", "run"]
    if python_executable:
        scons_cmd.extend(["--python", python_executable])
    scons_cmd.extend(["scons", "-j8", *scons_targets])
    _run(scons_cmd, cwd=openpilot_dir)
