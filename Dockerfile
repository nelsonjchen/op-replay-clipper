FROM ghcr.io/commaai/openpilot-prebuilt:latest

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    gdb \
    htop \
    vim \
    tigervnc-standalone-server \
    apitrace-tracers \
    apitrace \
    ffmpeg \
    mesa-utils
