"""PostgresRepository on a real PostgreSQL 16 with pgvector (Step 2, unit U8).

``test_repository.py`` holds the contract every backend shares. These tests
cover what only the database adds:

- ids bound for UUID columns (and run ids) are checked before any SQL: a
  repository whose DSN cannot even connect still raises
  ``InvalidRecordIdError``, so those tests need no database;
- caller ids (hypothesis ids such as ``h1``, playbook slugs as technique ids)
  follow the engine's id rule instead (Step 3, U1): they round-trip through
  trials, verdicts and lessons, and what the rule refuses is refused before
  SQL and, on a direct insert, by migration 005;
- a second project at a registered root raises ``ProjectConflictError``;
- the ``save_run`` column mapping, the lesson columns and their order;
- concurrent trial saves into one run lose nothing;
- text holding U+0000 (which JSONB and TEXT refuse) or the storage escape
  round-trips through every kind of column, also inside an engine run;
- a full gated engine run is recorded identically in both backends;
- migration 004: what it adds, its CHECK; migration 005: the lesson id
  columns, their CHECKs, a legacy UUID row; re-applying 003 onward.

Tests that need the database carry the ``postgres`` marker and are skipped
when ``TEST_DATABASE_URL`` is unset (see ``conftest.py``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any, LiteralString

import psycopg
import pytest
from psycopg import errors as pg_errors

from autonomous_ai_agents.common.errors import (
    EngineError,
    InvalidRecordIdError,
    ProjectConflictError,
)
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    ApprovalDecision,
    Baseline,
    ChangeClass,
    Delivery,
    DeliveryKind,
    Direction,
    EngineEvent,
    Guardrail,
    Hypothesis,
    Lesson,
    Objective,
    ObjectiveKind,
    Project,
    RunPhase,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Workload,
    new_id,
)
from autonomous_ai_agents.execution.runner import ScriptedOutcome
from autonomous_ai_agents.orchestrator.main import Orchestrator
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.orchestrator.serde import dump_state
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state
from autonomous_ai_agents.persistence.postgres import PostgresRepository
from autonomous_ai_agents.persistence.repository import InMemoryRepository, Repository

# ---------------------------------------------------------------------------
# Builders and helpers
# ---------------------------------------------------------------------------


def _state(
    run_id: str = "run-1",
    *,
    root: str = "/srv/bridge",
    project: Project | None = None,
    descriptions: Sequence[str] = ("minimize seconds per step",),
) -> EngineState:
    owner = project if project is not None else Project(name="bridge", root_path=root)
    workload = Workload(project_id=owner.id, name="train", command=("python", "t.py"))
    objectives = [
        Objective(
            project_id=owner.id,
            kind=ObjectiveKind.runtime,
            metric=METRIC_WALL_TIME_S,
            direction=Direction.minimize,
            description=text,
        )
        for text in descriptions
    ]
    return initial_state(owner, [workload], objectives, [], run_id=run_id)


def _trial(**fields: Any) -> Trial:
    values: dict[str, Any] = {
        "hypothesis_id": new_id(),
        "round": 1,
        "status": TrialStatus.measured,
    }
    return Trial(**{**values, **fields})


def _verdict(trial: Trial, **fields: Any) -> Verdict:
    values: dict[str, Any] = {
        "trial_id": trial.id,
        "hypothesis_id": trial.hypothesis_id,
        "outcome": VerdictOutcome.keep,
        "change_class": ChangeClass.efficiency,
        "summary": "keep: scripted",
    }
    return Verdict(**{**values, **fields})


def _lesson(**fields: Any) -> Lesson:
    values: dict[str, Any] = {"outcome": VerdictOutcome.keep, "text": "cache it"}
    return Lesson(**{**values, **fields})


def _rows(
    dsn: str, query: LiteralString, params: Mapping[str, Any] | None = None
) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn:
        return conn.execute(query, params).fetchall()


def _count_engine_rows(dsn: str) -> tuple[int, int, int]:
    (row,) = _rows(
        dsn,
        "SELECT (SELECT count(*) FROM projects), (SELECT count(*) FROM task_executions),"
        " (SELECT count(*) FROM lessons)",
    )
    return (row[0], row[1], row[2])


@pytest.fixture
def offline_repository(tmp_path: Path) -> PostgresRepository:
    """A repository whose DSN names a socket directory with no server in it."""
    return PostgresRepository(f"host={tmp_path} dbname=none user=none")


# ---------------------------------------------------------------------------
# Ids are checked before any SQL
# ---------------------------------------------------------------------------

UPPER_UUID = "0F8FAD5B-D9CB-469F-A165-70867728950E"
"""A valid uuid in a non-canonical (uppercase) form; fixed so xdist ids agree."""

CALLER_IDS = ("h1", "set-membership", "a" * 64, UPPER_UUID)
"""Caller ids the engine's id rule accepts (``validate_run_id``): a caller
hypothesis id, a playbook slug, the longest id, and a non-canonical uuid."""

BAD_CALLER_IDS = (
    "../x",
    "a..b",
    "Set Membership",
    "a" * 65,
    "x.lock",
    "x.",
    "",
    "h1\n",
)
"""Caller ids the rule refuses: traversal, ``..``, a space, 65 characters, a
git lock suffix, a trailing dot, the empty string and a trailing newline."""


def _run_with_project_id(repo: Repository) -> None:
    repo.save_run(_state(project=Project(id="project-a", name="b", root_path="/s")))


def _run_with_objective_id(repo: Repository) -> None:
    state = _state()
    state["objectives"] = [state["objectives"][0].model_copy(update={"id": "obj-1"})]
    repo.save_run(state)


def _run_with_workload_id(repo: Repository) -> None:
    state = _state()
    state["workloads"] = [state["workloads"][0].model_copy(update={"id": "train"})]
    repo.save_run(state)


def _run_with_bad_run_id(repo: Repository) -> None:
    state = _state()
    state["run_id"] = "../x"
    repo.save_run(state)


INVALID_ID_CASES: list[tuple[str, str, Callable[[Repository], None]]] = [
    ("lesson.id", "l1", lambda r: r.save_lesson(_lesson(id="l1"))),
    (
        "lesson.project_id",
        "project-a",
        lambda r: r.save_lesson(_lesson(project_id="project-a")),
    ),
    ("lesson.verdict_id", "v1", lambda r: r.save_lesson(_lesson(verdict_id="v1"))),
    ("project.id", "project-a", _run_with_project_id),
    ("objectives[0].id", "obj-1", _run_with_objective_id),
    ("workloads[0].id", "train", _run_with_workload_id),
    ("run_id", "../x", _run_with_bad_run_id),
    ("trial.id", "t1", lambda r: r.save_trial("run-1", _trial(id="t1"))),
    ("run_id", "a b", lambda r: r.save_trial("a b", _trial())),
    (
        "verdict.id",
        "v1",
        lambda r: r.save_verdict("run-1", _verdict(_trial(), id="v1")),
    ),
    (
        "verdict.trial_id",
        "t1",
        lambda r: r.save_verdict("run-1", _verdict(_trial(), trial_id="t1")),
    ),
    ("run_id", "r" * 65, lambda r: r.save_verdict("r" * 65, _verdict(_trial()))),
    *[
        case
        for value in BAD_CALLER_IDS
        for case in (
            (
                "trial.hypothesis_id",
                value,
                lambda r, v=value: r.save_trial("run-1", _trial(hypothesis_id=v)),
            ),
            (
                "verdict.hypothesis_id",
                value,
                lambda r, v=value: r.save_verdict(
                    "run-1", _verdict(_trial(), hypothesis_id=v)
                ),
            ),
            (
                "lesson.hypothesis_id",
                value,
                lambda r, v=value: r.save_lesson(_lesson(hypothesis_id=v)),
            ),
            (
                "lesson.technique_id",
                value,
                lambda r, v=value: r.save_lesson(_lesson(technique_id=v)),
            ),
        )
    ],
]


def test_the_offline_repository_really_cannot_connect(
    offline_repository: PostgresRepository,
) -> None:
    """
    GIVEN a repository whose DSN names an empty socket directory
    WHEN a valid call is made
    THEN psycopg fails to connect (so the id tests below prove "before SQL")
    """
    with pytest.raises(psycopg.OperationalError):
        offline_repository.list_lessons()


@pytest.mark.parametrize(
    ("field", "value", "call"),
    INVALID_ID_CASES,
    ids=[
        f"{i}:{field}={value[:12]}"
        for i, (field, value, _) in enumerate(INVALID_ID_CASES)
    ],
)
def test_an_invalid_id_raises_before_any_connection(
    offline_repository: PostgresRepository,
    field: str,
    value: str,
    call: Callable[[Repository], None],
) -> None:
    """
    GIVEN an id bound for a UUID column that is not a canonical uuid (or a
          run id that could not name a thread)
    WHEN it is saved through a repository that cannot connect
    THEN InvalidRecordIdError, an EngineError, names the field and the value
    """
    with pytest.raises(InvalidRecordIdError, match=re.escape(f"{field} {value!r}")):
        call(offline_repository)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "call",
    [
        lambda r: r.save_lesson(_lesson(hypothesis_id="../x")),
        lambda r: r.save_lesson(_lesson(technique_id="Set Membership")),
        _run_with_project_id,
        lambda r: r.save_trial("a b", _trial()),
        lambda r: r.save_trial("run-1", _trial(hypothesis_id="a..b")),
        lambda r: r.save_verdict("run-1", _verdict(_trial(), hypothesis_id="x.")),
    ],
    ids=[
        "lesson-hypothesis-traversal",
        "lesson-technique-space",
        "run-project-id",
        "trial-run-id",
        "trial-hypothesis-dots",
        "verdict-hypothesis-trailing-dot",
    ],
)
def test_an_invalid_id_writes_no_row(
    postgres_repository: PostgresRepository,
    postgres_dsn: str,
    call: Callable[[Repository], None],
) -> None:
    """
    GIVEN a reachable database
    WHEN a record with an invalid id is saved
    THEN InvalidRecordIdError is raised and no row is written
    """
    with pytest.raises(InvalidRecordIdError):
        call(postgres_repository)

    assert _count_engine_rows(postgres_dsn) == (0, 0, 0)


@pytest.mark.postgres
def test_reads_with_ids_no_write_accepts_find_nothing(
    postgres_repository: PostgresRepository,
) -> None:
    """
    GIVEN an empty database
    WHEN runs, trials, verdicts and lessons are read with odd ids
    THEN nothing is found and nothing raises
    """
    assert postgres_repository.get_run("x" * 300) is None
    assert postgres_repository.list_trials("../x") == ()
    assert postgres_repository.list_verdicts("a b") == ()
    assert postgres_repository.list_lessons(UPPER_UUID) == ()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_a_second_project_at_a_registered_root_raises_project_conflict(
    postgres_repository: PostgresRepository, postgres_dsn: str
) -> None:
    """
    GIVEN a run saved for project A at /srv/bridge
    WHEN a run for a new project id at the same root is saved
    THEN ProjectConflictError names the root and A's id, and nothing of the
         second run is written
    """
    first = _state("run-a")
    postgres_repository.save_run(first)
    second = _state("run-b")

    with pytest.raises(ProjectConflictError) as caught:
        postgres_repository.save_run(second)

    message = str(caught.value)
    registered = first["project"].id
    assert f"root /srv/bridge is already registered as project {registered}" in message
    assert second["project"].id in message
    assert isinstance(caught.value, EngineError)
    assert postgres_repository.get_run("run-b") is None
    assert _rows(postgres_dsn, "SELECT id::text, root_path FROM projects") == [
        (registered, "/srv/bridge")
    ]
    assert _rows(postgres_dsn, "SELECT thread_id FROM task_executions") == [("run-a",)]


@pytest.mark.postgres
@pytest.mark.parametrize("spelling", ["slash", "symlink"])
def test_another_spelling_of_a_registered_root_raises_project_conflict(
    postgres_repository: PostgresRepository,
    postgres_dsn: str,
    tmp_path: Path,
    spelling: str,
) -> None:
    """
    GIVEN a run saved for project A at a repository root
    WHEN a run for a new project id at the same root, spelled with a
         trailing slash or through a symlink, is saved
    THEN ProjectConflictError names A's id, and one project row remains
    """
    repo = tmp_path.resolve() / "repo"
    repo.mkdir()
    (tmp_path / "alias").symlink_to(repo)
    first = _state("run-a", root=str(repo))
    postgres_repository.save_run(first)
    other = f"{repo}/" if spelling == "slash" else str(tmp_path / "alias")

    with pytest.raises(ProjectConflictError, match=first["project"].id):
        postgres_repository.save_run(_state("run-b", root=other))

    assert _rows(postgres_dsn, "SELECT root_path FROM projects") == [(str(repo),)]


@pytest.mark.postgres
def test_moving_a_project_onto_another_projects_root_raises_project_conflict(
    postgres_repository: PostgresRepository, postgres_dsn: str
) -> None:
    """
    GIVEN projects A at /srv/a and B at /srv/b
    WHEN A is saved again with root /srv/b
    THEN ProjectConflictError names B, and A's run and row are as before
    """
    a, b = _state("run-a", root="/srv/a"), _state("run-b", root="/srv/b")
    postgres_repository.save_run(a)
    postgres_repository.save_run(b)
    moved = a.copy()
    moved["project"] = a["project"].model_copy(update={"root_path": "/srv/b"})
    moved["round"] = 2

    with pytest.raises(ProjectConflictError, match=b["project"].id):
        postgres_repository.save_run(moved)

    assert postgres_repository.get_run("run-a") == a
    assert sorted(
        _rows(postgres_dsn, "SELECT id::text, root_path FROM projects")
    ) == sorted([(a["project"].id, "/srv/a"), (b["project"].id, "/srv/b")])


@pytest.mark.postgres
def test_the_same_project_id_at_a_new_root_updates_its_row(
    postgres_repository: PostgresRepository, postgres_dsn: str
) -> None:
    """
    GIVEN a run saved for project A at /srv/old
    WHEN A is saved again with a new root, name and test command
    THEN A's single row is updated in place
    """
    first = _state(root="/srv/old")
    postgres_repository.save_run(first)
    moved = first.copy()
    moved["project"] = first["project"].model_copy(
        update={
            "root_path": "/srv/new",
            "name": "bridge2",
            "test_command": ("python", "-m", "unittest"),
        }
    )

    postgres_repository.save_run(moved)

    assert _rows(
        postgres_dsn, "SELECT id::text, name, root_path, test_command FROM projects"
    ) == [(first["project"].id, "bridge2", "/srv/new", ["python", "-m", "unittest"])]
    assert postgres_repository.get_run("run-1") == moved


@pytest.mark.postgres
def test_save_run_stores_every_project_column(
    postgres_repository: PostgresRepository, postgres_dsn: str
) -> None:
    """
    GIVEN a project with every field set, and one without a test command
    WHEN their runs are saved
    THEN the columns hold the values, test_command as a JSONB array or NULL
    """
    project = Project(
        name="bridge",
        root_path="/srv/bridge",
        default_branch="trunk",
        language="python",
        hardware={"cpus": 8, "arch": "arm64", "gpu": None},
        test_command=("python", "-m", "unittest", "discover"),
    )
    bare = Project(name="bare", root_path="/srv/bare")
    postgres_repository.save_run(_state("run-1", project=project))
    postgres_repository.save_run(_state("run-2", project=bare))

    rows = _rows(
        postgres_dsn,
        "SELECT name, root_path, default_branch, language, hardware, test_command,"
        " test_command IS NULL, created_at FROM projects ORDER BY name DESC",
    )

    assert rows == [
        (
            "bridge",
            "/srv/bridge",
            "trunk",
            "python",
            {"cpus": 8, "arch": "arm64", "gpu": None},
            ["python", "-m", "unittest", "discover"],
            False,
            project.created_at,
        ),
        ("bare", "/srv/bare", "main", "python", {}, None, True, bare.created_at),
    ]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("phase", "status", "ended"),
    [
        (RunPhase.connect, "pending", False),
        (RunPhase.trials, "running", False),
        (RunPhase.approval, "running", False),
        (RunPhase.done, "success", True),
        (RunPhase.failed, "failed", True),
    ],
)
def test_save_run_maps_the_run_columns(
    postgres_repository: PostgresRepository,
    postgres_dsn: str,
    phase: RunPhase,
    status: str,
    ended: bool,
) -> None:
    """
    GIVEN a state in a given phase, with tokens, cost and an error
    WHEN it is saved
    THEN thread, intent, status, phase, project, objectives, counters, error,
         completion time and the full state land in their columns
    """
    state = _state()
    state["phase"] = phase
    state["tokens_used"] = 3400
    state["cost_usd"] = 0.5
    state["error"] = "boom" if phase is RunPhase.failed else None

    postgres_repository.save_run(state)

    (row,) = _rows(
        postgres_dsn,
        "SELECT thread_id, user_intent, status, phase, project_id::text,"
        " objective_ids::text[], tokens_used, estimated_cost_usd, error_message,"
        " completed_at IS NOT NULL, baseline, delivery, state, trials, verdicts"
        " FROM task_executions",
    )
    assert row == (
        "run-1",
        "minimize seconds per step",
        status,
        phase.value,
        state["project"].id,
        [state["objectives"][0].id],
        3400,
        Decimal("0.5000"),
        state["error"],
        ended,
        None,
        None,
        dump_state(state),
        [],
        [],
    )


@pytest.mark.postgres
def test_save_run_copies_the_baseline_and_delivery_into_their_columns(
    postgres_repository: PostgresRepository, postgres_dsn: str
) -> None:
    """
    GIVEN a state with a baseline and a delivery
    WHEN it is saved
    THEN the baseline and delivery columns hold their JSON
    """
    state = _state()
    state["baseline"] = Baseline(commit="0" * 40, objectives=tuple(state["objectives"]))
    state["delivery"] = Delivery(
        project_id=state["project"].id,
        kind=DeliveryKind.report_only,
        report_markdown="# nothing kept",
    )

    postgres_repository.save_run(state)

    dumped = dump_state(state)
    assert _rows(postgres_dsn, "SELECT baseline, delivery FROM task_executions") == [
        (dumped["baseline"], dumped["delivery"])
    ]


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("descriptions", "intent"),
    [
        ((), "improve bridge"),
        (("  ",), "improve bridge"),
        (("minimize seconds", " lower memory "), "minimize seconds; lower memory"),
    ],
)
def test_user_intent_comes_from_the_objectives_or_the_project_name(
    postgres_repository: PostgresRepository,
    postgres_dsn: str,
    descriptions: tuple[str, ...],
    intent: str,
) -> None:
    """
    GIVEN objectives with or without descriptions
    WHEN the run is saved
    THEN user_intent (NOT NULL) joins the descriptions or says "improve <name>"
    """
    postgres_repository.save_run(_state(descriptions=descriptions))

    assert _rows(postgres_dsn, "SELECT user_intent FROM task_executions") == [(intent,)]


@pytest.mark.postgres
def test_completed_at_is_set_once_when_the_run_ends(
    postgres_repository: PostgresRepository, postgres_dsn: str
) -> None:
    """
    GIVEN a run that is saved while running, then done, then done again
    WHEN completed_at is read after each save
    THEN it is NULL while running and keeps the first completion time
    """
    state = _state()
    state["phase"] = RunPhase.trials
    postgres_repository.save_run(state)
    running = _rows(postgres_dsn, "SELECT completed_at FROM task_executions")
    state["phase"] = RunPhase.done
    postgres_repository.save_run(state)
    first = _rows(postgres_dsn, "SELECT completed_at FROM task_executions")
    postgres_repository.save_run(state)
    again = _rows(postgres_dsn, "SELECT completed_at FROM task_executions")

    assert running == [(None,)]
    assert first[0][0] is not None
    assert again == first


@pytest.mark.postgres
def test_save_run_never_touches_the_trials_and_verdicts_columns(
    postgres_repository: PostgresRepository, postgres_dsn: str
) -> None:
    """
    GIVEN a trial and a verdict saved before their run (a placeholder row)
    WHEN the run is then saved
    THEN get_run sees no state before and the full state after, and the
         trial and verdict survive the run save
    """
    trial = _trial()
    verdict = _verdict(trial)
    postgres_repository.save_trial("run-1", trial)
    postgres_repository.save_verdict("run-1", verdict)
    assert postgres_repository.get_run("run-1") is None
    state = _state()

    postgres_repository.save_run(state)

    assert postgres_repository.get_run("run-1") == state
    assert postgres_repository.list_trials("run-1") == (trial,)
    assert postgres_repository.list_verdicts("run-1") == (verdict,)
    assert _rows(postgres_dsn, "SELECT user_intent, status FROM task_executions") == [
        ("minimize seconds per step", "pending")
    ]


@pytest.mark.postgres
def test_trials_saved_concurrently_into_one_run_are_all_kept(
    postgres_repository: PostgresRepository,
) -> None:
    """
    GIVEN four threads each saving five trials into the same new run
    WHEN they run at the same time
    THEN every trial is stored once, each thread's in its own order
    """
    batches = [[_trial() for _ in range(5)] for _ in range(4)]

    def save(batch: list[Trial]) -> None:
        for trial in batch:
            postgres_repository.save_trial("run-1", trial)

    with ThreadPoolExecutor(max_workers=len(batches)) as pool:
        for future in [pool.submit(save, batch) for batch in batches]:
            future.result()

    saved = [trial.id for trial in postgres_repository.list_trials("run-1")]
    assert sorted(saved) == sorted(t.id for batch in batches for t in batch)
    for batch in batches:
        positions = [saved.index(trial.id) for trial in batch]
        assert positions == sorted(positions)


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_a_lesson_round_trips_through_its_typed_columns(
    postgres_repository: PostgresRepository, postgres_dsn: str
) -> None:
    """
    GIVEN a lesson with every field set and a gain REAL would round
    WHEN it is saved and listed
    THEN it comes back equal, from double precision and text[] columns
    """
    state = _state()
    postgres_repository.save_run(state)
    lesson = _lesson(
        project_id=state["project"].id,
        verdict_id=new_id(),
        hypothesis_id=new_id(),
        technique_id=new_id(),
        context=("frozen_encoder", "repeated_epochs"),
        gain=0.4167,
        weight=1.3,
        text="frozen encoder + repeated epochs -> cache embeddings: keep (+41.7%)",
    )

    postgres_repository.save_lesson(lesson)

    assert postgres_repository.list_lessons(state["project"].id) == (lesson,)
    assert postgres_repository.list_lessons(new_id()) == ()
    assert _rows(
        postgres_dsn,
        "SELECT pg_typeof(gain)::text, pg_typeof(weight)::text, context, outcome,"
        " hypothesis_id::text FROM lessons",
    ) == [
        (
            "double precision",
            "double precision",
            ["frozen_encoder", "repeated_epochs"],
            "keep",
            lesson.hypothesis_id,
        )
    ]


@pytest.mark.postgres
def test_a_replaced_lesson_keeps_its_place_in_the_order(
    postgres_repository: PostgresRepository,
) -> None:
    """
    GIVEN lessons A and B saved in that order
    WHEN a reweighted copy of A is saved
    THEN the listing is (A', B)
    """
    first, second = _lesson(text="first"), _lesson(text="second")
    postgres_repository.save_lesson(first)
    postgres_repository.save_lesson(second)
    reweighted = first.model_copy(update={"weight": 2.0, "gain": None})

    postgres_repository.save_lesson(reweighted)

    assert postgres_repository.list_lessons() == (reweighted, second)


# ---------------------------------------------------------------------------
# Caller ids: hypothesis ids and technique slugs (Step 3, U1)
# ---------------------------------------------------------------------------


@pytest.mark.postgres
@pytest.mark.parametrize("value", CALLER_IDS, ids=["h1", "slug", "64", "upper-uuid"])
def test_caller_ids_round_trip_through_trials_verdicts_and_lessons(
    postgres_repository: PostgresRepository, postgres_dsn: str, value: str
) -> None:
    """
    GIVEN a caller id the engine's id rule accepts (``h1``, a playbook slug,
          64 characters, an uppercase uuid)
    WHEN a trial and a verdict for it, and a lesson naming it as hypothesis
         and technique, are saved
    THEN each is listed back equal, and the lesson columns hold the text
    """
    state = _state()
    postgres_repository.save_run(state)
    trial = _trial(hypothesis_id=value)
    verdict = _verdict(trial)
    lesson = _lesson(
        project_id=state["project"].id, hypothesis_id=value, technique_id=value
    )

    postgres_repository.save_trial("run-1", trial)
    postgres_repository.save_verdict("run-1", verdict)
    postgres_repository.save_lesson(lesson)

    assert postgres_repository.list_trials("run-1") == (trial,)
    assert postgres_repository.list_verdicts("run-1") == (verdict,)
    assert postgres_repository.list_lessons(state["project"].id) == (lesson,)
    assert _rows(
        postgres_dsn,
        "SELECT hypothesis_id, technique_id, pg_typeof(hypothesis_id)::text"
        " FROM lessons",
    ) == [(value, value, "character varying")]


@pytest.mark.postgres
def test_a_run_with_a_caller_id_and_a_slug_records_its_lesson(
    make_context: Callable[..., NodeContext],
    postgres_repository: PostgresRepository,
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    h1_cache: Hypothesis,
) -> None:
    """
    GIVEN a caller hypothesis with id ``h1`` and the playbook slug
          ``set-membership`` as its technique, on memory and Postgres
    WHEN the run is executed (it spends on its trial before learning)
    THEN it ends done, and Postgres records the trial, the verdict and the
         lesson naming ``h1`` and the slug exactly as memory does
    """
    caller = h1_cache.model_copy(update={"id": "h1", "technique_id": "set-membership"})
    memory = InMemoryRepository()
    ctx = make_context([caller], repository=_Tee(memory, postgres_repository))

    result = Orchestrator(context=ctx).run(
        sample_project, [sample_workload], [sample_objective], sample_guardrails
    )

    assert result.status == "done"
    assert result.state["cost_usd"] > 0
    run_id = result.run_id
    assert postgres_repository.get_run(run_id) == result.state
    (trial,) = postgres_repository.list_trials(run_id)
    assert trial.hypothesis_id == "h1"
    assert postgres_repository.list_trials(run_id) == memory.list_trials(run_id)
    assert postgres_repository.list_verdicts(run_id) == memory.list_verdicts(run_id)
    (lesson,) = postgres_repository.list_lessons(sample_project.id)
    assert (lesson.hypothesis_id, lesson.technique_id) == ("h1", "set-membership")
    assert (lesson,) == memory.list_lessons(sample_project.id)


_INSERT_LESSON_ID: LiteralString = (
    "INSERT INTO lessons (outcome, text, hypothesis_id, technique_id)"
    " VALUES ('keep', 'direct', %(hypothesis_id)s, %(technique_id)s)"
)


@pytest.mark.postgres
@pytest.mark.parametrize("column", ["hypothesis_id", "technique_id"])
@pytest.mark.parametrize(
    "value",
    [v for v in BAD_CALLER_IDS if len(v) <= 64],
    ids=["traversal", "dots", "space", "lock", "trailing-dot", "empty", "newline"],
)
def test_a_direct_insert_of_a_refused_id_fails_the_005_check(
    postgres_dsn: str, column: str, value: str
) -> None:
    """
    GIVEN migration 005's CHECK on a lesson id column
    WHEN a row whose id the engine's rule refuses is inserted directly
    THEN the database refuses it, naming the column's constraint
    """
    row = {"hypothesis_id": None, "technique_id": None, column: value}

    with (
        pytest.raises(pg_errors.CheckViolation, match=f"chk_lesson_{column}"),
        psycopg.connect(postgres_dsn) as conn,
    ):
        conn.execute(_INSERT_LESSON_ID, row)


@pytest.mark.postgres
@pytest.mark.parametrize("column", ["hypothesis_id", "technique_id"])
def test_a_direct_insert_of_65_characters_is_refused(
    postgres_dsn: str, column: str
) -> None:
    """
    GIVEN migration 005's VARCHAR(64) lesson id columns
    WHEN a 65-character id is inserted directly
    THEN the database refuses it (the column width, before the CHECK)
    """
    row = {"hypothesis_id": None, "technique_id": None, column: "a" * 65}

    with (
        pytest.raises(pg_errors.StringDataRightTruncation),
        psycopg.connect(postgres_dsn) as conn,
    ):
        conn.execute(_INSERT_LESSON_ID, row)


@pytest.mark.postgres
@pytest.mark.parametrize("column", ["hypothesis_id", "technique_id"])
def test_the_005_check_itself_bounds_ids_at_64_characters(
    postgres_dsn: str, column: str
) -> None:
    """
    GIVEN a temporary copy of lessons with 005's CHECKs but unbounded TEXT ids
          (so the VARCHAR(64) width cannot refuse a value first)
    WHEN a 64-character id and then a 65-character id are inserted
    THEN the CHECK accepts 64 and refuses 65, naming the column's constraint
    """
    insert: LiteralString = (
        "INSERT INTO lesson_ids (outcome, text, hypothesis_id, technique_id)"
        " VALUES ('keep', 'direct', %(hypothesis_id)s, %(technique_id)s)"
    )
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("CREATE TEMP TABLE lesson_ids (LIKE lessons INCLUDING ALL)")
        conn.execute(
            "ALTER TABLE lesson_ids ALTER COLUMN hypothesis_id TYPE TEXT,"
            " ALTER COLUMN technique_id TYPE TEXT"
        )
        conn.execute(
            insert, {"hypothesis_id": None, "technique_id": None, column: "a" * 64}
        )

        with pytest.raises(pg_errors.CheckViolation, match=f"chk_lesson_{column}"):
            conn.execute(
                insert, {"hypothesis_id": None, "technique_id": None, column: "a" * 65}
            )


@pytest.mark.postgres
def test_a_direct_insert_of_accepted_ids_and_nulls_passes_the_005_check(
    postgres_dsn: str,
) -> None:
    """
    GIVEN migration 005's CHECKs
    WHEN rows with every accepted caller id, and with NULL ids, are inserted
    THEN all are stored (NULL means the lesson names no hypothesis/technique)
    """
    with psycopg.connect(postgres_dsn) as conn:
        for value in (*CALLER_IDS, None):
            conn.execute(
                _INSERT_LESSON_ID, {"hypothesis_id": value, "technique_id": value}
            )

    assert _rows(postgres_dsn, "SELECT hypothesis_id FROM lessons ORDER BY seq") == [
        (value,) for value in (*CALLER_IDS, None)
    ]


# ---------------------------------------------------------------------------
# Text Postgres cannot hold: U+0000 (and the escape that stores it)
# ---------------------------------------------------------------------------

STORAGE_ESCAPE = ""
"""The private-use character the repository escapes U+0000 with."""

AWKWARD_TEXTS = [
    pytest.param("a\x00b", id="nul-inside"),
    pytest.param("\x00", id="nul-only"),
    pytest.param("\x00\x00x\x00", id="nul-runs-at-both-ends"),
    pytest.param(STORAGE_ESCAPE, id="escape-only"),
    pytest.param(STORAGE_ESCAPE + "0", id="escape-then-zero"),
    pytest.param(
        STORAGE_ESCAPE + "\x00" + STORAGE_ESCAPE * 2 + "0", id="escape-and-nul-mixed"
    ),
    pytest.param("x" + STORAGE_ESCAPE, id="escape-at-the-end"),
]
"""Strings a naive store would lose, refuse or decode wrongly."""


def _save_everywhere(
    repositories: Sequence[Repository],
    state: EngineState,
    trial: Trial,
    verdict: Verdict,
    lesson: Lesson,
) -> None:
    for repository in repositories:
        repository.save_run(state)
        repository.save_trial(state["run_id"], trial)
        repository.save_verdict(state["run_id"], verdict)
        repository.save_lesson(lesson)


@pytest.mark.postgres
def test_a_trial_whose_error_holds_a_nul_is_stored_and_listed_back(
    postgres_repository: PostgresRepository,
) -> None:
    """
    GIVEN a failed trial whose error text holds U+0000 (valid UTF-8, which
          JSONB cannot store)
    WHEN it is saved
    THEN it is listed back unchanged, exactly as the in-memory backend does
    """
    trial = _trial(status=TrialStatus.failed, error="a\x00b")
    memory = InMemoryRepository()

    postgres_repository.save_trial("run-1", trial)
    memory.save_trial("run-1", trial)

    assert postgres_repository.list_trials("run-1") == (trial,)
    assert memory.list_trials("run-1") == (trial,)


@pytest.mark.postgres
@pytest.mark.parametrize("text", AWKWARD_TEXTS)
def test_awkward_text_round_trips_through_every_kind_of_column(
    postgres_repository: PostgresRepository, text: str
) -> None:
    """
    GIVEN a run, a trial, a verdict and a lesson whose free text, a JSON key
          and the copied TEXT columns hold NUL or the storage escape
    WHEN they are saved and read back
    THEN every one comes back equal, as from the in-memory backend
    """
    project = Project(name=f"bridge{text}", root_path=f"/srv/bridge{text}")
    state = _state(project=project, descriptions=(f"faster{text}",))
    state["error"] = text
    state["events"] = [
        EngineEvent(
            run_id="run-1", phase=RunPhase.connect, message=text, data={text: text}
        )
    ]
    trial = _trial(status=TrialStatus.failed, error=text, diff=text)
    verdict = _verdict(trial, summary=text)
    lesson = _lesson(project_id=project.id, text=text, context=(text, "plain"))
    memory = InMemoryRepository()

    _save_everywhere((postgres_repository, memory), state, trial, verdict, lesson)

    assert postgres_repository.get_run("run-1") == state == memory.get_run("run-1")
    assert postgres_repository.list_trials("run-1") == (trial,)
    assert postgres_repository.list_verdicts("run-1") == (verdict,)
    assert postgres_repository.list_lessons(project.id) == (lesson,)
    assert memory.list_lessons(project.id) == (lesson,)


@pytest.mark.postgres
def test_stored_text_escapes_nul_and_the_escape_character(
    postgres_repository: PostgresRepository, postgres_dsn: str
) -> None:
    """
    GIVEN text holding U+0000 and the storage escape U+E000
    WHEN it is saved into JSONB and TEXT columns
    THEN the columns hold U+0000 as U+E000 "0" and U+E000 as U+E000 U+E000,
         so no NUL reaches Postgres and the stored form decodes uniquely
    """
    text = f"a\x00b{STORAGE_ESCAPE}c"
    stored = f"a{STORAGE_ESCAPE}0b{STORAGE_ESCAPE * 2}c"
    state = _state(project=Project(name=text, root_path="/srv/bridge"))
    state["error"] = text
    trial = _trial(error=text)

    _save_everywhere(
        (postgres_repository,), state, trial, _verdict(trial), _lesson(text=text)
    )

    assert _rows(
        postgres_dsn,
        "SELECT p.name, t.error_message, t.state->>'error', t.trials->0->>'error',"
        " l.text FROM projects p, task_executions t, lessons l",
    ) == [(stored,) * 5]


@pytest.mark.postgres
def test_a_root_holding_a_nul_still_raises_project_conflict(
    postgres_repository: PostgresRepository,
) -> None:
    """
    GIVEN a run saved for a project whose root path holds U+0000
    WHEN a run for another project id at the same root is saved
    THEN ProjectConflictError names the first project's id
    """
    root = "/srv/odd\x00root"
    first = _state("run-a", root=root)
    postgres_repository.save_run(first)

    with pytest.raises(ProjectConflictError, match=first["project"].id):
        postgres_repository.save_run(_state("run-b", root=root))


# ---------------------------------------------------------------------------
# Other unique violations are not project conflicts
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_other_unique_violations_propagate_unchanged(
    postgres_repository: PostgresRepository, postgres_dsn: str
) -> None:
    """
    GIVEN an extra unique index on projects.name (test only)
    WHEN two projects with the same name at different roots are saved
    THEN psycopg's UniqueViolation propagates as is, not ProjectConflictError
    """
    with psycopg.connect(postgres_dsn, autocommit=True) as conn:
        conn.execute("CREATE UNIQUE INDEX uq_test_project_name ON projects(name)")
    try:
        postgres_repository.save_run(_state("run-a", root="/srv/a"))
        with pytest.raises(pg_errors.UniqueViolation) as caught:
            postgres_repository.save_run(_state("run-b", root="/srv/b"))
    finally:
        with psycopg.connect(postgres_dsn, autocommit=True) as conn:
            conn.execute("DROP INDEX uq_test_project_name")

    assert not isinstance(caught.value, ProjectConflictError)
    assert caught.value.diag.constraint_name == "uq_test_project_name"


# ---------------------------------------------------------------------------
# A full gated engine run, teed into both backends
# ---------------------------------------------------------------------------


class _Tee:
    """A Repository that writes to both backends and reads from the first."""

    def __init__(self, primary: Repository, mirror: Repository) -> None:
        self.primary = primary
        self.mirror = mirror

    def save_run(self, state: EngineState) -> None:
        self.primary.save_run(state)
        self.mirror.save_run(state)

    def get_run(self, run_id: str) -> EngineState | None:
        return self.primary.get_run(run_id)

    def save_trial(self, run_id: str, trial: Trial) -> None:
        self.primary.save_trial(run_id, trial)
        self.mirror.save_trial(run_id, trial)

    def save_verdict(self, run_id: str, verdict: Verdict) -> None:
        self.primary.save_verdict(run_id, verdict)
        self.mirror.save_verdict(run_id, verdict)

    def save_lesson(self, lesson: Lesson) -> None:
        self.primary.save_lesson(lesson)
        self.mirror.save_lesson(lesson)

    def list_lessons(self, project_id: str | None = None) -> tuple[Lesson, ...]:
        return self.primary.list_lessons(project_id)

    def list_trials(self, run_id: str) -> tuple[Trial, ...]:
        return self.primary.list_trials(run_id)

    def list_verdicts(self, run_id: str) -> tuple[Verdict, ...]:
        return self.primary.list_verdicts(run_id)


@pytest.mark.postgres
def test_a_full_gated_run_is_recorded_identically_in_both_backends(
    make_context: Callable[..., NodeContext],
    postgres_repository: PostgresRepository,
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    h1_cache: Hypothesis,
    h2_protected: Hypothesis,
    h3_noise: Hypothesis,
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN the briefing run (H1-H4 in one round) on a repository that writes
          to memory and to Postgres
    WHEN it pauses for H4, H4 is approved and the run finishes
    THEN Postgres returns the final state, the trials, the verdicts and the
         four lessons exactly as the in-memory backend does
    """
    memory = InMemoryRepository()
    ctx = make_context(
        [h1_cache, h2_protected, h3_noise, h4_behaviour],
        max_hypotheses_per_round=4,
        repository=_Tee(memory, postgres_repository),
    )
    orchestrator = Orchestrator(context=ctx)
    paused = orchestrator.run(
        sample_project, [sample_workload], [sample_objective], sample_guardrails
    )
    assert paused.status == "needs_approval"
    assert paused.approval_request is not None
    (item,) = paused.approval_request.items
    assert postgres_repository.get_run(paused.run_id) == paused.state

    final = orchestrator.resume(
        paused.run_id,
        ApprovalDecision(approved_verdict_ids=(item.verdict_id,), approver="praveen"),
    )

    assert final.status == "done"
    run_id = final.run_id
    stored = postgres_repository.get_run(run_id)
    assert stored is not None
    assert stored == final.state == memory.get_run(run_id)
    assert stored["phase"] is RunPhase.done
    trials = postgres_repository.list_trials(run_id)
    assert trials == memory.list_trials(run_id)
    assert len(trials) == 4
    assert postgres_repository.list_verdicts(run_id) == memory.list_verdicts(run_id)
    lessons = postgres_repository.list_lessons(sample_project.id)
    assert lessons == memory.list_lessons(sample_project.id)
    assert len(lessons) == 4


