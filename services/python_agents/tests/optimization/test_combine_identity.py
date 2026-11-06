"""S2 (emergence round 1): a keep's hunk identity and the reconcile record.

``hunk_signature`` is what ``duplicate_of`` reads: two keeps are one change
only when their diffs against the base remove and add the same lines at the
same base positions, whitespace collapsed, context dropped, so a ``-U3``
diff and a ``-U0`` diff of one change agree and an equal op count never
decides (board [69], [79]). ``reconcile_eligibility`` is part 3's record
without a trial: a blocked keep B is eligible only when B's most-cut counted
unit (S1's ``unit_calls`` rows) is still made on the survivor A's commit by
at least 2 % of the base's counted calls; a count-invisible B never is.
Fakes: hand-written diffs stand for ``git diff base..commit``, hand-built
``Measurement`` rows for S1's counted runs.
"""

from __future__ import annotations

from autonomous_ai_agents.common.models import Measurement, RunStats, Trial
from autonomous_ai_agents.execution.measure import (
    CALLEE_KEY,
    METRIC_OP_CALLS,
    METRIC_UNIT_CALLS,
    OUT_CALLS_KEY,
    UNIT_KEY,
)
from autonomous_ai_agents.optimization.evolve import (
    hunk_signature,
    reconcile_eligibility,
)

U3 = """diff --git a/pkg/a.py b/pkg/a.py
index 1111111..2222222 100644
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -2,7 +2,7 @@ def f():
     a = 1
     b = 2
     c = 3
-    d = slow(a)
+    d = fast(a)
     e = 5
     f = 6
     g = 7
"""
U0 = """diff --git a/pkg/a.py b/pkg/a.py
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -5 +5 @@ def f():
-    d = slow(a)
+    d  =  fast(a)
"""
OTHER = U0.replace("fast(a)", "faster(a)")
MOVED = U0.replace("@@ -5 +5 @@", "@@ -6 +6 @@")
INSERT_U0 = """diff --git a/pkg/a.py b/pkg/a.py
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -4,0 +5 @@
+    x = 0
\\ No newline at end of file
"""
INSERT_U3 = """diff --git a/pkg/a.py b/pkg/a.py
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -2,6 +2,7 @@
     a = 1
     b = 2
     c = 3
+    x = 0
     d = slow(a)
     e = 5
     f = 6
"""
BINARY = "diff --git a/pkg/b.bin b/pkg/b.bin\nindex 1..2 100644\nBinary files a/pkg/b.bin and b/pkg/b.bin differ\n"  # fmt: skip


def test_one_change_reads_the_same_with_context_or_without() -> None:
    assert hunk_signature(U3) == hunk_signature(U0) is not None
    assert hunk_signature(INSERT_U3) == hunk_signature(INSERT_U0) is not None


def test_a_different_line_or_position_is_another_change() -> None:
    signatures = {hunk_signature(d) for d in (U0, OTHER, MOVED, INSERT_U0)}
    assert len(signatures) == 4


def test_a_binary_change_has_an_identity_and_nothing_or_a_truncated_diff_none() -> None:
    assert hunk_signature(BINARY) is not None
    assert hunk_signature(BINARY) != hunk_signature(BINARY.replace("b.bin", "c.bin"))
    assert hunk_signature("") is None
    assert hunk_signature(U0 + "\n[diff truncated: 10 of 20 bytes shown]\n") is None


def _unit(unit: str, calls: int, out: int | None, trial_id: str | None) -> Measurement:
    hardware: dict[str, str | int] = {UNIT_KEY: unit}
    hardware |= {CALLEE_KEY: "x"} if out is None else {OUT_CALLS_KEY: out}
    return Measurement(workload_id="w", trial_id=trial_id, metric=METRIC_UNIT_CALLS,
                       stats=RunStats.from_samples((float(calls),), unit="calls"),
                       samples=(float(calls),), hardware=hardware)  # fmt: skip


def _total(calls: int) -> Measurement:
    return Measurement(workload_id="w", metric=METRIC_OP_CALLS,
                       stats=RunStats.from_samples((float(calls),), unit="calls"),
                       samples=(float(calls),))  # fmt: skip


LEX, GROUP = "pkg/lexer.py::get_tokens", "pkg/grouping.py::group"


def _trial(own: list[Measurement], base: list[Measurement]) -> Trial:
    return Trial(hypothesis_id="h", round=1, measurements=tuple(own),
                 base_measurements=tuple(base))  # fmt: skip


def test_a_blocked_keep_is_eligible_when_the_survivor_left_its_unit_made() -> None:
    """
    GIVEN a base of 1,000 counted calls; B cuts get_tokens' work 300 -> 100
        (and group's 50 -> 40); the survivor A cuts get_tokens only to 200
    WHEN part 3's eligibility is read
    THEN B is eligible: A still makes 100 more of B's most-cut unit, 10 % of
        the base's calls, over the 2 % bar; a callee row never counts
    """
    base = [_total(1000), _unit(LEX, 100, 200, None), _unit(GROUP, 10, 40, None)]
    blocked = _trial([_unit(LEX, 40, 60, "b"), _unit(LEX, 999, None, "b"),
                      _unit(GROUP, 10, 30, "b")], base)  # fmt: skip
    applied = _trial([_unit(LEX, 80, 120, "a")], base)

    assert reconcile_eligibility(applied, blocked) == "eligible"


def test_the_survivor_that_closed_the_unit_leaves_nothing_to_reconcile() -> None:
    base = [_total(1000), _unit(LEX, 100, 200, None)]
    blocked = _trial([_unit(LEX, 40, 60, "b")], base)
    applied = _trial([_unit(LEX, 40, 75, "a")], base)

    assert reconcile_eligibility(applied, blocked) == (
        "ineligible: the survivor left under 2 % of the base's counted calls"
    )


def test_a_count_invisible_or_uncounted_keep_is_never_eligible() -> None:
    """A hoist that moves no counted unit (B's counts equal the base's), a
    trial with no unit rows, a survivor that did not count B's unit, and a
    base with no op count each read ineligible, with the reason."""
    base = [_total(1000), _unit(LEX, 100, 200, None)]
    hoist = _trial([_unit(LEX, 100, 200, "b")], base)
    applied = _trial([_unit(LEX, 100, 200, "a")], base)
    assert reconcile_eligibility(applied, hoist) == (
        "ineligible: count-invisible (no counted unit cut)"
    )
    assert reconcile_eligibility(applied, _trial([], base)) == (
        "ineligible: uncounted (no unit rows)"
    )
    cut = _trial([_unit(LEX, 40, 60, "b")], base)
    assert reconcile_eligibility(_trial([_unit(GROUP, 1, 1, "a")], base), cut) == (
        "ineligible: the survivor did not count the unit"
    )
    no_total = _trial([_unit(LEX, 40, 60, "b")], base[1:])
    assert reconcile_eligibility(applied, no_total) == ("ineligible: no base op count")
