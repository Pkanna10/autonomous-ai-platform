"""Vf: the X1 report (idea-lab spec 6.5, with 6.2's measures), offline.

Pure code over results files: no request, no network, and the same bytes on
every run. ``uv run python -m live.ideas_report <results.jsonl>... [--e1 DIR]
[--out DIR]`` (from ``tests/``, ``PYTHONPATH=../src:.``) reads X1's rows and
writes, under ``--out`` (``REPORT_DIR`` by default):

- ``<library>-<configuration>.md``: every idea (title, mechanism, target
  lines, predicted ceiling, the auditor's verdict and what it repeats, the
  slice's trial verdict, lane and model), proposals in their own section;
- ``measures.md``: 6.2's measures per configuration, X1-4's proposals by rule
  relaxed (no score), cost with D64's seeded column and slice USD per win;
- ``tables.md`` and ``ceilings.svg``: 6.5's four comparison tables;
- ``owner-sample.md`` (no source) and ``owner-sample-key.json`` (the source).

Rows read (every other kind is skipped; a kind read is parsed strictly, its
fields by name, and a malformed row refuses the report): Vd's ``ideas-idea``,
``ideas-probe``, ``ideas-audit`` and ``ideas-proposal``; Vc's
``ideas-validate-score`` (exactly one; until its bar passes the raw titles
show beside the dedupe); E1's ``ideas-facts`` (floors, hotspots) and its arms
B, C and D's ``ideas-probe`` rows (``--e1``). Ve's slice, the contract this
report reads (optional rows, as ``ideas_slice.SliceRecorder`` writes them):
``ideas-slice-trial`` (repo, arm, label, position: the ``ideas-idea`` row it
ran; title, verdict, gain_pct, floor_pct, op_count; ``keep`` is a win) and
one ``ideas-slice-combine`` per (configuration, library) engine run (repo,
arm, summary chunks, cost_usd of the whole run and D64's seeded_calls and
seeded_cost_usd from its state, both required: 0 when no seeded call ran);
O39's fields: the trial's grader and ``grader_validated``. The pooled
ranking's rows as ``ideas_pool.rank_library`` writes them (the slice for its
four libraries, the ``ideas-pool`` suite for the other four): one
``ideas-pool-set`` a set request (repo, marker, model, validated, round, set,
of, ids, seed, shown, order, advanced, error) and one ``ideas-pool-result``
a library and marker (members with their ids, apart, top, requests, rounds).

O40/O41 (owner, 2026-11-03): marker-feasible is pooled. Per library, every
returned lens-lane idea of X1-0 to X1-3 forms one pool, ranked by a
tournament of sets of at most ``SET_SIZE`` (the set size the marker was
validated on); the measure is how many of the final set's top ``MARKER_TOP``
each configuration supplied, beside the full record (every round's sets,
each set's order, which advanced). The validated marker never ranks its own
model's ideas (listed apart); the other candidate ranks the whole pool, its
counts marked unvalidated. A row that breaks those rules, or a set past the
set size, is refused. Until Vc's dedupe passes its
bar, unique mechanisms and the share new to today's generator carry
``bound``'s label (read from the score row: under-merging makes them upper
bounds), the raw lists and counts beside them.

Readings: a configuration's ideas are its result, the returned non-proposal
``ideas-idea`` rows (``ProbeRow.ideas``' and the slice's population; "lane
ideas" counts every reply idea beside them), its audited ideas the reviewed
``ideas-audit`` rows with ``in_result``. A predicted ceiling is the share of
the innermost profiled hotspot holding the idea's target lines
(``amdahl_ceiling``'s rule on recorded rows: Vd's rows carry no anchor);
unique mechanisms are ``representatives`` of the ideas' mechanism keys within
a library (a keyless idea is its own); an idea is new to today's generator
when its class under the auditor's duplicate links, joined either way
(``ideas_slice.families``' rule), holds no arm-A audit; auditor-feasible is a
review that is not ``infeasible``.

V-rep (O42-O44): good counts are the corrected and strict ones (the as-coded
count rewards the arm the auditor read first: only in the per-library
appendix, labelled so); self/cross repeats count each audit row's
``duplicate_of`` link once, its target looked up in its own library (ids
restart in each), over in-result rows (the headline) and all audit rows;
X1-1's lens-lane USD per model (priced from ``ideas-reply`` usage) beside
its unique new mechanisms. ``--rerun`` (O42's X1-1 re-run: arms A and X1-1
alone) and ``--reaudit`` (its pooled re-audit, ``ideas-reaudit`` rows whose
digests name the re-run and one results file) go together: the re-run's
X1-1 probe, idea and reply rows replace those libraries', and the re-audit's
rows every audit-based figure there (the probe counts recomputed by
``audit_scores``); the headers name each library's files.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from autonomous_ai_agents.clients.cost import response_cost
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.optimization.idea_context import _totals
from autonomous_ai_agents.optimization.idea_dedupe import (
    MAX_DIFFERENT_MERGED,
    MIN_AGREEMENT,
    DedupeScore,
    MechanismKey,
    Target,
    mechanism_key,
    representatives,
)
from autonomous_ai_agents.optimization.idea_types import (
    LENS_LANES,
    Lane,
    Mechanism,
    MorphCell,
    RelaxedRule,
)

from . import ideas_pool as ipool
from .conftest import redact_keys
from .discovery_io import cells
from .ideas_probe import (
    AUDIT_EXPERIMENT,
    E1_REPOS,
    IDEA_EXPERIMENT,
    PROPOSAL_EXPERIMENT,
    REPLY_EXPERIMENT,
    ROW_EXPERIMENT,
    SERVICE_DIR,
    SQUARE_MODELS,
    X1_ARMS,
    FactsBody,
    load_facts,
)
from .ideas_reaudit import REAUDIT_EXPERIMENT
from .ideas_reaudit import REAUDIT_REPOS as REAUDIT_REPOS
from .ideas_validate import E1_DIR as E1_DIR
from .ideas_validate import SCORE_EXPERIMENT as DEDUPE_EXPERIMENT

REPORT_DIR: Final = SERVICE_DIR.parents[1] / ".claude/handoff/step3/idea-lab/x1"
SET_EXPERIMENT: Final = ipool.SET_EXPERIMENT
RESULT_EXPERIMENT: Final = ipool.RESULT_EXPERIMENT
POOL_CONFIGS: Final = ipool.POOL_CONFIGS
SET_SIZE: Final = ipool.SET_SIZE  # O41: the set size the marker was validated on
VB_SETS: Final = ipool.VB_SETS
MARKER_TOP: Final = ipool.TOP  # O40: the pool's top 3
TRIAL_EXPERIMENT: Final = "ideas-slice-trial"
COMBINE_EXPERIMENT: Final = "ideas-slice-combine"
NOTE_PREFIXES: Final = ("Vc's ", "These rows are the raw list")
CONFIGS: Final = tuple(a.key for a in X1_ARMS)  # A, then X1-0 to X1-4
TODAY, BASELINE = "A", "X1-0"
LEVERS: Final = CONFIGS[2:]
NOISE_ARMS: Final = ("B", "C", "D")  # E1: one Sonnet lane generator, three times
DELTA_MEASURES: Final = ("ideas", "non_obvious", "good_corrected", "good_strict",
                         "feasible", "cost_usd")  # O43: never the as-coded good  # fmt: skip
HANDED_ON: Final = "what the arm handed on (in-result rows)"  # O44's headline
GENERATED: Final = "every idea the lanes generated (all audit rows)"
_BAD: Final = "infeasible"
NO_BAND: Final = ("unique", "new", "above", "families")  # E1 has no idea rows
SAMPLE_SEED: Final = 20261103
SAMPLE_SIZE: Final = 24
LENSES: Final = tuple(lane.value for lane in LENS_LANES)
_LANES: Final = ("today", *(lane.value for lane in Lane))
_T = TypeVar("_T", bound="_Row")
_K = TypeVar("_K", bound=Hashable)
_V = TypeVar("_V")


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Lines(_Row):
    first: int
    last: int


class IdeaLine(_Row):
    repo: str
    arm: str
    lane: str
    label: str
    model: str
    position: int
    title: str
    change: str
    returned: bool
    proposal: bool
    relaxes: RelaxedRule | None
    mechanism: Mechanism | None
    cells: tuple[MorphCell, ...]
    path: str | None
    target: Lines | None

    @model_validator(mode="after")
    def _keyed(self) -> Self:
        self.key()  # a target ``Target`` refuses is a malformed row
        return self

    def key(self) -> MechanismKey | None:
        t = self.target
        if self.mechanism is None or self.path is None or t is None:
            return None
        target = Target(path=self.path, first=t.first, last=t.last)
        return mechanism_key(target, self.mechanism, self.cells)

    def where(self) -> str:
        t = self.target
        return "-" if t is None else f"{self.path}:{t.first}-{t.last}"


class ProbeLine(_Row):
    repo: str
    arm: str
    ideas: int
    non_obvious: int
    good: int | None  # as coded: a reading-order artifact (O43), appendix only
    audited: int
    auditor_infeasible: int
    proposals: int = 0  # ``ProbeRow``'s default; E1's rows predate it
    cost_usd: float
    good_corrected: int | None = None  # E1's rows predate both
    good_strict: int | None = None
    lever: str = ""
    lane_models: dict[str, str] = Field(default_factory=dict)  # X1-1: lens -> model

    @property
    def feasible(self) -> int:
        return self.audited - self.auditor_infeasible


class AuditLine(_Row):
    repo: str
    arm: str
    id: str
    title: str
    tier: int
    in_result: bool
    auditor: str | None
    reason: str | None
    duplicate_of: str | None


class ReauditLine(AuditLine):  # ``ideas_reaudit.ReauditSink``'s rows
    run1_sha256: str
    rerun_sha256: str


class ReplyLine(_Row):
    repo: str
    arm: str
    role: str
    label: str
    sent: bool
    usage: tuple[int, int, int, int]  # input, output, cache read, cache write


class ProposalLine(_Row):
    repo: str
    arm: str
    title: str
    rationale: tuple[str, ...]


class OpCount(_Row):
    present: bool
    cell: str | None
    base: float | None
    trial: float | None
    change: float | None


class TrialLine(_Row):
    repo: str
    arm: str
    label: str
    position: int
    title: str
    verdict: str
    gain_pct: float | None
    floor_pct: float | None
    op_count: OpCount
    grader: str | None  # None: the fallback order, no marker
    grader_validated: bool | None

    @model_validator(mode="after")
    def _graded(self) -> Self:
        if (self.grader is None) != (self.grader_validated is None):
            raise ValueError("grader and grader_validated: both or neither")
        return self


_NAME: Final = r"^[a-z0-9][a-z0-9.-]{0,63}$"  # shown in a heading: a plain name


class PoolKey(_Row):
    arm: str
    label: str
    position: int

    @model_validator(mode="after")
    def _config(self) -> Self:
        if self.arm not in POOL_CONFIGS:
            raise ValueError(f"{self.arm}: not one of X1-0 to X1-3")
        return self


class PoolMember(PoolKey):
    id: str


class PoolSetLine(_Row):
    repo: str
    marker: str
    round: int
    set: int
    of: int
    ids: tuple[str, ...]
    seed: str
    shown: tuple[str, ...]
    order: tuple[str, ...] | None  # the marker's, most likely first
    advanced: tuple[str, ...]
    error: str | None
    titles: tuple[str, ...] | None = None  # clipped, in ``ids``' order, when recorded

    @model_validator(mode="after")
    def _set(self) -> Self:
        ids, order = sorted(self.ids), self.order
        if not 0 < len(ids) <= SET_SIZE:
            raise ValueError(f"a set of {len(ids)} ideas, past the validated set size")
        if self.titles is not None and len(self.titles) != len(ids):
            raise ValueError("the titles are not one per id")
        if sorted(self.shown) != ids or (order is not None and sorted(order) != ids):
            raise ValueError("the shown order or the order is not a permutation")
        top = () if order is None or self.of == 1 else order[: ipool.ADVANCE]
        if self.advanced != top:
            raise ValueError("advanced is not the order's top two")
        return self


class PoolResultLine(_Row):
    repo: str
    marker: str = Field(pattern=_NAME)
    model: str = Field(pattern=_NAME)
    validated: bool
    members: tuple[PoolMember, ...]
    apart: tuple[PoolKey, ...]
    top: tuple[str, ...] | None
    requests: int
    rounds: int


class CombineLine(_Row):
    repo: str
    arm: str
    summary: tuple[str, ...]
    cost_usd: float
    seeded_calls: int  # D64's state keys
    seeded_cost_usd: float


class DedupeLine(_Row):
    score: DedupeScore | None


_KINDS: Final[Mapping[str, type[_Row]]] = {
    IDEA_EXPERIMENT: IdeaLine, ROW_EXPERIMENT: ProbeLine, AUDIT_EXPERIMENT: AuditLine,
    PROPOSAL_EXPERIMENT: ProposalLine, TRIAL_EXPERIMENT: TrialLine,
    COMBINE_EXPERIMENT: CombineLine, DEDUPE_EXPERIMENT: DedupeLine,
    SET_EXPERIMENT: PoolSetLine, RESULT_EXPERIMENT: PoolResultLine,
    REPLY_EXPERIMENT: ReplyLine,
}  # fmt: skip
_READ: Final[Mapping[str, type[_Row]]] = {
    **_KINDS,
    REAUDIT_EXPERIMENT: ReauditLine,
}  # the re-audit: opted in


def _parsed(paths: Iterable[Path], kinds: Iterable[str]) -> dict[str, list[_Row]]:
    """The rows of ``kinds`` in ``paths``, each strictly by its fields' names."""
    found: dict[str, list[_Row]] = {kind: [] for kind in kinds}
    for path in paths:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                row = json.loads(line) if line.strip() else {}
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n}: not JSON ({exc.msg})") from None
            kind = row.get("experiment") if isinstance(row, dict) else None
            if kind not in found:
                continue
            model = _READ[kind]
            try:
                fields = {k: v for k, v in row.items() if k in model.model_fields}
                found[kind].append(model.model_validate(fields))
            except ValidationError as exc:
                e = exc.errors()[0]
                why = f"{'.'.join(map(str, e['loc'])) or 'row'}: {e['msg']}"
                raise ValueError(f"{path}:{n}: malformed {kind} row ({why})") from None
    return found


