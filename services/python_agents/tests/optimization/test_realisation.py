"""The realisation record (emergence round 1, S1): pure, no I/O.

From a measured trial's diff, the base sources of the files it changed and
its ``unit_calls`` rows (the twin's in ``base_measurements``, its own in
``measurements``), the record says which files, hunks and functions (by AST
span, the innermost ``def`` or ``class`` of each changed base line) the edit
touched, whether it touched the idea's anchor, and how the anchor's counted
work (its own calls plus the calls its frames made) moved: an engine label
fixed before any run, ``fired`` (a cut of at least 10 %), ``not_fired``
(under 1 % either way), ``weak`` (in between), ``reversed`` (a rise of at
least 10 %) or ``uncounted``. Joined with the frozen verdict it flags a keep
whose anchor did not fire. No model-written number is read.
"""

from __future__ import annotations

import ast
import warnings

import pytest

from autonomous_ai_agents.common.models import Measurement, RunStats, Trial
from autonomous_ai_agents.execution.measure import (
    CALLEE_KEY,
    METRIC_OP_CALLS,
    METRIC_UNIT_CALLS,
    OUT_CALLS_KEY,
    UNIT_KEY,
)
from autonomous_ai_agents.optimization.evolve import (
    FIRED_AT,
    NOT_FIRED_UNDER,
    diff_hunks,
    realisation,
    realisation_label,
    touched_functions,
)
from autonomous_ai_agents.optimization.idea_types import Realisation, RealisationLabel

LEXER = """import re


def helper(x):
    return x


class Lexer:
    @staticmethod
    def get_tokens(text):
        out = []
        for i in range(len(text)):
            out.append(helper(i))

        def inner():
            return 1
        return out
"""

DIFF = """diff --git a/pkg/lexer.py b/pkg/lexer.py
index 1111111..2222222 100644
--- a/pkg/lexer.py
+++ b/pkg/lexer.py
@@ -1 +1,2 @@
 import re
+import sys
@@ -12,2 +13,2 @@ class Lexer:
-        for i in range(len(text)):
-            out.append(helper(i))
+        for i in range(len(text)):
+            out.append(i)
@@ -16,0 +17 @@ class Lexer:
+            pass
diff --git a/pkg/new.py b/pkg/new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/pkg/new.py
@@ -0,0 +1,3 @@
+def fresh():
+    return 1
+
diff --git a/pkg/old.py b/pkg/renamed.py
similarity index 90%
rename from pkg/old.py
rename to pkg/renamed.py
@@ -3,4 +3,4 @@ def f():
-    x
+    y
"""


def test_the_hunks_are_base_side_line_ranges_per_file() -> None:
    assert diff_hunks(DIFF) == {
        "pkg/lexer.py": ((1, 1), (12, 13), (16, 16)),
        "pkg/new.py": ((1, 1),),
        "pkg/old.py": ((3, 3),),
    }
    assert diff_hunks("") == {}


TWO = """def one():
    return 1

def two():
    return 2

def three():
    return 3
def four():
    return 4
"""

CONTEXT = "\n".join(
    [
        "diff --git a/pkg/a.py b/pkg/a.py",
        "--- a/pkg/a.py",
        "+++ b/pkg/a.py",
        "@@ -1,8 +1,10 @@",
        " def one():",
        "     return 1",
        " ",
        "-def two():",
        "+def two(x):",
        "     return 2",
        " ",
        "+# note",
        "+",
        " def three():",
        "     return 3",
        "@@ -9,2 +11,3 @@",
        "+import sys",
        " def four():",
        "     return 4",
        "\\ No newline at end of file",
        "",
    ]
)  # git's blank context lines are one space


