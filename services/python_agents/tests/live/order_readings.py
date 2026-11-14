"""What the combine-order replay reads from its looks (O65 item 2).

**Delivered gain, as the engine would deliver it** (``TipLook.delivered``):
a choice's set re-tested through the combine node's path delivers its own
gain when the re-test holds; when it does not, the node re-tests the single
best change (``combine_node._fallback_candidate``) alone, which delivers its
gain when that holds; else nothing is delivered, 0. A re-test that left no
rows (a RunFailure) did not hold, as ``combine_kept`` treats it: the set
falls back, a fallback delivers 0 (``no_rows``, ``fallback_no_rows``). The raw gain of the set
is kept beside it (``set_gain``), never mixed in. Each look records whether
the set held, its outcome and the fallback.

**The preference** (``RunResult.prefers``) is the mean delivered gain of each
choice's looks; it is ``clear`` when the difference exceeds the largest
floor among the looks that delivered (``look_floor``), else inside it.

**A conflicting pair** (``Pair``) has a stronger side when its singles'
re-measured gains differ (``higher``), and a stronger side past the floor
when they differ by more than the larger of the two singles' floors
(``decided``). Both counts are reported: which choice kept the stronger side
(``a_higher``) and which kept it past the floor (``a_beyond``).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Final

from .order_cases import ORDER_BASIS, ORDER_EXPERIMENT, OrderRun
from .replay_engine import BaselineLook, RetestLook

LOOK_PLAN: Final = ("a1", "b1", "b2", "a2")  # two tips, a, b, b, a
SAME_PLAN: Final = ("a1", "a2")  # both choices give one tree: one tip
_TIE: Final = 1e-9


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 4)


@dataclass(frozen=True)
class TipLook:
    """One re-test of a choice's set, and its fallback when the set failed."""

    name: str  # a1, b1, b2, a2
    expected: int  # the trials its choice applies
    measured: RetestLook
    seconds: float
    fallback: str | None = None  # the engine's fallback candidate, if it failed
    fallback_look: RetestLook | None = None
    fallback_s: float | None = None

    @property
    def side(self) -> str:
        return self.name[0]

    @property
    def merged(self) -> bool:
        """The combiner applied the choice's whole set (rows or not)."""
        return self.measured.applied == self.expected

    @property
    def measured_tip(self) -> bool:
        """Applied the choice's whole set and left its rows."""
        return self.merged and self.measured.rows

    @property
    def no_rows(self) -> bool:
        """Applied, but a RunFailure left no rows: did not hold (F1)."""
        return self.merged and not self.measured.rows

    @property
    def set_gain(self) -> float | None:
        """The raw gain of the set, held or not."""
        return self.measured.gain if self.measured_tip else None

    @property
    def _fallback_merged(self) -> bool:
        return self.fallback_look is not None and self.fallback_look.applied == 1

    @property
    def fallback_no_rows(self) -> bool:
        """The fallback applied, but left no rows: it did not hold (F1)."""
        return (
            self._fallback_merged
            and self.fallback_look is not None
            and not self.fallback_look.rows
        )

    @property
    def delivered(self) -> float | None:
        """What the engine would deliver (``combine_kept``): the set's gain if
        its re-test held, else the fallback's if that held, else 0. A
        re-test with no rows did not hold. ``None`` when a set or fallback
        was not applied whole."""
        if not self.merged:
            return None
        if self.measured_tip and self.measured.holds:
            return self.measured.gain
        if self.fallback is None:
            return 0.0
        if self.fallback_look is None or not self._fallback_merged:
            return None
        held = self.fallback_look.rows and self.fallback_look.holds
        return self.fallback_look.gain if held else 0.0

    @property
    def floor(self) -> float | None:
        """The floor of the measurement that delivered (or failed)."""
        fb = self.fallback_look
        if fb is not None and self._fallback_merged and fb.rows:
            return fb.floor
        return self.measured.floor if self.measured_tip else None

    @property
    def complete(self) -> bool:
        return self.delivered is not None


@dataclass(frozen=True)
class SingleLook:
    look: RetestLook
    seconds: float

    @property
    def gain(self) -> float | None:
        return self.look.gain if self.look.measured_tip else None

    @property
    def floor(self) -> float | None:
        return self.look.floor if self.look.measured_tip else None


