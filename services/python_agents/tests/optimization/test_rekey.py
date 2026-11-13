"""Re-keying idea anchors across a diff (X2-DT, stacked rounds; dt-design
section 1, Re-keying).

A seed's mechanism key names lines at the round base. When a round's tip is
adopted, ``rekey.rekey_events`` moves each key into the tip's coordinates
from ``git diff --no-renames base tip``: a line before or after a change
shifts by the cumulative delta, a span a change touches widens to the
change's new lines, and a key whose file is deleted, binary, unreadable or
cut off by the diff's truncation is dropped with its reason.
``rekey.rekeyed_keys`` reads the latest record per hypothesis back from the
node's event data; ``rekey.current_keys`` overlays them on
``idea_dedupe.recorded_keys``. Every diff here is either written by hand,
made by ``difflib`` (the same unified format) or read from real git through
``GitWorkspace.diff_commits``, the call ``GitStacker.diff`` wraps.
"""

from __future__ import annotations

import difflib
import random
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pytest

from autonomous_ai_agents.common.models import ScalarDict
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.optimization import rekey
from autonomous_ai_agents.optimization.idea_dedupe import (
    KEY_EVENT,
    IdeaKey,
    MechanismKey,
    Target,
    key_event,
    recorded_keys,
)
from autonomous_ai_agents.optimization.idea_types import (
    GenerateEvent,
    Mechanism,
    MorphCell,
)

BASE: Final = "a" * 40
TIP: Final = "b" * 40
TIP2: Final = "c" * 40
PATH: Final = "pkg/mod.py"
LINES: Final = tuple(f"line {n}" for n in range(1, 41))


def _key(
    first: int,
    last: int,
    path: str = PATH,
    *,
    function: str | None = "f",
    mechanism: Mechanism = Mechanism.remove_work,
    cell: MorphCell = MorphCell.work_eliminate,
) -> IdeaKey:
    target = Target(path=path, first=first, last=last)
    key = MechanismKey(target=target, mechanism=mechanism, cell=cell)
    return IdeaKey(key=key, function=function)


def _file_diff(
    path: str, old: Sequence[str], new: Sequence[str], *, context: int = 3
) -> str:
    """One file's ``diff --git`` block as git prints it (difflib's hunks)."""
    body = list(difflib.unified_diff(old, new, lineterm="", n=context))[2:]
    head = [f"diff --git a/{path} b/{path}", "index 1111111..2222222 100644",
            f"--- a/{path}", f"+++ b/{path}"]  # fmt: skip
    return "\n".join([*head, *body]) + "\n"


def _edit(
    old: Sequence[str], at: int, delete: int, insert: Sequence[str] = ()
) -> list[str]:
    """``old`` with ``delete`` lines from line ``at`` replaced by ``insert``."""
    return [*old[: at - 1], *insert, *old[at - 1 + delete :]]


def _data(events: Sequence[GenerateEvent]) -> list[ScalarDict]:
    """The events as the node stores them (``_note`` puts the code in)."""
    return [{"code": event.code, **event.data} for event in events]


def _moved(keys: Mapping[str, IdeaKey], diff: str) -> dict[str, tuple[int, int] | None]:
    found = rekey.rekeyed_keys(_data(rekey.rekey_events(keys, diff, BASE, TIP)))
    return {
        h: None if k is None else (k.key.target.first, k.key.target.last)
        for h, k in found.items()
    }


def _reasons(keys: Mapping[str, IdeaKey], diff: str) -> dict[str, str]:
    events = rekey.rekey_events(keys, diff, BASE, TIP)
    return {
        str(e.data["hypothesis_id"]): str(e.data["reason"])
        for e in events
        if e.code == rekey.DROP_EVENT
    }


# --------------------------------------------------------------------------
# The record's shape and the untouched identity
# --------------------------------------------------------------------------


def test_a_rekeyed_record_is_key_events_shape_plus_its_base_and_tip() -> None:
    """
    GIVEN a key in a file the diff shifts
    WHEN it is re-keyed
    THEN its data is exactly ``key_event``'s fields (moved lines) plus the
        base and the tip and the lines it had at the base, under
        ``idea_mechanism_rekeyed``, the mechanism, cell and function kept
    """
    key = _key(10, 12, function="total", mechanism=Mechanism.algorithm,
               cell=MorphCell.timing_precompute)  # fmt: skip
    diff = _file_diff(PATH, LINES, _edit(LINES, 3, 0, ["new a", "new b"]))

    (event,) = rekey.rekey_events({"h-1": key}, diff, BASE, TIP)

    moved = _key(12, 14, function="total", mechanism=Mechanism.algorithm,
                 cell=MorphCell.timing_precompute)  # fmt: skip
    assert event.code == rekey.REKEY_EVENT == "idea_mechanism_rekeyed"
    assert event.data == {**key_event("h-1", "t", moved).data, "base": BASE,
                          "tip": TIP, "base_first": 10, "base_last": 12}  # fmt: skip
    assert "'h-1'" in event.message and f"{PATH}:10-12" in event.message
    assert "12-14" in event.message
    assert rekey.rekeyed_keys(_data([event])) == {"h-1": moved}


