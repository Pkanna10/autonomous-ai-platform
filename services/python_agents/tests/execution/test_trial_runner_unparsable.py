"""The trial runner's capture call: ``base_of`` and ``unparsable_source`` (N0, D62).

Real git on a throwaway copy of the ``dedupe_repo`` fixture, plus a base file
``dedupe/loader.py`` that already imports ``importlib.import_module`` (as
mistune's plugin loader does). Fakes: ``FakeRun`` stands for
``procrun.run_once`` (no workload is launched; every call is recorded) and
``WriteEditor`` for ``ClaudeEditor`` (it writes fixed bytes). The real
``GitWorkspace`` reads the base blob, so the base the rule sees is git's.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_TESTS_PASSED,
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
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.protocols import (
    CodeEditor,
    EditResult,
    EditTask,
    TrialBrief,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import GitTrialRunner
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS

DEDUPE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "dedupe_repo"
PY, RUN_ID, TESTS = sys.executable, "run1", 11
UNITTEST = (PY, "-m", "unittest", "discover", "-s", "tests", "-t", ".")
LOADER = "dedupe/loader.py"
LOADER_PY = (
    b"from importlib import import_module\n\n\n"
    b"def load(name):\n    return import_module(name)\n"
)
_GIT_ENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.devnull,
    "LC_ALL": "C",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "user@example.invalid",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "user@example.invalid",
}


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], env=_GIT_ENV, capture_output=True, check=False
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc.stdout.decode().strip()


@dataclass
class FakeRun:
    """``run_once``: records each launch; unittest prints ``TESTS`` passing tests."""

    calls: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        sandbox: SandboxPolicy,
        timeout_s: float,
        caps: OutputCaps,
        *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:
        self.calls.append(tuple(argv))
        stderr = f"Ran {TESTS} tests in 0.010s\n\nOK\n" if "unittest" in argv else ""
        return RunSample(
            wall_ns=10_000_000,
            utime=0.01,
            stime=0.0,
            maxrss_bytes=1 << 20,
            exit=0,
            fs_isolated=True,
            net_isolated=True,
            stdout_sha256="1" * 64,
            stdout_head=b"",
            stdout_bytes=0,
            stderr_tail=stderr.encode(),
        )


@dataclass
class WriteEditor:
    """Writes ``files`` into the worktree and reports writing them."""

    files: Mapping[str, bytes]

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        for rel, data in self.files.items():
            (worktree / rel).write_bytes(data)
        return EditResult(written={rel: len(data) for rel, data in self.files.items()})


@dataclass
class Rig:
    repo: Path
    commit: str
    project: Project
    run: FakeRun

    def trial(self, files: Mapping[str, bytes]) -> Trial:
        def build(
            *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
        ) -> CodeEditor:
            return WriteEditor(files)

        runner = GitTrialRunner(
            self.project,
            editor=build,
            network="required",
            fs="required",
            platform="linux",
            base_env={"PATH": "/usr/bin"},
            run=self.run,
        )
        hypothesis = Hypothesis(
            project_id=self.project.id,
            source=HypothesisSource.playbook,
            title="h1",
            rationale="use a set for membership",
            change_class=ChangeClass.efficiency,
            expected_gain=0.5,
            provability=0.9,
            risk=0.1,
        )
        load = Workload(
            project_id=self.project.id,
            name="dedupe",
            command=(PY, "-m", "dedupe.main", "2000"),
            timeout_s=60.0,
            warmup_runs=0,
        )
        tests = Measurement(
            workload_id=load.id,
            metric=METRIC_TESTS_PASSED,
            stats=RunStats.from_samples((1.0,), unit="bool"),
            samples=(1.0,),
            hardware={"tests_counted": TESTS},
        )
        objective = Objective(  # CPU time judged: the spawn rule applies
            project_id=self.project.id,
            kind=ObjectiveKind.runtime,
            metric=METRIC_CPU_TIME_S,
            direction=Direction.minimize,
            description="less CPU",
        )
        baseline = Baseline(
            commit=self.commit, measurements=(tests,), objectives=(objective,)
        )
        return runner.run(
            hypothesis,
            [load],
            baseline,
            round=1,
            branch=f"{settings.TRIAL_BRANCH_PREFIX}trial-{RUN_ID}-{hypothesis.id}",
            budget_usd=1.0,
            brief=TrialBrief(None, (), DEFAULT_PROTECTED_PATTERNS),
        )


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    root = Path(os.path.realpath(tmp_path))
    wt_root = root / "wt-root"
    wt_root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", wt_root)
    repo = root / "user"
    shutil.copytree(DEDUPE_REPO, repo, ignore=shutil.ignore_patterns("__pycache__"))
    (repo / LOADER).write_bytes(LOADER_PY)
    git(root, "init", "-q", "-b", "main", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    project = Project(name="dedupe", root_path=str(repo), test_command=UNITTEST)
    return Rig(repo, git(repo, "rev-parse", "HEAD"), project, FakeRun())


def _never_run(rig: Rig, trial: Trial) -> None:
    assert trial.status is TrialStatus.failed
    assert (trial.commit, trial.measurements) == (None, ())
    assert rig.run.calls == []


def test_an_edit_beside_a_base_spawn_finding_is_measured(rig: Rig) -> None:
    """
    GIVEN a base file that already imports importlib.import_module, CPU judged
    WHEN the trial edits that file without touching the loader's statements
    THEN the runner hands check_capture the file's base, so the trial is measured
    """
    trial = rig.trial({LOADER: LOADER_PY + b"\n\nCACHE = {}\n"})

    assert (trial.status, trial.violations) == (TrialStatus.measured, ())
    assert rig.run.calls


def test_a_new_use_of_the_base_import_is_refused_before_it_runs(rig: Rig) -> None:
    trial = rig.trial({LOADER: LOADER_PY + b"\n\nPROC = import_module('subprocess')\n"})

    assert [v.rule for v in trial.violations] == [ViolationRule.process_spawn]
    assert "uses spawn-bound import_module" in trial.violations[0].message
    _never_run(rig, trial)


def test_an_edit_that_does_not_parse_is_unparsable_source(rig: Rig) -> None:
    """
    GIVEN an editor slip: dedupe/core.py rewritten with a missing colon
    WHEN the trial is captured with CPU time judged
    THEN its one violation is unparsable_source naming the file, the line and
        the parser's message, it is not process_spawn, and nothing ran
    """
    trial = rig.trial({"dedupe/core.py": b"def unique(xs)\n    return xs\n"})

    [violation] = trial.violations
    assert (violation.rule, violation.path) == (
        ViolationRule.unparsable_source,
        "dedupe/core.py",
    )
    assert "'dedupe/core.py'" in violation.message
    assert "(line 1: " in violation.message
    assert "process_spawn" not in str(trial.error)
    assert "unparsable_source" in str(trial.error)
    _never_run(rig, trial)


def test_a_base_read_that_fails_fails_the_trial_before_it_runs(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a base blob git cannot hand over (past MAX_OUTPUT_BYTES)
    WHEN the spawn rule reads the modified file's base
    THEN the trial fails as uncapturable, and nothing ran
    """
    real = GitWorkspace.read_blob

    def read(
        self: GitWorkspace, commit: str, path: str, *, limit: int | None = None
    ) -> bytes:
        if path == LOADER and limit is None:
            raise GitError("git cat-file failed: output past the limit")
        return real(self, commit, path, limit=limit)

    monkeypatch.setattr(GitWorkspace, "read_blob", read)

    trial = rig.trial({LOADER: LOADER_PY + b"# harmless\n"})

    assert "the change could not be captured" in str(trial.error)
    assert "output past the limit" in str(trial.error)
    _never_run(rig, trial)
