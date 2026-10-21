"""PostgreSQL ``Repository``: runs, trials, verdicts and lessons (Step 2).

Storage, from ``infrastructure/schema/003_engine.sql`` and
``004_engine_repository.sql``:

| Calls                          | Where                                          |
| ------------------------------ | ---------------------------------------------- |
| ``save_run`` / ``get_run``     | a ``projects`` row (upsert on id) and one      |
|                                | ``task_executions`` row per run                |
|                                | (``thread_id = run_id``, unique since 004)     |
|                                | holding the full state as JSONB plus copies of |
|                                | phase, status, counters, baseline and delivery |
| ``save_trial`` / ``list_trials`` | the run row's ``trials`` JSONB array         |
| ``save_verdict`` / ``list_verdicts`` | the run row's ``verdicts`` JSONB array   |
| ``save_lesson`` / ``list_lessons`` | ``lessons`` typed columns, ordered by      |
|                                | ``seq`` (004)                                  |

Rules:

- One short connection and one transaction per call; literal SQL only, every
  value a ``%(name)s`` parameter (JSON as ``Jsonb``). No ORM.
- Every id bound for a UUID column (project, objective, workload, trial,
  verdict, hypothesis, technique, lesson) must be a canonical uuid string,
  and every run id must pass ``validate_run_id``. Both are checked before
  connecting; a failure raises ``InvalidRecordIdError`` naming the field and
  the value, and nothing is written. Reads accept any id and find nothing.
- ``save_run`` never writes the trials or verdicts columns; a trial saved
  before its run creates a placeholder row without state, so ``get_run`` keeps
  returning ``None`` until the run is saved.
- Trials and verdicts are upserted by id inside their JSONB array: a known id
  is replaced in place, a new one appended, so listings keep insertion order.
  The row lock of ``INSERT ... ON CONFLICT DO UPDATE`` serialises concurrent
  writers to one run.
- One project id per ``root_path``: saving a run whose project root is
  registered under another id rolls back and raises ``ProjectConflictError``
  naming the root and the registered id.
- JSONB and TEXT cannot hold U+0000, which a trial's diff or stderr tail can
  carry, so every stored string (JSON keys included) writes it as
  ``STORAGE_ESCAPE`` + ``"0"`` and the escape itself as two escapes; reads
  undo it, so every value comes back exactly as the in-memory backend keeps it.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from typing import Any, LiteralString, cast

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from autonomous_ai_agents.common.errors import (
    InvalidRecordIdError,
    ProjectConflictError,
)
from autonomous_ai_agents.common.models import Lesson, Trial, Verdict
from autonomous_ai_agents.orchestrator.serde import dump_state, load_state
from autonomous_ai_agents.orchestrator.state import EngineState, validate_run_id

ROOT_PATH_CONSTRAINT = "projects_root_path_key"
"""Postgres's name for the ``UNIQUE`` on ``projects.root_path`` (003)."""

PLACEHOLDER_INTENT = "engine run (state not saved yet)"
"""``user_intent`` (NOT NULL) of a run row created by an early trial or verdict."""

_STATUS: Mapping[str, str] = {
    "connect": "pending",
    "done": "success",
    "failed": "failed",
}
"""``task_executions.status`` per phase (``chk_status``); every other phase runs."""

STORAGE_ESCAPE = "\ue000"
"""Stands for U+0000 in stored text (a Unicode private-use character)."""

_ESCAPED = re.compile(f"{STORAGE_ESCAPE}([{STORAGE_ESCAPE}0])")

_TRIALS: TypeAdapter[tuple[Trial, ...]] = TypeAdapter(tuple[Trial, ...])
_VERDICTS: TypeAdapter[tuple[Verdict, ...]] = TypeAdapter(tuple[Verdict, ...])

_UPSERT_PROJECT: LiteralString = """
INSERT INTO projects (id, name, root_path, default_branch, language, hardware,
                      test_command, created_at)
VALUES (%(id)s, %(name)s, %(root_path)s, %(default_branch)s, %(language)s,
        %(hardware)s, %(test_command)s, %(created_at)s)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name, root_path = EXCLUDED.root_path,
  default_branch = EXCLUDED.default_branch, language = EXCLUDED.language,
  hardware = EXCLUDED.hardware, test_command = EXCLUDED.test_command
"""

