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

# Add overlay
RUN git clone https://github.com/ftorkler/x11-overlay --depth 1 && make -C x11-overlay && cp x11-overlay/bin/overlay /usr/local/bin

# Add Google Stuff
# Downloading gcloud package
RUN curl https://dl.google.com/dl/cloudsdk/release/google-cloud-sdk.tar.gz > /tmp/google-cloud-sdk.tar.gz

# Installing the package
RUN mkdir -p /usr/local/gcloud \
  && tar -C /usr/local/gcloud -xvf /tmp/google-cloud-sdk.tar.gz \
  && /usr/local/gcloud/google-cloud-sdk/install.sh

# Adding the package path to local
ENV PATH $PATH:/usr/local/gcloud/google-cloud-sdk/bin

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