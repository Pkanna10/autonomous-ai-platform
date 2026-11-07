"""Near-miss compounds, the pure part (G5b, W4 folded in; D12, D22).

``evolve.find_pair`` reads this run's verdicts, trials and hypotheses and
returns at most one pair: two ``inconclusive`` verdicts whose primary gain
(the gain judge's ``JudgeResult.gain`` and ``noise_floor`` on the metric
``judges.primary_metric`` names) is positive and at least
``NEAR_MISS_FRACTION`` (0.5) of the floor, whose measured trials changed
disjoint files (case-folded), both ``efficiency``, neither a proposal nor
parked; the best by combined gain/floor ratio, ties by trial ids.
``compound_hypothesis`` turns it into a hypothesis of its own whose parents
travel in its tags (``compound_parents`` reads them back; a forged set does
not parse). No fakes: every input is a real model built here.
"""

from __future__ import annotations

import itertools

import pytest

from autonomous_ai_agents.common.models import (
    METRIC_PEAK_RSS_BYTES,
    METRIC_WALL_TIME_S,
    ChangeClass,
    Direction,
    Hypothesis,
    HypothesisSource,
    HypothesisStatus,
    JudgeOutcome,
    JudgeResult,
    Objective,
    ObjectiveKind,
    Project,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Violation,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.optimization.evolve import (
    COMPOUND_TAG,
    NEAR_MISS_FRACTION,
    PARENT_KEY,
    CompoundPair,
    NearMiss,
    ReplayRefusedError,
    compound_hypothesis,
    compound_id,
    compound_parents,
    find_pair,
    near_miss,
    primary_gain_floor,
    used_pairs,
)
from autonomous_ai_agents.optimization.idea_types import is_proposal
from autonomous_ai_agents.optimization.judges import SHADOW_JUDGES
from autonomous_ai_agents.orchestrator.serde import dump_state, load_state
from autonomous_ai_agents.orchestrator.state import initial_state

PROJECT = Project(name="lab", root_path="/srv/lab")
PRIMARY = METRIC_WALL_TIME_S
FLOOR = 0.04
Miss = tuple[Hypothesis, Trial, Verdict]


def _result(
    gain: float | None,
    floor: float | None = FLOOR,
    outcome: JudgeOutcome = JudgeOutcome.inconclusive,
    metric: str | None = PRIMARY,
    judge: str | None = None,
) -> JudgeResult:
    return JudgeResult(
        judge=judge or f"gain:{metric}", outcome=outcome, metric=metric,
        gain=gain, noise_floor=floor, reason="scripted",
    )  # fmt: skip


def _miss(
    title: str,
    paths: tuple[str, ...],
    gain: float | None,
    *,
    floor: float | None = FLOOR,
    outcome: VerdictOutcome = VerdictOutcome.inconclusive,
    results: tuple[JudgeResult, ...] | None = None,
    change_class: ChangeClass = ChangeClass.efficiency,
    verdict_class: ChangeClass | None = None,
    tags: tuple[str, ...] = (),
    commit: str | None = "c" * 40,
    status: TrialStatus = TrialStatus.measured,
    trial_violations: tuple[Violation, ...] = (),
    verdict_violations: tuple[Violation, ...] = (),
    trial_id: str | None = None,
) -> Miss:
    hypothesis = Hypothesis(
        project_id=PROJECT.id, source=HypothesisSource.novel, title=title,
        rationale="r", change_class=change_class, expected_gain=0.1,
        provability=0.6, risk=0.2, tags=tags, status=HypothesisStatus.inconclusive,
    )  # fmt: skip
    extra = {} if trial_id is None else {"id": trial_id}
    trial = Trial(
        hypothesis_id=hypothesis.id, round=1, commit=commit, touched_paths=paths,
        status=status, violations=trial_violations, **extra,
    )  # fmt: skip
    verdict = Verdict(
        trial_id=trial.id, hypothesis_id=hypothesis.id, outcome=outcome,
        change_class=verdict_class or change_class,
        judge_results=(_result(gain, floor),) if results is None else results,
        violations=verdict_violations, summary="s",
    )  # fmt: skip
    return hypothesis, trial, verdict


def _pair(*misses: Miss, parked: tuple[Hypothesis, ...] = (), **kw: object) -> CompoundPair | None:  # fmt: skip
    return find_pair(
        [m[2] for m in misses], [m[1] for m in misses], [m[0] for m in misses],
        primary=PRIMARY, parked=frozenset(h.id for h in parked), **kw,  # type: ignore[arg-type]
    )  # fmt: skip


def _a() -> Miss:
    return _miss("cache the parse", ("lib/parse.py",), 0.03)  # ratio 0.75


def _b() -> Miss:
    return _miss("hoist the lookup", ("lib/index.py",), 0.024)  # ratio 0.6


def test_two_disjoint_efficiency_near_misses_form_the_pair() -> None:
    a, b = _a(), _b()

    pair = _pair(a, b)

    assert pair is not None
    assert {pair.first.trial.id, pair.second.trial.id} == {a[1].id, b[1].id}
    assert pair.first.trial.id < pair.second.trial.id
    assert pair.ratio == pytest.approx(0.75 + 0.6)
    assert NEAR_MISS_FRACTION == 0.5


def test_a_ratio_of_exactly_half_the_floor_is_a_near_miss() -> None:
    a, edge = _a(), _miss("edge", ("lib/edge.py",), 0.02)

    pair = _pair(a, edge)

    assert pair is not None and pair.ratio == pytest.approx(0.75 + 0.5)


_SPAWN = Violation(rule=ViolationRule.process_spawn, message="spawn")
_PROTECTED = Violation(
    rule=ViolationRule.protected_path, path="tests/t.py", message="p"
)
_FAILS: dict[str, dict[str, object]] = {
    "a keep is no near miss": {"outcome": VerdictOutcome.keep},
    "a reject is no near miss": {"outcome": VerdictOutcome.reject},
    "a review is no near miss": {"outcome": VerdictOutcome.review},
    "a gain in the wrong direction": {"gain": -0.03},
    "no gain at all": {"gain": 0.0},
    "just below half the floor": {"gain": 0.0199},
    "no recorded gain": {"gain": None},
    "no recorded floor": {"floor": None},
    "a zero floor": {"floor": 0.0},
    "a behaviour hypothesis": {"change_class": ChangeClass.behaviour},
    "a behaviour verdict": {"verdict_class": ChangeClass.behaviour},
    "a novel hypothesis": {"change_class": ChangeClass.novel},
    "a proposal (its tag)": {"tags": ("proposal:new_dependency",)},
    "a proposal (its relaxing lane)": {"tags": ("lane:relax_output_order",)},
    "a trial with no commit": {"commit": None},
    "a failed trial": {"status": TrialStatus.failed},
    "a trial with a capture violation": {"trial_violations": (_SPAWN,)},
    "a verdict with a violation": {"verdict_violations": (_PROTECTED,)},
    "a trial that changed nothing": {"paths": ()},
    "a trial id no tag can carry": {"trial_id": "Trial-ID"},
    "the primary passed, a guardrail inconclusive": {"results": (
        _result(0.03, outcome=JudgeOutcome.passed),
        _result(None, None, metric=None, judge="tests"),
    )},
    "a failed judge beside the near miss": {"results": (
        _result(0.03),
        _result(None, None, JudgeOutcome.failed, metric=None, judge="equivalence"),
    )},
    "the gain is on a secondary metric only": {"results": (
        _result(0.03, metric=METRIC_PEAK_RSS_BYTES),
        _result(None, None, metric=PRIMARY),
    )},
    "a shadow judge's gain never counts": {"results": (
        _result(0.03, judge="op_count", outcome=JudgeOutcome.not_applicable),
    )},
}  # fmt: skip


@pytest.mark.parametrize("case", _FAILS)
def test_each_pair_condition_failing_on_its_own_leaves_no_pair(case: str) -> None:
    """
    GIVEN a qualifying near miss and a second one that differs in one way
    WHEN the pair finder runs
    THEN there is no pair, and the second alone is no near miss
    """
    fields = {"gain": 0.024, "paths": ("lib/index.py",), **_FAILS[case]}
    paths = fields.pop("paths")
    gain = fields.pop("gain")
    other = _miss("the other", paths, gain, **fields)  # type: ignore[arg-type]

    assert _pair(_a(), other) is None
    assert near_miss(other[2], other[1], other[0], primary=PRIMARY) is None


def test_a_parked_parent_is_no_near_miss() -> None:
    a, b = _a(), _b()

    assert _pair(a, b, parked=(b[0],)) is None
    assert near_miss(b[2], b[1], b[0], primary=PRIMARY, parked=frozenset({b[0].id})) is None  # fmt: skip


def test_no_primary_metric_means_no_near_miss() -> None:
    a, b = _a(), _b()

    assert find_pair([a[2], b[2]], [a[1], b[1]], [a[0], b[0]], primary=None) is None


@pytest.mark.parametrize(
    "paths",
    [("lib/parse.py",), ("LIB/Parse.py",), ("lib/parse.py", "lib/other.py")],
    ids=["same file", "same file case-folded", "one shared file"],
)
def test_overlapping_files_never_pair(paths: tuple[str, ...]) -> None:
    a, b = _a(), _miss("touches parse too", paths, 0.03)

    assert _pair(a, b) is None


def test_a_verdict_without_its_trial_or_hypothesis_is_skipped() -> None:
    a, b = _a(), _b()

    assert find_pair([a[2], b[2]], [a[1]], [a[0], b[0]], primary=PRIMARY) is None
    assert find_pair([a[2], b[2]], [a[1], b[1]], [a[0]], primary=PRIMARY) is None


def test_two_candidate_pairs_choose_the_best_combined_ratio() -> None:
    """
    GIVEN four near misses: A 0.75, B 0.6 and C 0.9 on disjoint files, D 1.0
          on A's file
    WHEN the finder runs, whatever the input order
    THEN it returns the best combined ratio of a disjoint pair: D + C (1.9),
         never D + A (they share a file)
    """
    a, b = _a(), _b()
    c = _miss("fuse the loops", ("lib/loop.py",), 0.036)
    d = _miss("rewrite parse", ("lib/parse.py",), 0.04 - 1e-9)

    found = {
        (p.first.trial.id, p.second.trial.id)
        for order in itertools.permutations([a, b, c, d])
        if (p := _pair(*order)) is not None
    }

    assert found == {tuple(sorted((c[1].id, d[1].id)))}


def test_a_tie_is_broken_by_the_trial_ids_whatever_the_order() -> None:
    misses = [
        _miss(
            f"idea {n}",
            (f"lib/m{n}.py",),
            0.03,
            trial_id=f"{n}0000000-0000-4000-8000-000000000000",
        )  # fmt: skip
        for n in range(1, 5)
    ]

    pairs = {(p.first.trial.id, p.second.trial.id)
             for order in itertools.permutations(misses)
             if (p := _pair(*order)) is not None}  # fmt: skip

    assert pairs == {(misses[0][1].id, misses[1][1].id)}


def test_a_used_pair_is_skipped_for_the_next_best() -> None:
    a, b = _a(), _b()
    c = _miss("fuse the loops", ("lib/loop.py",), 0.036)
    first = _pair(a, b, c)
    assert first is not None
    compound = compound_hypothesis(first)

    second = _pair(a, b, c, used=used_pairs([compound]))

    assert first.key == frozenset({a[1].id, c[1].id})
    assert second is not None and second.key == frozenset({b[1].id, c[1].id})
    assert _pair(a, b, used=used_pairs([compound_hypothesis(_pair(a, b))])) is None  # type: ignore[arg-type]


def test_one_near_miss_or_none_is_no_pair() -> None:
    assert _pair() is None
    assert _pair(_a()) is None


def test_the_compound_is_an_efficiency_hypothesis_of_its_own_never_a_proposal() -> None:
    a, b = _a(), _b()
    pair = _pair(a, b)
    assert pair is not None

    compound = compound_hypothesis(pair)

    first, second = sorted((a[1].id, b[1].id))
    assert compound.id == compound_id(first, second) == compound_id(second, first)
    assert compound.source is HypothesisSource.lesson
    assert compound.change_class is ChangeClass.efficiency
    assert compound.status is HypothesisStatus.proposed
    assert compound.tags == (COMPOUND_TAG, f"{PARENT_KEY}:{first}", f"{PARENT_KEY}:{second}")  # fmt: skip
    assert not is_proposal(compound)
    assert compound.title == "compound: cache the parse + hoist the lookup" or compound.title == "compound: hoist the lookup + cache the parse"  # fmt: skip
    assert (
        "replays" in compound.rationale and "judged from scratch" in compound.rationale
    )
    assert compound.expected_gain == pytest.approx(0.03 + 0.024)
    assert (compound.provability, compound.risk) == (0.6, 0.2)
    parents = compound_parents(compound)
    assert parents is not None and (parents.first, parents.second) == (first, second)


def test_a_long_title_is_capped() -> None:
    a = _miss("x" * 300, ("lib/a.py",), 0.03)
    b = _miss("y" * 300, ("lib/b.py",), 0.03)
    pair = _pair(a, b)
    assert pair is not None

    assert len(compound_hypothesis(pair).title) <= 200


def test_the_parents_survive_the_checkpoint_round_trip() -> None:
    pair = _pair(_a(), _b())
    assert pair is not None
    compound = compound_hypothesis(pair)
    workload = Workload(project_id=PROJECT.id, name="w", command=("python", "w.py"))
    objective = Objective(
        project_id=PROJECT.id, kind=ObjectiveKind.runtime, metric=PRIMARY,
        direction=Direction.minimize, description="d",
    )  # fmt: skip
    state = initial_state(PROJECT, [workload], [objective], [], run_id="run-g5b")
    state["hypotheses"] = [compound]

    again = load_state(dump_state(state))

    assert again["hypotheses"] == [compound]
    assert compound_parents(again["hypotheses"][0]) == compound_parents(compound)


def _forged(compound: Hypothesis, **update: object) -> Hypothesis:
    return compound.model_copy(update=update)


def test_a_forged_or_partial_compound_does_not_parse() -> None:
    """Only the engine's own record parses: the right source, the marker tag,
    exactly two distinct parents and the id derived from them."""
    pair = _pair(_a(), _b())
    assert pair is not None
    compound = compound_hypothesis(pair)
    first, second = compound.tags[1], compound.tags[2]
    other = f"{PARENT_KEY}:{'f' * 8}-0000-4000-8000-000000000000"

    forged = [
        _forged(compound, source=HypothesisSource.novel),
        _forged(compound, tags=(first, second)),
        _forged(compound, tags=(COMPOUND_TAG, first)),
        _forged(compound, tags=(COMPOUND_TAG, first, first)),
        _forged(compound, tags=(COMPOUND_TAG, first, other)),
        _forged(compound, tags=(COMPOUND_TAG, first, second, other)),
        _forged(compound, id="not-the-derived-id"),
    ]

    assert [compound_parents(h) for h in forged] == [None] * len(forged)
    assert used_pairs(forged) == frozenset()


def test_a_compound_pairs_again_only_as_a_near_miss_of_its_own() -> None:
    """
    GIVEN A + B's compound measured inconclusive at 0.8 of the floor, and C a
          near miss on a third file
    WHEN the finder runs with A + B used
    THEN the compound pairs with C (its files are A's and B's, so never with
         either parent); as a keep it pairs with nothing
    """
    a, b = _a(), _b()
    c = _miss("fuse the loops", ("lib/loop.py",), 0.036)
    ab = _pair(a, b)
    assert ab is not None
    compound = compound_hypothesis(ab)
    trial = Trial(
        hypothesis_id=compound.id, round=2, commit="d" * 40,
        touched_paths=("lib/index.py", "lib/parse.py"), status=TrialStatus.measured,
    )  # fmt: skip
    near = Verdict(
        trial_id=trial.id, hypothesis_id=compound.id,
        outcome=VerdictOutcome.inconclusive, change_class=ChangeClass.efficiency,
        judge_results=(_result(0.032),), summary="s",
    )  # fmt: skip
    kept = near.model_copy(update={"outcome": VerdictOutcome.keep})
    hypotheses = [a[0], b[0], c[0], compound]
    used = used_pairs(hypotheses)

    again = find_pair([a[2], b[2], c[2], near], [a[1], b[1], c[1], trial],
                      hypotheses, primary=PRIMARY, used=used)  # fmt: skip
    without = find_pair([a[2], b[2], kept], [a[1], b[1], trial],
                        [a[0], b[0], compound], primary=PRIMARY, used=used)  # fmt: skip

    assert again is not None and again.key == frozenset({trial.id, c[1].id})
    assert without is None


def test_a_near_miss_records_its_ratio_and_the_refusal_names_its_reason() -> None:
    a = _a()

    found = near_miss(a[2], a[1], a[0], primary=PRIMARY)
    refused = ReplayRefusedError("conflict", ("lib/parse.py",))

    assert isinstance(found, NearMiss) and found.ratio == pytest.approx(0.75)
    assert (refused.reason, refused.paths) == ("conflict", ("lib/parse.py",))
    assert str(refused) == "conflict: lib/parse.py"
    assert str(ReplayRefusedError("no commit")) == "no commit"


def test_the_primary_gain_and_floor_are_the_deciding_results_whatever_its_outcome() -> (
    None
):
    """The round seeds read a trial's ratio here (G5b), so seeds and compounds
    agree: the primary metric's deciding result, never a shadow judge's, for
    a keep or a reject as well as an inconclusive one."""
    shadow = _result(0.9, 0.01, judge=sorted(SHADOW_JUDGES)[0])
    kept = _result(0.12, 0.05, JudgeOutcome.passed)
    other = _result(0.3, 0.02, metric="peak_rss_bytes")
    assert primary_gain_floor((shadow, other, kept), PRIMARY) == (0.12, 0.05)
    assert primary_gain_floor((other,), PRIMARY) == (None, None)
    assert primary_gain_floor((kept,), None) == (None, None)
