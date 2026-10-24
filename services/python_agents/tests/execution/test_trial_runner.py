"""GitTrialRunner and GitBaselineRunner on real throwaway git repositories.

Every test commits the ``dedupe_repo`` fixture into a user repo in
``tmp_path`` and runs the real ``GitWorkspace``. Workload launches go through
an injected ``run_once`` double (``FakeRun``) that records each call and can
tamper with the user's repo or the run directory, so the steps the spec fixes
(edit, capture, checks, commit, own ref, measure, tests, F1, cleanup) are
asserted on real git state. Two tests then run the fixture through the real
launcher (isolation off, every platform; plus one sandboxed on Linux when the
host can sandbox).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import (
    EngineError,
    LLMConfigError,
    RepoTamperedError,
    TrialUnaffordable,
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
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.common.paths import RESERVED_MODULES
from autonomous_ai_agents.execution import launcher
from autonomous_ai_agents.execution.fakes import FakeEditor, ScriptedEditor
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.protocols import (
    Change,
    CodeEditor,
    EditResult,
    EditTask,
    TrialBrief,
    WorktreeHandle,
)
from autonomous_ai_agents.execution.runner import BaselineRunner, TrialRunner
from autonomous_ai_agents.execution.sandbox import UNSHARE_ARGV, SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import (
    INVOKE_PROTECTED,
    NONDETERMINISTIC_NOTE,
    TRIAL_NAMESPACE,
    GitBaselineRunner,
    GitTrialRunner,
    run_scope,
    trial_id_for,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEDUPE_REPO = FIXTURES / "dedupe_repo"
DEDUPE_EDITS = FIXTURES / "dedupe_edits"
PY = sys.executable
RUN_ID = "run1"
TESTS = 11  # the fixture's unittest suite
UNITTEST = (PY, "-m", "unittest", "discover", "-s", "tests", "-t", ".")
FAST_CORE = (DEDUPE_EDITS / "h1" / "files" / "dedupe" / "core.py").read_bytes()
linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux sandbox")

_GIT_ENV: dict[str, str] = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.devnull,
    "LC_ALL": "C",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "user@example.invalid",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "user@example.invalid",
    "GIT_AUTHOR_DATE": "@1700000000 +0000",
    "GIT_COMMITTER_DATE": "@1700000000 +0000",
}


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], env=_GIT_ENV, capture_output=True, check=False
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc.stdout.decode().strip()


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class Call(NamedTuple):
    argv: tuple[str, ...]
    cwd: Path
    sandbox: SandboxPolicy
    fresh_dirs: tuple[Path, ...]


@dataclass
class FakeRun:
    """``run_once``: unittest prints a summary of ``tests_ran`` tests."""

    calls: list[Call] = field(default_factory=list)
    tests_ran: int = TESTS
    exit: int = 0
    notes: tuple[str, ...] = ()
    hook: Callable[[Call], None] | None = None
    vary_output: bool = False  # every run prints something else

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
        call = Call(tuple(argv), cwd, sandbox, tuple(fresh_dirs))
        self.calls.append(call)
        if self.hook is not None:
            self.hook(call)
        suite = "unittest" in argv
        stderr = f"Ran {self.tests_ran} tests in 0.010s\n\nOK\n" if suite else ""
        return RunSample(
            wall_ns=10_000_000,
            utime=0.01,
            stime=0.0,
            maxrss_bytes=1 << 20,
            exit=self.exit,
            fs_isolated=True,
            net_isolated=True,
            stdout_sha256=f"{len(self.calls):064x}" if self.vary_output else "1" * 64,
            stdout_head=b"",
            stdout_bytes=0,
            stderr_tail=stderr.encode(),
            notes=self.notes,
        )


@dataclass
class WriteEditor:
    """Writes ``files`` into the worktree and reports ``report`` (default: honest)."""

    files: Mapping[str, bytes]
    report: Mapping[str, int] | None = None
    result: EditResult = field(default_factory=EditResult)
    tasks: list[EditTask] = field(default_factory=list)

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        self.tasks.append(task)
        for rel, data in self.files.items():
            target = worktree / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        written = {r: len(d) for r, d in self.files.items()}
        if self.report is not None:
            written = dict(self.report)
        return EditResult(
            written=written,
            cost_usd=self.result.cost_usd,
            tokens_used=self.result.tokens_used,
        )


@dataclass
class SpendingEditor:
    """Records into the budget, as the Claude editor does, and reports less."""

    usd: float
    tokens: int

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        (worktree / "dedupe" / "core.py").write_bytes(FAST_CORE)
        budget.spent_usd += self.usd
        budget.tokens += self.tokens
        return EditResult(written={"dedupe/core.py": len(FAST_CORE)})


@dataclass
class Rig:
    root: Path
    repo: Path
    wt_root: Path
    commit: str
    project: Project
    run: FakeRun
    notes: list[str]
    scopes: list[tuple[AbstractSet[str], AbstractSet[str]]] = field(
        default_factory=list
    )

    @property
    def run_dir(self) -> Path:
        return self.wt_root / RUN_ID

    def workload(self, *command: str, **changes: object) -> Workload:
        fields: dict[str, object] = {
            "project_id": self.project.id,
            "name": "dedupe",
            "command": command or (PY, "-m", "dedupe.main", "2000"),
            "timeout_s": 60.0,
            "warmup_runs": 0,
        }
        fields.update(changes)
        return Workload.model_validate(fields)

    def hypothesis(self, title: str = "h1") -> Hypothesis:
        return Hypothesis(
            project_id=self.project.id,
            source=HypothesisSource.playbook,
            title=title,
            rationale="use a set for membership",
            change_class=ChangeClass.efficiency,
            expected_gain=0.5,
            provability=0.9,
            risk=0.1,
        )

    def baseline(
        self,
        workloads: Sequence[Workload],
        *,
        metric: str = METRIC_WALL_TIME_S,
        tests_counted: int = TESTS,
        commit: str | None = None,
    ) -> Baseline:
        rows = tuple(
            Measurement(
                workload_id=w.id,
                metric=METRIC_TESTS_PASSED,
                stats=RunStats.from_samples((1.0,), unit="bool"),
                samples=(1.0,),
                hardware={"tests_counted": tests_counted},
            )
            for w in workloads
        )
        objective = Objective(
            project_id=self.project.id,
            kind=ObjectiveKind.runtime,
            metric=metric,
            direction=Direction.minimize,
            description="faster",
        )
        return Baseline(
            commit=commit or self.commit, measurements=rows, objectives=(objective,)
        )

    def runner(
        self,
        editor: CodeEditor,
        *,
        project: Project | None = None,
        git_workspace: GitWorkspace | None = None,
        notes: bool = True,
    ) -> GitTrialRunner:
        def build(
            *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
        ) -> CodeEditor:
            self.scopes.append((module_roots, reserved_modules))
            return editor

        return GitTrialRunner(
            project or self.project,
            editor=build,
            git=git_workspace,
            network="required",
            fs="required",
            platform="linux",
            base_env={"PATH": "/usr/bin"},
            run=self.run,
            on_note=self.notes.append if notes else None,
        )

    def branch(self, hypothesis: Hypothesis) -> str:
        return f"{settings.TRIAL_BRANCH_PREFIX}trial-{RUN_ID}-{hypothesis.id}"

    def trial(
        self,
        hypothesis: Hypothesis,
        runner: GitTrialRunner,
        *,
        workloads: Sequence[Workload] | None = None,
        baseline: Baseline | None = None,
        budget_usd: float = 1.0,
        round: int = 1,
        protected: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS,
    ) -> Trial:
        loads = workloads if workloads is not None else [self.workload()]
        return runner.run(
            hypothesis,
            loads,
            baseline or self.baseline(loads),
            round=round,
            branch=self.branch(hypothesis),
            budget_usd=budget_usd,
            brief=TrialBrief(understanding=None, hotspots=(), protected=protected),
        )

    def ref(self, hypothesis: Hypothesis) -> str | None:
        ref = f"refs/heads/{self.branch(hypothesis)}"
        out = git(self.repo, "for-each-ref", "--format=%(objectname)", ref)
        return out or None

    def state(self) -> tuple[str, ...]:
        """HEAD, the refs outside the engine prefix, status, the worktree list."""
        refs = git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)")
        user = [r for r in refs.splitlines() if not r.startswith("refs/heads/engine/")]
        return (
            git(self.repo, "rev-parse", "HEAD"),
            "\n".join(user),
            git(self.repo, "status", "--porcelain", "--ignored"),
            git(self.repo, "worktree", "list", "--porcelain"),
            git(self.repo, "config", "--list", "--local"),
        )


def make_repo(root: Path, extra: Mapping[str, str] = {}) -> tuple[Path, str]:
    repo = root / "user"
    shutil.copytree(DEDUPE_REPO, repo, ignore=shutil.ignore_patterns("__pycache__"))
    for rel, text in extra.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(root, "init", "-q", "-b", "main", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    root = Path(os.path.realpath(tmp_path))
    wt_root = root / "wt-root"
    wt_root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", wt_root)
    repo, commit = make_repo(root, {"scripts/bench.py": "print('bench')\n"})
    project = Project(name="dedupe", root_path=str(repo), test_command=UNITTEST)
    return Rig(root, repo, wt_root, commit, project, FakeRun(), [])


def user_git(rig: Rig, *args: str) -> Callable[[Call], None]:
    """A run hook that runs ``git *args`` in the user's repo (``-f``: again)."""

    def hook(call: Call) -> None:
        if args[0] == "branch":
            git(rig.repo, "branch", "-f", *args[1:])
        else:
            git(rig.repo, *args)

    return hook


