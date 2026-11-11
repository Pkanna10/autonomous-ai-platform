"""The framework catalogue and the deal (U-portfolio, ``idea_frameworks``).

The catalogue is data: each entry its id, source, evidence grade, numbered
steps with the product each must output, and whether it is dealt. The deal
is a seeded, balanced rotation over (library, run, round): the properties
are tested, not the scheme.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

import pytest

from autonomous_ai_agents.optimization import idea_frameworks as fw
from autonomous_ai_agents.optimization.idea_frameworks import (
    ACTIVE,
    CATALOGUE,
    DEAL_LIBRARIES,
    DEAL_ROUNDS,
    DEAL_RUNS,
    DEAL_SEED,
    DEAL_SIZE,
    GRADES,
    INACTIVE,
    SIT_TOOLS,
    Deal,
    by_id,
    check_library,
    check_run,
    deal,
)

ACTIVE_STEPS = {
    "bentley": 5, "per_element": 5, "backend": 4, "skiena": 6, "polya": 4,
    "from_spec": 4, "ifr": 4, "trim": 5, "sit": 4, "recall": 3,
}  # fmt: skip
"""The owner's ten active procedures, in order, with their step counts."""
INACTIVE_IDS = (
    "triz_matrix", "morphological", "synectics", "wordtree", "scamper",
    "ck_theory", "lean_wastes", "verbalized_sampling",
)  # fmt: skip


def _design(
    libraries: Iterable[str] = DEAL_LIBRARIES, rounds: int = DEAL_ROUNDS
) -> list[Deal]:
    return [
        deal(library, run, number)
        for library in libraries
        for run in range(1, DEAL_RUNS + 1)
        for number in range(1, rounds + 1)
    ]


def _counts(deals: Iterable[Deal]) -> Counter[str]:
    found: Counter[str] = Counter({f.id: 0 for f in ACTIVE})
    for d in deals:
        found.update(p.framework.id for p in d.procedures)
    return found


# --------------------------------------------------------------------------
# The catalogue
# --------------------------------------------------------------------------


def test_the_active_procedures_are_the_owners_ten_in_order() -> None:
    assert [f.id for f in ACTIVE] == list(ACTIVE_STEPS)
    assert {f.id: len(f.steps) for f in ACTIVE} == ACTIVE_STEPS
    assert all(f.active for f in ACTIVE)


def test_only_the_triz_matrix_states_a_reason_for_being_inactive() -> None:
    assert {f.id: f.note for f in CATALOGUE if f.note} == {
        "triz_matrix": "needs the matrix embedded as data"}  # fmt: skip


def test_the_inactive_entries_record_their_steps_and_are_never_dealt() -> None:
    assert tuple(f.id for f in INACTIVE) == INACTIVE_IDS
    assert all(not f.active and len(f.steps) >= 3 for f in INACTIVE)
    dealt = {p.framework.id for d in _design() for p in d.procedures}
    assert dealt.isdisjoint(INACTIVE_IDS)
    assert CATALOGUE == (*ACTIVE, *INACTIVE)


def test_every_entry_has_an_id_a_source_a_stated_grade_and_numbered_products() -> None:
    ids = [f.id for f in CATALOGUE]
    assert len(set(ids)) == len(ids)
    assert set(GRADES) == {"A", "B", "C", "D"}
    for f in CATALOGUE:
        assert re.fullmatch(r"[a-z][a-z_]{1,30}", f.id), f.id
        assert f.name and f.source and f.grade in GRADES
        assert [s.number for s in f.steps] == list(range(1, len(f.steps) + 1))
        for s in f.steps:
            assert s.task.strip() and s.product.strip(), (f.id, s.number)
            assert "\n" not in s.task + s.product
        assert by_id(f.id) is f
    with pytest.raises(KeyError):
        by_id("not_a_framework")


def test_only_sit_deals_a_tool_and_it_has_the_four() -> None:
    assert set(SIT_TOOLS) == {
        "multiplication", "division", "task unification", "attribute dependency",
    }  # fmt: skip
    assert by_id("sit").tools == SIT_TOOLS
    assert all(f.tools == () for f in CATALOGUE if f.id != "sit")


