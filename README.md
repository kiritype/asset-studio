# Asset Studio

English · [한국어](README.ko.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

**[User manual](https://kiritype.github.io/asset-studio/)** — every screen step by step, with screenshots.

Asset Studio is a local web app for making consistent character images with
[ComfyUI](https://github.com/comfyanonymous/ComfyUI). You keep your prompts as reusable
pieces (outfits, expressions, compositions, artist tags, quality tags), generate every
combination you need in one batch, review the results, and train a LoRA per character
from the images you approved. The app runs on your own PC and talks to your own ComfyUI.

What it does:

- **Prompts**: works › characters › outfit sets, expressions, compositions, artist and
  common tags. Pieces can be global, shared by one work, or belong to one character, and
  are marked as written for Anima, SDXL/Illustrious or both. Danbooru tag autocomplete
  helps while you type.
- **Jobs**: pick characters, outfits and expressions; the app counts the images and
  queues them. Anima and SDXL/Illustrious graphs are both supported.
- **Gallery**: review images (pass / fail), filter by work, character, outfit,
  expression or model, regenerate with a new seed, export approved images as a ZIP.
- **Lab**: try one prompt with several seeds or one changing setting (CFG, steps,
  sampler, scheduler, CLIP skip, LoRA strength) and compare results side by side or
  with a slider.
- **Image tools**: upload images or bring them from the gallery, read how they were made
  (Asset Studio record, ComfyUI graph, A1111 parameters, EXIF), tag them with WD14,
  remove the background, upscale, redraw faces and hands (detailer), censor with a mask
  you can paint, and convert to WebP.
- **LoRA**: build a dataset from approved images, edit captions, train with
  [anima_lora](https://github.com/sorryhyun/anima_lora), register the result and have it
  applied automatically when you generate that character.

Images are saved as PNG with the ComfyUI `prompt` and `workflow` embedded, so ComfyUI can
open any result as a workflow.

The interface is available in Korean, English, Japanese and Simplified Chinese
(**Settings › General**), with light, dark or system theme. The Japanese and Chinese
texts are machine translations; corrections are welcome.

## Requirements

- Windows 10 or 11. The launch scripts and process handling are Windows-only.
- An NVIDIA GPU. Developed on an RTX 4090 (24 GB); LoRA training needs a large GPU.
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI), tested with 0.38.0. Any install
  works: [Stability Matrix](https://github.com/LykosAI/StabilityMatrix), the portable
  build or a git clone.
- Python 3.12 or newer with [Pillow](https://pypi.org/project/pillow/). ComfyUI's own
  Python already has Pillow, so you can use it.
- [Git](https://git-scm.com/) for installing and updating.

## Install

1. Install ComfyUI and the models for generation (see [Dependencies](#dependencies)).
   Start ComfyUI once and check that it opens at http://127.0.0.1:8188.
2. Get Asset Studio:

   ```bat
   git clone https://github.com/kiritype/asset-studio.git
   cd asset-studio
   ```

3. Tell the launcher which Python to use. Create `launch.local.bat` next to `launch.bat`
   with one line pointing at `pythonw.exe` (no console window), for example ComfyUI's own:

   ```bat
   set "STUDIO_PYTHON=C:\path\to\ComfyUI\venv\Scripts\pythonw.exe"
   ```

   Without this file the launcher uses `pythonw` from `PATH`.
4. Optional features need ComfyUI custom nodes and models.
   `tools/install_comfy_nodes.py` installs the custom nodes at the
   [tested versions](#tested-versions) and links Asset Studio's node pack into ComfyUI. Run it with
   ComfyUI's Python (for the portable build, `python_embeded\python.exe`); typing just
   `python` may open the Microsoft Store instead. It finds the running ComfyUI and its Python, and
   only shows the plan until you add `--yes`:

   ```bat
   C:\path\to\ComfyUI\venv\Scripts\python.exe tools\install_comfy_nodes.py
   C:\path\to\ComfyUI\venv\Scripts\python.exe tools\install_comfy_nodes.py --yes
   ```

   `--only tagger,alpha` picks features (`autocomplete`, `tagger`, `alpha`, `detect`,
   `detailer`); `--comfy` and `--python` name the install when ComfyUI is not running or
   there are several. Nodes you already have are left alone. Restart ComfyUI afterwards and
   put the models from [Dependencies](#dependencies) in place.

## Start and stop

- `launch.bat` starts Asset Studio (if it is not running) and opens
  http://127.0.0.1:8195 in your browser.
- `stop.bat` stops it, `restart.bat` stops and starts it again. Both ask first when images
  are being generated or queued, or a LoRA is training.
- ComfyUI must be running for generation and image tools. The header shows the
  connection; **Settings** can also start, stop and restart a ComfyUI that Asset Studio
  started itself (fill in the ComfyUI folder and Python there).

The server listens on 127.0.0.1 only. Everything you make stays in the `data/` and
`outputs/` folders inside the Asset Studio folder.

## First steps

1. **Settings**
   - **General**: language, theme and tag autocomplete.
   - **ComfyUI connection**: check the address (default `http://127.0.0.1:8188`). Fill in
     the ComfyUI folder and its Python if you want Asset Studio to start and stop ComfyUI
     and to find the Danbooru tag data. **Find automatically** lists the ComfyUI installs on
     the PC (the running one first, Stability Matrix, portable, git) and fills these in.
2. **Prompts**: press **Import sample** to get a ready-made example work
   ("Starlight Academy": two characters, uniforms, five expressions), or build your own:
   1. **+ Work** creates a work, then **+ Character** adds characters with their
      appearance prompt.
   2. **+ Piece** adds outfit parts (hands, top, bottom, shoes, or the whole outfit),
      expressions, compositions, artist tags and common positive/negative tags.
   3. **+ Outfit set** combines outfit parts into an outfit.
   4. The scope buttons (Global / Shared in work / Character) decide who can use a piece.
      A character's own piece overrides a shared one with the same code.
3. **Jobs**: tick characters, outfits, expressions and the pieces to add, choose the model
   and settings (Anima or SDXL·IL tab), check the preview, and queue the images. The queue
   button in the header shows progress.
4. **Gallery**: open an image and mark it pass (P) or fail (F). Passed images are the ones
   you export and train on.
5. **LoRA**: choose a character, build a dataset from its images, train, then register the
   epoch you like and turn on **Auto apply** so new jobs for that character use it.

### Image tools at a glance

- **WebP conversion**: quality, lossless, resize. "Keep metadata" is off by default, so
  shared files carry no prompt or workflow.
- **Tagging**: WD14 tags compared with the image's prompt (matches, only in the image,
  not seen in the image). Keep a list of excluded tags, copy tags, open them in the lab,
  or export the chosen images' tags as TXT (LoRA captions) or JSON. Chosen images can be
  downloaded as one ZIP.
- **Post-processing**: upscale and detailer. Upscaling drops transparency, so remove the
  background after upscaling, not before.
- **Censor**: (1) optionally detect areas, (2) fix the red mask with the brush and the
  eraser (undo is there), (3) apply mosaic, blur or a solid color, with optional mask
  growth and a soft edge.
- **Background removal**: (1) split the background automatically, (2) fix the kept area
  (blue mask) and check it with the result preview, (3) apply.
- **Inpaint**: paint the area to redraw (green mask); only that area is redrawn with the
  image's own model, LoRAs and recorded prompt (editable). Unpainted areas keep the
  original pixels. Works on images made with Asset Studio.
- The original is never changed. Results of work images (work/character/outfit folders)
  are saved next to the source as new candidates; pass one in the gallery to adopt it.
  Other results go to `outputs/_tools/`.

## Dependencies

Nothing below is bundled; download each from its page and place it where ComfyUI expects
it. Model folders are ComfyUI's `models/` sub-folders (or the shared model folders of
Stability Matrix).

### Generation (required)

| What | Where to get it | ComfyUI folder |
|---|---|---|
| Anima diffusion model, e.g. `anima-aesthetic-v1.1.safetensors` or `anima-base-v1.0.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/diffusion_models) (also on [Civitai](https://civitai.com/models/2458426)) | `diffusion_models` |
| Text encoder `qwen_3_06b_base.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/text_encoders) | `text_encoders` |
| VAE `qwen_image_vae.safetensors` | [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files/vae) | `vae` |

Anima fine-tunes that ship as a checkpoint with their own text encoder (for example
[MiaoMiao Harem](https://civitai.com/models/934764)) also work: pick the checkpoint and its
text encoder in the generation settings. For SDXL/Illustrious, any Illustrious or NoobAI
checkpoint in `checkpoints` works.

Tip: put Anima files in an `anima` sub-folder and SDXL files in an `sdxl` sub-folder (for
example `loras/anima/`). Asset Studio then knows each file's model family and only offers
matching files. `tools/organize_models.py` can move existing files for you (dry run by
default).

### Optional features

| Feature | Custom nodes | Models |
|---|---|---|
| Tag autocomplete and tag check | [ComfyUI-EasyUseAnima](https://github.com/n0va39/ComfyUI-EasyUseAnima) (only its Danbooru tag files are read) | — |
| WD14 tagging (image tools) | [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | Downloaded by the node on first use, e.g. [wd-eva02-large-tagger-v3](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3) |
| Background removal | [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) (its requirements install `rembg`) and Asset Studio's node pack | `isnet-anime` is downloaded by rembg on first use |
| Censor area detection | Asset Studio's node pack, `ultralytics` in ComfyUI's Python (installed by Impact Subpack) | `ntd11_anime_nsfw_segm_v5-variant1.pt` from [Anime NSFW Detection](https://civitai.com/models/1313556) → `ultralytics/segm` |
| Person mask (alternative background removal) | Asset Studio's node pack, `ultralytics` | `person_yolov8n-seg.pt` from [Bingsu/adetailer](https://huggingface.co/Bingsu/adetailer) → `ultralytics/segm` |
| Upscale | Asset Studio's node pack | e.g. [2x-AnimeSharpV4](https://huggingface.co/Kim2091/2x-AnimeSharpV4), [4x-UltraSharp](https://huggingface.co/Kim2091/UltraSharp) → `upscale_models` |
| Detailer (face, eyes, mouth, hands) | [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack), [ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack), Asset Studio's node pack | `face_yolov8m.pt`, `hand_yolov8s.pt` from [Bingsu/adetailer](https://huggingface.co/Bingsu/adetailer) → `ultralytics/bbox`; `PitEyeDetailer-v2-seg.pt` from [Eye Detailer/Segmentation](https://civitai.com/models/334668) → `ultralytics/segm`; [sam_vit_b_01ec64.pth](https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth) → `sams` |
| Automatic review with a vision model | A local OpenAI-compatible server (for example [LM Studio](https://lmstudio.ai/)) | A vision-language model of your choice |
| LoRA training | — | See [LoRA training](#lora-training) |

Civitai detector downloads are ZIP files; extract the `.pt` file into the folder shown.
Asset Studio's node pack is the `comfy_nodes/asset_studio_nodes` folder linked in step 4
of [Install](#install). Censoring itself (mosaic, blur, solid color) needs no extra node; only the
automatic detection does.

### Tested versions

The node installer uses these versions; others may work but were not tested.

| Component | Version | Commit | License |
|---|---|---|---|
| ComfyUI | 0.38.0 | — | GPL-3.0 |
| [ComfyUI-EasyUseAnima](https://github.com/n0va39/ComfyUI-EasyUseAnima) | 1.1.1 | `66ae8b6` | MIT |
| [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | 1.0.1 | `9e0a6e7` | MIT |
| [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) | 1.1.0 | `9d9f4be` | MIT |
| [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) | 8.28.3 | `429d015` | GPL-3.0 |
| [ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack) | 1.3.5 | `50c7b71` | AGPL-3.0 |
| Python packages (installed by the nodes) | ultralytics 8.4.150, rembg 2.0.85, onnxruntime 1.30.0 | — | AGPL-3.0 · MIT · MIT |

## LoRA training

Training runs [anima_lora](https://github.com/sorryhyun/anima_lora) in its own Python
environment. It is a separate install:

1. Install [uv](https://docs.astral.sh/uv/) and clone anima_lora into `vendor/anima_lora`
   inside the Asset Studio folder. Asset Studio was tested with commit `69ff962`, which
   also needs its companion `anime_tools` (v0.7.5) in `vendor/anime_tools`:

   ```bat
   git clone https://github.com/sorryhyun/anime_tools.git vendor\anime_tools
   git -C vendor\anime_tools checkout v0.7.5
   git clone https://github.com/sorryhyun/anima_lora.git vendor\anima_lora
   cd vendor\anima_lora
   git checkout 69ff962
   uv sync
   ```

   Follow anima_lora's own [Setup](https://github.com/sorryhyun/anima_lora#setup) if
   `uv sync` needs more (it uses Python 3.13 and a CUDA build of PyTorch, so a recent
   NVIDIA driver is required).
2. Apply Asset Studio's small patch, which lets preprocessing use the model files you
   choose instead of anima_lora's `models/` folder:

   ```bat
   git apply ..\..\trainer\anima_lora\preprocess-model-paths.patch
   ```

3. In **Settings › LoRA training**, fill in:
   - **LoRA output folder**: your ComfyUI LoRA folder (for example `.../loras/anima`).
     Finished epochs are copied there.
   - **Official Anima base**: the files of the official
     [Anima base](https://huggingface.co/circlestone-labs/Anima/tree/main/split_files)
     (`anima-base-v1.0.safetensors`, `qwen_3_06b_base.safetensors`,
     `qwen_image_vae.safetensors`).
   - **Generation model** (optional): an Anima fine-tune to train on instead.

   Each path shows whether the file was found.

Asset Studio writes its trainer presets (marked `asset-studio` in
`vendor/anima_lora/configs/presets.toml`) and method files itself before each run. While a
LoRA trains, new images are not generated; queued images continue afterwards.

## Settings

Everything is set on the **Settings** page and stored in `data/settings/` on the server,
so every browser on the PC sees the same settings.

| Section | What it holds |
|---|---|
| General | Language, theme, tag autocomplete |
| ComfyUI connection | Address, folder and Python of ComfyUI |
| Danbooru tag data | Folder of the tag files when they are not in ComfyUI-EasyUseAnima |
| LoRA training | Trainer folder, its Python, LoRA output folder, training models |
| GPU use / GPU wait rules | Wait while other programs use the GPU (free VRAM, program names) |
| VLM server / VLM review | Optional automatic review: server address, model, the commands that load and unload the model (for example LM Studio's `lms load` / `lms unload` / `lms ps`), and the on/off switch |

`config/models.example.json` (copy to `data/settings/models.json`) sets a shared model
folder and manual model families; most setups do not need it.

## Your data

- `data/` holds the prompt library, reviews, datasets, LoRA records and settings.
  `outputs/` holds generated and processed images. Back up both folders; neither is part
  of the git repository.
- Deleting prompts moves them to the library trash, from where they can be restored.
- `outputs/_lab/` holds lab images and `outputs/_tools/` image-tool results; the gallery
  shows every image under `outputs/`.

## Troubleshooting

- **Cannot connect to ComfyUI**: start ComfyUI and check the address in Settings.
- **A model or node is "not in the list"**: install it, restart ComfyUI and reload the
  page. The image tools name the missing node.
- **Queue paused**: a failed job pauses the queue so nothing is lost. Read the error in
  the queue panel, fix it and resume.
- **Logs**: `logs/studio.log` (server), `logs/launcher.log` (start-up),
  `logs/lora/<run>/trainer.log` (training).

## License

Asset Studio is released under the [MIT License](LICENSE). It does not include any model
weights or third-party custom nodes; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
for what it uses and their licenses.

### About Anima models and LoRAs you train

Anima is published by CircleStone Labs under the
[CircleStone Labs Non-Commercial License](https://huggingface.co/circlestone-labs/Anima/blob/main/LICENSE.md),
and is also subject to the NVIDIA Open Model License because it is based on NVIDIA
Cosmos-Predict2. In short (read the license itself for the exact terms):

- LoRAs, fine-tunes and merges made from Anima weights, including LoRAs trained with
  Asset Studio and models such as Anima fine-tunes, are **Derivatives** under that license
  and carry its non-commercial terms.
- If you share such a LoRA, state that it modifies the CircleStone model and include the
  notice required by the license.
- Individuals may sell Derivatives they made themselves; offering the model as a paid
  service or inside a paid product needs a separate license from CircleStone Labs.
- CircleStone Labs claims no ownership of the images you generate.

Other models you use (upscalers, detectors, checkpoints) have their own licenses on their
download pages; for example the 2x-AnimeSharpV4 and 4x-UltraSharp upscalers are
CC BY-NC-SA 4.0.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
