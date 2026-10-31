"""The idea pipeline (Step 3 Wave 2, N4a; spec amendment 3.4, 4.2b, D44-D59,
D65, section 5's budget rows, appendix C1 and P10).

``IdeaPipelineGenerator`` composes S0 (code context), S1 (the obvious lane),
S2 (six lens lanes and the leap), S4a (the deterministic filter), S3 (the
reviewer) and S4b (the portfolio) behind the ``HypothesisGenerator``
Protocol. Every test runs on scripted replies: ``ScriptedTransport`` (with
``IDEAS_LANE_WORKERS=1`` the lanes go out in ``IDEAS_LENSES`` order, then
the leap) or a stub keyed by lane name for the parallel cases. No model is
called. Spend is read from the parent budget's delta, as the node reads it.
"""

from __future__ import annotations

import itertools
import json
import re
import secrets
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence

import pytest
from anthropic.types.beta import BetaMessage

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import preflight_estimate, response_cost
from autonomous_ai_agents.clients.transport import (
    LLMNoResponseError,
    LLMRequest,
    ScriptedReply,
    ScriptedTransport,
)
from autonomous_ai_agents.common.config import Role, Settings, role_settings
from autonomous_ai_agents.common.errors import (
    BudgetExceeded,
    LLMConfigError,
)
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Direction,
    EventLevel,
    Hotspot,
    HypothesisSource,
    Lesson,
    Objective,
    ObjectiveKind,
    Project,
    Technique,
    VerdictOutcome,
)
from autonomous_ai_agents.common.repo_read import RepoReader
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.optimization.hypothesis_source import (
    ClaudeHypothesisGenerator,
)
from autonomous_ai_agents.optimization.idea_pipeline import IdeaPipelineGenerator
from autonomous_ai_agents.optimization.idea_portfolio import rotation
from autonomous_ai_agents.optimization.idea_review import REVIEW_SYSTEM_PROMPT
from autonomous_ai_agents.optimization.idea_types import (
    LENS_LANES,
    Lane,
    ReviewVerdict,
)
from autonomous_ai_agents.optimization.sources import (
    GenerateResult,
    HypothesisGenerator,
)
from autonomous_ai_agents.research import playbook as playbook_module
from autonomous_ai_agents.research.playbook import StableTokens

Json = dict[str, object]
SHA = "0123456789abcdef0123456789abcdef01234567"
SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"
TOKENS = ("1a1a1a1a1a1a1a1a", "2b2b2b2b2b2b2b2b", "4d4d4d4d4d4d4d4d")
USAGE: Mapping[str, int] = {"input_tokens": 3000, "output_tokens": 900}
RUN_ID = "run-1"
BASE = Settings.model_validate(
    {
        "IDEA_PIPELINE": True,
        "ENGINE_FALLBACKS": False,
        "LLM_MAX_RETRIES": 0,
        "IDEAS_LANE_WORKERS": 1,
    }
)
LANES_ALL = (*LENS_LANES, Lane.leap)

SOURCE = '''"""Text tools."""
import re

KEYWORDS = ("if", "else", "while", "for", "return")


def parse_tokens(text, keywords=KEYWORDS):
    found = []
    for word in text.split():
        if word.strip().casefold() in keywords:
            found.append(word.upper())
    return found


def count_words(text):
    counts = {}
    for word in text.split():
        counts[word] = counts.get(word, 0) + 1
    return counts


def merge_runs(items):
    merged = []
    for item in sorted(items):
        if merged and merged[-1] == item:
            continue
        merged.append(item)
    return merged


def join_lines(lines):
    result = ""
    for line in lines:
        result = result + line + "\\n"
    return result


def find_all(pattern, text):
    hits = []
    for start in range(len(text)):
        if re.match(pattern, text[start:]):
            hits.append(start)
    return hits
'''
QUOTES = {
    "parse_tokens": "if word.strip().casefold() in keywords:",
    "count_words": "counts[word] = counts.get(word, 0) + 1",
    "merge_runs": "for item in sorted(items):\n    if merged and merged[-1] == item:",
    "join_lines": 'result = result + line + "\\n"',
    "find_all": "if re.match(pattern, text[start:]):",
    "header": 'KEYWORDS = ("if", "else", "while", "for", "return")',
}
PATH = "pkg/text.py"
PROJECT = Project(id="p1", name="texttools", root_path="/srv/texttools")
OBJECTIVE = Objective(
    project_id="p1",
    kind=ObjectiveKind.runtime,
    metric="wall_time_s",
    direction=Direction.minimize,
    min_relative_gain=0.043,
    description="make the text tools faster",
)
FUNCTIONS = ("parse_tokens", "count_words", "merge_runs", "join_lines", "find_all")
HOTSPOTS = tuple(
    Hotspot(
        id=f"h-{name}",
        project_id="p1",
        workload_id="w1",
        file_path=PATH,
        symbol=name,
        self_time_s=1.0,
        total_time_s=2.0,
        share=0.1,
    )
    for name in FUNCTIONS
)


@pytest.fixture(autouse=True)
def fixed_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_tokens(monkeypatch)
    monkeypatch.setattr(
        playbook_module, "STABLE_TOKENS", StableTokens(source=lambda: "5e5e" * 4)
    )


