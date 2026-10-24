"""Workload: ``python -m textindex.main``."""

from textindex.duplicates import most_similar, near_duplicates
from textindex.index import build, vocabulary
from textindex.library import documents
from textindex.report import answer, summary
from textindex.stats import coverage, document_frequencies, length_histogram, zipf_slope
from textindex.storage import dump, load, same_postings
from textindex.suggest import suggestions, unknown_words
from textindex.tokens import sentences

QUERIES = (
    "lighthouse storms",
    "river OR harbour",
    '"night train" travellers',
    "garden NOT winter",
    "observatory stars",
    '"market square" festival',
    "bakery morning OR mill workers",
    "archive letters NOT photographs",
)
TYPED = ("lighthuse", "harbor", "bakery", "observatry", "festivl")


def main() -> None:
    library = documents(1200, 9)
    index = build(library)
    for line in summary(index):
        print(line)
    print("top terms " + " ".join(f"{t}:{n}" for t, n in vocabulary(index, 8)))
    for text in QUERIES:
        for line in answer(index, text, 3):
            print(line)
    terms = sorted(index.postings)
    for word in unknown_words(list(TYPED), set(terms)):
        print(f"did you mean {word!r}: {', '.join(suggestions(word, terms)) or '-'}")
    print(f"zipf slope {zipf_slope(document_frequencies(index)):.4f}")
    print(f"lengths {length_histogram(index, 10)}")
    print(f"coverage {coverage(index, ['lighthous', 'harbour']):.4f}")
    sample = [(d.number, d.text) for d in library[:120]]
    print(f"near duplicates {len(near_duplicates(sample, 0.25))}")
    print(f"most similar {most_similar(sample)}")
    print(f"sentences {sum(len(sentences(d.text)) for d in library)}")
    saved = dump(index)
    print(f"stored {len(saved)} lines, round trip {same_postings(index, load(saved))}")


if __name__ == "__main__":
    main()
