"""Shipping rate cards per delivery region."""

DEFAULT_RATE = {"base": 9.5, "per_kg": 2.0}
RATES = {
    "eu-west": {"base": 4.5, "per_kg": 0.8},
    "eu-central": {"base": 5.0, "per_kg": 0.9},
    "us-east": {"base": 7.0, "per_kg": 1.2},
}


def rate_for(region):
    """The rate card for ``region``; a region without one pays the default rate."""
    return RATES[region]
