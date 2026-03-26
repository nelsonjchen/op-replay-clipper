import os
from pathlib import Path

from cog import BasePredictor, Input, Path as CogPath, Secret

from core import route_inputs
from core.clip_orchestrator import ClipRequest, run_clip
from core.openpilot_config import default_image_openpilot_root

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
        route: Secret = Input(
            description="One full https://connect.comma.ai/... clip URL.",
            default="https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488151496",
        ),
        smearAmount: int = Input(
            description="(UI only) Warm-up time before the visible clip start.",
            ge=5,
            le=40,
            default=5,
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
        route_text = route.get_secret_value() or ""
        route = route_inputs.validate_connect_url(
            route_text,
            error_message="Replicate/Cog route input must be a full https://connect.comma.ai/... clip URL.",
        )

        result = run_clip(
            ClipRequest(
                render_type=renderType,  # type: ignore[arg-type]
                route_or_url=route,
                start_seconds=0,
                length_seconds=0,
                target_mb=fileSize,
                file_format=fileFormat,  # type: ignore[arg-type]
                output_path="./shared/cog-clip.mp4",
                smear_seconds=smearAmount if renderType == "ui" else 0,
                jwt_token=jwtToken or None,
                metric=metric,
                forward_upon_wide_h=forwardUponWideH,
                execution_context="cog",
                minimum_length_seconds=MIN_LENGTH_SECONDS,
                maximum_length_seconds=MAX_LENGTH_SECONDS,
                local_acceleration="auto",
                openpilot_dir=default_image_openpilot_root(),
                qcam=False,
                headless=True,
            )
        )
        return Path(result.output_path)
