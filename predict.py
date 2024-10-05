# "Prediction" interface for Cog ⚙️
# We just use this to run a program in an Nvidia GPU-accelerated environment
# https://github.com/replicate/cog/blob/main/docs/python.md

from cog import BasePredictor, Input, Path, BaseModel
import subprocess

from typing import Iterator, Optional
import os
import downloader

import ffmpeg_clip
import route_or_url

MIN_LENGTH_SECONDS = 5
MAX_LENGTH_SECONDS = 300


class Predictor(BasePredictor):
    def setup(self) -> None:
        """There's nothing to setup!"""
        pass

    def predict(
        self,
        renderType: str = Input(
            description="UI renders with the comma openpilot UI. Forward, Wide, and Driver process the raw, segmented, and low-compatibility HEVC video files into a portable HEVC or H264 MP4 file, are fast transcodes, and are great for quick previews. 360 requires viewing/uploading the video file in VLC or YouTube to pan around in a 🌐 sphere or post-processing with software such as Insta360 Studio or similar software for reframing. Forward Upon Wide roughly overlays Forward video on Wide video for increased detail in Forward video. 360 Forward Upon Wide is 360 with Forward Upon Wide as the forward video and scales up to render at 8K for reframing with Insta360 Studio or similar software.",
            choices=[
                "ui",
                "forward",
                "wide",
                "driver",
                "360",
                "forward_upon_wide",
                "360_forward_upon_wide",
            ],
            default="ui",
        ),
        route: str = Input(
            description='One 🔗 comma connect URL (e.g. https://connect.comma.ai/18277b1abce7bbe4/00000029--e1c8705a52/132/144, this is the preferred input method and includes dongle ID with start/end times.) OR one #️⃣ route ID (e.g. a2a0ccea32023010|2023-07-27--13-01-19. Note that any segment ID \"--\" appended to the end will be ignored as\"startSecond\" is used instead, but route id portion of input will still accepted)'
            ' (⚠️ "Public Access" must be enabled or a valid JWT Token must be provided.'
            " All required files for render type in Comma Connect must be uploaded from device."
            " Please see the Quick Usage section of the README on GitHub at https://github.com/nelsonjchen/op-replay-clipper#quick-usage for instructions on generating an appropiate comma connect URL.)",
            default="https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488151496",
        ),
        startSeconds: int = Input(
            description="Start time in seconds for #️⃣ Route ID route input only. (🔗 comma connect URL already has the start time embedded in it and this input will be ignored in favor of that) ",
            ge=0,
            default=50,
        ),
        lengthSeconds: int = Input(
            description="Length of clip in seconds #️⃣ Route ID route input only. (🔗 comma connect URL already has the length time indirectly embedded in it from the embedded end time and this input will be ignored in favor of that. The minimum and maximum length will still be enforced)"
           , ge=MIN_LENGTH_SECONDS,
            le=MAX_LENGTH_SECONDS,
            default=20,
        ),
        smearAmount: int = Input(
            description="(UI Render only) Smear amount (Let the video start this time before beginning recording, useful for making sure the radar triangle (△), if not present, is present to be rendered at the start if necessary)",
            ge=5,
            le=40,
            default=5,
        ),
        speedhackRatio: float = Input(
            description="(UI Render only) Speedhack ratio (Higher ratio renders faster but renders may be more unstable and have artifacts) (Suggestion: 0.1-0.3 for jitter-free, 1-3 for fast renders). WARNING: Too low of a speed hack ratio may cause the render to exceed 10 minutes which is the max Replicate will allow for a single run. Please use 1.0 for everyday use.",
            ge=0.1,
            le=7.0,
            default=1.0,
        ),
        metric: bool = Input(
            description="(UI Render only) Render in metric units (km/h)", default=False
        ),
        forwardUponWideH: float = Input(
            description="(Forward Upon Wide Renders only) H-position of the forward video overlay on wide. Different devices can have different offsets from differing user mounting or factory calibration.",
            ge=1.0,
            le=3.0,
            default=2.2,
        ),
        fileSize: int = Input(
            description="Rough size of clip output in MB.", ge=10, le=200, default=25
        ),
        fileFormat: str = Input(
            description="Auto, H.264, or HEVC (HEVC is 50-60 percent higher quality for its filesize but may not be compatible with all web browsers or devices). Auto, which is recommended, will choose HEVC for 360 renders and H.264 for all other renders.",
            choices=[
                "auto",
                "h264",
                "hevc",
            ],
            default="auto",
        ),
        jwtToken: str = Input(
            description='Optional JWT Token from https://jwt.comma.ai for non-"Public access" routes. ⚠️ DO NOT SHARE THIS TOKEN WITH ANYONE as https://jwt.comma.ai generates JWT tokens valid for 90 days and they are irrevocable. Please use the safer, optionally temporary, more granular, and revocable "Public Access" toggle option on comma connect if possible. For more info, please see https://github.com/nelsonjchen/op-replay-clipper#jwt-token-input .',
            default="",
        ),
        notes: str = Input(
            description="Notes Text field. Doesn't affect output. For your own reference.",
            default="",
        ),
        # debugCommand: str = Input(
        #     description="Debug command to run instead of clip", default=""
        # ),
    ) -> Path:
        # Safety, remove the last clip
        if os.path.exists("./shared/cog-clip.mp4"):
            os.remove("./shared/cog-clip.mp4")

        # Print the notes
        print("NOTES:")
        print(notes)
        print("")

        parsed_input_route_or_url = route_or_url.parseRouteOrUrl(
            route_or_url=route,
            start_seconds=startSeconds,
            length_seconds=lengthSeconds,
            jwt_token=jwtToken,
        )
        route = parsed_input_route_or_url.route
        startSeconds = parsed_input_route_or_url.start_seconds
        lengthSeconds = parsed_input_route_or_url.length_seconds

        # Set filesize to be 1 less megabyte than the input. Discord only allows 25MB but sometimes the file is slightly larger than 25MB when set to 25MB.
        fileSize = fileSize - 1

        # Enforce the minimum and maximum lengths
        if lengthSeconds < MIN_LENGTH_SECONDS:
            raise ValueError(
                f"Length must be at least {MIN_LENGTH_SECONDS} seconds. Got {lengthSeconds} seconds."
            )
        if lengthSeconds > MAX_LENGTH_SECONDS:
            raise ValueError(
                f"Length must be at most {MAX_LENGTH_SECONDS} seconds. Got {lengthSeconds} seconds."
            )

        # Get the dongle ID from the route. It's everything before the first pipe.
        dongleID = route.split("|")[0]

        # Partition the data dir by the dongle ID from the route
        data_dir = os.path.join("./shared/data_dir", dongleID)

        # If the file format is auto, set it to HEVC if the render type is 360
        if fileFormat == "auto":
            if renderType == "360" or renderType == "360_forward_upon_wide":
                fileFormat = "hevc"
            else:
                fileFormat = "h264"

        if renderType == "ui":
            # Download the route data
            downloader.downloadSegments(
                route_or_segment=route,
                start_seconds=startSeconds,
                length=lengthSeconds,
                smear_seconds=smearAmount,
                data_dir=data_dir,
                jwt_token=jwtToken,
            )
            # Start the shell command and capture its output
            command = [
                # Run with GNU timeout to prevent runaway processes
                "timeout",
                "10m",
                "./clip.sh",
                route,
                f"--start-seconds={startSeconds}",
                f"--length-seconds={lengthSeconds}",
                f"--smear-amount={smearAmount}",
                f"--speedhack-ratio={speedhackRatio}",
                f"--target-mb={fileSize}",
                f"--format={fileFormat}",
                f"--nv-hybrid-encoding",
                f"--data-dir={os.path.abspath(data_dir)}",
                f"--output=cog-clip.mp4",
            ]
            # Check if we're inside WSL2 or nested in via `uname` and
            # don't append --nv-hardware-rendering if we are
            if b"microsoft-standard-WSL2" not in subprocess.check_output(
                ["uname", "--kernel-release"]
            ):
                command.append("--nv-hardware-rendering")

            if jwtToken:
                command.append(f"--jwt-token={jwtToken}")

            if metric:
                command.append("--metric")
            # if debugCommand != "":
            #     # Run bash with the command
            #     command = ["bash", "-c", debugCommand]
            env = {}
            env.update(os.environ)
            env.update({"DISPLAY": ":0", "SCALE": "1"})

            process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE)

            # Read the output as it becomes available and yield it to the caller
            try:
                while True:
                    proc_output = process.stdout.readline()
                    if proc_output == b"" and process.poll() is not None:
                        break
                    if proc_output:
                        print(proc_output)
            except KeyboardInterrupt:
                try:
                    process.kill()
                except Exception as e:
                    print(f"Failed to kill the process: {e}")
                try:
                    subprocess.run(["tmux", "kill-session", "-t", "clipper"], check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Failed to kill the tmux session 'clipper': {e}")
                except Exception as e:
                    print(f"An error occurred while trying to kill the tmux session 'clipper': {e}")
                raise

            return Path("./shared/cog-clip.mp4")

        else:
            # Download the route data
            if renderType == "360":
                file_types = ["ecameras", "dcameras"]
            elif renderType == "forward":
                file_types = ["cameras"]
            elif renderType == "wide":
                file_types = ["ecameras"]
            elif renderType == "driver":
                file_types = ["dcameras"]
            # Non-comma.ai origin render types
            elif renderType == "forward_upon_wide":
                file_types = ["ecameras", "cameras"]
            elif renderType == "360_forward_upon_wide":
                file_types = ["ecameras", "dcameras", "cameras"]

            downloader.downloadSegments(
                route_or_segment=route,
                start_seconds=startSeconds,
                length=lengthSeconds,
                smear_seconds=0,
                data_dir=data_dir,
                file_types=file_types,
                jwt_token=jwtToken,
            )

            # Start the shell command and capture its output
            ffmpeg_clip.make_ffmpeg_clip(
                render_type=renderType,
                data_dir=data_dir,
                route_or_segment=route,
                start_seconds=startSeconds,
                length_seconds=lengthSeconds,
                target_mb=fileSize,
                format=fileFormat,
                nvidia_hardware_rendering=True,
                forward_upon_wide_h=forwardUponWideH,
                output="./shared/cog-clip.mp4",
            )

            return Path("./shared/cog-clip.mp4")
