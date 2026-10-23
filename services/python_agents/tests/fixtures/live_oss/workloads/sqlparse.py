"""OSS corpus benchmark: sqlparse splits, parses and reformats a generated
SQL script of 160 statements (joins, subqueries, CASE, GROUP BY, inserts).

Copied into the cloned repository as ``benchmarks/bench_sqlparse.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import sqlparse

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "sqlparse" / "__init__.py"
STATEMENTS = 160
TABLES = ("orders", "customers", "items", "payments", "shipments")
COLUMNS = ("id", "amount", "status", "created_at", "region", "total")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(sqlparse.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"sqlparse imported from {sqlparse.__file__}, not {PACKAGE_INIT}"
        )


def _select(rng: random.Random, n: int) -> str:
    a, b = rng.sample(TABLES, 2)
    cols = ", ".join(f"{a}.{c}" for c in rng.sample(COLUMNS, 3))
    return (
        f"select {cols}, case when {b}.amount > {n} then 'big' else 'small' end as size, "
        f"count(*) as n from {a} join {b} on {a}.id = {b}.id "
        f"where {a}.status in ('open', 'paid') and {b}.created_at > '2026-01-{n % 28 + 1:02d}' "
        f"and {a}.total > (select avg(total) from {a} where region = 'r{n % 9}') "
        f"group by {cols} having count(*) > {n % 5} order by n desc limit {n % 50 + 1};"
    )


def _insert(rng: random.Random, n: int) -> str:
    values = ", ".join(
        f"({n + i}, {rng.random() * 100:.2f}, 'status-{i}')" for i in range(6)
    )
    return f"insert into {rng.choice(TABLES)} (id, amount, status) values {values};"


def main() -> None:
    _checked()
    rng = random.Random(17)
    script = "\n".join(
        _select(rng, n) if n % 3 else _insert(rng, n) for n in range(STATEMENTS)
    )
    digest = hashlib.sha256()
    statements = sqlparse.split(script)
    for statement in statements:
        pretty = sqlparse.format(
            statement, reindent=True, keyword_case="upper", identifier_case="lower"
        )
        digest.update(pretty.encode())
        parsed = sqlparse.parse(statement)[0]
        digest.update(parsed.get_type().encode())
    print(f"sqlparse statements={len(statements)} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
