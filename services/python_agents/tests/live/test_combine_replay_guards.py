"""Offline guards of the combine re-measure replay (``combine_replay.py``).

The owner's ruling (O62 item 5): the combine proposal's item 1 as an offline
replay only, the four archived rows whose combine floor was at least twice
the run's baseline floor, no API spend. What is checked here, with no
network:

- the cases: exactly the four rows of ``q3_floors.csv`` at a ratio of 2 or
  more, plus markdown's calibration-and-profile case; one profile a library;
- integrity: every patch path resolves inside the archive, every sha256 is
  the archived one, the repository's base is the archived ``base_commit``;
  a mismatch writes the ``error`` row, then fails the case;
- the rule: the trigger reads the floor only, the verdict is m2's when it
  fires on m1, else m1's;
- a whole case on a fake measurer and a fake clock (rows, timings, table);
- the real measurer on a local repository in the ``required`` sandbox (the
  engine's preflight, define, baseline with calibration, profile and the
  combine node's re-test), with no request;
- the ci.yml row, the minute estimate and the settings the X2 arms measured
  under.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

import pytest
from e2e.conftest import Isolation, UserRepo, _sandbox_problem, git

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import NoiseCalibration, Workload
from autonomous_ai_agents.execution.procrun import RunFailure, RunSample
from autonomous_ai_agents.execution.protocols import KeptChange

from . import combine_replay as cr
from . import ideas_x2
from .conftest import TESTS_DIR, LiveRun, make_repo
from .discovery_io import ResultsSink
from .oss import CloneRefusedError, OssRepo
from .test_corpus_guards import (
    CI_WORKFLOW,
    EXPERIMENT_MINUTES,
    _ci_block,
    _dispatch,
    _run_script,
)

ARCHIVE = cr.ARCHIVE
TIPS = [c for c in cr.CASES if c.tip != cr.NO_TIP]
SHA = "0" * 64


# ---------------------------------------------------------------------------
# The cases against the archive's own evidence
# ---------------------------------------------------------------------------


def test_the_tip_cases_are_the_four_rows_at_twice_the_baseline_floor() -> None:
    """The ruling's four rows, read from ``q3_floors.csv``, not retyped."""
    lines = (ARCHIVE / "zero-credit" / "q3_floors.csv").read_text().splitlines()
    head = lines[0].split(",")
    rows = [dict(zip(head, line.split(","), strict=True)) for line in lines[1:]]
    wide = {
        (r["arm"], r["run"], r["repo"])
        for r in rows
        if float(r["ratio_run_floor_to_baseline"]) >= cr.RULE_K
    }
    assert {(c.arm, c.dispatch, c.library) for c in TIPS} == wide
    assert len(TIPS) == 4 and len(cr.CASES) == 5
    assert [c.tip for c in TIPS].count(cr.FALLBACK) == 1


def test_each_library_is_profiled_once_and_markdown_has_no_tip() -> None:
    libraries = [c.library for c in cr.CASES]
    assert sorted({*libraries}) == ["markdown", "mistune", "sqlparse", "tomli"]
    profiled = [c.library for c in cr.CASES if c.profile]
    assert sorted(profiled) == sorted({*libraries})
    (markdown,) = [c for c in cr.CASES if c.library == "markdown"]
    assert (markdown.tip, markdown.patch, markdown.trial_id) == (cr.NO_TIP, None, None)
    assert markdown.base_commit.startswith("afd7a2f908")
    prefixes = {
        "sqlparse": "ddf10ae7de",
        "tomli": "e9735a7906",
        "mistune": "54306a1497",
    }
    for case in TIPS:
        assert case.base_commit.startswith(prefixes[case.library]), case.id
        assert re.fullmatch(r"[0-9a-f]{40}", case.base_commit)
    assert len({c.id for c in cr.CASES}) == len(cr.CASES)


def test_every_case_passes_integrity_on_the_committed_archive() -> None:
    """Paths inside the archive, the archived sha256s, the archived base."""
    found = {c.id: cr.load_archived(c) for c in cr.CASES}
    tomli = found["X2-D-43093773731-tomli"]
    assert tomli.patch is not None and tomli.patch.name == "delivered.patch"
    assert tomli.sha256 == (
        "4b2c9266e11ebedb385e10131d810174b2ff62dc379852a3a25fcc3d2e6c174e"
    )
    assert (round(tomli.gain_pct or 0, 2), round(tomli.floor_pct or 0, 2)) == (
        18.75,
        6.45,
    )
    assert round(tomli.baseline_floor_pct or 0, 2) == 2.58 and tomli.holds is True
    fallback = found["X2-D-43145496896-mistune"]
    assert fallback.patch is not None
    assert fallback.patch.name == "trial-d11a38da-7132-58ab-974a-a58979a65e81.diff"
    assert fallback.trial_id == "d11a38da-7132-58ab-974a-a58979a65e81"
    assert fallback.hypothesis_id == "709d0168-c07b-4e64-94f0-6be7fdcd4ffd"
    assert (round(fallback.gain_pct or 0, 2), round(fallback.floor_pct or 0, 2)) == (
        8.54,
        9.76,
    )
    assert fallback.holds is False and round(fallback.ratio or 0, 2) == 2.59
    markdown = found["X2-P-43104077245-markdown"]
    assert markdown.patch is None and markdown.sha256 is None
    for case in TIPS:
        got = found[case.id]
        assert got.patch == (ARCHIVE / str(case.patch)).resolve()
        assert (got.ratio or 0) >= cr.RULE_K, case.id


# ---------------------------------------------------------------------------
# Integrity failures on a scratch archive
# ---------------------------------------------------------------------------

BASE = "a" * 40


@dataclass
class Scratch:
    """A minimal archive: one run file, its run row, a patch and a kept diff."""

    root: Path
    patch: bytes = b"diff --git a/x b/x\n"
    kept: bytes = b"diff --git a/y b/y\n"

    def __post_init__(self) -> None:
        self.folder = self.root / "live" / "patches-X2-D-123456789" / "X2-D-tomli"
        self.folder.mkdir(parents=True)
        (self.folder / "delivered.patch").write_bytes(self.patch)
        (self.folder / "trial-t1.diff").write_bytes(self.kept)

    def row(self, **changes: object) -> dict[str, object]:
        row: dict[str, object] = {
            "experiment": "ideas-x2-run", "repo": "tomli", "base_commit": BASE,
            "arm": "X2-D", "dispatch": "X2-D:sqlparse,tomli",
            "gain_pct": 18.0, "floor_pct": 6.0, "holds": True, "seconds_measured": 700.0,
            "delivered_patch": {
                "file": "live-patches/X2-D-tomli/delivered.patch",
                "sha256": hashlib.sha256(self.patch).hexdigest(),
                "base_commit": BASE, "truncated": False, "error": None,
            },
            "kept_diffs": [{
                "file": "live-patches/X2-D-tomli/trial-t1.diff", "trial_id": "t1",
                "hypothesis_id": "h1", "sha256": hashlib.sha256(self.kept).hexdigest(),
                "base_commit": BASE, "truncated": False, "error": None,
            }],
        }  # fmt: skip
        row.update(changes)
        return row

    def write(
        self, *rows: dict[str, object], floors: Sequence[float] = (2.5, 3.0)
    ) -> None:
        hyps = [{"experiment": "ideas-x2-hypothesis", "repo": "tomli", "floor_pct": f}
                for f in floors]  # fmt: skip
        hyps.append(
            {"experiment": "ideas-x2-hypothesis", "repo": "tomli", "floor_pct": None}
        )
        hyps.append(
            {"experiment": "ideas-x2-hypothesis", "repo": "other", "floor_pct": 0.1}
        )
        text = "".join(json.dumps(r) + "\n" for r in (*hyps, *rows))
        (self.root / "live" / "ideas-x2-X2-D-123456789.jsonl").write_text(text)

    def case(self, **changes: object) -> cr.ReplayCase:
        fields: dict[str, object] = {
            "id": "X2-D-123456789-tomli", "arm": "X2-D", "dispatch": "123456789",
            "library": "tomli", "base_commit": BASE, "tip": cr.DELIVERED,
            "patch": "live/patches-X2-D-123456789/X2-D-tomli/delivered.patch",
            "trial_id": None, "profile": True,
        }  # fmt: skip
        fields.update(changes)
        return cr.ReplayCase(**fields)  # type: ignore[arg-type]


