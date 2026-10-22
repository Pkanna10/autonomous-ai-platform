"""Tests for the Step 2 seam types (unit U3): frozen carriers and their invariants.

``execution/protocols.py`` holds the value types every Step 2 seam passes
around and the runtime-checkable protocols for preflight, profiling, editing,
understanding, combining and publishing. The carriers are frozen dataclasses;
the few that feed an anti-cheat rule or the budget validate on construction.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
from pathlib import Path
from typing import Any, get_type_hints

import pytest

from autonomous_ai_agents.common.models import (
    ChangeClass,
    CombineSkip,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Project,
    ProjectUnderstanding,
    Workload,
)
from autonomous_ai_agents.execution.protocols import (
    BranchPublisher,
    Change,
    CodeEditor,
    CombineMeasured,
    Combiner,
    EditResult,
    EditTask,
    KeptChange,
    LaunchReport,
    Preflight,
    PreflightReport,
    Profiler,
    ProfileResult,
    ProjectUnderstander,
    TrialBrief,
    UnderstandResult,
    WorktreeHandle,
)

PROJECT = Project(name="dedupe", root_path="/home/dev/dedupe")
WORKLOAD = Workload(project_id=PROJECT.id, name="main", command=("python", "-m", "x"))
HYPOTHESIS = Hypothesis(
    project_id=PROJECT.id,
    source=HypothesisSource.playbook,
    title="h1",
    rationale="membership test on a list",
    change_class=ChangeClass.efficiency,
    expected_gain=0.5,
    provability=0.9,
    risk=0.1,
)
HOTSPOT = Hotspot(
    project_id=PROJECT.id,
    workload_id=WORKLOAD.id,
    file_path="dedupe/core.py",
    symbol="unique_in_order",
    self_time_s=0.8,
    total_time_s=0.84,
    share=0.95,
)
UNDERSTANDING = ProjectUnderstanding(
    language="python", summary="de-duplicates integers", served_by_model="m"
)
BRIEF = TrialBrief(understanding=UNDERSTANDING, hotspots=(HOTSPOT,), protected=("x",))


def _instances() -> list[object]:
    return [
        BRIEF,
        Change(status="M", old_mode="100644", new_mode="100644", path="a.py"),
        WorktreeHandle(
            path=Path("/wt"), gitdir=Path("/repo/.git/w/a"), link_bytes=b"x"
        ),
        PreflightReport(
            head_commit="a" * 40,
            dirty_entries=(),
            git_version=(2, 43, 0),
            network="required",
            fs="required",
            workloads=(WORKLOAD,),
            test_command=None,
            extra_protected=(),
        ),
        EditTask(hypothesis=HYPOTHESIS, brief=BRIEF, boundary="0123abcd"),
        EditResult(),
        ProfileResult(hotspots=(HOTSPOT,), notes=()),
        UnderstandResult(understanding=None),
        KeptChange(
            trial_id="t",
            hypothesis_id="h",
            verdict_id="v",
            commit="c",
            score=1.0,
            gain=0.5,
        ),
        CombineMeasured(
            tip_commit="c", applied=("t",), skipped=(), baseline=(), combined=()
        ),
    ]


# ---------------------------------------------------------------------------
# Every carrier is a frozen dataclass
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("instance", _instances(), ids=lambda i: type(i).__name__)
def test_every_carrier_is_a_frozen_dataclass(instance: object) -> None:
    """
    GIVEN one instance of each seam carrier
    WHEN a field is assigned
    THEN the assignment is refused (carriers never change after construction)
    """
    assert dataclasses.is_dataclass(instance)
    first = dataclasses.fields(instance)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, first, None)


def test_carriers_have_the_spec_fields_in_order() -> None:
    """
    GIVEN the seam carriers of spec section 3
    WHEN their field names are listed
    THEN they match the spec exactly, in order
    """
    expected: dict[type[Any], tuple[str, ...]] = {
        TrialBrief: ("understanding", "hotspots", "protected"),
        Change: ("status", "old_mode", "new_mode", "path"),
        WorktreeHandle: ("path", "gitdir", "link_bytes"),
        PreflightReport: (
            "head_commit",
            "dirty_entries",
            "git_version",
            "network",
            "fs",
            "workloads",
            "test_command",
            "extra_protected",
        ),
        EditTask: ("hypothesis", "brief", "boundary"),
        EditResult: ("written", "cost_usd", "tokens_used", "stop", "error"),
        ProfileResult: ("hotspots", "notes"),
        UnderstandResult: ("understanding", "notes", "cost_usd", "tokens_used"),
        KeptChange: (
            "trial_id",
            "hypothesis_id",
            "verdict_id",
            "commit",
            "score",
            "gain",
        ),
        CombineMeasured: ("tip_commit", "applied", "skipped", "baseline", "combined"),
    }
    for cls, names in expected.items():
        assert tuple(f.name for f in dataclasses.fields(cls)) == names, cls


# ---------------------------------------------------------------------------
# Change: git name-status letters, octal modes, clean paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "old_mode", "new_mode"),
    [
        ("A", "000000", "100644"),
        ("M", "100644", "100755"),
        ("D", "100644", "000000"),
        ("T", "100644", "120000"),
    ],
)
def test_change_accepts_git_name_status_letters_and_octal_modes(
    status: str, old_mode: str, new_mode: str
) -> None:
    """
    GIVEN a raw diff entry with status A, M, D or T and six-digit octal modes
    WHEN a Change is built
    THEN it keeps the values verbatim
    """
    change = Change(status=status, old_mode=old_mode, new_mode=new_mode, path="a.py")

    assert (change.status, change.old_mode, change.new_mode) == (
        status,
        old_mode,
        new_mode,
    )


@pytest.mark.parametrize("status", ["R", "C", "U", "X", "", "m", "AM"])
def test_change_refuses_any_other_status(status: str) -> None:
    """
    GIVEN a status that --no-renames capture never produces (rename, copy,
          unmerged, unknown, lower case, combined)
    WHEN a Change is built
    THEN a ValueError names the status, so a misparse cannot slip past capture
    """
    with pytest.raises(ValueError, match="status"):
        Change(status=status, old_mode="100644", new_mode="100644", path="a.py")


@pytest.mark.parametrize("mode", ["10064", "1006440", "100648", "abcdef", "", " 10064"])
def test_change_refuses_a_mode_that_is_not_six_octal_digits(mode: str) -> None:
    """
    GIVEN an old or new mode that is not six octal digits
    WHEN a Change is built
    THEN a ValueError names the mode
    """
    with pytest.raises(ValueError, match="mode"):
        Change(status="M", old_mode=mode, new_mode="100644", path="a.py")
    with pytest.raises(ValueError, match="mode"):
        Change(status="M", old_mode="100644", new_mode=mode, path="a.py")


@pytest.mark.parametrize(
    "path",
    ["./a.py", "/etc/passwd", "a/../b.py", "..", "a//b.py", "a/", ".", "", "a\0b"],
)
def test_change_refuses_a_path_git_cannot_emit(path: str) -> None:
    """
    GIVEN a path git never prints in a diff: absolute, empty, with an empty,
          "." or ".." component, or holding a NUL (the -z separator)
    WHEN a Change is built
    THEN a ValueError names it (a misparse fails loudly)
    """
    with pytest.raises(ValueError, match="path"):
        Change(status="A", old_mode="000000", new_mode="100644", path=path)


@pytest.mark.parametrize(
    "path", ["a\\b.py", "~/x.py", "~x.py", "c:x.py", "my dir/f.py", "naïve.py"]
)
def test_change_keeps_any_posix_path_git_can_emit_verbatim(path: str) -> None:
    """
    GIVEN a legal POSIX file name that normalize_path would rewrite or refuse
          (a backslash, a leading "~", a drive-like "c:")
    WHEN a Change is built from it
    THEN it is kept verbatim, so capture reports it (unrecorded_write: the
         editor normalises every path it writes) instead of crashing
    """
    change = Change(status="A", old_mode="000000", new_mode="100644", path=path)

    assert change.path == path


# ---------------------------------------------------------------------------
# EditResult: an immutable written map, honest money
# ---------------------------------------------------------------------------


def test_edit_result_defaults_describe_an_edit_that_wrote_nothing() -> None:
    """
    GIVEN an EditResult built with no arguments
    WHEN its fields are read
    THEN nothing was written, nothing was spent, the turn ended and no error
    """
    result = EditResult()

    assert dict(result.written) == {}
    assert result.cost_usd == 0.0
    assert result.tokens_used == 0
    assert result.stop == "end_turn"
    assert result.error is None


def test_edit_result_written_is_an_immutable_copy() -> None:
    """
    GIVEN an EditResult built from a mutable dict
    WHEN the dict is changed afterwards or the map is assigned through
    THEN the result is unaffected and item assignment is refused
    """
    source = {"dedupe/core.py": 120, "tests/test_core.py": 0}
    result = EditResult(written=source)
    source["extra.py"] = 1

    assert dict(result.written) == {"dedupe/core.py": 120, "tests/test_core.py": 0}
    with pytest.raises(TypeError):
        result.written["x.py"] = 3  # type: ignore[index]


def test_edit_results_with_equal_fields_are_equal() -> None:
    """
    GIVEN two EditResults built from equal maps
    WHEN they are compared
    THEN they are equal, and a different map is not
    """
    assert EditResult(written={"a.py": 1}) == EditResult(written={"a.py": 1})
    assert EditResult(written={"a.py": 1}) != EditResult(written={"a.py": 2})


def test_edit_result_is_hashable_and_agrees_with_equality() -> None:
    """
    GIVEN equal EditResults whose written maps were built in different orders
    WHEN they are hashed and put in a set
    THEN hashing works, equal results hash alike and the set keeps one
    """
    first = EditResult(written={"a.py": 1, "b.py": 0}, cost_usd=0.5, tokens_used=7)
    second = EditResult(written={"b.py": 0, "a.py": 1}, cost_usd=0.5, tokens_used=7)

    assert hash(first) == hash(second)
    assert len({first, second, EditResult()}) == 2
    assert {first: "kept"}[second] == "kept"


@pytest.mark.parametrize("key", ["./a.py", "/abs.py", "../x.py", ".", "a//b.py"])
def test_edit_result_refuses_a_written_key_that_is_not_normalised(key: str) -> None:
    """
    GIVEN a written key that is not a clean repo-relative file path
    WHEN an EditResult is built
    THEN a ValueError names it (unrecorded_write compares keys with git paths)
    """
    with pytest.raises(ValueError, match="written"):
        EditResult(written={key: 1})


def test_edit_result_refuses_negative_byte_counts() -> None:
    """
    GIVEN a written entry with -1 bytes
    WHEN an EditResult is built
    THEN a ValueError is raised (a deletion records 0, never less)
    """
    with pytest.raises(ValueError, match="written"):
        EditResult(written={"a.py": -1})


@pytest.mark.parametrize("cost", [-0.01, math.nan, math.inf])
def test_edit_result_refuses_a_negative_or_non_finite_cost(cost: float) -> None:
    """
    GIVEN a cost below 0, NaN or infinite
    WHEN an EditResult is built
    THEN a ValueError is raised (a NaN would pass every budget comparison)
    """
    with pytest.raises(ValueError, match="cost_usd"):
        EditResult(cost_usd=cost)


def test_edit_result_refuses_negative_tokens() -> None:
    """
    GIVEN tokens_used below 0
    WHEN an EditResult is built
    THEN a ValueError is raised
    """
    with pytest.raises(ValueError, match="tokens_used"):
        EditResult(tokens_used=-1)


# ---------------------------------------------------------------------------
# UnderstandResult and EditTask
# ---------------------------------------------------------------------------


def test_understand_result_defaults_and_money_rules() -> None:
    """
    GIVEN an UnderstandResult with only the understanding set
    WHEN it is read, and when one is built with a bad cost or token count
    THEN notes are empty, nothing is spent, and the bad values are refused
    """
    result = UnderstandResult(understanding=UNDERSTANDING)

    assert result.notes == ()
    assert result.cost_usd == 0.0
    assert result.tokens_used == 0
    with pytest.raises(ValueError, match="cost_usd"):
        UnderstandResult(understanding=None, cost_usd=math.nan)
    with pytest.raises(ValueError, match="tokens_used"):
        UnderstandResult(understanding=None, tokens_used=-5)


def test_edit_task_refuses_an_empty_boundary() -> None:
    """
    GIVEN an empty boundary token
    WHEN an EditTask is built
    THEN a ValueError is raised: every text contains "", so the rule that
         refuses content containing the boundary would be meaningless
    """
    with pytest.raises(ValueError, match="boundary"):
        EditTask(hypothesis=HYPOTHESIS, brief=BRIEF, boundary="")


def test_combine_measured_carries_skips_as_models() -> None:
    """
    GIVEN a combine result with one skipped conflict
    WHEN it is read
    THEN the skip is the CombineSkip model the Combination stores
    """
    skip = CombineSkip(trial_id="t5", reason="conflict", paths=("dedupe/core.py",))
    measured = CombineMeasured(
        tip_commit="c", applied=("t1",), skipped=(skip,), baseline=(), combined=()
    )

    assert measured.skipped == (skip,)


# ---------------------------------------------------------------------------
# LaunchReport and the protocol signatures
# ---------------------------------------------------------------------------


def test_launch_report_is_a_total_typed_dict_with_the_spec_keys() -> None:
    """
    GIVEN the launcher's JSON report type
    WHEN its keys and types are read
    THEN every spec key is required with the spec type
    """
    hints = get_type_hints(LaunchReport)

    assert LaunchReport.__required_keys__ == frozenset(hints)
    assert hints == {
        "wall_ns": int,
        "utime": float,
        "stime": float,
        "maxrss": int,
        "exit": int,
        "fs_isolated": bool,
        "net_isolated": bool,
        "error": str | None,
    }


def _signature(protocol: type[Any], method: str) -> list[tuple[str, Any]]:
    params = inspect.signature(getattr(protocol, method)).parameters.values()
    return [(p.name, p.kind) for p in params if p.name != "self"]


POS = inspect.Parameter.POSITIONAL_OR_KEYWORD
KW = inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize(
    ("protocol", "method", "expected"),
    [
        (
            Preflight,
            "check",
            [("project", POS), ("workloads", POS), ("guardrails", POS)],
        ),
        (Profiler, "profile", [("workloads", POS), ("run_id", KW), ("commit", KW)]),
        (CodeEditor, "edit", [("worktree", POS), ("task", POS), ("budget", POS)]),
        (
            ProjectUnderstander,
            "understand",
            [("project", POS), ("workloads", POS), ("commit", KW), ("budget", KW)],
        ),
        (
            Combiner,
            "combine",
            [
                ("run_id", POS),
                ("project", POS),
                ("base_commit", POS),
                ("kept", POS),
                ("workloads", POS),
                ("baseline_count", KW),
            ],
        ),
        (
            BranchPublisher,
            "publish",
            [("project", POS), ("branch", POS), ("tip", POS), ("base", POS)],
        ),
    ],
)
def test_protocol_methods_have_the_spec_signatures(
    protocol: type[Any], method: str, expected: list[tuple[str, Any]]
) -> None:
    """
    GIVEN each Step 2 seam protocol
    WHEN its method signature is inspected
    THEN names, order and keyword-only markers match spec section 3
    """
    assert _signature(protocol, method) == expected


@pytest.mark.parametrize(
    "protocol",
    [Preflight, Profiler, CodeEditor, ProjectUnderstander, Combiner, BranchPublisher],
)
def test_protocols_are_runtime_checkable(protocol: type[Any]) -> None:
    """
    GIVEN each seam protocol
    WHEN a plain object is checked against it
    THEN isinstance works (runtime_checkable) and refuses the object
    """
    assert not isinstance(object(), protocol)
