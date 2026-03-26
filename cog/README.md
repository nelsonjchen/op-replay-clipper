# Replicate.com/Cog Generation

This folder generates Cog build artifacts for running the clipper on Replicate or with local `cog build`.

Current upstream Cog already sets `NVIDIA_DRIVER_CAPABILITIES=all`, so a custom
Cog fork is no longer required for GPU visibility. We still keep a patched
runtime builder here for the stock Cog `0.17` URL-coercion regression.

`render_artifacts.sh` is still needed here for two repo-specific reasons:

1. It exports `requirements-cog.txt` from `uv.lock` so Cog uses a supported `python_requirements` file instead of deprecated `python_packages`.
2. It injects the shared `common/bootstrap_image_env.sh` into `cog.yaml`, because official Cog still documents that repo files are not available to `build.run` commands.

The shell entrypoint is intentionally thin now. The YAML rendering itself lives in `cog/render_config.py` so the Cog-specific generation logic is testable without adding more shell branching.

The project pins `attrs<24` in `pyproject.toml` on purpose so the exported Cog requirements remain compatible with Cog's own runtime dependency bounds.

For the broader runtime-patching background, see
[`../docs/runtime-patching-and-ui-rendering.md`](../docs/runtime-patching-and-ui-rendering.md)
and
[`../docs/upstream-modifications.md`](../docs/upstream-modifications.md).
For the higher-level project history, see [`../CHANGELOG.md`](../CHANGELOG.md).

## Patched Cog 0.17 runtime

This repo also contains a reproducible builder for the `cog 0.17` URL-coercion regression fix in [`runtime_patch/`](./runtime_patch).

Use that folder when you need to rebuild the patched Linux `coglet` runtime
wheel and matching SDK wheel for beta pushes from macOS or any other non-Linux
development machine.

That patch matters for this project because:

1. Hosted Replicate beta should accept a normal raw `https://connect.comma.ai/...` route URL.
2. Stock local `cog predict` on Cog `0.17` still coerces raw URL-like `str`
   inputs too early, so unpatched local testing may still need the
   `literal:https://...` workaround.
