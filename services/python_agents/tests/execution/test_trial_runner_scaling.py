"""The runners' scaling runs (G6b): attached as ``scale_wall_time_s`` rows.

With ``scaling`` a runner scales every workload that has a size setting
after its measurements, the suite and any counted run: a paired trial
scales the twin (its ``base_measurements``) and itself interleaved, an
unpaired one itself, the baseline runner the base. Off (the default), or for
a workload without a setting, nothing extra launches. A scaling run that
fails is a note, never a failed trial or an ``EngineError``. Fakes:
``Clock`` stands for ``procrun.run_once`` (it answers the timed runs and the
suite, and a scaling launch, recognised by the size variable in its
environment, with a time from ``time(phase, size)``), ``Edits`` for
``ClaudeEditor``; real git, the dedupe fixture.
"""

from __future__ import annotations

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
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Baseline,
    ChangeClass,
    Direction,
    Hypothesis,
    HypothesisSource,
    Measurement,
    Objective,
    ObjectiveKind,
    Project,
    RunStats,
    ScaleSetting,
    Trial,
    TrialStatus,
    Workload,
)
from autonomous_ai_agents.execution.measure import (
    METRIC_OP_CALLS,
    METRIC_SCALE_WALL_S,
    OPCOUNT_SHIM,
    SCALE_SIZE_KEY,
)
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
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
from autonomous_ai_agents.optimization.judges import ScalingJudge

DEDUPE = Path(__file__).resolve().parents[1] / "fixtures" / "dedupe_repo"
PY, TESTS, CORE, VAR = sys.executable, 11, "dedupe/core.py", "DEDUPE_N"
SAME = (DEDUPE / CORE).read_text() + "# same code, another commit\n"
ENV = {"PATH": os.defpath, "HOME": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull}
ENV |= {"GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
ENV |= {f"GIT_{r}_{k}": v for r in ("AUTHOR", "COMMITTER") for k, v in
        (("NAME", "User"), ("EMAIL", "u@example.invalid"), ("DATE", "@1700000000 +0000"))}  # fmt: skip


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], env=ENV, capture_output=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.decode().strip()