_UPSERT_RUN: LiteralString = """
INSERT INTO task_executions (thread_id, user_intent, status, phase, project_id,
  objective_ids, baseline, delivery, state, tokens_used, estimated_cost_usd,
  error_message, completed_at)
VALUES (%(run_id)s, %(user_intent)s, %(status)s, %(phase)s, %(project_id)s,
  %(objective_ids)s, %(baseline)s, %(delivery)s, %(state)s, %(tokens_used)s,
  %(cost_usd)s, %(error)s, CASE WHEN %(ended)s THEN NOW() END)
ON CONFLICT (thread_id) DO UPDATE SET
  user_intent = EXCLUDED.user_intent, status = EXCLUDED.status,
  phase = EXCLUDED.phase, project_id = EXCLUDED.project_id,
  objective_ids = EXCLUDED.objective_ids, baseline = EXCLUDED.baseline,
  delivery = EXCLUDED.delivery, state = EXCLUDED.state,
  tokens_used = EXCLUDED.tokens_used,
  estimated_cost_usd = EXCLUDED.estimated_cost_usd,
  error_message = EXCLUDED.error_message,
  completed_at = CASE WHEN EXCLUDED.completed_at IS NULL THEN NULL
    ELSE COALESCE(task_executions.completed_at, EXCLUDED.completed_at) END
"""

_PROJECT_AT_ROOT: LiteralString = """
SELECT COALESCE(
  (SELECT id::text FROM projects WHERE root_path = %(root_path)s), 'unknown')
"""

_UPSERT_TRIAL: LiteralString = """
INSERT INTO task_executions (thread_id, user_intent, status, trials)
VALUES (%(run_id)s, %(placeholder)s, 'running', jsonb_build_array(%(item)s::jsonb))
ON CONFLICT (thread_id) DO UPDATE SET trials = CASE
  WHEN task_executions.trials
       @> jsonb_build_array(jsonb_build_object('id', %(item_id)s::text))
  THEN (SELECT jsonb_agg(CASE WHEN e->>'id' = %(item_id)s::text
                              THEN %(item)s::jsonb ELSE e END ORDER BY i)
        FROM jsonb_array_elements(task_executions.trials) WITH ORDINALITY AS t(e, i))
  ELSE task_executions.trials || jsonb_build_array(%(item)s::jsonb)
END
"""

_UPSERT_VERDICT: LiteralString = """
INSERT INTO task_executions (thread_id, user_intent, status, verdicts)
VALUES (%(run_id)s, %(placeholder)s, 'running', jsonb_build_array(%(item)s::jsonb))
ON CONFLICT (thread_id) DO UPDATE SET verdicts = CASE
  WHEN task_executions.verdicts
       @> jsonb_build_array(jsonb_build_object('id', %(item_id)s::text))
  THEN (SELECT jsonb_agg(CASE WHEN e->>'id' = %(item_id)s::text
                              THEN %(item)s::jsonb ELSE e END ORDER BY i)
        FROM jsonb_array_elements(task_executions.verdicts) WITH ORDINALITY AS t(e, i))
  ELSE task_executions.verdicts || jsonb_build_array(%(item)s::jsonb)
END
"""

_GET_RUN: LiteralString = (
    "SELECT state FROM task_executions"
    " WHERE thread_id = %(run_id)s AND state IS NOT NULL"
)
_LIST_TRIALS: LiteralString = (
    "SELECT trials FROM task_executions WHERE thread_id = %(run_id)s"
)
_LIST_VERDICTS: LiteralString = (
    "SELECT verdicts FROM task_executions WHERE thread_id = %(run_id)s"
)

_UPSERT_LESSON: LiteralString = """
INSERT INTO lessons (id, project_id, verdict_id, hypothesis_id, technique_id,
                     context, outcome, gain, text, weight, created_at)
VALUES (%(id)s, %(project_id)s, %(verdict_id)s, %(hypothesis_id)s,
        %(technique_id)s, %(context)s, %(outcome)s, %(gain)s, %(text)s,
        %(weight)s, %(created_at)s)
ON CONFLICT (id) DO UPDATE SET
  project_id = EXCLUDED.project_id, verdict_id = EXCLUDED.verdict_id,
  hypothesis_id = EXCLUDED.hypothesis_id, technique_id = EXCLUDED.technique_id,
  context = EXCLUDED.context, outcome = EXCLUDED.outcome, gain = EXCLUDED.gain,
  text = EXCLUDED.text, weight = EXCLUDED.weight, created_at = EXCLUDED.created_at
"""

_LIST_LESSONS: LiteralString = """
SELECT id::text AS id, project_id::text AS project_id,
       verdict_id::text AS verdict_id, hypothesis_id::text AS hypothesis_id,
       technique_id::text AS technique_id, context, outcome, gain, text, weight,
       created_at
FROM lessons
WHERE %(every)s OR project_id IS NULL OR project_id = %(project_id)s
ORDER BY seq
"""


# ---------------------------------------------------------------------------
# Id checks (before any connection)
# ---------------------------------------------------------------------------


