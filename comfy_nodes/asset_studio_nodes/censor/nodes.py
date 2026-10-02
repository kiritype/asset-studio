"""ComfyUI wrapper for supplied detection masks and censor treatments."""

from __future__ import annotations

import os
import folder_paths
from comfy_api.latest import ComfyExtension, io

from .censor import apply_censor
from .detectors import REFERENCE_LABELS, detect_selected_segmentation_masks

def _models():
    try: return folder_paths.get_filename_list("ultralytics_segm")
    except KeyError: return []

class AssetStudioDetectNsfwMask(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(node_id="AssetStudioDetectNsfwMask", display_name="AssetStudio Detect NSFW Mask", category="AssetStudio/postprocessing", description="Runs an already registered local YOLO segmentation model and returns selected reference Censor labels. No model or runtime is downloaded.", inputs=[io.Image.Input("image"),io.Combo.Input("segmentation_model",options=_models()),io.String.Input("labels",default=",".join(REFERENCE_LABELS)),io.Float.Input("confidence",default=.35,min=0.,max=1.,step=.01)],outputs=[io.Mask.Output(display_name="detection_mask")])
    @classmethod
    def execute(cls,image,segmentation_model:str,labels:str,confidence:float=.35)->io.NodeOutput:
        if segmentation_model not in _models(): raise ValueError(f"segmentation model is not registered in ultralytics_segm: {segmentation_model!r}")
        path=folder_paths.get_full_path_or_raise("ultralytics_segm",segmentation_model)
        if not os.path.isfile(path): raise ValueError("segmentation model is not a readable local file.")
        return io.NodeOutput(detect_selected_segmentation_masks(image,path,tuple(item.strip() for item in labels.split(",") if item.strip()),confidence))


class AssetStudioCensor(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AssetStudioCensor", display_name="AssetStudio Censor", category="AssetStudio/postprocessing",
            description="Applies mosaic or white treatment where an upstream NSFW detector supplied MASK is 1. It does not detect NSFW regions.",
            inputs=[io.Image.Input("image"), io.Mask.Input("detection_mask", tooltip="NSFW detector mask: 1 is censored."), io.Combo.Input("treatment", options=["mosaic", "white", "white_solid"], default="mosaic"), io.Int.Input("intensity", default=15, min=1, max=128), io.Boolean.Input("enabled", default=True)],
            outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, image, detection_mask, treatment: str, intensity: int, enabled: bool = True) -> io.NodeOutput:
        return io.NodeOutput(apply_censor(image, detection_mask, treatment, intensity, enabled))


class AssetStudioCensorExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [AssetStudioDetectNsfwMask, AssetStudioCensor]
