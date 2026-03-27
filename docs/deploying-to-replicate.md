# Deploying To Replicate

This document describes how this repo is currently deployed to Replicate.

It covers:

- staging pushes to `nelsonjchen/op-replay-clipper-beta`
- production pushes to `nelsonjchen/op-replay-clipper`
- local testing before a push
- why deploys use a patched Cog runtime
- how to verify a pushed version before and after promotion

## Overview

This repo does not deploy with a plain stock `cog push`.

The deploy path depends on:

1. generated Cog build artifacts from [`cog/render_artifacts.sh`](../cog/render_artifacts.sh)
2. a patched Cog 0.17 runtime built under [`cog/runtime_patch/`](../cog/runtime_patch)
3. a normal `cog push` that injects those patched runtime wheels into the image build

That patched runtime matters because stock Cog 0.17 regressed plain
`https://connect.comma.ai/...` string handling for this project's
`route: str` input.

Without the patched runtime, hosted Replicate can coerce route URLs into file
inputs too early and break the model's public URL-only API.

## Models

The two Replicate targets are:

- staging: `r8.im/nelsonjchen/op-replay-clipper-beta`
- production: `r8.im/nelsonjchen/op-replay-clipper`

The intended workflow is:

1. push current work to the staging model
2. run the staging smoke matrix
3. if staging looks good, push the same repo state to the production model
4. run a smaller post-promotion smoke set on production

## Prerequisites

Before deploying:

- have a valid `REPLICATE_API_TOKEN`
- have Docker working locally
- have a working `cog` CLI installed
- be on the repo state you actually want to push

Common setup:

```bash
uv sync
set -a
source .env
set +a
```

## Local testing before a push

The cheapest and fastest validation path is still local-first:

1. run the local Python/uv path
2. optionally run local `cog predict`
3. use GCE when you want Linux/NVIDIA behavior without paying the Replicate
   startup tax
4. push to the staging Replicate model only after that looks good

### Local Python path

For most behavior checks, use the repo CLI directly:

```bash
uv sync
uv run python clip.py ui 'https://connect.comma.ai/<dongle>/<route>/<start>/<end>'
```

For hosted-model testing from your machine without building a local container:

```bash
uv run python replicate_run.py \
  --model 'nelsonjchen/op-replay-clipper-beta:<version>' \
  --url 'https://connect.comma.ai/<dongle>/<route>/<start>/<end>' \
  --render-type ui \
  --output ./shared/local-hosted-smoke.mp4
```

### Local `cog predict`

If you want to exercise the local Cog/container path:

```bash
./cog/render_artifacts.sh
cog predict -i renderType=ui -i route='literal:https://connect.comma.ai/<dongle>/<route>/<start>/<end>'
```

Notes:

- stock local Cog 0.17 may still need the `literal:` prefix if you are not
  using the patched runtime wheels locally
- the hosted Replicate model should not need `literal:` once it has been pushed
  with the patched runtime
- local `cog predict` is useful for image/runtime validation, but the hosted
  Replicate smokes are still the source of truth before promotion

### GCE testing

GCE is the best middle ground when you want:

- Linux behavior
- NVIDIA rendering/encoding behavior
- faster iteration than repeated Replicate cold starts

The typical GCE flow is:

1. create or start a GPU VM
2. sync the repo there
3. run the local CLI or local `cog predict`
4. copy the output artifact back
5. stop the VM when you are done

Host-side local CLI example on the VM:

```bash
uv sync
uv run python clip.py ui 'https://connect.comma.ai/<dongle>/<route>/<start>/<end>'
```

Hosted-model smoke from the VM:

```bash
uv run python replicate_run.py \
  --model 'nelsonjchen/op-replay-clipper-beta:<version>' \
  --url 'https://connect.comma.ai/<dongle>/<route>/<start>/<end>' \
  --render-type ui \
  --output ./shared/gce-hosted-smoke.mp4
```

Local Cog/container smoke on the VM:

```bash
./cog/render_artifacts.sh
cog predict --gpus all -i renderType=ui -i route='literal:https://connect.comma.ai/<dongle>/<route>/<start>/<end>'
```

GCE is especially useful for checking:

- null/EGL rendering on Linux
- NVENC behavior
- whether a new runtime or bootstrap change behaves correctly before pushing to
  Replicate

## Step 1: Build the patched Cog runtime wheels

Build the patched runtime artifacts with:

```bash
./cog/runtime_patch/build_wheels.sh
```

That produces wheels in:

```text
cog/runtime_patch/dist/
```

The important outputs are:

- a patched `cog` SDK wheel
- a patched Linux `coglet` wheel

These are what make hosted Replicate keep accepting normal raw route URLs.

