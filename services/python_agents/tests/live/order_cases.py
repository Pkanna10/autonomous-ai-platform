"""The combine-order replay's cases (O65 item 2): every archived held combine.

``census`` reads the archive (``replay_archive.ARCHIVE``, in git): every
``ideas-x2-run`` row of ``w2-sprint/live`` whose combine held with two or more
keeps is one ``OrderRun``. That is the O59 sprint, O61 and O62 rows alike;
X2-SV is out of scope (no kept diff was archived). A row in scope that lacks
what the measured-gain choice (b) needs is listed in ``Skipped`` with why, and
never measured:

- every keep's diff entry written whole (file, sha256, not truncated, no write
  error) and as many entries as keeps;
- every keep's recorded standalone gain (its hypothesis row's ``gain_pct``: the
  verdict's gain, the first look; the confirmation's second look is in no
  row, so ``order_gain``'s mean of both looks cannot be rebuilt);
- the delivered patch with the trials it applied, all of them keeps;
- today's greedy merge as the delivery: a row whose ``fallback_trial_id``
  names the fallback is a gap, since the score-order greedy set it replaced
  is in no row (the measurer also refuses a run whose left-out keep merges
  cleanly onto the delivered tip: ``combine_order.NotGreedyError``).

**(b) orders on the first look** (``ORDER_BASIS``): each keep's recorded
gain is the verdict's first look; the archive holds no ``confirmed_gain``,
so the order is noisier than the engine's mean-of-two order (``order_gain``),
and ties break on hypothesis id (no score is recorded).

**Greedy provability** (``greedy_basis``, F3): each run says whether its
delivery is provably today's greedy merge rather than a fallback, and why;
a run that is not provable is still measured, and flagged.

``load_run`` is the integrity check, before any clone: the delivered patch
and every kept diff through ``replay_archive.load_archived`` (one row a
library, its arm, dispatch and base; each path inside the run's own patch
directory and the archive; each sha256 the archived one), each keep's
hypothesis id its entry's.

**(b) alone** (O71 item 1, ``B_CASES``, ``b_census``): the pre-registered
X2-DT comparator is the 20 X2-D runs' delivered gain under gain order; 17
have O65 rows, three do not (one keep; a set that did not hold; a fallback
delivery). Those three are measured on the gain-ordered side alone
(``sides`` ``b``): no (a) set is rebuilt, no delivered patch is read, and
every keep's diff passes the same integrity check (``load_b_run``: the run
row's arm, dispatch and base, each keep's path and sha256). They are a case
list of their own (``B_RUNS``), selected by ``$LIVE_ORDER_BATCH`` ``b``
alone, so a dispatch runs exactly those three and the 58 both-sides cases
cannot run with them.

**Minutes** (``plan_minutes``): from the ``combine-replay`` run 43194422719's
measured times on a GitHub runner (``o62/replay.md`` section 2): per library
the baseline step with its calibration (``BASELINE_S``) and one re-test
(``LOOK_S``; markdown, not re-tested there, at the largest), plus a clone
allowance. A run is four looks of two tips (two when both choices give one
tree), each with a fallback look when its set does not hold, and one look per
keep of a conflicting pair; offline the conflicts and the holds are unknown,
so a run that left a keep out counts eight tip looks and every keep as a
single, one that left none out four (an upper bound). All 59 runs would be
about 145 minutes, past 150 for one job with twice the margin, so the
libraries go in ``BATCHES``; the job is ``JOB_SETUP_MINUTES`` plus twice the
largest batch. A (b)-only run is two looks of one tip, each with its
fallback, and every keep as a single when it has two or more: the three
need ``B_PLAN_MINUTES``, inside the same job.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .replay_archive import (
    ARCHIVE,
    DELIVERED,
    FALLBACK,
    NO_TIP,
    IntegrityError,
    ReplayCase,
    load_archived,
)

ORDER_EXPERIMENT: Final = "combine-order"
ORDER_RUN_CAP_USD: Final = 0.0  # no Claude request
OUT_OF_SCOPE: Final[Mapping[str, str]] = {"X2-SV": "X2-SV: no kept diff archived"}
NOT_HELD: Final = "the combine did not hold"
FEW_KEEPS: Final = "fewer than two keeps"
_FILE: Final = re.compile(r"ideas-x2-(X2-[A-Z0-9]{1,4})-([0-9]{6,12})\.jsonl")
_PATCHES: Final = "live-patches/"

BATCH_ENV: Final = "LIVE_ORDER_BATCH"
BATCHES: Final[Mapping[str, tuple[str, ...]]] = {
    "1": ("sqlparse",),
    "2": ("markdown",),
    "3": ("mistune", "tomli"),
}
B_BATCH: Final = "b"  # $LIVE_ORDER_BATCH for the (b)-only cases (O71 item 1)
SIDES_AB: Final = "ab"  # both choices, a, b, b, a (O65 item 2)
SIDES_B: Final = "b"  # the gain-ordered choice alone (O71 item 1)
B_PLAN_MINUTES: Final = 9  # plan_minutes of B_RUNS: 398 s mistune, 112 s tomli
# run 43194422719's measured seconds (o62/replay.md section 2), rounded up
BASELINE_S: Final[Mapping[str, float]] = {
    "tomli": 22.0, "mistune": 44.0, "sqlparse": 52.0, "markdown": 38.0,
}  # fmt: skip
LOOK_S: Final[Mapping[str, float]] = {
    "tomli": 6.0, "mistune": 14.0, "sqlparse": 14.0, "markdown": 14.0,
}  # fmt: skip
CLONE_S: Final = 60.0  # a pinned clone and every tip commit, with room
JOB_SETUP_MINUTES: Final = 15  # checkout, uv sync, sandbox probe, collection
ORDER_JOB_MINUTES: Final = 117  # ci.yml's combine-order timeout: 15 + 2 x 51
MAX_JOB_MINUTES: Final = 150  # the owner's bound for one dispatch
ORDER_BASIS: Final = "first look"  # what (b) orders on (no confirmed_gain archived)
PROVEN: Final = "proven"
NOT_PROVABLE: Final = "not provable"
ALL_APPLIED: Final = "every keep was applied"
BY_ROW: Final = "its row records no fallback"
SEVERAL: Final = "more than one change was delivered; a fallback delivers one"
NOT_FALLBACK: Final = (
    "the delivered keep is neither of the two best recorded singles, so it cannot be"
    " the fallback"
)
ONE_OF_TWO: Final = (
    "one keep was delivered and the fallback could have chosen it; the left-out"
    " keeps conflict with it"
)


@dataclass(frozen=True)
class Keep:
    """One kept trial: its ids, its recorded standalone gain (a fraction)
    and its diff's path from the archive root."""

    trial_id: str
    hypothesis_id: str
    gain: float
    patch: str


