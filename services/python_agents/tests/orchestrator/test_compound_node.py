"""Near-miss compounds in the loop (G5b, W4 folded in; D12, D22).

With ``near_miss_compounds`` on (``NEAR_MISS_COMPOUNDS``, off by default),
after a round's verdicts the router sends the run back to ``hypotheses``
while ``evolve.find_pair`` finds a pair of this run's near misses not
compounded yet; that node adds the pair's compound as a hypothesis of its
own (at most one a round, ahead of the round's ideas), and the trials node
asks the runner to replay its parents' measured trials instead of editing
(no fix retry). The compound is judged from its own measurements under the
same judges and anti-cheat as any trial, counted in the round's progress
and cost. A refused replay (a conflict) is no trial: a warning note, the
hypothesis rejected, never retried. Off, nothing changes (golden).

Swap points: ``Replayer`` stands for ``GitTrialRunner``: its ``run`` is the
conftest's ``StubTrialRunner`` (scripted by title) plus a commit, its
``replay`` returns the scripted compound outcome on the union of the
parents' files, or raises the refusal a conflict raises. The graph is the
real one on ``build_checkpointer``; the repository is ``InMemoryRepository``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    Baseline,
    ChangeClass,
    EngineEvent,
    Guardrail,
    Hypothesis,
    HypothesisSource,
    HypothesisStatus,
    Objective,
    Project,
    RunPhase,
    Trial,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.protocols import TrialBrief
from autonomous_ai_agents.execution.runner import ScriptedOutcome, StubTrialRunner
from autonomous_ai_agents.optimization.anticheat import fingerprint
from autonomous_ai_agents.optimization.evolve import (
    ReplayRefusedError,
    compound_id,
    compound_parents,
)
from autonomous_ai_agents.orchestrator.main import EngineGraph, run_config
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    NodeDelta,
    ReplayRunner,
    make_nodes,
    make_router,
)
from autonomous_ai_agents.orchestrator.serde import dump_state, load_state
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state
from autonomous_ai_agents.persistence.repository import InMemoryRepository

ContextFactory = Callable[..., NodeContext]
GraphFactory = Callable[..., EngineGraph]
VAL_LOSS, BASELINE_FINGERPRINT = "val_loss", fingerprint("baseline")  # the conftest's


def _script(
    *wall: float, cost: float = 0.05, path: str | None = None
) -> ScriptedOutcome:
    return ScriptedOutcome(
        touched_paths=() if path is None else (path,),
        samples={METRIC_WALL_TIME_S: wall, VAL_LOSS: (0.500,) * 5},
        output_fingerprint=BASELINE_FINGERPRINT, tests_passed=True,
        cost_usd=cost, tokens_used=1000,
    )  # fmt: skip


# Baseline 1.80 s (stdev 0.035): the floor is 0.0707 s, 3.93 %.
NEAR = {
    "N1 cache the parse": _script(1.75, 1.72, 1.78, 1.75, 1.75, path="lib/parse.py"),  # 0.71
    "N2 hoist the lookup": _script(1.76, 1.73, 1.79, 1.76, 1.76, path="lib/index.py"),  # 0.57
    "N0 fuse the loops": _script(1.755, 1.725, 1.785, 1.755, 1.755, path="lib/loop.py"),  # 0.64
}  # fmt: skip
WIN = _script(1.60, 1.58, 1.62, 1.60, 1.60, cost=0.0)
CLOSE = _script(1.74, 1.71, 1.77, 1.74, 1.74, cost=0.0)  # inconclusive, 0.85
FLAT = _script(1.80, 1.75, 1.85, 1.80, 1.80, cost=0.0)  # no gain at all


class Replayer(StubTrialRunner):
    """``StubTrialRunner`` whose trials carry a commit, plus ``replay``."""

    def __init__(
        self, scripts: dict[str, ScriptedOutcome], compound: ScriptedOutcome = WIN,
        *, conflict: bool = False,
    ) -> None:  # fmt: skip
        super().__init__(scripts)
        self.compound, self.conflict = compound, conflict
        self.replays: list[tuple[str, tuple[str, ...], int, int]] = []

    def run(self, hypothesis: Hypothesis, workloads: Sequence[Workload],
            baseline: Baseline, **kwargs: Any) -> Trial:  # fmt: skip
        trial = super().run(hypothesis, workloads, baseline, **kwargs)
        commit = hashlib.sha1(trial.id.encode()).hexdigest()  # noqa: S324 - a fake id
        return trial.model_copy(update={"commit": commit})

    def replay(
        self, hypothesis: Hypothesis, parents: Sequence[Trial],
        workloads: Sequence[Workload], baseline: Baseline, *, round: int,
        branch: str, budget_usd: float, brief: TrialBrief,
    ) -> Trial:  # fmt: skip
        self.replays.append(
            (hypothesis.id, tuple(p.id for p in parents), round, brief.fix_retries_left)
        )
        if self.conflict:
            raise ReplayRefusedError("conflict", ("lib/parse.py",))
        paths = tuple(sorted({p for parent in parents for p in parent.touched_paths}))
        inner = StubTrialRunner({}, default=self.compound)
        trial = inner.run(
            hypothesis, workloads, baseline, round=round, branch=branch,
            budget_usd=budget_usd, brief=brief,
        )  # fmt: skip
        return trial.model_copy(update={"touched_paths": paths, "commit": "f" * 40})


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
    return initial_state(
        sample_project, [sample_workload], [sample_objective], sample_guardrails,
        run_id="run-g5b", max_rounds=3, max_cost_usd=10.0,
    )  # fmt: skip


def _ideas(project: Project, *titles: str) -> list[Hypothesis]:
    return [_idea(project, title) for title in titles]


def _graph_run(
    make_context: ContextFactory, engine_graph: GraphFactory, state: EngineState,
    ideas: Sequence[Hypothesis], runner: StubTrialRunner, **ctx: Any,
) -> tuple[EngineState, EngineGraph]:  # fmt: skip
    context = make_context(ideas, runner=runner, max_hypotheses_per_round=3, **ctx)
    graph = engine_graph(context)
    final = graph.invoke(state, run_config("run-g5b", 3), version="v2").value
    return final, graph


def _codes(events: Sequence[EngineEvent]) -> list[object]:
    return [e.data.get("code") for e in events if "code" in e.data]


def test_two_near_misses_are_replayed_as_one_compound_judged_on_its_own(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    state: EngineState,
    sample_project: Project,
    in_memory_repo: InMemoryRepository,
) -> None:
    """
    GIVEN two caller ideas that end inconclusive at 0.71 and 0.57 of the
          floor on disjoint files, nothing else to try, compounds on
    WHEN the run completes
    THEN round 2 replays their compound (no editor run, no fix retry, no
         spend); it is judged from its own measurements and kept, saved,
         counted in round 2's progress; its parents are recorded in its tags
         through the checkpoint; the parents stay inconclusive
    """
    n1, n2 = _ideas(sample_project, "N1 cache the parse", "N2 hoist the lookup")
    runner = Replayer({k: NEAR[k] for k in (n1.title, n2.title)})

    final, graph = _graph_run(make_context, engine_graph, state, [n1, n2], runner,
                              near_miss_compounds=True)  # fmt: skip

    t1, t2 = final["trials"][:2]
    first, second = sorted((t1.id, t2.id))
    cid = compound_id(first, second)
    assert runner.calls == [(n1.id, 1), (n2.id, 1)]
    assert runner.replays == [(cid, (first, second), 2, 0)]
    assert [v.outcome for v in final["verdicts"]] == [
        VerdictOutcome.inconclusive, VerdictOutcome.inconclusive, VerdictOutcome.keep,
    ]  # fmt: skip
    compound_trial = final["trials"][2]
    verdict = final["verdicts"][2]
    assert (compound_trial.hypothesis_id, verdict.hypothesis_id) == (cid, cid)
    assert verdict.gain == pytest.approx(0.2 / 1.8)
    assert {m.trial_id for m in compound_trial.measurements} == {compound_trial.id}
    assert final["kept_verdict_ids"] == [verdict.id]
    assert compound_trial.id in {t.id for t in in_memory_repo.list_trials("run-g5b")}
    compound = next(h for h in final["hypotheses"] if h.id == cid)
    assert compound.status is HypothesisStatus.kept
    assert compound.change_class is ChangeClass.efficiency
    parents = compound_parents(compound)
    assert parents is not None and (parents.first, parents.second) == (first, second)
    stored = cast(list[Hypothesis], graph.get_state(run_config("run-g5b", 3)).values["hypotheses"])  # fmt: skip
    assert compound_parents(next(h for h in stored if h.id == cid)) == parents
    assert final["cost_usd"] == pytest.approx(0.10)
    progress = [e for e in final["events"] if e.phase is RunPhase.trials and "trials" in e.data]  # fmt: skip
    assert [e.data["trials"] for e in progress] == [2, 1]
    notes = [e for e in final["events"] if e.data.get("code") == "compound"]
    assert len(notes) == 1 and notes[0].data["parents"] == f"{first},{second}"
    assert "replays their measured commits" in notes[0].message


def test_its_verdict_comes_from_its_own_measurements(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    state: EngineState,
    sample_project: Project,
) -> None:
    """Parents summing to 1.28 of the floor prove nothing: a compound that
    measures no gain is inconclusive, never kept on its parents' numbers."""
    n1, n2 = _ideas(sample_project, "N1 cache the parse", "N2 hoist the lookup")
    runner = Replayer({k: NEAR[k] for k in (n1.title, n2.title)}, compound=FLAT)

    final, _ = _graph_run(make_context, engine_graph, state, [n1, n2], runner,
                          near_miss_compounds=True)  # fmt: skip

    assert len(runner.replays) == 1
    assert [v.outcome for v in final["verdicts"]] == [VerdictOutcome.inconclusive] * 3
    assert final["kept_verdict_ids"] == []


