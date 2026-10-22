"""Tests for the deterministic fakes and the ScriptedEditor (unit U3).

``execution/fakes.py`` gives every Step 2 seam a scripted double that records
its calls, so node tests never touch git, processes or Claude. The
``ScriptedEditor`` is the one fake with effects: it applies an edit set from
``tests/fixtures/dedupe_edits/<title>/`` to a worktree, so the E2E exercises
the real capture and anti-cheat on the fixture's h1 (copy), h2 (deletes a
test) and h6 (adds a symlink) edits.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.errors import DeliveryError, PreflightError
from autonomous_ai_agents.common.models import (
    ChangeClass,
    CombineSkip,
    Guardrail,
    GuardrailKind,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Project,
    ProjectUnderstanding,
    Workload,
)
from autonomous_ai_agents.execution.fakes import (
    FAKE_COMMIT,
    CombineCall,
    FakeCombiner,
    FakeEditor,
    FakePreflight,
    FakeProfiler,
    FakePublisher,
    FakeUnderstander,
    ScriptedEditor,
)
from autonomous_ai_agents.execution.protocols import (
    BranchPublisher,
    CodeEditor,
    CombineMeasured,
    Combiner,
    EditResult,
    EditTask,
    KeptChange,
    Preflight,
    PreflightReport,
    Profiler,
    ProjectUnderstander,
    TrialBrief,
    UnderstandResult,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEDUPE_REPO = FIXTURES / "dedupe_repo"
DEDUPE_EDITS = FIXTURES / "dedupe_edits"
CORE = "dedupe/core.py"

PROJECT = Project(
    name="dedupe", root_path="/home/dev/dedupe", test_command=("python", "-m", "t")
)
WORKLOAD = Workload(project_id=PROJECT.id, name="main", command=("python", "-m", "x"))
GUARDRAIL = Guardrail(
    project_id=PROJECT.id, kind=GuardrailKind.tests_pass, description="tests pass"
)
HOTSPOT = Hotspot(
    project_id=PROJECT.id,
    workload_id=WORKLOAD.id,
    file_path=CORE,
    symbol="unique_in_order",
    self_time_s=0.8,
    total_time_s=0.84,
    share=0.95,
)
BRIEF = TrialBrief(understanding=None, hotspots=(), protected=())


def _hypothesis(title: str) -> Hypothesis:
    return Hypothesis(
        project_id=PROJECT.id,
        source=HypothesisSource.playbook,
        title=title,
        rationale="scripted",
        change_class=ChangeClass.efficiency,
        expected_gain=0.5,
        provability=0.9,
        risk=0.1,
    )


def _task(title: str) -> EditTask:
    return EditTask(hypothesis=_hypothesis(title), brief=BRIEF, boundary="b0undary")


def _snapshot(root: Path) -> dict[str, bytes]:
    """Every entry under ``root``: file bytes, or ``->target`` for a symlink."""
    found: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [*dirnames, *filenames]:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                found[rel] = b"->" + os.fsencode(os.readlink(path))
            elif path.is_file():
                found[rel] = path.read_bytes()
    return found


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """A fresh copy of the dedupe_repo fixture (interpreter caches left out)."""
    target = tmp_path / "wt"
    shutil.copytree(DEDUPE_REPO, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


@pytest.fixture
def edits(tmp_path: Path) -> Path:
    """An empty edits dir the test fills with its own edit sets."""
    path = tmp_path / "edits"
    path.mkdir()
    return path


def _edit_set(edits: Path, title: str, files: dict[str, str] | None = None) -> Path:
    root = edits / title
    for rel, text in (files or {}).items():
        target = root / "files" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_every_fake_satisfies_its_protocol(tmp_path: Path) -> None:
    """
    GIVEN each fake and the ScriptedEditor
    WHEN checked against the runtime-checkable seam protocols
    THEN each conforms to its own protocol
    """
    assert isinstance(FakePreflight(), Preflight)
    assert isinstance(FakeProfiler(), Profiler)
    assert isinstance(FakeUnderstander(UnderstandResult(None)), ProjectUnderstander)
    assert isinstance(FakeCombiner([]), Combiner)
    assert isinstance(FakePublisher(), BranchPublisher)
    assert isinstance(FakeEditor({}), CodeEditor)
    assert isinstance(ScriptedEditor(tmp_path), CodeEditor)


# ---------------------------------------------------------------------------
# FakePreflight
# ---------------------------------------------------------------------------


def test_fake_preflight_echoes_the_inputs_by_default() -> None:
    """
    GIVEN a FakePreflight with no report and no error
    WHEN it checks a project
    THEN the report pins FAKE_COMMIT, echoes the workloads and test command,
         reports both isolation modes required, and the call is recorded
    """
    preflight = FakePreflight()

    report = preflight.check(PROJECT, [WORKLOAD], [GUARDRAIL])

    assert report == PreflightReport(
        head_commit=FAKE_COMMIT,
        dirty_entries=(),
        git_version=(2, 43, 0),
        network="required",
        fs="required",
        workloads=(WORKLOAD,),
        test_command=PROJECT.test_command,
        extra_protected=(),
    )
    assert preflight.calls == [(PROJECT, (WORKLOAD,), (GUARDRAIL,))]


def test_fake_preflight_returns_a_scripted_report_or_raises_an_error() -> None:
    """
    GIVEN one FakePreflight with a report and one with an error
    WHEN each checks a project
    THEN the first returns the report and the second raises, both recorded
    """
    report = FakePreflight().check(PROJECT, [WORKLOAD], [])
    dirty = replace(report, dirty_entries=(" M x.py",))
    scripted, failing = FakePreflight(dirty), FakePreflight(error=PreflightError("lfs"))

    assert scripted.check(PROJECT, [WORKLOAD], []) is dirty
    with pytest.raises(PreflightError, match="lfs"):
        failing.check(PROJECT, [], [GUARDRAIL])
    assert failing.calls == [(PROJECT, (), (GUARDRAIL,))]


def test_fake_preflight_refuses_both_a_report_and_an_error() -> None:
    """
    GIVEN both a report and an error
    WHEN a FakePreflight is built
    THEN a ValueError is raised (the script would be ambiguous)
    """
    report = FakePreflight().check(PROJECT, [], [])

    with pytest.raises(ValueError, match="report or an error"):
        FakePreflight(report, error=PreflightError("x"))


# ---------------------------------------------------------------------------
# FakeProfiler and FakeUnderstander
# ---------------------------------------------------------------------------


def test_fake_profiler_returns_its_script_and_records_run_id_and_commit() -> None:
    """
    GIVEN a FakeProfiler scripted with one hotspot and a note
    WHEN it profiles a workload for run r1 at a commit
    THEN it returns them and records the workloads, run id and commit
    """
    profiler = FakeProfiler((HOTSPOT,), ("profile_skipped: -c",))

    result = profiler.profile([WORKLOAD], run_id="r1", commit=FAKE_COMMIT)

    assert result.hotspots == (HOTSPOT,)
    assert result.notes == ("profile_skipped: -c",)
    assert profiler.calls == [((WORKLOAD,), "r1", FAKE_COMMIT)]


def test_fake_profiler_raises_a_scripted_error_after_recording() -> None:
    """
    GIVEN a FakeProfiler scripted with an error (an editable install)
    WHEN it profiles
    THEN the error propagates and the call is still recorded
    """
    profiler = FakeProfiler(error=RuntimeError("frame under the user's checkout"))

    with pytest.raises(RuntimeError, match="user's checkout"):
        profiler.profile([WORKLOAD], run_id="r1", commit="c")
    assert profiler.calls == [((WORKLOAD,), "r1", "c")]


def test_fake_understander_returns_its_result_and_snapshots_the_budget() -> None:
    """
    GIVEN a FakeUnderstander scripted with a result
    WHEN it is called with a budget that already spent 0.25 of 1.0
    THEN it returns the result, leaves the budget alone and records
         (project, workloads, commit, cap, spent)
    """
    understanding = ProjectUnderstanding(
        language="python", summary="dedupe", served_by_model="m"
    )
    result = UnderstandResult(understanding, ("dropped id w9",), 0.03, 900)
    fake = FakeUnderstander(result)
    budget = Budget(1.0, 0.25)

    assert fake.understand(PROJECT, [WORKLOAD], commit="c", budget=budget) is result
    assert (budget.spent_usd, budget.tokens) == (0.25, 0)
    assert fake.calls == [(PROJECT, (WORKLOAD,), "c", 1.0, 0.25)]


def test_fake_understander_raises_its_error_and_needs_exactly_one_script() -> None:
    """
    GIVEN a FakeUnderstander with an error, and attempts with neither or both
    WHEN it is called or built
    THEN the error propagates, and construction refuses the ambiguous scripts
    """
    fake = FakeUnderstander(error=PreflightError("no key"))

    with pytest.raises(PreflightError, match="no key"):
        fake.understand(PROJECT, [], commit="c", budget=Budget(1.0))
    assert len(fake.calls) == 1
    with pytest.raises(ValueError, match="exactly one"):
        FakeUnderstander()
    with pytest.raises(ValueError, match="exactly one"):
        FakeUnderstander(UnderstandResult(None), error=RuntimeError("x"))


# ---------------------------------------------------------------------------
# FakeCombiner and FakePublisher
# ---------------------------------------------------------------------------


def _measured(tip: str) -> CombineMeasured:
    return CombineMeasured(
        tip_commit=tip, applied=("t1",), skipped=(), baseline=(), combined=()
    )


def test_fake_combiner_replays_results_in_order_and_records_kept_lists() -> None:
    """
    GIVEN a FakeCombiner scripted with a result, an error and a second result
    WHEN it is called four times
    THEN calls 1 and 3 return the results, call 2 raises, call 4 raises an
         IndexError naming the call, and every kept list is recorded as a tuple
    """
    kept = [KeptChange("t1", "h1", "v1", "c1", 0.9, 0.5)]
    skip = CombineSkip(trial_id="t5", reason="conflict")
    second = CombineMeasured("tip2", ("t1",), (skip,), (), ())
    fake = FakeCombiner([_measured("tip1"), DeliveryError("merge failed"), second])

    assert (
        fake.combine(
            "r1", PROJECT, "base", kept, [WORKLOAD], baseline_count=3
        ).tip_commit
        == "tip1"
    )
    with pytest.raises(DeliveryError, match="merge failed"):
        fake.combine("r1", PROJECT, "base", kept, [WORKLOAD])
    assert fake.combine("r1", PROJECT, "base", kept[:0], [WORKLOAD]) is second
    with pytest.raises(IndexError, match="call 4"):
        fake.combine("r1", PROJECT, "base", kept, [])
    assert [call.kept for call in fake.calls] == [
        tuple(kept),
        tuple(kept),
        (),
        tuple(kept),
    ]
    assert fake.calls[0] == CombineCall(
        "r1", PROJECT, "base", tuple(kept), (WORKLOAD,), 3
    )
    assert [call.baseline_count for call in fake.calls] == [3, None, None, None]


def test_fake_publisher_returns_the_scripted_diff_or_raises() -> None:
    """
    GIVEN a FakePublisher with a diff, and one with a DeliveryError
    WHEN each publishes a branch
    THEN the first returns the diff, the second raises, both are recorded
    """
    publisher = FakePublisher("diff --git a/x b/x")
    failing = FakePublisher(error=DeliveryError("ref exists"))

    assert publisher.publish(PROJECT, "engine/run-r1", "tip", "base") == (
        "diff --git a/x b/x"
    )
    with pytest.raises(DeliveryError, match="ref exists"):
        failing.publish(PROJECT, "engine/run-r1", "tip", "base")
    assert publisher.calls == [(PROJECT, "engine/run-r1", "tip", "base")]
    assert len(failing.calls) == 1
    assert FakePublisher().publish(PROJECT, "b", "t", "s") == ""


# ---------------------------------------------------------------------------
# FakeEditor
# ---------------------------------------------------------------------------


def test_fake_editor_replays_results_by_title_with_a_default(tmp_path: Path) -> None:
    """
    GIVEN a FakeEditor scripted for h1, an error for h2 and a default
    WHEN it edits h1, h2 and an unscripted h9
    THEN h1 gets its result, h2 raises, h9 gets the default, and each call
         records the worktree, task and a (cap, spent) budget snapshot
    """
    h1 = EditResult(written={CORE: 10}, cost_usd=0.1, tokens_used=50)
    default = EditResult(error="no edit")
    fake = FakeEditor({"h1": h1, "h2": RuntimeError("budget gone")}, default=default)
    budget = Budget(2.0, 0.5)

    assert fake.edit(tmp_path, _task("h1"), budget) is h1
    with pytest.raises(RuntimeError, match="budget gone"):
        fake.edit(tmp_path, _task("h2"), budget)
    assert fake.edit(tmp_path, _task("h9"), budget) is default
    assert [(c.task.hypothesis.title, c.cap_usd, c.spent_usd) for c in fake.calls] == [
        ("h1", 2.0, 0.5),
        ("h2", 2.0, 0.5),
        ("h9", 2.0, 0.5),
    ]
    assert fake.calls[0].worktree == tmp_path


def test_fake_editor_without_a_script_or_default_raises_key_error(
    tmp_path: Path,
) -> None:
    """
    GIVEN a FakeEditor with no script for the title and no default
    WHEN it edits
    THEN a KeyError names the title, and the call is still recorded
    """
    fake = FakeEditor({})

    with pytest.raises(KeyError, match="h3"):
        fake.edit(tmp_path, _task("h3"), Budget(1.0))
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# ScriptedEditor on the real dedupe fixture
# ---------------------------------------------------------------------------


def test_scripted_editor_h1_copies_the_edited_module(worktree: Path) -> None:
    """
    GIVEN the dedupe_repo fixture and edit set h1 (a set-based core.py)
    WHEN the ScriptedEditor applies it
    THEN core.py holds the edit's bytes, written reports exactly those bytes,
         nothing was spent and the turn ended normally
    """
    expected = (DEDUPE_EDITS / "h1" / "files" / CORE).read_bytes()
    budget = Budget(0.0)

    result = ScriptedEditor(DEDUPE_EDITS).edit(worktree, _task("h1"), budget)

    assert result == EditResult(written={CORE: len(expected)})
    assert (worktree / CORE).read_bytes() == expected
    assert (budget.spent_usd, budget.tokens) == (0.0, 0)


def test_scripted_editor_h2_deletes_a_protected_test_and_reports_it(
    worktree: Path,
) -> None:
    """
    GIVEN edit set h2 (the set edit plus a _delete of tests/test_core.py)
    WHEN the ScriptedEditor applies it
    THEN the test file is gone and written records it with 0 bytes: the
         editor does not enforce protected paths, capture must see this
    """
    result = ScriptedEditor(DEDUPE_EDITS).edit(worktree, _task("h2"), Budget(1.0))

    assert result.error is None
    assert dict(result.written) == {
        CORE: len((DEDUPE_EDITS / "h2" / "files" / CORE).read_bytes()),
        "tests/test_core.py": 0,
    }
    assert not (worktree / "tests" / "test_core.py").exists()


def test_scripted_editor_h6_creates_the_symlink_verbatim(worktree: Path) -> None:
    """
    GIVEN edit set h6 (the set edit plus a _symlink dedupe/fast.py -> core.py)
    WHEN the ScriptedEditor applies it
    THEN dedupe/fast.py is a symlink whose target is "core.py" byte for byte
         and written records the target's length
    """
    result = ScriptedEditor(DEDUPE_EDITS).edit(worktree, _task("h6"), Budget(1.0))

    link = worktree / "dedupe" / "fast.py"
    assert result.error is None
    assert link.is_symlink()
    assert os.readlink(link) == "core.py"
    assert result.written["dedupe/fast.py"] == len(b"core.py")
    assert set(result.written) == {CORE, "dedupe/fast.py"}


@pytest.mark.parametrize("title", ["h3", "h5"])
def test_scripted_editor_other_fixture_sets_touch_only_core(
    worktree: Path, title: str
) -> None:
    """
    GIVEN edit sets h3 (sorted set) and h5 (dict.fromkeys)
    WHEN the ScriptedEditor applies each
    THEN only core.py is written
    """
    result = ScriptedEditor(DEDUPE_EDITS).edit(worktree, _task(title), Budget(1.0))

    assert result.error is None
    assert set(result.written) == {CORE}


@pytest.mark.parametrize(
    "title", ["../h1", "H1 set", "H1", "", "h1\n", "-h1", "_h1", "h1/x", "a" * 65]
)
def test_scripted_editor_refuses_an_unsafe_title(worktree: Path, title: str) -> None:
    """
    GIVEN a hypothesis title that is not ^[a-z0-9][a-z0-9_-]{0,63}$
    WHEN the ScriptedEditor edits
    THEN it returns an error result, writes nothing and changes nothing
    """
    before = _snapshot(worktree)

    result = ScriptedEditor(DEDUPE_EDITS).edit(worktree, _task(title), Budget(1.0))

    assert result.error is not None and "title" in result.error
    assert result.stop == "error"
    assert dict(result.written) == {}
    assert _snapshot(worktree) == before


def test_scripted_editor_accepts_a_64_character_title(
    worktree: Path, edits: Path
) -> None:
    """
    GIVEN a 64-character title (the longest the pattern allows) with an edit set
    WHEN the ScriptedEditor edits
    THEN the edit applies
    """
    title = "a" + "b-_9" * 15 + "xyz"
    assert len(title) == 64
    _edit_set(edits, title, {"new.py": "x = 1\n"})

    result = ScriptedEditor(edits).edit(worktree, _task(title), Budget(1.0))

    assert result == EditResult(written={"new.py": 6})


def test_scripted_editor_reports_a_missing_edit_set(worktree: Path) -> None:
    """
    GIVEN a safe title with no directory under the edits dir
    WHEN the ScriptedEditor edits
    THEN it returns an error result naming the title and writes nothing
    """
    result = ScriptedEditor(DEDUPE_EDITS).edit(worktree, _task("h9"), Budget(1.0))

    assert result.error is not None and "h9" in result.error
    assert dict(result.written) == {}


def test_scripted_editor_records_every_title(worktree: Path) -> None:
    """
    GIVEN a ScriptedEditor used for h1 and an unsafe title
    WHEN the calls are inspected
    THEN both titles are listed in order
    """
    editor = ScriptedEditor(DEDUPE_EDITS)
    editor.edit(worktree, _task("h1"), Budget(1.0))
    editor.edit(worktree, _task("../h1"), Budget(1.0))

    assert editor.calls == ["h1", "../h1"]


def test_scripted_editor_creates_parent_dirs_and_skips_caches(
    worktree: Path, edits: Path
) -> None:
    """
    GIVEN an edit set adding pkg/sub/new.py and holding a __pycache__ dir
    WHEN the ScriptedEditor applies it
    THEN the parents are created and the interpreter cache is not copied
    """
    root = _edit_set(edits, "e1", {"pkg/sub/new.py": "y = 2\n"})
    cache = root / "files" / "pkg" / "__pycache__"
    cache.mkdir()
    (cache / "new.cpython-313.pyc").write_bytes(b"\0pyc")

    result = ScriptedEditor(edits).edit(worktree, _task("e1"), Budget(1.0))

    assert result == EditResult(written={"pkg/sub/new.py": 6})
    assert (worktree / "pkg" / "sub" / "new.py").read_text() == "y = 2\n"
    assert not (worktree / "pkg" / "__pycache__").exists()


def test_scripted_editor_ignores_blank_manifest_lines(
    worktree: Path, edits: Path
) -> None:
    """
    GIVEN _delete and _symlink manifests with blank and whitespace-only lines
    WHEN the ScriptedEditor applies them
    THEN only the real entries are applied
    """
    root = _edit_set(edits, "e2")
    (root / "_delete").write_text("\n  \ndedupe/main.py\n\n", encoding="utf-8")
    (root / "_symlink").write_text("\nlink.py\tdedupe/core.py\n \n", encoding="utf-8")

    result = ScriptedEditor(edits).edit(worktree, _task("e2"), Budget(1.0))

    assert result == EditResult(
        written={"dedupe/main.py": 0, "link.py": len(b"dedupe/core.py")}
    )
    assert not (worktree / "dedupe" / "main.py").exists()
    assert os.readlink(worktree / "link.py") == "dedupe/core.py"


@pytest.mark.parametrize(
    ("manifest", "line"),
    [
        ("_delete", "../outside.txt"),
        ("_delete", "dedupe/../../outside.txt"),
        ("_delete", "{outside}"),
        ("_symlink", "../evil.py\tcore.py"),
        ("_symlink", "{outside}\tcore.py"),
        ("_symlink", "~/evil.py\tcore.py"),
    ],
)
def test_scripted_editor_refuses_traversal_and_absolute_manifest_paths(
    worktree: Path, edits: Path, manifest: str, line: str
) -> None:
    """
    GIVEN an edit set that also copies core.py, with a manifest entry that
          climbs out of the worktree or names an absolute path
    WHEN the ScriptedEditor applies it
    THEN it returns an error result before writing anything: core.py is
         unchanged and the file outside the worktree is intact
    """
    outside = worktree.parent / "outside.txt"
    outside.write_text("keep me", encoding="utf-8")
    root = _edit_set(edits, "e3", {CORE: "changed\n"})
    (root / manifest).write_text(line.format(outside=outside) + "\n", "utf-8")
    before = _snapshot(worktree)

    result = ScriptedEditor(edits).edit(worktree, _task("e3"), Budget(1.0))

    assert result.error is not None
    assert dict(result.written) == {}
    assert _snapshot(worktree) == before
    assert outside.read_text(encoding="utf-8") == "keep me"
    assert not (worktree.parent / "evil.py").exists()


@pytest.mark.parametrize(
    ("manifest", "line"),
    [
        ("_delete", "./dedupe/main.py"),
        ("_delete", "dedupe//main.py"),
        ("_delete", "."),
        ("_symlink", "./dedupe/fast.py\tcore.py"),
    ],
)
def test_scripted_editor_refuses_a_manifest_path_that_is_not_normalised(
    worktree: Path, edits: Path, manifest: str, line: str
) -> None:
    """
    GIVEN a manifest entry that normalize_path would rewrite, or "."
    WHEN the ScriptedEditor applies it
    THEN it returns an error result and writes nothing: written keys must be
         exactly the paths git reports, or unrecorded_write misfires
    """
    root = _edit_set(edits, "e13")
    (root / manifest).write_text(line + "\n", encoding="utf-8")
    before = _snapshot(worktree)

    result = ScriptedEditor(edits).edit(worktree, _task("e13"), Budget(1.0))

    assert result.error is not None and "normalised" in result.error
    assert dict(result.written) == {}
    assert _snapshot(worktree) == before


def test_scripted_editor_refuses_a_malformed_symlink_line(
    worktree: Path, edits: Path
) -> None:
    """
    GIVEN a _symlink line with no TAB, and one with an empty target
    WHEN the ScriptedEditor applies each
    THEN each gives an error result and nothing is written
    """
    for line in ("dedupe/fast.py core.py", "dedupe/fast.py\t"):
        root = _edit_set(edits, "e4")
        (root / "_symlink").write_text(line + "\n", encoding="utf-8")

        result = ScriptedEditor(edits).edit(worktree, _task("e4"), Budget(1.0))

        assert result.error is not None and "_symlink" in result.error
        assert not (worktree / "dedupe" / "fast.py").exists()


def test_scripted_editor_refuses_a_parent_dir_symlinked_outside(
    worktree: Path, edits: Path, tmp_path: Path
) -> None:
    """
    GIVEN a worktree dir "out" that is a symlink to a directory outside it,
          and an edit set writing out/x.py
    WHEN the ScriptedEditor applies it
    THEN it returns an error result and nothing lands outside the worktree
    """
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (worktree / "out").symlink_to(outside, target_is_directory=True)
    _edit_set(edits, "e5", {"out/x.py": "pwned\n"})

    result = ScriptedEditor(edits).edit(worktree, _task("e5"), Budget(1.0))

    assert result.error is not None and "outside" in result.error
    assert list(outside.iterdir()) == []


def test_scripted_editor_refuses_a_symlink_chain_out_of_the_worktree(
    worktree: Path, edits: Path, tmp_path: Path
) -> None:
    """
    GIVEN a _symlink manifest whose first link points outside the worktree
          and whose second link would be created through the first
    WHEN the ScriptedEditor applies it
    THEN the first link is made (its target is verbatim data), the second is
         refused when its parent resolves outside, nothing is created outside
         and written honestly lists only the first link
    """
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    root = _edit_set(edits, "e6")
    (root / "_symlink").write_text(f"esc\t{outside}\nesc/inner.py\tx\n", "utf-8")

    result = ScriptedEditor(edits).edit(worktree, _task("e6"), Budget(1.0))

    assert result.error is not None and "outside" in result.error
    assert dict(result.written) == {"esc": len(os.fsencode(str(outside)))}
    assert list(outside.iterdir()) == []


def test_scripted_editor_refuses_to_write_through_an_existing_symlink(
    worktree: Path, edits: Path, tmp_path: Path
) -> None:
    """
    GIVEN a worktree file that is a symlink to a file outside the worktree
          and an edit set that overwrites that path
    WHEN the ScriptedEditor applies it
    THEN it returns an error result and the outside file is unchanged
    """
    victim = tmp_path / "victim.txt"
    victim.write_text("original", encoding="utf-8")
    (worktree / "dedupe" / "linked.py").symlink_to(victim)
    _edit_set(edits, "e7", {"dedupe/linked.py": "overwritten\n"})

    result = ScriptedEditor(edits).edit(worktree, _task("e7"), Budget(1.0))

    assert result.error is not None
    assert victim.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("entry", ["dedupe/missing.py", "dedupe"])
def test_scripted_editor_refuses_to_delete_a_missing_file_or_a_directory(
    worktree: Path, edits: Path, entry: str
) -> None:
    """
    GIVEN a _delete entry naming a missing file or a directory
    WHEN the ScriptedEditor applies it
    THEN it returns an error result and the directory is still there
    """
    root = _edit_set(edits, "e8")
    (root / "_delete").write_text(entry + "\n", encoding="utf-8")

    result = ScriptedEditor(edits).edit(worktree, _task("e8"), Budget(1.0))

    assert result.error is not None and "delete" in result.error
    assert (worktree / "dedupe" / "core.py").is_file()


def test_scripted_editor_deletes_a_symlink_not_its_target(
    worktree: Path, edits: Path
) -> None:
    """
    GIVEN a worktree symlink dedupe/alias.py -> core.py and a _delete of it
    WHEN the ScriptedEditor applies it
    THEN the link is removed and core.py survives
    """
    (worktree / "dedupe" / "alias.py").symlink_to("core.py")
    root = _edit_set(edits, "e9")
    (root / "_delete").write_text("dedupe/alias.py\n", encoding="utf-8")

    result = ScriptedEditor(edits).edit(worktree, _task("e9"), Budget(1.0))

    assert result == EditResult(written={"dedupe/alias.py": 0})
    assert not (worktree / "dedupe" / "alias.py").is_symlink()
    assert (worktree / CORE).is_file()


def test_scripted_editor_refuses_an_existing_symlink_path(
    worktree: Path, edits: Path
) -> None:
    """
    GIVEN a _symlink entry whose link path already exists
    WHEN the ScriptedEditor applies it
    THEN it returns an error result and the existing file is unchanged
    """
    before = (worktree / CORE).read_bytes()
    root = _edit_set(edits, "e10")
    (root / "_symlink").write_text(f"{CORE}\tmain.py\n", encoding="utf-8")

    result = ScriptedEditor(edits).edit(worktree, _task("e10"), Budget(1.0))

    assert result.error is not None
    assert (worktree / CORE).read_bytes() == before


@pytest.mark.parametrize("kind", ["file", "dir", "files"])
def test_scripted_editor_refuses_symlinks_inside_the_edit_set(
    worktree: Path, edits: Path, tmp_path: Path, kind: str
) -> None:
    """
    GIVEN an edit set whose files/ holds a symlinked file or directory, or
          whose files/ is itself a symlink
    WHEN the ScriptedEditor applies it
    THEN it returns an error result (links belong in _symlink) and writes
         nothing, so it never copies data from wherever the link points
    """
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "key.txt").write_text("s3cret", encoding="utf-8")
    root = _edit_set(edits, "e11", {"ok.py": "z = 3\n"})
    if kind == "file":
        (root / "files" / "leak.txt").symlink_to(secret / "key.txt")
    elif kind == "dir":
        (root / "files" / "leakdir").symlink_to(secret, target_is_directory=True)
    else:
        shutil.rmtree(root / "files")
        (root / "files").symlink_to(secret, target_is_directory=True)

    result = ScriptedEditor(edits).edit(worktree, _task("e11"), Budget(1.0))

    assert result.error is not None and "symlink" in result.error
    assert dict(result.written) == {}
    assert not (worktree / "ok.py").exists()


def test_scripted_editor_reports_a_non_utf8_manifest(
    worktree: Path, edits: Path
) -> None:
    """
    GIVEN a _delete manifest that is not valid UTF-8
    WHEN the ScriptedEditor applies it
    THEN it returns an error result
    """
    root = _edit_set(edits, "e12")
    (root / "_delete").write_bytes(b"\xff\xfe bad\n")

    result = ScriptedEditor(edits).edit(worktree, _task("e12"), Budget(1.0))

    assert result.error is not None
    assert dict(result.written) == {}


def test_scripted_editor_reports_a_missing_worktree(tmp_path: Path) -> None:
    """
    GIVEN a worktree path that does not exist
    WHEN the ScriptedEditor applies h1
    THEN it returns an error result instead of raising
    """
    result = ScriptedEditor(DEDUPE_EDITS).edit(
        tmp_path / "absent", _task("h1"), Budget(1.0)
    )

    assert result.error is not None
    assert dict(result.written) == {}


# Path.resolve raises RuntimeError on a symlink loop on Python 3.11 and 3.12
# but not on 3.13, so these pin one behaviour on every supported version.


def test_scripted_editor_reports_a_symlink_loop(worktree: Path, edits: Path) -> None:
    """
    GIVEN a _symlink manifest that creates the loop "loop -> loop" and then
          a link beneath it
    WHEN the ScriptedEditor applies it
    THEN it returns an error result instead of raising, and written lists
         only the loop it made
    """
    root = _edit_set(edits, "e13")
    (root / "_symlink").write_text("loop\tloop\nloop/x.py\tcore.py\n", "utf-8")

    result = ScriptedEditor(edits).edit(worktree, _task("e13"), Budget(1.0))

    assert result.error is not None
    assert result.stop == "error"
    assert dict(result.written) == {"loop": 4}


@pytest.mark.parametrize("blocker", ["loop", "file"])
def test_scripted_editor_refuses_an_unusable_parent_before_writing(
    worktree: Path, edits: Path, blocker: str
) -> None:
    """
    GIVEN an edit set writing ok.py and blocked/x.py, where the worktree's
          "blocked" is a symlink loop or a regular file
    WHEN the ScriptedEditor applies it
    THEN the plan is refused before anything is written
    """
    blocked = worktree / "blocked"
    if blocker == "loop":
        blocked.symlink_to("blocked")
    else:
        blocked.write_text("not a directory\n", encoding="utf-8")
    _edit_set(edits, "e14", {"ok.py": "z = 3\n", "blocked/x.py": "y = 1\n"})

    result = ScriptedEditor(edits).edit(worktree, _task("e14"), Budget(1.0))

    assert result.error is not None
    assert dict(result.written) == {}
    assert not (worktree / "ok.py").exists()


def test_scripted_editor_reports_a_worktree_that_is_a_symlink_loop(
    tmp_path: Path,
) -> None:
    """
    GIVEN a worktree path that is a symlink to itself
    WHEN the ScriptedEditor applies h1
    THEN it returns an error result instead of raising
    """
    looped = tmp_path / "wt"
    looped.symlink_to("wt")

    result = ScriptedEditor(DEDUPE_EDITS).edit(looped, _task("h1"), Budget(1.0))

    assert result.error is not None
    assert dict(result.written) == {}