def no_leftovers(rig: Rig) -> None:
    assert git(rig.repo, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert not rig.run_dir.exists()


# ---------------------------------------------------------------------------
# Trial runner: the kept path
# ---------------------------------------------------------------------------


def test_the_real_runners_satisfy_the_protocols(rig: Rig) -> None:
    assert isinstance(rig.runner(FakeEditor({})), TrialRunner)
    assert isinstance(GitBaselineRunner(rig.project, run=rig.run), BaselineRunner)


def test_a_committed_trial_is_measured_on_its_own_ref_and_leaves_nothing(
    rig: Rig,
) -> None:
    """
    GIVEN the h1 edit set (a set for membership) and one workload
    WHEN the trial runs
    THEN it is measured with its deterministic id, its commit sits on its own
        ref with the engine identity, the base dates and the trailer, every
        launch ran in the trial worktree after the commit, the suite ran once
        with the baseline's count, and the user's repo and WORKTREE_ROOT/<run>
        are as before
    """
    before = rig.state()
    hypothesis = rig.hypothesis("h1")
    workload = rig.workload()

    trial = rig.trial(
        hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)), workloads=[workload]
    )

    expected_id = str(uuid.uuid5(TRIAL_NAMESPACE, f"{rig.branch(hypothesis)}@1"))
    assert trial.id == expected_id == trial_id_for(rig.branch(hypothesis), 1)
    assert (trial.status, trial.error, trial.violations) == (
        TrialStatus.measured,
        None,
        (),
    )
    assert (trial.hypothesis_id, trial.round, trial.branch) == (
        hypothesis.id,
        1,
        rig.branch(hypothesis),
    )
    assert trial.base_commit == rig.commit
    assert trial.touched_paths == ("dedupe/core.py",)
    assert "+    seen: set[int] = set()" in trial.diff
    assert trial.commit is not None and rig.ref(hypothesis) == trial.commit
    assert trial.worktree_path == str(rig.run_dir / f"trial-{hypothesis.id}")
    message = git(rig.repo, "log", "-1", "--format=%an <%ae> %ad|%P|%B", trial.commit)
    assert message.startswith(f"aip-engine <engine@aip.invalid> {_date(rig)}|")
    assert f"|{rig.commit}|" in message
    assert message.endswith(f"Engine-Trial: {trial.id}")
    assert (
        git(rig.repo, "show", f"{trial.commit}:dedupe/core.py").encode() + (b"\n")
        == FAST_CORE
    )
    metrics = [(m.workload_id, m.metric, m.trial_id) for m in trial.measurements]
    assert metrics == [
        (workload.id, metric, trial.id)
        for metric in (
            METRIC_WALL_TIME_S,
            METRIC_CPU_TIME_S,
            METRIC_PEAK_RSS_BYTES,
            METRIC_TESTS_PASSED,
        )
    ]
    assert trial.measurements[-1].samples == (1.0,)
    assert len(trial.measurements[0].samples) == settings.MIN_RUNS
    worktree = rig.run_dir / f"trial-{hypothesis.id}"
    scratch = rig.run_dir / "_scratch" / f"trial-{hypothesis.id}"
    assert len(rig.run.calls) == settings.MIN_RUNS + 1
    for call in rig.run.calls:
        assert call.cwd == worktree
        assert call.sandbox.writable == (worktree, scratch)
        assert call.sandbox.probe_dir == rig.run_dir / "_probe" / worktree.name
        assert call.fresh_dirs == (scratch, scratch / "home", scratch / "tmp")
    assert rig.run.calls[-1].argv == UNITTEST
    assert (trial.started_at is not None) and (trial.finished_at is not None)
    assert (trial.cost_usd, trial.tokens_used) == (0.0, 0)
    assert rig.state() == before
    no_leftovers(rig)


def _date(rig: Rig) -> str:
    return git(rig.repo, "log", "-1", "--format=%ad", rig.commit)


def test_the_editor_gets_the_brief_and_a_fresh_boundary_per_trial(
    rig: Rig,
) -> None:
    editor = WriteEditor({"dedupe/core.py": FAST_CORE})
    hypothesis = rig.hypothesis()

    rig.trial(hypothesis, rig.runner(editor), protected=("**/tests/**",))
    rig.trial(hypothesis, rig.runner(editor), protected=("**/tests/**",))

    first, second = editor.tasks
    assert first.hypothesis == hypothesis
    assert first.brief == TrialBrief(None, (), ("**/tests/**",))
    assert len(first.boundary) == 16 and first.boundary != second.boundary


def test_one_editor_is_built_per_scope_with_the_runs_roots_and_reserved_names(
    rig: Rig,
) -> None:
    """
    GIVEN workloads running `-m dedupe.main` from the root and a repo script
        from `scripts`, and a unittest test command
    WHEN two trials run on the same runner
    THEN the editor is built once, with the repo root, src, every working
        dir and every script's directory as module roots, and the stdlib and
        runner names plus every -m target reserved
    """
    editor = WriteEditor({"dedupe/core.py": FAST_CORE})
    runner = rig.runner(editor)
    loads = [
        rig.workload(),
        rig.workload(PY, "bench.py", name="bench", working_dir="scripts"),
    ]

    rig.trial(rig.hypothesis("a"), runner, workloads=loads)
    rig.trial(rig.hypothesis("b"), runner, workloads=loads)

    [(roots, reserved)] = rig.scopes
    assert roots == {"", "src", "scripts"}
    assert reserved == RESERVED_MODULES | {"dedupe", "unittest"}


