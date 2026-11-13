"""Re-keying idea anchors across a diff (X2-DT, stacked rounds; dt-design
section 1, Re-keying).

A seed's mechanism key (``idea_dedupe.KEY_EVENT``) names lines at the round
base it was generated on. When a round's tip is adopted as the next base,
``rekey_events`` moves every key into the tip's coordinates, read from
``git diff --no-renames base tip`` (``GitStacker.diff``, which is
``GitWorkspace.diff_commits``):

- each file's ``@@ -a,b +c,d @@`` hunks are walked line by line into change
  regions (a run of ``-`` and ``+`` rows between context rows), so context
  never counts as a change;
- a line before or after every region it is not part of shifts by the
  cumulative delta (lines added minus lines deleted before it);
- a span a region touches (a deleted line inside it, or an insertion between
  two of its lines) widens to that region's new lines; the result spans the
  tip lines of its surviving lines and of every region it touches.
  Decision: a span widens to the contiguous changed region, never to the
  whole hunk. A hunk is that region plus context rows, so widening to it
  would grow every key by up to twice the context for no change at all, and
  would make the same edit re-key differently under another
  ``diff.context``; the region is the tightest span that holds every
  changed line, and it is the same at any context size;
- a key is dropped, with its reason, when every target line is deleted with
  nothing added in their place, when its file is deleted (a rename is a
  delete plus an add: ``--no-renames``), new, binary, shown twice or not
  readable, or when truncation (``GitWorkspace._patch``'s marker) may have cut
  its file off: the last file shown and every file not shown;
- a file header that does not parse, or text before the first header, means
  any unshown file may have changed: every key in an unshown file is dropped.

Invariant: every key ``rekey_events`` records is in the tip's coordinates;
one it cannot place is recorded as dropped, never left at the base's lines.
A re-keyed record's data is exactly ``key_event``'s plus ``base``, ``tip``
and the lines it had at the base (``base_first``, ``base_last``), under
``REKEY_EVENT``; a drop is ``DROP_EVENT`` with the base lines and the
reason. ``rekeyed_keys`` reads the latest record of each hypothesis back
(``None``: dropped), and ``current_keys`` overlays them on
``recorded_keys``: with no re-key record it returns ``recorded_keys``
exactly.

Reading back fails closed. A record whose hypothesis id reads but which is
otherwise malformed drops that key: it never falls back to older lines. A
hypothesis's records must chain, or the key reads as dropped:

- each record's base lines, path, function, mechanism and cell are those of
  the key before it (the previous record, else the first ``KEY_EVENT``);
- each record's ``base`` is the previous record's ``tip``;
- a dropped key stays dropped: any later record of it is out of chain.

Limit: ``KEY_EVENT`` carries no commit, so the first record's ``base`` is
not checked (its lines are, against the ``KEY_EVENT``); with no
``KEY_EVENT`` the first record is taken as it is and the chain is checked
from the second on. A round fed ``recorded_keys`` instead of
``current_keys`` is caught by the lines whenever a key had moved (one that
had not moved is in the right place anyway). Every function here is pure:
no git, no clock, no model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Final

from pydantic import Field

from autonomous_ai_agents.clients.structured import count_note, shown
from autonomous_ai_agents.common.models import EngineModel, JsonScalar
from autonomous_ai_agents.optimization.idea_dedupe import (
    IdeaKey,
    MechanismKey,
    Target,
    key_event,
    recorded_keys,
)
from autonomous_ai_agents.optimization.idea_types import (
    GenerateEvent,
    Mechanism,
    MorphCell,
)

REKEY_EVENT: Final = "idea_mechanism_rekeyed"
"""A key moved to the tip: ``KEY_EVENT``'s data plus ``base`` and ``tip``."""
DROP_EVENT: Final = "idea_mechanism_dropped"
"""A key the diff cannot place at the tip: no seed line names it again."""

GONE: Final = "every target line is deleted at the tip"
DELETED: Final = "its file is deleted at the tip"
NEW_FILE: Final = "its file is new at the tip, so no base key can name it"
BINARY: Final = "its file changed as binary"
UNREADABLE: Final = "its file's diff could not be read"
TWICE: Final = "the diff shows its file twice"
CUT: Final = "its file's diff is cut off by truncation"
UNSHOWN: Final = "the diff is truncated, so its file may have been cut off"
BLIND: Final = "the diff holds a header it could not read, so its file may differ"

