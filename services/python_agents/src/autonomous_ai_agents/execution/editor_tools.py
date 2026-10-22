"""The worktree-confined handler behind Claude's text editor tool (unit U7).

``WorktreeEditor`` runs the ``text_editor_20250728`` commands (``view``,
``create``, ``str_replace``, ``insert``) in one trial worktree that Claude only
sees as ``/repo``; the real path never appears in a result. Rules, in code:

- Strict input: unknown keys, missing fields, wrong types are errors;
  ``undo_edit`` (retired by the tool version) is refused.
- Paths are absolute under ``/repo/``, free of ``C*`` (control, format,
  surrogate, unassigned) characters, line and paragraph separators and
  backslashes, then NFC and ``normalize_path``.
- Every command refuses a ``GIT_METADATA_NAMES`` component (case-insensitive:
  APFS folds case, and ``.git`` names the user's real git dir) and a path that
  is or lies inside a ``READ_DENY_PATTERNS`` match (reads reach the API;
  ``str_replace`` match counts are an oracle). Writes also refuse
  ``WRITE_DENY_PATTERNS``, the trial's protected patterns, and a new top-level
  module or package in ``/repo`` or ``/repo/src`` (first on a trial's
  ``sys.path``) named after a reserved module: shadowing the stdlib or the
  test runner can make a failing suite pass.
- Each existing component is ``lstat``-ed: a symlink is refused, never
  resolved, and files open with ``O_NOFOLLOW``. Only regular files with one
  hard link are read or written (another link may live outside the root).
  Writes go to a new temporary file that then replaces the target, so a
  failed write keeps the old content.
- Per-file, file-count and total-byte limits from settings; results capped.

No trial code runs while the editor works, so nothing races these checks;
the git-side capture rules audit the outcome afterwards.
"""

from __future__ import annotations

import contextlib
import os
import stat
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.paths import (
    GIT_METADATA_NAMES,
    READ_DENY_PATTERNS,
    WRITE_DENY_PATTERNS,
    PathTraversalError,
    matches_pattern,
    normalize_path,
)

# Top-level names a write may not newly add in /repo or /repo/src: one
# definition in common/paths.py, shared with the module_shadow capture rule.
from autonomous_ai_agents.common.paths import RESERVED_MODULES as RESERVED_MODULES
from autonomous_ai_agents.common.paths import RUNNER_MODULES as RUNNER_MODULES

VIRTUAL_ROOT = "/repo"  # the only root Claude sees
VIEW_MAX_CHARS = 20_000  # default result cap; the tool's ``max_characters``
LIST_DEPTH = 2  # a directory view lists this many levels below it
LIST_MAX_ENTRIES = 500  # ... and stops after this many entries
SNIPPET_CONTEXT = 4  # lines shown around an edit in its result

_Stat = os.stat_result | None
_GIT_NAMES = frozenset(name.casefold() for name in GIT_METADATA_NAMES)
_UNPRINTABLE = ("C", "Zl", "Zp")  # Unicode categories; Zl/Zp split a line
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_TEMP_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True)
class ToolOutcome:
    """A ``tool_result``'s text and whether it reports an error."""

    content: str
    is_error: bool = False


@dataclass(frozen=True)
class EditorLimits:
    """Per-trial write limits and the result cap; every value at least 1."""

    max_files: int
    max_file_bytes: int
    max_total_bytes: int
    max_view_chars: int = VIEW_MAX_CHARS

    def __post_init__(self) -> None:
        for spec in fields(self):
            if getattr(self, spec.name) < 1:
                raise ValueError(f"{spec.name} must be at least 1")

    @classmethod
    def from_settings(cls, config: Settings | None = None) -> EditorLimits:
        source = settings if config is None else config
        return cls(
            max_files=source.EDITOR_MAX_FILES,
            max_file_bytes=source.EDITOR_MAX_FILE_BYTES,
            max_total_bytes=source.EDITOR_MAX_TOTAL_BYTES,
        )


