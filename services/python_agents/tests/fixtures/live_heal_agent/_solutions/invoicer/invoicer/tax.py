"""Tax rates by category and country."""

RATES = {
    "de": {"books": 0.07, "food": 0.07, "standard": 0.19},
    "fr": {"books": 0.055, "food": 0.055, "standard": 0.20},
}


class TaxRateError(LookupError):
    """No rate is known for the category in the country."""


def rate_for(category, country):
    """The tax rate of ``category`` in ``country``, an ISO 3166 country code
    in any case ("de" and "DE" are the same country)."""
    try:
        return RATES[country.lower()][category]
    except KeyError:
        raise TaxRateError(f"no rate for {category!r} in {country!r}") from None
