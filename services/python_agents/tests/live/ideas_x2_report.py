"""V-x2rep: the X2 report (idea-lab spec 9.4 and 9.6b; O50, O51, O52), offline.

Pure code over results files: no request, no network, the same bytes on
every run and whatever the files' order. ``uv run python -m
live.ideas_x2_report <results.jsonl>... [--out DIR]`` (from ``tests/``,
``PYTHONPATH=../src:.``) reads the rows ``ideas_x2.X2Recorder`` writes,
``ideas-x2-hypothesis``, ``ideas-x2-round`` and ``ideas-x2-run`` (every other
kind skipped; a kind read is parsed strictly, its fields by name), and writes
``x2.md`` under ``--out`` (``REPORT_DIR`` by default).

Before any comparison it says that X2 is read arm to arm only (O50), states
the noise band (O51 as amended: each library against its own twin gap where
a twin exists, the fixed 4 points / 1 kept only without one) and O52's
reading rules and lists its sources. Then: the A/A band (X2-0 against its
twin X2-0', each twinned library's gaps), each arm and library's figures with
totals over the libraries every arm has and over the arm's own, each arm
against X2-0 with its band label, then O52's arm-level calls (a
kept-count sign count, and the mean combine difference against the twin's
mean gap), wins by lane and round, each lane's hit rate (4b: kept over
trialled, a trialled hypothesis being one that reached a keep, inconclusive
or reject verdict in a round), round 2's seeds, and the charter's
path-dependence measure (6, O54: section 1's twin gaps, by the same
function). A combine's gain counts only when it held: a run with no held
combine delivers 0 in every difference and mean. Rounds after the second
count as round 2's (X2 runs two). Refused, nothing written: a malformed
row, an arm or library
X2 does not run, a run, round or hypothesis recorded twice, rounds or
hypotheses with no run row, a run with no round or a gap in its rounds, and
kept counts that disagree between a run, its rounds and its ideas.

``--variance`` (emergence round 2, S1) writes ``variance.md`` instead: each
file is loaded alone, so every (arm, library) run of every file is a draw;
each draw is read against the A/A pool (``POOL``) with its own arm left
out, by rank with the null rate beside it; each arm's signs against each
library's pool median get the exact stratified null; then each run's
delivered mass, the n-need of each call and the lane views. O51 and O52, in
``x2.md``, stay the ruling reading.

``--rounds`` (Window 2, X2-D) writes ``rounds.md`` instead, each file
loaded alone as for ``--variance``: per run and per arm, each round's keeps
(round 1, 2 and 3, or as many as a run recorded) as fresh ideas and
near-miss compounds, their standalone points (vs base, not additive) and,
where per-keep combine records exist, the keeps delivered, beside the
delivered combine. It is not a contribution: a third round's delivered
gain is read only from X2-D's combine against the pool (``--variance``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations, product
from pathlib import Path
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from autonomous_ai_agents.common.models import VerdictOutcome
from autonomous_ai_agents.optimization.idea_types import (
    LENS_LANES,
    Lane,
    RealisationLabel,
)

from .conftest import redact_keys
from .discovery_io import cells, flag, per
from .ideas_probe import E1_REPOS, SERVICE_DIR
from .ideas_x2 import EVERY_ARM, IDEA_EXPERIMENT, ROUND_EXPERIMENT, RUN_EXPERIMENT

REPORT_DIR: Final = SERVICE_DIR.parents[1] / ".claude/handoff/step3/idea-lab/x2"
ARMS: Final = tuple(a.key for a in EVERY_ARM)  # the plan's, then those off it
BASE, TWIN = ARMS[0], ARMS[1]
BAND_GAIN: Final = 4.0  # O51, a library without a twin: points of combine gain
BAND_KEPT: Final = 1.0  # O51, a library without a twin: on the kept count
FIXED: Final = ("within the fixed band (no twin)", "outside the fixed band (no twin)")
UNBANDED: Final = "no band (unbanded)"  # O52's arm-level combine call with no twin
# O52 as O51 amended: a kept-count difference within the library's twin gap,
# one beyond it, two or more beyond it
KEPT: Final = ("inside the measured band", "outside the measured band, not significant",
               "outside the measured band")  # fmt: skip
Gaps = dict[str, tuple[float, int]]  # twinned library: (tg points, tk kept)
GROUPS: Final = {Lane.leap.value: "leap", Lane.obvious.value: "S1 (obvious)",
                 **{lane.value: lane.value for lane in LENS_LANES}}  # fmt: skip
COMPOUND: Final = "compound"
ORDER: Final = (*GROUPS.values(), COMPOUND)
TRIED: Final = frozenset(v.value for v in (VerdictOutcome.keep, VerdictOutcome.inconclusive,
                                           VerdictOutcome.reject))  # fmt: skip
Count = Annotated[int, Field(ge=0)]
Usd = Annotated[float, Field(ge=0)]
Key = tuple[str, str]  # (arm, library)


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    repo: str
    arm: str


class Realised(BaseModel):  # S1's record, the fields the report reads
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)
    label: Annotated[str, Field(pattern=f"^({'|'.join(RealisationLabel)})$")]
    anchor_touched: bool | None
    kept_not_fired: bool


class Combined(BaseModel):  # S2's per-keep combine record, the fields the report reads
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)
    delivered: bool
    skip_reason: str | None
    duplicate_of: str | None
    component: Count
    best_subset: bool
    gain_pct: float | None
    reconcile: str | None


class IdeaLine(_Row):
    round: Annotated[int, Field(ge=1)] | None  # None: left in the pool
    hypothesis_id: str
    lane: str | None
    model: str | None
    compound: bool
    verdict: str
    realisation: Realised | None = None  # X2-C only (S1)
    combine: Combined | None = None  # SITE_STACKS on or record only (S2)
    gain_pct: float | None = None
    floor_pct: float | None = None


class LaneView(BaseModel):  # IDEAS_VIEW_RECORD's record of one lane request
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    lane: str
    view_sha: Annotated[str, Field(pattern="^[0-9a-f]{8}$")]
    served_model: str | None


class RoundLine(_Row):
    round: Annotated[int, Field(ge=1)]
    trialled: Count
    kept: Count
    seeds: Count
    seeded_calls: Count
    seeded_cost_usd: Usd
    compounds: Count
    compounds_kept: Count
    lane_views: Annotated[tuple[LaneView, ...], Field(strict=False)] = ()


class RunLine(_Row):
    dispatch: str
    cost_usd: Usd
    seeded_calls: Count
    seeded_cost_usd: Usd
    kept: Count
    combined: bool
    holds: bool | None
    gain_pct: float | None
    floor_pct: float | None
    applied: Count | None = None


_READ: Final[dict[str, type[_Row]]] = {
    IDEA_EXPERIMENT: IdeaLine, ROUND_EXPERIMENT: RoundLine, RUN_EXPERIMENT: RunLine,
}  # fmt: skip


def _parse(path: Path) -> list[_Row]:
    out: list[_Row] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line) if line.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{n}: not JSON ({exc.msg})") from None
        kind = row.get("experiment") if isinstance(row, dict) else None
        if not isinstance(kind, str) or (cls := _READ.get(kind)) is None:
            continue
        try:
            r = cls.model_validate(
                {k: v for k, v in row.items() if k in cls.model_fields}
            )
        except ValidationError as exc:
            e = exc.errors()[0]
            why = f"{'.'.join(map(str, e['loc'])) or 'row'}: {e['msg']}"
            raise ValueError(f"{path}:{n}: malformed {kind} row ({why})") from None
        if r.arm not in ARMS or r.repo not in E1_REPOS:
            what = f"arm {r.arm!r}" if r.arm not in ARMS else f"library {r.repo!r}"
            raise ValueError(f"{path}:{n}: unknown {what}")
        if isinstance(r, IdeaLine) and not r.compound and r.lane not in GROUPS:
            raise ValueError(f"{path}:{n}: lane {r.lane!r}, not the leap, S1 or a lens")
        out.append(r)
    return out


@dataclass(frozen=True)
class Run:  # one (arm, library) engine run
    row: RunLine
    rounds: tuple[RoundLine, ...]
    ideas: tuple[IdeaLine, ...]

    @property
    def trialled(self) -> int:
        return sum(r.trialled for r in self.rounds)

    @property
    def delivered(self) -> float:  # the combine's gain when it held, else 0
        return (
            (self.row.gain_pct or 0.0) if self.row.combined and self.row.holds else 0.0
        )


@dataclass(frozen=True)
class Report:
    runs: dict[Key, Run]  # arm, then library, in X2's order
    sources: tuple[tuple[str, str, str], ...]  # (file, sha256 prefix, dispatches)

    @property
    def arms(self) -> tuple[str, ...]:
        return tuple(a for a in ARMS if any(k[0] == a for k in self.runs))

    def libs(self, arm: str) -> tuple[str, ...]:
        return tuple(repo for a, repo in self.runs if a == arm)


def _checked(at: str, row: RunLine, rounds: dict[int, RoundLine],
             ideas: Sequence[IdeaLine]) -> Run:  # fmt: skip
    got = sorted(rounds)
    if not got:
        raise ValueError(f"{at}: no round recorded")
    if got != list(range(1, got[-1] + 1)):
        raise ValueError(f"{at}: rounds {got}, not 1 to {got[-1]}")
    for i in ideas:
        if i.round is None and i.verdict == "keep":
            raise ValueError(f"{at}: hypothesis {i.hypothesis_id} kept in no round")
        if i.round is not None and i.round not in rounds:
            raise ValueError(f"{at}: hypothesis {i.hypothesis_id} in round {i.round}, "
                             "not recorded")  # fmt: skip
    for n in got:
        won = sum(i.round == n and i.verdict == "keep" for i in ideas)
        if won != rounds[n].kept:
            raise ValueError(
                f"{at}: round {n} records {rounds[n].kept} kept, its ideas {won}"
            )
    if row.kept != (total := sum(r.kept for r in rounds.values())):
        raise ValueError(f"{at}: the run records {row.kept} kept, its rounds {total}")
    return Run(row, tuple(rounds[n] for n in got), tuple(ideas))


def load(paths: Iterable[Path]) -> Report:
    files = [(p, _parse(p)) for p in sorted(paths, key=lambda p: (p.name, str(p)))]
    rows = [r for _, found in files for r in found]
    runs: dict[Key, RunLine] = {}
    rounds: dict[Key, dict[int, RoundLine]] = defaultdict(dict)
    ideas: dict[Key, dict[str, IdeaLine]] = defaultdict(dict)
    for r in rows:  # run rows first: a whole run twice reads as the run twice
        if isinstance(r, RunLine) and runs.setdefault((r.arm, r.repo), r) is not r:
            raise ValueError(f"{r.arm} {r.repo}: recorded twice")
    for r in rows:
        if isinstance(r, RoundLine):
            if rounds[r.arm, r.repo].setdefault(r.round, r) is not r:
                raise ValueError(f"{r.arm} {r.repo}: round {r.round} recorded twice")
        elif isinstance(r, IdeaLine):
            if ideas[r.arm, r.repo].setdefault(r.hypothesis_id, r) is not r:
                raise ValueError(f"{r.arm} {r.repo}: hypothesis {r.hypothesis_id} "
                                 "recorded twice")  # fmt: skip
    for a, repo in sorted({*rounds, *ideas} - {*runs}):
        raise ValueError(f"{a} {repo}: rounds with no {RUN_EXPERIMENT} row")
    if not runs:
        raise ValueError(
            f"no {RUN_EXPERIMENT} row in {', '.join(p.name for p, _ in files)}"
        )
    order = sorted(runs, key=lambda k: (ARMS.index(k[0]), E1_REPOS.index(k[1])))
    return Report(
        {k: _checked(" ".join(k), runs[k], rounds.get(k, {}),
                     list(ideas.get(k, {}).values())) for k in order},
        tuple((p.name, hashlib.sha256(p.read_bytes()).hexdigest()[:12],
               ", ".join(sorted({r.dispatch for r in found if isinstance(r, RunLine)})))
              for p, found in files),
    )  # fmt: skip


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _table(head: Sequence[object], body: Iterable[Sequence[object]]) -> list[str]:
    return [cells([redact_keys(str(v)) for v in head]), "| " + " | ".join("---" for _ in head) + " |",
            *(cells([redact_keys(str(v)) for v in r]) for r in body), ""]  # fmt: skip


def gain_cell(run: Run) -> str:
    g = run.row.gain_pct
    if not run.row.combined or g is None:
        return "none"
    return f"{g:+.1f}%" + ("" if run.row.holds else " (did not hold)")


def reading(diff: float, gap: float | None) -> str:  # O51 as amended, combine
    if gap is None:  # no twin: the fixed band
        return FIXED[abs(diff) >= BAND_GAIN]
    if abs(diff) <= gap:
        return f"inside its twin gap ({gap:.1f} points)"
    return "outside its twin gap"


def kept_reading(diff: int, gap: int | None) -> str:  # O52 as O51 amended
    if gap is None:  # no twin: the fixed band
        return FIXED[abs(diff) >= BAND_KEPT]
    beyond = max(abs(diff) - gap, 0)
    return (
        f"{KEPT[0]} (its twin gap, {gap} kept)" if not beyond else KEPT[min(beyond, 2)]
    )


def kept_call(diffs: Sequence[int]) -> str:  # O52: a sign count, no library decides
    more, fewer = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
    if more == fewer:
        return "no difference"
    return "keeps more" if more > fewer else "keeps fewer"


def mean_call(mean: float, gap: float | None) -> str:  # O52: against the twin's mean
    if gap is None:
        return UNBANDED
    if abs(mean) <= gap:
        return "within the twin's mean gap"
    return "better" if mean > 0 else "worse"


def _on(n: int) -> str:
    return f"on {n} librar{'y' if n == 1 else 'ies'}"


def twin_gaps(r: Report) -> Gaps:  # each twinned library's (tg, tk): sections 1, 6
    gaps: Gaps = {}
    for n in (n for n in r.libs(TWIN) if (BASE, n) in r.runs):
        a, b = r.runs[BASE, n], r.runs[TWIN, n]
        gaps[n] = abs(a.delivered - b.delivered), abs(a.row.kept - b.row.kept)
    return gaps


def twin_gap(r: Report) -> float | None:  # the twin's mean absolute combine gap
    gaps = [tg for tg, _ in twin_gaps(r).values()]
    return math.fsum(gaps) / len(gaps) if gaps else None


def hit_rate(kept: int, trialled: int) -> str:
    return f"{100 * kept / trialled:.1f} %" if trialled else "n/a"


def _hits(kept: tuple[int, int], tried: tuple[int, int]) -> list[object]:
    """Round 1, round 2 and the total: kept, trialled, the hit rate."""
    return [v for k, t in (*zip(kept, tried, strict=True), (sum(kept), sum(tried)))
            for v in (k, t, hit_rate(k, t))]  # fmt: skip


def _lane(i: IdeaLine) -> tuple[str, str, bool]:  # lane, model, round 1
    return COMPOUND if i.compound else GROUPS[str(i.lane)], i.model or "-", i.round == 1


def _path(r: Report, gaps: Gaps) -> list[str]:  # O54's measure, section 1's values
    if not gaps:
        return ["No twin rows: no path-dependence measure.", ""]
    body = [[n, gain_cell(r.runs[BASE, n]), gain_cell(r.runs[TWIN, n]), f"{tg:.1f}",
             r.runs[BASE, n].row.kept, r.runs[TWIN, n].row.kept, tk]
            for n, (tg, tk) in gaps.items()]  # fmt: skip
    many = "library" if len(gaps) == 1 else "libraries"
    return [*_table(("library", f"{BASE} combine", f"{TWIN} combine", "tg (points)",
                     f"{BASE} kept", f"{TWIN} kept", "tk (kept)"), body),
            f"The mean tg over {len(gaps)} {many} is {twin_gap(r):.1f} points.", "",
            "Identical settings, two runs: the gap measures how much the evolution "
            "loop's early keeps shape the outcome (O54), read with only one A/A pair "
            "per library.", ""]  # fmt: skip


def _band(r: Report, gaps: Gaps) -> list[str]:
    if not gaps:
        return ["No twin rows: every library below takes the fixed band (O51 as "
                "amended).", ""]  # fmt: skip
    body = [[n, r.runs[BASE, n].row.kept, r.runs[TWIN, n].row.kept, tk,
             gain_cell(r.runs[BASE, n]), gain_cell(r.runs[TWIN, n]), f"{tg:.1f}"]
            for n, (tg, tk) in gaps.items()]  # fmt: skip
    return [*_table(("library", f"{BASE} kept", f"{TWIN} kept", "kept gap (tk)", f"{BASE} combine",
                     f"{TWIN} combine", "combine gap (tg, points)"), body),
            "O51 as amended: each library with a twin is read against its own gaps above, "
            "a combine difference counting only beyond its tg and a kept-count difference "
            "only beyond its tk; only a library without a twin takes the fixed band of "
            f"{BAND_GAIN:g} points of combine gain and {BAND_KEPT:g} on the kept count.", "",
            f"The twin's mean gap over its {len(gaps)} libraries is {twin_gap(r):.1f} "
            "points of combine gain (O52's bar for an arm's combine).", ""]  # fmt: skip


def _sums(runs: Sequence[Run]) -> list[object]:
    cost, kept = math.fsum(x.row.cost_usd for x in runs), sum(x.row.kept for x in runs)
    rounds = [d for x in runs for d in x.rounds]
    return [sum(x.trialled for x in runs), kept,
            f"{math.fsum(x.delivered for x in runs) / len(runs):+.1f}%", f"{cost:.2f}",
            sum(x.row.seeded_calls for x in runs),
            f"{math.fsum(x.row.seeded_cost_usd for x in runs):.2f}",
            sum(d.compounds for d in rounds), sum(d.compounds_kept for d in rounds),
            per(cost, kept)]  # fmt: skip


def _seeds(arm: str, label: str, runs: Sequence[Run]) -> list[object]:
    late = [d for x in runs for d in x.rounds if d.round >= 2]
    usd, kept = math.fsum(d.seeded_cost_usd for d in late), sum(d.kept for d in late)
    return [arm, label, sum(d.trialled for d in late), kept, sum(d.seeds for d in late),
            sum(d.seeded_calls for d in late), f"{usd:.2f}", per(usd, kept)]  # fmt: skip


def _realised(r: Report) -> list[str]:  # S1, only where a row holds a record
    rows: list[list[object]] = []
    sums: list[list[object]] = []
    for arm in r.arms:
        recs = [(i.realisation, i.verdict == "keep") for (a, _), x in r.runs.items()
                if a == arm for i in x.ideas if i.realisation is not None]  # fmt: skip
        by, won = (
            Counter(c.label for c, _ in recs),
            Counter(c.label for c, k in recs if k),
        )
        rows += [[arm, lab, by[lab], won[lab]] for lab in RealisationLabel if by[lab]]
        few = (
            ""
            if min(by["fired"], by["not_fired"]) >= 10
            else " (needs 10 or more each side)"
        )
        sides = ", ".join(
            f"{lab} {won[lab]}/{by[lab]}" for lab in ("fired", "not_fired")
        )
        sums += [[arm, len(recs), sum(c.kept_not_fired for c, _ in recs),
                  sum(c.anchor_touched is False for c, _ in recs), sides + few]] if recs else []  # fmt: skip
    return [] if not rows else [
        "## 7 Realisation (S1)", "",
        "Each measured trial's engine label: how its anchor's counted work (its own "
        "calls and its frames' calls) moved; fired at a cut of 10 % or more, not_fired "
        "under 1 % either way. Counts are blind to per-unit speed, so this reads the "
        "counted gap, never the physical gap. The premise (fired keeps at least twice "
        "the not_fired rate, at least 10 trials each side) is read here, not decided.", "",
        *_table(("arm", "label", "trialled", "kept"), rows),
        *_table(("arm", "recorded", "kept, not fired", "anchor untouched",
                 "premise, kept of trialled"), sums),
    ]  # fmt: skip


def _combined(r: Report) -> list[str]:  # S2, only where a row holds a record
    runs: list[list[object]] = []
    why: list[list[object]] = []
    parts: list[list[object]] = []
    for (arm, lib), x in r.runs.items():
        recs = [(i.hypothesis_id, i.combine) for i in x.ideas if i.combine is not None]
        if not recs:
            continue
        lost = [c for _, c in recs if not c.delivered]
        runs.append([arm, lib, x.row.kept, x.row.kept - sum(c.duplicate_of is not None for _, c in recs),
                     len(recs), len(recs) - len(lost), len(lost),
                     sum(c.skip_reason is None for c in lost),
                     sum(c.reconcile == "eligible" for _, c in recs)])  # fmt: skip
        reasons = Counter(c.skip_reason or "(no reason)" for c in lost)
        why += [[arm, lib, k, reasons[k]] for k in sorted(reasons)]
        groups: dict[int, list[Combined]] = defaultdict(list)
        for _, c in recs:
            if c.duplicate_of is None:
                groups[c.component].append(c)
        hit = [g for g in groups.values() if len(g) > 1]
        same = sum({id(c) for c in g if c.delivered} == {id(c) for c in g if c.best_subset}
                   for g in hit)  # fmt: skip
        got = math.fsum(c.gain_pct or 0.0 for g in hit for c in g if c.delivered)
        top = math.fsum(c.gain_pct or 0.0 for g in hit for c in g if c.best_subset)
        parts.append([arm, lib, len(hit), same, f"{got:.1f}", f"{top:.1f}"])
    return [] if not runs else [
        "## 8 Combine record (S2)", "",
        "Each kept change at combine: delivered, or the reason it was not (its skip, "
        "or the combination's); hunk-identical keeps count once; eligible is part 3's "
        "record (the survivor left the blocked keep's counted unit made), no trial.", "",
        *_table(("arm", "library", "kept", "kept (duplicates once)", "recorded",
                 "delivered", "not delivered", "no reason", "eligible pairs"), runs),
        *_table(("arm", "library", "not delivered because", "keeps"), why),
        "Per run, the conflict components (two or more keeps that are not duplicates): "
        "how many delivered their max-sum conflict-free subset, and the standalone "
        "gains delivered against that subset's. Sums are not combines: only the tip's "
        "re-test is a delivered gain.", "",
        *_table(("arm", "library", "conflict components", "delivering the max-sum subset",
                 "delivered (standalone points)", "max-sum subset (standalone points)"), parts),
    ]  # fmt: skip


def render(r: Report) -> str:
    banded = twin_gaps(r)  # each twinned library's (tg, tk), sections 1 and 6
    common = [n for n in E1_REPOS if all((a, n) in r.runs for a in r.arms)]
    each = [[a, n, x.trialled, x.row.kept, gain_cell(x),
             "-" if x.row.floor_pct is None else f"{x.row.floor_pct:.1f}%", flag(x.row.holds),
             f"{x.row.cost_usd:.2f}", x.row.seeded_calls, f"{x.row.seeded_cost_usd:.2f}",
             sum(d.compounds for d in x.rounds), sum(d.compounds_kept for d in x.rounds),
             per(x.row.cost_usd, x.row.kept)] for (a, n), x in r.runs.items()]  # fmt: skip
    totals: list[list[object]] = []
    against: list[list[object]] = []
    lanes: list[list[object]] = []
    rates: list[list[object]] = []
    seeds: list[list[object]] = []
    calls: list[list[object]] = []
    gap = twin_gap(r)
    for arm in r.arms:
        own = [r.runs[arm, n] for n in r.libs(arm)]
        for scope, runs in ((f"every arm's ({', '.join(common)})", [r.runs[arm, n] for n in common]),
                            (f"own ({len(own)} libraries)", own)):  # fmt: skip
            totals += [[arm, scope, *_sums(runs)]] if runs else []
        both = [
            n for n in r.libs(arm) if arm not in (BASE, TWIN) and (BASE, n) in r.runs
        ]
        dks: list[int] = []
        dgs: list[float] = []
        for n in both:
            a, b = r.runs[BASE, n], r.runs[arm, n]
            dk, dg = b.row.kept - a.row.kept, b.delivered - a.delivered
            dks.append(dk)
            dgs.append(dg)
            tg, tk = banded.get(n, (None, None))
            against.append([arm, n, f"{dk:+d}", kept_reading(dk, tk), f"{dg:+.1f}",
                            reading(dg, tg)])  # fmt: skip
        if both:
            mean, on = math.fsum(dgs) / len(dgs), _on(len(both))
            calls.append([arm, ", ".join(both), sum(d > 0 for d in dks),
                          sum(d < 0 for d in dks), dks.count(0), f"{kept_call(dks)}, {on}",
                          f"{mean:+.1f}", "none" if gap is None else f"{gap:.1f}, {_on(len(banded))}",
                          f"{mean_call(mean, gap)}, {on}"])  # fmt: skip
        won = Counter(_lane(i) for x in own for i in x.ideas if i.verdict == "keep")
        tried = Counter(_lane(i) for x in own for i in x.ideas
                        if i.verdict in TRIED and i.round is not None)  # fmt: skip
        for g, m in sorted({(g, m) for g, m, _ in tried},
                           key=lambda k: (ORDER.index(k[0]), k[1])):  # fmt: skip
            rates.append([arm, g, m, *_hits((won[g, m, True], won[g, m, False]),
                                            (tried[g, m, True], tried[g, m, False]))])  # fmt: skip
        for g, m in sorted(
            {(g, m) for g, m, _ in won}, key=lambda k: (ORDER.index(k[0]), k[1])
        ):
            lanes.append([arm, g, m, won[g, m, True], won[g, m, False],
                          won[g, m, True] + won[g, m, False]])  # fmt: skip
        first = sum(v for k, v in won.items() if k[2])
        lanes.append([arm, "all lanes", "-", first, won.total() - first, won.total()])
        one = sum(v for k, v in tried.items() if k[2])
        rates.append([arm, "all lanes", "-",
                      *_hits((first, won.total() - first), (one, tried.total() - one))])  # fmt: skip
        seeds += [*(_seeds(arm, n, [r.runs[arm, n]]) for n in r.libs(arm)),
                  _seeds(arm, "all (own libraries)", own)]  # fmt: skip
    return "\n".join([
        "# X2 report: evolution on the levers X1 kept (spec 9.4, 9.6b)", "",
        "How to read it, before any comparison:", "",
        "- **Arm to arm only.** X2 is read arm to arm only, not against X1 on wins: "
        "round 1 trials the whole idea result (O50), where X1's slice trialled the "
        "marker's top 3 and the engine's default is 3 a round.",
        "- **The noise band (O51 as amended).** Each library is read against its own "
        f"twin gap where a twin exists: a difference from {BASE} counts only beyond "
        f"that library's gap between {BASE} and {TWIN}, in points of combine gain and "
        "on the kept count, and the gap itself is inside. Only a library without a "
        f"twin takes O51's fixed band: there an arm-to-arm difference under about "
        f"{BAND_GAIN:g} points of combine gain, or under {BAND_KEPT:g} on the kept "
        "count, is noise (O51).",
        "- **Reading the arms (O52).** Per library with a twin, a kept-count "
        "difference within its twin gap is inside the measured band, one beyond it is "
        "outside the measured band, not significant, and two or more beyond it are "
        "outside the measured band (with a twin gap of 0, O52's gaps of 0, 1 and 2 or "
        f"more). Per arm, against {BASE} over the libraries both ran: the "
        "kept count is a sign count, and the arm keeps more only if it keeps more on "
        "more libraries than it keeps fewer, keeps fewer only if it keeps fewer on more "
        "libraries than it keeps more, else no difference; the combine's mean "
        "difference is better only when it exceeds the twin's mean absolute gap, worse "
        "only when it is below minus that gap, else within the twin's mean gap. Each "
        "call says how many libraries it rests on. No single library decides (O52).",
        "- **Delivered gain.** A combine's gain counts only when it held: a run with "
        "no held combine delivers 0 in every difference and mean.",
        "- **Sources:** each results file, its SHA-256 prefix and its dispatches.", "",
        *_table(("file", "sha256", "dispatches"), r.sources),
        f"## 1 The A/A band ({BASE} against {TWIN})", "", *_band(r, banded),
        "## 2 Each arm and library", "",
        *_table(("arm", "library", "trialled", "kept", "combine", "floor", "held",
                 "cost USD", "seeded calls", "seeded USD", "compounds tried",
                 "compounds kept", "USD per win"), each),
        f"Totals over the libraries every arm has ({', '.join(common) or 'none'}), then "
        "each arm's own; the combine is the mean delivered gain.", "",
        *_table(("arm", "libraries", "trialled", "kept", "combine (mean)", "cost USD",
                 "seeded calls", "seeded USD", "compounds tried", "compounds kept",
                 "USD per win"), totals),
        f"## 3 Each arm against {BASE}", "",
        f"Differences are the arm less {BASE} on the same library: kept count and "
        "delivered combine gain in points.", "",
        *_table(("arm", "library", "kept", "reading", "combine (points)", "reading"), against),
        f"Arm-level calls against {BASE} over the libraries both ran: the kept-count "
        f"sign count, and the mean combine difference against the twin's ({TWIN}) "
        "mean gap. "
        "No single library decides (O52).", "",
        *_table(("arm", "libraries", "keeps more on", "keeps fewer on", "the same on",
                 "kept count", "combine mean (points)", "twin's mean gap", "combine"),
                calls),
        "## 4 Wins by lane", "",
        "Each kept hypothesis once, under its lane and model; round 2 is the seeded call's.", "",
        *_table(("arm", "lane", "model", "round 1", "round 2 (seeded)", "total"), lanes),
        "## 4b Hit rate by lane", "",
        "The hit rate is kept / trialled, so a lane's volume and its rate read apart. "
        "Trialled: each hypothesis of the lane, once, that reached a verdict (keep, "
        "inconclusive or reject) in a round, from section 4's rows; compounds are their "
        "own lane, and a lane with none trialled reads n/a.", "",
        *_table(("arm", "lane", "model", "round 1 kept", "round 1 trialled",
                 "round 1 hit rate", "round 2 kept", "round 2 trialled",
                 "round 2 hit rate", "total kept", "total trialled", "total hit rate"),
                rates),
        "## 5 Seeds (round 2)", "",
        *_table(("arm", "library", "trialled", "kept", "seeds shown", "seeded calls",
                 "seeded USD", "seeded USD per round-2 win"), seeds),
        "## 6 Path dependence (the charter's measure, O54): the twin gap on combine, "
        "per library", "",
        f"Section 1's values, by the same function: {BASE} and {TWIN} combine and "
        "their gap tg, kept and their gap tk.", "",
        *_path(r, banded),
        *_realised(r),
        *_combined(r),
    ])  # fmt: skip


# ---------------------------------------------------------------------------
# Variance (emergence round 2, S1): every draw against the pool, its arm out
# ---------------------------------------------------------------------------

POOL: Final = frozenset(a.key for a in EVERY_ARM if a.aa == "full")
SIGNS_NEED: Final = 6  # an arm call on fewer signs reads "not tested (n)" ([76])
SIDES: Final = "two-sided"  # the bar's p, pre-registered: 2 x the smaller tail
RANK_NEED: Final = 39  # the least k at which a rank's 2/(k+1) reaches 0.05


@dataclass(frozen=True)
class Draw:  # one (arm, library) run of one results file
    source: str
    run: Run

    @property
    def arm(self) -> str:
        return self.run.row.arm

    @property
    def repo(self) -> str:
        return self.run.row.repo

    @property
    def combine(self) -> float:
        return self.run.delivered


STATS: Final[tuple[tuple[str, Callable[[Draw], float]], ...]] = (
    ("kept", lambda d: float(d.run.row.kept)), ("combine", lambda d: d.combine))  # fmt: skip


def draws(paths: Iterable[Path]) -> tuple[Draw, ...]:
    """Each file loaded alone, its runs checked as ``load`` checks them; the
    same bytes twice are refused (a draw counted twice)."""
    out: list[Draw] = []
    seen: dict[str, str] = {}
    for p in sorted(paths, key=lambda p: (p.name, str(p))):
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if (first := seen.setdefault(digest, p.name)) != p.name:
            raise ValueError(f"{p.name}: the same bytes as {first}")
        out += [Draw(p.name, x) for x in load([p]).runs.values()]
    return tuple(out)


def pool(found: Iterable[Draw], arm: str, repo: str) -> tuple[Draw, ...]:
    return tuple(d for d in found if d.repo == repo and d.arm in POOL and d.arm != arm)


def _arm_out(d: Draw, against: Sequence[Draw]) -> None:
    if any(p.arm == d.arm for p in against):
        raise ValueError(f"{d.arm} {d.repo}: the pool holds the read arm's own run")


def rank(value: float, against: Sequence[float]) -> tuple[int, float]:
    """``value``'s position among ``against`` and itself (1 the lowest),
    ties read as least extreme, and the null rate of a position as extreme
    or more under exchangeable draws: 2 min(j, k + 2 - j) / (k + 1)."""
    k, below = len(against), sum(v < value for v in against)
    ties = sum(v == value for v in against)
    j = min(range(below + 1, below + ties + 2), key=lambda j: abs(j - (k + 2) / 2))
    return j, min(1.0, 2 * min(j, k + 2 - j) / (k + 1))


def rank_cells(d: Draw, against: Sequence[Draw]) -> list[object]:
    _arm_out(d, against)
    out: list[object] = []
    for name, stat in STATS:
        value = stat(d)
        j, rate = rank(value, [stat(p) for p in against]) if against else (0, 0.0)
        shown = f"{value:+.1f}" if name == "combine" else int(value)
        out += [
            shown,
            *((f"{j} of {len(against) + 1}", f"{rate:.2f}") if against else ("-", "-")),
        ]
    return out


def range_reading(d: Draw, against: Sequence[Draw]) -> str:
    """O51's form with the arm left out: kept against X2-0's mean in the
    pool, beyond the pool's range floored at 1 ([49]'s replay)."""
    _arm_out(d, against)
    base = [p.run.row.kept for p in against if p.arm == BASE]
    if not base:
        return "n/a"
    kept = [p.run.row.kept for p in against]
    beyond = abs(d.run.row.kept - math.fsum(base) / len(base)) > max(
        max(kept) - min(kept), 1
    )
    return "outside" if beyond else "inside"


def lower_median(values: Sequence[float]) -> float:
    return sorted(values)[(len(values) - 1) // 2]


@dataclass(frozen=True)
class SignCall:
    up: int
    down: int
    ties: int
    p_above: float  # the null's chance of a sign sum at least the observed
    p_below: float

    @property
    def p_two(self) -> float:
        return min(1.0, 2 * min(self.p_above, self.p_below))


def _sum(signs: Iterable[float], median: float) -> int:
    return sum((v > median) - (v < median) for v in signs)


def sign_call(groups: Iterable[tuple[Sequence[float], Sequence[float]]]) -> SignCall:
    """The arm's signs against each library's (pool, arm) lower pool median.
    The null deals each library's draws anew to pool and arm (exchangeable
    under no effect), so runs sharing one median are not counted as
    independent (judge [86]); libraries are independent: convolved."""
    up = down = ties = 0
    null: Counter[int] = Counter({0: 1})
    for against, arm in groups:
        median = lower_median(against)
        up, down = (
            up + sum(v > median for v in arm),
            down + sum(v < median for v in arm),
        )
        ties += sum(v == median for v in arm)
        both, one = [*against, *arm], Counter[int]()
        for picked in combinations(range(len(both)), len(arm)):
            rest = [v for i, v in enumerate(both) if i not in picked]
            one[_sum((both[i] for i in picked), lower_median(rest))] += 1
        both_null: Counter[int] = Counter()
        for (a, m), (b, n) in product(null.items(), one.items()):
            both_null[a + b] += m * n
        null = both_null
    total, seen = null.total(), up - down
    return SignCall(up, down, ties, sum(n for s, n in null.items() if s >= seen) / total,
                    sum(n for s, n in null.items() if s <= seen) / total)  # fmt: skip


def sign_cell(c: SignCall) -> str:
    head, n = f"{c.up} above, {c.down} below, {c.ties} ties", c.up + c.down
    if n < SIGNS_NEED:
        return f"{head}; not tested ({n})"
    return f"{head}; {SIDES} p {c.p_two:.4f} (above {c.p_above:.4f}, below {c.p_below:.4f})"


def delivered_sum(run: Run) -> float | None:
    """The standalone gains of the keeps that reached the tip (S2's record,
    else every keep where every keep applied), on 2 or more of them."""
    keeps = [i for i in run.ideas if i.verdict == "keep"]
    if any(i.combine is not None for i in keeps):
        keeps = [i for i in keeps if i.combine is not None and i.combine.delivered]
    elif run.row.applied != run.row.kept:
        return None
    return (
        math.fsum(i.gain_pct or 0.0 for i in keeps)
        if len(keeps) >= 2 and run.delivered
        else None
    )


def _mass(d: Draw) -> tuple[list[object], int]:
    gains = [i for i in d.run.ideas if i.verdict == "keep" and i.gain_pct is not None]
    top, total = max((i.gain_pct or 0.0 for i in gains), default=0.0), math.fsum(i.gain_pct or 0.0 for i in gains)  # fmt: skip
    wide = sum(i.floor_pct is not None and (i.gain_pct or 0.0) >= 2 * i.floor_pct for i in gains)  # fmt: skip
    ratio = delivered_sum(d.run)
    return [d.source, d.arm, d.repo, d.run.row.kept, f"{d.combine:+.1f}", wide,
            f"{top / total:.2f}" if total else "-", f"{d.combine - top:+.1f}",
            "-" if ratio is None else f"{ratio / d.combine:.3f}",
            f"{d.run.row.cost_usd / d.combine:.3f}" if d.combine > 0 else "n/a"], wide  # fmt: skip


def _read_row(d: Draw, found: Sequence[Draw]) -> list[object]:
    own = pool(found, d.arm, d.repo)
    return [
        d.source,
        d.arm,
        d.repo,
        len(own),
        *rank_cells(d, own),
        range_reading(d, own),
    ]


def render_variance(found: Sequence[Draw]) -> str:
    libs = sorted({d.repo for d in found})
    whole = {n: pool(found, "", n) for n in libs}  # every pool draw of the library
    ks = {n: len(p) for n, p in whole.items()}
    pools = [[n, ks[n], ", ".join(str(k) for k in sorted(d.run.row.kept for d in p)),
              ", ".join(f"{v:+.1f}" for v in sorted(d.combine for d in p))] for n, p in whole.items()]  # fmt: skip
    reads = [_read_row(d, found) for d in found]
    calls: list[list[object]] = []
    bars: list[list[object]] = []
    for arm in [a for a in ARMS if any(d.arm == a for d in found)]:
        mine = [(n, [d for d in found if d.arm == arm and d.repo == n]) for n in libs]
        read = [
            (n, ds, pool(found, arm, n)) for n, ds in mine if ds and pool(found, arm, n)
        ]
        for name, stat in STATS if read else ():
            c = sign_call(
                ([stat(p) for p in ps], [stat(d) for d in ds]) for _, ds, ps in read
            )
            calls.append([arm, name, ", ".join(n for n, _, _ in read), sign_cell(c)])
            bars.append([f"{arm} sign test, {name}", f"{SIGNS_NEED} signs", c.up + c.down,
                         f"read, {SIDES} p {c.p_two:.4f}" if c.up + c.down >= SIGNS_NEED
                         else f"not tested ({c.up + c.down})"])  # fmt: skip
    bars += [[f"rank call, {n}", f"k {RANK_NEED}", k, f"not tested (k {k})" if k < RANK_NEED else "read"]
             for n, k in ks.items()]  # fmt: skip
    mass, totals = [], []
    for arm in [a for a in ARMS if any(d.arm == a for d in found)]:
        rows = [_mass(d) for d in found if d.arm == arm]
        mass += [r for r, _ in rows]
        ds = [d for d in found if d.arm == arm]
        cost, kept, points = (math.fsum(d.run.row.cost_usd for d in ds), sum(d.run.row.kept for d in ds),
                              math.fsum(d.combine for d in ds))  # fmt: skip
        totals.append([arm, len(ds), f"{kept / len(ds):.1f}", f"{points / len(ds):+.1f}",
                       f"{sum(w for _, w in rows) / len(ds):.1f}", per(cost, kept),
                       f"{cost / points:.3f}" if points > 0 else "n/a"])  # fmt: skip
    ratios = sorted(
        s / d.combine for d in found if (s := delivered_sum(d.run)) is not None
    )
    views: dict[tuple[str, int, str], list[LaneView]] = defaultdict(list)
    for d in found:
        for r in d.run.rounds:
            for v in r.lane_views:
                views[d.repo, r.round, v.lane].append(v)
    seen = [[n, r, lane, len(vs), len({v.view_sha for v in vs}),
             ", ".join(sorted({v.served_model or "-" for v in vs}))]
            for (n, r, lane), vs in sorted(views.items())]  # fmt: skip
    return "\n".join([
        "# X2 variance: the A/A pool with the read arm left out (emergence round 2, S1)", "",
        f"- **The pool.** Per library, the runs of the arms whose requests and delivery are "
        f"{BASE}'s ({', '.join(a for a in ARMS if a in POOL)}), frozen before any run; a run "
        "is never read against its own arm's runs.",
        "- **Rank, not range.** Each run prints its position j among the pool's k draws and "
        "itself, and the null rate of a position as extreme, 2 min(j, k + 2 - j) / (k + 1); "
        f"a library call needs k {RANK_NEED} for 0.05.",
        "- **The arm call.** Each run's sign against its library's pool lower median; the "
        "exact null deals each library's draws anew, so an arm's runs on one library are not "
        f"counted as independent; fewer than {SIGNS_NEED} signs read not tested (n). The "
        f"call reads one p, {SIDES} (2 x the smaller tail, at most 1), fixed before any run; "
        "the two tails print beside it.",
        "- **Ruling.** O51 as amended and O52 stay the ruling reading (x2.md); this page is "
        "printed beside them. O51's form, the arm left out: kept against X2-0's mean beyond "
        "the pool's range floored at 1.", "",
        "## 1 The pool", "", *_table(("library", "k", "kept", "combine"), pools),
        "## 2 Each run against the pool, its arm left out", "",
        *_table(("file", "arm", "library", "k", "kept", "kept rank", "rate", "combine",
                 "combine rank", "rate", "O51's form (kept)"), reads),
        "## 3 Arm calls", "", *_table(("arm", "statistic", "libraries", "signs"), calls),
        "## 4 Delivered mass (measures 3 and 6)", "",
        *_table(("file", "arm", "library", "kept", "combine", "keeps at 2x floor",
                 "top keep share", "combine - top keep", "delivered sum / combine",
                 "USD per delivered point"), mass),
        *_table(("arm", "runs", "kept per run", "combine per run", "keeps at 2x floor per run",
                 "USD per kept", "USD per delivered point"), totals),
        f"{len(ratios)} runs with 2 or more delivered keeps" + (
            f": median {statistics.median(ratios):.2f}, range {ratios[0]:.2f}-{ratios[-1]:.2f}, "
            f"{sum(x >= 0.9 for x in ratios)} at 0.9 or more" if ratios else ""), "",
        "## 5 Bars and their n", "", *_table(("bar", "needs", "has", "status"), bars),
        "## 6 Lane views", "",
        *(_table(("library", "round", "lane", "runs", "distinct views", "served models"), seen)
          if seen else ["No lane view recorded.", ""]),
    ])  # fmt: skip


# ---------------------------------------------------------------------------
# Keeps by round (Window 2, X2-D): where each run's keeps came from
# ---------------------------------------------------------------------------

ROUNDS_SHOWN: Final = 3  # X2-D's rounds; a run recording more widens the page


@dataclass(frozen=True)
class RoundGain:  # one recorded round of one run
    round: int
    ideas: int  # fresh ideas kept
    compounds: int  # near-miss compounds kept (the round row's compounds_kept)
    idea_points: float  # standalone gains, vs base, not additive
    compound_points: float
    delivered: int | None  # keeps reaching the tip (S2's records), None without

    @property
    def kept(self) -> int:
        return self.ideas + self.compounds


def round_gains(at: str, run: Run) -> tuple[RoundGain, ...]:
    """Each recorded round's keeps, fresh ideas and compounds apart, with
    their standalone gains (a keep with no gain counts 0) under the round
    that first trialled them; refused when the round row's compounds kept
    and the hypothesis rows' compound flags disagree."""
    recorded = any(i.combine is not None for i in run.ideas)
    out = []
    for d in run.rounds:
        keeps = [i for i in run.ideas if i.round == d.round and i.verdict == "keep"]
        joined = [i for i in keeps if i.compound]
        if len(joined) != d.compounds_kept:
            raise ValueError(f"{at}: round {d.round} records {d.compounds_kept} "
                             f"compounds kept, its ideas {len(joined)}")  # fmt: skip
        out.append(RoundGain(
            d.round, d.kept - d.compounds_kept, d.compounds_kept,
            math.fsum(i.gain_pct or 0.0 for i in keeps if not i.compound),
            math.fsum(i.gain_pct or 0.0 for i in joined),
            sum(i.combine is not None and i.combine.delivered for i in keeps) if recorded else None,
        ))  # fmt: skip
    return tuple(out)


