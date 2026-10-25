"""Read a roster export: one name per line, blank lines skipped."""


def read_names(raw):
    """The names in the bytes of a roster export, in file order."""
    text = raw.decode("ascii")
    names = []
    for line in text.splitlines():
        name = line.strip()
        if name:
            names.append(name)
    return names


def load_roster(path):
    with open(path, "rb") as handle:
        return read_names(handle.read())
