# Prod Readiness Checklist

Use this checklist before promoting the current Replicate staging model
(`nelsonjchen/op-replay-clipper-beta`) to the production model
(`nelsonjchen/op-replay-clipper`).

The goal is not to re-litigate the entire repo. The goal is to verify the small
set of behaviors that have actually been risky in practice:

- BIG UI raw URL handling
- BIG UI HEVC output
- forward rendering
- 360 rendering on newer mici routes
- 360 forward-upon-wide rendering on newer mici routes
- JWT-backed UI rendering on a public route
- stock Cog raw-URL behavior on hosted Replicate

## Preconditions

- Have a fresh Replicate staging version built from the current branch.
- Have a valid `REPLICATE_API_TOKEN` in `.env` or your shell.
- Use a public route for the JWT smoke unless you are explicitly checking a
  private route.
- Use the same route for the UI and non-UI smokes unless a specific route is
  being called out below.

Recommended regression route:

```text
https://connect.comma.ai/5beb9b58bd12b691/0000010a--a51155e496/90/105
```

That route exercises the newer mici camera sizes that exposed the recent 360
regression.

## Model Names

Set these once before running the matrix:

```bash
export STAGING_MODEL='nelsonjchen/op-replay-clipper-beta:<version>'
export PROD_MODEL='nelsonjchen/op-replay-clipper:<version>'
export ROUTE_URL='https://connect.comma.ai/5beb9b58bd12b691/0000010a--a51155e496/90/105'
export JWT_TOKEN='<valid jwt>'
```

Use the staging model for the full smoke matrix first. Promote only after that
passes, then spot-check the production model with the same core cases.

## Smoke Matrix

### 1. BIG UI raw URL

```bash
uv run python replicate_run.py \
  --model "$STAGING_MODEL" \
  --url "$ROUTE_URL" \
  --render-type ui \
  --file-format auto \
  --output ./shared/prod-check-ui-raw.mp4
```

Pass criteria:

- the prediction succeeds on hosted Replicate
- the output video is playable
- the clip starts with the expected BIG UI metadata overlay
- no `literal:` wrapper is required on the hosted surface

### 2. BIG UI HEVC

```bash
uv run python replicate_run.py \
  --model "$STAGING_MODEL" \
  --url "$ROUTE_URL" \
  --render-type ui \
  --file-format hevc \
  --output ./shared/prod-check-ui-hevc.mp4
```

Pass criteria:

- the prediction succeeds on hosted Replicate
- `ffprobe` reports `codec_name=hevc` and `codec_tag_string=hvc1`
- the clip dimensions stay at the expected BIG UI size

### 3. Forward

```bash
uv run python replicate_run.py \
  --model "$STAGING_MODEL" \
  --url "$ROUTE_URL" \
  --render-type forward \
  --file-format auto \
  --output ./shared/prod-check-forward.mp4
```

Pass criteria:

- the prediction succeeds
- the clip is the expected forward-camera resolution for the route
- the clip duration matches the requested window

### 4. 360

```bash
uv run python replicate_run.py \
  --model "$STAGING_MODEL" \
  --url "$ROUTE_URL" \
  --render-type 360 \
  --file-format auto \
  --output ./shared/prod-check-360.mp4
```

Pass criteria:

- the prediction succeeds
- the output uses the route’s real wide-camera height instead of assuming an
  older fixed crop
- the output is encoded correctly and plays back cleanly

### 5. 360 Forward Upon Wide

```bash
uv run python replicate_run.py \
  --model "$STAGING_MODEL" \
  --url "$ROUTE_URL" \
  --render-type 360_forward_upon_wide \
  --file-format auto \
  --output ./shared/prod-check-360-fuw.mp4
```

Pass criteria:

- the prediction succeeds
- the output uses the route’s real wide-camera height as the basis for the
  overlaid driver crop
- the clip is still playable at the higher-resolution 360 output size

