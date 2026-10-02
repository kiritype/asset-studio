"""ComfyUI nodes for local character segmentation and alpha application."""

from __future__ import annotations

from comfy_api.latest import ComfyExtension, io
import folder_paths

from .alpha import apply_character_alpha
from .segmentation import detect_ultralytics_person_masks


def _segmentation_model_options() -> list[str]:
    """List models when this ComfyUI process configured the optional category."""
    try:
        return folder_paths.get_filename_list("ultralytics_segm")
    except KeyError:
        return []


def _registered_segmentation_model(name: str) -> str:
    """Resolve only an already registered local Ultralytics segmentation file."""
    options = _segmentation_model_options()
    if not options:
        raise ValueError(
            "ComfyUI has no registered 'ultralytics_segm' model folder. Configure a local "
            "folder and restart ComfyUI; this node will not create or download a model."
        )
    if not isinstance(name, str) or name not in options:
        raise ValueError(
            f"segmentation model is not registered in ComfyUI's ultralytics_segm folders: {name!r}"
        )
    path = folder_paths.get_full_path_or_raise("ultralytics_segm", name)
    import os
    if not os.path.isfile(path):
        raise ValueError(f"segmentation model is not a readable local file: {name!r}")
    return path


class AssetStudioDetectCharacterMask(io.ComfyNode):
    """Detect all COCO-person instances with an installed Ultralytics seg model."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AssetStudioDetectCharacterMask",
            display_name="AssetStudio Detect Character Mask",
            category="AssetStudio/postprocessing",
            description=(
                "Runs an installed local Ultralytics segmentation model and combines all "
                "COCO person instances into a foreground MASK. It never downloads a model."
            ),
            inputs=[
                io.Image.Input("image"),
                io.Combo.Input("segmentation_model", options=_segmentation_model_options()),
                io.Float.Input("confidence", default=0.35, min=0.0, max=1.0, step=0.01),
            ],
            outputs=[io.Mask.Output(display_name="character_mask")],
        )

    @classmethod
    def execute(cls, image, segmentation_model: str, confidence: float = 0.35) -> io.NodeOutput:
        model_path = _registered_segmentation_model(segmentation_model)
        return io.NodeOutput(detect_ultralytics_person_masks(image, model_path, confidence))


class AssetStudioApplyCharacterAlpha(io.ComfyNode):
    """Apply a foreground character mask; character detection is external."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AssetStudioApplyCharacterAlpha",
            display_name="AssetStudio Apply Character Alpha",
            category="AssetStudio/postprocessing",
            description=(
                "Applies a supplied foreground character MASK to IMAGE. "
                "This node does not detect or segment a character."
            ),
            inputs=[
                io.Image.Input("image"),
                io.Mask.Input("character_mask", tooltip="Foreground character mask: 1 preserves character, 0 clears background alpha."),
                io.Boolean.Input("enabled", default=True),
            ],
            outputs=[
                io.Image.Output(display_name="image_rgba"),
                io.Mask.Output(display_name="background_mask"),
            ],
        )

    @classmethod
    def execute(cls, image, character_mask, enabled: bool = True) -> io.NodeOutput:
        rgba, background_mask = apply_character_alpha(image, character_mask, enabled)
        return io.NodeOutput(rgba, background_mask)


class AssetStudioAlphaExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [AssetStudioDetectCharacterMask, AssetStudioApplyCharacterAlpha]
