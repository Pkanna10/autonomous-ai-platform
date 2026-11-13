"""U0 (X2-DT): the stacking-off golden, recorded before any stacking code.

An X2-D-shaped run (three rounds, ``portfolio_rounds`` 3, three generator
calls, confirmation on, a three-block calibration, the default output check,
near-miss compounds) goes through the real graph (``Orchestrator.run``:
``create_graph`` and ``run_config``) over fakes. Its fingerprint covers the
compiled graph (nodes and edges), every ``main.run_config`` call the run
made (arguments and result, spied), the node visit order (the
checkpoint history), every request the engine sent (each generator call's
keywords; every preflight, understand, baseline, calibration, profile, trial,
replay, combine and publish call), every repository call, every event, the
final state (``dump_state``; the later ``stack`` key must be ``None``) and
both reports. ``GOLDEN`` was recorded on 4f176d7, so with ``STACKED_ROUNDS``
at its default every unit of X2-DT must leave it unchanged.

The scripted rounds (titles keyed in ``_SCRIPTS``):

| Round | Ideas (model order)               | Verdicts                                  |
| ----- | --------------------------------- | ----------------------------------------- |
| 1     | cache, batch, tweak               | keep, keep, inconclusive (a near miss)    |
| 2     | skip-test, vectorise, pad, tweak  | reject (protected), reject (failed),      |
|       |                                   | inconclusive (a near miss); the repeated  |
|       |                                   | tweak is dropped: no keep                 |
| 3     | compound (tweak + pad, replayed), | keep, keep, review, inconclusive (did not |
|       | mask, bf16 (behaviour), vocab     | confirm)                                  |

The run set (cache, mask, batch, compound by score) re-tests with batch
skipped on a conflict and holds; the review set (bf16) holds on its own
branch.

Swap points: ``_RecordingGenerator`` stands for ``IdeaPipelineGenerator``
(scripted per call, spend recorded on the narrowed ``Budget``);
``_RecordingRunner`` for ``GitTrialRunner`` (the conftest's
``StubTrialRunner`` outcomes, committed on the baseline's commit with the
paired base rows; ``replay`` builds the compound the same way);
``StubBaselineRunner`` and ``_RecordingCalibrator`` for
``GitBaselineRunner``; ``FakeCombiner`` for ``GitCombiner`` (one scripted
re-test per call); ``_RecordingRepository`` is the ``InMemoryRepository``;
``FakePreflight``, ``FakeUnderstander``, ``FakeProfiler`` and
``FakePublisher`` for git and Claude. The clock is frozen and ids are a
counter (``models.datetime`` and ``models.uuid``, read only by ``utc_now``
and ``new_id``); the fingerprint also aliases every uuid by first
appearance, so it holds no clock, no fresh id and no tmp path.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import itertools
import json
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, tzinfo
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common import models
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Baseline,
    ChangeClass,
    CombineSkip,
    Guardrail,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Lesson,
    Measurement,
    NoiseCalibration,
    Objective,
    Project,
    ProjectUnderstanding,
    RunStats,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.fakes import (
    FAKE_COMMIT,
    FakeCombiner,
    FakePreflight,
    FakeProfiler,
    FakePublisher,
    FakeUnderstander,
)
from autonomous_ai_agents.execution.protocols import (
    CombineMeasured,
    TrialBrief,
    UnderstandResult,
)
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization.anticheat import fingerprint
from autonomous_ai_agents.optimization.evolve import COMPOUND_TAG, compound_id
from autonomous_ai_agents.optimization.idea_dedupe import (
    IdeaKey,
    MechanismKey,
    Target,
    key_event,
)
from autonomous_ai_agents.optimization.idea_pipeline import SEEDED_CALL
from autonomous_ai_agents.optimization.idea_types import (
    GenerateEvent,
    Mechanism,
    MorphCell,
)
from autonomous_ai_agents.optimization.judges import default_judges
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator import main
from autonomous_ai_agents.orchestrator.main import Orchestrator
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.orchestrator.serde import dump_state
from autonomous_ai_agents.orchestrator.state import EngineState
from autonomous_ai_agents.persistence.repository import InMemoryRepository

GOLDEN = "8c8ee6c26316087ba575d90241518bddddf9eaa26c83537eeb9eec5b4499df53"
"""``_fingerprint`` of the run below, recorded on HEAD 4f176d7 (before X2-DT)."""

RUN_ID = "run-x2dt-golden"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
VAL_LOSS = "val_loss"
SAME = fingerprint("baseline")
CAP_USD = 12.90
GENERATOR_USD = 0.25
ROUND_TIP, RUN_TIP, REVIEW_TIP = "c" * 40, "d" * 40, "f" * 40
DIFF = "diff --git a/src/bridge/encoder.py b/src/bridge/encoder.py\n"


# ---------------------------------------------------------------------------
# The ideas, their outcomes and the combiner's re-tests
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Idea:
    id: str
    title: str
    wall: float
    path: str = "src/bridge/encoder.py"
    change_class: ChangeClass = ChangeClass.efficiency
    val_loss: float = 0.500
    error: str | None = None
    cost_usd: float = 0.10


CACHE = _Idea("r1-cache", "Cache the frozen encoder", 1.05, cost_usd=0.12)
BATCH = _Idea("r1-batch", "Batch the collate loop", 1.50, "src/bridge/collate.py")
TWEAK = _Idea("r1-tweak", "Micro-tweak the tokenizer", 1.74, "src/bridge/tok.py")
SKIP = _Idea("r2-skip", "Skip the slow cache test", 1.20, "tests/test_cache.py")
VECTOR = _Idea("r2-vector", "Vectorise the scorer", 1.30, "src/bridge/score.py",
               error="SyntaxError: invalid syntax (score.py, line 3)")  # fmt: skip
PAD = _Idea("r2-pad", "Pad the batches once", 1.73, "src/bridge/pad.py")
AGAIN = _Idea("r2-again", "Micro-tweak  the TOKENIZER", 1.70, "src/bridge/tok.py")
MASK = _Idea("r3-mask", "Reuse the attention mask", 1.20, "src/bridge/attn.py")
BF16 = _Idea("r3-bf16", "Run the encoder in bf16", 1.50, "src/bridge/train.py",
             ChangeClass.behaviour, val_loss=0.503)  # fmt: skip
VOCAB = _Idea("r3-vocab", "Precompute the vocabulary", 1.40, "src/bridge/vocab.py")
CALLS: tuple[tuple[_Idea, ...], ...] = (
    (CACHE, BATCH, TWEAK),
    (SKIP, VECTOR, PAD, AGAIN),
    (MASK, BF16, VOCAB),
)
"""Each generator call's ideas, model order (AGAIN repeats TWEAK's title)."""
COMPOUND = _Idea(compound_id(f"t-{TWEAK.id}", f"t-{PAD.id}"), "compound", 1.62)
"""The near-miss compound of TWEAK and PAD (G5b), trialled in round 3."""


def _script(idea: _Idea) -> ScriptedOutcome:
    return ScriptedOutcome(
        touched_paths=(idea.path,),
        samples={
            METRIC_WALL_TIME_S: tuple(
                idea.wall + d for d in (0.0, -0.03, 0.03, 0.0, 0.0)
            ),
            VAL_LOSS: (idea.val_loss,) * 5,
        },
        output_fingerprint=SAME,
        tests_passed=True,
        error=idea.error,
        cost_usd=idea.cost_usd,
        tokens_used=int(idea.cost_usd * 20_000),
    )


_SCRIPTS = {idea.title: _script(idea) for call in CALLS for idea in call}
_SCRIPTS[COMPOUND.id] = dataclasses.replace(
    _script(COMPOUND), touched_paths=(TWEAK.path, PAD.path)
)


def _commit(idea_id: str) -> str:
    """The trial commit the recording runner reports for ``idea_id``."""
    return hashlib.sha256(idea_id.encode()).hexdigest()[:40]


def _rows(
    workload: Workload, wall: float, val_loss: float, *, suite: bool
) -> tuple[Measurement, ...]:
    samples = {
        METRIC_WALL_TIME_S: tuple(wall + d for d in (0.0, -0.02, 0.02, 0.0, 0.0)),
        VAL_LOSS: (val_loss,) * 5,
    }
    rows = [
        Measurement(workload_id=workload.id, metric=metric,
                    stats=RunStats.from_samples(values, unit="s"), samples=values,
                    output_fingerprint=SAME)
        for metric, values in samples.items()
    ]  # fmt: skip
    if suite:
        rows.append(Measurement(workload_id=workload.id, metric=METRIC_TESTS_PASSED,
                                stats=RunStats.from_samples((1.0,), unit="bool"),
                                samples=(1.0,)))  # fmt: skip
    return tuple(rows)


def _look(
    workload: Workload,
    tip: str,
    applied: Sequence[_Idea],
    wall: float,
    *,
    val_loss: float = 0.500,
    skipped: Sequence[CombineSkip] = (),
) -> CombineMeasured:
    """One ABAB re-test: A rows at 1.80 s, B rows (+ the suite) at ``wall``."""
    return CombineMeasured(
        tip_commit=tip,
        applied=tuple(f"t-{idea.id}" for idea in applied),
        skipped=tuple(skipped),
        baseline=_rows(workload, 1.80, 0.500, suite=False),
        combined=_rows(workload, wall, val_loss, suite=True),
    )


def _combiner_script(workload: Workload) -> list[CombineMeasured | Exception]:
    """The eight re-tests in call order: six second looks, then the sets."""
    conflict = CombineSkip(trial_id=f"t-{BATCH.id}", reason="merge conflict",
                           paths=(BATCH.path,))  # fmt: skip
    return [
        _look(workload, ROUND_TIP, (CACHE,), 1.06),  # round 1: confirmed
        _look(workload, ROUND_TIP, (BATCH,), 1.52),  # round 1: confirmed
        _look(workload, ROUND_TIP, (COMPOUND,), 1.63),  # round 3: confirmed
        _look(workload, ROUND_TIP, (MASK,), 1.22),  # round 3: confirmed
        _look(workload, ROUND_TIP, (BF16,), 1.50, val_loss=0.503),  # round 3
        _look(workload, ROUND_TIP, (VOCAB,), 1.79),  # round 3: did not confirm
        _look(workload, RUN_TIP, (CACHE, MASK, COMPOUND), 0.85, skipped=(conflict,)),
        _look(workload, REVIEW_TIP, (BF16,), 1.50, val_loss=0.503),
    ]


# ---------------------------------------------------------------------------
# Recording seams
# ---------------------------------------------------------------------------


def _hypothesis(project: Project, idea: _Idea) -> Hypothesis:
    return Hypothesis(id=idea.id, project_id=project.id, source=HypothesisSource.novel,
                      title=idea.title, rationale=f"{idea.title}: scripted for U0",
                      change_class=idea.change_class, expected_gain=0.2,
                      provability=0.6, risk=0.2)  # fmt: skip


def _key(idea: _Idea, first: int) -> IdeaKey:
    target = Target(path=idea.path, first=first, last=first + 9)
    key = MechanismKey(target=target, mechanism=Mechanism.precompute_or_cache,
                       cell=MorphCell.work_reuse)  # fmt: skip
    return IdeaKey(key=key, function="encode")


def _result(project: Project, index: int) -> GenerateResult:
    """Call ``index``'s ideas, a key event each, and on the later (seeded)
    calls the pipeline's ``seeded_second_call`` event."""
    ideas = CALLS[index]
    events = [key_event(idea.id, idea.title, _key(idea, 10 + 20 * n))
              for n, idea in enumerate(ideas)]  # fmt: skip
    if index:
        seeded = GenerateEvent(code=SEEDED_CALL, message=f"seeded call {index}",
                               data={"seeds": index * 3})  # fmt: skip
        events.insert(0, seeded)
    return GenerateResult(
        hypotheses=tuple(_hypothesis(project, idea) for idea in ideas),
        notes=(f"call {index}: {len(ideas)} idea(s)",),
        events=tuple(events),
    )


