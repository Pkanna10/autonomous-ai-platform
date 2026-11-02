"""The idea pipeline's code context, S0 (Step 3 Wave 2, N1b; spec amendment D44).

Repository text becomes model input here, so every rule below is a
protection (spec amendment section 5):

- Reading: only ``RepoReader`` blobs at the run's base commit, through the
  shared rules of ``common/repo_read.py`` (``READ_DENY_PATTERNS`` never
  read, git's binary sniff, a UTF-8 head with a cut flag). A path in the
  run's protected set (``DEFAULT_PROTECTED_PATTERNS`` always, plus the
  caller's ``protected`` and ``read_deny``), a path that is unprintable or
  holds a live fence token, and a file whose text holds one are never shown.
- Lines: a bidi override or isolate withholds the line (Trojan Source); a
  secret-shaped line (and a private key's body) is withheld, named in a note
  by path and line, never by content; every other invisible character
  (``Cf``, ``Cc`` but tab, the tag block, zero-width, U+061C) becomes a
  visible ``\\u{XXXX}`` escape in the rendering and the grounding text alike.
  ``\\r\\n`` and a lone ``\\r`` are line breaks, as Python numbers lines.
- What is shown: the top ``hot_functions`` hotspots by cumulative time
  (deduplicated by file and symbol), each as its enclosing ``def`` or
  ``class`` (found by ``ast`` at the profiled line, decorators included),
  the file's module header (at most ``header_max_lines``) and textual
  callers while the cap allows; a file within ``file_max_bytes`` is shown
  whole. A file the engine cannot parse (cut at ``parse_max_bytes``, or any
  of ``SyntaxError``, ``ValueError``, ``RecursionError``, ``MemoryError``) is
  shown as its head, anchored to its hottest hotspot. ``code_max_bytes``
  bounds the rendered text, prefixes included, hottest first.
- ``CodeDocument.raw`` holds the lines ``start_line``..``end_line`` in order,
  joined by ``\\n``: a line that is not shown or is withheld is empty, so
  line ``n`` is ``raw.split("\\n")[n - start_line]``.

No model is called here; ``render_data_block`` builds the cached prefix (D59).
"""

from __future__ import annotations

import ast
import posixpath
import re
import unicodedata
import warnings
from ast import parse as _ast_parse
from collections import Counter, deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

from pydantic import Field

from autonomous_ai_agents.clients.structured import (
    Fence,
    count_note,
    data_line,
    hotspot_rows,
    understanding_lines,
)
from autonomous_ai_agents.common.config import IdeaView, Settings
from autonomous_ai_agents.common.models import (
    EngineModel,
    Hotspot,
    Objective,
    Project,
    ProjectUnderstanding,
    Workload,
)
from autonomous_ai_agents.common.paths import matches_pattern, normalize_path
from autonomous_ai_agents.common.repo_read import (
    DENIED,
    ReadText,
    RepoReader,
    read_denied,
    read_text,
    unprintable,
)
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.optimization.anticheat import (
    DEFAULT_PROTECTED_PATTERNS,
    _spawn_findings,
)
from autonomous_ai_agents.optimization.idea_prompts import (
    VIEW_CODE_HEADING,
    VIEW_HEADINGS,
)
from autonomous_ai_agents.optimization.idea_types import (
    Anchor,
    CodeContext,
    CodeDocument,
    FunctionSpan,
)

HEADER_MAX_LINES: Final = 60
SPAWN_FINDINGS_SHOWN: Final = 5
_BIDI: Final = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
_SECRET: Final = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-ant-|AKIA[0-9A-Z]{16}|ghp_"
    r"|github_pat_|xox[bp]-"
)
_KEY_START: Final = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_KEY_END: Final = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_INVISIBLE: Final = frozenset(
    (*range(0xE0000, 0xE0080), *range(0x200B, 0x200E), *range(0x2060, 0x2065))
) | {0x180E, 0x061C, 0x2028, 0x2029}
_BIDI_LINE: Final = "(line withheld: a bidi control)"
_SECRET_LINE: Final = "(line withheld: secret-shaped)"
_DEFS: Final = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_SPAWN_SENTENCE: Final = (
    "A document marked spawn_finding holds a statement that can start "
    "processes or threads: an edit must leave that statement, and every use "
    "of the names it binds, unchanged."
)


class IdeaReadLimits(EngineModel):
    """S0's caps (D44); ``from_settings`` reads the ``IDEAS_*`` knobs."""

    hot_functions: int = Field(default=8, ge=1, le=30)
    max_files: int = Field(default=8, ge=1, le=20)
    file_max_bytes: int = Field(default=24 * 1024, ge=1)
    code_max_bytes: int = Field(default=64 * 1024, ge=1)
    parse_max_bytes: int = Field(default=512 * 1024, ge=1)
    header_max_lines: int = Field(default=HEADER_MAX_LINES, ge=0)
    whole_files: bool = True
    """A file within ``file_max_bytes`` is shown whole (a view turns it off)."""
    callers: bool = True
    """Textual callers in the shown files are added (a view turns it off)."""

    @classmethod
    def from_settings(cls, cfg: Settings) -> IdeaReadLimits:
        return cls(
            hot_functions=cfg.IDEAS_HOT_FUNCTIONS,
            max_files=cfg.IDEAS_MAX_FILES,
            file_max_bytes=cfg.IDEAS_FILE_MAX_BYTES,
            code_max_bytes=cfg.IDEAS_CODE_MAX_BYTES,
            parse_max_bytes=cfg.IDEAS_PARSE_MAX_BYTES,
        )


@dataclass(frozen=True)
class _Node:
    qualname: str
    name: str
    start: int  # the first decorator's line, as cProfile reports it
    end: int
    depth: int
    tree: ast.AST


@dataclass
class _File:
    """One readable file: its lines as shown, the lines it may show, its parse."""

    path: str
    shown: list[str]  # per line: escaped text or a withheld marker
    raw: list[str]  # per line: escaped text, or "" when withheld
    flags: dict[int, str]  # line -> "bidi" | "secret" | "escaped"
    nodes: list[_Node] | None  # None: unparsable, shown as its head
    findings: tuple[str, ...] = ()
    module: ast.Module | None = None
    listed: list[Hotspot] = field(default_factory=list)
    lines: set[int] = field(default_factory=set)
    spans: tuple[FunctionSpan, ...] = ()


@dataclass
class _Room:
    """The rendered-byte budget over every document of one context."""

    cap: int
    left: int


