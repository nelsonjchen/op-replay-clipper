# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12-bookworm
FROM --platform=$TARGETPLATFORM ${PYTHON_IMAGE} AS builder

ARG COG_REF=v0.17.0
ENV DEBIAN_FRONTEND=noninteractive
ENV PATH=/root/.cargo/bin:${PATH}

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    patchelf \
    pkg-config \
    python3-dev \
  && rm -rf /var/lib/apt/lists/*

RUN curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal \
  && rustup default stable

RUN python -m pip install --no-cache-dir --upgrade pip build maturin

WORKDIR /src
RUN git clone --depth 1 --branch "${COG_REF}" https://github.com/replicate/cog.git source

WORKDIR /src/source
COPY 0001-only-coerce-url-strings-for-file-and-path-inputs.patch /tmp/coglet-input-fix.patch
RUN git apply /tmp/coglet-input-fix.patch

RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    python -m build --wheel --outdir /out

RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/src/source/target \
    cd crates/coglet-python && maturin build --release --compatibility linux --out /out

FROM scratch AS dist
COPY --from=builder /out/ /
