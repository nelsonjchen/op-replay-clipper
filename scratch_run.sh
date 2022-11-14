#!/bin/bash

# Scratch file to edit and run clip.sh with

# Edit this file to run clip.sh
# Don't commit changes of this file to Git.
# Edit this file with your route id and other parameters.
# Run this file to run clip.sh with the parameters by running `./scratch_run.sh` from the Terminal.

/bin/bash clip.sh \
  "fe18f736cb0d7813|2022-11-11--20-20-49--2" \
  --jwt-token "replace_this_with_a_token_from_jwt_dot_comma_dot_ai" \
  --start-seconds 60 \
  --length-seconds 60 \
  --ntfysh op_clipper_change_this_topic_with_your_own_from_ntfy_dot_sh \
  --experimental 
  
