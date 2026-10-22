"""GitCombiner and GitBranchPublisher against real throwaway git repositories.

Every repository is built with the test's own git environment (no global or
system config, fixed identity and dates), and ``settings.WORKTREE_ROOT``
points into ``tmp_path``. Trial commits are made the way the trial runner
makes them: single-parent children of the base commit. The combiner's
measurement runs on an injected ``run_once`` double, so every launch, its
worktree and its order are asserted exactly; one test runs the real
launcher with isolation off, so it runs on any host.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import pytest

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import (
    DeliveryError,
    EngineError,
    RepoTamperedError,
)
from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    CombineSkip,
    Project,
    Workload,
)
from autonomous_ai_agents.execution.combine import GitBranchPublisher, GitCombiner
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.execution.procrun import OutputCaps, RunFailure, RunSample
from autonomous_ai_agents.execution.protocols import (
    BranchPublisher,
    CombineMeasured,
    Combiner,
    KeptChange,
    WorktreeHandle,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy

_ENV: dict[str, str] = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.devnull,
    "LC_ALL": "C",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "user@example.invalid",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "user@example.invalid",
    "GIT_AUTHOR_DATE": "@1700000000 +0100",
    "GIT_COMMITTER_DATE": "@1700003600 -0500",
}
RUN_ID = "run1"
PY = "/usr/bin/python3"
APP = "".join(f"line {n}\n" for n in range(1, 11))
UNITTEST_OK = b"...\n----\nRan 3 tests in 0.010s\n\nOK\n"
METRICS = (METRIC_WALL_TIME_S, METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES)


def run_git(
    cwd: Path,
    *args: str,
    stdin: bytes | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """The test's own git (never the engine's); requires exit 0."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        input=stdin,
        env={**_ENV, **(env or {})},
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc.stdout.decode().strip()


def child(
    repo: Path,
    parent: str,
    files: Mapping[str, str],
    *,
    extra_parents: Sequence[str] = (),
    label: str = "trial",
) -> str:
    """A commit on ``parent``'s tree with ``files`` rewritten, refs untouched."""
    index = repo.parent / f"index-{label}-{len(os.listdir(repo.parent))}"
    env = {"GIT_INDEX_FILE": str(index)}
    run_git(repo, "read-tree", parent, env=env)
    for path, text in files.items():
        blob = run_git(repo, "hash-object", "-w", "--stdin", stdin=text.encode())
        run_git(
            repo,
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{blob},{path}",
            env=env,
        )
    tree = run_git(repo, "write-tree", env=env)
    parents = [arg for p in (parent, *extra_parents) for arg in ("-p", p)]
    message = f"{label}\n\nEngine-Trial: {label}\n"
    return run_git(repo, "commit-tree", tree, *parents, "-m", message)


def edit_line(number: int, text: str) -> str:
    lines = APP.splitlines(keepends=True)
    lines[number - 1] = text + "\n"
    return "".join(lines)


def kept(trial_id: str, commit: str, *, gain: float | None = 0.5) -> KeptChange:
    return KeptChange(
        trial_id=trial_id,
        hypothesis_id=f"h-{trial_id}",
        verdict_id=f"v-{trial_id}",
        commit=commit,
        score=1.0,
        gain=gain,
    )


def sample(
    *, exit: int = 0, stderr: bytes = b"", notes: tuple[str, ...] = ()
) -> RunSample:
    return RunSample(
        wall_ns=1_000_000,
        utime=0.1,
        stime=0.0,
        maxrss_bytes=1 << 20,
        exit=exit,
        fs_isolated=True,
        net_isolated=True,
        stdout_sha256="0" * 64,
        stdout_head=b"",
        stdout_bytes=0,
        stderr_tail=stderr,
        notes=notes,
    )


class Call(NamedTuple):
    argv: tuple[str, ...]
    cwd: Path
    sandbox: SandboxPolicy
    fresh_dirs: tuple[Path, ...]


Respond = Callable[[Call], RunSample]


def default_respond(call: Call) -> RunSample:
    return sample(stderr=UNITTEST_OK if "unittest" in call.argv else b"")


@dataclass
class FakeRun:
    respond: Respond = default_respond
    calls: list[Call] = field(default_factory=list)

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
        return self.respond(call)

    def sides(self) -> list[str]:
        return [call.cwd.name for call in self.calls]


