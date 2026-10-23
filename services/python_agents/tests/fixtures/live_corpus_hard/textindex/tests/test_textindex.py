"""Tests for ``textindex`` (stdlib ``unittest``)."""

import unittest

from textindex.duplicates import jaccard, most_similar, near_duplicates, shingles
from textindex.index import build, index_terms, vocabulary
from textindex.library import Document, documents
from textindex.query import evaluate, parse, positive_terms
from textindex.ranking import rank
from textindex.report import answer
from textindex.snippets import best_window, snippet
from textindex.stats import coverage, document_frequencies, zipf_slope
from textindex.stemmer import stem
from textindex.stopwords import content_words, is_stopword, stopword_list
from textindex.storage import dump, load, same_postings
from textindex.suggest import edit_distance, suggestions, unknown_words
from textindex.tokens import sentences, tokens

DOCS = [
    Document(0, "zero", "The lighthouse watches the storms."),
    Document(1, "one", "A garden in winter. The garden sleeps."),
    Document(2, "two", "The night train follows the river to the harbour."),
]


class TokenTests(unittest.TestCase):
    def test_tokens_and_offsets(self) -> None:
        found = tokens("It's the keeper's lamp.")
        self.assertEqual([t.text for t in found], ["it", "the", "keeper", "lamp"])
        self.assertEqual(found[3].start, 18)
        self.assertEqual(sentences("One. Two! Three"), ["One.", "Two!", "Three"])


class StopwordTests(unittest.TestCase):
    def test_stopwords(self) -> None:
        self.assertTrue(is_stopword("the"))
        self.assertFalse(is_stopword("lighthouse"))
        self.assertEqual(
            content_words(["the", "river", "and", "mill"]), ["river", "mill"]
        )
        self.assertEqual(len(stopword_list()), len(set(stopword_list())))


class StemmerTests(unittest.TestCase):
    def test_suffixes(self) -> None:
        self.assertEqual(stem("storms"), "storm")
        self.assertEqual(stem("watches"), "watch")
        self.assertEqual(stem("stories"), "story")
        self.assertEqual(stem("glass"), "glass")
        self.assertEqual(stem("is"), "is")


class IndexTests(unittest.TestCase):
    def test_index_and_queries(self) -> None:
        index = build(DOCS)
        self.assertEqual(index.documents, 3)
        self.assertEqual(index_terms("the storms")[0], ("storm", 1))
        self.assertEqual(evaluate(index, parse("garden")), {1})
        self.assertEqual(evaluate(index, parse("garden OR storms")), {0, 1})
        self.assertEqual(evaluate(index, parse("NOT garden")), {0, 2})
        self.assertEqual(evaluate(index, parse('"night train"')), {2})
        self.assertEqual(evaluate(index, parse('"train night"')), set())
        self.assertEqual(positive_terms(parse("garden NOT winter")), ["garden"])
        self.assertEqual(rank(index, {0, 1}, ["garden"], 1)[0][0], 1)
        self.assertEqual(vocabulary(index, 1), [("follow", 1)])
        with self.assertRaises(ValueError):
            parse('"open')
        with self.assertRaises(ValueError):
            parse("the")

    def test_report(self) -> None:
        lines = answer(build(DOCS), "river", 2)
        self.assertEqual(lines[0], "query 'river': 1 match(es)")


class SnippetTests(unittest.TestCase):
    def test_window(self) -> None:
        text = "one two three lamp four five lamp six"
        self.assertEqual(best_window(text, ["lamp"], 4), (3, 7))
        self.assertEqual(snippet(text, ["lamp"], 3), "... two three [lamp] ...")


class SuggestTests(unittest.TestCase):
    def test_suggestions(self) -> None:
        self.assertEqual(edit_distance("kitten", "sitting"), 3)
        self.assertEqual(suggestions("harbor", ["harbour", "river"]), ["harbour"])
        self.assertEqual(unknown_words(["a", "b", "a"], {"b"}), ["a"])


class DuplicateTests(unittest.TestCase):
    def test_shingles(self) -> None:
        a = shingles("a b c d")
        self.assertEqual(len(a), 2)
        self.assertEqual(jaccard(a, a), 1.0)
        self.assertEqual(jaccard(set(), set()), 1.0)
        texts = [(0, "a b c d"), (1, "a b c e"), (2, "x y z w")]
        self.assertEqual(near_duplicates(texts, 0.3), [(0, 1, 0.3333)])
        self.assertEqual(most_similar(texts), (0, 1, 0.3333))


class StatsTests(unittest.TestCase):
    def test_statistics(self) -> None:
        index = build(documents(30, 3))
        self.assertTrue(document_frequencies(index))
        self.assertLess(zipf_slope([100, 50, 33, 25]), 0)
        self.assertGreater(coverage(index, ["river", "harbour"]), 0)
        self.assertEqual(documents(5, 2), documents(5, 2))


class StorageTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        index = build(DOCS)
        saved = dump(index)
        self.assertTrue(saved[0].startswith("#lengths\t0:"))
        self.assertTrue(same_postings(index, load(saved)))
        with self.assertRaises(ValueError):
            load(["garden\t1:0"])


if __name__ == "__main__":
    unittest.main()
