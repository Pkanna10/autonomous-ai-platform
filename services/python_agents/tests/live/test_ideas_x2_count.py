"""Offline guards of S1's count record in the ideas-x2 suite (emergence
round 1): the X2-C arm and its realisation rows and report section.

Not ``live``: these spend nothing. X2-C is X2-0's settings plus
``IDEAS_COUNT_CONTRACT=record`` (no request or prompt changes, so its lane
requests are X2-0's byte for byte); it is off the dispatch plan
(``dispatches``) until the Lead and the owner put it there. Its hypothesis
rows carry each measured trial's realisation record (``evolve.realisation``
over the base text of the changed files, read from the user's clone at E1's
commit by ``base_sources``); other arms' rows carry no such field. The report
adds a realisation section only when a row has one, so every committed
report reads byte for byte as before. Fakes: ``test_ideas_x2_guards``'s
``_Engine`` and hand-built state stand for the whole engine run; the clone
is a temporary directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.models import Measurement, RunStats, TrialStatus
from autonomous_ai_agents.execution.measure import (
    CALLEE_KEY,
    METRIC_UNIT_CALLS,
    OUT_CALLS_KEY,
    UNIT_KEY,
)
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import ideas_x2 as x2
from . import ideas_x2_report as xr
from . import test_ideas_x2_guards as xg
from . import test_ideas_x2_report_guards as rg
from .conftest import SUITE_CAP_ENV

x2_run = xg.x2_run
SOURCE = "def parse(src):\n    out = []\n    for c in src:\n        out.append(c)\n    return out\n"  # fmt: skip
DIFF = """diff --git a/tomli/_parser.py b/tomli/_parser.py
--- a/tomli/_parser.py
+++ b/tomli/_parser.py
@@ -3,2 +3 @@ def parse(src):
-    for c in src:
-        out.append(c)
+    out.extend(src)
"""


def unit_row(calls: int, out: int, trial_id: str | None) -> Measurement:
    hardware: dict[str, str | int] = {UNIT_KEY: "tomli/_parser.py::parse", OUT_CALLS_KEY: out}  # fmt: skip
    return Measurement(workload_id="w", trial_id=trial_id, metric=METRIC_UNIT_CALLS,
                       stats=RunStats.from_samples((float(calls),), unit="calls"),
                       samples=(float(calls),), hardware=hardware)  # fmt: skip


class _Counted(xg._Engine):
    """The fake run with a clone holding the base source, and measured
    trials: the lens idea's (anchored on ``parse``) cut its frames' calls
    from 40 to 2; the S1 idea's trial is measured with no anchor."""

    def __init__(self, clone: Path) -> None:
        super().__init__()
        self.clone = clone

    def start(self, *args: Any, **kwargs: Any) -> Any:
        loop = super().start(*args, **kwargs)
        loop.user.path = self.clone
        return loop

    def run(self, loop: Any, run: Any, isolation: Any, *, model: str, record: Any) -> Any:  # fmt: skip
        state: dict[str, Any] = dict(xg._state().state)
        trials = list(state["trials"])
        measured = {"status": TrialStatus.measured, "diff": DIFF}
        lens = trials[1]
        trials[1] = lens.model_copy(update={**measured,
            "base_measurements": (unit_row(1, 40, None),),
            "measurements": (unit_row(1, 2, lens.id), unit_row(9, 0, lens.id).model_copy(
                update={"hardware": {UNIT_KEY: "tomli/_parser.py::parse", CALLEE_KEY: "x"}}))})  # fmt: skip
        trials[0] = trials[0].model_copy(update=measured)
        state["trials"] = trials
        record(SimpleNamespace(guard="ok"), EngineRunResult("run", "done", cast(Any, state), None))  # fmt: skip


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    root = tmp_path / "clone"
    (root / "tomli").mkdir(parents=True)
    (root / "tomli" / "_parser.py").write_text(SOURCE, encoding="utf-8")
    return root


def test_x2_c_is_x2_0_with_the_count_record_and_off_the_plan() -> None:
    assert x2.X2_C.key == "X2-C" and x2.X2_C.repos == x2.X2_0.repos
    assert dict(x2.X2_C.update) == {**x2.SHARED, "IDEAS_COUNT_CONTRACT": "record"}
    assert x2.X2_C not in x2.X2_ARMS
    assert not any(d.startswith("X2-C") for d in x2.dispatches())
    assert x2.arm_cap(x2.X2_C) == x2.arm_cap(x2.X2_0)
    assert x2.run_minutes(x2.arm_settings(x2.X2_C)) == x2.run_minutes(x2.arm_settings(x2.X2_0))  # fmt: skip
    plan = x2.x2_plan({x2.DISPATCH_ENV: "X2-C:sqlparse", SUITE_CAP_ENV: "10"})
    assert [(a.key, r.name) for a, r in plan.runs] == [("X2-C", "sqlparse")]


