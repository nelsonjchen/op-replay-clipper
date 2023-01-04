#!/bin/bash
#
# Clipper Argbash
#
# ARG_OPTIONAL_SINGLE([start-seconds],[s],[Seconds to start at],[60])
# ARG_OPTIONAL_SINGLE([length-seconds],[l],[Clip length],[30])
# ARG_OPTIONAL_SINGLE([target-mb],[m],[Target converted file size in MB],[50])
# ARG_OPTIONAL_SINGLE([jwt-token],[j],[JWT Auth token to use (get token from https://jwt.comma.ai)])
# ARG_OPTIONAL_SINGLE([smear-amount],[],[Amount of seconds to smear the clip start by before recording starts],[10])
# ARG_OPTIONAL_SINGLE([ntfysh],[n],[ntfy.sh topic to post to when clip has completed rendering])
# ARG_OPTIONAL_SINGLE([speedhack-ratio],[r],[speedhack ratio for stable, non-jittery rendering],[0.3])
# ARG_OPTIONAL_SINGLE([video-cwd],[c],[video working and output directory],[./shared])
# ARG_OPTIONAL_SINGLE([vnc],[],[VNC Port for debugging, -1 will disable],[0])
# ARG_OPTIONAL_SINGLE([output],[o],[output clip name],[clip.mp4])
# ARG_OPTIONAL_BOOLEAN([metric],[],[Use metric system in the ui],[off])
# ARG_OPTIONAL_BOOLEAN([nv-direct-encoding],[],[Use an available Nvidia GPU to directly encode grabbed video],[off])
# ARG_POSITIONAL_SINGLE([route_id],[comma connect route id, segment id is ignored (hint, put this in quotes otherwise your shell might misinterpret the pipe) ])
# ARG_HELP([See README at https://github.com/nelsonjchen/op-replay-clipper/])
# ARGBASH_GO()
# needed because of Argbash --> m4_ignore([
### START OF CODE GENERATED BY Argbash v2.9.0 one line above ###
# Argbash is a bash code generator used to get arguments parsing right.
# Argbash is FREE SOFTWARE, see https://argbash.io for more info
# Generated online by https://argbash.io/generate


die()
{
	local _ret="${2:-1}"
	test "${_PRINT_HELP:-no}" = yes && print_help >&2
	echo "$1" >&2
	exit "${_ret}"
}


begins_with_short_option()
{
	local first_option all_short_options='slmjnrcoh'
	first_option="${1:0:1}"
	test "$all_short_options" = "${all_short_options/$first_option/}" && return 1 || return 0
}

# THE DEFAULTS INITIALIZATION - POSITIONALS
_positionals=()
# THE DEFAULTS INITIALIZATION - OPTIONALS
_arg_start_seconds="60"
_arg_length_seconds="30"
_arg_target_mb="50"
_arg_jwt_token=
_arg_smear_amount="10"
_arg_ntfysh=
_arg_speedhack_ratio="0.3"
_arg_video_cwd="./shared"
_arg_vnc="0"
_arg_output="clip.mp4"
_arg_metric="off"
_arg_nv_direct_encoding="off"


print_help()
{
	printf '%s\n' "See README at https://github.com/nelsonjchen/op-replay-clipper/"
	printf 'Usage: %s [-s|--start-seconds <arg>] [-l|--length-seconds <arg>] [-m|--target-mb <arg>] [-j|--jwt-token <arg>] [--smear-amount <arg>] [-n|--ntfysh <arg>] [-r|--speedhack-ratio <arg>] [-c|--video-cwd <arg>] [--vnc <arg>] [-o|--output <arg>] [--(no-)metric] [--(no-)nv-direct-encoding] [-h|--help] <route_id>\n' "$0"
	printf '\t%s\n' "<route_id>: comma connect route id, segment id is ignored (hint, put this in quotes otherwise your shell might misinterpret the pipe) "
	printf '\t%s\n' "-s, --start-seconds: Seconds to start at (default: '60')"
	printf '\t%s\n' "-l, --length-seconds: Clip length (default: '30')"
	printf '\t%s\n' "-m, --target-mb: Target converted file size in MB (default: '50')"
	printf '\t%s\n' "-j, --jwt-token: JWT Auth token to use (get token from https://jwt.comma.ai) (no default)"
	printf '\t%s\n' "--smear-amount: Amount of seconds to smear the clip start by before recording starts (default: '10')"
	printf '\t%s\n' "-n, --ntfysh: ntfy.sh topic to post to when clip has completed rendering (no default)"
	printf '\t%s\n' "-r, --speedhack-ratio: speedhack ratio for stable, non-jittery rendering (default: '0.3')"
	printf '\t%s\n' "-c, --video-cwd: video working and output directory (default: './shared')"
	printf '\t%s\n' "--vnc: VNC Port for debugging, -1 will disable (default: '0')"
	printf '\t%s\n' "-o, --output: output clip name (default: 'clip.mp4')"
	printf '\t%s\n' "--metric, --no-metric: Use metric system in the ui (off by default)"
	printf '\t%s\n' "--nv-direct-encoding, --no-nv-direct-encoding: Use an available Nvidia GPU to directly encode grabbed video (off by default)"
	printf '\t%s\n' "-h, --help: Prints help"
}


