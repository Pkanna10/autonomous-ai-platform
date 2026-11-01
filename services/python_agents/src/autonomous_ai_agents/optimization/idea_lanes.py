"""One idea lane: its request, its named defaults and its reply (Step 3 Wave 2,
N2; spec amendment 3.4, 4.2b.2, 4.2b.7, D45, D50, D59, D60).

- ``lane_request``: the system prompt, the data block as its own text block
  (the cached prefix: a 5-minute breakpoint for S1 and the lenses, none for
  the leap, whose prompt is sent once on another model) and the instruction.
- ``on_the_table``: titles as ASCII-escaped JSON data lines, so no title can
  forge an element; a title holding a live token or a tag shape is withheld.
- ``read_lane_reply``: the reply is untrusted. ``read_reply`` refuses a cut,
  declined or off-schema reply as a whole (enums included); then each idea is
  dropped, with a note and an ``idea_dropped`` event, when a text field is
  empty, over its cap, unprintable, holds a code fence, a live token or a tag
  shape, when it holds no 1 to 3 morph cells, when its title repeats one
  (whitespace collapsed, case-folded) or, outside S1, when its quote is not
  grounded (D50). An S1 idea with no grounding is kept without an anchor.
  Hotspots resolve against the shown profile only; ``lane`` comes from the
  request; numbers are clamped as today's generator clamps them.
- ``grounded``: the quote, without ``L123:`` prefixes and with whitespace
  collapsed, must occur in the named shown document's grounding text inside
  a hot function, and one of its lines must hold code, not only a comment or
  a docstring (``tokenize`` over the function; line by line when the shown
  function no longer tokenizes, e.g. a withheld line inside a string).
"""

from __future__ import annotations

import io
import re
import tokenize
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from typing import Final, Literal

from pydantic import Field

from autonomous_ai_agents.clients.structured import (
    Fence,
    Strict,
    check_count,
    clamp_unit,
    count_note,
    data_line,
    read_reply,
    shorten,
    shown,
    structured_request,
    text_problem,
)
from autonomous_ai_agents.clients.transport import LLMRequest, LLMResult
from autonomous_ai_agents.common.config import Effort
from autonomous_ai_agents.common.models import ChangeClass
from autonomous_ai_agents.common.paths import normalize_path
from autonomous_ai_agents.optimization.generate import (
    MAX_EXPECTED_GAIN,
    MAX_HOTSPOT_REFS,
    MAX_REPLY_ITEMS,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
)
from autonomous_ai_agents.optimization.idea_context import anchor_of
from autonomous_ai_agents.optimization.idea_prompts import (
    MAX_QUOTE_CHARS,
    MAX_QUOTE_LINES,
    MIN_QUOTE_CHARS,
)
from autonomous_ai_agents.optimization.idea_types import (
    Anchor,
    CodeContext,
    CodeDocument,
    GenerateEvent,
    IdeaCandidate,
    Lane,
    Mechanism,
    MorphCell,
    Tier,
    Typicality,
)

MAX_TABLE_TITLES: Final = 60
MAX_PATH_CHARS: Final = 300
MAX_MORPH_CELLS: Final = 3
_TAG_SHAPE: Final = re.compile(
    r"</?(?:idea|hypothesis|untrusted_|already_on_the_table|lens|example|document)",
    re.IGNORECASE,
)
_LINE_PREFIX: Final = re.compile(r"^\s*L\d+:\s?")
_NOT_CODE: Final = frozenset(
    {"COMMENT", "STRING", "NL", "NEWLINE", "INDENT", "DEDENT", "ENDMARKER",
     "FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END",
     "TSTRING_START", "TSTRING_MIDDLE", "TSTRING_END"}
)  # fmt: skip


def tag_shape(text: str) -> bool:
    """Whether ``text`` holds the start of an element a prompt uses."""
    return _TAG_SHAPE.search(text) is not None


def title_key(title: str) -> str:
    return " ".join(title.split()).casefold()