@dataclass(frozen=True)
class OrderRun:
    """One held combine: the delivered patch's case, the trials (a) applied
    in their merge order, and every keep in the row's order."""

    case: ReplayCase
    applied: tuple[str, ...]
    keeps: tuple[Keep, ...]
    archived_gain_pct: float | None
    archived_floor_pct: float | None
    # PROVEN or NOT_PROVABLE (greedy_basis); None: (b) alone reads no (a)
    greedy: str | None = PROVEN
    greedy_reason: str | None = ALL_APPLIED
    sides: str = SIDES_AB  # SIDES_AB, or SIDES_B: (b) alone, no (a) set
    why_no_a: str | None = None  # (b) alone: why (a) is not measured

    @property
    def id(self) -> str:
        return self.case.id

    @property
    def library(self) -> str:
        return self.case.library

    @property
    def left_out(self) -> bool:
        """(a) left a keep out: the only runs with a conflict to choose."""
        return len(self.applied) < len(self.keeps)


@dataclass(frozen=True)
class BCase:
    """One X2-D run measured on the gain-ordered side alone, and why (a) is not."""

    arm: str
    dispatch: str
    library: str
    why: str

    @property
    def id(self) -> str:
        return f"{self.arm}-{self.dispatch}-{self.library}"


B_CASES: Final = (
    BCase("X2-D", "43159144063", "tomli",
          "one keep (fewer than two keeps): no conflict choice, so (a) and (b) are"
          " one set; (b) alone is measured so that every comparator value is"
          " replay-measured"),
    BCase("X2-D", "43145496896", "mistune",
          "today's set did not hold and nothing was delivered: (a) is not"
          " measured; the comparator needs the gain-ordered side alone"),
    BCase("X2-D", "43159154661", "mistune",
          "the fallback was delivered and today's greedy set is not recorded, so"
          " (a) cannot be rebuilt; the comparator needs the gain-ordered side"
          " alone"),
)  # fmt: skip


