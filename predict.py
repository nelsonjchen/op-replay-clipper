# "Prediction" interface for Cog ⚙️
# We just use this to run a program in an Nvidia GPU-accelerated environment
# https://github.com/replicate/cog/blob/main/docs/python.md

from cog import BasePredictor, Input, Path, BaseModel
import subprocess

from typing import Iterator, Optional
import os
import downloader


class Predictor(BasePredictor):
    def setup(self) -> None:
        """There's nothing to setup!"""
        pass

    def predict(
        self,
        route: str = Input(
            description="Route/Segment ID "
            " (⚠️ ROUTE MUST BE PUBLIC! You can set this temporarily in Connect)"
            ' (⚠️ Ensure all data from forward and wide cameras and "Logs" to be rendered have been uploaded; See README for more info)',
            default="a2a0ccea32023010|2023-07-27--13-01-19",
        ),
        startSeconds: int = Input(
            description="Start time in seconds", ge=0, default=50
        ),
        lengthSeconds: int = Input(
            description="Length of clip in seconds", ge=5, le=60, default=20
        ),
        smearAmount: int = Input(
            description="Smear amount (Let the video start this time before beginning recording, useful for making sure the radar △, if present, is rendered at the start if necessary)",
            ge=6,
            le=40,
            default=10,
        ),
        speedhackRatio: float = Input(
            description="Speedhack ratio (Higher ratio renders faster but renders may be more unstable and have artifacts) (Suggestion: 0.3-0.5 for jitter-free, 1-3 for fast renders, 4+ for buggy territory)",
            ge=0.3,
            le=7.0,
            default=1.0,
        ),
        fileSize: int = Input(
            description="Rough size of clip in MB.", ge=25, le=50, default=50
        ),
        # debugCommand: str = Input(
        #     description="Debug command to run instead of clip", default=""
        # ),
    ) -> Path:
        """Run clip.sh with arguments."""
        # Safety, remove the last clip
        if os.path.exists("./shared/cog-clip.mp4"):
            os.remove("./shared/cog-clip.mp4")

        # Download the route data
        downloader.downloadSegments(
            route_or_segment=route,
            start_seconds=startSeconds,
            length=lengthSeconds,
            smear_seconds=smearAmount,
            data_dir="./shared/data_dir",
        )

        # Get the full absolute path of `./shared/data_dir`
        data_dir = os.path.abspath("./shared/data_dir")

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
            f"--data-dir={data_dir}",
            f"--output=cog-clip.mp4",
        ]
        # if debugCommand != "":
        #     # Run bash with the command
        #     command = ["bash", "-c", debugCommand]
        env = {}
        env.update(os.environ)
        env.update({"DISPLAY": ":0", "SCALE": "1"})

        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE)

        # Read the output as it becomes available and yield it to the caller
        while True:
            output = process.stdout.readline()
            if output == b"" and process.poll() is not None:
                break
            if output:
                print(output)

        return Path("./shared/cog-clip.mp4")