def lane_request(
    lane: Lane,
    *,
    system: str,
    prefix: str,
    instruction: str,
    schema: Mapping[str, object],
    max_tokens: int,
    effort: Effort | None,
) -> LLMRequest:
    """One lane's request; the data block carries the breakpoint unless the
    lane is the leap (D59: no cache write where nothing reads it)."""
    return structured_request(
        system,
        instruction,
        schema=schema,
        max_tokens=max_tokens,
        effort=effort,
        cache=lane is not Lane.leap,
        prefix=prefix,
    )


def on_the_table(titles: Sequence[str], fence: Fence, notes: list[str]) -> str:
    """``<already_on_the_table>``: one ``data_line`` per distinct title."""
    lines: list[str] = []
    seen: set[str] = set()
    withheld = hidden = 0
    for title in titles:
        key = title_key(title)
        line = data_line(title)
        if not key or key in seen:
            continue
        if fence.holds(line) or tag_shape(title):
            withheld += 1
            continue
        seen.add(key)
        if len(lines) == MAX_TABLE_TITLES:
            hidden += 1
        else:
            lines.append(line)
    count_note(notes, withheld, "title(s) withheld from <already_on_the_table>: "
               "they hold a boundary token or a tag shape")  # fmt: skip
    count_note(
        notes, hidden, f"title(s) not put on the table (limit {MAX_TABLE_TITLES})"
    )
    return fence.block("already_on_the_table", lines or ["(none)"])


# --------------------------------------------------------------------------
# The reply
# --------------------------------------------------------------------------


class _HotspotRef(Strict):
    file_path: str
    symbol: str


class _Idea(Strict):
    title: str
    technique_slug: str | None
    hotspots: list[_HotspotRef] = Field(max_length=MAX_HOTSPOT_REFS)
    change_summary: str
    justification_summary: str
    depends_on_path: str
    depends_on_quote: str
    precondition: str
    equivalence_summary: str
    mechanism: Mechanism
    morph_cells: list[MorphCell] = Field(max_length=len(MorphCell))
    tier: Tier
    typicality: Typicality
    change_class: Literal["efficiency", "behaviour", "novel"]
    expected_gain: float
    provability: float
    risk: float


class _Reply(Strict):
    hypotheses: list[_Idea] = Field(max_length=MAX_REPLY_ITEMS)


def read_lane_reply(
    result: LLMResult,
    *,
    lane: Lane,
    context: CodeContext,
    index: Mapping[tuple[str, str], list[str]],
    n: int,
    fence: Fence,
    notes: list[str],
    events: list[GenerateEvent] | None = None,
) -> tuple[IdeaCandidate, ...]:
    """At most ``n`` validated ideas of ``lane``, in the model's order.

    ``UnusableReplyError`` when the reply as a whole cannot be used; every
    dropped idea is noted and, when ``events`` is given, appended there as
    an ``idea_dropped`` event (D65). ``fence`` must hold every live token.
    """
    n = check_count("n", n, MAX_REPLY_ITEMS)
    reply = read_reply(result, _Reply, what=f"write ideas for the {lane.value} lane")
    label = f"lane {lane.value}"
    kept: list[IdeaCandidate] = []
    titles: set[str] = set()

    def drop(item: _Idea, reason: str, note: str, **where: str) -> None:
        notes.append(note)
        if events is not None:
            data: dict[str, str | None] = {"lane": lane.value, "reason": reason,
                                           "title": shorten(item.title), **where}  # fmt: skip
            events.append(GenerateEvent(code="idea_dropped", message=note, data=data))

    for position, item in enumerate(reply.hypotheses):
        if len(kept) == n:
            rest = len(reply.hypotheses) - position
            notes.append(f"{label}: dropped {rest} idea(s) beyond the first {n}")
            break
        named = shown(item.title)
        cells = tuple(dict.fromkeys(item.morph_cells))
        problem = _field_problem(item, fence)
        if problem is None and not 1 <= len(cells) <= MAX_MORPH_CELLS:
            problem = f"its morph_cells hold {len(cells)} cell(s), not 1 to 3"
        if problem is not None:
            drop(item, problem, f"{label}: dropped idea {named}: {problem}")
            continue
        found = _ground(item.depends_on_path, item.depends_on_quote, context)
        anchor = None
        if isinstance(found, str) and lane is not Lane.obvious:
            drop(item, found, f"{label}: dropped idea {named}: {found}",
                 path=item.depends_on_path, quote=item.depends_on_quote[:80])  # fmt: skip
            continue
        if isinstance(found, str):
            notes.append(f"{label}: idea {named} kept without an anchor: {found}")
        else:
            anchor = found[0]
        if title_key(item.title) in titles:
            drop(item, "duplicate title", f"{label}: dropped duplicate idea {named}")
            continue
        titles.add(title_key(item.title))
        ids = _hotspot_ids(item, index, f"{label}: idea {named}", notes)
        kept.append(_candidate(item, lane, len(kept) + 1, cells, anchor, ids))
    return tuple(kept)