def test_at_most_one_compound_a_round_the_best_pair_first(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    state: EngineState,
    sample_project: Project,
) -> None:
    """
    GIVEN three near misses (0.71, 0.57, 0.64) whose compound measures 0.85
    WHEN the run completes over three rounds
    THEN round 2 replays N1 + N0 (the best, 1.35) alone; round 3 replays
         one compound again: the round-2 compound, itself a near miss, with
         N2 (its files are N1's and N0's, so never with either)
    """
    ideas = _ideas(sample_project, *NEAR)
    runner = Replayer(dict(NEAR), compound=CLOSE)

    final, _ = _graph_run(make_context, engine_graph, state, ideas, runner,
                          near_miss_compounds=True)  # fmt: skip

    by_title = {h.title: h.id for h in ideas}
    trial_of = {t.hypothesis_id: t.id for t in final["trials"]}
    n1, n2, n0 = (trial_of[by_title[t]] for t in NEAR)
    assert [(r[2], r[1]) for r in runner.replays] == [
        (2, tuple(sorted((n1, n0)))),
        (3, tuple(sorted((trial_of[compound_id(n1, n0)], n2)))),
    ]
    per_round = [e.data["round"] for e in final["events"] if e.data.get("code") == "compound"]  # fmt: skip
    assert per_round == [2, 3]


