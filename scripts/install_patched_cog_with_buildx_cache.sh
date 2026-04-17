#!/usr/bin/env bash

set -euo pipefail

COG_VERSION="${COG_VERSION:-v0.17.2}"
INSTALL_DIR="${INSTALL_DIR:-$PWD/.bin}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

git clone --depth=1 --branch "${COG_VERSION}" https://github.com/replicate/cog.git "${TMP_DIR}/cog"

CONFIG_FILE="${TMP_DIR}/cog/pkg/config/config.go"
perl -0pi -e 's/"fmt"\n\t"path\/filepath"/"fmt"\n\t"os"\n\t"path\/filepath"/' "${CONFIG_FILE}"
perl -0pi -e 's/BuildXCachePath\s+string/BuildXCachePath           = os.Getenv("COG_BUILDX_CACHE_PATH")/' "${CONFIG_FILE}"

mkdir -p "${INSTALL_DIR}"
(
  cd "${TMP_DIR}/cog"
  go build -o "${INSTALL_DIR}/cog" ./cmd/cog
)

echo "Installed patched cog ${COG_VERSION} to ${INSTALL_DIR}/cog"
