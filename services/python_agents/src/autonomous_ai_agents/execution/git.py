"""Every git call the engine makes, on the user's repository and its worktrees.

The repository is untrusted input (research-git.md section 5; spec decisions
7, 8 and 16 to 19), so every call gets:

- **a scratch environment**: no inherited ``GIT_*``, no global or system
  config or attributes, optional locks off (a plain ``status`` rewrites the
  user's index), replace refs ignored, ``LC_ALL=C``, absolute ``PATH`` only;
- **``_CONFIG``**: hooks, fsmonitor, signing, network, credential helpers,
  external diffs and auto gc off, the engine identity pinned;
- **key overrides**: every ``filter``/``diff``/``merge`` driver command the
  repo defines is emptied, and every ``protocol.<scheme>.allow`` it sets
  (which beats ``protocol.allow``, so a partial clone's lazy fetch could
  reach the network or run an ``ext::`` command) becomes ``never``. Both go
  in via ``GIT_CONFIG_KEY_<n>``, re-read before each call in that call's
  context. Not via ``-c``: a subsection may contain ``=``, which ``-c``
  splits in the wrong place, so the driver would run;
- **``--attr-source=<empty tree>``** on git >= 2.40;
- for worktrees, **``--git-dir``/``--work-tree`` from the handle** read right
  after ``worktree add``; the ``.git`` file inside the writable worktree is
  never trusted again (``check_link`` compares its bytes);
- ``--`` before paths, ``--end-of-options`` before revisions, validated ids,
  refs and paths, argv lists only, never a shell, no stdin;
- **bounded output**: stdout is streamed and capped (``MAX_OUTPUT_BYTES``);
  a timeout kills git's whole session and returns at once.
"""

from __future__ import annotations

import codecs
import contextlib
import hashlib
import itertools
import math
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess  # nosec B404
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, cast

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError, RepoTamperedError
from autonomous_ai_agents.common.refnames import branch_prefix_problem, refname_problem
from autonomous_ai_agents.execution.protocols import Change, WorktreeHandle

ENGINE_NAME = "aip-engine"
ENGINE_EMAIL = "engine@aip.invalid"
ATTR_SOURCE_SINCE = (2, 40, 0)
"""First git with ``--attr-source``; Apple's git is 2.39."""

# worktree.useRelativePaths=false: otherwise git 2.48+ edits the user's config.
# ignoreStat, untrackedCache and sparseCheckout would hide edits from capture
# and reset; they must hold already when `worktree add` writes the index.
_CONFIG = (
    *"""core.hooksPath=/dev/null core.fsmonitor=false core.sshCommand=false
    core.attributesFile=/dev/null core.excludesFile=/dev/null core.pager=cat
    commit.gpgSign=false tag.gpgSign=false log.showSignature=false
    protocol.allow=never credential.helper= diff.external= gc.auto=0
    maintenance.auto=false submodule.recurse=false
    worktree.useRelativePaths=false core.ignoreStat=false
    core.untrackedCache=false core.sparseCheckout=false""".split(),
    f"user.name={ENGINE_NAME}",
    f"user.email={ENGINE_EMAIL}",
)
_CONFIG_ARGS = tuple(itertools.chain.from_iterable(("-c", kv) for kv in _CONFIG))
# Engine worktrees are on a local disk: a chmod or a rewrite must always show.
_WORKTREE_ARGS = (
    *("-c", "core.fileMode=true", "-c", "core.trustctime=true"),
    *("-c", "core.checkStat=default"),
)
_OVERRIDE_KEYS = (
    r"^(filter|diff|merge)\..*\.(clean|smudge|process|required|textconv|command"
    r"|driver)$|^protocol\..*\.allow$"
)
_FETCHED = ("refs/remotes/", "refs/prefetch/")
_MAX_MESSAGE = 1 << 16
"""A commit message travels as one argv entry (Linux caps one at 128 KiB)."""
_CHUNK = 1 << 16
_STATUS = (
    "status --porcelain=v1 -z --untracked-files=normal --no-renames "
    "--ignore-submodules=none"
).split()
_DIFF = "diff --no-renames --no-relative --ignore-submodules=none".split()
# No --binary: a deleted 1 GiB blob would otherwise be 1.3 GiB of patch.
_PATCH = (
    "--full-index --no-color --no-ext-diff --no-textconv "
    "--src-prefix=a/ --dst-prefix=b/"
).split()
_FORCE_REMOVE = ("worktree", "remove", "--force", "--force", "--")
_UPDATE_REF = ("update-ref", "--no-deref", "-m", ENGINE_NAME)
_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_VERSION = re.compile(rb"git version (\d+)\.(\d+)(?:\.(\d+))?")
_STAMP = rb" (\d+ [+-]\d{4})$"


