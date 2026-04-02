# Changelog

All notable changes to this project are documented in this file.

This repository does not currently publish versioned release tags, so the older history below is backfilled from shipped git history and grouped into date-based milestones instead. There is no `Unreleased` section at the moment because the current project state is considered released.

## 2026-03-27

- Removed: Dropped the repo-local patched Cog runtime builder after confirming upstream Cog `0.17.1` fixes the raw URL coercion regression for this project.
- Removed: Stopped accepting the legacy `literal:` URL wrapper in route validation and local helper paths.
- Changed: Simplified local and Replicate deployment docs back down to the stock `cog push` and raw `https://connect.comma.ai/...` flow.

## 2026-03-26

- Added: Documented the upstream openpilot and Cog modifications that the project depends on.
- Added: Introduced a reproducible patched Cog runtime builder for Replicate releases.
- Fixed: Patched Cog 0.17 URL coercion behavior so raw route URLs survive local testing more reliably.
- Changed: Cleaned up the Replicate helper and hosted route-input flow so raw `connect.comma.ai` URLs are preserved, easier to debug, and safer to pass through the public model surface.
- Added: Introduced route-driven metric versus imperial autodetection for BIG UI renders.
- Fixed: Corrected newer mici 360 camera dimensions so 360 and 360-forward-upon-wide renders keep working on newer routes.
- Changed: Tightened predictor field descriptions and added a production-readiness checklist plus supporting docs.

## 2026-03-25

- Added: Replaced the older coarse UI replay path with a repo-owned exact-frame BIG UI engine.
- Fixed: Corrected BIG UI frame synchronization so lane lines and overlays align with logged camera frames.
- Added: Introduced hidden BIG UI warmup so clips start with initialized UI state instead of blank opening frames.
- Changed: Kept metadata overlays visible for the full clip and restored the shell-style labels users preferred.
- Added: Introduced explicit runtime patching for openpilot UI recording so warmup, headless behavior, and encoder selection are controlled by the repo.
- Changed: Accelerated UI recording on NVIDIA with NVENC plus headless EGL/null-platform rendering paths.
- Added: Streamed BIG UI engine logs and final render stats through the parent process so hosted logs are more useful.
- Fixed: Applied upstream camera-fill fixes and timing fixes for newer demo routes.
- Changed: Reorganized the clip runtime into `core/` and `renderers/`, refreshed the README, and removed an outdated Docker publish workflow.

## 2026-03-24

- Added: Introduced the first URL-driven Replicate helper flow and a `uv`-native remote runner.
- Changed: Simplified the public model surface around URL-driven inputs instead of separate start/length-style fields.
- Changed: Removed the old manual `metric` input after moving the workflow toward route-driven behavior.
- Changed: Removed legacy UI speedhack controls that no longer fit the modern rendering path.

## 2026-03-23

- Changed: Modernized Cog generation around `uv` and current upstream behavior.
- Changed: Refactored the clip pipeline for `uv`-native local testing and more portable Cog config generation.
- Changed: Unified openpilot defaults and GCE checkout/bootstrap behavior.
- Changed: Removed legacy clip entrypoints and flags in favor of the newer Python-based runtime shape.
- Fixed: Cleaned up build contexts, dependency locking, and general repository metadata/tooling.

## 2026-02-23

- Added: Introduced a modern local openpilot UI clip workflow with repo-owned compatibility patches and font/runtime fixes.
- Changed: Refactored UI clip rendering behind Python backends and modernized the container bootstrap.
- Fixed: Improved headless modern Cog clip rendering on GCE and local warmup/runtime selection.

## 2025-05-10

- Changed: Lowered the default target clip size to 9 MB so free-tier Discord uploads fit more reliably.
- Changed: Relaxed file-size validation so renders can target as little as 5 MB.
- Changed: Cleaned up shared-memory handling in the clipping pipeline and refreshed local development/Cog config bumps.
- Changed: Refreshed README guidance around UI rendering and smearing behavior.

## 2024-12-22

- Fixed: Corrected route parsing when the second route identifier component is fully numeric.
- Fixed: Tightened video validation so invalid or incomplete video inputs fail more predictably.

## 2024-10-04

- Changed: Rebalanced codec defaults after HEVC compatibility feedback; H.264 became the safer default again.
- Changed: Introduced `auto` as the default file-format mode so the clipper can choose a better codec without forcing users to decide up front.
- Changed: Refined related input copy and format-selection behavior in the prediction interface.

## 2024-08-08

- Added: Introduced Zstandard handling in the downloader/setup flow to keep up with newer upstream artifacts.
- Changed: Refreshed the built-in docs and UI copy.

## 2024-07-10

