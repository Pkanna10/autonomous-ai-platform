"""The idea pipeline's deterministic stages S4a and S4b (Wave 2, N3b; spec
amendment D51-D53, D8 amended, section 6 N3b).

``deterministic_filter`` gates each lens or leap idea on its anchor's Amdahl
ceiling, drops structural duplicates and keeps only what is not already on
the table; ``portfolio`` picks 3-5 of the survivors by coverage quotas and
interleaves them with the obvious ideas. Every quota and every gate rule is
pinned by its own test. Candidates are hand-built ``IdeaCandidate`` values;
the entry-point test computes its ceiling with the real ``amdahl_ceiling``.
Nothing here calls a model, a transport or git.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

import pytest

from autonomous_ai_agents.common.models import (
    ChangeClass,
    Direction,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Lesson,
    Objective,
    ObjectiveKind,
    VerdictOutcome,
)
from autonomous_ai_agents.optimization.idea_context import amdahl_ceiling
from autonomous_ai_agents.optimization.idea_portfolio import (
    deterministic_filter,
    lesson_titles,
    portfolio,
    rotation,
    signature,
)
from autonomous_ai_agents.optimization.idea_types import (
    LENS_LANES,
    Anchor,
    CodeContext,
    CodeDocument,
    FunctionSpan,
    GenerateEvent,
    IdeaCandidate,
    Lane,
    Mechanism,
    MorphCell,
    Tier,
    Typicality,
)
from autonomous_ai_agents.optimization.ranking import rank_generated

FLOOR = 0.04
CELLS = tuple(MorphCell)


def _objective(kind: ObjectiveKind = ObjectiveKind.runtime) -> Objective:
    return Objective(
        project_id="p1",
        kind=kind,
        metric="wall_time_s",
        direction=Direction.minimize,
        min_relative_gain=FLOOR,
        description="faster",
    )


def _idea(
    ident: str,
    lane: Lane = Lane.eliminate,
    *,
    anchor: str | None = "f",
    path: str = "pkg/core.py",
    mechanism: Mechanism = Mechanism.remove_work,
    cells: Sequence[MorphCell] = (MorphCell.work_eliminate,),
    tier: Tier = Tier.exploratory,
    ceiling: float | None = 0.5,
    title: str | None = None,
    slug: str | None = None,
    change_class: ChangeClass = ChangeClass.efficiency,
    expected_gain: float = 0.1,
    hotspots: Sequence[str] = ("h1",),
) -> IdeaCandidate:
    return IdeaCandidate(
        id=ident,
        lane=lane,
        title=title or f"Idea {ident}",
        technique_slug=slug,
        hotspot_ids=tuple(hotspots),
        change_summary="Change the hot loop.",
        justification_summary="It runs on every call.",
        change_class=change_class,
        expected_gain=expected_gain,
        provability=0.5,
        risk=0.2,
        depends_on_path=path,
        depends_on_quote="for item in items: total += item",
        precondition="Items do not change.",
        equivalence_summary="Same sums.",
        mechanism=mechanism,
        morph_cells=tuple(cells),
        tier=tier,
        typicality=Typicality.uncommon,
        anchor=None if anchor is None else Anchor(path=path, qualname=anchor),
        ceiling=ceiling,
    )


def _filter(
    others: Sequence[IdeaCandidate],
    *,
    obvious: Sequence[IdeaCandidate] = (),
    kind: ObjectiveKind = ObjectiveKind.runtime,
    multiplier: float = 1.0,
    avoid: Sequence[str] = (),
    lessons: Collection[str] = (),
    slugs: Sequence[str] = (),
    notes: list[str] | None = None,
    events: list[GenerateEvent] | None = None,
) -> tuple[str, ...]:
    kept = deterministic_filter(
        obvious,
        others,
        floor=FLOOR,
        objective=_objective(kind),
        avoid=avoid,
        lesson_titles=lessons,
        multiplier=multiplier,
        notes=[] if notes is None else notes,
        shown_slugs=slugs,
        events=events,
    )
    return tuple(idea.id for idea in kept)


# --------------------------------------------------------------------------
# The Amdahl gate (D51)
# --------------------------------------------------------------------------


def test_the_gate_drops_below_the_floor_and_keeps_at_it_by_default() -> None:
    notes: list[str] = []
    below = _idea("a", anchor="f", ceiling=0.9 * FLOOR)
    at = _idea("b", anchor="g", ceiling=1.0 * FLOOR)
    assert _filter([below, at], notes=notes) == ("b",)
    assert len(notes) == 1
    assert "'Idea a'" in notes[0]
    assert "3.6%" in notes[0] and "4.0%" in notes[0]


def test_the_gate_at_one_and_a_half_drops_1_4x_and_keeps_1_5x() -> None:
    low = _idea("a", anchor="f", ceiling=1.4 * FLOOR)
    high = _idea("b", anchor="g", ceiling=1.5 * FLOOR)
    assert _filter([low, high], multiplier=1.5) == ("b",)
    assert _filter([low, high], multiplier=1.0) == ("a", "b")


def test_throughput_is_gated_like_runtime() -> None:
    low = _idea("a", ceiling=0.01)
    assert _filter([low], kind=ObjectiveKind.throughput) == ()


@pytest.mark.parametrize(
    "kind",
    [ObjectiveKind.peak_memory, ObjectiveKind.quality_metric, ObjectiveKind.custom],
)
def test_a_non_time_objective_is_never_gated(kind: ObjectiveKind) -> None:
    tiny = _idea("a", anchor="f", ceiling=0.0)
    unknown = _idea("b", anchor="g", ceiling=None)
    assert _filter([tiny, unknown], kind=kind) == ("a", "b")


def test_an_anchored_idea_with_an_unknown_ceiling_is_dropped_on_time() -> None:
    notes: list[str] = []
    assert _filter([_idea("a", ceiling=None)], notes=notes) == ()
    assert "ceiling is unknown" in notes[0]


@pytest.mark.parametrize("kind", [ObjectiveKind.runtime, ObjectiveKind.peak_memory])
def test_an_idea_with_no_anchor_is_dropped_not_passed(kind: ObjectiveKind) -> None:
    notes: list[str] = []
    assert _filter([_idea("a", anchor=None)], kind=kind, notes=notes) == ()
    assert "no anchor" in notes[0]


def _entry_point_context() -> tuple[CodeContext, Hotspot, Hotspot]:
    main = Hotspot(
        id="h_main",
        project_id="p1",
        workload_id="w1",
        file_path="pkg/app.py",
        symbol="main",
        self_time_s=0.1,
        total_time_s=10.0,
        share=0.01,
    )
    helper = Hotspot(
        id="h_helper",
        project_id="p1",
        workload_id="w1",
        file_path="pkg/app.py",
        symbol="helper",
        self_time_s=0.3,
        total_time_s=0.3,
        share=0.03,
    )
    spans = (
        FunctionSpan(
            path="pkg/app.py",
            qualname="main",
            start_line=1,
            end_line=5,
            hotspot_ids=("h_main",),
        ),  # fmt: skip
        FunctionSpan(
            path="pkg/app.py",
            qualname="helper",
            start_line=7,
            end_line=9,
            hotspot_ids=("h_helper",),
        ),  # fmt: skip
    )
    document = CodeDocument(
        path="pkg/app.py", start_line=1, end_line=9, rendered="", raw="", spans=spans
    )
    context = CodeContext(documents=(document,), totals_by_workload={"w1": 10.0})
    return context, main, helper


def test_an_entry_point_listing_is_gated_at_the_anchored_helpers_share() -> None:
    context, main, helper = _entry_point_context()
    anchor = Anchor(path="pkg/app.py", qualname="helper")
    ceiling = amdahl_ceiling(anchor, [main], context, profile=[main, helper])
    assert ceiling == pytest.approx(0.03)
    idea = _idea("a", path="pkg/app.py", anchor="helper", hotspots=("h_main",))
    gated = idea.model_copy(update={"ceiling": ceiling})
    assert _filter([gated]) == ()  # 3 % helper under a 4 % floor
    entry = Anchor(path="pkg/app.py", qualname="main")
    whole = amdahl_ceiling(entry, [main], context, profile=[main, helper])
    assert whole == pytest.approx(1.0)  # the listing alone would have passed


# --------------------------------------------------------------------------
# The signature and dedup (D52)
# --------------------------------------------------------------------------


def test_identical_signatures_keep_the_earlier_in_lane_then_model_order() -> None:
    notes: list[str] = []
    first = _idea("a", Lane.eliminate)
    same_lane = _idea("b", Lane.eliminate)
    later_lane = _idea("c", Lane.far)
    assert _filter([first, same_lane, later_lane], notes=notes) == ("a",)
    assert sum("duplicate of 'Idea a'" in note for note in notes) == 2


def test_equal_mechanism_and_cells_on_different_anchors_are_both_kept() -> None:
    assert _filter([_idea("a", anchor="f"), _idea("b", anchor="g")]) == ("a", "b")
    elsewhere = _idea("c", anchor="f", path="pkg/other.py")
    assert _filter([_idea("a", anchor="f"), elsewhere]) == ("a", "c")


def test_a_different_mechanism_on_one_anchor_is_distinct() -> None:
    other = _idea("b", mechanism=Mechanism.batching)
    assert _filter([_idea("a"), other]) == ("a", "b")


def test_a_signature_differing_only_in_a_secondary_cell_is_distinct() -> None:
    one = _idea("a", cells=(MorphCell.work_eliminate, MorphCell.timing_lazy))
    two = _idea("b", cells=(MorphCell.work_eliminate, MorphCell.timing_precompute))
    assert _filter([one, two]) == ("a", "b")


def test_the_cells_compare_as_a_set() -> None:
    one = _idea("a", cells=(MorphCell.work_eliminate, MorphCell.timing_lazy))
    two = _idea("b", cells=(MorphCell.timing_lazy, MorphCell.work_eliminate))
    assert signature(one) == signature(two)
    assert _filter([one, two]) == ("a",)


def test_the_anchor_leads_the_signature_and_hotspots_stand_in_without_one() -> None:
    anchored = _idea("a", anchor="f", hotspots=("h2", "h1"))
    assert signature(anchored)[0] == ("anchor", "pkg/core.py", "f")
    bare = _idea("b", anchor=None, hotspots=("h2", "h1"))
    assert signature(bare)[0] == ("hotspots", "h1", "h2")
    assert signature(bare)[1:] == (Mechanism.remove_work, ("work:eliminate",))


def test_a_gated_idea_does_not_shadow_a_later_duplicate() -> None:
    # Same anchor means the same ceiling in the pipeline; a hand-built pair
    # with differing ceilings shows dedup only counts what passed the gate.
    low = _idea("a", ceiling=0.0)
    high = _idea("b", ceiling=0.5)
    assert _filter([low, high]) == ("b",)


# --------------------------------------------------------------------------
# Non-obvious (D52)
# --------------------------------------------------------------------------


def test_an_s1_signature_is_not_non_obvious() -> None:
    notes: list[str] = []
    s1 = _idea("o1", Lane.obvious, title="Cache the regex")
    same = _idea("a", title="Precompile the pattern")
    kept = _filter([same, _idea("b", anchor="g")], obvious=[s1], notes=notes)
    assert kept == ("o1", "b")
    assert "obvious idea 'Cache the regex'" in notes[0]


def test_an_unanchored_s1_idea_never_matches_an_anchored_one() -> None:
    s1 = _idea("o1", Lane.obvious, anchor=None)
    assert _filter([_idea("a")], obvious=[s1]) == ("o1", "a")


def test_an_avoid_title_is_not_non_obvious_spacing_and_case_aside() -> None:
    notes: list[str] = []
    idea = _idea("a", title="Cache  the Regex")
    assert _filter([idea, _idea("b", anchor="g")], avoid=["cache the regex"],
                   notes=notes) == ("b",)  # fmt: skip
    assert "avoid_titles" in notes[0]


def test_a_lesson_title_is_not_non_obvious_even_one_holding_a_colon() -> None:
    lesson = Lesson(
        outcome=VerdictOutcome.reject,
        text="w1 -> Memo: cache parse results: reject (-1.0%)",
    )
    titles = lesson_titles([lesson])
    assert titles == frozenset({"Memo: cache parse results"})
    notes: list[str] = []
    idea = _idea("a", title="memo: cache parse results")
    assert _filter([idea], lessons=titles, notes=notes) == ()
    assert "lesson title" in notes[0]


@pytest.mark.parametrize("route", ["avoid", "lesson"])
def test_a_twin_of_an_avoided_or_learnt_idea_is_a_duplicate(route: str) -> None:
    # Dedup runs before the non-obvious test (4.2b step 4): a restatement
    # of an already-tried idea under a fresh title is still dropped.
    notes: list[str] = []
    tried = _idea("a", anchor="h", title="Cache the regex")
    twin = _idea("b", anchor="h", title="Precompile the pattern")
    titles = ["cache the regex"]
    kept = _filter(
        [tried, twin],
        avoid=titles if route == "avoid" else (),
        lessons=titles if route == "lesson" else (),
        notes=notes,
    )
    assert kept == ()
    assert len(notes) == 2
    assert "duplicate of 'Cache the regex'" in notes[1]


def test_a_shown_technique_is_not_non_obvious_in_matched_mode() -> None:
    notes: list[str] = []
    idea = _idea("a", slug="memoize-pure-function")
    assert _filter([idea], slugs=["memoize-pure-function"], notes=notes) == ()
    assert "shown technique" in notes[0]
    assert _filter([idea]) == ("a",)  # blind mode: no slug is shown


def test_s1_ideas_are_never_gated_deduplicated_or_filtered() -> None:
    s1 = (
        _idea("o1", Lane.obvious, anchor=None, ceiling=None, title="Same"),
        _idea("o2", Lane.obvious, ceiling=0.0, title="same"),
        _idea("o3", Lane.obvious, ceiling=0.0, slug="memoize"),
    )
    kept = _filter([], obvious=s1, avoid=["same"], slugs=["memoize"])
    assert kept == ("o1", "o2", "o3")


def test_every_drop_is_an_idea_dropped_event_when_events_are_given() -> None:
    notes: list[str] = []
    events: list[GenerateEvent] = []
    ideas = [
        _idea("a", anchor=None),
        _idea("b", ceiling=0.0),
        _idea("c", anchor="g", ceiling=None),
        _idea("d", anchor="h", title="Done before"),
        _idea("e", anchor="h", mechanism=Mechanism.batching),
        _idea("f", anchor="k", slug="memoize"),
        _idea("g", anchor="m", title="Learnt"),
        _idea("h", anchor="h", mechanism=Mechanism.batching),
        _idea("i", anchor="o", mechanism=Mechanism.algorithm),
    ]
    s1 = [_idea("o1", Lane.obvious, anchor="o", mechanism=Mechanism.algorithm)]
    kept = _filter(ideas, obvious=s1, avoid=["done before"], lessons=["learnt"],
                   slugs=["memoize"], notes=notes, events=events)  # fmt: skip
    assert kept == ("o1", "e")
    assert [event.data["reason"] for event in events] == [
        "no_anchor",
        "below_gate",
        "ceiling_unknown",
        "avoided_title",
        "shown_technique",
        "lesson_title",
        "duplicate",
        "obvious_signature",
    ]
    assert {event.code for event in events} == {"idea_dropped"}
    assert [event.message for event in events] == notes
    assert events[0].data["lane"] == "eliminate"
    assert events[0].data["title"] == "Idea a"
    assert _filter(ideas, obvious=s1) != ()  # events=None: notes only


@pytest.mark.parametrize(
    ("floor", "multiplier"),
    [(-0.1, 1.0), (1.1, 1.0), (0.04, 0.99), (0.04, float("inf"))],
)
def test_the_filter_refuses_an_impossible_floor_or_multiplier(
    floor: float, multiplier: float
) -> None:
    with pytest.raises(ValueError, match="floor|multiplier"):
        deterministic_filter(
            (), (), floor=floor, objective=_objective(), avoid=(),
            lesson_titles=(), multiplier=multiplier, notes=[],
        )  # fmt: skip


# --------------------------------------------------------------------------
# lesson_titles and rotation
# --------------------------------------------------------------------------


def test_lesson_titles_parse_on_the_last_outcome() -> None:
    lessons = [
        Lesson(outcome=VerdictOutcome.keep, text="general -> Use a set: keep (+3.0%)"),
        Lesson(outcome=VerdictOutcome.keep, text="general -> Odd: keep: keep"),
        Lesson(outcome=VerdictOutcome.review, text="a, b -> x -> y: review"),
        Lesson(outcome=VerdictOutcome.keep, text="free text with no shape"),
        Lesson(outcome=VerdictOutcome.keep, text="general -> Wrong: reject"),
        Lesson(outcome=VerdictOutcome.keep, text="general ->  : keep"),
    ]
    assert lesson_titles(lessons) == frozenset({"Use a set", "Odd: keep", "x -> y"})
    assert lesson_titles([]) == frozenset()


def test_rotation_is_a_stable_permutation_that_changes_with_the_seed() -> None:
    lanes = (*LENS_LANES, Lane.leap)
    first = rotation("run-1", lanes)
    assert sorted(first) == sorted(lanes)
    assert rotation("run-1", lanes) == first
    others = {rotation(f"run-{i}", lanes) for i in range(2, 8)}
    assert len(others | {first}) > 1
    assert rotation("run-1", (Lane.far, Lane.far, Lane.leap)) in {
        (Lane.far, Lane.leap),
        (Lane.leap, Lane.far),
    }
    assert rotation("run-1", ()) == ()


# --------------------------------------------------------------------------
# The portfolio (D53)
# --------------------------------------------------------------------------

ORDER = (*LENS_LANES, Lane.leap)


def _pick(
    candidates: Sequence[IdeaCandidate],
    *,
    obvious: Sequence[IdeaCandidate] = (),
    order: Sequence[Lane] = ORDER,
    minimum: int = 3,
    maximum: int = 5,
    notes: list[str] | None = None,
) -> tuple[str, ...]:
    picked = portfolio(
        obvious,
        candidates,
        rotation=order,
        minimum=minimum,
        maximum=maximum,
        notes=[] if notes is None else notes,
    )
    return tuple(idea.id for idea in picked)


def _distinct(ident: str, lane: Lane, slot: int, **extra: object) -> IdeaCandidate:
    """An idea on its own anchor and primary cell (slot picks both)."""
    fields: dict[str, object] = {"anchor": f"fn{slot}", "cells": (CELLS[slot],)}
    fields.update(extra)
    return _idea(ident, lane, **fields)  # type: ignore[arg-type]


def test_at_most_one_idea_per_lane() -> None:
    ideas = [
        _distinct("e1", Lane.eliminate, 0),
        _distinct("e2", Lane.eliminate, 1),
        _distinct("a1", Lane.assume_less, 2),
        _distinct("f1", Lane.far, 3),
    ]
    assert _pick(ideas) == ("e1", "a1", "f1")


def test_at_most_one_idea_per_anchor() -> None:
    ideas = [
        _distinct("e1", Lane.eliminate, 0),
        _distinct("a1", Lane.assume_less, 1, anchor="fn0"),
        _distinct("a2", Lane.assume_less, 2),
        _distinct("f1", Lane.far, 3),
    ]
    assert _pick(ideas) == ("e1", "a2", "f1")


def test_at_most_one_idea_per_primary_cell() -> None:
    shared = (CELLS[0], CELLS[5])
    ideas = [
        _distinct("e1", Lane.eliminate, 0, cells=shared),
        _distinct("a1", Lane.assume_less, 1, cells=(CELLS[0],)),
        _distinct("a2", Lane.assume_less, 2, cells=(CELLS[5], CELLS[0])),
        _distinct("f1", Lane.far, 3),
    ]
    assert _pick(ideas) == ("e1", "a2", "f1")


def test_lanes_are_visited_in_the_rotation() -> None:
    ideas = [_distinct(lane.value, lane, slot) for slot, lane in enumerate(ORDER)]
    order = (
        Lane.leap,
        Lane.far,
        Lane.recombine,
        *LENS_LANES[:3],
        Lane.resolve_tradeoff,
    )
    assert _pick(ideas, order=order) == (
        "leap", "far", "recombine", "eliminate", "assume_less",
    )  # fmt: skip
    stray = _distinct("s", Lane.obvious, 9)
    assert _pick([stray, *ideas[:2]], order=(Lane.assume_less,)) == (
        "assume_less", "s", "eliminate",
    )  # fmt: skip


def test_three_to_five_are_picked_and_fewer_when_fewer_survive() -> None:
    notes: list[str] = []
    ideas = [_distinct(lane.value, lane, slot) for slot, lane in enumerate(ORDER)]
    assert len(_pick(ideas)) == 5
    assert _pick(ideas[:2], notes=notes) == ("eliminate", "assume_less")
    assert notes == ["portfolio: only 2 non-obvious idea(s) survive; all are taken"]
    empty: list[str] = []
    assert _pick([], notes=empty) == ()
    assert empty == ["portfolio: no non-obvious idea survives"]


def test_the_relaxation_order_when_only_two_lanes_survive() -> None:
    notes: list[str] = []
    ideas = [
        _distinct("e1", Lane.eliminate, 0),
        _distinct("e2", Lane.eliminate, 0),  # same anchor and cell as e1
        _distinct("e3", Lane.eliminate, 1),
        _distinct("a1", Lane.assume_less, 2),
    ]
    # Relaxed quotas still break ties: e3 shares only the lane, e2 all three.
    assert _pick(ideas, notes=notes) == ("e1", "a1", "e3")
    assert notes == [
        "portfolio: relaxed the one-per-primary-cell quota to reach 3 ideas",
        "portfolio: relaxed the one-per-anchor quota to reach 3 ideas",
        "portfolio: relaxed the one-per-lane quota to reach 3 ideas",
    ]


def test_relaxation_stops_once_the_minimum_is_reached() -> None:
    notes: list[str] = []
    ideas = [
        _distinct("e1", Lane.eliminate, 0),
        _distinct("a1", Lane.assume_less, 1),
        _distinct("a2", Lane.assume_less, 2, cells=(CELLS[0],)),
        _distinct("f1", Lane.far, 3, anchor="fn0", cells=(CELLS[1],)),
    ]
    # Three lanes, but far shares e1's anchor and a2 shares e1's cell.
    assert _pick(ideas, notes=notes) == ("e1", "a1", "f1")
    assert notes == [
        "portfolio: relaxed the one-per-primary-cell quota to reach 3 ideas",
        "portfolio: relaxed the one-per-anchor quota to reach 3 ideas",
    ]


def test_a_transformational_idea_is_added_last_when_there_is_room() -> None:
    notes: list[str] = []
    ideas = [
        _distinct("e1", Lane.eliminate, 0),
        _distinct("e2", Lane.eliminate, 1),
        _distinct("e3", Lane.eliminate, 2, tier=Tier.transformational),
        _distinct("a1", Lane.assume_less, 3),
    ]
    assert _pick(ideas, notes=notes) == ("e1", "a1", "e2", "e3")
    assert notes[-1] == "portfolio: 'Idea e3' (transformational) added (tier quota)"


def test_a_transformational_idea_replaces_the_last_pick_when_full() -> None:
    notes: list[str] = []
    ideas = [
        _distinct("e1", Lane.eliminate, 0),
        _distinct("a1", Lane.assume_less, 1),
        _distinct("f1", Lane.far, 2),
        _distinct("leap", Lane.leap, 3, tier=Tier.transformational),
    ]
    assert _pick(ideas, maximum=3, notes=notes) == ("e1", "a1", "leap")
    assert notes == [
        "portfolio: 'Idea leap' (transformational) replaces 'Idea f1' (tier quota)"
    ]


def test_a_transformational_idea_replaces_the_pick_that_blocks_it() -> None:
    notes: list[str] = []
    ideas = [
        _distinct("e1", Lane.eliminate, 0),
        _distinct("e2", Lane.eliminate, 1, tier=Tier.transformational),
        _distinct("a1", Lane.assume_less, 2),
        _distinct("f1", Lane.far, 3),
    ]
    # Room for five, but e2 shares e1's lane: e2 takes e1's place.
    assert _pick(ideas, notes=notes) == ("e2", "a1", "f1")
    assert notes == [
        "portfolio: 'Idea e2' (transformational) replaces 'Idea e1' (tier quota)"
    ]


def test_a_transformational_leap_replaces_the_leap_first_in_the_rotation() -> None:
    notes: list[str] = []
    ideas = [
        _distinct("l1", Lane.leap, 0),
        _distinct("l2", Lane.leap, 1, tier=Tier.transformational),
        _distinct("e1", Lane.eliminate, 2),
        _distinct("a1", Lane.assume_less, 3),
        _distinct("f1", Lane.far, 4),
    ]
    order = (Lane.leap, *LENS_LANES)
    # The latest picks are tried first; only removing l1 lets l2 fit.
    assert _pick(ideas, order=order, notes=notes) == ("l2", "e1", "a1", "f1")
    assert notes == [
        "portfolio: 'Idea l2' (transformational) replaces 'Idea l1' (tier quota)"
    ]


def test_a_transformational_idea_that_fits_no_swap_relaxes_the_tier_quota() -> None:
    notes: list[str] = []
    ideas = [
        _distinct("e1", Lane.eliminate, 0),
        _distinct("a1", Lane.assume_less, 1),
        _distinct("f1", Lane.far, 2),
        # e1's lane, a1's anchor, f1's primary cell: no single swap fits.
        _distinct("t", Lane.eliminate, 2, anchor="fn1", tier=Tier.transformational),
    ]
    assert _pick(ideas, notes=notes) == ("e1", "a1", "f1")
    assert notes == [
        "portfolio: relaxed the tier quota: no transformational idea fits the others"
    ]


def test_a_transformational_idea_already_picked_needs_nothing_more() -> None:
    notes: list[str] = []
    ideas = [
        _distinct("e1", Lane.eliminate, 0, tier=Tier.transformational),
        _distinct("a1", Lane.assume_less, 1),
        _distinct("f1", Lane.far, 2),
        _distinct("l1", Lane.leap, 3, tier=Tier.transformational),
    ]
    assert _pick(ideas, maximum=3, notes=notes) == ("e1", "a1", "f1")
    assert notes == []


def test_the_returned_order_interleaves_obvious_and_non_obvious() -> None:
    obvious = [_idea(f"O{i}", Lane.obvious, anchor=None) for i in range(1, 6)]
    lanes = LENS_LANES[:4] + (Lane.leap,)
    news = [
        _distinct(
            f"N{i}", lane, i, tier=Tier.transformational if i == 5 else Tier.exploratory
        )  # fmt: skip
        for i, lane in enumerate(lanes, start=1)
    ]
    order = _pick(news, obvious=obvious)
    assert order == ("O1", "N1", "N2", "O2", "N3", "N4", "O3", "N5", "O4", "O5")
    assert _pick(news[:1], obvious=obvious[:2], minimum=1) == ("O1", "N1", "O2")
    assert _pick(news[:3], obvious=()) == ("N1", "N2", "N3")


def _hypotheses(ideas: Sequence[IdeaCandidate]) -> list[Hypothesis]:
    return [
        Hypothesis(
            id=idea.id,
            project_id="p1",
            source=HypothesisSource.novel,
            title=idea.title,
            rationale=idea.change_summary,
            change_class=idea.change_class,
            expected_gain=idea.expected_gain,
            provability=idea.provability,
            risk=idea.risk,
        )
        for idea in ideas
    ]


def _five_and_five(gain_at: int | None = None) -> tuple[IdeaCandidate, ...]:
    obvious = [_idea(f"O{i}", Lane.obvious, anchor=None) for i in range(1, 6)]
    news = [
        _distinct(f"N{i}", lane, i) for i, lane in enumerate(LENS_LANES[:5], start=1)
    ]
    picked = portfolio(obvious, news, rotation=ORDER, minimum=3, maximum=5,
                       notes=[])  # fmt: skip
    if gain_at is None:
        return picked
    bumped = picked[gain_at].model_copy(update={"expected_gain": 1.0})
    return (*picked[:gain_at], bumped, *picked[gain_at + 1 :])


def test_the_order_slices_into_rounds_under_rank_generated() -> None:
    ranked = rank_generated(_hypotheses(_five_and_five()))
    ids = [hypothesis.id for hypothesis in ranked]
    assert ids[0:3] == ["O1", "N1", "N2"]
    assert ids[3:6] == ["O2", "N3", "N4"]


def test_numbers_never_reorder_but_a_keep_lesson_does() -> None:
    bumped = _hypotheses(_five_and_five(gain_at=4))
    assert bumped[4].expected_gain == 1.0
    ranked = rank_generated(bumped)
    assert ranked[4].id == bumped[4].id == "N3"
    keep = Lesson(outcome=VerdictOutcome.keep, hypothesis_id="O2", weight=10.0,
                  text="general -> Idea O2: keep")  # fmt: skip
    lifted = [hypothesis.id for hypothesis in rank_generated(bumped, [keep])]
    assert lifted[:4] == ["O1", "N1", "O2", "N2"]


def test_a_repeated_title_and_a_novel_idea_are_filtered_before_the_interleave() -> None:
    notes: list[str] = []
    obvious = [
        _idea("O1", Lane.obvious, anchor=None, title="Use a set"),
        _idea("O2", Lane.obvious, anchor=None, title="use  a SET"),
        _idea("O3", Lane.obvious, anchor=None, change_class=ChangeClass.novel),
        _idea("O4", Lane.obvious, anchor=None),
    ]
    news = [
        _distinct("N1", Lane.eliminate, 1, title="Use a set"),
        _distinct("N2", Lane.assume_less, 2, change_class=ChangeClass.novel),
        _distinct("N3", Lane.recombine, 3),
        _distinct("N4", Lane.far, 4),
        _distinct("N5", Lane.leap, 5, change_class=ChangeClass.behaviour),
    ]
    order = _pick(news, obvious=obvious, notes=notes)
    assert order == ("O1", "N3", "N4", "O4", "N5", "O3", "N2")
    assert notes == [
        "portfolio: dropped repeated idea 'use  a SET'",
        "portfolio: novel idea 'Idea O3' placed after the portfolio (needs approval)",
        "portfolio: dropped repeated idea 'Use a set'",
        "portfolio: novel idea 'Idea N2' placed after the portfolio (needs approval)",
    ]


@pytest.mark.parametrize(("minimum", "maximum"), [(0, 5), (4, 3)])
def test_the_portfolio_refuses_impossible_bounds(minimum: int, maximum: int) -> None:
    with pytest.raises(ValueError, match="minimum"):
        _pick([], minimum=minimum, maximum=maximum)
