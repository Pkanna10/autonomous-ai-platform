"""The combine-order replay (O65 item 2): the ``combine-order`` suite.

The owner asked, before X2-DT is dispatched, how today's conflict choice
compares with the existing measured-gain choice, on new measurements of
archived diffs and with no API spend. **(b) orders on each keep's first
look's gain** (``b_order_basis``): the archive holds no ``confirmed_gain``,
so (b)'s order is noisier than the engine's mean-of-two order
(``order_gain``).

- **(a)** today's choice: the greedy merge in score order. Its set is the
  archived delivered patch's, rebuilt as the combine node merged it
  (``GitCombiner._merge`` of the delivered trials in their order); a run
  whose rebuilt tip is not the delivered patch's tree is refused. A delivery
  that was the fallback's is not today's greedy set, which no row records:
  a run whose row names its fallback (``order_cases``), or whose left-out
  keep merges cleanly onto (a)'s tip (``NotGreedyError``), is listed as a
  data gap and not measured, never guessed.
- **(b)** ``SITE_STACKS="on"``: ``plan_delivery(by_gain=True)`` on every keep,
  with the conflicts of ``GitCombiner.dry_merge`` and the recorded gains,
  then the same greedy merge of the plan's order.

**Delivered gain, both choices alike** (``order_readings``): each look is the
combine node's re-test of the choice's set (``EngineMeasurer.retest_set``,
``combine_node._retest``); when it measured and did not hold, the node's
fallback (``_fallback_candidate``: the best single by recorded gain, never
the failed set) is re-tested alone through the same path (``retest_one``).
A look delivers the set's gain if it held, else the fallback's if that
held, else 0; the set's raw gain, its hold, its outcome and the fallback are
recorded beside it. The preference reads delivered gain.

It is a sibling suite, not a mode of ``combine-replay``: its cases are every
held combine (``order_cases.RUNS``), not five rows; it measures per library
(one clone and one calibration, then every run of that library), records per
run and per conflicting pair, and needs its own batches
(``order_cases.BATCHES``). The archive checks (``replay_archive``) and the
engine measurer with its settings pinning and timing (``replay_engine``) are
shared, split out of ``combine_replay`` for both.

**Per library** (``measure_library``): every run's files through integrity,
then the clone (its base the archived one), every delivered patch and kept
diff committed beside it, the engine's connect and define, and one baseline
with its calibration. **Per run** (``measure_run``): (a)'s and (b)'s sets;
when the two tips are one tree, two looks of the one tip, else four, a, b,
b, a, each with its fallback when needed; then one look (``retest_one``) per
keep of a conflicting pair, alone, so each pair has a stronger side on the
same runner, past the singles' floors or not.

**Records** (``$LIVE_RESULTS_PATH``, never asserted): a ``run`` row per run,
a ``skipped`` row per data gap, a ``library`` row, then the tables
(``order_readings`` names every field). A look counts only if it applied
its choice's whole set and left its rows (and its fallback did, when one
ran); a run is complete when every look and single did.

**Failures:** an integrity mismatch before the clone, a crash or a guard
breach writes an ``error`` row and raises. A run whose rebuilt (a) is not the
delivered patch is an ``error`` row, and the library goes on. An
``EngineError`` stop is recorded. A library with any planned run neither
complete nor skipped fails its case after every run and row.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast

from e2e.conftest import Isolation

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.execution.combine import GitCombiner
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.protocols import KeptChange
from autonomous_ai_agents.orchestrator.combine_node import (
    DeliveryPlan,
    _fallback_candidate,
    plan_delivery,
)

from .conftest import LiveRun
from .discovery_io import ResultsSink, cells, flag, write_markdown
from .ideas_x2 import LIBRARIES
from .order_cases import (
    NOT_PROVABLE,
    ORDER_EXPERIMENT,
    RUNS,
    SKIPPED,
    Loaded,
    OrderRun,
    Skipped,
    exclusion_line,
    load_run,
)
from .order_readings import (
    LOOK_PLAN,
    SAME_PLAN,
    LibraryResult,
    Pair,
    RunResult,
    SingleLook,
    TipLook,
    _pct,
)
from .oss import PRODUCTION, GitPolicy
from .replay_archive import ARCHIVE, IntegrityError, _fit
from .replay_engine import BaselineLook, EngineMeasurer, RetestLook

DELIVERED_KEY: Final = "delivered"
BASIS_LINE: Final = (
    "(b) orders on each keep's first look's gain (the archive holds no"
    " confirmed_gain), noisier than the engine's mean-of-two order."
)


class NotGreedyError(Exception):
    """The delivered set is not today's greedy merge (the fallback delivered
    it): the score-order greedy set is not recorded, so the run is a data gap."""


@dataclass(frozen=True)
class Merged:
    """A greedy merge, objects only: its tip commit and the trials applied."""

    tip: str
    applied: tuple[str, ...]


class OrderMeasurer(Protocol):
    """The seam: the engine (``EngineOrderMeasurer``) or a test's fake."""

    def prepare(self) -> str: ...
    def commit_tip(self, patch: Path, label: str) -> str: ...
    def connect(self) -> None: ...
    def baseline(self) -> BaselineLook: ...
    def plan(self, changes: Sequence[KeptChange], gains: Mapping[str, float | None]) -> DeliveryPlan: ...  # fmt: skip
    def merged(self, changes: Sequence[KeptChange]) -> Merged: ...
    def same_tree(self, left: str, right: str) -> bool: ...
    def retest(self, look: str, change: KeptChange) -> RetestLook: ...
    def retest_set(self, look: str, changes: Sequence[KeptChange]) -> RetestLook: ...
    def check_guards(self, run: LiveRun) -> None: ...