def _field_problem(item: _Idea, fence: Fence) -> str | None:
    """``"its <field> ..."`` for the first unusable text field, else ``None``."""
    fields = [
        ("title", item.title, MAX_TITLE_CHARS, True),
        ("technique_slug", item.technique_slug, MAX_TITLE_CHARS, True),
        ("change_summary", item.change_summary, MAX_SUMMARY_CHARS, False),
        ("justification_summary", item.justification_summary, MAX_SUMMARY_CHARS, False),
        ("depends_on_path", item.depends_on_path, MAX_PATH_CHARS, True),
        ("depends_on_quote", item.depends_on_quote, MAX_QUOTE_CHARS, False),
        ("precondition", item.precondition, MAX_SUMMARY_CHARS, False),
        ("equivalence_summary", item.equivalence_summary, MAX_SUMMARY_CHARS, False),
    ]
    for name, value, cap, one_line in fields:
        if value is None:
            continue
        problem = text_problem(value, cap, one_line=one_line)
        if problem is not None and not problem.startswith("holds"):
            problem = f"is {problem}"
        elif problem is None and "```" in value:
            problem = "holds a code block"
        elif problem is None and fence.holds(value):
            problem = "holds a boundary token"
        elif problem is None and tag_shape(value):
            problem = "holds a tag shape"
        if problem is not None:
            return f"its {name} {problem}"
    return None


def _candidate(
    item: _Idea,
    lane: Lane,
    number: int,
    cells: tuple[MorphCell, ...],
    anchor: Anchor | None,
    hotspot_ids: tuple[str, ...],
) -> IdeaCandidate:
    return IdeaCandidate(
        id=f"{lane.value}-{number:02d}",
        lane=lane,
        title=item.title,
        technique_slug=item.technique_slug,
        hotspot_ids=hotspot_ids,
        change_summary=item.change_summary,
        justification_summary=item.justification_summary,
        change_class=ChangeClass(item.change_class),
        expected_gain=max(0.0, min(MAX_EXPECTED_GAIN, item.expected_gain)),
        provability=clamp_unit(item.provability),
        risk=clamp_unit(item.risk),
        depends_on_path=item.depends_on_path,
        depends_on_quote=item.depends_on_quote,
        precondition=item.precondition,
        equivalence_summary=item.equivalence_summary,
        mechanism=item.mechanism,
        morph_cells=cells,
        tier=item.tier,
        typicality=item.typicality,
        anchor=anchor,
    )


def _hotspot_ids(
    item: _Idea,
    index: Mapping[tuple[str, str], list[str]],
    named: str,
    notes: list[str],
) -> tuple[str, ...]:
    ids: list[str] = []
    for ref in item.hotspots:
        try:
            path = normalize_path(ref.file_path)
        except ValueError:
            notes.append(f"{named}: dropped hotspot {shown(ref.file_path)}: "
                         "not a repo-relative path")  # fmt: skip
            continue
        found = index.get((path, ref.symbol))
        if found is None:
            notes.append(f"{named}: dropped hotspot {shown(ref.file_path)} "
                         f"{shown(ref.symbol)}: not a listed hotspot")  # fmt: skip
            continue
        ids.extend(i for i in found if i not in ids)
    return tuple(ids)


