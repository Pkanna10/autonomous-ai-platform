"""The run's fix-retry cap in the trials node (Step 3, U16; D12, O8).

Swap point: ``_Retrying`` stands for ``GitTrialRunner``'s retry rule
(``execution/trial_runner.py``, ``_retry``) and its id rule (``trial_id_for``,
so a re-executed round rebuilds the same id): a planned round's trials crash
with a fixable error and retry only while ``attempts - 1 <
brief.fix_retries_left``; a planned number is a runner ignoring its
allowance. Everything else is the conftest's stubs; ``engine_graph`` with a
shared ``build_checkpointer()`` stands for a resumed process.

Residual (documented, not built): a trial lost after its retry request (an
engine error or a failed save) is not recorded, so resuming such a failed run
directly through the graph could grant one more retry. Orchestrator refuses to
resume a failed run; any later resume path must first record the grant durably.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, cast

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver

from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    Baseline,
    EngineEvent,
    EventLevel,
    Guardrail,
    Hypothesis,
    Objective,
    Project,
    RunPhase,
    Trial,
    TrialStatus,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.protocols import TrialBrief
from autonomous_ai_agents.execution.runner import StubTrialRunner
from autonomous_ai_agents.execution.trial_runner import trial_id_for
from autonomous_ai_agents.orchestrator.main import (
    EngineGraph,
    build_checkpointer,
    run_config,
)
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    _fix_retries_spent,
    make_nodes,
    progress_of,
)
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state
from autonomous_ai_agents.persistence.repository import InMemoryRepository

ContextFactory = Callable[..., NodeContext]
GraphFactory = Callable[..., EngineGraph]

RUN_ID = "run-u16"
CRASH = "workload w crashed: NameError: name 'seen' is not defined"
SPENT = "NameError; not retried: the run's fix retry is spent"
UNREADABLE = "fix_retry_count_unavailable"
Plan = Literal["fixed", "again"] | int


class _Unreadable(InMemoryRepository):
    """A repository whose trial list cannot be read (Postgres down)."""

    def list_trials(self, run_id: str) -> tuple[Trial, ...]:
        raise RuntimeError("connect to postgresql://dev:hunter2@db failed")


@dataclass
class _Retrying:
    """Each trial of a planned round crashes fixably on attempt 1; "fixed"
    retries into the stub's outcome, "again" keeps the first failure; an int
    is reported as the attempts whatever the brief allowed."""

    inner: StubTrialRunner
    plan: Mapping[int, Plan]
    crash_at: int | None = None  # this call (0-based) raises, as a node crash

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        if len(self.inner.briefs) == self.crash_at:
            self.inner.briefs.append(brief)
            raise RuntimeError("the process died inside the trials node")
        trial = self.inner.run(hypothesis, workloads, baseline, round=round,
                               branch=branch, budget_usd=budget_usd, brief=brief)  # fmt: skip
        trial = trial.model_copy(update={"id": trial_id_for(branch, round)})
        plan = self.plan.get(round)
        if plan is None:
            return trial
        if isinstance(plan, int):
            return trial.model_copy(update={"attempts": plan})
        crashed = trial.model_copy(
            update={"status": TrialStatus.failed, "measurements": (), "error": CRASH}
        )
        if brief.fix_retries_left <= 0:  # the runner's ``attempts - 1 >= left``
            return crashed.model_copy(update={"retry_notes": (SPENT,)})
        if plan == "fixed":
            return trial.model_copy(
                update={"attempts": 2, "retry_notes": ("NameError; retried",)}
            )
        note = "NameError; retry: TypeError, first failure kept"
        return crashed.model_copy(update={"attempts": 2, "retry_notes": (note,)})

    @property
    def lefts(self) -> list[int]:
        return [brief.fix_retries_left for brief in self.inner.briefs]


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    return initial_state(sample_project, [sample_workload], [sample_objective],
                         sample_guardrails, run_id=RUN_ID, max_rounds=3)  # fmt: skip


def _context(
    make_context: ContextFactory,
    candidates: Sequence[Hypothesis],
    plan: Mapping[int, Plan],
    crash_at: int | None = None,
    **overrides: object,
) -> tuple[NodeContext, _Retrying]:
    base = make_context(candidates, **overrides)
    assert isinstance(base.runner, StubTrialRunner)
    runner = _Retrying(base.runner, plan, crash_at)
    return replace(base, runner=runner), runner


def _before_trials(
    engine_graph: GraphFactory,
    ctx: NodeContext,
    start: EngineState | None,
    saver: BaseCheckpointSaver[str],
    node: str = "trials",
) -> EngineState:
    """Run the graph until the next ``node``; the checkpoint's state."""
    graph, cfg = engine_graph(ctx, saver), run_config(RUN_ID, 3)
    graph.invoke(start, cfg, interrupt_before=[node])
    snapshot = graph.get_state(cfg)
    assert snapshot.next == (node,)
    return cast(EngineState, snapshot.values)


