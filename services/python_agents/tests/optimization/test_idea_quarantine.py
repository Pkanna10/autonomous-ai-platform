"""G3: rule-relaxing lanes under a structural quarantine (idea-lab spec 1, O32).

A rule-relaxing lane (a new dependency, a changed output order, install-time
precompute, an API change) writes ideas that carry a ``proposal`` tag from
birth. The tag is set by the lane, never parsed from the reply: on an
``IdeaCandidate`` it is a field the validator ties to the lane (a copy that
clears or changes it is refused), on a ``Hypothesis`` it is a ``proposal:``
tag beside the relaxing lane's ``lane:`` tag, either of which quarantines.
Every later step keeps it (the dedupe, the portfolio, the ranking, a JSON
round-trip), and ``derive_verdict`` rejects any trial of a tagged idea, the
one that claims output equivalence first: the two are contradictory.

Swap points: replies are built ``LLMResult``s (for Claude), the context is
``read_code_context`` over a dict reader (for git).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest
from anthropic.types.beta import BetaMessage
from pydantic import ValidationError

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.clients.transport import (
    LLMResult,
    LLMTransport,
    ScriptedTransport,
)
from autonomous_ai_agents.common.config import (
    LANE_ROLE_LANES,
    Role,
    Settings,
    lane_chain,
    role_settings,
)
from autonomous_ai_agents.common.errors import UnusableReplyError
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Direction,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    JudgeOutcome,
    JudgeResult,
    Lesson,
    Objective,
    ObjectiveKind,
    Trial,
    TrialStatus,
    VerdictOutcome,
)
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.optimization.anticheat import proposal_conflict
from autonomous_ai_agents.optimization.idea_context import (
    IdeaReadLimits,
    read_code_context,
)
from autonomous_ai_agents.optimization.idea_lanes import (
    lane_transports,
    read_lane_reply,
)
from autonomous_ai_agents.optimization.idea_portfolio import (
    deterministic_filter,
    portfolio,
    signature,
)
from autonomous_ai_agents.optimization.idea_prompts import (
    LENS_TEXT,
    RELAX_ASK,
    RELAX_TEXT,
    lane_instruction,
)
from autonomous_ai_agents.optimization.idea_types import (
    LENS_LANES,
    PROPOSAL_TAG,
    RELAXING_LANES,
    CodeContext,
    IdeaCandidate,
    Lane,
    RelaxedRule,
    is_proposal,
    proposal_tag,
    relaxed_rules,
)
from autonomous_ai_agents.optimization.judges import derive_verdict
from autonomous_ai_agents.optimization.ranking import (
    rank_generated,
    rank_hypotheses,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
FENCE = Fence("1a1a1a1a1a1a1a1a", others=("3c3c3c3c3c3c3c3c",))
RELAX = Lane.relax_dependency
Json = dict[str, object]

PARSER = '''"""Parser module."""
KEYWORDS = ("if", "else", "while", "for", "return")


def parse_tokens(text, keywords=KEYWORDS):
    found = []
    for word in text.split():
        if word.strip().casefold() in keywords:
            found.append(word.upper())
    return found
'''
QUOTE = "for word in text.split():\n    if word.strip().casefold() in keywords:"
SPOT = Hotspot(
    id="h1",
    project_id="p1",
    workload_id="w1",
    file_path="pkg/parser.py",
    symbol="parse_tokens",
    line_start=5,
    self_time_s=0.5,
    total_time_s=1.0,
    share=0.5,
)
INDEX: Mapping[tuple[str, str], list[str]] = {("pkg/parser.py", "parse_tokens"): ["h1"]}
OBJECTIVE = Objective(
    project_id="p1",
    kind=ObjectiveKind.runtime,
    metric="wall_time_s",
    direction=Direction.minimize,
    min_relative_gain=0.02,
    description="make parsing faster",
)


class _Reader:
    def ls_tree(self, commit: str) -> tuple[str, ...]:
        if commit != SHA:
            raise GitError("unknown commit")
        return ("pkg/parser.py",)

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        data = PARSER.encode()
        return data if limit is None else data[:limit]


def _context() -> CodeContext:
    return read_code_context(
        _Reader(), SHA, (SPOT,), fence=FENCE, protected=(), read_deny=(),
        limits=IdeaReadLimits(), notes=[],
    )  # fmt: skip


CONTEXT = _context()


def _idea(**changes: object) -> Json:
    idea: Json = {
        "title": "Use a C-accelerated tokenizer package",
        "technique_slug": None,
        "hotspots": [{"file_path": "pkg/parser.py", "symbol": "parse_tokens"}],
        "change_summary": "Replace the scan with a compiled tokenizer.",
        "justification_summary": "parse_tokens holds 50 % of the time.",
        "depends_on_path": "pkg/parser.py",
        "depends_on_quote": QUOTE,
        "precondition": "the package builds wheels for the platform",
        "equivalence_summary": "the same tokens, via a new dependency",
        "mechanism": "algorithm",
        "morph_cells": ["algorithm:better_constant"],
        "tier": "exploratory",
        "typicality": "uncommon",
        "change_class": "efficiency",
        "expected_gain": 0.4,
        "provability": 0.6,
        "risk": 0.3,
    }
    idea.update(changes)
    return idea


def _result(text: str) -> LLMResult:
    message = BetaMessage.model_validate(
        {
            "id": "msg_relax",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        }
    )
    return LLMResult(
        message=message, cost_usd=0.0, tokens=20, estimate_usd=0.0,
        served_model="claude-sonnet-5-5", fell_back=False, unpriced_models=(),
        attempts=1,
    )  # fmt: skip


def _read(items: Sequence[Json], lane: Lane) -> tuple[IdeaCandidate, ...]:
    return read_lane_reply(
        _result(json.dumps({"hypotheses": list(items)})), lane=lane,
        context=CONTEXT, index=INDEX, n=6, fence=FENCE, notes=[],
    )  # fmt: skip


def _hypothesis(*tags: str, title: str = "an idea") -> Hypothesis:
    return Hypothesis(
        project_id="p1", source=HypothesisSource.novel, title=title,
        rationale="generated", change_class=ChangeClass.efficiency,
        expected_gain=0.2, provability=0.5, risk=0.1, tags=tags,
    )  # fmt: skip


# --------------------------------------------------------------------------
# The lanes and the tag (idea_types)
# --------------------------------------------------------------------------


def test_four_relaxing_lanes_each_relax_one_rule_and_none_is_a_lens() -> None:
    assert dict(RELAXING_LANES) == {
        Lane.relax_dependency: RelaxedRule.new_dependency,
        Lane.relax_output_order: RelaxedRule.output_order,
        Lane.relax_precompute: RelaxedRule.install_precompute,
        Lane.relax_api: RelaxedRule.api_change,
    }
    assert not set(RELAXING_LANES) & {*LENS_LANES, *LANE_ROLE_LANES, Lane.leap}
    assert [proposal_tag(rule) for rule in RelaxedRule] == [
        "proposal:new_dependency", "proposal:output_order",
        "proposal:install_precompute", "proposal:api_change",
    ]  # fmt: skip
    assert PROPOSAL_TAG == "proposal"
    with pytest.raises(TypeError):
        RELAXING_LANES[Lane.far] = RelaxedRule.api_change  # type: ignore[index]


def test_a_relaxing_lanes_idea_is_tagged_at_birth_and_a_lens_idea_is_not() -> None:
    for lane, rule in RELAXING_LANES.items():
        (idea,) = _read([_idea()], lane)
        assert idea.lane is lane and idea.proposal is rule
    (plain,) = _read([_idea()], Lane.far)
    assert plain.proposal is None


def test_a_reply_cannot_set_or_clear_the_tag() -> None:
    """
    GIVEN replies that try to name a ``proposal`` (null, a rule, a bogus
          value) in an idea, or at the top level
    WHEN a relaxing lane and a lens read them
    THEN every such reply is refused whole (the schema has no such field);
         the field is never read from a reply
    """
    for value in (None, "new_dependency", "none", False):
        for lane in (RELAX, Lane.far):
            with pytest.raises(UnusableReplyError, match="schema"):
                _read([_idea(proposal=value)], lane)
    top = json.dumps({"hypotheses": [_idea()], "proposal": None})
    with pytest.raises(UnusableReplyError, match="schema"):
        read_lane_reply(_result(top), lane=RELAX, context=CONTEXT, index=INDEX,
                        n=6, fence=FENCE, notes=[])  # fmt: skip


def test_the_validator_ties_the_tag_to_the_lane() -> None:
    (idea,) = _read([_idea()], RELAX)
    fields = idea.model_dump()
    for lane, wrong in (
        (RELAX, None),
        (RELAX, RelaxedRule.api_change),
        (Lane.far, RelaxedRule.new_dependency),
        (Lane.obvious, RelaxedRule.output_order),
    ):
        with pytest.raises(ValidationError, match="proposal"):
            IdeaCandidate.model_validate({**fields, "lane": lane, "proposal": wrong})


def test_no_copy_can_clear_change_or_orphan_the_tag() -> None:
    """``model_copy`` re-validates: clearing or swapping the tag, or moving
    a tagged idea to a lens lane, is refused; ordinary updates keep it."""
    (idea,) = _read([_idea()], RELAX)
    clearing: tuple[dict[str, object], ...] = (
        {"proposal": None},
        {"proposal": RelaxedRule.output_order},
        {"lane": Lane.far},
        {"lane": Lane.relax_api},
    )
    for change in clearing:
        with pytest.raises(ValidationError, match="proposal"):
            idea.model_copy(update=change)
    updates: tuple[dict[str, object] | None, ...] = (
        {"ceiling": 0.4},
        {"review": None, "plan": "do it"},
        None,
    )
    for update in updates:
        copied = idea.model_copy(update=update)
        assert copied.proposal is RelaxedRule.new_dependency
    assert idea.model_copy(deep=True) == idea


def test_hypothesis_tags_quarantine_by_proposal_or_relaxing_lane() -> None:
    """Either tag quarantines (fail closed): ``proposal:<any value>``, or a
    relaxing lane's ``lane:`` tag with its own ``proposal:`` lost."""
    assert relaxed_rules(_hypothesis("lane:far", "review:feasible")) == ()
    assert not is_proposal(_hypothesis("lane:far"))
    assert not is_proposal(_hypothesis("proposals:new_dependency"))
    tagged = _hypothesis("lane:relax_dependency", "proposal:new_dependency")
    assert relaxed_rules(tagged) == ("new_dependency",)
    assert is_proposal(tagged)
    assert relaxed_rules(_hypothesis("lane:relax_api")) == ("api_change",)
    assert relaxed_rules(_hypothesis("proposal:unheard_of")) == ("unheard_of",)
    both = _hypothesis("proposal:output_order", "lane:relax_precompute")
    assert relaxed_rules(both) == ("output_order", "install_precompute")


