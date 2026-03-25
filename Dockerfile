FROM ubuntu:24.04 AS base

COPY ./common/bootstrap_image_env.sh /bootstrap_image_env.sh

RUN /bootstrap_image_env.sh

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

COPY ./pyproject.toml /workspace/pyproject.toml
COPY ./uv.lock /workspace/uv.lock

RUN uv sync --frozen --no-group test

COPY ./clip.py /workspace/clip.py
COPY ./cog_predictor.py /workspace/cog_predictor.py
COPY ./replicate_run.py /workspace/replicate_run.py
COPY ./core /workspace/core
COPY ./renderers /workspace/renderers

CMD ["uv", "run", "--no-sync", "python", "/workspace/clip.py", "ui"]
