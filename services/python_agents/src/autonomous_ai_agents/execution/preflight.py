"""Connect-time preflight: refuse a repository or host the engine cannot measure.

``GitPreflight.check`` reads the repository only through ``GitWorkspace`` (its
``-c``, attribute and environment overrides), never writes the checkout or a
ref, and ends with ``phase.sweep_stale_runs`` (what a killed run left under
``WORKTREE_ROOT``, one note per run) and ``prune``. A ``PreflightError``
(printable text) names the problem and the fix: ``tests_pass`` without ``project.test_command``; git
< 2.38; dubious ownership (never ``safe.directory``); ``root_path`` not the top
of a work tree, without a commit, or overlapping ``WORKTREE_ROOT`` (the
checkout, the git common dir or another worktree of the repository, or an
unmarked engine leftover at ``<run>/<phase>``, with its recovery); a partial
clone; a crafted tree path, ``.gitmodules`` or a gitlink; LFS (``filter=lfs`` in
any ``.gitattributes`` blob read with ``cat-file``, in ``info/attributes``, or a
root ``.lfsconfig``; no filter runs); a custom merge driver (any
``merge.<name>.*`` key) a ``merge=`` attribute or ``merge.default`` selects
(``union``, ``ours`` and binary merges are notes: the combined tip is re-tested
anyway); an editable ``.py`` blob the engine's
Python cannot parse (a protected one is a note); an unresolvable command; or a
failed isolation probe (``true`` once through ``run_once`` and the launcher's
write and connect self-checks, in a fresh ``WORKTREE_ROOT/preflight-*``).

``_Resolver``: ``argv[0]`` is absolute, a hit on the absolute PATH entries, or
a repo executable reached through links that stay in the tree (as ``measure``
requires). Arguments naming base-tree files (``--opt=`` values, node ids, ``-m``
targets, through links, in any case) are protected, as is a directory the test
command names (not the root or ``src``), and every workload's ``output_file``,
which may not be committed (the reset would restore it before every run). A
tracked path given absolutely (the run would use the checkout's copy) and
inline shell or Python code are refused.

Merge attributes are parsed here, never through ``check-attr`` (the engine's
``--attr-source`` hides blobs from it), as git does: comments, a UTF-8 BOM,
quoted patterns, a NUL ending a blob (a file's line), lines of 2048 bytes or
an invalid attribute name dropped, ``-merge=x`` read as ``-merge``, and
``[attr]`` macros (the built-in ``binary`` too) resolved once each through
chains and loops (Tarjan's components: linear, never recursive). The engine's
``merge-tree`` reads ``<common-dir>/info/attributes`` (shared by linked
worktrees), the ``core.attributesFile`` its git reports (its ``-c`` pins
``/dev/null``) and ``merge.default``; on git < 2.40 (no ``--attr-source``) also
the checkout's ``.gitattributes`` (a directory link is followed, a link as the
file is not, as git opens them) and the index's, and there the base tree's
blobs count with them. Those sources refuse or note. On git >= 2.40 the base
tree's blobs (any depth, any case) are never read by a combine: what they set
is one note (the user's own merges differ). Macros count from any source read,
not only the top level as git does: that can only add a note or a refusal.
Valueless ``merge.default`` or ``merge.<name>.driver``/``name``/``recursive``
keys are refused: git dies on them in every content merge. Attribute files
over ``_MAX_ATTRIBUTES_BYTES`` are refused rather than checked in part.
"""

from __future__ import annotations

