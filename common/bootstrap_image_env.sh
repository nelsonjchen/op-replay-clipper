#!/usr/bin/env bash

set -euo pipefail

# Shared bootstrap for Docker/Cog images that need a working openpilot clip environment.
# CACHE_BUSTER: 2026-04-03-facefusion-rebuild-v3

APP_ROOT="${APP_ROOT:-$(pwd)}"
OPENPILOT_ROOT="${OPENPILOT_ROOT:-/home/batman/openpilot}"
OPENPILOT_REPO_URL="${OPENPILOT_REPO_URL:-https://github.com/commaai/openpilot.git}"
OPENPILOT_BRANCH="${OPENPILOT_BRANCH:-master}"
OPENPILOT_CLONE_DEPTH="${OPENPILOT_CLONE_DEPTH:-1}"
FACEFUSION_ROOT="${FACEFUSION_ROOT:-${APP_ROOT}/.cache/facefusion}"
FACEFUSION_REPO_URL="${FACEFUSION_REPO_URL:-https://github.com/facefusion/facefusion.git}"
FACEFUSION_COMMIT="${FACEFUSION_COMMIT:-519360bcd650679275024aa3ed10e8d673718bb3}"
FACEFUSION_PYTHON_VERSION="${FACEFUSION_PYTHON_VERSION:-3.12}"
FACEFUSION_PREWARM_MODELS="${FACEFUSION_PREWARM_MODELS:-1}"
FACEFUSION_PREWARM_RETRIES="${FACEFUSION_PREWARM_RETRIES:-3}"
FACEFUSION_PRUNE_VENV="${FACEFUSION_PRUNE_VENV:-1}"
FACEFUSION_HARDLINK_DEDUPE="${FACEFUSION_HARDLINK_DEDUPE:-1}"
FACEFUSION_PRUNE_UNUSED_PACKAGES="${FACEFUSION_PRUNE_UNUSED_PACKAGES:-1}"
RF_DETR_PREWARM_WEIGHTS="${RF_DETR_PREWARM_WEIGHTS:-1}"
RF_DETR_PREWARM_MODEL_IDS="${RF_DETR_PREWARM_MODEL_IDS:-rfdetr-seg-preview}"
export RF_DETR_PREWARM_WEIGHTS RF_DETR_PREWARM_MODEL_IDS
OPENPILOT_BUILD_UI_ASSETS="${OPENPILOT_BUILD_UI_ASSETS:-1}"
OPENPILOT_INSTALL_X_RUNTIME_PACKAGES="${OPENPILOT_INSTALL_X_RUNTIME_PACKAGES:-0}"
OPENPILOT_NVIDIA_GL_PACKAGE="${OPENPILOT_NVIDIA_GL_PACKAGE:-libnvidia-gl-580-server}"
SCONS_JOBS="${SCONS_JOBS:-$(command -v nproc >/dev/null 2>&1 && nproc || echo 8)}"
BUILD_TMPDIR="${BUILD_TMPDIR:-/var/tmp/op-clipper-build}"
export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

APT_PACKAGES=(
  build-essential
  cmake
  jq
  ffmpeg
  faketime
  eatmydata
  htop
  bc
  net-tools
  sudo
  wget
  curl
  capnproto
  git-lfs
  tzdata
  zstd
  git
)

UI_RUNTIME_APT_PACKAGES=(
  xserver-xorg-core
  mesa-utils
  xserver-xorg-video-nvidia-525
)

UI_APT_PACKAGES=(
  libxrandr-dev
  libxinerama-dev
  libxcursor-dev
  libxi-dev
  libxext-dev
  libegl1-mesa-dev
  xorg-dev
)

UI_GPU_RUNTIME_APT_PACKAGES=(
  "${OPENPILOT_NVIDIA_GL_PACKAGE}"
)

log_step() {
  printf '\n==> %s\n' "$1"
}

configure_build_tempdir() {
  log_step "Configuring build temp directory"
  mkdir -p "${BUILD_TMPDIR}"
  chmod 1777 "${BUILD_TMPDIR}"
  export TMPDIR="${BUILD_TMPDIR}"
  export TMP="${BUILD_TMPDIR}"
  export TEMP="${BUILD_TMPDIR}"
  export XDG_CACHE_HOME="${BUILD_TMPDIR}/xdg-cache"
  export UV_CACHE_DIR="${BUILD_TMPDIR}/uv-cache"
  export PIP_CACHE_DIR="${BUILD_TMPDIR}/pip-cache"
  export PIP_NO_CACHE_DIR=1
  export UV_NO_CACHE=1
  mkdir -p "${XDG_CACHE_HOME}" "${UV_CACHE_DIR}" "${PIP_CACHE_DIR}"
}