class _RecordingGenerator:
    """Records every keyword (the budget as cap, spent, tokens), spends
    ``GENERATOR_USD`` on it, and returns the call's scripted result."""

    def __init__(self, project: Project) -> None:
        self._project = project
        self.calls: list[dict[str, object]] = []

    def generate(self, **kwargs: Any) -> GenerateResult:  # noqa: ANN401
        budget = kwargs["budget"]
        assert isinstance(budget, Budget)
        seen = {k: v for k, v in kwargs.items() if k != "budget"}
        seen["budget"] = (budget.cap_usd, budget.spent_usd, budget.tokens)
        self.calls.append(seen)
        budget.check(GENERATOR_USD)
        budget.record(GENERATOR_USD, 5_000)
        index = kwargs["call_index"]
        assert isinstance(index, int)
        return _result(self._project, index)


class _RecordingRunner:
    """The stub's trial, committed on the baseline's commit (``t-<id>``,
    ``_commit``) with its paired base rows, as ``GitTrialRunner`` reports it;
    ``replay`` (a ``ReplayRunner``, so compounds are allowed) the compound's
    scripted trial the same way."""

    def __init__(self) -> None:
        self._inner = StubTrialRunner(_SCRIPTS)
        self.calls: list[dict[str, object]] = []

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
        self.calls.append({"kind": "run", "hypothesis": hypothesis,
                           "workloads": tuple(workloads), "baseline": baseline,
                           "round": round, "branch": branch,
                           "budget_usd": budget_usd, "brief": brief})  # fmt: skip
        trial = self._inner.run(hypothesis, workloads, baseline, round=round,
                                branch=branch, budget_usd=budget_usd, brief=brief)  # fmt: skip
        return self._committed(trial, hypothesis, baseline)

    def replay(
        self,
        hypothesis: Hypothesis,
        parents: Sequence[Trial],
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        self.calls.append({"kind": "replay", "hypothesis": hypothesis,
                           "parents": [(t.id, t.commit) for t in parents],
                           "workloads": tuple(workloads), "baseline": baseline,
                           "round": round, "branch": branch,
                           "budget_usd": budget_usd, "brief": brief})  # fmt: skip
        trial = self._inner.run(hypothesis, workloads, baseline, round=round,
                                branch=branch, budget_usd=budget_usd, brief=brief)  # fmt: skip
        return self._committed(trial, hypothesis, baseline)

    @staticmethod
    def _committed(trial: Trial, hypothesis: Hypothesis, baseline: Baseline) -> Trial:
        update: dict[str, object] = {"id": f"t-{hypothesis.id}",
                                     "base_commit": baseline.commit}  # fmt: skip
        if trial.status is TrialStatus.measured:
            paths = trial.touched_paths
            update |= {
                "commit": _commit(hypothesis.id),
                "diff": "".join(f"diff --git a/{p} b/{p}\n" for p in paths),
                "base_measurements": tuple(
                    m for m in baseline.measurements if m.metric != METRIC_TESTS_PASSED
                ),
            }
        return trial.model_copy(update=update)


class _RecordingBaseline:
    def __init__(self, inner: StubBaselineRunner) -> None:
        self._inner = inner
        self.calls: list[tuple[tuple[Workload, ...], str, str | None]] = []

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]:
        self.calls.append((tuple(workloads), run_id, commit))
        return self._inner.measure(workloads, run_id=run_id, commit=commit)


