"""Tests for the engine repository (Step 1, unit U5; Postgres in Step 2, U8).

The ``repository`` fixture is parametrised over every implementation in
``REPOSITORY_FACTORIES``, so ``InMemoryRepository`` and ``PostgresRepository``
run the same contract. The Postgres case carries the ``postgres`` marker and
is skipped when ``TEST_DATABASE_URL`` is unset (see ``conftest.py``).

Step 2 changed builders only: ``lessons.project_id`` is a foreign key to
``projects``, so a project lesson's project is first registered through
``save_run`` with a uuid4 id (``_registered_project``) and listed by that id.
No assertion changed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    ChangeClass,
    Direction,
    Lesson,
    Objective,
    ObjectiveKind,
    Project,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Workload,
    new_id,
)
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state
from autonomous_ai_agents.persistence.repository import InMemoryRepository, Repository


def _in_memory(request: pytest.FixtureRequest) -> Repository:
    return InMemoryRepository()


def _postgres(request: pytest.FixtureRequest) -> Repository:
    """A PostgresRepository on this worker's emptied test database (or a skip)."""
    repository: Repository = request.getfixturevalue("postgres_repository")
    return repository


REPOSITORY_FACTORIES: dict[str, Callable[[pytest.FixtureRequest], Repository]] = {
    "in_memory": _in_memory,
    "postgres": _postgres,
}
_MARKS: dict[str, pytest.MarkDecorator] = {"postgres": pytest.mark.postgres}


@pytest.fixture(
    params=[
        pytest.param(name, marks=[_MARKS[name]] if name in _MARKS else [])
        for name in sorted(REPOSITORY_FACTORIES)
    ]
)
def repository(request: pytest.FixtureRequest) -> Iterator[Repository]:
    """Yield a fresh repository of the parametrised implementation."""
    name: str = request.param
    yield REPOSITORY_FACTORIES[name](request)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _state(run_id: str = "run-1") -> EngineState:
    project = Project(name="bridge", root_path="/home/dev/bridge")
    workload = Workload(
        project_id=project.id, name="train", command=("python", "train.py")
    )
    objective = Objective(
        project_id=project.id,
        kind=ObjectiveKind.runtime,
        metric=METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        description="minimize seconds per step",
    )
    return initial_state(project, [workload], [objective], [], run_id=run_id)


def _trial(hypothesis_id: str | None = None) -> Trial:
    return Trial(
        hypothesis_id=hypothesis_id or new_id(),
        round=1,
        branch="engine/run-1/h1",
        status=TrialStatus.measured,
    )


def _verdict(trial: Trial, outcome: VerdictOutcome = VerdictOutcome.keep) -> Verdict:
    return Verdict(
        trial_id=trial.id,
        hypothesis_id=trial.hypothesis_id,
        outcome=outcome,
        change_class=ChangeClass.efficiency,
        summary=f"{outcome}: scripted",
    )


def _lesson(project_id: str | None, text: str) -> Lesson:
    return Lesson(project_id=project_id, outcome=VerdictOutcome.keep, text=text)


def _registered_project(repository: Repository, key: str) -> str:
    """Save a run for a fresh project rooted at /home/dev/<key>; return its id.

    A project lesson needs its project registered first on Postgres
    (``lessons.project_id`` references ``projects``); the in-memory backend
    accepts any id either way.
    """
    state = _state(f"run-{key}")
    project = state["project"].model_copy(update={"root_path": f"/home/dev/{key}"})
    state["project"] = project
    repository.save_run(state)
    return project.id


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


def test_repository_satisfies_the_protocol(repository: Repository) -> None:
    """
    GIVEN a repository implementation
    WHEN checked against the runtime-checkable Repository protocol
    THEN it conforms
    """
    assert isinstance(repository, Repository)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_save_run_then_get_run_round_trips(repository: Repository) -> None:
    """
    GIVEN a saved engine state
    WHEN it is fetched by run_id
    THEN an equal state comes back
    """
    state = _state("run-1")

    repository.save_run(state)

    assert repository.get_run("run-1") == state


def test_get_run_returns_a_copy_not_the_stored_object(
    repository: Repository,
) -> None:
    """
    GIVEN a saved state
    WHEN the caller mutates the returned dict and the original dict
    THEN the stored state is unaffected either way
    """
    state = _state("run-1")
    repository.save_run(state)

    fetched = repository.get_run("run-1")
    assert fetched is not None
    fetched["round"] = 5
    state["round"] = 9

    again = repository.get_run("run-1")
    assert again is not None
    assert again["round"] == 0
    assert again is not fetched


def test_save_run_twice_replaces_the_state(repository: Repository) -> None:
    """
    GIVEN a run saved once
    WHEN a newer state for the same run_id is saved
    THEN get_run returns the newer state
    """
    state = _state("run-1")
    repository.save_run(state)
    newer = state.copy()
    newer["round"] = 2

    repository.save_run(newer)

    fetched = repository.get_run("run-1")
    assert fetched is not None
    assert fetched["round"] == 2


def test_get_run_for_unknown_run_id_returns_none(repository: Repository) -> None:
    """
    GIVEN an empty repository
    WHEN an unknown run_id is fetched
    THEN None comes back
    """
    assert repository.get_run("missing") is None


