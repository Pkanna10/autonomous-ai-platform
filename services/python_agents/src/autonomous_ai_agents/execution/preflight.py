"""Connect-time preflight: refuse a repository or host the engine cannot measure.

``GitPreflight.check`` reads the repository only through ``GitWorkspace`` (its
``-c``, attribute and environment overrides), never writes the checkout or a
ref, and ends with ``prune``. A ``PreflightError`` (printable text) names the
problem and the fix: ``tests_pass`` without ``project.test_command``; git
< 2.38; dubious ownership (never ``safe.directory``); ``root_path`` not the top
of a work tree, without a commit, or holding ``WORKTREE_ROOT``; a partial
clone; a crafted tree path, ``.gitmodules`` or a gitlink; LFS (``filter=lfs`` in
any ``.gitattributes`` blob read with ``cat-file``, in ``info/attributes``, or a
root ``.lfsconfig``; no filter runs); an editable ``.py`` blob the engine's
Python cannot parse (a protected one is a note); an unresolvable command; or a
failed isolation probe (``true`` once through ``run_once`` and the launcher's
write and connect self-checks, in a fresh ``WORKTREE_ROOT/preflight-*``).

``_Resolver``: ``argv[0]`` is absolute, a hit on the absolute PATH entries, or
a repo executable reached through links that stay in the tree (as ``measure``
requires). Arguments naming base-tree files (``--opt=`` values, node ids, ``-m``
targets, through links, in any case) are protected, as is a directory the test
command names (not the root or ``src``). A tracked path given absolutely (the
run would use the checkout's copy) and inline shell or Python code are refused.
"""

from __future__ import annotations

import ast
import glob
import os
import posixpath
import re
import shutil
import sys
import tempfile
import warnings
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import PreflightError
from autonomous_ai_agents.common.models import (
    Guardrail,
    GuardrailKind,
    Project,
    Workload,
)
from autonomous_ai_agents.common.paths import (
    PathTraversalError,
    matches_pattern,
    normalize_path,
)
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.execution.measure import RunOnce
from autonomous_ai_agents.execution.procrun import (
    WRAPPER_PATH,
    OutputCaps,
    RunFailure,
    RunSample,
    run_once,
)
from autonomous_ai_agents.execution.protocols import PreflightReport
from autonomous_ai_agents.execution.sandbox import PLATFORMS, SandboxPolicy, child_env
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS

MIN_GIT_VERSION = (2, 38, 0)
"""First git with ``merge-tree --write-tree`` (Apple ships 2.39)."""
MAX_PARSE_BYTES = 2 * 1024 * 1024
PROBE_TIMEOUT_S = 30.0
SYSTEM_PATH = WRAPPER_PATH
"""Where the probe's ``true`` is looked up: ``/bin:/usr/bin``."""
PHASE = "preflight"
SYSCTL = "kernel.apparmor_restrict_unprivileged_userns"

_BATCH = 256
"""Blob ids per ``git show`` call (one argv stays far below ARG_MAX)."""
_BATCH_BYTES = 32 * 1024 * 1024
_MAX_ATTRIBUTES_BYTES = 16 * 1024 * 1024
_MAX_LINK_HOPS = 8
_MESSAGE_CAP = 2000
_SYMLINK, _EXECUTABLE = "120000", "100755"
_FALSE = frozenset({"false", "no", "off", "0", ""})
_BAD_PARTS = frozenset({"", ".", "..", ".git"})
_LFS = re.compile(rb"(?<!\S)filter=lfs(?!\S)", re.IGNORECASE)
_TREE = re.compile(r"([0-7]{6}) (blob|commit) ([0-9a-f]{40}|[0-9a-f]{64}) +(\d+|-)")
_PARTIAL = r"^(extensions\.partialclone|remote\..*\.promisor)$"
_SHELLS = frozenset({"sh", "bash", "dash", "zsh", "ksh", "mksh", "ash", "fish"})
_PYTHON = re.compile(r"(python|pypy)[0-9.]*t?")
_LONG_VALUE = frozenset({"--rcfile", "--init-file", "--check-hash-based-pycs"})
_UNPROTECTED_DIRS = frozenset({".", "src"})
"""Test-command directories left to the default patterns: they hold the code."""


@dataclass(frozen=True)
class GitPreflightReport(PreflightReport):
    """The protocol's report plus the engine's Python and the notes for events."""

    python_version: tuple[int, int, int]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class _Entry:
    mode: str
    kind: str
    oid: str
    size: int


