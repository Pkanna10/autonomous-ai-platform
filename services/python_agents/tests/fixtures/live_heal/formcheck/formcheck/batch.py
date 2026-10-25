"""Validate a batch of sign-ups at once."""

from formcheck.rules import ValidationError, validate


def validate_all(records):
    """The valid records, and the error message of each other one by index."""
    valid, errors = [], {}
    for index, record in enumerate(records):
        try:
            valid.append(validate(record))
        except ValidationError as error:
            errors[index] = str(error)
    return valid, errors
