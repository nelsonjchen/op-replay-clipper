from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


RAYLIB_REPO = "https://github.com/commaai/raylib.git"
PYRAY_REPO = "https://github.com/commaai/raylib-python-cffi.git"
RAYGUI_URL = (
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
        "import raylib\n"
        "base = Path(raylib.__file__).resolve().parent\n"
        "build = (base / 'build.py').read_text()\n"
        "version = (base / 'version.py').read_text().strip()\n"
        "print(version)\n"
        "assert \"os.path.join(get_the_lib_path(), 'libraylib.a')\" in build\n"
        "assert \"'-lEGL'\" in build\n"
    )
    run([python_bin, "-c", check])


def replace_once(text: str, needle: str, replacement: str, *, label: str) -> str:
    if replacement in text:
        return text
    if needle not in text:
        raise RuntimeError(f"Could not find {label} patch anchor")
    return text.replace(needle, replacement, 1)


def patch_internal_h(path: Path) -> None:
    text = path.read_text()
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
    path.write_text(text)


def patch_platform_c(path: Path) -> None:
    text = path.read_text()
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
    path.write_text(text)


def patch_rcore_glfw(path: Path) -> None:
    text = path.read_text()
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
    path.write_text(text)


def patch_egl_context(path: Path) -> None:
    text = path.read_text()
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
    path.write_text(text)


def patch_raylib_checkout(raylib_dir: Path) -> None:
    patch_internal_h(raylib_dir / "src/external/glfw/src/internal.h")
    patch_platform_c(raylib_dir / "src/external/glfw/src/platform.c")
    patch_rcore_glfw(raylib_dir / "src/platforms/rcore_desktop_glfw.c")
    patch_egl_context(raylib_dir / "src/external/glfw/src/egl_context.c")


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


def build_and_install(*, python_bin: str, work_dir: Path | None) -> None:
    with tempfile.TemporaryDirectory(dir=str(work_dir) if work_dir else None, prefix="pyray-null-egl-") as tmp:
        tmpdir = Path(tmp)
        raylib_dir = tmpdir / "raylib"
        pyray_dir = tmpdir / "raylib-python-cffi"
        stage_dir = tmpdir / "stage"
        include_dir = stage_dir / "include"
        glfw_include_dir = include_dir / "GLFW"
        lib_dir = stage_dir / "lib"
        glfw_include_dir.mkdir(parents=True, exist_ok=True)
        lib_dir.mkdir(parents=True, exist_ok=True)

        run(["git", "clone", "--depth=1", RAYLIB_REPO, str(raylib_dir)])
        patch_raylib_checkout(raylib_dir)

        run(
            [
                "cmake",
                "-S",
                str(raylib_dir),
                "-B",
                str(raylib_dir / "build"),
                "-DPLATFORM=Desktop",
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
        run(["curl", "-fsSLo", str(include_dir / "raygui.h"), RAYGUI_URL])

        run(["git", "clone", "--depth=1", PYRAY_REPO, str(pyray_dir)])
        patch_pyray_checkout(pyray_dir)
        env = dict(
            **{
                "RAYLIB_PLATFORM": "Desktop",
                "RAYLIB_INCLUDE_PATH": str(include_dir),
                "RAYLIB_LIB_PATH": str(lib_dir),
            },
            **dict(os.environ),
        )
        ensure_pip(python_bin)
        run([python_bin, "-m", "pip", "wheel", ".", "-w", "dist"], cwd=pyray_dir, env=env)
        wheels = sorted((pyray_dir / "dist").glob("*.whl"))
        if not wheels:
            raise RuntimeError("No pyray wheel was built")
        run([python_bin, "-m", "pip", "install", "--force-reinstall", *map(str, wheels)])
        verify_installed_pyray(python_bin)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and install a Linux pyray wheel with GLFW null+EGL support")
    parser.add_argument("--python-bin", default=sys.executable, help="Python interpreter whose environment should receive the wheel")
    parser.add_argument("--work-dir", help="Optional directory for temporary build files")
    args = parser.parse_args()
    build_and_install(
        python_bin=args.python_bin,
        work_dir=Path(args.work_dir).resolve() if args.work_dir else None,
    )


if __name__ == "__main__":
    main()