def test_only_changed_base_lines_count_never_the_context_around_them() -> None:
    """
    GIVEN git's default 3 lines of context around a one-line change, a run
        of insertions after a blank line and an insertion at a hunk's top
    WHEN the hunks and the touched functions are read
    THEN the change is its own base line, an insertion is the base line it
        follows (the line before a hunk's first line at its top), the context
        lines are no change, so ``one`` and ``four`` beside the edits are
        untouched
    """
    hunks = diff_hunks(CONTEXT)

    assert hunks == {"pkg/a.py": ((4, 4), (6, 6), (8, 8))}
    assert touched_functions({"pkg/a.py": TWO}, hunks) == (
        "pkg/a.py::two", "pkg/a.py::<module>", "pkg/a.py::three",
    )  # fmt: skip


def test_each_changed_base_line_names_its_innermost_def_or_class() -> None:
    """
    GIVEN the lexer's base source, an import-line hunk, a hunk inside the
        decorated method and an insertion after the nested function's line
    WHEN the touched functions are read
    THEN the module, the method and the nested function are named once each,
        in hunk order; a file with no base source or no parse names nothing
    """
    hunks = diff_hunks(DIFF)
    sources = {"pkg/lexer.py": LEXER, "pkg/old.py": "def f(:\n"}

    touched = touched_functions(sources, hunks)

    assert touched == (
        "pkg/lexer.py::<module>",
        "pkg/lexer.py::Lexer.get_tokens",
        "pkg/lexer.py::Lexer.get_tokens.inner",
    )
    assert touched_functions({"pkg/lexer.py": LEXER}, {"pkg/lexer.py": ((9, 9),)}) == (
        "pkg/lexer.py::Lexer.get_tokens",  # the decorator's line is the method's
    )


@pytest.mark.parametrize(
    ("base", "trial", "label", "moved"),
    [(100, 90, RealisationLabel.fired, 0.10), (100, 91, RealisationLabel.weak, 0.09),
     (1000, 990, RealisationLabel.weak, 0.01), (1000, 995, RealisationLabel.not_fired, 0.005),
     (1000, 1000, RealisationLabel.not_fired, 0.0),
     (1000, 1009, RealisationLabel.not_fired, -0.009),
     (100, 105, RealisationLabel.weak, -0.05), (100, 110, RealisationLabel.reversed, -0.10),
     (0, 0, RealisationLabel.uncounted, None), (None, 5, RealisationLabel.uncounted, None),
     (5, None, RealisationLabel.uncounted, None)],
)  # fmt: skip
def test_the_label_reads_the_counted_move_against_fixed_thresholds(
    base: int | None, trial: int | None, label: RealisationLabel, moved: float | None
) -> None:
    assert (FIRED_AT, NOT_FIRED_UNDER) == (0.10, 0.01)
    found, change = realisation_label(base, trial)
    assert found is label
    assert change == (None if moved is None else pytest.approx(moved))


def row(unit: str, calls: int, *, out: int | None = None, callee: str | None = None,
        trial_id: str | None = None, metric: str = METRIC_UNIT_CALLS) -> Measurement:  # fmt: skip
    hardware: dict[str, str | int] = {UNIT_KEY: unit}
    if out is not None:
        hardware[OUT_CALLS_KEY] = out
    if callee is not None:
        hardware[CALLEE_KEY] = callee
    return Measurement(workload_id="w", trial_id=trial_id, metric=metric,
                       stats=RunStats.from_samples((float(calls),), unit="calls"),
                       samples=(float(calls),), hardware=hardware)  # fmt: skip


UNIT = "pkg/lexer.py::get_tokens"


def trial(base_work: tuple[int, int], work: tuple[int, int]) -> Trial:
    base = (row(UNIT, base_work[0], out=base_work[1]), row(UNIT, 99, callee="helper"),
            row("pkg/lexer.py::helper", 7, out=0), row(UNIT, 5, metric=METRIC_OP_CALLS))  # fmt: skip
    own = (row(UNIT, work[0], out=work[1], trial_id="t"),
           row(UNIT, 1, callee="helper", trial_id="t"))  # fmt: skip
    return Trial(hypothesis_id="h", round=1, diff=DIFF, base_measurements=base,
                 measurements=own)  # fmt: skip


