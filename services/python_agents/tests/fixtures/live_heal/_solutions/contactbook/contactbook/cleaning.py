"""Normalise contact records and merge the ones that share an email address."""


def normalise_email(contact):
    """The contact's email address, trimmed and lower-cased; ``None`` if it has none."""
    email = contact.get("email")
    if email is None or not email.strip():
        return None
    return email.strip().lower()


def merge_contacts(contacts):
    """One record per email address; a later record fills in missing fields.

    Contacts without an email address are kept as they are, never merged.
    """
    merged = {}
    without_email = []
    for contact in contacts:
        key = normalise_email(contact)
        if key is None:
            without_email.append(dict(contact))
        elif key in merged:
            kept = merged[key]
            for field, value in contact.items():
                if value and not kept.get(field):
                    kept[field] = value
        else:
            merged[key] = dict(contact, email=key)
    return list(merged.values()) + without_email