class TestOneRetryPerRun:
    def test_the_node_passes_1_then_0_and_a_spent_crash_is_rejected(
        self,
        make_context: ContextFactory,
        engine_graph: GraphFactory,
        state: EngineState,
        h1_cache: Hypothesis,
        h2_protected: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN a run cap of 1 and three trials over two rounds, each crashing
              fixably
        WHEN the run goes to its end
        THEN the briefs carry 1, 0 (round 1), 0 (round 2); only the first trial
             retried; the others keep their first failure with the "spent"
             note, are rejected, and the run still finishes
        """
        ctx, runner = _context(make_context, [h1_cache, h2_protected, h3_noise],
                               {1: "again", 2: "again"}, fix_retries_per_run=1,
                               max_hypotheses_per_round=2)  # fmt: skip
        graph, cfg = engine_graph(ctx), run_config(RUN_ID, 3)

        final = graph.invoke(state, cfg)

        assert runner.lefts == [1, 0, 0]
        first, *spent = final["trials"]
        assert (first.attempts, first.status) == (2, TrialStatus.failed)
        assert [t.round for t in spent] == [1, 2]
        for trial in spent:
            assert (trial.attempts, trial.status) == (1, TrialStatus.failed)
            assert trial.retry_notes == (SPENT,)
        outcomes = {v.trial_id: v.outcome for v in final["verdicts"]}
        assert {outcomes[t.id] for t in spent} == {VerdictOutcome.reject}
        assert final["phase"] is RunPhase.done

    def test_spent_retries_sum_over_trials_and_sources_once_per_id(self) -> None:
        """Distinct trials add up (B-R2's cap 2 needs the sum, not the
        largest); one id in several sources is one trial; never below 0."""
        a = Trial(hypothesis_id="h-a", round=1, attempts=2)
        b = Trial(hypothesis_id="h-b", round=1, attempts=2)
        assert _fix_retries_spent([a, b]) == 2
        assert _fix_retries_spent([a], [a], [b]) == 2  # checkpoint, record, round
        assert _fix_retries_spent([a], [a.model_copy(update={"attempts": 1})]) == 1
        assert _fix_retries_spent([a.model_copy(update={"attempts": 0})]) == 0


class TestResume:
    @pytest.mark.parametrize(
        ("first_round", "cap_after", "expected"),
        [("again", 1, 0), (None, 1, 1), ("again", 0, 0)],
        ids=["retried-then-resumed", "control-no-retry", "cap-lowered-on-resume"],
    )
    def test_a_resume_counts_from_the_checkpointed_trials(
        self,
        make_context: ContextFactory,
        engine_graph: GraphFactory,
        state: EngineState,
        h2_protected: Hypothesis,
        h3_noise: Hypothesis,
        first_round: Plan | None,
        cap_after: int,
        expected: int,
    ) -> None:
        """
        GIVEN a run that stopped before round 2's trials, round 1's trial
              retried (or not), checkpointed
        WHEN a fresh process (new context, runner, an empty repository) resumes it
        THEN round 2's brief carries the cap minus the checkpointed retries,
             never below 0, so a resume never grants the spent retry again
        """
        candidates, saver = [h2_protected, h3_noise], build_checkpointer()
        plan_1: dict[int, Plan] = {} if first_round is None else {1: first_round}
        ctx_1, runner_1 = _context(make_context, candidates, plan_1,
                                   fix_retries_per_run=1, max_hypotheses_per_round=1)  # fmt: skip
        _before_trials(engine_graph, ctx_1, state, saver)
        stopped = _before_trials(engine_graph, ctx_1, None, saver)
        assert runner_1.lefts == [1]
        assert [t.attempts for t in stopped["trials"]] == [
            1 if first_round is None else 2
        ]

        ctx_2, runner_2 = _context(make_context, candidates, {2: "fixed"},
                                   fix_retries_per_run=cap_after, max_hypotheses_per_round=1,
                                   repository=InMemoryRepository())  # fmt: skip
        final = engine_graph(ctx_2, saver).invoke(None, run_config(RUN_ID, 3))

        assert runner_2.lefts[0] == expected
        second = final["trials"][1]
        assert second.attempts == 1 + expected
        assert (second.retry_notes == (SPENT,)) is (expected == 0)

    def test_b_r2_cap_2_adds_the_checkpoint_and_this_round(
        self,
        make_context: ContextFactory,
        engine_graph: GraphFactory,
        state: EngineState,
        h1_cache: Hypothesis,
        h2_protected: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN round 1's retry checkpointed and B-R2's future cap of 2 (set past
              NodeContext's 0-1 bound, which refuses it today)
        WHEN a fresh process with an empty repository runs round 2's two trials
        THEN they get 1, then 0: the checkpoint's retry and this round's add up
        """
        candidates, saver = [h1_cache, h2_protected, h3_noise], build_checkpointer()
        ctx_1, _ = _context(make_context, candidates, {1: "again"},
                            fix_retries_per_run=1, max_hypotheses_per_round=1)  # fmt: skip
        _before_trials(engine_graph, ctx_1, state, saver, "hypotheses")
        _before_trials(engine_graph, ctx_1, None, saver, "hypotheses")
        ctx_2, runner_2 = _context(make_context, candidates, {2: "again"},
                                   fix_retries_per_run=1, max_hypotheses_per_round=2,
                                   repository=InMemoryRepository())  # fmt: skip
        object.__setattr__(ctx_2, "fix_retries_per_run", 2)

        engine_graph(ctx_2, saver).invoke(None, run_config(RUN_ID, 3))

        assert runner_2.lefts == [1, 0]


class TestRepositoryCount:
    def test_a_crash_inside_the_node_never_regrants_the_saved_retry(
        self,
        make_context: ContextFactory,
        engine_graph: GraphFactory,
        state: EngineState,
        h1_cache: Hypothesis,
        h2_protected: Hypothesis,
        h3_noise: Hypothesis,
        in_memory_repo: InMemoryRepository,
    ) -> None:
        """
        GIVEN round 1's first trial retried and saved, then the next runner
              call raising, so the node never returns and the checkpoint holds
              no trial
        WHEN a fresh process on the same checkpointer and repository resumes,
             re-running round 1 (same trial ids) and then round 2
        THEN every brief carries 0, the re-run keeps the recorded 2 attempts
             (its save never lowers them) and round 2 gets no second retry
        """
        candidates, saver = [h1_cache, h2_protected, h3_noise], build_checkpointer()
        ctx_1, runner_1 = _context(make_context, candidates, {1: "again"}, crash_at=1,
                                   fix_retries_per_run=1, max_hypotheses_per_round=2)  # fmt: skip
        ready = _before_trials(engine_graph, ctx_1, state, saver)
        with pytest.raises(RuntimeError, match="died inside"):
            engine_graph(ctx_1, saver).invoke(None, run_config(RUN_ID, 3))
        assert (runner_1.lefts, ready["trials"]) == ([1, 0], [])
        (saved,) = in_memory_repo.list_trials(RUN_ID)
        assert saved.attempts == 2

        ctx_2, runner_2 = _context(make_context, candidates, {1: "again", 2: "fixed"},
                                   fix_retries_per_run=1, max_hypotheses_per_round=2)  # fmt: skip
        final = engine_graph(ctx_2, saver).invoke(None, run_config(RUN_ID, 3))

        assert runner_2.lefts == [0, 0, 0]
        recorded = {t.id: t for t in in_memory_repo.list_trials(RUN_ID)}
        assert recorded[saved.id].attempts == 2
        assert recorded[saved.id].retry_notes == (*saved.retry_notes, SPENT)
        assert final["trials"][0].id == saved.id
        assert [t.attempts for t in final["trials"]] == [2, 1, 1]

    @pytest.mark.parametrize(("cap", "warned"), [(1, True), (0, False)])
    def test_an_unreadable_repository_grants_none_and_warns_once(
        self,
        make_context: ContextFactory,
        engine_graph: GraphFactory,
        state: EngineState,
        h2_protected: Hypothesis,
        h3_noise: Hypothesis,
        cap: int,
        warned: bool,
    ) -> None:
        """
        GIVEN a repository whose list_trials raises (its text holds a secret)
        WHEN the trials node runs at cap 1 (cap 0 never reads it)
        THEN every brief carries 0, one warning names only the error type,
             and the round still runs
        """
        ctx, runner = _context(make_context, [h2_protected, h3_noise], {1: "fixed"},
                               fix_retries_per_run=cap)  # fmt: skip
        ready = _before_trials(engine_graph, ctx, state, build_checkpointer())

        delta = make_nodes(replace(ctx, repository=_Unreadable()))["trials"](ready)

        assert runner.lefts == [0, 0]
        events = [e for e in delta["events"] if isinstance(e, EngineEvent)]  # type: ignore[attr-defined]
        codes = [e for e in events if e.data.get("code") == UNREADABLE]
        assert len(codes) == int(warned)
        for event in codes:
            assert event.level is EventLevel.warning
            assert event.data["error"] == "RuntimeError"
            assert "RuntimeError" in event.message and "hunter2" not in event.message
        assert len(delta["round_trials"]) == 2  # type: ignore[arg-type]
        assert "budget_exhausted" not in delta  # a warning, not a stop


class TestAllowanceRefused:
    @pytest.mark.parametrize(
        ("cap", "attempts", "message"),
        [
            (0, 2, "attempts 2 exceeds the 0 fix retries it was given"),
            (1, 3, "attempts 3 exceeds the 1 fix retry it was given"),
            (1, 2, None),
            (0, 1, None),
        ],
    )
    def test_a_runner_over_its_allowance_is_refused(
        self,
        make_context: ContextFactory,
        engine_graph: GraphFactory,
        state: EngineState,
        h3_noise: Hypothesis,
        cap: int,
        attempts: int,
        message: str | None,
    ) -> None:
        """
        GIVEN a runner that reports ``attempts`` whatever its brief allowed
        WHEN the trials node checks the trial
        THEN more attempts than 1 + the allowance fail the round closed with an
             EngineError naming both; up to it the trial is accepted
        """
        ctx, runner = _context(make_context, [h3_noise], {1: attempts},
                               fix_retries_per_run=cap)  # fmt: skip
        ready = _before_trials(engine_graph, ctx, state, build_checkpointer())
        trials = make_nodes(ctx)["trials"]

        if message is None:
            ran = trials(ready)["round_trials"]
            assert isinstance(ran, list)
            (trial,) = ran
            assert isinstance(trial, Trial)
            assert trial.attempts == attempts
        else:
            with pytest.raises(EngineError, match=message):
                trials(ready)
        assert runner.lefts == [cap]

    def test_a_retry_after_the_run_spent_its_own_fails_the_round_closed(
        self,
        make_context: ContextFactory,
        engine_graph: GraphFactory,
        state: EngineState,
        h2_protected: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN a run cap of 1 and a runner retrying every trial regardless
        WHEN the second trial reports 2 attempts on a brief that allowed 0
        THEN it is refused like any untrustworthy trial: an EngineError, the
             first (allowed) trial kept as the failed run's progress
        """
        ctx, runner = _context(make_context, [h2_protected, h3_noise], {1: 2},
                               fix_retries_per_run=1)  # fmt: skip
        ready = _before_trials(engine_graph, ctx, state, build_checkpointer())

        with pytest.raises(EngineError, match="exceeds the 0 fix retries") as raised:
            make_nodes(ctx)["trials"](ready)

        assert runner.lefts == [1, 0]
        kept = progress_of(raised.value)["round_trials"]
        assert isinstance(kept, list)
        assert [t.attempts for t in kept] == [2]


class TestStep2Defaults:
    def test_cap_0_reproduces_step_2(
        self,
        make_context: ContextFactory,
        engine_graph: GraphFactory,
        state: EngineState,
        h1_cache: Hypothesis,
        h3_noise: Hypothesis,
    ) -> None:
        """
        GIVEN the default context (cap 0, noise rule off) and fixable crashes
        WHEN the run goes to its end
        THEN every brief carries 0 and no trial retries (Step 2)
        """
        ctx, runner = _context(make_context, [h1_cache, h3_noise], {1: "fixed"})
        assert ctx.fix_retries_per_run == 0
        assert (ctx.calibrator, ctx.confirm_winners) == (None, False)

        final = engine_graph(ctx).invoke(state, run_config(RUN_ID, 3))

        assert runner.lefts and set(runner.lefts) == {0}
        assert {t.attempts for t in final["trials"]} == {1}