@pytest.fixture
def scratch(tmp_path: Path) -> Scratch:
    return Scratch(Path(os.path.realpath(tmp_path)) / "archive")


def test_the_scratch_archive_passes_as_is(scratch: Scratch) -> None:
    scratch.write(scratch.row())
    found = cr.load_archived(scratch.case(), scratch.root)
    assert found.patch == scratch.folder / "delivered.patch"
    assert found.sha256 == hashlib.sha256(scratch.patch).hexdigest()
    assert (found.baseline_floor_pct, found.ratio) == (2.5, 6.0 / 2.5)
    assert (found.trial_id, found.hypothesis_id, found.seconds) == (None, None, 700.0)
    fallback = scratch.case(
        tip=cr.FALLBACK, trial_id="t1",
        patch="live/patches-X2-D-123456789/X2-D-tomli/trial-t1.diff",
    )  # fmt: skip
    kept = cr.load_archived(fallback, scratch.root)
    assert (kept.trial_id, kept.hypothesis_id) == ("t1", "h1")
    assert kept.sha256 == hashlib.sha256(scratch.kept).hexdigest()
    none = cr.load_archived(scratch.case(tip=cr.NO_TIP, patch=None), scratch.root)
    assert (none.patch, none.sha256, none.trial_id) == (None, None, None)
    scratch.write(scratch.row(gain_pct=None, floor_pct=None, holds=None), floors=())
    bare = cr.load_archived(scratch.case(), scratch.root)
    assert (bare.gain_pct, bare.floor_pct, bare.baseline_floor_pct, bare.ratio) == (
        None, None, None, None,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ({"base_commit": "b" * 40}, "base_commit"),
        ({"base_commit": "not-a-commit"}, "base_commit"),
        ({"delivered_patch": None}, "no delivered patch"),
        ({"delivered_patch": {"file": 3}}, "file"),
        ({"seconds_measured": "slow"}, "seconds_measured"),
        ({"gain_pct": "high"}, "gain_pct"),
        ({"holds": "yes"}, "holds"),
        ({"kept_diffs": "none"}, "kept_diffs"),
        ({"arm": "X2-P"}, "arm"),  # another arm's row in this run's file
        ({"arm": None}, "arm"),
        ({"dispatch": "X2-P:sqlparse,tomli"}, "dispatch"),  # another arm's dispatch
        ({"dispatch": "X2-D:sqlparse,markdown"}, "dispatch"),  # not this library's
        ({"dispatch": "X2-D"}, "dispatch"),
        ({"dispatch": 43093773731}, "dispatch"),
    ],
)
def test_a_malformed_run_row_is_refused(
    scratch: Scratch, row: dict[str, object], match: str
) -> None:
    scratch.write(scratch.row(**row))
    with pytest.raises(cr.IntegrityError, match=match):
        cr.load_archived(scratch.case(), scratch.root)


def test_a_patch_whose_sha256_is_not_the_archived_one_is_refused(
    scratch: Scratch,
) -> None:
    entry = {**scratch.row()["delivered_patch"], "sha256": SHA}  # type: ignore[dict-item]
    scratch.write(scratch.row(delivered_patch=entry))
    with pytest.raises(cr.IntegrityError, match="sha256"):
        cr.load_archived(scratch.case(), scratch.root)
    (scratch.folder / "delivered.patch").write_bytes(b"changed\n")
    scratch.write(scratch.row())
    with pytest.raises(cr.IntegrityError, match="sha256"):
        cr.load_archived(scratch.case(), scratch.root)


def test_a_kept_diff_whose_sha256_is_not_its_entry_is_refused(scratch: Scratch) -> None:
    case = scratch.case(
        tip=cr.FALLBACK, trial_id="t1",
        patch="live/patches-X2-D-123456789/X2-D-tomli/trial-t1.diff",
    )  # fmt: skip
    (scratch.folder / "trial-t1.diff").write_bytes(b"tampered\n")
    scratch.write(scratch.row())
    with pytest.raises(cr.IntegrityError, match="sha256"):
        cr.load_archived(case, scratch.root)
    with pytest.raises(cr.IntegrityError, match="no kept diff"):
        cr.load_archived(replace(case, trial_id="t9"), scratch.root)


@pytest.mark.parametrize(
    ("entry", "match"),
    [
        ({"truncated": True}, "truncated"),
        ({"error": "OSError"}, "error"),
        ({"base_commit": "c" * 40}, "base"),
        ({"sha256": "short"}, "sha256"),
    ],
)
def test_a_patch_entry_that_is_not_whole_is_refused(
    scratch: Scratch, entry: dict[str, object], match: str
) -> None:
    whole = scratch.row()["delivered_patch"]
    assert isinstance(whole, dict)
    scratch.write(scratch.row(delivered_patch={**whole, **entry}))
    with pytest.raises(cr.IntegrityError, match=match):
        cr.load_archived(scratch.case(), scratch.root)


def test_the_run_row_must_be_there_once(scratch: Scratch) -> None:
    scratch.write()
    with pytest.raises(cr.IntegrityError, match="0 run rows"):
        cr.load_archived(scratch.case(), scratch.root)
    scratch.write(scratch.row(), scratch.row())
    with pytest.raises(cr.IntegrityError, match="2 run rows"):
        cr.load_archived(scratch.case(), scratch.root)
    with pytest.raises(cr.IntegrityError, match="archive"):
        cr.load_archived(scratch.case(dispatch="999999999"), scratch.root)


def test_a_run_file_line_that_is_not_an_object_is_refused(scratch: Scratch) -> None:
    scratch.write(scratch.row())
    path = scratch.root / "live" / "ideas-x2-X2-D-123456789.jsonl"
    path.write_text(path.read_text() + "[1, 2]\n")
    with pytest.raises(cr.IntegrityError, match="not a JSON object"):
        cr.load_archived(scratch.case(), scratch.root)


