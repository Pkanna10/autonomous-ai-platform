"""A refused or failing ``save_trial`` keeps the round's progress (Step 3, U1).

The trials node saves each trial after ``run_one`` has spent on it. Before
U1 that call sat outside the node's ``try``, so a repository that refused the
trial (Postgres refusing a caller id such as ``h1``) or failed (a dropped
connection) dropped the money the trial had spent from the failed run. These
tests drive the node, and a whole run, through a repository that refuses one
trial, and check that the failed state carries every dollar spent.

Swap points: ``_RefusingRepository`` wraps the real ``InMemoryRepository``
(the fake), raising for one hypothesis id the way ``PostgresRepository``
raises ``InvalidRecordIdError`` before SQL; the trial runner is the stub
over the design scripts (H1 0.12 USD, H3 0.05 USD).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.errors import EngineError, InvalidRecordIdError
from autonomous_ai_agents.common.models import (
    Guardrail,
    Hypothesis,
    HypothesisStatus,
    Objective,
    Project,
    RunPhase,
    Trial,
    Workload,
)
from autonomous_ai_agents.execution.runner import ScriptedOutcome
from autonomous_ai_agents.orchestrator.main import Orchestrator
from autonomous_ai_agents.orchestrator.nodes import (
    LOOP_NODES,
    NodeContext,
    NodeDelta,
    NodeFn,
    make_nodes,
    progress_of,
)
from autonomous_ai_agents.orchestrator.state import (
    REDUCER_KEYS,
    EngineState,
    initial_state,
)
from autonomous_ai_agents.persistence.repository import InMemoryRepository

ContextFactory = Callable[..., NodeContext]
RUN_ID = "run-u1-save-trial"
H1_USD, H3_USD = 0.12, 0.05
"""What the design scripts charge for H1 and H3 (``tests/conftest.py``)."""


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


class _RefusingRepository(InMemoryRepository):
    """The in-memory repository, except that ``save_trial`` raises ``error``
    for trials of ``hypothesis_id`` (nothing is stored for them)."""

    def __init__(self, hypothesis_id: str, error: Exception) -> None:
        super().__init__()
        self._refused, self._error = hypothesis_id, error

    def save_trial(self, run_id: str, trial: Trial) -> None:
        if trial.hypothesis_id == self._refused:
            raise self._error
        super().save_trial(run_id, trial)


def _apply(state: EngineState, delta: Mapping[str, object]) -> EngineState:
    """Merge ``delta`` into ``state`` the way LangGraph's reducers would."""
    merged: dict[str, Any] = dict(state)
    for key, value in delta.items():
        if key in REDUCER_KEYS:
            assert isinstance(value, list), key
            merged[key] = [*merged[key], *value]
        else:
            merged[key] = value
    return cast(EngineState, merged)


def _before_trials(nodes: Mapping[str, NodeFn], state: EngineState) -> EngineState:
    for name in LOOP_NODES[: LOOP_NODES.index("trials")]:
        state = _apply(state, nodes[name](state))
    return state


def _trials(delta: NodeDelta, key: str) -> list[Trial]:
    value = delta[key]
    assert isinstance(value, list), key
    assert all(isinstance(item, Trial) for item in value), key
    return cast(list[Trial], value)


def _statuses(delta: NodeDelta) -> dict[str, HypothesisStatus]:
    value = delta["hypotheses"]
    assert isinstance(value, list)
    return {h.id: h.status for h in cast(list[Hypothesis], value)}


@pytest.fixture
def base_state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    """A fresh run with a fixed id."""
    return initial_state(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id=RUN_ID,
    )


@pytest.fixture
def design_costs(design_scripts: dict[str, ScriptedOutcome]) -> Sequence[float]:
    """Pins the two costs these tests add up, so a script change fails here."""
    costs = [script.cost_usd for script in design_scripts.values()]
    assert H1_USD in costs and H3_USD in costs
    return costs


# ---------------------------------------------------------------------------
# The trials node
# ---------------------------------------------------------------------------


ERRORS: list[Callable[[], Exception]] = [
    lambda: InvalidRecordIdError("trial.hypothesis_id 'h3' is not a valid id"),
    lambda: OSError("connection to the database was lost"),
]
"""Built per test: ``keep_progress`` writes onto the exception instance."""