class _RecordingRepository(InMemoryRepository):
    """Records every call: the method, its key ids, and the rows it saves
    (a run as its key fields: the whole state is the fingerprint's own)."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, object]] = []

    def save_run(self, state: EngineState) -> None:
        fields = ("run_id", "phase", "round", "error", "cost_usd", "tokens_used",
                  "generator_calls", "kept_verdict_ids", "base_commit")  # fmt: skip
        values = cast(Mapping[str, object], state)
        row: dict[str, object] = {k: values[k] for k in fields}
        row["events"] = len(state["events"])
        row["trials"] = [t.id for t in state["trials"]]
        row["verdicts"] = [v.id for v in state["verdicts"]]
        self.calls.append(("save_run", row))
        super().save_run(state)

    def get_run(self, run_id: str) -> EngineState | None:
        found = super().get_run(run_id)
        self.calls.append(("get_run", (run_id, found is not None)))
        return found

    def save_trial(self, run_id: str, trial: Trial) -> None:
        self.calls.append(("save_trial", (run_id, trial)))
        super().save_trial(run_id, trial)

    def save_verdict(self, run_id: str, verdict: Verdict) -> None:
        self.calls.append(("save_verdict", (run_id, verdict)))
        super().save_verdict(run_id, verdict)

    def save_lesson(self, lesson: Lesson) -> None:
        self.calls.append(("save_lesson", lesson))
        super().save_lesson(lesson)

    def list_lessons(self, project_id: str | None = None) -> tuple[Lesson, ...]:
        found = super().list_lessons(project_id)
        self.calls.append(("list_lessons", (project_id, [x.id for x in found])))
        return found

    def list_trials(self, run_id: str) -> tuple[Trial, ...]:
        found = super().list_trials(run_id)
        self.calls.append(("list_trials", (run_id, [t.id for t in found])))
        return found

    def list_verdicts(self, run_id: str) -> tuple[Verdict, ...]:
        found = super().list_verdicts(run_id)
        self.calls.append(("list_verdicts", (run_id, [v.id for v in found])))
        return found


class _RecordingCalibrator:
    """Three A/A blocks, a 5 % floor (above ``MIN_RELATIVE_GAIN``)."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Workload, ...], str, str, int]] = []

    def calibrate(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str, blocks: int
    ) -> NoiseCalibration:
        self.calls.append((tuple(workloads), run_id, commit, blocks))
        gaps = {f"{w.id}:{METRIC_WALL_TIME_S}": 0.02 for w in workloads}
        return NoiseCalibration(blocks=blocks, gaps=gaps, floor=0.05)


