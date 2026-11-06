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
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from autonomous_ai_agents.common.models import VerdictOutcome
from autonomous_ai_agents.optimization.idea_types import LENS_LANES, Lane

from .conftest import redact_keys
from .discovery_io import cells, flag, per
from .ideas_probe import E1_REPOS, SERVICE_DIR
from .ideas_x2 import IDEA_EXPERIMENT, ROUND_EXPERIMENT, RUN_EXPERIMENT, X2_ARMS

REPORT_DIR: Final = SERVICE_DIR.parents[1] / ".claude/handoff/step3/idea-lab/x2"
ARMS: Final = tuple(a.key for a in X2_ARMS)  # X2-0, X2-0', X2-V
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


class IdeaLine(_Row):
    round: Annotated[int, Field(ge=1)] | None  # None: left in the pool
    hypothesis_id: str
    lane: str | None
    model: str | None
    compound: bool
    verdict: str


class RoundLine(_Row):
    round: Annotated[int, Field(ge=1)]
    trialled: Count
    kept: Count
    seeds: Count
    seeded_calls: Count
    seeded_cost_usd: Usd
    compounds: Count
    compounds_kept: Count


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
    ])  # fmt: skip


def main(argv: Sequence[str] | None = None, echo: Callable[[str], None] = print) -> int:
    """Write ``x2.md``; 2 on a refused or unreadable input (nothing written)."""
    parser = argparse.ArgumentParser(prog="ideas_x2_report", description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    args = parser.parse_args(argv)
    try:
        text = render(load(args.results))
    except (OSError, ValueError) as error:
        echo(f"error: {error}")
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "x2.md").write_text(text, encoding="utf-8", newline="\n")
    echo(f"wrote x2.md to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
