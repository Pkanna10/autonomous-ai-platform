"""Stacked rounds' guards in the loop nodes (X2-DT U4; dt-design section 1,
"Guarded edits in orchestrator/nodes.py").

Four guards, each without effect while stacking is off:

- ``NodeContext`` refuses ``stack_rounds`` without a combiner or a stacker,
  with a quality check, with ``default_output_check`` off, or with a
  dry-merging combiner whose ``site_stacks`` is not ``"off"`` (O63: quality
  mode and SITE_STACKS are refused under stacking), at construction, so a
  misconfigured context never reaches a node, let alone a request;
- ``_run_verdicts`` reads the seeds' keys through ``rekey.current_keys``, so
  a key re-keyed onto an adopted tip seeds at the tip's lines; with no
  re-key record the result is today's (``recorded_keys``) exactly;
- ``_next_compound`` pairs only trials on the current round base while
  stacking (a replay needs both parents to be children of it);
- ``verdicts``, once ``state["stack"]`` holds a ledger and the round is
  measured at a tip, checks each trial's outputs against the original base
  too: a difference is an ``original base:`` violation, so rule 1 rejects.

Swap points: ``_Rebased`` stands for ``GitTrialRunner`` (a commit, and
``base_commit`` from the baseline's commit, as the real runner takes it),
over the conftest's ``StubTrialRunner``; ``FakeCombiner`` and
``FakeStacker`` (execution/fakes.py) stand for ``GitCombiner`` and
``GitStacker``; ``_Probing`` is a combiner that can dry-merge, as
``GitCombiner`` can. The tip's and the origin's baselines come from the
real baseline node over ``StubBaselineRunner`` scripts that differ only in
their output fingerprint. Nodes run by hand, merged as LangGraph's reducers
merge them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final, cast

import pytest

from autonomous_ai_agents.common.config import SiteStacks
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    Baseline,
    BuiltinMeasure,
    ChangeClass,
    EngineEvent,
    Guardrail,
    Hypothesis,
    HypothesisSource,
    Objective,
    Project,
    QualityCheck,
    RunPhase,
    StackLedger,
    Trial,
    Verdict,
    VerdictOutcome,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.execution.combine import DryMerge
from autonomous_ai_agents.execution.fakes import FakeCombiner, FakeStacker
from autonomous_ai_agents.execution.protocols import KeptChange, TrialBrief
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization import rekey
from autonomous_ai_agents.optimization.anticheat import fingerprint
from autonomous_ai_agents.optimization.evolve import ReplayRefusedError
from autonomous_ai_agents.optimization.idea_dedupe import (
    IdeaKey,
    MechanismKey,
    Target,
    key_event,
    recorded_keys,
)
from autonomous_ai_agents.optimization.idea_types import (
    GenerateEvent,
    Mechanism,
    MorphCell,
)
from autonomous_ai_agents.optimization.sources import RunVerdicts
from autonomous_ai_agents.orchestrator import nodes
from autonomous_ai_agents.orchestrator.combine_node import ConflictProbe
from autonomous_ai_agents.orchestrator.events import make_event
from autonomous_ai_agents.orchestrator.nodes import NodeContext, NodeDelta, make_nodes
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]
ORIGIN: Final = "a" * 40
TIP: Final = "b" * 40
VAL_LOSS: Final = "val_loss"
SAME: Final = fingerprint("baseline")  # the conftest's baseline output
ORIGIN_OUTPUT: Final = fingerprint("the original base")
PATH: Final = "lib/parse.py"
LOOP: Final = (
    "connect", "understand", "define", "baseline", "profile", "research",
    "hypotheses", "trials", "judges",
)  # fmt: skip


def _script(
    *wall: float, path: str, output: str = SAME, error: str | None = None
) -> ScriptedOutcome:
    return ScriptedOutcome(
        touched_paths=(path,),
        samples={METRIC_WALL_TIME_S: wall, VAL_LOSS: (0.500,) * 5},
        output_fingerprint=output, tests_passed=True, error=error,
        cost_usd=0.05, tokens_used=1000,
    )  # fmt: skip


WIN: Final = _script(1.05, 1.02, 1.08, 1.05, 1.05, path=PATH)
# Baseline 1.80 s (stdev 0.035): both are inconclusive near misses.
NEAR: Final = {
    "N1 cache the parse": _script(1.75, 1.72, 1.78, 1.75, 1.75, path="lib/parse.py"),
    "N2 hoist the lookup": _script(1.76, 1.73, 1.79, 1.76, 1.76, path="lib/index.py"),
}  # fmt: skip


class _Rebased(StubTrialRunner):
    """``StubTrialRunner`` whose trials carry a commit and start from the
    baseline's commit, as ``GitTrialRunner``'s do; ``replay`` is never
    reached here (the tests stop at the pair)."""

    def run(self, hypothesis: Hypothesis, workloads: Sequence[Workload],
            baseline: Baseline, **kwargs: Any) -> Trial:  # fmt: skip
        trial = super().run(hypothesis, workloads, baseline, **kwargs)
        commit = hashlib.sha1(trial.id.encode()).hexdigest()  # noqa: S324 - a fake id
        return trial.model_copy(
            update={"commit": commit, "base_commit": baseline.commit}
        )

    def replay(
        self, hypothesis: Hypothesis, parents: Sequence[Trial],
        workloads: Sequence[Workload], baseline: Baseline, *, round: int,
        branch: str, budget_usd: float, brief: TrialBrief,
    ) -> Trial:  # fmt: skip
        raise ReplayRefusedError("not reached in these tests")


class _Probing(FakeCombiner):
    """A combiner that can dry-merge (``ConflictProbe``), as ``GitCombiner``."""

    def __init__(self, site_stacks: SiteStacks) -> None:
        super().__init__([])
        self.site_stacks: SiteStacks = site_stacks

    def dry_merge(
        self, project: Project, base_commit: str, kept: Sequence[KeptChange]
    ) -> DryMerge:
        return DryMerge()


ACC: Final = QualityCheck(
    name="acc", measure=BuiltinMeasure.accuracy, labels="eval/labels.txt",
    frozen_paths=("eval/labels.txt",),
)  # fmt: skip


def _stacking(**overrides: Any) -> dict[str, Any]:
    """The knobs of a context that may stack, with ``overrides`` laid over."""
    knobs: dict[str, Any] = {
        "stack_rounds": True,
        "combiner": FakeCombiner([]),
        "stacker": FakeStacker(),
        "default_output_check": True,
    }
    return {**knobs, **overrides}


def _idea(project: Project, title: str) -> Hypothesis:
    return Hypothesis(
        project_id=project.id, source=HypothesisSource.novel, title=title,
        rationale="r", change_class=ChangeClass.efficiency, expected_gain=0.1,
        provability=0.7, risk=0.1,
    )  # fmt: skip


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    state = initial_state(
        sample_project, [sample_workload], [sample_objective], sample_guardrails,
        run_id="run-dt4", max_rounds=3, max_cost_usd=10.0,
    )  # fmt: skip
    state["base_commit"] = ORIGIN
    return state


def _apply(state: EngineState, delta: NodeDelta) -> EngineState:
    merged: dict[str, Any] = dict(state)
    for key, value in delta.items():
        reducer = key in ("events", "trials", "verdicts", "lessons")
        merged[key] = [*merged[key], *cast(list[Any], value)] if reducer else value
    return cast(EngineState, merged)


def _through(ctx: NodeContext, state: EngineState, names: Sequence[str]) -> EngineState:
    run = make_nodes(ctx)
    for name in names:
        state = _apply(state, run[name](state))
    return state


# ---------------------------------------------------------------------------
# The knobs: refused at construction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"combiner": None}, "stack_rounds needs a combiner"),
        ({"stacker": None}, "stack_rounds needs a stacker"),
        ({"quality": ACC}, "stack_rounds refuses a quality check"),
        ({"default_output_check": False}, "stack_rounds needs default_output_check"),
        ({"combiner": _Probing("record")}, "stack_rounds refuses SITE_STACKS='record'"),
        ({"combiner": _Probing("on")}, "stack_rounds refuses SITE_STACKS='on'"),
    ],
    ids=[
        "no combiner",
        "no stacker",
        "quality",
        "no output check",
        "site stacks record",
        "site stacks on",
    ],
)
def test_a_context_that_cannot_stack_is_refused_at_construction(
    make_context: ContextFactory, overrides: dict[str, Any], match: str
) -> None:
    """
    GIVEN stacking on and one requirement missing or one refused mode on
    WHEN the context is built (the factory, or ``dataclasses.replace``)
    THEN it is a ``ValueError`` naming it: no node, so no request, ever runs
    """
    with pytest.raises(ValueError, match=match):
        make_context(**_stacking(**overrides))


def test_a_context_that_can_stack_is_built_and_off_refuses_nothing(
    make_context: ContextFactory,
) -> None:
    """Stacking with a combiner (a dry-merging one too, SITE_STACKS off), a
    stacker and the default output check builds; off, the same modes stacking
    refuses still build, and the new fields default to off and ``None``."""
    probing = _Probing("off")
    assert isinstance(probing, ConflictProbe)
    assert not isinstance(FakeCombiner([]), ConflictProbe)
    on = make_context(**_stacking())
    assert on.stack_rounds is True and isinstance(on.stacker, FakeStacker)
    assert make_context(**_stacking(combiner=probing)).combiner is probing
    default = make_context()
    assert (default.stack_rounds, default.stacker) == (False, None)
    off = make_context(quality=ACC, combiner=_Probing("on"))
    assert off.quality == ACC


# ---------------------------------------------------------------------------
# The seeds' keys: current_keys, identical with no re-key record
# ---------------------------------------------------------------------------


def _key(first: int, last: int) -> IdeaKey:
    target = Target(path=PATH, first=first, last=last)
    key = MechanismKey(
        target=target, mechanism=Mechanism.remove_work, cell=MorphCell.work_eliminate
    )
    return IdeaKey(key=key, function="parse")


def _stored(state: EngineState, events: Sequence[GenerateEvent]) -> list[EngineEvent]:
    """The events as the node stores them (``_note`` puts the code in)."""
    return [
        make_event(state["run_id"], RunPhase.hypotheses, e.message,
                   data={"code": e.code, **e.data})
        for e in events
    ]  # fmt: skip


def _round_one(
    make_context: ContextFactory, state: EngineState, project: Project
) -> tuple[EngineState, Hypothesis, Hypothesis]:
    n1, n2 = (_idea(project, title) for title in NEAR)
    ctx = make_context([n1, n2], runner=_Rebased(dict(NEAR)))
    after = _through(ctx, state, (*LOOP, "verdicts"))
    assert [v.outcome for v in after["verdicts"]] == [VerdictOutcome.inconclusive] * 2
    return after, n1, n2


def _keys_of(found: RunVerdicts | None) -> dict[str, IdeaKey | None]:
    assert found is not None
    return {t.hypothesis.id: t.key for t in found.trialled}


def test_with_no_rekey_record_the_seeds_are_todays_exactly(
    make_context: ContextFactory,
    state: EngineState,
    sample_project: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN a run with two verdicts, one with a recorded key, no re-key record
    WHEN ``_run_verdicts`` reads them
    THEN the result equals the one today's reader (``recorded_keys``) gives,
         every field and every key
    """
    after, n1, n2 = _round_one(make_context, state, sample_project)
    after["events"] = [*after["events"], *_stored(after, [key_event(n1.id, "t", _key(5, 6))])]  # fmt: skip

    found = nodes._run_verdicts(after)
    monkeypatch.setattr(nodes, "current_keys", recorded_keys)
    today = nodes._run_verdicts(after)

    assert found == today
    assert _keys_of(found) == {n1.id: _key(5, 6), n2.id: None}