@dataclass(frozen=True)
class Skipped:
    id: str
    reason: str
    data: bool  # True: in scope but lacks what (b) needs; False: out of scope
    library: str = ""
    keeps: int = 0


def _declared(arm: str, dispatch: str, file: object) -> str | None:
    """A row's ``live-patches/<run>/<name>`` as a path from the archive root."""
    if not isinstance(file, str) or not file.startswith(_PATCHES):
        return None
    return f"live/patches-{arm}-{dispatch}/{file.removeprefix(_PATCHES)}"


def _whole(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and all(isinstance(entry.get(k), str) for k in ("trial_id", "file", "sha256"))
        and entry.get("truncated") is False
        and entry.get("error") is None
    )


def _gap(row: Mapping[str, object], gains: Mapping[str, object]) -> str | None:
    """Why ``row`` lacks what (b) needs, or ``None``."""
    fallback = row.get("fallback_trial_id")
    if isinstance(fallback, str):
        return f"delivered by the fallback ({fallback[:8]}): today's greedy set is not recorded"
    gap = _keeps_gap(row, gains)
    if gap is not None:
        return gap
    entries = row.get("kept_diffs")
    assert isinstance(entries, list)  # _keeps_gap read it
    trials = [str(e["trial_id"]) for e in entries]
    patch = row.get("delivered_patch")
    applied = patch.get("applied_trial_ids") if isinstance(patch, dict) else None
    if not isinstance(applied, list) or not applied:
        return "no delivered patch with its applied trials"
    if not set(applied) <= set(trials) or len(set(applied)) != len(applied):
        return "the delivered patch applied a trial that is not a keep"
    return None


def _keeps_gap(row: Mapping[str, object], gains: Mapping[str, object]) -> str | None:
    """Why ``row``'s keeps are not each written whole with a recorded gain."""
    kept, entries = row.get("kept"), row.get("kept_diffs")
    if not isinstance(entries, list) or len(entries) != kept:
        return "kept_diffs does not hold one entry per keep"
    if not all(_whole(e) for e in entries):
        return "a kept diff was not written whole"
    for e in entries:
        gain = gains.get(str(e.get("hypothesis_id")))
        if isinstance(gain, bool) or not isinstance(gain, int | float):
            return f"no recorded gain for keep {str(e['trial_id'])[:8]}"
    return None


def greedy_basis(row: Mapping[str, object], applied: Sequence[str],
                 keeps: Sequence[Keep]) -> tuple[str, str]:  # fmt: skip
    """Whether the delivered set is provably today's greedy merge, and why.

    A fallback delivers one change: the best single by recorded gain, or the
    second best when the failed greedy set was the best alone
    (``combine_node._fallback_candidate``'s key: gain, then hypothesis id).
    So a delivery is proven greedy when every keep applied, its row records
    that no fallback ran, it holds more than one change, or its one change
    is neither of the two best singles. Otherwise it is not provable (the
    measurer still refuses a left-out keep that merges cleanly)."""
    if len(applied) == len(keeps):
        return PROVEN, ALL_APPLIED
    if "fallback_trial_id" in row and row["fallback_trial_id"] is None:
        return PROVEN, BY_ROW
    if len(applied) > 1:
        return PROVEN, SEVERAL
    ranked = sorted(keeps, key=lambda k: (-k.gain, k.hypothesis_id))
    if applied[0] not in {k.trial_id for k in ranked[:2]}:
        return PROVEN, NOT_FALLBACK
    return NOT_PROVABLE, ONE_OF_TWO