class _RepoGit(GitWorkspace):
    """The read-only queries preflight needs, through the workspace's overrides."""

    def toplevel(self) -> Path:
        out = self._run("rev-parse", "--show-toplevel")
        return Path(os.path.realpath(os.fsdecode(out.rstrip(b"\n"))))

    def config_entries(self, pattern: str) -> list[tuple[str, str | None]]:
        """``(key, value)`` per match; ``None`` for a key with no ``=`` (true)."""
        entries: list[tuple[str, str | None]] = []
        out = self._run("config", "-z", "--get-regexp", pattern, ok=(0, 1))
        for record in filter(None, out.split(b"\0")):
            key, newline, value = record.partition(b"\n")
            entries.append((os.fsdecode(key), os.fsdecode(value) if newline else None))
        return entries

    def tree(self, commit: str) -> dict[str, _Entry]:
        """Every entry at ``commit`` (gitlinks too); a crafted path is refused."""
        entries: dict[str, _Entry] = {}
        out = self._run("ls-tree", "-r", "-z", "-l", "--full-tree", commit)
        for record in filter(None, out.split(b"\0")):
            meta, tab, raw = record.partition(b"\t")
            match = _TREE.fullmatch(meta.decode("ascii", "replace"))
            if not tab or match is None:
                raise GitError(f"unexpected ls-tree output: {record[:80]!r}")
            path = os.fsdecode(raw)
            if any(part.casefold() in _BAD_PARTS for part in path.split("/")):
                raise PreflightError(
                    f"{path} at {commit}: git would not check out this path"
                )
            mode, kind, oid, size = match.groups()
            entries[path] = _Entry(mode, kind, oid, 0 if size == "-" else int(size))
        return entries

    def contents(self, sizes: Mapping[str, int]) -> Iterator[dict[str, bytes]]:
        """Blob bytes by id, one ``git show`` (no textconv) per batch of ids."""
        batches: list[list[str]] = [[]]
        total = 0
        for oid, size in sizes.items():
            full = len(batches[-1]) >= _BATCH or total + size > _BATCH_BYTES
            if batches[-1] and full:
                batches.append([])
                total = 0
            batches[-1].append(oid)
            total += size
        for batch in filter(None, batches):
            out = self._run("show", "--no-textconv", "--no-color", *batch)
            if len(out) != (expected := sum(sizes[oid] for oid in batch)):
                raise GitError(f"git show printed {len(out)} of {expected} blob bytes")
            found: dict[str, bytes] = {}
            offset = 0
            for oid in batch:
                found[oid] = out[offset : offset + sizes[oid]]
                offset += sizes[oid]
            yield found


def _quote(text: str) -> str:
    """Printable text only (``?`` for the rest), capped: repo bytes reach a terminal."""
    return "".join(ch if ch.isprintable() else "?" for ch in text[:_MESSAGE_CAP])


def _has_lfs(data: bytes) -> bool:
    lines = (line for line in data.splitlines() if not line.lstrip().startswith(b"#"))
    return any(_LFS.search(line) for line in lines)


