"""OSS corpus benchmark: sqlglot qualifies and optimizes 80 generated BigQuery
queries that select struct fields out of ``UNNEST`` of array columns reached
through chains of CTEs and derived tables (``SELECT *`` and renamed
projections along the way, nested arrays unnested twice), against a schema
of typed array-of-struct columns, as a lineage or column-level analysis tool
does. Most chains are short (two to six CTEs); one query in four is a
dbt-style model of 13 to 17 chained CTEs in which a middle CTE renames the
array column before the final select unnests it.

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
from sqlglot.optimizer.qualify import qualify

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "sqlglot" / "__init__.py"
QUERIES = 80
SCHEMA = {
    "orders": {
        "id": "INT64",
        "customer_id": "INT64",
        "status": "STRING",
        "items": "ARRAY<STRUCT<sku STRING, qty INT64, price FLOAT64, tags ARRAY<STRING>>>",
        "events": "ARRAY<STRUCT<kind STRING, at TIMESTAMP, meta STRUCT<code INT64, note STRING>>>",
    },
    "customers": {
        "id": "INT64",
        "name": "STRING",
        "addresses": "ARRAY<STRUCT<city STRING, zip STRING, lines ARRAY<STRING>>>",
    },
    "shipments": {
        "order_id": "INT64",
        "carrier": "STRING",
        "legs": "ARRAY<STRUCT<origin STRING, dest STRING, hours FLOAT64>>",
    },
    "catalog": {"sku": "STRING", "title": "STRING", "weight": "FLOAT64"},
}
ARRAYS = {
    "orders": (("items", ("sku", "qty", "price")), ("events", ("kind", "at"))),
    "customers": (("addresses", ("city", "zip")),),
    "shipments": (("legs", ("origin", "dest", "hours")),),
}
LONG_EVERY = 4
LONG_DEPTH = (13, 17)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(sqlglot.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"sqlglot imported from {sqlglot.__file__}, not {PACKAGE_INIT}"
        )


def _query(rng: random.Random, n: int) -> str:
    table = rng.choice(tuple(ARRAYS))
    columns = [c for c in SCHEMA[table] if not SCHEMA[table][c].startswith("ARRAY")]
    arrays = ARRAYS[table]
    long_chain = n % LONG_EVERY == 0
    depth = rng.randint(*LONG_DEPTH) if long_chain else rng.randint(2, 6)
    rename_at = rng.randint(depth // 3, 2 * depth // 3) if long_chain else -1
    names = {array: array for array, _ in arrays}  # the array's current name
    ctes = []
    previous = table
    for level in range(depth):
        name = f"c{n}_{level}"
        if level == rename_at:
            # A staging model renames the array columns (items AS line_items).
            renamed = ", ".join(f"{names[a]} AS {a}_renamed" for a, _ in arrays)
            body = f"SELECT {', '.join(columns)}, {renamed} FROM {previous}"
            names = {a: f"{a}_renamed" for a in names}
        elif level % 2 == 0 or rng.random() < 0.3:
            body = f"SELECT * FROM {previous}"
        else:
            projected = ", ".join(
                columns + [f"{names[a]} AS {names[a]}" for a, _ in arrays]
            )
            body = f"SELECT {projected} FROM {previous} WHERE {columns[0]} IS NOT NULL"
        if level == depth - 1 and not long_chain and rng.random() < 0.4:
            # The last link narrows the projection to one array column.
            body = f"SELECT {columns[0]}, {names[arrays[0][0]]} FROM {previous}"
            arrays = arrays[:1]
        ctes.append(f"{name} AS ({body})")
        previous = name
    unnests = []
    selects = [f"{previous}.{columns[0]}"]
    for index, (array, fields) in enumerate(arrays):
        if index > 0 and rng.random() < 0.5:
            continue
        alias = f"u{index}"
        unnests.append(f"UNNEST({previous}.{names[array]}) AS {alias}")
        for field in rng.sample(fields, rng.randint(1, len(fields))):
            selects.append(f"{alias}.{field} AS {array}_{field}")
        if array == "items" and rng.random() < 0.6:
            unnests.append(f"UNNEST({alias}.tags) AS tag")
            selects.append("tag")
    where = (
        f" WHERE {previous}.{columns[0]} > {rng.randint(0, 100)}"
        if rng.random() < 0.5
        else ""
    )
    if rng.random() < 0.3:
        # A derived table around the chain instead of a bare CTE reference.
        source = f"(SELECT * FROM {previous}) AS d{n}"
        selects = [s.replace(f"{previous}.", f"d{n}.") for s in selects]
        unnests = [u.replace(f"{previous}.", f"d{n}.") for u in unnests]
        where = where.replace(f"{previous}.", f"d{n}.")
    else:
        source = previous
    return (
        f"WITH {', '.join(ctes)} SELECT {', '.join(selects)} FROM {source}, "
        f"{', '.join(unnests)}{where} LIMIT {rng.randint(10, 500)}"
    )


def main() -> None:
    _checked()
    from sqlglot.errors import SqlglotError

    rng = random.Random(73)
    digest = hashlib.sha256()
    failed = 0
    for n in range(QUERIES):
        sql = _query(rng, n)
        try:
            qualified = qualify(
                parse_one(sql, read="bigquery"), schema=SCHEMA, dialect="bigquery"
            )
            digest.update(qualified.sql(dialect="bigquery").encode())
            if n % 2 == 0:
                optimized = optimize(
                    parse_one(sql, read="bigquery"), schema=SCHEMA, dialect="bigquery"
                )
                digest.update(optimized.sql(dialect="bigquery").encode())
        except SqlglotError as error:  # a tool skips the queries it cannot resolve
            failed += 1
            digest.update(f"{n} {type(error).__name__}".encode())
    print(f"sqlglot queries={QUERIES} failed={failed} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
