FROM ghcr.io/commaai/openpilot-prebuilt:latest AS base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    htop \
    vim \
    tigervnc-standalone-server \
    ffmpeg \
    faketime \
    tmux \
    shellcheck \
    # for overlay
    libx11-dev \
    libxfixes-dev \
    libxrandr-dev \
    libxft-dev \
    libfreetype-dev \
    # For Debugging X stuff
    mesa-utils

RUN git clone https://github.com/ftorkler/x11-overlay --depth 1 && make -C x11-overlay && cp x11-overlay/bin/overlay /usr/local/bin

ARG USERNAME=robin
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# Create the user
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME -s /usr/bin/bash \
    #
    # [Optional] Add sudo support. Omit if you don't need to install software after connecting.
    && apt-get update \
    && apt-get install -y sudo \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

# ********************************************************
# * Anything else you want to do like clean up goes here *
# ********************************************************

# [Optional] Set the default user. Omit if you want to keep the default as root.
USER $USERNAME

FROM base AS dev

COPY ./clip.sh /workspace/clip.sh

CMD ["/workspace/clip.sh"]