class _Command(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: str


class _View(_Command):
    command: Literal["view"]
    view_range: list[int] | None = Field(default=None, min_length=2, max_length=2)


class _Create(_Command):
    command: Literal["create"]
    file_text: str


class _StrReplace(_Command):
    command: Literal["str_replace"]
    old_str: str
    new_str: str = ""


class _Insert(_Command):
    command: Literal["insert"]
    insert_line: int
    insert_text: str


_AnyCommand = _View | _Create | _StrReplace | _Insert
_COMMAND: TypeAdapter[_AnyCommand] = TypeAdapter(
    Annotated[_AnyCommand, Field(discriminator="command")]
)


class _EditError(Exception):
    """Becomes an ``is_error`` result; never escapes ``execute``."""


class WorktreeEditor:
    """Executes text editor tool commands inside one worktree, seen as ``/repo``.

    ``protected`` are the trial's protected patterns, enforced on writes, and
    ``reserved_modules`` the full set of top-level module names a write may
    not add (see ``RESERVED_MODULES``). ``written`` maps each repo-relative
    path to the bytes written to it so far, for the ``unrecorded_write`` rule.
    """

    def __init__(
        self,
        root: Path,
        *,
        protected: Sequence[str],
        limits: EditorLimits | None = None,
        reserved_modules: Collection[str] = RESERVED_MODULES,
    ) -> None:
        real = Path(os.path.realpath(root, strict=True))
        if not real.is_dir():
            raise ValueError(f"editor root {root} is not a directory")
        self._root = real
        self._protected = tuple(protected)
        self._reserved = frozenset(name.casefold() for name in reserved_modules)
        self._limits = EditorLimits.from_settings() if limits is None else limits
        self._written: dict[str, int] = {}

    @property
    def limits(self) -> EditorLimits:
        return self._limits

    @property
    def written(self) -> Mapping[str, int]:
        """A read-only snapshot: repo-relative path -> bytes written so far."""
        return MappingProxyType(dict(self._written))

    def execute(self, command_input: Mapping[str, object]) -> ToolOutcome:
        """Run one command; every refusal or failure is an ``is_error`` result."""
        try:
            if command_input.get("command") == "undo_edit":
                raise _EditError("undo_edit is not supported")
            content = self._dispatch(_COMMAND.validate_python(dict(command_input)))
            return ToolOutcome(self._cap(content))
        except ValidationError as exc:
            message = _describe(exc)
        except _EditError as exc:
            message = str(exc)
        return ToolOutcome(self._cap(message), is_error=True)

    def _dispatch(self, command: _AnyCommand) -> str:
        rel = self._resolve(command.path, write=not isinstance(command, _View))
        try:
            info = self._walk(rel)
            if info is not None and not stat.S_ISDIR(info.st_mode):
                if not stat.S_ISREG(info.st_mode):
                    raise _EditError(f"{_show(rel)} is not a regular file")
                if info.st_nlink > 1:
                    raise _EditError(f"{_show(rel)} has another hard link: refused")
            if isinstance(command, _View):
                return self._view(rel, info, command.view_range)
            if isinstance(command, _Create):
                return self._create(rel, info, command.file_text)
            if isinstance(command, _StrReplace):
                return self._str_replace(rel, info, command.old_str, command.new_str)
            return self._insert(rel, info, command.insert_line, command.insert_text)
        except OSError as exc:
            raise _EditError(f"{_show(rel)}: {exc.strerror or 'I/O error'}") from exc

    def _resolve(self, raw: str, *, write: bool) -> str:
        """The repo-relative path for ``raw``, refused unless every rule allows it."""
        if _unprintable(raw):
            raise _EditError(f"path {raw!r} holds control or unprintable characters")
        text = unicodedata.normalize("NFC", raw)
        if "\\" in text:
            raise _EditError(f"path {raw!r} holds a backslash: use '/' separators")
        if text != VIRTUAL_ROOT and not text.startswith(VIRTUAL_ROOT + "/"):
            raise _EditError(f"path {raw!r} must be absolute under {VIRTUAL_ROOT}/")
        try:
            rel = normalize_path(text[len(VIRTUAL_ROOT) + 1 :])
        except PathTraversalError as exc:
            raise _EditError(f"path {raw!r} leaves {VIRTUAL_ROOT} ('..', '~')") from exc
        parts = rel.split("/")
        for depth, part in enumerate(parts, 1):
            if part.casefold() in _GIT_NAMES:
                raise _EditError(f"{_show(rel)}: git metadata is off limits")
            scope = "/".join(parts[:depth])  # a secret directory's files too
            if (secret := _first_match(scope, READ_DENY_PATTERNS)) is not None:
                raise _EditError(
                    f"{_show(scope)} may hold secrets ({secret}): off limits"
                )
        if not write:
            return rel
        if rel == ".":
            raise _EditError(f"{VIRTUAL_ROOT} is a directory: name a file to write")
        if (compiled := _first_match(rel, WRITE_DENY_PATTERNS)) is not None:
            raise _EditError(f"{_show(rel)} is a compiled artefact ({compiled})")
        if (rule := _first_match(rel, self._protected)) is not None:
            raise _EditError(
                f"{_show(rel)} is protected ({rule}): tests, benchmarks, config "
                "and the harness are off limits"
            )
        if (name := self._shadowed(parts)) is not None:
            raise _EditError(
                f"{_show(rel)} would add a top-level module {name!r} that shadows "
                "the standard library or the test runner: choose another name"
            )
        return rel

    def _shadowed(self, parts: Sequence[str]) -> str | None:
        """The reserved module a write would newly add at ``.`` or ``src``."""
        nested = len(parts) > 1 and parts[0].casefold() == "src"
        for start in (0, 1) if nested else (0,):
            top = parts[start].casefold()
            if start + 1 < len(parts):
                name = top  # a directory: a package or a namespace portion
            elif top.endswith(".py"):
                name = top.removesuffix(".py")
            else:
                continue  # a data file is not importable
            entry = self._root.joinpath(*parts[: start + 1])
            if name in self._reserved and not os.path.lexists(entry):
                return name  # an entry the user's repo already has stays editable
        return None

    def _walk(self, rel: str) -> _Stat:
        """``lstat`` each component; ``None`` when the target does not exist yet."""
        parts = [] if rel == "." else rel.split("/")
        node = self._root
        info = os.lstat(node)
        for index, part in enumerate(parts):
            if not stat.S_ISDIR(info.st_mode):
                parent = _show("/".join(parts[:index]))
                raise _EditError(f"{_show(rel)}: {parent} is not a directory")
            node = node / part
            try:
                info = os.lstat(node)
            except FileNotFoundError:
                return None
            if stat.S_ISLNK(info.st_mode):
                link = _show("/".join(parts[: index + 1]))
                raise _EditError(f"{_show(rel)}: {link} is a symlink, never followed")
        return info

    def _view(self, rel: str, info: _Stat, span: list[int] | None) -> str:
        if info is not None and stat.S_ISDIR(info.st_mode):
            if span is not None:
                raise _EditError("view_range cannot be used on a directory")
            return self._listing(rel)
        lines = _split(self._read(rel, info))
        if span is None:
            return _numbered(lines, 1) if lines else f"{_show(rel)} is empty."
        start, end = span
        last = len(lines) if end == -1 else end
        if not 1 <= start <= last <= len(lines):
            raise _EditError(
                f"view_range {span} is outside {_show(rel)}, which has {len(lines)} "
                "lines: use [start, end], 1 <= start <= end <= that, or end -1"
            )
        return _numbered(lines[start - 1 : last], start)

    def _create(self, rel: str, info: _Stat, text: str) -> str:
        if info is not None and stat.S_ISDIR(info.st_mode):
            raise _EditError(f"{_show(rel)} is a directory")
        data = _encode(rel, text)
        self._write(rel, info, data)
        verb = "Created" if info is None else "Overwrote"
        return f"{verb} {_show(rel)} ({len(data)} bytes)."

    def _str_replace(self, rel: str, info: _Stat, old: str, new: str) -> str:
        if not old:
            raise _EditError("old_str must not be empty")
        text = self._read(rel, info)
        first = text.find(old)
        if first < 0:
            raise _EditError(f"no match for old_str in {_show(rel)}: copy it exactly")
        if text.find(old, first + 1) >= 0:
            count = max(text.count(old), 2)
            raise _EditError(
                f"old_str occurs {count} times in {_show(rel)}; it must occur exactly "
                "once: add surrounding lines"
            )
        updated = text[:first] + new + text[first + len(old) :]
        self._write(rel, info, _encode(rel, updated))
        start = text.count("\n", 0, first) + 1
        return _edited(rel, updated, start, start + new.count("\n"))

    def _insert(self, rel: str, info: _Stat, line: int, text: str) -> str:
        lines = _split(self._read(rel, info))
        if not 0 <= line <= len(lines):
            raise _EditError(
                f"insert_line {line} is outside {_show(rel)}, which has {len(lines)} "
                "lines: use 0 (before the first) up to that count (after the last)"
            )
        block = text if not text or text.endswith("\n") else text + "\n"
        if line and not lines[line - 1].endswith("\n"):
            lines[line - 1] += "\n"
        updated = "".join(lines[:line]) + block + "".join(lines[line:])
        self._write(rel, info, _encode(rel, updated))
        return _edited(rel, updated, line + 1, line + block.count("\n"))

    def _read(self, rel: str, info: _Stat) -> str:
        if info is None:
            raise _EditError(f"{_show(rel)} does not exist")
        if stat.S_ISDIR(info.st_mode):
            raise _EditError(f"{_show(rel)} is a directory")
        limit = self._limits.max_file_bytes
        with os.fdopen(os.open(self._root / rel, _READ_FLAGS), "rb") as handle:
            data = handle.read(limit + 1)
        if len(data) > limit:
            size = max(info.st_size, len(data))
            raise _EditError(f"{_show(rel)} is {size} bytes; the limit is {limit}")
        if b"\0" in data:
            raise _EditError(f"{_show(rel)} is a binary file (it holds NUL bytes)")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _EditError(f"{_show(rel)} is not UTF-8 text") from exc

    def _write(self, rel: str, info: _Stat, data: bytes) -> None:
        limits, spent = self._limits, sum(self._written.values())
        if len(data) > limits.max_file_bytes:
            cap = limits.max_file_bytes
            raise _EditError(f"{_show(rel)}: {len(data)} bytes; the limit is {cap}")
        if rel not in self._written and len(self._written) >= limits.max_files:
            raise _EditError(f"at most {limits.max_files} files per trial")
        if spent + len(data) > limits.max_total_bytes:
            raise _EditError(
                f"{_show(rel)}: {len(data)} more bytes would exceed the trial's "
                f"{limits.max_total_bytes}-byte write budget ({spent} used)"
            )
        node = self._root
        for part in rel.split("/")[:-1]:
            node = node / part
            with contextlib.suppress(FileExistsError):
                os.mkdir(node, 0o755)
        temp = node / f".engine-edit-{os.urandom(8).hex()}.tmp"
        mode = 0o644 if info is None else stat.S_IMODE(info.st_mode) & 0o777
        self._written[rel] = self._written.get(rel, 0)  # before any side effect
        descriptor = os.open(temp, _TEMP_FLAGS, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                os.fchmod(descriptor, mode)
                handle.write(data)
            os.replace(temp, self._root / rel)  # replaces a name, never follows
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(temp)
            raise
        self._written[rel] += len(data)

    def _listing(self, rel: str) -> str:
        entries: list[str] = []
        cut = self._scan(self._root / rel, rel, 1, entries)
        header = (
            f"Files and directories up to {LIST_DEPTH} levels deep in {_show(rel)} "
            "(git metadata, secret files and __pycache__ hidden; symlinks not followed):"
        )
        tail = ["... more entries not shown: view a subdirectory"] if cut else []
        return "\n".join([header, *entries, *tail])

    def _scan(self, directory: Path, rel: str, depth: int, out: list[str]) -> bool:
        """Append ``directory``'s entries depth first; ``True`` when cut short."""
        with os.scandir(directory) as found:
            children = sorted(found, key=lambda entry: entry.name)
        for entry in children:
            child = entry.name if rel == "." else f"{rel}/{entry.name}"
            if not _listable(entry.name, child):
                continue
            if len(out) >= LIST_MAX_ENTRIES:
                return True
            if entry.is_symlink():
                out.append(f"{_show(child)} -> symlink, not followed")
            elif entry.is_dir(follow_symlinks=False):
                out.append(f"{_show(child)}/")
                deeper = depth < LIST_DEPTH
                if deeper and self._scan(Path(entry.path), child, depth + 1, out):
                    return True
            else:
                out.append(_show(child))
        return False

    def _cap(self, text: str) -> str:
        limit = self._limits.max_view_chars
        if len(text) <= limit:
            return text
        return (
            f"{text[:limit]}\n[output truncated: {len(text) - limit} more characters; "
            "use view_range to read a smaller part]"
        )


def _unprintable(text: str) -> bool:
    return any(unicodedata.category(char).startswith(_UNPRINTABLE) for char in text)


def _listable(name: str, rel: str) -> bool:
    if _unprintable(name):
        return False
    folded = name.casefold()
    if folded in _GIT_NAMES or folded == "__pycache__":
        return False
    return _first_match(rel, READ_DENY_PATTERNS) is None


def _first_match(rel: str, patterns: Sequence[str]) -> str | None:
    return next((p for p in patterns if matches_pattern(rel, p)), None)


def _encode(rel: str, text: str) -> bytes:
    if "\0" in text:
        raise _EditError(f"{_show(rel)}: NUL bytes are refused (binary text)")
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _EditError(f"{_show(rel)}: the text is not valid Unicode") from exc


def _split(text: str) -> list[str]:
    """Lines with their newline kept; an unterminated last line is kept as is."""
    parts = text.split("\n")
    lines = [f"{part}\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _numbered(lines: Sequence[str], first: int) -> str:
    """``cat -n`` style: a six-wide line number, a tab, the line."""
    bare = (line.removesuffix("\n") for line in lines)
    return "\n".join(f"{number:6}\t{line}" for number, line in enumerate(bare, first))


def _edited(rel: str, text: str, first: int, last: int) -> str:
    lines = _split(text)
    if not lines:
        return f"Edited {_show(rel)}; it is now empty."
    low = max(first - SNIPPET_CONTEXT, 1)
    high = min(max(last, first) + SNIPPET_CONTEXT, len(lines))
    snippet = _numbered(lines[low - 1 : high], low)
    return f"Edited {_show(rel)}. Lines {low}-{high} now read:\n{snippet}"


def _show(rel: str) -> str:
    return VIRTUAL_ROOT if rel in (".", "") else f"{VIRTUAL_ROOT}/{rel}"


def _describe(exc: ValidationError) -> str:
    problems = []
    for error in exc.errors(include_url=False, include_input=False):
        where = ".".join(str(part) for part in error["loc"])
        problems.append(f"{where}: {error['msg']}" if where else error["msg"])
    return "invalid input: " + "; ".join(problems)