parse_commandline()
{
	_positionals_count=0
	while test $# -gt 0
	do
		_key="$1"
		case "$_key" in
			-s|--start-seconds)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_start_seconds="$2"
				shift
				;;
			--start-seconds=*)
				_arg_start_seconds="${_key##--start-seconds=}"
				;;
			-s*)
				_arg_start_seconds="${_key##-s}"
				;;
			-l|--length-seconds)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_length_seconds="$2"
				shift
				;;
			--length-seconds=*)
				_arg_length_seconds="${_key##--length-seconds=}"
				;;
			-l*)
				_arg_length_seconds="${_key##-l}"
				;;
			-m|--target-mb)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_target_mb="$2"
				shift
				;;
			--target-mb=*)
				_arg_target_mb="${_key##--target-mb=}"
				;;
			-m*)
				_arg_target_mb="${_key##-m}"
				;;
			-j|--jwt-token)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_jwt_token="$2"
				shift
				;;
			--jwt-token=*)
				_arg_jwt_token="${_key##--jwt-token=}"
				;;
			-j*)
				_arg_jwt_token="${_key##-j}"
				;;
			--smear-amount)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_smear_amount="$2"
				shift
				;;
			--smear-amount=*)
				_arg_smear_amount="${_key##--smear-amount=}"
				;;
			-n|--ntfysh)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_ntfysh="$2"
				shift
				;;
			--ntfysh=*)
				_arg_ntfysh="${_key##--ntfysh=}"
				;;
			-n*)
				_arg_ntfysh="${_key##-n}"
				;;
			-r|--speedhack-ratio)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_speedhack_ratio="$2"
				shift
				;;
			--speedhack-ratio=*)
				_arg_speedhack_ratio="${_key##--speedhack-ratio=}"
				;;
			-r*)
				_arg_speedhack_ratio="${_key##-r}"
				;;
			-c|--video-cwd)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_video_cwd="$2"
				shift
				;;
			--video-cwd=*)
				_arg_video_cwd="${_key##--video-cwd=}"
				;;
			-c*)
				_arg_video_cwd="${_key##-c}"
				;;
			--vnc)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_vnc="$2"
				shift
				;;
			--vnc=*)
				_arg_vnc="${_key##--vnc=}"
				;;
			-o|--output)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_output="$2"
				shift
				;;
			--output=*)
				_arg_output="${_key##--output=}"
				;;
			-o*)
				_arg_output="${_key##-o}"
				;;
			--no-metric|--metric)
				_arg_metric="on"
				test "${1:0:5}" = "--no-" && _arg_metric="off"
				;;
			--no-nv-direct-encoding|--nv-direct-encoding)
				_arg_nv_direct_encoding="on"
				test "${1:0:5}" = "--no-" && _arg_nv_direct_encoding="off"
				;;
			-h|--help)
				print_help
				exit 0
				;;
			-h*)
				print_help
				exit 0
				;;
			*)
				_last_positional="$1"
				_positionals+=("$_last_positional")
				_positionals_count=$((_positionals_count + 1))
				;;
		esac
		shift
	done
}


handle_passed_args_count()
{
	local _required_args_string="'route_id'"
	test "${_positionals_count}" -ge 1 || _PRINT_HELP=yes die "FATAL ERROR: Not enough positional arguments - we require exactly 1 (namely: $_required_args_string), but got only ${_positionals_count}." 1
	test "${_positionals_count}" -le 1 || _PRINT_HELP=yes die "FATAL ERROR: There were spurious positional arguments --- we expect exactly 1 (namely: $_required_args_string), but got ${_positionals_count} (the last one was: '${_last_positional}')." 1
}


assign_positional_args()
{
	local _positional_name _shift_for=$1
	_positional_names="_arg_route_id "

	shift "$_shift_for"
	for _positional_name in ${_positional_names}
	do
		test $# -gt 0 || break
		eval "$_positional_name=\${1}" || die "Error during argument parsing, possibly an Argbash bug." 1
		shift
	done
}

