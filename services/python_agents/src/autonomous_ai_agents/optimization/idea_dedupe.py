"""What is already taken: the mechanism key, the block a sequential lane is
shown, and the dedupe's acceptance scorer (Step 3 idea lab, G4;
spec-idea-lab section 1 G4).

The key (``KEY_RULE``). Two ideas are one mechanism when

1. their **target lines** lie in one file and share at least one line. An
   idea's target lines are the lines its ``depends_on_quote`` matches in the
   shown code (``quote_lines``: ``L123:`` prefixes stripped, whitespace
   collapsed, the first match inside the anchor's function span, as the
   grounding check anchored it, else in the whole document; the file is the
   anchor's, else the named shown document); and
2. they claim one **transformation**: the same ``mechanism`` and the same
   primary morph cell (``morph_cells[0]``).

Titles, summaries and every other text are ignored, so a mechanism cannot
return under a new title. An idea whose quote matches no shown line has no
key and is never merged. ``representatives`` merges each key into the first
earlier kept key it matches (greedy, in the given order).

``taken_block`` renders the keys for a sequential lane: one ASCII JSON line
per distinct key (file, function, lines, mechanism, cell), never a title,
under the request's fence, with a "do not repeat" lead-in. Every value is
engine-derived (shown paths, ``ast`` qualnames, line numbers, enum values).

The dedupe is itself a measurement, so it counts only once ``score`` passes
the bar fixed before it runs (at least ``MIN_AGREEMENT`` of labelled pairs
agree and at most ``MAX_DIFFERENT_MERGED`` of different-mechanism pairs are
merged); until then a report shows the raw idea lists beside the dedupe's
output (``DedupeScore.show_raw``). ``load_recorded`` reads E1's recorded
lane replies (V6's ``recorded.json`` and its code files) and
``candidate_pairs`` forms the same-file pairs a labeller is shown.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Final, Self

from pydantic import Field, JsonValue, field_validator, model_validator

from autonomous_ai_agents.clients.structured import (
    Fence,
    count_note,
    data_line,
    shown,
)
from autonomous_ai_agents.common.models import (
    EngineModel,
    JsonScalar,
    VerdictOutcome,
)
from autonomous_ai_agents.common.paths import normalize_path
from autonomous_ai_agents.optimization.idea_lanes import tag_shape
from autonomous_ai_agents.optimization.idea_types import (
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

KEY_RULE: Final = (
    "same file and overlapping target lines (the quote's lines in the shown "
    "code), the same mechanism and the same primary morph cell (G4, v1)"
)
MIN_AGREEMENT: Final = Fraction(9, 10)
MAX_DIFFERENT_MERGED: Final = Fraction(1, 20)
"""The bar, fixed before the dedupe is scored (spec-idea-lab G4)."""
MAX_TAKEN_LINES: Final = 48
TAKEN_TAG: Final = "already_on_the_table_mechanisms"
"""Its prefix is a tag shape ``idea_lanes.tag_shape`` already refuses."""
TAKEN_LEAD: Final = (
    f"Mechanisms earlier lanes of this request already proposed, inside "
    f"<{TAKEN_TAG}>, one per line: the file, the function, the target lines, "
    "the mechanism and the primary morph cell. Do not repeat these mechanisms: "
    "an idea that changes the same lines by the same transformation is a "
    "repeat whatever its title. Change other code, or change it another way."
)
SEEDED_LEAD: Final = (
    f"Mechanisms already on the table, inside <{TAKEN_TAG}>, one per line: the "
    "file, the function, the target lines, the mechanism and the primary morph "
    "cell. A mechanism this run already trialled also carries its title, its "
    "verdict (keeps first) and its measured primary gain as a multiple of the "
    "noise floor (null: not measured). Do not repeat these mechanisms: an idea "
    "that changes the same lines by the same transformation is a repeat "
    "whatever its title. Change other code, or change it another way."
)
"""The lead-in once a round seed is shown (G5b); ``TAKEN_LEAD`` otherwise."""
KEY_EVENT: Final = "idea_mechanism"
"""The event code that records a hypothesis's mechanism key (G5b)."""
SEED_TITLE_CHARS: Final = 80
_UNTITLED: Final = "(untitled)"
_TITLE_SWAPS: Final = str.maketrans({'"': "'", "\\": "/", "<": "(", ">": ")"})
_LINE_PREFIX: Final = re.compile(r"^\s*L\d+:\s?")
_PLAIN_NAME: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_Text = Annotated[str, Field(min_length=1)]
_Line = Annotated[int, Field(ge=1)]