class EngineOrderMeasurer(EngineMeasurer):
    """``EngineMeasurer`` plus what the combine node does before its
    re-test with ``SITE_STACKS="on"`` (``nodes._combine_set``): the dry
    merge, ``plan_delivery`` by gain, and the greedy merge itself."""

    def _parts(self) -> tuple[str, GitCombiner, GitWorkspace]:
        state, ctx = self._ready()
        git = GitWorkspace(self.user.path, executable=settings.GIT_EXECUTABLE,
                           timeout_s=settings.GIT_TIMEOUT_S)  # fmt: skip
        return str(state["base_commit"]), cast(GitCombiner, ctx.combiner), git

    def plan(self, changes: Sequence[KeptChange], gains: Mapping[str, float | None]) -> DeliveryPlan:  # fmt: skip
        base, combiner, _ = self._parts()
        state, _ = self._ready()
        dry = combiner.dry_merge(state["project"], base, changes)
        return plan_delivery(changes, gains, dry, by_gain=True)

    def merged(self, changes: Sequence[KeptChange]) -> Merged:
        """``GitCombiner._merge``: the combine's own greedy merge, objects only."""
        base, combiner, git = self._parts()
        tip, applied, _ = combiner._merge(git, base, changes)
        return Merged(tip, tuple(applied))

    def same_tree(self, left: str, right: str) -> bool:
        _, _, git = self._parts()
        return git.diff_commits(left, right) == ""


# ---------------------------------------------------------------------------
# One run, one library
# ---------------------------------------------------------------------------


def _kept(applied: Sequence[str], pair: tuple[str, str]) -> tuple[str, ...]:
    return tuple(t for t in pair if t in applied)


def _greedy(run: OrderRun, measurer: OrderMeasurer,
            changes: Mapping[str, KeptChange]) -> None:  # fmt: skip
    """``NotGreedyError`` when a left-out keep merges cleanly onto (a)'s tip:
    today's greedy merge would have applied it, so the delivery was the
    fallback's (``nothing left to apply`` is a skip, so it stays out)."""
    offer = [changes[t] for t in run.applied]
    for keep in (k for k in run.keeps if k.trial_id not in run.applied):
        if keep.trial_id in measurer.merged([*offer, changes[keep.trial_id]]).applied:
            raise NotGreedyError(
                f"{run.id}: left-out keep {keep.trial_id[:8]} merges cleanly onto (a)'s"
                " tip, so the delivery was the fallback; today's greedy set is not"
                " recorded"
            )