@pytest.mark.postgres
def test_a_run_whose_trial_error_holds_a_nul_finishes_and_is_recorded(
    make_context: Callable[..., NodeContext],
    postgres_repository: PostgresRepository,
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    h1_cache: Hypothesis,
) -> None:
    """
    GIVEN a run whose only trial fails with U+0000 in its error text (as a
          crashed workload's stderr tail can), on memory and Postgres
    WHEN the run is executed
    THEN it ends done (the trial rejected), and Postgres records the final
         state and the trial exactly as the in-memory backend does
    """
    error = "workload crashed: \x00\x00 core dumped"
    memory = InMemoryRepository()
    ctx = make_context(
        [h1_cache],
        scripts={h1_cache.title: ScriptedOutcome(error=error)},
        repository=_Tee(memory, postgres_repository),
    )

    result = Orchestrator(context=ctx).run(
        sample_project, [sample_workload], [sample_objective], sample_guardrails
    )

    assert result.status == "done"
    stored = postgres_repository.get_run(result.run_id)
    assert stored == result.state == memory.get_run(result.run_id)
    (trial,) = postgres_repository.list_trials(result.run_id)
    assert trial.error == error
    assert (trial,) == memory.list_trials(result.run_id)
    assert postgres_repository.list_verdicts(result.run_id) == memory.list_verdicts(
        result.run_id
    )


