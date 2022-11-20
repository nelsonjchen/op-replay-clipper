#!/bin/bash

# Hack/Scratch file to edit and run clip.sh as you tweak so you're not tediously editing the command on the terminal line.

# Please refer to the README.md for more information.

# Don't commit changes of this file to Git.
# Edit this file with your route id and other parameters you would like.
# You can find more parameters by running `./clip.sh --help` in the Terminal.
# Run this file to run clip.sh with the parameters by running `./scratch_run.sh` in the Terminal.

/bin/bash clip.sh \
  `# Get the route / segment id from https://connect.comma.ai` \
  `# Eg. fe18f736cb0d7813|2022-11-11--20-20-49` \
  "fffffsomedongleidzzzzz|2022-11-11--20-20-49" \
  `# Get a token from https://jwt.comma.ai` \
  --jwt-token "replace_this_with_that_token" \
  `# Segment IDs start from 0. Multiply the segment number by 60.` \
  --start-seconds 60 \
  `# It's the length of a clip. Keep it short. Or long, if you want.` \
  `# Longer clips take much longer though.` \
  --length-seconds 60 \
  `# Visit and allow notifications from https://ntfy.sh/ntfy_topic_of_your_choice` \
  `# so you know when its done and get a nice notification` \
  --ntfysh ntfy_topic_of_your_choice