# ---------------------------------------------------------------------------
# Trials and verdicts
# ---------------------------------------------------------------------------


def test_trials_are_listed_per_run_in_insertion_order(
    repository: Repository,
) -> None:
    """
    GIVEN trials saved under two runs
    WHEN each run's trials are listed
    THEN each run sees only its own trials, in the order saved
    """
    first, second, other = _trial(), _trial(), _trial()

    repository.save_trial("run-1", first)
    repository.save_trial("run-1", second)
    repository.save_trial("run-2", other)

    assert repository.list_trials("run-1") == (first, second)
    assert repository.list_trials("run-2") == (other,)
    assert repository.list_trials("missing") == ()


def test_saving_a_trial_with_the_same_id_replaces_it(
    repository: Repository,
) -> None:
    """
    GIVEN a trial saved once
    WHEN an updated copy with the same id is saved
    THEN the list holds the updated copy only, in the original position
    """
    first, second = _trial(), _trial()
    repository.save_trial("run-1", first)
    repository.save_trial("run-1", second)
    updated = first.model_copy(update={"status": TrialStatus.failed, "error": "boom"})

    repository.save_trial("run-1", updated)

    assert repository.list_trials("run-1") == (updated, second)


def test_verdicts_are_listed_per_run_in_insertion_order(
    repository: Repository,
) -> None:
    """
    GIVEN verdicts saved under two runs
    WHEN each run's verdicts are listed
    THEN each run sees only its own verdicts, in the order saved
    """
    keep, reject = _verdict(_trial()), _verdict(_trial(), VerdictOutcome.reject)
    other = _verdict(_trial())

    repository.save_verdict("run-1", keep)
    repository.save_verdict("run-1", reject)
    repository.save_verdict("run-2", other)

    assert repository.list_verdicts("run-1") == (keep, reject)
    assert repository.list_verdicts("run-2") == (other,)
    assert repository.list_verdicts("missing") == ()


def test_saving_a_verdict_with_the_same_id_replaces_it(
    repository: Repository,
) -> None:
    """
    GIVEN a verdict saved once
    WHEN an approved copy with the same id is saved
    THEN the list holds the approved copy only
    """
    verdict = _verdict(_trial(), VerdictOutcome.needs_approval)
    repository.save_verdict("run-1", verdict)
    approved = verdict.model_copy(
        update={"outcome": VerdictOutcome.keep, "approved_by": "praveen"}
    )

    repository.save_verdict("run-1", approved)

    assert repository.list_verdicts("run-1") == (approved,)


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------


def test_list_lessons_without_filter_returns_all_in_insertion_order(
    repository: Repository,
) -> None:
    """
    GIVEN global and per-project lessons
    WHEN lessons are listed without a project filter
    THEN all come back in the order saved
    """
    global_lesson = _lesson(None, "frozen encoder -> cache embeddings")
    project_a = _lesson(
        _registered_project(repository, "project-a"), "bf16 needs approval here"
    )
    project_b = _lesson(
        _registered_project(repository, "project-b"), "numba hurt on this workload"
    )

    repository.save_lesson(project_a)
    repository.save_lesson(global_lesson)
    repository.save_lesson(project_b)

    assert repository.list_lessons() == (project_a, global_lesson, project_b)
    assert repository.list_lessons(None) == (project_a, global_lesson, project_b)


def test_list_lessons_for_a_project_includes_global_ones(
    repository: Repository,
) -> None:
    """
    GIVEN global and per-project lessons
    WHEN lessons are listed for one project
    THEN that project's lessons and the global ones come back, others do not
    """
    a_id = _registered_project(repository, "project-a")
    b_id = _registered_project(repository, "project-b")
    global_lesson = _lesson(None, "frozen encoder -> cache embeddings")
    project_a = _lesson(a_id, "bf16 needs approval here")
    project_b = _lesson(b_id, "numba hurt on this workload")
    repository.save_lesson(project_a)
    repository.save_lesson(global_lesson)
    repository.save_lesson(project_b)

    assert repository.list_lessons(a_id) == (project_a, global_lesson)
    assert repository.list_lessons(b_id) == (global_lesson, project_b)
    assert repository.list_lessons("unknown") == (global_lesson,)


def test_saving_a_lesson_with_the_same_id_replaces_it(
    repository: Repository,
) -> None:
    """
    GIVEN a lesson saved once
    WHEN a reweighted copy with the same id is saved
    THEN the list holds the reweighted copy only
    """
    lesson = _lesson(_registered_project(repository, "project-a"), "cache embeddings")
    repository.save_lesson(lesson)
    reweighted = lesson.model_copy(update={"weight": 2.0})

    repository.save_lesson(reweighted)

    assert repository.list_lessons() == (reweighted,)


def test_empty_repository_lists_nothing(repository: Repository) -> None:
    """
    GIVEN an empty repository
    WHEN lessons, trials and verdicts are listed
    THEN every listing is an empty tuple
    """
    assert repository.list_lessons() == ()
    assert repository.list_trials("run-1") == ()
    assert repository.list_verdicts("run-1") == ()