# ---------------------------------------------------------------------------
# Migration 004, and re-applying 003 onward
# ---------------------------------------------------------------------------

_CATALOG_QUERIES: tuple[LiteralString, ...] = (
    "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)"
    " FROM pg_constraint WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2",
    "SELECT tablename, indexname, indexdef FROM pg_indexes"
    " WHERE schemaname = 'public' ORDER BY 1, 2",
    "SELECT table_name, column_name, data_type, is_nullable, column_default,"
    " is_identity, identity_generation FROM information_schema.columns"
    " WHERE table_schema = 'public' ORDER BY 1, 2",
)


def _catalog(dsn: str) -> list[list[tuple[Any, ...]]]:
    return [_rows(dsn, query) for query in _CATALOG_QUERIES]


@pytest.mark.postgres
def test_migration_004_adds_what_the_repository_needs(postgres_dsn: str) -> None:
    """
    GIVEN the test database built from 001-004
    WHEN the catalog is read
    THEN thread_id has a unique index, lessons.seq is an identity column with
         a unique index, gain and weight are double precision, and projects
         has a guarded test_command JSONB column
    """
    indexes = _rows(
        postgres_dsn,
        "SELECT indexname, indexdef FROM pg_indexes"
        " WHERE indexname IN ('uq_task_thread', 'uq_lessons_seq') ORDER BY 1",
    )
    columns = _rows(
        postgres_dsn,
        "SELECT table_name, column_name, data_type, is_nullable, is_identity,"
        " identity_generation FROM information_schema.columns"
        " WHERE table_schema = 'public' AND (table_name, column_name) IN"
        " (('lessons', 'seq'), ('lessons', 'gain'), ('lessons', 'weight'),"
        " ('projects', 'test_command')) ORDER BY 1, 2",
    )
    checks = _rows(
        postgres_dsn,
        "SELECT conname FROM pg_constraint"
        " WHERE conrelid = 'public.projects'::regclass AND contype = 'c'",
    )

    assert indexes == [
        (
            "uq_lessons_seq",
            "CREATE UNIQUE INDEX uq_lessons_seq ON public.lessons USING btree (seq)",
        ),
        (
            "uq_task_thread",
            "CREATE UNIQUE INDEX uq_task_thread ON public.task_executions"
            " USING btree (thread_id)",
        ),
    ]
    assert columns == [
        ("lessons", "gain", "double precision", "YES", "NO", None),
        ("lessons", "seq", "bigint", "NO", "YES", "ALWAYS"),
        ("lessons", "weight", "double precision", "NO", "NO", None),
        ("projects", "test_command", "jsonb", "YES", "NO", None),
    ]
    assert ("chk_project_test_command_argv",) in checks


