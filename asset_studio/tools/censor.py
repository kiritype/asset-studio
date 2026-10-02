"""Censoring with a mask: mosaic, blur or a solid color, done by Studio on the CPU.

The mask is a grayscale PNG the size of the image (white = cover). It comes from the
detector job and can be edited with brushes in the image tools before it is applied.
"""

import io
import re

from PIL import Image, ImageFilter, ImageOps

TREATMENTS = ('mosaic', 'blur', 'color', 'white', 'white_solid')
COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


def load_mask(raw, size):
    """A grayscale mask from PNG bytes; must match the image size."""
    with Image.open(io.BytesIO(raw)) as mask:
        if mask.size != tuple(size):
            raise ValueError(f'마스크 크기 {mask.size}가 이미지 크기 {tuple(size)}와 다릅니다.')
        if 'A' in mask.getbands():
            # An RGBA export from the editor: the alpha says where to cover.
            return mask.getchannel('A')
        return mask.convert('L')


def shape_mask(mask, grow=0, feather=0):
    """Grow (or shrink, when negative) the mask by ``grow`` px, then soften its edge."""
    if grow:
        spread = mask.filter(ImageFilter.GaussianBlur(radius=abs(grow)))
        # A blurred hard mask spreads past its edge; the threshold picks how far.
        if grow > 0:
            mask = spread.point(lambda v: 255 if v > 12 else 0)
        else:
            mask = spread.point(lambda v: 255 if v > 243 else 0)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))
    return mask


def apply(image, mask, treatment, intensity, color='#ffffff', opacity=100, grow=0, feather=0):
    """``image`` with the masked area covered.

    ``intensity`` is the mosaic block size or the blur radius in pixels; ``color`` and
    ``opacity`` (0–100) are for the solid fill. ``white`` / ``white_solid`` are the older
    names of a white fill with / without a soft edge.
    """
    if treatment not in TREATMENTS:
        raise ValueError('가림 방식을 고르세요.')
    if not COLOR.match(str(color)):
        raise ValueError('색은 #rrggbb 형식이어야 합니다.')
    if treatment == 'white':
        treatment, color, feather = 'color', '#ffffff', feather or intensity / 2
    elif treatment == 'white_solid':
        treatment, color = 'color', '#ffffff'
    image = ImageOps.exif_transpose(image)
    alpha = image.getchannel('A') if 'A' in image.getbands() else None
    base = image.convert('RGB')
    mask = mask.point(lambda v: 255 if v >= 128 else 0)
    mask = shape_mask(mask, grow, feather)
    if treatment == 'mosaic':
        block = max(1, int(intensity))
        small = base.resize(
            (max(1, base.width // block), max(1, base.height // block)), Image.Resampling.BOX
        )
        cover = small.resize(base.size, Image.Resampling.NEAREST)
    elif treatment == 'blur':
        cover = base.filter(ImageFilter.GaussianBlur(radius=max(1, intensity)))
    else:
        cover = Image.new('RGB', base.size, color)
        strength = max(0, min(100, opacity)) / 100
        if strength < 1:
            mask = mask.point(lambda v: round(v * strength))
    result = Image.composite(cover, base, mask)
    if alpha is not None:
        result.putalpha(alpha)
    return result