import ast
import codecs
import glob
import itertools
import os
import posixpath
import re
import shutil
import sys
import tempfile
import warnings
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
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
from autonomous_ai_agents.execution.git import (
    ATTR_SOURCE_SINCE,
    GitError,
    GitWorkspace,
)
from autonomous_ai_agents.execution.measure import RunOnce
from autonomous_ai_agents.execution.phase import (
    PROBE,
    RUN_LOCK,
    SCRATCH,
    require_dir_name,
    sweep_stale_runs,
)
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
_ATTRIBUTES_SPEC = ":(glob,icase)**/.gitattributes"
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_ATTR_WORD = re.compile(rb"[^ \t\r\n]+")
_ATTR_QUOTED = re.compile(rb'"(?:[^"\\]|\\.)*"')
_OCTAL = re.compile(rb"[0-3][0-7]{2}")
_C_ESCAPES = dict(zip(b'\\"abfnrtv', b'\\"\a\b\f\n\r\t\v', strict=True))
_MACRO = b"[attr]"
_BINARY = (b"-diff", b"-merge", b"-text")
"""git's built-in ``binary`` macro."""
_ATTR_TOKEN = re.compile(rb"[!-]?[A-Za-z0-9_.][-A-Za-z0-9_.]*(=.*)?", re.DOTALL)
"""A token git accepts; one invalid name drops the whole line."""
_MAX_LINE = 2048
"""git ignores an attributes line of this many bytes or more."""
_MERGE_KEYS = r"^merge\.(default|.*\..+)$"
"""``merge.default`` and every ``merge.<name>.<var>`` (``<name>`` may be empty):
any such key makes ``<name>`` a user driver that shadows a built-in (git dies
without a command)."""
_NEEDS_VALUE = frozenset({"driver", "name", "recursive"})
"""``merge.<name>.<var>`` keys git dies on when valueless (as ``merge.default``)."""
_MERGE_NOTES = {
    "union": (
        "merge=union",
        "git merge-tree keeps both sides' lines instead of reporting a conflict,"
        " so a combine can join two kept changes into code no trial ran alone;"
        " the combined tip is still fully re-tested",
    ),
    "ours": (
        "merge=ours",
        "git has no built-in ours driver and none is configured, so git"
        " merge-tree uses its 3-way text merge for these paths",
    ),
    "binary": (
        "a binary merge (merge=binary, -merge)",
        "git merge-tree reports a conflict whenever two kept changes touch"
        " these paths, so the combine keeps only one of them",
    ),
}
_COMMITTED_NOTE = (
    "the engine's combines do not read committed .gitattributes (its git"
    " >= 2.40 runs merge-tree with --attr-source=<empty tree>), so a combine"
    " 3-way merges these paths and may conflict where your own merges would"
    " not, and the delivered branch may merge differently under your git"
)
_SHOWN = 3
"""Places a merge note lists before 'and N more'."""

_Setting = tuple[bool, str]
"""One merge setting: ``(True, "")`` for ``-merge``, else ``(False, value)``."""


@dataclass(frozen=True)
class GitPreflightReport(PreflightReport):
    """The protocol's report with ``notes`` and ``python_version`` required."""

    notes: tuple[str, ...] = field()  # field(): no default inherited from the base
    python_version: tuple[int, int, int] = field()


@dataclass
class _Places:
    """Where one merge setting is made: the first places read, and how many."""

    first: list[tuple[tuple[int, int], str, str]] = field(default_factory=list)
    """``(order read, source, "source (pattern)")``."""
    count: int = 0

    def add(self, order: tuple[int, int], source: str, shown: str) -> None:
        self.count += 1
        if len(self.first) < _SHOWN:
            self.first.append((order, source, shown))


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

    def attributes_file(self) -> Path:
        """The ``core.attributesFile`` this git reads (``/dev/null`` if unset)."""
        argv = ("config", "-z", "--type=path", "--get", "core.attributesFile")
        value = os.fsdecode(self._run(*argv, ok=(0, 1)).rstrip(b"\0"))
        return Path(self.repo, value or os.devnull)

    def checkout_attributes(self) -> Iterator[tuple[str, bytes]]:
        """The index's and the checkout's ``.gitattributes`` (old git reads them)."""
        listing = self._run("ls-files", "-z", "-s", "--", _ATTRIBUTES_SPEC)
        for record in filter(None, listing.split(b"\0")):
            meta, _, raw = record.partition(b"\t")
            oid = (meta.split(b" ")[1:2] or [b""])[0].decode("ascii", "replace")
            if _OID.fullmatch(oid) is None:
                raise GitError(f"unexpected object id in ls-files output: {oid!r}")
            label = f"the index's {os.fsdecode(raw)}"
            if int(self._run("cat-file", "-s", oid)) > _MAX_ATTRIBUTES_BYTES:
                raise _too_large(label)
            yield label, self._run("cat-file", "blob", oid).partition(b"\0")[0]
        listing = self._run(
            "ls-files", "-z", "--cached", "--others", "--", _ATTRIBUTES_SPEC
        )
        for raw in filter(None, listing.split(b"\0")):
            label, path = (
                f"the checkout's {os.fsdecode(raw)}",
                self.repo / os.fsdecode(raw),
            )
            if not Path(os.path.realpath(path.parent)).is_relative_to(self.repo):
                label += " (through a directory link)"  # git's open follows it
            yield label, _read_head(path, False)

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