@pytest.mark.postgres
@pytest.mark.parametrize(
    "value", ["[]", '"python -m unittest"', '{"argv": []}', "null"]
)
def test_projects_test_command_must_be_a_non_empty_json_array(
    postgres_dsn: str, value: str
) -> None:
    """
    GIVEN the test_command CHECK from migration 004
    WHEN a project row with an empty, string, object or JSON-null command is
         inserted
    THEN the database refuses it (SQL NULL means "no test command")
    """
    with (
        pytest.raises(pg_errors.CheckViolation, match="chk_project_test_command_argv"),
        psycopg.connect(postgres_dsn) as conn,
    ):
        conn.execute(
            "INSERT INTO projects (name, root_path, test_command)"
            " VALUES ('x', '/srv/x', %(value)s::jsonb)",
            {"value": value},
        )


@pytest.mark.postgres
def test_reapplying_003_onward_leaves_the_catalog_unchanged(
    postgres_dsn: str, schema_files: list[Path]
) -> None:
    """
    GIVEN a database built from every migration (as CI's Schema Apply job does)
    WHEN 003 and every later file are applied again, in order
    THEN constraints, indexes and columns are exactly as before
    """
    before = _catalog(postgres_dsn)
    again = [p for p in schema_files if p.name[:4] >= "003_"]
    assert [p.name for p in again][:4] == [
        "003_engine.sql",
        "004_engine_repository.sql",
        "005_lesson_ids.sql",
        "006_review_outcome.sql",
    ]

    with psycopg.connect(postgres_dsn, autocommit=True) as conn:
        for path in again:
            conn.execute(path.read_bytes())

    assert _catalog(postgres_dsn) == before


