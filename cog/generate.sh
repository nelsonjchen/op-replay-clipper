#!/bin/bash

# Get the current directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
ROOT_DIR="$DIR/.."

uv export \
  --frozen \
  --format requirements.txt \
  --no-hashes \
  --no-emit-project \
  --no-group test \
  --output-file "$ROOT_DIR/requirements-cog.txt"

# Encode the setup.sh script into cog.template.yaml as base64 of ENCODED_SCRIPT and put it one directory up as cog.yml
if base64 --help 2>/dev/null | grep -q -- "--wrap"; then
  ENCODED_SCRIPT=$(base64 --wrap=0 "$ROOT_DIR"/common/setup.sh)
else
  ENCODED_SCRIPT=$(base64 < "$ROOT_DIR"/common/setup.sh | tr -d '\n')
fi
sed -e "s/ENCODED_SCRIPT/$ENCODED_SCRIPT/" "$DIR"/cog.template.yaml > "$ROOT_DIR"/cog.yaml