@dataclasses.dataclass(frozen=True)
class _Seams:
    generator: _RecordingGenerator
    runner: _RecordingRunner
    baseline: _RecordingBaseline
    calibrator: _RecordingCalibrator
    preflight: FakePreflight
    understander: FakeUnderstander
    profiler: FakeProfiler
    combiner: FakeCombiner
    publisher: FakePublisher
    repository: _RecordingRepository


def _seams(project: Project, workload: Workload, baseline: ScriptedOutcome) -> _Seams:
    understanding = ProjectUnderstanding(
        language="python", summary="a VLM bridge", served_by_model="claude-opus-5-5"
    )
    hotspot = Hotspot(project_id=project.id, workload_id=workload.id,
                      file_path="src/bridge/encoder.py", symbol="encode",
                      line_start=10, line_end=40, self_time_s=0.8, total_time_s=1.2,
                      share=0.6, calls=20, tags=("frozen-encoder",))  # fmt: skip
    return _Seams(
        generator=_RecordingGenerator(project),
        runner=_RecordingRunner(),
        baseline=_RecordingBaseline(StubBaselineRunner(baseline)),
        calibrator=_RecordingCalibrator(),
        preflight=FakePreflight(),
        understander=FakeUnderstander(
            UnderstandResult(understanding, cost_usd=0.02, tokens_used=1_500)
        ),
        profiler=FakeProfiler((hotspot,), ("skipped one workload: scripted",)),
        combiner=FakeCombiner(_combiner_script(workload)),
        publisher=FakePublisher(DIFF),
        repository=_RecordingRepository(),
    )


