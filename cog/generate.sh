#!/bin/bash

# Get the current directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Encode the setup.sh script into cog.template.yaml as base64 of ENCODED_SCRIPT and put it one directory up as cog.yml
if base64 --help 2>/dev/null | grep -q -- "--wrap"; then
  ENCODED_SCRIPT=$(base64 --wrap=0 "$DIR"/../common/setup.sh)
else
  ENCODED_SCRIPT=$(base64 < "$DIR"/../common/setup.sh | tr -d '\n')
fi
sed -e "s/ENCODED_SCRIPT/$ENCODED_SCRIPT/" "$DIR"/cog.template.yaml > "$DIR"/../cog.yaml
