import unittest

from scripts.check_utf8 import scan_utf8_violations


class EncodingPolicyTest(unittest.TestCase):
    def test_text_sources_are_utf8_without_bom(self):
        non_utf8, with_bom = scan_utf8_violations()
        self.assertEqual(non_utf8, [], f"Found non-UTF-8 files: {non_utf8}")
        self.assertEqual(with_bom, [], f"Found UTF-8 BOM files: {with_bom}")


if __name__ == "__main__":
    unittest.main()