@pytest.mark.usefixtures("design_costs")
@pytest.mark.parametrize("make_error", ERRORS, ids=["refused-id", "connection-lost"])
def test_a_save_trial_raise_keeps_the_rounds_spend(
    make_context: ContextFactory,
    base_state: EngineState,
    h1_cache: Hypothesis,
    h3_noise: Hypothesis,
    make_error: Callable[[], Exception],
) -> None:
    """
    GIVEN H1 then H3 proposed, 0.25 of 1.00 USD spent, and a repository that
          raises when H3's trial is saved
    WHEN trials runs
    THEN the error propagates carrying the round's progress: the running
         total with H1's and H3's money and tokens, H1's trial in round_trials
         and trials, H1 trialled and H3 (whose trial was not recorded) still
         proposed
    """
    error = make_error()
    repository = _RefusingRepository(h3_noise.id, error)
    nodes = make_nodes(make_context([h1_cache, h3_noise], repository=repository))
    started = _before_trials(nodes, base_state)
    state = cast(
        EngineState,
        {**started, "max_cost_usd": 1.0, "cost_usd": 0.25, "tokens_used": 100},
    )

    with pytest.raises(type(error)) as raised:
        nodes["trials"](state)

    assert raised.value is error
    progress = progress_of(raised.value)
    assert progress["cost_usd"] == pytest.approx(0.25 + H1_USD + H3_USD)
    [kept] = _trials(progress, "round_trials")
    assert kept.hypothesis_id == h1_cache.id
    assert _trials(progress, "trials") == [kept]
    assert repository.list_trials(RUN_ID) == (kept,)
    tokens = progress["tokens_used"]
    assert isinstance(tokens, int)
    assert tokens > 100 + kept.tokens_used
    assert _statuses(progress) == {
        h1_cache.id: HypothesisStatus.trialled,
        h3_noise.id: HypothesisStatus.proposed,
    }


@pytest.mark.usefixtures("design_costs")
def test_a_save_trial_raise_never_charges_past_the_cap(
    make_context: ContextFactory,
    base_state: EngineState,
    h1_cache: Hypothesis,
) -> None:
    """
    GIVEN 0.95 of 1.00 USD spent and H1 (0.12 USD) refused on save
    WHEN trials runs it within what is left and the save raises
    THEN the progress is the cap, never more (as the running total is)
    """
    error = InvalidRecordIdError("trial.hypothesis_id refused")
    repository = _RefusingRepository(h1_cache.id, error)
    nodes = make_nodes(
        make_context([h1_cache], repository=repository, min_trial_budget_usd=0.01)
    )
    started = _before_trials(nodes, base_state)
    state = cast(
        EngineState,
        {**started, "max_cost_usd": 1.0, "cost_usd": 0.95, "tokens_used": 0},
    )

    with pytest.raises(InvalidRecordIdError) as raised:
        nodes["trials"](state)

    progress = progress_of(raised.value)
    assert progress["cost_usd"] == pytest.approx(1.0)
    assert progress["round_trials"] == []


# ---------------------------------------------------------------------------
# A whole run
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("design_costs")
def test_a_run_whose_trial_save_is_refused_fails_with_its_spend_recorded(
    make_context: ContextFactory,
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    h1_cache: Hypothesis,
    h3_noise: Hypothesis,
) -> None:
    """
    GIVEN a run of H1 then H3 whose repository refuses H3's trial (an
          ``EngineError``, as Postgres raised for ``h1`` before U1)
    WHEN the run is executed
    THEN it fails naming the refusal, and the failed state the repository
         holds carries both trials' money, with H1's trial in it
    """
    error = InvalidRecordIdError("trial.hypothesis_id refused for this test")
    assert isinstance(error, EngineError)
    repository = _RefusingRepository(h3_noise.id, error)
    ctx = make_context([h1_cache, h3_noise], repository=repository)

    result = Orchestrator(context=ctx).run(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id=RUN_ID,
    )

    assert result.status == "failed"
    stored = repository.get_run(RUN_ID)
    assert stored is not None
    assert stored["phase"] is RunPhase.failed
    assert stored["error"] is not None
    assert "refused for this test" in stored["error"]
    assert stored["cost_usd"] == pytest.approx(H1_USD + H3_USD)
    assert [t.hypothesis_id for t in stored["trials"]] == [h1_cache.id]
    assert result.state["cost_usd"] == stored["cost_usd"]