def _look(index: int, name: str, measurer: OrderMeasurer, offered: Sequence[KeptChange],
          applied: tuple[str, ...], pool: Sequence[KeptChange],
          clock: Callable[[], float]) -> TipLook:  # fmt: skip
    """One re-test of a choice's set; when it did not hold (a re-test with no
    rows did not hold, as ``combine_kept`` treats it), the combine node's
    fallback (``_fallback_candidate`` over ``pool``, never the failed set)
    re-tested alone through the same path."""
    at = clock()
    measured = measurer.retest_set(f"r{index}-{name}", offered)
    found = TipLook(name, len(applied), measured, clock() - at)
    if not found.merged or (found.measured_tip and found.measured.holds):
        return found  # held, or not applied whole (no fallback to read)
    candidate = _fallback_candidate(pool, applied)
    if candidate is None:
        return found
    at = clock()
    single = measurer.retest(f"r{index}-{name}-f", candidate)
    return TipLook(name, found.expected, found.measured, found.seconds,
                   candidate.trial_id, single, clock() - at)  # fmt: skip


def measure_run(index: int, loaded: Loaded, measurer: OrderMeasurer,
                commits: Mapping[str, str], clock: Callable[[], float]) -> RunResult:  # fmt: skip
    """(a) rebuilt and checked, (b) planned, the looks a, b, b, a with each
    failed set's fallback, then the singles."""
    run, started = loaded.run, clock()
    found = RunResult(run)
    changes = {k.trial_id: KeptChange(k.trial_id, k.hypothesis_id, "replay",
                                      commits[k.trial_id], 0.0, k.gain)
               for k in run.keeps}  # fmt: skip
    offer_a = [changes[t] for t in run.applied]
    a = measurer.merged(offer_a)
    if a.applied != run.applied:
        raise IntegrityError(f"{run.id}: (a) rebuilt from its applied trials applied"
                             f" {len(a.applied)} of {len(run.applied)}")  # fmt: skip
    if not measurer.same_tree(a.tip, commits[DELIVERED_KEY]):
        raise IntegrityError(
            f"{run.id}: (a)'s rebuilt tip is not the delivered patch's tree"
        )
    _greedy(run, measurer, changes)
    gains: dict[str, float | None] = {k.trial_id: k.gain for k in run.keeps}
    plan = measurer.plan(list(changes.values()), gains)
    b = measurer.merged(plan.order)
    found.a_applied, found.b_applied = a.applied, b.applied
    found.same = measurer.same_tree(a.tip, b.tip)
    found.duplicates = len(plan.duplicate_of)
    found.conflicts = sorted((x, y) for x, y in (sorted(p) for p in plan.conflicts))
    found.plan_s = clock() - started
    # (a)'s fallback draws on every keep, as the node's does on all it was
    # offered; (b)'s on its plan, which is every keep in gain order
    choices = {"a": (offer_a, a.applied, list(changes.values())),
               "b": (list(plan.order), b.applied, list(plan.order))}  # fmt: skip
    try:
        for name in SAME_PLAN if found.same else LOOK_PLAN:
            offered, applied, pool = choices[name[0]]
            found.looks.append(
                _look(index, name, measurer, offered, applied, pool, clock)
            )
        for trial in sorted({t for pair in found.conflicts for t in pair}):
            at = clock()
            single = measurer.retest(f"r{index}-s-{trial[:8]}", changes[trial])
            found.singles[trial] = SingleLook(single, clock() - at)
    except EngineError as exc:  # where the engine would stop
        found.stopped = _fit(str(exc))
    for x, y in found.conflicts:
        sx, sy = found.singles.get(x), found.singles.get(y)
        found.pairs.append(Pair(
            x, y, _kept(a.applied, (x, y)), _kept(b.applied, (x, y)),
            (None if sx is None else sx.gain, None if sy is None else sy.gain),
            (None if sx is None else sx.floor, None if sy is None else sy.floor),
        ))  # fmt: skip
    found.wall_s = clock() - started
    return found