def read_code_context(
    reader: RepoReader,
    commit: str,
    hotspots: Sequence[Hotspot],
    *,
    fence: Fence,
    protected: Sequence[str],
    read_deny: Sequence[str],
    limits: IdeaReadLimits,
    notes: list[str],
    only: Sequence[tuple[str, str]] | None = None,
) -> CodeContext:
    """The hot code at ``commit`` (D44); every exclusion, cut and fallback is
    noted in ``notes`` and in the context's own ``notes``. ``only`` (a view,
    G2) shows just these ``(file_path, symbol)`` hotspots, in its order."""
    start = len(notes)
    totals = _totals(hotspots)
    try:
        tracked = frozenset(reader.ls_tree(commit))
    except GitError:
        notes.append("code context: the base commit's file list is unreadable in git")
        return CodeContext(totals_by_workload=totals, notes=tuple(notes[start:]))
    ranked = sorted(
        hotspots,
        key=lambda h: (-h.total_time_s, -h.self_time_s, h.file_path, h.symbol),
    )
    first: dict[tuple[str, str], Hotspot] = {}
    for spot in ranked:
        first.setdefault((spot.file_path, spot.symbol), spot)
    keys = first if only is None else [k for k in dict.fromkeys(only) if k in first]
    chosen = [first[key] for key in keys][: limits.hot_functions]
    patterns = (*DEFAULT_PROTECTED_PATTERNS, *protected, *read_deny)
    files: list[_File] = []
    room = _Room(limits.code_max_bytes, limits.code_max_bytes)
    denied = odd = 0
    paths = list(dict.fromkeys(h.file_path for h in chosen))
    for index, path in enumerate(paths):
        if len(files) == limits.max_files:
            rest = paths[index:]
            named = (p for p in rest if not (unprintable(p) or fence.holds(p)))
            notes.append(
                f"{len(rest)} file(s) not shown (file limit {limits.max_files}): "
                + ", ".join(named)
            )
            break
        if unprintable(path) or fence.holds(path):
            odd += 1
        elif read_denied(path):
            denied += 1
        elif any(matches_pattern(path, p) for p in patterns):
            notes.append(f"{path}: not shown (protected: a test, benchmark, "
                         "manifest or frozen file)")  # fmt: skip
        elif path not in tracked:
            notes.append(f"{path}: not tracked at the base commit")
        else:
            found = _load(reader, commit, path, fence, limits, notes)
            if found is not None:
                found.listed = [h for h in hotspots if h.file_path == path]
                spots = [h for h in chosen if h.file_path == path]
                if _place(found, spots, limits, room, notes):
                    files.append(found)
    if odd:
        notes.append(f"{odd} file(s) withheld: the path holds a boundary token "
                     "or an unprintable character")  # fmt: skip
    if denied:
        notes.append(f"{denied} secret-like file(s) never read")
    if limits.callers:
        _add_callers(files, chosen, room, notes)
    documents = tuple(_document(f, notes) for f in files)
    if documents:
        size = sum(len(d.rendered.encode()) for d in documents)
        names = ", ".join(d.path for d in documents)
        notes.append(f"code context: {len(documents)} file(s) shown ({size} "
                     f"rendered bytes): {names}")  # fmt: skip
    return CodeContext(
        documents=documents, totals_by_workload=totals, notes=tuple(notes[start:])
    )


def _totals(hotspots: Sequence[Hotspot]) -> dict[str, float]:
    """Each workload's profiled total, ``self_time_s / share`` (D51)."""
    totals: dict[str, float] = {}
    for spot in sorted(hotspots, key=lambda h: -h.share):
        if spot.share > 0 and spot.workload_id not in totals:
            totals[spot.workload_id] = spot.self_time_s / spot.share
    return totals


def _load(
    reader: RepoReader,
    commit: str,
    path: str,
    fence: Fence,
    limits: IdeaReadLimits,
    notes: list[str],
) -> _File | None:
    try:
        found = read_text(reader, commit, path, cap=limits.parse_max_bytes)
    except GitError:
        notes.append(f"{path}: unreadable in git")
        return None
    if not isinstance(found, ReadText):
        notes.append(f"{path}: not shown ({found})")
        return None
    if fence.holds(found.text):
        notes.append(f"{path}: withheld (it holds a boundary token)")
        return None
    text = found.text.replace("\r\n", "\n")
    if "\r" in text:
        notes.append(f"{path}: lone carriage returns read as line breaks")
        text = text.replace("\r", "\n")
    why = f"longer than {limits.parse_max_bytes} bytes" if found.cut else None
    tree: ast.Module | None = None
    if why is None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = _ast_parse(text)
        except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
            why = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    if tree is None:
        text = _head(text, limits.file_max_bytes)
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if not lines:
        notes.append(f"{path}: not shown (empty)")
        return None
    if why is not None:
        notes.append(f"{path}: shown as its first {len(lines)} line(s): it could "
                     f"not be parsed ({why})")  # fmt: skip
    loaded = _File(path, *_screen(lines), nodes=None)
    if tree is not None:
        loaded.nodes, loaded.module = list(_walk(tree)), tree
        found_spawn = sorted(set(_spawn_findings(tree)))
        loaded.findings = tuple(f"line {n}: {what}" for n, what in found_spawn)
    return loaded


def _head(text: str, cap: int) -> str:
    """At most ``cap`` bytes of whole lines (one cut line when it is the only one)."""
    data = text.encode()
    if len(data) <= cap:
        return text
    head = data[:cap].decode("utf-8", errors="ignore")  # drops a split character
    end = head.rfind("\n")
    return head if end < 0 else head[: end + 1]


def _screen(lines: list[str]) -> tuple[list[str], list[str], dict[int, str]]:
    shown, raw, flags = [], [], {}
    in_key = False
    for number, line in enumerate(lines, 1):
        if in_key or _SECRET.search(line):
            in_key = (in_key or bool(_KEY_START.search(line))) and not _KEY_END.search(
                line
            )
            shown.append(_SECRET_LINE)
            raw.append("")
            flags[number] = "secret"
        elif _BIDI.search(line):
            shown.append(_BIDI_LINE)
            raw.append("")
            flags[number] = "bidi"
        else:
            escaped = _escape(line)
            if escaped != line:
                flags[number] = "escaped"
            shown.append(escaped)
            raw.append(escaped)
    return shown, raw, flags


def _escape(line: str) -> str:
    if line.replace("\t", " ").isprintable():
        return line
    return "".join(
        f"\\u{{{ord(c):04X}}}"
        if c != "\t"
        and (unicodedata.category(c) in ("Cf", "Cc") or ord(c) in _INVISIBLE)
        else c
        for c in line
    )


