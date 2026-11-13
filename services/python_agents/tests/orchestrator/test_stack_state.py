"""X2-DT, U1: the state key ``stack`` (O63).

One new key, ``stack: StackLedger | None``, starts at ``None`` and stays
there unless stacking is on. It is an ``ADDED_KEYS`` key: a state stored, or
a run paused, before it existed loads and dumps with ``None``. With the key
at ``None`` every other key's dump is what it was before the key existed.
"""

from __future__ import annotations

import json
from typing import Any, cast, get_type_hints

import pytest

from autonomous_ai_agents.common.models import (
    Baseline,
    Combination,
    Guardrail,
    Objective,
    Project,
    RoundBase,
    StackLedger,
    Workload,
)
from autonomous_ai_agents.orchestrator.serde import ADDED_KEYS, dump_state, load_state
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ORIGIN = "a" * 40
TIP = "b" * 40


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    return initial_state(sample_project, [sample_workload], [sample_objective],
                         sample_guardrails, run_id="run-x2dt")  # fmt: skip


def _ledger() -> StackLedger:
    combination = Combination(base_commit=ORIGIN, tip_commit=TIP,
                              applied_trial_ids=("t-1",), holds=True,
                              summary="t-1 applied; holds")  # fmt: skip
    first = RoundBase(round=1, base_commit=ORIGIN, offered_trial_ids=("t-1",),
                      combination=combination, adopted=True, tip_commit=TIP,
                      floor=0.025, reason="held",
                      seconds={"combine": 4.0, "baseline": 2.5})  # fmt: skip
    return StackLedger(origin_commit=ORIGIN, origin_baseline=Baseline(commit=ORIGIN),
                       rounds=(first,))  # fmt: skip


def _without_stack(state: EngineState) -> EngineState:
    return cast(EngineState, {k: v for k, v in state.items() if k != "stack"})


def test_the_stack_key_is_declared_and_starts_empty(state: EngineState) -> None:
    hints = get_type_hints(EngineState)

    assert hints["stack"] == StackLedger | None
    assert state["stack"] is None
    assert ADDED_KEYS["stack"] is None


def test_a_state_with_a_ledger_round_trips_through_strict_json(
    state: EngineState,
) -> None:
    state["stack"] = _ledger()
    state["base_commit"] = TIP

    text = json.dumps(dump_state(state), allow_nan=False)
    loaded = load_state(json.loads(text))

    assert loaded == state
    ledger = loaded["stack"]
    assert isinstance(ledger, StackLedger)
    assert isinstance(ledger.rounds[0], RoundBase)
    assert ledger.current_base == TIP


def test_an_older_stored_state_loads_with_no_ledger(state: EngineState) -> None:
    """Stored data from before X2-DT has no ``stack``: it loads as ``None``;
    any other missing key is still refused."""
    dumped = dump_state(state)
    older: dict[str, Any] = {k: v for k, v in dumped.items() if k != "stack"}

    loaded = load_state(older)

    assert loaded["stack"] is None
    assert loaded == state
    with pytest.raises(ValueError, match=r"missing \['round'\]"):
        load_state({k: v for k, v in older.items() if k != "round"})


def test_a_run_paused_before_the_key_is_saved_with_no_ledger(
    state: EngineState,
) -> None:
    """A LangGraph checkpoint written before X2-DT has no ``stack`` channel:
    ``dump_state`` saves it with ``None``; any other missing key is refused."""
    older = _without_stack(state)

    dumped = dump_state(older)

    assert dumped["stack"] is None
    assert load_state(dumped) == {**older, "stack": None}
    with pytest.raises(ValueError, match=r"missing \['phase'\]"):
        dump_state(cast(EngineState, {k: v for k, v in older.items() if k != "phase"}))


def test_with_no_ledger_every_other_key_dumps_as_before(state: EngineState) -> None:
    """The default stays byte-identical: with ``stack`` at ``None`` the dump is
    the pre-X2-DT dump plus one ``"stack": null`` entry, in the last place."""
    with_key = dump_state(state)
    before = {k: v for k, v in with_key.items() if k != "stack"}

    assert list(with_key)[-1] == "stack"
    assert json.dumps(with_key) == json.dumps({**before, "stack": None})
    assert dump_state(_without_stack(state)) == with_key


def test_a_value_that_is_not_a_ledger_is_refused_by_name(state: EngineState) -> None:
    bad = cast(dict[str, Any], dict(state))
    bad["stack"] = {"origin_commit": ORIGIN}

    with pytest.raises(ValueError, match=r"state\['stack'\] does not fit"):
        dump_state(cast(EngineState, bad))
    with pytest.raises(ValueError, match=r"state\['stack'\] does not fit"):
        load_state({**dump_state(state), "stack": {"origin_commit": ORIGIN}})