def _read_head(path: Path) -> bytes:
    """Up to 16 MiB of a file git would read; nothing when it cannot be read."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            return os.read(fd, _MAX_ATTRIBUTES_BYTES)
        finally:
            os.close(fd)
    except OSError:
        return b""


def _parse_problem(source: bytes, path: str) -> str | None:
    try:
        with warnings.catch_warnings():  # a warning filter must not raise here
            warnings.simplefilter("ignore")
            ast.parse(source, filename=path)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
        return f"{type(error).__name__}: {error}"
    return None


def _engine_python() -> tuple[int, int, int]:
    return (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)


def _dotted(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def _git_refusal(repo: Path, error: Exception) -> PreflightError:
    if "dubious ownership" in str(error):
        return PreflightError(
            f"git refuses {repo}: detected dubious ownership (another user owns"
            " it). Run the engine as its owner or make it yours; the engine"
            " ignores your global git config, so safe.directory there cannot help"
        )
    return PreflightError(f"cannot read the git repository at {repo}: {error}")


def _check_repository(git: _RepoGit) -> tuple[str, dict[str, _Entry]]:
    """Version, shape, partial clone, submodules and LFS; the head and its tree."""
    if (version := git.version()) < MIN_GIT_VERSION:
        raise PreflightError(
            f"git {_dotted(version)} is older than 2.38 (merge-tree --write-tree):"
            " install git 2.38 or newer, or point GIT_EXECUTABLE at one"
        )
    if (top := git.toplevel()) != git.repo:
        message = f"{git.repo} is not the top of its work tree: set root_path to {top}"
        raise PreflightError(message)
    worktrees = Path(os.path.realpath(settings.WORKTREE_ROOT))
    if worktrees.is_relative_to(git.repo):
        raise PreflightError(
            f"WORKTREE_ROOT {worktrees} is inside the project {git.repo}: engine"
            " worktrees would land in your checkout; set WORKTREE_ROOT elsewhere"
        )
    for key, value in git.config_entries(_PARTIAL):
        shown = "true" if value is None else value
        if key.startswith("extensions.") or shown.lower() not in _FALSE:
            raise PreflightError(
                f"{git.repo} is a partial clone ({key}={shown}): git would fetch"
                " missing objects lazily. Run 'git fetch --refetch' to download"
                " every object, or use a full clone"
            )
    try:
        head = git.head_commit()
    except GitError as error:
        raise PreflightError(f"{git.repo} has no commit at HEAD yet: {error}") from None
    tree = git.tree(head)
    for path, entry in tree.items():
        if entry.kind == "commit" or path.casefold() == ".gitmodules":
            raise PreflightError(f"{path} at {head}: submodules are not supported yet")
        attributes = posixpath.basename(path).casefold() == ".gitattributes"
        if path.casefold() == ".lfsconfig" or (
            attributes and _has_lfs(git.read_blob(head, path))
        ):
            raise _lfs_refusal(path)
    info = git.common_dir() / "info" / "attributes"
    if _has_lfs(_read_head(info)):
        raise _lfs_refusal(str(info))
    return head, tree


def _lfs_refusal(source: str) -> PreflightError:
    return PreflightError(
        f"LFS is configured in {source}: LFS repositories are not supported yet"
        " (the engine never runs the LFS filter)"
    )


def _check_syntax(
    git: _RepoGit,
    head: str,
    tree: Mapping[str, _Entry],
    cap: int,
    protected: Sequence[str],
) -> list[str]:
    """Refuse an editable ``.py`` blob the engine cannot parse; notes for the rest."""
    notes: list[str] = []
    paths: dict[str, list[str]] = {}  # blob id -> the paths holding it
    sizes: dict[str, int] = {}
    for path, entry in tree.items():
        if entry.mode == _SYMLINK or not matches_pattern(path, "*.py"):
            continue
        if entry.size > cap:
            notes.append(f"{path} was not parsed: {entry.size} bytes > {cap}-byte cap")
        else:
            paths.setdefault(entry.oid, []).append(path)
            sizes[entry.oid] = entry.size
    python = f"the engine's Python {_dotted(_engine_python())}"
    for batch in git.contents(sizes):
        for oid, source in batch.items():
            if (problem := _parse_problem(source, paths[oid][0])) is None:
                continue
            for path in paths[oid]:
                if not any(matches_pattern(path, pattern) for pattern in protected):
                    raise PreflightError(
                        f"{python} cannot parse {path} at {head} ({problem}): run"
                        " the engine on the Python the project targets"
                    )
                notes.append(
                    f"{path} does not parse with {python} ({problem}); it is"
                    " protected, so no trial edits it"
                )
    return notes


def _directories(paths: Iterable[str]) -> frozenset[str]:
    """Every directory holding a tracked entry, ``.`` (the root) included."""
    found = {"."}
    for path in paths:
        parent = posixpath.dirname(path)
        while parent and parent not in found:
            found.add(parent)
            parent = posixpath.dirname(parent)
    return frozenset(found)


def _inline_code(argv: Sequence[str]) -> str | None:
    """A shell or Python anywhere in ``argv`` (env, uv run...) given inline code."""
    for start, arg in enumerate(argv):
        name = posixpath.basename(arg)
        shell = name in _SHELLS
        if shell or _PYTHON.fullmatch(name):
            if (option := _code_option(argv[start + 1 :], shell)) is not None:
                return f"{name} {option}"
    return None


def _code_option(args: Sequence[str], shell: bool) -> str | None:
    """The option making a shell (``-c``, ``-ec``) or Python run a code string."""
    takes, skip = ("oO" if shell else "mWX"), False  # options taking a value
    for arg in args:
        if skip:
            skip = False
        elif arg in ("-", "--") or not arg.startswith(("-", "+") if shell else "-"):
            return None  # the script operand (or stdin) ends the options
        elif arg.startswith("--"):
            if arg.partition("=")[0] == "--command":
                return arg
            skip = arg in _LONG_VALUE
        else:
            for index, letter in enumerate(arg[1:], start=2):
                if letter == "c":
                    return arg
                if letter in takes:
                    if letter == "m":
                        return None  # python -m: the rest belongs to the module
                    skip = index == len(arg)
                    break
    return None


@dataclass
class _Resolver:
    """Resolves commands against the base tree; collects the protected patterns."""

    git: _RepoGit
    head: str
    tree: Mapping[str, _Entry]
    search: str
    protected: set[str] = field(default_factory=set)
    dirs: frozenset[str] = field(init=False)
    folded: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self.dirs = _directories(self.tree)
        self.folded = {path.casefold(): path for path in (*self.tree, *self.dirs)}

    def workload(self, work: Workload) -> Workload:
        what = f"workload {work.name!r}"
        command = self.resolve(work.command, work.working_dir, what)
        return work.model_copy(update={"command": command})

    def resolve(
        self, argv: Sequence[str], workdir: str, what: str, *, suite: bool = False
    ) -> tuple[str, ...]:
        if any("\0" in arg for arg in argv):
            raise PreflightError(f"{what}: an argument contains a NUL byte")
        if (code := _inline_code(argv)) is not None:
            raise PreflightError(
                f"{what}: {code} runs inline code preflight cannot protect: put"
                " it in a script in the repository (then protected) and run that"
            )
        if workdir not in self.dirs:
            message = f"{what}: working_dir {workdir!r} is not a directory at base"
            raise PreflightError(message)
        program = self._program(argv[0], workdir, what)
        modules: list[str] = []
        for index, arg in enumerate(argv[1:], start=1):
            if arg == "-m" and index + 1 < len(argv):
                modules.append(argv[index + 1])
            elif arg.startswith("-m") and len(arg) > 2:
                modules.append(arg[2:])
            values = (arg, arg.partition("=")[2])  # --opt=file, KEY=file
            for value in dict.fromkeys(v.partition("::")[0] for v in values):
                if os.path.isabs(value):
                    self._refuse_checkout_copy(value, workdir, what)
                elif value:
                    self._argument(posixpath.join(workdir, value), what, suite)
        for module in modules:
            if all(part.isidentifier() for part in module.split(".")):
                stem = module.replace(".", "/")
                for top in dict.fromkeys((workdir, ".", "src")):
                    for name in (f"{stem}.py", f"{stem}/__main__.py"):
                        self._argument(posixpath.join(top, name), what, False)
        return (program, *argv[1:])

    def _program(self, name: str, workdir: str, what: str) -> str:
        """``argv[0]``: an absolute executable, a PATH hit, or a protected repo file."""
        here = posixpath.normpath(posixpath.join(workdir, name))
        root = "; argv[0] is relative to the repository root, not working_dir: use"
        beside = "" if workdir == "." else f"{root} {here}"
        if os.path.isabs(name):
            self._refuse_checkout_copy(name, ".", what)
            if not (os.path.isfile(name) and os.access(name, os.X_OK)):
                raise PreflightError(f"{what}: {name} is not an executable file")
            return name
        if "/" not in name and name not in self.tree:
            if (found := shutil.which(name, path=self.search)) is None:
                raise PreflightError(
                    f"{what}: {name!r} is not an executable on PATH (absolute"
                    f" entries only: {self.search}); give an absolute path, or"
                    f" ./{name} for a file in the repository{beside}"
                )
            self._refuse_checkout_copy(found, ".", what)
            return found
        try:
            rel = normalize_path(name)
        except PathTraversalError as error:
            message = f"{what}: {name!r} is neither absolute nor repo-relative: {error}"
            raise PreflightError(message) from None
        links, target = self._walk(rel, what)
        if target is None or target not in self.tree:
            raise PreflightError(
                f"{what}: {rel} is not a file in the repository{beside}"
            )
        if self.tree[target].mode != _EXECUTABLE:
            raise PreflightError(f"{what}: {rel} is not executable: chmod +x, commit")
        self.protected.update(glob.escape(path) for path in (*links, target))
        return rel

    def _refuse_checkout_copy(self, path: str, workdir: str, what: str) -> None:
        """Refuse an absolute ``path`` to a tracked file or directory of the checkout."""
        real = Path(os.path.realpath(path))
        if not real.is_relative_to(self.git.repo):
            return
        rel = real.relative_to(self.git.repo).as_posix()
        if rel in self.tree or rel in self.dirs:
            raise PreflightError(
                f"{what}: {path} is the checkout's {rel}; give the relative path"
                f" {posixpath.relpath(rel, workdir)!r} so each worktree uses its own"
            )

    def _argument(self, path: str, what: str, suite: bool) -> None:
        """Protect the file (or, for the test command, the directory) ``path`` opens."""
        links, target = self._walk(path, what)
        folded = self.folded.get(posixpath.normpath(path).casefold())
        if target is None and not links and folded is not None:
            links, target = self._walk(folded, what)  # a case-insensitive filesystem
        self.protected.update(glob.escape(link) for link in links)
        if target is None:
            return
        if target in self.tree:
            self.protected.add(glob.escape(target))
        elif suite and target not in _UNPROTECTED_DIRS:
            self.protected.add(glob.escape(target) + "/**")

    def _walk(self, path: str, what: str) -> tuple[list[str], str | None]:
        """Follow tree links along ``path``: the links passed, and the entry or
        directory reached (``None`` when it leaves the tree or names nothing)."""
        links: list[str] = []
        todo, done = path.split("/"), "."
        while todo:
            current = posixpath.normpath(posixpath.join(done, todo.pop(0)))
            entry = self.tree.get(current)
            if entry is not None and entry.mode == _SYMLINK:
                if len(links) == _MAX_LINK_HOPS:
                    message = f"{what}: {path} has more than {_MAX_LINK_HOPS} links"
                    raise PreflightError(message)
                links.append(current)
                target = os.fsdecode(self.git.read_blob(self.head, current))
                if target.startswith("/"):
                    return links, None
                todo[:0] = target.split("/")
            elif (entry is None and current not in self.dirs) or (entry and todo):
                # '..' past the root, a missing name, or a file used as a directory
                return links, None
            else:
                done = current
        return links, done


class GitPreflight:
    """The real ``Preflight``: git, the base tree, commands and the sandbox."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        network: IsolationMode | None = None,
        fs: IsolationMode | None = None,
        platform: str = sys.platform,
        search_path: str | None = None,
        run: RunOnce = run_once,
        max_parse_bytes: int = MAX_PARSE_BYTES,
        protected: Sequence[str] = DEFAULT_PROTECTED_PATTERNS,
    ) -> None:
        self._executable = executable or settings.GIT_EXECUTABLE
        self._network, self._fs = network, fs
        self._platform, self._search_path = platform, search_path
        self._run, self._max_parse_bytes = run, max_parse_bytes
        self._protected = tuple(protected)

    def check(
        self,
        project: Project,
        workloads: Sequence[Workload],
        guardrails: Sequence[Guardrail],
    ) -> GitPreflightReport:
        try:
            return self._check(project, workloads, guardrails)
        except PreflightError as error:  # paths and git output are repo-chosen
            raise PreflightError(_quote(str(error))) from None

    def _check(
        self,
        project: Project,
        workloads: Sequence[Workload],
        guardrails: Sequence[Guardrail],
    ) -> GitPreflightReport:
        guarded = any(rail.kind is GuardrailKind.tests_pass for rail in guardrails)
        if guarded and project.test_command is None:
            raise PreflightError(
                "a tests_pass guardrail needs project.test_command (the argv of the"
                " test suite): set it, or drop the guardrail"
            )
        network = settings.NETWORK_ISOLATION if self._network is None else self._network
        fs = settings.FS_ISOLATION if self._fs is None else self._fs
        timeout = settings.GIT_TIMEOUT_S
        git = _RepoGit(
            Path(project.root_path), executable=self._executable, timeout_s=timeout
        )
        try:
            head, tree = _check_repository(git)
            resolver = _Resolver(git, head, tree, self._search())
            resolved = tuple(resolver.workload(work) for work in workloads)
            test_command = project.test_command
            if test_command is not None:
                test_command = resolver.resolve(
                    test_command, ".", "test_command", suite=True
                )
            protected = (*self._protected, *resolver.protected)
            notes = _check_syntax(git, head, tree, self._max_parse_bytes, protected)
            dirty = git.dirty_entries()
            notes += self._probe(network, fs)
            git.prune()
        except (GitError, ValueError) as error:
            raise _git_refusal(git.repo, error) from None
        return GitPreflightReport(
            head_commit=head,
            dirty_entries=dirty,
            git_version=git.version(),
            network=network,
            fs=fs,
            workloads=resolved,
            test_command=test_command,
            extra_protected=tuple(sorted(resolver.protected)),
            python_version=_engine_python(),
            notes=tuple(notes),
        )

    def _search(self) -> str:
        """The PATH a bare name is looked up on: its absolute entries only."""
        raw = self._search_path
        if raw is None:
            raw = os.environ.get("PATH", "")
        entries = [entry for entry in raw.split(os.pathsep) if os.path.isabs(entry)]
        return os.pathsep.join(entries) or os.defpath

    def _probe(self, network: IsolationMode, fs: IsolationMode) -> list[str]:
        """Run ``true`` through the launcher once; notes, or ``PreflightError``."""
        if network == "off" and fs == "off":
            return []
        if self._platform not in PLATFORMS:
            raise PreflightError(
                f"isolation is not supported on {self._platform}: set"
                " NETWORK_ISOLATION=off and FS_ISOLATION=off to run unsandboxed"
            )
        if (true := shutil.which("true", path=SYSTEM_PATH)) is None:
            raise PreflightError(f"the isolation probe needs 'true' in {SYSTEM_PATH}")
        top = Path(os.path.realpath(settings.WORKTREE_ROOT))
        try:
            top.mkdir(mode=0o700, parents=True, exist_ok=True)
            run_dir = Path(tempfile.mkdtemp(prefix=f"{PHASE}-", dir=top))
        except OSError as error:
            message = f"cannot create the probe dir in WORKTREE_ROOT {top}: {error}"
            raise PreflightError(message) from None
        try:
            sample = self._probe_in(run_dir, true, network, fs)
        except RunFailure as failure:
            hint = self._hint(failure.reason, network)
            message = f"the isolation probe failed: {failure.reason}; {hint}"
            raise PreflightError(message) from None
        finally:
            shutil.rmtree(run_dir)
        if sample.exit != 0:
            raise PreflightError(f"the isolation probe's {true} exited {sample.exit}")
        return [f"isolation probe: {note}" for note in sample.notes]

    def _probe_in(
        self, run_dir: Path, true: str, network: IsolationMode, fs: IsolationMode
    ) -> RunSample:
        worktree = run_dir / PHASE
        scratch, probe = run_dir / "_scratch" / PHASE, run_dir / "_probe" / PHASE
        for path in (worktree, scratch, probe):
            path.mkdir(mode=0o700, parents=True)
        policy = SandboxPolicy(network, fs, (worktree, scratch), probe, self._platform)
        home, tmp = scratch / "home", scratch / "tmp"
        env = child_env(home=home, tmpdir=tmp, worktree=worktree)
        args = (
            [true],
            worktree,
            env,
            policy,
            PROBE_TIMEOUT_S,
            OutputCaps.from_settings(),
        )
        return self._run(*args, fresh_dirs=(scratch, home, tmp))

    def _hint(self, reason: str, network: IsolationMode) -> str:
        """The fix for a failed probe, by what failed and on which platform."""
        linux = self._platform == "linux"
        wrapper = reason.startswith("the sandbox wrapper")  # resolve_wrapper
        wrapped = network != "off" or not linux  # darwin wraps whenever a mode is on
        unwrapped = reason.startswith("no measurement report") and wrapped
        if wrapper and linux:
            return (
                "install util-linux (a root-owned unshare in /bin or /usr/bin),"
                " or set NETWORK_ISOLATION=off"
            )
        if unwrapped and linux:
            return (  # best_effort still starts unshare, so it cannot help here
                "unshare could not create its namespaces: on Ubuntu 23.10 and later"
                f" run 'sudo sysctl -w {SYSCTL}=0', or set NETWORK_ISOLATION=off"
            )
        if wrapper or unwrapped:
            return (
                "sandbox-exec could not run or apply the profile: set"
                " NETWORK_ISOLATION=off and FS_ISOLATION=off to run unsandboxed"
            )
        if "fs isolation" in reason:
            kernel = " (Landlock needs Linux 5.13+, landlock in lsm=)" if linux else ""
            return (
                f"set FS_ISOLATION=best_effort to run without write isolation{kernel}"
            )
        if "network isolation" in reason:
            return "set NETWORK_ISOLATION=best_effort to run without network isolation"
        return f"the engine's launcher could not run under {sys.executable}"
