"""Masked regional diffusion detailing backed by ComfyUI's native nodes."""

from __future__ import annotations

import math

import comfy.samplers
import nodes
from comfy_api.latest import ComfyExtension, io
from .impact_pipeline import run_pipeline


DETAIL_TARGETS = ("eyes", "mouth", "hands", "face")



def _validate_image_and_mask(image, region_mask) -> None:
    if not hasattr(image, "shape") or len(image.shape) != 4 or image.shape[0] < 1 or image.shape[-1] not in (3, 4):
        raise ValueError("image must be a non-empty batched RGB or RGBA IMAGE tensor.")
    if not hasattr(region_mask, "shape") or len(region_mask.shape) != 3:
        raise ValueError("region_mask must be a batched MASK tensor shaped [batch, height, width].")
    if tuple(region_mask.shape) != tuple(image.shape[:3]):
        raise ValueError("region_mask batch and pixel dimensions must exactly match image.")


def _validate_request(target: str, seed: int, steps: int, cfg: float, sampler: str, scheduler: str, denoise: float, grow_mask_by: int) -> None:
    if target not in DETAIL_TARGETS:
        raise ValueError(f"target must be one of {DETAIL_TARGETS}; got {target!r}.")
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("seed must be an unsigned 64-bit integer.")
    if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= 100:
        raise ValueError("steps must be an integer between 1 and 100.")
    if not isinstance(cfg, (int, float)) or isinstance(cfg, bool) or not math.isfinite(cfg) or not 0 <= cfg <= 20:
        raise ValueError("cfg must be a finite number between 0 and 20.")
    if sampler not in comfy.samplers.KSampler.SAMPLERS or scheduler not in comfy.samplers.KSampler.SCHEDULERS:
        raise ValueError("sampler or scheduler is not supported by this ComfyUI installation.")
    if not isinstance(denoise, (int, float)) or isinstance(denoise, bool) or not math.isfinite(denoise) or not 0 <= denoise <= 1:
        raise ValueError("denoise must be a finite number between 0 and 1.")
    if not isinstance(grow_mask_by, int) or isinstance(grow_mask_by, bool) or not 0 <= grow_mask_by <= 64:
        raise ValueError("grow_mask_by must be an integer between 0 and 64.")


def _composite_region(original, detailed, region_mask):
    """Keep pixels outside the supplied region exact after VAE decode."""
    mask = region_mask.unsqueeze(-1).to(dtype=original.dtype).clamp(0, 1)
    rgb = original[..., :3] * (1 - mask) + detailed[..., :3].to(dtype=original.dtype) * mask
    if original.shape[-1] == 3:
        return rgb
    # ComfyUI has already loaded torch before node execution; defer the import so
    # schema-only discovery has no additional runtime dependency side effect.
    import torch
    return torch.cat((rgb, original[..., 3:4]), dim=-1)


