"""OSS corpus benchmark: sqlparse reformats 16 wide generated statements
(SELECTs with 40 to 80 projected columns, CASE expressions, function calls
and nested parentheses, joins, subqueries in FROM and IN (...), BETWEEN ...
AND, GROUP BY lists; INSERT ... VALUES with 60 columns; UPDATE ... SET with
50 assignments; 3 to 8 KB each) with re-indentation in two styles (plain,
and comma-first with indented columns and wrapping), as a SQL
pretty-printer does.

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
STATEMENTS = 16
TABLES = ("orders", "customers", "items", "payments", "shipments")
COLUMNS = (
    "id",
    "amount",
    "status",
    "created_at",
    "region",
    "total",
    "qty",
    "sku",
    "note",
)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(sqlparse.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"sqlparse imported from {sqlparse.__file__}, not {PACKAGE_INIT}"
        )


def _projection(rng: random.Random, table: str, k: int) -> str:
    column = rng.choice(COLUMNS)
    shape = k % 6
    if shape == 0:
        return f"case when {table}.{column} > {k} then 'big' when {table}.{column} is null then 'none' else 'small' end as size_{k}"
    if shape == 1:
        return f"coalesce(sum({table}.{column}), round(avg({table}.amount), 2), 0) as agg_{k}"
    if shape == 2:
        return f"({table}.{column} * (1 + {k} / 100.0)) as adjusted_{k}"
    if shape == 3:
        return f"(select max({column}) from {rng.choice(TABLES)} where id = {table}.id) as sub_{k}"
    return f"{table}.{column} as col_{k}"


def _select(rng: random.Random, n: int) -> str:
    a, b, c = rng.sample(TABLES, 3)
    width = rng.randint(40, 80)
    cols = ",\n".join(_projection(rng, a, k) for k in range(width))
    ids = ", ".join(str(rng.randint(1, 9999)) for _ in range(30))
    return (
        f"select {cols} from {a} inner join {b} on {a}.id = {b}.id and {b}.status in ('open', 'paid') "
        f"left outer join (select id, count(*) as n from {c} group by id having count(*) > {n % 5}) as agg on agg.id = {a}.id "
        f"where {a}.created_at between '2026-01-01' and '2026-12-31' and {a}.region in ('r1', 'r2', 'r3') "
        f"and {a}.id in ({ids}) and ({a}.total > (select avg(total) from {a}) or {b}.amount < {n}) "
        f"group by {', '.join(f'{a}.{col}' for col in COLUMNS)} order by {a}.id desc, {b}.amount limit {n % 50 + 1};"
    )


def _insert(rng: random.Random, n: int) -> str:
    names = ", ".join(f"col_{k}" for k in range(60))
    rows = ",\n".join(
        "("
        + ", ".join(
            rng.choice(
                (str(rng.randint(0, 999)), f"'text-{k}'", "null", "current_timestamp")
            )
            for k in range(60)
        )
        + ")"
        for _ in range(4)
    )
    return f"insert into {rng.choice(TABLES)} ({names}) values {rows};"


def _update(rng: random.Random, n: int) -> str:
    sets = ", ".join(
        f"col_{k} = case when col_{k} is null then {k} else col_{k} + {n} end"
        if k % 4 == 0
        else f"col_{k} = {rng.randint(0, 99)}"
        for k in range(50)
    )
    return f"update {rng.choice(TABLES)} set {sets} where id between {n} and {n + 500} and status = 'open';"


def main() -> None:
    _checked()
    rng = random.Random(83)
    digest = hashlib.sha256()
    chars = 0
    for n in range(STATEMENTS):
        if n % 4 == 3:
            statement = _insert(rng, n) if n % 8 == 3 else _update(rng, n)
        else:
            statement = _select(rng, n)
        plain = sqlparse.format(statement, reindent=True, keyword_case="upper")
        fancy = sqlparse.format(
            statement,
            reindent=True,
            comma_first=True,
            indent_columns=True,
            wrap_after=100,
            indent_width=4,
        )
        chars += len(plain) + len(fancy)
        digest.update(plain.encode())
        digest.update(fancy.encode())
    print(f"sqlparse statements={STATEMENTS} chars={chars} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