def _context(seams: _Seams) -> NodeContext:
    """X2-D's knobs: three portfolio rounds and generator calls, confirmation,
    three calibration blocks, the default output check, near-miss compounds."""
    return NodeContext(
        runner=seams.runner, baseline_runner=seams.baseline,
        judges=default_judges(2.0, quality=None), repository=seams.repository,
        preflight=seams.preflight, understander=seams.understander,
        profiler=seams.profiler, combiner=seams.combiner, publisher=seams.publisher,
        min_trial_budget_usd=0.5, generator=seams.generator, generator_max_calls=3,
        default_output_check=True, calibrator=seams.calibrator, calibration_blocks=3,
        confirm_winners=True, portfolio_rounds=3, near_miss_compounds=True,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# The frozen clock and ids, and the fingerprint
# ---------------------------------------------------------------------------


class _Clock:
    """``models.datetime`` for ``utc_now``: every call reads ``NOW``."""

    @staticmethod
    def now(tz: tzinfo | None = None) -> datetime:
        return NOW if tz is not None else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Freeze ``utc_now`` and number ``new_id`` (the only readers of the two
    module names). Every model of ``models`` is built first: an incomplete
    one would resolve its annotations against the patch."""
    incomplete = [
        cls for cls in vars(models).values()
        if inspect.isclass(cls) and issubclass(cls, BaseModel)
        and cls.__module__ == models.__name__ and not cls.__pydantic_complete__
    ]  # fmt: skip
    for cls in incomplete:  # resolved now, against the real names
        cls.model_rebuild()
    counter = itertools.count(1)
    ids = SimpleNamespace(uuid4=lambda: uuid.UUID(int=next(counter)))
    monkeypatch.setattr(models, "datetime", _Clock)
    monkeypatch.setattr(models, "uuid", ids)
    yield


def _canon(value: object) -> object:
    """``value`` as plain JSON data: models dumped, dataclasses and named
    tuples as their fields, enums as values, paths as text."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _canon(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return {k: _canon(v) for k, v in value._asdict().items()}
    if isinstance(value, Mapping):
        return {str(k): _canon(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_canon(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path | datetime):
        return str(value)
    assert value is None or isinstance(value, str | int | float), type(value)
    return value


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _aliased(text: str) -> str:
    """Every uuid as ``<id-N>``, numbered by first appearance."""
    seen: dict[str, str] = {}
    return _UUID.sub(lambda m: seen.setdefault(m.group(), f"<id-{len(seen)}>"), text)


@dataclasses.dataclass(frozen=True)
class _Run:
    """The run's seams, its final state, the compiled graph's nodes and
    edges, every ``main.run_config`` call (args, kwargs, result) and the
    nodes it visited in order (its checkpoint history)."""

    seams: _Seams
    state: EngineState
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str, bool, str | None], ...]
    visits: tuple[str, ...]
    configs: tuple[dict[str, object], ...]


def _record(run: _Run) -> dict[str, object]:
    seams, state = run.seams, run.state
    dumped = dump_state(state)
    assert dumped.pop("stack", None) is None  # X2-DT's key (U1): None when off
    delivery, review = state["delivery"], state["review_delivery"]
    return {
        "configs": run.configs,
        "nodes": run.nodes,
        "edges": run.edges,
        "visits": run.visits,
        "generator": seams.generator.calls,
        "runner": seams.runner.calls,
        "baseline": seams.baseline.calls,
        "calibrator": seams.calibrator.calls,
        "preflight": seams.preflight.calls,
        "understander": seams.understander.calls,
        "profiler": seams.profiler.calls,
        "combiner": seams.combiner.calls,
        "publisher": seams.publisher.calls,
        "repository": seams.repository.calls,
        "events": [(e.phase, e.level, e.message, e.data) for e in state["events"]],
        "state": dumped,
        "report": None if delivery is None else delivery.report_markdown,
        "review_report": None if review is None else review.report_markdown,
    }


def _fingerprint(record: Mapping[str, object]) -> str:
    text = json.dumps(_canon(record), sort_keys=True, allow_nan=False)
    return hashlib.sha256(_aliased(text).encode()).hexdigest()


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@pytest.fixture
def run(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    baseline_script: ScriptedOutcome,
    monkeypatch: pytest.MonkeyPatch,
) -> _Run:
    configs: list[dict[str, object]] = []
    real = main.run_config

    def spied(*args: Any, **kwargs: Any) -> RunnableConfig:  # noqa: ANN401
        config = real(*args, **kwargs)
        configs.append({"args": args, "kwargs": kwargs, "result": config})
        return config

    monkeypatch.setattr(main, "run_config", spied)
    seams = _seams(sample_project, sample_workload, baseline_script)
    orchestrator = Orchestrator(context=_context(seams))
    result = orchestrator.run(
        sample_project, [sample_workload], [sample_objective], sample_guardrails,
        run_id=RUN_ID, max_rounds=3, max_cost_usd=CAP_USD,
    )  # fmt: skip
    assert result.status == "done", result.state["error"]
    drawn = orchestrator.graph.get_graph()
    edges = sorted(
        (e.source, e.target, e.conditional, None if e.data is None else str(e.data))
        for e in drawn.edges
    )
    history = orchestrator.graph.get_state_history(
        {"configurable": {"thread_id": RUN_ID}}
    )
    visits = [name for snap in reversed(list(history)) for name in snap.next]
    return _Run(seams, result.state, tuple(sorted(drawn.nodes)), tuple(edges),
                tuple(visits), tuple(configs))  # fmt: skip


def test_the_stacking_off_run_is_todays(run: _Run) -> None:
    """
    GIVEN an X2-D-shaped three-round run over fakes, stacking off
    THEN the graph, the config, every request, repository call and event,
         the final state and both reports hash to what they did on 4f176d7;
         the facts beside it say what went wrong first
    """
    seams, state = run.seams, run.state
    assert run.visits[:8] == ("__start__", "connect", "understand", "define",
                              "baseline", "profile", "research", "hypotheses")  # fmt: skip
    assert run.visits.count("hypotheses") == 3
    assert run.visits[-4:] == ("combine", "deliver", "learn", "watch")
    assert "restack" not in run.nodes
    assert [(c["args"], c["kwargs"]) for c in run.configs] == [((RUN_ID, 3), {})]
    calls = seams.generator.calls
    assert [c["call_index"] for c in calls] == [0, 1, 2]
    assert [c["commit"] for c in calls] == [FAKE_COMMIT] * 3
    assert calls[0]["verdicts"] is None
    assert [len(cast(Sequence[str], c["avoid_titles"])) for c in calls] == [0, 3, 6]
    outcomes = [(t.round, v.outcome) for v in state["verdicts"]
                for t in state["trials"] if t.id == v.trial_id]  # fmt: skip
    keep, reject = VerdictOutcome.keep, VerdictOutcome.reject
    inconclusive, review = VerdictOutcome.inconclusive, VerdictOutcome.review
    assert outcomes == [
        (1, keep), (1, keep), (1, inconclusive),
        (2, reject), (2, reject), (2, inconclusive),
        (3, keep), (3, keep), (3, review), (3, inconclusive),
    ]  # fmt: skip
    (compound,) = [h for h in state["hypotheses"] if COMPOUND_TAG in h.tags]
    assert compound.id == COMPOUND.id
    replays = [c for c in seams.runner.calls if c["kind"] == "replay"]
    assert [(c["round"], c["parents"]) for c in replays] == [
        (3, [(f"t-{TWEAK.id}", _commit(TWEAK.id)), (f"t-{PAD.id}", _commit(PAD.id))])
    ]
    combines = seams.combiner.calls
    assert len(combines) == 8
    assert {c.base_commit for c in combines} == {FAKE_COMMIT}
    assert [[k.commit for k in c.kept] for c in combines] == [
        [_commit(CACHE.id)], [_commit(BATCH.id)],
        [_commit(COMPOUND.id)], [_commit(MASK.id)], [_commit(BF16.id)],
        [_commit(VOCAB.id)],
        [_commit(CACHE.id), _commit(MASK.id), _commit(BATCH.id), _commit(COMPOUND.id)],
        [_commit(BF16.id)],
    ]  # fmt: skip
    assert [(p.branch, p.tip, p.base) for p in seams.publisher.calls] == [
        (f"engine/run-{RUN_ID}", RUN_TIP, FAKE_COMMIT),
        (f"engine/review-{RUN_ID}", REVIEW_TIP, FAKE_COMMIT),
    ]
    kept = {v.id: v.hypothesis_id for v in state["verdicts"]}
    assert [kept[i] for i in state["kept_verdict_ids"]] == [
        CACHE.id,
        MASK.id,
        COMPOUND.id,
    ]
    assert [c[2] for c in seams.baseline.calls] == [FAKE_COMMIT]
    assert [c[2] for c in seams.calibrator.calls] == [FAKE_COMMIT]
    assert [c.commit for c in seams.profiler.calls] == [FAKE_COMMIT]
    methods = [method for method, _ in seams.repository.calls]
    assert methods.count("save_lesson") == len(state["lessons"])
    assert methods.count("save_verdict") == len(state["verdicts"])
    assert _fingerprint(_record(run)) == GOLDEN
