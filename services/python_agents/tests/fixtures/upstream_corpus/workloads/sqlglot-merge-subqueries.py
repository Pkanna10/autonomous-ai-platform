"""OSS corpus benchmark: sqlglot rewrites 36 generated analytical queries over
wide tables (20 to 30 columns each) built from nested derived tables (two to
four levels), CTEs that are joined twice or aggregated, window functions
whose results the outer query filters, groups or orders by, numeric literals
projected and then used in GROUP BY and ORDER BY, DISTINCT / LIMIT / GROUP BY
in inner selects, and outer joins on inner selects that join themselves, as
a query rewriter or SQL linter does: every query is qualified against the
schema and has its subqueries merged (half of them also with tables left
isolated), and every third query runs through the full optimizer.

Copied into the cloned repository as ``benchmarks/bench_sqlglot.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import sqlglot
from sqlglot import parse_one
from sqlglot.optimizer import optimize
from sqlglot.optimizer.merge_subqueries import merge_subqueries
from sqlglot.optimizer.qualify import qualify

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "sqlglot" / "__init__.py"
QUERIES = 36


def _wide(base: dict[str, str], extra: int) -> dict[str, str]:
    """``base`` plus ``extra`` typed attribute columns, as analytics tables have."""
    kinds = ("INT", "DOUBLE", "TEXT", "DATE", "BOOLEAN")
    return {**base, **{f"attr_{k:02d}": kinds[k % len(kinds)] for k in range(extra)}}


SCHEMA = {
    "orders": _wide(
        {
            "id": "INT",
            "customer_id": "INT",
            "status": "TEXT",
            "total": "DOUBLE",
            "created_at": "DATE",
            "channel": "TEXT",
        },
        24,
    ),
    "customers": _wide(
        {"id": "INT", "name": "TEXT", "region": "TEXT", "tier": "INT"}, 22
    ),
    "items": _wide(
        {"order_id": "INT", "sku": "TEXT", "qty": "INT", "price": "DOUBLE"}, 16
    ),
    "payments": _wide(
        {"order_id": "INT", "amount": "DOUBLE", "method": "TEXT", "paid_at": "DATE"},
        16,
    ),
}


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(sqlglot.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"sqlglot imported from {sqlglot.__file__}, not {PACKAGE_INIT}"
        )


def _inner(rng: random.Random, table: str, depth: int, n: int) -> str:
    """A derived table over ``table``, nested ``depth`` levels deep."""
    columns = list(SCHEMA[table])
    if depth == 0:
        return f"(SELECT * FROM {table} WHERE {columns[-1]} IS NOT NULL) AS b{n}"
    alias = f"i{n}_{depth}"
    inner = _inner(rng, table, depth - 1, n)
    inner_alias = inner.rsplit(" AS ", 1)[1]
    shape = rng.randrange(7)
    projected = ", ".join(f"{inner_alias}.{c}" for c in columns)
    if shape == 0:
        body = f"SELECT {projected}, ROW_NUMBER() OVER (PARTITION BY {inner_alias}.{columns[1]} ORDER BY {inner_alias}.{columns[0]}) AS rn FROM {inner}"
    elif shape == 1:
        body = (
            f"SELECT {projected}, {rng.randint(1, 9)} AS lit, 'x' AS tag FROM {inner}"
        )
    elif shape == 2:
        body = f"SELECT DISTINCT {projected} FROM {inner}"
    elif shape == 3:
        body = f"SELECT {projected}, COUNT(*) AS cnt FROM {inner} GROUP BY {projected}"
    elif shape == 4:
        body = f"SELECT {projected} FROM {inner} ORDER BY {inner_alias}.{columns[0]} LIMIT {rng.randint(5, 50)}"
    elif shape == 5:
        body = (
            f"SELECT {projected}, c.name AS customer_name FROM {inner} "
            f"JOIN customers AS c ON c.id = {inner_alias}.{columns[1]}"
        )
    else:
        body = f"SELECT {projected} FROM {inner} WHERE {inner_alias}.{columns[0]} > {rng.randint(0, 500)}"
    return f"({body}) AS {alias}"


def _query(rng: random.Random, n: int) -> str:
    table = rng.choice(("orders", "customers"))
    other = rng.choice(("items", "payments"))
    main_inner = _inner(rng, table, rng.randint(1, 3), n)
    main_alias = main_inner.rsplit(" AS ", 1)[1]
    side_inner = _inner(rng, other, rng.randint(0, 2), n + 1000)
    side_alias = side_inner.rsplit(" AS ", 1)[1]
    order_columns = ", ".join(list(SCHEMA["orders"])[:12])
    cte_a = f"cte_a{n} AS (SELECT {order_columns} FROM orders WHERE total > {rng.randint(1, 99)})"
    cte_b = f"cte_b{n} AS (SELECT order_id, SUM(amount) AS paid, COUNT(*) AS payments FROM payments GROUP BY order_id)"
    cte_c = f"cte_c{n} AS (SELECT id AS cid, region, tier FROM customers)"
    selects = [
        f"{main_alias}.id AS main_id",
        f"{side_alias}.order_id AS side_id",
        "a.total",
        "a2.status AS status_again",
        "b.paid",
    ]
    tail = ""
    shape = rng.randrange(5)
    if shape == 0:
        selects.append(f"{rng.randint(1, 3)} AS grp")
        tail = f" GROUP BY {main_alias}.id, {side_alias}.order_id, a.total, a2.status, b.paid, {len(selects)} ORDER BY {len(selects)}"
    elif shape == 1:
        tail = f" WHERE {main_alias}.id > {rng.randint(0, 100)} ORDER BY a.total DESC LIMIT {rng.randint(1, 20)}"
    elif shape == 2:
        selects.append("c1.region AS region1")
        selects.append("c2.region AS region2")
        tail = f" JOIN cte_c{n} AS c1 ON c1.cid = {main_alias}.id LEFT JOIN cte_c{n} AS c2 ON c2.cid = {side_alias}.order_id"
    elif shape == 3:
        tail = f" WHERE EXISTS (SELECT 1 FROM cte_c{n} AS cc WHERE cc.cid = {main_alias}.id) ORDER BY 1, 2"
    join_kind = rng.choice(("JOIN", "LEFT JOIN", "CROSS JOIN"))
    on = (
        ""
        if join_kind == "CROSS JOIN"
        else f" ON {side_alias}.order_id = {main_alias}.id"
    )
    joins = (
        f" {join_kind} {side_inner}{on}"
        f" JOIN cte_a{n} AS a ON a.id = {main_alias}.id"
        f" LEFT JOIN cte_a{n} AS a2 ON a2.customer_id = {main_alias}.id"  # the CTE twice
        f" LEFT JOIN cte_b{n} AS b ON b.order_id = a.id"
    )
    if shape == 2:
        # The cte_c joins go after the other joins.
        joins, tail = joins + tail, ""
    return f"WITH {cte_a}, {cte_b}, {cte_c} SELECT {', '.join(selects)} FROM {main_inner}{joins}{tail}"


def main() -> None:
    _checked()
    from sqlglot.errors import SqlglotError

    rng = random.Random(79)
    digest = hashlib.sha256()
    merged_chars = failed = 0
    for n in range(QUERIES):
        sql = _query(rng, n)
        try:
            merged = merge_subqueries(qualify(parse_one(sql), schema=SCHEMA))
            text = merged.sql()
            merged_chars += len(text)
            digest.update(text.encode())
            if n % 2 == 0:
                isolated = merge_subqueries(
                    qualify(parse_one(sql), schema=SCHEMA), leave_tables_isolated=True
                )
                digest.update(isolated.sql().encode())
            if n % 3 == 0:
                optimized = optimize(parse_one(sql), schema=SCHEMA)
                digest.update(optimized.sql().encode())
        except SqlglotError as error:  # a tool skips the queries it cannot resolve
            failed += 1
            digest.update(f"{n} {type(error).__name__}".encode())
    print(
        f"sqlglot queries={QUERIES} failed={failed} merged_chars={merged_chars} "
        f"sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