def test_an_untouched_key_keeps_its_lines_and_is_still_recorded() -> None:
    """
    GIVEN keys in a file the diff does not show, and an empty diff
    WHEN they are re-keyed
    THEN each keeps its lines, and each is recorded at the tip
    """
    keys = {"h-1": _key(1, 1), "h-2": _key(5, 9, "other.py", function=None)}
    other = _file_diff("third.py", LINES, _edit(LINES, 1, 3))

    for diff in ("", other):
        events = rekey.rekey_events(keys, diff, BASE, TIP)
        assert [e.code for e in events] == [rekey.REKEY_EVENT] * 2
        assert rekey.rekeyed_keys(_data(events)) == keys
    assert rekey.rekey_events({}, other, BASE, TIP) == ()


def test_a_commit_must_be_named() -> None:
    for base, tip in (("", TIP), (BASE, "")):
        with pytest.raises(ValueError, match="base and tip"):
            rekey.rekey_events({"h": _key(1, 1)}, "", base, tip)


# --------------------------------------------------------------------------
# Shifts, insertions, deletions and replaced spans
# --------------------------------------------------------------------------


def test_an_insertion_before_a_span_shifts_it_and_one_after_does_not() -> None:
    keys = {"before": _key(1, 2), "boundary": _key(3, 4), "after": _key(10, 12)}
    inserted = _file_diff(PATH, LINES, _edit(LINES, 3, 0, ["n1", "n2"]))
    assert _moved(keys, inserted) == {
        "before": (1, 2), "boundary": (5, 6), "after": (12, 14),
    }  # fmt: skip
    tail = {"span": _key(10, 12)}
    after = _file_diff(PATH, LINES, _edit(LINES, 13, 0, ["n1"]))
    assert _moved(tail, after) == {"span": (10, 12)}


def test_a_deletion_before_a_span_shifts_it_down() -> None:
    diff = _file_diff(PATH, LINES, _edit(LINES, 3, 2))
    assert _moved({"h": _key(10, 12), "edge": _key(5, 6)}, diff) == {
        "h": (8, 10), "edge": (3, 4),
    }  # fmt: skip


def test_a_change_after_a_span_leaves_it() -> None:
    diff = _file_diff(PATH, LINES, _edit(LINES, 20, 1, ["x", "y", "z"]))
    assert _moved({"h": _key(10, 12), "end": _key(19, 19)}, diff) == {
        "h": (10, 12), "end": (19, 19),
    }  # fmt: skip


def test_an_insertion_inside_a_span_widens_it() -> None:
    diff = _file_diff(PATH, LINES, _edit(LINES, 11, 0, ["n1", "n2"]))
    assert _moved({"h": _key(10, 12)}, diff) == {"h": (10, 14)}


def test_a_deletion_inside_a_span_shrinks_it_and_a_whole_one_drops_it() -> None:
    keys = {"h": _key(10, 12)}
    assert _moved(keys, _file_diff(PATH, LINES, _edit(LINES, 11, 1))) == {"h": (10, 11)}
    assert _moved(keys, _file_diff(PATH, LINES, _edit(LINES, 10, 2))) == {"h": (10, 10)}
    assert _moved(keys, _file_diff(PATH, LINES, _edit(LINES, 11, 2))) == {"h": (10, 10)}
    gone = _file_diff(PATH, LINES, _edit(LINES, 9, 5))
    assert _moved(keys, gone) == {"h": None}
    assert _reasons(keys, gone) == {"h": rekey.GONE}


def test_a_span_a_replaced_region_touches_widens_to_its_new_span() -> None:
    """
    GIVEN old lines 11-14 replaced by three new lines (tip lines 11-13)
    WHEN keys overlapping its start, its end and its inside are re-keyed
    THEN each covers the region's whole new span and its own surviving
        lines, shifted
    """
    diff = _file_diff(PATH, LINES, _edit(LINES, 11, 4, ["r1", "r2", "r3"]))
    keys = {"start": _key(10, 12), "end": _key(13, 16), "inside": _key(12, 12),
            "around": _key(9, 20)}  # fmt: skip
    assert _moved(keys, diff) == {
        "start": (10, 13), "end": (11, 15), "inside": (11, 13), "around": (9, 19),
    }  # fmt: skip


