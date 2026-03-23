# "Prediction" interface for Cog

from __future__ import annotations

from cog import BasePredictor, Input, Path as CogPath

from clip_pipeline import ClipRequest, run_clip

MIN_LENGTH_SECONDS = 5
MAX_LENGTH_SECONDS = 300


class Predictor(BasePredictor):
    def setup(self) -> None:
        pass

    def predict(
        self,
        renderType: str = Input(
            description="UI renders with the comma openpilot UI. Forward, Wide, and Driver process the raw, segmented, and low-compatibility HEVC video files into a portable HEVC or H264 MP4 file. 360 and Forward Upon Wide variants remain available as before.",
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
            description='One comma connect URL or one route ID (e.g. "a2a0ccea32023010|2023-07-27--13-01-19").',
            default="https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488151496",
        ),
        startSeconds: int = Input(description="Start time in seconds for route-id input.", ge=0, default=50),
        lengthSeconds: int = Input(
            description="Length of clip in seconds for route-id input.",
            ge=MIN_LENGTH_SECONDS,
            le=MAX_LENGTH_SECONDS,
            default=20,
        ),
        smearAmount: int = Input(
            description="(UI only) Warm-up time before the visible clip start.",
            ge=5,
            le=40,
            default=5,
        ),
        speedhackRatio: float = Input(
            description="(UI only) Speedhack ratio for replay.",
            ge=0.1,
            le=7.0,
            default=1.0,
        ),
        metric: bool = Input(description="(UI only) Render in metric units (km/h).", default=False),
        forwardUponWideH: float = Input(
            description="(Forward Upon Wide only) Overlay height adjustment.",
            ge=1.0,
            le=3.0,
            default=2.2,
        ),
        fileSize: int = Input(description="Rough size of clip output in MB.", ge=5, le=200, default=9),
        fileFormat: str = Input(
            description="Auto, H.264, or HEVC.",
            choices=["auto", "h264", "hevc"],
            default="auto",
        ),
        jwtToken: str = Input(
            description="Optional JWT token for private routes.",
            default="",
        ),
        notes: str = Input(description="Notes field. Does not affect output.", default=""),
    ) -> CogPath:
        print("NOTES:")
        print(notes)
        print("")

        result = run_clip(
            ClipRequest(
                render_type=renderType,  # type: ignore[arg-type]
                route_or_url=route,
                start_seconds=startSeconds,
                length_seconds=lengthSeconds,
                target_mb=fileSize,
                file_format=fileFormat,  # type: ignore[arg-type]
                output_path="./shared/cog-clip.mp4",
                smear_seconds=smearAmount if renderType == "ui" else 0,
                jwt_token=jwtToken or None,
                metric=metric,
                speedhack_ratio=speedhackRatio,
                forward_upon_wide_h=forwardUponWideH,
                execution_context="cog",
                minimum_length_seconds=MIN_LENGTH_SECONDS,
                maximum_length_seconds=MAX_LENGTH_SECONDS,
                local_acceleration="auto",
                openpilot_dir="/home/batman/openpilot",
                qcam=False,
                headless=True,
            )
        )
        return CogPath(str(result.output_path))
