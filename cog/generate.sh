#!/bin/bash

# Get the current directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Encode the setup.sh script into cog.template.yaml as base64 of ENCODED_SCRIPT and put it one directory up as cog.yml
sed -e "s/ENCODED_SCRIPT/$(base64 -w 0 "$DIR"/../common/setup.sh)/" "$DIR"/cog.template.yaml > "$DIR"/../cog.yaml