def _reset_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    cycle: Iterator[str] = itertools.cycle(TOKENS)
    monkeypatch.setattr(secrets, "token_hex", lambda _n: next(cycle))


class _Reader:
    def __init__(self, blobs: Mapping[str, str]) -> None:
        self.blobs = {p: b.encode() for p, b in blobs.items()}

    def ls_tree(self, commit: str) -> tuple[str, ...]:
        if commit != SHA:
            raise GitError("unknown commit")
        return tuple(sorted(self.blobs))

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        data = self.blobs[path]
        return data if limit is None else data[:limit]


def _reader(_project: Project) -> _Reader:
    return _Reader({PATH: SOURCE})


# --------------------------------------------------------------------------
# Replies
# --------------------------------------------------------------------------


def _message(
    payload: Json,
    *,
    model: str = SONNET,
    stop: str = "end_turn",
    usage: Mapping[str, int] = USAGE,
) -> Json:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": dict(usage),
    }


def _idea(
    title: str,
    where: str,
    *,
    mechanism: str = "data_structure",
    cells: Sequence[str] = ("representation:indexed",),
    tier: str = "combinational",
    change_class: str = "efficiency",
    slug: str | None = None,
) -> Json:
    symbol = where if where in FUNCTIONS else "parse_tokens"
    return {
        "title": title,
        "technique_slug": slug,
        "hotspots": [{"file_path": PATH, "symbol": symbol}],
        "change_summary": f"Change {symbol} as the title says.",
        "justification_summary": f"{symbol} holds 20 % of the time.",
        "depends_on_path": PATH,
        "depends_on_quote": QUOTES[where],
        "precondition": "the inputs are plain strings",
        "equivalence_summary": "the same values come out in the same order",
        "mechanism": mechanism,
        "morph_cells": list(cells),
        "tier": tier,
        "typicality": "uncommon",
        "change_class": change_class,
        "expected_gain": 0.2,
        "provability": 0.8,
        "risk": 0.1,
    }


def _ideas(*items: Json, model: str = SONNET, stop: str = "end_turn") -> Json:
    return _message({"hypotheses": list(items)}, model=model, stop=stop)


def _review(*entries: tuple[str, str, str]) -> Json:
    reviews = [
        {
            "idea": idea,
            "verdict": verdict,
            "reason": reason,
            "duplicate_of": None,
            "change_plan": "" if verdict == "infeasible" else f"Edit {idea} in turn.",
        }
        for idea, verdict, reason in entries
    ]
    return _message({"reviews": reviews}, model=OPUS)


O1 = _idea("Use a frozenset for the keywords", "parse_tokens")
O2 = _idea(
    "Count words with a Counter",
    "count_words",
    cells=("representation:specialised_type",),
)
O3 = _idea(
    "Dedupe runs in one pass",
    "merge_runs",
    mechanism="algorithm",
    cells=("algorithm:better_constant",),
)
S1_REPLY = _ideas(O1, O2, O3)
LENS: dict[Lane, list[Json]] = {
    Lane.eliminate: [
        _idea("Skip the sort when items arrive sorted", "merge_runs",
              mechanism="remove_work", cells=("work:eliminate",)),
    ],
    Lane.assume_less: [
        _idea("Build lines with one join", "join_lines",
              mechanism="allocation_or_copying", cells=("memory:reuse_buffers",)),
    ],
    Lane.name_the_problem: [
        _idea("Scan with one compiled finditer pass", "find_all",
              mechanism="algorithm", cells=("algorithm:lower_complexity",),
              tier="transformational"),
    ],
    Lane.recombine: [
        _idea("Precompute a keyword table at import", "parse_tokens",
              mechanism="precompute_or_cache",
              cells=("timing:precompute", "memory:cache_across_calls"),
              tier="exploratory"),
    ],
    Lane.resolve_tradeoff: [],
    Lane.far: [_idea("Treat the keywords as a postal index", "header")],
}  # fmt: skip
LEAP = _ideas(
    _idea(
        "Represent counts as an array of word ids",
        "count_words",
        mechanism="representation",
        cells=("representation:compact",),
        tier="transformational",
    ),
    model=OPUS,
)
REVIEW = _review(
    ("obvious-01", "feasible", "none"),
    ("obvious-02", "feasible", "none"),
    ("obvious-03", "unknown", "none"),
    ("eliminate-01", "feasible", "none"),
    ("assume_less-01", "infeasible", "precondition_false"),
    ("name_the_problem-01", "feasible", "none"),
    ("recombine-01", "feasible", "none"),
    ("leap-01", "feasible", "none"),
)
TITLE_OF = {
    Lane.eliminate: "Skip the sort when items arrive sorted",
    Lane.name_the_problem: "Scan with one compiled finditer pass",
    Lane.recombine: "Precompute a keyword table at import",
    Lane.leap: "Represent counts as an array of word ids",
}


def _lens_replies(**changes: ScriptedReply) -> list[ScriptedReply]:
    return [changes.get(lane.value, _ideas(*LENS[lane])) for lane in LENS_LANES]


# --------------------------------------------------------------------------
# Running the pipeline
# --------------------------------------------------------------------------