def _read_head(path: Path, follow: bool = True) -> bytes:
    """A file git would read (``O_NOFOLLOW`` on the last component unless
    ``follow``); nothing when it cannot be read, refused past the cap."""
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        fd = os.open(path, flags if follow else flags | os.O_NOFOLLOW)
        try:
            data = os.read(fd, _MAX_ATTRIBUTES_BYTES + 1)
        finally:
            os.close(fd)
    except OSError:
        return b""
    if len(data) > _MAX_ATTRIBUTES_BYTES:
        raise _too_large(str(path))
    return data


def _too_large(source: str) -> PreflightError:
    return PreflightError(
        f"{source} is larger than the {_MAX_ATTRIBUTES_BYTES} bytes preflight"
        " reads (git reads attribute files up to 100 MB): shrink it to connect"
    )


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


def _overlaps(a: Path, b: Path) -> bool:
    return a.is_relative_to(b) or b.is_relative_to(a)


def _engine_shaped(root: Path, path: Path) -> bool:
    """Whether ``path`` is ``<root>/<run>/<phase>``, as ``phase_dirs`` lays a
    phase's worktree out."""
    if path.parent.parent != root or path.name in (SCRATCH, PROBE):
        return False
    try:
        require_dir_name("run id", path.parent.name)
        require_dir_name("phase", path.name)
    except ValueError:
        return False
    return True


def _unmarked_leftover(git: _RepoGit, root: Path, path: Path) -> PreflightError:
    """The refusal for an unmarked ``<run>/<phase>``-shaped worktree. Its shape
    is also a common layout for the user's own worktrees, so the message
    claims no owner and its advice cannot destroy work: plain ``git worktree
    remove`` refuses while the worktree holds uncommitted changes."""
    return PreflightError(
        f"WORKTREE_ROOT {root} holds {path}, a worktree of the repository at"
        f" {git.repo} that no engine run marks. An earlier engine run may have"
        " left it (its cleanup failed, or it was killed before run markers"
        " existed), or it may be yours; connect never removes it. If it is an"
        f" engine leftover, run 'git worktree remove {path}' (git refuses while"
        " it holds uncommitted work: look at that work before you remove it)"
        f" and remove {path.parent}; if it is yours, set WORKTREE_ROOT to a"
        " directory outside every checkout"
    )


def _check_worktree_root(git: _RepoGit) -> None:
    """``WORKTREE_ROOT`` may not overlap the checkout, the git common dir (its
    admin dirs, a linked worktree's main repository) or any other worktree
    of the repository: the engine's cleanup removes what is under it, and
    the user's ``git clean`` there would remove the engine's live dirs. An
    engine worktree (in a marked ``<run>``) and a stale registration under
    it are no overlap; connect sweeps or prunes them. An unmarked worktree
    laid out as ``<run>/<phase>`` may be an engine leftover or the user's own:
    connect never removes it, and the refusal claims no owner."""
    root = Path(os.path.realpath(settings.WORKTREE_ROOT))
    if root.is_relative_to(git.repo):
        raise PreflightError(
            f"WORKTREE_ROOT {root} is inside the project {git.repo}: engine"
            " worktrees would land in your checkout; set WORKTREE_ROOT elsewhere"
        )
    places = [("the git dir", git.common_dir())]
    leftovers: list[Path] = []
    for listed, prunable in git.registered_worktrees():
        path = Path(os.path.realpath(listed))
        if prunable:
            continue
        if path.is_relative_to(root):
            if (path.parent / RUN_LOCK).is_file():
                continue
            if _engine_shaped(root, path):
                leftovers.append(path)
                continue
        places.append(("the worktree", path))
    for what, place in places:
        if _overlaps(root, place):
            raise PreflightError(
                f"WORKTREE_ROOT {root} overlaps {what} {place} of the repository at"
                f" {git.repo}: set WORKTREE_ROOT to a directory outside every"
                " checkout and the .git directory of the repository"
            )
    if leftovers:
        raise _unmarked_leftover(git, root, leftovers[0])