class Target(EngineModel):
    """An idea's target lines: 1-based, inclusive, in one repo file."""

    path: _Text
    first: _Line
    last: _Line

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.last < self.first:
            raise ValueError(f"last {self.last} is before first {self.first}")
        return self


class MechanismKey(EngineModel):
    target: Target
    mechanism: Mechanism
    cell: MorphCell


class IdeaKey(EngineModel):
    """A mechanism key and the function the idea's anchor names (G5b)."""

    key: MechanismKey
    function: str | None = None


class Seed(EngineModel):
    """One trialled idea a lens lane is shown (G5b); the title is model
    text, so it is made plain (``plain_title``) whatever it was given."""

    key: IdeaKey
    title: str
    outcome: VerdictOutcome
    gain_over_floor: float | None = Field(allow_inf_nan=False)

    @field_validator("title", mode="before")
    @classmethod
    def _plain(cls, value: object) -> object:
        return plain_title(value) if isinstance(value, str) else value


def plain_title(title: str) -> str:
    """One capped line of printable ASCII with no character JSON would
    escape and no angle bracket (the evolution harness's rule, G4's fence)."""
    flat = " ".join(title.split()).translate(_TITLE_SWAPS)
    kept = "".join(c if c.isascii() and c.isprintable() else "?" for c in flat)
    return kept[:SEED_TITLE_CHARS].strip() or _UNTITLED


def key_event(hypothesis_id: str, title: str, key: IdeaKey) -> GenerateEvent:
    """The record of a hypothesis's key the next round seeds from."""
    target = key.key.target
    return GenerateEvent(
        code=KEY_EVENT,
        message=f"{shown(title)} targets {target.path}:{target.first}-{target.last}",
        data={"hypothesis_id": hypothesis_id, "path": target.path,
              "function": key.function, "first": target.first, "last": target.last,
              "mechanism": key.key.mechanism.value, "cell": key.key.cell.value},
    )  # fmt: skip


class _KeyRecord(EngineModel):
    code: str
    hypothesis_id: _Text
    path: _Text
    function: str | None
    first: _Line
    last: _Line
    mechanism: Mechanism
    cell: MorphCell


def recorded_keys(events: Iterable[Mapping[str, JsonScalar]]) -> dict[str, IdeaKey]:
    """Each hypothesis's key from the node's event data (``KEY_EVENT``, the
    first record of an id wins); a malformed record is skipped."""
    found: dict[str, IdeaKey] = {}
    for data in events:
        if data.get("code") != KEY_EVENT:
            continue
        fields = {name: data.get(name) for name in _KeyRecord.model_fields}
        try:
            row = _KeyRecord.model_validate(fields)
            target = Target(path=row.path, first=row.first, last=row.last)
        except ValueError:
            continue
        key = MechanismKey(target=target, mechanism=row.mechanism, cell=row.cell)
        found.setdefault(row.hypothesis_id, IdeaKey(key=key, function=row.function))
    return found


# --------------------------------------------------------------------------
# The key
# --------------------------------------------------------------------------


def quote_lines(raw: str, quote: str, *, start: int = 1) -> tuple[int, int] | None:
    """The (first, last) lines of ``raw`` (its first line is ``start``) the
    quote's first match covers, whitespace collapsed, or ``None``."""
    rows = [_LINE_PREFIX.sub("", row, count=1) for row in quote.strip("\n").split("\n")]
    needle = " ".join(" ".join(rows).split())
    if not needle:
        return None
    words: list[str] = []
    starts: list[int] = []
    owners: list[int] = []
    position = 0
    for number, line in enumerate(raw.split("\n"), start):
        for word in line.split():
            words.append(word)
            starts.append(position)
            owners.append(number)
            position += len(word) + 1
    at = " ".join(words).find(needle)
    if at < 0:
        return None
    first = owners[bisect_right(starts, at) - 1]
    return first, owners[bisect_right(starts, at + len(needle) - 1) - 1]