# ---------------------------------------------------------------------------
# Migration 005
# ---------------------------------------------------------------------------


@pytest.fixture
def legacy_dsn(postgres_database: str, schema_files: list[Path]) -> Iterator[str]:
    """A fresh database built from 001-004 only (the lesson ids still UUID),
    dropped afterwards; skipped with the other Postgres tests."""
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    name = f"{conninfo_to_dict(postgres_database)['dbname']}_legacy"
    drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
        sql.Identifier(name)
    )
    with psycopg.connect(postgres_database, autocommit=True) as admin:
        admin.execute(drop)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(postgres_database, dbname=name)
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            for path in schema_files:
                if path.name[:4] < "005_":
                    conn.execute(path.read_bytes())
        yield dsn
    finally:
        with psycopg.connect(postgres_database, autocommit=True) as admin:
            admin.execute(drop)


def _migration(schema_files: list[Path], prefix: str) -> Path:
    (path,) = [p for p in schema_files if p.name.startswith(prefix)]
    return path


_LESSON_ID_COLUMNS: LiteralString = (
    "SELECT column_name, data_type, character_maximum_length, is_nullable"
    " FROM information_schema.columns WHERE table_schema = 'public'"
    " AND table_name = 'lessons' AND column_name IN ('hypothesis_id', 'technique_id')"
    " ORDER BY 1"
)


