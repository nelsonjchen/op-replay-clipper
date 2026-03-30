FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV OPENPILOT_ROOT=/home/batman/openpilot

# Install Python 3.12 via deadsnakes PPA
RUN apt-get update -y && \
    apt-get install -y software-properties-common && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update -y && \
    apt-get install -y python3.12 python3.12-venv python3.12-dev && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    rm -rf /var/lib/apt/lists/*

# Copy and run the shared bootstrap script (installs system packages, clones
# openpilot, builds native deps, installs patched pyray, generates fonts).
COPY common/bootstrap_image_env.sh /tmp/bootstrap_image_env.sh
RUN bash /tmp/bootstrap_image_env.sh && rm /tmp/bootstrap_image_env.sh

# Install uv and project Python dependencies
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy project source
COPY core/ core/
COPY renderers/ renderers/
COPY common/ common/
COPY patches/ patches/
COPY clip.py ./

ENTRYPOINT ["uv", "run", "--no-sync", "python", "clip.py", \
    "--skip-openpilot-update", "--skip-openpilot-bootstrap"]
