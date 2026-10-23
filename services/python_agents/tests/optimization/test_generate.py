"""Tests for the Claude hypothesis generator (unit X2).

``generate_hypotheses`` sends one structured-output request and maps the
validated reply to engine ``Hypothesis`` records: a provided technique's slug
makes a ``playbook`` hypothesis, anything else a ``novel`` one; hotspots are
resolved from file and symbol against the shown profile only; numbers are
clamped; text is capped, printable and free of code. Every test runs on
``ScriptedTransport``; nothing here reaches the network.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence
from typing import NamedTuple

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.structured import (
    MAX_HOTSPOTS_SHOWN,
    PROMPT_ALLOWANCE_TOKENS,
)
from autonomous_ai_agents.clients.transport import (
    LLMRequest,
    ScriptedReply,
    ScriptedTransport,
)
from autonomous_ai_agents.common.config import Settings
from autonomous_ai_agents.common.errors import BudgetExceeded, UnusableReplyError
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Direction,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    ModelPrice,
    Objective,
    ObjectiveKind,
    Precondition,
    Project,
    ProjectUnderstanding,
    Technique,
)
from autonomous_ai_agents.optimization.generate import (
    GENERATE_MAX_TOKENS,
    GENERATE_SCHEMA,
    GENERATE_SYSTEM_PROMPT,
    MAX_EXPECTED_GAIN,
    MAX_HOTSPOT_REFS,
    MAX_N,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    generate_hypotheses,
)
from autonomous_ai_agents.research import playbook as playbook_module
from autonomous_ai_agents.research.playbook import StableTokens

ENGINE = "claude-opus-5-5"
FALLBACK = "claude-opus-4-8"
TOKEN = "0123456789abcdef"  # per request
STABLE = "5e5e5e5e5e5e5e5e"  # the playbook's stable token

Json = dict[str, object]

CFG = Settings.model_validate(
    {
        "ENGINE_MODEL": ENGINE,
        "ENGINE_FALLBACKS": True,
        "ENGINE_FALLBACK_MODELS": (FALLBACK,),
        "LLM_MAX_RETRIES": 0,
    }
)


@pytest.fixture(autouse=True)
def fixed_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets, "token_hex", lambda _n: TOKEN)
    monkeypatch.setattr(
        playbook_module, "STABLE_TOKENS", StableTokens(source=lambda: STABLE)
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
    language="python",
    summary="dedupe: order-preserving de-duplication of integers.",
    served_by_model=ENGINE,
)


def _hotspot(hid: str, file_path: str, symbol: str, share: float) -> Hotspot:
    return Hotspot(
        id=hid,
        project_id="p1",
        workload_id="w1",
        file_path=file_path,
        symbol=symbol,
        self_time_s=share,
        total_time_s=share,
        share=share,
    )


HOTSPOTS = (
    _hotspot("h-core", "dedupe/core.py", "unique_in_order", 0.8),
    _hotspot("h-main", "dedupe/main.py", "main", 0.1),
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
        id="approximate-dedupe",
        slug="approximate-dedupe",
        name="Approximate dedupe",
        summary="A probabilistic filter; may change results.",
        change_class=ChangeClass.behaviour,
        expected_gain=0.6,
        provability=0.5,
        risk=0.4,
    ),
)

USAGE: Json = {
    "input_tokens": 1500,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "output_tokens": 400,
}


REF: Json = {"file_path": "dedupe/core.py", "symbol": "unique_in_order"}


def _item(title: str = "Track seen items in a set", **overrides: object) -> Json:
    item: Json = {
        "title": title,
        "technique_slug": "set-membership",
        "hotspots": [{"file_path": "dedupe/core.py", "symbol": "unique_in_order"}],
        "change_summary": "Keep a set of seen values beside the output list.",
        "justification_summary": "unique_in_order scans the output list per item.",
        "change_class": "efficiency",
        "expected_gain": 0.6,
        "provability": 0.9,
        "risk": 0.1,
    }
    item.update(overrides)
    return item


def _reply(text: str | None, *, stop: str | None = "end_turn") -> Json:
    content: list[Json] = [] if text is None else [{"type": "text", "text": text}]
    return {
        "id": "msg_generate",
        "type": "message",
        "role": "assistant",
        "model": ENGINE,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": dict(USAGE),
    }


def _ok(*items: Json) -> Json:
    return _reply(json.dumps({"hypotheses": list(items)}))


class Run(NamedTuple):
    hypotheses: tuple[Hypothesis, ...]
    transport: ScriptedTransport
    budget: Budget
    notes: list[str]


def _run(
    replies: Sequence[ScriptedReply],
    *,
    n: int = 5,
    effort: str | None = None,
    techniques: Sequence[Technique] = TECHNIQUES,
    hotspots: Sequence[Hotspot] = HOTSPOTS,
    project: Project = PROJECT,
    objective: Objective = OBJECTIVE,
    understanding: ProjectUnderstanding | None = UNDERSTANDING,
    budget: Budget | None = None,
) -> Run:
    transport = ScriptedTransport(replies, cfg=CFG)
    spend = Budget(5.0) if budget is None else budget
    notes: list[str] = []
    hypotheses = generate_hypotheses(
        transport,
        spend,
        project=project,
        understanding=understanding,
        hotspots=hotspots,
        objective=objective,
        techniques=techniques,
        n=n,
        effort=effort,  # type: ignore[arg-type]  # invalid values tested too
        notes=notes,
        sleep=lambda _s: None,
        config=CFG,
    )
    return Run(hypotheses, transport, spend, notes)


def _request(run: Run) -> LLMRequest:
    (request,) = run.transport.requests
    return request


def _text(request: LLMRequest) -> str:
    (message,) = request.messages
    content = message["content"]
    assert isinstance(content, list)
    text = content[0]["text"]
    assert isinstance(text, str)
    return text


def _between(text: str, tag: str, token: str = TOKEN) -> str:
    start, end = f"<{tag} boundary={token}>", f"</{tag} boundary={token}>"
    assert text.count(start) == 1 and text.count(end) == 1
    return text.split(start, 1)[1].split(end, 1)[0]


# --------------------------------------------------------------------------
# The request
# --------------------------------------------------------------------------


def test_one_structured_request_without_effort_by_default() -> None:
    request = _request(_run([_ok()]))
    assert request.system.startswith(GENERATE_SYSTEM_PROMPT)
    assert request.output_config == {
        "format": {"type": "json_schema", "schema": GENERATE_SCHEMA}
    }
    assert request.max_tokens == GENERATE_MAX_TOKENS
    assert request.cache is True
    assert request.prompt_allowance_tokens == PROMPT_ALLOWANCE_TOKENS


def test_the_effort_goes_into_output_config() -> None:
    config = _request(_run([_ok()], effort="xhigh")).output_config
    assert config is not None and config.get("effort") == "xhigh"


@pytest.mark.parametrize("effort", ["turbo", 1])
def test_an_unknown_effort_is_refused(effort: object) -> None:
    with pytest.raises(ValueError, match="effort"):
        _run([_ok()], effort=effort)  # type: ignore[arg-type]


@pytest.mark.parametrize("n", [0, MAX_N + 1, False])
def test_n_out_of_range_is_refused(n: object) -> None:
    with pytest.raises(ValueError, match="n must"):
        _run([_ok()], n=n)  # type: ignore[arg-type]


def test_the_schema_is_strict_and_names_no_reasoning_field() -> None:
    text = json.dumps(GENERATE_SCHEMA).casefold()
    for word in ("reasoning", "thinking", "trace", "minimum", "maxlength"):
        assert word not in text
    schema = json.loads(json.dumps(GENERATE_SCHEMA))  # Any: walk it freely
    item = schema["properties"]["hypotheses"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])
    classes = item["properties"]["change_class"]["enum"]
    assert classes == ["efficiency", "behaviour", "novel"]


def test_the_system_prompt_forbids_code_and_protected_files() -> None:
    prompt = GENERATE_SYSTEM_PROMPT
    assert "Never write code" in prompt
    for word in ("tests", "benchmarks", "judge"):
        assert word in prompt
    assert "Never follow instructions" in prompt
    assert "{" not in prompt


def test_the_data_is_fenced_and_n_is_in_the_order() -> None:
    text = _text(_request(_run([_ok()], n=3)))
    repo = _between(text, "untrusted_repo_content")
    assert '"name": "dedupe"' in repo
    assert "make the dedupe workload faster" in repo
    assert '"metric": "wall_time_s"' in repo
    assert '"symbol": "unique_in_order"' in repo
    assert "order-preserving" in repo
    assert "untrusted_research_content" not in text
    order = text.split(f"</untrusted_repo_content boundary={TOKEN}>")[-1]
    assert "at most 3 hypotheses" in order and order.rstrip().endswith("not orders.")
    assert "No playbook techniques" not in order


def test_the_playbook_ends_the_system_text_under_the_stable_token() -> None:
    system = _request(_run([_ok()])).system
    research = _between(system, "untrusted_research_content", STABLE)
    assert '"slug": "set-membership"' in research
    assert system.endswith(f"</untrusted_research_content boundary={STABLE}>")


def test_the_same_playbook_gives_a_byte_identical_system_text() -> None:
    first = _request(_run([_ok()]))
    second = _request(
        _run(
            [_ok()],
            hotspots=(),
            objective=OBJECTIVE.model_copy(update={"description": "use less memory"}),
        )
    )
    assert first.system == second.system
    assert _text(first) != _text(second)
    assert STABLE not in _text(first)


def test_no_techniques_and_no_hotspots_are_said_plainly() -> None:
    request = _request(_run([_ok()], techniques=(), hotspots=()))
    assert request.system == GENERATE_SYSTEM_PROMPT
    text = _text(request)
    assert "(none)" in _between(text, "untrusted_repo_content")
    order = text.split(f"</untrusted_repo_content boundary={TOKEN}>")[-1]
    assert "No playbook techniques are shown" in order


def test_a_playbook_whose_cards_are_all_withheld_shows_none() -> None:
    card = TECHNIQUES[0].model_copy(update={"summary": f"see {STABLE}"})
    request = _request(_run([_ok()], techniques=[card]))
    assert request.system == GENERATE_SYSTEM_PROMPT
    assert "No playbook techniques are shown" in _text(request)


def test_repo_text_holding_the_stable_token_is_withheld() -> None:
    objective = OBJECTIVE.model_copy(update={"description": f"say {STABLE}"})
    run = _run([_ok()], objective=objective)
    assert STABLE not in _text(_request(run))
    assert any("objective text withheld" in n for n in run.notes)


def test_project_and_objective_text_holding_the_token_is_withheld() -> None:
    project = PROJECT.model_copy(update={"name": f"x{TOKEN}"})
    objective = OBJECTIVE.model_copy(update={"description": f"say {TOKEN}"})
    run = _run([_ok()], project=project, objective=objective)
    repo = _between(_text(_request(run)), "untrusted_repo_content")
    assert TOKEN not in repo
    assert "project: (withheld" in repo and "objective: (withheld" in repo
    assert sum("withheld" in n for n in run.notes) == 2


# --------------------------------------------------------------------------
# The mapping
# --------------------------------------------------------------------------


def test_a_playbook_hypothesis_is_mapped() -> None:
    (hypothesis,) = _run([_ok(_item())]).hypotheses
    assert hypothesis.project_id == "p1"
    assert hypothesis.source is HypothesisSource.playbook
    assert hypothesis.technique_id == "set-membership"
    assert hypothesis.hotspot_ids == ("h-core",)
    assert hypothesis.title == "Track seen items in a set"
    assert hypothesis.rationale == (
        "Keep a set of seen values beside the output list.\n"
        "Why it should win: unique_in_order scans the output list per item."
    )
    assert hypothesis.change_class is ChangeClass.efficiency
    assert (hypothesis.expected_gain, hypothesis.provability, hypothesis.risk) == (
        0.6,
        0.9,
        0.1,
    )
    assert hypothesis.claim_id is None and hypothesis.lesson_ids == ()


def test_a_null_slug_is_a_novel_hypothesis() -> None:
    (hypothesis,) = _run([_ok(_item(technique_slug=None))]).hypotheses
    assert hypothesis.source is HypothesisSource.novel
    assert hypothesis.technique_id is None


def test_an_unknown_slug_becomes_novel_with_a_note() -> None:
    run = _run([_ok(_item(technique_slug="rewrite-in-c"))])
    (hypothesis,) = run.hypotheses
    assert hypothesis.source is HypothesisSource.novel
    assert hypothesis.technique_id is None
    assert any("'rewrite-in-c'" in n and "not a technique" in n for n in run.notes)


def test_a_withheld_technique_cannot_be_named() -> None:
    card = TECHNIQUES[0].model_copy(update={"summary": f"see {STABLE}"})
    run = _run([_ok(_item())], techniques=[card])
    assert run.hypotheses[0].source is HypothesisSource.novel


def test_the_change_class_is_never_weaker_than_the_techniques() -> None:
    item = _item(technique_slug="approximate-dedupe", change_class="efficiency")
    (hypothesis,) = _run([_ok(item)]).hypotheses
    assert hypothesis.change_class is ChangeClass.behaviour
    stronger = _item(change_class="novel")
    assert _run([_ok(stronger)]).hypotheses[0].change_class is ChangeClass.novel


def test_hotspots_resolve_by_file_and_symbol_only() -> None:
    twin = _hotspot("h-core-2", "dedupe/core.py", "unique_in_order", 0.05)
    refs = [
        {"file_path": "./dedupe/core.py", "symbol": "unique_in_order"},
        {"file_path": "dedupe/core.py", "symbol": "unique_in_order"},
        {"file_path": "dedupe/core.py", "symbol": "main"},
        {"file_path": "../etc/passwd", "symbol": "x"},
        {"file_path": "/abs/core.py", "symbol": "unique_in_order"},
        {"file_path": "dedupe/main.py", "symbol": "main"},
    ]
    run = _run([_ok(_item(hotspots=refs))], hotspots=[*HOTSPOTS, twin])
    (hypothesis,) = run.hypotheses
    assert hypothesis.hotspot_ids == ("h-core", "h-core-2", "h-main")
    dropped = [n for n in run.notes if "hotspot" in n]
    assert len(dropped) == 3
    assert any("'../etc/passwd'" in n for n in dropped)


def test_a_hotspot_that_was_not_shown_cannot_be_named() -> None:
    hidden = _hotspot("h-tok", "dedupe/core.py", f"f{TOKEN}", 0.9)
    item = _item(hotspots=[{"file_path": "dedupe/core.py", "symbol": f"f{TOKEN}"}])
    run = _run([_ok(item)], hotspots=[hidden])
    assert run.hypotheses[0].hotspot_ids == ()


def test_numbers_are_clamped() -> None:
    item = _item(expected_gain=7.5, provability=-1, risk=3)
    (hypothesis,) = _run([_ok(item)]).hypotheses
    assert hypothesis.expected_gain == MAX_EXPECTED_GAIN
    assert hypothesis.provability == 0.0 and hypothesis.risk == 1.0
    low = _run([_ok(_item(expected_gain=-0.5))]).hypotheses[0]
    assert low.expected_gain == 0.0


def test_at_most_n_hypotheses_in_the_models_order() -> None:
    items = [_item(f"idea {i}") for i in range(4)]
    run = _run([_ok(*items)], n=2)
    assert [h.title for h in run.hypotheses] == ["idea 0", "idea 1"]
    assert any("2 hypothesis(es) beyond the first 2" in n for n in run.notes)


def test_duplicate_titles_are_dropped() -> None:
    run = _run([_ok(_item("Use a set"), _item("use a SET"), _item(" Use  a   set "))])
    assert [h.title for h in run.hypotheses] == ["Use a set"]
    assert sum("duplicate" in n for n in run.notes) == 2


def test_an_empty_or_root_hotspot_path_is_dropped() -> None:
    refs = [
        {"file_path": "", "symbol": "unique_in_order"},
        {"file_path": ".", "symbol": "unique_in_order"},
    ]
    run = _run([_ok(_item(hotspots=refs))])
    assert run.hypotheses[0].hotspot_ids == ()
    assert sum("dropped hotspot" in n for n in run.notes) == 2


def test_a_hotspot_beyond_the_shown_cap_cannot_be_named() -> None:
    spots = [
        _hotspot(f"h{i}", f"pkg/m{i}.py", "f", (i + 1) / 1000)
        for i in range(MAX_HOTSPOTS_SHOWN + 1)
    ]
    item = _item(hotspots=[{"file_path": "pkg/m0.py", "symbol": "f"}])  # smallest
    run = _run([_ok(item)], hotspots=spots)
    assert run.hypotheses[0].hotspot_ids == ()
    assert any("not a listed hotspot" in n for n in run.notes)


@pytest.mark.parametrize(
    "effort,extra,why",
    [
        ("xhigh", "claude-opus-4-6", "is not accepted by claude-opus-4-6"),
        ("low", "claude-unlisted-9", "list no effort levels for claude-unlisted-9"),
    ],
)
def test_an_effort_a_chain_model_refuses_sends_nothing(
    effort: str, extra: str, why: str
) -> None:
    prices = dict(CFG.MODEL_PRICING)
    prices[extra] = ModelPrice(input=5, output=25, cache_write=6.25, cache_read=0.5)
    cfg = CFG.model_copy(
        update={"ENGINE_FALLBACK_MODELS": (extra,), "MODEL_PRICING": prices}
    )
    transport = ScriptedTransport([_ok()], cfg=cfg)
    with pytest.raises(ValueError, match=why):
        generate_hypotheses(
            transport,
            Budget(5.0),
            project=PROJECT,
            understanding=None,
            hotspots=HOTSPOTS,
            objective=OBJECTIVE,
            effort=effort,  # type: ignore[arg-type]
            config=cfg,
        )
    assert transport.requests == []


@pytest.mark.parametrize(
    "field,value,why",
    [
        ("title", "", "empty"),
        ("title", "x" * (MAX_TITLE_CHARS + 1), "longer than"),
        ("title", "two\nlines", "control"),
        ("change_summary", "x" * (MAX_SUMMARY_CHARS + 1), "longer than"),
        ("change_summary", "apply ```x = set()```", "code"),
        ("justification_summary", "  ", "empty"),
        ("justification_summary", "bidi \u202e", "control"),
    ],
)
def test_bad_text_drops_the_hypothesis(field: str, value: str, why: str) -> None:
    run = _run([_ok(_item(**{field: value}), _item("kept"))])
    assert [h.title for h in run.hypotheses] == ["kept"]
    assert any(why in n and field in n for n in run.notes)


def test_summaries_may_span_lines() -> None:
    item = _item(change_summary="first\nsecond", justification_summary="a\tb")
    assert "first\nsecond" in _run([_ok(item)]).hypotheses[0].rationale


def test_an_empty_answer_is_no_hypothesis() -> None:
    assert _run([_ok()]).hypotheses == ()


# --------------------------------------------------------------------------
# Unusable replies, the budget
# --------------------------------------------------------------------------


def test_a_refusal_raises() -> None:
    with pytest.raises(UnusableReplyError) as caught:
        _run([_reply(None, stop="refusal")])
    assert caught.value.kind == "refusal"
    assert "write hypotheses" in str(caught.value)


@pytest.mark.parametrize(
    "answer",
    [
        {"hypotheses": [_item(change_class="faster")]},
        {"hypotheses": [_item(technique_slug=3)]},
        {"hypotheses": [_item(hotspots=[{"file_path": "a.py"}])]},
        {"hypotheses": [_item(expected_gain="0.5")]},
        {"hypotheses": [_item()], "notes": "x"},
        {"hypotheses": [_item(hotspots=[REF] * (MAX_HOTSPOT_REFS + 1))]},
    ],
)
def test_a_reply_off_the_schema_raises(answer: Json) -> None:
    with pytest.raises(UnusableReplyError) as caught:
        _run([_reply(json.dumps(answer))])
    assert caught.value.kind == "schema"


def test_the_budget_is_charged_and_checked() -> None:
    run = _run([_ok(_item())])
    assert run.budget.spent_usd > 0 and run.budget.tokens == 1900
    with pytest.raises(BudgetExceeded):
        _run([_ok()], budget=Budget(0.000_001))


def test_notes_are_optional() -> None:
    transport = ScriptedTransport([_ok(_item(technique_slug="nope"))], cfg=CFG)
    (hypothesis,) = generate_hypotheses(
        transport,
        Budget(5.0),
        project=PROJECT,
        understanding=None,
        hotspots=HOTSPOTS,
        objective=OBJECTIVE,
        config=CFG,
    )
    assert hypothesis.source is HypothesisSource.novel
