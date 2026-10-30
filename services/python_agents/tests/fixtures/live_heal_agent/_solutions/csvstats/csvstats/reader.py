"""A small CSV reader: commas separate fields, double quotes protect commas."""


class RowLengthError(ValueError):
    """A row does not have as many fields as the header."""


def split_row(line):
    """The fields of one line. A field in double quotes may hold commas; the
    quotes are not part of the value."""
    fields, current, quoted = [], "", False
    for char in line:
        if char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            fields.append(current)
            current = ""
        else:
            current += char
    fields.append(current)
    return fields


def read_rows(text):
    """The rows of ``text`` as dicts keyed by the header's names."""
    lines = [line for line in text.splitlines() if line.strip()]
    header = split_row(lines[0])
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        values = split_row(line)
        if len(values) != len(header):
            raise RowLengthError(
                f"line {number} has {len(values)} fields, expected {len(header)}"
            )
        rows.append(dict(zip(header, values, strict=False)))
    return rows