class GitError(EngineError):
    """A git command failed, timed out or printed something unexpected."""

    def __init__(
        self,
        message: str,
        *,
        argv: Sequence[str] = (),
        returncode: int | None = None,
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.argv = tuple(argv)
        self.returncode = returncode
        self.stderr = stderr


class GitDecodeError(GitError):
    """Output that must be UTF-8 text (a diff) is not."""


class _Full(Exception):  # noqa: N818 - control flow, never escapes read_blob
    """``read_blob`` holds ``limit`` bytes: stop reading."""


@dataclass(frozen=True)
class MergeResult:
    """``merge-tree`` outcome: the merged tree, or ``None`` and the conflicts."""

    tree: str | None
    conflicts: tuple[str, ...]


def _require_oid(value: str) -> str:
    if _OID.fullmatch(value) is None:
        raise ValueError(f"{value!r} is not a full object id")
    return value


def _require_path(path: str) -> str:
    if "\0" in path or any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError(f"{path!r} is not a repo-relative git path")
    return path


def _require_ref(ref: str, prefix: str = "refs/") -> str:
    if not ref.startswith(prefix) or refname_problem(ref) is not None:
        raise ValueError(f"{ref!r} is not a ref under {prefix}")
    return ref


def _engine_ref(ref: str, prefix: str | None) -> str:
    """Only the engine's own branches may be created, moved or deleted: those
    under the caller's branch ``prefix`` (``None``: the setting's)."""
    chosen = settings.TRIAL_BRANCH_PREFIX if prefix is None else prefix
    problem = branch_prefix_problem(chosen)
    if problem is not None:
        raise ValueError(f"branch prefix {chosen[:300]!r} {problem}")
    return _require_ref(ref, "refs/heads/" + chosen)


def _require_symref_name(name: str) -> str:
    if name != "HEAD":
        _require_ref(name)
    return name


def _oid(out: bytes) -> str:
    text = out.decode("ascii", "replace").strip()
    if _OID.fullmatch(text) is None:
        raise GitError(f"expected an object id from git, got {text[:80]!r}")
    return text


def _scratch_env() -> dict[str, str]:
    entries = os.environ.get("PATH", "").split(os.pathsep)
    return {
        "PATH": os.pathsep.join(e for e in entries if os.path.isabs(e)) or os.defpath,
        "HOME": "/dev/null",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",  # honoured by newer git; protocols cover older
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "GIT_EDITOR": "true",
    }


def _read_regular(path: Path) -> bytes | None:
    """A regular file's bytes; never follows a symlink or blocks on a FIFO."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as file:
            return file.read()
    finally:
        os.close(fd)


def contained(path: Path) -> Path:
    """``path`` with its parent resolved, strictly inside ``WORKTREE_ROOT``;
    ``ValueError`` otherwise. The last component is never resolved."""
    root = Path(os.path.realpath(settings.WORKTREE_ROOT))
    if not path.is_absolute() or path.name in ("", ".."):
        raise ValueError(f"{path} is not an absolute path inside WORKTREE_ROOT")
    resolved = Path(os.path.realpath(path.parent)) / path.name
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError(f"{path} is not inside WORKTREE_ROOT {root}")
    return resolved


def remove_contained(path: Path) -> None:
    """Remove an engine path strictly inside ``WORKTREE_ROOT`` (``contained``):
    a directory tree (read-only subdirectories made removable first), or a
    file or link, unlinked and never followed; a missing path is fine.
    ``ValueError`` when ``path`` is not inside, ``OSError`` when it cannot go."""
    target = contained(path)
    if os.path.isdir(target) and not os.path.islink(target):
        _rmtree(target)
    elif os.path.lexists(target):
        os.unlink(target)


def _rmtree(path: Path) -> None:
    """Remove an engine directory, making read-only subdirectories removable."""
    os.chmod(path, stat.S_IRWXU)
    for top, dirs, _files in os.walk(path):
        for name in dirs:
            child = os.path.join(top, name)
            if not os.path.islink(child):
                os.chmod(child, stat.S_IRWXU)
    shutil.rmtree(path)


def _scrub(top: Path) -> None:
    """Undo what ``status`` and ``clean`` cannot see, never following a link.

    Every directory becomes u+rwx (git skips one it cannot read, so it would
    keep its files); every ``.git`` below the top goes (git never lists one,
    so it could hold a whole cache), and so does every FIFO, socket or device
    (git never tracks one, so its name could carry state).
    """
    link = os.path.join(top, ".git")
    pending = [str(top)]
    while pending:
        directory = pending.pop()
        os.chmod(directory, stat.S_IMODE(os.lstat(directory).st_mode) | stat.S_IRWXU)
        with os.scandir(directory) as entries:
            for entry in entries:
                nested = entry.name.lower() == ".git" and entry.path != link
                if entry.is_dir(follow_symlinks=False):
                    if nested:
                        _rmtree(Path(entry.path))
                    else:
                        pending.append(entry.path)
                elif nested or not (entry.is_symlink() or entry.is_file()):
                    os.unlink(entry.path)


def _require_message(message: str) -> str:
    if "\0" in message:
        raise ValueError("a commit message cannot contain NUL")
    if len(message.encode("utf-8")) > _MAX_MESSAGE:
        raise ValueError(f"a commit message cannot be longer than {_MAX_MESSAGE} bytes")
    return message


class GitWorkspace:
    """One user repository and the engine worktrees made from it."""

    def __init__(
        self,
        repo: Path,
        *,
        executable: str = settings.GIT_EXECUTABLE,
        timeout_s: float = settings.GIT_TIMEOUT_S,
    ) -> None:
        bare_or_absolute = "/" not in executable or os.path.isabs(executable)
        if not executable or "\0" in executable or not bare_or_absolute:
            raise ValueError(
                f"executable {executable!r} must be a bare name or an absolute path"
            )
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError(f"timeout_s must be positive and finite, got {timeout_s}")
        self._repo = Path(os.path.realpath(repo))
        self._exe = executable
        self._timeout = timeout_s
        self._version: tuple[int, int, int] | None = None
        self._common: Path | None = None
        self._empty_tree: str | None = None

    @property
    def repo(self) -> Path:
        return self._repo

    def _spawn(
        self,
        argv: Sequence[str],
        what: str,
        *,
        env: Mapping[str, str] | None = None,
        limit: int | None = None,
        sink: Callable[[bytes], None] | None = None,
    ) -> tuple[int, bytes, bytes]:
        """Run git in a new session with no stdin; returns (code, stdout, stderr).

        At most ``limit`` bytes of stdout (default ``MAX_OUTPUT_BYTES``) are
        kept. Past that, without a ``sink`` git is killed and ``GitError``
        raised; a ``sink`` sees every chunk and reading goes on. On a timeout
        or any error the whole session is killed and the call returns at
        once, even if a process that left the session still holds the pipes.
        """
        command = [self._exe, *argv]
        try:
            # An argv list and a scratch environment; never a shell.
            proc = subprocess.Popen(  # nosec B603
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**_scratch_env(), **(env or {})},
                start_new_session=True,
            )
        except OSError as exc:
            raise GitError(f"cannot run {self._exe!r}: {exc}", argv=command) from exc
        keep = settings.MAX_OUTPUT_BYTES if limit is None else limit
        with proc:
            try:
                out, err = self._collect(proc, command, what, keep, sink)
            except BaseException:
                # macOS answers EPERM for a group whose members all exited
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
                raise
        return proc.returncode, out, err

    def _collect(
        self,
        proc: subprocess.Popen[bytes],
        command: list[str],
        what: str,
        keep: int,
        sink: Callable[[bytes], None] | None,
    ) -> tuple[bytes, bytes]:
        deadline = time.monotonic() + self._timeout
        timed_out = GitError(
            f"git {what} timed out after {self._timeout:g} s", argv=command
        )
        out, err = bytearray(), bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(cast(IO[bytes], proc.stdout), selectors.EVENT_READ, out)
            selector.register(cast(IO[bytes], proc.stderr), selectors.EVENT_READ, err)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                ready = selector.select(remaining) if remaining > 0 else []
                if not ready:
                    raise timed_out
                for key, _ in ready:
                    chunk = os.read(key.fd, _CHUNK)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.data is err:
                        err += chunk
                        del err[: -settings.STDERR_TAIL_BYTES]
                    else:
                        if sink is not None:
                            sink(chunk)
                        elif len(out) + len(chunk) > keep:
                            message = f"git {what} printed more than {keep} bytes"
                            raise GitError(message, argv=command)
                        out += chunk[: keep - len(out)]
        try:
            proc.wait(max(deadline - time.monotonic(), 0))
        except subprocess.TimeoutExpired:
            raise timed_out from None
        return bytes(out), bytes(err)

    def _exec(
        self,
        argv: Sequence[str],
        what: str,
        *,
        ok: tuple[int, ...] | None = (0,),
        env: Mapping[str, str] | None = None,
        limit: int | None = None,
        sink: Callable[[bytes], None] | None = None,
    ) -> tuple[int, bytes]:
        code, out, err = self._spawn(argv, what, env=env, limit=limit, sink=sink)
        if ok is not None and code not in ok:
            tail = err[-settings.STDERR_TAIL_BYTES :].decode("utf-8", "replace").strip()
            raise GitError(
                f"git {what} failed (exit {code}): {tail}",
                argv=[self._exe, *argv],
                returncode=code,
                stderr=tail,
            )
        return code, out

    def _git(
        self,
        where: WorktreeHandle | None,
        *args: str,
        ok: tuple[int, ...] | None = (0,),
        env: Mapping[str, str] | None = None,
        limit: int | None = None,
        sink: Callable[[bytes], None] | None = None,
    ) -> tuple[int, bytes]:
        """``git <args>`` in the user's repo (``None``) or a handle's worktree."""
        context = ["-C", str(self._repo)]
        if where is not None:
            wt = str(where.path)
            context = ["-C", wt, f"--git-dir={where.gitdir}", f"--work-tree={wt}"]
            context += _WORKTREE_ARGS
        listing = [*context, *_CONFIG_ARGS, "config", "--name-only", "-z"]
        _, out = self._exec(
            [*listing, "--get-regexp", _OVERRIDE_KEYS], "config", ok=(0, 1)
        )
        names = [os.fsdecode(name) for name in out.split(b"\0") if name]
        overrides = {"GIT_CONFIG_COUNT": str(len(names))}
        for index, name in enumerate(names):
            overrides[f"GIT_CONFIG_KEY_{index}"] = name
            value = "never" if name.startswith("protocol.") else ""
            overrides[f"GIT_CONFIG_VALUE_{index}"] = value
        argv = [*self._attr_source(), *context, *_CONFIG_ARGS, *args]
        env = {**overrides, **(env or {})}
        return self._exec(argv, args[0], ok=ok, env=env, limit=limit, sink=sink)

    def _run(self, *args: str, ok: tuple[int, ...] | None = (0,)) -> bytes:
        """``git <args>`` in the user's repository; returns stdout."""
        return self._git(None, *args, ok=ok)[1]

    def _attr_source(self) -> list[str]:
        if self.version() < ATTR_SOURCE_SINCE:
            return []
        if self._empty_tree is None:  # a SHA-256 repository has another one
            argv = ["-C", str(self._repo), *_CONFIG_ARGS, "hash-object", "-t", "tree"]
            _, out = self._exec([*argv, "--stdin", "--no-filters"], "hash-object")
            self._empty_tree = _oid(out)
        return [f"--attr-source={self._empty_tree}"]

    def version(self) -> tuple[int, int, int]:
        if self._version is None:
            _, out = self._exec(["version"], "version")
            match = _VERSION.match(out)
            if match is None:
                raise GitError(f"cannot parse {out[:80]!r} as a git version")
            major, minor, patch = match.groups()
            self._version = (int(major), int(minor), int(patch or b"0"))
        return self._version

    def common_dir(self) -> Path:
        if self._common is None:
            out = self._run("rev-parse", "--path-format=absolute", "--git-common-dir")
            self._common = Path(os.path.realpath(os.fsdecode(out.rstrip(b"\n"))))
        return self._common

    def head_commit(self) -> str:
        return self.resolve_commit("HEAD")

    def resolve_commit(self, rev: str) -> str:
        if not rev or "\0" in rev or "\n" in rev:
            raise ValueError(f"{rev!r} is not a revision")
        spec = rev + "^{commit}"
        return _oid(self._run("rev-parse", "--verify", "--end-of-options", spec))

    def dirty_entries(self) -> tuple[str, ...]:
        """The user's uncommitted entries (``XY path``), read without locking."""
        entries = self._run(*_STATUS).split(b"\0")
        return tuple(e.decode("utf-8", "backslashreplace") for e in entries if e)

    def ls_tree(self, commit: str) -> tuple[str, ...]:
        """Every blob path at ``commit`` (symlinks included, gitlinks not)."""
        out = self._run("ls-tree", "-r", "-z", "--full-tree", _require_oid(commit))
        paths = []
        for record in out.split(b"\0"):
            meta, _, path = record.partition(b"\t")
            if meta.split(b" ")[1:2] == [b"blob"]:
                paths.append(os.fsdecode(path))
        return tuple(paths)

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        """The blob at ``commit:path``. With no ``limit``, all of it (``GitError``
        past ``MAX_OUTPUT_BYTES``); with one, its first ``limit`` bytes at
        most: the blob streams into a buffer that never grows past ``limit``
        and git is stopped as soon as it is full."""
        spec = f"{_require_oid(commit)}:{_require_path(path)}"
        if limit is None:
            return self._run("cat-file", "blob", spec)
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        head = bytearray()

        def keep(chunk: bytes) -> None:
            head.extend(chunk[: limit - len(head)])
            if len(head) >= limit:
                raise _Full

        with contextlib.suppress(_Full):  # _spawn kills git on the way out
            self._git(None, "cat-file", "blob", spec, limit=0, sink=keep)
        return bytes(head)

    def commit_message(self, commit: str) -> bytes:
        """``commit``'s raw message (everything after the header), as stored."""
        raw = self._run("cat-file", "commit", _require_oid(commit))
        return raw.partition(b"\n\n")[2]

    def add_worktree(self, path: Path, commit: str) -> WorktreeHandle:
        """A detached worktree at ``commit``; whatever was at ``path`` goes first."""
        target = contained(path)
        _require_oid(commit)
        self.remove_worktree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        spec = commit + "^{commit}"
        self._run("worktree", "add", "--detach", "--", str(target), spec)
        try:
            return self._open(target)
        except RepoTamperedError:
            self.remove_worktree(target)
            raise

    def _open(self, path: Path) -> WorktreeHandle:
        """``path/.git`` must name a direct child of ``<common>/worktrees`` whose
        ``gitdir`` file points back here; git renames the child on a collision."""
        link = _read_regular(path / ".git") or b""
        named = link.removeprefix(b"gitdir: ").removesuffix(b"\n")
        admin = Path(os.path.realpath(self.common_dir() / "worktrees"))
        if link.startswith(b"gitdir: ") and b"\0" not in named:
            gitdir = Path(os.path.realpath(path / os.fsdecode(named)))
            back = (_read_regular(gitdir / "gitdir") or b"\0").rstrip(b"\n")
            points_back = b"\0" not in back and os.path.realpath(back) == os.fsencode(
                path / ".git"
            )
            if gitdir.parent == admin and points_back:
                return WorktreeHandle(path=path, gitdir=gitdir, link_bytes=link)
        raise RepoTamperedError(
            f"{path}/.git does not name an admin directory in {admin}: {link[:200]!r}"
        )

    def remove_worktree(self, target: WorktreeHandle | Path) -> None:
        """``worktree remove --force``, then a contained ``rmtree`` and a prune."""
        path = contained(target.path if isinstance(target, WorktreeHandle) else target)
        code, _ = self._git(None, *_FORCE_REMOVE, str(path), ok=None)
        remove_contained(path)
        if code != 0:
            self.prune()

    def prune(self) -> None:
        """Drop stale registrations under ``WORKTREE_ROOT``, then broken ones.

        Plain ``worktree prune`` would also drop the user's stale worktrees,
        say one on an unmounted drive. ``--expire=never`` drops only admin
        dirs that ``git gc`` drops whatever their age: no or an empty
        ``gitdir`` (an interrupted ``worktree add``), or a missing path with
        no index; never a locked one.
        """
        root = Path(os.path.realpath(settings.WORKTREE_ROOT))
        for entry in self._worktrees():
            where = Path(entry["worktree"])
            if "prunable" in entry and where != root and where.is_relative_to(root):
                self._run(*_FORCE_REMOVE, str(where))
        self._run("worktree", "prune", "--expire=never")

    def _worktrees(self) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        current: dict[str, str] = {}
        out = self._run("worktree", "list", "--porcelain", "-z")
        for field in [*out.split(b"\0"), b""]:
            if field:
                key, _, value = os.fsdecode(field).partition(" ")
                current[key] = value
            elif current:
                entries.append(current)
                current = {}
        return entries

    def registered_worktrees(self) -> tuple[tuple[Path, bool], ...]:
        """Every worktree git lists (the main one first), with whether git
        calls it prunable (its directory is gone)."""
        return tuple((Path(e["worktree"]), "prunable" in e) for e in self._worktrees())

    def checked_out_branches(self) -> frozenset[str]:
        return frozenset(e["branch"] for e in self._worktrees() if "branch" in e)

    def check_link(self, handle: WorktreeHandle) -> None:
        if _read_regular(handle.path / ".git") != handle.link_bytes:
            message = f"{handle.path}/.git changed after the worktree was created"
            raise RepoTamperedError(message)

    def reset(self, handle: WorktreeHandle) -> None:
        """Make the worktree equal its HEAD again, so no run sees another's files.

        Always ``_scrub``, ``checkout -f`` and ``clean -ffdx``: an empty
        ``status`` proves nothing (see ``_scrub``). A tracked file whose
        mtime, mode or xattrs changed is rewritten too: each change bumps its
        ctime, and ``core.trustctime`` makes that a stat mismatch. Not reset:
        directory metadata (mtime, xattrs, mode bits beyond u+rwx), a narrow
        channel only a deliberate workload would use.
        """
        self.check_link(handle)
        _scrub(handle.path)
        self._git(handle, "checkout", "-f", "-q")
        self.clean(handle)
        if self._dirty(handle):
            raise GitError(f"worktree {handle.path} is still dirty after a reset")
        self.check_link(handle)

    def _dirty(self, handle: WorktreeHandle) -> bool:
        return bool(self._git(handle, *_STATUS, "--ignored")[1])

    def stage_all(self, handle: WorktreeHandle) -> None:
        self._git(handle, "add", "--all", "--", ".")

    def changes(self, handle: WorktreeHandle, base: str) -> tuple[Change, ...]:
        """The staged entries against ``base``; a rename is a D plus an A."""
        argv = [*_DIFF, "--cached", "--raw", "-z", "--no-abbrev", _require_oid(base)]
        argv.append("--")
        fields = self._git(handle, *argv)[1].split(b"\0")
        try:  # strict=False: the output ends with a NUL, so one field is left over
            pairs = zip(fields[::2], fields[1::2], strict=False)
            return tuple(_change(meta, path) for meta, path in pairs)
        except ValueError as exc:
            raise GitError(f"unexpected diff --raw output: {exc}") from exc

    def diff(
        self,
        handle: WorktreeHandle,
        base: str,
        *,
        max_bytes: int = settings.MAX_DIFF_BYTES,
    ) -> str:
        """The staged patch, strict UTF-8, capped at ``max_bytes``.

        Streamed: only the first ``max_bytes`` are kept, the rest is checked
        as it passes. A binary file is git's one-line notice, never a payload.
        """
        argv = ("--cached", _require_oid(base))
        return self._patch(handle, argv, base, max_bytes)

    def diff_commits(
        self, base: str, tip: str, *, max_bytes: int = settings.MAX_DIFF_BYTES
    ) -> str:
        """``base..tip`` as ``diff`` prints it, read from the objects: no
        worktree, the same flags, strict UTF-8 and cap."""
        argv = (_require_oid(base), _require_oid(tip))
        return self._patch(None, argv, base, max_bytes)

    def _patch(
        self,
        where: WorktreeHandle | None,
        revisions: Sequence[str],
        base: str,
        max_bytes: int,
    ) -> str:
        if max_bytes < 1:
            raise ValueError(f"max_bytes must be at least 1, got {max_bytes}")
        decoder = codecs.getincrementaldecoder("utf-8")()
        total = 0

        def check(chunk: bytes) -> None:
            nonlocal total
            total += len(chunk)
            decoder.decode(chunk)

        argv = (*_DIFF, *_PATCH, *revisions, "--")
        try:
            out = self._git(where, *argv, limit=max_bytes, sink=check)[1]
            decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            message = f"the diff against {base} is not UTF-8 text"
            raise GitDecodeError(message) from exc
        head = out.decode("utf-8", "ignore")  # may end inside a character
        if total <= max_bytes:
            return head
        return f"{head}\n[diff truncated: {max_bytes} of {total} bytes shown]\n"

    def staged_blob(self, handle: WorktreeHandle, path: str) -> bytes:
        return self._git(handle, "cat-file", "blob", ":0:" + _require_path(path))[1]

    def commit(self, handle: WorktreeHandle, message: str, *, base: str) -> str:
        """Commit the index onto the worktree's HEAD; returns the new commit."""
        _require_message(message)
        _require_oid(base)
        tree = _oid(self._git(handle, "write-tree")[1])
        head = ("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}")
        parent = _oid(self._git(handle, *head)[1])
        new = self._commit_object(handle, tree, parent, message, base)
        self._git(handle, *_UPDATE_REF, "HEAD", new, parent)
        return new

    def clean(self, handle: WorktreeHandle) -> None:
        self._git(handle, "clean", "-f", "-f", "-d", "-x", "-q", "--")

    def merge(self, acc: str, commit: str) -> MergeResult:
        """``merge-tree --write-tree ACC X``: exit 1 is a conflict, others raise."""
        argv = ["merge-tree", "--write-tree", "--name-only", "-z", "--no-messages"]
        argv += [_require_oid(acc), _require_oid(commit)]
        code, out = self._git(None, *argv, ok=(0, 1))
        fields = out.split(b"\0")
        if code == 0:
            return MergeResult(tree=_oid(fields[0]), conflicts=())
        conflicts = tuple(os.fsdecode(f) for f in itertools.takewhile(bool, fields[1:]))
        return MergeResult(tree=None, conflicts=conflicts)

    def commit_tree(self, tree: str, parent: str, message: str, *, base: str) -> str:
        _require_message(message)
        ids = (_require_oid(tree), _require_oid(parent), _require_oid(base))
        return self._commit_object(None, ids[0], ids[1], message, ids[2])

    def _commit_object(
        self,
        where: WorktreeHandle | None,
        tree: str,
        parent: str,
        message: str,
        base: str,
    ) -> str:
        """One parent, the engine identity and ``base``'s dates (so a resumed run
        rebuilds the same SHAs); no hooks, no signing, no message cleanup
        (``-m`` keeps the text verbatim, adding a final newline if missing)."""
        header = self._run("cat-file", "commit", base).split(b"\n\n", 1)[0]
        author = re.search(rb"^author .*" + _STAMP, header, re.MULTILINE)
        committer = re.search(rb"^committer .*" + _STAMP, header, re.MULTILINE)
        if author is None or committer is None:
            raise GitError(f"commit {base} has no parseable author and committer dates")
        env = {"GIT_AUTHOR_DATE": "@" + author[1].decode("ascii")}
        env["GIT_COMMITTER_DATE"] = "@" + committer[1].decode("ascii")
        for role in ("AUTHOR", "COMMITTER"):
            env[f"GIT_{role}_NAME"] = ENGINE_NAME
            env[f"GIT_{role}_EMAIL"] = ENGINE_EMAIL
        argv = ["commit-tree", tree, "-p", parent, "--no-gpg-sign", "-m", message]
        return _oid(self._git(where, *argv, env=env)[1])

    def _refs(self, *patterns: str) -> dict[str, tuple[str, str]]:
        """``refname -> (object id, symref target)`` for refs under ``patterns``."""
        form = "--format=%(refname)%00%(objectname)%00%(symref)"
        records: dict[str, tuple[str, str]] = {}
        for line in self._run("for-each-ref", form, *patterns).splitlines():
            name, oid, symref = line.split(b"\0")
            records[os.fsdecode(name)] = (oid.decode("ascii"), os.fsdecode(symref))
        return records

    def is_ancestor(self, base: str, tip: str) -> bool:
        """``merge-base --is-ancestor``: exit 0 is yes, 1 no, anything else raises."""
        argv = ("merge-base", "--is-ancestor", _require_oid(base), _require_oid(tip))
        return self._git(None, *argv, ok=(0, 1))[0] == 0

    def symbolic_ref(self, name: str) -> str | None:
        """The ref ``name`` (``HEAD`` or under ``refs/``) finally points at, through
        every git symref, or ``None`` when it is no symref (or missing).
        ``GitError`` when git cannot resolve it (exit 128: a chain deeper than
        git follows, or one ending at a name git cannot parse). A loose ref
        file that is a filesystem link (git's legacy symref form) is not seen:
        ``None``."""
        argv = ("symbolic-ref", "-q", _require_symref_name(name))
        code, out = self._git(None, *argv, ok=(0, 1))
        return os.fsdecode(out.rstrip(b"\n")) if code == 0 else None

    def ref_value(self, ref: str) -> str | None:
        record = self._refs(_require_ref(ref)).get(ref)
        return None if record is None else record[0]

    def update_ref(
        self, ref: str, new: str, old: str | None, *, prefix: str | None = None
    ) -> None:
        """Move an engine ref from ``old`` to ``new``; ``old=None`` is create-only.
        Only a ref under ``refs/heads/<prefix>`` (``None``: the setting's
        prefix). ``--no-deref``: a symref planted at an engine name (pointing
        at a user branch, say) is replaced, never written through."""
        _engine_ref(ref, prefix)
        expected = "0" * len(_require_oid(new)) if old is None else _require_oid(old)
        self._run(*_UPDATE_REF, ref, new, expected)

    def delete_ref(self, ref: str, old: str, *, prefix: str | None = None) -> None:
        """Delete an engine ref at ``old``; the prefix rule of ``update_ref``."""
        _engine_ref(ref, prefix)
        expected = _require_oid(old)
        self._run(*_UPDATE_REF, "-d", ref, expected)

    def _head_state(self) -> bytes:
        symref = self._run("symbolic-ref", "-q", "HEAD", ok=(0, 1))
        target = self._run("rev-parse", "-q", "--verify", "HEAD", ok=(0, 1))
        return symref + b"\0" + target


def _change(meta: bytes, path: bytes) -> Change:
    old_mode, new_mode, _, _, status = meta.decode("ascii").removeprefix(":").split()
    return Change(status, old_mode, new_mode, os.fsdecode(path))


def _feed(update: Callable[[bytes], object], *parts: bytes) -> None:
    for part in parts:
        update(len(part).to_bytes(8, "big") + part)


def _feed_path(update: Callable[[bytes], object], rel: str, path: Path) -> None:
    """Hash a name, its type and mode and its bytes; a symlink as its text."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        _feed(update, b"missing", os.fsencode(rel))
        return
    head = (os.fsencode(rel), str(info.st_mode).encode())
    if stat.S_ISLNK(info.st_mode):
        _feed(update, b"link", *head, os.readlink(os.fsencode(path)))
    elif stat.S_ISREG(info.st_mode):
        _feed(update, b"file", *head, _read_regular(path) or b"")
    elif stat.S_ISDIR(info.st_mode):
        _feed(update, b"dir", *head)
        for name in sorted(os.listdir(path)):
            _feed_path(update, f"{rel}/{name}", path / name)
    else:
        _feed(update, b"other", *head)


def repo_fingerprint(
    git: GitWorkspace, *, exclude_refs: frozenset[str] = frozenset()
) -> str:
    """sha256 over what tampering would change in the user's repository.

    ``config``, ``config.worktree``, ``hooks/`` and ``info/`` in the common
    dir, the effective config (so a changed ``[include]`` target shows), the
    HEAD symref, and every ref (``refs/replace`` rewrites what the user's git
    shows, ``refs/stash`` what ``stash pop`` applies) minus ``exclude_refs``
    (a trial's own ref). Not the index, status, remote-tracking or prefetch
    refs, or logs: IDEs rewrite the index and fetch in the background.
    """
    common = git.common_dir()
    digest = hashlib.sha256(b"aip-repo-fingerprint/2")
    for name in ("config", "config.worktree", "hooks", "info"):
        _feed_path(digest.update, name, common / name)
    listing = ("config", "--list", "-z", "--show-scope", "--show-origin")
    _feed(digest.update, b"effective", git._run(*listing))
    _feed(digest.update, b"HEAD", git._head_state())
    for ref, (oid, symref) in sorted(git._refs("refs/").items()):
        if ref not in exclude_refs and not ref.startswith(_FETCHED):
            fields = (os.fsencode(ref), oid.encode(), os.fsencode(symref))
            _feed(digest.update, b"ref", *fields)
    return digest.hexdigest()