# --------------------------------------------------------------------------
# Later steps keep the tag: dedupe, portfolio, ranking, serialisation
# --------------------------------------------------------------------------


def _tagged(
    lane: Lane, title: str, ceiling: float = 0.5, **changes: object
) -> IdeaCandidate:
    (idea,) = _read([_idea(title=title, **changes)], lane)
    return idea.model_copy(update={"ceiling": ceiling})


def test_the_dedupe_and_the_portfolio_keep_the_tag() -> None:
    """
    GIVEN two ideas of one relaxing lane with the same signature, and one of
          another relaxing lane
    WHEN S4a dedupes them and S4b picks the portfolio
    THEN the duplicate is dropped whole, and every idea that survives either
         stage still carries its lane's tag; the signature never reads it
    """
    first = _tagged(RELAX, "Swap in a compiled tokenizer")
    twin = _tagged(RELAX, "Swap in a compiled scanner")
    other = _tagged(
        Lane.relax_output_order, "Emit tokens unordered", ceiling=0.6,
        mechanism="data_structure", morph_cells=["representation:indexed"],
    )  # fmt: skip
    assert signature(first) == signature(twin)
    notes: list[str] = []
    kept = deterministic_filter(
        (), (first, twin, other), floor=0.02, objective=OBJECTIVE, avoid=(),
        lesson_titles=(), multiplier=1.0, notes=notes,
    )  # fmt: skip
    assert [i.id for i in kept] == [first.id, other.id]
    assert [i.proposal for i in kept] == [
        RelaxedRule.new_dependency,
        RelaxedRule.output_order,
    ]
    picked = portfolio((), kept, rotation=(RELAX, Lane.relax_output_order),
                       minimum=2, maximum=5, notes=notes)  # fmt: skip
    assert {i.proposal for i in picked} == {
        RelaxedRule.new_dependency,
        RelaxedRule.output_order,
    }
    assert all(isinstance(i, IdeaCandidate) for i in picked)


