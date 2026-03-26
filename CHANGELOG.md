# Changelog

Backfilled from git history with an emphasis on major milestones, user-facing changes, and architecture shifts rather than every small commit.

## Unreleased

- BIG UI now auto-detects metric versus imperial units from the earliest downloaded route `rlog` when `IsMetric` is logged, and defaults to imperial when it is missing.
- The 360 renderer now adapts to the route’s actual camera dimensions instead of assuming older fixed sizes, which keeps newer mici routes working.
- Replicate beta continues to accept raw `https://connect.comma.ai/...` URLs on the hosted surface, while stock local `cog predict` still benefits from the patched runtime builder.

## Replicate And Cog

- Added a uv-native hosted runner for Replicate, then replaced the old one-off remote workflow with `replicate_run.py`.
- Removed the manual `metric` input from the public model surface and replaced it with route-driven unit detection.
- Patched Cog 0.17 so raw URL-like strings are not coerced into file/path inputs too early during local testing.
- Added a reproducible patched runtime builder under `cog/runtime_patch` so beta pushes can bake in the fixed Cog runtime.
- Restored and clarified beta push behavior so the newest changes can be exercised on hosted Replicate before landing on the main model.

## BIG UI Rendering

- Replaced the coarse old UI replay path with a repo-owned exact-frame BIG UI engine.
- Fixed the frame synchronization so lane lines and overlays line up with the logged road camera frames.
- Added a hidden warmup before recording so clips start with initialized UI state instead of a blank opening.
- Kept the metadata overlay visible for the full clip and restored the shell-style wording users preferred.
- Added runtime patching for openpilot UI recording so encoder selection, warmup skipping, and headless behavior are controlled explicitly.
- Accelerated the UI recording path on NVIDIA by using NVENC, and kept a headless EGL/null-platform path for in-container rendering.
- Streamed render progress and final render statistics through the parent process so hosted Replicate logs show real FPS.

## Repo Restructure

- Split the repo into `core/` for orchestration and integration, and `renderers/` for actual clip engines.
- Moved the main local entrypoint to `clip.py` and kept the Cog entrypoint in `cog_predictor.py`.
- Removed legacy speedhack controls once the modern exact-frame UI path made them obsolete.
- Cleaned up the command surface so the current workflow is URL-driven and no longer exposes the old start/length inputs on Replicate.
- Removed the standalone Docker publishing workflow after it stopped being useful for the actual day-to-day flow.

## Video Renderers

- Kept the ffmpeg-only renderers for forward, wide, driver, 360, and forward-upon-wide clips.
- Preserved file-size targeting and format selection for H.264 versus HEVC outputs.
- Added 360 metadata injection so spherical clips remain usable in standard tooling.
- Added auto-selection between CPU, VideoToolbox, and NVIDIA acceleration for non-UI ffmpeg renders.
- Adapted 360 and 360-forward-upon-wide rendering to newer mici camera dimensions.

## Compatibility And Cleanup

- Added support for Zstd route logs.
- Modernized the Cog generation path around `uv` and current upstream behavior.
- Made local openpilot checkout/bootstrap flow explicit and reusable across GCE, local, and hosted builds.
- Backed out stale README and workflow references as the repo moved away from shell scripts and old Docker-centric paths.

## Earlier Foundations

- The original working UI clip workflow was built around upstream openpilot replay and a heavier shell-based setup.
- Early README work focused on route selection, smearing, JWT route access, and practical guidance for generating clips from comma Connect.
- The repo grew from a single Cog image path into a broader local-first, hosted, and GCE-based development workflow.