_HEAD: Final = "diff --git "
_HUNK: Final = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_TRUNCATED: Final = re.compile(r"\n\[diff truncated: \d+ of \d+ bytes shown\]\n\Z")
_OCTAL: Final = re.compile(r"[0-3][0-7]{2}")
_ESCAPES: Final[Mapping[str, int]] = {
    "a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92,
}  # fmt: skip
"""git's C-style quoting of a path (``quote_c_style``); octal for the rest."""
_Text = Annotated[str, Field(min_length=1)]
_Line = Annotated[int, Field(ge=1)]


# --------------------------------------------------------------------------
# Reading the diff
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Region:
    """One change: ``deleted`` base lines from ``old`` (none: an insertion
    before base line ``old``) became ``added`` tip lines from ``new``."""

    old: int
    deleted: int
    new: int
    added: int


@dataclass(frozen=True)
class _File:
    regions: tuple[_Region, ...] = ()
    problem: str | None = None


@dataclass(frozen=True)
class _Diff:
    files: Mapping[str, _File]
    unshown: str | None
    """Why a file the diff does not show may have changed (``None``: it is
    unchanged)."""


def _parse(diff: str) -> _Diff:
    cap = _TRUNCATED.search(diff)
    rows = (diff if cap is None else diff[: cap.start()]).split("\n")
    if rows[-1] == "":
        rows.pop()
    blocks: list[list[str]] = []
    unshown = None if cap is None else UNSHOWN
    for row in rows:
        if row.startswith(_HEAD):
            blocks.append([row])
        elif blocks:
            blocks[-1].append(row)
        elif row:
            unshown = unshown or BLIND
    files: dict[str, _File] = {}
    for index, block in enumerate(blocks):
        path = _header_path(block[0])
        if path is None:
            unshown = unshown or BLIND
        elif path in files:
            files[path] = _File(problem=TWICE)
        elif cap is not None and index == len(blocks) - 1:
            files[path] = _File(problem=CUT)
        else:
            files[path] = _file(block[1:])
    return _Diff(files, unshown)


def _file(rows: Sequence[str]) -> _File:
    start = next((i for i, row in enumerate(rows) if row.startswith("@@")), len(rows))
    head = rows[:start]
    if any(row.startswith("deleted file mode ") for row in head):
        return _File(problem=DELETED)
    if any(row.startswith("new file mode ") for row in head):
        return _File(problem=NEW_FILE)
    if any(row.startswith(("Binary files ", "GIT binary patch")) for row in head):
        return _File(problem=BINARY)
    regions = _regions(rows[start:])
    return _File(problem=UNREADABLE) if regions is None else _File(regions=regions)


def _regions(rows: Sequence[str]) -> tuple[_Region, ...] | None:
    """Every hunk's change regions, in order; ``None`` when a hunk is out of
    order, off the running delta, or its rows do not match its counts."""
    found: list[_Region] = []
    delta, done, at = 0, 1, 0  # done: the first base line no hunk has passed
    while at < len(rows):
        row, at = rows[at], at + 1
        if row.startswith("\\"):  # "\ No newline at end of file"
            continue
        head = _HUNK.match(row)
        if head is None:
            return None
        a, b, c, d = (int(g) for g in head.groups("1"))
        old, new = (a if b else a + 1), (c if d else c + 1)
        if old < done or new != old + delta:
            return None
        walked = _walk(rows, at, old, new, b, d)
        if walked is None:
            return None
        at, done = walked[0], walked[1]
        found += walked[2]
        delta += d - b
    return tuple(found)


def _walk(
    rows: Sequence[str], at: int, old: int, new: int, left: int, right: int
) -> tuple[int, int, list[_Region]] | None:
    """One hunk's body from row ``at``: (the next row, the next base line,
    its regions); an empty row is context (``diff.suppressBlankEmpty``)."""
    regions: list[_Region] = []
    start: tuple[int, int] | None = None
    while left or right:
        if at == len(rows):
            return None
        row, at = rows[at], at + 1
        mark = row[:1]
        if mark == "\\":
            continue
        if mark in (" ", "") and left and right:
            if start is not None:
                regions.append(_Region(start[0], old - start[0], start[1], new - start[1]))  # fmt: skip
                start = None
            old, new, left, right = old + 1, new + 1, left - 1, right - 1
        elif mark == "-" and left:
            start = start or (old, new)
            old, left = old + 1, left - 1
        elif mark == "+" and right:
            start = start or (old, new)
            new, right = new + 1, right - 1
        else:
            return None
    if start is not None:
        regions.append(_Region(start[0], old - start[0], start[1], new - start[1]))
    return at, old, regions