- Changed: Refreshed the project to work with newer upstream/openpilot layouts and newer build inputs.
- Changed: Removed older shared-memory hacks that were no longer needed by the current pipeline.
- Changed: Surfaced route time more prominently in rendered output.
- Added: Introduced explicit H.264 versus HEVC output selection in the Replicate flow.
- Fixed: Added `faststart` MP4 handling and HEVC tagging fixes for better playback on Apple devices.
- Changed: Improved 360 Forward Upon Wide quality to make reframing and cropping more usable.
- Changed: Temporarily moved defaults toward HEVC as sharing-platform support improved.
- Changed: Expanded README guidance for JWT token handling, 360 reframing, and usage caveats.

## 2024-06-23

- Fixed: Updated route parsing to handle newer comma Connect route formats and newer timestamp fields.
- Fixed: Patched the downloader for newer comma API behavior.
- Fixed: Added Replicate-side workarounds for newer prediction URL behavior.
- Changed: Updated setup/build dependencies required by the newer route and downloader flows.

## 2023-12-16

- Added: Added direct H.264/HEVC selection to the standalone `clip.sh` flow.
- Fixed: Restored compatibility with upstream openpilot changes where the wrapper script disappeared.
- Fixed: Corrected UI command paths and mount handling in containerized development setups.

## 2023-11-19

- Added: Added JWT-authenticated route access for users who do not want to enable public route sharing.
- Added: Added Forward Upon Wide rendering.
- Changed: Tuned file-size behavior to stay closer to requested limits and relaxed smear defaults where possible.
- Fixed: Enabled NVIDIA hardware rendering conditionally under WSL2 instead of assuming it is always available.
- Changed: Improved non-public-route errors and user-facing copy around JWT usage and defaults.

## 2023-11-04

- Added: Shipped a standalone FFmpeg-based clipper path alongside the UI replay flow.
- Added: Added driver-camera output, working 360 rendering, and the first usable 360-forward compositions.
- Added: Added direct comma Connect URL input support and route-aware parsing via `route_or_url.py`.
- Changed: Partitioned working data by route ID to avoid collisions between jobs.
- Changed: Improved Chrome playback smoothness, reduced high-quality 360 jitter, and tightened default file-size limits.
- Fixed: Improved error handling for non-public routes and other invalid input states.

## 2023-09-24

- Added: Ported the project to Cog/Replicate with `predict.py` so the clipper could run as a hosted prediction service.
- Added: Added a dedicated downloader, notes field, file-size slider, metric toggle, optional workspace support, and a safety timeout.
- Added: Added initial GPU/NVIDIA direct-encoding and capture options plus early 3D/360 rendering groundwork.
- Changed: Greatly improved download speed, tuned defaults to reduce stutter, capped FPS, and improved hybrid encoding behavior.
- Changed: Reworked container/dev setup around Cog and shared build/setup scripts.

## 2023-01-24

- Changed: Retired the earlier experimental UI-rendering mode as the standard pipeline became the default path.
- Added: Added NVIDIA direct encoding options and higher-quality direct-capture settings.
- Changed: Switched overlay text rendering to FFmpeg `drawtext`, simplifying the stack and reducing extra helper tooling.
- Fixed: Improved overlay alignment and tmux/process cleanup so reruns behaved more consistently.
- Changed: Removed metadata tooling and waits that were no longer needed after later pipeline cleanups.

## 2022-12-11

- Added: Added `ntfy.sh` notifications for finished clips.
- Changed: Reworked route-info fetching and container defaults for a smoother Codespaces/devcontainer workflow.
- Changed: Disabled VNC by default, defaulted the file-size target to 50 MB, and improved output naming.
- Added: Embedded and burned more clip metadata into MP4 outputs.
- Changed: Switched clip labeling toward segment-based identifiers instead of route-only labeling.
- Added: Added metric-system support, overlay re-alignment, and an alternate web server option.

## 2022-10-29

- Added: Added configurable clip length, target file size, and output file naming.
- Changed: Added smear auto-calculation, then continued tuning smear defaults and exposed smear as a real option.
- Added: Added a slow-CPU mode and adjusted timing/predownload behavior to deal with newer extra camera streams.

## 2022-09-24

- Added: Shipped the first usable route clipper and demo route clipping flow.
- Added: Added JWT token input, overlay rendering, more clip controls, and bitrate targeting.
- Changed: Moved the CLI toward positional arguments and shorter options, parameterized recording length, and added `e2e_long` as a selectable rendering mode.
- Fixed: Improved route parsing, ordering, cleanup before transcoding, and compatibility-oriented output settings.

## 2022-08-23

- Added: Bootstrapped the project with the first Docker/devcontainer-based replay environment.
- Added: Added early VNC, tmux, logging, shared-folder, and faketime/retrace experimentation needed to make remote replay feasible.
- Changed: Tuned shared-memory, CPU, and local development setup to fit constrained cloud/container environments.