def test_several_hunks_add_their_deltas() -> None:
    new = _edit(LINES, 30, 0, ["c"])
    new = _edit(new, 15, 2)
    new = _edit(new, 3, 0, ["a", "b"])
    diff = _file_diff(PATH, LINES, new)
    assert sum(row.startswith("@@") for row in diff.split("\n")) == 3
    keys = {"a": _key(5, 6), "b": _key(10, 12), "c": _key(18, 20),
            "d": _key(26, 27), "e": _key(14, 17), "f": _key(31, 32)}  # fmt: skip
    assert _moved(keys, diff) == {
        "a": (7, 8), "b": (12, 14), "c": (18, 20), "d": (26, 27), "e": (16, 17),
        "f": (32, 33),
    }  # fmt: skip


def test_a_change_in_one_file_never_moves_a_key_in_another() -> None:
    diff = _file_diff("a.py", LINES, _edit(LINES, 1, 0, ["x"])) + _file_diff(
        "b.py", LINES, _edit(LINES, 1, 2)
    )
    keys = {"a": _key(5, 5, "a.py"), "b": _key(5, 5, "b.py"), "c": _key(5, 5)}
    assert _moved(keys, diff) == {"a": (6, 6), "b": (3, 3), "c": (5, 5)}


# --------------------------------------------------------------------------
# Deleted, renamed, new, binary and mode-only files
# --------------------------------------------------------------------------

_DELETED: Final = """\
diff --git a/gone.py b/gone.py
deleted file mode 100644
index 1111111..0000000
--- a/gone.py
+++ /dev/null
@@ -1,3 +0,0 @@
-a
-b
-c
"""
_ADDED: Final = """\
diff --git a/new.py b/new.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/new.py
@@ -0,0 +1,3 @@
+a
+b
+c
"""


def test_a_deleted_file_drops_its_key_with_a_note() -> None:
    keys = {"h": _key(1, 2, "gone.py"), "kept": _key(1, 2)}
    events = rekey.rekey_events(keys, _DELETED, BASE, TIP)
    drop = events[0]
    assert drop.code == rekey.DROP_EVENT == "idea_mechanism_dropped"
    assert drop.data == {"hypothesis_id": "h", "path": "gone.py", "first": 1,
                         "last": 2, "base": BASE, "tip": TIP,
                         "reason": rekey.DELETED}  # fmt: skip
    assert rekey.DELETED in drop.message and "gone.py:1-2" in drop.message
    assert rekey.rekeyed_keys(_data(events)) == {"h": None, "kept": keys["kept"]}


def test_a_renamed_file_is_a_delete_and_an_add() -> None:
    """``--no-renames``: the old path is deleted, the new one is new; a key
    on the old path is dropped, and none can name the new path at the base."""
    renamed = _DELETED + _ADDED
    keys = {"old": _key(2, 2, "gone.py"), "new": _key(2, 2, "new.py")}
    assert _reasons(keys, renamed) == {"old": rekey.DELETED, "new": rekey.NEW_FILE}


def test_a_binary_change_drops_and_a_mode_change_keeps() -> None:
    diff = (
        "diff --git a/data.py b/data.py\nindex 1111111..2222222 100644\n"
        "Binary files a/data.py and b/data.py differ\n"
        "diff --git a/run.py b/run.py\nold mode 100644\nnew mode 100755\n"
        "diff --git a/blob.py b/blob.py\nindex 1111111..2222222 100644\n"
        "GIT binary patch\nliteral 0\n"
    )
    keys = {"bin": _key(1, 1, "data.py"), "mode": _key(3, 4, "run.py"),
            "patch": _key(1, 1, "blob.py")}  # fmt: skip
    assert _moved(keys, diff) == {"bin": None, "mode": (3, 4), "patch": None}
    assert _reasons(keys, diff) == {"bin": rekey.BINARY, "patch": rekey.BINARY}


# --------------------------------------------------------------------------
# Truncation
# --------------------------------------------------------------------------


def _truncated(text: str) -> str:
    """``GitWorkspace._patch``'s cap marker after ``text``."""
    return f"{text}\n[diff truncated: {len(text)} of 99999 bytes shown]\n"