def target_of(idea: IdeaCandidate, context: CodeContext) -> Target | None:
    """The idea's target lines in the shown document of its anchor (else
    of its ``depends_on_path``), or ``None``."""
    path: str | None = None if idea.anchor is None else idea.anchor.path
    if path is None:
        try:
            path = normalize_path(idea.depends_on_path)
        except ValueError:
            return None
    document = next((d for d in context.documents if d.path == path), None)
    if document is None:
        return None
    lines = _anchored_lines(idea, document)
    return None if lines is None else Target(path=path, first=lines[0], last=lines[1])


def _anchored_lines(
    idea: IdeaCandidate, document: CodeDocument
) -> tuple[int, int] | None:
    """The quote's first match inside the anchor's span (each span named by
    the anchor's qualname, in order), as grounding anchored it; the whole
    document's first match when no span carries that name."""
    name = None if idea.anchor is None else idea.anchor.qualname
    spans = [s for s in document.spans if s.qualname == name]
    if not spans:
        return quote_lines(
            document.raw, idea.depends_on_quote, start=document.start_line
        )
    rows = document.raw.split("\n")
    for span in spans:
        start = span.start_line - document.start_line
        body = "\n".join(rows[start : span.end_line - document.start_line + 1])
        lines = quote_lines(body, idea.depends_on_quote, start=span.start_line)
        if lines is not None:
            return lines
    return None


def mechanism_key(
    target: Target | None, mechanism: Mechanism, cells: Sequence[MorphCell]
) -> MechanismKey | None:
    if target is None or not cells:
        return None
    return MechanismKey(target=target, mechanism=mechanism, cell=cells[0])


def idea_key(idea: IdeaCandidate, context: CodeContext) -> MechanismKey | None:
    return mechanism_key(target_of(idea, context), idea.mechanism, idea.morph_cells)


def same_mechanism(a: MechanismKey | None, b: MechanismKey | None) -> bool:
    """``KEY_RULE``: one file, a shared line, one mechanism and primary cell."""
    if a is None or b is None:
        return False
    return (
        a.target.path == b.target.path
        and a.target.first <= b.target.last
        and b.target.first <= a.target.last
        and a.mechanism is b.mechanism
        and a.cell is b.cell
    )


def representatives(keys: Sequence[MechanismKey | None]) -> tuple[int, ...]:
    """Each position's representative: the first earlier kept key it
    matches, else itself (kept); ``len(set(...))`` counts the mechanisms."""
    kept: list[int] = []
    found: list[int] = []
    for i, key in enumerate(keys):
        twin = next((k for k in kept if same_mechanism(keys[k], key)), None)
        if twin is None:
            kept.append(i)
        found.append(i if twin is None else twin)
    return tuple(found)


# --------------------------------------------------------------------------
# The block a sequential lane is shown
# --------------------------------------------------------------------------


def taken_block(
    ideas: Sequence[IdeaCandidate],
    keys: Mapping[str, MechanismKey],
    fence: Fence,
    notes: list[str],
    seeds: Sequence[Seed] = (),
) -> str:
    """The lead-in and ``<already_on_the_table_mechanisms>``, one line per
    distinct key: ``seeds`` first (G5b; in their order, each with its title,
    outcome and gain over the floor), then ``ideas``' keys no line holds
    yet; ``""`` when no line is left. With no seed shown it is G4's block."""
    lines: list[str] = []
    seen: set[MechanismKey] = set()
    counts = {"withheld": 0, "hidden": 0}
    shown_seed = False

    def add(
        key: MechanismKey, function: str | None, extra: dict[str, JsonScalar]
    ) -> bool:
        seen.add(key)
        line = data_line({
            "path": key.target.path, "function": function,
            "lines": f"{key.target.first}-{key.target.last}",
            "mechanism": key.mechanism.value, "cell": key.cell.value, **extra,
        })  # fmt: skip
        if fence.holds(line) or tag_shape(line):
            counts["withheld"] += 1
        elif len(lines) == MAX_TAKEN_LINES:
            counts["hidden"] += 1
        else:
            lines.append(line)
            return True
        return False

    for seed in seeds:
        if seed.key.key not in seen:
            extra: dict[str, JsonScalar] = {
                "title": seed.title, "outcome": seed.outcome.value,
                "gain_over_floor": seed.gain_over_floor,
            }  # fmt: skip
            shown_seed = add(seed.key.key, seed.key.function, extra) or shown_seed
    for idea in ideas:
        key = keys.get(idea.id)
        if key is not None and key not in seen:
            add(key, None if idea.anchor is None else idea.anchor.qualname, {})
    count_note(notes, counts["withheld"], "mechanism line(s) withheld: they hold a "
               "boundary token or a tag shape")  # fmt: skip
    count_note(
        notes,
        counts["hidden"],
        f"mechanism line(s) not shown (limit {MAX_TAKEN_LINES})",
    )
    if not lines:
        return ""
    lead = SEEDED_LEAD if shown_seed else TAKEN_LEAD
    return f"{lead}\n{fence.block(TAKEN_TAG, lines)}"


