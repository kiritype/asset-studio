"""Tensor-only alpha application used by the AssetStudio ComfyUI node.

The input mask represents the character foreground: 1 preserves the character
and 0 makes the background transparent.  This is deliberately separate from a
detector; no supplied mask is treated as a detection result.
"""

from __future__ import annotations

import torch


def apply_character_alpha(
    images: torch.Tensor, character_mask: torch.Tensor, enabled: bool
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return an RGBA image batch and a ComfyUI background mask.

    ``character_mask`` must be a foreground mask shaped ``[B, H, W]``.  The
    returned MASK follows ComfyUI's convention: 1 marks transparent pixels.
    Existing alpha, if present, is preserved by multiplication.
    """
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean.")
    if not isinstance(images, torch.Tensor) or images.ndim != 4:
        raise ValueError("images must be a tensor shaped [batch, height, width, channels].")
    if images.shape[-1] not in (3, 4):
        raise ValueError("images must have three RGB or four RGBA channels.")
    if not images.is_floating_point() or not torch.isfinite(images).all():
        raise ValueError("images must contain only finite floating-point values.")
    if not isinstance(character_mask, torch.Tensor) or character_mask.ndim != 3:
        raise ValueError("character_mask must be a tensor shaped [batch, height, width].")
    if not character_mask.is_floating_point() or not torch.isfinite(character_mask).all():
        raise ValueError("character_mask must contain only finite floating-point values.")
    if tuple(images.shape[:3]) != tuple(character_mask.shape):
        raise ValueError(
            "character_mask batch and dimensions must exactly match images; "
            "automatic resizing or batch broadcasting is not applied."
        )

    foreground = character_mask.to(device=images.device, dtype=images.dtype).clamp(0.0, 1.0)
    if not enabled:
        foreground = torch.ones_like(foreground)
    base_alpha = images[..., 3] if images.shape[-1] == 4 else torch.ones_like(foreground)
    alpha = base_alpha * foreground
    rgba = torch.cat((images[..., :3], alpha.unsqueeze(-1)), dim=-1)
    return rgba, 1.0 - alpha