def test_a_json_round_trip_keeps_the_candidates_tag() -> None:
    idea = _tagged(Lane.relax_precompute, "Build the keyword table at install")
    again = IdeaCandidate.model_validate_json(idea.model_dump_json())
    assert again == idea and again.proposal is RelaxedRule.install_precompute
    forged = json.loads(idea.model_dump_json())
    forged["proposal"] = None
    with pytest.raises(ValidationError, match="proposal"):
        IdeaCandidate.model_validate(forged)


def test_ranking_and_a_json_round_trip_keep_the_hypothesis_tags() -> None:
    tagged = _hypothesis("lane:relax_api", "proposal:api_change", title="api")
    plain = _hypothesis("lane:far", title="plain")
    lessons = [
        Lesson(project_id="p1", hypothesis_id=tagged.id,
               outcome=VerdictOutcome.keep, weight=1.0, text="taught"),
    ]  # fmt: skip
    for ranked in (
        rank_generated([plain, tagged], lessons),
        rank_hypotheses([plain, tagged], lessons),
    ):
        found = next(h for h in ranked if h.id == tagged.id)
        assert found.tags == tagged.tags and is_proposal(found)
    again = Hypothesis.model_validate_json(tagged.model_dump_json())
    assert again.tags == tagged.tags and is_proposal(again)


