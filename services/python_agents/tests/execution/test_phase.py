"""The shared phase-directory lifecycle (decision 38): layout and cleanup.

Real directories under a ``WORKTREE_ROOT`` in ``tmp_path``; worktrees come
from a real ``GitWorkspace`` or, to make a step fail or to record the order,
from a small double.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError, RepoTamperedError
from autonomous_ai_agents.execution import git as git_module
from autonomous_ai_agents.execution import phase as phase_module
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.execution.phase import (
    RUN_LOCK,
    PhaseDirs,
    PhaseGit,
    cleanup_phases,
    owned_phases,
    phase_dirs,
    raise_left,
    require_dir_name,
    sweep_stale_runs,
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


# ---------------------------------------------------------------------------
# Crash recovery: the run lock and the stale-run sweep
# ---------------------------------------------------------------------------

_KILLED_CHILD = """
import os, signal, sys
from pathlib import Path
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.phase import owned_phases, phase_dirs

git = GitWorkspace(Path(sys.argv[1]))
dirs = phase_dirs(sys.argv[2], "trial-h1")
with owned_phases(git, "the trial", dirs):
    git.add_worktree(dirs.worktree, git.head_commit())
    (dirs.scratch / "home").mkdir(parents=True)
    dirs.probe.mkdir(parents=True)
    os.kill(os.getpid(), signal.SIGKILL)
"""


def _kill_mid_phase(git: GitWorkspace, root: Path, run: str) -> PhaseDirs:
    """A child process that owns a trial phase and is killed with -9 in it."""
    env = {**os.environ, "WORKTREE_ROOT": str(root)}
    child = subprocess.run(
        [sys.executable, "-c", _KILLED_CHILD, str(git.repo), run],
        env=env,
        check=False,
        timeout=120,
    )
    assert child.returncode == -signal.SIGKILL
    return phase_dirs(run, "trial-h1")


def _admin_dirs(git: GitWorkspace) -> list[str]:
    admin = git.common_dir() / "worktrees"
    return sorted(os.listdir(admin)) if admin.is_dir() else []


def test_an_owner_marks_its_run_while_it_works_and_leaves_nothing(root: Path) -> None:
    dirs = made(phase_dirs(RUN, "baseline"))

    with owned_phases(Recorder(), "the baseline", dirs):
        assert (dirs.run / RUN_LOCK).is_file()

    assert not dirs.run.exists()


def test_a_run_killed_with_minus_9_is_recovered_by_the_next_sweep(
    root: Path, tmp_path: Path
) -> None:
    """
    GIVEN a process killed with SIGKILL in the middle of a trial phase: its
        worktree, its registration, its scratch and probe dirs and the
        run's marker are left
    WHEN the next run sweeps WORKTREE_ROOT
    THEN the registration and every dir are gone, git lists only the main
        worktree, and one note says what was removed
    """
    git = _repo(tmp_path)
    dirs = _kill_mid_phase(git, root, "killed")
    assert dirs.worktree.is_dir() and (dirs.run / RUN_LOCK).is_file()
    assert _admin_dirs(git) == ["trial-h1"]

    [note] = sweep_stale_runs(git)

    assert "killed" in note and "trial-h1" in note
    assert not dirs.run.exists()
    assert _admin_dirs(git) == []
    assert _registered(git).count("worktree ") == 1
    assert sweep_stale_runs(git) == []


def test_a_live_owners_run_is_never_swept(root: Path, tmp_path: Path) -> None:
    """
    GIVEN an owner working in its phase (its lock held), and a dir with a
        marker that another process holds
    WHEN a sweep runs meanwhile
    THEN nothing of either is touched
    """
    git = _repo(tmp_path)
    dirs = phase_dirs(RUN, "baseline")
    other = made(phase_dirs("other", "profile"))
    held = os.open(other.run / RUN_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(held, fcntl.LOCK_SH)
    try:
        with owned_phases(git, "the baseline", dirs):
            git.add_worktree(dirs.worktree, git.head_commit())

            assert sweep_stale_runs(git) == []

            assert dirs.worktree.is_dir() and _admin_dirs(git) == ["baseline"]
        assert other.worktree.is_dir() and other.scratch.is_dir()
    finally:
        os.close(held)
    assert not dirs.run.exists()


def test_the_sweep_leaves_unmarked_dirs_links_and_odd_names_alone(
    root: Path, tmp_path: Path
) -> None:
    """
    GIVEN under WORKTREE_ROOT: a user's dir without the marker, a link to a
        marked run outside the root, a marked dir whose name no run can
        have, a plain file, and the preflight probe's dir
    WHEN a sweep runs
    THEN none of them is touched and no note is made
    """
    (root / "mine" / "work").mkdir(parents=True)
    (root / "preflight-x1" / "preflight").mkdir(parents=True)
    outside = made(phase_dirs("away", "baseline"))
    shutil.move(outside.run, tmp_path / "away")
    (tmp_path / "away" / RUN_LOCK).write_text("")
    os.symlink(tmp_path / "away", root / "linked")
    (root / "_odd").mkdir()
    (root / "_odd" / RUN_LOCK).write_text("")
    (root / "file").write_text("x")

    assert sweep_stale_runs(Recorder()) == []

    assert (root / "mine" / "work").is_dir()
    assert (root / "preflight-x1" / "preflight").is_dir()
    assert (tmp_path / "away" / "baseline").is_dir()
    assert (root / "_odd" / RUN_LOCK).is_file() and (root / "file").is_file()


def test_the_sweep_with_no_root_yet_has_nothing_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "WORKTREE_ROOT", tmp_path / "never-made")

    assert sweep_stale_runs(Recorder()) == []


def test_a_stale_marker_alone_is_removed_with_its_run(root: Path) -> None:
    """A run killed after its cleanup but before it dropped the marker."""
    (root / RUN).mkdir()
    (root / RUN / RUN_LOCK).write_text("")
    git = Recorder()

    [note] = sweep_stale_runs(git)

    assert "no phase dirs" in note
    assert git.events == [] and not (root / RUN).exists()


def test_what_the_sweep_cannot_remove_is_reported_and_retried_next_time(
    root: Path,
) -> None:
    """
    GIVEN a stale marked run with a phase whose worktree cannot be removed
        and an entry no phase can be named
    WHEN a sweep runs
    THEN the note names both, the marker stays (so the next sweep tries
        again), and once the failure is gone the next sweep removes the rest
    """
    dirs = made(phase_dirs(RUN, "trial-h1"))
    (dirs.run / RUN_LOCK).write_text("")
    (dirs.run / "_scratch" / "x..y").mkdir()
    git = Recorder(
        fail={"remove_worktree": PermissionError(1, "Operation not permitted")}
    )

    [note] = sweep_stale_runs(git)

    assert str(dirs.worktree) in note and "x..y" in note
    assert "remove what is left by hand" in note
    assert (dirs.run / RUN_LOCK).is_file() and dirs.worktree.is_dir()
    shutil.rmtree(dirs.run / "_scratch" / "x..y")

    [again] = sweep_stale_runs(Recorder())

    assert "trial-h1" in again and not dirs.run.exists()


def test_a_marker_replaced_after_it_was_opened_is_left(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sweep that locked a marker an owner has since replaced does nothing."""
    dirs = made(phase_dirs(RUN, "baseline"))
    (dirs.run / RUN_LOCK).write_text("")
    monkeypatch.setattr(phase_module, "_same_file", lambda fd, path: False)

    assert sweep_stale_runs(Recorder()) == []

    assert dirs.worktree.is_dir()