## Step 2: Regenerate Cog build artifacts

The push helper does this for you, but the underlying command is:

```bash
./cog/render_artifacts.sh
```

That regenerates:

- `requirements-cog.txt`
- `cog.yaml`

The rendered `cog.yaml` embeds the shared bootstrap script so the build stays
reproducible inside Replicate/Cog.

## Step 3: Push staging

The standard staging deploy is:

```bash
./cog/runtime_patch/push_beta.sh
```

By default, that script targets:

```text
r8.im/nelsonjchen/op-replay-clipper-beta
```

It automatically:

1. finds the patched wheels in `cog/runtime_patch/dist/`
2. regenerates the Cog artifacts
3. runs `cog push` with:
   - `COG_SDK_WHEEL=...`
   - `COGLET_WHEEL=...`

## Step 4: Identify the new staging version

After the push, get the latest version id:

```bash
uv run python - <<'PY'
import os
import replicate

client = replicate.Client(api_token=os.environ["REPLICATE_API_TOKEN"])
model = client.models.get("nelsonjchen/op-replay-clipper-beta")
versions = list(model.versions.list())
print(versions[0].id)
PY
```

Use that exact version id for smoke testing rather than relying on the model
alias alone.

## Step 5: Run the staging smoke matrix

The current promotion gate is documented in:

- [`prod-readiness-checklist.md`](./prod-readiness-checklist.md)

The main risky surfaces are:

- UI raw URL handling
- UI HEVC output
- forward rendering
- 360 rendering on newer mici routes
- 360 forward-upon-wide rendering on newer mici routes
- JWT-backed UI rendering

The standard route used for the current regression matrix is:

```text
https://connect.comma.ai/5beb9b58bd12b691/0000010a--a51155e496/90/105
```

That route is useful because it exercises the newer mici camera dimensions that
previously broke the 360 path.

## Step 6: Push production

Once staging is good, push the same repo state to production by overriding the
target model:

```bash
MODEL='r8.im/nelsonjchen/op-replay-clipper' \
./cog/runtime_patch/push_beta.sh
```

Despite the script name, this is the same patched-runtime push flow, just with
the production model target overridden.

## Step 7: Identify the new production version

Get the newest production version id:

```bash
uv run python - <<'PY'
import os
import replicate

client = replicate.Client(api_token=os.environ["REPLICATE_API_TOKEN"])
model = client.models.get("nelsonjchen/op-replay-clipper")
versions = list(model.versions.list())
print(versions[0].id)
PY
```

## Step 8: Run the post-promotion smoke set

After a production push, rerun at least:

- UI raw URL
- UI HEVC
- one non-UI case, usually `360` or `forward`

Example:

```bash
uv run python replicate_run.py \
  --model 'nelsonjchen/op-replay-clipper:<prod-version>' \
  --url 'https://connect.comma.ai/5beb9b58bd12b691/0000010a--a51155e496/90/105' \
  --render-type ui \
  --file-format auto \
  --output ./shared/prod-live-ui-raw.mp4
```

```bash
uv run python replicate_run.py \
  --model 'nelsonjchen/op-replay-clipper:<prod-version>' \
  --url 'https://connect.comma.ai/5beb9b58bd12b691/0000010a--a51155e496/90/105' \
  --render-type ui \
  --file-format hevc \
  --output ./shared/prod-live-ui-hevc.mp4
```

```bash
uv run python replicate_run.py \
  --model 'nelsonjchen/op-replay-clipper:<prod-version>' \
  --url 'https://connect.comma.ai/5beb9b58bd12b691/0000010a--a51155e496/90/105' \
  --render-type 360 \
  --file-format auto \
  --output ./shared/prod-live-360.mp4
```

Verify with `ffprobe` after each run.

For 360 outputs, also verify spherical metadata is still present.

## What "good" looks like

A good deploy currently means:

- hosted Replicate accepts a normal raw `https://connect.comma.ai/...` route URL
- UI renders work in both H.264 and HEVC
- 360 outputs still include spherical metadata
- newer mici routes render successfully in 360 and 360 forward-upon-wide
- the pushed version was built with the patched Cog runtime, not stock Cog 0.17

## Notes and gotchas

- Local `cog predict` may still need `literal:https://...` when you are testing
  against an unpatched local Cog install.
- Hosted Replicate should not need the `literal:` workaround when the patched
  runtime is baked into the pushed model version.
- The script name `push_beta.sh` is historical. It can push either model by
  changing `MODEL=...`.
- If a deploy behaves strangely, check the current upstream/Cog patch context
  in:
  - [`upstream-modifications.md`](./upstream-modifications.md)
  - [`runtime-patching-and-ui-rendering.md`](./runtime-patching-and-ui-rendering.md)