def test_a_conflict_is_no_compound_but_a_note_and_never_retried(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    state: EngineState,
    sample_project: Project,
) -> None:
    n1, n2 = _ideas(sample_project, "N1 cache the parse", "N2 hoist the lookup")
    runner = Replayer({k: NEAR[k] for k in (n1.title, n2.title)}, conflict=True)

    final, _ = _graph_run(make_context, engine_graph, state, [n1, n2], runner,
                          near_miss_compounds=True)  # fmt: skip

    assert len(runner.replays) == 1 and len(final["trials"]) == 2
    assert len(final["verdicts"]) == 2
    (note,) = [e for e in final["events"] if e.data.get("code") == "compound_refused"]
    assert note.level.value == "warning" and note.data["reason"] == "conflict"
    assert "conflict: lib/parse.py" in note.message
    (compound,) = [h for h in final["hypotheses"] if compound_parents(h) is not None]
    assert compound.status is HypothesisStatus.rejected
    assert final["delivery"] is not None


GOLDEN = [  # recorded at HEAD before G5b (the pre-G5b nodes.py)
    ("connect", "connected bridge"),
    ("understand", "understanding bridge (stub: no LLM call in Step 1)"),
    ("define", "objectives: wall_time_s; guardrails: tests_pass, metric_bound"),
    ("baseline", "Baseline: wall_time_s mean 1.800 s over 5 run(s) on 1 workload(s)"),
    ("baseline", "noisy_host: workload train-step: CV 2.0%, smallest provable gain 3.9%"),
    ("profile", "profiled 0 hotspot(s) (stub)"),
    ("research", "research (blind): 0 technique(s), 0 paper(s)"),
    ("hypotheses", "round 1: ranked 2 of 2 candidates"),
    ("trials", "round 1: ran 2 trial(s), 0 failed"),
    ("judges", "round 1: judged 2 trial(s) with 4 judge(s)"),
    ("verdicts", "round 1: 2 verdict(s): 0 keep, 0 reject, 2 inconclusive, 0 need approval, 0 to review"),
    ("combine", "combined 0 kept change(s) (re-testing the combination is Step 2)"),
    ("deliver", "nothing kept: delivering the report only"),
    ("learn", "learned 2 lesson(s)"),
    ("watch", "watching for new papers and code changes (stub)"),
]  # fmt: skip


