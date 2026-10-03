# Image tools

The **Image tools** collect the work you do one image at a time. Source images are never changed.
Edits are saved as new files, while prompt-format results can be copied.

## Adding images

- **Upload files or ZIP**: PNG, WebP or JPEG files, or a ZIP of them. You can also drop them on
  the page.
- **From the gallery**: choose images in the gallery and press **Send to image tools**.

![Sending from the gallery](/shots/en/29-gallery-send-to-tools.webp)

Click an image in the list on the left to see it with how it was made. The Asset Studio record,
the ComfyUI graph, A1111 `parameters` and EXIF are read to show the prompt and settings, and
**Open in Generate & compare** hands them to that page.

![Reading how an image was made](/shots/en/31-tools-analysis.webp)

Ticked images can be downloaded at once with **Download ZIP**.

## Prompt format

The **Prompt format** tab converts prompt text without generating an image. Enter positive and
negative prompts directly, or choose prompt metadata from gallery images. When several images are
selected, each image's prompt is converted separately.

The available formats are NovelAI V5, Anima and SDXL·Illustrious (ComfyUI). Explicit artist forms
such as `@name` or `artist:name` are converted to artist tags. A bare name is treated as an artist
only when it appears in the optional artist list you provide. Weight syntax is converted
approximately for the target format; natural-language text is left as written. For example,
NovelAI `1.2::tag::` becomes ComfyUI `(tag:1.2)`, while simple ComfyUI `(tag:1.2)` becomes
NovelAI numeric weighting. Balanced `{tag}` and `[tag]` groups become explicit ComfyUI weights.
Weight numbers have different effects across models, so adjust converted prompts by hand. Unknown
ordinary tags and natural-language text stay as written without a warning. Unsupported complex
syntax (including nested forms it cannot convert), malformed syntax and nonpositive weights are
preserved with a warning. The converter
does not extract artist names from natural language or change quality tags. See [NovelAI's weight
syntax](https://docs.novelai.net/en/image/strengthening-weakening/)
and [Anima prompting](https://huggingface.co/circlestone-labs/Anima#prompting).

Copy the result or send it to Generate & compare (`/lab`). This tab does not generate images with
NovelAI or connect to an external AI service. The original image file is unchanged.

## Where results go

- Results of work images (images in a work / character / outfit folder) are saved **next to the
  source as new candidates**. Inpainting `002.png`, for example, creates `002_inpaint.png`; pass it
  in the gallery to make it the adopted image of that expression.
- Results of uploaded images and Generate & compare images go to `outputs/_tools/<date>/`.

## Tagging

The WD14 tagger reads tags from the image and compares them with the image's prompt.

![Tagging result](/shots/en/36-tools-tags.webp)

- **Matches the prompt**: in the prompt and seen in the image.
- **Only seen in the image**: not in the prompt but visible. Useful for spotting things you did
  not ask for.
- **Not seen in the image**: in the prompt but not read from the image. Either it was not drawn or
  the tagger does not know the phrase.

**Copy tags** and **Open tags in Generate & compare** are available. Tags listed under **Excluded tags** on the
right are left out of the view, copies and exports. **Export tags** as TXT packs one caption file
per image, named like the image ZIP (for LoRA training).

Tagging shares the generation queue, so it runs after images being generated.

## Inpaint

Redraws only the painted area with the image's own model, LoRAs and prompt. Use it to fix part of
an image, such as a hand or a prop. It works on images made with Asset Studio (with a record).

![Inpaint mask](/shots/en/33-tools-inpaint.webp)

1. Paint the **area to redraw** with the green brush and press **Save mask**.
2. The **Prompt** starts from the image's record. Add tags that describe the fix if you like.
3. Choose the **Area to redraw**:
   - **Mask area, enlarged (recommended)**: crops around the mask, redraws it enlarged to the
     generation size and pastes it back. Small parts such as fingers come out sharper. A wider
     **context padding** blends in better.
   - **Whole image**: redraws at the image's own size.
4. Set **Denoise**. Higher changes more; start at 0.5–0.7 for hands and props.
5. Press **Inpaint this image**.

Areas you did not paint keep the original pixels.

![Before and after inpainting](/shots/35-inpaint-before-after.webp)

## Background removal

1. **Split the background**: isnet-anime (for anime illustrations) or person segmentation finds
   the area to keep.
2. **Fix the mask**: the blue area is kept. Add with the brush, remove with the eraser, then save.
   **Preview result** shows the cut-out right away.
3. **Apply**: choose mask growth and edge softness and apply to save a PNG with a transparent
   background.

![Background removal preview](/shots/en/38-tools-alpha-preview.webp)

Upscaling drops transparency, so remove the background after upscaling.

## Censor

1. **Detect areas** (optional): finds the areas to cover automatically. It can miss some, so
   always check.
2. **Fix the mask**: the red area is covered. You can also paint it without detection.
3. **Apply**: choose mosaic, blur or a solid colour, with strength, colour, mask growth and edge
   softness.

![Censor](/shots/en/39-tools-censor.webp)

Censor and background removal can be applied to several images at once with the "apply to the
chosen images with a mask" button; each image uses its own saved mask.

## The mask editor

Inpaint, background removal and censor share one editor.

| Action         | How                                                 |
| -------------- | --------------------------------------------------- |
| Brush / eraser | **B** / **E**                                       |
| Brush size     | **[** / **]** or the size slider                    |
| Undo / redo    | **Ctrl+Z** / **Ctrl+Y**                             |
| Zoom           | Mouse wheel                                         |
| Pan            | Drag with **Space** held, or with the middle button |
| Fit / 100%     | **0** / **1**                                       |

**Show mask** and its opacity slider hide or fade the mask; **Background** picks what shows
behind transparent areas (checker, white or black).

## Post-processing

- **Upscale**: enlarges with an upscale model and matches the final scale you set.
- **Detailer** (experimental): finds faces, eyes, mouths and hands and redraws them with the
  image's own model. Faces can change, so check the result.

## WebP conversion

Converts to WebP with quality, lossless and long-side options. **Keep metadata** is off by default,
so shared files carry no prompt or workflow.
