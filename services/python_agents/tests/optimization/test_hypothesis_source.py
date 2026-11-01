"""Tests for the Claude-backed discovery adapters (Step 3, U7).

``ClaudeHypothesisGenerator`` and ``ClaudeTechniqueMatcher`` wrap
``generate_hypotheses`` and ``match_techniques`` behind the U2 protocols:
the role's effort and token cap come from the settings, the request is billed
to the ``Budget`` handed in (the node reads spend from its delta, D7), errors
propagate for the node to classify (D18), and ``lessons`` / ``avoid_titles``
do not reach the prompt until W1. Every test runs on ``ScriptedTransport``.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import response_cost
from autonomous_ai_agents.clients.transport import ScriptedReply, ScriptedTransport
from autonomous_ai_agents.common.config import Settings, role_settings
from autonomous_ai_agents.common.errors import BudgetExceeded, UnusableReplyError
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Direction,
    Hotspot,
    HypothesisSource,
    Lesson,
    Objective,
    ObjectiveKind,
    Precondition,
    Project,
    ProjectUnderstanding,
    Technique,
    TechniqueMatchRecord,
    VerdictOutcome,
)
from autonomous_ai_agents.optimization.hypothesis_source import (
    ClaudeHypothesisGenerator,
    ClaudeTechniqueMatcher,
)
from autonomous_ai_agents.optimization.sources import (
    GenerateResult,
    HypothesisGenerator,
    MatchResult,
    TechniqueMatcher,
)
from autonomous_ai_agents.research import playbook as playbook_module
from autonomous_ai_agents.research.playbook import MATCH_MAX_TOKENS, StableTokens

Json = dict[str, object]
SONNET = "claude-sonnet-5-5"
BASE = Settings.model_validate({"ENGINE_FALLBACKS": True, "LLM_MAX_RETRIES": 0})
GEN_CFG = role_settings(BASE, "generator")
MATCH_CFG = role_settings(BASE, "matcher")
USAGE: Json = {"input_tokens": 1500, "output_tokens": 400}


@pytest.fixture(autouse=True)
def fixed_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets, "token_hex", lambda _n: "0123456789abcdef")
    monkeypatch.setattr(
        playbook_module, "STABLE_TOKENS", StableTokens(source=lambda: "5e5e" * 4)
    )


PROJECT = Project(id="p1", name="dedupe", root_path="/tmp/dedupe")
OBJECTIVE = Objective(
    project_id="p1",
    kind=ObjectiveKind.runtime,
    metric="wall_time_s",
    direction=Direction.minimize,
    description="make the dedupe workload faster",
)
UNDERSTANDING = ProjectUnderstanding(
    language="python", summary="dedupe: de-duplication.", served_by_model=SONNET
)
HOTSPOTS = (
    Hotspot(
        id="h-core",
        project_id="p1",
        workload_id="w1",
        file_path="dedupe/core.py",
        symbol="unique_in_order",
        self_time_s=0.8,
        total_time_s=0.8,
        share=0.8,
    ),
)
TECHNIQUES = (
    Technique(
        id="set-membership",
        slug="set-membership",
        name="Set membership",
        summary="Use a set for membership tests in a loop.",
        change_class=ChangeClass.efficiency,
        preconditions=(Precondition(description="d", check="hotspot.membership"),),
        expected_gain=0.5,
        provability=0.9,
        risk=0.1,
    ),
    Technique(
        id="lru-cache",
        slug="lru-cache",
        name="Memoise",
        summary="Cache a pure function's results.",
        change_class=ChangeClass.efficiency,
        expected_gain=0.4,
        provability=0.8,
        risk=0.1,
    ),
)
LESSON = Lesson(project_id="p1", outcome=VerdictOutcome.keep, text="sets won")


def _reply(payload: Json) -> Json:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": SONNET,
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": dict(USAGE),
    }


def _idea(title: str, slug: str | None = None) -> Json:
    return {
        "title": title,
        "technique_slug": slug,
        "hotspots": [{"file_path": "dedupe/core.py", "symbol": "unique_in_order"}],
        "change_summary": "Keep a set of seen values.",
        "justification_summary": "The hotspot scans a list per item.",
        "change_class": "efficiency",
        "expected_gain": 0.6,
        "provability": 0.9,
        "risk": 0.1,
    }


def _ideas(*items: Json) -> Json:
    return _reply({"hypotheses": list(items)})


def _match(slug: str, fit: float, unmet: Sequence[str] = ()) -> Json:
    return {
        "slug": slug,
        "fit": fit,
        "justification_summary": f"{slug} fits the hotspot.",
        "unmet_preconditions": list(unmet),
    }


def _matches(*items: Json) -> Json:
    return _reply({"matches": list(items)})


def _one_cost(cfg: Settings) -> float:
    return response_cost(USAGE, cfg.MODEL_PRICING, model=SONNET)[0]


def _generate(
    replies: Sequence[ScriptedReply],
    *,
    budget: Budget | None = None,
    lessons: Sequence[Lesson] = (),
    avoid_titles: Sequence[str] = (),
    techniques: Sequence[Technique] = (),
    n: int = 5,
    cfg: Settings = GEN_CFG,
) -> tuple[GenerateResult, ScriptedTransport, Budget]:
    transport = ScriptedTransport(replies, cfg=cfg)
    spend = Budget(5.0) if budget is None else budget
    generator = ClaudeHypothesisGenerator(transport, config=cfg, sleep=lambda _s: None)
    result = generator.generate(
        project=PROJECT,
        understanding=UNDERSTANDING,
        hotspots=HOTSPOTS,
        objective=OBJECTIVE,
        techniques=techniques,
        lessons=lessons,
        avoid_titles=avoid_titles,
        n=n,
        budget=spend,
    )
    return result, transport, spend


def _match_run(
    replies: Sequence[ScriptedReply],
    *,
    budget: Budget | None = None,
    techniques: Sequence[Technique] = TECHNIQUES,
    k: int = 3,
) -> tuple[MatchResult, ScriptedTransport, Budget]:
    transport = ScriptedTransport(replies, cfg=MATCH_CFG)
    spend = Budget(5.0) if budget is None else budget
    matcher = ClaudeTechniqueMatcher(transport, config=MATCH_CFG, sleep=lambda _s: None)
    result = matcher.match(
        understanding=UNDERSTANDING,
        hotspots=HOTSPOTS,
        techniques=techniques,
        k=k,
        budget=spend,
    )
    return result, transport, spend


# --------------------------------------------------------------------------
# The generator
# --------------------------------------------------------------------------


def test_the_generator_is_a_hypothesis_generator() -> None:
    transport = ScriptedTransport([], cfg=GEN_CFG)
    assert isinstance(
        ClaudeHypothesisGenerator(transport, config=GEN_CFG), HypothesisGenerator
    )


def test_generate_keeps_the_model_order_and_records_spend_in_the_budget() -> None:
    result, transport, budget = _generate(
        [_ideas(_idea("Use a set"), _idea("Memoise", "lru-cache"), _idea("Use a set"))],
        techniques=TECHNIQUES,
        budget=Budget(5.0, spent_usd=1.0),
    )
    assert [h.title for h in result.hypotheses] == ["Use a set", "Memoise"]
    assert result.hypotheses[1].source is HypothesisSource.playbook
    assert result.hypotheses[1].technique_id == "lru-cache"
    assert any("duplicate" in note for note in result.notes)
    assert budget.spent_usd == pytest.approx(1.0 + _one_cost(GEN_CFG))
    assert len(transport.requests) == 1


def test_generate_sends_the_generator_effort_and_token_cap() -> None:
    cfg = role_settings(
        BASE, "generator", GENERATOR_EFFORT="low", GENERATOR_MAX_TOKENS=12000
    )
    _, transport, _ = _generate([_ideas()], cfg=cfg)
    (request,) = transport.requests
    assert request.max_tokens == 12000
    assert request.output_config is not None
    assert request.output_config.get("effort") == "low"


def test_generate_passes_n_through() -> None:
    result, _, _ = _generate([_ideas(_idea("a"), _idea("b"))], n=1)
    assert [h.title for h in result.hypotheses] == ["a"]
    assert any("beyond the first 1" in note for note in result.notes)


def test_lessons_and_avoid_titles_do_not_reach_the_prompt_until_w1() -> None:
    _, plain, _ = _generate([_ideas()])
    _, given, _ = _generate([_ideas()], lessons=[LESSON], avoid_titles=["Use a set"])
    assert given.requests == plain.requests


def test_an_unaffordable_request_raises_before_sending() -> None:
    transport = ScriptedTransport([_ideas()], cfg=GEN_CFG)
    budget = Budget(0.0001)
    generator = ClaudeHypothesisGenerator(transport, config=GEN_CFG)
    with pytest.raises(BudgetExceeded):
        generator.generate(
            project=PROJECT,
            understanding=UNDERSTANDING,
            hotspots=HOTSPOTS,
            objective=OBJECTIVE,
            techniques=(),
            lessons=(),
            avoid_titles=(),
            n=5,
            budget=budget,
        )
    assert transport.requests == []
    assert budget.spent_usd == 0.0


def test_an_unaffordable_match_raises_before_sending() -> None:
    transport = ScriptedTransport([_matches()], cfg=MATCH_CFG)
    budget = Budget(0.0001)
    matcher = ClaudeTechniqueMatcher(transport, config=MATCH_CFG)
    with pytest.raises(BudgetExceeded):
        matcher.match(
            understanding=UNDERSTANDING,
            hotspots=HOTSPOTS,
            techniques=TECHNIQUES,
            k=3,
            budget=budget,
        )
    assert transport.requests == []
    assert budget.spent_usd == 0.0


def test_an_unusable_reply_raises_after_charging() -> None:
    budget = Budget(5.0)
    with pytest.raises(UnusableReplyError):
        _generate([_reply({"wrong": []})], budget=budget)
    assert budget.spent_usd == pytest.approx(_one_cost(GEN_CFG))


def test_the_generator_refuses_a_transport_of_another_role() -> None:
    engine = ScriptedTransport([], cfg=BASE)  # Opus with fallbacks
    with pytest.raises(ValueError, match="generator"):
        ClaudeHypothesisGenerator(engine, config=BASE)


def test_the_generator_refuses_an_unknown_effort() -> None:
    cfg = GEN_CFG.model_copy(update={"GENERATOR_EFFORT": "turbo"})
    with pytest.raises(ValueError, match="effort"):
        ClaudeHypothesisGenerator(ScriptedTransport([], cfg=cfg), config=cfg)


def test_the_generator_refuses_a_level_its_model_does_not_serve() -> None:
    model = "claude-opus-4-5-20251101"  # no "max" level
    cfg = GEN_CFG.model_copy(
        update={
            "GENERATOR_MODEL": model,
            "ENGINE_MODEL": model,
            "GENERATOR_EFFORT": "max",
        }
    )
    with pytest.raises(ValueError, match="effort"):
        ClaudeHypothesisGenerator(ScriptedTransport([], cfg=cfg), config=cfg)


# --------------------------------------------------------------------------
# The matcher
# --------------------------------------------------------------------------


def test_the_matcher_is_a_technique_matcher() -> None:
    transport = ScriptedTransport([], cfg=MATCH_CFG)
    assert isinstance(
        ClaudeTechniqueMatcher(transport, config=MATCH_CFG), TechniqueMatcher
    )


def test_match_returns_records_best_fit_first_and_records_spend() -> None:
    result, transport, budget = _match_run(
        [
            _matches(
                _match("lru-cache", 0.4),
                _match("set-membership", 0.9, ["hotspot.membership", "nope"]),
                _match("unknown", 1.0),
            )
        ]
    )
    assert result.matches == (
        TechniqueMatchRecord(
            slug="set-membership",
            fit=0.9,
            justification_summary="set-membership fits the hotspot.",
            unmet_preconditions=("hotspot.membership",),
        ),
        TechniqueMatchRecord(
            slug="lru-cache",
            fit=0.4,
            justification_summary="lru-cache fits the hotspot.",
        ),
    )
    assert any("unknown" in note for note in result.notes)
    assert any("nope" in note for note in result.notes)
    assert budget.spent_usd == pytest.approx(_one_cost(MATCH_CFG))
    (request,) = transport.requests
    assert request.max_tokens == MATCH_MAX_TOKENS
    assert request.output_config is not None
    assert request.output_config.get("effort") == "medium"


def test_match_passes_k_through() -> None:
    result, _, _ = _match_run(
        [_matches(_match("lru-cache", 0.4), _match("set-membership", 0.9))], k=1
    )
    assert [m.slug for m in result.matches] == ["set-membership"]


def test_match_with_no_technique_sends_nothing_and_spends_nothing() -> None:
    result, transport, budget = _match_run([], techniques=())
    assert result == MatchResult()
    assert transport.requests == []
    assert budget.spent_usd == 0.0


def test_a_matcher_failure_propagates_after_charging() -> None:
    budget = Budget(5.0)
    with pytest.raises(UnusableReplyError):
        _match_run([_reply({"wrong": []})], budget=budget)
    assert budget.spent_usd == pytest.approx(_one_cost(MATCH_CFG))


def test_the_matcher_refuses_a_transport_of_another_role() -> None:
    with pytest.raises(ValueError, match="matcher"):
        ClaudeTechniqueMatcher(ScriptedTransport([], cfg=BASE), config=BASE)
