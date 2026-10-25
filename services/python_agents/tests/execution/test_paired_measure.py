"""Paired trials and the noise calibration (D41 a and c), on real git (U20).

A paired trial is measured ABBA against a twin worktree at its base
(``twin-trial-<hyp>``), the suite once on the trial; ``calibrate`` measures
the base against a second base worktree in A/A blocks. Fakes: ``Clock``
stands for ``procrun.run_once`` (scripted wall times per phase and launch
count, so nothing depends on real timing), ``Edits`` for ``ClaudeEditor``.
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
from autonomous_ai_agents.common.errors import (
    EngineError,
    RepoTamperedError,
    spend_of,
)
from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_PEAK_RSS_BYTES,
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
    Trial,
    TrialStatus,
    Workload,
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
from autonomous_ai_agents.orchestrator.nodes import NoiseCalibrator

DEDUPE = Path(__file__).resolve().parents[1] / "fixtures" / "dedupe_repo"
PY, TESTS, CORE = sys.executable, 11, "dedupe/core.py"
BASE_CORE = (DEDUPE / CORE).read_text()
SAME = BASE_CORE + "# same code, another commit\n"
RAISING = "        if item not in seen:\n"
BROKEN = BASE_CORE.replace("        if item not in result:\n", RAISING + "            seen.add(item)\n")  # fmt: skip
FIXED = BROKEN.replace("    result: list[int] = []\n", "    seen: set[int] = set()\n    result: list[int] = []\n")  # fmt: skip
LINE = BROKEN.splitlines().index(RAISING.rstrip("\n")) + 1
ENV = {"PATH": os.defpath, "HOME": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull}
ENV |= {"GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
ENV |= {f"GIT_{r}_{k}": v for r in ("AUTHOR", "COMMITTER") for k, v in
        (("NAME", "User"), ("EMAIL", "u@example.invalid"), ("DATE", "@1700000000 +0000"))}  # fmt: skip
TIME = (METRIC_WALL_TIME_S, METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES)


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], env=ENV, capture_output=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.decode().strip()


@dataclass
class Clock:
    """``run_once``: ``wall_ms(phase, n)`` for the n-th workload launch (0-based,
    over the whole test); ``calls`` records each launch's phase (``suite <phase>``
    for the suite); ``crash_on`` crashes the next ``crashes`` workload launches
    in a phase starting with it (a fixable NameError in core.py), after
    letting ``skip`` of them through."""

    run_dir: Path
    wall_ms: Callable[[str, int], float] = lambda phase, n: 100.0
    crash_on: str = "-"
    crashes: int = 0
    skip: int = 0
    calls: list[str] = field(default_factory=list)
    heads: dict[str, str] = field(default_factory=dict)

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        phase = cwd.relative_to(self.run_dir).parts[0]
        self.heads.setdefault(phase, git(cwd, "rev-parse", "HEAD"))
        if "unittest" in argv:
            self.calls.append(f"suite {phase}")
            err = f"Ran {TESTS} tests in 0.010s\n\nOK\n"
            return RunSample(1, 0.0, 0.0, 1, 0, True, True, "1" * 64, b"", 0, err.encode())  # fmt: skip
        wall = self.wall_ms(phase, sum(not c.startswith("suite") for c in self.calls))
        self.calls.append(phase)
        exit, err = 0, ""
        if phase.startswith(self.crash_on) and self.crashes and self.skip:
            self.skip -= 1
        elif phase.startswith(self.crash_on) and self.crashes:
            self.crashes -= 1
            exit, err = (
                1,
                (
                    f'Traceback (most recent call last):\n  File "{cwd}/{CORE}", line {LINE},'
                    f" in unique_in_order\n{RAISING}NameError: name 'seen' is not defined\n"
                ),
            )
        cpu = wall / 1000
        return RunSample(int(wall * 1e6), cpu, 0.0, 1 << 20, exit, True, True,
                         "1" * 64, b"", 0, err.encode())  # fmt: skip


@dataclass
class Edits:
    """Writes one core.py text per attempt; records the tasks."""

    attempts: list[str]
    tasks: list[EditTask] = field(default_factory=list)

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        self.tasks.append(task)
        text = self.attempts[len(self.tasks) - 1]
        (worktree / CORE).write_text(text)
        return EditResult({CORE: len(text.encode())}, cost_usd=0.01, tokens_used=10)


@dataclass
class Rig:
    repo: Path
    base: str
    project: Project
    clock: Clock
    notes: list[str] = field(default_factory=list)

    def workload(self, name: str = "dedupe", warmup_runs: int = 1) -> Workload:
        return Workload(
            project_id=self.project.id, name=name, warmup_runs=warmup_runs,
            command=(PY, "-m", "dedupe.main", "2000"), timeout_s=60.0,
        )  # fmt: skip

    def trial(
        self, editor: CodeEditor, workloads: Sequence[Workload], **runner: bool | int
    ) -> tuple[Trial, Hypothesis]:
        def build(
            *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
        ) -> CodeEditor:
            return editor

        hypothesis = Hypothesis(
            project_id=self.project.id, source=HypothesisSource.novel,
            title="use a set", rationale="membership in a set is O(1)",
            change_class=ChangeClass.efficiency, expected_gain=0.5,
            provability=0.9, risk=0.1,
        )  # fmt: skip
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
        baseline = Baseline(
            commit=self.base, measurements=rows, objectives=(objective,)
        )
        trial = GitTrialRunner(
            self.project, editor=build, network="required", fs="required",
            platform="linux", base_env={"PATH": "/usr/bin"}, run=self.clock,
            on_note=self.notes.append, **runner,  # type: ignore[arg-type]
        ).run(
            hypothesis, workloads, baseline, round=1, budget_usd=1.0,
            branch=f"{settings.TRIAL_BRANCH_PREFIX}trial-run1-{hypothesis.id}",
            brief=TrialBrief(None, (), DEFAULT_PROTECTED_PATTERNS, fix_retries_left=1),
        )  # fmt: skip
        return trial, hypothesis

    def baseline_runner(self) -> GitBaselineRunner:
        return GitBaselineRunner(
            self.project, network="required", fs="required", platform="linux",
            base_env={"PATH": "/usr/bin"}, run=self.clock, on_note=self.notes.append,
        )  # fmt: skip

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


def abba(a: str, b: str, indexes: int) -> list[str]:
    return [s for i in range(indexes) for s in ((a, b) if i % 2 == 0 else (b, a))]


def mean(rows: Sequence[Measurement], metric: str = METRIC_WALL_TIME_S) -> float:
    [row] = [m for m in rows if m.metric == metric]
    return row.stats.mean


def test_a_paired_trial_takes_its_base_rows_from_the_twin_run_by_run(rig: Rig) -> None:
    """ABBA over the warm-up and 5 timed runs (twin = A, trial = B), the twin
    at the base, the suite once on B; the A rows are the twin's, no trial id."""
    rig.clock.wall_ms = lambda phase, n: 200.0 if phase.startswith("twin-") else 100.0
    workload = rig.workload()
    trial, hypothesis = rig.trial(Edits([SAME]), [workload], paired=True)
    a, b = f"twin-trial-{hypothesis.id}", f"trial-{hypothesis.id}"
    assert rig.clock.calls == [*abba(a, b, 6), f"suite {b}"]
    assert rig.clock.heads == {a: rig.base, b: trial.commit}
    assert trial.status is TrialStatus.measured
    base, own = trial.base_measurements, trial.measurements
    assert [(m.metric, m.trial_id) for m in base] == [(m, None) for m in TIME]
    assert [(m.metric, m.trial_id) for m in own] == [
        *((m, trial.id) for m in TIME),
        (METRIC_TESTS_PASSED, trial.id),
    ]
    assert base[0].samples == (0.2,) * 5 and own[0].samples == (0.1,) * 5
    assert all(m.workload_id == workload.id for m in (*base, *own))
    rig.nothing_left()