class AssetStudioDetailer(io.ComfyNode):
    """Run masked inpaint diffusion for eyes, mouth, hands, or face."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AssetStudioDetailer",
            display_name="AssetStudio Detailer",
            category="AssetStudio/postprocessing",
            description=(
                "Runs native ComfyUI masked inpaint diffusion for one supplied eyes, mouth, "
                "hands, or face MASK. This node does not detect regions."
            ),
            inputs=[
                io.Image.Input("image"), io.Mask.Input("region_mask", tooltip="Detail region MASK: 1 is regenerated."),
                io.Model.Input("model"), io.Clip.Input("clip"), io.Vae.Input("vae"),
                io.Combo.Input("target", options=list(DETAIL_TARGETS), default="face"),
                io.String.Input("positive_prompt", multiline=True), io.String.Input("negative_prompt", multiline=True, default=""),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF), io.Int.Input("steps", default=20, min=1, max=100),
                io.Float.Input("cfg", default=5.0, min=0.0, max=20.0, step=0.1),
                io.Combo.Input("sampler", options=comfy.samplers.KSampler.SAMPLERS, default="euler"),
                io.Combo.Input("scheduler", options=comfy.samplers.KSampler.SCHEDULERS, default="normal"),
                io.Float.Input("denoise", default=0.35, min=0.0, max=1.0, step=0.01),
                io.Int.Input("grow_mask_by", default=6, min=0, max=64),
            ],
            outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, image, region_mask, model, clip, vae, target: str, positive_prompt: str, negative_prompt: str, seed: int, steps: int, cfg: float, sampler: str, scheduler: str, denoise: float, grow_mask_by: int) -> io.NodeOutput:
        _validate_image_and_mask(image, region_mask)
        _validate_request(target, seed, steps, cfg, sampler, scheduler, denoise, grow_mask_by)
        if not isinstance(positive_prompt, str) or not positive_prompt.strip() or not isinstance(negative_prompt, str):
            raise ValueError("positive_prompt must be non-empty and negative_prompt must be a string.")
        positive = nodes.CLIPTextEncode().encode(clip, positive_prompt)[0]
        negative = nodes.CLIPTextEncode().encode(clip, negative_prompt)[0]
        latent = nodes.VAEEncodeForInpaint().encode(vae, image[..., :3], region_mask, grow_mask_by)[0]
        sampled = nodes.KSampler().sample(model, seed, steps, cfg, sampler, scheduler, positive, negative, latent, denoise)[0]
        detailed = nodes.VAEDecode().decode(vae, sampled)[0]
        return io.NodeOutput(_composite_region(image, detailed, region_mask))


class AssetStudioImpactDetailerPipeline(io.ComfyNode):
    """Optional Impact Pack Face → Eye → Mouth → Hand orchestration wrapper."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="AssetStudioImpactDetailerPipeline", display_name="AssetStudio Detailer Pipeline (Impact)",
            category="AssetStudio/postprocessing",
            description="Runs enabled Impact Pack passes in fixed Face → Eye → Mouth → Hand order.",
            inputs=[
                io.Image.Input("image"), io.Model.Input("model"), io.Clip.Input("clip"), io.Vae.Input("vae"),
                io.Conditioning.Input("positive"), io.Conditioning.Input("negative"),
                io.Boolean.Input("face_enabled", default=True), io.String.Input("face_detector_model", default="bbox/face_yolov8m.pt"),
                io.Boolean.Input("eye_enabled", default=True), io.String.Input("eye_detector_model", default="segm/PitEyeDetailer-v2-seg.pt"),
                io.Boolean.Input("mouth_enabled", default=True), io.String.Input("mouth_detector_model", default="bbox/face_yolov8m.pt"),
                io.Boolean.Input("hand_enabled", default=True), io.String.Input("hand_detector_model", default="bbox/hand_yolov8s.pt"),
                io.String.Input("sam_model", default="sam_vit_b_01ec64.pth"),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF), io.Int.Input("steps", default=10, min=1, max=100),
                io.Float.Input("cfg", default=5.0, min=0.0, max=20.0, step=0.1),
                io.Combo.Input("sampler_name", options=comfy.samplers.KSampler.SAMPLERS, default="euler_ancestral"),
                io.Combo.Input("scheduler", options=comfy.samplers.KSampler.SCHEDULERS, default="normal"),
                io.Float.Input("denoise", default=0.5, min=0.0, max=1.0, step=0.01),
            ], outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, image, model, clip, vae, positive, negative, face_enabled=True, face_detector_model="bbox/face_yolov8m.pt", eye_enabled=True, eye_detector_model="segm/PitEyeDetailer-v2-seg.pt", mouth_enabled=True, mouth_detector_model="bbox/face_yolov8m.pt", hand_enabled=True, hand_detector_model="bbox/hand_yolov8s.pt", sam_model="sam_vit_b_01ec64.pth", seed=0, steps=10, cfg=5.0, sampler_name="euler_ancestral", scheduler="normal", denoise=0.5):
        _validate_request("face", seed, steps, cfg, sampler_name, scheduler, denoise, 0)
        settings = dict(guide_size=512, guide_size_for=True, max_size=1024, seed=seed, steps=steps, cfg=cfg,
                        sampler_name=sampler_name, scheduler=scheduler, denoise=denoise, feather=5, noise_mask=True,
                        force_inpaint=True, bbox_threshold=0.5, bbox_dilation=10, bbox_crop_factor=3,
                        sam_detection_hint="center-1", sam_dilation=0, sam_threshold=0.93, sam_bbox_expansion=0,
                        sam_mask_hint_threshold=0.7, sam_mask_hint_use_negative="False", drop_size=10,
                        refiner_ratio=0.2, cycle=1, inpaint_model=False, noise_mask_feather=20,
                        tiled_encode=False, tiled_decode=False)
        result = run_pipeline(image,
            {"face": face_enabled, "eye": eye_enabled, "mouth": mouth_enabled, "hand": hand_enabled},
            {"face": face_detector_model, "eye": eye_detector_model, "mouth": mouth_detector_model, "hand": hand_detector_model},
            sam_model, model, clip, vae, positive, negative, settings)
        return io.NodeOutput(result)




class AssetStudioDetailerExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [AssetStudioDetailer, AssetStudioImpactDetailerPipeline]