redirect_system_tmp() {
  log_step "Redirecting /tmp to build temp directory"
  rm -rf /tmp/*
  rmdir /tmp
  ln -s "${BUILD_TMPDIR}" /tmp
}

install_system_packages() {
  log_step "Installing system packages"
  apt-get update -y
  apt-get install -y "${APT_PACKAGES[@]}"
  if [[ "${OPENPILOT_BUILD_UI_ASSETS}" == "1" ]]; then
    apt-get install -y "${UI_APT_PACKAGES[@]}"
    apt-get install -y "${UI_GPU_RUNTIME_APT_PACKAGES[@]}"
    if [[ "${OPENPILOT_INSTALL_X_RUNTIME_PACKAGES}" == "1" ]]; then
      apt-get install -y "${UI_RUNTIME_APT_PACKAGES[@]}"
    fi
  fi
}

sync_python_nvidia_runtime_libs() {
  log_step "Linking Python-provided NVIDIA runtime libraries into system library path"
  python - <<'PY'
from __future__ import annotations

import pathlib
import site

system_lib_dir = pathlib.Path("/usr/lib/x86_64-linux-gnu")
if not system_lib_dir.exists():
    raise SystemExit(0)

for root in site.getsitepackages():
    nvidia_root = pathlib.Path(root) / "nvidia"
    if not nvidia_root.exists():
        continue
    for lib_dir in sorted(path for path in nvidia_root.iterdir() if (path / "lib").exists()):
        for lib_file in sorted((lib_dir / "lib").glob("lib*.so*")):
            if lib_file.is_dir():
                continue
            target = system_lib_dir / lib_file.name
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(lib_file)
            print(f"linked {target} -> {lib_file}", flush=True)
PY
}

configure_git_lfs() {
  log_step "Checking git-lfs CLI"
  git lfs version
}

clone_facefusion_checkout() {
  log_step "Cloning FaceFusion into ${FACEFUSION_ROOT}"
  rm -rf "${FACEFUSION_ROOT}"
  mkdir -p "$(dirname "${FACEFUSION_ROOT}")"
  git clone --filter=blob:none "${FACEFUSION_REPO_URL}" "${FACEFUSION_ROOT}"
  if [[ -n "${FACEFUSION_COMMIT}" ]]; then
    cd "${FACEFUSION_ROOT}"
    git checkout "${FACEFUSION_COMMIT}"
  fi
}

clone_openpilot_checkout() {
  log_step "Cloning openpilot into ${OPENPILOT_ROOT}"
  rm -rf "${OPENPILOT_ROOT}"
  git clone \
    --branch "${OPENPILOT_BRANCH}" \
    --depth "${OPENPILOT_CLONE_DEPTH}" \
    --filter=blob:none \
    --recurse-submodules \
    --shallow-submodules \
    --single-branch \
    "${OPENPILOT_REPO_URL}" \
    "${OPENPILOT_ROOT}"
}

install_openpilot_dependencies() {
  log_step "Installing openpilot dependencies"
  cd "${OPENPILOT_ROOT}"

  if [[ -x ./tools/setup_dependencies.sh ]]; then
    ./tools/setup_dependencies.sh
    return
  fi

  if [[ -x ./tools/ubuntu_setup.sh ]]; then
    INSTALL_EXTRA_PACKAGES=yes ./tools/ubuntu_setup.sh
    ./tools/install_python_dependencies.sh
    return
  fi

  echo "No supported openpilot dependency setup scripts found" >&2
  exit 1
}

ensure_uv_on_path() {
  if [[ ! -x /root/.local/bin/uv ]]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  ln -sf /root/.local/bin/uv /usr/local/bin/uv
  export PATH="/root/.local/bin:${PATH}"
}

prewarm_rf_detr_weights() {
  if [[ "${RF_DETR_PREWARM_WEIGHTS}" != "1" ]]; then
    log_step "Skipping RF-DETR weight prewarm"
    return
  fi

  log_step "Prewarming RF-DETR weights"
  local weights_dir="${RF_DETR_WEIGHTS_DIR:-}"
  if [[ -z "${weights_dir}" ]]; then
    if [[ "${APP_ROOT}" == "/" ]]; then
      weights_dir="/src/.cache/rfdetr"
    else
      weights_dir="${APP_ROOT}/.cache/rfdetr"
    fi
  fi
  mkdir -p "${weights_dir}"
  cd "${APP_ROOT}"
  RF_DETR_WEIGHTS_DIR="${weights_dir}" DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE=cpu python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

from rfdetr import (
    RFDETRSeg2XLarge,
    RFDETRSegLarge,
    RFDETRSegMedium,
    RFDETRSegNano,
    RFDETRSegPreview,
    RFDETRSegSmall,
    RFDETRSegXLarge,
)

model_ids = [model_id.strip() for model_id in os.environ.get("RF_DETR_PREWARM_MODEL_IDS", "").split(",") if model_id.strip()]
if not model_ids:
    raise SystemExit("RF_DETR_PREWARM_MODEL_IDS is empty")

model_classes = {
    "rfdetr-seg-preview": RFDETRSegPreview,
    "rfdetr-seg-nano": RFDETRSegNano,
    "rfdetr-seg-small": RFDETRSegSmall,
    "rfdetr-seg-medium": RFDETRSegMedium,
    "rfdetr-seg-large": RFDETRSegLarge,
    "rfdetr-seg-xlarge": RFDETRSegXLarge,
    "rfdetr-seg-2xlarge": RFDETRSeg2XLarge,
    "rfdetr-seg-xxlarge": RFDETRSeg2XLarge,
}
weight_filenames = {
    "rfdetr-seg-preview": "rf-detr-seg-preview.pt",
    "rfdetr-seg-nano": "rf-detr-seg-nano.pt",
    "rfdetr-seg-small": "rf-detr-seg-small.pt",
    "rfdetr-seg-medium": "rf-detr-seg-medium.pt",
    "rfdetr-seg-large": "rf-detr-seg-large.pt",
    "rfdetr-seg-xlarge": "rf-detr-seg-xlarge.pt",
    "rfdetr-seg-2xlarge": "rf-detr-seg-xxlarge.pt",
    "rfdetr-seg-xxlarge": "rf-detr-seg-xxlarge.pt",
}

weights_dir = Path(os.environ["RF_DETR_WEIGHTS_DIR"]).expanduser().resolve()
weights_dir.mkdir(parents=True, exist_ok=True)

for model_id in model_ids:
    try:
        model_class = model_classes[model_id]
        weight_filename = weight_filenames[model_id]
    except KeyError as exc:
        raise SystemExit(f"Unsupported RF-DETR segmentation model id: {model_id}") from exc
    model_class(pretrain_weights=str((weights_dir / weight_filename).resolve()), device="cpu")
    weights_path = weights_dir / weight_filename
    if not weights_path.exists():
        raise SystemExit(f"RF-DETR weights were not materialized for {model_id}: {weights_path}")
    print(f"warmed {weights_path}", flush=True)
PY
}

install_facefusion_runtime() {
  log_step "Installing FaceFusion CUDA runtime"
  cd "${FACEFUSION_ROOT}"
  uv python install "${FACEFUSION_PYTHON_VERSION}"
  uv venv --python "${FACEFUSION_PYTHON_VERSION}" --seed .venv
  . .venv/bin/activate
  python -m pip install --upgrade pip wheel setuptools
  python install.py --onnxruntime cuda --skip-conda
}

prewarm_facefusion_models() {
  if [[ "${FACEFUSION_PREWARM_MODELS}" != "1" ]]; then
    log_step "Skipping FaceFusion model prewarm"
    return
  fi
  log_step "Prewarming FaceFusion model assets"
  cd "${FACEFUSION_ROOT}"
  . .venv/bin/activate
  FACEFUSION_PREWARM_RETRIES="${FACEFUSION_PREWARM_RETRIES}" python - <<'PY'
from __future__ import annotations

import os
import time
import sys
from pathlib import Path

root = Path.cwd()
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from facefusion import state_manager
from facefusion import face_classifier, face_detector, face_landmarker, face_masker, face_recognizer
from facefusion.processors.modules.face_swapper import core as face_swapper

state_manager.init_item("execution_device_ids", [0])
state_manager.init_item("execution_providers", ["cpu"])
state_manager.init_item("download_providers", ["github", "huggingface"])
state_manager.init_item("face_detector_model", "yunet")
state_manager.init_item("face_detector_size", "640x640")
state_manager.init_item("face_detector_margin", [0, 0, 0, 0])
state_manager.init_item("face_detector_score", 0.35)
state_manager.init_item("face_detector_angles", [0])
state_manager.init_item("face_landmarker_model", "2dfan4")
state_manager.init_item("face_occluder_model", "xseg_1")
state_manager.init_item("face_parser_model", "bisenet_resnet_34")
state_manager.init_item("face_swapper_model", "hyperswap_1b_256")
state_manager.init_item("face_swapper_pixel_boost", "256x256")
state_manager.init_item("face_swapper_weight", 1.0)

max_attempts = max(1, int(os.environ.get("FACEFUSION_PREWARM_RETRIES", "3")))
checks = [
    ("face_detector", face_detector.pre_check),
    ("face_landmarker", face_landmarker.pre_check),
    ("face_recognizer", face_recognizer.pre_check),
    ("face_classifier", face_classifier.pre_check),
    ("face_masker", face_masker.pre_check),
    ("face_swapper", face_swapper.pre_check),
]
for label, fn in checks:
    for attempt in range(1, max_attempts + 1):
        ok = fn()
        print(f"{label} pre_check={ok} attempt={attempt}/{max_attempts}", flush=True)
        if ok:
            break
        if attempt == max_attempts:
            raise SystemExit(f"Failed to prewarm {label} after {max_attempts} attempts")
        time.sleep(min(attempt, 5))
PY
}

dedupe_python_env_against_main_site_packages() {
  local env_root="$1"
  local label="$2"

  if [[ "${FACEFUSION_HARDLINK_DEDUPE}" != "1" ]]; then
    log_step "Skipping ${label} hardlink dedupe"
    return
  fi

  log_step "Hardlinking duplicate ${label} files"
  python3 - "${env_root}" "${label}" <<'PY'
from __future__ import annotations

import hashlib
import os
import site
import sys
from pathlib import Path


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


env_root = Path(sys.argv[1]).expanduser().resolve()
label = sys.argv[2]
venv_site_packages = next(env_root.glob(".venv/lib/python*/site-packages"), None)
if venv_site_packages is None:
    print(f"{label} site-packages directory not found; skipping dedupe", flush=True)
    raise SystemExit(0)

main_site_packages = None
for candidate in map(Path, site.getsitepackages()):
    if candidate.name == "site-packages" and candidate.exists():
        main_site_packages = candidate.resolve()
        break

if main_site_packages is None:
    print("Main site-packages directory not found; skipping dedupe", flush=True)
    raise SystemExit(0)

linked_files = 0
linked_bytes = 0
for ff_path in sorted(venv_site_packages.rglob("*")):
    if not ff_path.is_file() or ff_path.is_symlink():
        continue
    relative = ff_path.relative_to(venv_site_packages)
    main_path = main_site_packages / relative
    if not main_path.exists() or not main_path.is_file() or main_path.is_symlink():
        continue
    ff_stat = ff_path.stat()
    main_stat = main_path.stat()
    if ff_stat.st_size == 0 or ff_stat.st_size != main_stat.st_size:
        continue
    if ff_stat.st_ino == main_stat.st_ino and ff_stat.st_dev == main_stat.st_dev:
        continue
    if sha256sum(ff_path) != sha256sum(main_path):
        continue
    ff_path.unlink()
    os.link(main_path, ff_path)
    linked_files += 1
    linked_bytes += ff_stat.st_size

print(
    f"Hardlinked {linked_files} duplicate {label} files "
    f"({linked_bytes / (1024 * 1024):.1f} MiB shared)",
    flush=True,
)
PY
}