def test_run_scope_reads_scripts_working_dirs_modules_and_invoke(
    rig: Rig,
) -> None:
    tracked = ("tools/run.sh", "pkg/a.py", "data/in.txt", "x.py")
    project = rig.project.model_copy(update={"test_command": ("/usr/bin/inv", "t")})
    loads = [
        rig.workload(
            "tools/run.sh", "../data/in.txt", "-v", "/abs/x.py", working_dir="tools"
        ),
        rig.workload(PY, "-mpkg.a", working_dir="pkg"),
        rig.workload(PY, "../../escape.py", "x.py"),
        rig.workload(PY, "-m"),
    ]

    scope = run_scope(project, loads, tracked)

    assert scope.module_roots == {"", "src", "tools", "data", "pkg"}
    assert scope.reserved_modules == RESERVED_MODULES | {"pkg"}
    assert scope.protected == INVOKE_PROTECTED
    assert "**/tasks.py" in INVOKE_PROTECTED


def test_run_scope_without_a_test_command_or_invoke_adds_nothing(rig: Rig) -> None:
    project = rig.project.model_copy(update={"test_command": None})

    scope = run_scope(project, [rig.workload(PY, "-m", "invoke", "x")], ())

    assert scope.reserved_modules == RESERVED_MODULES | {"invoke"}
    assert scope.protected == INVOKE_PROTECTED
    plain = run_scope(project, [rig.workload("/bin/true")], ())
    assert plain.module_roots == {"", "src"}
    assert plain.protected == ()


def test_a_symlinked_script_guards_the_dir_python_puts_on_sys_path(
    tmp_path: Path,
) -> None:
    """
    GIVEN tracked scripts/bench.py -> ../tools/real.py, a link out of the repo
        and a dangling one (CPython puts the resolved target's dir first)
    WHEN run_scope reads the workloads with the base worktree
    THEN tools/ joins the roots next to scripts/; nothing outside the repo does
    """
    worktree = tmp_path / "wt"
    (worktree / "tools").mkdir(parents=True)
    (worktree / "scripts").mkdir()
    (worktree / "tools" / "real.py").write_text("print('bench')\n")
    os.symlink("../tools/real.py", worktree / "scripts" / "bench.py")
    os.symlink(str(tmp_path), worktree / "scripts" / "out.py")
    os.symlink("../nowhere/gone.py", worktree / "scripts" / "gone.py")
    tracked = ("tools/real.py", "scripts/bench.py", "scripts/out.py", "scripts/gone.py")
    project = Project(name="p", root_path=str(tmp_path), test_command=None)
    loads = [
        Workload(project_id=project.id, name=n, command=(PY, f"scripts/{n}.py"))
        for n in ("bench", "out", "gone")
    ]

    scope = run_scope(project, loads, tracked, worktree=worktree)

    assert scope.module_roots == {"", "src", "scripts", "tools", "nowhere"}
    assert run_scope(project, loads, tracked).module_roots == {"", "src", "scripts"}


def test_shadowing_next_to_a_symlinked_scripts_target_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(os.path.realpath(tmp_path))
    wt_root = root / "wt-root"
    wt_root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", wt_root)
    repo = root / "user"
    (repo / "tools").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "tools" / "real.py").write_text("import json\n")
    os.symlink("../tools/real.py", repo / "scripts" / "bench.py")
    git(root, "init", "-q", "-b", "main", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    project = Project(name="sym", root_path=str(repo), test_command=None)
    rig = Rig(
        root, repo, wt_root, git(repo, "rev-parse", "HEAD"), project, FakeRun(), []
    )
    hypothesis = rig.hypothesis()
    editor = WriteEditor({"tools/json.py": b"SHADOW = True\n"})

    trial = rig.trial(
        hypothesis, rig.runner(editor), workloads=[rig.workload(PY, "scripts/bench.py")]
    )

    assert (ViolationRule.module_shadow, "tools/json.py") in [
        (v.rule, v.path) for v in trial.violations
    ]
    assert_never_executed(rig, trial, hypothesis)
    assert ("tools" in rig.scopes[0][0]) and ("json" in rig.scopes[0][1])


def test_an_added_file_in_a_directory_the_base_had_is_not_a_shadow(rig: Rig) -> None:
    """
    GIVEN `-m dedupe.main` (which reserves `dedupe`) and an edit that only
        adds dedupe/fast.py, so the diff alone does not prove dedupe/ existed
    WHEN the trial runs
    THEN the base tree's directories reach check_capture and it is measured
    """
    editor = WriteEditor({"dedupe/fast.py": b"FAST = True\n"})

    trial = rig.trial(rig.hypothesis(), rig.runner(editor))

    assert trial.status is TrialStatus.measured, trial.violations


def test_tracked_directory_names_check_capture_would_refuse_are_left_out(
    rig: Rig,
) -> None:
    """
    GIVEN a base tree with directories named `odd\\dir` and `~home` (legal
        POSIX names that normalize_path rewrites or refuses)
    WHEN a trial runs
    THEN they are not passed as existing directories and it is measured
    """
    for rel in ("odd\\dir/x.txt", "~home/y.txt"):
        (rig.repo / rel).parent.mkdir()
        (rig.repo / rel).write_text("data\n")
    git(rig.repo, "add", "-A")
    git(rig.repo, "commit", "-q", "-m", "odd names")
    rig.commit = git(rig.repo, "rev-parse", "HEAD")
    editor = WriteEditor({"dedupe/core.py": FAST_CORE})

    trial = rig.trial(rig.hypothesis(), rig.runner(editor))

    assert trial.status is TrialStatus.measured, trial.error


# ---------------------------------------------------------------------------
# Trial runner: refused before anything runs
# ---------------------------------------------------------------------------


def assert_never_executed(rig: Rig, trial: Trial, hypothesis: Hypothesis) -> None:
    assert trial.status is TrialStatus.failed
    assert (trial.commit, trial.measurements) == (None, ())
    assert rig.run.calls == []
    assert rig.ref(hypothesis) is None
    no_leftovers(rig)


@pytest.mark.parametrize(
    ("title", "rule", "path"),
    [
        ("h6", ViolationRule.forbidden_file_mode, "dedupe/fast.py"),
        ("h2", ViolationRule.protected_path, "tests/test_core.py"),
    ],
)
def test_a_capture_or_protected_path_violation_is_never_executed(
    rig: Rig, title: str, rule: ViolationRule, path: str
) -> None:
    hypothesis = rig.hypothesis(title)

    trial = rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))

    assert (rule, path) in [(v.rule, v.path) for v in trial.violations]
    assert trial.error is not None and "rule" in trial.error
    assert path in trial.touched_paths and trial.diff
    assert_never_executed(rig, trial, hypothesis)


def test_a_write_the_editor_did_not_report_is_unrecorded(rig: Rig) -> None:
    hypothesis = rig.hypothesis()
    editor = WriteEditor({"dedupe/core.py": FAST_CORE}, report={})

    trial = rig.trial(hypothesis, rig.runner(editor))

    assert [v.rule for v in trial.violations] == [ViolationRule.unrecorded_write]
    assert_never_executed(rig, trial, hypothesis)


@pytest.mark.parametrize(
    ("command", "workdir", "added"),
    [
        ((PY, "-m", "mybench"), ".", "mybench.py"),
        ((PY, "bench.py"), "scripts", "scripts/json.py"),
    ],
)
def test_shadowing_a_run_target_or_stdlib_module_on_a_script_root_is_refused(
    rig: Rig, command: tuple[str, ...], workdir: str, added: str
) -> None:
    hypothesis = rig.hypothesis()
    editor = WriteEditor({added: b"x = 1\n"})
    load = rig.workload(*command, working_dir=workdir)

    trial = rig.trial(hypothesis, rig.runner(editor), workloads=[load])

    assert [v.rule for v in trial.violations] == [ViolationRule.module_shadow]
    assert_never_executed(rig, trial, hypothesis)


