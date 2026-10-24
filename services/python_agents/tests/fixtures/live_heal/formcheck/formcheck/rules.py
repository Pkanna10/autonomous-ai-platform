"""The rules a sign-up record must meet."""


class ValidationError(ValueError):
    """A record that breaks one or more rules."""


def check_record(record, problems=[]):
    """The problems ``record`` has, added to ``problems``."""
    if not record.get("name", "").strip():
        problems.append("name is required")
    email = record.get("email", "")
    if "@" not in email or email.startswith("@"):
        problems.append("email is invalid")
    if not record.get("age", "").isdigit():
        problems.append("age must be a whole number")
    return problems


def validate(record):
    """``record`` unchanged, or ``ValidationError`` naming every problem."""
    problems = check_record(record)
    if problems:
        raise ValidationError("; ".join(problems))
    return record