@dataclass
class Clock:
    """``run_once``: ``calls`` records each launch as ``<kind> <phase>``
    (kind ``run``, ``suite``, ``count`` or ``scale``, a scale launch with
    its size); a scale launch answers ``time(phase, size)`` seconds, or
    exits 1 when it gives ``None``."""

    run_dir: Path
    time: Callable[[str, int], float | None] = lambda phase, size: 1e-8 * size**2
    calls: list[str] = field(default_factory=list)

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        phase = cwd.relative_to(self.run_dir).parts[0]
        exit, err, wall = 0, b"", 100_000_000
        if "unittest" in argv:
            self.calls.append(f"suite {phase}")
            err = f"Ran {TESTS} tests in 0.010s\n\nOK\n".encode()
        elif str(OPCOUNT_SHIM) in argv:
            self.calls.append(f"count {phase}")
            out = Path(argv[argv.index(str(OPCOUNT_SHIM)) + 1])
            out.write_bytes(b'{"version": 1, "python_calls": 7, "c_calls": 3}')
        elif VAR in env:
            self.calls.append(f"scale {phase} {env[VAR]}")
            seconds = self.time(phase, int(env[VAR]))
            if seconds is None:
                exit, err = 1, b"MemoryError\n"
            else:
                wall = round(seconds * 1e9)
        else:
            self.calls.append(f"run {phase}")
        return RunSample(wall, 0.1, 0.0, 1 << 20, exit, True, True, "1" * 64, b"", 0, err)  # fmt: skip


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

    def workload(self, scaled: bool = True) -> Workload:
        scale = (
            ScaleSetting(env_var=VAR, sizes=(1000, 4000), runs=2) if scaled else None
        )
        return Workload(
            project_id=self.project.id, name="dedupe", warmup_runs=0, runs=5,
            command=(PY, "-m", "dedupe.main"), timeout_s=60.0, scale=scale,
        )  # fmt: skip

    def options(self) -> dict[str, object]:
        return {
            "network": "required", "fs": "required", "platform": "linux",
            "base_env": {"PATH": "/usr/bin"}, "run": self.clock,
            "on_note": self.notes.append,
        }  # fmt: skip

    def trial(self, workloads: Sequence[Workload], **runner: bool) -> tuple[Trial, Hypothesis]:  # fmt: skip
        def build(
            *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
        ) -> CodeEditor:
            return Edits(SAME)

        hypothesis = Hypothesis(
            project_id=self.project.id, source=HypothesisSource.novel,
            title="dedupe with a dict", rationale="one C call",
            change_class=ChangeClass.efficiency, expected_gain=0.5,
            provability=0.9, risk=0.1,
        )  # fmt: skip
        trial = GitTrialRunner(
            self.project, editor=build, **self.options(), **runner,  # type: ignore[arg-type]
        ).run(
            hypothesis, workloads, self.baseline(workloads), round=1, budget_usd=1.0,
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


def scale_rows(rows: Sequence[Measurement]) -> list[tuple[str | None, object, tuple[float, ...]]]:  # fmt: skip
    return [(m.trial_id, m.hardware[SCALE_SIZE_KEY], m.samples) for m in rows if m.metric == METRIC_SCALE_WALL_S]  # fmt: skip


def test_a_paired_trial_scales_the_twin_and_itself_interleaved_after_the_count(
    rig: Rig,
) -> None:
    """
    GIVEN a paired trial with ``count_ops`` and ``scaling``, the twin
        quadratic and the trial linear on the clock
    WHEN it runs
    THEN after the ABBA runs, the suite and the counted runs, the sizes run
        interleaved on both sides; the twin's rows are in
        ``base_measurements`` (no trial id), the trial's last in
        ``measurements``; the judge reads the rates 2 and 1 from them
    """
    rig.clock.time = lambda phase, size: 1e-8 * size**2 if phase.startswith("twin-") else 1e-5 * size  # fmt: skip
    workload = rig.workload()

    trial, hypothesis = rig.trial([workload], paired=True, count_ops=True, scaling=True)

    a, b = f"twin-trial-{hypothesis.id}", f"trial-{hypothesis.id}"
    timed = [f"run {s}" for i in range(5) for s in ((a, b) if i % 2 == 0 else (b, a))]
    scaled = [f"scale {a} 1000", f"scale {b} 1000", f"scale {b} 4000", f"scale {a} 4000",
              f"scale {a} 4000", f"scale {b} 4000", f"scale {b} 1000", f"scale {a} 1000"]  # fmt: skip
    assert rig.clock.calls == [
        *timed,
        f"suite {b}",
        f"count {a}",
        f"count {b}",
        *scaled,
    ]
    assert trial.status is TrialStatus.measured
    assert scale_rows(trial.base_measurements) == [(None, 1000, (0.01, 0.01)), (None, 4000, (0.16, 0.16))]  # fmt: skip
    assert scale_rows(trial.measurements) == [(trial.id, 1000, (0.01, 0.01)), (trial.id, 4000, (0.04, 0.04))]  # fmt: skip
    assert trial.measurements[-1].metric == METRIC_SCALE_WALL_S
    base = rig.baseline([workload]).model_copy(update={"measurements": trial.base_measurements})  # fmt: skip
    details = ScalingJudge().evaluate(base, trial).details
    assert details["base_rate"] == pytest.approx(2.0)
    assert details["trial_rate"] == pytest.approx(1.0)
    rig.nothing_left()


def test_an_unpaired_trial_scales_itself_and_the_baseline_runner_the_base(
    rig: Rig,
) -> None:
    workload = rig.workload()

    runner = GitBaselineRunner(rig.project, **rig.options(), scaling=True)  # type: ignore[arg-type]
    rows = runner.measure([workload], run_id="run1", commit=rig.base)
    trial, hypothesis = rig.trial([workload], scaling=True)

    b = f"trial-{hypothesis.id}"
    sizes = ["1000", "4000", "4000", "1000"]
    assert rig.clock.calls[:10] == [*["run baseline"] * 5, "suite baseline", *[f"scale baseline {n}" for n in sizes]]  # fmt: skip
    assert rig.clock.calls[-5:] == [f"suite {b}", *[f"scale {b} {n}" for n in sizes]]
    assert [r[:2] for r in scale_rows(rows)] == [(None, 1000), (None, 4000)]
    assert trial.base_measurements == ()
    assert [r[:2] for r in scale_rows(trial.measurements)] == [(trial.id, 1000), (trial.id, 4000)]  # fmt: skip
    assert not any(m.metric == METRIC_OP_CALLS for m in trial.measurements)


def test_without_scaling_or_a_size_setting_nothing_extra_launches(rig: Rig) -> None:
    scaled, plain = rig.workload(), rig.workload(scaled=False)

    off, _ = rig.trial([scaled], paired=True)
    on, _ = rig.trial([plain], paired=True, scaling=True)

    assert not any(call.startswith("scale") for call in rig.clock.calls)
    rows = (*off.measurements, *off.base_measurements, *on.measurements, *on.base_measurements)  # fmt: skip
    assert scale_rows(rows) == []


def test_a_failed_scaling_run_is_a_note_never_a_failed_trial(rig: Rig) -> None:
    """The twin fails at the large size: the trial is still measured, no side
    has scaling rows (so the judge records nothing), and a note says why."""
    rig.clock.time = lambda phase, size: None if phase.startswith("twin-") and size == 4000 else 0.1  # fmt: skip

    trial, hypothesis = rig.trial([rig.workload()], paired=True, scaling=True)

    assert trial.status is TrialStatus.measured and trial.error is None
    assert scale_rows((*trial.measurements, *trial.base_measurements)) == []
    prefix = f"trial for hypothesis {hypothesis.id}: workload 'dedupe' is not scaled: "
    assert any(n.startswith(prefix) and "exit status 1" in n for n in rig.notes)
    rig.nothing_left()