def test_a_rekeyed_key_seeds_at_the_tip_and_a_dropped_one_has_none(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN two recorded keys, then an adopted tip whose diff shifts one key by
         two lines and deletes the other's file
    WHEN ``_run_verdicts`` reads them
    THEN the first seeds at its tip lines and the second has no key, where
         ``recorded_keys`` alone would have kept both at the base's lines
    """
    after, n1, n2 = _round_one(make_context, state, sample_project)
    gone = IdeaKey(
        key=MechanismKey(
            target=Target(path="lib/gone.py", first=1, last=1),
            mechanism=Mechanism.remove_work, cell=MorphCell.work_eliminate,
        ),
        function=None,
    )  # fmt: skip
    recorded = [key_event(n1.id, "t", _key(5, 6)), key_event(n2.id, "t", gone)]
    lines = [f"line {n}" for n in range(1, 21)]
    diff = (
        f"diff --git a/{PATH} b/{PATH}\nindex 1111111..2222222 100644\n"
        f"--- a/{PATH}\n+++ b/{PATH}\n@@ -1,3 +1,5 @@\n+new a\n+new b\n"
        + "".join(f" {row}\n" for row in lines[:3])
        + "diff --git a/lib/gone.py b/lib/gone.py\ndeleted file mode 100644\n"
        "index 3333333..0000000\n--- a/lib/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
    )
    stored = _stored(after, recorded)
    moved = rekey.rekey_events(recorded_keys(e.data for e in stored), diff, ORIGIN, TIP)
    after["events"] = [*after["events"], *stored, *_stored(after, moved)]

    assert {e.code for e in moved} == {rekey.REKEY_EVENT, rekey.DROP_EVENT}
    assert _keys_of(nodes._run_verdicts(after)) == {n1.id: _key(7, 8), n2.id: None}
    assert recorded_keys(e.data for e in after["events"]) == {n1.id: _key(5, 6), n2.id: gone}  # fmt: skip


# ---------------------------------------------------------------------------
# Compounds: only trials on the current round base
# ---------------------------------------------------------------------------


def _pair_ids(pair: Any) -> tuple[str, str] | None:
    return None if pair is None else (pair.first.trial.id, pair.second.trial.id)


def test_compounds_pair_only_trials_on_the_current_base_while_stacking(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN round one's two near misses, both started from the origin
    WHEN the next compound is looked for, stacking on and off, with the
         round base at the origin, at a tip, and with one trial moved to it
    THEN off always finds their pair (today); on finds it only while both
         trials are on the round base, and none once either is not
    """
    after, n1, n2 = _round_one(make_context, state, sample_project)
    runner = _Rebased(dict(NEAR))
    off = make_context([n1, n2], runner=runner, near_miss_compounds=True)
    on = make_context([n1, n2], runner=runner, near_miss_compounds=True, **_stacking())
    t1, t2 = after["trials"]
    assert (t1.base_commit, t2.base_commit) == (ORIGIN, ORIGIN)
    pair = _pair_ids(nodes._next_compound(off, after))
    assert pair is not None and set(pair) == {t1.id, t2.id}
    at_tip = cast(EngineState, {**after, "base_commit": TIP})
    split = cast(EngineState, {**after, "trials": [t1, t2.model_copy(update={"base_commit": TIP})]})  # fmt: skip
    unknown = cast(EngineState, {**after, "trials": [t1, t2.model_copy(update={"base_commit": None})]})  # fmt: skip

    assert _pair_ids(nodes._next_compound(on, after)) == pair
    assert nodes._next_compound(on, at_tip) is None
    assert nodes._next_compound(on, split) is None
    assert nodes._next_compound(on, unknown) is None
    for moved in (at_tip, split, unknown):
        assert _pair_ids(nodes._next_compound(off, moved)) == pair


# ---------------------------------------------------------------------------
# Verdicts: equivalence against the original base too
# ---------------------------------------------------------------------------


def _baseline_at(
    make_context: ContextFactory, state: EngineState, commit: str, output: str
) -> Baseline:
    script = ScriptedOutcome(
        samples={METRIC_WALL_TIME_S: (1.80, 1.75, 1.85, 1.80, 1.80),
                 VAL_LOSS: (0.500,) * 5},
        tests_passed=True, output_fingerprint=output,
    )  # fmt: skip
    ctx = make_context(baseline_runner=StubBaselineRunner(script))
    at = _through(ctx, cast(EngineState, {**state, "base_commit": commit}), LOOP[:4])
    measured = at["baseline"]
    assert measured is not None and measured.commit == commit
    return measured


def _judged_at_tip(
    make_context: ContextFactory,
    state: EngineState,
    project: Project,
    scripts: Mapping[str, ScriptedOutcome],
) -> tuple[NodeContext, EngineState]:
    """A round measured at the tip (the tip's twin outputs ``SAME``), judged."""
    ideas = [_idea(project, title) for title in scripts]
    ctx = make_context(ideas, runner=_Rebased(dict(scripts)))
    return ctx, _through(ctx, cast(EngineState, {**state, "base_commit": TIP}), LOOP)


def _ledger(
    make_context: ContextFactory, state: EngineState, output: str
) -> StackLedger:
    origin = _baseline_at(make_context, state, ORIGIN, output)
    return StackLedger(origin_commit=ORIGIN, origin_baseline=origin)


def _verdicts(
    ctx: NodeContext, state: EngineState, stack: StackLedger | None
) -> list[Verdict]:
    delta = make_nodes(ctx)["verdicts"](cast(EngineState, {**state, "stack": stack}))
    return cast(list[Verdict], delta["verdicts"])


def _decided(
    ctx: NodeContext, state: EngineState, stack: StackLedger | None
) -> list[dict[str, Any]]:
    """The verdicts as decided: without their fresh id and time."""
    return [
        v.model_dump(exclude={"id", "decided_at"}) for v in _verdicts(ctx, state, stack)
    ]


def test_a_trial_whose_outputs_differ_from_the_original_base_is_rejected(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN a round at a tip whose outputs are not the original base's, and a
          trial that matches the tip's twin exactly (the frozen judge passes)
    WHEN the verdicts node runs with the stack ledger set
    THEN the trial carries an ``original base:`` output violation and rule 1
         rejects it; with ``stack`` None it is today's keep, no violation
    """
    ctx, judged = _judged_at_tip(make_context, state, sample_project, {"W win": WIN})
    stack = _ledger(make_context, state, ORIGIN_OUTPUT)

    (today,) = _verdicts(ctx, judged, None)
    (stacked,) = _verdicts(ctx, judged, stack)

    assert (today.outcome, today.violations) == (VerdictOutcome.keep, ())
    assert stacked.outcome is VerdictOutcome.reject
    (violation,) = stacked.violations
    assert violation.rule is ViolationRule.fingerprint_mismatch
    workload = state["workloads"][0].id
    assert violation.message == f"original base: workload {workload}: output changed"


def test_every_workload_whose_output_differs_is_named(
    make_context: ContextFactory,
    state: EngineState,
    sample_project: Project,
    sample_workload: Workload,
) -> None:
    """Two workloads whose outputs differ from the original base's give two
    ``original base:`` violations, one each: none hides behind the other."""
    second = sample_workload.model_copy(update={"id": "w-2", "name": "eval-step"})
    two = cast(EngineState, {**state, "workloads": [sample_workload, second]})
    ctx, judged = _judged_at_tip(make_context, two, sample_project, {"W win": WIN})

    (stacked,) = _verdicts(ctx, judged, _ledger(make_context, two, ORIGIN_OUTPUT))

    assert stacked.outcome is VerdictOutcome.reject
    assert [v.message for v in stacked.violations] == [
        f"original base: workload {w.id}: output changed" for w in two["workloads"]
    ]


def test_no_origin_check_where_it_adds_nothing(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN the stack ledger set
    WHEN the round is measured at the original base itself (round one: its
         frozen judge already compared against it), the trial's outputs are
         the original base's, or the trial failed (rule 2 rejects it; its
         missing rows are a consequence, not a violation)
    THEN no ``original base:`` violation is added: each verdict is today's
    """
    ctx, judged = _judged_at_tip(make_context, state, sample_project, {"W win": WIN})
    tip = judged["baseline"]
    assert tip is not None and tip.commit == TIP
    relabelled = tip.model_copy(update={"commit": ORIGIN})  # measured "at the origin"
    at_origin = cast(EngineState, {**judged, "baseline": relabelled})
    differs = _ledger(make_context, state, ORIGIN_OUTPUT)
    same = _ledger(make_context, state, SAME)
    failed = {"F fails": _script(1.0, path=PATH, error="SyntaxError: boom")}
    fctx, fjudged = _judged_at_tip(make_context, state, sample_project, failed)

    assert _decided(ctx, at_origin, differs) == _decided(ctx, at_origin, None)
    assert _decided(ctx, judged, same) == _decided(ctx, judged, None)
    assert _decided(fctx, fjudged, differs) == _decided(fctx, fjudged, None)
    (stacked,) = _verdicts(fctx, fjudged, differs)
    assert stacked.outcome is VerdictOutcome.reject
    assert not any("original base" in v.message for v in stacked.violations)
    (kept,) = _verdicts(ctx, judged, same)
    assert (kept.outcome, kept.violations) == (VerdictOutcome.keep, ())


def test_a_checkpoint_written_before_the_stack_key_reads_as_no_ledger(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN a stacking-off run resumed from a checkpoint written before U1, so
          its state has no ``stack`` channel at all (LangGraph omits it)
    WHEN the verdicts node runs
    THEN it gives today's verdicts, as with ``stack`` None, never a KeyError
    """
    ctx, judged = _judged_at_tip(make_context, state, sample_project, {"W win": WIN})
    stored: dict[str, object] = {k: v for k, v in judged.items() if k != "stack"}
    assert "stack" not in stored and "stack" in judged

    delta = make_nodes(ctx)["verdicts"](cast(EngineState, stored))

    decided = [
        v.model_dump(exclude={"id", "decided_at"})
        for v in cast(list[Verdict], delta["verdicts"])
    ]
    assert decided == _decided(ctx, judged, None)
    assert decided[0]["outcome"] is VerdictOutcome.keep
