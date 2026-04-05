#!/usr/bin/env bash

set -euo pipefail

IMAGE="${1:-r8.im/nelsonjchen/op-replay-clipper-beta}"

docker run --rm --entrypoint bash "${IMAGE}" -lc '
set -euo pipefail

for path in \
  /src/.cache \
  /.cache \
  /home/batman/openpilot \
  /home/batman/openpilot/.venv \
  /root/.pyenv \
  /usr/lib/x86_64-linux-gnu \
  /usr/local/cuda \
  /src; do
  if [ -e "$path" ]; then
    du -shx "$path"
  fi
done

printf "\nTOP /src/.cache\n"
if [ -d /src/.cache ]; then
  du -shx /src/.cache/* 2>/dev/null | sort -hr | head -n 40
fi

printf "\nTOP /.cache (including hidden)\n"
if [ -d /.cache ]; then
  du -shx /.cache/.[!.]* /.cache/* 2>/dev/null | sort -hr | head -n 40
fi

printf "\nTOP /root/.pyenv/versions/3.12.11/lib/python3.12/site-packages\n"
if [ -d /root/.pyenv/versions/3.12.11/lib/python3.12/site-packages ]; then
  du -shx /root/.pyenv/versions/3.12.11/lib/python3.12/site-packages/* 2>/dev/null | sort -hr | head -n 80
fi

printf "\nTOP /.cache/facefusion/.venv/lib/python3.12/site-packages\n"
if [ -d /.cache/facefusion/.venv/lib/python3.12/site-packages ]; then
  du -shx /.cache/facefusion/.venv/lib/python3.12/site-packages/* 2>/dev/null | sort -hr | head -n 80
fi

printf "\nTOP /home/batman/openpilot\n"
if [ -d /home/batman/openpilot ]; then
  du -shx /home/batman/openpilot/* 2>/dev/null | sort -hr | head -n 80
fi
'
