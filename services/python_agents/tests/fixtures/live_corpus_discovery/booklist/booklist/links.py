"""Link slugs for titles."""


def slug(title: str) -> str:
    """The title in lower case, each run of other characters as one dash,
    none at either end."""
    out = ""
    pending = False
    for char in title.lower():
        if "a" <= char <= "z" or "0" <= char <= "9":
            if pending and out:
                out += "-"
            out += char
            pending = False
        else:
            pending = True
    return out
