import tempfile
from pathlib import Path

from cog import BasePredictor, Input, Path as CogPath

from core.rf_detr_runtime import (
    DEFAULT_RF_DETR_MODEL_ID,
    ensure_python_nvidia_libs_preferred,
    sync_python_nvidia_runtime_libs_to_system,
    supported_rf_detr_model_ids,
)
from core.rf_detr_repro import bundle_repro_artifacts, run_rf_detr_repro

ensure_python_nvidia_libs_preferred()


class Predictor(BasePredictor):
    def setup(self) -> None:
        sync_python_nvidia_runtime_libs_to_system()

    def predict(
        self,
        media: CogPath = Input(description="Input still image or short video for RF-DETR repro."),
        modelId: str = Input(
            description="RF-DETR segmentation model to load.",
            choices=supported_rf_detr_model_ids(),
            default=DEFAULT_RF_DETR_MODEL_ID,
        ),
        device: str = Input(
            description="Device to request for RF-DETR inference.",
            choices=["auto", "cpu", "cuda", "mps"],
            default="auto",
        ),
        threshold: float = Input(description="Detection threshold.", ge=0.05, le=0.95, default=0.4),
        maxFrames: int = Input(description="Maximum number of video frames to process.", ge=1, le=24, default=8),
        cropMode: str = Input(
            description="Crop mode before inference.",
            choices=["full", "left_half", "right_half", "center_square"],
            default="full",
        ),
        writeOverlayVideo: bool = Input(description="Write a tiny overlay MP4 when the input is a video.", default=True),
    ) -> CogPath:
        media_path = Path(media)
        with tempfile.TemporaryDirectory(prefix="rf-detr-repro-") as tmpdir:
            output_dir = Path(tmpdir) / "artifacts"
            run_rf_detr_repro(
                input_path=media_path,
                output_dir=output_dir,
                model_id=modelId,
                requested_device=device,
                threshold=threshold,
                max_frames=maxFrames,
                crop_mode=cropMode,
                write_overlay_video=writeOverlayVideo,
            )
            bundle_file = tempfile.NamedTemporaryFile(
                prefix="rf-detr-repro-artifacts-",
                suffix=".zip",
                delete=False,
            )
            bundle_file.close()
            bundled = bundle_repro_artifacts(output_dir, Path(bundle_file.name))
            return CogPath(bundled)
