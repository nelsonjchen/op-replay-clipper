# Upstream Modifications Inventory

This document only tracks things in this repo that modify, patch, rebuild, or
otherwise depend on code that originates outside this repo.

That means:

- openpilot files we patch at runtime
- externally sourced rendering/runtime code we rebuild or carry
- Cog runtime behavior we patch and rebake into pushed Replicate versions

It intentionally does not list repo-owned orchestration or renderer code such
as `renderers/big_ui_engine.py`, `renderers/ui_renderer.py`, or
`renderers/video_renderer.py` unless those files are directly involved in
patching or rebuilding external code.

## 1. openpilot runtime patches

These are the runtime edits that let the repo keep using current upstream
openpilot without carrying a full fork.

| Upstream target | Local files | Why it is modified |
| --- | --- | --- |
| `tools/lib/framereader.py` | [core/openpilot_integration.py](../core/openpilot_integration.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | Keeps framereader behavior compatible with this clip pipeline, including `pipe:0` handling and the hwaccel path used by current rendering. This is the one patch that still uses AST-guided logic. |
| `system/ui/lib/application.py` | [core/openpilot_integration.py](../core/openpilot_integration.py), [renderers/ui_renderer.py](../renderers/ui_renderer.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | Adds recorder hooks for warmup skipping, codec selection, bitrate/tag handling, `RECORD_SKIP_FRAMES`, and the headless null/EGL initialization path used by Replicate. |
| `selfdrive/ui/onroad/augmented_road_view.py` | [core/openpilot_integration.py](../core/openpilot_integration.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | Carries the upstream camera-fill fix so the road view frames correctly on current UI layouts. |
| `selfdrive/ui/mici/onroad/augmented_road_view.py` | [core/openpilot_integration.py](../core/openpilot_integration.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | Same camera-fill fix as above, but for the mici-specific UI path. |

## 2. openpilot-adjacent rendering/runtime rebuilds

These are not openpilot source patches in-place, but they rebuild or adapt
external rendering/runtime components that the clipper depends on.

| External target | Local files | Why it is rebuilt or adapted |
| --- | --- | --- |
| Linux `pyray` / raylib / GLFW stack as packaged for openpilot-style UI use | [common/build_linux_pyray_null_egl.py](../common/build_linux_pyray_null_egl.py), [common/bootstrap_image_env.sh](../common/bootstrap_image_env.sh), [core/render_runtime.py](../core/render_runtime.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | Produces the patched null-platform EGL-backed Linux wheel that gives the Replicate environment real GPU rendering instead of falling back to software `llvmpipe` through `Xtigervnc`. |

## 3. Cog runtime patches

The repo also carries a small Cog 0.17 patch set so Replicate can keep
accepting normal raw route URLs.

Related upstream issue:

- [replicate/cog#2868](https://github.com/issues/created?issue=replicate%7Ccog%7C2868)

| Upstream target | Local files | Why it is modified |
| --- | --- | --- |
| Cog 0.17 input coercion behavior in `coglet` / SDK runtime | [cog/runtime_patch/0001-only-coerce-url-strings-for-file-and-path-inputs.patch](../cog/runtime_patch/0001-only-coerce-url-strings-for-file-and-path-inputs.patch), [cog/runtime_patch/Dockerfile](../cog/runtime_patch/Dockerfile), [cog/runtime_patch/build_wheels.sh](../cog/runtime_patch/build_wheels.sh), [cog/runtime_patch/push_beta.sh](../cog/runtime_patch/push_beta.sh), [cog/runtime_patch/README.md](../cog/runtime_patch/README.md) | Stock Cog 0.17 started coercing raw URL-looking `str` inputs into file/path inputs too early. The patched runtime keeps plain route URLs as strings so Replicate model versions can accept normal `https://connect.comma.ai/...` inputs again. |

## 4. Generated Cog build wiring

These files do not patch Cog itself, but they exist specifically because of
Cog's build/runtime constraints.

| External constraint | Local files | Why it exists |
| --- | --- | --- |
| Cog expects `python_requirements`-style dependency input and does not expose repo files directly to `build.run` | [cog/render_artifacts.sh](../cog/render_artifacts.sh), [cog/render_config.py](../cog/render_config.py), [cog/cog.template.yaml](../cog/cog.template.yaml), [common/bootstrap_image_env.sh](../common/bootstrap_image_env.sh), [cog/README.md](../cog/README.md) | Exports `requirements-cog.txt`, injects the shared bootstrap script into `cog.yaml`, and keeps Replicate image builds reproducible without relying on deprecated or unavailable Cog behaviors. |

Anything else in the repo is repo-owned implementation and belongs in the main
runtime docs, not this external-modifications inventory.