def _keeps(arm: str, dispatch: str, row: Mapping[str, object],
           gains: Mapping[str, object]) -> tuple[Keep, ...]:  # fmt: skip
    """Every keep of a row ``_keeps_gap`` passed, in the row's order."""
    entries = list(row["kept_diffs"])  # type: ignore[call-overload]
    return tuple(
        Keep(
            str(e["trial_id"]),
            str(e.get("hypothesis_id")),
            float(gains[str(e.get("hypothesis_id"))]) / 100,  # type: ignore[arg-type]
            _declared(arm, dispatch, e["file"]) or "",
        )  # fmt: skip
        for e in entries
    )


def _archived(row: Mapping[str, object]) -> tuple[float | None, float | None]:
    """The row's own gain and floor (percent), or ``None``."""
    gain, floor = row.get("gain_pct"), row.get("floor_pct")
    return (float(gain) if isinstance(gain, int | float) else None,
            float(floor) if isinstance(floor, int | float) else None)  # fmt: skip


def _run(arm: str, dispatch: str, row: Mapping[str, object],
         gains: Mapping[str, object]) -> OrderRun:  # fmt: skip
    library = str(row["repo"])
    patch = row["delivered_patch"]
    assert isinstance(patch, dict)
    case = ReplayCase(f"{arm}-{dispatch}-{library}", arm, dispatch, library,
                      str(row.get("base_commit")), DELIVERED,
                      _declared(arm, dispatch, patch.get("file")), None, False)  # fmt: skip
    keeps = _keeps(arm, dispatch, row, gains)
    applied = tuple(map(str, patch["applied_trial_ids"]))
    return OrderRun(case, applied, keeps, *_archived(row),
                    *greedy_basis(row, applied, keeps))  # fmt: skip


def _gains(rows: Sequence[Mapping[str, object]], repo: object) -> dict[str, object]:
    """Each hypothesis row's recorded gain (percent) of ``repo``."""
    return {str(h.get("hypothesis_id")): h.get("gain_pct") for h in rows
            if h.get("experiment") == "ideas-x2-hypothesis" and h.get("repo") == repo}  # fmt: skip


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def census(archive: Path = ARCHIVE) -> tuple[tuple[OrderRun, ...], tuple[Skipped, ...]]:
    """Every held combine with two or more keeps, and every row left out."""
    runs: list[OrderRun] = []
    skipped: list[Skipped] = []
    for path in sorted((archive / "live").glob("ideas-x2-*.jsonl")):
        found = _FILE.fullmatch(path.name)
        if found is None:
            raise IntegrityError(f"{path.name}: not an ideas-x2 run file name")
        arm, dispatch = found.groups()
        rows = _rows(path)
        for row in (r for r in rows if r.get("experiment") == "ideas-x2-run"):
            name = f"{arm}-{dispatch}-{row.get('repo')}"
            kept = row.get("kept")
            where = (str(row.get("repo")), kept if isinstance(kept, int) else 0)
            gains = _gains(rows, row.get("repo"))
            gap = _gap(row, gains)
            if arm in OUT_OF_SCOPE:
                skipped.append(Skipped(name, OUT_OF_SCOPE[arm], False, *where))
            elif where[1] < 2:  # before the hold: no keeps, no combine to fail
                skipped.append(Skipped(name, FEW_KEEPS, False, *where))
            elif row.get("holds") is not True:
                skipped.append(Skipped(name, NOT_HELD, False, *where))
            elif gap is not None:
                skipped.append(Skipped(name, gap, True, *where))
            else:
                runs.append(_run(arm, dispatch, row, gains))
    return tuple(runs), tuple(skipped)