@pytest.mark.postgres
def test_migration_005_widens_the_lesson_id_columns(postgres_dsn: str) -> None:
    """
    GIVEN the test database built from every migration
    WHEN the catalog is read
    THEN lessons.hypothesis_id and technique_id are nullable VARCHAR(64), each
         with one CHECK encoding the engine's id rule
    """
    checks = _rows(
        postgres_dsn,
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE conrelid = 'public.lessons'::regclass AND conname IN"
        " ('chk_lesson_hypothesis_id', 'chk_lesson_technique_id') ORDER BY 1",
    )

    assert _rows(postgres_dsn, _LESSON_ID_COLUMNS) == [
        ("hypothesis_id", "character varying", 64, "YES"),
        ("technique_id", "character varying", 64, "YES"),
    ]
    assert [name for name, _ in checks] == [
        "chk_lesson_hypothesis_id",
        "chk_lesson_technique_id",
    ]
    for name, definition in checks:
        column = name.removeprefix("chk_lesson_")
        assert definition.count(column) == 3, definition
        assert "[A-Za-z0-9][A-Za-z0-9._-]{0,63}$" in definition, definition


@pytest.mark.postgres
def test_migration_005_keeps_legacy_uuid_lessons_and_applies_twice(
    legacy_dsn: str, postgres_dsn: str, schema_files: list[Path]
) -> None:
    """
    GIVEN a database at 004 holding lessons with UUID hypothesis and technique
          ids (and one with neither)
    WHEN 005 is applied, then applied again
    THEN the lessons read back with the same ids as text, the second apply
         changes nothing, and with the later migrations applied the catalog
         equals a database built from every file
    """
    hypothesis, technique = new_id(), new_id()
    with psycopg.connect(legacy_dsn) as conn:
        assert conn.execute(_LESSON_ID_COLUMNS).fetchall() == [
            ("hypothesis_id", "uuid", None, "YES"),
            ("technique_id", "uuid", None, "YES"),
        ]
        conn.execute(
            "INSERT INTO lessons (outcome, text, hypothesis_id, technique_id)"
            " VALUES ('keep', 'legacy', %(h)s::uuid, %(t)s::uuid),"
            " ('reject', 'global', NULL, NULL)",
            {"h": hypothesis, "t": technique},
        )
    migration = _migration(schema_files, "005_")

    with psycopg.connect(legacy_dsn, autocommit=True) as conn:
        conn.execute(migration.read_bytes())
    once = _catalog(legacy_dsn)
    with psycopg.connect(legacy_dsn, autocommit=True) as conn:
        conn.execute(migration.read_bytes())
    assert _catalog(legacy_dsn) == once
    with psycopg.connect(legacy_dsn, autocommit=True) as conn:
        for later in schema_files:
            if later.name[:4] > "005_":
                conn.execute(later.read_bytes())

    assert _catalog(legacy_dsn) == _catalog(postgres_dsn)
    lessons = PostgresRepository(legacy_dsn).list_lessons()
    assert [(x.text, x.hypothesis_id, x.technique_id) for x in lessons] == [
        ("legacy", hypothesis, technique),
        ("global", None, None),
    ]