def _check_repository(
    git: _RepoGit,
) -> tuple[str, dict[str, _Entry], list[tuple[str, bytes]]]:
    """Version, shape, partial clone, conditional includes, submodules and
    LFS: the head, its tree, and the attribute files read (``(label, bytes)``)."""
    if (version := git.version()) < MIN_GIT_VERSION:
        raise PreflightError(
            f"git {_dotted(version)} is older than 2.38 (merge-tree --write-tree):"
            " install git 2.38 or newer, or point GIT_EXECUTABLE at one"
        )
    if (top := git.toplevel()) != git.repo:
        message = f"{git.repo} is not the top of its work tree: set root_path to {top}"
        raise PreflightError(message)
    _check_worktree_root(git)
    for key, value in git.config_entries(_PARTIAL):
        shown = "true" if value is None else value
        if key.startswith("extensions.") or shown.lower() not in _FALSE:
            raise PreflightError(
                f"{git.repo} is a partial clone ({key}={shown}): git would fetch"
                " missing objects lazily. Run 'git fetch --refetch' to download"
                " every object, or use a full clone"
            )
    if conditional := git.config_entries(r"^includeif\."):
        raise PreflightError(
            f"{conditional[0][0]} in the repository config: a conditional include"
            " can hold in a git child (the checkout of a linked worktree) and not"
            " where the engine vets the config, so a driver it defines could run."
            " To connect, copy what it includes into .git/config and remove the key"
        )
    try:
        head = git.head_commit()
    except GitError as error:
        raise PreflightError(f"{git.repo} has no commit at HEAD yet: {error}") from None
    tree = git.tree(head)
    attributes: list[tuple[str, bytes]] = []
    for path, entry in tree.items():
        if entry.kind == "commit" or path.casefold() == ".gitmodules":
            raise PreflightError(f"{path} at {head}: submodules are not supported yet")
        if path.casefold() == ".lfsconfig":
            raise _lfs_refusal(path)
        if posixpath.basename(path).casefold() == ".gitattributes":
            if entry.size > _MAX_ATTRIBUTES_BYTES:
                raise _too_large(path)
            data = git.read_blob(head, path, limit=_MAX_ATTRIBUTES_BYTES)
            if _has_lfs(data):
                raise _lfs_refusal(path)
            attributes.append((path, data.partition(b"\0")[0]))  # git stops there
    info = git.common_dir() / "info" / "attributes"
    if _has_lfs(data := _read_head(info)):
        raise _lfs_refusal(str(info))
    return head, tree, [*attributes, (str(info), data)]


def _lfs_refusal(source: str) -> PreflightError:
    return PreflightError(
        f"LFS is configured in {source}: LFS repositories are not supported yet"
        " (the engine never runs the LFS filter)"
    )


def _unquote(quoted: bytes) -> bytes | None:
    """git's C-style unquoting of a ``"..."`` pattern; ``None`` when invalid."""
    body, out, index = quoted[1:-1], bytearray(), 0
    while index < len(body):
        if body[index] != ord("\\"):
            out.append(body[index])
            index += 1
        elif _OCTAL.fullmatch(body, index + 1, index + 4):
            out.append(int(body[index + 1 : index + 4], 8))
            index += 4
        elif (escaped := _C_ESCAPES.get(body[index + 1])) is not None:
            out.append(escaped)
            index += 2
        else:
            return None
    return bytes(out)


def _attribute_lines(
    data: bytes,
) -> Iterator[tuple[bytes, bytes | None, list[bytes]]]:
    """``(pattern, macro name or None, tokens)`` per line git keeps."""
    for line in data.removeprefix(codecs.BOM_UTF8).split(b"\n"):
        line = line.partition(b"\0")[0]  # a file's line ends at a NUL (strlen)
        if len(line.removesuffix(b"\r")) >= _MAX_LINE:
            continue
        line = line.lstrip(b" \t\r")
        if not line or line.startswith(b"#"):
            continue
        quoted = _ATTR_QUOTED.match(line)
        name = None if quoted is None else _unquote(quoted.group())
        if quoted is not None and name is not None:
            pattern, tokens = quoted.group(), _ATTR_WORD.findall(line[quoted.end() :])
        else:  # git's fallback when the quoting is invalid: split at blanks
            words = _ATTR_WORD.findall(line)
            pattern = name = words[0]
            tokens = words[1:]
        if all(_ATTR_TOKEN.fullmatch(token) for token in tokens):
            macro = name[len(_MACRO) :] if name.startswith(_MACRO) else None
            yield pattern, macro or None, tokens


