"""Fixtures for the Step 2 E2E scenarios (``tests/e2e/test_step2.py``).

- ``dedupe_repo``: builds the user's repository from
  ``tests/fixtures/dedupe_repo`` in ``tmp_path`` (``main`` checked out, one
  base commit, plus a branch, a tag and an unrelated ``engine/`` ref that no
  run may touch) and snapshots what the engine must leave alone.
- ``engine_settings`` (autouse): ``WORKTREE_ROOT`` in ``tmp_path`` and no
  API key, so no scenario can reach the real Claude API.
- ``isolation``: ``required`` when this host can sandbox (Linux: ``unshare``
  and Landlock; macOS: ``sandbox-exec``), else ``best_effort`` with the
  reason; ``REQUIRE_NETWORK_SANDBOX=1`` / ``REQUIRE_FS_SANDBOX=1`` (CI's
  probe) turn a missing sandbox into a failure.
- ``e2e_repository``: a ``PostgresRepository`` on a fresh database with
  ``infrastructure/schema/*.sql`` applied when ``TEST_DATABASE_URL`` is set,
  else an ``InMemoryRepository``.
- ``launches``: the real ``procrun.run_once``, recording the phase, the
  sandbox modes and the isolation the launcher reported for every launch;
  the factory passes it to everything that runs repository code.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.execution import launcher, procrun
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.sandbox import UNSHARE_ARGV, SandboxPolicy
from autonomous_ai_agents.persistence.repository import (
    InMemoryRepository,
    Repository,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEDUPE_REPO = FIXTURES / "dedupe_repo"
SCHEMA_DIR = Path(__file__).resolve().parents[4] / "infrastructure" / "schema"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
UNTOUCHED_REFS = {
    "refs/heads/feature": "HEAD",
    "refs/tags/v1": "HEAD",
    "refs/heads/engine/keep-me": "HEAD",
}
"""Pre-existing refs (one under the engine prefix) every run must leave alone."""

_GIT_ENV: dict[str, str] = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.devnull,
    "LC_ALL": "C",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_OPTIONAL_LOCKS": "0",  # our own status must not refresh the index
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "user@example.invalid",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "user@example.invalid",
    "GIT_AUTHOR_DATE": "@1700000000 +0000",
    "GIT_COMMITTER_DATE": "@1700000000 +0000",
}


def git(cwd: Path, *args: str) -> str:
    """Run git in the user's repository the way a user would; stdout stripped."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], env=_GIT_ENV, capture_output=True, check=False
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc.stdout.decode().strip()


Tree = tuple[tuple[str, int, str], ...]


def tree_digest(top: Path) -> Tree:
    """(path, lstat mode, sha256 or link target) of ``top`` and all under it.

    ``lstat`` throughout, so a file swapped for a symlink (or a new one)
    shows; a missing ``top`` is one ``missing`` entry.
    """
    if not os.path.lexists(top):
        return ((".", 0, "missing"),)
    paths = [top]
    for parent, dirs, files in os.walk(top):  # never follows a symlink
        paths.extend(Path(parent, name) for name in (*dirs, *files))
    entries: list[tuple[str, int, str]] = []
    for path in sorted(paths):
        info = os.lstat(path)
        content = ""
        if stat.S_ISLNK(info.st_mode):
            content = os.readlink(path)
        elif stat.S_ISREG(info.st_mode):
            content = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append((str(path.relative_to(top)), info.st_mode, content))
    return tuple(entries)


@dataclass(frozen=True)
class RepoSnapshot:
    """What the engine must never change in the user's repository."""

    head: str
    head_ref: str
    index_sha256: str
    status: str
    config: str
    refs: dict[str, str]
    hooks: Tree  # <common dir>/hooks: a hook runs in the user's next git command
    info: Tree  # <common dir>/info: exclude, attributes, sparse-checkout


@dataclass(frozen=True)
class UserRepo:
    path: Path
    base: str

    def refs(self) -> dict[str, str]:
        out = git(self.path, "for-each-ref", "--format=%(refname) %(objectname)")
        return dict(line.split(" ", 1) for line in out.splitlines())

    def common_dir(self) -> Path:
        common = Path(git(self.path, "rev-parse", "--git-common-dir"))
        return common if common.is_absolute() else self.path / common

    def snapshot(self) -> RepoSnapshot:
        index = (self.path / ".git" / "index").read_bytes()
        common = self.common_dir()
        return RepoSnapshot(
            head=git(self.path, "rev-parse", "HEAD"),
            head_ref=git(self.path, "symbolic-ref", "HEAD"),
            index_sha256=hashlib.sha256(index).hexdigest(),
            status=git(self.path, "status", "--porcelain", "--ignored"),
            config=git(self.path, "config", "--list", "--local"),
            refs=self.refs(),
            hooks=tree_digest(common / "hooks"),
            info=tree_digest(common / "info"),
        )

    def worktrees(self) -> list[str]:
        out = git(self.path, "worktree", "list", "--porcelain")
        return [line for line in out.splitlines() if line.startswith("worktree ")]


