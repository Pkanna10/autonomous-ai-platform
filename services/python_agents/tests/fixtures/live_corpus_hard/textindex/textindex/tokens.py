"""Splitting text into normalised tokens."""

import re
from dataclasses import dataclass

APOSTROPHES = "'’"
WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")


@dataclass(frozen=True)
class Token:
    text: str
    position: int  # the token's index in its document
    start: int  # character offset in the original text


def normalise(word: str) -> str:
    """Lower-case, with apostrophes and a trailing possessive removed."""
    word = word.lower()
    for mark in APOSTROPHES:
        if word.endswith(mark + "s"):
            word = word[:-2]
        word = word.replace(mark, "")
    return word


def tokens(text: str) -> list[Token]:
    """The words of ``text`` in order, normalised, with their offsets."""
    out: list[Token] = []
    for match in WORD.finditer(text):
        word = normalise(match.group())
        if word:
            out.append(Token(word, len(out), match.start()))
    return out


def sentences(text: str) -> list[str]:
    """``text`` split after each full stop, question or exclamation mark."""
    parts: list[str] = []
    current: list[str] = []
    for ch in text:
        current.append(ch)
        if ch in ".?!":
            sentence = "".join(current).strip()
            if sentence:
                parts.append(sentence)
            current = []
    rest = "".join(current).strip()
    if rest:
        parts.append(rest)
    return parts
