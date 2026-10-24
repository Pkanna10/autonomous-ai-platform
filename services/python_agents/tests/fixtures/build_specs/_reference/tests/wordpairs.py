import unittest

from wordpairs import render, top_pairs


class WordPairsTest(unittest.TestCase):
    def test_the_worked_example(self):
        self.assertEqual(
            render("Red fox, red fox. The red fox ran; red Fox ran!", 3),
            "1\tred fox\t4\n2\tfox ran\t2\n3\tfox red\t1\nkept=8 distinct=4\n",
        )

    def test_stop_words_do_not_join_neighbours(self):
        self.assertEqual(top_pairs("red and blue fox"), [("blue", "fox", 1)])

    def test_no_kept_pair(self):
        self.assertEqual(render("the"), "kept=0 distinct=0\n")

    def test_n_below_one_raises(self):
        with self.assertRaises(ValueError):
            top_pairs("a b", 0)

    def test_digits_and_apostrophes_separate_words(self):
        self.assertEqual(top_pairs("don't 9lives"), [("don", "t", 1), ("t", "lives", 1)])

    def test_line_breaks_do_not_end_the_sequence(self):
        self.assertEqual(top_pairs("red\nfox"), [("red", "fox", 1)])
