"""The runners' counted runs (G6a): one per side, attached as ``op_calls`` rows.

With ``count_ops`` a runner adds one counted run per workload and side after
its measurements and the suite: a paired trial counts the twin (its
``base_measurements``) and itself, an unpaired one itself, the baseline
runner the base. Off (the default) nothing extra launches. A counted run that
fails is a note, never a failed trial or an ``EngineError``. Fakes: ``Clock``
stands for ``procrun.run_once`` (it answers the timed runs and the suite and
writes a count document for each shim launch: ``calls(phase)``), ``Edits``
for ``ClaudeEditor``; the last test runs the real shim through the real
``run_once`` and real git, isolation off.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Baseline,
    ChangeClass,
    Direction,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Measurement,
    Objective,
    ObjectiveKind,
    Project,
    RunStats,
    Trial,
    TrialStatus,
    Workload,
)
from autonomous_ai_agents.execution.measure import (
    CALLEE_KEY,
    METRIC_OP_CALLS,
    METRIC_UNIT_CALLS,
    OPCOUNT_SHIM,
    OUT_CALLS_KEY,
    UNIT_KEY,
)
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample, run_once
from autonomous_ai_agents.execution.protocols import (
    CodeEditor,
    EditResult,
    EditTask,
    TrialBrief,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import (
    GitBaselineRunner,
    GitTrialRunner,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.optimization.judges import OpCountJudge

DEDUPE = Path(__file__).resolve().parents[1] / "fixtures" / "dedupe_repo"
PY, TESTS, CORE = sys.executable, 11, "dedupe/core.py"
BASE_CORE = (DEDUPE / CORE).read_text()
SAME = BASE_CORE + "# same code, another commit\n"
FEWER = BASE_CORE.replace(
    "    result: list[int] = []\n    for item in items:\n"
    "        if item not in result:\n            result.append(item)\n    return result\n",
    "    return list(dict.fromkeys(items))\n",
)
ENV = {"PATH": os.defpath, "HOME": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull}
ENV |= {"GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
ENV |= {f"GIT_{r}_{k}": v for r in ("AUTHOR", "COMMITTER") for k, v in
        (("NAME", "User"), ("EMAIL", "u@example.invalid"), ("DATE", "@1700000000 +0000"))}  # fmt: skip


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], env=ENV, capture_output=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.decode().strip()


def counts(python: int, c: int) -> bytes:
    return f'{{"version": 1, "python_calls": {python}, "c_calls": {c}}}'.encode()


@dataclass
class Clock:
    """``run_once``: ``calls`` records each launch as ``<kind> <phase>`` (kind
    ``run``, ``suite`` or ``count``); a count launch writes ``doc(phase)``
    into its OUT, or exits 1 when ``doc`` gives ``None``."""

    run_dir: Path
    doc: Callable[[str], bytes | None] = lambda phase: counts(70, 30)
    calls: list[str] = field(default_factory=list)

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        phase = cwd.relative_to(self.run_dir).parts[0]
        exit, err = 0, b""
        if "unittest" in argv:
            self.calls.append(f"suite {phase}")
            err = f"Ran {TESTS} tests in 0.010s\n\nOK\n".encode()
        elif str(OPCOUNT_SHIM) in argv:
            self.calls.append(f"count {phase}")
            written = self.doc(phase)
            if written is None:
                exit, err = 1, b"RuntimeError: no profiler\n"
            else:
                Path(argv[argv.index(str(OPCOUNT_SHIM)) + 1]).write_bytes(written)
        else:
            self.calls.append(f"run {phase}")
        return RunSample(100_000_000, 0.1, 0.0, 1 << 20, exit, True, True, "1" * 64, b"", 0, err)  # fmt: skip


@dataclass
class Edits:
    text: str

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        (worktree / CORE).write_text(self.text)
        return EditResult({CORE: len(self.text.encode())}, cost_usd=0.01, tokens_used=10)  # fmt: skip


@dataclass
class Rig:
    repo: Path
    base: str
    project: Project
    clock: Clock
    notes: list[str] = field(default_factory=list)
    network: IsolationMode = "required"
    run: object = None

    def workload(self) -> Workload:
        return Workload(
            project_id=self.project.id, name="dedupe", warmup_runs=0, runs=5,
            command=(PY, "-m", "dedupe.main", "2000"), timeout_s=60.0,
        )  # fmt: skip

    def options(self) -> dict[str, object]:
        return {
            "network": self.network, "fs": self.network, "platform": "linux",
            "base_env": {"PATH": "/usr/bin"},
            "run": self.clock if self.run is None else self.run,
            "on_note": self.notes.append,
        }  # fmt: skip

    def trial(
        self, text: str, workloads: Sequence[Workload], baseline: Baseline | None = None,
        **runner: bool,
    ) -> tuple[Trial, Hypothesis]:  # fmt: skip
        def build(
            *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
        ) -> CodeEditor:
            return Edits(text)

        hypothesis = Hypothesis(
            project_id=self.project.id, source=HypothesisSource.novel,
            title="dedupe with a dict", rationale="one C call",
            change_class=ChangeClass.efficiency, expected_gain=0.5,
            provability=0.9, risk=0.1,
        )  # fmt: skip
        trial = GitTrialRunner(
            self.project, editor=build, **self.options(), **runner,  # type: ignore[arg-type]
        ).run(
            hypothesis, workloads, baseline or self.baseline(workloads), round=1,
            budget_usd=1.0,
            branch=f"{settings.TRIAL_BRANCH_PREFIX}trial-run1-{hypothesis.id}",
            brief=TrialBrief(None, (), DEFAULT_PROTECTED_PATTERNS, fix_retries_left=1),
        )  # fmt: skip
        return trial, hypothesis

    def baseline(self, workloads: Sequence[Workload]) -> Baseline:
        rows = tuple(
            Measurement(workload_id=w.id, metric=METRIC_TESTS_PASSED,
                        stats=RunStats.from_samples((1.0,), unit="bool"),
                        samples=(1.0,), hardware={"tests_counted": TESTS})
            for w in workloads
        )  # fmt: skip
        objective = Objective(
            project_id=self.project.id, kind=ObjectiveKind.runtime, description="x",
            metric=METRIC_WALL_TIME_S, direction=Direction.minimize,
        )  # fmt: skip
        return Baseline(commit=self.base, measurements=rows, objectives=(objective,))

    def baseline_runner(self, **runner: bool) -> GitBaselineRunner:
        return GitBaselineRunner(self.project, **self.options(), **runner)  # type: ignore[arg-type]

    def nothing_left(self) -> None:
        assert git(self.repo, "worktree", "list", "--porcelain").count("worktree ") == 1
        assert not self.clock.run_dir.exists()


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    repo = root / "user"
    shutil.copytree(DEDUPE, repo, ignore=shutil.ignore_patterns("__pycache__"))
    git(root, "init", "-q", "-b", "main", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    unittest = (PY, "-m", "unittest", "discover", "-s", "tests", "-t", ".")
    project = Project(name="dedupe", root_path=str(repo), test_command=unittest)
    return Rig(repo, git(repo, "rev-parse", "HEAD"), project, Clock(root / "wt-root" / "run1"))  # fmt: skip


def op_rows(rows: Sequence[Measurement]) -> list[Measurement]:
    return [m for m in rows if m.metric == METRIC_OP_CALLS]


def test_a_paired_trial_counts_the_twin_and_itself_once_after_the_suite(
    rig: Rig,
) -> None:
    """
    GIVEN a paired trial with ``count_ops``
    WHEN it runs
    THEN after the ABBA runs and the suite, one counted run on the twin and
        one on the trial; the twin's row is in ``base_measurements`` (no trial
        id), the trial's last in ``measurements`` (its id); nothing is left
    """
    rig.clock.doc = lambda phase: counts(90, 40) if phase.startswith("twin-") else counts(70, 30)  # fmt: skip
    workload = rig.workload()

    trial, hypothesis = rig.trial(SAME, [workload], paired=True, count_ops=True)

    a, b = f"twin-trial-{hypothesis.id}", f"trial-{hypothesis.id}"
    timed = [f"run {s}" for i in range(5) for s in ((a, b) if i % 2 == 0 else (b, a))]
    assert rig.clock.calls == [*timed, f"suite {b}", f"count {a}", f"count {b}"]
    assert trial.status is TrialStatus.measured
    [base] = op_rows(trial.base_measurements)
    [own] = op_rows(trial.measurements)
    assert (base.samples, base.trial_id) == ((130.0,), None)
    assert (own.samples, own.trial_id) == ((100.0,), trial.id)
    assert trial.measurements[-1] == own
    assert base.workload_id == own.workload_id == workload.id
    result = OpCountJudge().evaluate(rig.baseline([workload]).model_copy(update={"measurements": trial.base_measurements}), trial)  # fmt: skip
    assert result.details["change"] == pytest.approx(100 / 130 - 1)
    rig.nothing_left()


def test_an_unpaired_trial_counts_itself_and_the_baseline_runner_the_base(
    rig: Rig,
) -> None:
    workload = rig.workload()

    rows = rig.baseline_runner(count_ops=True).measure([workload], run_id="run1", commit=rig.base)  # fmt: skip
    trial, hypothesis = rig.trial(SAME, [workload], count_ops=True)

    b = f"trial-{hypothesis.id}"
    assert rig.clock.calls[-2:] == [f"suite {b}", f"count {b}"]
    assert rig.clock.calls[:7] == [*["run baseline"] * 5, "suite baseline", "count baseline"]  # fmt: skip
    [base] = op_rows(rows)
    assert (base.samples, base.trial_id) == ((100.0,), None)
    assert trial.base_measurements == ()
    assert [m.trial_id for m in op_rows(trial.measurements)] == [trial.id]


def test_without_count_ops_nothing_extra_launches(rig: Rig) -> None:
    workload = rig.workload()

    rows = rig.baseline_runner().measure([workload], run_id="run1", commit=rig.base)
    trial, _ = rig.trial(SAME, [workload], paired=True)

    assert not any(call.startswith("count") for call in rig.clock.calls)
    assert op_rows((*rows, *trial.measurements, *trial.base_measurements)) == []


def test_a_failed_counted_run_is_a_note_never_a_failed_trial(rig: Rig) -> None:
    """The twin's counted run exits 1: the trial is still measured, the twin
    has no count (so the judge records nothing), and a note says why."""
    rig.clock.doc = lambda phase: None if phase.startswith("twin-") else counts(1, 1)
    workload = rig.workload()

    trial, hypothesis = rig.trial(SAME, [workload], paired=True, count_ops=True)

    assert trial.status is TrialStatus.measured and trial.error is None
    assert op_rows(trial.base_measurements) == []
    assert len(op_rows(trial.measurements)) == 1
    prefix = (
        f"trial for hypothesis {hypothesis.id}: workload 'dedupe' A is not counted: "
    )
    assert any(n.startswith(prefix) and "exit status 1" in n for n in rig.notes)


@pytest.mark.skipif(sys.platform != "linux", reason="isolation off is Linux's")
def test_real_counts_hold_an_a_a_pair_equal_and_see_the_calls_a_change_removes(
    rig: Rig,
) -> None:
    """
    GIVEN the dedupe fixture, the real shim, the real ``run_once`` and real git
    WHEN a paired trial that only adds a comment (A/A) and one that replaces
        the append loop by ``dict.fromkeys`` are counted
    THEN the A/A twin and trial count exactly the same, and the second trial
        counts fewer calls than its twin
    """
    rig.network, rig.run = "off", run_once
    workload = rig.workload()

    same, _ = rig.trial(SAME, [workload], paired=True, count_ops=True)
    fewer, _ = rig.trial(FEWER, [workload], paired=True, count_ops=True)

    [a], [a2] = op_rows(same.base_measurements), op_rows(same.measurements)
    assert a.samples == a2.samples and a.hardware == a2.hardware
    [b], [b2] = op_rows(fewer.base_measurements), op_rows(fewer.measurements)
    assert b.samples == a.samples
    assert b2.samples[0] < b.samples[0] - 1000
    rig.nothing_left()


# ---------------------------------------------------------------------------
# Units (emergence round 1, S1): the brief's hot functions ride the counted run
# ---------------------------------------------------------------------------

UNIT = f"{CORE}::unique_in_order"


def hot(symbol: str, path: str = CORE, *, project: str = "p") -> Hotspot:
    return Hotspot(project_id=project, workload_id="w", file_path=path, symbol=symbol,
                   self_time_s=0.1, total_time_s=0.2, share=0.5)  # fmt: skip


@dataclass
class Argv:
    """``run_once`` in front of ``Clock``: keeps each counted launch's argv
    and answers it with a version 2 document for the units it names."""

    clock: Clock
    counted: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], cwd: Path, *rest: object, **kw: object) -> RunSample:  # fmt: skip
        sample = self.clock(argv, cwd, *rest, **kw)  # type: ignore[arg-type]
        if str(OPCOUNT_SHIM) in argv and "--unit" in argv:
            self.counted.append(tuple(argv))
            units = [argv[i + 1] for i, a in enumerate(argv) if a == "--unit"]
            twin = cwd.relative_to(self.clock.run_dir).parts[0].startswith("twin-")
            n = 10 if twin else 4
            doc = {"version": 2, "python_calls": 70, "c_calls": 30, "units": [
                {"unit": u, "calls": 1, "out": n, "callees": [["append", n]]} for u in units]}  # fmt: skip
            Path(argv[argv.index(str(OPCOUNT_SHIM)) + 1]).write_text(json.dumps(doc))
        return sample


def unit_trial(rig: Rig, hotspots: Sequence[Hotspot], **runner: object) -> Trial:
    rig.run = argv = Argv(rig.clock)
    hypothesis = Hypothesis(
        project_id=rig.project.id, source=HypothesisSource.novel, title="dict",
        rationale="r", change_class=ChangeClass.efficiency, expected_gain=0.5,
        provability=0.9, risk=0.1,
    )  # fmt: skip
    workload = rig.workload()
    trial = GitTrialRunner(
        rig.project, editor=lambda **_: Edits(SAME), **rig.options(), **runner,  # type: ignore[arg-type]
    ).run(
        hypothesis, [workload], rig.baseline([workload]), round=1, budget_usd=1.0,
        branch=f"{settings.TRIAL_BRANCH_PREFIX}trial-run1-{hypothesis.id}",
        brief=TrialBrief(None, tuple(hotspots), DEFAULT_PROTECTED_PATTERNS),
    )  # fmt: skip
    rig.unit_argv = argv.counted  # type: ignore[attr-defined]
    return trial


def unit_rows(rows: Sequence[Measurement]) -> list[tuple[str, object, float]]:
    return [(str(m.hardware[UNIT_KEY]), m.hardware.get(CALLEE_KEY, "-"), m.samples[0])
            for m in rows if m.metric == METRIC_UNIT_CALLS]  # fmt: skip


def test_with_units_the_briefs_hot_functions_are_counted_on_both_sides(
    rig: Rig,
) -> None:
    """
    GIVEN a paired trial with ``count_ops`` and ``count_units`` whose brief
        names ``unique_in_order``, ``<module>`` (no function), a path that is
        not a unit and the same function twice
    WHEN it runs
    THEN the twin's and the trial's counted runs each carry the one unit,
        the unit rows land beside the ``op_calls`` rows (the twin's in
        ``base_measurements``), and the op-count judge reads what it reads
        without units
    """
    spots = [hot("unique_in_order"), hot("<module>"), hot("f", "a b.py"), hot("unique_in_order")]  # fmt: skip

    trial = unit_trial(rig, spots, paired=True, count_ops=True, count_units=True)

    assert trial.status is TrialStatus.measured
    flags = [argv[argv.index(str(OPCOUNT_SHIM)) + 2 :][:2] for argv in rig.unit_argv]  # type: ignore[attr-defined]
    assert flags == [("--unit", UNIT)] * 2
    assert unit_rows(trial.base_measurements) == [
        (UNIT, "-", 1.0),
        (UNIT, "append", 10.0),
    ]
    assert unit_rows(trial.measurements) == [(UNIT, "-", 1.0), (UNIT, "append", 4.0)]
    [base] = [m for m in trial.base_measurements if m.metric == METRIC_UNIT_CALLS][:1]
    assert (base.trial_id, base.hardware[OUT_CALLS_KEY]) == (None, 10)
    assert (
        len(op_rows(trial.measurements)) == len(op_rows(trial.base_measurements)) == 1
    )
    result = OpCountJudge().evaluate(rig.baseline([rig.workload()]).model_copy(update={"measurements": trial.base_measurements}), trial)  # fmt: skip
    assert result.details["change"] == 0.0


def test_at_most_four_units_ride_a_counted_run(rig: Rig) -> None:
    spots = [hot(f"f{i}") for i in range(6)]

    unit_trial(rig, spots, paired=True, count_ops=True, count_units=True)

    [argv, _] = rig.unit_argv  # type: ignore[attr-defined]
    assert [a for a in argv if a.startswith(f"{CORE}::")] == [
        f"{CORE}::f{i}" for i in range(4)
    ]


@pytest.mark.parametrize("mode", ["off", "record"])
def test_count_units_defaults_to_the_count_contract_setting(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(settings, "IDEAS_COUNT_CONTRACT", mode)

    trial = unit_trial(rig, [hot("unique_in_order")], paired=True, count_ops=True)

    assert len(rig.unit_argv) == (2 if mode == "record" else 0)  # type: ignore[attr-defined]
    assert bool(unit_rows(trial.measurements)) is (mode == "record")


def test_units_without_count_ops_launch_nothing_extra(rig: Rig) -> None:
    trial = unit_trial(rig, [hot("unique_in_order")], paired=True, count_units=True)

    assert not any(call.startswith("count") for call in rig.clock.calls)
    assert unit_rows(trial.measurements) == []