def _of(found: Mapping[str, list[_Row]], kind: str, cls: type[_T]) -> tuple[_T, ...]:
    return tuple(r for r in found[kind] if isinstance(r, cls))


@dataclass(frozen=True)
class Rows:
    ideas: tuple[IdeaLine, ...]
    probes: tuple[ProbeLine, ...]
    audits: tuple[AuditLine, ...]
    proposals: tuple[ProposalLine, ...]
    trials: tuple[TrialLine, ...]
    combines: tuple[CombineLine, ...]
    dedupe: DedupeScore | None
    pool_sets: tuple[PoolSetLine, ...] = ()
    pool_results: tuple[PoolResultLine, ...] = ()
    replies: tuple[ReplyLine, ...] = ()
    sources: tuple[tuple[str, str], ...] = ()  # (library, the files its figures use)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rerun_of(found: Mapping[str, list[_Row]]) -> set[str]:
    """The libraries holding the X1-1 re-run's shape: arms A and X1-1 alone."""
    arms = _grouped(_of(found, ROW_EXPERIMENT, ProbeLine), lambda p: p.repo)
    return {r for r, ps in arms.items() if {p.arm for p in ps} == {TODAY, "X1-1"}}


def _at(i: IdeaLine | TrialLine) -> tuple[str, str, str, int]:
    return (i.repo, i.arm, i.label, i.position)


def _pool_id(i: IdeaLine) -> str:  # ``ideas_pool.idea_id``: the row key's hash
    return ipool.idea_id(ipool.IdeaRow.model_validate(
        {"experiment": IDEA_EXPERIMENT, **i.model_dump(mode="json")}))  # fmt: skip


def _shows(s: PoolSetLine, title: Mapping[str, str], x: str) -> bool:
    """Whether ``s`` showed ``x`` titled ``title[x]``: by the row's own title, or
    else ``s.shown`` is ``ideas_marker.shown_order`` on ``title`` (ties in any
    order: the change class is unrecorded) with the seed's shuffle undone."""
    if s.titles is not None:
        return dict(zip(s.ids, s.titles, strict=True))[x] == title[x]
    perm, ranked = list(range(len(s.shown))), list(s.shown)
    random.Random(s.seed).shuffle(perm)  # noqa: S311 - the marker's own shuffle
    for j, y in zip(perm, s.shown, strict=True):
        ranked[j] = y
    names = [title[y] for y in ranked if y in title]
    return len(names) == len(ranked) and names == sorted(names)