def test_the_record_joins_the_diff_the_anchor_and_its_counts() -> None:
    """
    GIVEN a trial whose anchor ``Lexer.get_tokens`` did 1 + 99 calls of work
        on the twin and 1 + 9 on the trial, kept
    WHEN the record is built
    THEN it names the files, the 5 hunks and the touched functions, says the
        anchor was touched, reads the anchor's unit ``PATH::co_name`` from the
        unit rows alone (never a callee or ``op_calls`` row) and labels it
        fired; a kept fired trial is no kept-not_fired
    """
    sources = {"pkg/lexer.py": LEXER}

    rec = realisation(trial((1, 99), (1, 9)), sources,
                      anchor=("pkg/lexer.py", "Lexer.get_tokens"), kept=True)  # fmt: skip

    assert rec == Realisation(
        files=("pkg/lexer.py", "pkg/new.py", "pkg/old.py"), hunks=5,
        functions=("pkg/lexer.py::<module>", "pkg/lexer.py::Lexer.get_tokens",
                   "pkg/lexer.py::Lexer.get_tokens.inner"),
        anchor="pkg/lexer.py::Lexer.get_tokens", anchor_touched=True, unit=UNIT,
        base_calls=1, base_out=99, trial_calls=1, trial_out=9, moved=0.9,
        label=RealisationLabel.fired, kept_not_fired=False,
    )  # fmt: skip


def test_a_keep_whose_anchor_did_not_move_is_flagged_and_an_untouched_anchor_said() -> (
    None
):
    sources = {"pkg/lexer.py": LEXER}

    rec = realisation(trial((1, 99), (1, 99)), sources,
                      anchor=("pkg/lexer.py", "helper"), kept=True)  # fmt: skip

    assert (rec.anchor_touched, rec.unit, rec.base_calls) == (False, "pkg/lexer.py::helper", 7)  # fmt: skip
    assert (rec.trial_calls, rec.label, rec.kept_not_fired) == (None, RealisationLabel.uncounted, False)  # fmt: skip
    same = realisation(trial((1, 99), (1, 99)), sources,
                       anchor=("pkg/lexer.py", "Lexer.get_tokens"), kept=True)  # fmt: skip
    assert (same.label, same.moved, same.kept_not_fired) == (RealisationLabel.not_fired, 0.0, True)  # fmt: skip
    dropped = realisation(trial((1, 99), (1, 99)), sources,
                          anchor=("pkg/lexer.py", "Lexer.get_tokens"), kept=False)  # fmt: skip
    assert dropped.kept_not_fired is False


def test_without_an_anchor_nothing_is_counted_and_nothing_is_touched() -> None:
    rec = realisation(trial((1, 99), (1, 9)), {}, anchor=None, kept=True)

    assert (rec.anchor, rec.anchor_touched, rec.unit) == (None, None, None)
    assert (rec.base_calls, rec.label, rec.functions) == (None, RealisationLabel.uncounted, ())  # fmt: skip


@pytest.mark.parametrize("error", [RecursionError, MemoryError])
def test_a_source_that_blows_the_parser_names_nothing_and_loses_no_record(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    """The record runs after a paid run: a parse that overflows the
    recursion limit or memory leaves that file unnamed, never the run's
    rows (the same guard as idea_context's)."""

    parse = ast.parse

    def blow(source: str, filename: str = "<unknown>", mode: str = "exec") -> ast.AST:
        if source == LEXER:
            raise error
        return parse(source, filename, mode)

    monkeypatch.setattr(ast, "parse", blow)  # the module evolve parses with

    assert touched_functions({"pkg/lexer.py": LEXER}, {"pkg/lexer.py": ((9, 9),)}) == ()


def test_a_warning_from_the_parsed_source_is_silenced() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        touched = touched_functions({"a.py": 'def f():\n    return "\\d"\n'}, {"a.py": ((2, 2),)})  # fmt: skip

    assert touched == ("a.py::f",)
