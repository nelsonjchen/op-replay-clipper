f from last run
cleanup

STARTING_SEC=$_arg_start_seconds
# Sometimes it takes a bit of time for openpilot drawing to settle in.
# Calculate optimal smear seconds as starting seconds mod 60 plus 30 seconds.
SMEAR_AMOUNT=$((($STARTING_SEC % 60) + 30))
SMEARED_STARTING_SEC=$(($STARTING_SEC - $SMEAR_AMOUNT))
# SMEARED_STARTING_SEC must be greater than 0
if [ $SMEARED_STARTING_SEC -lt 0 ]; then
    SMEARED_STARTING_SEC=0
fi
RECORDING_LENGTH=$_arg_length_seconds
# Cleanup trailing segment count. Seconds is what matters
ROUTE=$(echo "$_arg_route_id" | sed 's/--[0-9]$//')
RENDER_E2E_LONG=$_arg_e2e_long
JWT_AUTH=$_arg_jwt_token
VIDEO_CWD=$_arg_video_cwd
VIDEO_RAW_OUTPUT=$VIDEO_CWD/clip.mkv
VIDEO_OUTPUT=$VIDEO_CWD/$_arg_output
# Target an appropiate bitrate of filesize of 8MB for the video length
TARGET_MB=$_arg_target_mb
# Subtract a quarter of a megabyte to give some leeway for uploader limits
TARGET_BYTES=$((($TARGET_MB - 1) * 1024 * 1024 + 768 * 1024))
TARGET_BITRATE=$(($TARGET_BYTES * 8 / $RECORDING_LENGTH))

# Render speed
SPEEDHACK_AMOUNT=0.25
RECORD_FRAMERATE=5
# if low cpu set speedhack to 0.25
if [ "$_arg_slow_cpu" = "on" ]; then
    SPEEDHACK_AMOUNT=0.10
    RECORD_FRAMERATE=2
fi

# Starting seconds must be greater than 30
if [ "$STARTING_SEC" -lt $SMEAR_AMOUNT ]; then
    echo "Starting seconds must be greater than $SMEAR_AMOUNT"
    exit 1
fi

pushd /home/batman/openpilot

if [ ! -z "$JWT_AUTH" ]; then
    mkdir -p "$HOME"/.comma/
    echo "{\"access_token\": \"$JWT_AUTH\"}" > "$HOME"/.comma/auth.json
fi

# Start processes
tmux new-session -d -s clipper -n x11 "Xtigervnc :0 -geometry 1920x1080 -SecurityTypes None"
tmux new-window -n replay -t clipper: "TERM=xterm-256color faketime -m -f \"+0 x$SPEEDHACK_AMOUNT\" ./tools/replay/replay --ecam -s \"$SMEARED_STARTING_SEC\" \"$ROUTE\""
tmux new-window -n ui -t clipper: "faketime -m -f \"+0 x$SPEEDHACK_AMOUNT\" ./selfdrive/ui/ui"

# Pause replay and let it download the route
tmux send-keys -t clipper:replay Space
sleep 3

tmux send-keys -t clipper:replay Enter "$SMEARED_STARTING_SEC" Enter
tmux send-keys -t clipper:replay Space
sleep 1
tmux send-keys -t clipper:replay Space

# Generate and start overlay
echo "Route: $ROUTE , Starting Second: $STARTING_SEC, Clip Length: $RECORDING_LENGTH" > /tmp/overlay.txt
overlay /tmp/overlay.txt &

# Record with ffmpeg
mkdir -p "$VIDEO_CWD"
pushd "$VIDEO_CWD"
# Render with e2e_long
if [ "$RENDER_E2E_LONG" = "on" ]; then
    echo -n "1" > ~/.comma/params/d/EndToEndLong
else
    echo -n "0" > ~/.comma/params/d/EndToEndLong
fi
# Make sure the UI runs at full speed.
nice -n 10 ffmpeg -framerate "$RECORD_FRAMERATE" -video_size 1920x1080 -f x11grab -draw_mouse 0 -i :0.0 -ss "$SMEAR_AMOUNT" -vcodec libx264rgb -crf 0 -preset ultrafast -r 20 -filter:v "setpts=$SPEEDHACK_AMOUNT*PTS,scale=1920:1080" -y -t "$RECORDING_LENGTH" "$VIDEO_RAW_OUTPUT"
# The setup is no longer needed. Just transcode now.
cleanup
ffmpeg -y -i "$VIDEO_RAW_OUTPUT" -c:v libx264 -b:v "$TARGET_BITRATE" -pix_fmt yuv420p -preset medium -pass 1 -an -f MP4 /dev/null
ffmpeg -y -i "$VIDEO_RAW_OUTPUT" -c:v libx264 -b:v "$TARGET_BITRATE" -pix_fmt yuv420p -preset medium -pass 2 -movflags +faststart -f MP4 "$VIDEO_OUTPUT"

ctrl_c
