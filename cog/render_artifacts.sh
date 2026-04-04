#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"

uv export \
  --frozen \
  --format requirements.txt \
  --no-hashes \
  --no-emit-project \
  --no-group test \
  --output-file "${ROOT_DIR}/requirements-cog.txt"

# The hosted predictor imports the shared RF-DETR passenger-redaction path
# directly, so the image needs the same core vision/runtime stack that exists
# in the local dev environment.
cat >>"${ROOT_DIR}/requirements-cog.txt" <<'EOF'
numpy==2.4.4
opencv-python-headless==4.13.0.92
torch==2.11.0
torchvision==0.26.0
rfdetr==1.6.3
supervision==0.27.0.post2
EOF

cat >"${ROOT_DIR}/requirements-rfdetr-repro-cog.txt" <<'EOF'
numpy==2.4.4
opencv-python-headless==4.13.0.92
torch==2.11.0
torchvision==0.26.0
rfdetr==1.6.3
supervision==0.27.0.post2
EOF

python3 "${SCRIPT_DIR}/render_config.py" \
  --template "${SCRIPT_DIR}/cog.template.yaml" \
  --setup-script "${ROOT_DIR}/common/bootstrap_image_env.sh" \
  --output "${ROOT_DIR}/cog.yaml"

python3 "${SCRIPT_DIR}/render_config.py" \
  --template "${SCRIPT_DIR}/cog-rfdetr-repro.template.yaml" \
  --setup-script "${ROOT_DIR}/common/bootstrap_rfdetr_repro_env.sh" \
  --output "${ROOT_DIR}/cog-rfdetr-repro.yaml"
