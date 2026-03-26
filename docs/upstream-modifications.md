# Upstream Modifications Inventory

This repo is not a pure wrapper around upstream openpilot or Cog. It depends on a
small set of permanent-ish runtime patches, build-time shims, and repo-owned
renderers that keep the clipper working across current openpilot, Cog/Replicate,
and local development environments.

This document is an inventory of those dependencies as they exist now. It is
not a changelog and not a history of everything that was ever tried.

## 1. openpilot runtime patches

These are the modifications that let the repo consume current upstream openpilot
without forking the whole project.

| Area | Local files | Upstream targets | Why it exists |
| --- | --- | --- | --- |
| Framereader compatibility | [core/openpilot_integration.py](../core/openpilot_integration.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | `tools/lib/framereader.py` | Keeps the clip pipeline working across upstream framereader drift, including `pipe:0` handling and the hwaccel path that current clip rendering depends on. |
| UI recording hook | [core/openpilot_integration.py](../core/openpilot_integration.py), [renderers/ui_renderer.py](../renderers/ui_renderer.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | `system/ui/lib/application.py` | Adds warmup skipping, codec selection, bitrate/tag handling, and the `RECORD_SKIP_FRAMES` hook so BIG UI can start after a short preroll instead of recording the blank startup state. |
| Headless UI backend | [core/openpilot_integration.py](../core/openpilot_integration.py), [core/render_runtime.py](../core/render_runtime.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | `system/ui/lib/application.py`, raylib/GLFW platform code as packaged by openpilot | Lets Linux render in a real GPU-backed null/EGL mode instead of falling back to `Xtigervnc`/llvmpipe. This is the big performance unlock for hosted beta. |
| Road-view fill behavior | [core/openpilot_integration.py](../core/openpilot_integration.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | `selfdrive/ui/onroad/augmented_road_view.py` and `selfdrive/ui/mici/onroad/augmented_road_view.py` | Preserves the camera fill fix that keeps the road-view content aligned and avoids the cropped/letterboxed look on current UI variants. |

## 2. BIG UI renderer ownership

The old coarse `tools/clip/run.py` flow is no longer the main implementation.
The repo now owns the actual BIG UI replay/recording engine.

| Area | Local files | Upstream dependency replaced | Why it exists |
| --- | --- | --- | --- |
| Exact-frame replay engine | [renderers/big_ui_engine.py](../renderers/big_ui_engine.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | Previous coarse 20 Hz clip loop in upstream `tools/clip/run.py` | Replays road camera frames and model/UI state in exact frame order so lane lines and path overlays stay aligned. This is the core correctness fix for UI renders. |
| UI orchestration layer | [renderers/ui_renderer.py](../renderers/ui_renderer.py), [core/render_runtime.py](../core/render_runtime.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | The upstream clip runner’s environment/setup behavior | Chooses the headless display strategy, configures the encoder, injects metric/autodetect state, and launches the repo-owned BIG UI engine. |
| Logged metric autodetect | [renderers/ui_renderer.py](../renderers/ui_renderer.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | openpilot `IsMetric` param behavior | Reads the first downloaded `rlog` `initData.params` snapshot and seeds `IsMetric` for the UI subprocess. Defaults to imperial when the key is absent. |

## 3. Non-UI renderers

The non-UI paths are still ffmpeg-based, but they now depend on a few repo-owned
improvements so they work with current routes and newer device layouts.

| Area | Local files | Upstream behavior adjusted | Why it exists |
| --- | --- | --- | --- |
| Video render orchestration | [renderers/video_renderer.py](../renderers/video_renderer.py), [tests/test_clip_orchestrator.py](../tests/test_clip_orchestrator.py) | `ffmpeg` concatenation/cropping paths | Provides the forward, wide, driver, 360, and overlay variants without requiring the old clip script. |
| Dynamic 360 dimensions | [renderers/video_renderer.py](../renderers/video_renderer.py), [tests/test_clip_orchestrator.py](../tests/test_clip_orchestrator.py) | Assumed driver crop sizes in older 360 tooling | Probes the actual wide-camera height from the first segment so newer mici routes with different camera sizes render correctly. |
| Encoder selection | [renderers/video_renderer.py](../renderers/video_renderer.py), [tests/test_clip_orchestrator.py](../tests/test_clip_orchestrator.py) | Single hardcoded software encode path | Picks `nvenc`, `VideoToolbox`, or CPU encoders depending on platform and availability, so local and hosted renders can use acceleration when present. |

## 4. Route parsing and CLI surface

These files are the repo’s user-facing compatibility layer. They keep the public
API small while handling Cog/Replicate quirks internally.

| Area | Local files | Dependency | Why it exists |
| --- | --- | --- | --- |
| Route parsing | [core/route_inputs.py](../core/route_inputs.py), [tests/test_replicate_run.py](../tests/test_replicate_run.py) | Raw `https://connect.comma.ai/...` route URLs | Normalizes route URLs and `literal:`-prefixed URLs, and keeps the public API URL-only. |
| Request normalization | [core/clip_orchestrator.py](../core/clip_orchestrator.py) | Route timing / file-type selection / output sizing | Converts the public request into a render plan and dispatches to either UI or ffmpeg rendering. |
| Local CLI | [clip.py](../clip.py) | Shared orchestrator and route parser | Primary local entrypoint for development and smoke tests. |
| Cog predictor | [cog_predictor.py](../cog_predictor.py), [tests/test_replicate_run.py](../tests/test_replicate_run.py) | Cog/Replicate input schema | Hosted and local Cog entrypoint; documents the current public fields and their rationale. |
| Replicate helper | [replicate_run.py](../replicate_run.py), [tests/test_replicate_run.py](../tests/test_replicate_run.py) | Replicate API payload shape | Lets the repo submit predictable hosted runs while hiding helper-only compatibility details like `literal:` wrapping. |

## 5. Cog and runtime-patch infrastructure

This is the other major piece of upstream dependence. The repo now carries a
small Cog 0.17 runtime patch set so hosted versions keep accepting plain route
URLs again.

| Area | Local files | Upstream dependency | Why it exists |
| --- | --- | --- | --- |
| Patched Cog runtime builder | [cog/runtime_patch/README.md](../cog/runtime_patch/README.md), [cog/runtime_patch/Dockerfile](../cog/runtime_patch/Dockerfile), [cog/runtime_patch/build_wheels.sh](../cog/runtime_patch/build_wheels.sh), [cog/runtime_patch/push_beta.sh](../cog/runtime_patch/push_beta.sh), [cog/runtime_patch/0001-only-coerce-url-strings-for-file-and-path-inputs.patch](../cog/runtime_patch/0001-only-coerce-url-strings-for-file-and-path-inputs.patch) | Cog 0.17 input coercion behavior | Rebuilds patched `cog`/`coglet` wheels so `cog push` on beta produces a runtime that keeps plain `str` route URLs as strings instead of coercing them into file/path inputs. |
| Cog artifact generation | [cog/render_artifacts.sh](../cog/render_artifacts.sh), [cog/render_config.py](../cog/render_config.py), [cog/cog.template.yaml](../cog/cog.template.yaml) | Cog build-time file access limitations | Exports `requirements-cog.txt`, base64-embeds `common/bootstrap_image_env.sh` into `cog.yaml`, and keeps the image bootstrap reproducible. |
| Cog docs | [cog/README.md](../cog/README.md) | The current build/push workflow | Explains why the repo still uses generated Cog artifacts and how the patched runtime builder fits into that flow. |

## 6. Openpilot checkout and local runtime bootstrap

These helpers make local development and hosted pushes behave like the same
runtime, even though the machine classes are different.

| Area | Local files | Upstream dependency | Why it exists |
| --- | --- | --- | --- |
| Openpilot checkout/bootstrap | [core/openpilot_bootstrap.py](../core/openpilot_bootstrap.py), [core/openpilot_config.py](../core/openpilot_config.py) | Current openpilot repo layout and branch selection | Clones/fetches the matching openpilot checkout, syncs dependencies, and keeps the local managed checkout healthy. |
| Shared image bootstrap | [common/bootstrap_image_env.sh](../common/bootstrap_image_env.sh) | Repo files not visible in Cog `build.run` | Provides the shared Linux bootstrap that both Cog and image-style environments consume. |
| Linux pyray / raylib helper | [common/build_linux_pyray_null_egl.py](../common/build_linux_pyray_null_egl.py) | openpilot’s Linux raylib/pyray packaging | Builds the accelerated Linux wheel that enables null/EGL-backed UI rendering in the repo-owned BIG UI path. |
| Render environment selection | [core/render_runtime.py](../core/render_runtime.py), [tests/test_big_ui_engine.py](../tests/test_big_ui_engine.py) | Host graphics stack / Xorg / EGL availability | Chooses between macOS, Linux null/EGL, or Xorg-backed headless rendering and exposes the runtime knobs the UI renderer needs. |

## 7. What to treat as permanent versus temporary

The repo currently has a few layers of patches that are best thought of
separately:

* **Permanent-ish runtime integrations**: exact-frame BIG UI replay, metric autodetect, headless EGL support, and the 360 dimension probing.
* **Compatibility patches that should stay narrow**: the framereader AST patch and the openpilot UI recording hooks.
* **Build/push glue**: Cog artifact generation, patched Cog runtime wheels, and the shared bootstrap script.

If any of those upstream files move again, the first places to re-check are:

* [core/openpilot_integration.py](../core/openpilot_integration.py)
* [renderers/ui_renderer.py](../renderers/ui_renderer.py)
* [renderers/big_ui_engine.py](../renderers/big_ui_engine.py)
* [renderers/video_renderer.py](../renderers/video_renderer.py)
* [cog/runtime_patch/README.md](../cog/runtime_patch/README.md)
