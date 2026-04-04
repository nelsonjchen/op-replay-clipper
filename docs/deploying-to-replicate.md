# Deploying To Replicate

This document describes how this repo is currently deployed to Replicate.

It covers:

- staging pushes to `nelsonjchen/op-replay-clipper-beta`
- production pushes to `nelsonjchen/op-replay-clipper`
- local testing before a push
- how stock `cog 0.17.2+` fits into the current flow
- how to verify a pushed version before and after promotion

## Overview

This repo now deploys with a normal stock `cog push`, but it still relies on
repo-generated Cog artifacts and a substantial bootstrap script.

The deploy path depends on:

1. generated Cog build artifacts from [`cog/render_artifacts.sh`](../cog/render_artifacts.sh)
2. stock `cog 0.17.2+`
3. a normal `cog push`

Upstream Cog `0.17.2` fixed the earlier raw-URL coercion bug for plain `str`
inputs, so hosted Replicate can again accept normal
`https://connect.comma.ai/...` route URLs without a custom runtime patch.

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
cog predict -i renderType=ui -i route='https://connect.comma.ai/<dongle>/<route>/<start>/<end>'
```

Notes:

- stock `cog 0.17.2+` should accept plain connect URLs for this repo's
  `route: str` input
- the local parser still accepts `literal:https://...` as a backwards-compatible
  form if you happen to have an older local helper flow lying around
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
cog predict --gpus all -i renderType=ui -i route='https://connect.comma.ai/<dongle>/<route>/<start>/<end>'
```

GCE is especially useful for checking:

- null/EGL rendering on Linux
- NVENC behavior
- whether a new runtime or bootstrap change behaves correctly before pushing to
  Replicate
- the passenger redaction product path via
  `./scripts/smoke_driver_redaction.sh --backend local --accel nvidia`

For this repo's current Linux/NVIDIA validation target, use your Cowboy project
GPU VM and keep the details in local environment config rather than committing
them into the repo.

Add these to your local `.env`:

```bash
export GCE_PROJECT=your-gcp-project
export GCE_ZONE=your-gce-zone
export GCE_INSTANCE=your-gpu-vm-name
```

Typical start/stop flow:

```bash
set -a
source .env
set +a

gcloud compute instances start "$GCE_INSTANCE" \
  --project "$GCE_PROJECT" \
  --zone "$GCE_ZONE"

gcloud compute ssh "$GCE_INSTANCE" \
  --project "$GCE_PROJECT" \
  --zone "$GCE_ZONE"
```

If the zone is temporarily out of L4 capacity, use the retry helper instead of
manually re-running `gcloud compute instances start`:

```bash
set -a
source .env
set +a

./scripts/wait_for_gce_instance_start.sh
```

It retries through `ZONE_RESOURCE_POOL_EXHAUSTED` / stockout errors every 10
minutes by default and exits as soon as the instance reaches `RUNNING`.

For the RF-DETR Linux/CUDA debugging track, use the dedicated T4 acquisition
helper instead. It creates a temporary T4 VM, tries spot first, falls back to
standard if spot capacity stays unavailable, and keeps retrying ordered zones
until one succeeds:

```bash
set -a
source .env
set +a

./scripts/acquire_t4_gce_instance.sh
```

It writes the chosen instance name and zone into a local temp state dir so
follow-up scripts can reuse the VM. When you are done, delete that temporary VM
and clear the state with:

```bash
./scripts/delete_t4_gce_instance.sh
```

Before running Cog or RF-DETR smokes on that VM, bootstrap it into the
known-good T4 state:

```bash
./scripts/bootstrap_t4_gce_vm.sh
```

That installs Docker, Cog, `nvidia-container-toolkit`, and the NVIDIA video
driver packages (`libnvidia-encode-580-server`,
`libnvidia-decode-580-server`) so NVENC/NVCUVID are available inside the Cog
container instead of only bare CUDA compute.

### Tiny RF-DETR repro path

There is also a tiny RF-DETR-only repro surface for debugging Cog/Replicate GPU
issues without the rest of the clipper stack.

It uses:

- [`scripts/rf_detr_repro.py`](../scripts/rf_detr_repro.py) for plain local Python
- [`cog_rfdetr_repro_predictor.py`](../cog_rfdetr_repro_predictor.py) for local/hosted Cog
- [`rf_detr_repro_run.py`](../rf_detr_repro_run.py) for hosted Replicate smoke runs
- [`scripts/smoke_rf_detr_repro.sh`](../scripts/smoke_rf_detr_repro.sh) to prepare a tiny still and tiny clip from an existing local source

Local plain-Python repro:

```bash
uv sync
./scripts/smoke_rf_detr_repro.sh --backend local-cli
```

Local Cog repro:

```bash
./cog/render_artifacts.sh
./scripts/smoke_rf_detr_repro.sh --backend local-cog --device cuda --require-actual-device cuda
```

Hosted beta repro:

```bash
./cog/render_artifacts.sh
cog push --file cog-rfdetr-repro.yaml r8.im/nelsonjchen/op-replay-clipper-rfdetr-repro-beta

uv run python rf_detr_repro_run.py \
  --model 'nelsonjchen/op-replay-clipper-rfdetr-repro-beta:<version>' \
  --input ./shared/rf-detr-repro-inputs/tiny-clip.mp4 \
  --output ./shared/rf-detr-repro-hosted-artifacts.zip
```

Use this path when you want to answer questions like:

- does RF-DETR itself succeed on GPU in plain Python?
- does local `cog predict` keep or lose GPU access?
- does hosted Replicate fail on the same tiny input?

For the current GPU-only debugging track, treat any RF-DETR CPU fallback as a
failure. On Linux/NVIDIA, require `actual_model_device = "cuda"` in the repro
report and require the driver redaction selection report to show
`hidden_redaction.rf_detr_device = "cuda"`.

## Step 1: Regenerate Cog build artifacts

The push helper does this for you, but the underlying command is:

```bash
./cog/render_artifacts.sh
```

That regenerates:

- `requirements-cog.txt`
- `cog.yaml`
- `cog-rfdetr-repro.yaml`

The rendered `cog.yaml` embeds the shared bootstrap script so the build stays
reproducible inside Replicate/Cog.

## Step 2: Push staging

The standard staging deploy is:

```bash
./cog/render_artifacts.sh
cog push r8.im/nelsonjchen/op-replay-clipper-beta
```

That targets:

```text
r8.im/nelsonjchen/op-replay-clipper-beta
```

## Step 3: Identify the new staging version

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

## Step 4: Run the staging smoke matrix

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

## Step 5: Push production

Once staging is good, push the same repo state to production by overriding the
target model:

```bash
cog push r8.im/nelsonjchen/op-replay-clipper
```

## Step 6: Identify the new production version

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

## Step 7: Run the post-promotion smoke set

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
- the pushed version was built from stock `cog 0.17.2+` with the current repo bootstrap

## Notes and gotchas

- Local `cog predict` should work with plain connect URLs on stock
  `cog 0.17.2+`.
- The parser still accepts `literal:https://...` for backwards compatibility,
  but that is no longer the recommended path.
- If a deploy behaves strangely, check the current upstream/Cog patch context
  in:
  - [`upstream-modifications.md`](./upstream-modifications.md)
  - [`runtime-patching-and-ui-rendering.md`](./runtime-patching-and-ui-rendering.md)