def _walk(tree: ast.AST) -> Iterator[_Node]:
    """Every ``def`` and ``class`` with its qualified name, iteratively."""
    stack: list[tuple[ast.AST, str, int]] = [(tree, "", 0)]
    while stack:
        node, prefix, depth = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _DEFS):
                name = f"{prefix}{child.name}"
                first = min([d.lineno for d in child.decorator_list] + [child.lineno])
                end = child.end_lineno or child.lineno
                yield _Node(name, child.name, first, end, depth + 1, child)
                stack.append((child, f"{name}.", depth + 1))
            else:
                stack.append((child, prefix, depth))


def _node_of(nodes: list[_Node], spot: Hotspot) -> _Node | None:
    """The innermost ``def``/``class`` at the hotspot's line, or the one
    named by the symbol's last component when there is no line. cProfile's
    ``<module>`` row (line 1, the whole run) is never a function's (D51)."""
    line = spot.line_start
    if spot.symbol == "<module>":
        return None
    if line is None:
        name = spot.symbol.rsplit(".", 1)[-1]
        named = [n for n in nodes if n.name == name]
        return named[0] if len(named) == 1 else None
    holding = [n for n in nodes if n.start <= line <= n.end]
    return max(holding, key=lambda n: n.depth, default=None)


def _place(
    found: _File,
    spots: list[Hotspot],
    limits: IdeaReadLimits,
    room: _Room,
    notes: list[str],
) -> bool:
    """Choose the file's shown lines within the room; whether it is shown."""
    path, count, nodes = found.path, len(found.shown), found.nodes
    everything = set(range(1, count + 1))
    if nodes is None:  # the head, anchored to the file's hottest function
        names = [s.symbol for s in spots if s.symbol != "<module>"]
        ids = tuple(h.id for h in found.listed if names and h.symbol == names[0])
        found.spans = tuple(FunctionSpan(path=path, qualname=name, start_line=1,
                                         end_line=count, hotspot_ids=ids)
                            for name in names[:1])  # fmt: skip
        return _try(found, everything, room, notes, f"{path}: the file head")
    whole = limits.whole_files and (
        len("\n".join(found.raw).encode()) <= limits.file_max_bytes
    )
    resolved = any(_node_of(nodes, spot) for spot in found.listed)
    if whole and resolved and _try(found, everything, room, notes, None):
        return True
    for spot in spots:
        node = _node_of(nodes, spot)
        if node is None:
            notes.append(f"{path}: no function found for hotspot {spot.symbol!r}")
        else:
            body = set(range(node.start, node.end + 1))
            _try(found, body, room, notes, f"{path}: hot function {node.qualname}")
    if not found.lines:
        notes.append(f"{path}: not shown (no hot function could be shown)")
        return False
    first = min(n.start for n in nodes)
    header = set(range(1, min(first - 1, limits.header_max_lines) + 1))
    _try(found, header, room, notes, f"{path}: the module header")
    return True


def _spans(found: _File, nodes: list[_Node]) -> tuple[FunctionSpan, ...]:
    """Hot spans: listed hotspots' functions wholly shown, and every
    ``def``/``class`` inside them (with no hotspot of its own)."""
    ids: dict[_Node, list[str]] = {}
    for spot in found.listed:
        node = _node_of(nodes, spot)
        if node is not None and found.lines.issuperset(range(node.start, node.end + 1)):
            ids.setdefault(node, []).append(spot.id)
    return tuple(
        FunctionSpan(path=found.path, qualname=n.qualname, start_line=n.start,
                     end_line=n.end, hotspot_ids=tuple(ids.get(n, ())))
        for n in sorted(nodes, key=lambda n: (n.start, -n.end))
        if any(h.start <= n.start and n.end <= h.end for h in ids)
    )  # fmt: skip


def _try(
    found: _File, lines: set[int], room: _Room, notes: list[str], what: str | None
) -> bool:
    """Add ``lines`` if the rendered documents still fit; else note ``what``."""
    added = found.lines | lines
    grow = len(_render(found, added).encode()) - len(
        _render(found, found.lines).encode()
    )
    if grow > room.left:
        if what is not None:
            notes.append(f"{what} not shown (code limit {room.cap} bytes)")
        return False
    room.left -= grow
    found.lines = added
    return True


def _render(found: _File, lines: set[int]) -> str:
    return _numbered((number, found.shown[number - 1]) for number in sorted(lines))


def _numbered(rows: Iterable[tuple[int, str]]) -> str:
    """Ascending ``(line, text)`` rows as ``L<n>: <text>``, each gap marked."""
    out: list[str] = []
    previous = None
    for number, text in rows:
        if previous is not None and number != previous + 1:
            out.append(f"(lines {previous + 1}-{number - 1} not shown)")
        out.append(f"L{number}: {text}")
        previous = number
    return "\n".join(out)


def _add_callers(
    files: list[_File], chosen: list[Hotspot], room: _Room, notes: list[str]
) -> None:
    """Functions of shown files that name a hot symbol, while the room allows."""
    names = {h.symbol.rsplit(".", 1)[-1] for h in chosen}
    shown = dropped = 0
    for found in files:
        for node in sorted(found.nodes or (), key=lambda n: n.start):
            body = set(range(node.start, node.end + 1))
            if isinstance(node.tree, ast.ClassDef) or body & found.lines:
                continue
            used = {
                n.id if isinstance(n, ast.Name) else n.attr
                for n in ast.walk(node.tree)
                if isinstance(n, ast.Name | ast.Attribute)
            }
            if names & used:
                if _try(found, body, room, notes, None):
                    shown += 1
                else:
                    dropped += 1
    if shown:
        notes.append(f"{shown} textual caller(s) shown")
    if dropped:
        notes.append(
            f"{dropped} textual caller(s) not shown (code limit {room.cap} bytes)"
        )


def _document(found: _File, notes: list[str]) -> CodeDocument:
    first, last = min(found.lines), max(found.lines)
    for flag, what in (
        ("bidi", "withheld (a bidi control: a Trojan-Source line)"),
        ("secret", "withheld (secret-shaped)"),
        ("escaped", None),
    ):
        hit = [
            n for n, f in sorted(found.flags.items()) if f == flag and n in found.lines
        ]
        if hit and what is None:
            notes.append(f"{found.path}: invisible character(s) on line(s) "
                         f"{_ranges(hit)} shown as \\u{{...}} escapes")  # fmt: skip
        elif hit:
            notes.append(f"{found.path}: line(s) {_ranges(hit)} {what}")
    raw = [found.raw[n - 1] if n in found.lines else "" for n in range(first, last + 1)]
    return CodeDocument(
        path=found.path,
        start_line=first,
        end_line=last,
        rendered=_render(found, found.lines),
        raw="\n".join(raw),
        spans=found.spans if found.nodes is None else _spans(found, found.nodes),
        spawn_findings=found.findings,
    )


