"""OSS corpus benchmark: sqlparse parses, splits and strips the comments
from a generated 250-statement migration script that is commented the way
real ones are: a multi-line licence header, runs of ``--`` lines before
statements, trailing ``--`` comments after columns, ``/* hints */`` inside
expressions, block comments spanning lines, comments right before the
terminating semicolon, blocks of 20 to 60 ``--`` lines after some
statements (commented-out alternatives), and a commented-out rollback
section of 1,500 ``--`` lines at the end of the script (the previous
schema's DDL, kept for reference).

Copied into the cloned repository as ``benchmarks/bench_sqlparse.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import sqlparse
from sqlparse import sql

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "sqlparse" / "__init__.py"
STATEMENTS = 250
STRIPPED = 120
ROLLBACK_LINES = 1500
TABLES = ("orders", "customers", "items", "payments", "shipments")
COLUMNS = ("id", "amount", "status", "created_at", "region", "total")
HEADER = """/*
 * Migration script, generated for a benchmark.
 * Copyright: none. Licence: none.
 *
 * Every statement below carries comments of several kinds.
 */
"""


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(sqlparse.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"sqlparse imported from {sqlparse.__file__}, not {PACKAGE_INIT}"
        )


def _comment_run(rng: random.Random, n: int, lines: int | None = None) -> str:
    return "".join(
        f"-- note {n}.{k}: {rng.choice(COLUMNS)} {rng.choice(TABLES)}\n"
        for k in range(lines or rng.randint(1, 4))
    )


def _statement(rng: random.Random, n: int) -> str:
    table = rng.choice(TABLES)
    kind = n % 5
    if kind == 0:
        cols = ",\n".join(
            f"    {col} {rng.choice(('integer', 'text', 'numeric(12, 2)', 'timestamp'))} -- the {col}"
            for col in COLUMNS
        )
        body = f"create table {table}_{n} (\n{cols}\n    /* trailing block\n       comment */\n);"
    elif kind == 1:
        body = (
            f"select /*+ index({table} idx_{n}) */ {table}.id, -- key\n"
            f"    {table}.amount /* money */, {table}.status\n"
            f"from {table} -- source\n"
            f"where {table}.created_at > '2026-01-{n % 28 + 1:02d}' /* since */ and {table}.region = 'r{n % 9}'\n"
            f"order by {table}.id -- newest last\n;"
        )
    elif kind == 2:
        values = ", ".join(
            f"({n + i}, {rng.random() * 100:.2f}, 'status-{i}')" for i in range(5)
        )
        body = f"insert into {table} (id, amount, status) -- columns\nvalues {values}; -- rows"
    elif kind == 3:
        body = (
            f"update {table}\nset status = 'closed', -- was open\n    amount = amount * 1.{n % 9} /* uplift */\n"
            f"where id in (select id from {rng.choice(TABLES)} /* related */ where total > {n});"
        )
    else:
        body = f"alter table {table} add column note_{n} text; /* added in {n} */"
    prefix = _comment_run(rng, n) if n % 3 else ""
    if n % 25 == 24:
        # A commented-out alternative kept after the statement.
        suffix = (
            "\n-- alternative:\n" + _comment_run(rng, n, rng.randint(20, 60)) + "\n"
        )
    elif n % 4 == 0:
        suffix = f"\n-- end of {n}\n-- blank follows\n\n"
    else:
        suffix = "\n"
    return prefix + body + suffix


def _rollback(rng: random.Random) -> str:
    lines = ["-- DOWN (kept for reference, run by hand):\n"]
    for k in range(ROLLBACK_LINES):
        table = rng.choice(TABLES)
        if k % 3 == 0:
            lines.append(f"-- drop table if exists {table}_{k};\n")
        elif k % 3 == 1:
            lines.append(f"-- alter table {table} drop column note_{k};\n")
        else:
            lines.append(f"-- delete from {table} where id between {k} and {k + 5};\n")
    return "".join(lines)


def main() -> None:
    _checked()
    rng = random.Random(89)
    script = HEADER + "".join(_statement(rng, n) for n in range(STATEMENTS))
    script += "\n" + _rollback(rng)
    digest = hashlib.sha256()
    statements = sqlparse.parse(script)
    comments = 0
    for statement in statements:
        digest.update(statement.get_type().encode())
        digest.update(str(statement).encode())
        for token in statement.tokens:
            if isinstance(token, sql.Comment):
                comments += 1
                digest.update(token.value.encode())
    pieces = sqlparse.split(script)
    digest.update(f"{len(pieces)} {pieces[0]} {pieces[-1]}".encode())
    stripped = sqlparse.format("".join(pieces[:STRIPPED]), strip_comments=True)
    digest.update(stripped.encode())
    print(
        f"sqlparse bytes={len(script)} statements={len(statements)} comments={comments} "
        f"split={len(pieces)} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
