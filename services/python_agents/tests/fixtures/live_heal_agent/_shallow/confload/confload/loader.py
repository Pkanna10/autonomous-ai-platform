"""Loading a table."""

from confload.cache import dialect_for, forget


class TableError(ValueError):
    """A row does not have the table's columns."""


def load_table(name, text, columns):
    """The rows of ``text`` (the file ``name``) as dicts keyed by
    ``columns``, the header row included; every row must have exactly
    ``len(columns)`` fields."""
    delimiter = dialect_for(name, text)
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split(delimiter)
        if len(fields) != len(columns) and number == 1:  # a stale delimiter
            forget()
            delimiter = dialect_for(name, text)
            fields = line.split(delimiter)
        if len(fields) != len(columns):
            raise TableError(
                f"{name} line {number} has {len(fields)} field(s), expected "
                f"{len(columns)}"
            )
        rows.append(dict(zip(columns, fields, strict=False)))
    return rows