def _ranges(numbers: list[int]) -> str:
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    text = [str(a) if a == b else f"{a}-{b}" for a, b in runs[:10]]
    more = f" and {len(runs) - 10} more" if len(runs) > 10 else ""
    return ", ".join(text) + more


# --------------------------------------------------------------------------
# The engine's facts from a match (D50, D51)
# --------------------------------------------------------------------------


def anchor_of(
    path: str, quote_span: tuple[int, int], context: CodeContext
) -> Anchor | None:
    """The innermost shown function holding lines ``quote_span`` (1-based,
    inclusive) inside a hot span of ``path``, or ``None`` (D50)."""
    first, last = quote_span
    for document in context.documents:
        if document.path == path:
            holding = [
                s
                for s in document.spans
                if s.start_line <= first and last <= s.end_line
            ]
            if any(s.hotspot_ids for s in holding):
                best = min(
                    holding, key=lambda s: (s.end_line - s.start_line, -s.start_line)
                )
                return Anchor(path=path, qualname=best.qualname)
    return None


def amdahl_ceiling(
    anchor: Anchor | None,
    idea_hotspots: Sequence[Hotspot],
    context: CodeContext,
    *,
    profile: Sequence[Hotspot],
) -> float | None:
    """The anchor's cumulative share, largest over workloads, clipped to 1 (D51).

    ``profile`` resolves span hotspot ids. An anchor with no hotspot of its
    own takes the innermost enclosing hot span's share; failing that (a
    hand-built context), the smallest share among ``idea_hotspots`` (the
    idea's resolved hotspots) in its file. ``None`` when nothing is known.
    """
    spans = [s for d in context.documents if d.path == (anchor and anchor.path)
             for s in d.spans]  # fmt: skip
    span = next((s for s in spans if anchor and s.qualname == anchor.qualname), None)
    if anchor is None or span is None:
        return None
    holding = sorted(
        (
            s
            for s in spans
            if s.start_line <= span.start_line <= span.end_line <= s.end_line
        ),
        key=lambda s: s.end_line - s.start_line,
    )
    own = next(
        (o for s in holding if (o := [h for h in profile if h.id in s.hotspot_ids])),
        [],
    )
    pool = own or [h for h in idea_hotspots if h.file_path == anchor.path]
    shares: dict[str, list[float]] = {}
    for spot in pool:
        total = context.totals_by_workload.get(spot.workload_id)
        if total:
            shares.setdefault(spot.workload_id, []).append(spot.total_time_s / total)
    pick = max if own else min
    best = max((pick(values) for values in shares.values()), default=None)
    return None if best is None else min(1.0, best)


# --------------------------------------------------------------------------
# The data block (the cached prefix, D59)
# --------------------------------------------------------------------------


def render_data_block(
    context: CodeContext,
    *,
    project: Project,
    objective: Objective,
    understanding: ProjectUnderstanding | None,
    hotspots: Sequence[Hotspot],
    fence: Fence,
    notes: list[str],
    view: IdeaView | None = None,
    facts: Sequence[str] = (),
) -> str:
    """The fenced data block: project, objective, floor, understanding,
    profile rows and the documents, in that order; byte-stable for one
    context and fence. Anything holding a live token is withheld, noted.

    With ``view`` (G2) the hot-code heading is that view's, followed by its
    ``facts`` (capped, withheld when they hold a live token or a secret
    shape) and the documents of ``context``, the view's own."""

    def kept(what: str, value: str) -> str:
        if not fence.holds(value):
            return value
        notes.append(f"the {what} withheld: it holds a boundary token")
        return "(withheld)"

    floor = objective.min_relative_gain
    rows, _ = hotspot_rows(hotspots, fence, notes)
    lines = [
        "project: "
        + data_line(
            {
                "name": kept("project name", project.name),
                "language": kept("project language", project.language),
            }
        ),
        "objective: "
        + data_line(
            {
                "kind": objective.kind.value,
                "metric": kept("objective metric", objective.metric),
                "direction": objective.direction.value,
                "min_relative_gain": floor,
                "description": kept("objective description", objective.description),
            }
        ),
        f"noise floor: a gain below {_percent(floor)} % of the metric is not kept "
        "(per-project calibration)",
        *understanding_lines(understanding, fence, notes),
        "",
        "profiler hotspots (largest self-time share first; total_time_s is the "
        "cumulative time under the profiler, which inflates call-heavy functions):",
        *rows,
        "",
    ]
    if view is None:
        lines.append("hot code at the base commit (line numbers are for reference; "
                     "quote the code, not the numbers):")  # fmt: skip
    else:
        lines += [VIEW_HEADINGS[view], *_view_facts(facts, fence, notes), "",
                  VIEW_CODE_HEADING]  # fmt: skip
    if any(d.spawn_findings for d in context.documents):
        lines.append(_SPAWN_SENTENCE)
    lines.append("<documents>")
    withheld = 0
    for document in context.documents:
        element = _element(document, hotspots, context)
        if fence.holds(element):
            withheld += 1
        else:
            lines.append(element)
    if withheld:
        notes.append(f"{withheld} document(s) withheld: they hold a boundary token")
    lines.append("</documents>")
    return "\n".join((fence.opening(), fence.block("untrusted_repo_content", lines)))


def _element(
    document: CodeDocument, hotspots: Sequence[Hotspot], context: CodeContext
) -> str:
    by_id = {h.id: h for h in hotspots}
    hot: list[tuple[float, str]] = []
    for span in document.spans:
        if span.hotspot_ids:
            share = max(
                (by_id[i].total_time_s / context.totals_by_workload[by_id[i].workload_id]
                 for i in span.hotspot_ids
                 if i in by_id and context.totals_by_workload.get(by_id[i].workload_id)),
                default=None,
            )  # fmt: skip
            label = span.qualname
            if share is not None:
                label += f" (cumulative {_percent(min(share, 1.0))} %)"
            hot.append((-(share or 0.0), label))
    reason = "hot functions: " + ", ".join(label for _, label in sorted(hot))
    attributes = (
        f"path={data_line(document.path)} "
        f'lines="{document.start_line}-{document.end_line}" reason={data_line(reason)}'
    )
    if document.spawn_findings:
        shown = list(document.spawn_findings[:SPAWN_FINDINGS_SHOWN])
        rest = len(document.spawn_findings) - len(shown)
        if rest:
            shown.append(f"{rest} more")
        finding = "; ".join(shown) + (
            "; an edit may not touch this statement or the names it binds"
        )
        attributes += f" spawn_finding={data_line(finding)}"
    return f"<document {attributes}>\n{document.rendered}\n</document>"


