# Generate & compare

**Generate & compare** is where you try prompts outside the library and compare results. The page
keeps its existing `/lab` address. Results are saved in `outputs/_lab/<date>/` and appear in the
gallery.

The positive and negative prompt fields are shared by both tabs. Enter them directly; tag
autocomplete and the tag checks point out tags that Danbooru does not know. Generation settings
match Jobs, and you can load or save a generation preset.

## Single generation

The **Single generation** tab makes one image from the prompt and generation settings. Values or
artist candidates entered on the Comparison tab do not affect it.

## Comparison

The **Comparison** tab keeps the same conditions while it changes only the seed, or changes one
setting at a time.

- **Seeds**: generate the same prompt with several seeds to see how stable it is.
- **Settings**: compare values for one setting.

| Setting             | Example values                                                    |
| ------------------- | ----------------------------------------------------------------- |
| CFG                 | 3, 4.5, 6                                                         |
| Steps               | 20, 28, 36                                                        |
| Sampler · scheduler | leave empty for the whole list                                    |
| CLIP skip (SDXL)    | 1, 2                                                              |
| LoRA strength       | 0.4, 0.7, 1.0                                                     |
| Artist              | one candidate per line; put a mix of artists together on one line |

Enter one artist candidate per line. Turn on **Include a no-artist baseline** to add a result with
no artist tag. The common prompt stays in every result, and existing artist tags are not removed automatically. Leave the
artists being compared out of the common prompt so each candidate replaces the previous one. All
candidates in one row use the same seed.

You can compare up to 12 candidates and 16 seeds, with a maximum of 48 images in one run.

You can open a job preview or a gallery image in Generate & compare. The image tools can also send
the current prompt or analyzed tags. The source is shown when a prompt comes from another screen.

## Comparing results

Choose two results as **Reference** and **Result**.

- **Side by side**: place the two images next to each other.
- **Slider**: layer one image over the other and drag the edge to see the difference.
- **Swap reference and result** and **Load the result's settings** (brings the settings of the one
  you like back into the form) are available.
