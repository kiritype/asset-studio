"""A final-scale image upscaler that delegates model work to ComfyUI."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import math

import comfy.utils
import folder_paths
from comfy_api.latest import ComfyExtension, io
from comfy_extras.nodes_upscale_model import ImageUpscaleWithModel, UpscaleModelLoader


def _registered_upscale_model(name: str) -> str:
    """Accept only a model name exposed by ComfyUI's configured folders."""
    if not isinstance(name, str) or name not in folder_paths.get_filename_list("upscale_models"):
        raise ValueError(f"upscale model is not registered: {name!r}")
    return name


def _target_dimension(source: int, scale: float) -> int:
    """Calculate the final target dimension with documented half-up rounding."""
    if not isinstance(source, int) or isinstance(source, bool) or source < 1:
        raise ValueError("image dimensions must be positive integers.")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be a finite number greater than zero.")
    return max(1, int((Decimal(source) * Decimal(str(scale))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def _final_resize(image, width: int, height: int):
    """Resize a ComfyUI IMAGE tensor using the temporary implementation choice."""
    if image.shape[-3:-1] == (height, width):
        return image
    channels_first = image.movedim(-1, 1)
    return comfy.utils.common_upscale(
        channels_first, width, height, "lanczos", "disabled"
    ).movedim(1, -1)


class AssetStudioUpscale(io.ComfyNode):
    """Upscale IMAGE with one installed model to an input-relative final scale."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AssetStudioUpscale",
            display_name="AssetStudio Upscale",
            category="AssetStudio/postprocessing",
            description=(
                "Upscales IMAGE with an installed ComfyUI model, then resizes it "
                "to the requested final scale relative to the input image."
            ),
            inputs=[
                io.Image.Input("image"),
                io.Combo.Input("upscale_model", options=folder_paths.get_filename_list("upscale_models")),
                io.Float.Input("scale", default=1.5, step=0.01),
            ],
            outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, image, upscale_model: str, scale: float) -> io.NodeOutput:
        _registered_upscale_model(upscale_model)
        if (
            not hasattr(image, "shape")
            or len(image.shape) != 4
            or image.shape[0] < 1
            or image.shape[-3] < 1
            or image.shape[-2] < 1
            or image.shape[-1] != 3
        ):
            raise ValueError("image must be a non-empty batched RGB IMAGE tensor.")
        target_width = _target_dimension(image.shape[-2], scale)
        target_height = _target_dimension(image.shape[-3], scale)

        loaded_model = UpscaleModelLoader.execute(upscale_model)[0]
        model_upscaled = ImageUpscaleWithModel.execute(loaded_model, image)[0]
        return io.NodeOutput(_final_resize(model_upscaled, target_width, target_height))


class AssetStudioUpscaleExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [AssetStudioUpscale]
