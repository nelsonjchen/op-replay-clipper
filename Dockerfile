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

COPY ./clip.sh /workspace/clip.sh

CMD ["/workspace/clip.sh"]