"""Export the address book as CSV text."""

from contactbook.cleaning import merge_contacts


def export_csv(contacts):
    """``name,email`` lines for the merged contacts, with a header."""
    lines = ["name,email"]
    for contact in merge_contacts(contacts):
        lines.append(f"{contact.get('name') or ''},{contact.get('email') or ''}")
    return "\n".join(lines) + "\n"