# --------------------------------------------------------------------------
# The deal
# --------------------------------------------------------------------------


def test_a_deal_is_three_distinct_active_procedures_and_repeatable() -> None:
    for d in _design():
        ids = [p.framework.id for p in d.procedures]
        assert len(ids) == DEAL_SIZE == len(set(ids))
        assert [p.position for p in d.procedures] == [1, 2, 3]
        assert d.seed == DEAL_SEED
        assert d == deal(d.library, d.run, d.round)
    cells = [d.cell for d in _design()]
    assert len(set(cells)) == len(cells)


def test_each_procedure_is_dealt_equally_often_over_the_design() -> None:
    """GIVEN the sprint's 4 libraries x 3 runs x rounds 1-2 (X2-P and X2-F)
    or 1-3 THEN the counts differ by at most 1, and so after round 1 alone."""
    for rounds in range(1, DEAL_ROUNDS + 1):
        counts = _counts(_design(rounds=rounds))
        assert sum(counts.values()) == len(DEAL_LIBRARIES) * DEAL_RUNS * rounds * 3
        assert max(counts.values()) - min(counts.values()) <= 1, (rounds, counts)


def test_each_library_meets_as_many_procedures_as_the_design_allows() -> None:
    """Round 1 (9 places): 9 distinct; rounds 1-2 (18 places): all ten;
    rounds 1-3 (27 places): every procedure at least twice."""
    for library in DEAL_LIBRARIES:
        for rounds, distinct, least in ((1, 9, 0), (2, 10, 1), (3, 10, 2)):
            seen = _counts(d for d in _design(rounds=rounds) if d.library == library)
            assert sum(v > 0 for v in seen.values()) == distinct, (library, rounds)
            assert min(seen.values()) >= least, (library, rounds, seen)


def test_sits_tool_is_dealt_by_the_rotation_in_balance() -> None:
    for rounds in (2, DEAL_ROUNDS):
        tools: Counter[str] = Counter({t: 0 for t in SIT_TOOLS})
        for d in _design(rounds=rounds):
            for p in d.procedures:
                assert (p.tool is not None) is (p.framework.id == "sit")
                if p.tool is not None:
                    tools[p.tool] += 1
        assert max(tools.values()) - min(tools.values()) <= 1, tools


def test_the_deal_depends_on_the_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    before = [tuple(p.framework.id for p in d.procedures) for d in _design()]
    monkeypatch.setattr(fw, "DEAL_SEED", "another seed")
    fw._order.cache_clear()
    try:
        after = [tuple(p.framework.id for p in d.procedures) for d in _design()]
    finally:
        monkeypatch.undo()
        fw._order.cache_clear()
    assert after != before


def test_a_round_past_the_design_still_deals_three_distinct() -> None:
    late = deal(DEAL_LIBRARIES[0], 1, DEAL_ROUNDS + 2)
    assert len({p.framework.id for p in late.procedures}) == DEAL_SIZE


@pytest.mark.parametrize(
    "library", ["", "Tomli", "no-such-lib", "../x", "requests", "pyparsing"]
)
def test_a_library_off_the_design_is_refused(library: str) -> None:
    with pytest.raises(ValueError, match="deal library"):
        check_library(library)
    with pytest.raises(ValueError, match="deal library"):
        deal(library, 1, 1)


@pytest.mark.parametrize("run", [0, 4, 9, 10, -1, True, 1.0])
def test_a_run_outside_the_designs_three_is_refused(run: object) -> None:
    with pytest.raises(ValueError, match="deal run"):
        check_run(run)


@pytest.mark.parametrize("number", [0, -2, False])
def test_a_round_below_one_is_refused(number: object) -> None:
    with pytest.raises(ValueError, match="deal round"):
        deal(DEAL_LIBRARIES[0], 1, number)  # type: ignore[arg-type]


def test_the_design_libraries_are_the_sprints_four() -> None:
    assert DEAL_LIBRARIES == ("sqlparse", "tomli", "mistune", "markdown")
    for library in DEAL_LIBRARIES:
        assert check_library(library) == library
    assert [check_run(r) for r in (1, 2, 3)] == [1, 2, 3] and DEAL_RUNS == 3