# ---------------------------------------------------------------------------
# Migration 006
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_a_review_lesson_is_saved_and_listed_back(
    postgres_repository: PostgresRepository,
) -> None:
    """
    GIVEN a lesson whose verdict sent the change to the review branch (D35)
    WHEN it is saved and listed
    THEN migration 006's outcome CHECK accepts it and it comes back equal
    """
    state = _state()
    postgres_repository.save_run(state)
    lesson = _lesson(
        project_id=state["project"].id,
        verdict_id=new_id(),
        outcome=VerdictOutcome.review,
    )

    postgres_repository.save_lesson(lesson)

    assert postgres_repository.list_lessons(state["project"].id) == (lesson,)


@pytest.mark.postgres
def test_migration_006_allows_every_verdict_outcome_and_no_other(
    postgres_dsn: str,
) -> None:
    """
    GIVEN the test database built from every migration
    WHEN the lesson outcome CHECK is read and a direct insert tries a value
        that is no VerdictOutcome
    THEN the CHECK lists exactly the VerdictOutcome values, once, and the
        insert fails it
    """
    ((definition,),) = _rows(
        postgres_dsn,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE conrelid = 'public.lessons'::regclass"
        " AND conname = 'chk_lesson_outcome'",
    )
    for outcome in VerdictOutcome:
        assert f"'{outcome.value}'" in definition
    with (
        psycopg.connect(postgres_dsn, autocommit=True) as conn,
        pytest.raises(psycopg.errors.CheckViolation, match="chk_lesson_outcome"),
    ):
        conn.execute("INSERT INTO lessons (outcome, text) VALUES ('merged', 'x')")