def b_census(archive: Path = ARCHIVE,
             cases: Sequence[BCase] = B_CASES) -> tuple[OrderRun, ...]:  # fmt: skip
    """Each (b)-only case's run row, every keep written whole with its
    recorded gain (``IntegrityError`` otherwise; no delivered patch read)."""
    runs: list[OrderRun] = []
    for c in cases:
        path = archive / "live" / f"ideas-x2-{c.arm}-{c.dispatch}.jsonl"
        if not path.is_file():
            raise IntegrityError(f"{c.id}: no run file {path.name} in the archive")
        rows = _rows(path)
        found = [r for r in rows if r.get("experiment") == "ideas-x2-run"
                 and r.get("repo") == c.library]  # fmt: skip
        if len(found) != 1:
            raise IntegrityError(
                f"{c.id}: {len(found)} run rows for {c.library}, not 1"
            )
        (row,) = found
        gains = _gains(rows, c.library)
        gap = _keeps_gap(row, gains) or (None if row.get("kept") else "no keeps")
        if gap is not None:
            raise IntegrityError(f"{c.id}: {gap}")
        case = ReplayCase(c.id, c.arm, c.dispatch, c.library, str(row.get("base_commit")),
                          NO_TIP, None, None, False)  # fmt: skip
        runs.append(OrderRun(case, (), _keeps(c.arm, c.dispatch, row, gains),
                             *_archived(row), None, None, SIDES_B, c.why))  # fmt: skip
    return tuple(runs)


RUNS, SKIPPED = census()
B_RUNS: Final = b_census()


@dataclass(frozen=True)
class Loaded:
    """A run whose every file passed integrity: the delivered patch, then
    each keep with its diff."""

    run: OrderRun
    delivered: Path
    diffs: tuple[tuple[Keep, Path], ...]


def keep_case(run: OrderRun, keep: Keep) -> ReplayCase:
    """A keep's diff checked the way the fallback's single change is: its
    ``kept_diffs`` entry."""
    c = run.case
    return ReplayCase(f"{c.id}-{keep.trial_id[:8]}", c.arm, c.dispatch, c.library,
                      c.base_commit, FALLBACK, keep.patch or None, keep.trial_id, False)  # fmt: skip


@dataclass(frozen=True)
class LoadedB:
    """A (b)-only run whose run row and every kept diff passed integrity."""

    run: OrderRun
    diffs: tuple[tuple[Keep, Path], ...]


def load_run(run: OrderRun, archive: Path = ARCHIVE) -> Loaded:
    """Every file of ``run`` through ``load_archived`` (``IntegrityError``)."""
    delivered = load_archived(run.case, archive).patch
    assert delivered is not None  # a delivered case always has its patch
    return Loaded(run, delivered, _diffs(run, archive))


def load_b_run(run: OrderRun, archive: Path = ARCHIVE) -> LoadedB:
    """A (b)-only run: its row (one a library, its arm, dispatch and base)
    and every kept diff through ``load_archived`` (``IntegrityError``)."""
    load_archived(run.case, archive)
    return LoadedB(run, _diffs(run, archive))


def _diffs(run: OrderRun, archive: Path) -> tuple[tuple[Keep, Path], ...]:
    """Each keep's diff, checked as the fallback's single change is."""
    diffs: list[tuple[Keep, Path]] = []
    for keep in run.keeps:
        found = load_archived(keep_case(run, keep), archive)
        if found.hypothesis_id != keep.hypothesis_id or found.patch is None:
            raise IntegrityError(
                f"{run.id}: keep {keep.trial_id[:8]}'s entry names another hypothesis"
            )
        diffs.append((keep, found.patch))
    return tuple(diffs)


