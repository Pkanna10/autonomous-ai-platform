"""Normalise contact records and merge the ones that share an email address."""


def normalise_email(contact):
    """The contact's email address, trimmed and lower-cased."""
    return contact.get("email").strip().lower()


def merge_contacts(contacts):
    """One record per email address; a later record fills in missing fields."""
    merged = {}
    for contact in contacts:
        key = normalise_email(contact)
        if key in merged:
            kept = merged[key]
            for field, value in contact.items():
                if value and not kept.get(field):
                    kept[field] = value
        else:
            merged[key] = dict(contact, email=key)
    return list(merged.values())
