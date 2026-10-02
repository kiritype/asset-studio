# Troubleshooting

## Cannot connect to ComfyUI

If the connection badge at the top right is red, ComfyUI is not running or the address differs.
Start ComfyUI and check the address under **Settings › ComfyUI connection**.

## A model or node is "not in the list"

After installing a model or a custom node, restart ComfyUI and reload the Asset Studio page. The
image tools name any missing node. See the
[README's Dependencies](https://github.com/kiritype/asset-studio#dependencies) for what is needed.

## The queue stopped

When a job fails the queue pauses so nothing else is lost. Read the failed job's error in the
queue panel, fix the cause and resume.

## Generation waits and does not start

Another task (LoRA training, VLM review) is using the GPU, or a **GPU wait rule** applies. The
connection badge at the top right and **Settings › GPU use** show the reason.

## The framing goes odd with the LoRA on

A small or one-sided dataset teaches the LoRA the framing as well (two figures, extreme close-ups
and so on). Grow the dataset following [a good dataset](./lora#a-good-dataset), and try a lower
strength or an earlier epoch.

## Log files

| File | Contents |
|---|---|
| `logs/studio.log` | Server |
| `logs/launcher.log` | Start and stop |
| `logs/lora/<run name>/trainer.log` | LoRA training |

## Backing up your data

Back up `data/` (library, reviews, datasets, LoRA records, settings) and `outputs/` (images).
Neither is part of the git repository.