def _percent(share: float) -> str:
    return f"{round(share * 100, 1):g}"


# --------------------------------------------------------------------------
# The lane views (G2): one slice of the profiled repository per lens lane
# --------------------------------------------------------------------------

VIEW_FACTS_MAX_BYTES: Final = 8 * 1024
VIEW_SCAN_FILES: Final = 200
CALL_SITES_MAX: Final = 40
USES_MAX: Final = 30
INPUT_FILES_MAX: Final = 4
INPUT_SAMPLE_BYTES: Final = 64 * 1024
INPUT_HEAD_LINES: Final = 5
FACT_TEXT_CHARS: Final = 200
HISTORY_WALK_MAX: Final = 400
HISTORY_COMMITS_MAX: Final = 20
HISTORY_DIFF_BYTES: Final = 256 * 1024
_PERF: Final = re.compile(
    r"\b(?:speed\w*|fast\w*|perf|performance|optimi[sz]\w*|slow\w*|cach\w*"
    r"|accelerat\w*|efficien\w*|memory|quick\w*|latency|throughput)\b",
    re.IGNORECASE,
)
_DIFF_HEAD: Final = re.compile(r"^diff --git a/(.*) b/(.*)$", re.MULTILINE)
_LOOPS: Final = (ast.For, ast.AsyncFor, ast.While, ast.ListComp, ast.SetComp,
                 ast.DictComp, ast.GeneratorExp)  # fmt: skip
_SCOPES: Final = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_KINDS: Final[Mapping[type[ast.AST], str]] = {
    ast.Dict: "dict literal", ast.List: "list literal", ast.Set: "set literal",
    ast.Tuple: "tuple literal", ast.ListComp: "comprehension",
    ast.SetComp: "comprehension", ast.DictComp: "comprehension",
    ast.GeneratorExp: "comprehension",
}  # fmt: skip
_SUBSCRIPT: Final[Mapping[type[ast.expr_context], str]] = {
    ast.Load: "subscript_read", ast.Store: "subscript_write",
    ast.Del: "subscript_delete",
}  # fmt: skip


@runtime_checkable
class HistoryReader(Protocol):
    """Commits read backwards from one; ``GitWorkspace`` is the real one."""

    def resolve_commit(self, rev: str) -> str: ...

    def commit_message(self, commit: str) -> bytes: ...

    def diff_commits(self, base: str, tip: str, *, max_bytes: int = ...) -> str: ...


@dataclass(frozen=True)
class ViewSource:
    """What every view reads: S0's reader, commit, profile, fence and rules."""

    reader: RepoReader
    commit: str
    hotspots: tuple[Hotspot, ...]
    fence: Fence
    protected: tuple[str, ...]
    read_deny: tuple[str, ...]
    limits: IdeaReadLimits
    workloads: tuple[Workload, ...] = ()
    history: HistoryReader | None = None


@dataclass(frozen=True)
class LaneView:
    """One lane's view: the documents it sees and grounds in, and its facts
    (``label: <JSON>`` lines, rendered by ``render_data_block``)."""

    name: IdeaView
    context: CodeContext
    facts: tuple[str, ...] = ()


_Builder = Callable[[ViewSource, frozenset[str], list[str]], "LaneView | None"]


def build_view(name: IdeaView, source: ViewSource, notes: list[str]) -> LaneView | None:
    """One lens lane's view (G2) at ``source.commit``, or ``None`` when its
    code cannot be shown. Every note is prefixed ``view <name>: ``."""
    found: list[str] = []
    try:
        tracked = frozenset(source.reader.ls_tree(source.commit))
    except GitError:
        found.append("the base commit's file list is unreadable in git")
        view = None
    else:
        view = _BUILDERS[name](source, tracked, found)
    notes.extend(f"view {name}: {note}" for note in found)
    return view


def _key(spot: Hotspot) -> tuple[str, str]:
    return spot.file_path, spot.symbol


def _by_self(hotspots: Sequence[Hotspot]) -> list[Hotspot]:
    """One hotspot per (file, symbol), largest self-time share first; never
    cProfile's ``<module>`` row (D51)."""
    ranked = sorted(hotspots, key=lambda h: (-h.share, -h.self_time_s,
                                             -h.total_time_s, h.file_path, h.symbol))  # fmt: skip
    first: dict[tuple[str, str], Hotspot] = {}
    for spot in ranked:
        if spot.symbol != "<module>":
            first.setdefault(_key(spot), spot)
    return list(first.values())


def _context(
    source: ViewSource,
    keys: Sequence[tuple[str, str]],
    notes: list[str],
    **limits: object,
) -> CodeContext:
    """S0's reading of ``keys`` alone, within the whole-file size: no whole
    file, textual callers or header unless ``limits`` turns them back on."""
    base = source.limits
    update = {"whole_files": False, "callers": False, "header_max_lines": 0,
              "code_max_bytes": base.file_max_bytes, **limits}  # fmt: skip
    return read_code_context(
        source.reader, source.commit, source.hotspots, fence=source.fence,
        protected=source.protected, read_deny=source.read_deny,
        limits=base.model_copy(update=update), notes=notes, only=keys,
    )  # fmt: skip


def _anchor(
    source: ViewSource, notes: list[str], *, module: bool = False
) -> tuple[Hotspot, CodeContext] | None:
    """The hottest function by self time that can be shown, alone, so the
    lane's quotes ground (D50); ``module``: with its whole file, or as much
    of its hot code as the call's code cap holds."""
    ranked = _by_self(source.hotspots)
    cap, header = source.limits.code_max_bytes, source.limits.header_max_lines
    for spot in ranked[: source.limits.hot_functions]:
        if module:
            keys = [
                _key(spot),
                *(_key(h) for h in ranked if h.file_path == spot.file_path),
            ]
            context = _context(source, keys, notes, whole_files=True, callers=True,
                               header_max_lines=header, max_files=1,
                               file_max_bytes=cap, code_max_bytes=cap)  # fmt: skip
        else:
            context = _context(source, [_key(spot)], notes)
        if context.documents:
            return spot, context
    notes.append("no hot function could be shown")
    return None


def _clip(text: str) -> str:
    return text[:FACT_TEXT_CHARS]


