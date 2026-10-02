# Source of these nodes

Copied from AtelierX (the same author's project), `custom_nodes/atelierx_{alpha,censor,upscale,detailer}`,
at commit `1161bf143764f2b01babf05804dfb7b6d4b8b102` on 2026-10-01. Changes: node ids, classes and
categories renamed from `AtelierX` to `AssetStudio`; one entry point for the whole folder. Tests,
scripts and example workflows were not copied.

| File | SHA-256 of the original |
|---|---|
| alpha/alpha.py | `c6c6310352779afe…` |
| alpha/nodes.py | `0d039a164062c003…` |
| alpha/segmentation.py | `38ad4390c8edac95…` |
| censor/censor.py | `f032be078d9d4346…` |
| censor/detectors.py | `a208b28bfb6ccd49…` |
| censor/nodes.py | `94a8079cbc40af90…` |
| upscale/nodes.py | `2937642980cec817…` |
| detailer/impact_pipeline.py | `5e05203a1f9dedf8…` |
| detailer/nodes.py | `b84b34040604ca45…` |

Runtime needs (not shipped): ultralytics and its segmentation models for detection, ComfyUI
upscale models, and ComfyUI-Impact-Pack for the detailer pipeline.