def test_truncation_keeps_whole_files_and_drops_the_cut_and_the_unshown() -> None:
    """
    GIVEN a diff of a.py and b.py, cut inside c.py's hunk
    WHEN keys in each, and in a file the diff never reaches, are re-keyed
    THEN a.py's and b.py's move, c.py's is dropped as cut, and the unshown
        file's is dropped (it may sort after the cut)
    """
    whole = (
        _file_diff("a.py", LINES, _edit(LINES, 1, 0, ["x"]))
        + _file_diff("b.py", LINES, _edit(LINES, 1, 1))
        + _file_diff("c.py", LINES, _edit(LINES, 1, 0, ["y"]))
    )
    cut = _truncated(whole[: whole.index("+y")])
    keys = {"a": _key(5, 5, "a.py"), "b": _key(5, 5, "b.py"),
            "c": _key(5, 5, "c.py"), "z": _key(5, 5, "z.py")}  # fmt: skip
    assert _moved(keys, cut) == {"a": (6, 6), "b": (4, 4), "c": None, "z": None}
    assert _reasons(keys, cut) == {"c": rekey.CUT, "z": rekey.UNSHOWN}


def test_a_cut_inside_the_next_header_makes_the_file_before_it_the_cut_one() -> None:
    whole = _file_diff("a.py", LINES, _edit(LINES, 1, 0, ["x"])) + _file_diff(
        "b.py", LINES, _edit(LINES, 1, 1)
    )
    keys = {"a": _key(5, 5, "a.py"), "b": _key(5, 5, "b.py")}
    inside = _truncated(whole[: whole.index("diff --git a/b.py") + 6])
    assert _reasons(keys, inside) == {"a": rekey.CUT, "b": rekey.UNSHOWN}
    assert _reasons(keys, _truncated(whole)) == {"b": rekey.CUT}
    assert _moved(keys, _truncated(whole)) == {"a": (6, 6), "b": None}


def test_a_diff_that_ends_like_a_marker_inside_is_not_truncated() -> None:
    marker = "\n[diff truncated: 1 of 2 bytes shown]\n"
    diff = _file_diff(PATH, LINES, _edit(LINES, 1, 0, ["x"])) + marker + "\n"
    assert _reasons({"h": _key(5, 5)}, diff) == {"h": rekey.UNREADABLE}


# --------------------------------------------------------------------------
# The latest record wins; malformed records are skipped with a note
# --------------------------------------------------------------------------


def test_the_latest_record_of_a_hypothesis_wins() -> None:
    first = rekey.rekey_events(
        {"h-1": _key(5, 6), "h-2": _key(8, 8, "gone.py"), "h-3": _key(1, 1)},
        _file_diff(PATH, LINES, _edit(LINES, 1, 0, ["x"])),
        BASE,
        TIP,
    )
    second = rekey.rekey_events(
        {"h-1": _key(6, 7), "h-2": _key(8, 8, "gone.py"), "h-3": _key(2, 2)},
        _file_diff(PATH, LINES, _edit(LINES, 1, 0, ["y", "z"])) + _DELETED,
        TIP,
        TIP2,
    )
    revived = rekey.rekey_events({"h-2": _key(3, 3)}, "", TIP2, TIP2)
    found = rekey.rekeyed_keys(_data([*first, *second]))
    assert found == {"h-1": _key(8, 9), "h-2": None, "h-3": _key(4, 4)}
    notes: list[str] = []
    later = rekey.rekeyed_keys(_data([*first, *second, *revived]), notes)
    assert later["h-2"] is None  # a dropped key stays dropped (fail closed)
    assert notes == ["1 re-key record(s) out of chain: their key reads as dropped"]


def test_current_keys_overlays_the_rekeyed_on_the_recorded() -> None:
    """
    GIVEN keys recorded at the base, then one round re-keyed to the tip (one
        dropped), and a key recorded at the tip in the next round
    WHEN ``current_keys`` reads every event
    THEN each key is the tip's, the dropped one is gone, and with no
        re-key record it is ``recorded_keys`` exactly
    """
    recorded = [key_event("h-1", "t", _key(5, 6)), key_event("h-2", "t",
                _key(1, 1, "gone.py"))]  # fmt: skip
    moved = rekey.rekey_events(
        recorded_keys(_data(recorded)),
        _file_diff(PATH, LINES, _edit(LINES, 1, 0, ["x"])) + _DELETED,
        BASE,
        TIP,
    )
    fresh = [key_event("h-3", "t", _key(9, 9))]
    events = _data([*recorded, *moved, *fresh])
    assert rekey.current_keys(events) == {"h-1": _key(6, 7), "h-3": _key(9, 9)}
    plain = _data([*recorded, *fresh])
    assert rekey.current_keys(plain) == recorded_keys(plain)
    assert list(rekey.current_keys(plain)) == ["h-1", "h-2", "h-3"]


