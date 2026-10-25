"""The subscriber list."""

from newsletter.normalise import canonical_email
from newsletter.validate import is_email


class InvalidEmailError(ValueError):
    pass


class AlreadySubscribedError(ValueError):
    pass


class Subscribers:
    """Subscribers by canonical address: one subscription per inbox."""

    def __init__(self):
        self._by_key = {}

    def subscribe(self, address, name):
        key = canonical_email(address)
        if not is_email(key):
            raise InvalidEmailError(f"not a valid email address: {address!r}")
        if key in self._by_key:
            raise AlreadySubscribedError(f"{address!r} is already subscribed")
        self._by_key[key] = {"address": address.strip(), "name": name}

    def is_subscribed(self, address):
        return canonical_email(address) in self._by_key

    def __len__(self):
        return len(self._by_key)
