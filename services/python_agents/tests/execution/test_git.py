"""GitWorkspace against real git repositories built in ``tmp_path``.

Every repository is created with the test's own git environment (global and
system config off, fixed identity and dates), so the host's git config
(this sandbox signs every commit) never leaks in and xdist workers never
share state. ``settings.WORKTREE_ROOT`` points into ``tmp_path`` for every
test that builds worktrees.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError, RepoTamperedError
from autonomous_ai_agents.execution import git as git_module
from autonomous_ai_agents.execution.git import (
    ENGINE_EMAIL,
    ENGINE_NAME,
    GitDecodeError,
    GitError,
    GitWorkspace,
    MergeResult,
    contained,
    remove_contained,
    repo_fingerprint,
)
from autonomous_ai_agents.execution.protocols import Change, WorktreeHandle

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
CORE_V1 = "def f(x):\n    return x\n"
OWN_REF = "refs/heads/engine/trial-run1-h1"


def run_git(
    cwd: Path, *args: str, stdin: bytes | None = None, env: Mapping[str, str] = _ENV
) -> bytes:
    """Run the test's own git (never the engine's) and require exit 0."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        input=stdin,
        env=dict(env),
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc.stdout


def out(cwd: Path, *args: str) -> str:
    return run_git(cwd, *args).decode().strip()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def fake_git(tmp_path: Path, body: str) -> str:
    """An executable stand-in for git that runs ``body`` under /bin/sh."""
    script = tmp_path / "fake-git"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    return str(script)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    worktree_root = (tmp_path / "wt-root").resolve()
    worktree_root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", worktree_root)
    return worktree_root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "user"
    run_git(tmp_path, "init", "-q", "-b", "main", str(path))
    write(path / "core.py", CORE_V1)
    write(path / "pkg" / "util.py", "VALUE = 1\n")
    write(path / "run.sh", "#!/bin/sh\necho run\n").chmod(0o755)
    write(path / ".gitignore", "cache/\n")
    run_git(path, "add", "-A")
    run_git(path, "commit", "-q", "-m", "base")
    return path.resolve()


@pytest.fixture
def ws(repo: Path, root: Path) -> GitWorkspace:
    return GitWorkspace(repo)


@pytest.fixture
def base(repo: Path) -> str:
    return out(repo, "rev-parse", "HEAD")


Sink = Callable[[bytes], None]


@pytest.fixture
def calls(ws: GitWorkspace, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every argv the workspace spawns, recorded after the real call."""
    recorded: list[list[str]] = []
    real = ws._spawn

    def spy(
        argv: Sequence[str],
        what: str,
        *,
        env: Mapping[str, str] | None = None,
        limit: int | None = None,
        sink: Sink | None = None,
    ) -> tuple[int, bytes, bytes]:
        recorded.append(list(argv))
        return real(argv, what, env=env, limit=limit, sink=sink)

    monkeypatch.setattr(ws, "_spawn", spy)
    return recorded


def edit_and_commit(
    ws: GitWorkspace, root: Path, base: str, name: str, path: str, text: str
) -> str:
    handle = ws.add_worktree(root / "commits" / name, base)
    write(handle.path / path, text)
    ws.stage_all(handle)
    commit = ws.commit(handle, f"{name}\n\nEngine-Trial: {name}\n", base=base)
    ws.remove_worktree(handle)
    return commit


def full_cycle(ws: GitWorkspace, root: Path, base: str) -> None:
    """Call every public method once, the way a trial and a combine would."""
    assert ws.version() >= (2, 38, 0)
    ws.common_dir()
    assert ws.head_commit() == ws.resolve_commit("HEAD")
    ws.dirty_entries()
    for path in ws.ls_tree(base):
        ws.read_blob(base, path)
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    ws.reset(handle)
    write(handle.path / "core.py", "memo\n")
    write(handle.path / "cache" / "memo.txt", "1\n")
    ws.reset(handle)
    assert (handle.path / "core.py").read_bytes() == ws.read_blob(base, "core.py")
    assert not (handle.path / "cache").exists()
    write(handle.path / "core.py", "def f(x):\n    return x + 1\n")
    ws.stage_all(handle)
    assert [c.path for c in ws.changes(handle, base)] == ["core.py"]
    assert "return x + 1" in ws.diff(handle, base)
    ws.staged_blob(handle, "core.py")
    commit = ws.commit(handle, "h1\n\nEngine-Trial: h1\n", base=base)
    ws.clean(handle)
    ws.check_link(handle)
    ws.update_ref(OWN_REF, commit, None)
    assert ws.ref_value(OWN_REF) == commit
    other = edit_and_commit(ws, root, base, "h2", "core.py", "def f(x):\n    pass\n")
    ws.merge(commit, other)
    merged = ws.merge(base, commit)
    assert merged.tree is not None
    tip = ws.commit_tree(merged.tree, base, "apply h1\n", base=base)
    assert "refs/heads/main" in ws.checked_out_branches()
    ws.update_ref("refs/heads/engine/run-run1", tip, None)
    ws.delete_ref("refs/heads/engine/run-run1", tip)
    ws.update_ref("refs/heads/bots/run-run1", tip, None, prefix="bots/")
    ws.delete_ref("refs/heads/bots/run-run1", tip, prefix="bots/")
    assert "return x + 1" in ws.diff_commits(base, commit)
    assert ws.is_ancestor(base, tip) and not ws.is_ancestor(tip, base)
    assert ws.symbolic_ref("HEAD") == "refs/heads/main"
    assert ws.commit_message(commit) == b"h1\n\nEngine-Trial: h1\n"
    assert ws.read_blob(base, "core.py", limit=4) == CORE_V1.encode()[:4]
    repo_fingerprint(ws, exclude_refs=frozenset({OWN_REF}))
    ws.remove_worktree(handle)
    ws.prune()


# --------------------------------------------------------------------------
# Construction, process handling and the environment
# --------------------------------------------------------------------------


@pytest.mark.parametrize("executable", ["", "bin/git", "./git", "g\0it"])
def test_refuses_an_executable_that_is_neither_bare_nor_absolute(
    repo: Path, executable: str
) -> None:
    with pytest.raises(ValueError, match="bare name or an absolute path"):
        GitWorkspace(repo, executable=executable)


@pytest.mark.parametrize("timeout_s", [0.0, -1.0, math.inf, math.nan])
def test_refuses_a_timeout_that_is_not_positive_and_finite(
    repo: Path, timeout_s: float
) -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        GitWorkspace(repo, timeout_s=timeout_s)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("git version 2.43.0", (2, 43, 0)),
        ("git version 2.39.5 (Apple Git-154)", (2, 39, 5)),
        ("git version 2.40.1.windows.1", (2, 40, 1)),
        ("git version 2.41", (2, 41, 0)),
    ],
)
def test_version_parses_release_strings_once(
    tmp_path: Path, line: str, expected: tuple[int, int, int]
) -> None:
    counter = tmp_path / "count"
    git = GitWorkspace(
        tmp_path, executable=fake_git(tmp_path, f"echo x >> {counter}\necho '{line}'\n")
    )
    assert git.version() == expected
    assert git.version() == expected
    assert counter.read_text() == "x\n"


def test_version_refuses_output_that_is_not_a_git_version(tmp_path: Path) -> None:
    git = GitWorkspace(tmp_path, executable=fake_git(tmp_path, "echo hello\n"))
    with pytest.raises(GitError, match="cannot parse"):
        git.version()


def test_the_real_git_is_at_least_the_floor(ws: GitWorkspace) -> None:
    assert ws.version() >= (2, 38, 0)


def test_a_missing_executable_raises_a_git_error(tmp_path: Path) -> None:
    git = GitWorkspace(tmp_path, executable=str(tmp_path / "no-such-git"))
    with pytest.raises(GitError, match="cannot run"):
        git.version()


def test_a_failure_carries_the_exit_code_and_a_capped_stderr_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "STDERR_TAIL_BYTES", 64)
    body = "i=0\nwhile [ $i -lt 500 ]; do printf noise >&2; i=$((i+1)); done\n"
    git = GitWorkspace(
        tmp_path, executable=fake_git(tmp_path, body + "echo THE-END >&2\nexit 3\n")
    )
    with pytest.raises(GitError) as caught:
        git.version()
    error = caught.value
    assert isinstance(error, EngineError)
    assert error.returncode == 3
    assert error.stderr.endswith("THE-END")
    assert len(error.stderr) <= 64
    assert error.argv[-1] == "version"
    assert "git version failed (exit 3)" in str(error)


def test_a_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    # A background child of git's keeps writing a heartbeat; once the call
    # has timed out, the heartbeat must stop because its group was killed.
    beat = tmp_path / "beat"
    body = (
        f"( i=0; while :; do i=$((i+1)); echo $i > '{beat}'; sleep 0.05; done ) &\n"
        "sleep 30\n"
    )
    git = GitWorkspace(tmp_path, executable=fake_git(tmp_path, body), timeout_s=1.0)
    started = time.monotonic()
    with pytest.raises(GitError, match="timed out after 1 s"):
        git.version()
    assert time.monotonic() - started < 10

    def heartbeat() -> str | None:
        return beat.read_text() if beat.exists() else None

    time.sleep(0.3)
    first = heartbeat()
    time.sleep(0.5)
    assert heartbeat() == first


def test_a_git_that_closes_its_pipes_and_hangs_still_times_out(
    tmp_path: Path,
) -> None:
    body = "exec >&- 2>&-\nsleep 30\n"
    git = GitWorkspace(tmp_path, executable=fake_git(tmp_path, body), timeout_s=0.5)
    started = time.monotonic()
    with pytest.raises(GitError, match="timed out after 0.5 s"):
        git.version()
    assert time.monotonic() - started < 5


def test_a_timeout_returns_even_when_a_detached_child_holds_the_pipes(
    tmp_path: Path,
) -> None:
    # The grandchild leaves git's session (so the group kill misses it) and
    # keeps stdout and stderr open for 6 s; the call must not wait for it.
    detach = "import os, time; os.setsid(); time.sleep(6)"
    body = f"'{sys.executable}' -I -S -c '{detach}' &\nsleep 30\n"
    git = GitWorkspace(tmp_path, executable=fake_git(tmp_path, body), timeout_s=1.0)
    started = time.monotonic()
    with pytest.raises(GitError, match="timed out after 1 s"):
        git.version()
    assert time.monotonic() - started < 4


def test_output_past_the_cap_kills_git_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MAX_OUTPUT_BYTES", 1 << 20)
    git = GitWorkspace(
        tmp_path, executable=fake_git(tmp_path, "exec yes 'git version 2.43.0'\n")
    )
    started = time.monotonic()
    with pytest.raises(GitError, match="printed more than 1048576 bytes"):
        git.version()
    assert time.monotonic() - started < 10


def test_a_blob_past_the_output_cap_is_refused(
    ws: GitWorkspace, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repo / "big.txt", "x" * 5000)
    run_git(repo, "add", "big.txt")
    run_git(repo, "commit", "-q", "-m", "big")
    head = ws.head_commit()
    assert ws.read_blob(head, "big.txt") == b"x" * 5000
    monkeypatch.setattr(settings, "MAX_OUTPUT_BYTES", 4096)
    with pytest.raises(GitError, match="cat-file printed more than 4096 bytes"):
        ws.read_blob(head, "big.txt")


def test_a_group_of_zombies_answering_eperm_never_hides_the_cap_error(
    ws: GitWorkspace, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a git call past its output cap, on a host whose killpg answers
          EPERM for a group whose members already exited (macOS)
    WHEN the engine kills git's process group
    THEN the cap's GitError is what the caller sees, not PermissionError
    """
    write(repo / "big.txt", "x" * 5000)
    run_git(repo, "add", "big.txt")
    run_git(repo, "commit", "-q", "-m", "big")
    head = ws.head_commit()
    killed: list[int] = []

    def macos_killpg(pgid: int, sig: int) -> None:
        killed.append(sig)
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "killpg", macos_killpg)
    monkeypatch.setattr(settings, "MAX_OUTPUT_BYTES", 4096)

    with pytest.raises(GitError, match="cat-file printed more than 4096 bytes"):
        ws.read_blob(head, "big.txt")
    assert killed == [signal.SIGKILL]