def test_process_spawning_is_refused_only_while_cpu_or_rss_is_judged(
    rig: Rig,
) -> None:
    spawning = FAST_CORE + b"\nimport subprocess\n"
    hypothesis = rig.hypothesis()
    editor = WriteEditor({"dedupe/core.py": spawning})
    load = rig.workload()

    judged = rig.trial(
        hypothesis,
        rig.runner(editor),
        workloads=[load],
        baseline=rig.baseline([load], metric=METRIC_CPU_TIME_S),
    )
    assert [v.rule for v in judged.violations] == [ViolationRule.process_spawn]
    assert_never_executed(rig, judged, hypothesis)

    wall_only = rig.trial(hypothesis, rig.runner(editor), workloads=[load])
    assert wall_only.status is TrialStatus.measured


def test_invoke_protects_tasks_py_for_the_editor_and_the_diff(rig: Rig) -> None:
    project = rig.project.model_copy(update={"test_command": ("/usr/bin/invoke", "t")})
    hypothesis = rig.hypothesis()
    editor = WriteEditor({"tasks.py": b"x = 1\n"})

    trial = rig.trial(hypothesis, rig.runner(editor, project=project))

    assert editor.tasks[0].brief.protected == (
        *DEFAULT_PROTECTED_PATTERNS,
        *INVOKE_PROTECTED,
    )
    assert [(v.rule, v.path) for v in trial.violations] == [
        (ViolationRule.protected_path, "tasks.py")
    ]
    assert_never_executed(rig, trial, hypothesis)


def test_an_empty_diff_fails_with_the_money_spent(rig: Rig) -> None:
    hypothesis = rig.hypothesis()
    editor = WriteEditor(
        {"dedupe/core.py": (DEDUPE_REPO / "dedupe" / "core.py").read_bytes()},
        result=EditResult(cost_usd=0.25, tokens_used=900),
    )

    trial = rig.trial(hypothesis, rig.runner(editor))

    assert trial.error == "the editor changed nothing"
    assert (trial.cost_usd, trial.tokens_used, trial.diff) == (0.25, 900, "")
    assert_never_executed(rig, trial, hypothesis)


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (
            EditResult(cost_usd=0.5, tokens_used=10, stop="refusal", error="no"),
            "the editor stopped (refusal): no",
        ),
        (
            EditResult(cost_usd=0.5, tokens_used=10, stop="no_edits"),
            "the editor stopped (no_edits): no reason given",
        ),
    ],
)
def test_an_editor_error_fails_with_the_money_spent(
    rig: Rig, result: EditResult, error: str
) -> None:
    hypothesis = rig.hypothesis()

    trial = rig.trial(hypothesis, rig.runner(FakeEditor({"h1": result})))

    assert (trial.error, trial.cost_usd, trial.tokens_used) == (error, 0.5, 10)
    assert_never_executed(rig, trial, hypothesis)


def test_a_trial_the_cap_stops_before_its_first_request_never_started(
    rig: Rig,
) -> None:
    """
    GIVEN an editor stopped by the cost cap before its first request: nothing
        written, nothing spent
    WHEN the trial runs
    THEN TrialUnaffordable says it never started (it is no rejected change),
        and nothing is left: no worktree, no run dir, no ref
    """
    hypothesis = rig.hypothesis()
    stopped = EditResult(stop="budget", error="the run's cost cap stopped the edit")

    with pytest.raises(TrialUnaffordable, match="cost cap"):
        rig.trial(hypothesis, rig.runner(FakeEditor({"h1": stopped})))

    assert rig.ref(hypothesis) is None
    no_leftovers(rig)


@pytest.mark.parametrize(
    "result",
    [
        EditResult(cost_usd=0.1, tokens_used=5, stop="budget", error="cap"),
        EditResult(written={"dedupe/core.py": 3}, stop="budget", error="cap"),
    ],
    ids=["spent", "wrote"],
)
def test_a_budget_stop_after_work_began_is_a_failed_trial(
    rig: Rig, result: EditResult
) -> None:
    trial = rig.trial(rig.hypothesis(), rig.runner(FakeEditor({"h1": result})))

    assert trial.status is TrialStatus.failed
    assert trial.error == "the editor stopped (budget): cap"


def test_the_cost_is_the_larger_of_the_report_and_the_budget_record(
    rig: Rig,
) -> None:
    trial = rig.trial(rig.hypothesis(), rig.runner(SpendingEditor(0.3, 70)))

    assert (trial.status, trial.cost_usd, trial.tokens_used) == (
        TrialStatus.measured,
        0.3,
        70,
    )


def test_an_editor_over_its_budget_fails_charged_exactly_the_budget(
    rig: Rig,
) -> None:
    hypothesis = rig.hypothesis()

    trial = rig.trial(hypothesis, rig.runner(SpendingEditor(0.8, 1000)), budget_usd=0.2)

    assert (trial.cost_usd, trial.tokens_used) == (0.2, 250)
    assert trial.error is not None and "above the trial's budget" in trial.error
    assert_never_executed(rig, trial, hypothesis)


class BadNameGit(GitWorkspace):
    """A real workspace whose diff names a path that is not valid UTF-8, as
    git reports one on Linux (APFS refuses such names, so no file is made)."""

    def changes(self, handle: WorktreeHandle, base: str) -> tuple[Change, ...]:
        bad = Change("A", "000000", "100644", os.fsdecode(b"bad\xff.py"))
        return (*super().changes(handle, base), bad)


def test_a_path_that_is_not_utf8_fails_the_trial(rig: Rig) -> None:
    hypothesis = rig.hypothesis()
    editor = WriteEditor({"dedupe/core.py": FAST_CORE})

    trial = rig.trial(
        hypothesis, rig.runner(editor, git_workspace=BadNameGit(rig.repo))
    )

    assert trial.error is not None and "not valid UTF-8" in trial.error
    assert "bad\\udcff.py" in trial.error
    assert trial.violations == ()
    assert_never_executed(rig, trial, hypothesis)


class FailingGit(GitWorkspace):
    """A real workspace whose named method raises ``error``."""

    def __init__(self, repo: Path, method: str, error: Exception) -> None:
        super().__init__(repo)
        self.method, self.error = method, error

    def staged_blob(self, handle: WorktreeHandle, path: str) -> bytes:
        if self.method == "staged_blob":
            raise self.error
        return super().staged_blob(handle, path)

    def changes(self, handle: WorktreeHandle, base: str) -> tuple[Change, ...]:
        if self.method == "changes":
            raise self.error
        return super().changes(handle, base)


def test_a_git_error_during_capture_fails_the_trial(rig: Rig) -> None:
    hypothesis = rig.hypothesis()
    failing = FailingGit(
        rig.repo, "staged_blob", GitError("git cat-file printed more than 9 bytes")
    )
    editor = WriteEditor({"dedupe/core.py": FAST_CORE})

    trial = rig.trial(hypothesis, rig.runner(editor, git_workspace=failing))

    assert trial.error == (
        "the change could not be captured: git cat-file printed more than 9 bytes"
    )
    assert_never_executed(rig, trial, hypothesis)


