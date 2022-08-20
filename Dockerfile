FROM ghcr.io/commaai/openpilot-prebuilt:latest AS base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    gdb \
    htop \
    vim \
    tigervnc-standalone-server \
    apitrace-tracers \
    apitrace \
    ffmpeg \
    faketime \
    mesa-utils

FROM base AS dev

# Get Rust
RUN curl https://sh.rustup.rs -sSf | bash -s -- -y

RUN echo 'source $HOME/.cargo/env' >> $HOME/.bashrc