def _header_path(row: str) -> str | None:
    """The one path of a ``--no-renames`` header (``a/P b/P``, each side
    C-quoted by git when it must be), or ``None``."""
    rest = row[len(_HEAD) :]
    names: tuple[str, str] | None
    if rest.startswith('"'):
        names = _quoted_pair(rest)
    else:
        size = (len(rest) - 1) // 2
        names = (
            (rest[:size], rest[size + 1 :]) if rest[size : size + 1] == " " else None
        )
    if names is None:
        return None
    path = names[0][2:]
    ok = names[0].startswith("a/") and names[1] == f"b/{path}" and path
    return path if ok else None


def _quoted_pair(rest: str) -> tuple[str, str] | None:
    first = _unquote(rest)
    if first is None or not first[1].startswith(' "'):
        return None
    second = _unquote(first[1][1:])
    if second is None or second[1]:
        return None
    return first[0], second[0]


def _unquote(text: str) -> tuple[str, str] | None:
    """The C-quoted name opening ``text`` (UTF-8 bytes) and what follows."""
    out = bytearray()
    at = 1
    while at < len(text):
        char = text[at]
        if char == '"':
            try:
                return out.decode("utf-8"), text[at + 1 :]
            except UnicodeDecodeError:
                return None
        if char != "\\":
            out += char.encode("utf-8", "surrogatepass")
            at += 1
        elif (code := text[at + 1 : at + 2]) in _ESCAPES:
            out.append(_ESCAPES[code])
            at += 2
        elif _OCTAL.fullmatch(text[at + 1 : at + 4]):
            out.append(int(text[at + 1 : at + 4], 8))
            at += 4
        else:
            return None
    return None


# --------------------------------------------------------------------------
# Moving a span
# --------------------------------------------------------------------------


def _touches(region: _Region, first: int, last: int) -> bool:
    if region.deleted:
        return region.old <= last and first < region.old + region.deleted
    return first < region.old <= last


def _shift(regions: Sequence[_Region], line: int) -> int:
    """A surviving base line's tip line: the delta of every region before it."""
    return line + sum(r.added - r.deleted for r in regions if r.old + r.deleted <= line)


def _moved(regions: Sequence[_Region], first: int, last: int) -> tuple[int, int] | None:
    """The tip span of base lines ``first..last``: its surviving lines and
    the new lines of every region it touches; ``None``: nothing is left."""
    lines = [
        line
        for r in regions
        if r.added and _touches(r, first, last)
        for line in (r.new, r.new + r.added - 1)
    ]
    low, high = first, last
    for r in regions:
        if r.old <= low < r.old + r.deleted:
            low = r.old + r.deleted
    for r in reversed(regions):
        if r.old <= high < r.old + r.deleted:
            high = r.old - 1
    if low <= high:
        lines += [_shift(regions, low), _shift(regions, high)]
    return (min(lines), max(lines)) if lines else None


def _placed(diff: _Diff, target: Target) -> tuple[int, int] | str:
    """The target's tip lines, or why it is dropped."""
    found = diff.files.get(target.path)
    if found is None:
        return diff.unshown or (target.first, target.last)
    if found.problem is not None:
        return found.problem
    return _moved(found.regions, target.first, target.last) or GONE


# --------------------------------------------------------------------------
# The records
# --------------------------------------------------------------------------


def rekey_events(
    keys: Mapping[str, IdeaKey], diff: str, base: str, tip: str
) -> tuple[GenerateEvent, ...]:
    """One record per key, in ``keys``' order: ``REKEY_EVENT`` with the
    key's tip lines, or ``DROP_EVENT`` with its reason. ``diff`` is
    ``base..tip`` as ``GitWorkspace.diff_commits`` prints it."""
    if not base or not tip:
        raise ValueError("base and tip must name commits")
    parsed = _parse(diff)
    events: list[GenerateEvent] = []
    for hypothesis_id, key in keys.items():
        target = key.key.target
        where = f"{shown(hypothesis_id)} {target.path}:{target.first}-{target.last}"
        placed = _placed(parsed, target)
        if isinstance(placed, str):
            data: dict[str, JsonScalar] = {
                "hypothesis_id": hypothesis_id, "path": target.path,
                "first": target.first, "last": target.last, "base": base,
                "tip": tip, "reason": placed,
            }  # fmt: skip
            message = f"{where}: dropped, {placed}"
            events.append(GenerateEvent(code=DROP_EVENT, message=message, data=data))
            continue
        moved = Target(path=target.path, first=placed[0], last=placed[1])
        mechanism = MechanismKey(target=moved, mechanism=key.key.mechanism, cell=key.key.cell)  # fmt: skip
        record = IdeaKey(key=mechanism, function=key.function)
        # key_event's data, so the shape cannot drift from KEY_EVENT's
        data = {**key_event(hypothesis_id, hypothesis_id, record).data,
                "base": base, "tip": tip, "base_first": target.first,
                "base_last": target.last}  # fmt: skip
        message = f"{where} re-keyed to {moved.first}-{moved.last} at {tip}"
        events.append(GenerateEvent(code=REKEY_EVENT, message=message, data=data))
    return tuple(events)