def test_rounds_chain_into_the_last_tips_coordinates() -> None:
    tip1 = _edit(LINES, 2, 0, ["a", "b"])
    tip2 = _edit(tip1, 30, 3)
    tip2 = _edit(tip2, 1, 1)
    events = _data([key_event("h", "t", _key(20, 21))])
    events += _data(rekey.rekey_events(rekey.current_keys(events),
                    _file_diff(PATH, LINES, tip1), BASE, TIP))  # fmt: skip
    events += _data(rekey.rekey_events(rekey.current_keys(events),
                    _file_diff(PATH, tip1, tip2), TIP, TIP2))  # fmt: skip
    (key,) = rekey.current_keys(events).values()
    target = key.key.target
    assert tip2[target.first - 1 : target.last] == list(LINES[19:21])
    assert events[-1]["base"] == TIP and events[-1]["tip"] == TIP2


def test_a_malformed_record_drops_its_key_and_an_unnamed_one_is_skipped() -> None:
    """
    GIVEN re-key and drop records, some malformed
    WHEN they are read back
    THEN a malformed record whose hypothesis id reads drops that key (never
        its older lines), one with no readable id is skipped, and each is
        counted in the notes
    """
    (good,) = _data(rekey.rekey_events({"h": _key(2, 3)}, "", BASE, TIP))
    (drop,) = _data(rekey.rekey_events({"d": _key(1, 1, "gone.py")}, _DELETED,
                                       BASE, TIP))  # fmt: skip
    events: list[ScalarDict] = [
        {"code": KEY_EVENT, "hypothesis_id": "x"},  # another code: not counted
        {"code": "generated", "kept": 1},
        good,
        {**good, "hypothesis_id": "a", "tip": None},
        {**good, "hypothesis_id": "b", "first": 9},  # last before first
        {**good, "hypothesis_id": "c", "mechanism": "magic"},
        {**good, "hypothesis_id": "e", "first": 0},
        {**good, "hypothesis_id": ""},
        {**good, "hypothesis_id": 7},
        {**drop, "hypothesis_id": "f", "base": ""},
        {**good, "hypothesis_id": "g"},
        {**good, "hypothesis_id": "g", "base": TIP, "tip": TIP2, "last": "x"},
        drop,
    ]
    notes: list[str] = []
    found = rekey.rekeyed_keys(events, notes)
    assert found == {"h": _key(2, 3), "a": None, "b": None, "c": None, "e": None,
                     "f": None, "g": None, "d": None}  # fmt: skip
    assert notes == [
        "2 malformed re-key record(s) skipped",
        "6 re-key record(s) malformed: their key reads as dropped",
    ]
    assert rekey.rekeyed_keys(events) == found
    quiet: list[str] = []
    assert rekey.current_keys([good], quiet) == {"h": _key(2, 3)} and quiet == []
    rekey.current_keys(events, quiet)
    assert quiet == notes


def test_round_two_fed_recorded_keys_instead_of_current_keys_is_caught() -> None:
    """
    GIVEN round 1 re-keyed h-1 (shifted) and dropped h-2 (deleted file)
    WHEN round 2 is fed ``recorded_keys`` (the base's lines) by mistake
    THEN h-1's record starts from lines its last record did not end on and
        h-2's follows its drop: both read as dropped, noted; h-3, unmoved,
        chains; fed ``current_keys``, every record chains
    """
    recorded = _data([key_event("h-1", "t", _key(5, 6)),
                      key_event("h-2", "t", _key(1, 1, "gone.py")),
                      key_event("h-3", "t", _key(20, 20, "other.py"))])  # fmt: skip
    one = _file_diff(PATH, LINES, _edit(LINES, 1, 0, ["x"])) + _DELETED
    events = recorded + _data(
        rekey.rekey_events(recorded_keys(recorded), one, BASE, TIP)
    )
    two = _file_diff(PATH, LINES, _edit(LINES, 1, 0, ["y"]))
    wrong = _data(rekey.rekey_events(recorded_keys(events), two, TIP, TIP2))
    notes: list[str] = []
    assert rekey.current_keys(events + wrong, notes) == {
        "h-3": _key(20, 20, "other.py")
    }
    assert notes == ["2 re-key record(s) out of chain: their key reads as dropped"]
    right = _data(rekey.rekey_events(rekey.current_keys(events), two, TIP, TIP2))
    clean: list[str] = []
    assert rekey.current_keys(events + right, clean) == {
        "h-1": _key(7, 8), "h-3": _key(20, 20, "other.py"),
    }  # fmt: skip
    assert clean == []