parse_commandline "$@"
handle_passed_args_count
assign_positional_args 1 "${_positionals[@]}"

# OTHER STUFF GENERATED BY Argbash

### END OF CODE GENERATED BY Argbash (sortof) ### ])
# [ <-- needed because of Argbash
# ] <-- needed because of Argbash


set -ex

# Cleanup processes for easy fast testing.
# Rely on Docker to clean up containers processes in production though
function cleanup() {
    tmux list-panes -s -t clipper -F "#{pane_pid} #{pane_current_command}" \
    | grep -v tmux | awk '{print $1}' | xargs kill -9 || true
}

function ctrl_c() {
    cleanup
    pkill -P $$ || true
}
# trap ctrl-c and call ctrl_c()
trap ctrl_c INT

# # Cleanup stale stuff from last run
cleanup

STARTING_SEC=$_arg_start_seconds
# Sometimes it takes a bit of time for openpilot drawing to settle in.
SMEAR_AMOUNT=$_arg_smear_amount
SMEARED_STARTING_SEC=$(($STARTING_SEC - $SMEAR_AMOUNT))
# SMEARED_STARTING_SEC must be greater than 0
if [ $SMEARED_STARTING_SEC -lt 0 ]; then
		SMEARED_STARTING_SEC=0
fi
RECORDING_LENGTH=$_arg_length_seconds
# Cleanup trailing segment count. Seconds is what matters
ROUTE=$(echo "$_arg_route_id" | sed -E 's/--[0-9]+$//g')
# Segment ID is the floor of the starting seconds divided by 60
SEGMENT_NUM=$(($STARTING_SEC / 60))
SEGMENT_ID="$ROUTE--$SEGMENT_NUM"
RENDER_METRIC_SYSTEM=$_arg_metric
NVIDIA_DIRECT_ENCODING=$_arg_nv_direct_encoding
JWT_AUTH=$_arg_jwt_token
VIDEO_CWD=$_arg_video_cwd
VIDEO_RAW_OUTPUT=clip_raw.mkv
VIDEO_OUTPUT=$_arg_output
# Target an appropiate bitrate of filesize of 8MB for the video length
TARGET_MB=$_arg_target_mb
# Subtract a quarter of a megabyte to give some leeway for uploader limits
TARGET_BYTES=$((($TARGET_MB - 1) * 1024 * 1024 + 768 * 1024))
TARGET_BITRATE=$(($TARGET_BYTES * 8 / $RECORDING_LENGTH))
VNC_PORT=$_arg_vnc

# URL Encode Route
URL_ROUTE=$(echo "$ROUTE" | sed 's/|/%7C/g')