def _uuid(field: str, value: str) -> uuid.UUID:
    """``value`` as a UUID, or ``InvalidRecordIdError`` naming ``field``.

    Only the canonical form (lowercase, hyphenated: what ``new_id`` makes) is
    accepted, so the id Postgres returns equals the one that was saved.
    """
    try:
        parsed: uuid.UUID | None = uuid.UUID(value)
    except ValueError:
        parsed = None
    if parsed is None or str(parsed) != value:
        raise InvalidRecordIdError(
            f"{field} {value!r} is not a UUID (lowercase, hyphenated); "
            "it is bound for a UUID column"
        )
    return parsed


def _optional_uuid(field: str, value: str | None) -> uuid.UUID | None:
    return None if value is None else _uuid(field, value)


def _run_key(run_id: str) -> str:
    """``run_id`` for the ``thread_id`` column, or ``InvalidRecordIdError``."""
    try:
        return validate_run_id(run_id)
    except ValueError as exc:
        raise InvalidRecordIdError(
            f"run_id {run_id!r} is not a valid run id: {exc}"
        ) from exc


def _filter_key(project_id: str) -> uuid.UUID | None:
    """The UUID to filter lessons by; ``None`` when no saved row can match."""
    try:
        return _uuid("project_id", project_id)
    except InvalidRecordIdError:
        return None


def _jsonb(value: object) -> Jsonb | None:
    """SQL NULL for ``None``, else a JSONB parameter (never JSON ``null``)."""
    return None if value is None else Jsonb(value)


def _store_text(text: str) -> str:
    """``text`` with U+0000 as ESC "0" and ESC as ESC ESC (ESC: ``STORAGE_ESCAPE``)."""
    if "\x00" not in text and STORAGE_ESCAPE not in text:
        return text
    doubled = text.replace(STORAGE_ESCAPE, STORAGE_ESCAPE * 2)
    return doubled.replace("\x00", STORAGE_ESCAPE + "0")


def _load_text(text: str) -> str:
    """The text ``_store_text`` was given."""
    if STORAGE_ESCAPE not in text:
        return text
    return _ESCAPED.sub(lambda m: "\x00" if m[1] == "0" else STORAGE_ESCAPE, text)


def _each_text(value: Any, convert: Callable[[str], str]) -> Any:
    """JSON ``value`` with ``convert`` applied to every string and object key."""
    if isinstance(value, str):
        return convert(value)
    if isinstance(value, list):
        return [_each_text(item, convert) for item in value]
    if isinstance(value, dict):
        return {convert(key): _each_text(item, convert) for key, item in value.items()}
    return value


def _user_intent(state: EngineState) -> str:
    goals = [text for o in state["objectives"] if (text := o.description.strip())]
    return "; ".join(goals) if goals else f"improve {state['project'].name}"


# ---------------------------------------------------------------------------
# The repository
# ---------------------------------------------------------------------------