### 6. JWT On Public Route

```bash
uv run python replicate_run.py \
  --model "$STAGING_MODEL" \
  --url "$ROUTE_URL" \
  --render-type ui \
  --jwt-token "$JWT_TOKEN" \
  --file-format auto \
  --output ./shared/prod-check-ui-jwt.mp4
```

Pass criteria:

- the prediction succeeds even though the route is already public
- the JWT field does not break the raw URL input path
- the output matches the normal UI smoke

### 7. Driver Hidden Passenger Blur

```bash
uv run python replicate_run.py \
  --model "$STAGING_MODEL" \
  --url "$ROUTE_URL" \
  --render-type driver \
  --anonymization-profile 'driver face swap, passenger hidden' \
  --passenger-redaction-style blur \
  --jwt-token "$JWT_TOKEN" \
  --output ./shared/prod-check-driver-hidden-blur.mp4
```

Pass criteria:

- the prediction succeeds
- the output is playable
- the driver banner reads `DRIVER SWAPPED, PASSENGER BLURRED`
- the hidden passenger region uses the RF-DETR body mask instead of the old coarse pixel box

### 8. Driver Hidden Passenger Silhouette

```bash
uv run python replicate_run.py \
  --model "$STAGING_MODEL" \
  --url "$ROUTE_URL" \
  --render-type driver \
  --anonymization-profile 'driver face swap, passenger hidden' \
  --passenger-redaction-style silhouette \
  --jwt-token "$JWT_TOKEN" \
  --output ./shared/prod-check-driver-hidden-silhouette.mp4
```

Pass criteria:

- the prediction succeeds
- the output is playable
- the driver banner reads `DRIVER SWAPPED, PASSENGER SILHOUETTED`
- the hidden passenger region is fully opaque white with the dashed cutout outline

### 9. Driver Debug Hidden Passenger Blur

```bash
uv run python replicate_run.py \
  --model "$STAGING_MODEL" \
  --url "$ROUTE_URL" \
  --render-type driver-debug \
  --anonymization-profile 'driver unchanged, passenger hidden' \
  --passenger-redaction-style blur \
  --jwt-token "$JWT_TOKEN" \
  --output ./shared/prod-check-driver-debug-hidden-blur.mp4
```

Pass criteria:

- the prediction succeeds
- the output is playable
- the driver-debug footer still renders correctly
- the hidden passenger region is blurred for the full delivered clip with no exposed frames

## Runtime Assumptions To Verify

These are not separate smokes, but they should be true when the matrix passes.

- The hosted Replicate model version was built with stock `cog 0.17.2+`.
- The runtime still accepts plain raw `https://connect.comma.ai/...` URLs on
  the hosted surface.
- The hosted `anonymizationProfile` surface accepts the new hidden-passenger
  labels and still accepts old pixelize labels as compatibility aliases.
- The hosted `passengerRedactionStyle` surface accepts `blur` and
  `silhouette`, defaulting to `blur`.
- BIG UI unit detection should come from the logged route `IsMetric` param
  when present, and imperial should remain the fallback when it is missing.
- The 360 renderer should no longer assume older fixed camera dimensions on
  newer mici routes.

## Promotion Gate

Do not promote staging to production until all of the following are true:

- raw URL UI smoke passes
- UI HEVC smoke passes
- forward smoke passes
- 360 smoke passes
- 360 forward-upon-wide smoke passes
- JWT-on-public-route smoke passes
- `ffprobe` matches the expected codec and dimensions for the generated clips
- the run used the current stock Cog hosted path, not a stale local-only fallback

If any one of these fails, stop and fix the regression before promoting.

## After Promotion

After pushing the same commit to the production model, rerun at least:

- raw URL UI smoke
- UI HEVC smoke
- one non-UI smoke (`forward` or `360`)

That catches the most likely “worked in staging, broke in prod” mistakes without
repeating the whole matrix twice.