# --------------------------------------------------------------------------
# Grounding (D50)
# --------------------------------------------------------------------------


def grounded(path: str, quote: str, context: CodeContext) -> tuple[int, int] | None:
    """The document lines (first, last) the quote matches in hot code, or ``None``."""
    found = _ground(path, quote, context)
    return None if isinstance(found, str) else found[1]


def _ground(
    path: str, quote: str, context: CodeContext
) -> tuple[Anchor, tuple[int, int]] | str:
    """The anchor and the matched lines, or why the quote grounds nothing."""
    try:
        wanted: str | None = normalize_path(path)
    except ValueError:
        wanted = None
    document = next((d for d in context.documents if d.path == wanted), None)
    if document is None:
        return f"its depends_on_path {shown(path)} names no shown document"
    lines = [_LINE_PREFIX.sub("", t, count=1) for t in quote.strip("\n").split("\n")]
    target = " ".join(" ".join(lines).split())
    if len(lines) > MAX_QUOTE_LINES:
        return f"its quote has more than {MAX_QUOTE_LINES} lines"
    if len(target.replace(" ", "")) < MIN_QUOTE_CHARS:
        return f"its quote holds under {MIN_QUOTE_CHARS} non-whitespace characters"
    text, starts, owners = _collapsed(document)
    why = f"its quote is not found in {shown(document.path)}"
    at = text.find(target)
    while at >= 0:
        first = owners[bisect_right(starts, at) - 1]
        last = owners[bisect_right(starts, at + len(target) - 1) - 1]
        anchor = anchor_of(document.path, (first, last), context)
        if anchor is None:
            why = "its quote lies outside every hot function"
        elif _has_code(document, first, last):
            return anchor, (first, last)
        else:
            why = "its quote is only a comment or a docstring"
        at = text.find(target, at + 1)
    return why


def _collapsed(document: CodeDocument) -> tuple[str, list[int], list[int]]:
    """The grounding text with whitespace collapsed, each word's start and line."""
    words: list[str] = []
    starts: list[int] = []
    owners: list[int] = []
    position = 0
    for number, line in enumerate(document.raw.split("\n"), document.start_line):
        for word in line.split():
            words.append(word)
            starts.append(position)
            owners.append(number)
            position += len(word) + 1
    return " ".join(words), starts, owners


def _has_code(document: CodeDocument, first: int, last: int) -> bool:
    """Whether a line in ``first..last`` holds code, read in its outermost hot
    function so a docstring line is seen as part of its string."""
    outer = max(
        (s for s in document.spans
         if s.hotspot_ids and s.start_line <= first and last <= s.end_line),
        key=lambda s: s.end_line - s.start_line,
    )  # fmt: skip
    offset = outer.start_line - document.start_line
    lines = document.raw.split("\n")[
        offset : offset + outer.end_line - outer.start_line + 1
    ]
    rows = _code_rows(lines)
    return any(number - outer.start_line in rows for number in range(first, last + 1))


def _code_rows(lines: list[str]) -> set[int]:
    """0-based indices of ``lines`` that start a code token."""
    try:
        return {t.start[0] - 1 for t in _tokens("\n".join(lines))}
    except (tokenize.TokenError, SyntaxError):
        found: set[int] = set()
        for i, line in enumerate(lines):
            try:
                if _tokens(line.strip()):
                    found.add(i)
            except (tokenize.TokenError, SyntaxError):
                pass
        return found


def _tokens(source: str) -> list[tokenize.TokenInfo]:
    """The code tokens of ``source`` (raises on what does not tokenize)."""
    reader = io.StringIO(source + "\n").readline
    return [t for t in tokenize.generate_tokens(reader)
            if tokenize.tok_name[t.type] not in _NOT_CODE]  # fmt: skip
