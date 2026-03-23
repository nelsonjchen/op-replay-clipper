# Replicate.com/Cog Generation

This folder generates Cog build artifacts for running the clipper on Replicate or with local `cog build`.

Current upstream Cog already sets `NVIDIA_DRIVER_CAPABILITIES=all`, so a custom Cog fork is no longer required.

`generate.sh` is still needed here for two repo-specific reasons:

1. It exports `requirements-cog.txt` from `uv.lock` so Cog uses a supported `python_requirements` file instead of deprecated `python_packages`.
2. It injects the shared `common/setup.sh` into `cog.yaml`, because official Cog still documents that repo files are not available to `build.run` commands.
