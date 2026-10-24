"""Command line: ``python -m wordfreq.cli --words N --top K``."""

import argparse
from collections.abc import Sequence

from wordfreq.corpus import generate
from wordfreq.counter import count_words, top


def main(argv: Sequence[str] | None = None) -> int:
    """Print the ``--top`` most frequent words of a ``--words`` word corpus."""
    parser = argparse.ArgumentParser(prog="wordfreq")
    parser.add_argument("--words", type=int, default=20_000)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)
    for word, total in top(count_words(generate(args.words)), args.top):
        print(f"{word}\t{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