def test_tampering_seen_during_capture_propagates_after_cleanup(rig: Rig) -> None:
    hypothesis = rig.hypothesis()
    failing = FailingGit(rig.repo, "changes", RepoTamperedError("link changed"))
    editor = WriteEditor({"dedupe/core.py": FAST_CORE})

    with pytest.raises(RepoTamperedError, match="link changed"):
        rig.trial(hypothesis, rig.runner(editor, git_workspace=failing))

    no_leftovers(rig)


def test_an_editor_that_rewrites_the_git_link_is_tampering(rig: Rig) -> None:
    class Relink:
        def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
            (worktree / ".git").write_text("gitdir: /elsewhere\n")
            return EditResult()

    with pytest.raises(RepoTamperedError, match="changed after the worktree"):
        rig.trial(rig.hypothesis(), rig.runner(Relink()))

    no_leftovers(rig)


def test_an_editor_exception_propagates_after_cleanup(rig: Rig) -> None:
    editor = FakeEditor({"h1": LLMConfigError("401: invalid key")})

    with pytest.raises(LLMConfigError, match="invalid key"):
        rig.trial(rig.hypothesis(), rig.runner(editor))

    no_leftovers(rig)


# ---------------------------------------------------------------------------
# Trial runner: measurement outcomes and notes
# ---------------------------------------------------------------------------


def test_a_run_failure_fails_the_committed_trial_and_emits_its_notes(
    rig: Rig,
) -> None:
    """
    GIVEN a workload that exits 1 and a run note
    WHEN the trial runs
    THEN it is failed with the reason, keeps its commit and own ref (it was
        committed), has no measurements, and every note was emitted
    """
    rig.run.exit, rig.run.notes = 1, ("isolation weakened",)
    hypothesis = rig.hypothesis()

    trial = rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))

    assert trial.status is TrialStatus.failed
    assert trial.error is not None and "ended with exit status 1" in trial.error
    assert trial.measurements == ()
    assert trial.commit is not None and rig.ref(hypothesis) == trial.commit
    assert rig.notes == [
        f"trial for hypothesis {hypothesis.id}: workload 'dedupe' run 1/5: "
        "isolation weakened"
    ]
    no_leftovers(rig)


def test_fewer_tests_than_the_baseline_is_a_failing_tests_row(rig: Rig) -> None:
    rig.run.tests_ran = TESTS - 1
    hypothesis = rig.hypothesis()

    trial = rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))

    assert trial.status is TrialStatus.measured
    assert trial.measurements[-1].samples == (0.0,)
    assert rig.notes == [
        f"trial for hypothesis {hypothesis.id}: the test command: {TESTS - 1} tests"
        f" passed, fewer than the baseline's {TESTS}"
    ]


def test_notes_without_a_sink_are_dropped(rig: Rig) -> None:
    rig.run.notes = ("a note",)

    trial = rig.trial(
        rig.hypothesis(), rig.runner(ScriptedEditor(DEDUPE_EDITS), notes=False)
    )

    assert trial.status is TrialStatus.measured and rig.notes == []


def test_a_nondeterministic_trial_output_is_a_marked_note(rig: Rig) -> None:
    """
    GIVEN a workload whose every run prints something else
    WHEN the trial runs
    THEN the measurement's warning reaches on_note with the trial prefix,
        carries NONDETERMINISTIC_NOTE, and the wall row has no fingerprint
    """
    rig.run.vary_output = True
    hypothesis = rig.hypothesis()

    trial = rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))

    marked = [n for n in rig.notes if NONDETERMINISTIC_NOTE in n]
    assert marked == [
        f"trial for hypothesis {hypothesis.id}: workload 'dedupe': the 5 timed"
        " runs did not agree on one output; no output fingerprint"
    ]
    [wall] = [m for m in trial.measurements if m.metric == METRIC_WALL_TIME_S]
    assert wall.output_fingerprint is None


# ---------------------------------------------------------------------------
# Trial runner: fingerprints and the own ref (decisions 16 and 18)
# ---------------------------------------------------------------------------


def test_a_run_that_creates_a_branch_raises_repo_tampered(rig: Rig) -> None:
    rig.run.hook = user_git(rig, "branch", "planted")

    with pytest.raises(RepoTamperedError, match="changed while the trial ran"):
        rig.trial(rig.hypothesis(), rig.runner(ScriptedEditor(DEDUPE_EDITS)))

    no_leftovers(rig)


def test_a_run_that_moves_the_own_ref_raises_repo_tampered(rig: Rig) -> None:
    hypothesis = rig.hypothesis()
    ref = f"refs/heads/{rig.branch(hypothesis)}"
    rig.run.hook = user_git(rig, "update-ref", ref, rig.commit)

    with pytest.raises(RepoTamperedError, match="own ref"):
        rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))

    no_leftovers(rig)


@dataclass
class SpendThenRaise:
    """Records a paid request into the budget, then raises ``error``."""

    error: Exception

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        budget.spent_usd += 0.2
        budget.tokens += 40
        raise self.error


def test_tampering_after_the_commit_undoes_the_own_ref_and_keeps_the_spend(
    rig: Rig,
) -> None:
    """
    GIVEN an editor that spent 0.3 USD, and the user committing (a new
        branch) while the committed trial is measured
    WHEN the trial runs
    THEN RepoTamperedError propagates carrying the 0.3 USD and 70 tokens
        spent, and the trial's own ref, which nothing records, is removed
    """
    rig.run.hook = user_git(rig, "branch", "planted")
    hypothesis = rig.hypothesis()

    with pytest.raises(RepoTamperedError, match="changed while") as raised:
        rig.trial(hypothesis, rig.runner(SpendingEditor(0.3, 70)))

    assert spend_of(raised.value) == (0.3, 70)
    assert rig.ref(hypothesis) is None
    no_leftovers(rig)


def test_tampering_in_a_re_executed_trial_puts_the_own_ref_back(rig: Rig) -> None:
    """
    GIVEN a trial already committed on its own ref, re-executed with another
        edit while the user creates a branch
    WHEN the re-executed trial is aborted as tampering
    THEN its own ref points at the earlier trial commit again
    """
    hypothesis = rig.hypothesis()
    first = rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))
    rig.run.hook = user_git(rig, "branch", "planted")
    other = WriteEditor({"dedupe/core.py": FAST_CORE + b"\n# again\n"})

    with pytest.raises(RepoTamperedError):
        rig.trial(hypothesis, rig.runner(other))

    assert rig.ref(hypothesis) == first.commit


def test_an_own_ref_someone_else_moved_is_left_where_they_put_it(rig: Rig) -> None:
    hypothesis = rig.hypothesis()
    ref = f"refs/heads/{rig.branch(hypothesis)}"
    rig.run.hook = user_git(rig, "update-ref", ref, rig.commit)

    with pytest.raises(RepoTamperedError, match="own ref"):
        rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))

    assert rig.ref(hypothesis) == rig.commit


@dataclass
class CheckoutThenTamper:
    """A run hook: once, the user checks ``branch`` out at ``path`` and creates
    a branch (tampering); ``seen`` is the branch's commit at that moment."""

    rig: Rig
    branch: str
    path: Path
    seen: str = ""

    def __call__(self, call: Call) -> None:
        if not self.path.exists():
            git(self.rig.repo, "worktree", "add", "-q", str(self.path), self.branch)
            git(self.rig.repo, "branch", "-f", "planted")
            self.seen = git(self.rig.repo, "rev-parse", self.branch)


