# Replicate.com/Cog Generation

This folder generates Cog build artifacts for running the clipper on Replicate or with local `cog build`.

Current upstream Cog already sets `NVIDIA_DRIVER_CAPABILITIES=all`, so a custom
Cog fork is no longer required for GPU visibility. Cog `0.17.1` also fixed the
upstream URL-coercion regression for this project's plain `route: str` input.

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