@dataclass(frozen=True)
class Pair:
    """One conflicting pair: the side each choice kept, the singles' gains
    and floors."""

    first: str
    second: str
    a_kept: tuple[str, ...]
    b_kept: tuple[str, ...]
    gains: tuple[float | None, float | None]
    floors: tuple[float | None, float | None] = (None, None)

    @property
    def higher(self) -> str | None:
        """The side whose single gained more; ``None`` on a tie or a single
        not measured."""
        x, y = self.gains
        if x is None or y is None or x == y:
            return None
        return self.first if x > y else self.second

    @property
    def decided(self) -> bool:
        """The singles differ by more than the larger of their floors."""
        (x, y), (fx, fy) = self.gains, self.floors
        if self.higher is None or x is None or y is None or fx is None or fy is None:
            return False
        return abs(x - y) > max(fx, fy)

    def _picked(self, kept: tuple[str, ...], *, past: bool) -> bool | None:
        if self.higher is None or len(kept) != 1 or (past and not self.decided):
            return None
        return kept[0] == self.higher

    @property
    def a_higher(self) -> bool | None:
        return self._picked(self.a_kept, past=False)

    @property
    def b_higher(self) -> bool | None:
        return self._picked(self.b_kept, past=False)

    @property
    def a_beyond(self) -> bool | None:
        return self._picked(self.a_kept, past=True)

    @property
    def b_beyond(self) -> bool | None:
        return self._picked(self.b_kept, past=True)

    def row(self) -> dict[str, object]:
        return {"first": self.first, "second": self.second, "a_kept": list(self.a_kept),
                "b_kept": list(self.b_kept), "gains_pct": [_pct(g) for g in self.gains],
                "floors_pct": [_pct(f) for f in self.floors], "higher": self.higher,
                "decided": self.decided, "a_higher": self.a_higher,
                "b_higher": self.b_higher, "a_beyond": self.a_beyond,
                "b_beyond": self.b_beyond}  # fmt: skip