def test_the_replay_context_runs_no_trial() -> None:
    nothing: Any = None
    with pytest.raises(AssertionError, match="runs no trial"):
        cr._NoTrials().run(
            nothing, (), nothing, round=1, branch="b", budget_usd=0.0, brief=nothing
        )


@pytest.mark.parametrize(
    "file",
    [
        "patches/X2-D-tomli/delivered.patch",  # not the patch directory
        "live-patches/../../../etc/passwd",
        "live-patches/X2-D-tomli/../delivered.patch",
        "live-patches/X2-D-tomli/sub/delivered.patch",
        "live-patches//delivered.patch",
        "live-patches/.hidden/delivered.patch",
        "live-patches/X2-D-tomli/missing.patch",
        "live-patches/X2-D-tomli/.delivered.patch",  # not a safe file name
        "/etc/passwd",
    ],
)
def test_a_patch_path_outside_its_run_directory_is_refused(
    scratch: Scratch, file: str
) -> None:
    with pytest.raises(cr.IntegrityError):
        cr.patch_file(scratch.root, scratch.case(), file)


def test_a_link_out_of_the_archive_is_refused(scratch: Scratch, tmp_path: Path) -> None:
    outside = tmp_path / "outside.patch"
    outside.write_bytes(scratch.patch)
    link = scratch.folder / "linked.patch"
    link.symlink_to(outside)
    with pytest.raises(cr.IntegrityError, match="outside the archive"):
        cr.patch_file(
            scratch.root, scratch.case(), "live-patches/X2-D-tomli/linked.patch"
        )
    with pytest.raises(cr.IntegrityError, match="outside the archive"):
        cr.archive_path(
            scratch.root, "live/patches-X2-D-123456789/X2-D-tomli/linked.patch"
        )
    with pytest.raises(cr.IntegrityError, match="not a regular file"):
        cr.archive_path(scratch.root, "live/patches-X2-D-123456789/X2-D-tomli")
    for bad in ("../outside.patch", "/etc/passwd", "live/../../outside.patch", ""):
        with pytest.raises(cr.IntegrityError):
            cr.archive_path(scratch.root, bad)


def test_the_declared_patch_must_be_the_rows_patch(scratch: Scratch) -> None:
    scratch.write(scratch.row())
    other = scratch.case(patch="live/patches-X2-D-123456789/X2-D-tomli/trial-t1.diff")
    with pytest.raises(cr.IntegrityError, match="declares"):
        cr.load_archived(other, scratch.root)
    with pytest.raises(cr.IntegrityError, match="declares no patch"):
        cr.load_archived(scratch.case(patch=None), scratch.root)


def test_a_case_with_unsafe_names_is_refused_before_any_file_is_read() -> None:
    good = cr.CASES[0]
    for bad in (
        {"arm": "X2-D/../x"}, {"dispatch": "1;id"}, {"library": "Tomli"},
        {"tip": "both"}, {"trial_id": "t1"}, {"base_commit": "abc"},
        {"tip": cr.FALLBACK, "trial_id": None},
    ):  # fmt: skip
        with pytest.raises(ValueError):
            replace(good, **bad)
    with pytest.raises(ValueError, match="patch"):
        replace(cr.CASES[-1], patch="live/x.patch")


# ---------------------------------------------------------------------------
# The rule: the trigger reads the floor only
# ---------------------------------------------------------------------------


def test_the_trigger_reads_the_floor_against_k_times_the_baseline_floor() -> None:
    assert cr.triggered(0.0597, 0.0298) is True  # 2.003 x
    assert cr.triggered(0.0596, 0.0298) is False  # 2.000 x: not above
    assert cr.triggered(0.02, 0.02) is False
    assert cr.triggered(None, 0.02) is None and cr.triggered(0.05, None) is None
    assert cr.triggered(0.07, 0.02, k=4.0) is False


def _retest(
    gain: float | None,
    floor: float | None,
    holds: bool,
    *,
    applied: int = 1,
    rows: bool = True,
) -> cr.RetestLook:
    return cr.RetestLook(
        applied=applied, gain=gain, floor=floor, outcome="keep" if holds else "reject",
        holds=holds, reason="r", tests="passed", tests_counted=3, tests_s=1.0, notes=(),
        rows=rows,
    )  # fmt: skip


SKIPPED = _retest(None, None, False, applied=0, rows=False)  # the combiner skipped it
NO_ROWS = _retest(None, None, False, rows=False)  # a RunFailure: applied, no rows


def _result(*looks: cr.RetestLook, base: float | None = 0.03) -> cr.CaseResult:
    archived = cr.Archived(None, None, None, None, None, None, None, None, None)
    found = cr.CaseResult(cr.CASES[0], archived)
    found.baseline = cr.BaselineLook(base, base, 0.01, 1.0, 3)
    found.looks = [
        cr.Look(name, r, 2.0) for name, r in zip(cr.LOOKS, looks, strict=False)
    ]
    return found


def test_the_verdict_is_m2s_when_the_rule_fires_on_m1_else_m1s() -> None:
    fired = _result(
        _retest(0.2, 0.07, True), _retest(0.1, 0.05, False), _retest(0.1, 0.02, True)
    )
    assert (fired.rule_triggered, fired.rule_verdict) == (True, False)
    assert fired.floor_spread == pytest.approx(0.05)
    quiet = _result(_retest(0.2, 0.05, False), _retest(0.2, 0.02, True))
    assert (quiet.rule_triggered, quiet.rule_verdict) == (False, False)
    # the trigger never reads the verdict: a high floor that held is re-measured too
    held = _result(_retest(0.3, 0.09, True), _retest(0.01, 0.02, False))
    assert (held.rule_triggered, held.rule_verdict) == (True, False)
    alone = _result(_retest(0.3, 0.09, True))  # stopped before m2: no second look
    assert (alone.rule_triggered, alone.rule_verdict) == (True, None)
    unknown = _result(_retest(None, None, False), _retest(0.2, 0.02, True))
    assert (unknown.rule_triggered, unknown.rule_verdict) == (None, False)
    none = _result()
    assert (none.rule_triggered, none.rule_verdict, none.floor_spread) == (
        None,
        None,
        None,
    )
    unbased = _result(_retest(0.2, 0.07, True), base=None)
    assert unbased.baseline is not None and unbased.rule_triggered is None


def test_a_look_that_did_not_measure_the_tip_gives_no_verdict() -> None:
    assert _retest(0.1, 0.02, True).measured_tip
    assert not SKIPPED.measured_tip and not NO_ROWS.measured_tip
    assert not _retest(0.1, 0.02, True, applied=2).measured_tip
    m1_lost = _result(NO_ROWS, _retest(0.2, 0.02, True))
    assert (m1_lost.rule_triggered, m1_lost.rule_verdict) == (None, None)
    m2_lost = _result(_retest(0.2, 0.02, True), SKIPPED)  # quiet m1, but no m2
    assert (m2_lost.rule_triggered, m2_lost.rule_verdict) == (False, None)
    fired = _result(_retest(0.2, 0.09, True), NO_ROWS)
    assert (fired.rule_triggered, fired.rule_verdict) == (True, None)
    assert (
        fired.not_measured == "m2"
        and _result(_retest(0.2, 0.02, True)).not_measured is None
    )
    assert cr._cell(NO_ROWS) == "not measured" and cr._cell(None) == "-"


