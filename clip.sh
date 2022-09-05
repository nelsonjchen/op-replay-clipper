#!/usr/bin/bash

set -ex

# Cleanup processes for easy fast testing.
# Rely on Docker to clean up containers processes in production though
function cleanup() {
    tmux list-panes -s -t clipper -F "#{pane_pid} #{pane_current_command}" \
    | grep -v tmux | awk '{print $1}' | xargs kill -9 || true
}

function ctrl_c() {
    cleanup
    pkill -P $$
}
# trap ctrl-c and call ctrl_c()
trap ctrl_c INT

# Cleanup stale stuff from last run
cleanup

STARTING_SEC=${1:-60}
SMEARED_STARTING_SEC=$($STARTING_SEC - 30)
ROUTE=${2:-4cf7a6ad03080c90|2021-09-29--13-46-36}
JWT_AUTH=${3:-false}

# Starting seconds must be greater than 30
if [ "$STARTING_SEC" -lt 30 ]; then
    echo "Starting seconds must be greater than 30"
    exit 1
fi

pushd /home/batman/openpilot

if [ "$JWT_AUTH" != "false" ]; then
    echo "{\"access_token\": \"$JWT_AUTH\"}" > "$HOME"/.comma/auth.json
fi

# Start processes
tmux new-session -d -s clipper -n x11 "Xtigervnc :0 -geometry 1920x1080 -SecurityTypes None"
tmux new-window -n replay -t clipper: "TERM=xterm-256color faketime -m -f \"+0 x0.5\" ./tools/replay/replay -s \"$SMEARED_STARTING_SEC\" \"$ROUTE\""
tmux new-window -n ui -t clipper: 'faketime -m -f "+0 x0.5" ./selfdrive/ui/ui'

# Pause replay and let it download the route
tmux send-keys -t clipper:replay Space
sleep 3

tmux send-keys -t clipper:replay Enter "$SMEARED_STARTING_SEC" Enter
tmux send-keys -t clipper:replay Space
sleep 1
tmux send-keys -t clipper:replay Space
# Record with ffmpeg
ffmpeg -framerate 10 -video_size 1920x1080 -f x11grab -i :0.0 -ss 30 -vcodec libx264 -preset medium -pix_fmt yuv420p -r 20 -filter:v "setpts=0.5*PTS,scale=1920:1080" -y -t 30 /workspace/shared/video.mp4

ctrl_c