def test_under_a_slow_drift_the_paired_gain_is_near_zero_where_step_2_wins(
    rig: Rig,
) -> None:
    """Identical code, a host getting 1 % faster every launch: the Step 2 trial
    beats the earlier baseline by over 2 %, the paired trial its twin by < 0.5 %."""
    rig.clock.wall_ms = lambda phase, n: 100.0 * (1 - 0.01 * n)
    workload = rig.workload()
    baseline = rig.baseline_runner().measure([workload], run_id="run1", commit=rig.base)
    step2, _ = rig.trial(Edits([SAME]), [workload])
    paired, _ = rig.trial(Edits([SAME]), [workload], paired=True)
    assert (mean(baseline) - mean(step2.measurements)) / mean(baseline) > 0.02
    gain = (mean(paired.base_measurements) - mean(paired.measurements)) / mean(
        paired.base_measurements
    )
    assert abs(gain) < 0.005


def test_unpaired_is_step_2(rig: Rig) -> None:
    workload = rig.workload()
    trial, hypothesis = rig.trial(Edits([SAME]), [workload])
    b = f"trial-{hypothesis.id}"
    assert rig.clock.calls == [b] * 6 + [f"suite {b}"]
    assert trial.base_measurements == () and len(trial.measurements) == 4
    rig.nothing_left()


def test_a_retry_is_measured_paired_like_a_first_attempt(rig: Rig) -> None:
    rig.clock.crash_on, rig.clock.crashes = "trial-", 1
    rig.clock.wall_ms = lambda phase, n: 200.0 if phase.startswith("twin-") else 100.0
    editor = Edits([BROKEN, FIXED])
    trial, hypothesis = rig.trial(
        editor, [rig.workload(warmup_runs=0)], paired=True, fix_retries=1
    )
    a, b = f"twin-trial-{hypothesis.id}", f"trial-{hypothesis.id}"
    assert (trial.status, trial.attempts) == (TrialStatus.measured, 2)
    assert trial.retry_notes == ("NameError; retried",)
    assert rig.clock.calls == [a, b, *abba(a, b, 5), f"suite {b}"]
    assert trial.base_measurements[0].samples == (0.2,) * 5
    rig.nothing_left()