def _provenance(
    files: Mapping[Path, Mapping[str, list[_Row]]], redo: set[str],
    run1: Mapping[tuple[str, str, str, int], str], ideas: Iterable[IdeaLine],
) -> None:  # fmt: skip
    """O44 under O46: X1-1 slice and pool rows on a re-run library are kept
    only when the titles they recorded are the re-run's ideas' (``ideas``,
    swapped): a trial its own (the join checks it), a combine through its
    trials, a pool result through its dispatch's set rows (their titles, or
    for rows from before ``titles`` the shown order the titles give)."""
    now = {_at(i): i for i in ideas if i.repo in redo}
    title = {_pool_id(i): i.title[: ipool.MARKER_TITLE_MAX] for i in now.values()}
    for p, h in files.items():
        trials = [t for t in _of(h, TRIAL_EXPERIMENT, TrialLine)
                  if t.repo in redo and t.arm == "X1-1"]  # fmt: skip
        for t in trials:  # run 1's title, not the re-run's at that key
            if t.title == run1.get(_at(t)) != getattr(now.get(_at(t)), "title", None):
                raise ValueError(f"{p.name}: {t.repo} X1-1 slice row names run 1's "
                                 "idea, not the re-run's (O44)")  # fmt: skip
        for c in _of(h, COMBINE_EXPERIMENT, CombineLine):
            if (
                c.repo in redo
                and c.arm == "X1-1"
                and c.repo not in {t.repo for t in trials}
            ):
                raise ValueError(f"{p.name}: {c.repo} X1-1 slice combine has no trial "
                                 "row to prove its ideas (O44)")  # fmt: skip
        sets = _of(h, SET_EXPERIMENT, PoolSetLine)
        for r in _of(h, RESULT_EXPERIMENT, PoolResultLine):
            keys = [k for k in (*r.members, *r.apart) if k.arm == "X1-1"]
            if r.repo in redo and keys and r.marker not in {s.marker for s in sets
                                                            if s.repo == r.repo}:  # fmt: skip
                raise ValueError(f"{p.name}: {r.repo} {r.marker} pool result has no "
                                 f"{SET_EXPERIMENT} row (O44)")  # fmt: skip
            for k in keys if r.repo in redo else ():
                i = now.get((r.repo, k.arm, k.label, k.position))
                x = "" if i is None else _pool_id(i)
                on = [s for s in sets if x in s.ids]
                if not on or not all(_shows(s, title, x) for s in on):
                    raise ValueError(f"{p.name}: {r.repo} {r.marker} pool: X1-1 "
                                     f"{k.label} #{k.position} is not shown with the "
                                     "re-run's title (O44)")  # fmt: skip


def _swap(
    f: dict[str, list[_Row]], files: Mapping[Path, Mapping[str, list[_Row]]],
    rerun: Path, reaudit: Path,
) -> tuple[set[str], str]:  # fmt: skip
    """O44: the re-run's X1-1 rows and the pooled re-audit's audit rows in
    place of run 1's on the re-run's libraries; refused unless the re-audit's
    digests name the re-run and one of ``files``."""
    g = _parsed([rerun], _KINDS)
    redo = _rerun_of(g)
    if not redo or redo != {p.repo for p in _of(g, ROW_EXPERIMENT, ProbeLine)}:
        raise ValueError(f"{rerun.name}: not the X1-1 re-run (arms A and X1-1 "
                         "alone on each library, O42)")  # fmt: skip
    audits = _of(_parsed([reaudit], (REAUDIT_EXPERIMENT,)), REAUDIT_EXPERIMENT,
                 ReauditLine)  # fmt: skip
    shas = {_sha(p): p for p in files}
    pair = {(a.run1_sha256, a.rerun_sha256) for a in audits}
    if len(pair) != 1 or (d := pair.pop())[1] != _sha(rerun) or d[0] not in shas:
        raise ValueError(f"{reaudit.name}: its digests do not name {rerun.name} "
                         "and one results file as X1 run 1 (O44)")  # fmt: skip
    if (done := {a.repo for a in audits}) != redo:
        raise ValueError(f"{reaudit.name}: re-audits {sorted(done)}, the re-run "
                         f"ran {sorted(redo)}")  # fmt: skip
    run1 = {
        _at(i): i.title for i in _of(f, IDEA_EXPERIMENT, IdeaLine) if i.arm == "X1-1"
    }
    swapped = (IDEA_EXPERIMENT, ROW_EXPERIMENT, REPLY_EXPERIMENT, PROPOSAL_EXPERIMENT)
    for kind, rows in f.items():
        rows[:] = [r for r in rows if getattr(r, "repo", None) not in redo
                   or (kind != AUDIT_EXPERIMENT and (kind not in swapped
                                                     or getattr(r, "arm", "") != "X1-1"))]  # fmt: skip
        if kind in swapped:
            rows += [r for r in g[kind] if getattr(r, "arm", "") == "X1-1"]
    fields = set(AuditLine.model_fields)
    f[AUDIT_EXPERIMENT] += [AuditLine.model_validate(a.model_dump(include=fields))
                            for a in audits]  # fmt: skip
    _provenance(files, redo, run1, _of(f, IDEA_EXPERIMENT, IdeaLine))
    return redo, (f"X1-1's probe, idea and reply rows from {rerun.name}; every "
                  "audit-based figure (share-new, self/cross, good counts, "
                  f"auditor-feasible) from {reaudit.name}; the rest from "
                  f"{shas[d[0]].name}")  # fmt: skip


def load_rows(
    paths: Sequence[Path], rerun: Path | None = None, reaudit: Path | None = None
) -> Rows:
    """X1's rows from its results files, refused when a kind is missing; with
    O44's re-run and its pooled re-audit swapped in (``_swap``)."""
    if (rerun is None) != (reaudit is None):
        raise ValueError("the X1-1 re-run and its pooled re-audit go together "
                         "(--rerun and --reaudit, O44), never one alone")  # fmt: skip
    files = {p: _parsed([p], _KINDS) for p in paths}
    for p, g in files.items():
        if held := _rerun_of(g):
            raise ValueError(f"{p.name}: holds the X1-1 re-run (arms A and X1-1 "
                             f"alone on {', '.join(sorted(held))}): name it with "
                             "--rerun beside its pooled re-audit (O44)")  # fmt: skip
    f = {kind: [r for g in files.values() for r in g[kind]] for kind in _KINDS}
    redo, swapped = (set(), "") if rerun is None or reaudit is None else (
        _swap(f, files, rerun, reaudit))  # fmt: skip
    named = {repo: ", ".join(dict.fromkeys(p.name for p, g in files.items()
                                           for r in _of(g, ROW_EXPERIMENT, ProbeLine)
                                           if r.repo == repo))
             for repo in E1_REPOS}  # fmt: skip
    scored = audit_scores([a for a in _of(f, AUDIT_EXPERIMENT, AuditLine)
                           if a.repo in redo])  # fmt: skip
    probes: list[_Row] = [p.model_copy(update=scored.get((p.repo, p.arm), {}))
                          for p in _of(f, ROW_EXPERIMENT, ProbeLine)]  # fmt: skip
    f[ROW_EXPERIMENT] = probes
    rows = Rows(
        _of(f, IDEA_EXPERIMENT, IdeaLine), _of(f, ROW_EXPERIMENT, ProbeLine),
        _of(f, AUDIT_EXPERIMENT, AuditLine), _of(f, PROPOSAL_EXPERIMENT, ProposalLine),
        _of(f, TRIAL_EXPERIMENT, TrialLine), _of(f, COMBINE_EXPERIMENT, CombineLine),
        None, _of(f, SET_EXPERIMENT, PoolSetLine),
        _of(f, RESULT_EXPERIMENT, PoolResultLine), _of(f, REPLY_EXPERIMENT, ReplyLine),
        tuple((r, swapped if r in redo else v) for r, v in named.items()
              if v or r in redo),
    )  # fmt: skip
    for kind, found in ((IDEA_EXPERIMENT, rows.ideas), (ROW_EXPERIMENT, rows.probes)):
        if not found:
            raise ValueError(f"no {kind} row in {', '.join(map(str, paths))}")
    scores = _of(f, DEDUPE_EXPERIMENT, DedupeLine)
    if len(scores) != 1:
        raise ValueError(f"no {DEDUPE_EXPERIMENT} row (Vc's dedupe validation)"
                         if not scores else f"{DEDUPE_EXPERIMENT} row twice")  # fmt: skip
    keyed: Sequence[ProbeLine | IdeaLine | AuditLine | TrialLine | CombineLine]
    for keyed in (rows.ideas, rows.probes, rows.audits, rows.trials, rows.combines):
        for r in keyed:
            if r.arm not in CONFIGS or r.repo not in E1_REPOS:
                raise ValueError(f"{r.repo} {r.arm!r}: not an X1 arm on one of the "
                                 "8 development libraries")  # fmt: skip
    twice = [
        k for k, n in Counter((p.repo, p.arm) for p in rows.probes).items() if n > 1
    ]
    if twice:
        raise ValueError(f"{ROW_EXPERIMENT}: {' '.join(twice[0])} twice")
    repos = [p.repo for p in rows.pool_sets] + [p.repo for p in rows.pool_results]
    if bad := [r for r in repos if r not in E1_REPOS]:
        raise ValueError(f"{bad[0]}: a pooled row's library is not one of the 8")
    pools = Counter((p.repo, p.marker) for p in rows.pool_results)
    if again := [k for k, n in pools.items() if n > 1]:
        raise ValueError(f"{RESULT_EXPERIMENT}: {' '.join(again[0])} twice")
    return dataclasses.replace(rows, dedupe=scores[0].score)