# --------------------------------------------------------------------------
# The lane's transport and prompt (idea_lanes, idea_prompts)
# --------------------------------------------------------------------------


def _roles(cfg: Settings) -> dict[Role, LLMTransport]:
    return {
        role: ScriptedTransport([], cfg=role_settings(cfg, role))
        for role in ("lane", "leap", "reviewer")
    }


def test_relaxing_lanes_run_on_the_lane_roles_transport_only() -> None:
    cfg = Settings(_env_file=None, IDEA_PIPELINE=True)
    roles = _roles(cfg)
    found = lane_transports(roles, {}, cfg)
    for lane in RELAXING_LANES:
        assert found[lane] is roles["lane"]
        assert lane_chain(cfg, lane) == tuple(roles["lane"].chain)
    with pytest.raises(ValueError, match="relax_api lane runs on the lane transport"):
        lane_transports(roles, {Lane.relax_api: roles["lane"]}, cfg)


def test_each_relaxing_lane_names_its_rule_and_that_nothing_ships() -> None:
    """The prompt explains the lane; it is not the quarantine (that is the
    tag). Each lens names the rule it lifts and says its ideas are
    proposals for a human, never trialled or shipped."""
    assert set(RELAX_TEXT) == set(RELAXING_LANES)
    for lane, rule in RELAXING_LANES.items():
        text = lane_instruction(lane, table="<table/>", examples=(), n=4,
                                floor=0.02, model="claude-opus-5-5")  # fmt: skip
        assert text.startswith("<table/>\n")
        assert RELAX_TEXT[lane] in text and f'rule="{rule.value}"' in text
        assert text.endswith(RELAX_ASK.format(n=4))
        assert "never trialled" in RELAX_ASK and "human" in RELAX_ASK
        assert not any(lens in text for lens in LENS_TEXT.values())


# --------------------------------------------------------------------------
# The anti-cheat and the verdict (anticheat, judges)
# --------------------------------------------------------------------------


def _result_of(judge: str, outcome: JudgeOutcome, **extra: object) -> JudgeResult:
    return JudgeResult.model_validate(
        {"judge": judge, "outcome": outcome, "reason": "measured", **extra}
    )


SPEED_PASS = _result_of("speed", JudgeOutcome.passed, metric="wall_time_s", gain=0.4)
SAME_OUTPUT = _result_of("equivalence", JudgeOutcome.passed)
CHANGED_OUTPUT = _result_of("equivalence", JudgeOutcome.passed, output_changed=True)
NO_CHECK = _result_of("equivalence", JudgeOutcome.not_applicable)
TESTS_PASS = _result_of("tests", JudgeOutcome.passed)


