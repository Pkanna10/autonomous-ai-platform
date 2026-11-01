"""Remembering each file's delimiter, so a file is sniffed only once."""

from confload.sniff import sniff

_DIALECTS = {}


def dialect_for(name, text):
    """The delimiter of the file ``name`` holding ``text``: sniffed the first
    time the file is loaded, then remembered for that file."""
    key = name.rsplit(".", 1)[-1]
    if key not in _DIALECTS:
        _DIALECTS[key] = sniff(text)
    return _DIALECTS[key]


def forget():
    """Forget every remembered delimiter."""
    _DIALECTS.clear()