def load_e1(e1_dir: Path) -> tuple[dict[str, FactsBody], tuple[ProbeLine, ...]]:
    """E1's facts by library and its arms B, C and D's rows (the noise)."""
    files = sorted(e1_dir.glob("*.jsonl"))
    facts: dict[str, FactsBody] = {}
    for path in files:
        for repo, body in load_facts(path).items():
            if repo in facts:
                raise ValueError(f"{e1_dir}: facts for {repo} recorded twice")
            facts[repo] = body
    probes = _of(_parsed(files, (ROW_EXPERIMENT,)), ROW_EXPERIMENT, ProbeLine)
    noise = tuple(p for p in probes if p.arm in NOISE_ARMS)
    if {p.arm for p in noise} != set(NOISE_ARMS):
        raise ValueError(f"{e1_dir}: no {ROW_EXPERIMENT} rows of arms B, C and D")
    return facts, noise


def ceiling(idea: IdeaLine, body: FactsBody) -> float | None:
    """The innermost hotspot holding the target lines: its largest share
    over workloads, clipped to 1; ``None`` when no profiled span holds them."""
    t = idea.target
    spans = [
        (h.line_end - h.line_start, h.line_start, h)
        for h in body.hotspots
        if t is not None and h.file_path == idea.path
        and h.line_start is not None and h.line_end is not None
        and h.line_start <= t.first and t.last <= h.line_end
    ]  # fmt: skip
    if not spans:
        return None
    inner = min(s[:2] for s in spans)
    totals = _totals(body.hotspots)
    shares = [h.total_time_s / totals[h.workload_id] for *s, h in spans
              if tuple(s) == inner and totals.get(h.workload_id)]  # fmt: skip
    return min(1.0, max(shares)) if shares else None


def fresh(audits: Iterable[AuditLine]) -> frozenset[tuple[str, str]]:
    """The (library, id) of audits whose class under the auditor's duplicate
    links, joined either way, holds no arm-A audit: new to today's generator."""
    by = {(a.repo, a.id): a for a in audits}
    parent = {k: k for k in by}

    def find(k: tuple[str, str]) -> tuple[str, str]:
        while parent[k] != k:
            k = parent[k]
        return k

    for k, a in sorted(by.items()):
        to = (a.repo, a.duplicate_of or "")
        if (a.auditor, a.reason) == ("infeasible", "duplicate_of") and to in by:
            parent[find(k)] = find(to)
    taken = {find(k) for k, a in by.items() if a.arm == TODAY}
    return frozenset(k for k in by if find(k) not in taken)


def audit_scores(
    audits: Sequence[AuditLine],
) -> dict[tuple[str, str], dict[str, int | None]]:
    """``ideas_probe.scores``' counts from audit rows alone (the pooled
    re-audit writes no probe row): a duplicate whose root, followed through
    the links within its library, is another arm's takes the root's verdict;
    strict leaves out roots of arm A; a library with no verdict is unknown."""
    out: dict[tuple[str, str], dict[str, int | None]] = {}
    for repo, rows in _grouped(audits, lambda a: a.repo).items():
        by, known = {a.id: a for a in rows}, any(a.auditor is not None for a in rows)

        def root(a: AuditLine, by: Mapping[str, AuditLine] = by) -> AuditLine | None:
            seen = {a.id}
            while (a.auditor, a.reason) == (_BAD, "duplicate_of"):
                if (t := by.get(a.duplicate_of or "")) is None or t.id in seen:
                    return None
                seen.add(t.id)
                a = t
            return a

        for arm, mine in _grouped(rows, lambda a: a.arm).items():
            kept = [(a.title, a if (r := root(a)) is None or r.arm == arm else r)
                    for a in mine if a.tier == 0]  # fmt: skip
            kept = [(t, w) for t, w in kept if w.auditor not in (None, _BAD)]
            audited = [a for a in mine if a.auditor is not None]
            out[(repo, arm)] = {
                "audited": len(audited),
                "auditor_infeasible": sum(a.auditor == _BAD for a in audited),
                "good": len({a.title for a in audited if a.tier == 0
                             and a.auditor != _BAD}) if known else None,
                "good_corrected": len({t for t, _ in kept}) if known else None,
                "good_strict": None if arm == TODAY or not known
                else len({t for t, w in kept if w.arm != TODAY}),
            }  # fmt: skip
    return out


def _index(audits: Sequence[AuditLine]) -> Callable[[AuditLine], AuditLine | None]:
    """A link's target, looked up within its own library (O44: ids restart)."""
    by = {(a.repo, a.id): a for a in audits}
    return lambda a: by.get((a.repo, a.duplicate_of or ""))


def repeats(
    audits: Sequence[AuditLine], in_result: bool
) -> dict[tuple[str, str], Counter[str]]:
    """Per (library, arm): each audit row's ``duplicate_of`` link once, self
    when its target is the same arm's, cross otherwise (O43, O44)."""
    target = _index(audits)
    out: dict[tuple[str, str], Counter[str]] = {}
    for a in audits:
        found = out.setdefault((a.repo, a.arm), Counter())
        if a.duplicate_of is not None and (a.in_result or not in_result):
            t = target(a)
            found["unresolved" if t is None else "self" if t.arm == a.arm
                  else "cross"] += 1  # fmt: skip
    return out


def _grouped(items: Iterable[_V], key: Callable[[_V], _K]) -> dict[_K, list[_V]]:
    out: dict[_K, list[_V]] = defaultdict(list)
    for item in items:
        out[key(item)].append(item)
    return out


def _unique(ideas: Iterable[IdeaLine]) -> int:
    return sum(len(set(representatives([i.key() for i in g])))
               for g in _grouped(ideas, lambda i: i.repo).values())  # fmt: skip


def quantiles(values: Sequence[float]) -> tuple[float, ...] | None:
    """Min, quartiles and max, linearly interpolated; ``None`` for none."""
    v = sorted(values)
    if not v:
        return None

    def at(p: float) -> float:
        x = p * (len(v) - 1)
        lo = math.floor(x)
        return v[lo] + (v[min(lo + 1, len(v) - 1)] - v[lo]) * (x - lo)

    return tuple(at(p) for p in (0.0, 0.25, 0.5, 0.75, 1.0))


@dataclass(frozen=True)
class Measures:
    proposed: int  # the result: returned, not a proposal
    lane: int  # every lane-reply idea, the reviewers' removals included
    unique: int
    raw: int  # distinct titles, shown until the dedupe passes
    audited: int
    new: int | None  # None for today's generator, the reference
    feasible: int
    above: int
    known: int  # ideas with a predicted ceiling
    families: int
    cost_usd: float


@dataclass(frozen=True)
class LensCost:  # one model of X1-1's square (O42)
    requests: int
    usd: float
    ideas: int
    new: int
    unique: int


@dataclass(frozen=True)
class Cluster:
    repo: str
    key: MechanismKey
    counts: dict[str, int]
    titles: tuple[str, ...]


@dataclass(frozen=True)
class Cost:
    idea_usd: float
    slice_usd: float
    seeded_calls: int
    seeded_usd: float
    wins: int
    per_win: float | None


@dataclass(frozen=True)
class Pool:
    marker: str
    model: str
    validated: bool
    members: dict[str, IdeaLine]  # by id
    apart: tuple[IdeaLine, ...]  # the marker's own model's: not ranked
    top: tuple[str, ...] | None  # None: the tournament stopped
    sets: tuple[PoolSetLine, ...]  # by round and set
    requests: int
    rounds: int

    def counts(self) -> dict[str, int] | None:
        if self.top is None:
            return None
        found = Counter(self.members[x].arm for x in self.top)
        return {c: found[c] for c in POOL_CONFIGS}