def test_an_out_of_order_or_altered_record_is_refused() -> None:
    """
    GIVEN h's records for base..tip and tip..tip2
    WHEN they are read out of order, repeated, or with a field a re-key never
        changes altered
    THEN h reads as dropped with a note; with no ``KEY_EVENT`` (which carries
        no base) the first record is taken as it is, and the chain is checked
        from the second record on
    """
    anchor = _data([key_event("h", "t", _key(5, 6))])
    (r1,) = _data(rekey.rekey_events({"h": _key(5, 6)},
                  _file_diff(PATH, LINES, _edit(LINES, 1, 0, ["x"])), BASE, TIP))  # fmt: skip
    (r2,) = _data(rekey.rekey_events({"h": _key(6, 7)},
                  _file_diff(PATH, LINES, _edit(LINES, 1, 0, ["y"])), TIP, TIP2))  # fmt: skip
    assert rekey.rekeyed_keys([*anchor, r1, r2]) == {"h": _key(7, 8)}
    assert rekey.rekeyed_keys([r2]) == {"h": _key(7, 8)}  # the limit: unanchored
    for events, count in (
        ([*anchor, r2, r1], 2),  # r2 is off the anchor, r1 follows the break
        ([r2, r1], 1),
        ([r1, r1], 1),
        ([r1, {**r2, "cell": MorphCell.work_reuse.value}], 1),
        ([r1, {**r2, "function": "g"}], 1),
        ([r1, {**r2, "path": "x.py"}], 1),
        ([r1, {**r2, "base_first": 5}], 1),
        ([*anchor, {**r1, "path": "x.py"}], 1),
    ):
        notes: list[str] = []
        assert rekey.rekeyed_keys(events, notes) == {"h": None}
        assert notes == [
            f"{count} re-key record(s) out of chain: their key reads as dropped"
        ]
    (drop,) = _data(rekey.rekey_events({"h": _key(6, 7)}, _DELETED.replace(
        "gone.py", PATH), TIP, TIP2))  # fmt: skip
    assert rekey.rekeyed_keys([*anchor, r1, drop]) == {"h": None}
    late: list[str] = []
    assert rekey.rekeyed_keys([*anchor, r1, {**drop, "base": BASE}], late) == {
        "h": None
    }
    assert late == ["1 re-key record(s) out of chain: their key reads as dropped"]


# --------------------------------------------------------------------------
# A diff that cannot be read fails closed
# --------------------------------------------------------------------------

_HEAD: Final = f"diff --git a/{PATH} b/{PATH}\n--- a/{PATH}\n+++ b/{PATH}\n"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("@@ -4,3 +4,4 @@\n l4\n+x\n l5\n", id="hunk-cut-short"),
        pytest.param("@@ -4,2 +4,2 @@\n l4\n?l5\n", id="unknown-mark"),
        pytest.param("@@ -4,1 +4,2 @@\n l4\n l5\n", id="context-past-old"),
        pytest.param("@@ -4,2 +4,1 @@\n l4\n+l5\n", id="add-past-new"),
        pytest.param(
            "@@ -8 +8,2 @@\n l8\n+x\n@@ -6 +7 @@\n-l6\n+y\n", id="out-of-order"
        ),  # fmt: skip
        pytest.param(
            "@@ -2 +2,2 @@\n l2\n+x\n@@ -9 +9 @@\n-l9\n+y\n",
            id="new-start-off-the-delta",
        ),  # fmt: skip
        pytest.param("@@ -0,1 +0,1 @@\n-a\n+b\n", id="old-line-zero"),
        pytest.param("@@ -4 +4 @@\n-l4\n+x\nstray\n", id="stray-row"),
        pytest.param("@@ -4 +4 @@\n-l4\n+x\n\n", id="blank-after-hunk"),
        pytest.param("@@ -4 +4 @@ \n-l4\n+x\n@@ nonsense @@\n", id="bad-header"),
        pytest.param("@@ x\n-l4\n+x\n", id="bad-first-header"),
    ],
)
def test_a_hunk_that_does_not_parse_drops_the_files_keys(body: str) -> None:
    diff = _HEAD + body
    keys = {"h": _key(5, 5), "other": _key(5, 5, "other.py")}
    assert _reasons(keys, diff) == {"h": rekey.UNREADABLE}
    assert _moved(keys, diff)["other"] == (5, 5)


def test_no_newline_markers_and_blank_context_rows_parse() -> None:
    """``\\ No newline at end of file`` inside and after a hunk is skipped;
    an empty row inside a hunk is context (``diff.suppressBlankEmpty``)."""
    diff = _HEAD + (
        "@@ -3,3 +3,4 @@ def f():\n l3\n\n-l5\n\\ No newline at end of file\n"
        "+x\n+y\n\\ No newline at end of file\n"
    )
    assert _moved({"h": _key(5, 5), "t": _key(6, 7)}, diff) == {
        "h": (5, 6), "t": (7, 8),
    }  # fmt: skip


