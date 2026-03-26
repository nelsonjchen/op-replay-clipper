# Runtime Patching And BIG UI Rendering

This project is no longer a thin wrapper around upstream openpilot's clip tool.
The current BIG UI path is a repo-owned renderer with a small openpilot
integration layer around it.

This document explains:

- what we own directly
- what we still patch in upstream openpilot
- why some patches exist at all
- when AST patching is used and why it is the exception
- how the accelerated headless rendering path works on NVIDIA/Cog/Replicate

## Big Picture

The runtime split today looks like this:

- [clip.py](../clip.py)
  Local CLI entrypoint.
- [cog_predictor.py](../cog_predictor.py)
  Cog/Replicate entrypoint.
- [core/clip_orchestrator.py](../core/clip_orchestrator.py)
  Shared request normalization and dispatch.
- [renderers/ui_renderer.py](../renderers/ui_renderer.py)
  App-facing BIG UI renderer orchestration.
- [renderers/big_ui_engine.py](../renderers/big_ui_engine.py)
  Repo-owned exact-frame BIG UI replay/recording engine.
- [core/openpilot_integration.py](../core/openpilot_integration.py)
  Small runtime patch layer over upstream openpilot.
- [core/render_runtime.py](../core/render_runtime.py)
  Headless rendering environment setup.

The important design choice is that the actual clip runner is ours now.
We do not rely on upstream `tools/clip/run.py` for correctness anymore.

## Why We Own The BIG UI Engine

The newer upstream clip path was fast, but it did not line up correctly for this
project's requirements.

The key correctness problem was synchronization:

- route camera frames
- model output
- UI overlays

need to line up exactly.

The old replay-based shell flow happened to match better for some routes because
it was effectively tied to actual replay timing. The newer convenience clip path
was simpler and faster, but it was too loose for clip-for-debugging use.

That is why [renderers/big_ui_engine.py](../renderers/big_ui_engine.py)
exists:

- it builds render steps from logged `modelV2`
- it matches those to `roadEncodeIdx` camera references
- it feeds VIPC using the real logged frame ids and timestamps
- it records as fast as the machine can render, without faketime

So the current architecture is intentionally:

- repo-owned replay/recording core
- upstream UI code reused where practical
- targeted integration patches around the edges

## Patch Inventory

The openpilot integration layer currently handles a small set of targeted
runtime patches.

### 1. Framereader compatibility

File touched upstream:
- `tools/lib/framereader.py`

Why:
- local files and remote/file-like inputs need to work consistently
- we need `pipe:0` handling and ffprobe compatibility for how this project
  stages route assets
- hardware accel env passthrough for ffmpeg decoding needs to be injected in a
  stable way

This is the one patch that still uses AST-guided logic.

### 2. UI recorder behavior

File touched upstream:
- `system/ui/lib/application.py`

Why:
- warmup frames need to be dropped cleanly before the visible clip begins
- encoder selection must be controllable from the environment
- HEVC tag behavior needs to be selectable
- headless null-EGL initialization needs to be injected

This patch is done with anchored source rewriting because the target snippets
are narrow and stable enough.

### 3. Augmented road view fill fix

Files touched upstream:
- `selfdrive/ui/onroad/augmented_road_view.py`
- `selfdrive/ui/mici/onroad/augmented_road_view.py`

Why:
- import of the upstream camera fill fixes from openpilot PR #37673
- better framing for newer routes and device layouts

This is also simple anchored source rewriting.

## Why AST Patching Is Not The Default

AST patching sounds attractive because it feels "robust," but in practice it
comes with real costs:

- harder to read and debug
- easier to accidentally over-generalize
- more mental overhead when upstream changes
- much less obvious to future maintainers

For this project, the current rule should be:

- use direct anchored source rewrites when the target code shape is narrow and
  stable
- use AST only when the patch has to survive meaningful upstream structural
  drift

That is why [core/openpilot_integration.py](../core/openpilot_integration.py)
now treats AST as a special case, not as the pattern to copy everywhere.

Today, only framereader still qualifies.

## The Current Headless Acceleration Story

The final working accelerated path was not obvious.

What did not work well:

- `Xtigervnc`
  This ended up on software `llvmpipe`.
- containerized Xorg
  This was not reliable enough for Cog/Replicate.

What does work:

- a patched Linux raylib/pyray stack
- GLFW null platform
- EGL-backed headless rendering
- NVIDIA rendering in-container
- NVENC for UI recording on NVIDIA hosts

The relevant pieces are:

- [common/build_linux_pyray_null_egl.py](../common/build_linux_pyray_null_egl.py)
  Builds the patched Linux pyray/raylib wheel.
- [common/bootstrap_image_env.sh](../common/bootstrap_image_env.sh)
  Installs that accelerated wheel in image/bootstrap environments.
- [core/render_runtime.py](../core/render_runtime.py)
  Selects the headless runtime environment.
- [renderers/ui_renderer.py](../renderers/ui_renderer.py)
  Chooses the recording encoder and launches the engine.

The result is that hosted Replicate beta can now show real render-loop
throughput around 20 fps instead of the older software-rendered ~8 fps class.

## Why The Parent Renderer Streams Child Logs

The BIG UI engine runs as a child process launched by
[renderers/ui_renderer.py](../renderers/ui_renderer.py).

Replicate/Cog did not consistently surface that child process output when we
just inherited stdio.

That is why the renderer now captures and re-emits child output explicitly:

- the engine prints render progress and final render stats
- the parent process streams those lines back out
- hosted Replicate logs can now show the BIG UI render FPS

Without that extra plumbing, the detailed render timing was often invisible even
when the engine itself was printing it.

## Current Tradeoffs

The current design is intentionally pragmatic.

Good:

- correctness is owned in-repo where it matters
- acceleration works in local Cog, GCE, and hosted beta
- the patch layer is smaller than a full openpilot fork

Not ideal:

- runtime patching still exists and needs upkeep
- image/bootstrap is still more complicated than we would like
- some behaviors still depend on upstream file layout staying recognizable

So the rule of thumb going forward should be:

- own the logic that defines clip correctness or clip performance
- patch upstream only where reusing upstream is still clearly cheaper than
  replacing it

## What To Clean Up Next

If we keep refining this area, the best next steps are:

1. Split [core/openpilot_integration.py](../core/openpilot_integration.py)
   into smaller modules by concern:
   - framereader compatibility
   - UI recorder/runtime patches
   - augmented road view fixes
2. Give each patch an explicit upstream anchor comment or upstream PR reference.
3. Reduce duplication between
   [common/build_linux_pyray_null_egl.py](../common/build_linux_pyray_null_egl.py)
   and the inline bootstrap logic in
   [common/bootstrap_image_env.sh](../common/bootstrap_image_env.sh).
4. Consider replacing the remaining framereader AST patch only if a clearly
   simpler anchored strategy becomes stable across the openpilot revisions we
   care about.

## Short Version

Patching was the right tactic, but it should stay constrained.

The current intended policy is:

- repo-owned BIG UI engine for correctness and performance
- targeted openpilot integration patches for the smallest possible surface
- AST patching only where direct source rewriting would be more fragile

That is a much healthier long-term shape than either:

- forcing everything through upstream clip code, or
- fully forking openpilot just for the clipper.
