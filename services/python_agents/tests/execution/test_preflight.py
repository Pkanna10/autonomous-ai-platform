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
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
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
    GitWorkspace,
    repo_fingerprint,
)
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