def test_a_file_shown_twice_drops_its_key() -> None:
    once = _file_diff(PATH, LINES, _edit(LINES, 1, 0, ["x"]))
    assert _reasons({"h": _key(5, 5)}, once + once) == {"h": rekey.TWICE}


@pytest.mark.parametrize(
    "header",
    [
        f"diff --git a/{PATH} b/other.py",
        f"diff --git a/{PATH} b/{PATH}x",
        f"diff --git a/{PATH}?b/{PATH}",
        f"diff --git c/{PATH} d/{PATH}",
        "diff --git a/ b/",
        'diff --git "a/x.py "b/x.py"',
        'diff --git "a/x.py" b/x.py',
        'diff --git "a/x.py" "b/x.py" ',
        'diff --git "a/x\\q.py" "b/x\\q.py"',
        'diff --git "a/\\377.py" "b/\\377.py"',
        'diff --git "a/x.py" "b/y.py"',
        'diff --git "a/x.py',
    ],
)
def test_a_header_that_does_not_parse_blinds_every_unshown_file(header: str) -> None:
    """A file header that cannot be read may name any file: a key in a file
    the diff does not otherwise show is dropped (fail closed)."""
    shown = _file_diff("a.py", LINES, _edit(LINES, 1, 0, ["x"]))
    diff = f"{shown}{header}\n@@ -1 +1 @@\n-a\n+b\n"
    keys = {"a": _key(5, 5, "a.py"), "z": _key(5, 5, "z.py")}
    assert _moved(keys, diff) == {"a": (6, 6), "z": None}
    assert _reasons(keys, diff) == {"z": rekey.BLIND}


def test_text_before_the_first_header_blinds_every_unshown_file() -> None:
    diff = "warning: something\n" + _file_diff("a.py", LINES, LINES[:-1])
    assert _reasons({"z": _key(5, 5, "z.py")}, diff) == {"z": rekey.BLIND}
    assert _moved({"z": _key(5, 5, "z.py")}, "\n\n") == {"z": (5, 5)}


def test_a_quoted_path_is_read_as_git_quotes_it() -> None:
    path = 'dir/café "q"\t\\.py'
    quoted = '"a/dir/caf\\303\\251 \\"q\\"\\t\\\\.py" "b/dir/caf\\303\\251 \\"q\\"\\t\\\\.py"'
    diff = f"diff --git {quoted}\nindex 1..2 100644\n@@ -1 +1,2 @@\n-a\n+b\n+c\n"
    assert _moved({"h": _key(3, 4, path)}, diff) == {"h": (4, 5)}


