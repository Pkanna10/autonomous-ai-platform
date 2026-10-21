"""Repository: where the engine records what it did and what it learned.

``Repository`` is a narrow Protocol so the orchestrator never depends on a
database driver. ``InMemoryRepository`` is the Step 1 implementation and the
one tests use; Step 2 adds a Postgres class behind the same Protocol and
reuses ``tests/persistence/test_repository.py`` unchanged. Graph-state
checkpoints are the LangGraph checkpointer's job, not the repository's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from autonomous_ai_agents.common.models import Lesson, Trial, Verdict

if TYPE_CHECKING:
    from autonomous_ai_agents.orchestrator.state import EngineState


@runtime_checkable
class Repository(Protocol):
    """Durable store for runs, trials, verdicts and lessons."""

    def save_run(self, state: EngineState) -> None: ...

    def get_run(self, run_id: str) -> EngineState | None: ...

    def save_trial(self, run_id: str, trial: Trial) -> None: ...

    def save_verdict(self, run_id: str, verdict: Verdict) -> None: ...

    def save_lesson(self, lesson: Lesson) -> None: ...

    def list_lessons(self, project_id: str | None = None) -> tuple[Lesson, ...]: ...

    def list_trials(self, run_id: str) -> tuple[Trial, ...]: ...

    def list_verdicts(self, run_id: str) -> tuple[Verdict, ...]: ...


class InMemoryRepository:
    """Dict-backed ``Repository``; saving an id again replaces the earlier row."""

    def __init__(self) -> None:
        self._runs: dict[str, EngineState] = {}
        self._trials: dict[str, dict[str, Trial]] = {}
        self._verdicts: dict[str, dict[str, Verdict]] = {}
        self._lessons: dict[str, Lesson] = {}

    def save_run(self, state: EngineState) -> None:
        """Store a shallow copy of ``state`` under its run_id."""
        self._runs[state["run_id"]] = state.copy()

    def get_run(self, run_id: str) -> EngineState | None:
        """Return a shallow copy of the stored state, or None when unknown."""
        stored = self._runs.get(run_id)
        return None if stored is None else stored.copy()

    def save_trial(self, run_id: str, trial: Trial) -> None:
        """Store ``trial`` under ``run_id``, replacing one with the same id."""
        self._trials.setdefault(run_id, {})[trial.id] = trial

    def save_verdict(self, run_id: str, verdict: Verdict) -> None:
        """Store ``verdict`` under ``run_id``, replacing one with the same id."""
        self._verdicts.setdefault(run_id, {})[verdict.id] = verdict

    def save_lesson(self, lesson: Lesson) -> None:
        """Store ``lesson``, replacing one with the same id."""
        self._lessons[lesson.id] = lesson

    def list_lessons(self, project_id: str | None = None) -> tuple[Lesson, ...]:
        """All lessons, or the project's plus the global ones, in insertion order."""
        return tuple(
            lesson
            for lesson in self._lessons.values()
            if project_id is None or lesson.project_id in (None, project_id)
        )

    def list_trials(self, run_id: str) -> tuple[Trial, ...]:
        """The run's trials in insertion order; empty for an unknown run."""
        return tuple(self._trials.get(run_id, {}).values())

    def list_verdicts(self, run_id: str) -> tuple[Verdict, ...]:
        """The run's verdicts in insertion order; empty for an unknown run."""
        return tuple(self._verdicts.get(run_id, {}).values())