class _Run:
    def __init__(
        self,
        *,
        lane: Sequence[ScriptedReply] = (),
        leap: Sequence[ScriptedReply] = (),
        reviewer: Sequence[ScriptedReply] = (),
        cfg: Settings = BASE,
        fallback: HypothesisGenerator | None = None,
        reader: Callable[[Project], RepoReader] | None = _reader,
    ) -> None:
        self.cfg = cfg
        self.transports: dict[Role, ScriptedTransport] = {
            "lane": ScriptedTransport(lane, cfg=role_settings(cfg, "lane")),
            "leap": ScriptedTransport(leap, cfg=role_settings(cfg, "leap")),
            "reviewer": ScriptedTransport(reviewer, cfg=role_settings(cfg, "reviewer")),
        }
        self.generator = IdeaPipelineGenerator(
            dict(self.transports),
            reader=reader,
            config=cfg,
            sleep=lambda _s: None,
            fallback=fallback,
        )

    def __call__(
        self,
        *,
        budget: Budget | None = None,
        commit: str | None = SHA,
        run_id: str | None = RUN_ID,
        call_index: int = 0,
        avoid_titles: Sequence[str] = (),
        lessons: Sequence[Lesson] = (),
        techniques: Sequence[Technique] = (),
        n: int = 5,
        hotspots: Sequence[Hotspot] = HOTSPOTS,
    ) -> GenerateResult:
        self.budget = Budget(5.0) if budget is None else budget
        return self.generator.generate(
            project=PROJECT,
            understanding=None,
            hotspots=hotspots,
            objective=OBJECTIVE,
            techniques=techniques,
            lessons=lessons,
            avoid_titles=avoid_titles,
            n=n,
            budget=self.budget,
            commit=commit,
            run_id=run_id,
            call_index=call_index,
        )

    def requests(self, role: Role) -> list[LLMRequest]:
        return self.transports[role].requests


def _full() -> _Run:
    return _Run(lane=[S1_REPLY, *_lens_replies()], leap=[LEAP], reviewer=[REVIEW])


def _texts(request: LLMRequest) -> list[str]:
    content = request.messages[0]["content"]
    assert isinstance(content, list)
    found: list[str] = []
    for block in content:
        assert isinstance(block, dict)
        text = block.get("text")
        assert isinstance(text, str)
        found.append(text)
    return found


def _bill(model: str, usage: Mapping[str, int] = USAGE) -> float:
    return response_cost(usage, BASE.MODEL_PRICING, model=model)[0]


def _estimate(transport: ScriptedTransport, request: LLMRequest) -> float:
    return preflight_estimate(
        transport.count_input_tokens(request),
        request.max_tokens,
        transport.chain,
        transport.prices,
    )


def _noted(notes: Sequence[str], *parts: str) -> bool:
    return any(all(part in note for part in parts) for note in notes)


def _non_obvious_order() -> list[str]:
    return [TITLE_OF[lane] for lane in rotation(RUN_ID, LANES_ALL) if lane in TITLE_OF]


# --------------------------------------------------------------------------
# The whole pipeline
# --------------------------------------------------------------------------


def test_nine_replies_give_the_interleaved_portfolio() -> None:
    run = _full()
    result = run()
    picks = _non_obvious_order()
    titles = [h.title for h in result.hypotheses]
    assert titles == [
        O1["title"], picks[0], picks[1],
        O2["title"], picks[2], picks[3],
        O3["title"],
    ]  # fmt: skip
    assert len(run.requests("lane")) == 7
    assert len(run.requests("leap")) == 1
    assert len(run.requests("reviewer")) == 1
    assert all(t.remaining == 0 for t in run.transports.values())
    assert isinstance(run.generator, HypothesisGenerator)


def test_spend_is_the_budget_delta_summed_over_every_stage() -> None:
    run = _full()
    start = Budget(5.0, spent_usd=0.5, tokens=7)
    result = run(budget=start)
    expected = 7 * _bill(SONNET) + 2 * _bill(OPUS)
    assert run.budget.spent_usd == pytest.approx(0.5 + expected)
    assert run.budget.tokens == 7 + 9 * sum(USAGE.values())
    assert result.stats is not None
    assert result.stats.cost_usd == pytest.approx(expected)


def test_the_requests_share_one_data_block_and_cache_it_only_for_the_lanes() -> None:
    run = _full()
    run()
    s1, *lenses = run.requests("lane")
    leap = run.requests("leap")[0]
    prefix = _texts(s1)[0]
    assert prefix.startswith("This request's boundary token is")
    assert "<untrusted_repo_content" in prefix
    for request in (s1, *lenses, leap):
        assert _texts(request)[0] == prefix
        assert request.cache is False
    content = s1.messages[0]["content"]
    assert isinstance(content, list)
    assert content[0].get("cache_control") == {"type": "ephemeral"}
    leap_content = leap.messages[0]["content"]
    assert isinstance(leap_content, list)
    assert "cache_control" not in leap_content[0]


