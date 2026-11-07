"""wordpkg's core at the base: ``render`` lexes a text into characters and
upper-cases the text once (a real cut on every input, the capture shim's test package, S4)."""


def lex(text):
    return [ch for ch in text]


def shout(ch):
    return ch.upper()


def render(text, sep=""):
    return sep.join(lex(text.upper()))
