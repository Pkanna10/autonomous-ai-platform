"""Canonical e-mail addresses: one key per inbox."""

import re

TAG = re.compile(r"\+[^@]*(?=@)")


def canonical_email(address):
    """The key a subscriber is stored under: trimmed, lower-cased and
    without a "+tag" in the local part, since ann+news@example.com and
    ann@example.com deliver to the same inbox."""
    return TAG.sub("", address.strip().lower())
