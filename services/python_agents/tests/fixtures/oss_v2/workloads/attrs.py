"""OSS corpus v2 benchmark: attrs builds 30,000 validated and converted
instances of four classes (slotted, frozen, ordered, nested), compares,
sorts, hashes and evolves them, and turns them into dicts and tuples.

Copied into the cloned repository as ``benchmarks/bench_attrs.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest. The
classes are defined in ``main`` (after ``_checked``), never at import.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import attr

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "src" / "attr" / "__init__.py"
ORDERS = 15000
REGIONS = ("north", "south", "east", "west")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(attr.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"attr imported from {attr.__file__}, not {PACKAGE_INIT}")


def _classes() -> tuple[type, type, type, type]:
    v = attr.validators

    @attr.s(slots=True, frozen=True, order=True)
    class Point:
        x = attr.ib(validator=v.instance_of(int))
        y = attr.ib(validator=v.instance_of(int))

    @attr.s(slots=True, order=True)
    class Item:
        sku = attr.ib(validator=[v.instance_of(str), v.min_len(3)])
        quantity = attr.ib(converter=int, validator=v.ge(0))
        price = attr.ib(converter=float, validator=v.and_(v.ge(0.0), v.lt(1e6)))
        tags = attr.ib(
            factory=tuple,
            validator=v.deep_iterable(v.instance_of(str), v.instance_of(tuple)),
        )

    @attr.s(slots=True)
    class Order:
        number = attr.ib(validator=v.instance_of(int))
        region = attr.ib(validator=v.in_(REGIONS))
        origin = attr.ib(validator=v.instance_of(Point))
        items = attr.ib(validator=v.deep_iterable(v.instance_of(Item)))
        note = attr.ib(default=None, validator=v.optional(v.instance_of(str)))
        meta = attr.ib(
            factory=dict,
            validator=v.deep_mapping(v.instance_of(str), v.instance_of(int)),
        )

    @attr.s(frozen=True)
    class Summary:
        count = attr.ib()
        total = attr.ib()
        regions = attr.ib(converter=tuple)

    return Point, Item, Order, Summary


def main() -> None:
    _checked()
    point, item, order, summary = _classes()
    rng = random.Random(37)
    digest = hashlib.sha256()
    orders = []
    for n in range(ORDERS):
        lines = [
            item(
                f"sku-{(n * 3 + k) % 500:04d}",
                str(rng.randint(0, 40)),
                rng.random() * 90,
                tuple(rng.sample(("red", "blue", "bulk", "fragile", "new"), 2)),
            )
            for k in range(rng.randint(1, 3))
        ]
        origin = point(rng.randint(-50, 50), rng.randint(-50, 50))
        note = None if n % 3 else f"order {n}"
        meta = {"priority": n % 5, "batch": n // 100}
        orders.append(order(n, rng.choice(REGIONS), origin, lines, note, meta))
    items = sorted(line for o in orders for line in o.items)
    digest.update(repr(items[:50]).encode())
    points = sorted({o.origin for o in orders})
    digest.update(repr(points[:50]).encode())
    moved = [attr.evolve(o, region=REGIONS[o.number % 4]) for o in orders]
    for o in moved[::5]:
        digest.update(repr(attr.asdict(o)).encode())
        digest.update(repr(attr.astuple(o.origin)).encode())
    same = sum(a == b for a, b in zip(orders, moved, strict=True))
    total = summary(len(orders), sum(len(o.items) for o in orders), REGIONS)
    digest.update(repr(total).encode())
    print(
        f"attrs orders={len(orders)} items={len(items)} same={same} "
        f"sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
