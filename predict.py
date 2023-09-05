# "Prediction" interface for Cog ⚙️
# We just use this to run a program in an Nvidia GPU-accelerated environment
# https://github.com/replicate/cog/blob/main/docs/python.md

from cog import BasePredictor, Input, Path, BaseModel
import subprocess

from typing import Iterator, Optional


class Output(BaseModel):
    running_log: str
    output_clip: Optional[Path]


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
            description="Length of clip in seconds", ge=10, le=60, default=30
        ),
        speedhackRatio: float = Input(
            description="Speedhack ratio", ge=0.2, le=3.0, default=1.5
        ),
    ) -> Output:
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
        process = subprocess.Popen(
            command,
            env={
                "DISPLAY": ":0",
                "SCALE": "1"
            },
            stdout=subprocess.PIPE
         )

        running_log = ""

        # Read the output as it becomes available and yield it to the caller
        while True:
            output = process.stdout.readline()
            if output == b"" and process.poll() is not None:
                break
            if output:
                running_log += output.decode("utf-8")


        return Output(
            running_log=running_log, output_clip=Path("./shared/cog-clip.mp4")
        )