@dataclass
class RunResult:
    run: OrderRun
    a_applied: tuple[str, ...] = ()
    b_applied: tuple[str, ...] = ()
    same: bool | None = None  # the two choices' tips are one tree
    duplicates: int = 0
    conflicts: list[tuple[str, str]] = field(default_factory=list)
    looks: list[TipLook] = field(default_factory=list)
    singles: dict[str, SingleLook] = field(default_factory=dict)
    pairs: list[Pair] = field(default_factory=list)
    plan_s: float | None = None
    wall_s: float | None = None
    stopped: str | None = None

    def _side(self, side: str) -> list[TipLook]:
        return [x for x in self.looks if x.side == side]

    def measured(self, side: str) -> list[float]:
        """The delivered gains of ``side``'s looks that measured."""
        return [g for x in self._side(side) if (g := x.delivered) is not None]

    def mean(self, side: str) -> float | None:
        found = self.measured(side)
        return statistics.fmean(found) if found else None

    def raw_mean(self, side: str) -> float | None:
        found = [g for x in self._side(side) if (g := x.set_gain) is not None]
        return statistics.fmean(found) if found else None

    @property
    def look_floor(self) -> float | None:
        floors = [f for x in self.looks if (f := x.floor) is not None]
        return max(floors) if floors else None

    def _diff(self) -> float | None:
        a, b = self.mean("a"), self.mean("b")
        return None if a is None or b is None else b - a

    @property
    def prefers(self) -> str | None:
        """``a`` or ``b`` by mean delivered gain, ``tie``, ``same`` when both
        choices give one tree, ``None`` unmeasured."""
        if self.same:
            return "same"
        diff = self._diff()
        if diff is None:
            return None
        return "tie" if abs(diff) < _TIE else ("b" if diff > 0 else "a")

    @property
    def clear(self) -> bool | None:
        """The preference exceeds the largest floor among the looks."""
        diff, floor = self._diff(), self.look_floor
        if self.prefers not in ("a", "b") or diff is None or floor is None:
            return None
        return abs(diff) > floor

    @property
    def complete(self) -> bool:
        plan = SAME_PLAN if self.same else LOOK_PLAN
        return (
            self.stopped is None and self.same is not None
            and tuple(x.name for x in self.looks) == plan
            and all(x.complete for x in self.looks)
            and all(s.gain is not None for s in self.singles.values())
        )  # fmt: skip

    def counts(self, side: str, *, past: bool = False) -> tuple[int, int]:
        """(pairs where ``side`` kept the stronger single, pairs read); with
        ``past``, only pairs whose singles differ past their floors."""
        picks = [
            (p.a_beyond if side == "a" else p.b_beyond) if past
            else (p.a_higher if side == "a" else p.b_higher)
            for p in self.pairs
        ]  # fmt: skip
        return sum(x is True for x in picks), sum(x is not None for x in picks)

    def row(self) -> dict[str, object]:
        r = self.run
        a, b = self.counts("a"), self.counts("b")
        pa, pb = self.counts("a", past=True), self.counts("b", past=True)
        side: dict[str, object] = {}
        for s in ("a", "b"):
            looks = self._side(s)
            fbs = [x.fallback_look for x in looks]
            side.update({
                f"{s}_gains_pct": [_pct(x.delivered) for x in looks],
                f"{s}_set_gains_pct": [_pct(x.set_gain) for x in looks],
                f"{s}_holds": [x.measured.holds if x.measured_tip else None for x in looks],
                f"{s}_outcomes": [x.measured.outcome for x in looks],
                f"{s}_floors_pct": [_pct(x.floor) for x in looks],
                f"{s}_fallbacks": [x.fallback for x in looks],
                f"{s}_fallback_gains_pct": [None if f is None else _pct(f.gain) for f in fbs],
                f"{s}_fallback_holds": [None if f is None else f.holds for f in fbs],
                f"{s}_no_rows": [x.no_rows for x in looks],
                f"{s}_fallback_no_rows": [x.fallback_no_rows for x in looks],
                f"mean_{s}_pct": _pct(self.mean(s)), f"raw_mean_{s}_pct": _pct(self.raw_mean(s)),
            })  # fmt: skip
        return {
            "experiment": ORDER_EXPERIMENT, "kind": "run", "id": r.id, "arm": r.case.arm,
            "dispatch": r.case.dispatch, "library": r.library, "keeps": len(r.keeps),
            "applied_a": list(self.a_applied), "applied_b": list(self.b_applied),
            "same": self.same, "duplicates": self.duplicates, **side,
            "b_order_basis": ORDER_BASIS, "greedy": r.greedy,
            "greedy_reason": r.greedy_reason,
            "look_floor_pct": _pct(self.look_floor), "prefers": self.prefers,
            "clear": self.clear, "conflicts": [list(p) for p in self.conflicts],
            "pairs": [p.row() for p in self.pairs],
            "a_higher": a[0], "decided_a": a[1], "b_higher": b[0], "decided_b": b[1],
            "a_beyond": pa[0], "beyond_a": pa[1], "b_beyond": pb[0], "beyond_b": pb[1],
            "singles_pct": {t: _pct(s.gain) for t, s in self.singles.items()},
            "singles_floor_pct": {t: _pct(s.floor) for t, s in self.singles.items()},
            "recorded_gains_pct": {k.trial_id: _pct(k.gain) for k in r.keeps},
            "archived_gain_pct": r.archived_gain_pct,
            "archived_floor_pct": r.archived_floor_pct,
            "plan_s": self.plan_s, "look_s": [x.seconds for x in self.looks],
            "fallback_s": [x.fallback_s for x in self.looks],
            "singles_s": {t: s.seconds for t, s in self.singles.items()},
            "wall_s": self.wall_s, "stopped": self.stopped, "complete": self.complete,
        }  # fmt: skip


@dataclass
class LibraryResult:
    library: str
    runs: list[RunResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # not today's greedy merge
    ids: tuple[str, ...] = ()  # every run planned for the library
    baseline: BaselineLook | None = None
    setup_s: float | None = None
    connect_s: float | None = None
    baseline_s: float | None = None
    wall_s: float | None = None
    stopped: str | None = None

    @property
    def planned(self) -> int:
        return len(self.ids)

    @property
    def incomplete(self) -> list[str]:
        """Planned runs neither complete nor skipped as a data gap: an
        error, a stop, a look not measured, or never reached."""
        done = {r.run.id for r in self.runs if r.complete} | set(self.skipped)
        return [i for i in self.ids if i not in done]

    @property
    def complete(self) -> bool:
        return self.stopped is None and not self.incomplete

    def row(self) -> dict[str, object]:
        b = self.baseline
        return {
            "experiment": ORDER_EXPERIMENT, "kind": "library", "library": self.library,
            "planned": self.planned, "runs": len(self.runs), "errors": list(self.errors),
            "skipped": list(self.skipped),
            "baseline_floor_pct": _pct(None if b is None else b.floor),
            "calibrated_floor_pct": _pct(None if b is None else b.calibrated),
            "setup_s": self.setup_s, "connect_s": self.connect_s,
            "baseline_s": self.baseline_s,
            "calibration_s": None if b is None else b.calibration_s,
            "wall_s": self.wall_s, "stopped": self.stopped, "complete": self.complete,
        }  # fmt: skip