def measure_library(library: str, runs: Sequence[OrderRun], measurer: OrderMeasurer,
                    recorder: OrderRecorder, live: LiveRun, *, archive: Path = ARCHIVE,
                    clock: Callable[[], float] = time.monotonic) -> LibraryResult:  # fmt: skip
    """Integrity, the clone and every tip, one calibration, every run; the
    guards; the library fails after its rows if any run is not complete."""
    started = clock()
    found = LibraryResult(library, ids=tuple(r.id for r in runs))
    try:
        loaded = [load_run(r, archive) for r in runs]
        base = measurer.prepare()
        if any(r.case.base_commit != base for r in runs):
            raise IntegrityError(
                f"{library}: the repository's base {base} is not the archived"
            )
        commits: dict[str, dict[str, str]] = {}
        for item in loaded:
            run = item.run
            tips = {DELIVERED_KEY: measurer.commit_tip(item.delivered, f"{run.id}-d")}
            for keep, path in item.diffs:
                tips[keep.trial_id] = measurer.commit_tip(
                    path, f"{run.id}-{keep.trial_id[:8]}"
                )
            commits[run.id] = tips
        found.setup_s = clock() - started
        try:
            at = clock()
            measurer.connect()
            found.connect_s = clock() - at
            at = clock()
            found.baseline = measurer.baseline()
            found.baseline_s = clock() - at
        except EngineError as exc:
            found.stopped = _fit(str(exc))
        for index, item in enumerate(loaded if found.stopped is None else ()):
            try:
                result = measure_run(index, item, measurer, commits[item.run.id], clock)
            except IntegrityError as exc:
                found.errors.append(item.run.id)
                recorder.record_error(item.run.id, live, f"{type(exc).__name__}: {exc}")
                continue
            except NotGreedyError as exc:
                found.skipped.append(item.run.id)
                recorder.record_skip(item.run.id, live, str(exc))
                continue
            found.runs.append(result)
            recorder.record_run(result, live)
        found.wall_s = clock() - started
    except BaseException as exc:
        recorder.record_error(library, live, f"{type(exc).__name__}: {exc}")
        raise
    try:
        measurer.check_guards(live)
    except BaseException as exc:
        recorder.record_error(library, live, f"guards: {exc}", found.row())
        raise
    recorder.record_library(found, live)
    if not found.complete:
        missing = ", ".join(found.incomplete) or "every run (the library stopped)"
        raise AssertionError(f"{library}: not every run measured: {missing}")
    return found


# ---------------------------------------------------------------------------
# The recorder
# ---------------------------------------------------------------------------