@pytest.mark.parametrize(
    ("version", "attr_source"), [("2.43.0", True), ("2.39.5", False)]
)
def test_every_call_gets_a_scratch_environment_and_the_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, attr_source: bool
) -> None:
    log = tmp_path / "calls"
    log.mkdir()
    oid = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    body = (
        f'{{ env; echo "--argv--"; for a in "$@"; do echo "$a"; done; }} > {log}/$$\n'
        'case " $* " in\n'
        f'  *" version "*) echo "git version {version}" ;;\n'
        f'  *" hash-object "*|*" rev-parse "*) echo {oid} ;;\n'
        '  *" config "*) printf "filter.a=b.clean\\0diff.x.textconv\\0'
        'protocol.ext.allow\\0" ;;\n'
        "esac\n"
    )
    monkeypatch.setenv("GIT_DIR", "/evil/git-dir")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.hooksPath'='/evil'")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-key")
    monkeypatch.setenv("PATH", os.pathsep.join([".", "rel/bin", _ENV["PATH"]]))
    git = GitWorkspace(tmp_path, executable=fake_git(tmp_path, body))
    assert git.resolve_commit("HEAD") == oid
    records = [p.read_text().split("--argv--\n") for p in log.iterdir()]
    env_text, argv_text = next(r for r in records if "rev-parse" in r[1].split())
    argv = argv_text.splitlines()
    assert any(a.startswith("--attr-source") for a in argv) is attr_source
    assert ("--attr-source=" + oid in argv) is attr_source
    pairs = {argv[i + 1] for i, a in enumerate(argv) if a == "-c"}
    for pair in (
        "core.hooksPath=/dev/null",
        "core.fsmonitor=false",
        "core.sshCommand=false",
        "commit.gpgSign=false",
        "protocol.allow=never",
        "credential.helper=",
        "diff.external=",
        "core.attributesFile=/dev/null",
        "core.excludesFile=/dev/null",
        "gc.auto=0",
        "maintenance.auto=false",
        f"user.name={ENGINE_NAME}",
        f"user.email={ENGINE_EMAIL}",
    ):
        assert pair in pairs
    assert argv[-2:] == ["--end-of-options", "HEAD^{commit}"]
    env = {k: v for k, _, v in (line.partition("=") for line in env_text.splitlines())}
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert env["LC_ALL"] == "C"
    assert env["GIT_NO_LAZY_FETCH"] == "1"
    assert env["GIT_CONFIG_COUNT"] == "3"
    assert env["GIT_CONFIG_KEY_0"] == "filter.a=b.clean"
    assert env["GIT_CONFIG_VALUE_0"] == ""
    assert env["GIT_CONFIG_KEY_1"] == "diff.x.textconv"
    assert env["GIT_CONFIG_VALUE_1"] == ""
    assert env["GIT_CONFIG_KEY_2"] == "protocol.ext.allow"
    assert env["GIT_CONFIG_VALUE_2"] == "never"
    for pair in ("core.ignoreStat=false", "core.untrackedCache=false"):
        assert pair in pairs
    assert "core.sparseCheckout=false" in pairs
    for leaked in ("GIT_DIR", "GIT_CONFIG_PARAMETERS", "ANTHROPIC_API_KEY"):
        assert leaked not in env
    assert all(os.path.isabs(entry) for entry in env["PATH"].split(os.pathsep))


# --------------------------------------------------------------------------
# Reads in the user's repository
# --------------------------------------------------------------------------


def test_common_dir_head_and_resolve_commit(
    ws: GitWorkspace, repo: Path, base: str
) -> None:
    assert ws.repo == repo
    assert ws.common_dir() == (repo / ".git").resolve()
    assert ws.head_commit() == base
    assert ws.resolve_commit("main") == base
    run_git(repo, "tag", "-a", "-m", "annotated", "v1")
    assert ws.resolve_commit("v1") == base


def test_resolve_commit_of_an_unknown_rev_raises_with_git_stderr(
    ws: GitWorkspace,
) -> None:
    with pytest.raises(GitError, match="rev-parse failed") as caught:
        ws.resolve_commit("no-such-rev")
    assert caught.value.returncode == 128
    assert caught.value.stderr


@pytest.mark.parametrize("rev", ["", "a\0b", "a\nb"])
def test_resolve_commit_refuses_a_malformed_rev(ws: GitWorkspace, rev: str) -> None:
    with pytest.raises(ValueError, match="not a revision"):
        ws.resolve_commit(rev)


def test_head_commit_refuses_output_that_is_not_an_object_id(tmp_path: Path) -> None:
    body = 'case " $* " in *" version "*) echo "git version 2.39.0";; *) echo nope;; esac\n'
    git = GitWorkspace(tmp_path, executable=fake_git(tmp_path, body))
    with pytest.raises(GitError, match="expected an object id"):
        git.head_commit()


def test_dirty_entries_lists_the_users_changes_without_rewriting_the_index(
    ws: GitWorkspace, repo: Path
) -> None:
    write(repo / "core.py", "changed\n")
    write(repo / "staged.txt", "s\n")
    run_git(repo, "add", "staged.txt")
    write(repo / "untracked.txt", "u\n")
    os.utime(repo / "pkg" / "util.py", (1_000_000, 1_000_000))
    index = repo / ".git" / "index"
    before = index.read_bytes()
    assert set(ws.dirty_entries()) == {
        " M core.py",
        "A  staged.txt",
        "?? untracked.txt",
    }
    assert index.read_bytes() == before
    # Control: a plain status (optional locks on) does rewrite it.
    plain = {k: v for k, v in _ENV.items() if k != "GIT_OPTIONAL_LOCKS"}
    run_git(repo, "status", "--porcelain", env=plain)
    assert index.read_bytes() != before


def test_ls_tree_lists_blob_paths_and_read_blob_returns_their_bytes(
    ws: GitWorkspace, repo: Path, base: str
) -> None:
    write(repo / "deep" / "a" / "b.txt", "deep\n")
    os.symlink("core.py", repo / "alias.py")
    run_git(repo, "add", "-A")
    run_git(repo, "update-index", "--add", "--cacheinfo", f"160000,{base},vendored")
    run_git(repo, "commit", "-q", "-m", "more")
    head = out(repo, "rev-parse", "HEAD")
    assert sorted(ws.ls_tree(head)) == [
        ".gitignore",
        "alias.py",
        "core.py",
        "deep/a/b.txt",
        "pkg/util.py",
        "run.sh",
    ]
    assert ws.read_blob(head, "alias.py") == b"core.py"
    assert ws.read_blob(head, "deep/a/b.txt") == b"deep\n"
    assert ws.read_blob(base, "core.py") == CORE_V1.encode()


def test_blob_modes_reports_each_blob_entrys_mode(
    ws: GitWorkspace, repo: Path, base: str
) -> None:
    write(repo / "deep" / "tool.sh", "echo\n")
    (repo / "deep" / "tool.sh").chmod(0o755)
    os.symlink("core.py", repo / "alias.py")
    run_git(repo, "add", "-A")
    run_git(repo, "update-index", "--add", "--cacheinfo", f"160000,{base},vendored")
    run_git(repo, "commit", "-q", "-m", "modes")
    modes = ws.blob_modes(out(repo, "rev-parse", "HEAD"))
    assert set(modes) == set(ws.ls_tree(out(repo, "rev-parse", "HEAD")))
    assert (modes["core.py"], modes["deep/tool.sh"]) == ("100644", "100755")
    assert modes["alias.py"] == "120000" and "vendored" not in modes


