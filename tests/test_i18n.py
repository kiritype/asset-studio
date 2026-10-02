import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import i18n_check


class CatalogTest(unittest.TestCase):
    def test_every_message_is_translated_with_the_same_placeholders(self):
        for language, result in i18n_check.check().items():
            with self.subTest(language=language):
                self.assertEqual(result['missing'], [], 'run tools/i18n_check.py')
                self.assertEqual(result['placeholders'], [])


if __name__ == '__main__':
    unittest.main()
