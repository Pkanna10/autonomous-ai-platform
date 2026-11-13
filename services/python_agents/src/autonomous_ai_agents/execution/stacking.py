"""The git seam of stacked rounds (X2-DT): squash, diff and changed paths.

``GitStacker`` is the real ``Stacker`` over ``GitWorkspace`` and adds no git
call of its own: ``is_ancestor``, ``merge``, ``commit_tree`` and
``diff_commits`` keep their safety wrappers (scratch environment, validated
ids, argv only, capped output). It writes objects only, never a ref or a
worktree (``gc.auto=0`` keeps an unreferenced squash alive for the run).

- ``squash`` refuses a bad label (``require_stack_label``) and a ``tip``
  that does not strictly descend from ``base``; ``merge-tree base tip`` then
  is ``tip``'s own tree (the merge base is ``base``, which ``tip`` changes
  and ``base`` does not), committed with ``base`` as its only parent, the
  engine identity and ``base``'s dates, so the same inputs give the same
  SHA and the FIXED combiner takes it as one trial's diff
  (``combine._unfit``). Before any object is written, the merged tree is
  checked against the tip's own, read as ``merge(tip, tip).tree`` (the
  combiner's idiom: ``GitWorkspace`` has no tree reader); a mismatch is an
  ``EngineError``.
- ``changed_paths`` parses the capped ``base..tip`` patch. Its answer feeds
  the protected-path check of the cumulative diff, so it fails closed: every
  line must be a ``diff --git`` header, a known file-header line (``index``,
  ``---``, ``+++``, mode, ``new file``, ``deleted file``, (dis)similarity,
  ``Binary files``), a hunk line (``@@``), or inside a hunk a content line
  (`` ``, ``+``, ``-``, or an empty line: blank context under a repo's
  ``diff.suppressBlankEmpty``) or ``\\ No newline at end of file``.
  Anything else is an ``EngineError``: notably the ``Submodule <path> ...``
  line a repo's ``diff.submodule=log`` or ``diff`` prints for a gitlink with
  no header, a rename or copy line, or an empty line before a file's first
  hunk. So are a truncated patch, a header
  that is not ``a/P b/P`` with one path ``P`` (``--no-renames``: both
  sides name the same file), a bad C quote and a path that is not
  repo-relative. A path is never dropped. Paths are data: they are compared
  as text and never reach a shell.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import Project
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.execution.protocols import require_stack_label

TRUNCATED: Final = "\n[diff truncated: "
"""The marker ``GitWorkspace._patch`` appends to a capped patch."""
_OID: Final = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_HEADER: Final = "diff --git "
_QUOTED: Final = re.compile(r'"a/((?:[^"\\]|\\.)*)" "b/((?:[^"\\]|\\.)*)"')
_ESCAPES: Final = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13,
                   '"': 34, "\\": 92}  # fmt: skip
_OCTAL: Final = re.compile(r"[0-3][0-7]{2}")
_QUOTE: Final = 300
_FILE_LINES: Final = ("index ", "--- ", "+++ ", "old mode ", "new mode ",
                      "new file mode ", "deleted file mode ", "similarity index ",
                      "dissimilarity index ", "Binary files ")  # fmt: skip
_HUNK: Final = "@@ "
_CONTENT: Final = (" ", "+", "-")
_NO_NEWLINE: Final = "\\ No newline at end of file"


def _quote(text: str) -> str:
    return "".join(ch if ch.isprintable() else "?" for ch in text[:_QUOTE])


class GitStacker:
    """The real ``Stacker``; ``git`` defaults to the project's workspace and
    ``max_diff_bytes`` caps ``diff`` (``MAX_DIFF_BYTES``)."""

    def __init__(
        self,
        *,
        git: GitWorkspace | None = None,
        max_diff_bytes: int = settings.MAX_DIFF_BYTES,
    ) -> None:
        if max_diff_bytes < 1:
            raise ValueError(f"max_diff_bytes must be at least 1, got {max_diff_bytes}")
        self._git = git
        self._max = max_diff_bytes

    def _workspace(self, project: Project, base: str, tip: str) -> GitWorkspace:
        git = self._git or GitWorkspace(Path(project.root_path))
        _require_commit(git, "base", base)
        _require_commit(git, "tip", tip)
        return git

    def squash(self, project: Project, base: str, tip: str, label: str) -> str:
        """One commit: ``tip``'s tree, ``base`` its only parent, ``label``
        (one safe token, like a run id) in its message."""
        require_stack_label(label)
        git = self._workspace(project, base, tip)
        if base == tip:
            raise EngineError(f"tip {tip} is the base: nothing to squash")
        if not git.is_ancestor(base, tip):
            raise EngineError(f"tip {tip} does not descend from the base {base}")
        merged = git.merge(base, tip)
        if merged.tree is None:
            conflicts = ", ".join(_quote(path) for path in merged.conflicts[:5])
            raise EngineError(
                f"tip {tip} did not merge cleanly onto {base}: {conflicts}"
            )
        message = (
            f"aip: stacked rounds {label}\n\nEngine-Stack: {label}\nEngine-Tip: {tip}\n"
        )
        if merged.tree != git.merge(tip, tip).tree:
            raise EngineError(
                f"the squash's tree is not the tip's: {merged.tree} for {tip}"
            )
        return git.commit_tree(merged.tree, base, message, base=base)

    def diff(self, project: Project, base: str, tip: str) -> str:
        """``base..tip`` as ``GitWorkspace.diff_commits`` prints it, capped."""
        git = self._workspace(project, base, tip)
        return git.diff_commits(base, tip, max_bytes=self._max)

    def changed_paths(self, project: Project, base: str, tip: str) -> tuple[str, ...]:
        """Every path ``base..tip`` changes, once, in git's order."""
        return parse_changed_paths(self.diff(project, base, tip))