def test_s1_shows_no_lens_and_no_examples_and_the_lanes_name_its_titles() -> None:
    run = _full()
    run(avoid_titles=("Inline the helper",))
    s1, *lenses = run.requests("lane")
    ask = _texts(s1)[1]
    assert "<lens" not in ask
    assert "<examples" not in ask
    assert '"Inline the helper"' in ask
    assert "Think the problem through before you answer." in ask  # Sonnet lane
    for lane, request in zip(LENS_LANES, lenses, strict=True):
        text = _texts(request)[1]
        assert f'<lens name="{lane.value}">' in text
        assert text.count("<example ") == 3
        for title in (O1["title"], O2["title"], O3["title"], "Inline the helper"):
            assert json.dumps(title) in text
    leap_text = _texts(run.requests("leap")[0])[1]
    assert '<lens name="leap">' in leap_text
    assert "Think the problem through" not in leap_text  # Opus leap
    assert "4.3 %" in leap_text


def test_events_record_each_drop_and_stats_count_each_stage() -> None:
    result = _full()()
    dropped = [e for e in result.events if e.code == "idea_dropped"]
    reasons = {(e.data["lane"], e.data["reason"]) for e in dropped}
    assert ("far", "its quote lies outside every hot function") in reasons
    assert ("assume_less", "review_precondition_false") in reasons
    assert all(e.level is EventLevel.info for e in dropped)
    stats = result.stats
    assert stats is not None
    assert stats.ideas_per_lane[Lane.obvious] == 3
    assert stats.ideas_per_lane[Lane.far] == 0
    assert stats.ideas_per_lane[Lane.resolve_tradeoff] == 0
    assert stats.ideas_per_lane[Lane.leap] == 1
    assert stats.grounded == 8
    assert stats.anchored == 8
    assert stats.gate_passed == 5
    assert stats.non_obvious == 5
    assert stats.review_verdicts == {
        ReviewVerdict.feasible: 6,
        ReviewVerdict.unknown: 1,
        ReviewVerdict.infeasible: 1,
    }
    assert stats.unique_signatures == 8
    assert stats.cache_read_tokens == 0
    assert stats.stop_reasons == dict.fromkeys(
        ["obvious", *(lane.value for lane in LANES_ALL), "reviewer"], "end_turn"
    )


def test_tags_mark_engine_facts_and_claimed_labels() -> None:
    result = _full()()
    first = result.hypotheses[0]
    assert first.tags == (
        "lane:obvious",
        "review:feasible",
        "claimed_tier:combinational",
        "claimed_mechanism:data_structure",
        "claimed_cell:representation:indexed",
        "claimed_typicality:uncommon",
    )
    recombined = next(h for h in result.hypotheses if "keyword table" in h.title)
    assert "lane:recombine" in recombined.tags
    assert "claimed_cell:timing:precompute" in recombined.tags
    assert "claimed_cell:memory:cache_across_calls" in recombined.tags
    for hypothesis in result.hypotheses:
        claims = [t for t in hypothesis.tags if not t.startswith(("lane:", "review:"))]
        assert all(t.startswith("claimed_") for t in claims)


def test_the_rationale_carries_precondition_equivalence_and_plan() -> None:
    result = _full()()
    first = result.hypotheses[0]
    assert first.rationale == (
        "Change parse_tokens as the title says.\n"
        "Why it should win: parse_tokens holds 20 % of the time.\n"
        "Precondition: the inputs are plain strings\n"
        "Why the output stays the same: the same values come out in the same order\n"
        "Plan: Edit obvious-01 in turn."
    )
    third_obvious = next(h for h in result.hypotheses if h.title == O3["title"])
    assert third_obvious.rationale.endswith("Plan: Edit obvious-03 in turn.")
    assert first.hotspot_ids == ("h-parse_tokens",)
    assert first.source is HypothesisSource.novel


# --------------------------------------------------------------------------
# Reservation and child budgets (D48)
# --------------------------------------------------------------------------


def test_an_unaffordable_fan_out_skips_s2_whole_and_returns_s1() -> None:
    probe = _Run(lane=[S1_REPLY])
    probe(call_index=1)
    s1_estimate = _estimate(probe.transports["lane"], probe.requests("lane")[0])
    run = _full()
    result = run(budget=Budget(s1_estimate * 2))
    assert [h.title for h in result.hypotheses] == [
        O1["title"],
        O2["title"],
        O3["title"],
    ]
    assert len(run.requests("lane")) == 1
    assert run.requests("leap") == [] and run.requests("reviewer") == []
    (event,) = [e for e in result.events if e.code == "discovery_unaffordable"]
    assert event.level is EventLevel.warning
    assert event.data["stage"] == "lanes"
    assert run.budget.spent_usd == pytest.approx(_bill(SONNET))
    assert all("review:" not in tag for h in result.hypotheses for tag in h.tags)


def test_an_unaffordable_s1_raises_before_anything_is_sent() -> None:
    run = _full()
    with pytest.raises(BudgetExceeded):
        run(budget=Budget(1e-6))
    assert run.requests("lane") == []
    assert run.budget.spent_usd == 0.0


def test_a_timed_out_lane_is_charged_its_estimate_and_the_others_run() -> None:
    cfg = BASE.model_copy(update={"LLM_MAX_RETRIES": 2})
    timeout = LLMNoResponseError("Claude API: no answer in time", timed_out=True)
    run = _Run(
        lane=[S1_REPLY, *_lens_replies(eliminate=timeout)],
        leap=[LEAP],
        reviewer=[REVIEW],
        cfg=cfg,
    )
    result = run()
    eliminate = run.requests("lane")[1]
    charged = _estimate(run.transports["lane"], eliminate)
    expected = 6 * _bill(SONNET) + 2 * _bill(OPUS) + charged
    assert run.budget.spent_usd == pytest.approx(expected)
    assert len(run.requests("lane")) == 7  # sent once: the retry is refused
    assert _noted(result.notes, "lane eliminate: charged failure, not retried")
    assert TITLE_OF[Lane.eliminate] not in [h.title for h in result.hypotheses]
    assert result.stats is not None
    assert result.stats.stop_reasons["eliminate"] is None