@pytest.mark.parametrize("rerun", [False, True], ids=["new-ref", "re-executed"])
def test_an_aborted_trial_leaves_an_own_ref_a_worktree_checked_out(
    rig: Rig, rerun: bool
) -> None:
    """
    GIVEN the user checks the trial branch out in a new worktree while the
        committed trial is measured, and creates a branch (tampering)
    WHEN the trial is aborted (RepoTamperedError)
    THEN the own ref is left alone, so the user's worktree HEAD still
        resolves to it, and a note says why, without claiming where the ref
        is now (the worktree may have moved it)
    """
    hypothesis = rig.hypothesis()
    branch = rig.branch(hypothesis)
    first = None
    if rerun:
        first = rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))
        editor: CodeEditor = WriteEditor({"dedupe/core.py": FAST_CORE + b"\n# 2\n"})
    else:
        editor = ScriptedEditor(DEDUPE_EDITS)
    user_wt = rig.root / "user-wt"
    hook = rig.run.hook = CheckoutThenTamper(rig, branch, user_wt)

    with pytest.raises(RepoTamperedError, match="changed while"):
        rig.trial(hypothesis, rig.runner(editor))

    moved = hook.seen
    assert moved and (first is None or moved != first.commit)
    assert rig.ref(hypothesis) == moved
    assert git(user_wt, "symbolic-ref", "HEAD") == f"refs/heads/{branch}"
    assert git(user_wt, "rev-parse", "HEAD") == moved
    assert rig.notes[-1] == (
        f"trial for hypothesis {hypothesis.id}: refs/heads/{branch} was left"
        f" alone (the aborted trial had moved it to {moved}): a worktree has it"
        " checked out"
    )
    assert not rig.run_dir.exists()


@pytest.mark.parametrize(
    "error",
    [LLMConfigError("402: billing"), RuntimeError("bug")],
    ids=["engine-error", "other"],
)
def test_an_editor_exception_carries_the_money_it_spent(
    rig: Rig, error: Exception
) -> None:
    with pytest.raises(type(error)) as raised:
        rig.trial(rig.hypothesis(), rig.runner(SpendThenRaise(error)))

    assert spend_of(raised.value) == (0.2, 40)
    no_leftovers(rig)


def test_a_re_executed_trial_is_idempotent(rig: Rig) -> None:
    hypothesis = rig.hypothesis("h1")
    runner = rig.runner(ScriptedEditor(DEDUPE_EDITS))

    first = rig.trial(hypothesis, runner)
    second = rig.trial(hypothesis, runner)

    assert (first.id, first.commit) == (second.id, second.commit)
    assert second.status is TrialStatus.measured
    assert rig.ref(hypothesis) == second.commit


def test_a_re_executed_trial_re_points_its_own_ref(rig: Rig) -> None:
    hypothesis = rig.hypothesis()
    first = rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))
    other = WriteEditor({"dedupe/core.py": FAST_CORE + b"# again\n"})

    second = rig.trial(hypothesis, rig.runner(other))

    assert second.commit not in (None, first.commit)
    assert rig.ref(hypothesis) == second.commit


def test_a_re_executed_trial_that_commits_nothing_drops_its_stale_ref(
    rig: Rig,
) -> None:
    hypothesis = rig.hypothesis()
    rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))
    failing = FakeEditor({"h1": EditResult(stop="error", error="boom")})

    second = rig.trial(hypothesis, rig.runner(failing))

    assert second.commit is None and rig.ref(hypothesis) is None


@pytest.mark.parametrize("target", ["other-trial", "user-commit"])
def test_a_foreign_own_ref_is_never_moved(rig: Rig, target: str) -> None:
    """
    GIVEN the trial's ref already exists at a commit with another trial's
        trailer (a later round), or at the user's own commit (no trailer)
    WHEN the trial runs
    THEN EngineError before any worktree exists, and the ref is untouched
    """
    hypothesis = rig.hypothesis()
    ref = f"refs/heads/{rig.branch(hypothesis)}"
    if target == "user-commit":
        oid = rig.commit
    else:
        rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)), round=2)
        oid = git(rig.repo, "rev-parse", ref)
    git(rig.repo, "update-ref", ref, oid)
    rig.run.calls.clear()

    with pytest.raises(EngineError, match="not this trial's"):
        rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))

    assert git(rig.repo, "rev-parse", ref) == oid
    assert rig.run.calls == []
    no_leftovers(rig)


# ---------------------------------------------------------------------------
# Trial runner: argument checks
# ---------------------------------------------------------------------------


def test_a_trial_branch_checked_out_by_the_user_is_never_moved(rig: Rig) -> None:
    """
    GIVEN a committed trial whose branch the user then checks out in a worktree
    WHEN the trial is re-executed with another edit
    THEN EngineError before any worktree exists; the user's worktree HEAD,
        status and the ref are unchanged
    """
    hypothesis = rig.hypothesis()
    first = rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))
    checkout = rig.root / "user-checkout"
    git(rig.repo, "worktree", "add", "-q", str(checkout), rig.branch(hypothesis))
    rig.run.calls.clear()
    other = WriteEditor({"dedupe/core.py": FAST_CORE + b"# again\n"})

    with pytest.raises(EngineError, match="checked out"):
        rig.trial(hypothesis, rig.runner(other))

    assert git(checkout, "rev-parse", "HEAD") == first.commit
    assert git(checkout, "status", "--porcelain") == ""
    assert rig.ref(hypothesis) == first.commit
    assert other.tasks == [] and rig.run.calls == []
    assert not rig.run_dir.exists()


def test_a_trial_branch_checked_out_while_the_editor_ran_is_never_moved(
    rig: Rig,
) -> None:
    """
    GIVEN a committed trial, re-executed, and the user checks its branch out
        while the editor works
    WHEN the runner would re-point the ref
    THEN EngineError, the user's HEAD and the ref stay at the first commit
    """
    hypothesis = rig.hypothesis()
    first = rig.trial(hypothesis, rig.runner(ScriptedEditor(DEDUPE_EDITS)))
    checkout = rig.root / "user-checkout"

    class CheckoutMidway(WriteEditor):
        def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
            git(
                rig.repo, "worktree", "add", "-q", str(checkout), rig.branch(hypothesis)
            )
            return super().edit(worktree, task, budget)

    editor = CheckoutMidway({"dedupe/core.py": FAST_CORE + b"# again\n"})

    with pytest.raises(EngineError, match="checked out"):
        rig.trial(hypothesis, rig.runner(editor))

    assert git(checkout, "rev-parse", "HEAD") == first.commit
    assert git(checkout, "status", "--porcelain") == ""
    assert rig.ref(hypothesis) == first.commit
    assert not rig.run_dir.exists()


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), -0.01])
def test_a_bad_budget_is_refused(rig: Rig, budget: float) -> None:
    with pytest.raises(ValueError, match="budget_usd"):
        rig.trial(rig.hypothesis(), rig.runner(FakeEditor({})), budget_usd=budget)


def test_a_baseline_without_a_commit_is_refused(rig: Rig) -> None:
    runner = rig.runner(FakeEditor({}))
    load = rig.workload()
    baseline = rig.baseline([load]).model_copy(update={"commit": None})

    with pytest.raises(ValueError, match="commit"):
        rig.trial(rig.hypothesis(), runner, workloads=[load], baseline=baseline)


@pytest.mark.parametrize(
    "branch",
    [
        "engine/run-run1",
        "engine/trial--{h}",
        "other/trial-run1-{h}",
        "engine/trial-a/b-{h}",
    ],
)
def test_a_branch_that_does_not_name_this_trial_is_refused(
    rig: Rig, branch: str
) -> None:
    hypothesis = rig.hypothesis()
    load = rig.workload()

    with pytest.raises(ValueError, match="branch|run id"):
        rig.runner(FakeEditor({})).run(
            hypothesis,
            [load],
            rig.baseline([load]),
            round=1,
            branch=branch.format(h=hypothesis.id),
            budget_usd=1.0,
            brief=TrialBrief(None, (), ()),
        )

    assert git(rig.repo, "worktree", "list", "--porcelain").count("worktree ") == 1


