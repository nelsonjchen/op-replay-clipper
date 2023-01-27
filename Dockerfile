FROM ghcr.io/commaai/openpilot-prebuilt:latest AS base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    # The usual dev stuff
    htop \
    vim \
    jq \
    shellcheck \
    # For Replay
    tigervnc-standalone-server \
    ffmpeg \
    faketime \
    tmux \    
    # For Debugging X stuff
    mesa-utils \
    # For script calcuation
    bc \
    # For network monitoring
    net-tools

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

FROM base AS clipper

COPY ./clip.sh /workspace/clip.sh

CMD ["/workspace/clip.sh"]
