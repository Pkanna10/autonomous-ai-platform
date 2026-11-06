"""V-x2rep: the X2 report (idea-lab spec 9.4 and 9.6b; O50, O51, O52), offline.

Pure code over results files: no request, no network, the same bytes on
every run and whatever the files' order. ``uv run python -m
live.ideas_x2_report <results.jsonl>... [--out DIR]`` (from ``tests/``,
``PYTHONPATH=../src:.``) reads the rows ``ideas_x2.X2Recorder`` writes,
``ideas-x2-hypothesis``, ``ideas-x2-round`` and ``ideas-x2-run`` (every other
kind skipped; a kind read is parsed strictly, its fields by name), and writes
``x2.md`` under ``--out`` (``REPORT_DIR`` by default).

Before any comparison it says that X2 is read arm to arm only (O50), states
O51's noise band and O52's reading rules and lists its sources. Then: the
A/A band (X2-0 against its twin X2-0', per library), each arm and library's
figures with totals over the libraries every arm has and over the arm's own,
each arm against X2-0 with its band label, then O52's arm-level calls (a
kept-count sign count, and the mean combine difference against the twin's
mean gap), wins by lane and round, and round 2's seeds. A combine's
gain counts only when it held: a run with no held combine delivers 0 in
every difference and mean. Rounds after the second count as round 2's
(X2 runs two). Refused, nothing written: a malformed row, an arm or library
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
ARMS: Final = tuple(a.key for a in EVERY_ARM)  # X2-0, X2-0', X2-V, X2-C
BASE, TWIN = ARMS[0], ARMS[1]
BAND_GAIN: Final = 4.0  # O51: points of combine gain
BAND_KEPT: Final = 1.0  # O51: on the kept count
WITHIN, OUTSIDE = "within the band (noise)", "outside the band"
UNBANDED: Final = "no band (unbanded)"
# O52, per library: a kept-count gap of 0, of 1, of 2 or more
KEPT: Final = ("inside the measured band", "outside the measured band, not significant",
               "outside the measured band")  # fmt: skip
GROUPS: Final = {Lane.leap.value: "leap", Lane.obvious.value: "S1 (obvious)",
                 **{lane.value: lane.value for lane in LENS_LANES}}  # fmt: skip
COMPOUND: Final = "compound"
ORDER: Final = (*GROUPS.values(), COMPOUND)
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


class IdeaLine(_Row):
    round: Annotated[int, Field(ge=1)] | None  # None: left in the pool
    hypothesis_id: str
    lane: str | None
    model: str | None
    compound: bool
    verdict: str
    realisation: Realised | None = None  # X2-C only (S1)


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


def reading(diff: float, band: float, *, banded: bool) -> str:
    return UNBANDED if not banded else WITHIN if abs(diff) < band else OUTSIDE


def kept_reading(diff: int, *, banded: bool) -> str:  # O52, per library
    return KEPT[min(abs(diff), 2)] if banded else UNBANDED


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


def twin_gap(r: Report) -> float | None:  # the twin's mean absolute combine gap
    gaps = [abs(r.runs[BASE, n].delivered - r.runs[TWIN, n].delivered)
            for n in r.libs(TWIN) if (BASE, n) in r.runs]  # fmt: skip
    return math.fsum(gaps) / len(gaps) if gaps else None


def _band(r: Report) -> tuple[list[str], frozenset[str]]:
    libs = [n for n in r.libs(TWIN) if (BASE, n) in r.runs]
    if not libs:
        return ["No twin rows: every difference below is unbanded.", ""], frozenset()
    body, kg, gg = [], 0, 0.0
    for n in libs:
        a, b = r.runs[BASE, n], r.runs[TWIN, n]
        k, g = abs(a.row.kept - b.row.kept), abs(a.delivered - b.delivered)
        kg, gg = max(kg, k), max(gg, g)
        body.append(
            [n, a.row.kept, b.row.kept, k, gain_cell(a), gain_cell(b), f"{g:.1f}"]
        )
    return [*_table(("library", f"{BASE} kept", f"{TWIN} kept", "kept gap", f"{BASE} combine",
                     f"{TWIN} combine", "gain gap (points)"), body),
            f"O51 fixed the band at under {BAND_GAIN:g} points of combine gain and under "
            f"{BAND_KEPT:g} on the kept count; the twin measured a largest gap of "
            f"{gg:.1f} points and {kg} on the kept count.", "",
            f"The twin's mean gap over its {len(libs)} libraries is {twin_gap(r):.1f} "
            "points of combine gain (O52's bar for an arm's combine).", ""], frozenset(libs)  # fmt: skip


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
        "## 6 Realisation (S1)", "",
        "Each measured trial's engine label: how its anchor's counted work (its own "
        "calls and its frames' calls) moved; fired at a cut of 10 % or more, not_fired "
        "under 1 % either way. Counts are blind to per-unit speed, so this reads the "
        "counted gap, never the physical gap. The premise (fired keeps at least twice "
        "the not_fired rate, at least 10 trials each side) is read here, not decided.", "",
        *_table(("arm", "label", "trialled", "kept"), rows),
        *_table(("arm", "recorded", "kept, not fired", "anchor untouched",
                 "premise, kept of trialled"), sums),
    ]  # fmt: skip


def render(r: Report) -> str:
    band, banded = _band(r)
    common = [n for n in E1_REPOS if all((a, n) in r.runs for a in r.arms)]
    each = [[a, n, x.trialled, x.row.kept, gain_cell(x),
             "-" if x.row.floor_pct is None else f"{x.row.floor_pct:.1f}%", flag(x.row.holds),
             f"{x.row.cost_usd:.2f}", x.row.seeded_calls, f"{x.row.seeded_cost_usd:.2f}",
             sum(d.compounds for d in x.rounds), sum(d.compounds_kept for d in x.rounds),
             per(x.row.cost_usd, x.row.kept)] for (a, n), x in r.runs.items()]  # fmt: skip
    totals: list[list[object]] = []
    against: list[list[object]] = []
    lanes: list[list[object]] = []
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
            against.append([arm, n, f"{dk:+d}", kept_reading(dk, banded=n in banded),
                            f"{dg:+.1f}", reading(dg, BAND_GAIN, banded=n in banded)])  # fmt: skip
        if both:
            mean, on = math.fsum(dgs) / len(dgs), _on(len(both))
            calls.append([arm, ", ".join(both), sum(d > 0 for d in dks),
                          sum(d < 0 for d in dks), dks.count(0), f"{kept_call(dks)}, {on}",
                          f"{mean:+.1f}", "none" if gap is None else f"{gap:.1f}, {_on(len(banded))}",
                          f"{mean_call(mean, gap)}, {on}"])  # fmt: skip
        won = Counter((COMPOUND if i.compound else GROUPS[str(i.lane)], i.model or "-",
                       i.round == 1) for x in own for i in x.ideas if i.verdict == "keep")  # fmt: skip
        for g, m in sorted(
            {(g, m) for g, m, _ in won}, key=lambda k: (ORDER.index(k[0]), k[1])
        ):
            lanes.append([arm, g, m, won[g, m, True], won[g, m, False],
                          won[g, m, True] + won[g, m, False]])  # fmt: skip
        first = sum(v for k, v in won.items() if k[2])
        lanes.append([arm, "all lanes", "-", first, won.total() - first, won.total()])
        seeds += [*(_seeds(arm, n, [r.runs[arm, n]]) for n in r.libs(arm)),
                  _seeds(arm, "all (own libraries)", own)]  # fmt: skip
    return "\n".join([
        "# X2 report: evolution on the levers X1 kept (spec 9.4, 9.6b)", "",
        "How to read it, before any comparison:", "",
        "- **Arm to arm only.** X2 is read arm to arm only, not against X1 on wins: "
        "round 1 trials the whole idea result (O50), where X1's slice trialled the "
        "marker's top 3 and the engine's default is 3 a round.",
        f"- **The noise band.** On the twin's libraries an arm-to-arm difference under "
        f"about {BAND_GAIN:g} points of combine gain, or under {BAND_KEPT:g} on the kept "
        "count, is noise (O51). A library with no twin run has no band: its "
        "differences are unbanded.",
        f"- **Reading the arms (O52).** Per library, a kept-count gap of 0 is inside "
        "the measured band (the twin's), a gap of 1 is outside the measured band, not "
        "significant, and a gap of 2 or more is outside the measured band; the combine "
        f"label stays O51's. Per arm, against {BASE} over the libraries both ran: the "
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
        f"## 1 The A/A band ({BASE} against {TWIN})", "", *band,
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
        "## 5 Seeds (round 2)", "",
        *_table(("arm", "library", "trialled", "kept", "seeds shown", "seeded calls",
                 "seeded USD", "seeded USD per round-2 win"), seeds),
        *_realised(r),
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
