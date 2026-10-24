"""The rule set, as the JSON document the pricing service publishes."""

import json

CATEGORIES = tuple(f"cat-{n:03d}" for n in range(400))


def _rules() -> dict[str, dict[str, int]]:
    return {
        name: {"tax_permille": 50 + (n * 37) % 200, "discount_permille": (n * 11) % 90}
        for n, name in enumerate(CATEGORIES)
    }


RULES_JSON = json.dumps({"version": 3, "categories": _rules()}, sort_keys=True)