def _callee(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _callers(
    source: ViewSource, tracked: frozenset[str], notes: list[str]
) -> LaneView | None:
    """Who calls the hot function (by its last name, textually: the profile
    holds no call graph, O36.3), how often and with what argument shape."""
    found = _anchor(source, notes)
    if found is None:
        return None
    spot, context = found
    name = spot.symbol.rsplit(".", 1)[-1]
    sites: list[tuple[str, int, str]] = []
    keys: list[tuple[str, str]] = []
    for loaded, module in _scan(source, tracked, spot.file_path, notes):
        nodes = loaded.nodes or []
        for call, loop in _calls_named(module, name):
            holding = [n for n in nodes if n.start <= call.lineno <= n.end]
            node = max(holding, key=lambda n: n.depth, default=None)
            listed = [h for h in source.hotspots if h.file_path == loaded.path
                      and node is not None and _node_of(nodes, h) == node]  # fmt: skip
            keys += [_key(h) for h in listed]
            fact = {
                "path": loaded.path, "line": call.lineno,
                "caller": "<module>" if node is None else node.qualname,
                "call": _clip(loaded.shown[call.lineno - 1].strip()),
                "positional": len(call.args),
                "keywords": [k.arg or "**" for k in call.keywords],
                "in_loop": loop,
                "caller_calls": max((h.calls for h in listed if h.calls is not None),
                                    default=None),
            }  # fmt: skip
            sites.append((loaded.path, call.lineno, f"call site: {data_line(fact)}"))
    sites.sort()
    count_note(notes, len(sites) - CALL_SITES_MAX,
               f"call site(s) not listed (limit {CALL_SITES_MAX})")  # fmt: skip
    if keys:
        context = _context(source, [_key(spot), *keys], notes)
    calls = {h.workload_id: h.calls for h in source.hotspots
             if _key(h) == _key(spot) and h.calls is not None}  # fmt: skip
    hot = data_line({"path": spot.file_path, "symbol": spot.symbol, "calls": calls})
    facts = (f"hot function: {hot}", *(f for _, _, f in sites[:CALL_SITES_MAX]))
    return LaneView("callers", context, facts)


def _scan(
    source: ViewSource, tracked: frozenset[str], first: str, notes: list[str]
) -> Iterator[tuple[_File, ast.Module]]:
    """The parsed Python files S0 may show, the hot file first, at most
    ``VIEW_SCAN_FILES``; each read as S0 reads it (``_load``)."""
    patterns = (*DEFAULT_PROTECTED_PATTERNS, *source.protected, *source.read_deny)
    paths = sorted(
        (p for p in tracked if p.endswith(".py") and not (
            unprintable(p) or source.fence.holds(p) or read_denied(p)
            or any(matches_pattern(p, x) for x in patterns))),
        key=lambda p: (p != first, p),
    )  # fmt: skip
    count_note(notes, len(paths) - VIEW_SCAN_FILES,
               f"file(s) not scanned for callers (limit {VIEW_SCAN_FILES})")  # fmt: skip
    for path in paths[:VIEW_SCAN_FILES]:
        loaded = _load(source.reader, source.commit, path, source.fence,
                       source.limits, [])  # fmt: skip
        if loaded is not None and loaded.module is not None:
            yield loaded, loaded.module


def _calls_named(tree: ast.AST, name: str) -> Iterator[tuple[ast.Call, bool]]:
    """Every call of ``name`` and whether a loop of its own scope holds it."""
    stack: list[tuple[ast.AST, bool]] = [(tree, False)]
    while stack:
        node, loop = stack.pop()
        if isinstance(node, ast.Call) and _callee(node.func) == name:
            yield node, loop
        inner = isinstance(node, _LOOPS) or (loop and not isinstance(node, _SCOPES))
        stack.extend((child, inner) for child in ast.iter_child_nodes(node))


def _structures(
    source: ViewSource, tracked: frozenset[str], notes: list[str]
) -> LaneView | None:
    """The data the hot function touches: module-level names with their
    kind and size, the classes it names or runs in, and each name's uses."""
    found = _anchor(source, notes)
    if found is None:
        return None
    spot, context = found
    loaded = _load(source.reader, source.commit, spot.file_path, source.fence,
                   source.limits, [])  # fmt: skip
    node = None if loaded is None or not loaded.nodes else _node_of(loaded.nodes, spot)
    if loaded is None or loaded.module is None or node is None:
        return LaneView("data_structures", context)
    names = {n.id for n in ast.walk(node.tree) if isinstance(n, ast.Name)}
    facts: list[str] = []
    for stmt in loaded.module.body:
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in names:
                fact = {"name": target.id, "line": stmt.lineno, "kind": _kind(value),
                        "size": _size(value),
                        "text": _clip(loaded.shown[stmt.lineno - 1].strip())}  # fmt: skip
                facts.append(f"module name: {data_line(fact)}")
    for cls in loaded.nodes or ():
        tree = cls.tree
        if isinstance(tree, ast.ClassDef) and (
            cls.name in names or cls.start <= node.start <= cls.end
        ):
            facts.append(f"class: {data_line(_class_fact(cls.qualname, tree))}")
    uses = _uses(node.tree)
    facts += [f"uses: {data_line({'name': key, 'uses': dict(sorted(uses[key].items()))})}"
              for key in sorted(uses)[:USES_MAX]]  # fmt: skip
    return LaneView("data_structures", context, tuple(facts))


def _kind(value: ast.expr) -> str:
    if isinstance(value, ast.Constant):
        return f"constant {type(value.value).__name__}"
    if isinstance(value, ast.Call):
        return f"call to {_callee(value.func) or 'an expression'}"
    return _KINDS.get(type(value), type(value).__name__)


def _size(value: ast.expr) -> int | None:
    if isinstance(value, ast.Dict):
        return len(value.keys)
    return (
        len(value.elts) if isinstance(value, ast.List | ast.Set | ast.Tuple) else None
    )


def _class_fact(qualname: str, tree: ast.ClassDef) -> dict[str, object]:
    decorators = (d.func if isinstance(d, ast.Call) else d for d in tree.decorator_list)
    slots = any(isinstance(s, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "__slots__" for t in s.targets)
        for s in tree.body)  # fmt: skip
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                  and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name)
                  and n.value.id == "self"}  # fmt: skip
    return {
        "class": qualname, "line": tree.lineno,
        "bases": [b for b in map(_callee, tree.bases) if b],
        "decorators": [d for d in map(_callee, decorators) if d],
        "slots": slots, "attributes": sorted(attributes)[:20],
    }  # fmt: skip