class _Rekeyed(EngineModel):
    hypothesis_id: _Text
    path: _Text
    function: str | None
    first: _Line
    last: _Line
    mechanism: Mechanism
    cell: MorphCell
    base: _Text
    tip: _Text
    base_first: _Line
    base_last: _Line

    def key(self) -> IdeaKey:
        target = Target(path=self.path, first=self.first, last=self.last)
        key = MechanismKey(target=target, mechanism=self.mechanism, cell=self.cell)
        return IdeaKey(key=key, function=self.function)

    def at_base(self) -> tuple[str, int, int]:
        return self.path, self.base_first, self.base_last


class _Dropped(EngineModel):
    hypothesis_id: _Text
    path: _Text
    first: _Line
    last: _Line
    base: _Text
    tip: _Text

    def at_base(self) -> tuple[str, int, int]:
        return self.path, self.first, self.last


def _read(code: str, data: Mapping[str, JsonScalar]) -> tuple[_Rekeyed | _Dropped, IdeaKey | None]:  # fmt: skip
    """A record and the key it leaves (``None``: dropped); ValueError when
    it is malformed."""
    if code == REKEY_EVENT:
        row = _Rekeyed.model_validate({n: data.get(n) for n in _Rekeyed.model_fields})
        return row, row.key()
    gone = _Dropped.model_validate({n: data.get(n) for n in _Dropped.model_fields})
    return gone, None


def _follows(row: _Rekeyed | _Dropped, before: IdeaKey | None, tip: str | None) -> bool:  # fmt: skip
    """Whether ``row`` chains on the key before it and the previous tip."""
    if tip is not None and row.base != tip:
        return False
    if before is None:
        return True
    target = before.key.target
    if row.at_base() != (target.path, target.first, target.last):
        return False
    kept = (before.function, before.key.mechanism, before.key.cell)
    return isinstance(row, _Dropped) or (row.function, row.mechanism, row.cell) == kept


def rekeyed_keys(
    events: Iterable[Mapping[str, JsonScalar]], notes: list[str] | None = None
) -> dict[str, IdeaKey | None]:
    """The latest re-key record of each hypothesis from the node's event
    data (``None``: dropped, malformed or out of chain); a record with no
    readable hypothesis id is skipped. Each is counted in ``notes``.
    Records of other codes are only read as the chain's anchor."""
    rows = list(events)
    anchors = recorded_keys(rows)
    found: dict[str, IdeaKey | None] = {}
    tips: dict[str, str] = {}
    skipped = malformed = unchained = 0
    for data in rows:
        code = data.get("code")
        if code != REKEY_EVENT and code != DROP_EVENT:
            continue
        ident = data.get("hypothesis_id")
        if not isinstance(ident, str) or not ident:
            skipped += 1
            continue
        if ident in found and found[ident] is None:
            unchained += 1  # a dropped key stays dropped
            continue
        try:
            row, key = _read(code, data)
        except ValueError:
            found[ident], malformed = None, malformed + 1
            continue
        if not _follows(row, found.get(ident) or anchors.get(ident), tips.get(ident)):
            found[ident], unchained = None, unchained + 1
            continue
        found[ident], tips[ident] = key, row.tip
    if notes is not None:
        count_note(notes, skipped, "malformed re-key record(s) skipped")
        count_note(notes, malformed, "re-key record(s) malformed: their key reads as dropped")  # fmt: skip
        count_note(notes, unchained, "re-key record(s) out of chain: their key reads as dropped")  # fmt: skip
    return found


def current_keys(
    events: Iterable[Mapping[str, JsonScalar]], notes: list[str] | None = None
) -> dict[str, IdeaKey]:
    """``recorded_keys`` with each hypothesis's latest re-key record laid
    over it (a dropped key removed): every key in the current base's
    coordinates. With no re-key record it is ``recorded_keys`` exactly."""
    rows = list(events)
    keys = recorded_keys(rows)
    for hypothesis_id, key in rekeyed_keys(rows, notes).items():
        if key is None:
            keys.pop(hypothesis_id, None)
        else:
            keys[hypothesis_id] = key
    return keys
