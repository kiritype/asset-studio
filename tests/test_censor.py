import unittest

from PIL import Image

from asset_studio.tools.censor import apply


class CensorTest(unittest.TestCase):
    def setUp(self):
        # Left half red, right half blue, with a checker inside the red part.
        self.image = Image.new('RGB', (40, 20), (0, 0, 255))
        self.image.paste((255, 0, 0), (0, 0, 20, 20))
        for x in range(0, 20, 2):
            self.image.putpixel((x, 0), (0, 255, 0))
        self.mask = Image.new('L', (40, 20), 0)
        self.mask.paste(255, (0, 0, 20, 20))

    def test_mosaic_changes_only_the_masked_area(self):
        result = apply(self.image, self.mask, 'mosaic', 10)
        self.assertEqual(result.getpixel((30, 10)), (0, 0, 255))
        # Inside the mask each 10px block is one color.
        block = {result.getpixel((x, y)) for x in range(10) for y in range(10)}
        self.assertEqual(len(block), 1)

    def test_white_keeps_transparency(self):
        rgba = self.image.convert('RGBA')
        rgba.putalpha(128)
        result = apply(rgba, self.mask, 'white', 4)
        self.assertEqual(result.mode, 'RGBA')
        self.assertEqual(result.getpixel((5, 10))[:3], (255, 255, 255))
        self.assertEqual(result.getpixel((5, 10))[3], 128)

    def test_color_with_opacity(self):
        result = apply(self.image, self.mask, 'color', 0, color='#000000', opacity=50)
        # Half black over red: about (128, 0, 0); the unmasked side stays blue.
        r, g, b = result.getpixel((10, 10))
        self.assertTrue(120 <= r <= 135 and g == 0 and b == 0, (r, g, b))
        self.assertEqual(result.getpixel((30, 10)), (0, 0, 255))
        with self.assertRaises(ValueError):
            apply(self.image, self.mask, 'color', 0, color='white')

    def test_blur_and_grow_reach_past_the_mask(self):
        plain = apply(self.image, self.mask, 'blur', 4)
        self.assertEqual(plain.getpixel((30, 10)), (0, 0, 255))
        self.assertNotEqual(plain.getpixel((10, 10)), (255, 0, 0))
        grown = apply(self.image, self.mask, 'color', 0, color='#00ff00', grow=4)
        self.assertEqual(grown.getpixel((22, 10)), (0, 255, 0))
        shrunk = apply(self.image, self.mask, 'color', 0, color='#00ff00', grow=-4)
        self.assertEqual(shrunk.getpixel((18, 10)), (255, 0, 0))
        soft = apply(self.image, self.mask, 'color', 0, color='#00ff00', feather=3)
        r, g, b = soft.getpixel((20, 10))
        self.assertTrue(0 < g < 255, (r, g, b))

    def test_unknown_treatment(self):
        with self.assertRaises(ValueError):
            apply(self.image, self.mask, 'sticker', 4)


if __name__ == '__main__':
    unittest.main()