def test_a_lane_out_of_retries_is_dropped_and_noted() -> None:
    timeout = LLMNoResponseError("Claude API: connection lost", timed_out=False)
    run = _Run(
        lane=[S1_REPLY, *_lens_replies(far=timeout)], leap=[LEAP], reviewer=[REVIEW]
    )
    result = run()
    assert _noted(result.notes, "lane far failed (LLMUnavailable)", "gave up")
    assert len(result.hypotheses) == 7


class _CountOnce(ScriptedTransport):
    """Counts each request once honestly; a recount would be refused."""

    def __init__(self, replies: Sequence[ScriptedReply], *, cfg: Settings) -> None:
        super().__init__(replies, cfg=cfg)
        self.counted: list[LLMRequest] = []

    def count_input_tokens(self, request: LLMRequest) -> int:
        if any(r is request for r in self.counted):
            raise AssertionError("a lane's prompt was counted twice")
        self.counted.append(request)
        return super().count_input_tokens(request)


def test_a_lane_whose_recount_would_fail_still_runs_on_its_estimate() -> None:
    run = _full()
    lane_cfg = role_settings(BASE, "lane")
    counted = _CountOnce([S1_REPLY, *_lens_replies()], cfg=lane_cfg)
    run.transports["lane"] = counted
    run.generator = IdeaPipelineGenerator(
        dict(run.transports), reader=_reader, config=BASE, sleep=lambda _s: None
    )
    result = run()
    assert len(counted.counted) == 7
    assert len(counted.requests) == 7
    assert len(result.hypotheses) == 7


def test_a_refused_lane_is_dropped_and_never_sent_again() -> None:
    refusal = _ideas(*LENS[Lane.recombine], stop="refusal")
    run = _Run(
        lane=[S1_REPLY, *_lens_replies(recombine=refusal)],
        leap=[LEAP],
        reviewer=[REVIEW],
    )
    result = run()
    assert len(run.requests("lane")) == 7
    assert _noted(result.notes, "lane recombine failed (UnusableReplyError)")
    assert TITLE_OF[Lane.recombine] not in [h.title for h in result.hypotheses]
    assert result.stats is not None
    assert result.stats.stop_reasons["recombine"] == "refusal"


def test_a_lane_configuration_error_propagates_after_the_spend_is_recorded() -> None:
    denied = LLMConfigError("Claude API HTTP 401: check ANTHROPIC_API_KEY")
    run = _Run(lane=[S1_REPLY, *_lens_replies()], leap=[denied], reviewer=[REVIEW])
    with pytest.raises(LLMConfigError):
        run()
    assert run.budget.spent_usd == pytest.approx(7 * _bill(SONNET))
    assert run.requests("reviewer") == []


def test_after_a_configuration_error_lanes_not_yet_started_are_not_sent() -> None:
    # One worker (BASE): the first lens fails with a configuration error, so
    # the other lenses and the leap are never sent and nothing more is spent.
    denied = LLMConfigError("Claude API HTTP 401: check ANTHROPIC_API_KEY")
    run = _Run(lane=[S1_REPLY, *_lens_replies(eliminate=denied)], leap=[LEAP])
    with pytest.raises(LLMConfigError):
        run()
    assert len(run.requests("lane")) == 2
    assert run.requests("leap") == []
    assert run.requests("reviewer") == []
    assert run.budget.spent_usd == pytest.approx(_bill(SONNET))


def test_a_parent_overrun_is_recorded_whole_then_raised() -> None:
    huge = _message(
        {"hypotheses": []}, usage={"input_tokens": 10, "output_tokens": 400_000}
    )
    run = _Run(lane=[S1_REPLY, *_lens_replies(eliminate=huge)], leap=[LEAP])
    budget = Budget(4.0)
    with pytest.raises(BudgetExceeded, match="recorded spend"):
        run(budget=budget)
    expected = 6 * _bill(SONNET) + _bill(OPUS)
    expected += _bill(SONNET, {"input_tokens": 10, "output_tokens": 400_000})
    assert budget.spent_usd == pytest.approx(expected)


# --------------------------------------------------------------------------
# Parallel lanes (IDEAS_LANE_WORKERS)
# --------------------------------------------------------------------------

_LENS_TAG = re.compile(r'<lens name="([a-z_]+)">')


