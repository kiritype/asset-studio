"""Pure tensor operations for masking sensitive regions."""

from __future__ import annotations

import torch
import torch.nn.functional as functional


def _validate(image: torch.Tensor, detection_mask: torch.Tensor, intensity: int) -> None:
    if not isinstance(image, torch.Tensor) or image.ndim != 4 or image.shape[0] < 1 or image.shape[-1] not in (3, 4) or not image.is_floating_point():
        raise ValueError("image must be a non-empty floating-point batched RGB or RGBA IMAGE tensor.")
    if not isinstance(detection_mask, torch.Tensor) or detection_mask.ndim != 3 or not detection_mask.is_floating_point() or tuple(detection_mask.shape) != tuple(image.shape[:3]):
        raise ValueError("detection_mask must be a floating-point MASK exactly matching image batch and pixels.")
    if not torch.isfinite(image).all() or not torch.isfinite(detection_mask).all():
        raise ValueError("image and detection_mask must contain only finite values.")
    if not isinstance(intensity, int) or isinstance(intensity, bool) or not 1 <= intensity <= 128:
        raise ValueError("intensity must be an integer between 1 and 128.")


def apply_censor(image: torch.Tensor, detection_mask: torch.Tensor, treatment: str, intensity: int, enabled: bool = True) -> torch.Tensor:
    """Reference-aligned mosaic, feathered white, or solid white treatment."""
    _validate(image, detection_mask, intensity)
    if treatment not in ("mosaic", "white", "white_solid"):
        raise ValueError("treatment must be mosaic, white, or white_solid.")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean.")
    if not enabled:
        return image
    # Reference SEGS Extractor uses dilation = intensity * 2.
    aligned_mask = detection_mask.to(device=image.device, dtype=image.dtype)
    expanded = functional.max_pool2d(aligned_mask.unsqueeze(1), kernel_size=intensity * 2 + 1, stride=1, padding=intensity).squeeze(1)
    mask = expanded.clamp(0, 1).unsqueeze(-1).to(dtype=image.dtype)
    rgb = image[..., :3]
    if treatment in ("white", "white_solid"):
        replacement = torch.ones_like(rgb)
    else:
        channels_first = rgb.movedim(-1, 1)
        height, width = rgb.shape[1:3]
        scale = min((intensity / 50) * 8.0, 8.0); block_size = max(2, min(height, width, round(scale)))
        pooled = functional.avg_pool2d(channels_first, kernel_size=block_size, stride=block_size, ceil_mode=True)
        replacement = functional.interpolate(pooled, size=(height, width), mode="nearest").movedim(1, -1)
    if treatment == "white":
        # Reference white mode feathers the dilated mask with Gaussian blur.
        kernel = max(3, intensity | 1); coords=torch.arange(kernel,device=image.device,dtype=image.dtype)-(kernel-1)/2; weights=torch.exp(-(coords**2)/(2*max(.5,intensity/2)**2)); weights=weights/weights.sum()
        blurred=functional.conv2d(functional.conv2d(mask.movedim(-1,1),weights.view(1,1,1,-1),padding=(0,kernel//2)),weights.view(1,1,-1,1),padding=(kernel//2,0)).movedim(1,-1).clamp(0,1)
        mask=blurred
    censored_rgb = rgb * (1 - mask) + replacement * mask
    return censored_rgb if image.shape[-1] == 3 else torch.cat((censored_rgb, image[..., 3:4]), dim=-1)
