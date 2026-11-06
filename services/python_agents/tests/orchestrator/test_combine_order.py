"""S2 (emergence round 1): combine record and delivery by confirmed gain.

``plan_delivery`` reads a dry merge (``DryMerge``: the conflicting pairs and
each keep's diff) and the keeps' order gains (``order_gain``: both looks'
mean, the first look when confirmation was skipped). Hunk-identical keeps
are one node, the highest gain its representative; each conflict component
gets its max-sum conflict-free subset (exact up to ``EXACT_MAX`` nodes,
greedy by gain above). ``record`` keeps today's score order and only
records; ``on`` offers each component's subset first, by gain. The greedy
merge, the tip re-test, the frozen verdict and the fallback are unchanged:
``combine_kept`` only names the applied keep that blocked a skip, and
``keep_records`` writes one ``KeepRecord`` per keep. The combine node does
all of this only when its combiner is a ``ConflictProbe`` whose
``site_stacks`` is not ``off``.

Fakes: ``ProbeCombiner`` (``FakeCombiner`` plus a scripted dry merge) stands
for ``GitCombiner``; the stub runners and ``make_context`` are conftest's.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.config import SiteStacks
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    ChangeClass,
    Combination,
    CombineSkip,
    Guardrail,
    Hypothesis,
    KeepRecord,
    Measurement,
    Objective,
    Project,
    RunStats,
    Trial,
    Verdict,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.combine import DryMerge
from autonomous_ai_agents.execution.fakes import FakeCombiner
from autonomous_ai_agents.execution.protocols import CombineMeasured, KeptChange
from autonomous_ai_agents.orchestrator.combine_node import (
    EXACT_MAX,
    CombineOutcome,
    ConflictProbe,
    keep_records,
    order_gain,
    plan_delivery,
)
from autonomous_ai_agents.orchestrator.nodes import LOOP_NODES, make_nodes
from autonomous_ai_agents.orchestrator.state import (
    REDUCER_KEYS,
    EngineState,
    initial_state,
)

SHA, TIP = "a" * 40, "b" * 40
DIFF = (
    "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -{n} +{n} @@\n-x\n+{text}\n"
)


def change(name: str, score: float = 0.5) -> KeptChange:
    return KeptChange(
        name, f"h-{name}", f"v-{name}", f"{ord(name[0]):040x}", score, 0.01
    )


def dry(
    pairs: Iterable[Iterable[str]], diffs: Mapping[str, str] | None = None
) -> DryMerge:
    return DryMerge(frozenset(frozenset(p) for p in pairs), dict(diffs or {}))


def _ids(changes: Sequence[KeptChange]) -> list[str]:
    return [c.trial_id for c in changes]


# ---------------------------------------------------------------------------
# The order key
# ---------------------------------------------------------------------------


def _verdict(gain: float | None, confirmed: float | None) -> Verdict:
    return Verdict(trial_id="t", hypothesis_id="h", outcome=VerdictOutcome.keep,
                   change_class=ChangeClass.efficiency, gain=gain,
                   confirmed_gain=confirmed, confirmations=1 + (confirmed is not None),
                   summary="keep")  # fmt: skip


def test_the_order_gain_is_both_looks_mean_or_the_first_look() -> None:
    assert order_gain(_verdict(0.10, 0.20)) == pytest.approx(0.15)
    assert order_gain(_verdict(0.10, None)) == 0.10  # confirmation skipped
    assert order_gain(_verdict(None, None)) is None


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def test_on_delivers_the_larger_gain_where_the_score_put_it_second() -> None:
    """
    GIVEN keeps a (score 0.9, gain 4 %) and b (score 0.1, gain 9 %) that
        conflict
    WHEN the delivery is planned
    THEN ``on`` offers b first; ``record`` keeps a first (today's order) and
        still marks b as its component's best subset
    """
    changes = [change("a", 0.9), change("b", 0.1)]
    gains = {"a": 0.04, "b": 0.09}

    on = plan_delivery(changes, gains, dry(["ab"]), by_gain=True)
    record = plan_delivery(changes, gains, dry(["ab"]), by_gain=False)

    assert _ids(on.order) == ["b", "a"]
    assert _ids(record.order) == ["a", "b"]
    assert on.best == record.best == frozenset({"b"})
    assert on.component == {"b": 0, "a": 0}


def test_the_exact_subset_beats_greedy_by_gain() -> None:
    """
    GIVEN a 3-node component: a 10 % conflicts with b 6 % and with c 6 %,
        b and c merge; and a lone d 1 %, a gain-less e
    WHEN the delivery is planned with ``on``
    THEN b and c (12 % in all) go first, then d and e, a last
    """
    changes = [change(n) for n in "abcde"]
    gains = {"a": 0.10, "b": 0.06, "c": 0.06, "d": 0.01, "e": None}

    plan = plan_delivery(changes, gains, dry(["ab", "ac"]), by_gain=True)

    assert plan.best == frozenset({"b", "c", "d", "e"})
    assert _ids(plan.order) == ["b", "c", "d", "e", "a"]
    assert plan.component == {"a": 0, "b": 0, "c": 0, "d": 1, "e": 2}


def test_above_the_exact_cap_the_subset_is_greedy_by_gain() -> None:
    """A star of one 10 % keep against EXACT_MAX 2 % leaves (their sum is
    larger): over the cap the greedy takes the centre alone."""
    leaves = [f"l{n}" for n in range(EXACT_MAX)]
    changes = [change("x"), *(change(n) for n in leaves)]
    gains = {"x": 0.10, **dict.fromkeys(leaves, 0.02)}

    plan = plan_delivery(changes, gains, dry([("x", n) for n in leaves]), by_gain=True)

    assert plan.best == frozenset({"x"})
    assert _ids(plan.order)[0] == "x"


def test_hunk_identical_keeps_are_one_node_and_never_a_conflict_pair() -> None:
    """
    GIVEN a (5 %) and d (8 %) with one change (whitespace apart), b another
        change of the same line that conflicts with both
    WHEN the delivery is planned
    THEN a is ``duplicate_of`` d, the pair is one node of b's component, d
        beats b, and a is offered last
    """
    diffs = {"a": DIFF.format(n=3, text="y = 1"), "d": DIFF.format(n=3, text="y  =  1"),
             "b": DIFF.format(n=3, text="y = 2")}  # fmt: skip
    changes = [change("a", 0.9), change("b"), change("d", 0.1)]
    gains = {"a": 0.05, "b": 0.07, "d": 0.08}

    plan = plan_delivery(changes, gains, dry(["ab", "bd"], diffs), by_gain=True)

    assert plan.duplicate_of == {"a": "d"}
    assert plan.best == frozenset({"d"})
    assert _ids(plan.order) == ["d", "b", "a"]
    assert plan.component == {"d": 0, "b": 0, "a": 0}


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


def _outcome(applied: Sequence[str], skipped: Sequence[CombineSkip], *, holds: bool,
             fallback: str | None = None, kept: Sequence[str] = ()) -> CombineOutcome:  # fmt: skip
    combination = Combination(base_commit=SHA, tip_commit=TIP, applied_trial_ids=tuple(applied),
                              skipped=tuple(skipped), holds=holds,
                              fallback_trial_id=fallback, summary="s")  # fmt: skip
    return CombineOutcome(tuple(f"v-{k}" for k in kept), combination)


def test_every_keep_records_whether_it_was_delivered_and_why_not() -> None:
    """
    GIVEN a held combine of b and c; a skipped as a conflict blocked by b; d
        a whitespace variant of c, so git conflicts it with c (blocked by c)
    WHEN the keeps are recorded
    THEN each keep has one record: b and c delivered, a with its reason, its
        blocker and part 3's eligibility, d with its reason, its blocker and
        its duplicate, and a duplicate is never offered for a reconcile
    """
    diffs = {
        "c": DIFF.format(n=9, text="z = 1"),
        "d": DIFF.format(n=9, text="z  =  1 "),
    }
    changes = [change(n) for n in "abcd"]
    plan = plan_delivery(changes, {"a": 0.06, "b": 0.1, "c": 0.06, "d": 0.01},
                         dry(["ab", "cd"], diffs), by_gain=True)  # fmt: skip
    skips = [CombineSkip(trial_id="a", reason="conflict", paths=("m.py",), blocked_by="b"),
             CombineSkip(trial_id="d", reason="conflict", paths=("m.py",), blocked_by="c")]  # fmt: skip
    trials = {n: Trial(id=n, hypothesis_id=f"h-{n}", round=1) for n in "abcd"}

    out = keep_records(plan, _outcome(["b", "c"], skips, holds=True, kept="bc"), trials)

    records = {k.trial_id: k for k in out.combination.keeps}
    assert [k.trial_id for k in out.combination.keeps] == _ids(plan.order)
    assert out.combination.conflicts == (("a", "b"), ("c", "d"))
    assert records["a"] == KeepRecord(
        trial_id="a", verdict_id="v-a", gain=0.06, component=0, best_subset=False,
        delivered=False, skip_reason="conflict", blocked_by="b",
        reconcile="ineligible: uncounted (no unit rows)",
    )  # fmt: skip
    assert records["b"].delivered and records["b"].skip_reason is None
    assert records["d"].duplicate_of == records["d"].blocked_by == "c"
    assert records["d"].skip_reason == "conflict" and records["d"].reconcile is None
    assert records["d"].component == records["c"].component
    assert records["c"].superseded_by is None  # part 3 trials none


def test_a_keep_lost_with_the_combination_says_so() -> None:
    changes = [change("a"), change("b")]
    plan = plan_delivery(changes, {"a": 0.1, "b": 0.05}, dry([]), by_gain=True)
    trials = {n: Trial(id=n, hypothesis_id=f"h-{n}", round=1) for n in "ab"}

    held = keep_records(
        plan, _outcome(["a"], [], holds=True, fallback="a", kept="a"), trials
    )
    lost = keep_records(plan, _outcome(["a"], [], holds=False, fallback="a"), trials)
    none = keep_records(plan, _outcome([], [], holds=False), trials)

    why = {k.trial_id: k.skip_reason for k in held.combination.keeps}
    assert why == {"a": None, "b": "the combination did not hold; the fallback "
                   "re-tested trial a alone"}  # fmt: skip
    assert [k.skip_reason for k in lost.combination.keeps] == [
        "the combination did not hold, nor this change alone",
        "the combination did not hold; the fallback re-tested trial a alone",
    ]
    assert {k.skip_reason for k in none.combination.keeps} == {
        "the combination did not hold"
    }


# ---------------------------------------------------------------------------
# The combine node
# ---------------------------------------------------------------------------


class ProbeCombiner(FakeCombiner):
    """``FakeCombiner`` with a mode and a scripted dry merge (``GitCombiner``)."""

    def __init__(self, results: Sequence[CombineMeasured], site_stacks: SiteStacks,
                 pairs: Sequence[tuple[str, str]] = ()) -> None:  # fmt: skip
        super().__init__(results)
        self.site_stacks: SiteStacks = site_stacks
        self.pairs = pairs
        self.dry: list[tuple[str, ...]] = []

    def dry_merge(self, project: Project, base_commit: str,
                  kept: Sequence[KeptChange]) -> DryMerge:  # fmt: skip
        self.dry.append(tuple(c.trial_id for c in kept))
        names = {c.hypothesis_id: c.trial_id for c in kept}
        return dry([(names[a], names[b]) for a, b in self.pairs])


def _apply(state: EngineState, delta: Mapping[str, object]) -> EngineState:
    merged: dict[str, Any] = dict(state)
    for key, value in delta.items():
        merged[key] = [*merged[key], *cast(list[Any], value)] if key in REDUCER_KEYS else value  # fmt: skip
    return cast(EngineState, merged)


def _rows(workload: str, wall: Sequence[float], tests: bool) -> tuple[Measurement, ...]:
    def row(metric: str, samples: Sequence[float], unit: str) -> Measurement:
        return Measurement(workload_id=workload, metric=metric, samples=tuple(samples),
                           stats=RunStats.from_samples(tuple(samples), unit=unit))  # fmt: skip

    out = [row(METRIC_WALL_TIME_S, wall, "s"), row("val_loss", (0.5,) * 5, "")]
    return (*out, row(METRIC_TESTS_PASSED, (1.0,), "bool")) if tests else tuple(out)


@pytest.fixture
def base_state(sample_project: Project, sample_workload: Workload,
               sample_objective: Objective,
               sample_guardrails: tuple[Guardrail, ...]) -> EngineState:  # fmt: skip
    return initial_state(sample_project, [sample_workload], [sample_objective],
                         sample_guardrails, run_id="run-s2", max_rounds=3)  # fmt: skip


@pytest.fixture
def before_combine(make_context: Any, base_state: EngineState,
                   h1_cache: Hypothesis) -> tuple[EngineState, list[Hypothesis]]:  # fmt: skip
    """Two keeps: hyp-a (score 0.9, gain 4 %, confirmed 6 %) and hyp-b
    (score 0.1, gain 9 %, its confirmation skipped), every trial committed."""
    hyps = [h1_cache.model_copy(update={"id": n}) for n in ("hyp-a", "hyp-b")]
    nodes = make_nodes(make_context(hyps, max_hypotheses_per_round=2))
    state = base_state
    for name in LOOP_NODES:
        state = _apply(state, nodes[name](state))
    looks = {"hyp-a": (0.04, 0.06, 2), "hyp-b": (0.09, None, 1)}
    state["verdicts"] = [v.model_copy(update=dict(zip(("gain", "confirmed_gain", "confirmations"),
                         looks[v.hypothesis_id], strict=True))) for v in state["verdicts"]]  # fmt: skip
    state["hypotheses"] = [h.model_copy(update={"score": 0.9 if h.id == "hyp-a" else 0.1})
                           for h in state["hypotheses"]]  # fmt: skip
    state["trials"] = [t.model_copy(update={"commit": f"{n + 1:040x}"})
                       for n, t in enumerate(state["trials"])]  # fmt: skip
    state["base_commit"] = SHA
    assert all(v.outcome is VerdictOutcome.keep for v in state["verdicts"])
    return state, hyps


def _run(make_context: Any, state: EngineState, hyps: list[Hypothesis], workload: Workload,
         mode: SiteStacks) -> tuple[ProbeCombiner, Mapping[str, Any]]:  # fmt: skip
    trial = {t.hypothesis_id: t.id for t in state["trials"]}
    measured = CombineMeasured(TIP, (trial["hyp-b"],),
                               (CombineSkip(trial_id=trial["hyp-a"], reason="conflict"),),
                               _rows(workload.id, (1.8,) * 5, False),
                               _rows(workload.id, (1.05,) * 5, True))  # fmt: skip
    combiner = ProbeCombiner([measured], mode, [("hyp-a", "hyp-b")])
    delta = make_nodes(make_context(hyps, combiner=combiner))["combine"](state)
    return combiner, cast(Mapping[str, Any], delta)


def test_on_offers_the_confirmed_larger_gain_first_and_records_the_blocker(
    make_context: Any, before_combine: tuple[EngineState, list[Hypothesis]],
    sample_workload: Workload,
) -> None:  # fmt: skip
    """
    GIVEN hyp-a ahead by score, hyp-b ahead by gain with its confirmation
        skipped, the two conflicting
    WHEN combine runs with ``on``
    THEN hyp-b is offered first, the skip names hyp-b's trial as the
        blocker, and every keep and the event carry the record
    """
    state, hyps = before_combine
    trial = {t.hypothesis_id: t.id for t in state["trials"]}

    combiner, delta = _run(make_context, state, hyps, sample_workload, "on")

    assert isinstance(combiner, ConflictProbe)
    assert [c.hypothesis_id for c in combiner.calls[0].kept] == ["hyp-b", "hyp-a"]
    combination = delta["combination"]
    assert combination.skipped[0].blocked_by == trial["hyp-b"]
    assert [(k.trial_id, k.delivered) for k in combination.keeps] == [
        (trial["hyp-b"], True), (trial["hyp-a"], False)]  # fmt: skip
    assert combination.keeps[1].gain == pytest.approx(0.05)
    event = next(e for e in delta["events"] if "applied" in e.data)
    assert event.data["site_stacks"] == "on"
    assert event.data["skips"] == f"{trial['hyp-a'][:8]}: conflict, blocked by {trial['hyp-b'][:8]}"  # fmt: skip


def test_record_keeps_the_score_order_and_off_never_dry_merges(
    make_context: Any, before_combine: tuple[EngineState, list[Hypothesis]],
    sample_workload: Workload,
) -> None:  # fmt: skip
    state, hyps = before_combine

    record, recorded = _run(make_context, state, hyps, sample_workload, "record")
    off, plain = _run(make_context, state, hyps, sample_workload, "off")

    assert [c.hypothesis_id for c in record.calls[0].kept] == ["hyp-a", "hyp-b"]
    assert [k.best_subset for k in recorded["combination"].keeps] == [False, True]
    assert [c.hypothesis_id for c in off.calls[0].kept] == ["hyp-a", "hyp-b"]
    assert off.dry == [] and plain["combination"].keeps == ()
    assert plain["combination"].skipped[0].blocked_by is None
    event = next(e for e in plain["events"] if "applied" in e.data)
    assert "skips" not in event.data and "site_stacks" not in event.data