def prefixed_runner(rig: Rig, prefix: str) -> GitTrialRunner:
    def build(
        *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
    ) -> CodeEditor:
        return ScriptedEditor(DEDUPE_EDITS)

    return GitTrialRunner(
        rig.project,
        editor=build,
        network="required",
        fs="required",
        platform="linux",
        base_env={"PATH": "/usr/bin"},
        run=rig.run,
        prefix=prefix,
    )


def test_the_trial_ref_lives_under_the_callers_prefix(rig: Rig) -> None:
    """
    GIVEN a runner built with the context's prefix bots/ (not the setting's)
    WHEN a trial on bots/trial-<run>-<hyp> commits
    THEN its own ref is refs/heads/bots/trial-<run>-<hyp>, and a branch
        under the setting's prefix is refused before any worktree
    """
    hypothesis = rig.hypothesis()
    load = rig.workload()
    runner = prefixed_runner(rig, "bots/")
    branch = f"bots/trial-{RUN_ID}-{hypothesis.id}"

    trial = runner.run(
        hypothesis, [load], rig.baseline([load]), round=1, branch=branch,
        budget_usd=1.0, brief=TrialBrief(None, (), DEFAULT_PROTECTED_PATTERNS),
    )  # fmt: skip

    assert trial.status is TrialStatus.measured, trial.error
    assert git(rig.repo, "rev-parse", f"refs/heads/{branch}") == trial.commit
    no_leftovers(rig)
    with pytest.raises(ValueError, match="branch"):
        runner.run(
            hypothesis, [load], rig.baseline([load]), round=1,
            branch=rig.branch(hypothesis), budget_usd=1.0,
            brief=TrialBrief(None, (), ()),
        )  # fmt: skip


@pytest.mark.parametrize("prefix", ["", "bots", "a b/"])
def test_an_unsafe_prefix_is_refused_when_the_runner_is_built(
    rig: Rig, prefix: str
) -> None:
    with pytest.raises(ValueError, match="prefix"):
        prefixed_runner(rig, prefix)


# ---------------------------------------------------------------------------
# Cleanup: the shared phase helper (tests/execution/test_phase.py) is used
# ---------------------------------------------------------------------------


def move_run_dir(rig: Rig) -> Callable[[Call], None]:
    def move(call: Call) -> None:
        if not rig.run_dir.is_symlink():
            shutil.move(rig.run_dir, rig.root / "moved")
            os.symlink(rig.root / "moved", rig.run_dir)

    return move


def test_a_dir_that_cannot_be_removed_safely_is_an_engine_error(rig: Rig) -> None:
    hypothesis = rig.hypothesis()
    rig.run.hook = move_run_dir(rig)

    with pytest.raises(EngineError, match="could not clean up") as raised:
        rig.trial(hypothesis, rig.runner(FakeEditorThatWrites()))

    name = f"trial-{hypothesis.id}"
    assert str(rig.run_dir / "_scratch" / name) in str(raised.value)
    assert (rig.root / "moved" / "_probe" / name).is_dir()


def test_a_cleanup_problem_never_hides_the_error_already_raised(rig: Rig) -> None:
    move = move_run_dir(rig)

    def tamper(call: Call) -> None:
        move(call)
        git(rig.repo, "config", "user.name", "planted")

    rig.run.hook = tamper

    with pytest.raises(RepoTamperedError):
        rig.trial(rig.hypothesis(), rig.runner(FakeEditorThatWrites()))


class FakeEditorThatWrites(WriteEditor):
    def __init__(self) -> None:
        super().__init__({"dedupe/core.py": FAST_CORE})


class CleanupFailingGit(GitWorkspace):
    """A real workspace whose ``method`` raises ``error`` once a worktree exists
    (``add_worktree`` itself calls both first), as a git timeout or an
    unremovable file would."""

    def __init__(self, repo: Path, method: str, error: Exception) -> None:
        super().__init__(repo)
        self.method, self.error, self.armed = method, error, False

    def add_worktree(self, path: Path, commit: str) -> WorktreeHandle:
        handle = super().add_worktree(path, commit)
        self.armed = True
        return handle

    def remove_worktree(self, target: WorktreeHandle | Path) -> None:
        if self.armed and self.method == "remove_worktree":
            raise self.error
        super().remove_worktree(target)

    def prune(self) -> None:
        if self.armed and self.method == "prune":
            raise self.error
        super().prune()


CLEANUP_FAILURES = [
    pytest.param("remove_worktree", GitError("git worktree remove timed out"), id="remove-git"),
    pytest.param("remove_worktree", PermissionError(1, "Operation not permitted"), id="remove-os"),
    pytest.param("prune", GitError("git worktree list timed out"), id="prune-git"),
]  # fmt: skip


def assert_engine_dirs_removed(rig: Rig, phase: str, method: str) -> None:
    """Scratch and probe are gone whatever failed; the worktree only stays
    when its own removal failed."""
    assert not (rig.run_dir / "_scratch").exists()
    assert not (rig.run_dir / "_probe").exists()
    if method == "remove_worktree":
        assert os.listdir(rig.run_dir) == [phase]
    else:
        assert not rig.run_dir.exists()


@pytest.mark.parametrize(("method", "error"), CLEANUP_FAILURES)
def test_a_failing_cleanup_step_never_hides_tampering(
    rig: Rig, method: str, error: Exception
) -> None:
    hypothesis = rig.hypothesis()
    failing = CleanupFailingGit(rig.repo, method, error)
    rig.run.hook = user_git(rig, "config", "user.name", "planted")

    with pytest.raises(RepoTamperedError):
        rig.trial(hypothesis, rig.runner(FakeEditorThatWrites(), git_workspace=failing))

    assert_engine_dirs_removed(rig, f"trial-{hypothesis.id}", method)


# ---------------------------------------------------------------------------
# Baseline runner
# ---------------------------------------------------------------------------


def baseline_runner(
    rig: Rig, project: Project | None = None, *, git: GitWorkspace | None = None
) -> GitBaselineRunner:
    return GitBaselineRunner(
        project or rig.project,
        git=git,
        network="required",
        fs="required",
        platform="linux",
        base_env={"PATH": "/usr/bin"},
        run=rig.run,
        on_note=rig.notes.append,
    )


def test_the_baseline_measures_every_workload_and_counts_the_tests(
    rig: Rig,
) -> None:
    before = rig.state()
    loads = [rig.workload(), rig.workload(name="second", warmup_runs=1)]

    rows = baseline_runner(rig).measure(loads, run_id=RUN_ID, commit=rig.commit)

    metrics = [(m.workload_id, m.metric, m.trial_id) for m in rows]
    assert metrics == [
        *((loads[0].id, m, None) for m in (METRIC_WALL_TIME_S, METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES)),
        *((loads[1].id, m, None) for m in (METRIC_WALL_TIME_S, METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES)),
        (loads[0].id, METRIC_TESTS_PASSED, None),
        (loads[1].id, METRIC_TESTS_PASSED, None),
    ]  # fmt: skip
    assert rows[-1].hardware["tests_counted"] == TESTS
    worktree = rig.run_dir / "baseline"
    assert len(rig.run.calls) == 2 * settings.MIN_RUNS + 1 + 1
    assert {call.cwd for call in rig.run.calls} == {worktree}
    assert rig.state() == before
    no_leftovers(rig)