def test_off_by_default_changes_no_state_event_or_request(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    state: EngineState,
    sample_project: Project,
) -> None:
    """
    GIVEN the two near misses and a runner that can replay, compounds left
          at their default (off)
    WHEN the run completes
    THEN the runner is asked exactly what it was asked before G5b, nothing
         is replayed, and the events (phase, message) and the trials and
         verdicts are the pre-G5b run's, compared with an explicit off
    """
    n1, n2 = _ideas(sample_project, "N1 cache the parse", "N2 hoist the lookup")
    scripts = {k: NEAR[k] for k in (n1.title, n2.title)}
    default, explicit = Replayer(dict(scripts)), Replayer(dict(scripts))

    final, _ = _graph_run(make_context, engine_graph, dict(state), [n1, n2], default)  # type: ignore[arg-type]
    again, _ = _graph_run(make_context, engine_graph, dict(state), [n1, n2], explicit,  # type: ignore[arg-type]
                          near_miss_compounds=False)  # fmt: skip

    shape = [(e.phase.value, e.message) for e in final["events"]]
    assert default.calls == [(n1.id, 1), (n2.id, 1)] == explicit.calls
    assert default.replays == [] == explicit.replays
    assert shape == [(e.phase.value, e.message) for e in again["events"]]
    assert [m for _, m in shape if "compound" in m] == []
    assert shape == GOLDEN
    assert [h.id for h in final["hypotheses"]] == [n1.id, n2.id]
    assert [v.outcome for v in final["verdicts"]] == [VerdictOutcome.inconclusive] * 2


def test_a_runner_that_cannot_replay_is_refused_at_construction(
    make_context: ContextFactory,
) -> None:
    with pytest.raises(ValueError, match="near_miss_compounds needs a runner"):
        make_context(near_miss_compounds=True)
    assert isinstance(Replayer({}), ReplayRunner)
    assert make_context().near_miss_compounds is False