dedupe_facefusion_venv_files() {
  dedupe_python_env_against_main_site_packages "${FACEFUSION_ROOT}" "FaceFusion virtualenv"
}

prune_facefusion_unused_runtime_packages() {
  if [[ "${FACEFUSION_PRUNE_UNUSED_PACKAGES}" != "1" ]]; then
    log_step "Skipping FaceFusion unused package pruning"
    return
  fi

  log_step "Pruning FaceFusion web UI packages not used by hosted clip paths"
  cd "${FACEFUSION_ROOT}"
  . .venv/bin/activate
  python -m pip uninstall -y \
    gradio \
    gradio_client \
    gradio_rangeslider \
    pandas \
    fastapi \
    starlette \
    uvicorn \
    websockets \
    orjson || true
}

dedupe_openpilot_venv_files() {
  dedupe_python_env_against_main_site_packages "${OPENPILOT_ROOT}" "openpilot virtualenv"
}

deactivate_facefusion_venv() {
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    log_step "Deactivating FaceFusion virtualenv before openpilot bootstrap"
    deactivate || true
  fi
}

prune_facefusion_venv() {
  if [[ "${FACEFUSION_PRUNE_VENV}" != "1" ]]; then
    log_step "Skipping FaceFusion virtualenv pruning"
    return
  fi

  log_step "Pruning FaceFusion virtualenv bootstrap tooling"
  local facefusion_venv="${FACEFUSION_ROOT}/.venv"
  if [[ ! -d "${facefusion_venv}" ]]; then
    return
  fi

  rm -rf "${facefusion_venv}/include" "${facefusion_venv}/share"
  find "${facefusion_venv}" -type d -name '__pycache__' -prune -exec rm -rf {} +
  find "${facefusion_venv}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

  python3 - "${facefusion_venv}" <<'PY'
from __future__ import annotations

import shutil
import sys
from pathlib import Path

venv_root = Path(sys.argv[1]).expanduser().resolve()
site_packages = next(venv_root.glob("lib/python*/site-packages"), None)
if site_packages is None:
    raise SystemExit(0)

for pattern in (
    "pip",
    "pip-*",
    "setuptools",
    "setuptools-*",
    "wheel",
    "wheel-*",
    "pkg_resources",
):
    for path in site_packages.glob(pattern):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()

for path in site_packages.glob("distutils-precedence.pth"):
    path.unlink()
PY
}

