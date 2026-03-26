# Changelog

Backfilled from git history with an emphasis on major milestones, user-facing changes, and architecture shifts rather than every small commit.

## Unreleased

- BIG UI now auto-detects metric versus imperial units from the earliest downloaded route `rlog` when `IsMetric` is logged, and defaults to imperial when it is missing.
- The 360 renderer now adapts to the route’s actual camera dimensions instead of assuming older fixed sizes, which keeps newer mici routes working.
- Replicate model versions built with the patched Cog runtime continue to accept raw `https://connect.comma.ai/...` URLs on the hosted surface, while stock local `cog predict` still benefits from the patched runtime builder.

## 2026-03-26

- Added the upstream openpilot and Cog modifications inventory so the repo’s external dependencies are documented in one place.
- Added a reproducible patched Cog runtime builder so pushed Replicate model versions can bake in the fixed Cog runtime.
- Patched Cog 0.17 so raw URL-like strings are not coerced into file/path inputs too early during local testing.
- Restored and clarified push behavior so the newest changes can be exercised on Replicate before landing on the main model.
- Cleaned up the Replicate helper so raw route URLs are preserved and easier to debug.
- Added route-driven unit detection for BIG UI renders.
- Clarified the hosted HEVC and Cog URL documentation.
- Restored the URL-only route input copy after the public model surface dropped separate start and length inputs.
- Fixed the newer mici 360 camera dimensions so 360 and 360-forward-upon-wide renders keep working on newer routes.

## 2026-03-25

- Replaced the coarse old UI replay path with a repo-owned exact-frame BIG UI engine.
- Fixed the frame synchronization so lane lines and overlays line up with the logged road camera frames.
- Added a hidden warmup before recording so clips start with initialized UI state instead of a blank opening.
- Kept the metadata overlay visible for the full clip and restored the shell-style wording users preferred.
- Added runtime patching for openpilot UI recording so encoder selection, warmup skipping, and headless behavior are controlled explicitly.
- Accelerated the UI recording path on NVIDIA by using NVENC, and kept a headless EGL/null-platform path for in-container rendering.
- Streamed render progress and final render statistics through the parent process so hosted Replicate logs show real FPS.
- Applied the upstream camera fill fixes for BIG UI.
- Fixed BIG UI timing for newer demo routes.
- Reorganized the clip runtime into `core/` and `renderers/`.
- Refreshed the README for the current clipper workflow.
- Removed the standalone Docker publishing workflow after it stopped being useful for the actual day-to-day flow.
- Removed legacy speedhack controls once the modern exact-frame UI path made them obsolete.

## 2026-03-24

- Added the first URL-driven Replicate helper flow.
- Removed the manual `metric` input from the public model surface during the URL-driven cleanup, before the later route-driven unit autodetect landed.
- Cleaned up the command surface so the current workflow is URL-driven and no longer exposes the old start/length inputs on Replicate.

## Earlier Foundations

- The original working UI clip workflow was built around upstream openpilot replay and a heavier shell-based setup.
- Early README work focused on route selection, smearing, JWT route access, and practical guidance for generating clips from comma Connect.
- The repo grew from a single Cog image path into a broader local-first, hosted, and GCE-based development workflow.
