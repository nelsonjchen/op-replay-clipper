# 📽 openpilot Replay Clipper

*Here's a small openpilot bug clip with a small dash of Big Altima Energy*:

https://github.com/commaai/openpilot/assets/5363/97a6c767-9b67-4206-8ba7-b4030f08a8cd

Capture and develop clips of [openpilot][op] from comma.ai's [Comma Connect](https://connect.comma.ai/).

The clipper can produce clips of:

* comma.ai openpilot UI (including desired path, lane lines, modes, etc.)
  * Route metadata is branded into the clip for debugging and reporting, including the route id, platform, git remote, branch, commit, `Dirty` state, and a running route timer. Useful for posting clips in the [comma.ai Discord's #driving-feedback and/or #openpilot-experience channel](https://discord.comma.ai), [reddit](https://www.reddit.com/r/comma_ai), [Facebook](https://www.facebook.com/groups/706398630066928), or anywhere else that takes video. Very useful for [making outstanding bug reports](https://github.com/commaai/openpilot/wiki/FAQ#how-do-i-report-a-bug) as well as feedback on good behavior.
* `ui-alt`, a UI layout variant that reserves a footer below the road view and shows a rotating steering wheel driven by the logged steering angle plus a mici-style confidence rail
* `driver-debug`, a driver camera replay/debug layout
  * Replays the driver camera without the normal mirror effect, draws a coarse driver-face box estimate, and adds a large telemetry footer with driver monitoring state, awareness, distraction, pose/model values, and route/git metadata. Useful for debugging DM behavior and building better DM bug reports.
* Forward, Wide, and Driver Camera with no UI
  * Concatenate, cut, and convert the raw, low-compatibility, and separated HEVC files to one fairly compatible HEVC MP4 or super-compatible H.264 MP4 for easy sharing.
* 360 Video
  * Rendered from Wide and Driver Camera. Uploadable to YouTube, viewable in VLC, loadable in 360 video editing software such as Insta360 Studio or even the Insta360 mobile app, and accepted by any video players or web services that take 360 videos.
* Forward Upon Wide and 360 Forward Upon Wide
  * Forward video is automatically projected onto the wide video using logged camera calibration. Not perfect, but much better aligned than the old manual overlay.
  * 360 Forward Upon Wide scales and renders the final result at a higher resolution to assist in reframing the 360 video to a normal video if that's what you want.

All clip options have a configurable target file size option as platforms like Discord limit file upload sizes.

The clipper is deployed on [Replicate](https://replicate.com):

https://replicate.com/nelsonjchen/op-replay-clipper

Replicate is an ultra-low-cost pay-as-you-go compute platform for running software jobs. Replicate is a great way to run this clipper as it's fast, easy to use, and you don't need to install anything on your computer or even deploy anything yourself. Just enter in the required information into the form, and Replicate will generate a clip. Expect to pay about ~$0.01 per clip but not even need to put in any payment details until you've reached a generously large level of usage.

On Replicate and `cog predict`, the `route` input is now URL-only. The clip timing comes from the `connect.comma.ai` URL itself, so there are no separate `startSeconds` or `lengthSeconds` inputs anymore.

> [!WARNING]
> [comma devices should not be used as primary dashcams for numerous reasons!](https://github.com/commaai/openpilot/wiki/Video-Files#consider-another-device-for-serious-dashcam-purposes)
>
> They are still great as a backup dashcam, openpilot, and for other purposes though.

## Terminology

* Route - A drive recorded by openpilot. Generally from Ignition On to Ignition Off.

## Requirements

- [comma.ai device](https://comma.ai/shop) that can upload to [comma Connect](https://connect.comma.ai).
- [Free GitHub](https://github.com) account to log into [Replicate](https://replicate.com) with

### Non-Requirements

- A comma lite or prime subscription.
   * Clipping was a comma connect prime-only feature but was [removed for refurbishment](https://discord.com/channels/469524606043160576/819046761287909446/1163326961276440616). This is a free and open source tool to do the same.

## Quick Usage

We assume you've already paired your device and have access to the device with your comma connect account.

1. Visit [comma connect][connect] and select a route.
2. Scrub to the time you want to clip.
   * In this example, I've scrubbed to a time where I want to make a small clip of behind this cool car.
   * ![image](https://github.com/nelsonjchen/dutil/assets/5363/b37cba35-5ee1-4980-84bb-697c7306c99a)
3. Now I need to select the portion of the route I want to clip. Here's a video of what that UI looks like
   * See how I drag and select a portion.
   * You can see me make a mistake but pressing the left arrow (←) in the top-left corner lets me re-expand and try to trim again.
   * The clipper has a maximum length of 5 minutes. Try to select a portion that's less than that. Try to aim for 20 seconds to a minute though as everybody else has short attention spans.
   * Video:

     https://github.com/commaai/openpilot/assets/5363/504665de-9222-4e6b-b090-c26cdcc7137a
4. Once satisified with the selected portion, prepare the route and files for rendering.
   * Make sure all files are uploaded. Select "Upload All" under the "Files" dropdown if you haven't already and make sure it says `uploaded`. You may need to wait and your device may need to be on for a while for all files to upload.
      * The clipper only works with high-resolution files and needs all files that are part of the clip to be uploaded.
      * ![image](https://github.com/commaai/openpilot/assets/5363/ce997a7b-9a93-4f67-944b-95d09ae68b02)
   * Make sure the route has "Public access" under "More info" turned on. You can set this to off after you're done with clip making.
      * ![image](https://github.com/commaai/openpilot/assets/5363/6a55c181-d93f-4db5-9513-ff6a1d370757)
5. Copy the URL in the address bar of your browser to your clipboard. This is not the segment ID underneath the More Info button. In the case above, I've copied an old URL of "https://connect.comma.ai/fe18f736cb0d7813/1698203405863/1698203460702" to my clipboard. 
   * **Note**: comma has changed the URL format since this step/guide was originally written. Current URLs are like "https://connect.comma.ai/fe18f736cb0d7813/000001bb--4c0c0efba9/21/90". It has a dongle ID, a new route designator format, and the time is relative to the route itself.
   * When you were adjusting the selected portion of the route in a previous step, it was changing those last two numbers in the browser address bar URL which is the start time and end time respectively.
   * "Share This Route" button if it is present will work too. Choose "copy to clipboard" or similar.
6. Visit https://replicate.com/nelsonjchen/op-replay-clipper
7. Under `route`, paste the URL you copied in the previous step.
   * ![image](https://github.com/commaai/openpilot/assets/5363/15d286cc-057f-4a1c-be82-855c5b570b90)
8. Tweak any settings you like.
9. Press `Run`.
10. Wait for the clip to render. It may take a few minutes.
11. Once done, you can download the clip. If you want, turn off "Public access" on the route after you're done.
    * Here's a generated clip with the `wide` rendering type with no UI:

      https://github.com/commaai/openpilot/assets/5363/8bd91642-51ff-4de9-87d2-31e770c64542
    * If you have issues downloading the clip with the "Download" button in Replicate's UI, click on the vertical ellipsis button or whatever is available in your browser for video in the lower right corner of the video and download via that. This is a [strange issue](https://github.com/nelsonjchen/op-replay-clipper/issues/77) in Replicate's UI that this clipper can't do anything about.
    * You can reupload this file onto Discord. Be aware of Discord's file size limits. Discord Free users should target 9MB file sizes for rendering to slip in under the 10MB limit.
   
### UI Renders and Smearing

UI rendering works by actually running the openpilot UI on the remote server, feeding it recorded route data, and then recording the rendered output.

Unfortunately, there's sometimes some state tracked in the openpilot UI. Past data may be needed to be sent to get the UI to the correct state at the beginning of the clip. We need to smear the start.

Lack of or insufficient smearing can cause:

* No lead car marker (for openpilot longitudinal)
* Desire path coloring being green when openpilot actually had the gas suppressed in gating.

Those can be important information in describing what has happened.

One way to describe this issue would be like on a movie set. Let's say you are a director and you want to have a shot where the actor is already running. You would say "lights", roll the "camera", and then say "ACTION!". In post, the editor would not include the clapboard, the director yelling "ACTION!" or the actor starting to run. They would splice the film when the actor is already running in stride. 

The smear point is when the clipper does some cutting after "ACTION!". It's the amount of seconds before the clip is to start. The clipper "production crew" aims starts recording immediately (CAMERA) once the data has started to be sent (LIGHTS) but a later "editor" will cut the intermediate clip some "smear" seconds later as the actual beginning and return that to you.

**Due to this, you may need to upload an additional minute of video and data before the current start point for UI renders.** You may need to adjust the quick usage steps above accordingly by selecting a minute before your desired start point and uploading the data, if you get segments not uploaded errors.

## Gallery

Demonstration of speed or longitudinal behavior of openpilot with model-based longitudinal is nearly impossible or hard without this clipper. This video is of a good model based long behavior at highway speeds.

https://user-images.githubusercontent.com/5363/202886008-82cfbf02-d19a-4482-ab7a-59f96c802dd1.mp4

Cars can have bugs themselves. Here's my 2020 Corolla Hatchback phantomly braking on metal strips in stop and go traffic probably from the radar. Perhaps a future openpilot that doesn't depend on radar might be the one sanity checking the radar instead of the other way around currently. And another example of that in Portland.

https://user-images.githubusercontent.com/5363/219708673-4673f4ff-9b47-4c57-9be3-65f3ea703f3f.mp4

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/1e59844b-46f8-4289-bea9-511db2718549

This is a video of a bug report where openpilot's lateral handling lost the lane.

https://user-images.githubusercontent.com/5363/205901777-53fd18f9-2ab5-400b-92f5-45daf3a34fbd.mp4

Lane cutting?

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/d0ab3365-b5ef-4e05-84ee-370b88e8af02

Nav-assisted follow the road instead of taking the side road.

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/8f970c76-21d1-4209-b0e1-3eb6989feea8

Copying the car in front to get around someone waiting for the left turn

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/9f845b8d-e4aa-4ab3-8785-8d09b83c9d8b

Search up the readme for 360 stuff! It's pretty cool.

https://github.com/user-attachments/assets/deea7b78-61ee-43be-8a29-38319114c083

## Limitations

- The UI replayed is comma.ai's latest stock UI on their master branch; routes from forks that differ alot from stock may not render correctly. Your experience may and will vary. Please make sure to note these replays are from fork data and may not be representative of the stock behavior. [The comma team really does not like it if you ask them to debug fork code as "it just takes too much time to be sidetracked by hidden and unclear changes"](https://discord.com/channels/469524606043160576/616456819027607567/1042263657851142194).

## Usage Tips

### Bookmark/Preserve

Learn how to bookmark, preserve, and flag interesting points on a drive/route.

[Preservation saves the last couple segments from being deleted on your device as well.](https://github.com/commaai/openpilot/blob/d43bf899786bb752fc13818c6a4f8d4a7669ab37/system/loggerd/deleter.py#L28)

With the car on, **within a minute** after an incident when it is safe to do so:

1. Tap the screen to reveal a bookmark flag button in the bottom left if it isn't there already.
   * ![button_flag](https://github.com/nelsonjchen/op-replay-clipper/assets/5363/d0cf9372-78ad-4a06-9128-b6fdb6f5394c)
2. Tap that icon.
3. This will result in small slivers of yellow in the timeline you can quickly hone in on.
   * ![flagged](https://github.com/nelsonjchen/op-replay-clipper/assets/5363/15a3f611-ffb8-47de-b917-1988a0f6f66a)
4. You should also set the route to preserve under More Info while you're working on it. Non-comma Prime users need to heed this especially since while files aren't deleted *on* the device, visiblity in and through comma connect sunsets after 3 days.
5. With regards to the clipper usage, during the process in which you are honing in on the start and end boundaries of the clip, your upper bound of the clip will nearly all the time be at that yellow so your first or early drags to hone down should basically top out there and be very generous with the start time before the yellow.

> [!TIP]
> If you find it a hassle to reach out and touch the device or it is too inconvenient, try installing a custom macropad like the [🦾 comma three Faux-Touch keyboard](https://github.com/nelsonjchen/c3-faux-touch-keyboard/)!
>
> ![touchkey keyboard demo](https://github.com/nelsonjchen/c3-touchkey-keyboard/assets/5363/d9617916-2442-4287-b430-709dad173da8)



## Advanced Usage

### Local-first development workflow

Use `clip.py` as the primary local entrypoint for cheap validation on macOS or Linux before paying for GCE runs.

Repo layout:

* repo root: user-facing entrypoints such as `clip.py`, `cog_predictor.py`, and `replicate_run.py`
* `core/`: shared runtime modules for orchestration, route inputs, downloading, integration, and bootstrap
* `renderers/`: UI and video renderer implementations
* `cog/` and `common/`: build/bootstrap helpers for Cog and image setup

BIG UI is the supported UI target.

If you want the detailed background on the repo-owned BIG UI engine, runtime
patches, and the headless acceleration path, see
[docs/runtime-patching-and-ui-rendering.md](docs/runtime-patching-and-ui-rendering.md).
If you want the inventory of upstream/openpilot/Cog modifications that this
repo currently depends on, see
[docs/upstream-modifications.md](docs/upstream-modifications.md). For a
milestone-oriented history of how the project got here, see
[CHANGELOG.md](CHANGELOG.md).
For a concrete pre-promotion smoke checklist, see
[docs/prod-readiness-checklist.md](docs/prod-readiness-checklist.md).

Examples:

```bash
uv sync
uv run python clip.py ui "https://connect.comma.ai/<dongle>/<route>/<start>/<end>"
uv run python clip.py ui-alt "https://connect.comma.ai/<dongle>/<route>/<start>/<end>"
uv run python clip.py driver-debug "https://connect.comma.ai/<dongle>/<route>/<start>/<end>"
uv run python clip.py forward "a2a0ccea32023010|2023-07-27--13-01-19" --demo
```

Driver backing-video face anonymization:

```bash
uv run python clip.py driver --demo --length-seconds 20 \
  --driver-face-anonymization facefusion \
  --driver-face-profile driver_face_swap_passenger_hidden \
  --passenger-redaction-style blur \
  --driver-face-source-image ./assets/driver-face-donors/generic-donor-clean-shaven.jpg \
  --driver-face-preset fast \
  --output ./shared/driver-facefusion.mp4

uv run python clip.py driver --demo --length-seconds 20 \
  --driver-face-anonymization facefusion \
  --driver-face-profile driver_face_swap_passenger_hidden \
  --passenger-redaction-style silhouette \
  --driver-face-selection auto_best_match \
  --driver-face-donor-bank-dir ./assets/driver-face-donors \
  --driver-face-preset fast \
  --output ./shared/driver-facefusion-silhouette.mp4

uv run python clip.py driver-debug --demo --length-seconds 20 \
  --driver-face-anonymization facefusion \
  --driver-face-profile driver_unchanged_passenger_hidden \
  --passenger-redaction-style blur \
  --driver-face-source-image ./assets/driver-face-donors/generic-donor-clean-shaven.jpg \
  --driver-face-preset fast \
  --output ./shared/driver-debug-facefusion.mp4

uv run python clip.py 360 --demo --length-seconds 20 \
  --driver-face-anonymization facefusion \
  --driver-face-profile driver_face_swap_passenger_hidden \
  --passenger-redaction-style blur \
  --driver-face-selection auto_best_match \
  --driver-face-donor-bank-dir ./assets/driver-face-donors \
  --driver-face-preset fast \
  --output ./shared/driver-360-facefusion.mp4
```

Tiny RF-DETR-only repro:

```bash
uv sync
./scripts/smoke_rf_detr_repro.sh --backend local-cli
./scripts/smoke_rf_detr_repro.sh --backend local-cog

./cog/render_artifacts.sh
cog push --file cog-rfdetr-repro.yaml r8.im/nelsonjchen/op-replay-clipper-rfdetr-repro-beta
uv run python rf_detr_repro_run.py \
  --model 'nelsonjchen/op-replay-clipper-rfdetr-repro-beta:<version>' \
  --input ./shared/rf-detr-repro-inputs/tiny-clip.mp4 \
  --output ./shared/rf-detr-repro-hosted-artifacts.zip
```

The bundled donor bank lives in [`assets/driver-face-donors`](assets/driver-face-donors). It currently keeps full light/medium/dark tone coverage for masculine donors, while the active feminine bank is intentionally limited to younger light/medium donors plus a feminine clean-shaven fallback, with additional masculine glasses/beard variants. To regenerate the checked-in bank with Runware FLUX Kontext, use:

```bash
export RUNWARE_API_KEY=...
./.cache/facefusion/.venv/bin/python tools/generate_driver_face_donor_bank.py --skip-existing
```

BIG UI smoke test:

```bash
uv run python clip.py ui --demo --qcam --length-seconds 2 --output ./shared/demo-big-ui-clip.mp4
```

Exact-sync BIG UI smoke test:

```bash
make ui-exact-smoke
```

Driver debug smoke test:

```bash
uv run python clip.py driver-debug --demo --length-seconds 2 --output ./shared/demo-driver-debug-clip.mp4
```

`driver-debug` is the DM-focused openpilot render. It replays the driver camera through openpilot's driver camera dialog, keeps the camera unmirrored, draws the repo-owned face box estimate, and renders a footer with awareness, distraction, model timing, pose, and route/build metadata.

Notes:

* `clip.py` is the primary local CLI for UI and non-UI renders
* `driver-debug` is an openpilot-backed render type like `ui` and `ui-alt`, but it only needs `dcameras` and `logs`
* `driver`, `driver-debug`, `360`, and `360_forward_upon_wide` can optionally anonymize the backing driver video with `--driver-face-anonymization facefusion`
* `--driver-face-profile` controls who is swapped versus hidden: `driver_unchanged_passenger_hidden`, `driver_unchanged_passenger_face_swap`, `driver_face_swap_passenger_hidden`, and `driver_face_swap_passenger_face_swap`
* `--passenger-redaction-style` controls how hidden passengers are rendered and currently supports `blur` and `silhouette`
* Old `...passenger_pixelize` profile slugs are still accepted as compatibility aliases, but they now map to hidden-passenger + `blur`
* That anonymization path reuses the repo-owned DM face track, uses FaceFusion for swapped seats, and uses the shared RF-DETR full-body redaction path for hidden passengers before the final driver-video render
* Every anonymized output now burns a bright mode-specific banner into the driver video, for example `PASSENGER BLURRED`, `PASSENGER SILHOUETTED`, or `DRIVER SWAPPED, PASSENGER BLURRED`, so viewers can tell what was actually changed
* `--driver-face-preset fast` is the practical default for short clips, while `quality` trades more time for cleaner masking and higher-resolution swapping
* `--driver-face-selection auto_best_match` runs a short same-tone donor search against the donor bank, writes a `<output>.driver-face-selection.json` sidecar report, then uses the selected donor for the final swap
* Driver-backed anonymization also needs `logs`, because the face crop is driven by driver-monitoring telemetry rather than a fresh detector pass
* `driver-debug` uses the same hidden preroll/cut behavior as the UI renderers so the visible clip starts after the DM state has initialized
* BIG UI renders now use a repo-owned exact-frame runner instead of the old coarse 20 Hz chunk mapping, so lane lines and path overlays stay aligned to the logged road camera frames
* The BIG UI renderer also does a hidden 1-second warmup before recording so the visible clip starts with initialized video/UI state instead of a blank opening
* BIG UI units are auto-detected from the route's logged `IsMetric` param when present, and otherwise default to imperial
* `pyproject.toml` declares compatible dependency ranges and `uv.lock` pins the exact resolved environment
* `uv sync` bootstraps the local Python environment used by the local CLI
* On macOS it prefers a local acceleration policy for ffmpeg-based renders where available
* It clones/updates `openpilot` into `./.cache/openpilot-local` for openpilot-backed renders such as `ui`, `ui-alt`, and `driver-debug`
* `--openpilot-repo-url` lets you point local bootstrap at an SSH remote if you want to reuse Git agent forwarding or a closer mirror
* It runs `uv sync --frozen --all-extras` and builds the native modules needed by the repo-owned BIG UI exact-frame runner
* On macOS it applies the same `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` workaround used by upstream `tools/install_python_dependencies.sh`
* `uv run pytest` runs the local refactor tests
* `./cog/render_artifacts.sh` exports `requirements-cog.txt` from `uv.lock` for Cog, so the local and Cog dependency sets stay aligned
* `cog.yaml` and `requirements-cog.txt` are generated artifacts and are intentionally not committed

### Driver Face Evaluation Harness

Use `driver_face_eval.py` for local-only benchmark prep when you want clean
`driver` clips plus a DM-guided face-track crop for trying anonymization or
face-replacement approaches against real comma driver-camera footage.

The built-in seed set currently materializes:

* `mici-baseline`
* `tici-baseline`
* `tici-occlusion`

Outputs for each sample land under `./shared/driver-face-eval/<sample-id>/`:

* `driver-source.mp4` - clean full-frame driver clip
* `face-crop.mp4` - square DM-guided crop clip resized for model input
* `face-track.json` - per-frame ROI sidecar with telemetry and crop geometry
* `evaluation.md` - scoring template for candidate methods
* `driver-debug-analysis.mp4` - optional debug/analysis render

Materialize the default seed set:

```bash
uv run python driver_face_eval.py seed-set
```

Include a `driver-debug` analysis clip for the same samples:

```bash
uv run python driver_face_eval.py seed-set --include-driver-debug
```

Materialize one custom sample:

```bash
uv run python driver_face_eval.py sample my-sample \
  'https://connect.comma.ai/<dongle>/<route>/<start>/<end>' \
  --start-seconds 90 \
  --length-seconds 2
```

### Hosted Replicate runs with uv

You can also run the hosted Replicate model from this repo with the Python client and a local `.env`.

1. Put your API token in `.env`:

```bash
REPLICATE_API_TOKEN=...
```

2. Sync the uv environment:

```bash
uv sync
```

3. Run a hosted prediction and save the returned file locally:

```bash
uv run python replicate_run.py \
  --url 'https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496' \
  --render-type driver-debug \
  --output ./shared/replicate-run-driver-debug.mp4
```

Notes:

* `replicate_run.py` uses the hosted Replicate model version, not a local Cog/container run
* pass `--model <owner>/<model>:<version>` to target a specific hosted Replicate model version during smoke tests
* the script loads `REPLICATE_API_TOKEN` from `.env` via `python-dotenv`
* it prints the remote file URL when Replicate returns one, then writes the file to the path you passed with `--output`
* the hosted helper now takes a full `connect.comma.ai` clip URL and does not expose separate `start-seconds` or `length-seconds` flags
* `.env` is ignored by git; `.env.example` is the committed placeholder

### Cog 0.17.2 route input behavior

This repo now assumes stock `cog 0.17.2+` for Replicate deploys.

Upstream Cog fixed the earlier raw-URL coercion regression for plain `str`
inputs, so hosted model versions can once again accept normal
`https://connect.comma.ai/...` route URLs without a custom patched runtime.

The local parser still accepts `literal:https://...` as a backwards-compatible
input form, but it is no longer the recommended deploy or smoke-test path.

For the full current deploy flow, including staging pushes, production pushes,
and post-promotion verification, see
[docs/deploying-to-replicate.md](docs/deploying-to-replicate.md).

### JWT Token Input

There is a JWT Token input field.
This is for users who do not wish to set a route to be "Public access".
There is a major catch though.
The JWT Token is valid for 90 days and is irrevocable in any way.
Password changes from SSO account logins like in Comma Connect will not invalidate the token.
Addtionally, it is not granular, meaning it will give access to all routes for the user if leaked.

If you share a JWT Token with anyone, they will be able to access all your routes for 90 days with no possibility of revocation from you.
This is why it's not recommended to use this feature unless you know what you're doing compared to the "Public access" method which is much easier to revoke access to.

Tokens can be obtained from visiting https://jwt.comma.ai/ and logging in with the same comma connect account type. Tokens should be about 181 characters or longer.

### Replicate can queue up jobs to run in parallel

After you run something, just use your browser to "Duplicate" the tab, change the settings for the next thing, and press Run. Replicate will queue up jobs and if necessary, even scale up to run multiple jobs in parallel. Very cool!

### Reframing 360 and 360 Forward Upon Wide to a normal video

360 videos are cool but sometimes you want a normal video pointing at a specific direction or directions from that data.

https://github.com/user-attachments/assets/08b51cee-f357-4afc-87f2-4c4d0f6aedba

With 360 videos, it is possible to reframe the 360 video so it is a non-360 video to a normal video pointing at a specific direction.

The best current way to do this is to use a 360 video editor like [Insta360 Studio](https://www.insta360.com/download/insta360-onex) to reframe the video to a normal video. Simply load the 360 video into the editor and reframe the video to the desired direction. A more through description of this functionality can be [found at their site](https://www.insta360.com/blog/tips/how-to-edit-and-reframe-360.html).

![insta360](https://github.com/nelsonjchen/op-replay-clipper/assets/5363/dece938d-e575-48f7-b64e-659464800bc7)

The Insta360 mobile apps also allow using the phone's movement and swipes for a more natural reframing as well. That is also described at [their site](https://www.insta360.com/blog/tips/how-to-edit-and-reframe-360.html)

https://github.com/user-attachments/assets/deea7b78-61ee-43be-8a29-38319114c083

There may be alternative software that'll do it and I will take pull requests to add them to this README, but this is the best way I know how to do it and it is free.

The 360 Forward Upon Wide rendering option scales input videos and renders the final result in a much higher 8K resolution to assist reframing with a high resolution forward video. The normal 360 option just glues the videos together. 

If wanting to use 360 Forward Upon Wide, test with the non-360 Forward Upon Wide option first so you can quickly sanity-check the route's automatic camera alignment before paying for the larger 360 output.

## Credits

### UI

The real MVP is [@deanlee](https://github.com/deanlee) for the replay tool in the openpilot project. The level of effort to develop the replay tool is far beyond this project. This tool builds on that replay work to make clipping videos practical.

https://github.com/commaai/openpilot/blame/master/tools/replay/main.cc

### Video-only

A lot of the FFmpeg commands is based off of [@ntegan1](https://github.com/ntegan1)'s research and documentation including a small disclosure of some but not all details by [@incognitojam](https://github.com/incognitojam) when [@incognitojam](https://github.com/incognitojam) was at comma.

https://discord.com/channels/469524606043160576/819046761287909446/1068406169317675078

[@morrislee](https://github.com/morrislee) provided original data suitable to try to reverse engineer 360 clips.

[do]: https://www.digitalocean.com/
[op]: https://github.com/commaai/openpilot
[ghcs]: https://github.com/features/codespaces
[replicate]: https://replicate.com/nelsonjchen/op-replay-clipper
[connect]: https://connect.comma.ai/