def _f(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _cell(look: TipLook) -> str:
    """A look's delivered gain, marked when the fallback or nothing delivered."""
    if look.delivered is None:
        return "not measured"
    if look.measured_tip and look.measured.holds:
        return _f(_pct(look.delivered))
    notes = ["no rows"] if look.no_rows else []
    fb = look.fallback_look
    if fb is not None and fb.rows and fb.holds:
        notes.append(f"fallback {str(look.fallback)[:8]}")
    elif look.fallback_no_rows:
        notes.append("fallback no rows")
    elif not notes:
        notes.append("did not hold")
    return f"{_f(_pct(look.delivered))} ({'; '.join(notes)})"


def _gains(result: RunResult, side: str) -> str:
    return ", ".join(_cell(x) for x in result.looks if x.side == side) or "-"


RUN_HEAD: Final = (
    "| run | keeps | (a) applied | (b) applied | same | (a) delivered | (b) delivered "
    "| prefers | conflicting pairs | (a) stronger (past floor) "
    "| (b) stronger (past floor) | archived gain | complete |"
)
PAIR_HEAD: Final = (
    "| run | pair | (a) kept | (b) kept | single gains | single floors | stronger "
    "| past the floor |"
)
LIBRARY_HEAD: Final = (
    "| library | runs | errors | baseline floor | clone and tips | preflight "
    "| baseline | calibration | case | stopped |"
)


def _head(text: str) -> list[str]:
    return [text, "|" + " --- |" * (text.count("|") - 1)]


class OrderRecorder:
    """Rows to the sink as they come, a note per library, the tables."""

    def __init__(self, sink: ResultsSink) -> None:
        self.sink = sink
        self.runs: list[RunResult] = []
        self.libraries: list[LibraryResult] = []
        self.errors: list[tuple[str, str]] = []
        self.skipped: list[tuple[str, str]] = []

    def record_skip(self, name: str, live: LiveRun, reason: str) -> None:
        """A run that is not today's greedy merge: listed as a data gap."""
        self.skipped.append((name, _fit(reason)))
        self.sink.write({"experiment": ORDER_EXPERIMENT, "kind": "skipped", "id": name,
                         "reason": _fit(reason)})  # fmt: skip
        live.note(_fit(f"ORDER {name}: skipped, {reason}"))

    def record_run(self, result: RunResult, live: LiveRun) -> None:
        self.runs.append(result)
        self.sink.write(result.row())

    def record_library(self, result: LibraryResult, live: LiveRun) -> None:
        self.libraries.append(result)
        self.sink.write(result.row())
        live.note(_fit(f"ORDER {result.library}: {len(result.runs)} of {result.planned}"
                       f" runs, complete {flag(result.complete)}"))  # fmt: skip

    def record_error(self, name: str, live: LiveRun, error: str,
                     measured: Mapping[str, object] | None = None) -> None:  # fmt: skip
        self.errors.append((name, _fit(error)))
        row: dict[str, object] = {"experiment": ORDER_EXPERIMENT, "kind": "error",
                                  "id": name, "error": _fit(error)}  # fmt: skip
        if measured is not None:
            row["measured"] = dict(measured)
        self.sink.write(row)
        live.note(_fit(f"ORDER {name}: error {error}"))

    def markdown(self) -> str:
        width = RUN_HEAD.count("|") - 1
        lines = ["## Combine order replay (O65 item 2: score order (a) against gain order (b))",
                 "", BASIS_LINE, "", *_head(RUN_HEAD)]  # fmt: skip
        for r in self.runs:
            a, b = r.counts("a"), r.counts("b")
            pa, pb = r.counts("a", past=True), r.counts("b", past=True)
            clear = (
                ""
                if r.clear is None
                else (" (clear)" if r.clear else " (inside the floor)")
            )
            lines.append(cells([
                r.run.id, len(r.run.keeps), len(r.a_applied), len(r.b_applied), flag(r.same),
                _gains(r, "a"), _gains(r, "b"), f"{r.prefers or '-'}{clear}", len(r.pairs),
                f"{a[0]} of {a[1]} ({pa[0]} of {pa[1]})",
                f"{b[0]} of {b[1]} ({pb[0]} of {pb[1]})", _f(r.run.archived_gain_pct),
                flag(r.complete),
            ]))  # fmt: skip
        for name, error in self.errors:
            lines.append(cells([name, "error", error, *("-",) * (width - 3)]))
        for name, reason in self.skipped:
            lines.append(cells([name, "skipped", reason, *("-",) * (width - 3)]))
        for gone in self._excluded():
            lines.append(
                cells([gone.id, "excluded", gone.reason, *("-",) * (width - 3)])
            )
        lost = [r.run.id for r in self.runs if not r.complete]
        flagged = [r.run.id for r in self.runs if r.run.greedy == NOT_PROVABLE]
        lines += ["", self._totals(), "", self._exclusion(),
                  f"Not counted (a look or single lost): {', '.join(lost) or 'none'}",
                  f"Greedy not provable (measured, flagged): {', '.join(flagged) or 'none'}",
                  "", *_head(PAIR_HEAD)]  # fmt: skip
        for r in self.runs:
            for p in r.pairs:
                lines.append(cells([
                    r.run.id, f"{p.first[:8]} / {p.second[:8]}",
                    ", ".join(t[:8] for t in p.a_kept) or "-",
                    ", ".join(t[:8] for t in p.b_kept) or "-",
                    " / ".join(_f(_pct(g)) if g is not None else "not measured" for g in p.gains),
                    " / ".join(_f(_pct(f)) for f in p.floors),
                    "-" if p.higher is None else p.higher[:8], flag(p.decided),
                ]))  # fmt: skip
        lines += ["", "Wall time (s):", "", *_head(LIBRARY_HEAD)]
        for x in self.libraries:
            base = x.baseline
            lines.append(cells([
                x.library, f"{len(x.runs)} of {x.planned}", len(x.errors),
                _f(_pct(None if base is None else base.floor), 2), _f(x.setup_s),
                _f(x.connect_s), _f(x.baseline_s),
                _f(None if base is None else base.calibration_s), _f(x.wall_s),
                x.stopped or "-",
            ]))  # fmt: skip
        return "\n".join(lines)

    def _totals(self) -> str:
        """The run counts, the preferences clear and inside the floor, and
        how often each choice kept the stronger single (past the floor)."""

        counted = [r for r in self.runs if r.complete]  # F4: complete runs only

        def pick(side: str, *, past: bool) -> str:
            counts = [r.counts(side, past=past) for r in counted]
            return f"{sum(x for x, _ in counts)} of {sum(n for _, n in counts)}"

        def prefer(side: str) -> str:
            chosen = [r for r in counted if r.prefers == side]
            return (
                f"{side} {len(chosen)} ({sum(r.clear is True for r in chosen)} clear)"
            )

        prefers = [r.prefers for r in counted]
        return (
            f"{len(counted)} run(s) counted, {len(self.runs) - len(counted)} not counted"
            f" (incomplete), {len(self.skipped)} skipped,"
            f" {len(self.errors)} error(s); prefers {prefer('a')}, {prefer('b')}, same"
            f" {prefers.count('same')}, tie {prefers.count('tie')}; (a) picked the"
            f" stronger single {pick('a', past=False)} ({pick('a', past=True)} past the"
            f" floor), (b) {pick('b', past=False)} ({pick('b', past=True)} past the floor)"
        )

    def _excluded(self) -> list[Skipped]:
        """The census's left-out rows of the libraries recorded (F2)."""
        names = {x.library for x in self.libraries}
        return [s for s in SKIPPED if s.library in names]

    def _exclusion(self) -> str:
        return exclusion_line(
            [x.library for x in self.libraries],
            sum(r.complete for r in self.runs),
            [name for name, _ in self.skipped],
            planned=sum(x.planned for x in self.libraries),
        )

    def finish(self, echo: Callable[[str], None]) -> None:
        """The census's exclusions to the sink, then the tables."""
        for x in self._excluded():
            self.sink.write({"experiment": ORDER_EXPERIMENT, "kind": "excluded",
                             "id": x.id, "library": x.library, "reason": x.reason,
                             "data": x.data, "keeps": x.keeps})  # fmt: skip
        write_markdown("Combine order", self.markdown(), self.sink.environ, echo)


def order_live(library: str, live: LiveRun, root: Path, isolation: Isolation,
               recorder: OrderRecorder, *, policy: GitPolicy = PRODUCTION) -> LibraryResult:  # fmt: skip
    """One library on the engine measurer: its runs, its own directory."""
    measurer = EngineOrderMeasurer(LIBRARIES[library], root / library, isolation,
                                   run_id=f"order-{library}", policy=policy)  # fmt: skip
    runs = [r for r in RUNS if r.library == library]
    return measure_library(library, runs, measurer, recorder, live)