@pytest.mark.skipif(sys.platform == "darwin", reason="APFS refuses non-UTF-8 names")
def test_a_non_utf8_file_name_round_trips(ws: GitWorkspace, repo: Path) -> None:
    name = os.fsdecode(b"caf\xe9.txt")
    (repo / name).write_bytes(b"latin\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "latin-1 name")
    head = out(repo, "rev-parse", "HEAD")
    assert name in ws.ls_tree(head)
    assert ws.read_blob(head, name) == b"latin\n"


@pytest.mark.parametrize(
    "path", ["", "/etc/passwd", "a/../b", "./core.py", "a//b", "a\0b"]
)
def test_read_blob_refuses_a_path_git_cannot_name(
    ws: GitWorkspace, base: str, path: str
) -> None:
    with pytest.raises(ValueError, match="repo-relative git path"):
        ws.read_blob(base, path)


@pytest.mark.parametrize("commit", ["HEAD", "main", "abc123", "A" * 40, "-" + "0" * 39])
def test_object_id_arguments_must_be_full_hex_ids(
    ws: GitWorkspace, commit: str
) -> None:
    with pytest.raises(ValueError, match="full object id"):
        ws.read_blob(commit, "core.py")
    with pytest.raises(ValueError, match="full object id"):
        ws.ls_tree(commit)


def test_read_blob_of_a_missing_path_or_a_tree_raises(
    ws: GitWorkspace, base: str
) -> None:
    with pytest.raises(GitError, match="cat-file failed"):
        ws.read_blob(base, "missing.py")
    with pytest.raises(GitError, match="cat-file failed"):
        ws.read_blob(base, "pkg")


# --------------------------------------------------------------------------
# Worktrees and their handles
# --------------------------------------------------------------------------


def test_add_worktree_checks_out_the_commit_and_records_a_valid_handle(
    ws: GitWorkspace, root: Path, base: str
) -> None:
    handle = ws.add_worktree(root / "run1" / "baseline", base)
    assert handle.path == root / "run1" / "baseline"
    assert handle.gitdir == ws.common_dir() / "worktrees" / "baseline"
    assert handle.link_bytes == (handle.path / ".git").read_bytes()
    assert handle.link_bytes == f"gitdir: {handle.gitdir}\n".encode()
    assert (handle.path / "core.py").read_text() == CORE_V1
    assert os.access(handle.path / "run.sh", os.X_OK)
    assert out(handle.path, "rev-parse", "HEAD") == base
    ws.check_link(handle)


def test_add_worktree_refuses_paths_outside_the_worktree_root(
    ws: GitWorkspace, root: Path, tmp_path: Path, base: str
) -> None:
    (tmp_path / "outside").mkdir()
    os.symlink(tmp_path / "outside", root / "escape")
    for path in (
        tmp_path / "elsewhere",
        root,
        root / "run1" / "..",
        Path("relative/wt"),
        root / "escape" / "wt",
        Path("/"),
    ):
        with pytest.raises(ValueError, match="WORKTREE_ROOT"):
            ws.add_worktree(path, base)
    assert not (tmp_path / "outside" / "wt").exists()


def test_add_worktree_replaces_whatever_is_at_the_path(
    ws: GitWorkspace, repo: Path, root: Path, base: str
) -> None:
    path = root / "run1" / "trial-h1"
    first = ws.add_worktree(path, base)
    write(first.path / "core.py", "changed\n")
    ws.stage_all(first)
    ws.commit(first, "c\n", base=base)
    write(first.path / "junk.txt", "junk\n")
    second = ws.add_worktree(path, base)
    assert out(second.path, "rev-parse", "HEAD") == base
    assert not (second.path / "junk.txt").exists()
    assert (second.path / "core.py").read_text() == CORE_V1
    shutil.rmtree(path)  # registered but missing
    third = ws.add_worktree(path, base)
    assert third.gitdir.name == "trial-h1"
    shutil.rmtree(path)
    write(path / "stray.txt", "a plain directory\n")
    ws.add_worktree(path, base)
    listing = out(repo, "worktree", "list", "--porcelain")
    assert listing.count("worktree ") == 2
    assert not (path / "stray.txt").exists()


def test_a_name_collision_gets_its_own_admin_dir_and_every_call_uses_it(
    ws: GitWorkspace, repo: Path, root: Path, base: str, calls: list[list[str]]
) -> None:
    first = ws.add_worktree(root / "run1" / "baseline", base)
    second = ws.add_worktree(root / "run2" / "baseline", base)
    assert first.gitdir.name == "baseline"
    assert second.gitdir.name == "baseline1"
    # Point second's .git at first's admin dir: only the handle may decide
    # which admin dir (index, HEAD) a call on ``second`` reads and writes.
    (second.path / ".git").write_bytes(first.link_bytes)
    calls.clear()
    write(second.path / "core.py", "changed\n")
    write(second.path / "cache" / "x.txt", "x\n")
    ws.stage_all(second)
    assert [c.path for c in ws.changes(second, base)] == ["core.py"]
    assert "+changed" in ws.diff(second, base)
    assert ws.staged_blob(second, "core.py") == b"changed\n"
    commit = ws.commit(second, "c\n", base=base)
    ws.clean(second)
    assert ws.changes(second, commit) == ()
    made = list(calls)
    assert not (second.path / "cache").exists()
    assert (second.gitdir / "HEAD").read_text().strip() == commit
    assert (first.gitdir / "HEAD").read_text().strip() == base
    assert out(first.path, "status", "--porcelain") == ""
    assert ws.changes(first, base) == ()
    contexts = [argv[argv.index("-C") + 1] for argv in made]
    assert contexts.count(str(second.path)) >= 16  # each call lists its keys
    for argv, context in zip(made, contexts, strict=True):
        assert f"--git-dir={first.gitdir}" not in argv
        if context == str(second.path):
            assert f"--git-dir={second.gitdir}" in argv
            assert f"--work-tree={second.path}" in argv
        else:
            assert context == str(repo)


def _forge_outside(handle: Path, common: Path, tmp_path: Path) -> None:
    (tmp_path / "evil").mkdir()
    (handle / ".git").write_text(f"gitdir: {tmp_path / 'evil'}\n")


def _forge_nested(handle: Path, common: Path, tmp_path: Path) -> None:
    nested = common / "worktrees" / "trial-h1" / "nested"
    nested.mkdir()
    (handle / ".git").write_text(f"gitdir: {nested}\n")


def _forge_other_admin_dir(handle: Path, common: Path, tmp_path: Path) -> None:
    (handle / ".git").write_text(f"gitdir: {common / 'worktrees' / 'other'}\n")


def _forge_symlink(handle: Path, common: Path, tmp_path: Path) -> None:
    copy = tmp_path / "link-copy"
    copy.write_bytes((handle / ".git").read_bytes())
    (handle / ".git").unlink()
    os.symlink(copy, handle / ".git")


def _forge_garbage(handle: Path, common: Path, tmp_path: Path) -> None:
    (handle / ".git").write_bytes(b"not a gitdir line")


def _forge_nul(handle: Path, common: Path, tmp_path: Path) -> None:
    (handle / ".git").write_bytes(b"gitdir: /tmp/a\0b\n")


@pytest.mark.parametrize(
    "forge",
    [
        _forge_outside,
        _forge_nested,
        _forge_other_admin_dir,
        _forge_symlink,
        _forge_garbage,
        _forge_nul,
    ],
)
def test_a_forged_gitdir_link_is_refused_and_the_worktree_removed(
    ws: GitWorkspace,
    repo: Path,
    root: Path,
    tmp_path: Path,
    base: str,
    monkeypatch: pytest.MonkeyPatch,
    forge: Callable[[Path, Path, Path], None],
) -> None:
    other = ws.add_worktree(root / "run0" / "other", base)
    target = root / "run1" / "trial-h1"
    real = ws._spawn

    def forging_spawn(
        argv: Sequence[str],
        what: str,
        *,
        env: Mapping[str, str] | None = None,
        limit: int | None = None,
        sink: Sink | None = None,
    ) -> tuple[int, bytes, bytes]:
        result = real(argv, what, env=env, limit=limit, sink=sink)
        if "add" in argv and str(target) in argv:
            forge(target, ws.common_dir(), tmp_path)
        return result

    monkeypatch.setattr(ws, "_spawn", forging_spawn)
    with pytest.raises(RepoTamperedError, match="does not name an admin directory"):
        ws.add_worktree(target, base)
    assert not os.path.lexists(target)
    listing = out(repo, "worktree", "list", "--porcelain")
    assert str(target) not in listing
    assert str(other.path) in listing
    ws.check_link(other)
    assert out(other.path, "rev-parse", "HEAD") == base


def _relink(path: Path, tmp_path: Path) -> None:
    path.write_text(f"gitdir: {tmp_path}\n")


def _append(path: Path, tmp_path: Path) -> None:
    path.write_bytes(path.read_bytes() + b" ")


def _symlink(path: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    copy.write_bytes(path.read_bytes())
    path.unlink()
    os.symlink(copy, path)


def _directory(path: Path, tmp_path: Path) -> None:
    path.unlink()
    path.mkdir()


def _fifo(path: Path, tmp_path: Path) -> None:
    path.unlink()
    os.mkfifo(path)


def _delete(path: Path, tmp_path: Path) -> None:
    path.unlink()


@pytest.mark.parametrize(
    "rewrite", [_relink, _append, _symlink, _directory, _fifo, _delete]
)
def test_a_rewritten_git_link_is_detected(
    ws: GitWorkspace,
    root: Path,
    tmp_path: Path,
    base: str,
    rewrite: Callable[[Path, Path], None],
) -> None:
    handle = ws.add_worktree(root / "run1" / "baseline", base)
    rewrite(handle.path / ".git", tmp_path)
    with pytest.raises(RepoTamperedError, match="changed after the worktree"):
        ws.check_link(handle)
    with pytest.raises(RepoTamperedError):
        ws.reset(handle)
    ws.remove_worktree(handle)
    assert not os.path.lexists(handle.path)


def test_remove_worktree_by_handle_or_path(
    ws: GitWorkspace, repo: Path, root: Path, tmp_path: Path, base: str
) -> None:
    handle = ws.add_worktree(root / "run1" / "baseline", base)
    ws.remove_worktree(handle)
    assert not handle.path.exists()
    assert not handle.gitdir.exists()
    ws.remove_worktree(root / "run1" / "never-existed")
    outside = tmp_path / "outside"
    write(outside / "keep.txt", "keep\n")
    scratch = root / "run1" / "_scratch" / "baseline"
    write(scratch / "locked" / "file.txt", "x\n")
    os.symlink(outside, scratch / "to-outside")
    (scratch / "locked").chmod(0)
    ws.remove_worktree(scratch)
    assert not scratch.exists()
    os.symlink(outside, root / "run1" / "linked")
    ws.remove_worktree(root / "run1" / "linked")
    assert not os.path.lexists(root / "run1" / "linked")
    write(root / "run1" / "afile", "x\n")
    ws.remove_worktree(root / "run1" / "afile")
    assert not os.path.lexists(root / "run1" / "afile")
    assert (outside / "keep.txt").read_text() == "keep\n"
    with pytest.raises(ValueError, match="WORKTREE_ROOT"):
        ws.remove_worktree(outside)
    assert outside.exists()
    assert out(repo, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_remove_worktree_with_a_rewritten_link_still_cleans_up(
    ws: GitWorkspace, repo: Path, root: Path, tmp_path: Path, base: str
) -> None:
    other = ws.add_worktree(root / "run0" / "other", base)
    handle = ws.add_worktree(root / "run1" / "baseline", base)
    (handle.path / ".git").write_bytes(other.link_bytes)
    ws.remove_worktree(handle)
    assert not handle.path.exists()
    assert not handle.gitdir.exists()
    ws.check_link(other)
    listing = out(repo, "worktree", "list", "--porcelain")
    assert str(other.path) in listing
    assert str(handle.path) not in listing


def test_prune_only_drops_stale_registrations_under_the_root(
    ws: GitWorkspace, repo: Path, root: Path, tmp_path: Path, base: str
) -> None:
    user_wt = (tmp_path / "user-wt").resolve()
    run_git(repo, "worktree", "add", "-q", "--detach", str(user_wt), base)
    shutil.rmtree(user_wt)  # e.g. on an unmounted drive: not ours to prune
    stale = ws.add_worktree(root / "run1" / "trial-h1", base)
    live = ws.add_worktree(root / "run1" / "trial-h2", base)
    shutil.rmtree(stale.path)
    ws.prune()
    listing = out(repo, "worktree", "list", "--porcelain")
    assert str(user_wt) in listing
    assert str(live.path) in listing
    assert str(stale.path) not in listing
    assert not stale.gitdir.exists()


def test_prune_drops_admin_dirs_an_interrupted_add_left_behind(
    ws: GitWorkspace, repo: Path, root: Path, tmp_path: Path, base: str
) -> None:
    user_wt = (tmp_path / "user-wt").resolve()
    run_git(repo, "worktree", "add", "-q", "--detach", str(user_wt), base)
    shutil.rmtree(user_wt)  # its index stays in the admin dir: kept
    admin = ws.common_dir() / "worktrees"
    (admin / "half").mkdir()  # killed before gitdir was written
    write(admin / "empty" / "gitdir", "")
    write(admin / "initializing" / "locked", "initializing\n")
    ws.prune()
    assert sorted(p.name for p in admin.iterdir()) == ["initializing", "user-wt"]
    assert str(user_wt) in out(repo, "worktree", "list", "--porcelain")


def test_checked_out_branches_covers_every_worktree(
    ws: GitWorkspace, repo: Path, root: Path, tmp_path: Path, base: str
) -> None:
    run_git(repo, "worktree", "add", "-q", "-b", "feature", str(tmp_path / "feat"))
    ws.add_worktree(root / "run1" / "baseline", base)
    assert ws.checked_out_branches() == frozenset(
        {"refs/heads/main", "refs/heads/feature"}
    )


# --------------------------------------------------------------------------
# Capture: staging, changes, diff, blobs, commit, clean, reset
# --------------------------------------------------------------------------


def test_changes_report_every_kind_of_edit_and_skip_ignored_files(
    ws: GitWorkspace, root: Path, base: str
) -> None:
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    wt = handle.path
    write(wt / "core.py", "def f(x):\n    return x + 1\n")
    os.rename(wt / "pkg" / "util.py", wt / "pkg" / "helpers.py")
    (wt / "run.sh").chmod(0o644)
    os.symlink("/etc/passwd", wt / "leak")
    (wt / "table.bin").write_bytes(b"\x00\x01\x02 binary")
    write(wt / "cache" / "answer.txt", "42\n")
    ws.stage_all(handle)
    found = {c.path: c for c in ws.changes(handle, base)}
    assert found == {
        "core.py": Change("M", "100644", "100644", "core.py"),
        "pkg/util.py": Change("D", "100644", "000000", "pkg/util.py"),
        "pkg/helpers.py": Change("A", "000000", "100644", "pkg/helpers.py"),
        "run.sh": Change("M", "100755", "100644", "run.sh"),
        "leak": Change("A", "000000", "120000", "leak"),
        "table.bin": Change("A", "000000", "100644", "table.bin"),
    }
    assert ws.staged_blob(handle, "leak") == b"/etc/passwd"
    assert ws.staged_blob(handle, "table.bin") == b"\x00\x01\x02 binary"
    assert ws.staged_blob(handle, "pkg/helpers.py") == b"VALUE = 1\n"
    with pytest.raises(GitError):
        ws.staged_blob(handle, "pkg/util.py")
    ws.commit(handle, "trial\n", base=base)
    assert (wt / "cache" / "answer.txt").exists()
    ws.clean(handle)
    assert not (wt / "cache").exists()
    assert (wt / "leak").is_symlink()


def test_a_file_replaced_by_a_symlink_is_a_type_change(
    ws: GitWorkspace, root: Path, base: str
) -> None:
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    (handle.path / "core.py").unlink()
    os.symlink("pkg/util.py", handle.path / "core.py")
    ws.stage_all(handle)
    assert ws.changes(handle, base) == (Change("T", "100644", "120000", "core.py"),)


def test_changes_wraps_output_it_cannot_parse(
    ws: GitWorkspace, tmp_path: Path, base: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = WorktreeHandle(path=tmp_path, gitdir=tmp_path, link_bytes=b"")

    def garbage(*args: object, **kwargs: object) -> tuple[int, bytes]:
        return 0, b":100644 100644 a b U\0path\0"

    monkeypatch.setattr(ws, "_git", garbage)
    with pytest.raises(GitError, match="unexpected diff --raw output"):
        ws.changes(handle, base)


def test_diff_is_binary_safe_and_truncated_on_a_character_boundary(
    ws: GitWorkspace, root: Path, base: str
) -> None:
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    write(handle.path / "core.py", "def f(x):\n    return 'ééééé'\n")
    (handle.path / "blob.bin").write_bytes(bytes(range(256)) * 4)
    ws.stage_all(handle)
    full = ws.diff(handle, base)
    assert "diff --git a/core.py b/core.py" in full
    assert "Binary files /dev/null and b/blob.bin differ" in full
    raw = full.encode()
    cut_at = raw.index("é".encode()) + 1  # inside the two-byte character
    cut = ws.diff(handle, base, max_bytes=cut_at)
    head = raw[: cut_at - 1].decode()
    assert cut == f"{head}\n[diff truncated: {cut_at} of {len(raw)} bytes shown]\n"
    assert ws.diff(handle, base, max_bytes=len(raw)) == full
    with pytest.raises(ValueError, match="max_bytes"):
        ws.diff(handle, base, max_bytes=0)


def test_deleting_a_large_binary_never_puts_its_payload_in_the_diff(
    ws: GitWorkspace, repo: Path, root: Path
) -> None:
    (repo / "weights.bin").write_bytes(b"\0" + os.urandom(2 * 1024 * 1024))
    run_git(repo, "add", "weights.bin")
    run_git(repo, "commit", "-q", "-m", "weights")
    base = ws.head_commit()
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    (handle.path / "weights.bin").unlink()
    ws.stage_all(handle)
    text = ws.diff(handle, base)
    assert "Binary files a/weights.bin and /dev/null differ" in text
    assert len(text) < 1024


def test_a_large_diff_is_streamed_never_held_whole(
    ws: GitWorkspace, root: Path, base: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    write(handle.path / "big.py", "x = 1  # é\n" * 20_000)
    ws.stage_all(handle)
    # Any call that held more than 4 KiB of output would raise: the diff
    # keeps its first 1000 bytes, validates the rest as it streams past.
    monkeypatch.setattr(settings, "MAX_OUTPUT_BYTES", 4096)
    text = ws.diff(handle, base, max_bytes=1000)
    head, _, marker = text.rpartition("\n[diff truncated: ")
    assert head.startswith("diff --git a/big.py b/big.py")
    assert len(head.encode()) <= 1000
    shown, _, total = marker.removesuffix(" bytes shown]\n").partition(" of ")
    assert shown == "1000"
    assert int(total) > 20_000 * 12
    (handle.path / "latin.py").write_bytes(b"x = 1\n" * 1000 + b"caf\xe9\n")
    ws.stage_all(handle)
    with pytest.raises(GitDecodeError, match="not UTF-8"):
        ws.diff(handle, base, max_bytes=1000)


def test_a_diff_that_is_not_utf8_raises_a_decode_error(
    ws: GitWorkspace, root: Path, base: str
) -> None:
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    (handle.path / "core.py").write_bytes(b"name = 'caf\xe9'\n")
    ws.stage_all(handle)
    assert [c.path for c in ws.changes(handle, base)] == ["core.py"]
    with pytest.raises(GitDecodeError, match="not UTF-8") as caught:
        ws.diff(handle, base)
    assert isinstance(caught.value, GitError)


def test_commit_is_reproducible_with_the_engine_identity_and_base_dates(
    ws: GitWorkspace, repo: Path, root: Path, base: str
) -> None:
    message = "Apply h1\n\n# kept verbatim\nEngine-Trial: 0b8f\n"
    commits = []
    for run in ("run1", "run2"):
        handle = ws.add_worktree(root / run / "trial-h1", base)
        write(handle.path / "core.py", "v2\n")
        ws.stage_all(handle)
        commits.append(ws.commit(handle, message, base=base))
        assert out(handle.path, "rev-parse", "HEAD") == commits[-1]
        assert ws.changes(handle, commits[-1]) == ()
    assert commits[0] == commits[1]
    raw = run_git(repo, "cat-file", "commit", commits[0]).decode()
    header, body = raw.split("\n\n", 1)
    assert body == message
    lines = header.splitlines()
    assert f"parent {base}" in lines
    assert f"author {ENGINE_NAME} <{ENGINE_EMAIL}> 1700000000 +0100" in lines
    assert f"committer {ENGINE_NAME} <{ENGINE_EMAIL}> 1700003600 -0500" in lines
    assert not any(line.startswith("gpgsig") for line in lines)


def test_commit_with_a_parent_is_a_child_of_it_and_moves_head_from_the_last(
    ws: GitWorkspace, root: Path, base: str
) -> None:
    """D15: a retried trial's second commit sits on the base, not on commit 1."""
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    write(handle.path / "core.py", "v2\n")
    ws.stage_all(handle)
    first = ws.commit(handle, "one\n", base=base)
    write(handle.path / "core.py", "v3\n")
    ws.stage_all(handle)
    second = ws.commit(handle, "two\n", base=base, parent=base)
    assert out(handle.path, "rev-parse", "HEAD") == second != first
    parents = out(handle.path, "rev-list", "--parents", "-n", "1", second)
    assert parents.split() == [second, base]
    with pytest.raises(ValueError, match="full object id"):
        ws.commit(handle, "m", base=base, parent="HEAD")


def test_commit_refuses_a_nul_in_the_message_or_a_bad_base(
    ws: GitWorkspace, root: Path, base: str
) -> None:
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    with pytest.raises(ValueError, match="NUL"):
        ws.commit(handle, "a\0b", base=base)
    with pytest.raises(ValueError, match="longer than 65536 bytes"):
        ws.commit(handle, "é" * 32_769, base=base)
    with pytest.raises(UnicodeEncodeError):
        ws.commit_tree(base, base, "lone \udce9 surrogate", base=base)
    tree = out(handle.path, "rev-parse", "HEAD^{tree}")
    dash = ws.commit_tree(tree, base, "-m starts like an option\n", base=base)
    raw = run_git(ws.repo, "cat-file", "commit", dash).decode()
    assert raw.split("\n\n", 1)[1] == "-m starts like an option\n"
    with pytest.raises(ValueError, match="full object id"):
        ws.commit(handle, "m", base="HEAD")


def test_a_base_without_parseable_dates_raises(
    ws: GitWorkspace, repo: Path, base: str
) -> None:
    tree = out(repo, "rev-parse", "HEAD^{tree}")
    broken = (
        run_git(
            repo,
            "hash-object",
            "-t",
            "commit",
            "-w",
            "--literally",
            "--stdin",
            stdin=f"tree {tree}\nauthor a <a> soon\ncommitter c <c> later\n\nm\n".encode(),
        )
        .decode()
        .strip()
    )
    with pytest.raises(GitError, match="dates"):
        ws.commit_tree(tree, base, "m\n", base=broken)


def test_reset_always_checks_out_and_cleans_and_restores_a_dirty_tree(
    ws: GitWorkspace, root: Path, base: str, calls: list[list[str]]
) -> None:
    handle = ws.add_worktree(root / "run1" / "baseline", base)
    calls.clear()
    ws.reset(handle)  # a clean status proves nothing: see the hidden channels
    assert any("checkout" in argv for argv in calls)
    assert any("clean" in argv for argv in calls)
    wt = handle.path
    write(wt / "core.py", "memoised\n")
    (wt / "pkg" / "util.py").unlink()
    write(wt / "cache" / "memo.json", "{}\n")
    write(wt / "new.txt", "new\n")
    (wt / "run.sh").chmod(0o644)
    ws.reset(handle)
    assert any("checkout" in argv for argv in calls)
    assert (wt / "core.py").read_text() == CORE_V1
    assert (wt / "pkg" / "util.py").exists()
    assert not (wt / "cache").exists()
    assert not (wt / "new.txt").exists()
    assert os.access(wt / "run.sh", os.X_OK)
    assert out(wt, "status", "--porcelain", "--ignored") == ""


def _entries(top: Path) -> list[str]:
    found = []
    for directory, dirs, files in os.walk(top):
        for name in [*dirs, *files]:
            found.append(os.path.relpath(os.path.join(directory, name), top))
    return sorted(found)


def test_reset_removes_what_status_and_clean_cannot_see(
    ws: GitWorkspace,
    repo: Path,
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write(repo / "lib" / "a.py", "A = 1\n")
    write(repo / "docs" / "b.md", "b\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "more dirs")
    handle = ws.add_worktree(root / "run1" / "baseline", ws.head_commit())
    wt = handle.path
    expected = _entries(wt)
    mode = (wt / "core.py").stat().st_mode
    outside = tmp_path / "outside"
    write(outside / "keep.txt", "keep\n")
    # Each of these survives `status --ignored` plus `clean -ffdx`, so a
    # warm-up run could hand state to the timed runs through it.
    os.utime(wt / "core.py", (1_234_567, 1_234_567))  # a tracked file's stat
    (wt / "core.py").chmod(0o600)
    (wt / "memo-answer-42").mkdir()  # an empty directory's name
    (wt / "pkg" / "memo-43").mkdir()
    write(wt / "pkg" / ".git" / "memo.json", "{}\n")  # git never lists a .git
    write(wt / "docs" / ".Git", "gitdir: /nowhere\n")
    os.symlink(outside, wt / "lib" / ".git")  # removed, never followed
    os.mkfifo(wt / "fifo-44")  # git never tracks a FIFO or a socket
    with monkeypatch.context() as cwd:
        cwd.chdir(wt / "pkg")  # macOS caps AF_UNIX paths at 104 bytes
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind("sock-45")
    write(wt / "hidden" / "memo.txt", "42\n")
    (wt / "hidden").chmod(0)  # unreadable: invisible to status and clean
    (wt / "lib").chmod(0)  # a tracked directory git cannot enter
    ws.reset(handle)
    assert _entries(wt) == expected
    assert (wt / "core.py").stat().st_mode == mode
    assert int((wt / "core.py").stat().st_mtime) != 1_234_567
    assert (wt / "lib").stat().st_mode & stat.S_IRWXU == stat.S_IRWXU
    assert sorted(os.listdir(outside)) == ["keep.txt"]
    ws.check_link(handle)


@pytest.mark.skipif(sys.platform == "darwin", reason="'.GIT' is '.git' on APFS")
def test_reset_removes_a_case_variant_of_git_at_the_top(
    ws: GitWorkspace, root: Path, base: str
) -> None:
    handle = ws.add_worktree(root / "run1" / "baseline", base)
    write(handle.path / ".GIT" / "memo", "42\n")
    ws.reset(handle)
    assert not os.path.lexists(handle.path / ".GIT")
    ws.check_link(handle)


class _Listed:
    """A finished ``os.scandir`` listing, iterated after the tree changed."""

    def __init__(self, entries: list[os.DirEntry[str]]) -> None:
        self._entries = entries

    def __enter__(self) -> list[os.DirEntry[str]]:
        return self._entries

    def __exit__(self, *exc: object) -> None:
        return None


def test_reset_never_follows_a_directory_swapped_for_a_link_mid_walk(
    ws: GitWorkspace,
    root: Path,
    base: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN a process that outlived its run (macOS has no PID namespace)
        swaps an untracked directory of the worktree for a link to a
        directory outside it, right after the scrub listed the top
    WHEN the engine resets the worktree
    THEN the reset refuses, and the outside directory keeps its mode, its
        .git and its FIFO: the scrub never walks through the link
    """
    handle = ws.add_worktree(root / "run1" / "baseline", base)
    write(handle.path / "swap" / "deep" / "memo.txt", "1\n")
    outside = tmp_path / "outside"
    write(outside / ".git" / "HEAD", "ref: refs/heads/main\n")
    os.mkfifo(outside / "agent.sock")
    outside.chmod(0o750)
    top = os.stat(handle.path)
    real = os.scandir
    armed = [True]

    def racing(target: Any = ".") -> Any:
        listing = real(target)
        if not armed[0] or not os.path.samestat(os.stat(target), top):
            return listing
        armed[0] = False
        with listing as entries:
            seen = list(entries)
        shutil.rmtree(handle.path / "swap")
        os.symlink(outside, handle.path / "swap")
        return _Listed(seen)

    monkeypatch.setattr(os, "scandir", racing)

    with pytest.raises(RepoTamperedError, match="swap"):
        ws.reset(handle)

    monkeypatch.undo()
    assert stat.S_IMODE(outside.stat().st_mode) == 0o750
    assert (outside / ".git" / "HEAD").is_file()
    assert stat.S_ISFIFO((outside / "agent.sock").lstat().st_mode)


def _ignore_stat(repo: Path) -> None:
    run_git(repo, "config", "core.ignoreStat", "true")


def _sparse_checkout(repo: Path) -> None:
    run_git(repo, "sparse-checkout", "set", "--no-cone", "/pkg/")


def _untracked_cache(repo: Path) -> None:
    run_git(repo, "config", "core.untrackedCache", "true")


@pytest.mark.parametrize(
    "configure", [_ignore_stat, _sparse_checkout, _untracked_cache]
)
def test_a_config_that_hides_edits_cannot_blind_capture_or_reset(
    ws: GitWorkspace,
    repo: Path,
    root: Path,
    base: str,
    configure: Callable[[Path], None],
) -> None:
    configure(repo)
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    wt = handle.path
    for path in ws.ls_tree(base):
        assert (wt / path).read_bytes() == ws.read_blob(base, path)
    write(wt / "core.py", "def f(x):\n    return x + 1\n")
    write(wt / "new.py", "N = 1\n")
    ws.stage_all(handle)
    assert sorted(c.path for c in ws.changes(handle, base)) == ["core.py", "new.py"]
    write(wt / "core.py", "memo\n")
    ws.reset(handle)
    assert (wt / "core.py").read_text() == CORE_V1
    assert not (wt / "new.py").exists()


def test_reset_raises_when_the_tree_stays_dirty(
    ws: GitWorkspace, root: Path, base: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = ws.add_worktree(root / "run1" / "baseline", base)
    write(handle.path / "stuck.txt", "x\n")
    monkeypatch.setattr(ws, "clean", lambda handle: None)
    with pytest.raises(GitError, match="still dirty"):
        ws.reset(handle)


# --------------------------------------------------------------------------
# Combine: merge-tree and commit-tree
# --------------------------------------------------------------------------


def test_merge_applies_independent_changes_in_a_linear_history_and_skips_conflicts(
    ws: GitWorkspace, repo: Path, root: Path, base: str
) -> None:
    a = edit_and_commit(ws, root, base, "a", "core.py", "def f(x):\n    return 2 * x\n")
    b = edit_and_commit(ws, root, base, "b", "pkg/util.py", "VALUE = 2\n")
    c = edit_and_commit(ws, root, base, "c", "core.py", "def f(x):\n    return 3 * x\n")
    first = ws.merge(base, a)
    assert first.conflicts == ()
    assert first.tree is not None
    acc1 = ws.commit_tree(first.tree, base, "apply a\n\nEngine-Trial: a\n", base=base)
    second = ws.merge(acc1, b)
    assert second.tree is not None
    acc2 = ws.commit_tree(second.tree, acc1, "apply b\n\nEngine-Trial: b\n", base=base)
    assert ws.merge(acc2, c) == MergeResult(tree=None, conflicts=("core.py",))
    assert out(repo, "rev-list", "--parents", f"{base}..{acc2}").splitlines() == [
        f"{acc2} {acc1}",
        f"{acc1} {base}",
    ]
    assert ws.read_blob(acc2, "core.py") == b"def f(x):\n    return 2 * x\n"
    assert ws.read_blob(acc2, "pkg/util.py") == b"VALUE = 2\n"
    assert out(repo, "status", "--porcelain") == ""


def test_merge_of_unrelated_histories_raises(
    ws: GitWorkspace, repo: Path, base: str
) -> None:
    tree = out(repo, "rev-parse", "HEAD^{tree}")
    orphan = out(repo, "commit-tree", tree, "-m", "orphan")
    with pytest.raises(GitError, match="merge-tree failed"):
        ws.merge(base, orphan)
    with pytest.raises(ValueError, match="full object id"):
        ws.merge(base, "main")


# --------------------------------------------------------------------------
# Refs
# --------------------------------------------------------------------------


def test_update_ref_is_create_only_with_no_old_value(
    ws: GitWorkspace, root: Path, base: str
) -> None:
    other = edit_and_commit(ws, root, base, "a", "core.py", "a\n")
    ref = "refs/heads/engine/run-r1"
    assert ws.ref_value(ref) is None
    ws.update_ref(ref, base, None)
    assert ws.ref_value(ref) == base
    with pytest.raises(GitError, match="update-ref failed"):
        ws.update_ref(ref, other, None)
    with pytest.raises(GitError, match="update-ref failed"):
        ws.update_ref(ref, other, other)  # wrong expected old value
    assert ws.ref_value(ref) == base
    ws.update_ref(ref, other, base)
    assert ws.ref_value(ref) == other
    with pytest.raises(GitError, match="update-ref failed"):
        ws.delete_ref(ref, base)
    ws.delete_ref(ref, other)
    assert ws.ref_value(ref) is None


def test_ref_value_matches_the_exact_ref_only(
    ws: GitWorkspace, repo: Path, base: str
) -> None:
    run_git(repo, "update-ref", "refs/heads/engine/run-r1/nested", base)
    assert ws.ref_value("refs/heads/engine/run-r1") is None
    assert ws.ref_value("refs/heads/main") == base


@pytest.mark.parametrize(
    "ref",
    [
        "refs/heads/main",
        "refs/tags/engine/x",
        "refs/heads/engine/",
        "refs/heads/engine/../main",
        "refs/heads/engine/x.lock",
        "refs/heads/engine/a b",
        "HEAD",
        "engine/run-r1",
    ],
)
def test_update_and_delete_ref_refuse_refs_outside_the_engine_prefix(
    ws: GitWorkspace, base: str, ref: str
) -> None:
    with pytest.raises(ValueError, match="not a ref under refs/heads/engine/"):
        ws.update_ref(ref, base, None)
    with pytest.raises(ValueError, match="not a ref under refs/heads/engine/"):
        ws.delete_ref(ref, base)


@pytest.mark.parametrize("ref", ["HEAD", "main", "refs/heads/a..b", "refs/x y"])
def test_ref_value_refuses_a_malformed_ref(ws: GitWorkspace, ref: str) -> None:
    with pytest.raises(ValueError, match="not a ref under refs/"):
        ws.ref_value(ref)


def test_update_ref_validates_object_ids(ws: GitWorkspace, base: str) -> None:
    with pytest.raises(ValueError, match="full object id"):
        ws.update_ref("refs/heads/engine/run-r1", "HEAD", None)
    with pytest.raises(ValueError, match="full object id"):
        ws.update_ref("refs/heads/engine/run-r1", base, "main")


def test_update_ref_never_writes_through_a_symref(
    ws: GitWorkspace, repo: Path, root: Path, base: str
) -> None:
    other = edit_and_commit(ws, root, base, "a", "core.py", "a\n")
    run_git(repo, "symbolic-ref", "refs/heads/engine/run-x", "refs/heads/main")
    with pytest.raises(GitError):
        ws.update_ref("refs/heads/engine/run-x", other, None)
    ws.delete_ref("refs/heads/engine/run-x", base)
    assert out(repo, "rev-parse", "refs/heads/main") == base
    assert ws.ref_value("refs/heads/engine/run-x") is None


# --------------------------------------------------------------------------
# Untrusted repositories: nothing the repo configures may run
# --------------------------------------------------------------------------


def _arm_traps(repo: Path, markers: Path) -> None:
    """Configure every executable hook the research found, each writing a marker."""

    def trap(name: str, tail: str = "") -> str:
        script = markers.parent / "traps" / name
        write(script, f"#!/bin/sh\ntouch '{markers / name}'\n{tail}")
        script.chmod(0o755)
        return str(script)

    hooks = markers.parent / "hooks-path"
    for hook in (
        "pre-commit",
        "prepare-commit-msg",
        "commit-msg",
        "post-commit",
        "post-checkout",
        "post-index-change",
        "reference-transaction",
        "pre-auto-gc",
        "post-rewrite",
    ):
        for where in (hooks, repo / ".git" / "hooks"):
            write(where / hook, f"#!/bin/sh\ntouch '{markers}/hook-{hook}'\n")
            (where / hook).chmod(0o755)
    settings_ = {
        "core.fsmonitor": trap("fsmonitor", "exit 1\n"),
        "core.hooksPath": str(hooks),
        "core.sshCommand": trap("ssh"),
        "core.pager": trap("pager"),
        "core.editor": trap("editor"),
        "core.alternateRefsCommand": trap("alternate-refs"),
        "filter.evil.clean": trap("clean", "cat\n"),
        "filter.evil.smudge": trap("smudge", "cat\n"),
        "filter.evil.required": "true",
        "filter.ev=il.clean": trap("clean-eq", "cat\n"),
        "filter.proc.process": trap("process"),
        "diff.evil.command": trap("diff-command"),
        "diff.evil.textconv": trap("textconv", 'cat "$1"\n'),
        "diff.external": trap("diff-external"),
        "merge.evil.driver": trap("merge-driver", "exit 0\n"),
        "merge.default": "evil",
        "gpg.program": trap("gpg"),
        "commit.gpgSign": "true",
        "credential.helper": trap("credential"),
        "gc.auto": "1",
        "protocol.ext.allow": "always",
        "protocol.file.allow": "always",
        "remote.origin.url": "ext::" + trap("ext-transport"),
        # Not commands, but they would blind capture and reset (full_cycle).
        "core.ignoreStat": "true",
        "core.untrackedCache": "true",
    }
    for key, value in settings_.items():
        run_git(repo, "config", key, value)
    attributes = (
        "* filter=evil diff=evil merge=evil\n*.py filter=ev=il\nrun.sh filter=proc\n"
    )
    write(repo / ".git" / "info" / "attributes", attributes)


@pytest.mark.parametrize("attr_source", [True, False], ids=["git>=2.40", "git<2.40"])
def test_a_malicious_config_never_runs_anything(
    repo: Path,
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attr_source: bool,
) -> None:
    write(repo / ".gitattributes", "* filter=evil diff=evil merge=evil\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "attributes")
    base = out(repo, "rev-parse", "HEAD")
    markers = tmp_path / "markers"
    markers.mkdir()
    _arm_traps(repo, markers)
    write(repo / "core.py", "user edit\n")
    ws = GitWorkspace(repo)
    if not attr_source:
        monkeypatch.setattr(ws, "version", lambda: (2, 39, 5))
    full_cycle(ws, root, base)
    assert sorted(p.name for p in markers.iterdir()) == []
    # Control: plain git on the same repo runs the traps (and may then fail).
    subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        env=_ENV,
        capture_output=True,
        check=False,
    )
    assert sorted(p.name for p in markers.iterdir()) != []


def _hide_a_smudge_filter(repo: Path, tmp_path: Path) -> Path:
    """A smudge filter defined only for linked worktrees: an includeIf whose
    gitdir: condition matches ``<common>/worktrees/<id>`` and never the repo's
    own git dir, selected by info/attributes. Returns the marker it writes."""
    marker = tmp_path / "markers" / "smudge"
    marker.parent.mkdir()
    script = write(tmp_path / "traps" / "smudge", f"#!/bin/sh\ntouch '{marker}'\ncat\n")
    script.chmod(0o755)
    hidden = tmp_path / "hidden.inc"
    write(hidden, f'[filter "hide"]\n\tsmudge = {script}\n\tclean = cat\n')
    run_git(repo, "config", "includeIf.gitdir:worktrees/.path", str(hidden))
    write(repo / ".git" / "info" / "attributes", "* filter=hide\n")
    return marker


def test_a_driver_only_a_linked_worktree_sees_never_runs_at_checkout(
    repo: Path, root: Path, tmp_path: Path, base: str
) -> None:
    """
    GIVEN a smudge filter included only when the git dir is a linked
        worktree's admin dir (invisible from the repository itself)
    WHEN the engine adds a worktree, the way every phase starts
    THEN the checkout ran no filter and the files are the committed blobs;
        plain git adding a worktree runs it (the control)
    """
    marker = _hide_a_smudge_filter(repo, tmp_path)
    ws = GitWorkspace(repo)

    handle = ws.add_worktree(root / "run1" / "baseline", base)

    assert not marker.exists()
    assert (handle.path / "core.py").read_bytes() == ws.read_blob(base, "core.py")
    assert ws.dirty_entries() == ()
    ws.reset(handle)
    assert not marker.exists()
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "--detach"]
        + [str(tmp_path / "plain"), base],
        env=_ENV,
        capture_output=True,
        check=True,
    )
    assert marker.exists()


def test_a_failed_checkout_leaves_no_worktree_behind(
    ws: GitWorkspace, root: Path, base: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN the checkout into a new worktree fails
    WHEN the engine adds the worktree
    THEN the error propagates and the worktree is neither on disk nor
        registered
    """
    real = ws._git

    def failing(
        where: WorktreeHandle | None, *args: str, **kw: Any
    ) -> tuple[int, bytes]:
        if args[:1] == ("checkout",):
            raise GitError("checkout failed")
        return real(where, *args, **kw)

    monkeypatch.setattr(ws, "_git", failing)
    target = root / "run1" / "baseline"

    with pytest.raises(GitError, match="checkout failed"):
        ws.add_worktree(target, base)

    assert not target.exists()
    listed = out(ws.repo, "worktree", "list", "--porcelain")
    assert str(target) not in listed


def _missing_objects(repo: Path) -> int:
    listing = run_git(repo, "rev-list", "--objects", "--missing=print", "HEAD")
    return sum(line.startswith(b"?") for line in listing.splitlines())


@pytest.mark.parametrize("transport", ["file", "ext"])
def test_a_partial_clone_never_fetches_from_its_promisor_remote(
    repo: Path, root: Path, tmp_path: Path, transport: str
) -> None:
    run_git(repo, "config", "uploadpack.allowFilter", "true")
    clone = tmp_path / "partial"
    run_git(
        tmp_path,
        *("-c", "protocol.file.allow=always", "clone", "-q", "--no-checkout"),
        *("--filter=blob:none", f"file://{repo}", str(clone)),
    )
    marker = tmp_path / "ext-ran"
    if transport == "ext":  # the promisor URL is a command line
        run_git(clone, "config", "remote.origin.url", f"ext::touch {marker}")
    # The repo's per-scheme permission beats the engine's protocol.allow.
    run_git(clone, "config", f"protocol.{transport}.allow", "always")
    missing = _missing_objects(clone)
    assert missing == 4
    ws = GitWorkspace(clone)
    base = ws.head_commit()
    with pytest.raises(GitError, match="cat-file failed"):
        ws.read_blob(base, "core.py")
    with pytest.raises(GitError, match="checkout failed"):
        ws.add_worktree(root / "run1" / "baseline", base)
    assert _missing_objects(clone) == missing
    assert not marker.exists()
    # Control: plain git does use the promisor remote.
    subprocess.run(
        ["git", "-C", str(clone), "cat-file", "blob", f"{base}:core.py"],
        env=_ENV,
        capture_output=True,
        check=False,
    )
    assert marker.exists() or _missing_objects(clone) < missing


def _snapshot(repo: Path) -> tuple[bytes, ...]:
    git_dir = repo / ".git"
    hooks = sorted((p.name, p.read_bytes()) for p in (git_dir / "hooks").iterdir())
    return (
        (git_dir / "HEAD").read_bytes(),
        hashlib.sha256((git_dir / "index").read_bytes()).digest(),
        run_git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all"),
        (git_dir / "config").read_bytes(),
        repr(hooks).encode(),
        run_git(repo, "stash", "list"),
    )


def test_the_users_head_index_status_and_config_survive_a_full_cycle(
    ws: GitWorkspace, repo: Path, root: Path, base: str
) -> None:
    write(repo / "core.py", "uncommitted\n")
    write(repo / "staged.txt", "staged\n")
    run_git(repo, "add", "staged.txt")
    write(repo / "untracked.txt", "untracked\n")
    before = _snapshot(repo)
    full_cycle(ws, root, base)
    assert _snapshot(repo) == before
    assert (repo / "core.py").read_text() == "uncommitted\n"
    listing = out(repo, "worktree", "list", "--porcelain")
    assert listing.count("worktree ") == 1


def test_a_sha256_repository_works_end_to_end(tmp_path: Path, root: Path) -> None:
    repo = tmp_path / "sha256"
    run_git(tmp_path, "init", "-q", "--object-format=sha256", "-b", "main", str(repo))
    write(repo / "core.py", CORE_V1)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "base")
    ws = GitWorkspace(repo)
    base = ws.head_commit()
    assert len(base) == 64
    handle = ws.add_worktree(root / "run1" / "trial-h1", base)
    write(handle.path / "core.py", "v2\n")
    ws.stage_all(handle)
    commit = ws.commit(handle, "c\n", base=base)
    ws.update_ref(OWN_REF, commit, None)
    assert ws.ref_value(OWN_REF) == commit
    ws.remove_worktree(handle)


# --------------------------------------------------------------------------
# The user-repo fingerprint
# --------------------------------------------------------------------------


def test_the_fingerprint_survives_a_full_cycle_when_the_own_ref_is_excluded(
    ws: GitWorkspace, root: Path, base: str
) -> None:
    own = frozenset({OWN_REF})
    before = repo_fingerprint(ws, exclude_refs=own)
    assert before == repo_fingerprint(ws)
    full_cycle(ws, root, base)
    assert repo_fingerprint(ws, exclude_refs=own) == before
    assert repo_fingerprint(ws) != before


def _new_branch(repo: Path, common: Path) -> None:
    run_git(repo, "branch", "other")


def _new_tag(repo: Path, common: Path) -> None:
    run_git(repo, "tag", "v1")


def _moved_branch(repo: Path, common: Path) -> None:
    tree = out(repo, "rev-parse", "HEAD^{tree}")
    run_git(
        repo, "update-ref", "refs/heads/main", out(repo, "commit-tree", tree, "-m", "x")
    )


def _another_engine_ref(repo: Path, common: Path) -> None:
    run_git(repo, "update-ref", "refs/heads/engine/trial-run1-h2", "HEAD")


def _symref(repo: Path, common: Path) -> None:
    run_git(repo, "symbolic-ref", "refs/heads/alias", "refs/heads/main")


def _config(repo: Path, common: Path) -> None:
    run_git(repo, "config", "core.hooksPath", "/tmp/hooks")


def _config_worktree(repo: Path, common: Path) -> None:
    write(common / "config.worktree", "[core]\n\tfsmonitor = /tmp/x\n")


def _hook(repo: Path, common: Path) -> None:
    write(common / "hooks" / "pre-commit", "#!/bin/sh\n")


def _config_mode(repo: Path, common: Path) -> None:
    config = common / "config"
    config.chmod(config.stat().st_mode ^ stat.S_IXUSR)


def _hooks_dir_gone_or_new(repo: Path, common: Path) -> None:
    hooks = common / "hooks"
    if hooks.exists():
        shutil.rmtree(hooks)
    else:
        hooks.mkdir()


def _info_attributes(repo: Path, common: Path) -> None:
    write(common / "info" / "attributes", "* filter=evil\n")


def _head_switched(repo: Path, common: Path) -> None:
    run_git(repo, "symbolic-ref", "HEAD", "refs/heads/elsewhere")


def _head_detached(repo: Path, common: Path) -> None:
    run_git(repo, "update-ref", "--no-deref", "HEAD", "HEAD")


def _replace_ref(repo: Path, common: Path) -> None:
    # The user's own git would then show this commit's tree for HEAD.
    tree = out(repo, "rev-parse", "HEAD^{tree}")
    fake = out(repo, "commit-tree", tree, "-m", "evil")
    run_git(repo, "update-ref", f"refs/replace/{out(repo, 'rev-parse', 'HEAD')}", fake)


def _notes_ref(repo: Path, common: Path) -> None:
    run_git(repo, "notes", "add", "-m", "run evil.sh", "HEAD")


def _stash_ref(repo: Path, common: Path) -> None:
    run_git(repo, "update-ref", "refs/stash", "HEAD")  # `stash pop` applies it


@pytest.mark.parametrize(
    "tamper",
    [
        _new_branch,
        _new_tag,
        _moved_branch,
        _another_engine_ref,
        _symref,
        _config,
        _config_worktree,
        _hook,
        _config_mode,
        _hooks_dir_gone_or_new,
        _info_attributes,
        _head_switched,
        _head_detached,
        _replace_ref,
        _notes_ref,
        _stash_ref,
    ],
)
def test_the_fingerprint_changes_on_any_ref_config_hook_or_head_change(
    ws: GitWorkspace, repo: Path, tamper: Callable[[Path, Path], None]
) -> None:
    before = repo_fingerprint(ws, exclude_refs=frozenset({OWN_REF}))
    tamper(repo, ws.common_dir())
    assert repo_fingerprint(ws, exclude_refs=frozenset({OWN_REF})) != before


def test_the_fingerprint_follows_included_config_files(
    ws: GitWorkspace, repo: Path, tmp_path: Path
) -> None:
    extra = write(tmp_path / "shm" / "extra", "[user]\n\tname = x\n")
    run_git(repo, "config", "include.path", str(extra))
    before = repo_fingerprint(ws)
    assert repo_fingerprint(ws) == before
    write(extra, f"[core]\n\thooksPath = {tmp_path / 'shm' / 'hooks'}\n")
    assert repo_fingerprint(ws) != before


def test_the_fingerprint_ignores_the_index_remotes_logs_and_objects(
    ws: GitWorkspace, repo: Path, base: str
) -> None:
    before = repo_fingerprint(ws)
    run_git(repo, "update-ref", "refs/remotes/origin/main", base)
    run_git(repo, "update-ref", "refs/prefetch/remotes/origin/main", base)
    write(repo / "new.txt", "n\n")
    run_git(repo, "add", "new.txt")
    run_git(repo, "hash-object", "-w", "--stdin", stdin=b"loose object\n")
    write(repo / ".git" / "logs" / "extra", "log\n")
    assert repo_fingerprint(ws) == before


def test_the_fingerprint_records_symlinks_unfollowed_and_never_opens_a_fifo(
    ws: GitWorkspace, tmp_path: Path
) -> None:
    hooks = ws.common_dir() / "hooks"
    hooks.mkdir(exist_ok=True)
    target = write(tmp_path / "target.sh", "a\n")
    os.symlink(target, hooks / "pre-push")
    os.mkfifo(hooks / "pipe")
    (ws.common_dir() / "info" / "nested").mkdir(parents=True)
    before = repo_fingerprint(ws)
    target.write_text("b\n")
    assert repo_fingerprint(ws) == before
    (hooks / "pre-push").unlink()
    os.symlink(tmp_path / "other.sh", hooks / "pre-push")
    assert repo_fingerprint(ws) != before


# --------------------------------------------------------------------------
# Public helpers (U20a): contained paths, messages, bounded blobs, commit
# diffs, ancestry, symrefs and the caller's branch prefix
# --------------------------------------------------------------------------


def test_contained_resolves_the_parent_and_refuses_anything_outside(
    root: Path, tmp_path: Path
) -> None:
    (root / "run1").mkdir()
    os.symlink(root / "run1", root / "alias")
    assert contained(root / "run1" / "x") == root / "run1" / "x"
    assert contained(root / "alias" / "x") == root / "run1" / "x"
    os.symlink(tmp_path, root / "out")
    for path in (root, root / "out" / "x", tmp_path / "x", Path("run1/x")):
        with pytest.raises(ValueError, match="WORKTREE_ROOT"):
            contained(path)
    with pytest.raises(ValueError, match="WORKTREE_ROOT"):
        contained(root / "run1" / "..")


def test_remove_contained_removes_trees_files_and_links_never_following_one(
    root: Path, tmp_path: Path
) -> None:
    """
    GIVEN a dir with a read-only subdir and a link out, a planted link, a
        file and a missing path, all inside WORKTREE_ROOT, and a dir outside
    WHEN each is removed
    THEN each is gone, nothing outside is touched, and outside is refused
    """
    outside = write(tmp_path / "outside" / "keep.txt", "keep\n").parent
    tree = root / "run1" / "_scratch" / "baseline"
    write(tree / "locked" / "file.txt", "x\n")
    os.symlink(outside, tree / "to-outside")
    (tree / "locked").chmod(0)
    link = root / "run1" / "link"
    os.symlink(outside, link)
    file = write(root / "run1" / "file", "x\n")
    for path in (tree, link, file, root / "run1" / "missing"):
        remove_contained(path)
        assert not os.path.lexists(path)
    assert (outside / "keep.txt").read_text() == "keep\n"
    with pytest.raises(ValueError, match="WORKTREE_ROOT"):
        remove_contained(outside)
    assert outside.is_dir()


def test_remove_contained_never_follows_a_tree_swapped_for_a_link(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a tree inside WORKTREE_ROOT that is swapped for a link to a
        directory outside right after remove_contained checked it
    WHEN it is removed
    THEN the removal refuses the link and the outside directory keeps its mode
        and its files
    """
    outside = write(tmp_path / "outside" / "keep.txt", "keep\n").parent
    outside.chmod(0o750)
    tree = write(root / "run1" / "_scratch" / "baseline" / "f", "x\n").parent
    real = os.path.islink

    def racing(path: Any) -> bool:
        if Path(path) == tree and not real(tree):
            shutil.rmtree(tree)
            os.symlink(outside, tree)
            return False
        return real(path)

    monkeypatch.setattr(os.path, "islink", racing)

    with pytest.raises(OSError):  # Linux: ENOTDIR; macOS: rmtree refuses a link
        remove_contained(tree)

    monkeypatch.undo()
    assert stat.S_IMODE(outside.stat().st_mode) == 0o750
    assert (outside / "keep.txt").read_text() == "keep\n"


def test_without_o_path_the_chmod_changes_a_link_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a platform without O_PATH (macOS)
    WHEN the engine makes a directory u+rwx
    THEN it asks for fchmodat(AT_SYMLINK_NOFOLLOW) (follow_symlinks=False)
        relative to the parent's fd, so a link is never followed
    """
    calls: list[tuple[str, int, int | None, bool]] = []
    real = os.chmod

    def chmod(
        path: str, mode: int, *, dir_fd: int | None = None, follow_symlinks: bool = True
    ) -> None:
        calls.append((path, mode, dir_fd, follow_symlinks))
        real(path, mode, dir_fd=dir_fd)  # Linux has no fchmodat(NOFOLLOW)

    (tmp_path / "locked").mkdir(mode=0)
    monkeypatch.delattr(os, "O_PATH", raising=False)  # macOS has none
    monkeypatch.setattr(os, "chmod", chmod)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        git_module._chmod_at(fd, "locked", stat.S_IRWXU)
    finally:
        os.close(fd)

    monkeypatch.undo()
    assert calls == [("locked", stat.S_IRWXU, fd, False)]
    assert stat.S_IMODE((tmp_path / "locked").stat().st_mode) == stat.S_IRWXU


def test_commit_message_is_the_raw_message_after_the_header(
    ws: GitWorkspace, repo: Path, root: Path, base: str
) -> None:
    commit = edit_and_commit(ws, root, base, "h1", "core.py", "v2\n")
    assert ws.commit_message(commit) == b"h1\n\nEngine-Trial: h1\n"
    assert ws.commit_message(base) == b"base\n"
    with pytest.raises(ValueError, match="full object id"):
        ws.commit_message("HEAD")
    tree = out(repo, "rev-parse", "HEAD^{tree}")
    with pytest.raises(GitError, match="cat-file failed"):
        ws.commit_message(tree)


def _spy_sink(ws: GitWorkspace, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Bytes git printed per call, counted as they stream past the sink."""
    printed: list[int] = []
    real = ws._spawn

    def spy(
        argv: Sequence[str],
        what: str,
        *,
        env: Mapping[str, str] | None = None,
        limit: int | None = None,
        sink: Sink | None = None,
    ) -> tuple[int, bytes, bytes]:
        printed.append(0)
        if sink is None:
            return real(argv, what, env=env, limit=limit, sink=sink)
        inner = sink

        def counting(chunk: bytes) -> None:
            printed[-1] += len(chunk)
            inner(chunk)

        return real(argv, what, env=env, limit=limit, sink=counting)

    monkeypatch.setattr(ws, "_spawn", spy)
    return printed


def test_read_blob_with_a_limit_keeps_only_the_head_and_stops_git(
    ws: GitWorkspace, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a tracked 8 MiB blob and an output cap of 4 KiB
    WHEN it is read with a 10-byte limit
    THEN the first 10 bytes come back, nothing past the cap was held, and
        git was stopped long before the whole blob streamed past
    """
    (repo / "huge.bin").write_bytes(b"0123456789" * (800 * 1024))
    write(repo / "small.txt", "tiny\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "huge")
    head = ws.head_commit()
    monkeypatch.setattr(settings, "MAX_OUTPUT_BYTES", 4096)
    printed = _spy_sink(ws, monkeypatch)
    assert ws.read_blob(head, "huge.bin", limit=10) == b"0123456789"
    assert printed[-1] < 1024 * 1024
    assert ws.read_blob(head, "small.txt", limit=10) == b"tiny\n"
    assert ws.read_blob(head, "small.txt", limit=5) == b"tiny\n"
    assert ws.read_blob(head, "small.txt", limit=1) == b"t"
    with pytest.raises(GitError, match="cat-file failed"):
        ws.read_blob(head, "missing.txt", limit=10)
    with pytest.raises(ValueError, match="limit"):
        ws.read_blob(head, "small.txt", limit=0)
    with pytest.raises(ValueError, match="repo-relative git path"):
        ws.read_blob(head, "../x", limit=10)


def _commit_files(repo: Path, base: str, files: Mapping[str, bytes]) -> str:
    """A child of ``base`` with ``files`` written, built by the test's git."""
    index = repo.parent / "test-index"
    env = {**_ENV, "GIT_INDEX_FILE": str(index)}
    run_git(repo, "read-tree", base, env=env)
    for path, data in files.items():
        blob = run_git(repo, "hash-object", "-w", "--stdin", stdin=data).decode()
        cache = f"100644,{blob.strip()},{path}"
        run_git(repo, "update-index", "--add", "--cacheinfo", cache, env=env)
    tree = run_git(repo, "write-tree", env=env).decode().strip()
    index.unlink()
    return out(repo, "commit-tree", tree, "-p", base, "-m", "child")


def test_diff_commits_equals_the_worktree_diff_without_any_worktree(
    ws: GitWorkspace, repo: Path, root: Path, base: str, calls: list[list[str]]
) -> None:
    tip = _commit_files(repo, base, {"core.py": b"def f(x):\n    return 2\n"})
    handle = ws.add_worktree(root / "run1" / "check", tip)
    expected = ws.diff(handle, base)
    ws.remove_worktree(handle)
    calls.clear()
    assert ws.diff_commits(base, tip) == expected
    assert "diff --git a/core.py b/core.py" in expected
    assert not any(a.startswith("--work-tree") for argv in calls for a in argv)
    assert os.listdir(root) == ["run1"] and os.listdir(root / "run1") == []
    with pytest.raises(ValueError, match="full object id"):
        ws.diff_commits("main", tip)
    with pytest.raises(ValueError, match="max_bytes"):
        ws.diff_commits(base, tip, max_bytes=0)


def test_diff_commits_is_capped_streamed_and_strict_utf8(
    ws: GitWorkspace, repo: Path, base: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = _commit_files(repo, base, {"big.py": "x = 1  # é\n".encode() * 20_000})
    monkeypatch.setattr(settings, "MAX_OUTPUT_BYTES", 4096)
    text = ws.diff_commits(base, big, max_bytes=1000)
    head, _, marker = text.rpartition("\n[diff truncated: ")
    assert head.startswith("diff --git a/big.py b/big.py")
    assert len(head.encode()) <= 1000 and marker.startswith("1000 of ")
    latin = _commit_files(repo, base, {"lib.py": b"caf\xe9\n"})
    with pytest.raises(GitDecodeError, match="not UTF-8"):
        ws.diff_commits(base, latin)


def test_is_ancestor_answers_and_raises_on_anything_but_yes_or_no(
    ws: GitWorkspace, repo: Path, base: str
) -> None:
    child = _commit_files(repo, base, {"lib.py": b"x\n"})
    tree = out(repo, "rev-parse", "HEAD^{tree}")
    orphan = out(repo, "commit-tree", tree, "-m", "orphan")
    assert ws.is_ancestor(base, child) is True
    assert ws.is_ancestor(base, base) is True
    assert ws.is_ancestor(child, base) is False
    assert ws.is_ancestor(orphan, child) is False
    with pytest.raises(GitError, match="merge-base failed"):
        ws.is_ancestor("0" * 39 + "1", child)
    with pytest.raises(ValueError, match="full object id"):
        ws.is_ancestor("HEAD", child)


def test_symbolic_ref_returns_the_final_target_or_none(
    ws: GitWorkspace, repo: Path, base: str
) -> None:
    run_git(repo, "symbolic-ref", "refs/heads/a", "refs/heads/b")
    run_git(repo, "symbolic-ref", "refs/heads/b", "refs/heads/engine/run-x")
    assert ws.symbolic_ref("HEAD") == "refs/heads/main"
    assert ws.symbolic_ref("refs/heads/a") == "refs/heads/engine/run-x"
    assert ws.symbolic_ref("refs/heads/main") is None
    assert ws.symbolic_ref("refs/heads/missing") is None
    for name in ("main", "refs/heads/a..b", "refs/x y", "-x", "HEAD\n"):
        with pytest.raises(ValueError, match="not a ref"):
            ws.symbolic_ref(name)


def test_symbolic_ref_raises_on_an_unexpected_exit(tmp_path: Path) -> None:
    body = (
        'case " $* " in *" version "*) echo "git version 2.39.0";;'
        ' *" symbolic-ref "*) exit 128;; esac\n'
    )
    git = GitWorkspace(tmp_path, executable=fake_git(tmp_path, body))
    with pytest.raises(GitError, match="symbolic-ref failed"):
        git.symbolic_ref("refs/heads/main")


def test_the_callers_prefix_decides_which_refs_may_move(
    ws: GitWorkspace, base: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a caller's branch prefix bots/
    WHEN refs are created, moved and deleted with it
    THEN refs under bots/ move, refs under the setting's prefix do not, a
        malformed prefix is refused, and no prefix means the setting
    """
    ref = "refs/heads/bots/run-r1"
    ws.update_ref(ref, base, None, prefix="bots/")
    assert ws.ref_value(ref) == base
    with pytest.raises(ValueError, match="not a ref under refs/heads/bots/"):
        ws.update_ref("refs/heads/engine/run-r1", base, None, prefix="bots/")
    with pytest.raises(ValueError, match="not a ref under refs/heads/engine/"):
        ws.delete_ref(ref, base)
    ws.delete_ref(ref, base, prefix="bots/")
    assert ws.ref_value(ref) is None
    for prefix in ("", "bots", "a b/", "refs/heads/../"):
        with pytest.raises(ValueError, match="prefix"):
            ws.update_ref(ref, base, None, prefix=prefix)
        with pytest.raises(ValueError, match="prefix"):
            ws.delete_ref(ref, base, prefix=prefix)
    monkeypatch.setattr(settings, "TRIAL_BRANCH_PREFIX", "bots/")
    ws.update_ref(ref, base, None)
    ws.delete_ref(ref, base)
    assert ws.ref_value(ref) is None
