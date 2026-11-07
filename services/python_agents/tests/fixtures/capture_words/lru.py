"""wordpkg's core at the base: ``render`` lexes a text into characters and
upper-cases each one, ``render`` memoised by ``functools.lru_cache`` on the
point itself (the capture shim's test package, S4)."""

import functools


def lex(text):
    return [ch for ch in text]


def shout(ch):
    return ch.upper()


@functools.lru_cache(maxsize=None)  # noqa: UP033 (a workload: Python 3.8)
def render(text, sep=""):
    return sep.join(shout(ch) for ch in lex(text))
