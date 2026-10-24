"""PostgreSQL fixtures for the persistence tests (Step 2, unit U8).

Tests that need a database take ``postgres_dsn`` or ``postgres_repository``
and carry the ``postgres`` marker. They run against the server at
``TEST_DATABASE_URL`` (PostgreSQL 16 with pgvector, a role that may create
databases, as in the CI service container) and are skipped when it is unset.

Each pytest process (every xdist worker, or the single process without
xdist) creates its own database, named after ``PYTEST_XDIST_WORKER`` and the
process id so two sessions on one server never share one, and applies
``infrastructure/schema/*.sql`` in file-name order, each file as one
simple-protocol query (the files hold ``DO`` blocks and several statements).
Every test starts from empty engine tables; the database is dropped when the
session ends. A server without pgvector fails the setup instead of skipping.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from autonomous_ai_agents.persistence.postgres import PostgresRepository

SCHEMA_DIR = Path(__file__).resolve().parents[4] / "infrastructure" / "schema"
"""The migrations CI applies, in file-name order."""

ENGINE_TABLES = (
    "lessons",
    "hypotheses",
    "hotspots",
    "performance_metrics",
    "task_executions",
    "workloads",
    "objectives",
    "guardrails",
    "projects",
)
"""Tables emptied before each test, children before their parents."""

# psycopg ships in the ``database`` extra. Without it there is nothing to run
# the Postgres-only module against, so it is not collected; when
# TEST_DATABASE_URL is set a missing driver is a broken setup and must fail.
collect_ignore: list[str] = []
if importlib.util.find_spec("psycopg") is None and not os.environ.get(
    "TEST_DATABASE_URL"
):
    collect_ignore.append("test_postgres.py")


@pytest.fixture(scope="session")
def schema_files() -> list[Path]:
    """Every migration file, in the order CI applies them."""
    files = sorted(SCHEMA_DIR.glob("*.sql"))
    assert files, f"no migrations under {SCHEMA_DIR}"
    return files


@pytest.fixture(scope="session")
def postgres_database(schema_files: list[Path]) -> Iterator[str]:
    """Create this process's test database with the schema applied; yield its DSN."""
    server = os.environ.get("TEST_DATABASE_URL")
    if not server:
        pytest.skip("TEST_DATABASE_URL is not set")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    name = f"aip_test_{worker}_{os.getpid()}"
    drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
        sql.Identifier(name)
    )
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(drop)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(server, dbname=name)
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            for path in schema_files:
                conn.execute(path.read_bytes())
        yield dsn
    finally:
        with psycopg.connect(server, autocommit=True) as admin:
            admin.execute(drop)


@pytest.fixture
def postgres_dsn(postgres_database: str) -> str:
    """The test database's DSN, with every engine table emptied."""
    import psycopg

    statements = "".join(f"DELETE FROM {table};" for table in ENGINE_TABLES)
    with psycopg.connect(postgres_database, autocommit=True) as conn:
        conn.execute(statements.encode())
    return postgres_database


@pytest.fixture
def postgres_repository(postgres_dsn: str) -> PostgresRepository:
    """A ``PostgresRepository`` on the emptied test database."""
    from autonomous_ai_agents.persistence.postgres import PostgresRepository

    return PostgresRepository(postgres_dsn)
