"""Preflight against real git repositories built in ``tmp_path``.

Every refusal and the happy path run on a real repository with the test's own
git environment (global and system config off, fixed identity and dates).
The isolation probe is a fake ``run_once`` where a real probe cannot fail on
demand, plus one real probe through the launcher on a host that can sandbox
(``REQUIRE_NETWORK_SANDBOX=1`` or ``REQUIRE_FS_SANDBOX=1`` turns the skip into
a failure, as in ``test_procrun.py``). A fake git executable stands in where
real git cannot be made old or suspicious.
"""

from __future__ import annotations

import ast
import dataclasses
import fcntl
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import EngineError, PreflightError
from autonomous_ai_agents.common.models import (
    Guardrail,
    GuardrailKind,
    Project,
    Workload,
)
from autonomous_ai_agents.common.paths import matches_pattern
from autonomous_ai_agents.execution import launcher, preflight
from autonomous_ai_agents.execution.git import (
    ATTR_SOURCE_SINCE,
    GitError,
    GitWorkspace,
    repo_fingerprint,
)
from autonomous_ai_agents.execution.phase import RUN_LOCK
from autonomous_ai_agents.execution.preflight import (
    MIN_GIT_VERSION,
    GitPreflight,
    GitPreflightReport,
)
from autonomous_ai_agents.execution.procrun import OutputCaps, RunFailure, RunSample
from autonomous_ai_agents.execution.protocols import Preflight, PreflightReport
from autonomous_ai_agents.execution.sandbox import UNSHARE_ARGV, SandboxPolicy

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
ENGINE_VERSION = f"Python {sys.version_info.major}.{sys.version_info.minor}"


def run_git(cwd: Path, *args: str, stdin: bytes | None = None) -> bytes:
    """Run the test's own git (never the engine's) and require exit 0."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=_ENV,
        input=stdin,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc.stdout


def out(cwd: Path, *args: str) -> str:
    return run_git(cwd, *args).decode().strip()


def write(path: Path, text: str | bytes, *, mode: int = 0o644) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)
    path.chmod(mode)
    return path


def commit_all(repo: Path, message: str = "change") -> str:
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)
    return out(repo, "rev-parse", "HEAD")


def executable(path: Path, body: str = "exit 0\n") -> Path:
    return write(path, "#!/bin/sh\n" + body, mode=0o755)


def fake_git(tmp_path: Path, body: str) -> str:
    """An executable stand-in for git that runs ``body`` under /bin/sh."""
    return str(executable(tmp_path / "fake-git", body))


def logging_git(tmp_path: Path, log: Path) -> str:
    """The real git, logging the argv of every ``git show`` call to ``log``."""
    body = f'case " $* " in *" show "*) echo "$*" >> "{log}";; esac\nexec git "$@"\n'
    return fake_git(tmp_path, body)


def shown(log: Path) -> list[list[str]]:
    """The blob ids each logged ``git show`` call asked for."""
    lines = log.read_text().splitlines() if log.exists() else []
    calls = [line.split(" show ", 1)[1].split() for line in lines]
    return [[w for w in call if re.fullmatch("[0-9a-f]{40}", w)] for call in calls]


def py_blobs(repo: Path) -> set[str]:
    """The distinct ids of the regular ``.py`` blobs at HEAD."""
    entries = [line.split() for line in out(repo, "ls-tree", "-r", "HEAD").splitlines()]
    return {e[2] for e in entries if e[0] != "120000" and e[3].endswith(".py")}


def hash_blob(repo: Path, data: bytes) -> str:
    return run_git(repo, "hash-object", "-w", "--stdin", stdin=data).decode().strip()


def sample(**changes: Any) -> RunSample:
    fields: dict[str, Any] = {
        "wall_ns": 1_000_000,
        "utime": 0.0,
        "stime": 0.0,
        "maxrss_bytes": 4096,
        "exit": 0,
        "fs_isolated": True,
        "net_isolated": True,
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stdout_head": b"",
        "stdout_bytes": 0,
        "stderr_tail": b"",
    }
    fields.update(changes)
    return RunSample(**fields)


@dataclass(frozen=True)
class ProbeCall:
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    policy: SandboxPolicy
    timeout_s: float
    fresh_dirs: tuple[Path, ...]
    probe_dir_empty: bool


class FakeRun:
    """``run_once`` stand-in: records the probe, then returns or raises."""

    def __init__(
        self, result: RunSample | None = None, *, failure: RunFailure | None = None
    ) -> None:
        self.result = result or sample()
        self.failure = failure
        self.calls: list[ProbeCall] = []

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
        assert caps == OutputCaps.from_settings()
        empty = sandbox.probe_dir.is_dir() and not any(sandbox.probe_dir.iterdir())
        self.calls.append(
            ProbeCall(
                tuple(argv),
                cwd,
                dict(env),
                sandbox,
                timeout_s,
                tuple(fresh_dirs),
                empty,
            )
        )
        if self.failure is not None:
            raise self.failure
        return self.result


# ---------------------------------------------------------------------------
# Fixtures: a real repository, a PATH of fake tools, a preflight factory
# ---------------------------------------------------------------------------


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    worktree_root = tmp_path.resolve() / "wt-root"
    monkeypatch.setattr(settings, "WORKTREE_ROOT", worktree_root)
    return worktree_root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "user"
    run_git(tmp_path, "init", "-q", "-b", "main", str(path))
    write(path / "core.py", "def f(x):\n    return x\n")
    write(path / "pkg" / "__init__.py", "")
    write(path / "pkg" / "bench.py", "print('bench')\n")
    write(path / "src" / "tool" / "__main__.py", "print('tool')\n")
    executable(path / "scripts" / "bench", "echo bench\n")
    write(path / "scripts" / "bench.py", "print(1)\n")
    executable(path / "run.sh", "echo run\n")
    write(path / "plain.sh", "#!/bin/sh\n")
    write(path / "conf.toml", "x = 1\n")
    write(path / "sub" / "bench.py", "print(2)\n")
    write(path / "tests" / "test_core.py", "import unittest\n")
    write(path / "checks" / "testcore.py", "import unittest\n")
    os.symlink("scripts/bench", path / "link-run")
    commit_all(path, "base")
    return path.resolve()


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    path = tmp_path / "bin"
    for name in ("tool", "python3", "sh", "bash"):
        executable(path / name)
    write(path / "notexec", "#!/bin/sh\n")
    return path.resolve()


@pytest.fixture
def project(repo: Path) -> Project:
    return Project(name="user", root_path=str(repo))


Factory = Callable[..., GitPreflight]


@pytest.fixture
def make(root: Path, bin_dir: Path) -> Factory:
    """A preflight with a passing fake probe and ``bin_dir`` as the PATH."""

    def build(**overrides: Any) -> GitPreflight:
        options: dict[str, Any] = {
            "network": "required",
            "fs": "required",
            "platform": "linux",
            "search_path": str(bin_dir),
            "run": FakeRun(),
        }
        options.update(overrides)
        return GitPreflight(**options)

    return build


def workload(project: Project, *command: str, working_dir: str = ".") -> Workload:
    return Workload(
        project_id=project.id, name="w", command=command, working_dir=working_dir
    )


def tests_pass(project: Project) -> Guardrail:
    return Guardrail(
        project_id=project.id, kind=GuardrailKind.tests_pass, description="tests pass"
    )


def check(
    pf: GitPreflight,
    project: Project,
    workloads: Sequence[Workload] = (),
    guardrails: Sequence[Guardrail] = (),
) -> GitPreflightReport:
    return pf.check(project, workloads, guardrails)


def refused(
    pf: GitPreflight,
    project: Project,
    workloads: Sequence[Workload] = (),
    guardrails: Sequence[Guardrail] = (),
) -> str:
    with pytest.raises(PreflightError) as caught:
        pf.check(project, workloads, guardrails)
    return str(caught.value)


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_preflight_satisfies_the_protocol(make: Factory) -> None:
    assert isinstance(make(), Preflight)
    assert issubclass(GitPreflightReport, PreflightReport)
    assert MIN_GIT_VERSION == (2, 38, 0)


def test_git_preflight_report_narrows_the_protocol_report() -> None:
    """
    GIVEN the protocol's PreflightReport (notes, python_version optional)
    WHEN GitPreflightReport's fields are listed
    THEN they are the protocol's, in order, with notes and python_version
        required: GitPreflight always fills both
    """
    names = [f.name for f in dataclasses.fields(GitPreflightReport)]
    required = [
        f.name
        for f in dataclasses.fields(GitPreflightReport)
        if f.default is dataclasses.MISSING
    ]

    assert names == [f.name for f in dataclasses.fields(PreflightReport)]
    assert names[-2:] == ["notes", "python_version"]
    assert required == names


def test_happy_path_pins_head_and_reports_everything(
    make: Factory, project: Project, repo: Path, bin_dir: Path
) -> None:
    """
    GIVEN a clean repository, one workload and a test command on PATH
    WHEN preflight checks it
    THEN it pins HEAD, reports git's and the engine's versions, both modes,
        no dirty entries, the workloads with argv[0] resolved and their ids
        kept, the resolved test command and the test dir it names protected
    """
    project = project.model_copy(
        update={"test_command": ("tool", "-m", "unittest", "discover", "-s", "tests")}
    )
    work = workload(project, "tool", "core")

    report = check(make(), project, [work], [tests_pass(project)])

    assert report.head_commit == out(repo, "rev-parse", "HEAD")
    assert report.git_version == GitWorkspace(repo).version()
    assert report.python_version == tuple(sys.version_info[:3])
    assert (report.network, report.fs) == ("required", "required")
    assert report.dirty_entries == ()
    assert [w.id for w in report.workloads] == [work.id]
    assert report.workloads[0].command == (str(bin_dir / "tool"), "core")
    assert report.test_command == (
        str(bin_dir / "tool"),
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
    )
    assert report.extra_protected == ("tests/**",)
    assert report.notes == ()


def test_no_test_command_and_no_tests_pass_guardrail_is_fine(
    make: Factory, project: Project
) -> None:
    report = check(make(), project)

    assert report.test_command is None
    assert report.workloads == ()


def test_preflight_never_writes_the_user_checkout_or_refs(
    make: Factory, project: Project, repo: Path
) -> None:
    """
    GIVEN a checkout with a modified, a staged and an untracked file
    WHEN preflight checks it
    THEN the dirty entries are reported, and HEAD, the index, the status,
        the files, the config and every ref are exactly as before
    """
    write(repo / "core.py", "def f(x):\n    return x + 1\n")
    write(repo / "staged.txt", "s\n")
    run_git(repo, "add", "staged.txt")
    write(repo / "untracked.txt", "u\n")
    index = hashlib.sha256((repo / ".git" / "index").read_bytes()).hexdigest()
    status = run_git(repo, "status", "--porcelain=v1", "-z")
    before = repo_fingerprint(GitWorkspace(repo))

    report = check(make(), project)

    assert report.dirty_entries == (" M core.py", "A  staged.txt", "?? untracked.txt")
    assert hashlib.sha256((repo / ".git" / "index").read_bytes()).hexdigest() == index
    assert run_git(repo, "status", "--porcelain=v1", "-z") == status
    assert repo_fingerprint(GitWorkspace(repo)) == before
    assert (repo / "core.py").read_text() == "def f(x):\n    return x + 1\n"


def test_preflight_ends_with_a_scoped_worktree_prune(
    make: Factory, project: Project, repo: Path, root: Path
) -> None:
    """
    GIVEN an engine worktree under WORKTREE_ROOT whose directory was deleted
        (a run killed with -9)
    WHEN preflight checks the repository
    THEN its stale registration is pruned
    """
    stale = root / "run1" / "baseline"
    stale.parent.mkdir(parents=True)
    run_git(repo, "worktree", "add", "--detach", str(stale), "HEAD")
    shutil.rmtree(stale)
    assert str(stale) in out(repo, "worktree", "list", "--porcelain")

    check(make(), project)

    assert str(stale) not in out(repo, "worktree", "list", "--porcelain")


def test_connect_recovers_what_a_killed_run_left_in_worktree_root(
    make: Factory, project: Project, repo: Path, root: Path
) -> None:
    """
    GIVEN a run killed with -9 in a trial: its marked run dir under
        WORKTREE_ROOT still holds the registered worktree and its scratch
        and probe dirs (the directory exists, so git does not call it stale)
    WHEN the next run's preflight checks the repository
    THEN the worktree, its registration and the run dir are gone, and a
        note says so
    """
    stale = root / "killed-run" / "trial-h1"
    stale.parent.mkdir(parents=True)
    run_git(repo, "worktree", "add", "--detach", str(stale), "HEAD")
    for sub in ("_scratch", "_probe"):
        (root / "killed-run" / sub / "trial-h1").mkdir(parents=True)
    (root / "killed-run" / RUN_LOCK).write_text("")

    report = check(make(), project)

    assert out(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert not (root / "killed-run").exists()
    assert not (repo / ".git" / "worktrees").exists() or not os.listdir(
        repo / ".git" / "worktrees"
    )
    [note] = report.notes
    assert "killed-run" in note and "trial-h1" in note


@pytest.mark.parametrize(
    ("output_file", "committed"),
    [("conf.toml", "conf.toml"), ("link-run", "scripts/bench")],
    ids=["tracked", "through-a-tracked-link"],
)
def test_a_committed_output_file_is_refused(
    make: Factory, project: Project, output_file: str, committed: str
) -> None:
    """
    GIVEN a workload whose output_file is a committed file, directly or
        through a committed link
    WHEN preflight checks it
    THEN it refuses, naming the file and the fix: the reset before every run
        restores the committed copy, so a run that never writes the file
        would still be fingerprinted as if it had
    """
    work = workload(project, "tool", "core").model_copy(
        update={"output_file": output_file}
    )

    message = refused(make(), project, [work])

    assert f"output_file {output_file}" in message and committed in message
    assert "git rm --cached" in message


def test_an_untracked_output_file_is_protected_so_no_trial_commits_one(
    make: Factory, project: Project
) -> None:
    """
    GIVEN a workload whose output_file is not in the repository
    WHEN preflight checks it
    THEN it is accepted and the path is protected: a trial that commits a
        copy of it (the same memo, made by the trial) is rejected unrun
    """
    work = workload(project, "tool", "core").model_copy(
        update={"output_file": "out/result[1].txt"}
    )

    report = check(make(), project, [work])

    assert "out/result[[]1].txt" in report.extra_protected


# ---------------------------------------------------------------------------
# Refusals: test command, git version, ownership, repository shape
# ---------------------------------------------------------------------------


def test_tests_pass_without_a_test_command_is_refused(
    make: Factory, project: Project
) -> None:
    message = refused(make(), project, guardrails=[tests_pass(project)])

    assert "tests_pass" in message
    assert "test_command" in message


def test_git_older_than_2_38_is_refused(
    make: Factory, project: Project, tmp_path: Path
) -> None:
    git = fake_git(tmp_path, 'echo "git version 2.37.1"\n')

    message = refused(make(executable=git), project)

    assert "2.37.1" in message
    assert "2.38" in message


def test_git_2_38_is_accepted(make: Factory, project: Project, tmp_path: Path) -> None:
    body = 'if [ "$1" = version ]; then echo "git version 2.38.0"; exit 0; fi\n'
    git = fake_git(tmp_path, body + 'exec git "$@"\n')

    report = check(make(executable=git), project)

    assert report.git_version == (2, 38, 0)


def test_dubious_ownership_is_refused_with_the_fix(
    make: Factory, project: Project, tmp_path: Path
) -> None:
    """
    GIVEN a git that reports dubious ownership for every repository command
    WHEN preflight checks the repository
    THEN it names the problem and the fix, and never suggests safe.directory
    """
    git = fake_git(
        tmp_path,
        'if [ "$1" = version ]; then echo "git version 2.43.0"; exit 0; fi\n'
        "echo \"fatal: detected dubious ownership in repository at '/x'\" >&2\n"
        "exit 128\n",
    )

    message = refused(make(executable=git), project)

    assert "dubious ownership" in message
    assert "owner" in message
    assert "safe.directory=*" not in message.replace("'", "")


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() != 0, reason="needs root to chown"
)
def test_real_dubious_ownership_is_refused(
    make: Factory, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN (as root) a copy of the repository owned by nobody
    WHEN preflight checks it with the real git
    THEN git's dubious-ownership refusal becomes a PreflightError
    """
    foreign = tmp_path / "foreign"
    shutil.copytree(repo, foreign, symlinks=True)
    for top, dirs, files in os.walk(foreign):
        for name in [*dirs, *files]:
            os.chown(os.path.join(top, name), 65534, 65534, follow_symlinks=False)
    os.chown(foreign, 65534, 65534)

    message = refused(make(), Project(name="f", root_path=str(foreign)))

    assert "dubious ownership" in message


