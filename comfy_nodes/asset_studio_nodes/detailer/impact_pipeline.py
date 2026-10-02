"""Optional adapter for the Impact Pack detailer pipeline.

The adapter is deliberately late-bound: installing this AssetStudio package does
not import Impact Pack, download detector weights, or make ComfyUI fail to load.
"""

from __future__ import annotations

import importlib


STAGES = ("face", "eye", "mouth", "hand")
REQUIRED_CLASSES = ("UltralyticsDetectorProvider", "SAMLoader", "ToDetailerPipe", "FaceDetailerPipe")


def _classes():
    try:
        mappings = importlib.import_module("nodes").NODE_CLASS_MAPPINGS
    except (ImportError, AttributeError) as exc:
        raise RuntimeError("Impact Pack node registry is unavailable; install and enable ComfyUI-Impact-Pack and Impact Subpack.") from exc
    missing = [name for name in REQUIRED_CLASSES if name not in mappings]
    if missing:
        raise RuntimeError("Missing Impact detailer classes: " + ", ".join(missing) + ". Install/enable ComfyUI-Impact-Pack and Impact Subpack.")
    return mappings


def _first(value, label: str):
    if not isinstance(value, (tuple, list)) or not value:
        raise RuntimeError(f"Impact {label} returned no output.")
    return value[0]


class ImpactPipeline:
    """Executes the reference Face→Eye→Mouth→Hand pipeline in order."""

    def __init__(self, classes=None):
        self.classes = classes if classes is not None else _classes()
        missing = [name for name in REQUIRED_CLASSES if name not in self.classes]
        if missing:
            raise RuntimeError("Missing Impact detailer classes: " + ", ".join(missing) + ". Install/enable ComfyUI-Impact-Pack and Impact Subpack.")

    def run_stage(self, image, stage: str, detector_model: str, sam_model: str, model, clip, vae, positive, negative, settings: dict):
        if stage not in STAGES:
            raise ValueError(f"Unknown detail stage: {stage}")
        if not isinstance(detector_model, str) or not detector_model.strip() or not isinstance(sam_model, str) or not sam_model.strip():
            raise ValueError(f"{stage} detector and SAM model names must be non-empty strings.")
        provider = self.classes["UltralyticsDetectorProvider"]()
        detector = provider.doit(detector_model)
        bbox_detector = _first(detector, "UltralyticsDetectorProvider")
        segm_detector = detector[1] if len(detector) > 1 else None
        sam_model_opt = _first(self.classes["SAMLoader"]().load_model(sam_model, "AUTO"), "SAMLoader")
        pipe = _first(self.classes["ToDetailerPipe"]().doit(
            model=model, clip=clip, vae=vae, positive=positive, negative=negative,
            wildcard="", bbox_detector=bbox_detector, sam_model_opt=sam_model_opt,
            segm_detector_opt=segm_detector,
        ), "ToDetailerPipe")
        result = self.classes["FaceDetailerPipe"]().doit(image=image, detailer_pipe=pipe, **settings)
        return _first(result, "FaceDetailerPipe")


def run_pipeline(image, enabled: dict[str, bool], detector_models: dict[str, str], sam_model: str, model, clip, vae, positive, negative, settings: dict, pipeline=None):
    """Return the sequentially detailed image; disabled stages do not load deps."""
    if set(enabled) != set(STAGES) or set(detector_models) != set(STAGES):
        raise ValueError("enabled and detector_models must contain face, eye, mouth, and hand.")
    current = image
    active = [stage for stage in STAGES if enabled[stage] is True]
    if any(type(enabled[stage]) is not bool for stage in STAGES):
        raise ValueError("detail stage flags must be booleans.")
    if not active:
        return current
    runner = pipeline or ImpactPipeline()
    for stage in active:
        current = runner.run_stage(current, stage, detector_models[stage], sam_model, model, clip, vae, positive, negative, settings)
    return current