# --------------------------------------------------------------------------
# E1's recorded ideas, the candidate pairs and the acceptance scorer
# --------------------------------------------------------------------------


class RecordedIdea(EngineModel):
    """One idea of a recorded lane reply, as written, with its target."""

    library: _Text
    lane: Lane
    position: _Line
    title: str
    change_summary: str
    mechanism: Mechanism
    morph_cells: tuple[MorphCell, ...]
    path: str
    quote: str
    target: Target | None

    @property
    def ident(self) -> str:
        return f"{self.lane.value}-{self.position:02d}"

    def key(self) -> MechanismKey | None:
        return mechanism_key(self.target, self.mechanism, self.morph_cells)


class CandidatePair(EngineModel):
    """Two same-file ideas of one library and the dedupe's verdict on them."""

    id: _Text
    first: RecordedIdea
    second: RecordedIdea
    overlap: bool
    merged: bool


class PairLabel(EngineModel):
    pair_id: _Text
    same: bool


class DedupeScore(EngineModel):
    rule: str = KEY_RULE
    labelled: int
    agreed: int
    agreement: float
    same_pairs: int
    same_merged: int
    different_pairs: int
    different_merged: int
    different_merged_share: float | None
    passed: bool
    show_raw: bool
    """Reports show the raw idea lists beside the dedupe until it passes."""
    why: str


def candidate_pair(first: RecordedIdea, second: RecordedIdea) -> CandidatePair:
    a, b = first.target, second.target
    overlap = (
        a is not None and b is not None and a.path == b.path
        and a.first <= b.last and b.first <= a.last
    )  # fmt: skip
    return CandidatePair(
        id=f"{first.library}:{first.ident}|{second.ident}",
        first=first,
        second=second,
        overlap=overlap,
        merged=same_mechanism(first.key(), second.key()),
    )


def candidate_pairs(ideas: Sequence[RecordedIdea]) -> tuple[CandidatePair, ...]:
    """Every pair of one library naming one file, in the ideas' order (a
    pair across files is never the same target lines)."""
    return tuple(
        candidate_pair(a, b)
        for i, a in enumerate(ideas)
        for b in ideas[i + 1 :]
        if a.library == b.library and a.path == b.path
    )


def score(pairs: Sequence[CandidatePair], labels: Sequence[PairLabel]) -> DedupeScore:
    """The dedupe against ``labels`` (the labelled subset of ``pairs``)."""
    by_id: dict[str, CandidatePair] = {}
    for pair in pairs:
        if pair.id in by_id:
            raise ValueError(f"pair id {pair.id!r} appears twice")
        by_id[pair.id] = pair
    if not labels:
        raise ValueError("no labelled pair to score")
    seen: set[str] = set()
    same = same_merged = different = different_merged = 0
    for label in labels:
        if label.pair_id not in by_id:
            raise ValueError(f"label names an unknown pair {label.pair_id!r}")
        if label.pair_id in seen:
            raise ValueError(f"pair {label.pair_id!r} is labelled twice")
        seen.add(label.pair_id)
        merged = int(by_id[label.pair_id].merged)
        if label.same:
            same, same_merged = same + 1, same_merged + merged
        else:
            different, different_merged = different + 1, different_merged + merged
    agreed = same_merged + different - different_merged
    agreement = Fraction(agreed, len(labels))
    share = Fraction(different_merged, different) if different else None
    problems = []
    if agreement < MIN_AGREEMENT:
        problems.append(f"agreement {float(agreement):.1%} is under "
                        f"{float(MIN_AGREEMENT):.0%}")  # fmt: skip
    if share is None:
        problems.append("no different-mechanism pair is labelled")
    elif share > MAX_DIFFERENT_MERGED:
        problems.append(f"{float(share):.1%} of different-mechanism pairs merged, "
                        f"over {float(MAX_DIFFERENT_MERGED):.0%}")  # fmt: skip
    if not same:
        problems.append("no same-mechanism pair is labelled")
    return DedupeScore(
        labelled=len(labels), agreed=agreed, agreement=float(agreement),
        same_pairs=same, same_merged=same_merged, different_pairs=different,
        different_merged=different_merged,
        different_merged_share=None if share is None else float(share),
        passed=not problems, show_raw=bool(problems),
        why="; ".join(problems) or "passed the fixed bar",
    )  # fmt: skip


