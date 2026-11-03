"""The compound replay (G5b): ``GitTrialRunner.replay``.

A compound's commit is built by cherry-picking its two measured parent
commits onto the run's base with the combiner's hardened git
(``GitWorkspace.merge``, ``merge-tree --write-tree``: objects only, no ref,
no index, no hook), never by the editor: no request, no tokens. The merged
tree is checked out in the trial's own worktree and then runs exactly as an
edited trial does: capture, every anti-cheat rule on its own diff against
the base, the engine commit with its trailer (one child of the base), its
own measurements. A conflict or an unfit parent raises ``ReplayRefusedError``
before any worktree exists, so the repository is left exactly as it was.

Fakes: ``Clock`` stands for ``procrun.run_once`` (it answers the timed runs
and the suite, with a wall time per phase), ``Edits`` for ``ClaudeEditor``
(the parents' edits) and ``NoEditor`` for an editor the replay must never
call; ``Brittle`` is the real ``GitWorkspace`` whose ``staged_blob`` fails
on demand. Git is real.
"""

from __future__ import annotations

import hashlib
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
    Violation,
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
    WorktreeHandle,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import GitTrialRunner
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.optimization.evolve import ReplayRefusedError

DEDUPE = Path(__file__).resolve().parents[1] / "fixtures" / "dedupe_repo"
PY, TESTS = sys.executable, 11
CORE, MAIN = "dedupe/core.py", "dedupe/main.py"
BASE_CORE, BASE_MAIN = (DEDUPE / CORE).read_text(), (DEDUPE / MAIN).read_text()
LOOP = (
    "    result: list[int] = []\n    for item in items:\n"
    "        if item not in result:\n            result.append(item)\n    return result\n"
)
FEWER = BASE_CORE.replace(LOOP, "    return list(dict.fromkeys(items))\n")
OTHER = BASE_CORE.replace(LOOP, "    seen: set[int] = set()\n    return [i for i in items if not (i in seen or seen.add(i))]\n")  # fmt: skip
MAIN_NOTE = BASE_MAIN + "# parse once\n"
ENV = {"PATH": os.defpath, "HOME": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull}
ENV |= {"GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
ENV |= {f"GIT_{r}_{k}": v for r in ("AUTHOR", "COMMITTER") for k, v in
        (("NAME", "User"), ("EMAIL", "u@example.invalid"), ("DATE", "@1700000000 +0000"))}  # fmt: skip


def git(cwd: Path, *args: str, env: Mapping[str, str] | None = None, stdin: bytes | None = None) -> str:  # fmt: skip
    done = subprocess.run(
        ["git", "-C", str(cwd), *args], env={**ENV, **(env or {})},
        capture_output=True, input=stdin,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return done.stdout.decode().strip()


@dataclass
class Clock:
    """``run_once``: ``calls`` records each launch as ``<kind> <phase>``; a
    timed run of a phase in ``wall_ns`` takes that long (else 0.1 s)."""

    run_dir: Path
    wall_ns: dict[str, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        phase = cwd.relative_to(self.run_dir).parts[0]
        err = b""
        if "unittest" in argv:
            self.calls.append(f"suite {phase}")
            err = f"Ran {TESTS} tests in 0.010s\n\nOK\n".encode()
        else:
            self.calls.append(f"run {phase}")
        wall = self.wall_ns.get(phase, 100_000_000)
        return RunSample(wall, 0.1, 0.0, 1 << 20, 0, True, True, "1" * 64, b"", 0, err)  # fmt: skip


@dataclass
class Edits:
    files: Mapping[str, str]

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        for path, text in self.files.items():
            (worktree / path).write_text(text)
        sizes = {path: len(text.encode()) for path, text in self.files.items()}
        return EditResult(sizes, cost_usd=0.01, tokens_used=10)


class NoEditor:
    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        raise AssertionError("a replay never asks the editor")


class Brittle(GitWorkspace):
    """The real workspace; ``staged_blob`` raises once ``broken`` is set."""

    broken = False

    def staged_blob(self, handle: WorktreeHandle, path: str) -> bytes:
        if self.broken:
            raise GitError("cat-file failed")
        return super().staged_blob(handle, path)


@dataclass
class Rig:
    repo: Path
    base: str
    project: Project
    clock: Clock
    notes: list[str] = field(default_factory=list)
    workspace: GitWorkspace | None = None

    def workload(self) -> Workload:
        return Workload(
            project_id=self.project.id, name="dedupe", warmup_runs=0, runs=5,
            command=(PY, "-m", "dedupe.main", "2000"), timeout_s=60.0,
        )  # fmt: skip

    def runner(self, editor: CodeEditor, **options: object) -> GitTrialRunner:
        def build(
            *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
        ) -> CodeEditor:
            return editor

        return GitTrialRunner(
            self.project, editor=build, network="required", fs="required",
            platform="linux", base_env={"PATH": "/usr/bin"}, run=self.clock,
            on_note=self.notes.append, git=self.workspace, **options,  # type: ignore[arg-type]
        )  # fmt: skip

    def hypothesis(self, title: str) -> Hypothesis:
        return Hypothesis(
            project_id=self.project.id, source=HypothesisSource.novel, title=title,
            rationale="r", change_class=ChangeClass.efficiency, expected_gain=0.1,
            provability=0.9, risk=0.1,
        )  # fmt: skip

    def baseline(self) -> Baseline:
        rows = (
            Measurement(workload_id=self.workload_id, metric=METRIC_TESTS_PASSED,
                        stats=RunStats.from_samples((1.0,), unit="bool"),
                        samples=(1.0,), hardware={"tests_counted": TESTS}),
        )  # fmt: skip
        objective = Objective(
            project_id=self.project.id, kind=ObjectiveKind.runtime, description="x",
            metric=METRIC_WALL_TIME_S, direction=Direction.minimize,
        )  # fmt: skip
        return Baseline(commit=self.base, measurements=rows, objectives=(objective,))

    workload_id: str = ""

    def brief(self) -> TrialBrief:
        return TrialBrief(None, (), DEFAULT_PROTECTED_PATTERNS, fix_retries_left=0)

    def branch(self, hypothesis: Hypothesis) -> str:
        return f"{settings.TRIAL_BRANCH_PREFIX}trial-run1-{hypothesis.id}"

    def parent(self, title: str, files: Mapping[str, str], workload: Workload) -> Trial:
        hypothesis = self.hypothesis(title)
        return self.runner(Edits(files)).run(
            hypothesis, [workload], self.baseline(), round=1, budget_usd=1.0,
            branch=self.branch(hypothesis), brief=self.brief(),
        )  # fmt: skip

    def replay(
        self, parents: Sequence[Trial], workload: Workload, **options: object
    ) -> tuple[Trial, Hypothesis]:
        hypothesis = self.hypothesis("compound")
        trial = self.runner(NoEditor(), **options).replay(
            hypothesis, parents, [workload], self.baseline(), round=2,
            branch=self.branch(hypothesis), budget_usd=1.0, brief=self.brief(),
        )  # fmt: skip
        return trial, hypothesis

    def snapshot(self) -> tuple[str, ...]:
        """Refs, worktrees, status (ignored files too), HEAD, the index bytes,
        the worktree admin dirs and the engine's run dir."""
        common = self.repo / ".git"
        admin = sorted(p.name for p in (common / "worktrees").glob("*")) if (common / "worktrees").exists() else []  # fmt: skip
        return (
            git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)"),
            git(self.repo, "worktree", "list", "--porcelain"),
            git(self.repo, "status", "--porcelain", "--ignored"),
            git(self.repo, "rev-parse", "HEAD"),
            hashlib.sha256((common / "index").read_bytes()).hexdigest(),
            ",".join(admin),
            str(
                sorted(p.name for p in self.clock.run_dir.glob("*"))
                if self.clock.run_dir.exists()
                else None
            ),  # fmt: skip
        )

    def crafted(
        self, files: Mapping[str, str], *, parent: str | None = None,
        trailer: str | None, merge: str | None = None,
    ) -> str:  # fmt: skip
        """A commit object (no ref) with ``files`` changed on ``parent`` (the
        base) and an ``Engine-Trial`` trailer, built with plain git."""
        onto = parent or self.base
        index = self.repo.parent / f"index-{len(files)}-{trailer}"
        env = {"GIT_INDEX_FILE": str(index)}
        git(self.repo, "read-tree", onto, env=env)
        for path, text in files.items():
            blob = git(self.repo, "hash-object", "-w", "--stdin", stdin=text.encode())
            git(self.repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)  # fmt: skip
        tree = git(self.repo, "write-tree", env=env)
        index.unlink()
        message = "crafted\n" + (
            "" if trailer is None else f"\nEngine-Trial: {trailer}\n"
        )
        second = () if merge is None else ("-p", merge)
        return git(self.repo, "commit-tree", tree, "-p", onto, *second, "-m", message)


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


@pytest.fixture
def workload(rig: Rig) -> Workload:
    found = rig.workload()
    rig.workload_id = found.id
    return found


def nothing_left(rig: Rig) -> None:
    assert git(rig.repo, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert not rig.clock.run_dir.exists()


def test_a_replay_cherry_picks_both_parents_onto_the_base_with_no_editor(
    rig: Rig, workload: Workload
) -> None:
    """
    GIVEN two measured trials, one on core.py and one on main.py
    WHEN their compound is replayed
    THEN the editor is never asked and nothing is spent; the commit is one
         child of the base with both changes and the compound's own trailer,
         its own ref points at it, its diff names both files, it is measured
         from its own runs (its own phase, its own wall time, its own id),
         and nothing is left behind
    """
    a = rig.parent("dict.fromkeys", {CORE: FEWER}, workload)
    b = rig.parent("note", {MAIN: MAIN_NOTE}, workload)
    before = list(rig.clock.calls)

    trial, hypothesis = rig.replay([a, b], workload)

    assert trial.status is TrialStatus.measured and trial.error is None
    assert (trial.cost_usd, trial.tokens_used, trial.attempts) == (0.0, 0, 1)
    assert trial.commit not in (None, a.commit, b.commit)
    commit = str(trial.commit)
    assert git(rig.repo, "rev-parse", f"{commit}^@") == rig.base
    assert git(rig.repo, "show", f"{commit}:{CORE}") == FEWER.strip()
    assert git(rig.repo, "show", f"{commit}:{MAIN}") == MAIN_NOTE.strip()
    assert f"Engine-Trial: {trial.id}" in git(rig.repo, "log", "-1", "--format=%B", commit)  # fmt: skip
    assert git(rig.repo, "rev-parse", f"refs/heads/{rig.branch(hypothesis)}") == commit
    assert set(trial.touched_paths) == {CORE, MAIN}
    assert f"+++ b/{CORE}" in trial.diff and f"+++ b/{MAIN}" in trial.diff
    phase = f"trial-{hypothesis.id}"
    assert rig.clock.calls[len(before):] == [*[f"run {phase}"] * 5, f"suite {phase}"]  # fmt: skip
    assert {m.trial_id for m in trial.measurements} == {trial.id}
    nothing_left(rig)


def test_the_compound_is_measured_from_its_own_runs(
    rig: Rig, workload: Workload
) -> None:
    """Its phase runs faster than its parents': its rows say so, theirs do not."""
    a = rig.parent("dict.fromkeys", {CORE: FEWER}, workload)
    b = rig.parent("note", {MAIN: MAIN_NOTE}, workload)
    hypothesis = rig.hypothesis("compound")
    rig.clock.wall_ns[f"trial-{hypothesis.id}"] = 40_000_000

    trial = rig.runner(NoEditor()).replay(
        hypothesis, [a, b], [workload], rig.baseline(), round=2,
        branch=rig.branch(hypothesis), budget_usd=1.0, brief=rig.brief(),
    )  # fmt: skip

    wall = {m.trial_id: m.stats.mean for p in (a, b, trial) for m in p.measurements
            if m.metric == METRIC_WALL_TIME_S}  # fmt: skip
    assert wall[trial.id] == pytest.approx(0.04)
    assert wall[a.id] == pytest.approx(0.1) == wall[b.id]


def test_a_paired_replay_is_measured_against_its_own_twin(
    rig: Rig, workload: Workload
) -> None:
    a = rig.parent("dict.fromkeys", {CORE: FEWER}, workload)
    b = rig.parent("note", {MAIN: MAIN_NOTE}, workload)

    trial, hypothesis = rig.replay([a, b], workload, paired=True)

    assert trial.status is TrialStatus.measured
    assert trial.base_measurements and all(m.trial_id is None for m in trial.base_measurements)  # fmt: skip
    assert f"run twin-trial-{hypothesis.id}" in rig.clock.calls
    nothing_left(rig)


def test_a_cherry_pick_conflict_leaves_the_repository_exactly_as_before(
    rig: Rig, workload: Workload
) -> None:
    """
    GIVEN two measured trials that rewrote the same lines of core.py
    WHEN their compound is replayed
    THEN ``ReplayRefusedError`` names the conflict and the file; refs, worktrees,
         status, HEAD, the index, the admin dirs and the run dir are exactly
         as before, and nothing ran
    """
    a = rig.parent("dict.fromkeys", {CORE: FEWER}, workload)
    b = rig.parent("a seen set", {CORE: OTHER}, workload)
    before, calls = rig.snapshot(), list(rig.clock.calls)

    with pytest.raises(ReplayRefusedError) as refused:
        rig.replay([a, b], workload)

    assert (refused.value.reason, refused.value.paths) == ("conflict", (CORE,))
    assert rig.snapshot() == before
    assert rig.clock.calls == calls
    nothing_left(rig)


def test_a_protected_path_never_reaches_a_compound(
    rig: Rig, workload: Workload
) -> None:
    """
    GIVEN a trial whose editor rewrote a test: it is failed by capture and
          never committed, so it has no commit a replay could pick
    AND a crafted commit on the base that changes the same test, with a
        trailer, posing as a measured parent
    WHEN the compound of a real parent and the crafted one is replayed
    THEN the compound's own capture rejects its diff (protected_path): it is
         failed, never committed and never executed
    """
    test_file = "tests/test_core.py"
    cheat = rig.parent("skip the slow test", {test_file: "# nothing\n"}, workload)
    a = rig.parent("dict.fromkeys", {CORE: FEWER}, workload)
    forged_id = "0" * 8 + "-0000-4000-8000-000000000000"
    forged = Trial(
        id=forged_id, hypothesis_id="h", round=1, status=TrialStatus.measured,
        commit=rig.crafted({test_file: "# nothing\n"}, trailer=forged_id),
        touched_paths=(test_file,),
    )  # fmt: skip
    calls = list(rig.clock.calls)

    trial, hypothesis = rig.replay([a, forged], workload)

    assert cheat.status is TrialStatus.failed and cheat.commit is None
    assert ViolationRule.protected_path in {v.rule for v in cheat.violations}
    assert trial.status is TrialStatus.failed and trial.commit is None
    assert [v.path for v in trial.violations if v.rule is ViolationRule.protected_path] == [test_file]  # fmt: skip
    assert rig.clock.calls == calls
    assert git(rig.repo, "for-each-ref", f"refs/heads/{rig.branch(hypothesis)}") == ""
    nothing_left(rig)


def _unfit(rig: Rig, a: Trial, case: str) -> Trial:
    other = "1" * 8 + "-0000-4000-8000-000000000000"
    if case == "no commit":
        return a.model_copy(update={"id": other, "commit": None})
    if case == "not a commit id":
        return a.model_copy(update={"id": other, "commit": "HEAD"})
    if case == "no such commit":
        return a.model_copy(update={"id": other, "commit": "e" * 40})
    if case == "no trailer of its own":
        return a.model_copy(update={"id": other, "commit": rig.crafted({MAIN: MAIN_NOTE}, trailer=None)})  # fmt: skip
    if case == "another trial's trailer":
        return a.model_copy(update={"id": other, "commit": rig.crafted({MAIN: MAIN_NOTE}, trailer=a.id)})  # fmt: skip
    if case == "not a child of the base":
        onto = rig.crafted({MAIN: MAIN_NOTE}, parent=str(a.commit), trailer=other)
        return a.model_copy(update={"id": other, "commit": onto})
    if case == "a merge commit":
        onto = rig.crafted({MAIN: MAIN_NOTE}, trailer=other, merge=str(a.commit))
        return a.model_copy(update={"id": other, "commit": onto})
    if case == "a failed trial":
        return a.model_copy(update={"status": TrialStatus.failed})
    assert case == "a trial with violations"
    spawn = Violation(rule=ViolationRule.process_spawn, message="x")
    return a.model_copy(update={"violations": (spawn,)})


@pytest.mark.parametrize(
    "case",
    ["no commit", "not a commit id", "no such commit", "no trailer of its own",
     "another trial's trailer", "not a child of the base", "a merge commit",
     "a failed trial",
     "a trial with violations"],
)  # fmt: skip
def test_an_unfit_parent_is_refused_before_anything_is_built(
    rig: Rig, workload: Workload, case: str
) -> None:
    a = rig.parent("dict.fromkeys", {CORE: FEWER}, workload)
    b = rig.parent("note", {MAIN: MAIN_NOTE}, workload)
    unfit = _unfit(rig, b, case)
    before, calls = rig.snapshot(), list(rig.clock.calls)

    with pytest.raises(ReplayRefusedError) as refused:
        rig.replay([a, unfit], workload)

    assert refused.value.reason.startswith("parent ") and refused.value.paths == ()
    assert rig.snapshot() == before and rig.clock.calls == calls


def test_a_replay_needs_two_parents(rig: Rig, workload: Workload) -> None:
    a = rig.parent("dict.fromkeys", {CORE: FEWER}, workload)

    with pytest.raises(ValueError, match="at least two parents"):
        rig.replay([a], workload)


def test_a_compound_over_the_write_limits_is_failed_unrun(
    rig: Rig, workload: Workload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No rule is relaxed: the two parents together pass the one-file limit
    each passed alone, so the compound is failed and never executed."""
    a = rig.parent("dict.fromkeys", {CORE: FEWER}, workload)
    b = rig.parent("note", {MAIN: MAIN_NOTE}, workload)
    monkeypatch.setattr(settings, "EDITOR_MAX_FILES", 1)
    calls = list(rig.clock.calls)

    trial, _ = rig.replay([a, b], workload)

    assert trial.status is TrialStatus.failed and trial.commit is None
    assert "over the trial's write limits" in str(trial.error)
    assert rig.clock.calls == calls
    nothing_left(rig)


def test_a_git_error_while_reading_the_replay_fails_the_trial(
    rig: Rig, workload: Workload
) -> None:
    brittle = Brittle(rig.repo)
    rig.workspace = brittle
    a = rig.parent("dict.fromkeys", {CORE: FEWER}, workload)
    b = rig.parent("note", {MAIN: MAIN_NOTE}, workload)
    brittle.broken = True

    trial, _ = rig.replay([a, b], workload)

    assert trial.status is TrialStatus.failed and trial.commit is None
    assert trial.error == "the replay could not be captured: cat-file failed"
    nothing_left(rig)


def test_a_git_error_in_the_merge_is_a_refusal(
    rig: Rig, workload: Workload, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = rig.parent("dict.fromkeys", {CORE: FEWER}, workload)
    b = rig.parent("note", {MAIN: MAIN_NOTE}, workload)

    def broken(self: GitWorkspace, acc: str, commit: str) -> object:
        raise GitError("merge-tree is too old")

    monkeypatch.setattr(GitWorkspace, "merge", broken)

    with pytest.raises(ReplayRefusedError, match="merge-tree is too old"):
        rig.replay([a, b], workload)
    nothing_left(rig)