def test_a_path_that_is_not_a_repository_is_refused(
    make: Factory, tmp_path: Path
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    message = refused(make(), Project(name="p", root_path=str(plain)))

    assert str(plain.resolve()) in message


def test_a_subdirectory_of_a_repository_is_refused(make: Factory, repo: Path) -> None:
    message = refused(make(), Project(name="p", root_path=str(repo / "pkg")))

    assert "top" in message
    assert str(repo) in message


def test_a_repository_without_a_commit_is_refused(
    make: Factory, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    run_git(tmp_path, "init", "-q", "-b", "main", str(empty))

    message = refused(make(), Project(name="e", root_path=str(empty)))

    assert "HEAD" in message


def test_worktree_root_inside_the_project_is_refused(
    make: Factory, project: Project, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "WORKTREE_ROOT", repo / ".cache" / "wt")

    message = refused(make(), project)

    assert "WORKTREE_ROOT" in message


@pytest.mark.parametrize(
    "where",
    ["main-checkout", "common-dir", "admin-dir", "contains-both", "other-worktree"],
)
def test_worktree_root_overlapping_the_repository_beyond_root_path_is_refused(
    make: Factory,
    project: Project,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    where: str,
) -> None:
    """
    GIVEN root_path is a linked worktree, and WORKTREE_ROOT inside the main
        checkout, inside the git common dir, at its admin dir, containing
        both checkouts, or inside another (unmarked) worktree of the repository
    WHEN preflight checks the linked worktree
    THEN it refuses, naming WORKTREE_ROOT and what it overlaps
    """
    linked = (tmp_path / "linked").resolve()
    run_git(repo, "worktree", "add", "-q", "--detach", str(linked), "HEAD")
    other = (tmp_path / "other").resolve()
    run_git(repo, "worktree", "add", "-q", "--detach", str(other), "HEAD")
    chosen = {
        "main-checkout": repo / ".aip-worktrees",
        "common-dir": repo / ".git" / "aip",
        "admin-dir": repo / ".git" / "worktrees",
        "contains-both": tmp_path.resolve(),
        "other-worktree": other / "wt",
    }[where]
    monkeypatch.setattr(settings, "WORKTREE_ROOT", chosen)
    project = project.model_copy(update={"root_path": str(linked)})

    message = refused(make(), project)

    assert "WORKTREE_ROOT" in message and "overlaps" in message


def test_engine_worktrees_under_worktree_root_are_no_overlap(
    make: Factory, project: Project, repo: Path, root: Path
) -> None:
    """
    GIVEN a live engine run's marked worktree under WORKTREE_ROOT (another
        process holds its lock)
    WHEN preflight checks the repository
    THEN it accepts the repository and leaves that worktree alone
    """
    live = root / "live-run" / "baseline"
    live.parent.mkdir(parents=True)
    run_git(repo, "worktree", "add", "--detach", str(live), "HEAD")
    held = os.open(live.parent / RUN_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(held, fcntl.LOCK_SH)
    try:
        report = check(make(), project)
    finally:
        os.close(held)

    assert report.notes == ()
    assert str(live) in out(repo, "worktree", "list", "--porcelain")


def test_an_unmarked_engine_leftover_is_refused_with_its_recovery(
    make: Factory, project: Project, repo: Path, root: Path
) -> None:
    """
    GIVEN <WORKTREE_ROOT>/<run>/<phase> is a registered worktree of the
        repository without the run marker: what an owner whose cleanup
        failed, or a run killed before run markers existed, leaves
    WHEN the next run connects
    THEN it refuses without claiming whose worktree it is, with a recovery
        that cannot destroy work (plain 'git worktree remove', never
        --force); once the user follows it, connect accepts the repository
    """
    stale = root / "old-run" / "baseline"
    stale.parent.mkdir(parents=True)
    run_git(repo, "worktree", "add", "-q", "--detach", str(stale), "HEAD")
    (root / "old-run" / "_scratch" / "baseline").mkdir(parents=True)

    message = refused(make(), project)

    assert message == unmarked_refusal(root, stale, repo)
    assert "--force" not in message
    run_git(repo, "worktree", "remove", str(stale))
    shutil.rmtree(stale.parent)
    assert check(make(), project).notes == ()


def unmarked_refusal(root: Path, path: Path, repo: Path) -> str:
    return (
        f"WORKTREE_ROOT {root} holds {path}, a worktree of the repository at"
        f" {repo} that no engine run marks. An earlier engine run may have left"
        " it (its cleanup failed, or it was killed before run markers existed),"
        " or it may be yours; connect never removes it. If it is an engine"
        f" leftover, run 'git worktree remove {path}' (git refuses while it"
        " holds uncommitted work: look at that work before you remove it) and"
        f" remove {path.parent}; if it is yours, set WORKTREE_ROOT to a"
        " directory outside every checkout"
    )


def test_a_user_worktree_shaped_like_an_engine_phase_keeps_its_work(
    make: Factory, project: Project, repo: Path, root: Path
) -> None:
    """
    GIVEN the user's own worktree at <WORKTREE_ROOT>/<repo>/<branch> (two
        plain names, the shape of an engine phase) with a branch checked
        out and uncommitted work in it
    WHEN preflight refuses it
    THEN the refusal does not call it the engine's and never advises
        --force, and following its advice to the letter cannot delete the
        user's work: plain 'git worktree remove' refuses
    """
    mine = root / "myrepo" / "feature"
    mine.parent.mkdir(parents=True)
    run_git(repo, "worktree", "add", "-q", "-b", "feature", str(mine), "HEAD")
    (mine / "draft.py").write_text("work in progress\n")

    message = refused(make(), project)

    assert message == unmarked_refusal(root, mine, repo)
    assert "--force" not in message
    assert "or it may be yours" in message
    removed = subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", str(mine)],
        capture_output=True,
        check=False,
    )
    assert removed.returncode != 0
    assert (mine / "draft.py").read_text() == "work in progress\n"


@pytest.mark.parametrize(
    "rel", ["mine", "a/b/c", ".hidden/baseline", "run/..x", "run/_scratch"], ids=str
)
def test_a_user_worktree_under_worktree_root_is_an_overlap(
    make: Factory, project: Project, repo: Path, root: Path, rel: str
) -> None:
    """
    GIVEN an unmarked worktree of the repository under WORKTREE_ROOT that
        is not shaped <run>/<phase> (two engine dir names)
    WHEN preflight checks the repository
    THEN it refuses with the overlap advice: it is no engine leftover
    """
    mine = root / rel
    mine.parent.mkdir(parents=True, exist_ok=True)
    run_git(repo, "worktree", "add", "-q", "--detach", str(mine), "HEAD")

    message = refused(make(), project)

    assert f"overlaps the worktree {mine}" in message
    assert "set WORKTREE_ROOT to a directory outside" in message


@pytest.mark.parametrize(
    ("key", "value"),
    [("extensions.partialClone", "origin"), ("remote.origin.promisor", "true")],
)
def test_partial_clones_and_promisor_remotes_are_refused(
    make: Factory, project: Project, repo: Path, key: str, value: str
) -> None:
    run_git(repo, "config", key, value)

    message = refused(make(), project)

    assert "git fetch --refetch" in message
    assert "full clone" in message


def test_a_promisor_without_a_value_counts_as_true(
    make: Factory, project: Project, repo: Path
) -> None:
    with (repo / ".git" / "config").open("a") as config:
        config.write('[remote "lazy"]\n\tpromisor\n')

    assert "lazy" in refused(make(), project)


def test_a_remote_that_is_not_a_promisor_is_accepted(
    make: Factory, project: Project, repo: Path
) -> None:
    run_git(repo, "config", "remote.origin.promisor", "false")
    run_git(repo, "config", "remote.origin.url", "https://example.invalid/r.git")

    assert check(make(), project).head_commit == out(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("name", [".gitmodules", ".GITMODULES"])
def test_submodules_are_refused(
    make: Factory, project: Project, repo: Path, name: str
) -> None:
    write(repo / name, '[submodule "x"]\n\tpath = x\n\turl = ./x\n')
    commit_all(repo)

    assert "submodule" in refused(make(), project)


def test_a_gitlink_without_gitmodules_is_refused(
    make: Factory, project: Project, repo: Path
) -> None:
    head = out(repo, "rev-parse", "HEAD")
    run_git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},vendored")
    run_git(repo, "commit", "-q", "-m", "gitlink")

    message = refused(make(), project)

    assert "submodule" in message
    assert "vendored" in message


@pytest.mark.parametrize("name", ["..", ".", ".git", ".GIT"])
def test_a_tree_entry_git_would_not_check_out_is_refused(
    make: Factory, project: Project, repo: Path, name: str
) -> None:
    """
    GIVEN a base commit built with git mktree holding a directory named
        '..', '.', '.git' or '.GIT' (a clone imports it: fsck is off by default)
    WHEN preflight reads the base tree
    THEN it refuses with a PreflightError naming the path, never a ValueError
    """
    blob = hash_blob(repo, LFS_LINE.encode())
    inner = run_git(
        repo, "mktree", stdin=f"100644 blob {blob}\t.gitattributes\n".encode()
    )
    listing = run_git(repo, "ls-tree", "HEAD") + b"040000 tree %s\t%s\n" % (
        inner.strip(),
        name.encode(),
    )
    top = run_git(repo, "mktree", stdin=listing).decode().strip()
    run_git(repo, "update-ref", "HEAD", out(repo, "commit-tree", top, "-m", "crafted"))

    message = refused(make(), project)

    assert f"{name}/.gitattributes" in message
    assert "check out" in message


def test_a_value_error_from_the_git_layer_is_a_preflight_error(
    make: Factory, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: GitWorkspace) -> tuple[str, ...]:
        raise ValueError("'x' is not a repo-relative git path")

    monkeypatch.setattr(GitWorkspace, "dirty_entries", broken)

    assert "not a repo-relative git path" in refused(make(), project)


# ---------------------------------------------------------------------------
# LFS: attribute sources read directly, never through check-attr or a filter
# ---------------------------------------------------------------------------


LFS_LINE = "*.bin filter=lfs diff=lfs merge=lfs -text\n"


def _arm_lfs_filter(repo: Path, marker: Path) -> None:
    """Configure an LFS filter that would leave ``marker`` if it ever ran."""
    command = f"sh -c 'touch {marker}; cat'"
    for key in ("smudge", "clean", "process"):
        run_git(repo, "config", f"filter.lfs.{key}", command)
    run_git(repo, "config", "filter.lfs.required", "true")


@pytest.mark.parametrize(
    "where", [".gitattributes", "assets/deep/.gitattributes", "assets/.GitAttributes"]
)
def test_lfs_in_a_committed_gitattributes_is_refused(
    make: Factory, project: Project, repo: Path, tmp_path: Path, where: str
) -> None:
    """
    GIVEN filter=lfs in a .gitattributes at the root or at any depth, an
        armed LFS filter in the repo config, and a git that supports
        --attr-source (so the engine's own calls hide the attributes)
    WHEN preflight checks the repository
    THEN it refuses, naming the file, and the filter never ran
    """
    write(repo / where, LFS_LINE)
    write(repo / "assets" / "w.bin", b"\x00binary")
    commit_all(repo)
    marker = tmp_path / "filter-ran"
    _arm_lfs_filter(repo, marker)
    engine_git = GitWorkspace(repo)
    hides = engine_git.version() >= ATTR_SOURCE_SINCE
    assert (engine_git._attr_source() != []) == hides

    message = refused(make(), project)

    assert "LFS" in message
    assert where in message
    assert not marker.exists()


def test_lfs_in_info_attributes_is_refused(
    make: Factory, project: Project, repo: Path
) -> None:
    write(repo / ".git" / "info" / "attributes", "# local\n" + LFS_LINE)

    message = refused(make(), project)

    assert "info/attributes" in message


@pytest.mark.parametrize("nested", [False, True], ids=["direct", "via-include"])
def test_a_conditional_include_is_refused(
    make: Factory, project: Project, repo: Path, tmp_path: Path, nested: bool
) -> None:
    """
    GIVEN an includeIf in the repository config, set directly or inside a
        file an unconditional include pulls in
    WHEN preflight checks the repository
    THEN it refuses, naming the key and the fix: a gitdir: or onbranch:
        condition can hold in a git child the engine's listing never sees
    """
    key = "includeIf.gitdir:worktrees/.path"
    hidden = write(tmp_path / "hidden.inc", '[filter "hide"]\n\tsmudge = cat\n')
    if nested:
        outer = write(
            tmp_path / "outer.inc",
            f'[includeIf "gitdir:worktrees/"]\n\tpath = {hidden}\n',
        )
        run_git(repo, "config", "include.path", str(outer))
    else:
        run_git(repo, "config", key, str(hidden))

    message = refused(make(), project)

    assert "includeif.gitdir:worktrees/.path" in message
    assert "conditional include" in message
    assert "remove" in message


def test_a_root_lfsconfig_is_refused(
    make: Factory, project: Project, repo: Path
) -> None:
    write(repo / ".lfsconfig", '[lfs]\n\turl = "https://example.invalid"\n')
    commit_all(repo)

    assert ".lfsconfig" in refused(make(), project)


def test_attributes_without_lfs_are_accepted(
    make: Factory, project: Project, repo: Path
) -> None:
    """
    GIVEN attribute files with other filters, a commented-out LFS line, a
        macro attribute that is not LFS, and an info/attributes without LFS
    WHEN preflight checks the repository
    THEN none of them refuses it
    """
    write(
        repo / ".gitattributes",
        "# *.psd filter=lfs diff=lfs\n*.txt text eol=lf\n*.dat filter=lfsx\n",
    )
    write(repo / "docs" / ".gitattributes", "[attr]big -diff\n*.raw big\n")
    commit_all(repo)
    write(repo / ".git" / "info" / "attributes", "*.md diff=markdown\n")

    assert check(make(), project).notes == ()


# ---------------------------------------------------------------------------
# merge= attributes: every source the engine's git reads for a combine
# ---------------------------------------------------------------------------


def merge_notes(report: PreflightReport) -> list[str]:
    return [note for note in report.notes if "merge" in note]


def info_attributes(repo: Path) -> Path:
    return repo / ".git" / "info" / "attributes"


def old_git(tmp_path: Path) -> str:
    """Real git reporting 2.39.0, so the engine passes no ``--attr-source``."""
    body = 'if [ "$1" = version ]; then echo "git version 2.39.0"; exit 0; fi\n'
    return fake_git(tmp_path, body + 'exec git "$@"\n')


def _arm_merge_driver(repo: Path, name: str, marker: Path) -> None:
    run_git(repo, "config", f"merge.{name}.driver", f"touch {marker}; false")


def _diverged(repo: Path) -> tuple[str, str]:
    """Commit the checkout with f.txt, then two commits changing its middle
    line differently (a 3-way conflict); HEAD is the second."""
    write(repo / "f.txt", "a\nb\nc\n")
    base = commit_all(repo)
    write(repo / "f.txt", "a\nX\nc\n")
    left = commit_all(repo)
    run_git(repo, "reset", "-q", "--hard", base)
    write(repo / "f.txt", "a\nY\nc\n")
    return left, commit_all(repo)


def _needs_attr_source(repo: Path) -> None:
    if GitWorkspace(repo).version() < ATTR_SOURCE_SINCE:
        pytest.skip("the real git has no --attr-source")


@pytest.mark.parametrize(
    "where",
    [".gitattributes", "a/b/.gitattributes", "assets/.GitAttributes", "info"],
)
def test_merge_union_in_any_attribute_source_is_a_note(
    make: Factory, project: Project, repo: Path, tmp_path: Path, where: str
) -> None:
    """
    GIVEN merge=union in a committed .gitattributes at any depth (any case)
        or in info/attributes, on a git without --attr-source (2.39: its
        merge-tree reads the committed files through the checkout)
    WHEN preflight checks the repository
    THEN it is accepted with one note naming the source and the pattern and
        saying the combined tip is still re-tested
    """
    if where == "info":
        write(info_attributes(repo), "*.txt merge=union\n")
        label = str(info_attributes(repo))
    else:
        write(repo / where, "*.txt merge=union\n")
        commit_all(repo)
        label = where

    (note,) = merge_notes(check(make(executable=old_git(tmp_path)), project))

    assert "merge=union" in note
    assert f"{label} (*.txt)" in note
    assert "re-tested" in note


def test_union_ours_and_binary_produce_one_note_each(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN on git 2.39 union on two patterns, ours on one, and binary through
        merge=binary, -merge, -merge=x (git drops the value of a - token)
        and the built-in binary macro
    WHEN preflight checks the repository
    THEN there is one note per kind, each naming its patterns
    """
    write(
        repo / ".gitattributes",
        "*.a merge=union\n*.b\tmerge=union\n*.c merge=ours\n"
        "*.d merge=binary\n*.e -merge\n*.png binary\n*.f -merge=x\n",
    )
    commit_all(repo)

    notes = merge_notes(check(make(executable=old_git(tmp_path)), project))

    assert len(notes) == 3
    union, ours, binary = notes
    assert "merge=union" in union
    assert "(*.a)" in union
    assert "(*.b)" in union
    assert "merge=ours" in ours
    assert "(*.c)" in ours
    assert "3-way" in ours
    assert all(f"(*.{p})" in binary for p in ("d", "e", "png"))
    assert "conflict" in binary
    assert "and 9 more" in binary  # *.f, then the checkout's and index's copies


def test_a_long_list_of_sources_is_capped_in_the_note(
    make: Factory, project: Project, repo: Path
) -> None:
    lines = "".join(f"*.u{i} merge=union\n" for i in range(5))
    write(info_attributes(repo), lines)

    (note,) = merge_notes(check(make(), project))

    assert "(*.u0)" in note
    assert "(*.u2)" in note
    assert "(*.u3)" not in note
    assert note.count("(*.u") == 3
    assert "and 2 more" in note


def test_merge_values_that_change_nothing_are_not_noted(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN on git 2.39 merge set, unspecified, =text, a name with no driver, a
        commented line, an unused macro, an unset or valued binary macro,
        !merge=union (unspecified), a value that only starts with union, and
        lines git drops whole: an invalid attribute name beside merge=union
        (bad$name, --x, !-x, a bare - or =x) and a line of 2048 bytes or more
    WHEN preflight checks the repository
    THEN no merge note is produced and it is accepted
    """
    long_line = "*.p" + " " * 2045 + "merge=union\n"
    write(
        repo / ".gitattributes",
        "*.a merge\n*.b !merge\n*.c merge=text\n*.d merge=nodriver\n"
        "# *.e merge=union\n   \n[attr]unused merge=union\n*.f -binary\n"
        "*.g binary=x\n*.h !merge=union\n*.i merge=unionx\n"
        "*.j merge=union bad$name\n*.k merge=union --x\n*.l merge=union !-x\n"
        "*.m merge=union -\n*.n merge=union =x\n[attr]bad merge=union b@d\n"
        "*.o bad\n" + long_line,
    )
    commit_all(repo)

    assert merge_notes(check(make(executable=old_git(tmp_path)), project)) == []


def test_macros_expand_across_sources_through_chains_and_loops(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN on git 2.39, a macro chain with a loop defined in a root .gitattributes that
        starts with a UTF-8 BOM, used under quoted patterns (one with an
        escape) in info/attributes, a macro whose quoted name is spelled with
        an octal escape, and an invalid quoted pattern git splits at blanks
    WHEN preflight checks the repository
    THEN the union, ours and binary they expand to are noted with the lines
    """
    write(
        repo / ".gitattributes",
        "\ufeff[attr]keep merge=union\n[attr]outer keep loop\n[attr]loop outer\n"
        '"\\133attr]esc" merge=ours\n',
    )
    commit_all(repo)
    info = '"sub dir/*.txt" loop\n*.z esc\n"bad\\q" binary\n"t\\tab" keep\n'
    write(info_attributes(repo), info)

    union, ours, binary = merge_notes(
        check(make(executable=old_git(tmp_path)), project)
    )

    assert '("sub dir/*.txt")' in union
    assert '("t\\tab")' in union
    assert '("bad\\q")' in binary  # invalid quoting: git splits at blanks
    assert "(*.z)" in ours


def test_info_attributes_of_a_linked_worktree_are_read_from_the_common_dir(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN root_path is a linked worktree and merge=union in the main
        repository's info/attributes (git reads info/ from the common dir)
    WHEN preflight checks the linked worktree
    THEN the note names the common dir's info/attributes
    """
    linked = tmp_path / "linked"
    run_git(repo, "worktree", "add", "-q", "--detach", str(linked), "HEAD")
    write(info_attributes(repo), "*.txt merge=union\n")
    project = project.model_copy(update={"root_path": str(linked.resolve())})

    (note,) = merge_notes(check(make(), project))

    assert str(info_attributes(repo)) in note


@pytest.mark.parametrize("where", [".gitattributes", "deep/er/.gitattributes", "info"])
def test_a_custom_merge_driver_is_refused_naming_the_file_and_the_fix(
    make: Factory, project: Project, repo: Path, tmp_path: Path, where: str
) -> None:
    """
    GIVEN merge=mine in an attribute source and merge.mine.driver configured,
        on git 2.39 (its merge-tree reads the committed files)
    WHEN preflight checks the repository
    THEN it refuses, naming the source, the attribute, the driver key and
        the fix, and the driver never ran
    """
    if where == "info":
        write(info_attributes(repo), "*.txt merge=mine\n")
        label = str(info_attributes(repo))
    else:
        write(repo / where, "*.txt merge=mine\n")
        commit_all(repo)
        label = where
    marker = tmp_path / "driver-ran"
    _arm_merge_driver(repo, "mine", marker)

    message = refused(make(executable=old_git(tmp_path)), project)

    assert f"{label} (*.txt)" in message
    assert "merge=mine" in message
    assert "merge.mine.driver" in message
    assert "remove" in message
    assert not marker.exists()


@pytest.mark.parametrize("name", ["union", "my.drv"])
def test_a_driver_under_a_builtin_name_or_in_a_macro_is_refused(
    make: Factory, project: Project, repo: Path, tmp_path: Path, name: str
) -> None:
    """
    GIVEN a macro that sets merge=<name>, and merge.<name>.driver configured
        under a built-in name (a user driver beats the built-in union) or a
        subsection with a dot
    WHEN preflight checks the repository
    THEN it refuses on git 2.39, naming the line that uses the macro
    """
    write(repo / ".gitattributes", f"[attr]joined merge={name}\n*.txt joined\n")
    commit_all(repo)
    _arm_merge_driver(repo, name, tmp_path / "ran")

    message = refused(make(executable=old_git(tmp_path)), project)

    assert ".gitattributes (*.txt)" in message
    assert f"merge.{name}.driver" in message


@pytest.mark.parametrize("key", ["name", "recursive"])
def test_any_key_under_a_merge_subsection_makes_a_shadowing_driver(
    make: Factory, project: Project, repo: Path, key: str
) -> None:
    # info/attributes: the engine's merge-tree reads it on every git version
    """
    GIVEN merge=union and only merge.union.<key> configured (no driver
        command: git then dies with 'lacks command line' instead of merging)
    WHEN preflight checks the repository
    THEN it refuses, naming that key
    """
    write(info_attributes(repo), "*.txt merge=union\n")
    run_git(repo, "config", f"merge.union.{key}", "text")

    message = refused(make(), project)

    assert f"merge.union.{key}" in message


def test_unset_merge_uses_the_builtin_binary_even_with_a_binary_driver(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN -merge (and the binary macro) with merge.binary.driver configured
    WHEN preflight checks the repository
    THEN it is a note, not a refusal: git never looks up a driver for an
        unset merge attribute
    """
    write(info_attributes(repo), "*.e -merge\n*.png binary\n")
    _arm_merge_driver(repo, "binary", tmp_path / "ran")

    (note,) = merge_notes(check(make(), project))

    assert "(*.e)" in note
    assert "(*.png)" in note


def test_a_configured_driver_no_attribute_names_is_accepted(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    _arm_merge_driver(repo, "mine", tmp_path / "ran")
    run_git(repo, "config", "--bool", "merge.flag.driver", "true")

    assert merge_notes(check(make(), project)) == []


def test_merge_default_union_is_a_note_and_a_default_driver_is_refused(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN merge.default=union, then merge.default=mine with merge.mine.driver
    WHEN preflight checks the repository each time
    THEN the first is a note naming merge.default, the second a refusal
    """
    run_git(repo, "config", "merge.default", "union")

    (note,) = merge_notes(check(make(), project))

    assert "merge.default" in note
    run_git(repo, "config", "merge.default", "mine")
    _arm_merge_driver(repo, "mine", tmp_path / "ran")
    message = refused(make(), project)
    assert "merge.default" in message
    assert "merge.mine.driver" in message


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("[merge]", "merge.default"),
        ('[merge "mine"]', "merge.mine.driver"),
        ('[merge "mine"]', "merge.mine.name"),
        ('[merge "mine"]', "merge.mine.recursive"),
    ],
)
def test_a_valueless_merge_key_git_dies_on_is_refused(
    make: Factory, project: Project, repo: Path, section: str, key: str
) -> None:
    """
    GIVEN a valueless merge.default, merge.<name>.driver, .name or .recursive
        in the repository config (no attribute names the driver)
    WHEN the engine's git merges, and preflight checks the repository
    THEN git dies ('bad config variable'), so preflight refuses, naming the
        key and the fix
    """
    left, right = _diverged(repo)
    with (repo / ".git" / "config").open("a") as config:
        config.write(f"{section}\n\t{key.rpartition('.')[2]}\n")
    with pytest.raises(GitError, match="bad config variable"):
        GitWorkspace(repo).merge(left, right)

    message = refused(make(), project)

    assert f"{key} in the repository config has no value" in message
    assert "set a value or remove it" in message


def test_a_valued_unknown_key_under_a_merge_subsection_is_accepted(
    make: Factory, project: Project, repo: Path
) -> None:
    with (repo / ".git" / "config").open("a") as config:
        config.write('[merge "mine"]\n\tother\n')

    assert merge_notes(check(make(), project)) == []


@pytest.mark.parametrize("select", ["attribute", "default"])
def test_a_driver_in_the_empty_merge_subsection_is_refused(
    make: Factory, project: Project, repo: Path, tmp_path: Path, select: str
) -> None:
    """
    GIVEN [merge ""] driver = ... in the repository config, selected by an
        empty merge= attribute in info/attributes or by merge.default = ""
    WHEN preflight checks the repository
    THEN it refuses, naming merge..driver (git runs that driver)
    """
    with (repo / ".git" / "config").open("a") as config:
        config.write(f'[merge ""]\n\tdriver = touch {tmp_path / "ran"}\n')
    if select == "attribute":
        write(info_attributes(repo), "*.txt merge=\n")
    else:
        run_git(repo, "config", "merge.default", "")

    message = refused(make(), project)

    assert "merge..driver" in message
    assert 'selects merge="", a custom merge driver' in message


def test_the_repo_core_attributes_file_is_overridden_like_the_engine_git(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN core.attributesFile in the repository config naming a union file
    WHEN preflight checks the repository
    THEN no note: the engine's git pins core.attributesFile=/dev/null, so
        its merge-tree never reads that file either
    """
    attributes = write(tmp_path / "global-attributes", "*.txt merge=union\n")
    run_git(repo, "config", "core.attributesFile", str(attributes))

    assert merge_notes(check(make(), project)) == []


@pytest.mark.parametrize("relative", [False, True], ids=["absolute", "relative"])
def test_the_attributes_file_the_engine_git_reports_is_read(
    make: Factory, project: Project, repo: Path, tmp_path: Path, relative: bool
) -> None:
    """
    GIVEN a git whose effective core.attributesFile (absolute, or relative
        to the repository) holds merge=union
    WHEN preflight checks the repository
    THEN the note names core.attributesFile and the file
    """
    attributes = write(repo / "attrs.txt", "*.txt merge=union\n")
    value = "attrs.txt" if relative else str(attributes)
    body = (
        'case " $* " in *" --get core.attributesFile "*)'
        f" printf '%s\\0' '{value}'; exit 0;; esac\n"
    )
    git = fake_git(tmp_path, body + 'exec git "$@"\n')

    (note,) = merge_notes(check(make(executable=git), project))

    assert f"core.attributesFile {attributes}" in note


def test_an_unset_attributes_file_reads_nothing(
    make: Factory, project: Project, tmp_path: Path
) -> None:
    body = 'case " $* " in *" --get core.attributesFile "*) exit 1;; esac\n'
    git = fake_git(tmp_path, body + 'exec git "$@"\n')

    assert merge_notes(check(make(executable=git), project)) == []


def test_old_git_reads_the_checkout_and_index_attributes(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN an untracked root .gitattributes with union and a staged nested
        one with ours deleted from the checkout, on a git without
        --attr-source (2.39) and on the real git
    WHEN preflight checks the repository with each
    THEN the old git notes both (its merge-tree reads the checkout, then the
        index), the real git notes neither (--attr-source hides them)
    """
    write(repo / ".gitattributes", "*.txt merge=union\n")
    write(repo / "n" / ".gitattributes", "*.c merge=ours\n")
    run_git(repo, "add", "n/.gitattributes")
    (repo / "n" / ".gitattributes").unlink()
    if GitWorkspace(repo).version() < ATTR_SOURCE_SINCE:
        pytest.skip("the real git has no --attr-source")

    union, ours = merge_notes(check(make(executable=old_git(tmp_path)), project))

    assert "the checkout's .gitattributes (*.txt)" in union
    assert "the index's n/.gitattributes (*.c)" in ours
    assert merge_notes(check(make(), project)) == []


def test_old_git_reads_through_a_directory_link_but_not_a_file_link(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN on git 2.39 a tracked d/.gitattributes whose directory became a
        link out of the repository, and an untracked e/.gitattributes that is
        itself a link, both reaching union attributes outside it
    WHEN preflight checks the repository
    THEN the d file is noted and labelled as read through a directory link
        (git's open follows a directory link), the e link is not read (git
        opens the last component with O_NOFOLLOW)
    """
    outside = tmp_path / "outside"
    write(outside / ".gitattributes", "*.txt merge=union\n")
    write(repo / "d" / ".gitattributes", "*.x text\n")
    commit_all(repo)
    shutil.rmtree(repo / "d")
    os.symlink(outside, repo / "d")
    write(repo / "e" / "keep", "")
    os.symlink(outside / ".gitattributes", repo / "e" / ".gitattributes")

    (note,) = merge_notes(check(make(executable=old_git(tmp_path)), project))

    assert "the checkout's d/.gitattributes (through a directory link) (*.txt)" in note
    assert "e/.gitattributes" not in note


def test_old_git_index_entries_with_a_bad_object_id_are_a_preflight_error(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    body = (
        'case " $* " in *" ls-files -z -s "*)'
        " printf '100644 zz 0\\t.gitattributes\\0'; exit 0;; esac\n"
        'if [ "$1" = version ]; then echo "git version 2.39.0"; exit 0; fi\n'
    )
    git = fake_git(tmp_path, body + 'exec git "$@"\n')

    message = refused(make(executable=git), project)

    assert "object id" in message


def test_merge_note_text_is_printable(
    make: Factory, project: Project, repo: Path
) -> None:
    write(info_attributes(repo), b"\x1b[31m*.txt merge=union\n")

    (note,) = merge_notes(check(make(), project))

    assert "\x1b" not in note
    assert "?[31m*.txt" in note
    assert note.isprintable()


def test_the_engine_merge_tree_really_honours_info_attributes_union(
    repo: Path,
) -> None:
    """
    GIVEN two commits changing one line differently and merge=union in
        info/attributes
    WHEN the engine's own GitWorkspace.merge combines them
    THEN merge-tree reports no conflict: the case the note warns about
    """
    left, right = _diverged(repo)
    git = GitWorkspace(repo)

    assert git.merge(left, right).tree is None
    write(info_attributes(repo), "*.txt merge=union\n")
    assert git.merge(left, right).tree is not None


def test_the_engine_merge_tree_ignores_a_committed_union_on_git_with_attr_source(
    repo: Path,
) -> None:
    """
    GIVEN on git >= 2.40 a committed *.txt merge=union and two commits
        changing one line differently
    WHEN the user's plain git merge-tree and the engine's GitWorkspace.merge
        combine them
    THEN the user's merge unions (exit 0), the engine's conflicts: why a
        committed file is a note there, not a refusal
    """
    _needs_attr_source(repo)
    write(repo / ".gitattributes", "*.txt merge=union\n")
    left, right = _diverged(repo)

    run_git(repo, "merge-tree", "--write-tree", left, right)  # exit 0 asserted
    assert GitWorkspace(repo).merge(left, right).conflicts == ("f.txt",)


def test_committed_merge_attributes_are_one_note_where_the_engine_ignores_them(
    make: Factory, project: Project, repo: Path, tmp_path: Path
) -> None:
    """
    GIVEN on git >= 2.40 committed .gitattributes (root and nested) with a
        custom driver (merge.mine.driver configured), union, -merge, ours
        with no ours driver, and a macro defined there that info/attributes
        uses
    WHEN preflight checks the repository
    THEN it is accepted with one note naming the committed places of the
        driver, union and binary merges (not ours: both gits 3-way merge it)
        and saying the engine's combines do not read them; the info line
        using the committed macro is not noted (the engine's git does not
        read the macro either) and the driver never ran
    """
    _needs_attr_source(repo)
    write(
        repo / ".gitattributes",
        "[attr]joined merge=union\n*.txt merge=mine\n*.c merge=ours\n",
    )
    write(repo / "n" / ".gitattributes", "*.a merge=union\n*.b -merge\n")
    commit_all(repo)
    write(info_attributes(repo), "*.m joined\n")
    _arm_merge_driver(repo, "mine", tmp_path / "ran")

    (note,) = merge_notes(check(make(), project))

    assert note.startswith("merge=mine, merge=union, -merge in .gitattributes (*.txt)")
    assert "n/.gitattributes (*.a), n/.gitattributes (*.b):" in note
    assert "(*.c)" not in note
    assert "(*.m)" not in note
    assert "do not read committed .gitattributes" in note
    assert not (tmp_path / "ran").exists()


def test_a_nul_ends_a_committed_blob_but_only_its_line_in_a_file(
    make: Factory, project: Project, repo: Path
) -> None:
    """
    GIVEN on git >= 2.40 a committed .gitattributes with a NUL after its
        first line, and an info/attributes with a NUL inside its first line
    WHEN preflight checks the repository
    THEN as git: the blob is read up to the NUL (*.b ignored), the file's
        first line up to the NUL and its later lines in full
    """
    _needs_attr_source(repo)
    write(repo / ".gitattributes", b"*.a merge=union\0\n*.b merge=union\n")
    commit_all(repo)
    write(info_attributes(repo), b"*.c merge=union\0junk\n*.d merge=union\n")

    union, committed = merge_notes(check(make(), project))

    assert "(*.c)" in union
    assert "(*.d)" in union
    assert "(*.a)" in committed
    assert "(*.b)" not in committed


def test_macro_fan_out_and_long_chains_are_checked_in_linear_time(
    make: Factory, project: Project, repo: Path
) -> None:
    """
    GIVEN info/attributes defining one macro 2,000 times (22,000 attributes,
        merge=union among them; lines stay under git's 2048 bytes) used on
        8,000 lines, and a chain of 5,000 macros ending in merge=union used on
        5,000 lines (expanding each use again took over 30 s; a recursive walk
        would overflow the stack)
    WHEN preflight checks the repository
    THEN it finishes well within 5 s and notes every line
    """
    names = " ".join(f"t{i}" for i in range(10))
    definitions = f"[attr]a merge=union {names}\n" * 2_000
    chain = "".join(f"[attr]c{i} c{i + 1}\n" for i in range(5_000))
    lines = "p a\n" * 8_000 + "".join(f"q{i} c{i}\n" for i in range(5_000))
    text = f"{definitions}{chain}[attr]c5000 merge=union\n{lines}"
    write(info_attributes(repo), text)

    start = time.monotonic()
    (note,) = merge_notes(check(make(), project))

    assert time.monotonic() - start < 5
    assert "and 12997 more" in note


@pytest.mark.parametrize("where", ["committed", "info"])
def test_an_attribute_file_over_the_read_cap_is_refused(
    make: Factory,
    project: Project,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    where: str,
) -> None:
    """
    GIVEN a committed .gitattributes or an info/attributes larger than the
        bytes preflight reads (git reads attribute files up to 100 MB)
    WHEN preflight checks the repository
    THEN it refuses, naming the file and the cap, instead of checking a part
    """
    monkeypatch.setattr(preflight, "_MAX_ATTRIBUTES_BYTES", 64)
    text = "*.txt text\n" * 10
    if where == "committed":
        write(repo / "d" / ".gitattributes", text)
        commit_all(repo)
        name = "d/.gitattributes"
    else:
        write(info_attributes(repo), text)
        name = str(info_attributes(repo))

    message = refused(make(), project)

    assert f"{name} is larger than the 64 bytes preflight reads" in message


def test_old_git_refuses_an_index_attribute_blob_over_the_read_cap(
    make: Factory,
    project: Project,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "_MAX_ATTRIBUTES_BYTES", 64)
    write(repo / "n" / ".gitattributes", "*.txt text\n" * 10)
    run_git(repo, "add", "n/.gitattributes")

    message = refused(make(executable=old_git(tmp_path)), project)

    assert "the index's n/.gitattributes is larger than the 64 bytes" in message


# ---------------------------------------------------------------------------
# The engine Python must parse every .py blob at base
# ---------------------------------------------------------------------------


def test_a_py_file_the_engine_cannot_parse_is_refused(
    make: Factory, project: Project, repo: Path
) -> None:
    write(repo / "pkg" / "new_syntax.py", "def f(:\n    pass\n")
    commit_all(repo)

    message = refused(make(), project)

    assert "pkg/new_syntax.py" in message
    assert ENGINE_VERSION in message


def test_a_py_file_with_nul_bytes_is_refused(
    make: Factory, project: Project, repo: Path
) -> None:
    write(repo / "nul.py", b"x = 1\x00\n")
    commit_all(repo)

    assert "nul.py" in refused(make(), project)


def test_a_py_file_too_deep_for_the_parser_is_refused(
    make: Factory, project: Project, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repo / "deep.py", "x = 1\n")
    commit_all(repo)
    real = ast.parse

    def parse(source: str | bytes, *args: Any, **kwargs: Any) -> ast.AST:
        if source == b"x = 1\n":
            raise RecursionError("maximum recursion depth exceeded")
        tree: ast.AST = real(source, *args, **kwargs)
        return tree

    monkeypatch.setattr(ast, "parse", parse)

    message = refused(make(), project)

    assert "deep.py" in message
    assert "RecursionError" in message


def test_the_syntax_scan_reads_the_base_commit_not_the_checkout(
    make: Factory, project: Project, repo: Path
) -> None:
    write(repo / "core.py", "def broken(:\n")

    report = check(make(), project)

    assert report.dirty_entries == (" M core.py",)


def test_symlinks_are_not_parsed_and_big_files_are_skipped_with_a_note(
    make: Factory, project: Project, repo: Path
) -> None:
    """
    GIVEN a .py symlink whose target text is not Python, and a .py file
        larger than the parse cap that does not parse
    WHEN preflight checks the repository
    THEN the symlink is ignored, the big file is skipped with a note
    """
    os.symlink("not python (", repo / "link.py")
    write(repo / "big.py", "def f(:\n" * 20)
    commit_all(repo)

    report = check(make(max_parse_bytes=64), project)

    assert len(report.notes) == 1
    assert "big.py" in report.notes[0]
    assert "64" in report.notes[0]


@pytest.mark.parametrize(
    ("path", "command", "patterns"),
    [
        ("tests/fixtures/py2.py", (), None),
        ("tools/harness.py", ("tool", "tools/harness.py"), None),
        ("fixtures/py2.py", (), ("fixtures/**",)),
    ],
)
def test_an_unparsable_protected_file_is_a_note_not_a_refusal(
    make: Factory,
    project: Project,
    repo: Path,
    path: str,
    command: tuple[str, ...],
    patterns: tuple[str, ...] | None,
) -> None:
    """
    GIVEN a Python 2 file no trial may edit: under a default protected
        pattern, a harness the workload names, or under the patterns the
        engine passes in
    WHEN preflight scans the base tree
    THEN it is a note naming the file and the engine's Python, not a refusal
    """
    write(repo / path, 'print "hello"\n')
    commit_all(repo)
    pf = make() if patterns is None else make(protected=patterns)

    report = check(pf, project, [workload(project, *command)] if command else [])

    (note,) = report.notes
    assert path in note
    assert ENGINE_VERSION in note
    assert "protected" in note


def test_the_scan_batches_blobs_and_reads_shared_content_once(
    make: Factory,
    project: Project,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN more .py blobs than one batch holds, some with the same content,
        and an unparsable file in the last batch
    WHEN preflight checks the repository
    THEN the error names that file, git show ran once per batch of two ids,
        and each distinct blob was asked for exactly once
    """
    monkeypatch.setattr(preflight, "_BATCH", 2)
    for index in range(5):
        write(repo / "many" / f"m{index}.py", f"VALUE = {index}\n")
    write(repo / "many" / "same.py", "VALUE = 0\n")
    write(repo / "zz_last.py", "def f(:\n")
    commit_all(repo)
    log = tmp_path / "show.log"

    message = refused(make(executable=logging_git(tmp_path, log)), project)

    assert "zz_last.py" in message
    blobs, calls = py_blobs(repo), shown(log)
    assert len(calls) == math.ceil(len(blobs) / 2)
    assert all(1 <= len(call) <= 2 for call in calls)
    assert sorted(oid for call in calls for oid in call) == sorted(blobs)


def test_the_scan_stops_reading_at_the_first_refusal(
    make: Factory,
    project: Project,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN an unparsable file in the first batch of many
    WHEN preflight scans the base tree
    THEN it refuses after reading that one batch (blobs are never all held)
    """
    monkeypatch.setattr(preflight, "_BATCH", 2)
    write(repo / "aa_first.py", "def f(:\n")
    commit_all(repo)
    log = tmp_path / "show.log"

    assert "aa_first.py" in refused(
        make(executable=logging_git(tmp_path, log)), project
    )
    assert len(shown(log)) == 1
    assert len(py_blobs(repo)) > 2


@pytest.mark.parametrize(
    ("name", "shown_as"),
    [(b"\x1b[2K\x1b[1Ahidden.py", "?[2K?[1Ahidden.py"), (b"bad\xff.py", "bad?.py")],
)
def test_refusal_text_is_printable_utf8(
    make: Factory, project: Project, repo: Path, name: bytes, shown_as: str
) -> None:
    """
    GIVEN a committed .py file that does not parse, named with terminal
        escapes or with bytes that are not UTF-8
    WHEN preflight refuses it
    THEN the message shows '?' for them, so it prints on any terminal
    """
    blob = hash_blob(repo, b"def f(:\n")
    entry = f"100644,{blob},{os.fsdecode(name)}"
    run_git(repo, "update-index", "--add", "--cacheinfo", entry)
    run_git(repo, "commit", "-q", "-m", "odd name")

    message = refused(make(), project)

    assert shown_as in message
    assert message.isprintable()
    assert message.encode("utf-8")


def test_a_truncated_blob_read_is_a_preflight_error(
    make: Factory, project: Project, tmp_path: Path
) -> None:
    body = (
        'case " $* " in *" show "*) printf x; exit 0;; esac\n'
        'if [ "$1" = version ]; then echo "git version 2.43.0"; exit 0; fi\n'
        'exec git "$@"\n'
    )

    message = refused(make(executable=fake_git(tmp_path, body)), project)

    assert "bytes" in message


def test_malformed_ls_tree_output_is_a_preflight_error(
    make: Factory, project: Project, tmp_path: Path
) -> None:
    body = (
        'case " $* " in *" ls-tree "*) printf "garbage\\0"; exit 0;; esac\n'
        'if [ "$1" = version ]; then echo "git version 2.43.0"; exit 0; fi\n'
        'exec git "$@"\n'
    )

    message = refused(make(executable=fake_git(tmp_path, body)), project)

    assert "ls-tree" in message


# ---------------------------------------------------------------------------
# Command resolution and the protected harness
# ---------------------------------------------------------------------------


def test_bare_names_resolve_on_the_absolute_path_entries_only(
    make: Factory,
    project: Project,
    tmp_path: Path,
    bin_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN a PATH with an empty and a relative entry before bin_dir, and a
        'tool' in the current directory and in that relative entry
    WHEN preflight resolves 'tool'
    THEN it finds bin_dir/tool, never the current directory's copy
    """
    monkeypatch.chdir(tmp_path)
    executable(tmp_path / "tool")
    executable(tmp_path / "relbin" / "tool")
    pf = make(search_path=os.pathsep.join(["", "relbin", str(bin_dir)]))

    report = check(pf, project, [workload(project, "tool")])

    assert report.workloads[0].command == (str(bin_dir / "tool"),)


@pytest.mark.parametrize("search", ["", "relbin", ":relbin:."])
def test_a_bare_name_only_on_relative_entries_is_refused(
    make: Factory,
    project: Project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    search: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    executable(tmp_path / "only-here")
    executable(tmp_path / "relbin" / "only-here")

    message = refused(
        make(search_path=search), project, [workload(project, "only-here")]
    )

    assert "only-here" in message
    assert "PATH" in message


def test_the_default_search_path_is_the_engine_path(
    make: Factory, project: Project, bin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), os.environ["PATH"]]))

    report = check(make(search_path=None), project, [workload(project, "tool")])

    assert report.workloads[0].command == (str(bin_dir / "tool"),)


@pytest.mark.parametrize(
    ("command", "resolved", "protected"),
    [
        (("./run.sh",), ("run.sh",), ("run.sh",)),
        (("run.sh", "x"), ("run.sh", "x"), ("run.sh",)),
        (("scripts/bench",), ("scripts/bench",), ("scripts/bench",)),
        (("link-run",), ("link-run",), ("link-run", "scripts/bench")),
    ],
)
def test_repo_relative_commands_stay_relative_and_are_protected(
    make: Factory,
    project: Project,
    command: tuple[str, ...],
    resolved: tuple[str, ...],
    protected: tuple[str, ...],
) -> None:
    report = check(make(), project, [workload(project, *command)])

    assert report.workloads[0].command == resolved
    assert report.extra_protected == protected


def test_every_argv_element_naming_a_repo_file_is_protected(
    make: Factory, project: Project, bin_dir: Path
) -> None:
    """
    GIVEN a harness script argument, an --option=file, a KEY=file, '-m'
        targets (a module file, a src/ package's __main__, -mNAME), arguments
        resolved from working_dir, a name that is not a file, a directory and
        a path escaping the repository
    WHEN preflight resolves the commands
    THEN exactly the repository files among them are protected
    """
    first = workload(
        project,
        "tool",
        "scripts/bench.py",
        "--config=conf.toml",
        "INIT=pkg/__init__.py",
        "-m",
        "pkg.bench",
        "-mtool",
        "-m",
        "not a module",
        "missing.py",
        "core",
        "tests",
        "-m",
    )
    second = workload(
        project, "tool", "bench.py", "../core.py", "../../x", working_dir="sub"
    )

    report = check(make(), project, [first, second])

    assert report.workloads[1].command[0] == str(bin_dir / "tool")
    assert report.extra_protected == (
        "conf.toml",
        "core.py",
        "pkg/__init__.py",
        "pkg/bench.py",
        "scripts/bench.py",
        "src/tool/__main__.py",
        "sub/bench.py",
    )


def test_a_repo_relative_test_command_is_protected(
    make: Factory, project: Project
) -> None:
    project = project.model_copy(update={"test_command": ("./run.sh", "-v")})

    report = check(make(), project, guardrails=[tests_pass(project)])

    assert report.test_command == ("run.sh", "-v")
    assert report.extra_protected == ("run.sh",)


def test_protected_paths_with_glob_characters_are_escaped(
    make: Factory, project: Project, repo: Path
) -> None:
    write(repo / "bench[1].py", "print(1)\n")
    commit_all(repo)

    report = check(make(), project, [workload(project, "tool", "bench[1].py")])

    (pattern,) = report.extra_protected
    assert matches_pattern("bench[1].py", pattern)
    assert not matches_pattern("bench1.py", pattern)


def test_an_absolute_executable_outside_the_repo_is_kept(
    make: Factory, project: Project, bin_dir: Path, repo: Path
) -> None:
    untracked = executable(repo / ".venv" / "bin" / "py")
    commands = [(str(bin_dir / "tool"),), (str(untracked), "core.py")]

    report = check(make(), project, [workload(project, *c) for c in commands])

    assert [w.command for w in report.workloads] == commands
    assert report.extra_protected == ("core.py",)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (("nosuchtool",), "PATH"),
        (("plain.sh",), "not executable"),
        (("scripts/missing",), "not a file in the repository"),
        (("~/bin/tool",), "repo-relative"),
        (("tool", "a\0b"), "NUL"),
    ],
)
def test_unresolvable_commands_are_refused(
    make: Factory, project: Project, command: tuple[str, ...], expected: str
) -> None:
    message = refused(make(), project, [workload(project, *command)])

    assert expected in message


def test_a_non_executable_absolute_command_is_refused(
    make: Factory, project: Project, bin_dir: Path
) -> None:
    message = refused(make(), project, [workload(project, str(bin_dir / "notexec"))])

    assert "notexec" in message


@pytest.mark.parametrize("position", [0, 1])
def test_an_absolute_path_to_a_tracked_file_is_refused(
    make: Factory, project: Project, repo: Path, position: int
) -> None:
    """
    GIVEN a command naming a tracked file by its absolute path in the
        user's checkout (as argv[0] or as an argument)
    WHEN preflight resolves it
    THEN it refuses: the run would use the checkout's copy, not the trial's
    """
    path = str(repo / "run.sh")
    command = (path,) if position == 0 else ("tool", path)

    message = refused(make(), project, [workload(project, *command)])

    assert "run.sh" in message
    assert "relative" in message


def test_a_working_dir_missing_at_base_is_refused(
    make: Factory, project: Project
) -> None:
    message = refused(
        make(), project, [workload(project, "tool", working_dir="nowhere")]
    )

    assert "nowhere" in message


def test_a_symlink_loop_command_is_refused(
    make: Factory, project: Project, repo: Path
) -> None:
    os.symlink("loop-b", repo / "loop-a")
    os.symlink("loop-a", repo / "loop-b")
    commit_all(repo)

    assert "loop-a" in refused(make(), project, [workload(project, "loop-a")])


@pytest.mark.parametrize("target", ["absolute", "../outside-tool", "scripts", "gone"])
def test_a_command_link_that_leaves_the_tree_is_refused(
    make: Factory, project: Project, repo: Path, bin_dir: Path, target: str
) -> None:
    """
    GIVEN a tracked argv[0] symlink to an absolute path, out of the
        repository with '..', to a directory, or to nothing
    WHEN preflight resolves it
    THEN it refuses, as the measurement would ('resolves outside the worktree')
    """
    link = str(bin_dir / "tool") if target == "absolute" else target
    os.symlink(link, repo / "link-cmd")
    commit_all(repo)

    message = refused(make(), project, [workload(project, "link-cmd")])

    assert "link-cmd is not a file in the repository" in message


def test_a_command_through_a_linked_directory_is_protected_with_the_link(
    make: Factory, project: Project, repo: Path
) -> None:
    os.symlink("scripts", repo / "linkdir")
    commit_all(repo)

    report = check(make(), project, [workload(project, "linkdir/bench")])

    assert report.workloads[0].command == ("linkdir/bench",)
    assert report.extra_protected == ("linkdir", "scripts/bench")


def test_arguments_through_linked_dirs_or_in_another_case_are_protected(
    make: Factory, project: Project, repo: Path
) -> None:
    """
    GIVEN harness arguments named through a tracked directory symlink, or in
        another case (macOS opens Scripts/Bench.PY as scripts/bench.py)
    WHEN preflight resolves them
    THEN the file each one opens is protected, and so is the link
    """
    os.symlink("scripts", repo / "linkdir")
    commit_all(repo)
    first = workload(project, "tool", "linkdir/bench.py")
    second = workload(project, "tool", "Scripts/Bench.PY", "CORE.py")

    report = check(make(), project, [first, second])

    assert report.extra_protected == ("core.py", "linkdir", "scripts/bench.py")


@pytest.mark.parametrize("command", ["./go.sh", "go.sh"])
def test_argv0_beside_working_dir_names_the_root_relative_path(
    make: Factory, project: Project, repo: Path, command: str
) -> None:
    """
    GIVEN an executable sub/go.sh and a workload in working_dir 'sub' that
        names it relative to working_dir
    WHEN preflight resolves argv[0]
    THEN it refuses and says argv[0] is relative to the root: use sub/go.sh
    """
    executable(repo / "sub" / "go.sh")
    commit_all(repo)

    message = refused(make(), project, [workload(project, command, working_dir="sub")])

    assert "relative to the repository root, not working_dir" in message
    assert "sub/go.sh" in message


@pytest.mark.parametrize("target", ["tests", "."])
def test_an_absolute_checkout_directory_is_refused(
    make: Factory, project: Project, repo: Path, target: str
) -> None:
    """
    GIVEN a workload argument, and a test command argument, naming a tracked
        directory of the user's checkout (a test dir, the root) absolutely
    WHEN preflight resolves them
    THEN it refuses both: the run would read the checkout, not the worktree
    """
    path = str(repo / target)
    suite = project.model_copy(update={"test_command": ("tool", "-m", "pytest", path)})

    messages = [
        refused(make(), project, [workload(project, "tool", path)]),
        refused(make(), suite, guardrails=[tests_pass(suite)]),
    ]

    for message in messages:
        assert "is the checkout's" in message
        assert "relative" in message


def test_a_path_hit_inside_the_checkout_is_refused(
    make: Factory, project: Project, repo: Path
) -> None:
    """
    GIVEN a PATH entry inside the checkout (direnv's PATH_add) holding a
        tracked harness
    WHEN preflight resolves the harness by its bare name
    THEN it refuses and names the repo-relative path to give instead
    """
    pf = make(search_path=str(repo / "scripts"))

    message = refused(pf, project, [workload(project, "bench")])

    assert "is the checkout's scripts/bench" in message
    assert "'scripts/bench'" in message


def test_untracked_files_inside_the_checkout_are_kept(
    make: Factory, project: Project, repo: Path
) -> None:
    """
    GIVEN an untracked virtualenv inside the checkout, on PATH, and its
        directory named by absolute path
    WHEN preflight resolves them
    THEN the interpreter resolves to its absolute path and both are kept
    """
    venv = repo / ".venv"
    python = executable(venv / "bin" / "py")

    report = check(
        make(search_path=str(venv / "bin")),
        project,
        [workload(project, "py", str(venv))],
    )

    assert report.workloads[0].command == (str(python), str(venv))
    assert report.extra_protected == ()


@pytest.mark.parametrize(
    "command",
    [
        ("sh", "-c", "python scripts/bench.py"),
        ("bash", "--norc", "-ec", "x"),
        ("bash", "-o", "pipefail", "-c", "x"),
        ("fish", "--command=x"),
        ("python3", "-c", "import bench"),
        ("python3", "-Bc", "import bench"),
        ("python3", "-W", "error", "-c", "x"),
        ("tool", "python3.13", "-I", "-c", "x"),
    ],
)
def test_inline_code_strings_are_refused(
    make: Factory, project: Project, command: tuple[str, ...]
) -> None:
    """
    GIVEN a shell or Python (also behind a launcher such as env or uv run)
        given its code as a string
    WHEN preflight resolves the command
    THEN it refuses: preflight cannot protect a harness it cannot see
    """
    message = refused(make(), project, [workload(project, *command)])

    assert "inline code" in message
    assert "script in the repository" in message


def test_an_inline_test_command_is_refused(make: Factory, project: Project) -> None:
    suite = project.model_copy(update={"test_command": ("python3", "-c", "import t")})

    message = refused(make(), suite, guardrails=[tests_pass(suite)])

    assert "test_command" in message
    assert "inline code" in message


@pytest.mark.parametrize(
    "command",
    [
        ("python3", "-m", "pytest", "-c", "conf.toml"),
        ("python3", "-Wdefault::ResourceWarning", "-X", "importtime", "core.py", "-c"),
        ("python3", "--check-hash-based-pycs", "always", "-", "-c"),
        ("python3", "--", "-c"),
        ("sh", "-e", "run.sh", "-c", "x"),
        ("bash", "--rcfile", "-c", "run.sh"),
        ("bash", "+o", "posix", "run.sh"),
        ("tool", "-c", "conf.toml"),
        ("tool", "--shell", "sh"),
    ],
)
def test_options_that_are_not_inline_code_are_accepted(
    make: Factory, project: Project, command: tuple[str, ...]
) -> None:
    report = check(make(), project, [workload(project, *command)])

    assert report.workloads[0].command[1:] == command[1:]


@pytest.mark.parametrize(
    ("suite", "protected"),
    [
        (("tool", "-m", "unittest", "discover", "-s", "checks"), ("checks/**",)),
        (
            ("tool", "--rootdir=Checks/", "checks/testcore.py::TestCore"),
            ("checks/**", "checks/testcore.py"),
        ),
        (("tool", ".", "src", "./src/", "missing/"), ()),
    ],
)
def test_test_directories_named_by_the_test_command_are_protected(
    make: Factory,
    project: Project,
    suite: tuple[str, ...],
    protected: tuple[str, ...],
) -> None:
    """
    GIVEN a test command naming a test directory outside the default
        patterns (a unittest start dir, an --option=dir value in another
        case), a pytest node id, or the root and src
    WHEN preflight resolves it
    THEN each named test directory's whole tree is protected, except the
        root and src, which hold the code under optimisation
    """
    project = project.model_copy(update={"test_command": suite})

    report = check(make(), project, guardrails=[tests_pass(project)])

    assert report.extra_protected == protected


# ---------------------------------------------------------------------------
# The isolation probe
# ---------------------------------------------------------------------------


def test_the_probe_runs_true_through_the_launcher_in_its_own_dirs(
    make: Factory, project: Project, root: Path
) -> None:
    """
    GIVEN both modes required
    WHEN preflight probes the sandbox
    THEN it runs the system 'true' once under that policy, in a worktree,
        scratch and empty probe dir under WORKTREE_ROOT/<run>/..., with HOME
        and TMPDIR fresh, and removes everything afterwards
    """
    run = FakeRun()

    check(make(run=run), project)

    (call,) = run.calls
    assert call.argv == (shutil.which("true", path=os.defpath),)
    assert os.path.isabs(call.argv[0])
    run_dir = call.cwd.parent
    assert run_dir.parent == root.resolve()
    assert call.policy.writable == (call.cwd, run_dir / "_scratch" / "preflight")
    assert call.policy.probe_dir == run_dir / "_probe" / "preflight"
    assert (call.policy.network, call.policy.fs, call.policy.platform) == (
        "required",
        "required",
        "linux",
    )
    assert call.probe_dir_empty
    scratch = call.policy.writable[1]
    assert call.fresh_dirs == (scratch, scratch / "home", scratch / "tmp")
    assert (call.env["HOME"], call.env["TMPDIR"]) == (
        str(scratch / "home"),
        str(scratch / "tmp"),
    )
    assert call.timeout_s == preflight.PROBE_TIMEOUT_S
    assert not run_dir.exists()
    assert list(root.iterdir()) == []


def test_no_probe_runs_when_both_modes_are_off(make: Factory, project: Project) -> None:
    run = FakeRun()

    report = check(make(run=run, network="off", fs="off"), project)

    assert run.calls == []
    assert (report.network, report.fs) == ("off", "off")


def test_the_modes_default_to_the_settings(
    make: Factory, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "NETWORK_ISOLATION", "best_effort")
    monkeypatch.setattr(settings, "FS_ISOLATION", "off")
    run = FakeRun()

    report = check(make(run=run, network=None, fs=None), project)

    assert (report.network, report.fs) == ("best_effort", "off")
    assert (run.calls[0].policy.network, run.calls[0].policy.fs) == (
        "best_effort",
        "off",
    )


def test_best_effort_isolation_not_applied_becomes_a_note(
    make: Factory, project: Project
) -> None:
    run = FakeRun(
        sample(fs_isolated=False, notes=("fs isolation was not applied (best_effort)",))
    )

    report = check(make(run=run, fs="best_effort"), project)

    assert report.notes == (
        "isolation probe: fs isolation was not applied (best_effort)",
    )


@pytest.mark.parametrize(
    ("platform", "network", "reason", "expected"),
    [
        (
            "linux",
            "required",
            "no measurement report (wrapper exit 1): unshare: unshare failed:"
            " Operation not permitted",
            ("kernel.apparmor_restrict_unprivileged_userns=0", "NETWORK_ISOLATION=off"),
        ),
        (
            "linux",
            "required",
            "launcher: fs isolation is required but applying Landlock failed:"
            " OSError: [Errno 38] Function not implemented",
            ("FS_ISOLATION=best_effort", "Landlock"),
        ),
        (
            "linux",
            "required",
            "launcher: network isolation is required but bringing up lo failed",
            ("NETWORK_ISOLATION=best_effort",),
        ),
        (
            "darwin",
            "required",
            "no measurement report (wrapper exit 65): sandbox-exec: invalid profile",
            ("sandbox-exec", "NETWORK_ISOLATION=off", "FS_ISOLATION=off"),
        ),
        (
            "darwin",
            "required",
            "launcher: fs isolation is required but self-check failed",
            ("FS_ISOLATION=best_effort",),
        ),
        (
            "linux",
            "off",
            "no measurement report (wrapper exit 1): python: not found",
            ("launcher",),
        ),
    ],
)
def test_a_failed_probe_is_refused_with_the_fix(
    make: Factory,
    project: Project,
    root: Path,
    platform: str,
    network: IsolationMode,
    reason: str,
    expected: tuple[str, ...],
) -> None:
    run = FakeRun(failure=RunFailure(reason))

    message = refused(make(run=run, platform=platform, network=network), project)

    assert reason in message
    for fix in expected:
        assert fix in message
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    ("platform", "wrapper", "expected"),
    [
        ("linux", "unshare", ("util-linux", "NETWORK_ISOLATION=off")),
        ("darwin", "sandbox-exec", ("NETWORK_ISOLATION=off", "FS_ISOLATION=off")),
    ],
)
def test_a_missing_sandbox_wrapper_names_the_install_fix(
    make: Factory,
    project: Project,
    platform: str,
    wrapper: str,
    expected: tuple[str, ...],
) -> None:
    reason = f"the sandbox wrapper {wrapper!r} is not installed in /bin:/usr/bin"
    run = FakeRun(failure=RunFailure(reason))

    message = refused(make(run=run, platform=platform), project)

    assert reason in message
    for fix in expected:
        assert fix in message
    assert "launcher could not run" not in message


def test_a_probe_whose_true_fails_is_refused(make: Factory, project: Project) -> None:
    message = refused(make(run=FakeRun(sample(exit=1))), project)

    assert "exit" in message


def test_an_unsupported_platform_is_refused_unless_isolation_is_off(
    make: Factory, project: Project
) -> None:
    message = refused(make(platform="freebsd"), project)

    assert "freebsd" in message
    assert check(make(platform="freebsd", network="off", fs="off"), project)


def test_a_worktree_root_that_cannot_be_created_is_refused(
    make: Factory, project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = write(tmp_path / "blocker", "a file, not a directory\n")
    monkeypatch.setattr(settings, "WORKTREE_ROOT", blocker / "wt")

    message = refused(make(), project)

    assert "WORKTREE_ROOT" in message
    assert str(blocker.resolve()) in message


def test_a_missing_true_is_refused(
    make: Factory, project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(preflight, "SYSTEM_PATH", str(tmp_path / "nothing"))

    assert "true" in refused(make(), project)


def _require() -> bool:
    return "1" in (
        os.environ.get("REQUIRE_NETWORK_SANDBOX"),
        os.environ.get("REQUIRE_FS_SANDBOX"),
    )


def _host_sandbox_problem() -> str | None:
    if sys.platform == "darwin":
        if shutil.which("sandbox-exec") is None:
            return "sandbox-exec is not installed"
        return None
    if sys.platform != "linux":
        return f"no sandbox on {sys.platform}"
    if shutil.which("unshare") is None:
        return "unshare is not installed"
    probe = subprocess.run(
        [*UNSHARE_ARGV, "true"], capture_output=True, timeout=30, check=False
    )
    if probe.returncode != 0:
        return f"{' '.join(UNSHARE_ARGV)} true failed: {probe.stderr!r}"
    try:
        launcher.default_ops().syscall(444, (None, 0, 1))
    except OSError as error:
        return f"Landlock is unavailable: {error}"
    return None


@pytest.fixture(scope="module")
def host_sandbox() -> None:
    """Skip (or fail under REQUIRE_*) when this host cannot sandbox."""
    problem = _host_sandbox_problem()
    if problem is not None:
        if _require():
            pytest.fail(f"sandbox required but unavailable: {problem}")
        pytest.skip(problem)


@pytest.mark.usefixtures("host_sandbox")
def test_real_probe_passes_on_a_host_that_can_sandbox(
    project: Project, root: Path
) -> None:
    """
    GIVEN both modes required on a host that can sandbox (Linux: unshare and
        Landlock; darwin: sandbox-exec)
    WHEN preflight runs the real probe through the launcher
    THEN the write and connect self-checks pass, nothing is noted, and the
        probe's run dir is gone
    """
    report = GitPreflight(network="required", fs="required").check(project, [], [])

    assert (report.network, report.fs) == ("required", "required")
    assert report.notes == ()
    assert list(root.iterdir()) == []


def test_preflight_error_is_an_engine_error() -> None:
    assert issubclass(PreflightError, EngineError)