class _ByLane(ScriptedTransport):
    """Answers by lane name; the first ``meet`` lane requests wait for each
    other, which proves they were in flight together."""

    def __init__(
        self,
        replies: Mapping[str, ScriptedReply],
        *,
        cfg: Settings,
        barrier: threading.Barrier | None = None,
        meet: int = 0,
    ) -> None:
        super().__init__([], cfg=cfg)
        self.by_lane = dict(replies)
        self.barrier, self.meet = barrier, meet
        self.lock = threading.Lock()
        self.sent: list[str] = []

    def send(self, request: LLMRequest) -> BetaMessage:
        if request.system == REVIEW_SYSTEM_PROMPT:
            name = "reviewer"
        else:
            found = _LENS_TAG.search(_texts(request)[1])
            name = "obvious" if found is None else found.group(1)
        with self.lock:
            self.requests.append(request)
            self.sent.append(name)
            arrived = len([s for s in self.sent if s not in ("obvious", "reviewer")])
        if self.barrier is not None and name != "obvious" and arrived <= self.meet:
            self.barrier.wait(timeout=20)
        reply = self.by_lane[name]
        if isinstance(reply, Exception):
            raise reply
        assert isinstance(reply, Mapping)
        return BetaMessage.model_validate(reply)


def _usage(i: int) -> dict[str, int]:
    return {"input_tokens": 1000 + 100 * i, "output_tokens": 200 + 10 * i}


def _parallel(
    *, barrier: threading.Barrier | None, meet: int, failing: str | None = None
) -> tuple[_ByLane, _ByLane, Settings]:
    cfg = BASE.model_copy(update={"IDEAS_LANE_WORKERS": 4, "IDEAS_REVIEW": False})
    replies: dict[str, ScriptedReply] = {"obvious": S1_REPLY}
    for i, which in enumerate(LENS_LANES):
        replies[which.value] = _message({"hypotheses": LENS[which]}, usage=_usage(i))
    if failing is not None:
        replies[failing] = LLMConfigError("Claude API HTTP 401: check the key")
    lane = _ByLane(replies, cfg=role_settings(cfg, "lane"), barrier=barrier, meet=meet)
    leap_reply = _message({"hypotheses": []}, model=OPUS, usage=_usage(9))
    leap = _ByLane({"leap": leap_reply}, cfg=role_settings(cfg, "leap"))
    return lane, leap, cfg


def _pipeline(lane: _ByLane, leap: _ByLane, cfg: Settings) -> IdeaPipelineGenerator:
    reviewer = ScriptedTransport([], cfg=role_settings(cfg, "reviewer"))
    return IdeaPipelineGenerator(
        {"lane": lane, "leap": leap, "reviewer": reviewer},
        reader=_reader,
        config=cfg,
        sleep=lambda _s: None,
    )


def _generate(generator: IdeaPipelineGenerator, budget: Budget) -> GenerateResult:
    return generator.generate(
        project=PROJECT,
        understanding=None,
        hotspots=HOTSPOTS,
        objective=OBJECTIVE,
        techniques=(),
        lessons=(),
        avoid_titles=(),
        n=5,
        budget=budget,
        commit=SHA,
        run_id=RUN_ID,
    )


def test_four_workers_send_the_seven_lanes_in_parallel_on_child_budgets() -> None:
    barrier = threading.Barrier(4)
    lane, leap, cfg = _parallel(barrier=barrier, meet=4)
    budget = Budget(5.0)
    result = _generate(_pipeline(lane, leap, cfg), budget)
    assert not barrier.broken
    assert sorted(lane.sent + leap.sent) == sorted(
        ["obvious", *(x.value for x in LANES_ALL)]
    )
    children = sum(_bill(SONNET, _usage(i)) for i in range(len(LENS_LANES)))
    children += _bill(OPUS, _usage(9))
    assert budget.spent_usd == pytest.approx(_bill(SONNET) + children)
    assert _noted(result.notes, "ideas not reviewed (IDEAS_REVIEW is off)")
    assert all("review:unknown" in h.tags for h in result.hypotheses)


def test_a_parallel_configuration_error_waits_for_every_lane_in_flight() -> None:
    lane, leap, cfg = _parallel(barrier=None, meet=0, failing="assume_less")
    budget = Budget(5.0)
    with pytest.raises(LLMConfigError):
        _generate(_pipeline(lane, leap, cfg), budget)
    sent = [name for name in lane.sent if name not in ("obvious", "assume_less")]
    paid = {lane.value: _bill(SONNET, _usage(i)) for i, lane in enumerate(LENS_LANES)}
    expected = _bill(SONNET) + sum(paid[name] for name in sent)
    expected += _bill(OPUS, _usage(9)) if leap.sent else 0.0
    assert budget.spent_usd == pytest.approx(expected)


# --------------------------------------------------------------------------
# Degraded paths
# --------------------------------------------------------------------------


def test_an_unaffordable_reviewer_leaves_every_idea_unknown() -> None:
    cfg = BASE.model_copy(update={"IDEAS_REVIEWER_MAX_TOKENS": 10_000_000})
    run = _Run(lane=[S1_REPLY, *_lens_replies()], leap=[LEAP], cfg=cfg)
    result = run()
    assert run.requests("reviewer") == []
    assert _noted(result.notes, "ideas not reviewed (the reviewer is unaffordable)")
    assert all("review:unknown" in h.tags for h in result.hypotheses)
    assert "Plan:" not in result.hypotheses[0].rationale
    assert len(result.hypotheses) == 8  # assume_less is no longer removed