prune_facefusion_checkout() {
  log_step "Pruning FaceFusion checkout"
  cd "${FACEFUSION_ROOT}"
  rm -rf .git .github tests
}

prune_openpilot_venv_artifacts() {
  log_step "Pruning openpilot virtualenv bytecode caches"
  local openpilot_venv="${OPENPILOT_ROOT}/.venv"
  if [[ ! -d "${openpilot_venv}" ]]; then
    return
  fi
  find "${openpilot_venv}" -type d -name '__pycache__' -prune -exec rm -rf {} +
  find "${openpilot_venv}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
}

clean_transient_package_caches() {
  log_step "Cleaning transient package caches"
  rm -rf /root/.cache/uv /root/.cache/pip
  rm -rf "${UV_CACHE_DIR}" "${PIP_CACHE_DIR}"
  mkdir -p "${UV_CACHE_DIR}" "${PIP_CACHE_DIR}"
}

fix_vendored_tool_permissions() {
  if [[ ! -d "${OPENPILOT_ROOT}/.venv/lib" ]]; then
    return
  fi

  log_step "Fixing vendored tool permissions"
  find "${OPENPILOT_ROOT}/.venv/lib" -type f \
    \( -name 'arm-none-eabi-*' -o -name 'capnp' -o -name 'capnpc*' -o -name 'ffmpeg' -o -name 'ffprobe' \) \
    -exec chmod +x {} + || true
}

