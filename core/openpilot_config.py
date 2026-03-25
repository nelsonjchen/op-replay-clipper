from __future__ import annotations

import os


DEFAULT_OPENPILOT_REPO_URL = "https://github.com/commaai/openpilot.git"
DEFAULT_OPENPILOT_BRANCH = "master"
DEFAULT_IMAGE_OPENPILOT_ROOT = "/home/batman/openpilot"
DEFAULT_LOCAL_OPENPILOT_ROOT = "./.cache/openpilot-local"


def default_openpilot_repo_url() -> str:
    return os.environ.get("OPENPILOT_REPO_URL", DEFAULT_OPENPILOT_REPO_URL)


def default_openpilot_branch() -> str:
    return os.environ.get("OPENPILOT_BRANCH", DEFAULT_OPENPILOT_BRANCH)


def default_image_openpilot_root() -> str:
    return os.environ.get("OPENPILOT_ROOT", DEFAULT_IMAGE_OPENPILOT_ROOT)


def default_local_openpilot_root() -> str:
    return os.environ.get("OPENPILOT_LOCAL_ROOT", DEFAULT_LOCAL_OPENPILOT_ROOT)
