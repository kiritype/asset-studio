"""Local, opt-in character-mask detection backends.

The package deliberately has no model downloader.  Its first backend uses an
already installed Ultralytics *segmentation* model and selects every COCO
``person`` instance.  This is a concrete detector path, but it is not a claim
that every illustration is recognised as a person.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import torch


PERSON_CLASS_ID = 0


def _validate_images(images: torch.Tensor) -> None:
    if not isinstance(images, torch.Tensor) or images.ndim != 4:
        raise ValueError("images must be a tensor shaped [batch, height, width, channels].")
    if images.shape[0] < 1 or images.shape[1] < 1 or images.shape[2] < 1:
        raise ValueError("images must contain at least one non-empty image.")
    if images.shape[-1] not in (3, 4):
        raise ValueError("images must have three RGB or four RGBA channels.")
    if not images.is_floating_point() or not torch.isfinite(images).all():
        raise ValueError("images must contain only finite floating-point values.")


def _validate_confidence(confidence: float) -> float:
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be a finite number between 0 and 1.")
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be a finite number between 0 and 1.")
    return float(confidence)


def _load_local_ultralytics_model(model_path: str):
    """Load only a caller-resolved local file; Ultralytics receives no URL/name."""
    try:
        from ultralytics import YOLO
    except ImportError as error:
        raise RuntimeError(
            "Ultralytics character segmentation requires the 'ultralytics' Python "
            "package in this ComfyUI environment. No dependency was installed."
        ) from error
    return YOLO(model_path)


def _ultralytics_bgr_uint8(image: torch.Tensor):
    """Convert a ComfyUI RGB float IMAGE pixel to Ultralytics ndarray input.

    Ultralytics expects an ndarray source in HWC BGR ``uint8`` form, scaled to
    0--255. Passing ComfyUI's RGB float IMAGE directly would make its
    predictor flip already-RGB values and divide them by 255 a second time.
    """
    return (
        image[..., :3]
        .detach()
        .to("cpu", dtype=torch.float32)
        .clamp(0, 1)
        .mul(255)
        .round()
        .to(dtype=torch.uint8)
        .flip(-1)
        .contiguous()
        .numpy()
    )


def detect_ultralytics_person_masks(
    images: torch.Tensor,
    model_path: str,
    confidence: float,
    *,
    model_loader: Callable[[str], object] = _load_local_ultralytics_model,
) -> torch.Tensor:
    """Return a foreground mask for all local-COCO-person segmentation instances.

    ``retina_masks=True`` requests masks at the source image dimensions.  A
    backend returning another shape is rejected instead of being silently
    resized, because alpha application must use a pixel-aligned foreground.
    """
    _validate_images(images)
    confidence = _validate_confidence(confidence)
    if not isinstance(model_path, str) or not model_path:
        raise ValueError("segmentation_model must resolve to a local readable model file.")

    model = model_loader(model_path)
    masks: list[torch.Tensor] = []
    height, width = images.shape[1:3]
    for image in images:
        bgr_uint8 = _ultralytics_bgr_uint8(image)
        try:
            results = model.predict(
                source=bgr_uint8,
                classes=[PERSON_CLASS_ID],
                conf=confidence,
                retina_masks=True,
                verbose=False,
            )
        except Exception as error:
            raise RuntimeError(f"Ultralytics segmentation inference failed: {error}") from error
        if len(results) != 1:
            raise RuntimeError("Ultralytics segmentation returned an unexpected result count.")
        result_masks = getattr(results[0], "masks", None)
        if result_masks is None or getattr(result_masks, "data", None) is None:
            raise RuntimeError(
                "No person segmentation was detected; alpha was not changed. "
                "Use a suitable segmentation model or supply character_mask explicitly."
            )
        instances = torch.as_tensor(result_masks.data)
        if instances.ndim != 3 or tuple(instances.shape[1:]) != (height, width):
            raise RuntimeError(
                "Ultralytics segmentation mask dimensions do not match the input image; "
                "automatic resizing is not applied."
            )
        if instances.shape[0] == 0:
            raise RuntimeError(
                "No person segmentation was detected; alpha was not changed. "
                "Use a suitable segmentation model or supply character_mask explicitly."
            )
        masks.append(instances.to(device=images.device).gt(0).any(dim=0).to(dtype=images.dtype))
    return torch.stack(masks)