# ---------------------------------------------------------------------------
# Batches, the minutes and the need
# ---------------------------------------------------------------------------


def exclusion_line(libraries: Sequence[str], measured: int, not_greedy: Sequence[str],
                   planned: int | None = None) -> str:  # fmt: skip
    """F2's line: the measured runs as part of every held or failed run with
    two or more keeps of ``libraries`` (X2-SV aside), and the runs left out
    because today's set failed its re-test: ``not_greedy`` (the fallback
    delivered) and the census's failed combines (nothing delivered)."""
    failed = [s.id for s in SKIPPED if s.library in libraries and s.reason == NOT_HELD
              and s.keeps >= 2]  # fmt: skip
    count = sum(r.library in libraries for r in RUNS) if planned is None else planned
    head = (f"{measured} measured of {count + len(failed)} held-or-failed runs with two"
            " or more keeps (X2-SV aside);")  # fmt: skip
    gone = [*(f"{i}, fallback delivered" for i in not_greedy),
            *(f"{i}, nothing delivered" for i in failed)]  # fmt: skip
    if not gone:
        return f"{head} none excluded."
    return (f"{head} {len(gone)} excluded because today's set failed its re-test"
            f" ({'; '.join(gone)}). The gain-ordered choice cannot be measured on them;"
            " the exclusion does not favour it.")  # fmt: skip


def batch(environ: Mapping[str, str], runs: Sequence[OrderRun] = RUNS,
          b_runs: Sequence[OrderRun] = B_RUNS) -> tuple[str, ...]:  # fmt: skip
    """``$LIVE_ORDER_BATCH``'s libraries (``1`` when unset), each with runs;
    ``b``: the libraries of the (b)-only cases."""
    name = environ.get(BATCH_ENV, "1")
    if name == B_BATCH:
        return tuple(sorted({r.library for r in b_runs}))
    if name not in BATCHES:
        raise ValueError(
            f"{BATCH_ENV} must be one of {', '.join(BATCHES)} or {B_BATCH}, got {name!r}"
        )
    present = {r.library for r in runs}
    return tuple(lib for lib in BATCHES[name] if lib in present)


def sides(environ: Mapping[str, str]) -> str:
    """What ``$LIVE_ORDER_BATCH`` measures: (b) alone for ``b``, else both."""
    return SIDES_B if environ.get(BATCH_ENV) == B_BATCH else SIDES_AB


def cases(library: str, kind: str) -> tuple[OrderRun, ...]:
    """``library``'s cases of one kind: the 59 held combines (``SIDES_AB``)
    or the (b)-only three (``SIDES_B``), never both."""
    if kind not in (SIDES_AB, SIDES_B):
        raise ValueError(f"sides must be {SIDES_AB} or {SIDES_B}, got {kind!r}")
    return tuple(
        r for r in (B_RUNS if kind == SIDES_B else RUNS) if r.library == library
    )


def run_looks(run: OrderRun) -> int:
    """Looks a run may take: four of two tips, each with its fallback, and
    every keep as a single when (a) left one out, else two of one tip with
    theirs (an upper bound). (b) alone: two of its tip with theirs, and
    every keep as a single when it has two or more."""
    if run.sides == SIDES_B:
        return 2 * 2 + (len(run.keeps) if len(run.keeps) > 1 else 0)
    return 2 * 4 + len(run.keeps) if run.left_out else 2 * 2


def library_seconds(library: str, runs: Sequence[OrderRun] = RUNS) -> float:
    looks = sum(run_looks(r) for r in runs if r.library == library)
    return CLONE_S + BASELINE_S[library] + LOOK_S[library] * (1 + looks)  # + preflight


def plan_minutes(libraries: Sequence[str], runs: Sequence[OrderRun] = RUNS) -> int:
    return math.ceil(math.fsum(library_seconds(lib, runs) for lib in libraries) / 60)


def order_need() -> float:
    """What a combine-order dispatch asks the ledger for: nothing."""
    return ORDER_RUN_CAP_USD