class PostgresRepository:
    """``Repository`` on PostgreSQL 16 through psycopg 3, schema 001-004.

    ``dsn`` is a libpq connection string or URL; it is kept private and never
    put into an error message. ``connect_timeout`` bounds each connection
    attempt in seconds.
    """

    def __init__(self, dsn: str, *, connect_timeout: int = 10) -> None:
        self._dsn = dsn
        self._connect_timeout = connect_timeout

    def _connect(self) -> psycopg.Connection[tuple[Any, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout)

    # runs ------------------------------------------------------------------

    def save_run(self, state: EngineState) -> None:
        """Upsert the run's project and run row in one transaction.

        Raises ``InvalidRecordIdError`` (before connecting) for a bad id and
        ``ProjectConflictError`` when the project's root is registered under
        another project id; nothing is written in either case.
        """
        run_id = _run_key(state["run_id"])
        project = state["project"]
        project_key = _uuid("project.id", project.id)
        objective_keys = [
            _uuid(f"objectives[{i}].id", o.id)
            for i, o in enumerate(state["objectives"])
        ]
        for i, workload in enumerate(state["workloads"]):
            _uuid(f"workloads[{i}].id", workload.id)
        payload = _each_text(dump_state(state), _store_text)
        phase: str = payload["phase"]
        record = payload["project"]
        project_row = {
            "id": project_key,
            "name": record["name"],
            "root_path": record["root_path"],
            "default_branch": record["default_branch"],
            "language": record["language"],
            "hardware": Jsonb(record["hardware"]),
            "test_command": _jsonb(record["test_command"]),
            "created_at": project.created_at,
        }
        run_row = {
            "run_id": run_id,
            "user_intent": _store_text(_user_intent(state)),
            "status": _STATUS.get(phase, "running"),
            "phase": phase,
            "project_id": project_key,
            "objective_ids": objective_keys,
            "baseline": _jsonb(payload["baseline"]),
            "delivery": _jsonb(payload["delivery"]),
            "state": Jsonb(payload),
            "tokens_used": payload["tokens_used"],
            "cost_usd": payload["cost_usd"],
            "error": payload["error"],
            "ended": phase in ("done", "failed"),
        }
        with self._connect() as conn:
            try:
                with conn.transaction():
                    conn.execute(_UPSERT_PROJECT, project_row)
                    conn.execute(_UPSERT_RUN, run_row)
            except UniqueViolation as exc:
                if exc.diag.constraint_name != ROOT_PATH_CONSTRAINT:
                    raise
                at_root = {"root_path": record["root_path"]}
                found = conn.execute(_PROJECT_AT_ROOT, at_root)
                (registered,) = cast(tuple[str], found.fetchone())
                raise ProjectConflictError(
                    f"root {project.root_path} is already registered as project "
                    f"{registered}; this run's project id is {project.id}"
                ) from exc

    def get_run(self, run_id: str) -> EngineState | None:
        """The run's typed state, or ``None`` when no state was saved for it."""
        with self._connect() as conn:
            row = conn.execute(_GET_RUN, {"run_id": run_id}).fetchone()
        return None if row is None else load_state(_each_text(row[0], _load_text))

    # trials and verdicts ---------------------------------------------------

    def _upsert_item(
        self, sql: LiteralString, run_id: str, item_id: str, item: Mapping[str, Any]
    ) -> None:
        params = {
            "run_id": run_id,
            "placeholder": PLACEHOLDER_INTENT,
            "item": Jsonb(_each_text(item, _store_text)),
            "item_id": item_id,
        }
        with self._connect() as conn:
            conn.execute(sql, params)

    def save_trial(self, run_id: str, trial: Trial) -> None:
        """Store ``trial`` in the run's trials array, replacing one with its id."""
        key = _run_key(run_id)
        _uuid("trial.id", trial.id)
        _uuid("trial.hypothesis_id", trial.hypothesis_id)
        self._upsert_item(_UPSERT_TRIAL, key, trial.id, trial.model_dump(mode="json"))

    def save_verdict(self, run_id: str, verdict: Verdict) -> None:
        """Store ``verdict`` in the run's verdicts array, replacing one with its id."""
        key = _run_key(run_id)
        _uuid("verdict.id", verdict.id)
        _uuid("verdict.trial_id", verdict.trial_id)
        _uuid("verdict.hypothesis_id", verdict.hypothesis_id)
        item = verdict.model_dump(mode="json")
        self._upsert_item(_UPSERT_VERDICT, key, verdict.id, item)

    def list_trials(self, run_id: str) -> tuple[Trial, ...]:
        """The run's trials in insertion order; empty for an unknown run."""
        with self._connect() as conn:
            row = conn.execute(_LIST_TRIALS, {"run_id": run_id}).fetchone()
        return (
            ()
            if row is None
            else _TRIALS.validate_python(_each_text(row[0], _load_text))
        )

    def list_verdicts(self, run_id: str) -> tuple[Verdict, ...]:
        """The run's verdicts in insertion order; empty for an unknown run."""
        with self._connect() as conn:
            row = conn.execute(_LIST_VERDICTS, {"run_id": run_id}).fetchone()
        return (
            ()
            if row is None
            else _VERDICTS.validate_python(_each_text(row[0], _load_text))
        )

    # lessons ---------------------------------------------------------------

    def save_lesson(self, lesson: Lesson) -> None:
        """Upsert ``lesson`` by id; a replaced lesson keeps its place in the order."""
        params = {
            "id": _uuid("lesson.id", lesson.id),
            "project_id": _optional_uuid("lesson.project_id", lesson.project_id),
            "verdict_id": _optional_uuid("lesson.verdict_id", lesson.verdict_id),
            "hypothesis_id": _optional_uuid(
                "lesson.hypothesis_id", lesson.hypothesis_id
            ),
            "technique_id": _optional_uuid("lesson.technique_id", lesson.technique_id),
            "context": [_store_text(tag) for tag in lesson.context],
            "outcome": lesson.outcome.value,
            "gain": lesson.gain,
            "text": _store_text(lesson.text),
            "weight": lesson.weight,
            "created_at": lesson.created_at,
        }
        with self._connect() as conn:
            conn.execute(_UPSERT_LESSON, params)

    def list_lessons(self, project_id: str | None = None) -> tuple[Lesson, ...]:
        """All lessons, or the project's plus the global ones, in insertion order."""
        params = {
            "every": project_id is None,
            "project_id": None if project_id is None else _filter_key(project_id),
        }
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(_LIST_LESSONS, params).fetchall()
        return tuple(Lesson.model_validate(_each_text(row, _load_text)) for row in rows)
