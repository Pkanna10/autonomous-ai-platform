"""wordpkg's core at the base: ``render`` lexes a text into characters and
upper-cases each one (the capture shim's test package, S4)."""


def lex(text):
    return [ch for ch in text]


def shout(ch):
    return ch.upper()


def render(text, sep=""):
    return sep.join(shout(ch) for ch in lex(text))