def test_x2_c_rows_carry_each_measured_trials_realisation(x2_run: Any, clone: Path) -> None:  # fmt: skip
    """
    GIVEN an X2-C run whose lens trial (anchored on ``tomli/_parser.py``'s
        ``parse``) replaced the append loop, its frames' calls 40 to 2, and
        whose S1 trial is measured with no anchor
    WHEN it is recorded
    THEN the lens row's realisation names the touched function, the anchor
        touched and fired; the S1 row's has no anchor and is uncounted; a
        trial that was not measured, and an idea left in the pool, have none
    """
    _, rows = x2_run(engine=_Counted(clone), arm=x2.X2_C)

    ideas = {r["title"]: r for r in xg._rows(rows, x2.IDEA_EXPERIMENT)}
    lens = ideas["lens idea"]["realisation"]
    assert {k: lens[k] for k in ("files", "hunks", "functions", "anchor", "anchor_touched",
                                 "unit", "base_out", "trial_out", "label", "kept_not_fired")} == {
        "files": ["tomli/_parser.py"], "hunks": 1,
        "functions": ["tomli/_parser.py::parse"], "anchor": "tomli/_parser.py::parse",
        "anchor_touched": True, "unit": "tomli/_parser.py::parse", "base_out": 40,
        "trial_out": 2, "label": "fired", "kept_not_fired": False,
    }  # fmt: skip
    s1 = next(r for t, r in ideas.items() if t.startswith("S1 idea"))["realisation"]
    assert (s1["anchor"], s1["label"], s1["functions"]) == (None, "uncounted", ["tomli/_parser.py::parse"])  # fmt: skip
    assert ideas["leap idea"]["realisation"] is None
    assert ideas["pool idea"]["realisation"] is None


def test_other_arms_rows_carry_no_realisation(x2_run: Any) -> None:
    _, rows = x2_run()

    assert not any("realisation" in r for r in rows)


def test_base_sources_read_only_plain_python_files_inside_the_clone(tmp_path: Path) -> None:  # fmt: skip
    root = tmp_path / "clone"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "pkg" / "big.py").write_text("#" * 64, encoding="utf-8")
    (root / "pkg" / "bad.py").write_bytes(b"\xff\n")
    (root / "pkg" / "notes.txt").write_text("n", encoding="utf-8")
    (tmp_path / "outside.py").write_text("y = 2\n", encoding="utf-8")
    os.symlink(tmp_path / "outside.py", root / "pkg" / "link.py")

    found = x2.base_sources(root, ["pkg/a.py", "pkg/big.py", "pkg/bad.py", "pkg/notes.txt",
                                   "pkg/link.py", "../outside.py", "/etc/x.py",
                                   "pkg/missing.py", "pkg//a.py"], cap=32)  # fmt: skip

    assert found == {"pkg/a.py": "x = 1\n"}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def _realised(rows: list[rg.Row], labels: dict[str, tuple[str, bool | None]]) -> list[rg.Row]:  # fmt: skip
    out = []
    for r in rows:
        if r["experiment"] == x2.IDEA_EXPERIMENT:
            label, touched = labels.get(str(r["hypothesis_id"]), ("uncounted", None))
            kept = r["verdict"] == "keep"
            r = {**r, "realisation": {"label": label, "anchor_touched": touched,
                                      "kept_not_fired": kept and label == "not_fired",
                                      "unit": "ignored"}}  # fmt: skip
        out.append(r)
    return out


def test_the_report_reads_the_realisation_labels_by_arm(tmp_path: Path) -> None:
    """
    GIVEN an X2-C run of 4 trials (a kept fired idea, a kept not-fired idea
        whose anchor was untouched, an inconclusive fired one, an uncounted
        one) beside an X2-0 run with no record
    WHEN the report renders
    THEN X2-C is read against X2-0 like any arm, and a realisation section
        counts trials and keeps per label, the kept-not-fired flag and the
        untouched anchors, with the premise's sides and their sizes
    """
    base = rg._rows("X2-0", "tomli", [(2, ["obvious"])])
    arm = _realised(rg._rows("X2-C", "tomli", [(4, ["leap", "far"])]), {
        "tomli-1-0": ("fired", True), "tomli-1-1": ("not_fired", False),
        "tomli-1-2": ("fired", True)})  # fmt: skip

    text = rg._text(rg._write(tmp_path / "x.jsonl", base, arm))

    assert "| X2-C | tomli | +1 |" in text
    section = text[text.index("## 7 Realisation (S1)") :]
    assert "| X2-C | fired | 2 | 1 |" in section
    assert "| X2-C | not_fired | 1 | 1 |" in section
    assert "| X2-C | uncounted | 1 | 0 |" in section
    assert "| X2-C | 4 | 1 | 1 | fired 1/2, not_fired 1/1 (needs 10 or more each side) |" in section  # fmt: skip
    assert "X2-0 |" not in section


def test_without_a_record_the_report_has_no_realisation_section(tmp_path: Path) -> None:
    base = rg._rows("X2-0", "tomli", [(2, ["obvious"])])

    assert "Realisation" not in rg._text(rg._write(tmp_path / "x.jsonl", base))
    assert xr.ARMS[-2:] == ("X2-C", "X2-SV")


def test_a_malformed_realisation_is_refused(tmp_path: Path) -> None:
    arm = _realised(rg._rows("X2-C", "tomli", [(1, [])]), {})
    arm[0]["realisation"] = {"label": 3}

    with pytest.raises(ValueError, match="realisation"):
        rg._text(rg._write(tmp_path / "x.jsonl", arm))
