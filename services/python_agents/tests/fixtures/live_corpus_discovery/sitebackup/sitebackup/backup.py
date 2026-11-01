"""The backup archive."""

import hashlib
import lzma


def bundle(site: dict[str, list[str]]) -> bytes:
    """Every page, in section order, as one UTF-8 document."""
    document = ""
    for section, pages in site.items():
        document = document + f"== {section}\n" + "".join(pages)
    return document.encode()


def archive(site: dict[str, list[str]]) -> bytes:
    return lzma.compress(bundle(site), preset=6)


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