def test_a_baseline_without_a_test_command_runs_no_suite(rig: Rig) -> None:
    project = rig.project.model_copy(update={"test_command": None})

    rows = baseline_runner(rig, project).measure(
        [rig.workload()], run_id=RUN_ID, commit=rig.commit
    )

    assert METRIC_TESTS_PASSED not in {m.metric for m in rows}
    assert len(rig.run.calls) == settings.MIN_RUNS


def test_a_baseline_run_failure_is_an_engine_error_with_its_notes(rig: Rig) -> None:
    rig.run.exit, rig.run.notes = 3, ("note",)

    with pytest.raises(EngineError, match="the baseline could not be measured"):
        baseline_runner(rig).measure([rig.workload()], run_id=RUN_ID, commit=rig.commit)

    assert rig.notes == ["baseline: workload 'dedupe' run 1/5: note"]
    no_leftovers(rig)


def test_baseline_tampering_wins_over_a_run_failure(rig: Rig) -> None:
    rig.run.exit = 3
    rig.run.hook = user_git(rig, "branch", "planted")

    with pytest.raises(RepoTamperedError, match="changed while the baseline ran"):
        baseline_runner(rig).measure([rig.workload()], run_id=RUN_ID, commit=rig.commit)

    no_leftovers(rig)


def test_baseline_measurement_notes_are_emitted(rig: Rig) -> None:
    rig.run.notes = ("weak",)

    baseline_runner(rig).measure([rig.workload()], run_id=RUN_ID, commit=rig.commit)

    assert rig.notes[0] == "baseline: workload 'dedupe' run 1/5: weak"
    assert rig.notes[-1] == "baseline: the test command: weak"


def test_a_nondeterministic_baseline_output_is_a_marked_note(rig: Rig) -> None:
    rig.run.vary_output = True

    rows = baseline_runner(rig).measure(
        [rig.workload()], run_id=RUN_ID, commit=rig.commit
    )

    marked = [n for n in rig.notes if NONDETERMINISTIC_NOTE in n]
    assert marked == [
        "baseline: workload 'dedupe': the 5 timed runs did not agree on one"
        " output; no output fingerprint"
    ]
    [wall] = [m for m in rows if m.metric == METRIC_WALL_TIME_S]
    assert wall.output_fingerprint is None


@pytest.mark.parametrize(("method", "error"), CLEANUP_FAILURES)
def test_a_failing_baseline_cleanup_step_still_runs_every_other_step(
    rig: Rig, method: str, error: Exception
) -> None:
    runner = baseline_runner(rig, git=CleanupFailingGit(rig.repo, method, error))

    with pytest.raises(EngineError, match="could not clean up") as raised:
        runner.measure([rig.workload()], run_id=RUN_ID, commit=rig.commit)

    assert str(error) in str(raised.value)
    assert_engine_dirs_removed(rig, "baseline", method)


def test_a_baseline_cleanup_problem_is_an_engine_error(rig: Rig) -> None:
    rig.run.hook = move_run_dir(rig)

    with pytest.raises(EngineError, match="could not clean up"):
        baseline_runner(rig).measure([rig.workload()], run_id=RUN_ID, commit=rig.commit)


@pytest.mark.parametrize(("method", "error"), CLEANUP_FAILURES)
def test_a_failing_baseline_cleanup_step_never_hides_tampering(
    rig: Rig, method: str, error: Exception
) -> None:
    runner = baseline_runner(rig, git=CleanupFailingGit(rig.repo, method, error))
    rig.run.hook = user_git(rig, "config", "user.name", "planted")

    with pytest.raises(RepoTamperedError):
        runner.measure([rig.workload()], run_id=RUN_ID, commit=rig.commit)

    assert_engine_dirs_removed(rig, "baseline", method)


@pytest.mark.parametrize("run_id", ["", "../x", "a/b", "x..y", "-x", "x.lock"])
def test_an_unsafe_run_id_is_refused(rig: Rig, run_id: str) -> None:
    with pytest.raises(ValueError, match="run id"):
        baseline_runner(rig).measure([rig.workload()], run_id=run_id, commit=rig.commit)

    assert rig.run.calls == []


def test_a_baseline_without_a_commit_is_refused_before_anything_runs(
    rig: Rig,
) -> None:
    with pytest.raises(ValueError, match="commit"):
        baseline_runner(rig).measure([rig.workload()], run_id=RUN_ID, commit=None)

    assert rig.run.calls == []


def test_the_runners_default_to_the_projects_git_workspace(rig: Rig) -> None:
    runner = GitTrialRunner(
        rig.project, editor=lambda **_: ScriptedEditor(DEDUPE_EDITS)
    )

    assert runner.git.repo == rig.repo


# ---------------------------------------------------------------------------
# The real launcher
# ---------------------------------------------------------------------------


def _require() -> bool:
    return "1" in (
        os.environ.get("REQUIRE_NETWORK_SANDBOX"),
        os.environ.get("REQUIRE_FS_SANDBOX"),
    )


def _linux_sandbox_problem() -> str | None:
    if shutil.which("unshare") is None:
        return "unshare is not installed"
    probe = subprocess.run(
        [*UNSHARE_ARGV, "true"], capture_output=True, timeout=30, check=False
    )
    if probe.returncode != 0:
        return f"{' '.join(UNSHARE_ARGV)} true failed"
    try:
        launcher.default_ops().syscall(444, (None, 0, 1))
    except OSError as error:
        return f"Landlock is unavailable: {error}"
    return None


@pytest.fixture(scope="module")
def linux_sandbox() -> None:
    problem = _linux_sandbox_problem()
    if problem is not None:
        if _require():
            pytest.fail(f"sandbox required but unavailable: {problem}")
        pytest.skip(problem)


def real_cycle(rig: Rig, mode: IsolationMode) -> None:
    """Baseline, then the h1 trial, through the real launcher and real git."""
    before = rig.state()
    load = rig.workload()
    base_rows = GitBaselineRunner(rig.project, network=mode, fs=mode).measure(
        [load], run_id=RUN_ID, commit=rig.commit
    )
    baseline = Baseline(
        commit=rig.commit,
        measurements=base_rows,
        objectives=rig.baseline([]).objectives,
    )
    runner = GitTrialRunner(
        rig.project,
        editor=lambda **_: ScriptedEditor(DEDUPE_EDITS),
        network=mode,
        fs=mode,
    )
    hypothesis = rig.hypothesis("h1")

    trial = rig.trial(hypothesis, runner, workloads=[load], baseline=baseline)

    assert trial.status is TrialStatus.measured, trial.error
    by_metric = {m.metric: m for m in trial.measurements}
    base_by_metric = {m.metric: m for m in base_rows}
    assert by_metric[METRIC_TESTS_PASSED].samples == (1.0,)
    assert base_by_metric[METRIC_TESTS_PASSED].hardware["tests_counted"] == TESTS
    wall = by_metric[METRIC_WALL_TIME_S]
    assert wall.output_fingerprint is not None
    assert (
        wall.output_fingerprint == base_by_metric[METRIC_WALL_TIME_S].output_fingerprint
    )
    assert rig.state() == before and rig.ref(hypothesis) == trial.commit
    no_leftovers(rig)


def test_real_baseline_and_trial_cycle_leaves_only_the_trial_ref(rig: Rig) -> None:
    """
    GIVEN the dedupe fixture, isolation off (runs on every platform)
    WHEN the baseline and then the h1 trial run through the real launcher
    THEN both measure, the outputs agree, the suite passes with the
        baseline's count, and only the trial's own ref was added
    """
    real_cycle(rig, "off")


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_sandboxed_cycle(rig: Rig) -> None:
    real_cycle(rig, "required")