RepoFactory = Callable[..., UserRepo]


@pytest.fixture
def dedupe_repo(tmp_path: Path) -> RepoFactory:
    """``make(symlink=False)``: the user's dedupe repository, committed on main.

    ``symlink=True`` also commits ``dedupe/fast.py -> core.py`` (E2E-A's
    editor attack goes through it).
    """

    def make(*, symlink: bool = False) -> UserRepo:
        repo = Path(os.path.realpath(tmp_path)) / "user"
        shutil.copytree(DEDUPE_REPO, repo, ignore=shutil.ignore_patterns("__pycache__"))
        if symlink:
            (repo / "dedupe" / "fast.py").symlink_to("core.py")
        git(repo.parent, "init", "-q", "-b", "main", str(repo))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        for ref, target in UNTOUCHED_REFS.items():
            git(repo, "update-ref", ref, target)
        return UserRepo(repo, git(repo, "rev-parse", "HEAD"))

    return make


@pytest.fixture(autouse=True)
def engine_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``WORKTREE_ROOT`` beside the user's repository; never an API key."""
    root = Path(os.path.realpath(tmp_path)) / "wt-root"
    root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    return root


@dataclass(frozen=True)
class Isolation:
    mode: IsolationMode
    missing: str | None  # why the host cannot sandbox; None under required


def _sandbox_problem(platform: str) -> str | None:
    if platform == "darwin":
        return None if os.path.exists(SANDBOX_EXEC) else f"{SANDBOX_EXEC} is missing"
    if platform != "linux":
        return f"no sandbox on {platform}"
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


@pytest.fixture(scope="session")
def isolation() -> Isolation:
    problem = _sandbox_problem(sys.platform)
    if problem is None:
        return Isolation("required", None)
    required = "1" in (
        os.environ.get("REQUIRE_NETWORK_SANDBOX"),
        os.environ.get("REQUIRE_FS_SANDBOX"),
    )
    if required:
        pytest.fail(f"sandbox required but unavailable: {problem}")
    return Isolation("best_effort", problem)


@dataclass(frozen=True)
class Launch:
    phase: str  # the phase directory the run's cwd lies in
    network: str  # the sandbox modes the launch was given
    fs: str
    net_isolated: bool  # what the launcher reported it applied
    fs_isolated: bool


class LaunchLog:
    """``RunOnce``: the real ``procrun.run_once``, every launch recorded.

    The cwd of every launch must lie in ``<WORKTREE_ROOT>/<dir>/<phase>``
    (a ``ValueError`` otherwise): no engine run executes anywhere else.
    """

    def __init__(self) -> None:
        self.launches: list[Launch] = []

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
        where = Path(os.path.realpath(cwd)).relative_to(settings.WORKTREE_ROOT)
        sample = procrun.run_once(
            argv, cwd, env, sandbox, timeout_s, caps, fresh_dirs=fresh_dirs
        )
        launch = Launch(
            where.parts[1],
            sandbox.network,
            sandbox.fs,
            sample.net_isolated,
            sample.fs_isolated,
        )
        self.launches.append(launch)
        return sample

    def phases(self) -> set[str]:
        """Every phase launched in; trials collapse to ``trial-*``."""
        return {
            "trial-*" if launch.phase.startswith("trial-") else launch.phase
            for launch in self.launches
        }


@pytest.fixture
def launches() -> LaunchLog:
    return LaunchLog()


@pytest.fixture
def e2e_repository() -> Iterator[Repository]:
    """Postgres when ``TEST_DATABASE_URL`` is set (a fresh database), else memory."""
    server = os.environ.get("TEST_DATABASE_URL")
    if not server:
        yield InMemoryRepository()
        return
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    from autonomous_ai_agents.persistence.postgres import PostgresRepository

    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    name = f"aip_e2e_{worker}_{os.getpid()}"
    drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
        sql.Identifier(name)
    )
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(drop)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(server, dbname=name)
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            for path in sorted(SCHEMA_DIR.glob("*.sql")):
                conn.execute(path.read_bytes())
        yield PostgresRepository(dsn)
    finally:
        with psycopg.connect(server, autocommit=True) as admin:
            admin.execute(drop)
