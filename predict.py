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
MAX_LENGTH_SECONDS = 180


class Predictor(BasePredictor):
    def setup(self) -> None:
        """There's nothing to setup!"""
        pass

    def predict(
        self,
        renderType: str = Input(
            description="Render Type. UI is slow. Forward, Wide, and Driver are fast transcodes; they are great for quick previews. 360 is slow and requires downloadin the video file in VLC or uploading to YouTube to pan around in a 🌐 sphere.",
            choices=["ui", "forward", "wide", "driver", "360"],
            default="ui",
        ),
        route: str = Input(
            description="comma connect URL (e.g. https://connect.comma.ai/fe18f736cb0d7813/1698620773416/1698620855707 ) OR route/segment ID (e.g. a2a0ccea32023010|2023-07-27--13-01-19)"
            " (⚠️ \"Public Access\" must be enabled and All Files must be uploaded. Please see the README for more info.)",
            default="a2a0ccea32023010|2023-07-27--13-01-19",
        ),
        startSeconds: int = Input(
            description=
            "Start time in seconds (Ignored if comma connect URL input is used)",
            ge=0,
            default=50
        ),
        lengthSeconds: int = Input(
            description="Length of clip in seconds (Ignored if comma connect URL input is used, however the minimum and maximum lengths are still enforced)", ge=MIN_LENGTH_SECONDS,
            le=MAX_LENGTH_SECONDS,
            default=20
        ),
        smearAmount: int = Input(
            description="(UI Render only) Smear amount (Let the video start this time before beginning recording, useful for making sure the radar △, if present, is rendered at the start if necessary)",
            ge=5,
            le=40,
            default=5,
        ),
        speedhackRatio: float = Input(
            description="(UI Render only) Speedhack ratio (Higher ratio renders faster but renders may be more unstable and have artifacts) (Suggestion: 0.3-0.5 for jitter-free, 1-3 for fast renders, 4+ for buggy territory)",
            ge=0.3,
            le=7.0,
            default=1.0,
        ),
        metric: bool = Input(
            description="(UI Render only) Render in metric units (km/h)", default=False
        ),
        fileSize: int = Input(
            description="Rough size of clip output in MB.", ge=10, le=100, default=25
        ),
        notes: str = Input(
            description="Notes Text field. Doesn't affect output. For your own reference.", default="",
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
            route_or_url=route, start_seconds=startSeconds, length_seconds=lengthSeconds
        )
        route = parsed_input_route_or_url.route
        startSeconds = parsed_input_route_or_url.start_seconds
        lengthSeconds = parsed_input_route_or_url.length_seconds

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

        if renderType == "ui":
            # Download the route data
            downloader.downloadSegments(
                route_or_segment=route,
                start_seconds=startSeconds,
                length=lengthSeconds,
                smear_seconds=smearAmount,
                data_dir=data_dir,
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
                f"--nv-hardware-rendering",
                f"--nv-hybrid-encoding",
                f"--data-dir={os.path.abspath(data_dir)}",
                f"--output=cog-clip.mp4",
            ]
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
                process.kill()
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

            downloader.downloadSegments(
                route_or_segment=route,
                start_seconds=startSeconds,
                length=lengthSeconds,
                smear_seconds=0,
                data_dir=data_dir,
                file_types=file_types,
            )

            # Start the shell command and capture its output
            ffmpeg_clip.make_ffmpeg_clip(
                render_type=renderType,
                data_dir=data_dir,
                route_or_segment=route,
                start_seconds=startSeconds,
                length_seconds=lengthSeconds,
                target_mb=fileSize,
                nvidia_hardware_rendering=True,
                output="./shared/cog-clip.mp4",
            )

            return Path("./shared/cog-clip.mp4")
