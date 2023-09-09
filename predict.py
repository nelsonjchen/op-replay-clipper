# "Prediction" interface for Cog ⚙️
# We just use this to run a program in an Nvidia GPU-accelerated environment
# https://github.com/replicate/cog/blob/main/docs/python.md

from cog import BasePredictor, Input, Path, BaseModel
import subprocess

from typing import Iterator, Optional
import os


class Predictor(BasePredictor):
    def setup(self) -> None:
        """There's nothing to setup!"""
        pass

    def predict(
        self,
        route: str = Input(
            description="Route/Segment ID",
            default="a2a0ccea32023010|2023-07-27--13-01-19",
        ),
        startSeconds: int = Input(
            description="Start time in seconds", ge=0, default=60
        ),
        lengthSeconds: int = Input(
            description="Length of clip in seconds", ge=5, le=60, default=10
        ),
        speedhackRatio: float = Input(
            description="Speedhack ratio", ge=0.2, le=3.0, default=1.5
        ),
        # debugCommand: str = Input(
        #     description="Debug command to run instead of clip", default=""
        # ),
    ) -> Path:
        """Run clip.sh with arguments."""

        # Start the shell command and capture its output
        command = [
            "./clip.sh",
            route,
            f"--start-seconds={startSeconds}",
            f"--length-seconds={lengthSeconds}",
            f"--smear-amount=5",
            f"--speedhack-ratio={speedhackRatio}",
            f"--nv-direct-encoding",
            f"--output=cog-clip.mp4",
        ]
        # if debugCommand != "":
        #     # Run bash with the command
        #     command = ["bash", "-c", debugCommand]
        env = {}
        env.update(os.environ)
        env.update({
            "DISPLAY": ":0",
            "SCALE": "1"
        })

        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE
         )

        # Read the output as it becomes available and yield it to the caller
        while True:
            output = process.stdout.readline()
            if output == b"" and process.poll() is not None:
                break

        return Path("./shared/cog-clip.mp4")
