"""The raw invoice lines of one day, generated deterministically.

Each line is a semicolon-separated record:

    invoice;customer;region;sku;family;quantity;unit_cents;day

A few lines are deliberately malformed (a missing field, a non-numeric
quantity, an unknown region) so the parser's rejections are exercised.
"""

FAMILIES = ("tools", "garden", "kitchen", "lighting", "storage", "paint")
REGIONS = (
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK",
)  # fmt: skip


class Lcg:
    """A linear congruential sequence: reproducible pseudo-random numbers."""

    def __init__(self, seed: int) -> None:
        self.state = seed

    def next(self) -> int:
        self.state = (self.state * 1103515245 + 12345) % (1 << 31)
        return self.state >> 4

    def pick(self, options: tuple[str, ...]) -> str:
        return options[self.next() % len(options)]

    def between(self, low: int, high: int) -> int:
        """An integer in ``[low, high]``."""
        return low + self.next() % (high - low + 1)


def customer_names(count: int, seed: int = 3) -> list[str]:
    """``count`` distinct customer names."""
    rng = Lcg(seed)
    first = ("Ada", "Ben", "Cleo", "Dov", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jun")
    last = ("Moss", "Reed", "Vale", "Hart", "Penn", "Lund", "Okafor", "Sato")
    names: list[str] = []
    for index in range(count):
        names.append(f"{rng.pick(first)} {rng.pick(last)} #{index:04d}")
    return names


def raw_lines(count: int, customers: int, seed: int = 11) -> list[str]:
    """``count`` raw lines over ``customers`` customers."""
    rng = Lcg(seed)
    names = customer_names(customers)
    lines: list[str] = []
    invoice = 50000
    customer = names[0]
    for index in range(count):
        if index == 0 or rng.next() % 4 == 0:
            invoice += 1
            customer = names[rng.next() % len(names)]
        region = rng.pick(REGIONS)
        family = rng.pick(FAMILIES)
        sku = f"{family[:3].upper()}-{rng.between(100, 999)}"
        quantity = str(rng.between(1, 40))
        unit = str(rng.between(99, 25000))
        day = f"2026-10-{rng.between(1, 28):02d}"
        if index % 997 == 13:
            quantity = "many"
        if index % 1499 == 7:
            region = "XX"
        fields = [str(invoice), customer, region, sku, family, quantity, unit, day]
        if index % 2003 == 5:
            fields.pop()
        lines.append(";".join(fields))
    return lines