build_openpilot_clip_dependencies() {
  log_step "Building native openpilot clip dependencies"
  cd "${OPENPILOT_ROOT}"
  uv run --no-sync scons -j"${SCONS_JOBS}" \
    msgq_repo/msgq/ipc_pyx.so \
    msgq_repo/msgq/visionipc/visionipc_pyx.so \
    common/params_pyx.so \
    selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so \
    selfdrive/controls/lib/lateral_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so
}

install_accelerated_linux_pyray() {
  if [[ ! -x "${OPENPILOT_ROOT}/.venv/bin/python" ]]; then
    return
  fi
  log_step "Installing accelerated Linux pyray wheel"
  python3 - "${OPENPILOT_ROOT}/.venv/bin/python" <<'PY'
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

python_bin = sys.argv[1]
raylib_repo = "https://github.com/commaai/raylib.git"
pyray_repo = "https://github.com/commaai/raylib-python-cffi.git"
raygui_url = (
    "https://raw.githubusercontent.com/raysan5/raygui/"
    "76b36b597edb70ffaf96f046076adc20d67e7827/src/raygui.h"
)


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def capture(cmd: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def ensure_pip(python_bin: str) -> None:
    try:
        run([python_bin, "-m", "pip", "--version"])
    except subprocess.CalledProcessError:
        run([python_bin, "-m", "ensurepip", "--upgrade"])
        run([python_bin, "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"])


def verify_installed_pyray(python_bin: str) -> None:
    check = (
        "from pathlib import Path\n"
        "import subprocess\n"
        "import raylib\n"
        "base = Path(raylib.__file__).resolve().parent\n"
        "build = (base / 'build.py').read_text()\n"
        "so = next(base.glob('_raylib_cffi*.so'))\n"
        "version = (base / 'version.py').read_text().strip()\n"
        "binary_strings = subprocess.run(['strings', str(so)], check=True, capture_output=True, text=True).stdout\n"
        "print(version)\n"
        "assert \"os.path.join(get_the_lib_path(), 'libraylib.a')\" in build\n"
        "assert \"'-lEGL'\" in build\n"
        "assert 'GLFW forced null connect' in binary_strings\n"
    )
    run([python_bin, "-c", check])


def replace_once(text: str, needle: str, replacement: str, *, label: str) -> str:
    if replacement in text:
        return text
    if needle not in text:
        raise RuntimeError(f"Could not find {label} patch anchor")
    return text.replace(needle, replacement, 1)


def patch_checkout(raylib_dir: Path) -> None:
    internal = raylib_dir / "src/external/glfw/src/internal.h"
    text = internal.read_text()
    text = replace_once(
        text,
        "#define EGL_WINDOW_BIT 0x0004\n",
        "#define EGL_PBUFFER_BIT 0x0001\n#define EGL_WINDOW_BIT 0x0004\n",
        label="EGL_PBUFFER_BIT",
    )
    text = replace_once(
        text,
        "#define EGL_NATIVE_VISUAL_ID 0x302e\n",
        "#define EGL_NATIVE_VISUAL_ID 0x302e\n#define EGL_WIDTH 0x3057\n#define EGL_HEIGHT 0x3056\n",
        label="EGL pbuffer dimensions",
    )
    text = replace_once(
        text,
        "typedef EGLSurface (APIENTRY * PFN_eglCreateWindowSurface)(EGLDisplay,EGLConfig,EGLNativeWindowType,const EGLint*);\n",
        "typedef EGLSurface (APIENTRY * PFN_eglCreateWindowSurface)(EGLDisplay,EGLConfig,EGLNativeWindowType,const EGLint*);\n"
        "typedef EGLSurface (APIENTRY * PFN_eglCreatePbufferSurface)(EGLDisplay,EGLConfig,const EGLint*);\n",
        label="PFN_eglCreatePbufferSurface typedef",
    )
    text = replace_once(
        text,
        "#define eglCreateWindowSurface _glfw.egl.CreateWindowSurface\n",
        "#define eglCreateWindowSurface _glfw.egl.CreateWindowSurface\n"
        "#define eglCreatePbufferSurface _glfw.egl.CreatePbufferSurface\n",
        label="eglCreatePbufferSurface macro",
    )
    text = replace_once(
        text,
        "        PFN_eglCreateWindowSurface  CreateWindowSurface;\n",
        "        PFN_eglCreateWindowSurface  CreateWindowSurface;\n"
        "        PFN_eglCreatePbufferSurface CreatePbufferSurface;\n",
        label="CreatePbufferSurface field",
    )
    internal.write_text(text)

    platform_c = raylib_dir / "src/external/glfw/src/platform.c"
    text = platform_c.read_text()
    text = replace_once(
        text,
        "#if defined(_GLFW_X11)\n    { GLFW_PLATFORM_X11, _glfwConnectX11 },\n#endif\n};\n",
        "#if defined(_GLFW_X11)\n    { GLFW_PLATFORM_X11, _glfwConnectX11 },\n#endif\n"
        "    { GLFW_PLATFORM_NULL, _glfwConnectNull },\n};\n",
        label="null platform selector",
    )
    text = replace_once(
        text,
        "    const size_t count = sizeof(supportedPlatforms) / sizeof(supportedPlatforms[0]);\n    size_t i;\n\n",
        "    const size_t count = sizeof(supportedPlatforms) / sizeof(supportedPlatforms[0]);\n    size_t i;\n\n"
        "    if (getenv(\"OPENPILOT_UI_NULL_EGL\"))\n    {\n"
        "        fprintf(stderr, \"GLFW forced null connect\\n\");\n"
        "        return _glfwConnectNull(GLFW_PLATFORM_NULL, platform);\n"
        "    }\n\n",
        label="null platform env override",
    )
    platform_c.write_text(text)

    rcore = raylib_dir / "src/platforms/rcore_desktop_glfw.c"
    text = rcore.read_text()
    text = replace_once(
        text,
        "#if defined(__APPLE__)\n    glfwInitHint(GLFW_COCOA_CHDIR_RESOURCES, GLFW_FALSE);\n#endif\n    // Initialize GLFW internal global state\n",
        "#if defined(__APPLE__)\n    glfwInitHint(GLFW_COCOA_CHDIR_RESOURCES, GLFW_FALSE);\n#endif\n"
        "    if (getenv(\"OPENPILOT_UI_NULL_EGL\")) glfwInitHint(GLFW_PLATFORM, GLFW_PLATFORM_NULL);\n"
        "    // Initialize GLFW internal global state\n",
        label="glfwInit null hint",
    )
    text = replace_once(
        text,
        "    glfwDefaultWindowHints();                       // Set default windows hints\n",
        "    glfwDefaultWindowHints();                       // Set default windows hints\n"
        "    if (getenv(\"OPENPILOT_UI_NULL_EGL\")) glfwWindowHint(GLFW_CONTEXT_CREATION_API, GLFW_EGL_CONTEXT_API);\n",
        label="glfw EGL hint",
    )
    rcore.write_text(text)

    egl = raylib_dir / "src/external/glfw/src/egl_context.c"
    text = egl.read_text()
    text = replace_once(
        text,
        "    _glfw.egl.CreateWindowSurface = (PFN_eglCreateWindowSurface)\n        _glfwPlatformGetModuleSymbol(_glfw.egl.handle, \"eglCreateWindowSurface\");\n",
        "    _glfw.egl.CreateWindowSurface = (PFN_eglCreateWindowSurface)\n"
        "        _glfwPlatformGetModuleSymbol(_glfw.egl.handle, \"eglCreateWindowSurface\");\n"
        "    _glfw.egl.CreatePbufferSurface = (PFN_eglCreatePbufferSurface)\n"
        "        _glfwPlatformGetModuleSymbol(_glfw.egl.handle, \"eglCreatePbufferSurface\");\n",
        label="eglCreatePbufferSurface loader",
    )
    text = replace_once(
        text,
        "        !_glfw.egl.CreateWindowSurface ||\n",
        "        !_glfw.egl.CreateWindowSurface ||\n"
        "        !_glfw.egl.CreatePbufferSurface ||\n",
        label="CreatePbufferSurface required check",
    )
    text = replace_once(
        text,
        "        // Only consider window EGLConfigs\n        if (!(getEGLConfigAttrib(n, EGL_SURFACE_TYPE) & EGL_WINDOW_BIT))\n            continue;\n",
        "        // Only consider surface-capable configs\n"
        "        if (_glfw.platform.platformID == GLFW_PLATFORM_NULL)\n"
        "        {\n"
        "            if (!(getEGLConfigAttrib(n, EGL_SURFACE_TYPE) & EGL_PBUFFER_BIT))\n"
        "                continue;\n"
        "        }\n"
        "        else\n"
        "        {\n"
        "            if (!(getEGLConfigAttrib(n, EGL_SURFACE_TYPE) & EGL_WINDOW_BIT))\n"
        "                continue;\n"
        "        }\n",
        label="null EGL config filtering",
    )
    text = replace_once(
        text,
        "    native = _glfw.platform.getEGLNativeWindow(window);\n"
        "    // HACK: ANGLE does not implement eglCreatePlatformWindowSurfaceEXT\n"
        "    //       despite reporting EGL_EXT_platform_base\n"
        "    if (_glfw.egl.platform && _glfw.egl.platform != EGL_PLATFORM_ANGLE_ANGLE)\n"
        "    {\n"
        "        window->context.egl.surface =\n"
        "            eglCreatePlatformWindowSurfaceEXT(_glfw.egl.display, config, native, attribs);\n"
        "    }\n"
        "    else\n"
        "    {\n"
        "        window->context.egl.surface =\n"
        "            eglCreateWindowSurface(_glfw.egl.display, config, native, attribs);\n"
        "    }\n",
        "    if (_glfw.platform.platformID == GLFW_PLATFORM_NULL)\n"
        "    {\n"
        "        const EGLint pbufferAttribs[] = {\n"
        "            EGL_WIDTH, window->null.width > 0 ? window->null.width : 1,\n"
        "            EGL_HEIGHT, window->null.height > 0 ? window->null.height : 1,\n"
        "            EGL_NONE\n"
        "        };\n"
        "        window->context.egl.surface =\n"
        "            eglCreatePbufferSurface(_glfw.egl.display, config, pbufferAttribs);\n"
        "    }\n"
        "    else\n"
        "    {\n"
        "        native = _glfw.platform.getEGLNativeWindow(window);\n"
        "        // HACK: ANGLE does not implement eglCreatePlatformWindowSurfaceEXT\n"
        "        //       despite reporting EGL_EXT_platform_base\n"
        "        if (_glfw.egl.platform && _glfw.egl.platform != EGL_PLATFORM_ANGLE_ANGLE)\n"
        "        {\n"
        "            window->context.egl.surface =\n"
        "                eglCreatePlatformWindowSurfaceEXT(_glfw.egl.display, config, native, attribs);\n"
        "        }\n"
        "        else\n"
        "        {\n"
        "            window->context.egl.surface =\n"
        "                eglCreateWindowSurface(_glfw.egl.display, config, native, attribs);\n"
        "        }\n"
        "    }\n",
        label="null pbuffer surface creation",
    )
    egl.write_text(text)


def patch_pyray_checkout(pyray_dir: Path) -> None:
    build_py = pyray_dir / "raylib/build.py"
    text = build_py.read_text()
    text = replace_once(
        text,
        "        extra_link_args = get_lib_flags() + [ '-lm', '-lpthread', '-lGL',\n"
        "                                              '-lrt', '-lm', '-ldl', '-lpthread', '-latomic']\n",
        "        extra_link_args = [os.path.join(get_the_lib_path(), 'libraylib.a'), '-lm', '-lpthread', '-lGL',\n"
        "                           '-lEGL', '-lrt', '-lm', '-ldl', '-lpthread', '-latomic']\n",
        label="direct static raylib link",
    )
    build_py.write_text(text)


with tempfile.TemporaryDirectory(prefix="pyray-null-egl-") as tmp:
    tmpdir = Path(tmp)
    raylib_dir = tmpdir / "raylib"
    pyray_dir = tmpdir / "raylib-python-cffi"
    stage_dir = tmpdir / "stage"
    include_dir = stage_dir / "include"
    glfw_include_dir = include_dir / "GLFW"
    lib_dir = stage_dir / "lib"
    glfw_include_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    run(["git", "clone", "--depth=1", raylib_repo, str(raylib_dir)])
    patch_checkout(raylib_dir)
    run(
        [
            "cmake",
            "-S",
            str(raylib_dir),
            "-B",
            str(raylib_dir / "build"),
            "-DPLATFORM=Desktop",
            "-DGLFW_BUILD_NULL=ON",
            "-DGLFW_BUILD_WAYLAND=OFF",
            "-DGLFW_BUILD_X11=ON",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DWITH_PIC=ON",
            "-DBUILD_EXAMPLES=OFF",
            "-DBUILD_GAMES=OFF",
        ]
    )
    jobs = capture(["bash", "-lc", "nproc || echo 8"])
    run(["cmake", "--build", str(raylib_dir / "build"), "-j", jobs])

    shutil.copy2(raylib_dir / "build/raylib/libraylib.a", lib_dir / "libraylib.a")
    for header in ("raylib.h", "rlgl.h", "raymath.h"):
        shutil.copy2(raylib_dir / "src" / header, include_dir / header)
    shutil.copy2(raylib_dir / "src/external/glfw/include/GLFW/glfw3.h", glfw_include_dir / "glfw3.h")
    run(["curl", "-fsSLo", str(include_dir / "raygui.h"), raygui_url])

    run(["git", "clone", "--depth=1", pyray_repo, str(pyray_dir)])
    patch_pyray_checkout(pyray_dir)
    env = dict(os.environ)
    env["RAYLIB_PLATFORM"] = "Desktop"
    env["RAYLIB_INCLUDE_PATH"] = str(include_dir)
    env["RAYLIB_LIB_PATH"] = str(lib_dir)
    ensure_pip(python_bin)
    run([python_bin, "-m", "pip", "wheel", ".", "-w", "dist"], cwd=pyray_dir, env=env)
    wheels = sorted((pyray_dir / "dist").glob("*.whl"))
    run([python_bin, "-m", "pip", "install", "--force-reinstall", *map(str, wheels)])
    verify_installed_pyray(python_bin)
PY
}

generate_ui_fonts() {
  log_step "Generating UI font atlases"
  cd "${OPENPILOT_ROOT}"
  uv run --no-sync python selfdrive/assets/fonts/process.py
}

record_checkout_commit() {
  log_step "Recording openpilot commit"
  cd "${OPENPILOT_ROOT}"
  git rev-parse HEAD > "${OPENPILOT_ROOT}/COMMIT"
}

clean_image_artifacts() {
  log_step "Cleaning bootstrap caches"
  rm -rf /tmp/*
  rm -rf "${BUILD_TMPDIR}"/*
  rm -rf /root/.cache
  rm -rf /var/lib/apt/lists/*
}

main() {
  install_system_packages
  sync_python_nvidia_runtime_libs
  configure_build_tempdir
  redirect_system_tmp
  configure_git_lfs
  ensure_uv_on_path
  prewarm_rf_detr_weights
  clone_facefusion_checkout
  install_facefusion_runtime
  prewarm_facefusion_models
  dedupe_facefusion_venv_files
  prune_facefusion_unused_runtime_packages
  prune_facefusion_venv
  deactivate_facefusion_venv
  prune_facefusion_checkout
  clean_transient_package_caches
  clone_openpilot_checkout
  install_openpilot_dependencies
  fix_vendored_tool_permissions
  build_openpilot_clip_dependencies
  dedupe_openpilot_venv_files
  prune_openpilot_venv_artifacts
  if [[ "${OPENPILOT_BUILD_UI_ASSETS}" == "1" ]]; then
    install_accelerated_linux_pyray
    generate_ui_fonts
  fi
  record_checkout_commit
  clean_image_artifacts
}

main "$@"