def _require_commit(git: GitWorkspace, what: str, value: str) -> None:
    """A full id naming a commit object itself (not a tag, tree or ref)."""
    problem = f"{what} {_quote(value)!r} is not a commit id"
    if _OID.fullmatch(value) is None:
        raise EngineError(problem)
    try:
        resolved = git.resolve_commit(value)
    except GitError as exc:
        raise EngineError(problem) from exc
    if resolved != value:
        raise EngineError(problem)


def parse_changed_paths(diff: str) -> tuple[str, ...]:
    """The path of each ``diff --git`` header in ``diff``, once, in order;
    ``EngineError`` on a truncated patch or a line of no known kind.

    Lines are split on ``\\n`` only (a content line holding another line
    separator stays one line); the patch's final newline ends it. Before the
    first ``@@`` of a file only file-header lines are known; after it only
    hunk, content (an empty line is blank context) and no-newline lines, until
    the next header.
    """
    if TRUNCATED in diff:
        raise EngineError("the diff is truncated: its changed paths are unknown")
    lines = diff.split("\n")
    if lines[-1] == "":
        lines.pop()
    paths: list[str] = []
    in_hunk: bool | None = None  # None: no header yet
    for line in lines:
        if line.startswith("diff"):
            path, in_hunk = _header_path(line), False
            if path not in paths:
                paths.append(path)
        elif in_hunk is not None and line.startswith(_HUNK):
            in_hunk = True
        elif not _known(line, in_hunk):
            problem = f"diff line {_quote(line)!r} is of no known kind"
            raise EngineError(f"{problem}: the changed paths are unknown")
    return tuple(paths)


def _known(line: str, in_hunk: bool | None) -> bool:
    if in_hunk is None:
        return False
    if in_hunk:
        return line.startswith(_CONTENT) or line in ("", _NO_NEWLINE)
    return line.startswith(_FILE_LINES)


def _header_path(line: str) -> str:
    problem = f"diff header {_quote(line)!r} does not parse"
    rest = line.removeprefix(_HEADER)
    if rest == line:
        raise EngineError(problem)
    if rest.startswith('"'):
        quoted = _QUOTED.fullmatch(rest)
        if quoted is None:
            raise EngineError(problem)
        old, new = (_unquote(side, problem) for side in quoted.groups())
    elif rest.startswith("a/"):
        both = rest[2:]
        half = (len(both) - 3) // 2
        old, new = both[:half], both[half + 3 :]
        if both[half : half + 3] != " b/":
            raise EngineError(problem)
    else:
        raise EngineError(problem)
    if old != new or "\0" in old:
        raise EngineError(problem)
    if any(part in ("", ".", "..") for part in old.split("/")):
        raise EngineError(f"{problem}: {_quote(old)!r} is not a repo-relative path")
    return old


def _unquote(body: str, problem: str) -> str:
    """Git's ``quote_c_style`` undone: named escapes and ``\\ooo`` bytes, the
    bytes decoded as ``os.fsdecode`` decodes every other git path."""
    out = bytearray()
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            out += char.encode("utf-8")
            index += 1
        elif (named := _ESCAPES.get(body[index + 1 : index + 2])) is not None:
            out.append(named)
            index += 2
        elif _OCTAL.fullmatch(body[index + 1 : index + 4]) is not None:
            out.append(int(body[index + 1 : index + 4], 8))
            index += 4
        else:
            raise EngineError(problem)
    return os.fsdecode(bytes(out))