def _uses(tree: ast.AST) -> dict[str, Counter[str]]:
    """Per name (``x`` or ``x.attr``): the methods called on it, subscripts,
    augmented assignments, iteration, ``len`` and membership tests."""
    uses: dict[str, Counter[str]] = {}

    def add(target: ast.expr, use: str) -> None:
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            uses.setdefault(f"{target.value.id}.{target.attr}", Counter())[use] += 1
        elif isinstance(target, ast.Name):
            uses.setdefault(target.id, Counter())[use] += 1

    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            add(n.func.value, n.func.attr)
        elif isinstance(n, ast.Call) and _callee(n.func) == "len" and n.args:
            add(n.args[0], "len")
        elif isinstance(n, ast.Subscript):
            add(n.value, _SUBSCRIPT[type(n.ctx)])
        elif isinstance(n, ast.AugAssign):
            add(n.target, "augmented")
        elif isinstance(n, ast.For | ast.AsyncFor | ast.comprehension):
            add(n.iter, "iterated")
        elif isinstance(n, ast.Compare):
            for op, right in zip(n.ops, n.comparators, strict=True):
                if isinstance(op, ast.In | ast.NotIn):
                    add(right, "membership")
    return uses


def _inputs(
    source: ViewSource, tracked: frozenset[str], notes: list[str]
) -> LaneView | None:
    """The workloads' real inputs: each command and inputs, and a summary
    and head of every tracked file they name (data, never a script). A
    secret-like or frozen quality file is never read."""
    found = _anchor(source, notes)
    if found is None:
        return None
    if not source.workloads:
        notes.append("no workload is known, so no input is shown")
        return LaneView("input_shape", found[1])
    facts: list[str] = []
    paths: list[str] = []
    for workload in source.workloads:
        facts.append("workload: " + data_line({"name": workload.name, "argv": list(
            workload.command), "inputs": dict(workload.inputs)}))  # fmt: skip
        named = (*workload.command[1:],
                 *(v for v in workload.inputs.values() if isinstance(v, str)))  # fmt: skip
        for value in named:
            path = _under(workload.working_dir, value)
            if (path is None or path not in tracked or path in paths
                    or path.endswith(".py") or path == workload.entrypoint):  # fmt: skip
                continue
            if read_denied(path):
                notes.append(f"{path}: {DENIED}")
            elif any(matches_pattern(path, p) for p in source.read_deny):
                notes.append(f"{path}: never read (a frozen quality file)")
            else:
                paths.append(path)
    count_note(notes, len(paths) - INPUT_FILES_MAX,
               f"input file(s) not read (limit {INPUT_FILES_MAX})")  # fmt: skip
    for path in paths[:INPUT_FILES_MAX]:
        facts.append(f"input file: {data_line(_input_summary(source, path, notes))}")
    return LaneView("input_shape", found[1], tuple(facts))


def _under(working_dir: str, value: str) -> str | None:
    try:
        return normalize_path(posixpath.join(working_dir, value))
    except ValueError:
        return None


def _input_summary(
    source: ViewSource, path: str, notes: list[str]
) -> dict[str, object]:
    try:
        found = read_text(source.reader, source.commit, path, cap=INPUT_SAMPLE_BYTES)
    except GitError:
        notes.append(f"{path}: unreadable in git")
        return {"path": path, "kind": "unreadable"}
    if not isinstance(found, ReadText):
        return {"path": path, "kind": found}
    lines = found.text.replace("\r\n", "\n").split("\n")
    if lines[-1] == "":
        lines.pop()
    sizes = [len(line) for line in lines]
    return {
        "path": path, "bytes": len(found.text.encode()), "cut": found.cut,
        "lines": len(lines), "blank_lines": sum(not line.strip() for line in lines),
        "distinct_lines": len(set(lines)), "longest_line": max(sizes, default=0),
        "mean_line": round(sum(sizes) / len(sizes), 1) if sizes else 0.0,
        "ascii": found.text.isascii(),
        "head": [_clip(line) for line in _screen(lines[:INPUT_HEAD_LINES])[0]],
    }  # fmt: skip


def _module(
    source: ViewSource, tracked: frozenset[str], notes: list[str]
) -> LaneView | None:
    found = _anchor(source, notes, module=True)
    return None if found is None else LaneView("whole_module", found[1])


def _next(
    source: ViewSource, tracked: frozenset[str], notes: list[str]
) -> LaneView | None:
    ranked = _by_self(source.hotspots)
    if len(ranked) < 2:
        notes.append("no 2nd or 3rd hotspot in the profile")
        return None
    keys = [_key(h) for h in ranked[1:3]]
    context = _context(source, keys, notes,
                       header_max_lines=source.limits.header_max_lines)  # fmt: skip
    if not context.documents:
        notes.append("the 2nd and 3rd hotspots could not be shown")
        return None
    top = data_line({"path": ranked[0].file_path, "symbol": ranked[0].symbol})
    return LaneView("next_hotspots", context, (f"hottest function (not shown): {top}",))


def _history(
    source: ViewSource, tracked: frozenset[str], notes: list[str]
) -> LaneView | None:
    """The project's own past performance commits, as prior art. The walk
    starts at the pinned commit and only ever steps to a parent, so no
    commit after the pin can be reached (the contamination guard)."""
    found = _anchor(source, notes)
    if found is None:
        return None
    if source.history is None:
        notes.append("no commit history reader, so no commit is shown")
        return LaneView("history", found[1])
    hot = {h.file_path for h in source.hotspots}
    facts = _perf_commits(source.history, source.commit, hot, source.fence, notes)
    return LaneView("history", found[1], tuple(facts))


def _perf_commits(
    history: HistoryReader, pinned: str, hot: set[str], fence: Fence, notes: list[str]
) -> list[str]:
    """Performance commits among ``pinned`` and its ancestors, nearest first:
    breadth first over every parent, so a speed-up merged in through a merge
    commit is seen as ``git log`` sees it; at most ``HISTORY_COMMITS_MAX``
    within ``HISTORY_WALK_MAX`` commits. Only parents are ever followed."""
    facts: list[str] = []
    queue, seen = deque([pinned]), {pinned}
    for _ in range(HISTORY_WALK_MAX):
        commit = queue.popleft()
        try:
            message = history.commit_message(commit).decode("utf-8", "replace")
        except GitError:
            notes.append(f"commit {commit[:12]}: commit message unreadable; the "
                         "walk stops")  # fmt: skip
            return facts
        parents = _parents(history, commit)
        if _PERF.search(message):
            lines = [line.strip() for line in message.strip().split("\n")]
            files = _commit_files(history, parents[0], commit, fence,
                                  notes) if parents else []  # fmt: skip
            facts.append("commit: " + data_line({
                "commit": commit[:12], "subject": _clip(lines[0]),
                "body": [_clip(line) for line in lines[1:] if line][:3],
                "files": files[:10], "touches_hot_file": not hot.isdisjoint(files),
            }))  # fmt: skip
            if len(facts) == HISTORY_COMMITS_MAX:
                return facts
        fresh = [parent for parent in parents if parent not in seen]
        seen.update(fresh)
        queue.extend(fresh)
        if not queue:
            return facts
    notes.append(f"history walk stopped after {HISTORY_WALK_MAX} commits "
                 f"(limit {HISTORY_WALK_MAX})")  # fmt: skip
    return facts


