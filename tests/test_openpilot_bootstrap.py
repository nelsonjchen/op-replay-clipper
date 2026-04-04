from __future__ import annotations

from pathlib import Path
from unittest import mock

from core import openpilot_bootstrap


def test_capture_preserves_path_when_setting_pwd(tmp_path: Path) -> None:
    with mock.patch.dict("os.environ", {"PATH": "/tmp/fake-bin"}, clear=True):
        with mock.patch("core.openpilot_bootstrap.subprocess.run") as run:
            run.return_value = mock.Mock(stdout="ok")
            openpilot_bootstrap._capture(["uv", "python", "find", "3.12"], cwd=tmp_path)

    env = run.call_args.kwargs["env"]
    assert env["PATH"] == "/tmp/fake-bin"
    assert env["PWD"] == str(tmp_path)


@mock.patch("core.openpilot_bootstrap._run")
def test_clone_checkout_uses_blobless_public_repo_flags(run: mock.Mock, tmp_path: Path) -> None:
    openpilot_dir = tmp_path / "openpilot"

    openpilot_bootstrap.ensure_openpilot_checkout(
        openpilot_dir,
        branch="feature/test",
        repo_url="git@github.com:commaai/openpilot.git",
    )

    commands = [call.args[0] for call in run.call_args_list]
    assert commands[0] == ["git", "lfs", "version"]
    command = commands[1]
    assert command[:2] == ["git", "clone"]
    assert "--filter=blob:none" in command
    assert "--shallow-submodules" in command
    assert "--single-branch" in command
    assert "git@github.com:commaai/openpilot.git" in command
    assert "feature/test" in command
    assert str(openpilot_dir) == command[-1]
    assert commands[2] == ["git", "lfs", "pull"]


@mock.patch("core.openpilot_bootstrap._run")
def test_existing_checkout_updates_remote_fetch_and_submodules(run: mock.Mock, tmp_path: Path) -> None:
    openpilot_dir = tmp_path / "openpilot"
    openpilot_dir.mkdir()

    openpilot_bootstrap.ensure_openpilot_checkout(
        openpilot_dir,
        branch="master",
        repo_url="https://github.com/commaai/openpilot.git",
    )

    commands = [call.args[0] for call in run.call_args_list]
    assert ["git", "lfs", "version"] in commands
    assert ["git", "remote", "set-url", "origin", "https://github.com/commaai/openpilot.git"] in commands
    assert ["git", "fetch", "--depth", "1", "--filter=blob:none", "origin", "master"] in commands
    assert ["git", "submodule", "sync", "--recursive"] in commands
    assert ["git", "submodule", "update", "--init", "--recursive", "--depth", "1", "--jobs", "8"] in commands
    assert ["git", "lfs", "pull"] in commands


@mock.patch("core.openpilot_bootstrap.shutil.rmtree")
@mock.patch("core.openpilot_bootstrap.default_local_openpilot_root")
@mock.patch("core.openpilot_bootstrap._run")
def test_managed_checkout_reclones_when_ff_only_update_fails(
    run: mock.Mock,
    default_root: mock.Mock,
    rmtree: mock.Mock,
    tmp_path: Path,
) -> None:
    openpilot_dir = tmp_path / "managed-openpilot"
    openpilot_dir.mkdir()
    default_root.return_value = str(openpilot_dir)

    def side_effect(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
        if cmd[:3] == ["git", "pull", "--ff-only"]:
            raise openpilot_bootstrap.subprocess.CalledProcessError(128, cmd)

    run.side_effect = side_effect

    openpilot_bootstrap.ensure_openpilot_checkout(
        openpilot_dir,
        branch="master",
        repo_url="https://github.com/commaai/openpilot.git",
    )

    rmtree.assert_called_once_with(openpilot_dir)
    commands = [call.args[0] for call in run.call_args_list]
    assert ["git", "lfs", "version"] in commands
    assert ["git", "clone", *openpilot_bootstrap.GIT_CLONE_FLAGS, "--branch", "master", "https://github.com/commaai/openpilot.git", str(openpilot_dir)] in commands
    assert ["git", "lfs", "pull"] in commands