def test_the_anticheat_names_a_tagged_equivalence_claim_contradictory() -> None:
    tagged = _hypothesis("lane:relax_dependency", "proposal:new_dependency")
    assert proposal_conflict(_hypothesis("lane:far"), (SAME_OUTPUT,)) is None
    found = proposal_conflict(tagged, (SPEED_PASS, SAME_OUTPUT))
    assert found is not None and "contradictory" in found
    assert "new_dependency" in found and "equivalence" in found
    behaviour = tagged.model_copy(update={"change_class": ChangeClass.behaviour})
    quiet = proposal_conflict(behaviour, (SPEED_PASS, NO_CHECK))
    assert quiet is not None and "contradictory" not in quiet
    assert "quarantined" in quiet
    efficiency_claim = proposal_conflict(tagged, (SPEED_PASS, NO_CHECK))
    assert efficiency_claim is not None and "contradictory" in efficiency_claim


@pytest.mark.parametrize(
    ("tags", "results", "contradictory"),
    [
        (("proposal:new_dependency",), (SPEED_PASS, SAME_OUTPUT, TESTS_PASS), True),
        (("lane:relax_output_order",), (SPEED_PASS, SAME_OUTPUT, TESTS_PASS), True),
        (("proposal:api_change",), (SPEED_PASS, CHANGED_OUTPUT, TESTS_PASS), False),
        (("proposal:unheard_of",), (SPEED_PASS, NO_CHECK), False),
    ],
)
def test_a_tagged_trial_whose_judges_all_pass_is_rejected(
    tags: tuple[str, ...],
    results: tuple[JudgeResult, ...],
    contradictory: bool,
) -> None:
    """
    GIVEN a trial of a tagged idea whose every judge passed, the equivalence
          judge included, in exact and quality modes
    WHEN the verdict is derived, for each change class
    THEN it is a reject, never keep, review or needs_approval (rule 0,
         before every other rule); its summary says why
    """
    for change_class in ChangeClass:
        hypothesis = _hypothesis(*tags).model_copy(
            update={"change_class": change_class}
        )
        trial = Trial(hypothesis_id=hypothesis.id, round=1,
                      status=TrialStatus.measured)  # fmt: skip
        verdict = derive_verdict(trial, hypothesis, results, (),
                                 primary_metric="wall_time_s")  # fmt: skip
        assert verdict.outcome is VerdictOutcome.reject
        assert verdict.summary.startswith("reject: proposal")
        claims = contradictory or change_class is ChangeClass.efficiency
        assert ("contradictory" in verdict.summary) is claims
        assert verdict.judge_results == results


def test_an_untagged_trial_is_judged_as_before() -> None:
    hypothesis = _hypothesis("lane:far")
    trial = Trial(hypothesis_id=hypothesis.id, round=1, status=TrialStatus.measured)
    verdict = derive_verdict(trial, hypothesis, (SPEED_PASS, SAME_OUTPUT), (),
                             primary_metric="wall_time_s")  # fmt: skip
    assert verdict.outcome is VerdictOutcome.keep


# --------------------------------------------------------------------------
# The setting (config)
# --------------------------------------------------------------------------


def test_the_relaxing_lanes_are_off_by_default_and_validated() -> None:
    assert Settings(_env_file=None).IDEAS_RELAX_LANES == ()
    on = Settings(_env_file=None, IDEAS_RELAX_LANES=(RELAX, Lane.relax_api))
    assert on.IDEAS_RELAX_LANES == (RELAX, Lane.relax_api)
    for bad in ((RELAX, RELAX), (Lane.far,), (Lane.leap,), (Lane.obvious, RELAX)):
        with pytest.raises(ValidationError, match="IDEAS_RELAX_LANES"):
            Settings(_env_file=None, IDEAS_RELAX_LANES=bad)
    with pytest.raises(ValidationError, match="IDEAS_LENSES"):
        Settings(_env_file=None, IDEAS_LENSES=(Lane.far, RELAX))
    for key in ("IDEAS_LANE_MODELS", "IDEAS_LANE_VIEWS"):
        with pytest.raises(ValidationError, match=key):
            Settings.model_validate({key: {"relax_api": "callers"}})


def test_the_relaxing_lanes_setting_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IDEAS_RELAX_LANES", '["relax_output_order"]')
    assert Settings(_env_file=None).IDEAS_RELAX_LANES == (Lane.relax_output_order,)
