from pathlib import Path

from cog import BasePredictor, Input, Path as CogPath

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
            description="UI renders with the comma openpilot UI. Forward, Wide, and Driver process the raw, segmented, and low-compatibility HEVC video files into a portable HEVC or H264 MP4 file, are fast transcodes, and are great for quick previews. 360 requires viewing/uploading the video file in VLC or YouTube to pan around in a sphere or post-processing with software such as Insta360 Studio or similar software for reframing. Forward Upon Wide roughly overlays Forward video on Wide video for increased detail in Forward video. 360 Forward Upon Wide is 360 with Forward Upon Wide as the forward video and scales up to render at 8K for reframing with Insta360 Studio or similar software.",
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
            description='One full comma connect clip URL (e.g. https://connect.comma.ai/18277b1abce7bbe4/00000029--e1c8705a52/132/144). Public Access must be enabled or a valid JWT Token must be provided. All required files for the selected render type in Comma Connect must be uploaded from device. Please see the Quick Usage section of the README on GitHub at https://github.com/nelsonjchen/op-replay-clipper#quick-usage for instructions on generating an appropriate comma connect URL.',
            default="https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488151496",
        ),
        smearAmount: int = Input(
            description="(UI Render only) Smear amount (Let the video start this time before beginning recording, useful for making sure important UI state is present to be rendered at the visible start)",
            ge=5,
            le=40,
            default=5,
        ),
        forwardUponWideH: float = Input(
            description="(Forward Upon Wide Renders only) H-position of the forward video overlay on wide. Different devices can have different offsets from differing user mounting or factory calibration.",
            ge=1.0,
            le=3.0,
            default=2.2,
        ),
        fileSize: int = Input(description="Rough size of clip output in MB.", ge=5, le=200, default=9),
        fileFormat: str = Input(
            description="Auto, H.264, or HEVC (HEVC is 50-60 percent higher quality for its filesize but may not be compatible with all web browsers or devices). Auto, which is recommended, will choose HEVC for 360 renders and H.264 for all other renders.",
            choices=["auto", "h264", "hevc"],
            default="auto",
        ),
        jwtToken: str = Input(
            description='Optional JWT Token from https://jwt.comma.ai for non-"Public access" routes. DO NOT SHARE THIS TOKEN WITH ANYONE as https://jwt.comma.ai generates JWT tokens valid for 90 days and they are irrevocable. Please use the safer, optionally temporary, more granular, and revocable "Public Access" toggle option on comma connect if possible. For more info, please see https://github.com/nelsonjchen/op-replay-clipper#jwt-token-input .',
            default="",
        ),
        notes: str = Input(description="Notes Text field. Doesn't affect output. For your own reference.", default=""),
    ) -> CogPath:
        print("NOTES:")
        print(notes)
        print("")
        route = route_inputs.validate_connect_url(
            route,
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
