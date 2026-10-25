"""E-mail address syntax."""

import re

EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+")


def is_email(address):
    """Whether ``address`` (lower case) looks like a deliverable address."""
    return EMAIL.fullmatch(address) is not None
