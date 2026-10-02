"""Asset Studio post-processing nodes for ComfyUI (background alpha, censor, upscale, detailer).

Copied from AtelierX with ``AssetStudio`` node ids so both packs can be installed side by
side; see SOURCE.md. Link this folder into ComfyUI's ``custom_nodes`` to register it.
"""

from comfy_api.latest import ComfyExtension, io

from .alpha.nodes import AssetStudioAlphaExtension
from .censor.nodes import AssetStudioCensorExtension
from .detailer.nodes import AssetStudioDetailerExtension
from .upscale.nodes import AssetStudioUpscaleExtension

PARTS = (
    AssetStudioAlphaExtension,
    AssetStudioCensorExtension,
    AssetStudioUpscaleExtension,
    AssetStudioDetailerExtension,
)


class AssetStudioExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        nodes = []
        for part in PARTS:
            nodes += await part().get_node_list()
        return nodes


async def comfy_entrypoint() -> AssetStudioExtension:
    return AssetStudioExtension()
