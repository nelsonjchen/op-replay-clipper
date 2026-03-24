from __future__ import annotations

from pathlib import Path
from unittest import mock

import openpilot_setup


@mock.patch("openpilot_setup._run")
def test_clone_checkout_uses_blobless_public_repo_flags(run: mock.Mock, tmp_path: Path) -> None:
    openpilot_dir = tmp_path / "openpilot"

    openpilot_setup.ensure_openpilot_checkout(
        openpilot_dir,
        branch="feature/test",
        repo_url="git@github.com:commaai/openpilot.git",
    )

    command = run.call_args.args[0]
    assert command[:2] == ["git", "clone"]
    assert "--filter=blob:none" in command
    assert "--shallow-submodules" in command
    assert "--single-branch" in command
    assert "git@github.com:commaai/openpilot.git" in command
    assert "feature/test" in command
    assert str(openpilot_dir) == command[-1]


@mock.patch("openpilot_setup._run")
def test_existing_checkout_updates_remote_fetch_and_submodules(run: mock.Mock, tmp_path: Path) -> None:
    openpilot_dir = tmp_path / "openpilot"
    openpilot_dir.mkdir()

    openpilot_setup.ensure_openpilot_checkout(
        openpilot_dir,
        branch="master",
        repo_url="https://github.com/commaai/openpilot.git",
    )

    commands = [call.args[0] for call in run.call_args_list]
    assert ["git", "remote", "set-url", "origin", "https://github.com/commaai/openpilot.git"] in commands
    assert ["git", "fetch", "--depth", "1", "--filter=blob:none", "origin", "master"] in commands
    assert ["git", "submodule", "sync", "--recursive"] in commands
    assert ["git", "submodule", "update", "--init", "--recursive", "--depth", "1", "--jobs", "8"] in commands
