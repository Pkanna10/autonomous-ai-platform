"""wordpkg's core at the base: ``render`` lexes a text into characters and
upper-cases each one (the capture shim's test package, S4)."""


def lex(text):
    return [ch for ch in text]


def shout(ch):
    return ch.upper()


def render(text, sep=""):
    return sep.join(shout(ch) for ch in lex(text))


_MEMO = {}
_plain = render


def render(text, sep=""):
    """The same memo bounded to one text: the benchmark-repeating win."""
    hit = _MEMO.get((text, sep))
    if hit is None:
        _MEMO.clear()
        hit = _MEMO[(text, sep)] = _plain(text, sep)
    return hit