def _apply(state: EngineState, delta: NodeDelta) -> EngineState:
    merged: dict[str, Any] = dict(state)
    for key, value in delta.items():
        reducer = key in ("events", "trials", "verdicts", "lessons")
        merged[key] = [*merged[key], *cast(list[Any], value)] if reducer else value
    return cast(EngineState, merged)


def _round_one(ctx: NodeContext, state: EngineState) -> EngineState:
    nodes = make_nodes(ctx)
    for name in ("connect", "understand", "define", "baseline", "profile",
                 "research", "hypotheses", "trials", "judges", "verdicts"):  # fmt: skip
        state = _apply(state, nodes[name](state))
    return state


@pytest.mark.parametrize(
    ("on", "round_", "budget", "expected"),
    [
        (True, 1, False, "hypotheses"),
        (True, 3, False, "combine"),
        (True, 1, True, "combine"),
        (False, 1, False, "combine"),
    ],
    ids=["a pair waits", "the last round", "budget exhausted", "off"],
)
def test_the_router_waits_for_a_pair_only_while_a_round_is_left(
    make_context: ContextFactory,
    state: EngineState,
    sample_project: Project,
    on: bool,
    round_: int,
    budget: bool,
    expected: str,
) -> None:
    n1, n2 = _ideas(sample_project, "N1 cache the parse", "N2 hoist the lookup")
    runner = Replayer({k: NEAR[k] for k in (n1.title, n2.title)})
    ctx = make_context([n1, n2], runner=runner, near_miss_compounds=on)
    after = _round_one(ctx, state)
    after["round"], after["budget_exhausted"] = round_, budget

    assert make_router(ctx)(after) == expected


def test_a_compound_left_proposed_runs_only_while_compounds_are_on(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """A compound in the checkpoint with compounds now off (a resume with
    another setting) is refused, not edited; one whose parent trial is not in
    the run is refused too."""
    n1, n2 = _ideas(sample_project, "N1 cache the parse", "N2 hoist the lookup")
    runner = Replayer({k: NEAR[k] for k in (n1.title, n2.title)})
    on = make_context([n1, n2], runner=runner, near_miss_compounds=True)
    after = _round_one(on, state)
    with_compound = _apply(after, make_nodes(on)["hypotheses"](after))
    (compound,) = [h for h in with_compound["hypotheses"] if compound_parents(h)]
    off = make_context([n1, n2], runner=runner)
    orphan = dict(with_compound)
    orphan["trials"] = []

    refused_off = make_nodes(off)["trials"](with_compound)
    refused_orphan = make_nodes(on)["trials"](cast(EngineState, orphan))

    for delta, reason in ((refused_off, "near-miss compounds are off"),
                          (refused_orphan, "is not in this run")):  # fmt: skip
        assert delta["round_trials"] == []
        (note,) = [e for e in cast(list[EngineEvent], delta["events"]) if e.data.get("code") == "compound_refused"]  # fmt: skip
        assert reason in str(note.data["reason"])
        statuses = {h.id: h.status for h in cast(list[Hypothesis], delta["hypotheses"])}
        assert statuses[compound.id] is HypothesisStatus.rejected
    assert runner.replays == []


def test_the_compound_survives_a_serde_round_trip_mid_run(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    n1, n2 = _ideas(sample_project, "N1 cache the parse", "N2 hoist the lookup")
    runner = Replayer({k: NEAR[k] for k in (n1.title, n2.title)})
    ctx = make_context([n1, n2], runner=runner, near_miss_compounds=True)
    after = _round_one(ctx, state)
    planned = _apply(after, make_nodes(ctx)["hypotheses"](after))

    again = load_state(dump_state(planned))
    delta = make_nodes(ctx)["trials"](again)

    (trial,) = cast(list[Trial], delta["round_trials"])
    assert compound_parents(next(h for h in again["hypotheses"] if h.id == trial.hypothesis_id))  # fmt: skip
    assert len(runner.replays) == 1