# --------------------------------------------------------------------------
# Real git: the diff ``GitStacker.diff`` returns
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    argv = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args]
    return subprocess.run(argv, cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()  # fmt: skip


def _write(repo: Path, files: Mapping[str, Sequence[str]]) -> None:
    for name, rows in files.items():
        (repo / name).write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")


def test_real_git_diffs_rekey_onto_the_tips_lines(tmp_path: Path) -> None:
    """
    GIVEN a base and a tip: m.py edited in three places, gone.py deleted,
        old.py renamed, a quoted name edited, run.sh only chmod-ed
    WHEN keys in each are re-keyed from ``GitWorkspace.diff_commits``
    THEN every surviving key line is inside its new span at the tip, an
        untouched span maps exactly, and the deleted and renamed files' keys
        are dropped; a capped diff re-keys only what it shows whole
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    m = [f"m{n}" for n in range(1, 61)]
    odd = [f"q{n}" for n in range(1, 11)]
    odd_name = 'café "q".py'
    _write(repo, {"m.py": m, "gone.py": ["g"] * 5, "old.py": ["o1", "o2"],
                  odd_name: odd, "run.sh": ["echo"]})  # fmt: skip
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    tip_m = _edit(_edit(_edit(m, 50, 2, ["n50"]), 25, 1, ["r25", "r25b"]), 5, 0, ["i5"])
    _write(repo, {"m.py": tip_m, odd_name: _edit(odd, 2, 1)})
    (repo / "gone.py").unlink()
    _git(repo, "mv", "old.py", "new.py")
    (repo / "run.sh").chmod(0o755)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "tip")
    tip = _git(repo, "rev-parse", "HEAD")
    git = GitWorkspace(repo)
    diff = git.diff_commits(base, tip)
    assert diff.startswith("diff --git") and '"a/caf\\303\\251' in diff
    keys = {"a": _key(1, 4, "m.py"), "b": _key(10, 30, "m.py"),
            "c": _key(24, 26, "m.py"), "d": _key(49, 52, "m.py"),
            "e": _key(55, 60, "m.py"), "g": _key(2, 3, "gone.py"),
            "o": _key(1, 2, "old.py"), "q": _key(1, 4, odd_name),
            "s": _key(1, 1, "run.sh")}  # fmt: skip
    moved = _moved(keys, diff)
    assert moved == {"a": (1, 4), "b": (11, 32), "c": (25, 28), "d": (51, 53),
                     "e": (56, 61), "g": None, "o": None, "q": (1, 3),
                     "s": (1, 1)}  # fmt: skip
    assert _reasons(keys, diff) == {"g": rekey.DELETED, "o": rekey.DELETED}
    capped = git.diff_commits(base, tip, max_bytes=len(diff.encode()) // 2)
    partial = _moved(keys, capped)
    assert {h for h, lines in partial.items() if lines is not None} < set(keys)
    assert all(lines in (None, moved[h]) for h, lines in partial.items())


# --------------------------------------------------------------------------
# Property: random hunks on random keys keep spans valid and ordered
# --------------------------------------------------------------------------


def _random_edit(rng: random.Random, old: Sequence[str]) -> list[str]:
    new: list[str] = []
    fresh = 0

    def insert() -> None:
        nonlocal fresh
        for _ in range(rng.randint(1, 3)):
            fresh += 1
            new.append(f"new {fresh}")

    for row in old:
        if rng.random() < 0.1:
            insert()
        roll = rng.random()
        if roll < 0.15:
            continue
        if roll < 0.3:
            insert()
        else:
            new.append(row)
    if rng.random() < 0.1:
        insert()
    return new


def _expected(
    old: Sequence[str], new: Sequence[str], first: int, last: int
) -> tuple[int, int] | None:
    """The rule computed independently from difflib's opcodes: the tip
    lines of the span's surviving lines and of every change it touches."""
    found: list[int] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes():
        if tag == "equal":
            found += [j1 + 1 + x - i1 for x in range(i1, i2) if first <= x + 1 <= last]
        elif (i1 < i2 and i1 + 1 <= last and first <= i2) or (
            i1 == i2 and first < i1 + 1 <= last
        ):
            found += list(range(j1 + 1, j2 + 1))
    return (min(found), max(found)) if found else None


def _spans(rng: random.Random, size: int) -> list[tuple[int, int]]:
    """Random disjoint, ordered spans over lines 1..size."""
    cuts = sorted(rng.sample(range(1, size + 1), rng.randint(1, size)))
    ends = [*(c - 1 for c in cuts[1:]), size]
    return [(f, rng.randint(f, end)) for f, end in zip(cuts, ends, strict=True)]


def _check(
    old: Sequence[str],
    new: Sequence[str],
    spans: Sequence[tuple[int, int]],
    diff: str,
    path: str = PATH,
) -> None:
    keys = {f"h-{i}": _key(f, last, path) for i, (f, last) in enumerate(spans)}
    moved = _moved(keys, diff)
    placed = [moved[h] for h in keys]
    for (f, last), lines in zip(spans, placed, strict=True):
        assert lines == _expected(old, new, f, last), (old, new, f, last)
        if lines is not None:
            assert 1 <= lines[0] <= lines[1] <= len(new)
    kept = [lines for lines in placed if lines is not None]
    assert kept == sorted(kept)
    assert all(a[1] <= b[1] for a, b in zip(kept, kept[1:], strict=False))


@pytest.mark.parametrize("seed", range(4))
def test_random_hunks_keep_random_spans_valid_and_ordered(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(100):
        old = [f"old {n}" for n in range(1, rng.randint(1, 60) + 1)]
        new = _random_edit(rng, old)
        if new == old:
            continue
        diff = _file_diff(PATH, old, new, context=rng.choice([0, 1, 3]))
        _check(old, new, _spans(rng, len(old)), diff)


def test_random_edits_through_real_git_match_the_oracle(tmp_path: Path) -> None:
    """The property again on 30 random edits committed in a real repo and
    diffed by ``GitWorkspace.diff_commits`` (git's own hunks and headers)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, {"m.py": []})
    _git(repo, "add", "m.py")
    git = GitWorkspace(repo)
    rng = random.Random(2026)
    cases = 0
    while cases < 30:
        old = [f"old {n}" for n in range(1, rng.randint(1, 40) + 1)]
        new = _random_edit(rng, old)
        if new == old:
            continue
        commits = []
        for rows in (old, new):
            _write(repo, {"m.py": rows})
            _git(repo, "commit", "-q", "--allow-empty", "-am", "c")
            commits.append(_git(repo, "rev-parse", "HEAD"))
        diff = git.diff_commits(commits[0], commits[1])
        assert diff.startswith("diff --git a/m.py b/m.py\n")
        _check(old, new, _spans(rng, len(old)), diff, "m.py")
        cases += 1