def test_same_file_tells_a_replaced_or_missing_marker(tmp_path: Path) -> None:
    path = tmp_path / RUN_LOCK
    path.write_text("")
    fd = os.open(path, os.O_RDONLY)
    try:
        assert phase_module._same_file(fd, path)
        os.unlink(path)
        assert not phase_module._same_file(fd, path)
        path.write_text("")
        assert not phase_module._same_file(fd, path)
    finally:
        os.close(fd)


def test_an_owner_that_cannot_mark_its_run_still_works_and_cleans_up(
    root: Path, tmp_path: Path
) -> None:
    """
    GIVEN <run> replaced by a link before the owner starts (fs=off)
    WHEN the owner works
    THEN no marker is made through the link, and the cleanup reports <run>
    """
    target = tmp_path / "elsewhere"
    target.mkdir()
    os.symlink(target, root / RUN)
    dirs = phase_dirs(RUN, "baseline")

    with pytest.raises(EngineError, match="could not clean up"):
        with owned_phases(Recorder(), "the baseline", dirs):
            pass

    assert os.listdir(target) == []


def test_a_second_owner_of_the_run_keeps_the_marker_for_the_last_one(
    root: Path,
) -> None:
    """
    GIVEN two owners of one run working at once (the combine's sides, or two
        resumes)
    WHEN the first one ends
    THEN the marker stays while the second works, and goes with it
    """
    first, second = made(phase_dirs(RUN, "combine")), made(phase_dirs(RUN, "profile"))

    with owned_phases(Recorder(), "the profiler", second):
        with owned_phases(Recorder(), "the combine", first):
            pass
        assert (second.run / RUN_LOCK).is_file()

    assert not second.run.exists()


def test_an_owner_whose_cleanup_left_something_drops_the_marker(root: Path) -> None:
    """What is left is the owner's error to report; the marker goes with it."""
    dirs = made(phase_dirs(RUN, "baseline"))
    git = Recorder(
        fail={"remove_worktree": PermissionError(1, "Operation not permitted")}
    )

    with pytest.raises(EngineError, match="could not clean up"):
        with owned_phases(git, "the baseline", dirs):
            pass

    assert os.listdir(dirs.run) == ["baseline"]
