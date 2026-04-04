import os
from pathlib import Path

from cog import BasePredictor, Input, Path as CogPath

from core import route_inputs
from core.clip_orchestrator import ClipRequest, is_smear_render_type, run_clip
from core.openpilot_config import default_image_openpilot_root

MIN_LENGTH_SECONDS = 5
MAX_LENGTH_SECONDS = 300
HOSTED_ANONYMIZATION_PROFILE_CHOICES = [
    "none",
    "driver unchanged, passenger hidden",
    "driver unchanged, passenger face swap",
    "driver face swap, passenger hidden",
    "driver face swap, passenger face swap",
]

GUI_ANONYMIZATION_PROFILE_MAP = {
    "none": ("none", "driver_face_swap_passenger_face_swap"),
    "driver unchanged, passenger hidden": ("facefusion", "driver_unchanged_passenger_hidden"),
    "driver unchanged, passenger face swap": ("facefusion", "driver_unchanged_passenger_face_swap"),
    "driver unchanged, passenger pixelize": ("facefusion", "driver_unchanged_passenger_pixelize"),
    "driver face swap, passenger hidden": ("facefusion", "driver_face_swap_passenger_hidden"),
    "driver face swap, passenger pixelize": ("facefusion", "driver_face_swap_passenger_pixelize"),
    "driver face swap, passenger face swap": ("facefusion", "driver_face_swap_passenger_face_swap"),
}


def default_facefusion_root(repo_root: Path) -> Path:
    candidates = [
        Path(os.environ.get("FACEFUSION_ROOT", "")).expanduser() if os.environ.get("FACEFUSION_ROOT") else None,
        repo_root / ".cache/facefusion",
        Path("/.cache/facefusion"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate.resolve()
    return (repo_root / ".cache/facefusion").resolve()


class Predictor(BasePredictor):
    def setup(self) -> None:
        repo_root = Path(__file__).resolve().parent
        os.environ["FACEFUSION_ROOT"] = str(default_facefusion_root(repo_root))
        os.environ.setdefault("DRIVER_FACE_SOURCE_IMAGE", str(repo_root / "assets/driver-face-donors/generic-donor-clean-shaven.jpg"))
        os.environ.setdefault("DRIVER_FACE_DONOR_BANK_DIR", str(repo_root / "assets/driver-face-donors"))
        # RF-DETR on Replicate/Cog is more stable on CPU today, while video
        # transcode can still use NVENC independently.
        os.environ.setdefault("DRIVER_FACE_BENCHMARK_RF_DETR_DEVICE", "cpu")

    def predict(
        self,
        renderType: str = Input(
            description="UI renders with the comma openpilot UI. Forward, Wide, and Driver process the raw, segmented, and low-compatibility HEVC video files into a portable HEVC or H264 MP4 file, are fast transcodes, and are great for quick previews. 360 requires viewing/uploading the video file in VLC or YouTube to pan around in a sphere or post-processing with software such as Insta360 Studio or similar software for reframing. Forward Upon Wide roughly overlays Forward video on Wide video for increased detail in Forward video. 360 Forward Upon Wide is 360 with Forward Upon Wide as the forward video and scales up to render at 8K for reframing with Insta360 Studio or similar software.",
            choices=[
                "ui",
                "ui-alt",
                "driver-debug",
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
            description="(UI only) Seconds of hidden preroll before the visible clip start. Increase this if important UI state is missing at the beginning of the clip.",
            ge=3,
            le=40,
            default=3,
        ),
        fileSize: int = Input(description="Target output size in MB. Actual size may vary.", ge=5, le=200, default=9),
        fileFormat: str = Input(
            description="Output codec. Auto is recommended: it uses HEVC for 360 renders and H.264 for the others. HEVC usually gives better quality for the size, but some browsers and devices do not play it well.",
            choices=["auto", "h264", "hevc"],
            default="auto",
        ),
        jwtToken: str = Input(
            description="Optional JWT Token from https://jwt.comma.ai for routes without Public Access. Do not share this token: it is valid for 90 days and cannot be revoked early. Public Access is usually the safer option.",
            default="",
        ),
        anonymizationProfile: str = Input(
            description="Seat anonymization strategy for driver-camera renders. Recommended values are: none, driver unchanged/passenger hidden, driver unchanged/passenger face swap, driver face swap/passenger hidden, driver face swap/passenger face swap.",
            choices=HOSTED_ANONYMIZATION_PROFILE_CHOICES,
            default="none",
        ),
        passengerRedactionStyle: str = Input(
            description="How to hide the passenger when the chosen anonymization profile uses passenger hidden mode.",
            choices=["blur", "silhouette"],
            default="blur",
        ),
        notes: str = Input(description="Optional notes for your own reference. Does not affect output.", default=""),
    ) -> CogPath:
        print("NOTES:")
        print(notes)
        print("")
        route = route_inputs.validate_connect_url(
            route,
            error_message="Replicate/Cog route input must be a full https://connect.comma.ai/... clip URL.",
        )

        try:
            driver_face_anonymization, driver_face_profile = GUI_ANONYMIZATION_PROFILE_MAP[anonymizationProfile]
        except KeyError as exc:
            raise ValueError(f"Unsupported anonymization profile: {anonymizationProfile}") from exc
        result = run_clip(
            ClipRequest(
                render_type=renderType,  # type: ignore[arg-type]
                route_or_url=route,
                start_seconds=0,
                length_seconds=0,
                target_mb=fileSize,
                file_format=fileFormat,  # type: ignore[arg-type]
                output_path="./shared/cog-clip.mp4",
                smear_seconds=smearAmount if is_smear_render_type(renderType) else 0,  # type: ignore[arg-type]
                jwt_token=jwtToken or None,
                forward_upon_wide_h="auto",
                execution_context="cog",
                minimum_length_seconds=MIN_LENGTH_SECONDS,
                maximum_length_seconds=MAX_LENGTH_SECONDS,
                local_acceleration="auto",
                openpilot_dir=default_image_openpilot_root(),
                qcam=False,
                headless=True,
                driver_face_anonymization=driver_face_anonymization,  # type: ignore[arg-type]
                driver_face_profile=driver_face_profile,  # type: ignore[arg-type]
                passenger_redaction_style=passengerRedactionStyle,  # type: ignore[arg-type]
                driver_face_selection="auto_best_match",
            )
        )
        return Path(result.output_path)