@dataclass
class Rig:
    root: Path
    repo: Path
    base: str
    t1: str  # app.py line 1
    t2: str  # lib.py
    t3: str  # app.py line 1 again: conflicts with t1
    project: Project
    run: FakeRun

    @property
    def wt_root(self) -> Path:
        return self.root / "wt-root"

    @property
    def run_dir(self) -> Path:
        return self.wt_root / RUN_ID

    def combiner(self, git: GitWorkspace | None = None) -> GitCombiner:
        return GitCombiner(
            git=git,
            network="required",
            fs="required",
            platform="linux",
            base_env={"PATH": "/usr/bin"},
            run=self.run,
        )

    def workload(self, name: str = "bench", **changes: object) -> Workload:
        fields: dict[str, object] = {
            "project_id": self.project.id,
            "name": name,
            "command": (PY, "bench.py"),
            "warmup_runs": 0,
        }
        fields.update(changes)
        return Workload.model_validate(fields)

    def combine(
        self,
        *changes: KeptChange,
        workloads: Sequence[Workload] | None = None,
        project: Project | None = None,
        combiner: GitCombiner | None = None,
        baseline_count: int | None = None,
    ) -> CombineMeasured:
        return (combiner or self.combiner()).combine(
            RUN_ID,
            project or self.project,
            self.base,
            changes,
            [self.workload()] if workloads is None else workloads,
            baseline_count=baseline_count,
        )

    def user_state(self) -> tuple[str, ...]:
        """What the user sees: HEAD, refs, index, status, config, worktrees."""
        return (
            run_git(self.repo, "symbolic-ref", "HEAD"),
            run_git(self.repo, "rev-parse", "HEAD"),
            run_git(self.repo, "for-each-ref"),
            run_git(self.repo, "ls-files", "--stage"),
            run_git(self.repo, "status", "--porcelain", "--ignored"),
            (self.repo / ".git" / "config").read_text(),
            run_git(self.repo, "worktree", "list", "--porcelain"),
        )

    def show(self, rev: str, path: str) -> str:
        return run_git(self.repo, "show", f"{rev}:{path}")


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    root = Path(os.path.realpath(tmp_path))
    (root / "wt-root").mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    repo = root / "user"
    run_git(root, "init", "-q", "-b", "main", str(repo))
    (repo / "app.py").write_text(APP)
    (repo / "lib.py").write_text("VALUE = 1\n")
    (repo / "bench.py").write_text("print(open('app.py').read())\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "base")
    base = run_git(repo, "rev-parse", "HEAD")
    t1 = child(repo, base, {"app.py": edit_line(1, "fast 1")}, label="t1")
    t2 = child(repo, base, {"lib.py": "VALUE = 2\n"}, label="t2")
    t3 = child(repo, base, {"app.py": edit_line(1, "other 1")}, label="t3")
    project = Project(name="demo", root_path=str(repo))
    return Rig(root, repo, base, t1, t2, t3, project, FakeRun())


def assert_cleaned(rig: Rig) -> None:
    assert not rig.run_dir.exists()
    listing = run_git(rig.repo, "worktree", "list", "--porcelain")
    assert listing.count("worktree ") == 1


# ---------------------------------------------------------------------------
# Combiner
# ---------------------------------------------------------------------------


def test_the_real_combiner_and_publisher_satisfy_the_protocols() -> None:
    assert isinstance(GitCombiner(), Combiner)
    assert isinstance(GitBranchPublisher(), BranchPublisher)


def test_two_independent_changes_make_a_linear_history_of_engine_commits(
    rig: Rig,
) -> None:
    """
    GIVEN two kept changes on disjoint files
    WHEN they are combined
    THEN the tip has both, as two single-parent commits on the base with the
        engine identity, the base's dates and an Engine-Trial trailer each,
        and the user's repository (HEAD, refs, index, status, config,
        worktrees) is exactly as before
    """
    before = rig.user_state()

    result = rig.combine(kept("t1", rig.t1), kept("t2", rig.t2))

    assert result.applied == ("t1", "t2")
    assert result.skipped == ()
    tip = result.tip_commit
    assert run_git(rig.repo, "rev-list", "--parents", f"{rig.base}..{tip}").split(
        "\n"
    ) == [
        f"{tip} {run_git(rig.repo, 'rev-parse', tip + '^')}",
        f"{run_git(rig.repo, 'rev-parse', tip + '^')} {rig.base}",
    ]
    assert rig.show(tip, "app.py") == edit_line(1, "fast 1").rstrip("\n")
    assert rig.show(tip, "lib.py") == "VALUE = 2"
    messages = run_git(rig.repo, "log", "--format=%B%x00", f"{rig.base}..{tip}")
    assert "Engine-Trial: t2" in messages.split("\0")[0]
    assert "Engine-Trial: t1" in messages.split("\0")[1]
    who = run_git(rig.repo, "log", "--format=%an <%ae>|%cn <%ce>", "-1", tip)
    assert who == "aip-engine <engine@aip.invalid>|aip-engine <engine@aip.invalid>"
    dates = "--format=%ad|%cd"
    assert run_git(rig.repo, "log", dates, "--date=raw", "-1", tip) == run_git(
        rig.repo, "log", dates, "--date=raw", "-1", rig.base
    )
    assert rig.user_state() == before
    assert_cleaned(rig)


def test_the_tip_is_reproducible_so_a_second_call_is_self_contained(
    rig: Rig,
) -> None:
    first = rig.combine(kept("t1", rig.t1), kept("t2", rig.t2))
    second = rig.combine(kept("t1", rig.t1), kept("t2", rig.t2))
    alone = rig.combine(kept("t2", rig.t2))

    assert second.tip_commit == first.tip_commit
    assert alone.applied == ("t2",)
    assert run_git(rig.repo, "rev-parse", alone.tip_commit + "^") == rig.base
    assert_cleaned(rig)


def test_the_re_test_interleaves_base_and_tip_and_runs_the_suite_on_the_tip(
    rig: Rig,
) -> None:
    """
    GIVEN one workload with a warm-up and a test command
    WHEN a change is combined
    THEN the runs alternate combine-base / combine (warm-up included), each
        side has its own scratch and probe dirs, the suite runs once on the
        tip only, and the result splits A rows from B rows plus tests_passed
    """
    project = rig.project.model_copy(update={"test_command": (PY, "-m", "unittest")})
    load = rig.workload(warmup_runs=1)

    result = rig.combine(kept("t1", rig.t1), workloads=[load], project=project)

    assert rig.run.sides() == ["combine-base", "combine"] * 6 + ["combine"]
    assert rig.run.calls[-1].argv == (PY, "-m", "unittest")
    for call in rig.run.calls:
        side = call.cwd.name
        assert call.sandbox.writable == (
            rig.run_dir / side,
            rig.run_dir / "_scratch" / side,
        )
        assert call.sandbox.probe_dir == rig.run_dir / "_probe" / side
    assert [(m.workload_id, m.metric) for m in result.baseline] == [
        (load.id, metric) for metric in METRICS
    ]
    assert [(m.workload_id, m.metric) for m in result.combined] == [
        *((load.id, metric) for metric in METRICS),
        (load.id, METRIC_TESTS_PASSED),
    ]
    assert all(m.stats.n == 5 for m in (*result.baseline, *result.combined[:3]))
    assert result.combined[-1].samples == (1.0,)
    assert_cleaned(rig)


def test_every_workload_is_re_tested_and_gets_its_own_tests_row(rig: Rig) -> None:
    project = rig.project.model_copy(update={"test_command": (PY, "-m", "unittest")})
    loads = [rig.workload("one"), rig.workload("two")]

    result = rig.combine(kept("t1", rig.t1), workloads=loads, project=project)

    assert len(rig.run.calls) == 2 * 10 + 1
    assert [m.workload_id for m in result.baseline] == [loads[0].id] * 3 + [
        loads[1].id
    ] * 3
    tests = [m for m in result.combined if m.metric == METRIC_TESTS_PASSED]
    assert [m.workload_id for m in tests] == [loads[0].id, loads[1].id]


@pytest.mark.parametrize(("count", "passed"), [(3, 1.0), (4, 0.0), (None, 1.0)])
def test_the_suite_must_reach_the_baseline_count(
    rig: Rig, count: int | None, passed: float
) -> None:
    project = rig.project.model_copy(update={"test_command": (PY, "-m", "unittest")})

    combiner = rig.combiner()
    result = rig.combine(
        kept("t1", rig.t1), project=project, combiner=combiner, baseline_count=count
    )

    [tests] = [m for m in result.combined if m.metric == METRIC_TESTS_PASSED]
    assert tests.samples == (passed,)
    if passed == 0.0:
        assert any("fewer than the baseline's 4" in n for n in combiner.last_notes)


def test_without_a_test_command_no_suite_runs(rig: Rig) -> None:
    result = rig.combine(kept("t1", rig.t1))

    assert len(rig.run.calls) == 10
    assert all(m.metric != METRIC_TESTS_PASSED for m in result.combined)


def test_a_conflict_is_skipped_with_its_paths_and_the_rest_still_applies(
    rig: Rig,
) -> None:
    result = rig.combine(kept("t1", rig.t1), kept("t3", rig.t3), kept("t2", rig.t2))

    assert result.applied == ("t1", "t2")
    assert result.skipped == (
        CombineSkip(trial_id="t3", reason="conflict", paths=("app.py",)),
    )
    assert rig.show(result.tip_commit, "app.py").startswith("fast 1")


def test_the_given_order_decides_which_side_of_a_conflict_wins(rig: Rig) -> None:
    result = rig.combine(kept("t3", rig.t3), kept("t1", rig.t1))

    assert result.applied == ("t3",)
    assert [skip.trial_id for skip in result.skipped] == ["t1"]


def test_a_change_with_nothing_left_to_apply_is_skipped(rig: Rig) -> None:
    same = child(rig.repo, rig.base, {"lib.py": "VALUE = 2\n"}, label="same")
    empty = child(rig.repo, rig.base, {}, label="empty")

    result = rig.combine(kept("t2", rig.t2), kept("same", same), kept("empty", empty))

    assert result.applied == ("t2",)
    assert [(s.trial_id, s.reason) for s in result.skipped] == [
        ("same", "nothing left to apply"),
        ("empty", "nothing left to apply"),
    ]


def test_a_commit_that_is_not_a_single_parent_child_of_the_base_is_skipped(
    rig: Rig,
) -> None:
    """
    GIVEN kept commits that would bring in more than their own diff (a
        grandchild of the base, a merge commit) or no commit at all
    WHEN they are combined
    THEN each is skipped before merge-tree sees it, and the real change
        still applies
    """
    grandchild = child(rig.repo, rig.t2, {"app.py": APP + "x\n"}, label="g")
    merge = child(rig.repo, rig.base, {"app.py": APP + "y\n"}, label="m",
                  extra_parents=[rig.t2])  # fmt: skip
    blob = run_git(rig.repo, "rev-parse", f"{rig.base}:lib.py")
    run_git(rig.repo, "tag", "-a", "-m", "t1", "t1-tag", rig.t1)
    tag = run_git(rig.repo, "rev-parse", "refs/tags/t1-tag")

    result = rig.combine(
        kept("g", grandchild),
        kept("m", merge),
        kept("missing", "f" * 40),
        kept("blob", blob),
        kept("tag", tag),
        kept("short", rig.t1[:12]),
        kept("base", rig.base),
        kept("t1", rig.t1),
    )

    assert result.applied == ("t1",)
    reasons = {skip.trial_id: skip.reason for skip in result.skipped}
    assert reasons == {
        "g": "not a single-parent child of the base commit",
        "m": "not a single-parent child of the base commit",
        "missing": "not a commit",
        "blob": "not a commit",
        "tag": "not a commit",
        "short": "not a commit",
        "base": "not a single-parent child of the base commit",
    }
    assert rig.show(result.tip_commit, "lib.py") == "VALUE = 1"


def test_nothing_applied_returns_the_base_unmeasured(rig: Rig) -> None:
    """
    GIVEN kept changes none of which can apply, or none at all
    WHEN nothing applies
    THEN the tip is the base, nothing is measured, no worktree is created
    """
    result = rig.combine(kept("missing", "f" * 40))
    nothing = rig.combine()

    for measured in (result, nothing):
        assert measured.tip_commit == rig.base
        assert measured.applied == ()
        assert measured.baseline == measured.combined == ()
    assert [skip.trial_id for skip in result.skipped] == ["missing"]
    assert rig.run.calls == []
    assert_cleaned(rig)


def test_only_the_first_of_two_identical_commits_applies(rig: Rig) -> None:
    result = rig.combine(kept("t3", rig.t3), kept("again", rig.t3))

    assert result.applied == ("t3",)
    assert result.skipped == (
        CombineSkip(trial_id="again", reason="nothing left to apply"),
    )


def test_run_notes_reach_last_notes_and_are_reset_per_call(rig: Rig) -> None:
    rig.run.respond = lambda call: sample(notes=("slow host",))
    combiner = rig.combiner()

    rig.combine(kept("t1", rig.t1), combiner=combiner)

    assert combiner.last_notes
    assert all(note.endswith("slow host") for note in combiner.last_notes)
    rig.combine(combiner=combiner)
    assert combiner.last_notes == ()


def test_a_run_failure_is_an_unmeasured_combination_and_a_note(rig: Rig) -> None:
    """
    GIVEN a combined tip whose workload fails on its third run
    WHEN it is re-tested
    THEN the result names what was applied but holds no rows (the node's
        completeness rule then refuses it), the reason is a note, and the
        worktrees are gone
    """

    def respond(call: Call) -> RunSample:
        if call.cwd.name == "combine" and len(rig.run.calls) > 4:
            raise RunFailure("boom", ("first note",))
        return sample()

    rig.run.respond = respond
    combiner = rig.combiner()

    result = rig.combine(kept("t1", rig.t1), combiner=combiner)

    assert result.applied == ("t1",)
    assert result.tip_commit != rig.base
    assert result.baseline == result.combined == ()
    assert any(n.endswith("first note") for n in combiner.last_notes)
    assert any(
        "not re-tested" in n and "B run 3/5: boom" in n for n in combiner.last_notes
    )
    assert_cleaned(rig)


def test_a_failing_test_run_is_also_an_unmeasured_combination(rig: Rig) -> None:
    project = rig.project.model_copy(update={"test_command": (PY, "-m", "unittest")})

    def respond(call: Call) -> RunSample:
        if "unittest" in call.argv:
            raise RunFailure("suite timed out")
        return sample()

    rig.run.respond = respond

    result = rig.combine(kept("t1", rig.t1), project=project)

    assert result.baseline == result.combined == ()


def test_tampering_during_the_re_test_raises_after_cleanup(rig: Rig) -> None:
    def respond(call: Call) -> RunSample:
        run_git(rig.repo, "update-ref", "refs/heads/planted", rig.base)
        return sample()

    rig.run.respond = respond

    with pytest.raises(RepoTamperedError, match="combine"):
        rig.combine(kept("t1", rig.t1))

    assert_cleaned(rig)


def test_tampering_is_checked_even_after_a_run_failure(rig: Rig) -> None:
    def respond(call: Call) -> RunSample:
        run_git(rig.repo, "config", "core.hooksPath", "/tmp/x")
        raise RunFailure("boom")

    rig.run.respond = respond

    with pytest.raises(RepoTamperedError):
        rig.combine(kept("t1", rig.t1))


def test_a_stale_combine_base_is_replaced_by_a_fresh_worktree(rig: Rig) -> None:
    stale = rig.run_dir / "combine-base"
    stale.mkdir(parents=True)
    (stale / "planted.txt").write_text("state from an earlier run")
    seen: list[bool] = []

    def respond(call: Call) -> RunSample:
        seen.append((call.cwd / "planted.txt").exists())
        return sample()

    rig.run.respond = respond

    rig.combine(kept("t1", rig.t1))

    assert seen and not any(seen)
    assert_cleaned(rig)


class FailingAdd(GitWorkspace):
    """Fails the second ``add_worktree`` (combine-base)."""

    def __init__(self, repo: Path) -> None:
        super().__init__(repo)
        self.adds = 0

    def add_worktree(self, path: Path, commit: str) -> WorktreeHandle:
        self.adds += 1
        if self.adds == 2:
            raise GitError("worktree add failed")
        return super().add_worktree(path, commit)


def test_a_failed_worktree_add_still_cleans_up(rig: Rig) -> None:
    git = FailingAdd(rig.repo)

    with pytest.raises(GitError, match="worktree add failed"):
        rig.combine(kept("t1", rig.t1), combiner=rig.combiner(git))

    assert rig.run.calls == []
    assert_cleaned(rig)


def test_cleanup_keeps_a_busy_run_dir_and_unlinks_a_planted_scratch_link(
    rig: Rig,
) -> None:
    """
    GIVEN another phase's dir in <run> and a run that replaces its scratch
        root with a link to a directory outside (possible with fs=off)
    WHEN the combine is cleaned up
    THEN the link is unlinked (its target untouched), the combine's own
        dirs are gone and <run> stays for its other owner
    """
    outside = rig.root / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (rig.run_dir / "baseline").mkdir(parents=True)

    def respond(call: Call) -> RunSample:
        scratch = call.sandbox.writable[1]
        if not scratch.is_symlink():
            shutil.rmtree(scratch)
            os.symlink(outside, scratch)
        return sample()

    rig.run.respond = respond

    rig.combine(kept("t1", rig.t1))

    assert (outside / "keep.txt").read_text() == "keep"
    assert sorted(os.listdir(rig.run_dir)) == ["baseline"]


def test_cleanup_unlinks_a_planted_link_in_place_of_the_scratch_parent(
    rig: Rig,
) -> None:
    outside = rig.root / "outside"
    (outside / "combine").mkdir(parents=True)
    (outside / "combine" / "keep.txt").write_text("keep")

    def respond(call: Call) -> RunSample:
        parent = call.sandbox.writable[1].parent
        if not parent.is_symlink():
            shutil.rmtree(parent)
            os.symlink(outside, parent)
        return sample()

    rig.run.respond = respond

    rig.combine(kept("t1", rig.t1))

    assert (outside / "combine" / "keep.txt").read_text() == "keep"
    assert_cleaned(rig)


def move_run_dir(rig: Rig) -> Path:
    moved = rig.root / "moved"
    shutil.move(rig.run_dir, moved)
    os.symlink(moved, rig.run_dir)
    return moved


def test_a_dir_that_cannot_be_removed_safely_is_an_engine_error(rig: Rig) -> None:
    """
    GIVEN a run that moves <run> outside WORKTREE_ROOT and leaves a link
    WHEN the combine is cleaned up
    THEN nothing outside is removed through the link and EngineError names
        every dir left behind
    """
    moved: list[Path] = []

    def respond(call: Call) -> RunSample:
        if not moved:
            moved.append(move_run_dir(rig))
        raise RunFailure("gone")

    rig.run.respond = respond

    with pytest.raises(EngineError, match="could not clean up") as raised:
        rig.combine(kept("t1", rig.t1))

    message = str(raised.value)
    for name in ("combine", "combine-base", "_scratch/combine", "_probe/combine"):
        assert str(rig.run_dir / name) in message
    assert (moved[0] / "_scratch" / "combine").is_dir()


def test_a_cleanup_problem_never_hides_the_error_already_raised(rig: Rig) -> None:
    def respond(call: Call) -> RunSample:
        if not rig.run_dir.is_symlink():
            move_run_dir(rig)
            run_git(rig.repo, "update-ref", "refs/heads/planted", rig.base)
        return sample()

    rig.run.respond = respond

    with pytest.raises(RepoTamperedError):
        rig.combine(kept("t1", rig.t1))


@pytest.mark.parametrize("run_id", ["", "../x", "a/b", "x..y", "-x", "x.lock"])
def test_an_unsafe_run_id_is_refused_before_anything_runs(
    rig: Rig, run_id: str
) -> None:
    with pytest.raises(ValueError, match="run_id"):
        rig.combiner().combine(
            run_id, rig.project, rig.base, [kept("t1", rig.t1)], [rig.workload()]
        )

    assert not os.listdir(rig.wt_root)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        (["t1", "t1"], "more than once"),
        (["t1\nEngine-Trial: x"], "trial_id"),
        (["../t1"], "trial_id"),
    ],
)
def test_bad_kept_changes_are_refused_before_anything_runs(
    rig: Rig, changes: list[str], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        rig.combine(*(kept(trial, rig.t1) for trial in changes))

    assert not os.listdir(rig.wt_root)


def test_a_bad_hypothesis_id_is_refused(rig: Rig) -> None:
    change = KeptChange("t1", "h\n1", "v1", rig.t1, 1.0, 0.5)

    with pytest.raises(ValueError, match="hypothesis_id"):
        rig.combine(change)


@pytest.mark.parametrize(
    ("base", "error", "match"),
    [
        ("HEAD", ValueError, "is not a commit id"),  # refused before any git call
        ("main", ValueError, "is not a commit id"),
        ("tag", ValueError, "is not a commit object"),  # rev-parse peels it
        ("f" * 40, GitError, "rev-parse"),  # well-formed, but no such object
    ],
)
def test_the_base_must_be_a_full_commit_id(
    rig: Rig, base: str, error: type[Exception], match: str
) -> None:
    if base == "tag":  # an annotated tag's own object id names no commit
        run_git(rig.repo, "tag", "-a", "-m", "v1", "v1", rig.base)
        base = run_git(rig.repo, "rev-parse", "refs/tags/v1")
        assert base != rig.base
    with pytest.raises(error, match=match):
        rig.combiner().combine(
            RUN_ID, rig.project, base, [kept("t1", rig.t1)], [rig.workload()]
        )

    assert rig.run.calls == []


def test_the_real_launcher_measures_the_base_and_the_tip(rig: Rig) -> None:
    """
    GIVEN the real launcher with isolation off and a workload printing app.py
    WHEN a change to app.py is combined
    THEN the A runs saw the base and the B runs the tip (their output
        fingerprints differ) and every run's numbers are real
    """
    combiner = GitCombiner(network="off", fs="off")
    load = rig.workload(command=(sys.executable, "bench.py"))

    result = combiner.combine(
        RUN_ID, rig.project, rig.base, [kept("t1", rig.t1)], [load]
    )

    a = {m.metric: m for m in result.baseline}
    b = {m.metric: m for m in result.combined}
    assert set(a) == set(b) == set(METRICS)
    assert a[METRIC_WALL_TIME_S].output_fingerprint is not None
    assert b[METRIC_WALL_TIME_S].output_fingerprint is not None
    assert (
        a[METRIC_WALL_TIME_S].output_fingerprint
        != b[METRIC_WALL_TIME_S].output_fingerprint
    )
    assert all(value > 0 for value in a[METRIC_PEAK_RSS_BYTES].samples)
    assert_cleaned(rig)


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------

BRANCH = "engine/run-run1"
REF = "refs/heads/" + BRANCH


def combined_tip(rig: Rig) -> str:
    return rig.combine(kept("t1", rig.t1), kept("t2", rig.t2)).tip_commit


def test_publish_creates_the_branch_and_returns_the_base_to_tip_diff(
    rig: Rig,
) -> None:
    """
    GIVEN a combined tip
    WHEN it is published
    THEN the engine branch points at the tip, the diff is base..tip, and
        nothing else in the user's repository changed and nothing is left
        under WORKTREE_ROOT
    """
    tip = combined_tip(rig)
    before = rig.user_state()

    diff = GitBranchPublisher().publish(rig.project, BRANCH, tip, rig.base)

    assert run_git(rig.repo, "rev-parse", REF) == tip
    assert "diff --git a/app.py b/app.py" in diff
    assert "+fast 1" in diff and "-line 1" in diff
    assert "+VALUE = 2" in diff
    after = rig.user_state()
    added = set(after[2].splitlines()) - set(before[2].splitlines())
    assert added == {f"{tip} commit\t{REF}"}
    assert set(before[2].splitlines()) <= set(after[2].splitlines())
    assert after[:2] + after[3:] == before[:2] + before[3:]
    assert os.listdir(rig.wt_root) == []
    assert run_git(rig.repo, "log", "-g", "--format=%gs", REF) == "aip-engine"


def test_publishing_again_at_the_same_tip_is_a_no_op(rig: Rig) -> None:
    tip = combined_tip(rig)
    publisher = GitBranchPublisher()
    first = publisher.publish(rig.project, BRANCH, tip, rig.base)

    second = publisher.publish(rig.project, BRANCH, tip, rig.base)

    assert second == first
    assert run_git(rig.repo, "rev-parse", REF) == tip


def test_an_existing_branch_at_another_commit_is_refused_and_kept(rig: Rig) -> None:
    tip = combined_tip(rig)
    run_git(rig.repo, "update-ref", REF, rig.t3)

    with pytest.raises(DeliveryError, match="already exists"):
        GitBranchPublisher().publish(rig.project, BRANCH, tip, rig.base)

    assert run_git(rig.repo, "rev-parse", REF) == rig.t3
    assert os.listdir(rig.wt_root) == []


class _Counting(GitWorkspace):
    """Counts the worktrees added (the publisher's diff checks one out)."""

    def __init__(self, repo: Path) -> None:
        super().__init__(repo)
        self.added: list[Path] = []

    def add_worktree(self, path: Path, commit: str) -> WorktreeHandle:
        self.added.append(path)
        return super().add_worktree(path, commit)


def test_a_refused_publish_checks_nothing_out(rig: Rig) -> None:
    tip = combined_tip(rig)
    run_git(rig.repo, "update-ref", REF, rig.t3)
    git = _Counting(rig.repo)

    with pytest.raises(DeliveryError, match="already exists"):
        GitBranchPublisher(git=git).publish(rig.project, BRANCH, tip, rig.base)

    assert git.added == []


def test_a_default_branch_that_is_a_symref_to_the_engine_branch_is_not_moved(
    rig: Rig,
) -> None:
    """
    GIVEN refs/heads/main is a dangling symbolic ref to the delivery branch
        and is not checked out (so no worktree reports it)
    WHEN the delivery branch is published
    THEN it is refused, the engine branch is not left behind, and main still
        resolves to nothing
    """
    tip = combined_tip(rig)
    run_git(rig.repo, "checkout", "-q", "-b", "dev")
    run_git(rig.repo, "symbolic-ref", "refs/heads/main", REF)
    before = rig.user_state()

    with pytest.raises(DeliveryError, match="default branch 'main'"):
        GitBranchPublisher().publish(rig.project, BRANCH, tip, rig.base)

    assert run_git(rig.repo, "symbolic-ref", "refs/heads/main") == REF
    assert os.path.lexists(rig.repo / ".git" / "refs" / "heads" / "main")
    assert not os.path.lexists(rig.repo / ".git" / "refs" / "heads" / BRANCH)
    assert rig.user_state() == before
    assert os.listdir(rig.wt_root) == []


def test_a_default_branch_that_does_not_exist_does_not_block_publishing(
    rig: Rig,
) -> None:
    tip = combined_tip(rig)
    project = rig.project.model_copy(update={"default_branch": "trunk"})

    GitBranchPublisher().publish(project, BRANCH, tip, rig.base)

    assert run_git(rig.repo, "rev-parse", REF) == tip


class _Stuck(GitWorkspace):
    """``update-ref -d`` fails, as if another writer moved the ref meanwhile."""

    def delete_ref(self, ref: str, old: str) -> None:
        raise GitError("cannot lock ref")


def test_a_failed_undo_is_still_a_delivery_error(rig: Rig) -> None:
    tip = combined_tip(rig)
    run_git(rig.repo, "checkout", "-q", "-b", "dev")
    run_git(rig.repo, "symbolic-ref", "refs/heads/main", REF)

    with pytest.raises(DeliveryError, match="could not be undone"):
        GitBranchPublisher(git=_Stuck(rig.repo)).publish(
            rig.project, BRANCH, tip, rig.base
        )


@pytest.mark.parametrize(
    ("branch", "default", "match"),
    [
        ("main", "main", "default branch"),
        ("engine/run-run1", "engine/run-run1", "default branch"),
        ("engine/RUN-run1", "engine/run-run1", "default branch"),
        ("feature/x", "main", "outside the engine prefix"),
        ("refs/heads/engine/x", "main", "outside the engine prefix"),
        ("engine/../main", "main", "refname"),
        ("engine/run.lock", "main", "refname"),
        ("engine/run@{1}", "main", "refname"),
        ("engine/-x", "main", "refname"),
        ("engine/a b", "main", "refname"),
    ],
)
def test_an_unsafe_branch_is_refused_before_any_git_call(
    rig: Rig, branch: str, default: str, match: str
) -> None:
    project = rig.project.model_copy(update={"default_branch": default})

    with pytest.raises(DeliveryError, match=match):
        GitBranchPublisher(git=_Exploding(rig.repo)).publish(
            project, branch, rig.t1, rig.base
        )


class _Exploding(GitWorkspace):
    """Every git subprocess goes through ``_exec``: none may run."""

    def _exec(self, *args: object, **kwargs: object) -> tuple[int, bytes]:
        raise AssertionError("git was called")


@pytest.mark.parametrize("checked_out", [BRANCH, "engine/Run-run1"])
def test_a_branch_checked_out_in_any_worktree_is_refused(
    rig: Rig, checked_out: str
) -> None:
    other = rig.root / "other"
    run_git(rig.repo, "worktree", "add", "-q", "-b", checked_out, str(other), rig.base)
    tip = combined_tip(rig)

    with pytest.raises(DeliveryError, match="checked out"):
        GitBranchPublisher().publish(rig.project, BRANCH, tip, rig.base)

    assert run_git(rig.repo, "rev-parse", "refs/heads/" + checked_out) == rig.base


def test_an_unborn_branch_checked_out_elsewhere_is_refused(rig: Rig) -> None:
    other = rig.root / "other"
    run_git(rig.repo, "worktree", "add", "-q", "--detach", str(other), rig.base)
    run_git(other, "symbolic-ref", "HEAD", REF)
    tip = combined_tip(rig)

    with pytest.raises(DeliveryError, match="checked out"):
        GitBranchPublisher().publish(rig.project, BRANCH, tip, rig.base)


class _Racy(GitWorkspace):
    """Reports the ref absent once, as if another process created it just now."""

    def __init__(self, repo: Path, planted: str) -> None:
        super().__init__(repo)
        self.planted, self.reads = planted, 0

    def ref_value(self, ref: str) -> str | None:
        self.reads += 1
        if self.reads == 1:
            subprocess.run(
                ["git", "-C", str(self.repo), "update-ref", ref, self.planted],
                env=_ENV,
                check=True,
            )
            return None
        return super().ref_value(ref)


def test_a_racing_writer_at_another_commit_is_a_delivery_error(rig: Rig) -> None:
    tip = combined_tip(rig)

    with pytest.raises(DeliveryError, match="already exists"):
        GitBranchPublisher(git=_Racy(rig.repo, rig.t3)).publish(
            rig.project, BRANCH, tip, rig.base
        )

    assert run_git(rig.repo, "rev-parse", REF) == rig.t3


def test_a_racing_writer_at_the_same_tip_is_fine(rig: Rig) -> None:
    tip = combined_tip(rig)

    diff = GitBranchPublisher(git=_Racy(rig.repo, tip)).publish(
        rig.project, BRANCH, tip, rig.base
    )

    assert "+fast 1" in diff


class _Refusing(GitWorkspace):
    """``update-ref`` fails while the ref stays absent (a case collision)."""

    def update_ref(self, ref: str, new: str, old: str | None) -> None:
        raise GitError("cannot lock ref")


def test_a_failed_create_with_the_ref_still_absent_is_a_delivery_error(
    rig: Rig,
) -> None:
    tip = combined_tip(rig)

    with pytest.raises(DeliveryError, match="could not be created: cannot lock"):
        GitBranchPublisher(git=_Refusing(rig.repo)).publish(
            rig.project, BRANCH, tip, rig.base
        )

    assert os.listdir(rig.wt_root) == []


@pytest.mark.parametrize("which", ["tip", "base"])
@pytest.mark.parametrize("value", ["HEAD", "f" * 40, "--all"])
def test_tip_and_base_must_be_full_commit_ids(rig: Rig, which: str, value: str) -> None:
    tip, base = (value, rig.base) if which == "tip" else (rig.t1, value)

    with pytest.raises(DeliveryError, match="not a commit"):
        GitBranchPublisher().publish(rig.project, BRANCH, tip, base)

    assert run_git(rig.repo, "for-each-ref", REF) == ""


def test_the_returned_diff_is_capped(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    tip = combined_tip(rig)
    monkeypatch.setattr(settings, "MAX_DIFF_BYTES", 40)

    diff = GitBranchPublisher().publish(rig.project, BRANCH, tip, rig.base)

    assert re.search(r"\[diff truncated: 40 of \d+ bytes shown\]", diff)


def test_a_diff_that_fails_leaves_no_branch_and_no_worktree(rig: Rig) -> None:
    blob = run_git(rig.repo, "hash-object", "-w", "--stdin", stdin=b"caf\xe9\n")
    index = rig.root / "latin-index"
    env = {"GIT_INDEX_FILE": str(index)}
    run_git(rig.repo, "read-tree", rig.base, env=env)
    run_git(rig.repo, "update-index", "--cacheinfo", f"100644,{blob},lib.py", env=env)
    tree = run_git(rig.repo, "write-tree", env=env)
    latin = run_git(rig.repo, "commit-tree", tree, "-p", rig.base, "-m", "latin")

    with pytest.raises(GitError, match="not UTF-8"):
        GitBranchPublisher().publish(rig.project, BRANCH, latin, rig.base)

    assert run_git(rig.repo, "for-each-ref", REF) == ""
    assert os.listdir(rig.wt_root) == []
