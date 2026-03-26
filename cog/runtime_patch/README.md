# Patched Cog 0.17 Runtime Builder

This folder makes the Replicate/Cog `0.17` URL-coercion fix reproducible from this repo.

## Why this exists

Stock `cog 0.17.0` moved input coercion into `coglet` and started coercing any `http://` or `https://` string input into a downloaded file-like path, even for plain `str` predictor inputs.

That breaks this project's public `route: str` API, because a normal `https://connect.comma.ai/...` route URL arrives as a downloaded temp file instead of the original URL string.

The patch in this folder narrows that behavior back down so URL coercion only applies to `Path` and `File`-typed inputs. Plain `str` inputs remain plain strings again.

## What gets built

`build_wheels.sh` produces two wheel artifacts in `cog/runtime_patch/dist/`:

- a patched `cog` SDK wheel
- a patched Linux `coglet` wheel

Those two wheels can then be injected into a normal `cog push` using:

- `COG_SDK_WHEEL=...`
- `COGLET_WHEEL=...`

That means a patched local push bakes a patched runtime into the resulting Replicate model version.

## Build the wheels

This is designed to work from macOS by using Docker to build Linux artifacts.

```bash
./cog/runtime_patch/build_wheels.sh
```

Optional environment variables:

- `COG_REF=v0.17.0`
- `PLATFORM=linux/amd64`
- `OUTPUT_DIR=/abs/path/to/output`

The Dockerfile uses BuildKit cache mounts for `pip`, Cargo registry downloads, and Cargo build output, so repeated builds should be much faster than the first one.

## Push beta with the patched runtime

Use an official `cog 0.17.x` CLI binary or installation, then point the push at the patched runtime wheels:

```bash
COG_BIN=/path/to/cog \
./cog/runtime_patch/push_beta.sh
```

By default this pushes to:

```text
r8.im/nelsonjchen/op-replay-clipper-beta
```

Optional environment variables:

- `MODEL=r8.im/nelsonjchen/op-replay-clipper-beta`
- `DIST_DIR=/abs/path/to/wheels`
- `COG_SDK_WHEEL=/abs/path/to/cog-....whl`
- `COGLET_WHEEL=/abs/path/to/coglet-....whl`

## Notes

- The important platform-specific artifact is the Linux `coglet` wheel. That is why this builder exists even if you push from a Mac.
- The pushed Replicate version will still usually report `cog_version: 0.17.0`, because the public version string stays the same even though the runtime wheel contents are patched.
- This folder is intentionally scoped to the URL-coercion regression. It does not replace the main `cog/render_artifacts.sh` flow for `cog.yaml` and requirements generation.