def test_a_reviewer_cut_off_by_max_tokens_leaves_every_idea_unknown() -> None:
    cut = _message({"reviews": []}, model=OPUS, stop="max_tokens")
    run = _Run(lane=[S1_REPLY, *_lens_replies()], leap=[LEAP], reviewer=[cut])
    result = run()
    assert _noted(result.notes, "ideas not reviewed (the reply is unusable")
    assert result.stats is not None
    assert result.stats.review_verdicts == {ReviewVerdict.unknown: 8}
    assert result.stats.stop_reasons["reviewer"] == "max_tokens"


def test_a_failed_reviewer_request_leaves_every_idea_unknown() -> None:
    timeout = LLMNoResponseError("Claude API: no answer in time", timed_out=True)
    run = _Run(lane=[S1_REPLY, *_lens_replies()], leap=[LEAP], reviewer=[timeout])
    result = run()
    assert _noted(result.notes, "ideas not reviewed (the reviewer failed")
    assert all("review:unknown" in h.tags for h in result.hypotheses)


def test_no_idea_left_for_the_reviewer_sends_no_review() -> None:
    empty = _ideas()
    run = _Run(lane=[empty, *[empty] * 6], leap=[_ideas(model=OPUS)])
    result = run()
    assert result.hypotheses == ()
    assert run.requests("reviewer") == []
    assert _noted(result.notes, "portfolio: no non-obvious idea survives")


def test_a_failed_s1_lets_the_lanes_run_on_the_named_defaults() -> None:
    broken = _message({"not": "the schema"})
    run = _Run(lane=[broken, *_lens_replies()], leap=[LEAP], reviewer=[REVIEW])
    result = run(avoid_titles=("Inline the helper",))
    assert _noted(result.notes, "lane obvious failed (UnusableReplyError)")
    lens_text = _texts(run.requests("lane")[1])[1]
    assert json.dumps("Inline the helper") in lens_text
    assert json.dumps(O1["title"]) not in lens_text
    assert [h.title for h in result.hypotheses] == _non_obvious_order()


def test_no_commit_delegates_to_todays_generator_unchanged() -> None:
    gen_cfg = role_settings(BASE, "generator")
    today = _message(
        {"hypotheses": [{k: O1[k] for k in (
            "title", "technique_slug", "hotspots", "change_summary",
            "justification_summary", "change_class", "expected_gain",
            "provability", "risk")}]}
    )  # fmt: skip
    direct_transport = ScriptedTransport([today], cfg=gen_cfg)
    direct = ClaudeHypothesisGenerator(direct_transport, config=gen_cfg)
    direct.generate(
        project=PROJECT, understanding=None, hotspots=HOTSPOTS, objective=OBJECTIVE,
        techniques=(), lessons=(), avoid_titles=(), n=5, budget=Budget(5.0),
    )  # fmt: skip
    fallback_transport = ScriptedTransport([today], cfg=gen_cfg)
    fallback = ClaudeHypothesisGenerator(fallback_transport, config=gen_cfg)
    run = _Run(fallback=fallback)
    # The pipeline's own fence takes one token, then the fallback the direct one's.
    secrets_reset = itertools.chain([TOKENS[2]], itertools.cycle(TOKENS))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(secrets, "token_hex", lambda _n: next(secrets_reset))
        result = run(commit=None)
    assert fallback_transport.requests == direct_transport.requests
    assert [h.title for h in result.hypotheses] == [O1["title"]]
    assert result.notes[0] == "idea pipeline: no code context"
    assert all(run.requests(role) == [] for role in ("lane", "leap", "reviewer"))


def test_no_readable_file_delegates_too_and_no_fallback_returns_nothing() -> None:
    elsewhere = tuple(
        h.model_copy(update={"file_path": "pkg/gone.py"}) for h in HOTSPOTS
    )
    result = _Run()(hotspots=elsewhere)
    assert result.hypotheses == ()
    assert _noted(result.notes, "pkg/gone.py: not tracked at the base commit")
    assert "idea pipeline: no code context" in result.notes
    assert _Run(reader=None)().notes == ("idea pipeline: no code context",)


def test_a_second_call_sends_s1_only_with_the_earlier_titles_on_the_table() -> None:
    run = _Run(lane=[_ideas(O2)])
    result = run(call_index=1, avoid_titles=(str(O1["title"]),))
    (s1,) = run.requests("lane")
    assert json.dumps(O1["title"]) in _texts(s1)[1]
    assert run.requests("leap") == [] and run.requests("reviewer") == []
    assert [h.title for h in result.hypotheses] == [O2["title"]]
    assert _noted(result.notes, "second generator call: S1 only")


def test_a_skipped_leap_sends_no_leap_request() -> None:
    cfg = BASE.model_copy(update={"IDEAS_LEAP_N": 0})
    review = _review(*[(i, "feasible", "none") for i in (
        "obvious-01", "obvious-02", "obvious-03", "eliminate-01",
        "assume_less-01", "name_the_problem-01", "recombine-01")])  # fmt: skip
    run = _Run(lane=[S1_REPLY, *_lens_replies()], reviewer=[review], cfg=cfg)
    result = run()
    assert run.requests("leap") == []
    assert result.stats is not None
    assert Lane.leap not in result.stats.ideas_per_lane


# --------------------------------------------------------------------------
# Rotation, techniques, the novel bound
# --------------------------------------------------------------------------


def _example_blocks(run: _Run) -> list[str]:
    texts = [_texts(r)[1] for r in (*run.requests("lane")[1:], *run.requests("leap"))]
    return [t[t.index("<examples") :] for t in texts]