# ---------------------------------------------------------------------------
# A whole case on a fake measurer and a fake clock
# ---------------------------------------------------------------------------


class Clock:
    """``time.monotonic``'s stand-in: each call one ``step`` later."""

    def __init__(self, step: float = 1.0) -> None:
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


@dataclass
class FakeMeasurer:
    """Canned looks in order; each call recorded; ``fail`` raises at a step."""

    base: str
    looks: list[cr.RetestLook] = field(default_factory=list)
    fail: dict[str, BaseException] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    changes: list[KeptChange] = field(default_factory=list)

    def _step(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise self.fail[name]

    def prepare(self) -> str:
        self._step("prepare")
        return self.base

    def commit_tip(self, patch: Path, label: str) -> str:
        self._step(f"commit {patch.name} {label}")
        return "f" * 40

    def connect(self) -> None:
        self._step("connect")

    def baseline(self) -> cr.BaselineLook:
        self._step("baseline")
        return cr.BaselineLook(0.0298, 0.0298, 0.0149, 41.5, 12)

    def profile(self) -> cr.ProfileLook:
        self._step("profile")
        return cr.ProfileLook(True, 7, 0, None)

    def retest(self, look: str, change: KeptChange) -> cr.RetestLook:
        self._step(look)
        self.changes.append(change)
        return self.looks.pop(0)

    def check_guards(self, run: LiveRun) -> None:
        self._step("guards")


def _lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def sink(tmp_path: Path) -> ResultsSink:
    return ResultsSink({"LIVE_RESULTS_PATH": str(tmp_path / "results.jsonl")})


def test_a_whole_case_records_three_looks_the_rule_and_every_timing(
    sink: ResultsSink, tmp_path: Path
) -> None:
    case = TIPS[0]  # X2-D tomli: archived floor 6.45 against 2.58
    looks = [
        _retest(0.19, 0.0701, True),
        _retest(0.18, 0.031, True),
        _retest(0.17, 0.05, False),
    ]
    measurer = FakeMeasurer(case.base_commit, looks=list(looks))
    recorder = cr.ReplayRecorder(sink)
    run = LiveRun("offline", cr.REPLAY_RUN_CAP_USD)
    found = cr.replay_case(case, measurer, recorder, run, clock=Clock())
    assert measurer.calls == [
        "prepare", f"commit delivered.patch {case.id}", "connect", "baseline",
        "profile", "m1", "m2", "m3", "guards",
    ]  # fmt: skip
    (change,) = {(c.trial_id, c.commit) for c in measurer.changes}
    assert change == (f"delivered-{case.dispatch}", "f" * 40)
    # the fake clock ticks 1 s a call: every span is 1 s, the case 14 s
    assert (found.connect_s, found.baseline_s, found.profile_s) == (1.0, 1.0, 1.0)
    assert [x.seconds for x in found.looks] == [1.0, 1.0, 1.0]
    assert found.setup_s == 1.0 and found.wall_s == 14.0 and found.stopped is None
    assert (found.rule_triggered, found.rule_verdict) == (True, True)
    rows = _lines(tmp_path / "results.jsonl")
    assert [r["kind"] for r in rows] == ["retest", "retest", "retest", "case"]
    m1 = rows[0]
    assert m1["experiment"] == cr.REPLAY_EXPERIMENT == "combine-replay"
    assert (m1["look"], m1["gain_pct"], m1["floor_pct"], m1["holds"]) == (
        "m1",
        19.0,
        7.01,
        True,
    )
    assert (m1["retest_s"], m1["tests_s"], m1["tests"], m1["tests_counted"]) == (
        1.0,
        1.0,
        "passed",
        3,
    )
    assert m1["over_k_baseline"] is True and rows[1]["over_k_baseline"] is False
    row = rows[-1]
    assert row["id"] == case.id and row["tip"] == cr.DELIVERED
    assert (row["archived_gain_pct"], row["archived_floor_pct"]) == (
        pytest.approx(18.751, abs=1e-3), pytest.approx(6.448, abs=1e-3),
    )  # fmt: skip
    assert row["archived_baseline_floor_pct"] == pytest.approx(2.582, abs=1e-3)
    assert row["archived_holds"] is True and row["archived_seconds"] == 757.5
    assert (row["baseline_floor_pct"], row["calibrated_floor_pct"]) == (2.98, 2.98)
    assert row["largest_gap_pct"] == 1.49 and row["baseline_tests"] == 12
    assert row["gains_pct"] == [19.0, 18.0, 17.0] and row["holds"] == [
        True,
        True,
        False,
    ]
    assert row["floors_pct"] == [7.01, 3.1, 5.0]
    assert row["floor_spread_pct"] == pytest.approx(3.91)
    assert (row["rule_k"], row["rule_triggered_m1"], row["rule_verdict"]) == (
        2.0,
        True,
        True,
    )
    assert (row["m1_holds"], row["m2_holds"]) == (True, True)
    assert (row["profile_ok"], row["profile_hotspots"], row["profile_error"]) == (
        True,
        7,
        None,
    )
    assert (row["connect_s"], row["baseline_s"], row["calibration_s"]) == (
        1.0,
        1.0,
        41.5,
    )
    assert (row["profile_s"], row["retest_s"], row["tests_s"]) == (
        1.0,
        [1.0] * 3,
        [1.0] * 3,
    )
    assert (row["setup_s"], row["wall_s"], row["stopped"]) == (1.0, 14.0, None)
    assert row["patch_sha256"] == cr.load_archived(case).sha256
    assert run.notes == [cr.note(found)] and "fires on m1" in run.notes[0]
    table = recorder.markdown()
    assert case.id in table and "19.0 / 7.01 / yes" in table and "41.5" in table
    lines = table.splitlines()
    rows_at = [i for i, x in enumerate(lines) if x.startswith(f"| {case.id} |")]
    assert len(rows_at) == 2
    for at in rows_at:  # each row as wide as its header
        assert lines[at].count("|") == lines[at - 2].count("|")


def test_markdown_runs_the_calibration_and_the_profile_with_no_tip(
    sink: ResultsSink, tmp_path: Path
) -> None:
    (case,) = [c for c in cr.CASES if c.tip == cr.NO_TIP]
    measurer = FakeMeasurer(case.base_commit)
    recorder = cr.ReplayRecorder(sink)
    found = cr.replay_case(
        case, measurer, recorder, LiveRun("x", 0.0), clock=Clock(0.5)
    )
    assert measurer.calls == ["prepare", "connect", "baseline", "profile", "guards"]
    assert found.looks == [] and found.profile_s == 0.5 and found.wall_s == 4.0
    (row,) = _lines(tmp_path / "results.jsonl")
    assert row["tip"] == cr.NO_TIP and row["patch"] is None and row["gains_pct"] == []
    assert (row["rule_triggered_m1"], row["rule_verdict"]) == (None, None)
    assert "no tip" in cr.note(found)


def test_a_case_without_the_profile_has_no_profile_timing(
    sink: ResultsSink, tmp_path: Path
) -> None:
    (case,) = [c for c in TIPS if not c.profile]
    looks = [_retest(0.1, 0.02, True)] * 3
    measurer = FakeMeasurer(case.base_commit, looks=list(looks))
    found = cr.replay_case(case, measurer, cr.ReplayRecorder(sink), LiveRun("x", 0.0),
                           clock=Clock())  # fmt: skip
    assert "profile" not in measurer.calls and found.profile is None
    assert (found.profile_s, found.rule_triggered, found.rule_verdict) == (
        None,
        False,
        True,
    )
    assert measurer.changes[0].trial_id == case.trial_id
    assert measurer.changes[0].hypothesis_id == "709d0168-c07b-4e64-94f0-6be7fdcd4ffd"
    row = _lines(tmp_path / "results.jsonl")[-1]
    assert (row["profile_ok"], row["profile_s"]) == (None, None)


def test_an_engine_stop_is_recorded_with_the_timings_so_far(
    sink: ResultsSink, tmp_path: Path
) -> None:
    case = TIPS[1]
    measurer = FakeMeasurer(
        case.base_commit, looks=[_retest(0.1, 0.02, True)],
        fail={"m2": EngineError("the noise floor is 100%")},
    )  # fmt: skip
    found = cr.replay_case(case, measurer, cr.ReplayRecorder(sink), LiveRun("x", 0.0),
                           clock=Clock())  # fmt: skip
    assert found.stopped == "the noise floor is 100%" and len(found.looks) == 1
    assert measurer.calls[-2:] == ["m2", "guards"]
    row = _lines(tmp_path / "results.jsonl")[-1]
    assert row["stopped"] == "the noise floor is 100%" and row["retest_s"] == [1.0]
    assert "stopped" in cr.note(found)


@pytest.mark.parametrize(
    ("fail", "match"),
    [
        ({}, "is not the archived"),  # the clone's base is another commit
        ({"prepare": CloneRefusedError("clone refused")}, "clone refused"),
        ({"commit": CloneRefusedError("does not apply")}, "does not apply"),
        ({"baseline": RunFailure("crashed")}, "crashed"),
    ],
)
def test_a_mismatch_or_a_crash_writes_the_error_row_then_fails(
    sink: ResultsSink, tmp_path: Path, fail: dict[str, BaseException], match: str
) -> None:
    case = TIPS[0]
    base = "e" * 40 if not fail else case.base_commit
    measurer = FakeMeasurer(base, fail=fail)
    measurer.fail = {(f"commit delivered.patch {case.id}" if k == "commit" else k): v
                     for k, v in fail.items()}  # fmt: skip
    recorder = cr.ReplayRecorder(sink)
    run = LiveRun("x", 0.0)
    with pytest.raises(Exception, match=match):
        cr.replay_case(case, measurer, recorder, run, clock=Clock())
    (row,) = _lines(tmp_path / "results.jsonl")
    assert (row["kind"], row["id"]) == ("error", case.id) and match in str(row["error"])
    assert "guards" not in measurer.calls
    assert recorder.errors and "error" in recorder.markdown()


@pytest.mark.parametrize(
    ("lost", "looks"),
    [(SKIPPED, ["m1", "m2"]), (NO_ROWS, ["m1", "m2", "m3"])],
    ids=["skipped", "no-rows"],
)
def test_a_look_that_did_not_measure_the_tip_fails_after_its_rows(
    sink: ResultsSink, tmp_path: Path, lost: cr.RetestLook, looks: list[str]
) -> None:
    """The combiner skipped the change (deterministic: the looks stop), or a
    RunFailure left no rows (m3 still runs): not a "holds: false" but an
    integrity failure, raised once every row is out."""
    case = TIPS[0]
    canned = [_retest(0.2, 0.02, True), lost, _retest(0.2, 0.03, True)]
    measurer = FakeMeasurer(case.base_commit, looks=canned)
    recorder = cr.ReplayRecorder(sink)
    with pytest.raises(cr.IntegrityError, match="m2 did not measure the tip"):
        cr.replay_case(case, measurer, recorder, LiveRun("x", 0.0), clock=Clock())
    assert measurer.calls[-len(looks) - 1 :] == [*looks, "guards"]
    rows = _lines(tmp_path / "results.jsonl")
    assert [r["kind"] for r in rows] == [*(["retest"] * len(looks)), "case", "error"]
    tips = [True, False, True][: len(looks)]
    assert [r["measured_tip"] for r in rows[: len(looks)]] == tips
    case_row = rows[len(looks)]
    assert case_row["not_measured"] == "m2" and case_row["rule_verdict"] is None
    assert case_row["measured_tip"] == tips
    assert "m2 did not measure the tip" in str(rows[-1]["error"])
    assert "| not measured |" in recorder.markdown()
    assert recorder.unmeasured() == [f"{case.id} ({len(looks) - 1} of 3)"]


def test_an_integrity_failure_measures_nothing(
    sink: ResultsSink, tmp_path: Path
) -> None:
    case = replace(TIPS[0], patch=str(TIPS[1].patch))  # declares another run's patch
    measurer = FakeMeasurer(case.base_commit)
    with pytest.raises(cr.IntegrityError, match="declares"):
        cr.replay_case(case, measurer, cr.ReplayRecorder(sink), LiveRun("x", 0.0))
    assert measurer.calls == []
    assert _lines(tmp_path / "results.jsonl")[0]["kind"] == "error"


def test_a_guard_breach_writes_the_measured_row_then_fails(
    sink: ResultsSink, tmp_path: Path
) -> None:
    case = TIPS[2]
    looks = [_retest(0.3, 0.07, True)] * 3
    measurer = FakeMeasurer(case.base_commit, looks=list(looks),
                            fail={"guards": AssertionError("unsandboxed launch")})  # fmt: skip
    with pytest.raises(AssertionError, match="unsandboxed"):
        cr.replay_case(case, measurer, cr.ReplayRecorder(sink), LiveRun("x", 0.0),
                       clock=Clock())  # fmt: skip
    (row,) = _lines(tmp_path / "results.jsonl")
    assert row["error"] == "guards: unsandboxed launch"
    measured = row["measured"]
    assert isinstance(measured, dict) and measured["gains_pct"] == [30.0] * 3


def test_a_tip_case_short_of_three_measured_looks_fails_the_job_at_the_end(
    sink: ResultsSink, tmp_path: Path
) -> None:
    """An EngineError stop is recorded and the run goes on, as does a case
    that failed on an unmeasured look; ``finish`` then fails the job after
    every case and the tables, naming each tip case with fewer than three
    measured looks. Three measured looks pass; markdown has no look by design."""
    recorder = cr.ReplayRecorder(sink)
    stopped, partial, whole = TIPS[1], TIPS[2], TIPS[0]
    stop = FakeMeasurer(
        stopped.base_commit, fail={"m1": EngineError("the floor is 100%")}
    )
    found = cr.replay_case(stopped, stop, recorder, LiveRun("x", 0.0), clock=Clock())
    assert found.stopped == "the floor is 100%" and found.looks == []
    late = FakeMeasurer(partial.base_commit,
                        looks=[_retest(0.2, 0.02, True), _retest(0.2, 0.02, True)],
                        fail={"m3": EngineError("stopped at m3")})  # fmt: skip
    cr.replay_case(partial, late, recorder, LiveRun("x", 0.0), clock=Clock())
    good = [_retest(0.2, 0.02, True)] * 3
    cr.replay_case(whole, FakeMeasurer(whole.base_commit, looks=list(good)), recorder,
                   LiveRun("x", 0.0), clock=Clock())  # fmt: skip
    (markdown,) = [c for c in cr.CASES if c.tip == cr.NO_TIP]
    cr.replay_case(markdown, FakeMeasurer(markdown.base_commit), recorder,
                   LiveRun("x", 0.0), clock=Clock())  # fmt: skip
    named = [f"{stopped.id} (0 of 3)", f"{partial.id} (2 of 3)"]
    assert recorder.unmeasured() == named
    echoed: list[str] = []
    with pytest.raises(AssertionError, match="fewer than 3 measured looks"):
        recorder.finish(echoed.append)
    tail = next(line for line in echoed if "fewer than 3 measured looks" in line)
    assert all(name in tail for name in named)  # the table names each, first
    quiet = cr.ReplayRecorder(sink)
    cr.replay_case(markdown, FakeMeasurer(markdown.base_commit), quiet,
                   LiveRun("x", 0.0), clock=Clock())  # fmt: skip
    assert quiet.unmeasured() == []
    quiet.finish(echoed.append)


def test_the_recorder_writes_its_table_to_the_job_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    recorder = cr.ReplayRecorder(ResultsSink({"GITHUB_STEP_SUMMARY": str(summary)}))
    found = _result(
        _retest(0.2, 0.07, True),
        _retest(0.2, 0.02, False),
        _retest(0.2, 0.02, True),
        base=None,
    )  # three measured looks: the job may pass
    found.profile = cr.ProfileLook(False, 0, 1, "EngineError: the profiler crashed")
    recorder.record(found, LiveRun("x", 0.0))
    recorder.record_error("X2-P-1-sqlparse", LiveRun("x", 0.0), "boom")
    echoed: list[str] = []
    recorder.finish(echoed.append)
    text = summary.read_text()
    assert (
        "Combine re-measure replay" in text
        and "| X2-P-1-sqlparse | error | boom |" in text
    )
    assert "no (0 hotspots, 1 notes)" in text and "1 case(s), 1 error(s)" in text
    assert echoed[0].endswith("written to the job summary")
    for line in text.splitlines():  # error rows as wide as the verdict table
        if line.startswith("| X2-P-1-sqlparse"):
            assert line.count("|") == text.splitlines()[2].count("|")


# ---------------------------------------------------------------------------
# The timing seams: every launch and the calibration, on a fake clock
# ---------------------------------------------------------------------------


SAMPLE = cast(RunSample, object())  # what the inner run returns, handed on as is


@dataclass
class FakeRun:
    """A ``RunOnce`` that returns ``sample`` or raises ``failure``."""

    failure: RunFailure | None = None
    argv: list[Sequence[str]] = field(default_factory=list)

    def __call__(
        self, argv: Sequence[str], *args: object, **kwargs: object
    ) -> RunSample:
        self.argv.append(argv)
        if self.failure is not None:
            raise self.failure
        return SAMPLE


def test_timed_run_times_each_launch_and_tells_the_suite_apart() -> None:
    inner = FakeRun()
    timed = cr.TimedRun(inner, clock=Clock(0.25))
    workload = ["/usr/bin/python3", "bench/bench_tomli.py"]
    pytest_argv = ["/usr/bin/python3", "-m", "pytest", "--junitxml=x", "-q", "tests"]
    unittest_argv = ["/usr/bin/python3", "-m", "unittest", "discover", "-s", "tests"]
    for argv in (workload, pytest_argv, workload):
        assert timed(argv, Path("/w"), {}, None, 1.0, None) is SAMPLE  # type: ignore[arg-type]
    mark = len(timed.spans)
    assert timed.suite_seconds(0) == 0.25 and timed.suite_seconds(mark) is None
    timed(unittest_argv, Path("/w"), {}, None, 1.0, None, fresh_dirs=())  # type: ignore[arg-type]
    assert timed.suite_seconds(mark) == 0.25 and timed.suite_seconds(0) == 0.5
    assert [s.suite for s in timed.spans] == [False, True, False, True]
    inner.failure = RunFailure("the suite timed out")
    with pytest.raises(RunFailure):
        timed(pytest_argv, Path("/w"), {}, None, 1.0, None)  # type: ignore[arg-type]
    assert timed.spans[-1] == cr.Span(True, 0.25)  # a failed launch is timed too
    assert len(inner.argv) == 5


@dataclass
class FakeCalibrator:
    calls: list[tuple[str, str, int]] = field(default_factory=list)

    def calibrate(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str, blocks: int
    ) -> NoiseCalibration:
        self.calls.append((run_id, commit, blocks))
        if run_id == "bad":
            raise EngineError("calibration failed")
        return NoiseCalibration(blocks=blocks, gaps={"w": 0.01}, floor=0.02)


def test_timed_calibrator_hands_the_call_on_and_times_it() -> None:
    inner = FakeCalibrator()
    assert cr.TimedCalibrator(inner).seconds is None
    timed = cr.TimedCalibrator(inner, Clock(2.0))
    found = timed.calibrate((), run_id="r", commit="c", blocks=3)
    assert (
        found.floor == 0.02 and inner.calls == [("r", "c", 3)] and timed.seconds == 2.0
    )
    with pytest.raises(EngineError):
        timed.calibrate((), run_id="bad", commit="c", blocks=3)
    assert timed.seconds == 4.0


# ---------------------------------------------------------------------------
# The real measurer on a local repository in the required sandbox
# ---------------------------------------------------------------------------

SLOW = '''"""A tiny library with a quadratic hot spot."""


def unique(items):
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
'''
FAST = '''"""A tiny library with a quadratic hot spot."""


def unique(items):
    seen = set()
    found = []
    for item in items:
        if item not in seen:
            seen.add(item)
            found.append(item)
    return found
'''
SUITE = """import unittest

import pkg


class TestUnique(unittest.TestCase):
    def test_keeps_first_occurrences_in_order(self):
        self.assertEqual(pkg.unique([3, 1, 3, 2, 1]), [3, 1, 2])
"""
BENCH = """import hashlib

import pkg

found = pkg.unique([i % 1500 for i in range(6000)])
print(f"unique={len(found)} sha256={hashlib.sha256(repr(found).encode()).hexdigest()}")
"""


def _require_sandbox() -> None:
    problem = _sandbox_problem(sys.platform)
    if problem is not None:
        required = ("REQUIRE_NETWORK_SANDBOX", "REQUIRE_FS_SANDBOX")
        if any(os.environ.get(name) == "1" for name in required):
            pytest.fail(f"sandbox required but unavailable: {problem}")
        pytest.skip(f"the host cannot sandbox: {problem}")


@pytest.fixture
def local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    _require_sandbox()
    root = Path(os.path.realpath(tmp_path))
    (root / "wt-root").mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    for key, value in {**cr.REPLAY_SETTINGS, "NOISE_CALIBRATION_BLOCKS": 1}.items():
        monkeypatch.setattr(settings, key, value)
    yield root


def _library(source: Path) -> tuple[OssRepo, cr.Prepare]:
    repo = replace(
        ideas_x2.LIBRARIES["tomli"], name="pkg", package="pkg", module_root="pkg",
        test_command=("python", "-m", "unittest", "discover", "-s", "tests"),
    )  # fmt: skip
    files = {"pkg/__init__.py": SLOW, "tests/__init__.py": "", "tests/test_pkg.py": SUITE,
             repo.bench_path: BENCH}  # fmt: skip
    for rel, text in files.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_text(text, encoding="utf-8")

    def prepare(dest: Path) -> UserRepo:
        return make_repo(source, dest)

    return repo, prepare


def _fast_patch(root: Path) -> str:
    """The set-based fix as ``git diff`` writes it against the base."""
    probe = make_repo(root / "source", root / "probe")
    (probe.path / "pkg" / "__init__.py").write_text(FAST, encoding="utf-8")
    return git(probe.path, "diff", "--no-color") + "\n"


def test_the_engine_measurer_replays_a_tip_through_the_engines_own_steps(
    local: Path, sink: ResultsSink, tmp_path: Path
) -> None:
    """Preflight, define, the baseline node with its calibration, the
    profile node and the combine node's re-test three times, every launch
    sandboxed; no request, the user's repository as it was after the tip."""
    repo, prepare = _library(local / "source")
    patch = local / "fast.patch"
    patch.write_text(_fast_patch(local), encoding="utf-8")
    clock = Clock(0.0)  # time stands still: the spans are 0, but recorded
    case_root = local / "X2-D-1-pkg"  # not there yet: prepare makes it
    measurer = cr.EngineMeasurer(repo, case_root, Isolation("required", None),
                                 run_id="replay-0", prepare=prepare, clock=clock)  # fmt: skip
    assert not case_root.exists()
    assert measurer.prepare() == measurer.user.base
    assert measurer.user.path == case_root / "user"
    tip = measurer.commit_tip(patch, "pkg-case")
    assert git(measurer.user.path, "rev-parse", f"{tip}^") == measurer.user.base
    assert git(measurer.user.path, "rev-parse", "refs/replay/pkg-case") == tip
    measurer.connect()
    base = measurer.baseline()
    assert base.floor is not None and base.floor >= 0.02
    assert base.calibrated is not None and base.calibration_s == 0.0
    assert base.tests == 1 and base.largest_gap is not None
    profile = measurer.profile()
    assert profile.ok and profile.hotspots >= 1 and profile.error is None
    change = KeptChange("replay-pkg", "combination", "replay", tip, 0.0, None)
    looks = [measurer.retest(name, change) for name in cr.LOOKS]
    for look in looks:
        assert look.measured_tip and look.rows
        assert look.applied == 1 and look.tests == "passed" and look.tests_counted == 1
        assert look.gain is not None and look.gain > 0.3, look.reason
        assert look.floor is not None and look.tests_s == 0.0
        assert look.holds is (look.outcome == "keep")
    run = LiveRun("offline", cr.REPLAY_RUN_CAP_USD)
    measurer.check_guards(run)
    phases = measurer.launches.phases()
    assert phases <= cr.REPLAY_PHASES
    assert {"preflight", "baseline", "calibrate", "profile", "combine"} <= phases
    assert run.capture.exchanges == [] and run.records == []


def test_the_engine_measurer_marks_a_tip_that_crashes_as_not_measured(
    local: Path,
) -> None:
    """A tip whose workload crashes: the combiner applied it, but its
    RunFailure left no rows, so the look did not measure the tip."""
    repo, prepare = _library(local / "source")
    crash = _fast_patch(local).replace("+    seen = set()", "+    raise SystemExit(3)")
    patch = local / "crash.patch"
    patch.write_text(crash, encoding="utf-8")
    measurer = cr.EngineMeasurer(repo, local / "crash", Isolation("required", None),
                                 run_id="replay-6", prepare=prepare)  # fmt: skip
    measurer.prepare()
    tip = measurer.commit_tip(patch, "pkg-crash")
    measurer.connect()
    measurer.baseline()
    found = measurer.retest("m1", KeptChange("t", "h", "v", tip, 0.0, None))
    assert (found.applied, found.rows, found.measured_tip) == (1, False, False)
    assert found.holds is False


def test_the_engine_measurer_refuses_a_patch_that_does_not_apply(local: Path) -> None:
    repo, prepare = _library(local / "source")
    bad = local / "bad.patch"
    bad.write_text(
        _fast_patch(local).replace("-    seen = []", "-    seen = {}"), encoding="utf-8"
    )
    measurer = cr.EngineMeasurer(repo, local, Isolation("required", None),
                                 run_id="replay-1", prepare=prepare)  # fmt: skip
    measurer.prepare()
    with pytest.raises(cr.IntegrityError, match="does not apply"):
        measurer.commit_tip(bad, "pkg-bad")


def test_the_engine_measurer_records_a_profile_that_fails(
    local: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, prepare = _library(local / "source")
    measurer = cr.EngineMeasurer(repo, local, Isolation("required", None),
                                 run_id="replay-2", prepare=prepare)  # fmt: skip
    measurer.prepare()
    measurer.connect()

    def broken(state: object) -> object:
        raise EngineError("the profiler refused")

    monkeypatch.setitem(measurer.nodes, "profile", broken)
    found = measurer.profile()
    assert (found.ok, found.hotspots, found.error) == (
        False,
        0,
        "EngineError: the profiler refused",
    )


def test_the_engine_measurer_guards_name_each_breach(local: Path) -> None:
    repo, prepare = _library(local / "source")
    measurer = cr.EngineMeasurer(repo, local, Isolation("required", None),
                                 run_id="replay-3", prepare=prepare)  # fmt: skip
    with pytest.raises(AssertionError, match="not prepared"):
        _ = measurer.user
    with pytest.raises(AssertionError, match="not connected"):
        measurer.baseline()
    measurer.prepare()
    measurer.connect()
    run = LiveRun("offline", 0.0)
    measurer.check_guards(run)  # the preflight alone ran: still clean
    (measurer.user.path / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(AssertionError, match="user repository changed"):
        measurer.check_guards(run)
    loose = cr.EngineMeasurer(repo, local, Isolation("best_effort", "no unshare"),
                              run_id="replay-4", prepare=prepare)  # fmt: skip
    with pytest.raises(AssertionError, match="isolation not required"):
        loose.check_guards(run)
    idle = cr.EngineMeasurer(repo, local / "idle", Isolation("required", None),
                             run_id="replay-5", prepare=prepare)  # fmt: skip
    with pytest.raises(AssertionError, match="no launch"):
        idle.check_guards(run)


def test_replay_live_runs_a_case_on_the_engine_measurer(
    local: Path, sink: ResultsSink, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``replay_live`` wires the case's library and a fresh measurer."""
    seen: dict[str, object] = {}

    class Spy(FakeMeasurer):
        def __init__(
            self, repo: object, root: Path, isolation: Isolation, **kw: object
        ) -> None:
            super().__init__(cr.CASES[-1].base_commit)
            seen.update(repo=repo, root=root, isolation=isolation, **kw)

    monkeypatch.setattr(cr, "EngineMeasurer", Spy)
    found = cr.replay_live(cr.CASES[-1], LiveRun("x", 0.0), local,
                           Isolation("required", None), cr.ReplayRecorder(sink))  # fmt: skip
    assert found.case == cr.CASES[-1] and seen["repo"] is ideas_x2.LIBRARIES["markdown"]
    assert seen["root"] == local / cr.CASES[-1].id and seen["run_id"] == "replay-4"


# ---------------------------------------------------------------------------
# The settings the X2 arms measured under
# ---------------------------------------------------------------------------


def test_the_replay_settings_are_the_x2_arms_measurement_settings() -> None:
    """ci.yml's step3 rule and the op-count judge: what X2-D and X2-P ran."""
    step3 = settings.model_copy(
        update={
            "PAIRED_TRIALS": True,
            "CONFIRM_WINNERS": True,
            "NOISE_CALIBRATION_BLOCKS": 3,
        }
    )
    pinned = {"MIN_RUNS", "NOISE_MULTIPLIER", "NOISE_GAP_MULTIPLIER", "MIN_RELATIVE_GAIN",
              "DEFAULT_OUTPUT_CHECK", "SHADOW_VERIFY", "TEST_TIMEOUT_S",
              "SCALING_JUDGE", "SITE_STACKS"}  # fmt: skip
    assert pinned <= set(cr.REPLAY_SETTINGS)
    defaults = {k: Settings.model_fields[k].default for k in pinned}
    assert {k: cr.REPLAY_SETTINGS[k] for k in pinned} == defaults  # as the arms ran
    assert cr.REPLAY_SETTINGS["SHADOW_VERIFY"] == "off"
    step3 = step3.model_copy(update=defaults)
    for arm in (ideas_x2.X2_D, ideas_x2.X2_P):
        assert not pinned & set(arm.update), arm.key  # neither arm moves one
        cr.check_settings(ideas_x2.arm_settings(arm, step3))
    assert {c.arm for c in cr.CASES} == {"X2-D", "X2-P"}
    for key, value in cr.REPLAY_SETTINGS.items():
        with pytest.raises(ValueError, match=key):
            cr.check_settings(
                step3.model_copy(update={key: "x" if value is True else 9})
            )


# ---------------------------------------------------------------------------
# The minutes and the ci.yml row
# ---------------------------------------------------------------------------


def _upper_bounds() -> dict[str, int]:
    """Per library, the most an X2-D or X2-P run spent per measured unit:
    its measured seconds over (trials + confirmations + the combine)."""
    best: dict[str, float] = {}
    for path in sorted((ARCHIVE / "live").glob("ideas-x2-X2-[DP]-*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for run in (r for r in rows if r["experiment"] == "ideas-x2-run"):
            trialled = sum(
                1 for r in rows if r["experiment"] == "ideas-x2-hypothesis"
                and r["repo"] == run["repo"] and r["round"] is not None
            )  # fmt: skip
            unit = run["seconds_measured"] / (trialled + run["kept"] + 1)
            best[run["repo"]] = max(best.get(run["repo"], 0.0), unit)
    return {repo: math.ceil(unit) for repo, unit in best.items()}


def test_the_unit_seconds_are_the_archived_runs_upper_bounds() -> None:
    assert dict(cr.UNIT_S) == _upper_bounds()
    assert cr.case_units(TIPS[0]) == 9 and cr.case_units(cr.CASES[-1]) == 6
    assert cr.case_units(TIPS[3]) == 8  # the fallback case: no profile
    total = math.fsum(
        cr.SETUP_S + cr.case_units(c) * cr.UNIT_S[c.library] for c in cr.CASES
    )
    assert cr.plan_minutes() == math.ceil(total / 60) == 45
    assert cr.JOB_SETUP_MINUTES + 2 * cr.plan_minutes() <= cr.REPLAY_JOB_MINUTES <= 360


def test_the_need_is_zero_and_the_live_module_runs_what_this_file_checks() -> None:
    assert cr.replay_need() == cr.REPLAY_RUN_CAP_USD == 0.0
    path = TESTS_DIR / "live" / "test_combine_replay_live.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    marks = [ast.unparse(n.value) for n in tree.body
             if isinstance(n, ast.Assign) and [ast.unparse(t) for t in n.targets] == ["pytestmark"]]  # fmt: skip
    assert marks == ["pytest.mark.live"]
    tests = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]  # fmt: skip
    assert tests == ["test_the_archived_tip_is_measured_again"]
    assert "live(REPLAY_RUN_CAP_USD)" in source and "replay_live(" in source
    assert "check_settings()" in source and "CASES, ids=[c.id for c in CASES]" in source


def test_the_ci_row_need_timeout_rule_and_stage_a_ignore() -> None:
    assert "combine-replay" in _ci_block("      suite:", "      mode:")
    cap_help = _ci_block("      suite_cap_usd:", "\n\n")
    assert "combine-replay 0 (no request, but the cap must be above 0)" in cap_help
    block = _ci_block("  live-smoke:", "    defaults:")
    assert f"inputs.suite == 'combine-replay' && {cr.REPLAY_JOB_MINUTES} ||" in block
    assert (
        "combine-replay" in block.split("timeout-minutes:")[0]
    )  # the estimate's comment
    assert EXPERIMENT_MINUTES["combine-replay"] == cr.REPLAY_JOB_MINUTES
    script = _run_script()
    row = "combine-replay) paths=(tests/live/test_combine_replay_live.py); need=0 ;;"
    assert row in script
    rule = script[script.index('case "${INPUT_SUITE}" in\n  noise |') :]
    rule = rule[: rule.index("esac")]
    step3 = [line for line in rule.splitlines() if "noise_rule=step3" in line]
    assert any(re.search(r"\bcombine-replay\b", line) for line in step3)
    assert "--ignore=tests/live/test_combine_replay_live.py" in script
    assert CI_WORKFLOW.read_text(encoding="utf-8").count("combine-replay") >= 6


def test_the_ci_run_step_exports_the_x2_measurement_settings(tmp_path: Path) -> None:
    for name in ("ok", "zero", "other"):
        (tmp_path / name).mkdir()
    code, output, calls = _dispatch(
        tmp_path / "ok", "combine-replay", "claude-opus-5-5", "1"
    )
    assert code == 0, output
    argv = "run pytest tests/live/test_combine_replay_live.py -m live --no-cov -n 0 -rA"
    assert calls.splitlines()[0] == argv
    rule = (tmp_path / "ok" / "rule.txt").read_text(encoding="utf-8").split()
    assert rule[:3] == ["true", "true", "3"]
    env = (tmp_path / "ok" / "env.txt").read_text(encoding="utf-8").splitlines()
    assert "OP_COUNT_JUDGE=true" in env and "LIVE_REQUIRE_CASES=combine-replay" in env
    code, output, calls = _dispatch(
        tmp_path / "zero", "combine-replay", "claude-opus-5-5", "0"
    )
    assert (code, calls) == (1, "") and "above 0" in output
    code, output, _ = _dispatch(tmp_path / "other", "noise", "claude-opus-5-5", "1")
    other = (tmp_path / "other" / "env.txt").read_text(encoding="utf-8").splitlines()
    assert code == 0 and not any(x.startswith("OP_COUNT_JUDGE=") for x in other), output