def _parents(history: HistoryReader, commit: str) -> list[str]:
    """``commit``'s parents in order (``<sha>^1``, ``^2``, ... until git has
    none): none for a root commit, two or more for a merge."""
    parents: list[str] = []
    while True:
        try:
            parents.append(history.resolve_commit(f"{commit}^{len(parents) + 1}"))
        except GitError:
            return parents


def _commit_files(
    history: HistoryReader, parent: str, commit: str, fence: Fence, notes: list[str]
) -> list[str]:
    try:
        diff = history.diff_commits(parent, commit, max_bytes=HISTORY_DIFF_BYTES)
    except GitError:
        notes.append(f"commit {commit[:12]}: files unreadable (the diff is not text)")
        return []
    return _diff_paths(diff, fence)


def _diff_paths(diff: str, fence: Fence) -> list[str]:
    """Each file a patch changes (the new path of a rename), once; a path
    that is unprintable or holds a live token is left out."""
    paths: list[str] = []
    for match in _DIFF_HEAD.finditer(diff):
        path = match.group(2)
        if not (unprintable(path) or fence.holds(path)) and path not in paths:
            paths.append(path)
    return paths


def _view_facts(facts: Sequence[str], fence: Fence, notes: list[str]) -> list[str]:
    """``facts`` within ``VIEW_FACTS_MAX_BYTES``; one holding a live token or
    a secret shape is withheld; none at all reads ``(none found)``."""
    kept: list[str] = []
    room, withheld, dropped = VIEW_FACTS_MAX_BYTES, 0, 0
    for fact in facts:
        size = len(fact.encode()) + 1
        if fence.holds(fact) or _SECRET.search(fact):
            withheld += 1
        elif size > room:
            dropped += 1
        else:
            room -= size
            kept.append(fact)
    count_note(notes, withheld, "view fact(s) withheld: they hold a boundary token "
               "or a secret shape")  # fmt: skip
    count_note(notes, dropped, f"view fact(s) dropped (limit {VIEW_FACTS_MAX_BYTES} "
               "bytes)")  # fmt: skip
    return kept or ["(none found)"]


# --------------------------------------------------------------------------
# The reviewer's documents (G2): it checks quotes in the code a lane was shown
# --------------------------------------------------------------------------

_NUMBERED: Final = re.compile(r"L([1-9][0-9]*): (.*)", re.DOTALL)


def review_context(
    shared: CodeContext, views: Sequence[CodeContext], *, cap: int, notes: list[str]
) -> CodeContext:
    """The shared block's documents plus what ``views`` showed beyond them,
    so the reviewer sees every line an idea could be grounded in: a path
    both show is one document of both line sets, a new path follows. The
    added rendered bytes stay within ``cap``; a document past it is left
    out, noted. A view adding nothing leaves the shared documents as they
    are."""
    documents = {d.path: d for d in shared.documents}
    room, left_out = cap, []
    for context in views:
        for document in context.documents:
            have = documents.get(document.path)
            merged = document if have is None else _union(have, document)
            if merged is have:
                continue
            grow = len(merged.rendered.encode()) - (
                0 if have is None else len(have.rendered.encode())
            )
            if grow > room:
                left_out.append(document.path)
            else:
                room -= grow
                documents[document.path] = merged
    if left_out:
        notes.append(f"{len(left_out)} view document(s) not shown to the reviewer "
                     f"(limit {cap} bytes): " + ", ".join(left_out))  # fmt: skip
    return CodeContext(
        documents=tuple(documents.values()),
        totals_by_workload=shared.totals_by_workload,
    )


def _union(have: CodeDocument, extra: CodeDocument) -> CodeDocument:
    """One file's two documents (the same commit, so a line reads the same
    in both) as one: ``have`` itself when ``extra`` shows no other line."""
    shown, raw = _numbered_lines(have), _raw_lines(have)
    more = _numbered_lines(extra)
    if more.keys() <= shown.keys():
        return have
    extra_raw = _raw_lines(extra)
    for number, text in more.items():
        shown.setdefault(number, text)
        raw.setdefault(number, extra_raw[number])
    first, last = min(shown), max(shown)
    spans: dict[tuple[str, int, int], FunctionSpan] = {}
    for span in (*have.spans, *extra.spans):
        key = (span.qualname, span.start_line, span.end_line)
        known = spans.get(key)
        ids = span.hotspot_ids if known is None else known.hotspot_ids
        merged_ids = tuple(dict.fromkeys((*ids, *span.hotspot_ids)))
        spans[key] = span.model_copy(update={"hotspot_ids": merged_ids})
    return have.model_copy(update={
        "start_line": first, "end_line": last,
        "rendered": _numbered(sorted(shown.items())),
        "raw": "\n".join(raw.get(n, "") for n in range(first, last + 1)),
        "spans": tuple(sorted(spans.values(),
                              key=lambda s: (s.start_line, -s.end_line))),
        "spawn_findings": have.spawn_findings or extra.spawn_findings,
    })  # fmt: skip


def _numbered_lines(document: CodeDocument) -> dict[int, str]:
    """Each shown line of a document as S0 rendered it (``L<n>: <text>``);
    the ``(lines a-b not shown)`` gaps are not lines."""
    found: dict[int, str] = {}
    for row in document.rendered.split("\n"):
        match = _NUMBERED.fullmatch(row)
        if match is not None:
            found[int(match.group(1))] = match.group(2)
    return found


def _raw_lines(document: CodeDocument) -> dict[int, str]:
    rows = document.raw.split("\n")
    return {n: rows[n - document.start_line] for n in _numbered_lines(document)}


_BUILDERS: Final[Mapping[IdeaView, _Builder]] = {
    "callers": _callers,
    "data_structures": _structures,
    "input_shape": _inputs,
    "whole_module": _module,
    "next_hotspots": _next,
    "history": _history,
}
