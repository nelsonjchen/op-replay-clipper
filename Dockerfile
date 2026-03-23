FROM ubuntu:24.04 AS base

COPY ./common/setup.sh /setup.sh

RUN /setup.sh

ARG USERNAME=ubuntu
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME \
    && chown $USERNAME /home/$USERNAME

# ********************************************************
# * Anything else you want to do like clean up goes here *
# ********************************************************

# [Optional] Set the default user. Omit if you want to keep the default as root.
USER $USERNAME

FROM base AS clipper

WORKDIR /workspace

COPY ./clip.sh /workspace/clip.sh
COPY ./local_clip.py /workspace/local_clip.py
COPY ./clip_pipeline.py /workspace/clip_pipeline.py
COPY ./ffmpeg_clip.py /workspace/ffmpeg_clip.py
COPY ./ui_clip.py /workspace/ui_clip.py
COPY ./runtime_env.py /workspace/runtime_env.py
COPY ./openpilot_setup.py /workspace/openpilot_setup.py
COPY ./openpilot_compat.py /workspace/openpilot_compat.py
COPY ./route_or_url.py /workspace/route_or_url.py
COPY ./downloader.py /workspace/downloader.py
COPY ./pyproject.toml /workspace/pyproject.toml

CMD ["/workspace/clip.sh"]