class _Hotspot(EngineModel):
    file_path: str
    symbol: str


class _ReplyIdea(EngineModel):
    """One item of ``idea_prompts.IDEAS_SCHEMA``, exactly."""

    title: str
    technique_slug: str | None
    hotspots: tuple[_Hotspot, ...]
    change_summary: str
    justification_summary: str
    depends_on_path: str
    depends_on_quote: str
    precondition: str
    equivalence_summary: str
    mechanism: Mechanism
    morph_cells: tuple[MorphCell, ...]
    tier: Tier
    typicality: Typicality
    change_class: str
    expected_gain: float
    provability: float
    risk: float


class _Reply(EngineModel):
    hypotheses: tuple[_ReplyIdea, ...]


class _Library(EngineModel):
    repo: str
    wave1: str
    licence: str
    upstream: str
    facts: JsonValue
    code: tuple[str, ...]
    replies: dict[str, str]
    recorded: JsonValue


class _Recorded(EngineModel):
    source: str
    arm: str
    libraries: tuple[_Library, ...]


def load_recorded(path: Path) -> tuple[RecordedIdea, ...]:
    """Every lane idea of the recorded replies (the reviewer's is skipped),
    each with its target in ``<path's dir>/code/<repo>/<file>.txt``. The
    replies are model output: read as data, never followed."""
    data = _Recorded.model_validate_json(path.read_text(encoding="utf-8"))
    found: list[RecordedIdea] = []
    for library in data.libraries:
        files = _code(path.parent / "code", library)
        for label, reply in library.replies.items():
            if label == "reviewer":
                continue
            if label not in Lane.__members__:
                raise ValueError(f"{library.repo}: reply label {label!r} is not a lane")
            items = _Reply.model_validate(json.loads(reply)).hypotheses
            for position, item in enumerate(items, 1):
                found.append(
                    _recorded(library.repo, Lane(label), position, item, files)
                )
    return tuple(found)


def _code(root: Path, library: _Library) -> dict[str, str]:
    if _PLAIN_NAME.fullmatch(library.repo) is None or ".." in library.repo:
        raise ValueError(f"repo {library.repo!r} is not a plain directory name")
    base = (root / library.repo).resolve()
    files: dict[str, str] = {}
    for name in library.code:
        where = (base / f"{name}.txt").resolve()
        try:
            clean = normalize_path(name) == name
        except ValueError:
            clean = False
        if not clean or not where.is_relative_to(base):
            raise ValueError(f"{library.repo}: {name!r} leaves its code directory")
        files[name] = where.read_text(encoding="utf-8")
    return files


def _recorded(
    library: str, lane: Lane, position: int, item: _ReplyIdea, files: Mapping[str, str]
) -> RecordedIdea:
    try:
        path: str | None = normalize_path(item.depends_on_path)
    except ValueError:
        path = None
    raw = None if path is None else files.get(path)
    lines = None if raw is None else quote_lines(raw, item.depends_on_quote)
    return RecordedIdea(
        library=library,
        lane=lane,
        position=position,
        title=item.title,
        change_summary=item.change_summary,
        mechanism=item.mechanism,
        morph_cells=tuple(dict.fromkeys(item.morph_cells)),
        path=item.depends_on_path if path is None else path,
        quote=item.depends_on_quote,
        target=None if path is None or lines is None
        else Target(path=path, first=lines[0], last=lines[1]),
    )  # fmt: skip