# Get route info
if [ -n "$JWT_AUTH" ]; then
	ROUTE_INFO=$(curl --fail -H "Authorization: JWT $JWT_AUTH" https://api.commadotai.com/v1/route/$URL_ROUTE/)
else
	ROUTE_INFO=$(curl --fail https://api.commadotai.com/v1/route/$URL_ROUTE/)
fi

ROUTE_INFO_GIT_REMOTE=$(echo "$ROUTE_INFO" | jq -r '.git_remote')
ROUTE_INFO_GIT_BRANCH=$(echo "$ROUTE_INFO" | jq -r '.git_branch')
ROUTE_INFO_GIT_COMMIT=$(echo "$ROUTE_INFO" | jq -r '.git_commit' | cut -c1-8)
ROUTE_INFO_GIT_DIRTY=$(echo "$ROUTE_INFO" | jq -r '.git_dirty')

# Get platform of route
ROUTE_INFO_PLATFORM=$(echo "$ROUTE_INFO" | jq -r '.platform')

# Render speed
# RECORD_FRAMERATE = SPEEDHACK_AMOUNT * 20
SPEEDHACK_AMOUNT=$_arg_speedhack_ratio
RECORD_FRAMERATE=$(echo "($SPEEDHACK_AMOUNT * 20)/1" | bc)

pushd /home/batman/openpilot

if [ -n "$JWT_AUTH" ]; then
    mkdir -p "$HOME"/.comma/
    echo "{\"access_token\": \"$JWT_AUTH\"}" > "$HOME"/.comma/auth.json
fi

# Start processes
tmux new-session -d -s clipper -n x11 "Xtigervnc :0 -geometry 1920x1080 -SecurityTypes None -rfbport $VNC_PORT"
tmux new-window -n replay -t clipper: "TERM=xterm-256color faketime -m -f \"+0 x$SPEEDHACK_AMOUNT\" ./tools/replay/replay --ecam -s \"$SMEARED_STARTING_SEC\" \"$ROUTE\""
tmux new-window -n ui -t clipper: "faketime -m -f \"+0 x$SPEEDHACK_AMOUNT\" ./selfdrive/ui/ui"

# Pause replay and let it download the route
tmux send-keys -t clipper:replay Space

sleep 2
# Wait until netstat shows less than 2 connections from ./tools/replay process
while [ "$(netstat -tuplan | grep -E '443.*repl' | wc -l)" -gt 1 ]; do
		echo "Waiting for segments to download..."
		sleep 3
done

tmux send-keys -t clipper:replay Enter "$SMEARED_STARTING_SEC" Enter
tmux send-keys -t clipper:replay Space
sleep 1
tmux send-keys -t clipper:replay Space

popd

# Generate and start overlay
CLIP_DESC="Segment ID: $SEGMENT_ID, Starting Second: $STARTING_SEC, Clip Length: $RECORDING_LENGTH, \
$ROUTE_INFO_GIT_REMOTE, $ROUTE_INFO_GIT_BRANCH, $ROUTE_INFO_GIT_COMMIT, Dirty: \
$ROUTE_INFO_GIT_DIRTY, $ROUTE_INFO_PLATFORM"
echo "$CLIP_DESC" > /tmp/overlay.txt
overlay -o N -e 10 /tmp/overlay.txt &

# Record with ffmpeg
mkdir -p "$VIDEO_CWD"
pushd "$VIDEO_CWD"
# Use metric system in the ui
if [ "$RENDER_METRIC_SYSTEM" = "on" ]; then
	echo -n "1" > ~/.comma/params/d/IsMetric
else
	echo -n "0" > ~/.comma/params/d/IsMetric
fi
# Make sure the UI runs at full speed.
pwd

if [ "$NVIDIA_DIRECT_ENCODING" = "on" ]; then
	# Directly encode with nvidia hardware
	ffmpeg -framerate "$RECORD_FRAMERATE" -video_size 1920x1080 -f x11grab -draw_mouse 0 -i :0.0 -ss "$SMEAR_AMOUNT" -vcodec h264_nvenc -preset llhq -rc vbr_hq -cq 0 -b:v "$TARGET_BITRATE" -r 20 -filter:v "setpts=$SPEEDHACK_AMOUNT*PTS,scale=1920:1080" -y -t "$RECORDING_LENGTH" "$VIDEO_OUTPUT"
	cleanup
else
	nice -n 10 ffmpeg -framerate "$RECORD_FRAMERATE" -video_size 1920x1080 -f x11grab -draw_mouse 0 -i :0.0 -ss "$SMEAR_AMOUNT" -vcodec libx264rgb -crf 0 -preset ultrafast -r 20 -filter:v "setpts=$SPEEDHACK_AMOUNT*PTS,scale=1920:1080" -y -t "$RECORDING_LENGTH" "$VIDEO_RAW_OUTPUT"
	# The setup is no longer needed. Just transcode now.
	cleanup
	ffmpeg -y -i "$VIDEO_RAW_OUTPUT" -c:v libx264 -b:v "$TARGET_BITRATE" -pix_fmt yuv420p -preset medium -pass 1 -an -f MP4 /dev/null
	ffmpeg -y -i "$VIDEO_RAW_OUTPUT" -c:v libx264 -b:v "$TARGET_BITRATE" -pix_fmt yuv420p -preset medium -pass 2 -movflags +faststart -f MP4 "$VIDEO_OUTPUT"
fi

# Set mp4 metadata
AtomicParsley "$VIDEO_OUTPUT" --title "Segment ID: $SEGMENT_ID, Starting Sec: $STARTING_SEC" \
--description "$CLIP_DESC" \
--encodedBy "https://github.com/nelsonjchen/op-replay-clipper, $(git describe --all --long)" \
 --overWrite

ctrl_c

RENDER_COMPLETE_MESSAGE="Finished rendering $SEGMENT_ID to $VIDEO_OUTPUT."
# If _arg_ntfysh is defined, send a notification to a ntfy.sh topic
if [ ! -z "$_arg_ntfysh" ]; then
	curl -X POST -H "Title: Rendering Complete" -d "$RENDER_COMPLETE_MESSAGE" "https://ntfy.sh/$_arg_ntfysh"
fi
echo -e "$RENDER_COMPLETE_MESSAGE\n" "Please remember to include the segment ID if posting for comma to look at!\n" "\`$SEGMENT_ID\`"