def _token(token: bytes) -> tuple[_Setting | None, bytes | None]:
    """The merge setting a valid token makes, or the macro it may name."""
    if token[:1] in (b"-", b"!"):  # git drops a value after - or !
        merge = token[1:].partition(b"=")[0] == b"merge" and token[:1] == b"-"
        return ((True, "") if merge else None), None
    name, equals, value = token.partition(b"=")
    if equals:
        return ((False, os.fsdecode(value)) if name == b"merge" else None), None
    return None, token  # only a set macro expands


def _expand(
    macros: Mapping[bytes, Sequence[Sequence[bytes]]],
    relevant: Callable[[_Setting], bool],
) -> dict[bytes, frozenset[_Setting]]:
    """The relevant settings each macro reaches through all its definitions,
    by Tarjan's components (iterative): linear in the definitions."""
    own: dict[bytes, set[_Setting]] = {}
    edges: dict[bytes, list[bytes]] = {}
    for macro, definitions in macros.items():
        own[macro], edges[macro] = set(), []
        for setting, name in map(_token, itertools.chain.from_iterable(definitions)):
            if setting is not None and relevant(setting):
                own[macro].add(setting)
            elif name is not None and name in macros:
                edges[macro].append(name)
    done: dict[bytes, frozenset[_Setting]] = {}
    index: dict[bytes, int] = {}
    low: dict[bytes, int] = {}
    stack: list[bytes] = []
    for root in macros:
        work = [] if root in index else [(root, 0)]
        while work:
            node, at = work.pop()
            if at == 0:
                index[node] = low[node] = len(index)
                stack.append(node)
            if at < len(edges[node]):
                work.append((node, at + 1))
                if (succ := edges[node][at]) not in index:
                    work.append((succ, 0))
                elif succ not in done:  # still on the stack: one component
                    low[node] = min(low[node], index[succ])
                continue
            if low[node] == index[node]:
                members = [stack.pop()]
                while members[-1] != node:
                    members.append(stack.pop())
                reached = set().union(*(own[member] for member in members))
                for succ in itertools.chain.from_iterable(edges[m] for m in members):
                    reached.update(done.get(succ, ()))
                done.update(dict.fromkeys(members, frozenset(reached)))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return done


def _merge_places(
    sources: Sequence[tuple[str, bytes]],
    macro_sources: Sequence[tuple[str, bytes]],
    relevant: Callable[[_Setting], bool],
) -> dict[_Setting, _Places]:
    """Where ``sources`` make each relevant setting, with the macros
    ``macro_sources`` define."""
    macros: dict[bytes, list[Sequence[bytes]]] = {b"binary": [_BINARY]}
    for _, data in macro_sources:
        for _, macro, tokens in _attribute_lines(data):
            if macro is not None:
                macros.setdefault(macro, []).append(tokens)
    expanded = _expand(macros, relevant)
    places: dict[_Setting, _Places] = {}
    for at, (label, data) in enumerate(sources):
        for line, (pattern, macro, tokens) in enumerate(_attribute_lines(data)):
            if macro is not None:
                continue  # a definition sets nothing by itself
            found: set[_Setting] = set()
            for setting, name in map(_token, tokens):
                if setting is not None and relevant(setting):
                    found.add(setting)
                elif name is not None:
                    found.update(expanded.get(name, ()))
            text = pattern.decode("utf-8", "backslashreplace") if found else ""
            shown = f"{label} ({text})"
            for setting in sorted(found):
                places.setdefault(setting, _Places()).add((at, line), label, shown)
    return places


def _merge_config(git: _RepoGit) -> tuple[dict[str, str], list[str]]:
    """The user drivers (name -> the first key defining it) and the
    ``merge.default`` values; a valueless key git dies on is refused."""
    drivers: dict[str, str] = {}
    defaults: list[str] = []
    for key, value in git.config_entries(_MERGE_KEYS):
        default = key == "merge.default"
        if not default:
            drivers.setdefault(key.removeprefix("merge.").rpartition(".")[0], key)
        if value is None and (default or key.rpartition(".")[2] in _NEEDS_VALUE):
            raise PreflightError(
                f"{key} in the repository config has no value: git stops every"
                " content merge with 'bad config variable'. To connect, set a"
                " value or remove it"
            )
        if default and value is not None:
            defaults.append(value)
    return drivers, defaults