def test_the_same_run_id_gives_the_same_rotation_and_examples_on_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = _full(), _full()
    one = first()
    _reset_tokens(monkeypatch)
    two = second()
    assert [h.title for h in one.hypotheses] == [h.title for h in two.hypotheses]
    assert _example_blocks(first) == _example_blocks(second)
    assert first.requests("lane") == second.requests("lane")


def test_without_a_run_id_the_seed_is_the_commit_and_the_project() -> None:
    picks = [
        TITLE_OF[lane]
        for lane in rotation(f"{SHA}:{PROJECT.id}", LANES_ALL)
        if lane in TITLE_OF
    ]
    result = _full()(run_id=None)
    assert [h.title for h in result.hypotheses][1:3] == picks[:2]


TECHNIQUES = (
    Technique(
        id="t-set",
        slug="set-membership",
        name="Set membership",
        summary="Use a set for membership tests.",
        change_class=ChangeClass.behaviour,
        expected_gain=0.3,
        provability=0.8,
        risk=0.1,
    ),
)


def test_a_named_technique_sets_the_source_and_raises_the_class() -> None:
    playbook = _idea("Apply set membership", "parse_tokens", slug="set-membership")
    unknown = _idea("Apply a made-up trick", "count_words", slug="made-up",
                    cells=("representation:compact",))  # fmt: skip
    run = _Run(lane=[_ideas(playbook, unknown)])
    result = run(call_index=1, techniques=TECHNIQUES)
    first, second = result.hypotheses
    assert first.source is HypothesisSource.playbook
    assert first.technique_id == "t-set"
    assert first.change_class is ChangeClass.behaviour
    assert second.source is HypothesisSource.novel
    assert second.technique_id is None
    assert _noted(result.notes, "'Apply a made-up trick' names 'made-up'")
    assert json.dumps("Set membership") in _texts(run.requests("lane")[0])[1]


def test_lesson_and_avoided_titles_are_not_non_obvious() -> None:
    lesson = Lesson(
        project_id="p1",
        outcome=VerdictOutcome.reject,
        text=f"runtime -> {TITLE_OF[Lane.eliminate]}: reject",
    )
    run = _Run(lane=[S1_REPLY, *_lens_replies()], leap=[LEAP], reviewer=[REVIEW])
    result = run(lessons=(lesson,))
    assert TITLE_OF[Lane.eliminate] not in [h.title for h in result.hypotheses]
    assert any(e.data.get("reason") == "lesson_title" for e in result.events)


def test_novel_ideas_after_the_portfolio_are_bounded_by_the_totals() -> None:
    cfg = BASE.model_copy(update={"IDEAS_REVIEW": False, "IDEAS_PORTFOLIO_MAX": 3})
    mechanisms = ("remove_work", "batching", "lazy_or_streaming", "other")
    novel = {
        lane: [
            _idea(f"{lane.value} novel {fn} {mech}", fn, mechanism=mech,
                  cells=("work:defer",), change_class="novel")
            for fn in FUNCTIONS[:2] for mech in mechanisms[i % 2 :: 2]
        ]
        for i, lane in enumerate(LENS_LANES)
    }  # fmt: skip
    replies = [_ideas(*novel[lane]) for lane in LENS_LANES]
    run = _Run(lane=[_ideas(O1), *replies], leap=[_ideas(model=OPUS)], cfg=cfg)
    result = run(n=1)
    assert len(result.hypotheses) == 1 + 3
    assert result.hypotheses[0].title == O1["title"]
    assert all(h.change_class is ChangeClass.novel for h in result.hypotheses[1:])
    assert _noted(result.notes, "novel idea(s) past the result's bound of 4 dropped")


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------


def test_construction_refuses_a_missing_or_miswired_role() -> None:
    lane = ScriptedTransport([], cfg=role_settings(BASE, "lane"))
    leap = ScriptedTransport([], cfg=role_settings(BASE, "leap"))
    reviewer = ScriptedTransport([], cfg=role_settings(BASE, "reviewer"))
    with pytest.raises(ValueError, match="needs a reviewer transport"):
        IdeaPipelineGenerator({"lane": lane, "leap": leap}, config=BASE)
    with pytest.raises(ValueError, match="the leap transport bills"):
        IdeaPipelineGenerator(
            {"lane": lane, "leap": lane, "reviewer": reviewer}, config=BASE
        )
    bad = BASE.model_copy(update={"IDEAS_LANE_EFFORT": "turbo"})
    with pytest.raises(ValueError, match="effort must be one of"):
        IdeaPipelineGenerator(
            {"lane": lane, "leap": leap, "reviewer": reviewer}, config=bad
        )


def test_ideas_the_reviewer_may_not_be_shown_are_dropped_unsent() -> None:
    spaced = {**O1, "change_summary": "Close the block: < /hypothesis and go on."}
    empty = _ideas()
    run = _Run(lane=[_ideas(spaced), *[empty] * 6], leap=[_ideas(model=OPUS)])
    result = run()
    assert run.requests("reviewer") == []
    assert result.hypotheses == ()
    assert _noted(result.notes, "dropped before review: it holds a tag shape")
    assert _noted(result.notes, "not reviewed (no idea could be shown to the reviewer)")
