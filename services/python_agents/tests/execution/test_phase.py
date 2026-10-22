"""The shared phase-directory lifecycle (decision 38): layout and cleanup.

Real directories under a ``WORKTREE_ROOT`` in ``tmp_path``; worktrees come
from a real ``GitWorkspace`` or, to make a step fail or to record the order,
from a small double.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError, RepoTamperedError
from autonomous_ai_agents.execution import git as git_module
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.execution.phase import (
    PhaseDirs,
    PhaseGit,
    cleanup_phases,
    owned_phases,
    phase_dirs,
    raise_left,
    require_dir_name,
)
from autonomous_ai_agents.execution.protocols import WorktreeHandle

RUN = "run1"
_ENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = Path(os.path.realpath(tmp_path)) / "wt-root"
    path.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", path)
    return path


@dataclass
class Recorder:
    """A ``PhaseGit`` that records each call and can fail one of them."""

    events: list[str] = field(default_factory=list)
    fail: dict[str, BaseException] = field(default_factory=dict)

    def remove_worktree(self, target: WorktreeHandle | Path) -> None:
        path = target.path if isinstance(target, WorktreeHandle) else target
        self.events.append(f"remove {path.name}")
        if "remove_worktree" in self.fail:
            raise self.fail["remove_worktree"]
        git_module.remove_contained(path)

    def prune(self) -> None:
        self.events.append("prune")
        if "prune" in self.fail:
            raise self.fail["prune"]


def made(dirs: PhaseDirs) -> PhaseDirs:
    for path in (dirs.worktree, dirs.scratch / "home", dirs.probe):
        path.mkdir(parents=True)
    return dirs


def test_the_recorder_is_a_phase_git() -> None:
    assert isinstance(Recorder(), PhaseGit)
    assert isinstance(GitWorkspace(Path("/")), PhaseGit)


def test_phase_dirs_follow_decision_38(root: Path) -> None:
    dirs = phase_dirs(RUN, "trial-h1")

    assert dirs == PhaseDirs(
        run=root / RUN,
        worktree=root / RUN / "trial-h1",
        scratch=root / RUN / "_scratch" / "trial-h1",
        probe=root / RUN / "_probe" / "trial-h1",
    )


@pytest.mark.parametrize("name", ["", "../x", "a/b", "x..y", "-x", "x.lock", "_x"])
def test_unsafe_names_are_refused(root: Path, name: str) -> None:
    with pytest.raises(ValueError, match="run id"):
        require_dir_name("run id", name)
    with pytest.raises(ValueError, match="run_id"):
        phase_dirs(name, "baseline")
    with pytest.raises(ValueError, match="phase"):
        phase_dirs(RUN, name)


def test_cleanup_runs_every_step_in_order_and_removes_an_empty_run(
    root: Path,
) -> None:
    git = Recorder()
    dirs = made(phase_dirs(RUN, "baseline"))

    assert cleanup_phases(git, dirs) == []

    assert git.events == ["remove baseline", "prune"]
    assert not dirs.run.exists()


def test_cleanup_removes_a_real_worktree_and_its_registration(
    root: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "user"
    subprocess.run(["git", "init", "-q", str(repo)], env=_ENV, check=True)
    (repo / "a.py").write_text("a\n")
    for argv in (["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-C", str(repo), *argv], env=_ENV, check=True)
    git = GitWorkspace(repo)
    dirs = phase_dirs(RUN, "baseline")
    handle = git.add_worktree(dirs.worktree, git.head_commit())
    (dirs.scratch / "home").mkdir(parents=True)
    dirs.probe.mkdir(parents=True)

    assert cleanup_phases(git, dirs) == []

    assert not dirs.run.exists() and not handle.gitdir.exists()
    listing = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert listing.count("worktree ") == 1


def test_several_phases_of_one_run_go_together(root: Path) -> None:
    git = Recorder()
    tip, base = made(phase_dirs(RUN, "combine")), made(phase_dirs(RUN, "combine-base"))

    assert cleanup_phases(git, tip, base) == []

    assert git.events == ["remove combine", "remove combine-base", "prune"]
    assert not tip.run.exists()


def test_phases_of_different_runs_are_refused(root: Path) -> None:
    with pytest.raises(ValueError, match="one run"):
        cleanup_phases(Recorder(), phase_dirs("a", "x"), phase_dirs("b", "x"))
    with pytest.raises(ValueError, match="at least one"):
        cleanup_phases(Recorder())


def test_a_busy_run_dir_stays_and_a_planted_scratch_link_is_unlinked(
    root: Path, tmp_path: Path
) -> None:
    """
    GIVEN another owner's dir in <run> and a link planted in place of the
        scratch root (possible with fs=off)
    WHEN the phase is cleaned up
    THEN the link is unlinked (its target untouched), the phase's own dirs
        are gone and <run> stays for its other owner
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    dirs = made(phase_dirs(RUN, "profile"))
    (dirs.run / "baseline").mkdir()
    shutil.rmtree(dirs.scratch)
    os.symlink(outside, dirs.scratch)

    assert cleanup_phases(Recorder(), dirs) == []

    assert (outside / "keep.txt").read_text() == "keep"
    assert sorted(os.listdir(dirs.run)) == ["baseline"]


