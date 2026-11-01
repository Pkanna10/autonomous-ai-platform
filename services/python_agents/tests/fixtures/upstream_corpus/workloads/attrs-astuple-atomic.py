"""OSS corpus benchmark: attrs turns 12,000 nested order records into tuples
for a row-oriented export, four ways (the default recursion, retained
collection types, a filter, a list factory). Each order holds scalar fields,
a nested point, one to three item lines with five to ten string tags each, a
quantity history of 10 to 40 integers, a span, a dict and a frozenset.

Copied into the cloned repository as ``benchmarks/bench_attrs.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest. The
classes are defined in ``main`` (after ``_checked``), never at import.
"""

from __future__ import annotations

import hashlib
import random
from collections import namedtuple
from pathlib import Path

import attr

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "src" / "attr" / "__init__.py"
ORDERS = 12000
REGIONS = ("north", "south", "east", "west")
TAGS = (
    "red",
    "blue",
    "bulk",
    "fragile",
    "new",
    "gift",
    "cold",
    "heavy",
    "promo",
    "b2b",
)

Span = namedtuple("Span", ["start", "end"])


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(attr.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"attr imported from {attr.__file__}, not {PACKAGE_INIT}")


def _classes() -> tuple[type, type, type]:
    @attr.s(slots=True, frozen=True)
    class Point:
        x = attr.ib()
        y = attr.ib()

    @attr.s(slots=True)
    class Item:
        sku = attr.ib()
        quantity = attr.ib()
        price = attr.ib()
        tags = attr.ib(factory=tuple)

    @attr.s(slots=True)
    class Order:
        number = attr.ib()
        region = attr.ib()
        paid = attr.ib()
        origin = attr.ib()
        items = attr.ib()
        span = attr.ib()
        history = attr.ib(factory=list)
        meta = attr.ib(factory=dict)
        flags = attr.ib(factory=frozenset)
        note = attr.ib(default=None)

    return Point, Item, Order


def _orders(rng: random.Random, point: type, item: type, order: type) -> list:
    orders = []
    for n in range(ORDERS):
        lines = [
            item(
                f"sku-{(n * 3 + k) % 500:04d}",
                rng.randint(0, 40),
                round(rng.random() * 90, 2),
                tuple(rng.sample(TAGS, rng.randint(5, 10))),
            )
            for k in range(rng.randint(1, 3))
        ]
        origin = point(rng.randint(-50, 50), rng.randint(-50, 50))
        note = None if n % 3 else f"order {n}"
        meta = {"priority": n % 5, "batch": n // 100, "origin": origin}
        # At most one flag: a set's iteration order would otherwise depend
        # on the hash seed, and the digest covers the converted collections.
        flags = frozenset(rng.sample(("rush", "gift", "return", "sample"), n % 2))
        span = Span(n, n + rng.randint(1, 9))
        history = [rng.randint(0, 500) for _ in range(rng.randint(10, 40))]
        orders.append(
            order(
                n,
                rng.choice(REGIONS),
                n % 2 == 0,
                origin,
                lines,
                span,
                history,
                meta,
                flags,
                note,
            )
        )
    return orders


def _skip_private(attribute: object, value: object) -> bool:
    return getattr(attribute, "name", "") not in ("meta", "note")


def main() -> None:
    _checked()
    point, item, order = _classes()
    orders = _orders(random.Random(37), point, item, order)
    digest = hashlib.sha256()

    def feed(label: str, rows: list) -> None:
        digest.update(f"{label}:{len(rows)}".encode())
        for row in rows[::25]:
            digest.update(repr(row).encode())

    feed("default", [attr.astuple(o) for o in orders])
    feed("retain", [attr.astuple(o, retain_collection_types=True) for o in orders])
    feed("filtered", [attr.astuple(o, filter=_skip_private) for o in orders])
    feed("lists", [attr.astuple(o, tuple_factory=list) for o in orders[::2]])
    feed("flat", [attr.astuple(o, recurse=False)[:4] for o in orders])
    print(f"attrs orders={ORDERS} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
