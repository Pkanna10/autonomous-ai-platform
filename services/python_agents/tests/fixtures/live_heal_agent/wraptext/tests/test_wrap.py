import unittest

from wraptext.layout import paragraph
from wraptext.wrap import WrapError, wrap


class WrapTest(unittest.TestCase):
    def test_words_are_wrapped(self):
        self.assertEqual(wrap("the quick brown fox", 10), ["the quick", "brown fox"])

    def test_an_indented_paragraph(self):
        self.assertEqual(paragraph("a b c d", 5, "> "), "> a b\n> c d")

    def test_a_width_below_one_is_refused(self):
        with self.assertRaises(WrapError):
            wrap("x", 0)


if __name__ == "__main__":
    unittest.main()
