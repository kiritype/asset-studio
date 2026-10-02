"""Local YOLO segmentation adapter; no models are fetched here."""
from __future__ import annotations
import math
import numpy as np
import torch

REFERENCE_LABELS = ("nipples", "pussy", "penis", "anus", "testicles", "x-ray", "cross-section")

def _load_ultralytics(path: str):
    try:
        from ultralytics import YOLO
    except ImportError as error:
        raise RuntimeError("Censor detection requires the local 'ultralytics' runtime; no dependency was installed.") from error
    return YOLO(path)

def detect_selected_segmentation_masks(images: torch.Tensor, model_path: str, labels: tuple[str, ...], confidence: float, *, model_loader=_load_ultralytics) -> torch.Tensor:
    if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[0] < 1 or images.shape[1] < 1 or images.shape[2] < 1 or images.shape[-1] not in (3, 4) or not images.is_floating_point() or not torch.isfinite(images).all(): raise ValueError("images must be non-empty finite floating-point batched RGB or RGBA IMAGE tensor.")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1: raise ValueError("confidence must be a finite number between 0 and 1.")
    if not labels or any(item not in REFERENCE_LABELS for item in labels): raise ValueError("labels must contain one or more supported Censor labels.")
    detector = model_loader(model_path); height, width = images.shape[1:3]; masks=[]; labels_checked=False
    for image in images:
        rgb=image[..., :3].detach().to("cpu", dtype=torch.float32).clamp(0,1).numpy()
        source=np.ascontiguousarray((rgb[..., ::-1] * 255).round().astype(np.uint8))
        try: results=detector.predict(source=source, conf=float(confidence), retina_masks=True, verbose=False)
        except Exception as error: raise RuntimeError(f"Ultralytics segmentation inference failed: {error}") from error
        if len(results) != 1: raise RuntimeError("Ultralytics segmentation returned an unexpected result count.")
        result=results[0]; result_masks=getattr(getattr(result, "masks", None), "data", None); classes=getattr(getattr(result, "boxes", None), "cls", None); names=getattr(result, "names", {})
        if not labels_checked:
            missing=set(labels)-set(names.values())
            if missing: raise ValueError(f"configured labels are absent from segmentation model: {', '.join(sorted(missing))}")
            labels_checked=True
        mask=torch.zeros((height,width), device=images.device, dtype=images.dtype)
        if result_masks is not None:
            instances=torch.as_tensor(result_masks); classes=torch.as_tensor(classes) if classes is not None else None
            if instances.ndim != 3 or tuple(instances.shape[1:]) != (height,width) or classes is None or classes.numel() != instances.shape[0]: raise RuntimeError("Ultralytics segmentation returned incompatible masks/classes.")
            selected=[i for i,value in enumerate(classes.tolist()) if names.get(int(value), str(int(value))) in labels]
            if selected: mask=instances[selected].to(device=images.device).gt(0).any(dim=0).to(dtype=images.dtype)
        masks.append(mask)
    return torch.stack(masks)