def test_a_link_planted_in_place_of_the_scratch_parent_is_unlinked(
    root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    (outside / "profile").mkdir(parents=True)
    (outside / "profile" / "keep.txt").write_text("keep")
    dirs = made(phase_dirs(RUN, "profile"))
    shutil.rmtree(dirs.run / "_scratch")
    os.symlink(outside, dirs.run / "_scratch")

    assert cleanup_phases(Recorder(), dirs) == []

    assert (outside / "profile" / "keep.txt").read_text() == "keep"
    assert not dirs.run.exists()


def plant_run_link(dirs: PhaseDirs, target: Path) -> None:
    """Move <run> to ``target`` and leave a link to it in its place."""
    shutil.move(dirs.run, target)
    os.symlink(target, dirs.run)


@pytest.mark.parametrize("where", ["outside", "inside"])
def test_a_planted_run_link_is_never_followed(
    root: Path, tmp_path: Path, where: str
) -> None:
    """
    GIVEN <run> replaced by a link, out of WORKTREE_ROOT or to another dir
        inside it
    WHEN the phase is cleaned up
    THEN every other step is still attempted, nothing is removed through the
        link (not the worktree, not even an empty dir: git is never asked to
        remove a worktree through it), and what is left names the worktree,
        scratch and probe
    """
    target = tmp_path / "moved" if where == "outside" else root / "other-run"
    dirs = made(phase_dirs(RUN, "profile"))
    plant_run_link(dirs, target)
    git = Recorder()

    left = cleanup_phases(git, dirs)

    assert git.events == ["prune"]
    assert (target / "profile").is_dir()
    assert (target / "_scratch" / "profile" / "home").is_dir()
    assert (target / "_probe" / "profile").is_dir()
    text = "; ".join(left)
    assert str(dirs.worktree) in text
    assert str(dirs.scratch) in text and str(dirs.probe) in text
    assert "a link was planted in place of the run directory" in text
    assert os.path.islink(dirs.run)


def test_a_worktree_through_a_run_link_out_of_the_root_is_left(
    root: Path, tmp_path: Path
) -> None:
    dirs = made(phase_dirs(RUN, "profile"))
    plant_run_link(dirs, tmp_path / "moved")
    git = Recorder()

    left = cleanup_phases(git, dirs)

    assert str(dirs.worktree) in "; ".join(left)
    assert (tmp_path / "moved" / "profile").is_dir()


def _repo(tmp_path: Path) -> GitWorkspace:
    repo = tmp_path / "user"
    subprocess.run(["git", "init", "-q", str(repo)], env=_ENV, check=True)
    (repo / "a.py").write_text("a\n")
    for argv in (["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-C", str(repo), *argv], env=_ENV, check=True)
    return GitWorkspace(repo)


def _registered(git: GitWorkspace) -> str:
    return subprocess.run(
        ["git", "-C", str(git.repo), "worktree", "list", "--porcelain"],
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_a_run_link_into_another_run_never_reaches_its_live_worktree(
    root: Path, tmp_path: Path
) -> None:
    """
    GIVEN run B's live, registered worktree, and run A's <run> swapped (fs=off)
        for a link to run B's <run>, which is inside WORKTREE_ROOT
    WHEN run A's phase is cleaned up with the real GitWorkspace
    THEN run B's worktree, its files and its registration survive, and run
        A's worktree is named as left
    """
    git = _repo(tmp_path)
    victim = phase_dirs("run-b", "baseline")
    handle = git.add_worktree(victim.worktree, git.head_commit())
    (victim.worktree / "precious.txt").write_text("another owner's file")
    attacker = made_except_worktree(phase_dirs("run-a", "baseline"))
    git.add_worktree(attacker.worktree, git.head_commit())
    shutil.move(attacker.run, tmp_path / "moved")
    os.symlink(victim.run, attacker.run)

    left = cleanup_phases(git, attacker)

    assert (victim.worktree / "precious.txt").read_text() == "another owner's file"
    assert handle.gitdir.exists() and str(victim.worktree) in _registered(git)
    text = "; ".join(left)
    assert str(attacker.worktree) in text
    assert "a link was planted in place of the run directory" in text
    assert os.path.islink(attacker.run)


def test_a_link_planted_at_the_worktree_path_is_unlinked_never_followed(
    root: Path, tmp_path: Path
) -> None:
    """
    GIVEN run B's live, registered worktree, and a link to it planted in
        place of run A's worktree path
    WHEN run A's phase is cleaned up with the real GitWorkspace
    THEN the link is unlinked, git never removes the worktree behind it (run
        B's files and registration survive), and the worktree is named as left
    """
    git = _repo(tmp_path)
    victim = phase_dirs("run-b", "baseline")
    handle = git.add_worktree(victim.worktree, git.head_commit())
    (victim.worktree / "precious.txt").write_text("another owner's file")
    attacker = made_except_worktree(phase_dirs("run-a", "baseline"))
    os.symlink(victim.worktree, attacker.worktree)

    left = cleanup_phases(git, attacker)

    assert (victim.worktree / "precious.txt").read_text() == "another owner's file"
    assert handle.gitdir.exists() and str(victim.worktree) in _registered(git)
    assert not os.path.lexists(attacker.worktree)
    [entry] = left
    assert str(attacker.worktree) in entry
    assert "a link was planted in place of the worktree" in entry
    assert not attacker.run.exists()


def test_a_worktree_link_is_unlinked_without_asking_git(root: Path) -> None:
    git = Recorder()
    dirs = made_except_worktree(phase_dirs(RUN, "profile"))
    os.symlink(root, dirs.worktree)

    [entry] = cleanup_phases(git, dirs)

    assert git.events == ["prune"]
    assert "unlinked, never followed" in entry
    assert root.is_dir() and not dirs.run.exists()


def made_except_worktree(dirs: PhaseDirs) -> PhaseDirs:
    for path in (dirs.scratch / "home", dirs.probe):
        path.mkdir(parents=True)
    return dirs


FAILURES = [
    pytest.param("remove_worktree", GitError("git worktree remove timed out"), id="remove-git"),
    pytest.param("remove_worktree", PermissionError(1, "Operation not permitted"), id="remove-os"),
    pytest.param("remove_worktree", ValueError("not inside WORKTREE_ROOT"), id="remove-value"),
    pytest.param("prune", GitError("git worktree list timed out"), id="prune-git"),
]  # fmt: skip


@pytest.mark.parametrize(("method", "error"), FAILURES)
def test_a_failing_step_is_recorded_and_every_other_step_runs(
    root: Path, method: str, error: Exception
) -> None:
    """
    GIVEN worktree removal or prune failing with a git, OS or containment
        error
    WHEN the phase is cleaned up
    THEN the failure is recorded, not raised, scratch and probe still go
        and <run> is removed when nothing else is left in it
    """
    git = Recorder(fail={method: error})
    dirs = made(phase_dirs(RUN, "baseline"))

    left = cleanup_phases(git, dirs)

    [entry] = left
    expected = "WORKTREE_ROOT" if isinstance(error, ValueError) else str(error)
    assert expected in entry
    assert git.events == ["remove baseline", "prune"]
    assert not (dirs.run / "_scratch").exists() and not (dirs.run / "_probe").exists()
    if method == "remove_worktree":
        assert os.listdir(dirs.run) == ["baseline"]
    else:
        assert not dirs.run.exists()


def test_an_unexpected_error_still_lets_every_step_run_then_propagates(
    root: Path,
) -> None:
    git = Recorder(fail={"remove_worktree": RuntimeError("bug")})
    dirs = made(phase_dirs(RUN, "baseline"))

    with pytest.raises(RuntimeError, match="bug"):
        cleanup_phases(git, dirs)

    assert git.events == ["remove baseline", "prune"]
    assert os.listdir(dirs.run) == ["baseline"]


def test_a_scratch_dir_that_cannot_be_removed_still_lets_probe_go(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = made(phase_dirs(RUN, "baseline"))
    real = git_module._rmtree

    def rmtree(path: Path) -> None:
        if Path(path) == dirs.scratch:
            raise PermissionError(1, "Operation not permitted", str(path))
        real(path)

    monkeypatch.setattr(git_module, "_rmtree", rmtree)

    [left] = cleanup_phases(Recorder(), dirs)

    assert str(dirs.scratch) in left and "Operation not permitted" in left
    assert dirs.scratch.is_dir() and not dirs.probe.exists()


def test_raise_left_names_the_owner_and_everything_left() -> None:
    raise_left("the trial", [])
    with pytest.raises(EngineError, match="the trial could not clean up") as raised:
        raise_left("the trial", ["'a': x", "'b': y"])
    assert "'a': x; 'b': y" in str(raised.value)
    assert "remove what is left by hand" in str(raised.value)


def test_owned_phases_cleans_up_and_raises_what_is_left(root: Path) -> None:
    dirs = made(phase_dirs(RUN, "baseline"))
    git = Recorder(fail={"prune": GitError("timed out")})

    with pytest.raises(EngineError, match="the baseline could not clean up"):
        with owned_phases(git, "the baseline", dirs):
            assert dirs.worktree.is_dir()

    assert not dirs.run.exists()


@pytest.mark.parametrize("left", [True, False], ids=["with-left", "clean"])
def test_owned_phases_never_hides_the_error_already_raised(
    root: Path, left: bool
) -> None:
    """
    GIVEN a body that raises (tampering) and a cleanup that leaves something
        or nothing
    WHEN the phase ends
    THEN the body's error propagates unchanged and the cleanup still ran
    """
    dirs = made(phase_dirs(RUN, "baseline"))
    git = Recorder(fail={"remove_worktree": GitError("timed out")} if left else {})

    with pytest.raises(RepoTamperedError, match="planted"):
        with owned_phases(git, "the baseline", dirs):
            raise RepoTamperedError("planted")

    assert git.events == ["remove baseline", "prune"]
    assert not (dirs.run / "_scratch").exists()


def test_owned_phases_returns_normally_when_all_is_clean(root: Path) -> None:
    dirs = made(phase_dirs(RUN, "baseline"))

    with owned_phases(Recorder(), "the baseline", dirs):
        pass

    assert not dirs.run.exists()
