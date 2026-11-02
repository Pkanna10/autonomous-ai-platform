"""The mechanism dedupe, the "already taken" block and the dedupe's
acceptance scorer (Step 3 idea lab, G4; spec-idea-lab section 1 G4).

Two ideas are the same mechanism when their target lines (the lines the
quote matches in the shown code) are in one file and overlap, and they
claim the same ``mechanism`` and primary morph cell; no wording counts.
The scorer reads hand-made labelled pairs here (the real labels come from
a live run by a model that wrote none of E1's ideas); the loader reads
E1's recorded ideas (``tests/fixtures/idea_eval/recorded.json``, V6) and
forms the candidate pairs. Nothing here calls a model, a transport or git.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Final

import pytest
from pydantic import ValidationError

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.optimization import idea_dedupe as dd
from autonomous_ai_agents.optimization.idea_dedupe import (
    KEY_RULE,
    MAX_DIFFERENT_MERGED,
    MAX_TAKEN_LINES,
    MIN_AGREEMENT,
    TAKEN_TAG,
    CandidatePair,
    MechanismKey,
    PairLabel,
    RecordedIdea,
    Target,
    candidate_pair,
    candidate_pairs,
    idea_key,
    load_recorded,
    mechanism_key,
    quote_lines,
    representatives,
    same_mechanism,
    score,
    taken_block,
    target_of,
)
from autonomous_ai_agents.optimization.idea_types import (
    LENS_LANES,
    Anchor,
    CodeContext,
    CodeDocument,
    FunctionSpan,
    IdeaCandidate,
    Lane,
    Mechanism,
    MorphCell,
    Tier,
    Typicality,
)

FIXTURE: Final = Path(__file__).parents[1] / "fixtures" / "idea_eval" / "recorded.json"
TOKEN: Final = "7f7f7f7f7f7f7f7f"
PATH: Final = "pkg/core.py"
RAW: Final = "\n".join(
    [
        "def total(items):",  # 10
        "    acc = 0",  # 11
        "    for item in items:",  # 12
        "        acc   +=   item",  # 13
        "    return acc",  # 14
        "",  # 15
        "def first(items):",  # 16
        "    return items[0]",  # 17
    ]
)
CONTEXT: Final = CodeContext(
    documents=(
        CodeDocument(path=PATH, start_line=10, end_line=17, rendered=RAW, raw=RAW),
    )
)


def _idea(
    ident: str,
    *,
    lane: Lane = Lane.eliminate,
    quote: str = "for item in items:",
    path: str = PATH,
    anchor: str | None = "total",
    mechanism: Mechanism = Mechanism.remove_work,
    cells: Sequence[MorphCell] = (MorphCell.work_eliminate,),
    title: str | None = None,
) -> IdeaCandidate:
    return IdeaCandidate(
        id=ident,
        lane=lane,
        title=title or f"Idea {ident}",
        change_summary="Change the loop.",
        justification_summary="It is hot.",
        change_class="efficiency",
        expected_gain=0.1,
        provability=0.5,
        risk=0.2,
        depends_on_path=path,
        depends_on_quote=quote,
        precondition="none",
        equivalence_summary="same sums",
        mechanism=mechanism,
        morph_cells=tuple(cells),
        tier=Tier.exploratory,
        typicality=Typicality.common,
        anchor=None if anchor is None else Anchor(path=path, qualname=anchor),
    )


def _key(
    first: int,
    last: int,
    *,
    path: str = PATH,
    mechanism: Mechanism = Mechanism.remove_work,
    cell: MorphCell = MorphCell.work_eliminate,
) -> MechanismKey:
    return MechanismKey(
        target=Target(path=path, first=first, last=last),
        mechanism=mechanism,
        cell=cell,
    )


# --------------------------------------------------------------------------
# Target lines
# --------------------------------------------------------------------------


def test_a_quote_maps_to_its_lines_whitespace_and_line_prefixes_aside() -> None:
    assert quote_lines(RAW, "for item in items:\n  acc += item", start=10) == (12, 13)
    assert quote_lines(RAW, "L12:     for item in items:\nL13: acc +=  item") == (3, 4)
    assert quote_lines(RAW, "acc = 0", start=10) == (11, 11)
    assert quote_lines(RAW, "return items[0]", start=10) == (17, 17)


@pytest.mark.parametrize("quote", ["", " \n ", "while True:", "L5: "])
def test_a_quote_that_matches_nothing_has_no_lines(quote: str) -> None:
    assert quote_lines(RAW, quote) is None


def test_the_first_occurrence_names_the_lines() -> None:
    raw = "x = 1\ny = 2\nx = 1"
    assert quote_lines(raw, "x = 1") == (1, 1)


def test_an_ideas_target_is_found_in_its_anchor_or_named_document() -> None:
    assert target_of(_idea("a"), CONTEXT) == Target(path=PATH, first=12, last=12)
    unanchored = _idea("b", anchor=None, path="./pkg/core.py", quote="return acc")
    assert target_of(unanchored, CONTEXT) == Target(path=PATH, first=14, last=14)


@pytest.mark.parametrize(
    ("path", "quote"),
    [("pkg/other.py", "for item in items:"), ("../pkg/core.py", "acc = 0"),
     (PATH, "not in the file")],
)  # fmt: skip
def test_an_unshown_file_or_an_unmatched_quote_gives_no_target(
    path: str, quote: str
) -> None:
    assert target_of(_idea("a", path=path, anchor=None, quote=quote), CONTEXT) is None


SPANNED_RAW: Final = "\n".join(
    [
        "def cold(items):",  # 20
        "    for item in items:",  # 21
        "        print(item)",  # 22
        "",  # 23
        "def hot(items):",  # 24
        "    acc = 0",  # 25
        "    for item in items:",  # 26
        "        acc += item",  # 27
        "    return acc",  # 28
    ]
)


def _spanned(*spans: tuple[str, int, int, bool]) -> CodeContext:
    return CodeContext(
        documents=(
            CodeDocument(
                path=PATH, start_line=20, end_line=28, rendered=SPANNED_RAW,
                raw=SPANNED_RAW,
                spans=tuple(
                    FunctionSpan(path=PATH, qualname=name, start_line=start,
                                 end_line=end, hotspot_ids=("h1",) if hot else ())
                    for name, start, end, hot in spans
                ),
            ),
        )
    )  # fmt: skip


SPANNED: Final = _spanned(("cold", 20, 22, False), ("hot", 24, 28, True))


def test_an_anchored_target_is_searched_inside_its_anchor_only() -> None:
    # The quote first occurs in the cold function; grounding anchored the
    # idea in ``hot``, so its target lines are the hot loop's.
    a = _idea("a", anchor="hot")
    b = _idea("b", anchor="hot", quote="for item in items:\n    acc += item")
    assert target_of(a, SPANNED) == Target(path=PATH, first=26, last=26)
    assert target_of(b, SPANNED) == Target(path=PATH, first=26, last=27)
    assert same_mechanism(idea_key(a, SPANNED), idea_key(b, SPANNED))
    assert target_of(_idea("c", anchor="cold"), SPANNED) == Target(
        path=PATH, first=21, last=21
    )


def test_an_anchor_with_no_match_inside_has_no_target() -> None:
    assert target_of(_idea("a", anchor="cold", quote="acc += item"), SPANNED) is None


def test_an_anchor_no_span_names_falls_back_to_the_whole_document() -> None:
    assert target_of(_idea("a", anchor="gone"), SPANNED) == Target(
        path=PATH, first=21, last=21
    )


def test_every_span_carrying_the_anchors_name_is_searched_in_order() -> None:
    # Line 22 holds no loop header, so the second ``hot`` span answers.
    twice = _spanned(("hot", 22, 22, True), ("hot", 24, 28, True))
    assert target_of(_idea("a", anchor="hot"), twice) == Target(
        path=PATH, first=26, last=26
    )
    assert target_of(_idea("b", anchor="hot", quote="print(item)"), twice) == Target(
        path=PATH, first=22, last=22
    )


def test_a_target_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="before"):
        Target(path=PATH, first=5, last=4)


# --------------------------------------------------------------------------
# The key (KEY_RULE)
# --------------------------------------------------------------------------


def test_the_rule_is_stated() -> None:
    assert "overlap" in KEY_RULE and "primary morph cell" in KEY_RULE
    assert MIN_AGREEMENT == Fraction(9, 10)
    assert MAX_DIFFERENT_MERGED == Fraction(1, 20)


def test_the_key_takes_the_mechanism_and_the_primary_cell() -> None:
    target = Target(path=PATH, first=3, last=4)
    key = mechanism_key(
        target, Mechanism.algorithm, (MorphCell.timing_lazy, MorphCell.work_reuse)
    )
    assert key == MechanismKey(
        target=target, mechanism=Mechanism.algorithm, cell=MorphCell.timing_lazy
    )
    assert mechanism_key(None, Mechanism.algorithm, (MorphCell.timing_lazy,)) is None
    assert mechanism_key(target, Mechanism.algorithm, ()) is None
    assert idea_key(_idea("a"), CONTEXT) == _key(12, 12)
    assert idea_key(_idea("a", quote="nowhere at all"), CONTEXT) is None


def test_the_same_lines_by_the_same_transformation_is_one_mechanism() -> None:
    assert same_mechanism(_key(12, 13), _key(12, 13))
    assert same_mechanism(_key(12, 13), _key(13, 20))  # one shared line
    assert same_mechanism(_key(10, 20), _key(14, 14))  # inside


@pytest.mark.parametrize(
    "other",
    [
        _key(14, 15),  # adjacent, no shared line
        _key(12, 13, path="pkg/other.py"),
        _key(12, 13, mechanism=Mechanism.algorithm),
        _key(12, 13, cell=MorphCell.work_reuse),
        None,
    ],
)
def test_other_lines_files_or_transformations_are_distinct(
    other: MechanismKey | None,
) -> None:
    assert not same_mechanism(_key(12, 13), other)
    assert not same_mechanism(other, _key(12, 13))


def test_wording_never_decides() -> None:
    a = _idea("a", title="Hoist the loop", cells=(MorphCell.work_eliminate,))
    b = _idea("b", title="Something else entirely", quote="acc += item",
              cells=(MorphCell.work_eliminate, MorphCell.timing_lazy))  # fmt: skip
    c = _idea("c", title="Hoist the loop", mechanism=Mechanism.algorithm)
    ka, kb, kc = (idea_key(i, CONTEXT) for i in (a, b, c))
    assert not same_mechanism(ka, kb)  # 12 vs 13: no shared line
    b2 = b.model_copy(update={"depends_on_quote": "for item in items:\nacc += item"})
    assert same_mechanism(ka, idea_key(b2, CONTEXT))
    assert not same_mechanism(ka, kc)


def test_representatives_merge_into_the_first_kept_twin() -> None:
    keys = [_key(12, 13), _key(13, 14), _key(14, 15), None, _key(30, 31), None]
    # 1 shares line 13 with 0; 2 shares 14 with 1 but 1 is merged, and
    # nothing with 0: it stays its own; a missing key is never merged.
    assert representatives(keys) == (0, 0, 2, 3, 4, 5)
    assert representatives([]) == ()


# --------------------------------------------------------------------------
# The block a sequential lane is shown
# --------------------------------------------------------------------------


def _block_lines(block: str) -> list[dict[str, object]]:
    lines = block.split("\n")
    start = lines.index(f"<{TAKEN_TAG} boundary={TOKEN}>")
    end = lines.index(f"</{TAKEN_TAG} boundary={TOKEN}>")
    return [json.loads(line) for line in lines[start + 1 : end]]


def test_the_block_shows_each_mechanism_once_without_titles() -> None:
    ideas = [
        _idea("a", title="Hoist the loop"),
        _idea("b", title="Same again"),  # the same key: shown once
        _idea("c", quote="return items[0]", anchor="first",
              mechanism=Mechanism.algorithm, cells=(MorphCell.work_reuse,)),
        _idea("d", quote="missing"),  # no target: not shown
        _idea("e", quote="acc = 0", anchor=None),
    ]  # fmt: skip
    keys = {i.id: k for i in ideas if (k := idea_key(i, CONTEXT)) is not None}
    notes: list[str] = []
    block = taken_block(ideas, keys, Fence(TOKEN), notes)
    assert _block_lines(block) == [
        {"path": PATH, "function": "total", "lines": "12-12",
         "mechanism": "remove_work", "cell": "work:eliminate"},
        {"path": PATH, "function": "first", "lines": "17-17",
         "mechanism": "algorithm", "cell": "work:reuse"},
        {"path": PATH, "function": None, "lines": "11-11",
         "mechanism": "remove_work", "cell": "work:eliminate"},
    ]  # fmt: skip
    head = block.split("\n")[0]
    assert "Do not repeat these mechanisms" in head and TAKEN_TAG in head
    for idea in ideas:
        assert idea.title not in block
    assert notes == []


def test_nothing_taken_gives_no_block() -> None:
    assert taken_block([], {}, Fence(TOKEN), []) == ""
    unkeyed = [_idea("d", quote="missing")]
    assert taken_block(unkeyed, {}, Fence(TOKEN), []) == ""


def test_a_line_holding_a_live_token_or_a_tag_shape_is_withheld() -> None:
    ideas = [
        _idea("a", anchor=f"f{TOKEN}"),
        _idea("b", anchor="<idea>", quote="acc = 0"),
        _idea("c", anchor="first", quote="return items[0]"),
    ]
    keys = {i.id: k for i in ideas if (k := idea_key(i, CONTEXT)) is not None}
    notes: list[str] = []
    block = taken_block(ideas, keys, Fence(TOKEN), notes)
    assert [e["function"] for e in _block_lines(block)] == ["first"]
    assert notes == [
        "2 mechanism line(s) withheld: they hold a boundary token or a tag shape"
    ]


def test_past_the_cap_the_block_says_how_many_it_left_out() -> None:
    ideas: list[IdeaCandidate] = []
    keys: dict[str, MechanismKey] = {}
    for i in range(MAX_TAKEN_LINES + 2):
        idea = _idea(f"i{i}")
        ideas.append(idea)
        keys[idea.id] = _key(100 + i, 100 + i)
    notes: list[str] = []
    block = taken_block(ideas, keys, Fence(TOKEN), notes)
    assert len(_block_lines(block)) == MAX_TAKEN_LINES
    assert notes == [f"2 mechanism line(s) not shown (limit {MAX_TAKEN_LINES})"]


# --------------------------------------------------------------------------
# The acceptance scorer (hand-made labelled pairs)
# --------------------------------------------------------------------------


def _recorded(
    position: int,
    first: int,
    last: int,
    *,
    lane: Lane = Lane.eliminate,
    mechanism: Mechanism = Mechanism.remove_work,
    cells: Sequence[MorphCell] = (MorphCell.work_eliminate,),
    library: str = "lib",
    path: str = PATH,
) -> RecordedIdea:
    return RecordedIdea(
        library=library,
        lane=lane,
        position=position,
        title=f"Idea {position}",
        change_summary="Change it.",
        mechanism=mechanism,
        morph_cells=tuple(cells),
        path=path,
        quote="quoted",
        target=Target(path=path, first=first, last=last),
    )


def _pairs(merged: int, apart: int) -> list[CandidatePair]:
    """``merged`` pairs the dedupe merges, then ``apart`` it keeps apart."""
    pairs = []
    for i in range(merged):
        pairs.append(candidate_pair(_recorded(2 * i + 1, 5, 6),
                                    _recorded(2 * i + 2, 6, 7, lane=Lane.far)))  # fmt: skip
    for i in range(apart):
        pairs.append(candidate_pair(_recorded(100 + 2 * i, 5, 6),
                                    _recorded(101 + 2 * i, 50, 60)))  # fmt: skip
    return pairs


def test_a_candidate_pair_records_the_dedupes_verdict() -> None:
    a = _recorded(1, 5, 6)
    merged = candidate_pair(a, _recorded(2, 6, 9, lane=Lane.far))
    assert merged.merged and merged.overlap
    assert merged.id == "lib:eliminate-01|far-02"
    other = candidate_pair(a, _recorded(3, 6, 9, mechanism=Mechanism.algorithm))
    assert other.overlap and not other.merged
    apart = candidate_pair(a, _recorded(4, 7, 9))
    assert not apart.overlap and not apart.merged
    unknown = a.model_copy(update={"target": None})
    blind = candidate_pair(unknown, a.model_copy(update={"position": 9}))
    assert not blind.overlap and not blind.merged


def test_perfect_labels_pass_the_bar_and_lift_the_raw_lists() -> None:
    pairs = _pairs(3, 7)
    labels = [PairLabel(pair_id=p.id, same=p.merged) for p in pairs]
    result = score(pairs, labels)
    assert result.labelled == 10 and result.agreed == 10
    assert result.agreement == 1.0
    assert (result.same_pairs, result.same_merged) == (3, 3)
    assert (result.different_pairs, result.different_merged) == (7, 0)
    assert result.different_merged_share == 0.0
    assert result.passed and not result.show_raw
    assert result.rule == KEY_RULE
    assert result.why == "passed the fixed bar"


def _labels(pairs: Sequence[CandidatePair], same: Sequence[bool]) -> list[PairLabel]:
    return [PairLabel(pair_id=p.id, same=s) for p, s in zip(pairs, same, strict=True)]


def test_the_bar_is_inclusive_at_90_percent_agreement() -> None:
    pairs = _pairs(1, 9)  # one apart pair is labelled same: missed, not merged
    result = score(pairs, _labels(pairs, [True, True, *[False] * 8]))
    assert (result.agreed, result.labelled) == (9, 10)
    assert result.different_merged == 0
    assert result.passed and not result.show_raw


def test_the_bar_is_inclusive_at_5_percent_of_different_pairs_merged() -> None:
    pairs = _pairs(2, 19)  # the second merged pair is labelled different
    result = score(pairs, _labels(pairs, [True, *[False] * 20]))
    assert (result.different_merged, result.different_pairs) == (1, 20)
    assert result.different_merged_share == pytest.approx(0.05)
    assert result.agreement == pytest.approx(20 / 21)
    assert result.passed


def test_one_merge_too_many_fails_with_good_agreement() -> None:
    pairs = _pairs(2, 18)
    result = score(pairs, _labels(pairs, [True, *[False] * 19]))
    assert (result.different_merged, result.different_pairs) == (1, 19)
    assert result.agreement == pytest.approx(19 / 20)
    assert not result.passed and result.show_raw
    assert "different-mechanism pairs merged" in result.why


def test_agreement_below_90_percent_fails_even_with_nothing_wrongly_merged() -> None:
    pairs = _pairs(0, 10)
    labels = [PairLabel(pair_id=p.id, same=i < 2) for i, p in enumerate(pairs)]
    result = score(pairs, labels)  # two same pairs missed: 8 / 10
    assert result.agreement == pytest.approx(0.8)
    assert result.different_merged == 0
    assert not result.passed and result.show_raw
    assert "agreement" in result.why


def test_only_labelled_pairs_count() -> None:
    pairs = _pairs(2, 5)
    labels = [PairLabel(pair_id=pairs[0].id, same=True),
              PairLabel(pair_id=pairs[3].id, same=False)]  # fmt: skip
    result = score(pairs, labels)
    assert result.labelled == 2 and result.passed


def test_no_different_pair_labelled_cannot_pass() -> None:
    pairs = _pairs(2, 0)
    result = score(pairs, _labels(pairs, [True, True]))
    assert result.different_merged_share is None
    assert not result.passed and "no different-mechanism pair" in result.why


def test_no_same_pair_labelled_cannot_pass() -> None:
    pairs = _pairs(0, 3)
    result = score(pairs, _labels(pairs, [False] * 3))
    assert result.agreement == 1.0 and result.different_merged_share == 0.0
    assert not result.passed and result.show_raw
    assert "no same-mechanism pair" in result.why


def test_the_scorer_refuses_unknown_repeated_or_no_labels() -> None:
    pairs = _pairs(1, 1)
    with pytest.raises(ValueError, match="no labelled pair"):
        score(pairs, [])
    with pytest.raises(ValueError, match="unknown pair"):
        score(pairs, [PairLabel(pair_id="nope", same=True)])
    twice = [PairLabel(pair_id=pairs[0].id, same=True)] * 2
    with pytest.raises(ValueError, match="labelled twice"):
        score(pairs, twice)
    with pytest.raises(ValueError, match="pair id"):
        score([*pairs, pairs[0]], [PairLabel(pair_id=pairs[1].id, same=False)])


# --------------------------------------------------------------------------
# E1's recorded ideas (V6) and their candidate pairs
# --------------------------------------------------------------------------


def _reply_ideas() -> dict[str, int]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    for library in data["libraries"]:
        total = 0
        for label, reply in library["replies"].items():
            if label != "reviewer":
                total += len(json.loads(reply)["hypotheses"])
        found[library["repo"]] = total
    return found


def test_every_recorded_lane_idea_is_loaded_with_its_target() -> None:
    ideas = load_recorded(FIXTURE)
    counts = _reply_ideas()
    assert {lib: sum(i.library == lib for i in ideas) for lib in counts} == counts
    assert {i.lane for i in ideas} == {Lane.obvious, *LENS_LANES, Lane.leap}
    with_target = [i for i in ideas if i.target is not None]
    assert len(with_target) >= 0.9 * len(ideas)
    tomli = [i for i in ideas if i.library == "tomli" and i.lane is Lane.eliminate]
    assert tomli[0].position == 1 and tomli[0].path == "src/tomli/_parser.py"
    assert tomli[0].key() is not None


def test_the_candidate_pairs_are_same_file_pairs_within_a_library() -> None:
    ideas = load_recorded(FIXTURE)
    pairs = candidate_pairs(ideas)
    assert len({p.id for p in pairs}) == len(pairs)
    for pair in pairs:
        assert pair.first.library == pair.second.library
        assert pair.first.path == pair.second.path
        assert pair.merged == same_mechanism(pair.first.key(), pair.second.key())
    expected = sum(
        1
        for i, a in enumerate(ideas)
        for b in ideas[i + 1 :]
        if a.library == b.library and a.path == b.path
    )
    assert len(pairs) == expected
    assert any(p.merged for p in pairs) and any(
        p.overlap and not p.merged for p in pairs
    )


def test_e1s_skip_loop_twins_in_tomli_are_merged() -> None:
    # eliminate "Avoid double comment/whitespace skip loop" and
    # resolve_tradeoff "Skip empty-comment and whitespace loop passes": the
    # same quoted lines, loop_or_control_flow, work:eliminate.
    pairs = {p.id: p for p in candidate_pairs(load_recorded(FIXTURE))}
    assert pairs["tomli:eliminate-03|resolve_tradeoff-01"].merged


def _write(tmp_path: Path, library: dict[str, object]) -> Path:
    path = tmp_path / "recorded.json"
    path.write_text(json.dumps({"source": "test", "arm": "C",
                                "libraries": [library]}), encoding="utf-8")  # fmt: skip
    return path


def _reply(*ideas: dict[str, object]) -> str:
    return json.dumps({"hypotheses": list(ideas)})


def _raw_idea(path: str, quote: str) -> dict[str, object]:
    return {
        "title": "t", "technique_slug": None,
        "hotspots": [{"file_path": path, "symbol": "f"}],
        "change_summary": "c", "justification_summary": "j",
        "depends_on_path": path, "depends_on_quote": quote,
        "precondition": "p", "equivalence_summary": "e",
        "mechanism": "remove_work",
        "morph_cells": ["work:eliminate", "work:eliminate"],
        "tier": "exploratory", "typicality": "common", "change_class": "efficiency",
        "expected_gain": 0.1, "provability": 0.5, "risk": 0.2,
    }  # fmt: skip


def _library(
    code: list[str], replies: dict[str, str], repo: str = "lib"
) -> dict[str, object]:
    return {"repo": repo, "wave1": "never", "licence": "MIT", "upstream": "u@c",
            "facts": {}, "code": code, "replies": replies, "recorded": {}}  # fmt: skip


def test_the_loader_reads_only_listed_code_and_skips_the_reviewer(
    tmp_path: Path,
) -> None:
    code = tmp_path / "code" / "lib" / "pkg"
    code.mkdir(parents=True)
    (code / "core.py.txt").write_text(RAW, encoding="utf-8")
    replies = {
        "obvious": _reply(_raw_idea("pkg/core.py", "acc = 0"),
                          _raw_idea("pkg/gone.py", "acc = 0"),
                          _raw_idea("/etc/passwd", "root")),
        "reviewer": json.dumps({"reviews": []}),
    }  # fmt: skip
    ideas = load_recorded(_write(tmp_path, _library(["pkg/core.py"], replies)))
    assert [(i.lane, i.position) for i in ideas] == [
        (Lane.obvious, n) for n in (1, 2, 3)
    ]
    assert ideas[0].target == Target(path="pkg/core.py", first=2, last=2)
    assert ideas[0].morph_cells == (MorphCell.work_eliminate,)
    assert ideas[1].target is None and ideas[2].target is None


@pytest.mark.parametrize(
    ("code", "repo", "label", "match"),
    [
        (["../escape.py"], "lib", "obvious", "leaves its code directory"),
        (["pkg/core.py"], "../lib", "obvious", "not a plain directory name"),
        ([], "lib", "lens_x", "not a lane"),
    ],
)
def test_the_loader_refuses_paths_out_of_its_tree_and_unknown_labels(
    tmp_path: Path, code: list[str], repo: str, label: str, match: str
) -> None:
    library = _library(code, {label: _reply()}, repo=repo)
    with pytest.raises(ValueError, match=match):
        load_recorded(_write(tmp_path, library))


def test_the_loader_refuses_an_off_schema_reply(tmp_path: Path) -> None:
    bad = _raw_idea("pkg/core.py", "acc = 0") | {"extra": 1}
    with pytest.raises(ValidationError):
        load_recorded(_write(tmp_path, _library([], {"far": _reply(bad)})))


def test_the_module_states_its_bar_constants_once() -> None:
    assert dd.MIN_AGREEMENT is MIN_AGREEMENT
    assert dd.MAX_DIFFERENT_MERGED is MAX_DIFFERENT_MERGED
