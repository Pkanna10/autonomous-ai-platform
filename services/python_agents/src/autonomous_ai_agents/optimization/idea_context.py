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
import re
import unicodedata
import warnings
from ast import parse as _ast_parse
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Final

from pydantic import Field

from autonomous_ai_agents.clients.structured import (
    Fence,
    data_line,
    hotspot_rows,
    understanding_lines,
)
from autonomous_ai_agents.common.config import Settings
from autonomous_ai_agents.common.models import (
    EngineModel,
    Hotspot,
    Objective,
    Project,
    ProjectUnderstanding,
)
from autonomous_ai_agents.common.paths import matches_pattern
from autonomous_ai_agents.common.repo_read import (
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
) -> CodeContext:
    """The hot code at ``commit`` (D44); every exclusion, cut and fallback is
    noted in ``notes`` and in the context's own ``notes``."""
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
    seen: set[tuple[str, str]] = set()
    chosen: list[Hotspot] = []
    for spot in ranked:
        if (spot.file_path, spot.symbol) not in seen:
            seen.add((spot.file_path, spot.symbol))
            chosen.append(spot)
    chosen = chosen[: limits.hot_functions]
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
        loaded.nodes = list(_walk(tree))
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
    whole = len("\n".join(found.raw).encode()) <= limits.file_max_bytes
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
    out: list[str] = []
    previous = None
    for number in sorted(lines):
        if previous is not None and number != previous + 1:
            out.append(f"(lines {previous + 1}-{number - 1} not shown)")
        out.append(f"L{number}: {found.shown[number - 1]}")
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
) -> str:
    """The fenced data block: project, objective, floor, understanding,
    profile rows and the documents, in that order; byte-stable for one
    context and fence. Anything holding a live token is withheld, noted."""

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
        "hot code at the base commit (line numbers are for reference; quote the "
        "code, not the numbers):",
    ]
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