def _of(gains: Sequence[RoundGain]) -> str:  # delivered of kept, over recorded runs
    got = [g for g in gains if g.delivered is not None]
    return (
        f"{sum(g.delivered or 0 for g in got)} of {sum(g.kept for g in got)}"
        if got
        else "-"
    )


def render_rounds(found: Sequence[Draw]) -> str:
    gains = [
        {g.round: g for g in round_gains(f"{d.arm} {d.repo}", d.run)} for d in found
    ]
    depth = max(ROUNDS_SHOWN, *(len(gs) for gs in gains))
    numbers = range(1, depth + 1)
    runs: list[list[object]] = []
    for d, gs in zip(found, gains, strict=True):
        total = math.fsum(g.idea_points + g.compound_points for g in gs.values())
        runs.append([d.source, d.arm, d.repo, len(gs),
                     *(v for n in numbers for v in (
                         (f"{gs[n].ideas} + {gs[n].compounds}", f"{gs[n].idea_points:+.1f}",
                          f"{gs[n].compound_points:+.1f}", _of([gs[n]]))
                         if n in gs else ("-",) * 4)),
                     f"{total:+.1f}", f"{d.combine:+.1f}"])  # fmt: skip
    arms: list[list[object]] = []
    for arm in [a for a in ARMS if any(d.arm == a for d in found)]:
        mine = [(d, gs) for d, gs in zip(found, gains, strict=True) if d.arm == arm]
        total = math.fsum(g.idea_points + g.compound_points for _, gs in mine for g in gs.values())  # fmt: skip
        cells: list[object] = []
        for n in numbers:
            got = [gs[n] for _, gs in mine if n in gs]
            k = len(got)
            cells += [k, *((f"{sum(g.ideas for g in got) / k:.1f} + {sum(g.compounds for g in got) / k:.1f}",
                            f"{math.fsum(g.idea_points for g in got) / k:+.1f}",
                            f"{math.fsum(g.compound_points for g in got) / k:+.1f}", _of(got))
                           if got else ("-",) * 4)]  # fmt: skip
        arms.append([arm, len(mine), *cells, f"{total / len(mine):+.1f}",
                     f"{math.fsum(d.combine for d, _ in mine) / len(mine):+.1f}"])  # fmt: skip
    points = "standalone points, {} (vs base, not additive)"
    per_run = [f"round {n} {c}" for n in numbers for c in (
        "kept, ideas + compounds", points.format("ideas"), points.format("compounds"),
        "delivered")]  # fmt: skip
    per_arm = [f"round {n} {c}" for n in numbers for c in (
        "runs", "kept per run, ideas + compounds", points.format("ideas") + " per run",
        points.format("compounds") + " per run", "delivered")]  # fmt: skip
    return "\n".join([
        "# X2 keeps by round: where each run's keeps came from (Window 2, X2-D)", "",
        "- **Not a contribution.** Each round's standalone points are its keeps' own "
        "gains against the base (each hypothesis row's gain), summed under the round "
        "that first trialled them; standalone gains overlap and a compound holds its "
        "parents' sites, so the points are neither additive nor a round's share of the "
        "delivered gain.",
        "- **The third round's delivered gain.** What a third round adds to delivered "
        "gain is read only from X2-D's delivered combine against the pool on the "
        "variance page (``--variance``; O59 section 5's primary measure). This page "
        "says where the keeps came from, nothing more.",
        "- **Fresh ideas + near-miss compounds.** Each round's keeps and points are split "
        "into fresh ideas and near-miss compounds (the round row's compounds kept, the "
        "hypothesis rows' compound flag), so a round that kept only a compound reads "
        "0 + 1.",
        "- **Delivered.** Where the rows carry per-keep combine records (S2), the round's "
        "keeps that reached the tip, of its keeps; else -. The run's delivered combine "
        "(0 when it did not hold) is printed beside.",
        "- **Runs.** As the variance page, each file alone: every (arm, library) run of "
        "every file is one run; a round it did not reach reads -, and an arm's per-run "
        "figures for a round are over the runs that reached it.", "",
        "## 1 Each run", "",
        *_table(("file", "arm", "library", "rounds", *per_run,
                 points.format("every keep"), "delivered combine"), runs),
        "## 2 Each arm", "",
        *_table(("arm", "runs", *per_arm, points.format("every keep") + " per run",
                 "delivered combine per run"), arms),
    ])  # fmt: skip


def main(argv: Sequence[str] | None = None, echo: Callable[[str], None] = print) -> int:
    """Write ``x2.md`` (``--variance``: ``variance.md``; ``--rounds``:
    ``rounds.md``); 2 on a refused or unreadable input (nothing written)."""
    parser = argparse.ArgumentParser(prog="ideas_x2_report", description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    page = parser.add_mutually_exclusive_group()
    page.add_argument("--variance", action="store_true")
    page.add_argument("--rounds", action="store_true")
    args = parser.parse_args(argv)
    name = "variance.md" if args.variance else "rounds.md" if args.rounds else "x2.md"
    try:
        if args.variance:
            text = render_variance(draws(args.results))
        elif args.rounds:
            text = render_rounds(draws(args.results))
        else:
            text = render(load(args.results))
    except (OSError, ValueError) as error:
        echo(f"error: {error}")
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / name).write_text(text, encoding="utf-8", newline="\n")
    echo(f"wrote {name} to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