def pool_of(
    p: PoolResultLine,
    sets: Iterable[PoolSetLine],
    at: Mapping[tuple[str, str, str, int], IdeaLine],
) -> Pool:
    """One ranking, refused when its rows break O39, O40 or O41's rules."""

    def idea(k: PoolKey) -> IdeaLine:
        if (i := at.get((p.repo, k.arm, k.label, k.position))) is None:
            raise ValueError(f"{p.repo} {k.arm} {k.label} #{k.position}: a pooled "
                             "idea with no ideas-idea row")  # fmt: skip
        if i.lane not in LENSES or i.proposal or not i.returned:
            raise ValueError(f"{p.repo}: {i.title!r} ({i.arm}, {i.lane}) is not a "
                             "lens-lane idea of X1-0 to X1-3's results")  # fmt: skip
        return i

    def say(i: IdeaLine, why: str) -> ValueError:
        return ValueError(
            f"{p.repo} {p.marker}: {i.title!r} ({i.arm}, {i.model}) {why}"
        )

    members = {m.id: idea(m) for m in p.members}
    apart = tuple(idea(k) for k in p.apart)
    if p.validated and (own := [i for i in members.values() if i.model == p.model]):
        raise say(own[0], "is ranked, but written by the marker's own model (O39)")
    if other := [i for i in apart if i.model != p.model]:
        raise say(other[0], "is listed apart but not the marker's model")
    mine = tuple(sorted((s for s in sets if (s.repo, s.marker) == (p.repo, p.marker)),
                        key=lambda s: (s.round, s.set)))  # fmt: skip
    first = sorted(x for s in mine if s.round == 1 for x in s.ids)
    if not mine:  # no request: a pool of one idea or none (a set of one is not sent)
        complete, expected = len(members) <= 1, tuple(sorted(members))[:MARKER_TOP]
    else:
        last = mine[-1]
        complete = last.of == 1 and last.order is not None
        expected = (last.order or ())[:MARKER_TOP]
    if (not set(first) <= set(members) or (p.top is not None) != complete
            or (complete and (p.top != expected
                              or (mine and first != sorted(members))))):  # fmt: skip
        raise ValueError(f"{p.repo} {p.marker}: the top {MARKER_TOP} is not the "
                         "final set's, or round 1's sets are not the pool")  # fmt: skip
    return Pool(p.marker, p.model, p.validated, dict(sorted(members.items())), apart,
                p.top, mine, p.requests, p.rounds)  # fmt: skip


@dataclass(frozen=True)
class Report:
    rows: Rows
    facts: dict[str, FactsBody]
    measures: dict[str, Measures]
    proposals: dict[str, int]
    overlap: tuple[Cluster, ...]
    square: dict[tuple[str, str], tuple[int, int, int]]
    margins: dict[str, tuple[float, ...]]
    deltas: dict[tuple[str, str], tuple[float | None, float | None]]
    costs: dict[str, Cost]
    sample: tuple[IdeaLine, ...]
    pools: dict[str, tuple[Pool, ...]]  # by library: each ranking
    good: dict[str, tuple[int | None, int | None]]  # corrected, strict (O43)
    repeats: dict[str, dict[tuple[str, str], Counter[str]]]  # by filter label
    lens_costs: dict[str, LensCost]  # by model


def _order(i: IdeaLine) -> tuple[object, ...]:
    lane = _LANES.index(i.lane) if i.lane in _LANES else len(_LANES)
    return (CONFIGS.index(i.arm), i.repo, lane, i.position, i.title, i.model, i.label)


def owner_sample(
    ideas: Sequence[IdeaLine], *, seed: int = SAMPLE_SEED, size: int = SAMPLE_SIZE
) -> tuple[IdeaLine, ...]:
    """A seeded round robin over (configuration, lane, model) strata of the
    configurations' results (returned; not today's, not a proposal)."""
    pool = sorted((i for i in ideas if i.arm != TODAY and i.returned
                   and not i.proposal), key=_order)  # fmt: skip
    strata = _grouped(pool, lambda i: (i.arm, i.lane, i.model))
    rng = random.Random(seed)  # noqa: S311 - a reproducible draw, not a secret
    keys = sorted(strata)
    rng.shuffle(keys)
    for k in keys:
        rng.shuffle(strata[k])
    depth = max((len(v) for v in strata.values()), default=0)
    drawn = [strata[k][d] for d in range(depth) for k in keys if d < len(strata[k])]
    return tuple(drawn[:size])


