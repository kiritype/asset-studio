# Third-party notices

Asset Studio is MIT-licensed (see [LICENSE](LICENSE)). It does not bundle model weights
or third-party ComfyUI custom nodes; users install those themselves. This file lists
what is included from other projects and what Asset Studio works with.

## Included in this repository

### anima_lora — MIT

`trainer/anima_lora/methods/*.toml` are adapted from anima_lora's method configs, and
`trainer/anima_lora/preprocess-model-paths.patch` modifies anima_lora's
`scripts/tasks/preprocess.py`.

- Project: https://github.com/sorryhyun/anima_lora
- Copyright (c) 2026 Seunghyun Ji
- License: MIT

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

anima_lora itself contains code derived from
[kohya-ss/sd-scripts](https://github.com/kohya-ss/sd-scripts) under the Apache License
2.0; see anima_lora's own NOTICE when you install it.

## Used at run time, installed separately

| Project | License | Used for |
|---|---|---|
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | GPL-3.0 | Image generation and processing (Asset Studio talks to it over HTTP) |
| [anima_lora](https://github.com/sorryhyun/anima_lora) | MIT (with Apache-2.0 parts) | LoRA training |
| [ComfyUI-EasyUseAnima](https://github.com/n0va39/ComfyUI-EasyUseAnima) | MIT | Danbooru tag data for autocomplete |
| [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | MIT | WD14 tagging |
| [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) | MIT | Background removal (rembg session nodes) |
| [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack), [ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack) | GPL-3.0 / AGPL-3.0 | Detailer pipeline and detectors |

Licenses above are as stated by each project at the time of writing; check the
project pages for the current terms.

## Models

Asset Studio ships no model files. Each model has its own license on its download page.
Notably:

- **Anima** (CircleStone Labs): CircleStone Labs Non-Commercial License, plus the
  NVIDIA Open Model License for its Cosmos-Predict2 base. LoRAs and fine-tunes made from
  Anima weights are Derivatives under that license. See the README section
  "About Anima models and LoRAs you train".
- **2x-AnimeSharpV4, 4x-UltraSharp** (Kim2091): CC BY-NC-SA 4.0.
- **Bingsu/adetailer** detectors: Apache-2.0.
- **WD14 taggers** (SmilingWolf): Apache-2.0.
- **Segment Anything** (Meta): Apache-2.0.
- Civitai models (checkpoints, LoRAs, detectors): see each model page.