@pytest.mark.parametrize(
    ("skip", "twins"),
    [(0, [True]), (1, [True, False, False, True])],
    ids=["even-index-a-leads", "odd-index-b-leads"],
)
def test_a_crash_on_the_twin_is_an_engine_error_never_retried(
    rig: Rig, skip: int, twins: list[bool]
) -> None:
    """The base, not the hypothesis, failed: no verdict, no lesson (as a
    baseline crash); the spend rides on the error and nothing is left."""
    rig.clock.crash_on, rig.clock.crashes, rig.clock.skip = "twin-", 1, skip
    editor = Edits([SAME, SAME])
    with pytest.raises(EngineError) as raised:
        rig.trial(editor, [rig.workload()], paired=True, fix_retries=1)
    assert str(raised.value).startswith(
        "the paired base run failed: workload 'dedupe' A"
    )
    assert [c.startswith("twin-") for c in rig.clock.calls] == twins
    assert spend_of(raised.value) == (0.01, 10) and len(editor.tasks) == 1
    assert git(rig.repo, "for-each-ref", "refs/heads/") == git(
        rig.repo, "for-each-ref", "refs/heads/main"
    )
    rig.nothing_left()


def test_the_baseline_runner_is_a_noise_calibrator(rig: Rig) -> None:
    assert isinstance(rig.baseline_runner(), NoiseCalibrator)


@pytest.mark.parametrize(
    ("twin_ms", "multiplier", "floor"),
    [(103.0, 2.0, 2 * 3 / 103), (100.5, 2.0, 0.02), (103.0, 3.0, 3 * 3 / 103)],
    ids=["gap-sets-the-floor", "never-below-2-percent", "multiplier"],
)
def test_calibrate_gives_the_largest_gap_per_workload_and_a_floor(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, twin_ms: float, multiplier: float,
    floor: float,
) -> None:  # fmt: skip
    """3 blocks of 2 workloads (10 launches each, ABBA): the twin is slower by
    1 ms except on workload 2 in block 2; wall time only (CPU time follows
    wall here and is not calibrated)."""
    monkeypatch.setattr(settings, "NOISE_GAP_MULTIPLIER", multiplier)

    def wall(phase: str, n: int) -> float:
        twin = twin_ms if n // 10 == 3 else 101.0  # block 2, workload 2
        return twin if phase.startswith("twin-") else 100.0

    rig.clock.wall_ms = wall
    one, two = rig.workload("one", 0), rig.workload("two", 0)
    found = rig.baseline_runner().calibrate([one, two], run_id="run1", commit=rig.base, blocks=3)  # fmt: skip
    assert rig.clock.calls == abba("calibrate", "twin-calibrate", 5) * 6
    assert rig.clock.heads == {"calibrate": rig.base, "twin-calibrate": rig.base}
    assert found.blocks == 3 and found.floor == pytest.approx(floor)
    gap_two = max(1 / 101, (twin_ms - 100) / twin_ms)
    assert found.gaps == pytest.approx({
        f"{one.id}:{METRIC_WALL_TIME_S}": 1 / 101,
        f"{two.id}:{METRIC_WALL_TIME_S}": gap_two,
    })  # fmt: skip
    rig.nothing_left()


@pytest.mark.parametrize("blocks", [0, 6])
def test_calibrate_refuses_blocks_out_of_range(rig: Rig, blocks: int) -> None:
    with pytest.raises(ValueError, match="blocks must be 1-5"):
        rig.baseline_runner().calibrate([rig.workload()], run_id="run1", commit=rig.base, blocks=blocks)  # fmt: skip
    assert rig.clock.calls == []


def test_a_calibration_run_failure_is_an_engine_error(rig: Rig) -> None:
    rig.clock.crash_on, rig.clock.crashes = "twin-", 1
    with pytest.raises(
        EngineError, match="the noise calibration could not be measured"
    ):
        rig.baseline_runner().calibrate([rig.workload()], run_id="run1", commit=rig.base, blocks=1)  # fmt: skip
    rig.nothing_left()


def test_calibration_tampering_names_the_noise_calibration(rig: Rig) -> None:
    def wall(phase: str, n: int) -> float:
        if n == 0:
            git(rig.repo, "branch", "planted")
        return 100.0

    rig.clock.wall_ms = wall
    with pytest.raises(RepoTamperedError, match="while the noise calibration ran"):
        rig.baseline_runner().calibrate([rig.workload()], run_id="run1", commit=rig.base, blocks=1)  # fmt: skip
    rig.nothing_left()


def test_two_zero_means_are_no_gap(rig: Rig) -> None:
    rig.clock.wall_ms = lambda phase, n: 0.0
    load = rig.workload()
    found = rig.baseline_runner().calibrate([load], run_id="run1", commit=rig.base, blocks=1)  # fmt: skip
    assert (found.gaps, found.floor) == ({f"{load.id}:{METRIC_WALL_TIME_S}": 0.0}, 0.02)