def report_of(
    results: Sequence[Path], e1_dir: Path = E1_DIR, *,
    rerun: Path | None = None, reaudit: Path | None = None,
) -> Report:  # fmt: skip
    rows = load_rows(results, rerun, reaudit)
    facts, noise = load_e1(e1_dir)
    for repo in sorted({i.repo for i in rows.ideas} | {p.repo for p in rows.probes}):
        if repo not in facts:
            raise ValueError(f"{repo}: no facts in {e1_dir}")
    lane = sorted((i for i in rows.ideas if not i.proposal), key=_order)
    scored = [i for i in lane if i.returned]  # the configurations' results
    ceil = {i: ceiling(i, facts[i.repo]) for i in scored}
    floor = {r: b.objective.min_relative_gain for r, b in facts.items()}
    over = {i: c - floor[i.repo] for i, c in ceil.items() if c is not None}
    new_ids = fresh(rows.audits)

    def measures(arm: str, repo: str | None = None) -> Measures:
        mine = [i for i in scored if i.arm == arm and repo in (None, i.repo)]
        audited = [a for a in rows.audits if a.arm == arm and a.in_result
                   and a.auditor is not None and repo in (None, a.repo)]  # fmt: skip
        new = sum((a.repo, a.id) in new_ids for a in audited)
        return Measures(
            proposed=len(mine), unique=_unique(mine),
            lane=sum(i.arm == arm and repo in (None, i.repo) for i in lane),
            raw=len({(i.repo, " ".join(i.title.casefold().split())) for i in mine}),
            audited=len(audited), new=None if arm == TODAY else new,
            feasible=sum(a.auditor != "infeasible" for a in audited),
            above=sum(over[i] >= 0 for i in mine if i in over),
            known=sum(i in over for i in mine),
            families=len({i.mechanism for i in mine if i.mechanism is not None}),
            cost_usd=math.fsum(p.cost_usd for p in rows.probes
                               if p.arm == arm and repo in (None, p.repo)),
        )  # fmt: skip

    clusters: list[Cluster] = []
    for repo, group in sorted(_grouped(scored, lambda i: i.repo).items()):
        keyed = [(k, i) for i in group if i.arm != TODAY and (k := i.key()) is not None]
        reps = representatives([k for k, _ in keyed])
        for r, members in _grouped(range(len(keyed)), reps.__getitem__).items():
            ideas = [keyed[n][1] for n in members]
            counts = Counter(i.arm for i in ideas)
            clusters.append(Cluster(repo, keyed[r][0],
                                    {a: counts[a] for a in CONFIGS if counts[a]},
                                    tuple(dict.fromkeys(i.title for i in ideas))))  # fmt: skip

    lens = [i for i in scored if i.arm == "X1-1" and i.lane in LENSES]
    on = {(p.repo, k): m for p in rows.probes if p.arm == "X1-1"
          for k, m in p.lane_models.items()}  # fmt: skip
    spent = _grouped(((m, r) for r in rows.replies if (r.arm, r.role) == ("X1-1", "lane")
                      and r.sent and (m := on.get((r.repo, r.label)))), lambda x: x[0])  # fmt: skip
    audit_of = {(a.repo, a.arm, a.title): a for a in rows.audits}
    novel = [i for i in lens if (a := audit_of.get((i.repo, i.arm, i.title)))
             and (a.repo, a.id) in new_ids]  # fmt: skip

    def priced(m: str, u: tuple[int, int, int, int]) -> float:
        usage = {"input_tokens": u[0], "output_tokens": u[1],
                 "cache_read_input_tokens": u[2], "cache_creation_input_tokens": u[3]}  # fmt: skip
        return response_cost(usage, settings.MODEL_PRICING, model=m)[0]

    lens_costs = {m: LensCost(
        len(spent.get(m, [])), math.fsum(priced(m, r.usage) for _, r in spent.get(m, [])),
        sum(i.model == m for i in lens), sum(i.model == m for i in novel),
        _unique(i for i in novel if i.model == m)) for m in SQUARE_MODELS}  # fmt: skip

    def summed(arm: str, m: str) -> int | None:
        found = [getattr(p, m) for p in rows.probes if p.arm == arm]
        return None if not found or None in found else sum(found)

    square = {
        k: (len(g), _unique(g), sum(over.get(i, -1.0) >= 0 for i in g))
        for by in (lambda i: (i.model, i.lane), lambda i: (i.model, "*"),
                   lambda i: ("*", i.lane))
        for k, g in _grouped(lens, by).items()
    }  # fmt: skip

    probe = {(p.repo, p.arm): p for p in rows.probes}
    e1 = _grouped(noise, lambda p: p.repo)
    deltas: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    bases = sorted(r for r, a in probe if a == BASELINE)
    for m in DELTA_MEASURES:
        ranges = []
        for repo in bases:
            vals = [v for p in (*e1.get(repo, []), probe[(repo, BASELINE)])
                    if (v := getattr(p, m)) is not None]  # fmt: skip
            if len(vals) > 1:
                ranges.append(max(vals) - min(vals))
        spread = math.fsum(ranges) / len(ranges) if ranges else None
        for arm in LEVERS:
            diffs = [getattr(probe[(r, arm)], m) - getattr(probe[(r, BASELINE)], m)
                     for r in bases if (r, arm) in probe
                     and None not in (getattr(probe[(r, arm)], m),
                                      getattr(probe[(r, BASELINE)], m))]  # fmt: skip
            deltas[(arm, m)] = (
                math.fsum(diffs) / len(diffs) if diffs else None,
                spread,
            )
    for m in NO_BAND:  # the lever's per-library delta alone: no A/A band
        for arm in LEVERS:
            gaps = [float(x - y) for r in bases if (r, arm) in probe
                    if (x := getattr(measures(arm, r), m)) is not None
                    and (y := getattr(measures(BASELINE, r), m)) is not None]  # fmt: skip
            deltas[(arm, m)] = (math.fsum(gaps) / len(gaps) if gaps else None, None)

    costs = {}
    for arm in CONFIGS:
        runs = [c for c in rows.combines if c.arm == arm]
        wins = sum(t.verdict == "keep" for t in rows.trials if t.arm == arm)
        usd = math.fsum(c.cost_usd for c in runs)
        costs[arm] = Cost(
            measures(arm).cost_usd, usd, sum(c.seeded_calls for c in runs),
            math.fsum(c.seeded_cost_usd for c in runs), wins, usd / wins if wins else None,
        )  # fmt: skip
    at = {(i.repo, i.arm, i.label, i.position): i for i in rows.ideas}
    for t in rows.trials:  # the library file joins them by (label, position)
        where = f"{t.repo} {t.arm} {t.label} #{t.position}"
        if (i := at.get((t.repo, t.arm, t.label, t.position))) is None:
            raise ValueError(f"{where}: a trial with no ideas-idea row")
        if i.title != t.title:
            raise ValueError(f"{where}: the trial's {t.title!r} is not the idea "
                             f"there ({i.title!r})")  # fmt: skip
    pools: dict[str, list[Pool]] = defaultdict(list)
    for p in sorted(rows.pool_results, key=lambda p: p.repo):  # each: as recorded
        pools[p.repo].append(pool_of(p, rows.pool_sets, at))
    return Report(
        rows=rows, facts=facts, measures={a: measures(a) for a in CONFIGS},
        proposals=dict(sorted(Counter(i.relaxes.value for i in rows.ideas
                                      if i.proposal and i.relaxes).items())),
        overlap=tuple(clusters), square=square,
        margins={a: tuple(sorted(v for i, v in over.items() if i.arm == a))
                 for a in CONFIGS},
        deltas=deltas, costs=costs, sample=owner_sample(scored),
        pools={repo: tuple(found) for repo, found in pools.items()},
        good={a: (summed(a, "good_corrected"), summed(a, "good_strict"))
              for a in CONFIGS},
        repeats={label: repeats(rows.audits, label == HANDED_ON)
                 for label in (HANDED_ON, GENERATED)}, lens_costs=lens_costs,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# Rendering: every model-derived string redacted, then made inert (``cells``)
# ---------------------------------------------------------------------------


def _row(values: Iterable[object]) -> str:
    return cells([redact_keys(str(v)) for v in values])


def _table(head: Sequence[str], body: Iterable[Iterable[object]]) -> list[str]:
    return [_row(head), "| " + " | ".join("---" for _ in head) + " |",
            *(_row(r) for r in body)]  # fmt: skip


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def _num(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def bound(score: DedupeScore | None) -> str | None:
    """What unique mechanisms and the new share are while the dedupe fails
    its bar, by the direction Vc's score row shows; None once it passes."""
    if score is None:
        return "unvalidated, no pair labelled"
    if score.passed:
        return None
    under = (
        score.same_pairs > 0 and score.same_merged < MIN_AGREEMENT * score.same_pairs
    )
    over = (score.different_merged_share or 0.0) > MAX_DIFFERENT_MERGED
    if under != over:
        return ("upper bound, the dedupe under-merges (O39)" if under
                else "lower bound, the dedupe over-merges")  # fmt: skip
    return "unvalidated, the dedupe failed its bar"


def _tag(label: str | None) -> str:
    return "" if label is None else f" ({label})"


def trial_cell(t: TrialLine) -> str:
    unvalidated = t.grader_validated is False
    return t.verdict + (f" (graded by {t.grader}, unvalidated)" if unvalidated else "")


def _library_file(r: Report, repo: str, arm: str) -> str:
    rows = r.rows
    audit = {(a.repo, a.arm, a.title): a for a in rows.audits}
    by_id = {(a.repo, a.id): a for a in rows.audits}
    trial = {(t.repo, t.arm, t.label, t.position): t for t in rows.trials}
    why = {(p.repo, p.arm, p.title): "".join(p.rationale) for p in rows.proposals}
    mine = sorted((i for i in rows.ideas if (i.repo, i.arm) == (repo, arm)), key=_order)
    body = []
    for n, i in enumerate((i for i in mine if not i.proposal), 1):
        a = audit.get((repo, arm, i.title))
        t = trial.get((repo, arm, i.label, i.position))
        dup = None if a is None else by_id.get((repo, a.duplicate_of or ""))
        body.append([
            n, i.title, i.mechanism or "-", i.where(), _pct(ceiling(i, r.facts[repo])),
            "-" if a is None else a.auditor or "not reviewed",
            "-" if a is None or a.duplicate_of is None
            else a.duplicate_of if dup is None else f"{dup.title} ({dup.arm})",
            "-" if t is None else trial_cell(t),
            "-" if t is None else f"{_num(t.gain_pct, 1)}% / {_num(t.floor_pct, 1)}%",
            "-" if t is None else t.op_count.cell or "-",
            i.lane, i.model or "-", i.returned,
        ])  # fmt: skip
    floor = r.facts[repo].objective.min_relative_gain
    label = bound(r.rows.dedupe)
    return "\n".join([
        f"# X1 ideas: {repo}, {arm}", "",
        f"Floor {_pct(floor)}; ceilings predicted from E1's profile.", "",
        *([f"These rows are the raw list behind unique mechanisms and the share "
           f"new to today's generator{_tag(label)}.", ""] if label else []),
        *_table(("#", "title", "mechanism", "target lines", "ceiling", "audit",
                 "duplicate of", "trial", "gain / floor", "op count", "lane", "model",
                 "returned"), body),
        "", "## Proposals (rule-relaxing, never scored or trialled)", "",
        *_table(("title", "relaxes", "lane", "model", "returned", "rationale"),
                [[i.title, i.relaxes or "-", i.lane, i.model or "-", i.returned,
                  why.get((repo, arm, i.title), "-")] for i in mine if i.proposal]),
        "",
    ])  # fmt: skip


def _ideas(found: Iterable[tuple[str | None, IdeaLine]]) -> list[list[object]]:
    return [[*(() if k is None else (k,)), i.title, i.arm, i.lane, i.model or "-"]
            for k, i in found]  # fmt: skip


def _ranking(p: Pool) -> list[str]:
    tag = "validated" if p.validated else "unvalidated"

    def advanced(s: PoolSetLine) -> str:
        if s.order is None:
            return f"no order ({s.error or 'no reply'}), the tournament stopped"
        return ", ".join(s.advanced) if s.of > 1 else f"final, the top {MARKER_TOP}"

    record = [[s.round, s.set, ", ".join(s.shown), s.seed,
               "-" if s.order is None else ", ".join(s.order), advanced(s)]
              for s in p.sets]  # fmt: skip
    top = [[n, *row] for n, row in enumerate(
        _ideas((x, p.members[x]) for x in p.top or ()), 1)]  # fmt: skip
    return [
        f"#### Ranked by {p.marker} ({p.model}), {tag}: {len(p.members)} ideas, "
        f"{p.requests} requests in {p.rounds} rounds", "",
        *(_table(("rank", "id", "title", "configuration", "lane", "model"), top)
          if p.top is not None else ["The tournament stopped: no top 3."]), "",
        "Every set (ids in the order shown; the marker's order, most likely first):",
        "", *_table(("round", "set", "shown", "seed", "the marker's order",
                     "advanced"), record), "",
        "The pool:", "",
        *_table(("id", "title", "configuration", "lane", "model"),
                _ideas(p.members.items())), "",
        f"Not ranked (written by {p.model}, the marker's own model):", "",
        *(_table(("title", "configuration", "lane", "model"),
                 _ideas((None, i) for i in p.apart)) if p.apart else ["none"]), "",
    ]  # fmt: skip


def _marker_section(r: Report) -> list[str]:
    if not r.pools:
        return ["No pooled ranking recorded (no ideas-pool-result row): no "
                "marker-feasible count."]  # fmt: skip
    every = [p for found in r.pools.values() for p in found]
    shown = [len(s.ids) for p in every for s in p.sets]
    failed = sorted({p.marker for p in every if not p.validated})
    size = (f"Every request showed {min(shown)} to {max(shown)} ideas, at most "
            f"{SET_SIZE}: the set size the marker was validated on (Vb's 48 scored "
            f"sets: {VB_SETS[0]} to {VB_SETS[1]} ideas, {VB_SETS[2]} on average)."
            if shown else "No set request was sent.")  # fmt: skip

    def row(repo: str, ps: Sequence[Pool]) -> list[object]:
        p, done = ps[0], [x.counts() for x in ps]
        tag = "" if p.validated else " unvalidated"
        cells = (["-"] * len(POOL_CONFIGS) if None in done else
                 [f"{sum(c[a] for c in done if c)}{tag}" for a in POOL_CONFIGS])  # fmt: skip
        return [repo, f"{p.marker} ({'validated' if p.validated else 'unvalidated'})",
                *cells, sum(len(x.members) for x in ps), sum(len(x.apart) for x in ps),
                sum(x.requests for x in ps), max(x.rounds for x in ps)]  # fmt: skip

    by_marker = _grouped(every, lambda p: p.marker)
    out = [
        "Per library, every configuration's lens-lane ideas (X1-0 to X1-3, their "
        "results; never S1, the leap or the rule-relaxing lanes) form one pool, "
        "ranked by a tournament, not one ranking of the whole pool (O41): in "
        "sorted idea-id order (an id hashed from the idea's row, carrying no "
        f"configuration, lane or model) the pool is split into ceil(n/{SET_SIZE}) "
        "sets as equal as possible; each set is ranked in one blind request "
        "(titles, class and the library's hot code, shown in an order shuffled by "
        f"a recorded seed); the top {ipool.ADVANCE} of each set advance, round after "
        "round, until "
        "the advancing ideas fit one set, whose ranking gives the top "
        f"{MARKER_TOP}. {size} The count is how many of that top {MARKER_TOP} each "
        "configuration supplied (O40). The validated marker (Vb's verdict) never "
        "ranks its own model's ideas (O39): those are listed apart, not ranked. "
        "The other candidate ranks the whole pool, its counts marked unvalidated"
        + (f" ({', '.join(failed)} failed O37)" if failed else "")
        + ", so X1-1 has a comparable number.", "",
        *_table(("library", "ranked by", *POOL_CONFIGS, "pooled",
                 "not ranked (the marker's own model)", "requests", "rounds"),
                [*(row(repo, (p,)) for repo, ps in r.pools.items() for p in ps),
                 *(row("all libraries", ps) for ps in by_marker.values())]),
    ]  # fmt: skip
    for repo, ps in r.pools.items():
        out += ["", f"### {repo}", "", *(x for p in ps for x in _ranking(p))]
    return out


def _sources(r: Report) -> list[str]:
    found = "; ".join(f"{repo}: {files}" for repo, files in r.rows.sources)
    return [f"Sources (O44): {found}", ""]


def _known(value: int | None) -> object:
    return "-" if value is None else value


def _vrep_sections(r: Report) -> list[str]:
    """O43's good counts, O44's self/cross tables, the as-coded appendix."""
    out = [
        "## Good ideas, corrected and strict (O43)", "",
        "Summed over the libraries (- when one is unknown). Corrected: returned "
        "non-obvious ideas the auditor did not mark infeasible, a duplicate taking "
        "the verdict of the other arm's idea it repeats; strict: of those, none "
        "decided on an arm-A idea. The as-coded count rewards the arm the auditor "
        "read first, so it is shown only in the appendix.", "",
        *_table(("configuration", "good corrected", "good strict"),
                [[a, _known(c), _known(st)] for a, (c, st) in r.good.items()]), "",
        "## Self and cross repeats (O43, O44)", "",
        "Each audit row's duplicate_of link counted once: self when its target is "
        "the same configuration's idea, cross otherwise, the target looked up "
        "within the same library (audit ids restart in each).", "",
    ]  # fmt: skip
    for label in (HANDED_ON, GENERATED):
        tag, by = label[label.index("(") :], r.repeats[label]
        keyed = sorted(by.items(), key=lambda kv: (kv[0][0], CONFIGS.index(kv[0][1])))
        total = [(("all libraries", a), sum((c for (_, x), c in by.items() if x == a),
                                            Counter[str]())) for a in CONFIGS
                 if any(x == a for _, x in by)]  # fmt: skip
        out += [f"### {label.capitalize()}", "", *_table(
            ("library", "configuration",
             *(f"{h} {tag}" for h in ("self", "cross", "target not found"))),
            [[repo, arm, *(f"{c[k]} {tag}" for k in ("self", "cross", "unresolved"))]
             for (repo, arm), c in (*keyed, *total)]), ""]  # fmt: skip
    probes = sorted(r.rows.probes, key=lambda p: (p.repo, CONFIGS.index(p.arm)))
    return [*out, "## Appendix: per-library raw good counts", "", *_table(
        ("library", "configuration", "good corrected", "good strict",
         "as coded (reading-order artifact)"),
        [[p.repo, p.arm, _known(p.good_corrected), _known(p.good_strict),
          _known(p.good)] for p in probes]), ""]  # fmt: skip


def _lens_costs(r: Report, tag: str) -> list[str]:
    body = [[m, c.requests, f"{c.usd:.4f}", c.ideas, c.new, c.unique,
             f"{c.usd / c.unique:.4f}" if c.unique else "no unique new mechanism"]
            for m, c in r.lens_costs.items()]  # fmt: skip
    return [
        "## 2b X1-1 cost per unique new mechanism, per model (O42)", "",
        "Per model of the Latin square: the USD of its X1-1 lens-lane requests "
        "(S1, the leap and the reviewer left out), priced from each sent "
        "request's recorded usage (ideas-reply rows) at common/config.py's "
        "MODEL_PRICING: no row records a request's cost. Ideas: its returned "
        "lens-lane ideas; new to today's generator by the auditor's duplicate "
        "links; unique new by the G4 mechanism key.", "",
        *_table(("model", "lens-lane requests", "USD", "ideas",
                 f"new to today's generator{tag}", f"unique new mechanisms{tag}",
                 "USD per unique new mechanism"), body), "",
    ]  # fmt: skip


def _measures_file(r: Report, show_raw: bool, verdict: str) -> str:
    raw = ("raw titles",) if show_raw else ()
    tag, score = _tag(bound(r.rows.dedupe)), r.rows.dedupe
    note = [] if score is None or score.passed else [
        f"Vc's {score.labelled} labelled pairs are the dedupe's development set "
        "for a fix before X2 (O39); X1 is not held for it.", ""]  # fmt: skip
    body = [[a, m.proposed, m.lane, m.unique, *((m.raw,) if show_raw else ()),
             "-" if m.new is None else f"{m.new}/{m.audited}", f"{m.above}/{m.known}",
             m.families, f"{m.feasible}/{m.audited}", f"{m.cost_usd:.4f}"]
            for a, m in r.measures.items()]  # fmt: skip
    costs = [[a, f"{c.idea_usd:.4f}", f"{c.slice_usd:.4f}", c.seeded_calls,
              f"{c.seeded_usd:.4f}", c.wins, _num(c.per_win, 4)]
             for a, c in r.costs.items()]  # fmt: skip
    return "\n".join([
        "# X1 idea measures (spec-idea-lab 6.2)", "", *_sources(r),
        *_table(("dedupe (G4)", "verdict"), [["Vc's validation", verdict]]), "",
        *note,
        "Ideas: each configuration's result (returned, not a proposal: "
        "ideas-probe's and the slice's population); lane ideas: every lane-reply "
        "idea, its reviewers' removals included; audited: reviewed audits with "
        "in_result. Only auditor-feasible has an A/A band (tables.md, Table 4); "
        "unique, new, ceilings and families have no A/A band offline, so a "
        "ranking on them is provisional (6.3).", "",
        *_table(("configuration", "ideas proposed", "lane ideas",
                 f"unique mechanisms{tag}", *raw, f"new to today's generator{tag}",
                 "ceiling over the floor (of known)", "mechanism families",
                 "auditor-feasible (of audited)", "USD"), body),
        "", "## X1-4 proposals by rule relaxed (no score)", "",
        *_table(("rule", "proposals"), r.proposals.items()),
        "", "## Cost per configuration", "",
        "Ideas USD excludes the pooled auditor (its own line per library); the "
        "slice's USD is its engine runs', D64's seeded calls included.", "",
        *_table(("configuration", "ideas USD", "slice USD", "seeded calls",
                 "seeded USD", "wins", "slice USD per win"), costs), "",
        "## Marker-feasible ideas (6.2, O40, O41)", "", *_marker_section(r), "",
        *_vrep_sections(r),
    ])  # fmt: skip


def _tables_file(r: Report, show_raw: bool) -> str:
    levers, tag = CONFIGS[1:], _tag(bound(r.rows.dedupe))
    overlap = [[c.repo, c.key.mechanism.value, c.key.cell.value,
                f"{c.key.target.path}:{c.key.target.first}-{c.key.target.last}",
                *(c.counts.get(a, 0) for a in levers),
                f"only {next(iter(c.counts))}" if len(c.counts) == 1 else "-",
                *(("; ".join(c.titles),) if show_raw else ())]
               for c in r.overlap]  # fmt: skip
    models = [*SQUARE_MODELS, "*"]
    square = [[m if m != "*" else "all models",
               *("/".join(map(str, r.square[(m, x)])) if (m, x) in r.square else "-"
                 for x in (*LENSES, "*"))] for m in models]  # fmt: skip
    ceil = [[a, len(v), r.measures[a].proposed - len(v), sum(x >= 0 for x in v),
             *(_pct(x) for x in quantiles(v) or (None,) * 5)]
            for a, v in r.margins.items()]  # fmt: skip
    deltas = [[a, f"{m}{tag}" if m in ("unique", "new") else m, _num(d), _num(s),
               "-" if d is None else "no A/A band (provisional)" if s is None
               else "inside the noise" if abs(d) <= s else "beyond the noise"]
              for (a, m), (d, s) in r.deltas.items()]  # fmt: skip
    return "\n".join([
        "# X1 comparison tables (spec-idea-lab 6.5)", "", *_sources(r),
        f"## 1 Mechanism x configuration overlap{tag}", "",
        "Each deduplicated mechanism (keyed ideas only) and how many ideas of "
        "each configuration it holds.", "",
        *_table(("library", "mechanism", "cell", "target", *levers, "unique to",
                 *(("raw titles",) if show_raw else ())), overlap),
        "", f"## 2 X1-1 model x lens (ideas/unique mechanisms{tag}/ceilings over "
        "floor)", "",
        *_table(("model", *LENSES, "all lenses"), square),
        "", *_lens_costs(r, tag), "## 3 Predicted ceilings against the floor (ceiling - floor)", "",
        *_table(("configuration", "with a ceiling", "unknown", "over the floor",
                 "min", "q25", "median", "q75", "max"), ceil),
        "", "![ceiling less floor per configuration](ceilings.svg)", "",
        "## 4 Every lever's delta beside the noise", "",
        "Delta: mean over libraries of the lever's value less X1-0's (ideas-probe "
        "fields; feasible = audited less auditor-infeasible); spread: mean "
        "per-library range over E1's arms B, C, D and X1-0. Unique, new, above "
        "and families come from idea rows E1 lacks: no A/A band.", "",
        *_table(("lever", "measure", "delta", "A/A spread", "reading"), deltas), "",
    ])  # fmt: skip


_SVG_STYLE: Final = (
    ".s{fill:#fcfcfb}.t{fill:#0b0b0b}.m{fill:#52514e}.g{stroke:#d9d8d4}"
    ".b{fill:#2a78d6;fill-opacity:.25;stroke:#2a78d6}.k{stroke:#2a78d6;stroke-width:2}"
    ".d{fill:#2a78d6}.f{stroke:#52514e;stroke-dasharray:4 3}"
    "@media (prefers-color-scheme:dark){.s{fill:#1a1a19}.t{fill:#f0efec}"
    ".m{fill:#c3c2b7}.g{stroke:#3a3a37}.b{fill:#3987e5;stroke:#3987e5}"
    ".k{stroke:#3987e5}.d{fill:#3987e5}.f{stroke:#c3c2b7}}"
)
_LO, _HI, _X0, _W = -0.25, 1.0, 96.0, 500.0


def _x(value: float) -> str:
    v = min(_HI, max(_LO, value))
    return f"{_X0 + (v - _LO) / (_HI - _LO) * _W:.1f}"


def plot(margins: Mapping[str, Sequence[float]]) -> str:
    """Ceiling less floor per configuration: box (quartiles), whiskers, one
    dot per idea, the floor dashed at 0; a static SVG, no script or link."""
    h = 48 + 32 * len(margins)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="{h}" '
           f'viewBox="0 0 640 {h}" font-family="sans-serif" font-size="12">',
           "<title>Predicted ceiling less the floor, per configuration</title>",
           f"<style>{_SVG_STYLE}</style>",
           f'<rect class="s" width="640" height="{h}"/>']  # fmt: skip
    for tick in (-0.25, 0.0, 0.25, 0.5, 0.75, 1.0):
        label = "floor" if tick == 0 else f"{100 * tick:+.0f} pp"
        out += [f'<line class="{"f" if tick == 0 else "g"}" x1="{_x(tick)}" '
                f'x2="{_x(tick)}" y1="16" y2="{h - 24}"/>',
                f'<text class="m" x="{_x(tick)}" y="{h - 8}" '
                f'text-anchor="middle">{label}</text>']  # fmt: skip
    for n, (arm, values) in enumerate(margins.items()):
        y = 36 + 32 * n
        out.append(f'<text class="t" x="8" y="{y + 4}">{arm} ({len(values)})</text>')
        q = quantiles(values)
        if q is None:
            out.append(f'<text class="m" x="{_X0}" y="{y + 4}">no ceiling</text>')
            continue
        out += [f'<line class="k" x1="{_x(q[0])}" x2="{_x(q[4])}" y1="{y}" y2="{y}"/>',
                f'<rect class="b" x="{_x(q[1])}" y="{y - 8}" height="16" '
                f'width="{float(_x(q[3])) - float(_x(q[1])):.1f}" rx="4"/>',
                f'<line class="k" x1="{_x(q[2])}" x2="{_x(q[2])}" y1="{y - 8}" '
                f'y2="{y + 8}"/>',
                *(f'<circle class="d" cx="{_x(v)}" cy="{y}" r="4"/>' for v in values)]  # fmt: skip
    return "\n".join([*out, "</svg>", ""])


def render(r: Report) -> dict[str, str]:
    """Every output file's text by name; no clock, no set order, no I/O."""
    score = r.rows.dedupe
    show_raw = score is None or score.show_raw
    verdict = "no pair labelled" if score is None else (
        f"{'passed' if score.passed else 'not passed'}: {score.why}")  # fmt: skip
    files = {f"{p.repo}-{p.arm}.md": _library_file(r, p.repo, p.arm)
             for p in sorted(r.rows.probes, key=lambda p: (p.repo, CONFIGS.index(p.arm)))}  # fmt: skip
    ids = [f"S{k:02d}" for k in range(1, len(r.sample) + 1)]
    files["measures.md"] = _measures_file(r, show_raw, verdict)
    files["tables.md"] = _tables_file(r, show_raw)
    files["ceilings.svg"] = plot(r.margins)
    files["owner-sample.md"] = "\n".join([
        "# X1 owner-read sample (source hidden; the key is a separate file)", "",
        f"{len(ids)} ideas, a seeded draw ({SAMPLE_SEED}) across configurations, "
        "lanes and models.", "",
        *_table(("sample", "library", "title", "change", "mechanism", "target"),
                [[k, i.repo, i.title, i.change, i.mechanism or "-", i.where()]
                 for k, i in zip(ids, r.sample, strict=True)]), "",
    ])  # fmt: skip
    key = {k: {"repo": i.repo, "arm": i.arm, "lane": i.lane, "model": i.model,
               "label": i.label, "position": i.position}
           for k, i in zip(ids, r.sample, strict=True)}  # fmt: skip
    files["owner-sample-key.json"] = json.dumps(key, indent=1, sort_keys=True) + "\n"
    return files


def main(argv: Sequence[str] | None = None, echo: Callable[[str], None] = print) -> int:
    """Write the report; 2 on a refused or unreadable input (nothing written)."""
    parser = argparse.ArgumentParser(prog="ideas_report", description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--e1", type=Path, default=E1_DIR)
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    parser.add_argument("--rerun", type=Path, help="O42's X1-1 re-run results")
    parser.add_argument("--reaudit", type=Path, help="its pooled re-audit (O44)")
    args = parser.parse_args(argv)
    try:
        report = report_of(args.results, args.e1, rerun=args.rerun,
                           reaudit=args.reaudit)  # fmt: skip
        files = render(report)
    except (OSError, ValueError) as error:
        echo(f"error: {error}")
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (args.out / name).write_text(text, encoding="utf-8", newline="\n")
    echo(f"wrote {len(files)} files to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
