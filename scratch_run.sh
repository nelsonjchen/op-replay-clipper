#!/bin/bash

# Hack/Scratch file to edit and run clip.sh as you tweak so you're not tediously editing the command on the terminal line.

# Please refer to the README.md for more information.

# Don't commit changes of this file to Git.
# Edit this file with your route id and other parameters you would like.
# You can find more parameters by running `./clip.sh --help` in the Terminal.
# Run this file to run clip.sh with the parameters by running `./scratch_run.sh` in the Terminal.
# Terminal not shown in Codespaces? Click the three bars on the top left corner and select View -> Terminal.

/bin/bash clip.sh \
  `# Get the route / segment id from https://connect.comma.ai and put it below` \
  "fffffsomedongleidzzzzz|2022-11-11--20-20-49" \
  `# Get a token from https://jwt.comma.ai` \
  --jwt-token "replace_this_with_that_token" \
  `# Segment IDs start from 0. e.g. fe18f736cb0d7813|2022-11-11--20-20-49--1 has a segment id of 1` \
  `# Multiply the segment number by 60 and add an offset if you want.` \
  --start-seconds 60 \
  `# It's the length of a clip. Keep it short. Or long, if you want.` \
  `# Longer clips take proportionally longer to render.` \
  --length-seconds 30 \
  `# https://ntfy.sh can be used to provide desktop notifications when a rendering is complete.` \
  `# Pick a unique topic name of your choice, and replace "ntfy_topic_of_your_choice" below with it` \
  `# Then, visit and allow desktop notifications from https://ntfy.sh/ntfy_topic_of_your_choice` \
  `# so you know when its done and get a nice notification on your desktop to come back.` \
  --ntfysh ntfy_topic_of_your_choice \
  `# Much of the world like a superior systems of measurement. Uncomment-ize the next line to render in metric.` \
  `# --metric` \
  `# Change the output clip file name here. Any existing files will be overwritten.` \
  --output clip.mp4