def _check_merge(
    git: _RepoGit,
    committed: Sequence[tuple[str, bytes]],
    info: tuple[str, bytes],
) -> list[str]:
    """Refuse a custom merge driver that a source the engine's merge-tree reads
    selects; notes for union, ours and binary merges, and for what committed
    files set where the engine's git never reads them."""
    drivers, defaults = _merge_config(git)
    path = git.attributes_file()
    read = [info, (f"core.attributesFile {path}", _read_head(path))]
    old = git.version() < ATTR_SOURCE_SINCE  # no --attr-source: the checkout counts
    if old:
        read = [*committed, *read, *git.checkout_attributes()]
    places = _merge_places(
        read, read, lambda s: s[0] or s[1] in drivers or s[1] in _MERGE_NOTES
    )
    where = "the repository config's merge.default"
    for value in defaults:
        places.setdefault((False, value), _Places()).add((len(read), 0), where, where)
    kinds: dict[str, list[_Places]] = {}
    for (unset, value), found in sorted(places.items()):
        if not unset and value in drivers:
            _, source, shown = found.first[0]
            named = value or '""'
            raise PreflightError(
                f"{shown} selects merge={named}, a custom merge driver"
                f" ({drivers[value]} in the repository config): the engine never"
                " runs merge drivers, so its combines would differ from your"
                f" merges. To connect, remove merge={value} from {source} or the"
                f" merge.{value}.* keys from the repository config"
            )
        kinds.setdefault("binary" if unset else value, []).append(found)
    notes = [
        f"{label} in {_listing(kinds[kind])}: {effect}"
        for kind, (label, effect) in _MERGE_NOTES.items()
        if kind in kinds
    ]
    if old:
        return notes
    changes = {"union", "binary", *drivers}  # ours: both gits 3-way merge it
    sources = [*committed, *read]
    ignored = _merge_places(committed, sources, lambda s: s[0] or s[1] in changes)
    if ignored:
        names = ", ".join("-merge" if u else f"merge={v}" for u, v in sorted(ignored))
        notes.append(f"{names} in {_listing(ignored.values())}: {_COMMITTED_NOTE}")
    return notes


def _listing(groups: Iterable[_Places]) -> str:
    groups = list(groups)
    first = sorted(itertools.chain.from_iterable(group.first for group in groups))
    total = sum(group.count for group in groups)
    more = f" and {total - _SHOWN} more" if total > _SHOWN else ""
    return ", ".join(shown for _, _, shown in first[:_SHOWN]) + more


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
        if work.output_file is not None:
            self._output_file(work.output_file, what)
        return work.model_copy(update={"command": command})

    def _output_file(self, rel: str, what: str) -> None:
        """Refuse a committed ``output_file`` (the reset before every run
        restores it, so the fingerprint would read it whether or not the run
        wrote it); protect the path, so no trial commits one either."""
        links, target = self._walk(rel, what)
        if target is not None and target in self.tree:
            raise PreflightError(
                f"{what}: output_file {rel} is committed ({target}): the reset"
                " before every run restores it, so a run that never writes it"
                f" would still be fingerprinted. Run 'git rm --cached {target}',"
                " ignore it in .gitignore and commit"
            )
        self.protected.update(glob.escape(path) for path in (*links, rel))

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
            head, tree, attributes = _check_repository(git)
            notes = _check_merge(git, attributes[:-1], attributes[-1])
            resolver = _Resolver(git, head, tree, self._search())
            resolved = tuple(resolver.workload(work) for work in workloads)
            test_command = project.test_command
            if test_command is not None:
                test_command = resolver.resolve(
                    test_command, ".", "test_command", suite=True
                )
            protected = (*self._protected, *resolver.protected)
            notes += _check_syntax(git, head, tree, self._max_parse_bytes, protected)
            dirty = git.dirty_entries()
            notes += self._probe(network, fs)
            notes += sweep_stale_runs(git)
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
            notes=tuple(_quote(note) for note in notes),
            python_version=_engine_python(),
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
