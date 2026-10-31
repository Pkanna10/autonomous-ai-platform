"""Define's output modes, the baseline's output checks and the trials brief
(Step 3, U25; O7, O9, D37, D40).

Swap points: ``_Freezing`` stands for ``GitBaselineRunner`` (U24) behind the
factory's ``ConnectedBaselineRunner`` (U10): it replays the conftest's
scripted baseline and reports the ``quality_files`` and ``label_leaks`` a
real freeze would; ``StubTrialRunner`` records each ``TrialBrief``. A
``QualityCheck`` in ``NodeContext.quality`` is the caller's one confirmation
(D40); a ``QualityProposal`` in the understanding is model output only.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    BuiltinMeasure,
    Direction,
    DropUnit,
    EngineEvent,
    EventLevel,
    FrozenFile,
    Guardrail,
    GuardrailKind,
    Hypothesis,
    Measurement,
    Objective,
    OutputTolerance,
    Project,
    ProjectUnderstanding,
    QualityCheck,
    QualityProposal,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.common.paths import matches_pattern
from autonomous_ai_agents.execution.measure import output_fingerprint
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization.anticheat import check_diff_all
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    _report,
    _review_report,
    make_nodes,
)
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]
COMMIT = "c" * 40
LABELS = "eval/labels.txt"
EMPTY = output_fingerprint(0, hashlib.sha256(b"").hexdigest(), None)
ACC = QualityCheck(
    name="acc",
    measure=BuiltinMeasure.accuracy,
    labels=LABELS,
    frozen_paths=(LABELS,),
    max_drop=0.005,
)
FROZEN = (FrozenFile(path=LABELS, sha256="d" * 64, size=12),)


class _Freezing(StubBaselineRunner):
    """The scripted baseline plus what a freezing runner reports."""

    def __init__(
        self,
        script: ScriptedOutcome,
        files: tuple[FrozenFile, ...] = (),
        leaks: tuple[str, ...] = (),
        raw: str | None = None,
    ) -> None:
        super().__init__(script)
        self.quality_files, self.label_leaks, self._raw = files, leaks, raw

    def measure(
        self,
        workloads: Sequence[Workload],
        *,
        run_id: str | None = None,
        commit: str | None = None,
    ) -> tuple[Measurement, ...]:
        rows = super().measure(workloads, run_id=run_id, commit=commit)
        return tuple(r.model_copy(update={"raw_fingerprint": self._raw}) for r in rows)


def _script(
    fingerprint: str | None = "a" * 64, quality: bool = False
) -> ScriptedOutcome:
    samples: dict[str, tuple[float, ...]] = {
        METRIC_WALL_TIME_S: (1.0, 1.01, 0.99, 1.0, 1.0)
    }
    if quality:
        samples[ACC.metric] = (0.9,)
    return ScriptedOutcome(samples=samples, output_fingerprint=fingerprint)


@pytest.fixture
def state(
    sample_project: Project, sample_workload: Workload, sample_objective: Objective
) -> EngineState:
    state = initial_state(
        sample_project, [sample_workload], [sample_objective], [], run_id="run-u25"
    )
    state["base_commit"] = COMMIT
    state["extra_protected"] = ["setup.cfg"]
    return state


def _merge(state: EngineState, delta: dict[str, object]) -> EngineState:
    merged = cast(dict[str, Any], dict(state))
    for key, value in delta.items():
        merged[key] = (
            [*merged[key], *cast(list[object], value)] if key == "events" else value
        )
    return cast(EngineState, merged)


def _defined(ctx: NodeContext, state: EngineState) -> EngineState:
    return _merge(state, make_nodes(ctx)["define"](state))


def _equivalence(project: Project) -> Guardrail:
    return Guardrail(
        project_id=project.id, kind=GuardrailKind.output_equivalence, description="eq"
    )


def _quality_bound(project: Project) -> Guardrail:
    return Guardrail(
        project_id=project.id,
        kind=GuardrailKind.metric_bound,
        metric=ACC.metric,
        max_drop=0.5,
        direction=Direction.maximize,
        description="the caller's own quality bound",
    )


def _codes(events: Sequence[EngineEvent]) -> list[object]:
    return [e.data.get("code") for e in events]


class TestDefine:
    def test_the_default_output_check_adds_equivalence_once(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        ctx = make_context(default_output_check=True)
        done = _defined(ctx, state)
        kinds = [g.kind for g in done["guardrails"]]
        assert kinds == [GuardrailKind.output_equivalence]
        assert done["extra_protected"] == ["setup.cfg"]
        assert "output check: exact" in done["events"][-1].message
        again = make_nodes(ctx)["define"](done)
        assert "guardrails" not in again  # present already: nothing added

    def test_off_keeps_step2s_delta(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        delta = make_nodes(make_context())["define"](state)
        assert set(delta) == {"phase", "objectives", "events"}

    def test_a_quality_check_adds_its_bound_and_protects_its_files(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        done = _defined(make_context(quality=ACC, default_output_check=True), state)
        (bound,) = done["guardrails"]
        assert (bound.kind, bound.metric, bound.max_drop) == (
            GuardrailKind.metric_bound,
            "quality:acc",
            0.005,
        )
        assert (bound.direction, bound.drop_unit) == (
            Direction.maximize,
            DropUnit.absolute,
        )
        assert done["extra_protected"] == ["setup.cfg", LABELS]
        protected = (*make_context().protected_patterns, *done["extra_protected"])
        for touched in (LABELS, "Eval/Labels.TXT"):
            (violation,) = check_diff_all((touched,), protected)
            assert violation.rule is ViolationRule.protected_path
        assert "output check: quality:acc" in done["events"][-1].message

    def test_a_quality_check_beside_equivalence_is_refused(
        self, make_context: ContextFactory, state: EngineState, sample_project: Project
    ) -> None:
        state["guardrails"] = [_equivalence(sample_project)]
        with pytest.raises(EngineError, match="not both"):
            make_nodes(make_context(quality=ACC))["define"](state)

    def test_frozen_paths_reach_the_matchers_glob_escaped(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        odd = ACC.model_construct(**{**dict(ACC), "frozen_paths": ("eval/a[1].csv",)})
        done = _defined(make_context(quality=odd), state)
        pattern = done["extra_protected"][-1]
        assert matches_pattern("eval/a[1].csv", pattern)
        assert not matches_pattern("eval/a1.csv", pattern)

    def test_a_proposal_never_activates_itself(
        self, make_context: ContextFactory, state: EngineState, h1_cache: Hypothesis
    ) -> None:
        proposal = QualityProposal(measure=BuiltinMeasure.accuracy, labels=LABELS)
        state["understanding"] = ProjectUnderstanding(
            language="python",
            summary="s",
            served_by_model="m",
            quality_proposal=proposal,
        )
        ctx = make_context([h1_cache], default_output_check=True)
        done = _defined(ctx, state)
        assert [g.kind for g in done["guardrails"]] == [
            GuardrailKind.output_equivalence
        ]
        assert done["extra_protected"] == ["setup.cfg"]
        assert _brief(ctx, done, h1_cache).read_deny == ()

    def test_a_workload_tolerance_is_echoed(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        tolerance = OutputTolerance(float_digits=9)
        state["workloads"] = [
            state["workloads"][0].model_copy(update={"output_tolerance": tolerance})
        ]
        delta = make_nodes(make_context(default_output_check=True))["define"](state)
        message = cast(list[EngineEvent], delta["events"])[0].message
        assert "train-step equal within tolerance (9 significant digits" in message


def _brief(ctx: NodeContext, state: EngineState, hypothesis: Hypothesis) -> Any:
    measured = make_nodes(ctx)["baseline"](state)["baseline"]
    state = _merge(
        state, {"baseline": measured, "hypotheses": [hypothesis], "round": 1}
    )
    make_nodes(ctx)["trials"](state)
    runner = ctx.runner
    assert isinstance(runner, StubTrialRunner)
    return runner.briefs[-1]


ODD = ACC.model_construct(
    **{**dict(ACC), "labels": "eval/a[1].csv", "frozen_paths": ("eval/a[1].csv",)}
)


@pytest.mark.parametrize("check", [ACC, ODD], ids=["literal", "glob-character"])
def test_the_trials_brief_read_denies_the_frozen_paths(
    make_context: ContextFactory,
    state: EngineState,
    h1_cache: Hypothesis,
    check: QualityCheck,
) -> None:
    (path,) = check.frozen_paths
    files = (FrozenFile(path=path, sha256="d" * 64, size=12),)
    runner = _Freezing(_script(quality=True), files=files)
    ctx = make_context([h1_cache], quality=check, baseline_runner=runner)
    if check is ODD:  # literal, never escaped: the brief refuses the raw name
        with pytest.raises(ValueError, match=re.escape(f"read_deny {path!r}")):
            _brief(ctx, _defined(ctx, state), h1_cache)
        return
    brief = _brief(ctx, _defined(ctx, state), h1_cache)
    assert brief.read_deny == (LABELS,)
    assert LABELS in brief.protected


class TestResume:
    """Quality mode is pinned to the check that defined the run (D40)."""

    @pytest.mark.parametrize("resumed", [None, ACC.model_copy(update={"name": "f1"})])
    def test_trials_refuse_a_context_without_the_defining_check(
        self,
        make_context: ContextFactory,
        state: EngineState,
        h1_cache: Hypothesis,
        resumed: QualityCheck | None,
    ) -> None:
        runner = _Freezing(_script(quality=True), files=FROZEN)
        ctx = make_context([h1_cache], quality=ACC, baseline_runner=runner)
        defined = _defined(ctx, state)
        measured = make_nodes(ctx)["baseline"](defined)["baseline"]
        done = _merge(
            defined, {"baseline": measured, "hypotheses": [h1_cache], "round": 1}
        )
        later = replace(ctx, quality=resumed)
        with pytest.raises(EngineError, match="resume with the quality check"):
            make_nodes(later)["trials"](done)
        trial_runner = later.runner
        assert isinstance(trial_runner, StubTrialRunner)
        assert trial_runner.briefs == []  # refused before any brief

    @pytest.mark.parametrize("confirmed", [None, ACC.model_copy(update={"name": "f1"})])
    def test_a_quality_bound_comes_only_from_the_confirmed_check(
        self,
        make_context: ContextFactory,
        state: EngineState,
        confirmed: QualityCheck | None,
    ) -> None:
        own = _quality_bound(state["project"])
        state["guardrails"] = [own]
        with pytest.raises(EngineError, match="only through the confirmed check"):
            make_nodes(make_context(quality=confirmed))["define"](state)


class TestBaseline:
    def _run(
        self, ctx: NodeContext, state: EngineState
    ) -> tuple[EngineState, dict[str, object]]:
        defined = _defined(ctx, state)
        delta = make_nodes(ctx)["baseline"](defined)
        return _merge(defined, delta), delta

    def test_the_baseline_records_the_frozen_files(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        runner = _Freezing(_script(quality=True), files=FROZEN)
        done, _ = self._run(make_context(quality=ACC, baseline_runner=runner), state)
        assert done["baseline"] is not None
        assert done["baseline"].quality_files == FROZEN

    @pytest.mark.parametrize(
        "files", [(), (FrozenFile(path="other.txt", sha256="e" * 64, size=1),)]
    )
    def test_quality_mode_refuses_a_baseline_that_froze_other_files(
        self,
        make_context: ContextFactory,
        state: EngineState,
        files: tuple[FrozenFile, ...],
    ) -> None:
        runner = _Freezing(_script(quality=True), files=files)
        with pytest.raises(EngineError, match="froze"):
            self._run(make_context(quality=ACC, baseline_runner=runner), state)

    def test_a_label_leak_is_warned_and_reported(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        runner = _Freezing(
            _script(quality=True), files=FROZEN, leaks=("data/test.csv column 3",)
        )
        done, delta = self._run(
            make_context(quality=ACC, baseline_runner=runner), state
        )
        (leak,) = [
            e
            for e in cast(list[EngineEvent], delta["events"])
            if e.data.get("code") == "label_leak"
        ]
        assert leak.level is EventLevel.warning
        assert "data/test.csv column 3" in leak.message
        report = _report(done, "engine/", quality=ACC)
        assert "- Labels also in: data/test.csv column 3" in report
        assert "accuracy over eval/labels.txt, may drop at most 0.5 points" in report
        assert "other than the frozen ones determines the labels" in report
        reviewed = _review_report(done, "engine/", confirm=False, quality=ACC)
        for said in (
            "- Output check: quality check acc, accuracy over eval/labels.txt",
            "other than the frozen ones determines the labels",
            "- Labels also in: data/test.csv column 3",
        ):
            assert said in reviewed

    def test_quality_mode_refuses_a_runner_that_freezes_nothing(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        ctx = make_context(
            quality=ACC, baseline_runner=StubBaselineRunner(_script(quality=True))
        )
        with pytest.raises(EngineError, match="froze nothing"):
            self._run(ctx, state)

    @pytest.mark.parametrize("raw", [None, EMPTY])
    def test_an_empty_output_is_warned_in_exact_mode(
        self, make_context: ContextFactory, state: EngineState, raw: str | None
    ) -> None:
        # raw EMPTY under a canonical tolerance fingerprint; or the stub's EMPTY
        fingerprint = EMPTY if raw is None else "b" * 64
        runner = _Freezing(_script(fingerprint), raw=raw)
        ctx = make_context(default_output_check=True, baseline_runner=runner)
        done, delta = self._run(ctx, state)
        events = cast(list[EngineEvent], delta["events"])
        (empty,) = [
            e for e in events if e.data.get("code") == "output_compares_nothing"
        ]
        assert empty.level is EventLevel.warning
        said = "the output check compares nothing on workload train-step: print the result or declare `output_file`"
        assert said in empty.message
        assert f"- Output check: exact; {said}" in _report(done, "engine/")

    def test_an_empty_output_stops_quality_mode(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        runner = _Freezing(_script(EMPTY, quality=True), files=FROZEN)
        with pytest.raises(
            EngineError, match="compares nothing on workload train-step"
        ):
            self._run(make_context(quality=ACC, baseline_runner=runner), state)

    def test_without_an_output_check_an_empty_output_is_not_warned(
        self, make_context: ContextFactory, state: EngineState
    ) -> None:
        runner = _Freezing(_script(EMPTY))
        done, delta = self._run(make_context(baseline_runner=runner), state)
        assert "output_compares_nothing" not in _codes(
            cast(list[EngineEvent], delta["events"])
        )
        assert "- Output check:" not in _report(done, "engine/")

    @pytest.mark.parametrize("quality", [False, True])
    def test_disagreeing_runs_stop_both_modes_with_the_ways_out(
        self, make_context: ContextFactory, state: EngineState, quality: bool
    ) -> None:
        runner = _Freezing(
            _script(None, quality=quality), files=FROZEN if quality else ()
        )
        ctx = make_context(
            quality=ACC if quality else None,
            default_output_check=True,
            baseline_runner=runner,
        )
        with pytest.raises(
            EngineError, match="nondeterministic or missing output"
        ) as err:
            self._run(ctx, state)
        assert "an output tolerance" in str(err.value)
        assert "a quality check" in str(err.value)
