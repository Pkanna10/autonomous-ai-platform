"""Offline guards of the ideas-probe suite (V7, ``ideas_probe.py``).

Not ``live``: these spend nothing. They prove, before a dollar goes to
``test_ideas_probe_live.py``, that each arm's cap is the E1 row's sum of
worst cases (spec amendment section 6), the three dispatches' needs (E0b
count mode, E1, E1b on recorded facts) and their ci.yml lines, the strict
knobs, D58's models and efforts per arm, the retention flag only for arm D
on a pinned OSS library (D63, O15), count mode's two sent requests, the
auditor (the reviewer prompt on Opus 5.5 high over the pooled ideas), the
rows and replies on the results file, and the facts round trip through a
fresh clone.

Fakes and what they stand for: ``dg.Wire`` for the Messages API (the live
run's captured ``AnthropicTransport``: counts are a fixed 900 tokens);
``_Reader`` for the project's git objects (``factory.repo_reader``'s
``GitWorkspace``); ``og.LOCAL`` and a ``file://`` bare upstream for GitHub
over https (``oss.PRODUCTION``). What only a live run proves: the real
counts against D55's bounds, cache reads, the models' replies.
"""

from __future__ import annotations

import ast
import dataclasses
import itertools
import json
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx2
import pytest

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.common.config import Role, Settings, role_chain, settings
from autonomous_ai_agents.common.errors import LLMRequestError
from autonomous_ai_agents.common.models import (
    Direction,
    Hotspot,
    Objective,
    ObjectiveKind,
    Project,
)
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.optimization.idea_review import (
    REVIEW_SYSTEM_PROMPT,
    review_request,
)
from autonomous_ai_agents.optimization.idea_types import (
    LENS_LANES,
    Mechanism,
    MorphCell,
)
from autonomous_ai_agents.orchestrator.factory import repo_reader

from . import discovery_ab as ab
from . import ideas_probe as ip
from . import oss
from . import test_discovery_guards as dg
from . import test_oss_guards as og
from .conftest import TESTS_DIR, LiveRun, StartLive
from .discovery import FABLE, OPUS, SONNET, RepoFacts, ceil_usd, worst_usd
from .discovery_io import ResultsSink
from .discovery_oss import (
    OSS_BLIND_PROMPT_BOUND,
    OSS_PHASE_ONE_WORST_USD,
    OSS_SELECTABLE,
)
from .oss import OSS_CORPUS
from .test_corpus_guards import EXPERIMENT_MINUTES, _ci_block, _run_script

dry = dg.dry
upstream = og.upstream

Json = dict[str, Any]
HAIKU = "claude-haiku-5-5"
LIVE_DIR = TESTS_DIR / "live"
SHA = "0123456789abcdef0123456789abcdef01234567"
# The E1 row (spec amendment section 6), per pipeline call and per library:
# the spec's E1 row re-derived by E0b (D61) on its measured prompt maxima.
E1_ROW = {"B": 1.99, "C": 2.475, "D": 4.53, "E": 1.04525, "auditor": 0.69}
# The row's caps, independent of the needs (E1's whole plan needs 8 x 11.40).
E1_CAP = 92.0  # the E1 cap re-derived from E0b, recorded in STATUS D61 (was 90)
E1B_CAP = 20.0
TABLE = {"default": 46, "count": 9, "C-low,C-high": 20}  # the ci.yml needs
# E1 runs four libraries a dispatch (4 x 56 = 224 of the 240-minute job)
E1_DISPATCH = "pyparsing,tomli,mistune,idna"

SOURCE = '''"""Number tools."""


def slow_sum(values):
    total = 0
    for value in values:
        total = total + abs(value)
    return total


def slow_join(parts):
    text = ""
    for part in parts:
        text = text + str(part).strip()
    return text
'''
PATH = "pkg/text.py"
QUOTES = {
    "slow_sum": "total = total + abs(value)",
    "slow_join": "text = text + str(part).strip()",
}
LIB = OSS_CORPUS[8]  # tomli, a pinned OSS library


def _base() -> Settings:
    """One lane worker (replies in request order), no retries; the key the
    ``dry`` fixture set."""
    return Settings.model_validate(
        {"IDEAS_LANE_WORKERS": 1, "LLM_MAX_RETRIES": 0, "ENGINE_FALLBACKS": False}
    )


# ---------------------------------------------------------------------------
# Caps, needs and the plan
# ---------------------------------------------------------------------------


def test_each_arm_worst_case_is_the_e1_rows_sum_of_its_roles() -> None:
    """D55's bounds and the prices: S1 and six lenses on the lane model, the
    leap and the reviewer; arm A today's generator on the OSS blind bound.
    The bounds are discovery_ab's (one source, re-derived from E0b, D61)."""
    assert (ip.LANE_PROMPT_BOUND, ip.REVIEW_PROMPT_BOUND) == (38_000, 44_000)
    assert (ip.LANE_PROMPT_BOUND, ip.REVIEW_PROMPT_BOUND) == (
        ab.IDEAS_LANE_PROMPT_BOUND,
        ab.IDEAS_REVIEW_PROMPT_BOUND,
    )
    source = (LIVE_DIR / "ideas_probe.py").read_text(encoding="utf-8")
    assert "38_000" not in source and "44_000" not in source
    lane = ip.request_usd(ip.LANE_PROMPT_BOUND, 12_000, SONNET)
    assert lane == pytest.approx(0.215)
    assert ip.request_usd(ip.LANE_PROMPT_BOUND, 12_000, OPUS) == pytest.approx(0.43)
    assert ip.request_usd(ip.REVIEW_PROMPT_BOUND, 16_000, OPUS) == pytest.approx(0.54)
    for arm in (ip.ARM_B, ip.ARM_C, ip.ARM_D, ip.ARM_E):
        assert ip.arm_usd(arm) == pytest.approx(E1_ROW[arm.key], abs=5e-3), arm
    assert ip.arm_usd(ip.ARM_C_LOW) == ip.arm_usd(ip.ARM_C_HIGH) == ip.arm_usd(ip.ARM_C)
    assert ip.AUDIT_USD == pytest.approx(E1_ROW["auditor"])
    # Arm A: the spec's 0.18 assumed a 6,000-token prompt; the OSS blind
    # bound the oss-ab suite measured is the real worst case.
    today = worst_usd(OSS_BLIND_PROMPT_BOUND, settings.GENERATOR_MAX_TOKENS, SONNET)
    assert ip.arm_usd(ip.ARM_A) == today == pytest.approx(0.26955)
    assert ip.arm_usd(ip.ARM_COUNT) == pytest.approx(ip.COUNT_SENT * lane) == 0.43


def test_the_three_dispatches_need_their_table_entries_within_the_row_caps() -> None:
    whole = ip.ProbePlan(ip.E1_ARMS, _repos(ip.E1_REPOS))
    e1 = ip.probe_plan({ip.REPOS_ENV: E1_DISPATCH})
    per_library = ceil_usd(
        OSS_PHASE_ONE_WORST_USD + sum(ip.arm_usd(a) for a in ip.E1_ARMS) + ip.AUDIT_USD
    )
    assert e1.library_cap() == whole.library_cap() == per_library == 11.40
    assert ip.probe_need(whole) == pytest.approx(8 * per_library)
    assert ip.probe_need(whole) <= E1_CAP
    assert ip.probe_need(e1) == pytest.approx(4 * per_library)
    count = ip.probe_plan({ip.ARMS_ENV: "count"})
    assert count.library_cap() == ceil_usd(OSS_PHASE_ONE_WORST_USD + 0.43) == 0.85
    assert ip.probe_need(count) == pytest.approx(8.5)
    e1b = ip.ProbePlan((ip.ARM_C_LOW, ip.ARM_C_HIGH), _repos(ip.E1B_REPOS), Path("f"))
    assert not e1b.audit and e1b.library_cap() == ceil_usd(2 * 2.475) == 4.95
    assert ip.probe_need(e1b) == 19.8 <= E1B_CAP
    for plan, key in ((e1, "default"), (count, "count")):
        assert ip.probe_need(plan) <= TABLE[key] < ip.probe_need(plan) + 1
    assert ip.probe_need(e1b) <= TABLE["C-low,C-high"] < ip.probe_need(e1b) + 1


def _repos(names: Sequence[str]) -> tuple[oss.OssRepo, ...]:
    return tuple(r for r in OSS_SELECTABLE if r.name in names)


def test_the_defaults_follow_the_pre_registered_runs() -> None:
    """Unset: E1 (arms A-E, its eight libraries, one auditor pass), which a
    dispatch runs four libraries at a time; count alone: E0b on the ten OSS
    libraries; the effort variants alone: E1b."""
    arms = ip.probe_arms({})
    assert arms == ip.E1_ARMS == (ip.ARM_A, ip.ARM_B, ip.ARM_C, ip.ARM_D, ip.ARM_E)
    assert [r.name for r in ip.probe_repos({}, arms)] == [
        r.name for r in OSS_SELECTABLE if r.name in ip.E1_REPOS
    ]
    e1 = ip.probe_plan({ip.REPOS_ENV: E1_DISPATCH})
    assert [r.name for r in e1.repos] == ["mistune", "pyparsing", "idna", "tomli"]
    assert len(ip.E1_REPOS) == 8 and e1.audit and e1.facts is None
    assert set(ip.E1_REPOS) == {
        "more_itertools", "pyparsing", "tomli", "sortedcontainers",
        "mistune", "sqlparse", "markdown", "idna",
    }  # fmt: skip
    count = ip.probe_plan({ip.ARMS_ENV: "count"})
    assert count.arms == (ip.ARM_COUNT,) and count.repos == OSS_CORPUS
    assert not count.audit
    e1b = ip.probe_arms({ip.ARMS_ENV: "C-high,C-low"})
    assert e1b == (ip.ARM_C_LOW, ip.ARM_C_HIGH)
    assert ip.probe_repos({}, e1b) == _repos(ip.E1B_REPOS) and len(ip.E1B_REPOS) == 4
    mixed = ip.probe_plan({ip.ARMS_ENV: "C,C-low", ip.REPOS_ENV: "idna"})
    assert mixed.audit and [r.name for r in mixed.repos] == ["idna"]


@pytest.mark.parametrize(
    ("env", "match"),
    [
        ({ip.ARMS_ENV: "a"}, "distinct entries"),
        ({ip.ARMS_ENV: "A,A"}, "distinct entries"),
        ({ip.ARMS_ENV: ""}, "distinct entries"),
        ({ip.ARMS_ENV: "F"}, "distinct entries"),
        ({ip.ARMS_ENV: "count,C"}, "count runs alone"),
        ({ip.REPOS_ENV: "requests"}, "distinct entries"),
        ({ip.FACTS_ENV: "tests/fixtures/ideas_probe/none.jsonl"}, "no recorded facts"),
        ({ip.REPOS_ENV: ",".join(r.name for r in OSS_SELECTABLE)}, "ceiling"),
    ],
)
def test_knobs_parse_strictly_before_any_spend(env: dict[str, str], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        ip.probe_plan(env)


def test_a_plan_past_the_jobs_minutes_is_refused_before_any_spend() -> None:
    """D55's stages run in order, about ``STAGE_MINUTES`` each (kept until
    E1's recorded seconds re-pin it: E0b timed only count mode's Sonnet
    sends), phase 1 ``PHASE_ONE_MINUTES`` (E0b: a count-mode library about
    47 s): E1 56 minutes a library (phase 1, A, four pipeline calls of S1,
    two lens rounds on four workers and the reviewer, the auditor), so four
    a 240-minute dispatch (224), five refused (280); E0b's ten at 8, E1b's
    four at 25 on recorded facts."""
    assert ip.JOB_MINUTES == 240 and ip.STAGE_MINUTES == 3
    assert ip.PHASE_ONE_MINUTES == 2
    assert [ip.arm_stages(a) for a in ip.E1_ARMS] == [1, 4, 4, 4, 4]
    assert ip.arm_stages(ip.ARM_COUNT) == ip.COUNT_SENT == 2
    assert ip.ProbePlan(ip.E1_ARMS, _repos(("tomli",))).library_minutes() == 56
    assert ip.probe_plan({ip.REPOS_ENV: E1_DISPATCH}).minutes() == 4 * 56 == 224
    assert ip.probe_plan({ip.ARMS_ENV: "count"}).minutes() == 10 * 8
    e1b = ip.ProbePlan((ip.ARM_C_LOW, ip.ARM_C_HIGH), _repos(ip.E1B_REPOS), Path("f"))
    assert e1b.library_minutes() == 25 and e1b.minutes() == 100
    five = ",".join(ip.E1_REPOS[:5])
    for env in ({}, {ip.REPOS_ENV: five}):
        with pytest.raises(ValueError, match="past the 240-minute job"):
            ip.probe_plan(env)
    assert ip.ProbePlan(ip.E1_ARMS, _repos(ip.E1_REPOS[:5])).minutes() == 280
    assert ip.ProbePlan(ip.E1_ARMS, _repos(ip.E1_REPOS[:7])).minutes() == 392
    assert ip.probe_plan({ip.REPOS_ENV: "idna"}).minutes() == 56


def test_recorded_facts_resolve_against_the_service_directory(tmp_path: Path) -> None:
    facts = tmp_path / "facts.jsonl"
    facts.write_text("", encoding="utf-8")
    one = {ip.REPOS_ENV: "tomli"}
    assert ip.probe_plan({**one, ip.FACTS_ENV: str(facts)}).facts == facts
    relative = os.path.relpath(facts, ip.SERVICE_DIR)
    found = ip.probe_plan({**one, ip.FACTS_ENV: relative}).facts
    assert found == ip.SERVICE_DIR / relative
    plan = ip.probe_plan({ip.FACTS_ENV: str(facts), ip.ARMS_ENV: "C-low,C-high"})
    assert plan.library_cap() == 4.95  # no phase 1 on recorded facts


# ---------------------------------------------------------------------------
# Arms: D58's models and efforts, the retention flag (D63, O15)
# ---------------------------------------------------------------------------

D58: dict[str, dict[Role, tuple[str, str, int]]] = {  # per arm and role
    "B": {"lane": (SONNET, "medium", 12_000), "leap": (SONNET, "high", 12_000),
          "reviewer": (SONNET, "high", 16_000)},
    "C": {"lane": (SONNET, "medium", 12_000), "leap": (OPUS, "high", 12_000),
          "reviewer": (OPUS, "high", 16_000)},
    "D": {"lane": (SONNET, "medium", 12_000), "leap": (FABLE, "high", 20_000),
          "reviewer": (FABLE, "high", 20_000)},
    "E": {"lane": (HAIKU, "medium", 12_000), "leap": (OPUS, "high", 12_000),
          "reviewer": (OPUS, "high", 16_000)},
    "C-low": {"lane": (SONNET, "low", 12_000)},
    "C-high": {"lane": (SONNET, "high", 12_000)},
}  # fmt: skip
TOKENS = {"lane": "IDEAS_LANE", "leap": "IDEAS_LEAP", "reviewer": "IDEAS_REVIEWER"}


def _project(name: str = LIB.name) -> Project:
    return Project(id="p1", name=name, root_path="/srv/lib")


@pytest.mark.parametrize("arm", ip.IDEA_ARMS, ids=[a.key for a in ip.IDEA_ARMS])
def test_each_arm_runs_its_roles_on_d58s_models_and_efforts(arm: ip.IdeaArm) -> None:
    cfg = ip.arm_config(arm, _project())
    assert cfg.IDEA_PIPELINE is arm.pipeline
    assert cfg.ALLOW_RETENTION_MODELS is (arm is ip.ARM_D)
    for role, (model, effort, tokens) in D58.get(arm.key, {}).items():
        prefix = TOKENS[role]
        assert role_chain(cfg, role) == (model,), (arm.key, role)
        assert getattr(cfg, f"{prefix}_EFFORT") == effort, (arm.key, role)
        assert getattr(cfg, f"{prefix}_MAX_TOKENS") == tokens, (arm.key, role)
    if arm is ip.ARM_A:
        assert role_chain(cfg, "generator") == (SONNET,)
    assert (cfg.IDEAS_LANE_WORKERS == 1) is (arm is ip.ARM_COUNT)
    assert cfg.IDEAS_LENSES == LENS_LANES and cfg.IDEAS_LEAP_N == 3


def test_the_retention_flag_is_set_only_for_arm_d_on_a_pinned_oss_library() -> None:
    for name in ("blockhash", "private-app", "tomli2"):  # a fixture, any other
        with pytest.raises(ValueError, match=r"pinned OSS library \(O15\)"):
            ip.arm_config(ip.ARM_D, _project(name))
    for repo in OSS_SELECTABLE:
        assert ip.arm_config(ip.ARM_D, _project(repo.name)).ALLOW_RETENTION_MODELS
    carried = settings.model_copy(update={"ALLOW_RETENTION_MODELS": True})
    for arm in ip.IDEA_ARMS:
        if arm is not ip.ARM_D:
            cfg = ip.arm_config(arm, _project("private-app"), carried)
            assert cfg.ALLOW_RETENTION_MODELS is False, arm.key  # never carried


# ---------------------------------------------------------------------------
# One arm on the wire: count mode, a full pipeline, today's generator
# ---------------------------------------------------------------------------


class _Reader:
    def ls_tree(self, commit: str) -> tuple[str, ...]:
        if commit != SHA:
            raise GitError("unknown commit")
        return (PATH,)

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        data = SOURCE.encode()
        return data if limit is None else data[:limit]


def _reader(_project: Project) -> _Reader:
    return _Reader()


def _facts(project: Project | None = None) -> ip.IdeaFacts:
    project = project or _project()
    spots = tuple(
        Hotspot(
            id=f"h-{name}",
            project_id=project.id,
            workload_id="w1",
            file_path=PATH,
            symbol=name,
            self_time_s=1.0,
            total_time_s=2.0,
            share=0.4,
        )  # fmt: skip
        for name in QUOTES
    )
    objective = Objective(
        project_id=project.id,
        kind=ObjectiveKind.runtime,
        metric="wall_time_s",
        direction=Direction.minimize,
        min_relative_gain=0.02,
        description="make the number tools faster",
    )
    return ip.IdeaFacts(RepoFacts(project, None, spots, objective), SHA, "run-1", ())


_MECHANISMS = [m.value for m in Mechanism if m is not Mechanism.other]
_CELLS = [c.value for c in MorphCell]
_SHOWN_ID = re.compile(r'"id": "([a-z_]+-\d+|i\d+)"')


def _lane_idea(k: int) -> Json:
    symbol = list(QUOTES)[k % 2]
    return {
        "title": f"Idea {k}: rework {symbol}",
        "technique_slug": None,
        "hotspots": [{"file_path": PATH, "symbol": symbol}],
        "change_summary": f"Change {symbol} as the title says.",
        "justification_summary": f"{symbol} holds 40 % of the time.",
        "depends_on_path": PATH,
        "depends_on_quote": QUOTES[symbol],
        "precondition": "the inputs are plain numbers",
        "equivalence_summary": "the same values come out",
        "mechanism": _MECHANISMS[k % len(_MECHANISMS)],
        "morph_cells": [_CELLS[k % len(_CELLS)]],
        "tier": "combinational",
        "typicality": "uncommon",
        "change_class": "efficiency",
        "expected_gain": 0.2,
        "provability": 0.8,
        "risk": 0.1,
    }


def _today_idea(k: int) -> Json:
    return {
        "title": f"Today {k}",
        "technique_slug": None,
        "hotspots": [{"file_path": PATH, "symbol": "slow_sum"}],
        "change_summary": "Sum with the builtin.",
        "justification_summary": "slow_sum dominates.",
        "change_class": "efficiency",
        "expected_gain": 0.3,
        "provability": 0.8,
        "risk": 0.1,
    }


def _text(body: Json) -> str:
    content = body["messages"][0]["content"]
    blocks = [content] if isinstance(content, str) else [b["text"] for b in content]
    return "\n".join(blocks)


class _Answers:
    """Lane requests get one new idea each, today's generator two, a review
    every shown id feasible but the first lens idea (``remove``) and any
    id in ``twice`` reviewed twice."""

    def __init__(
        self, remove: bool = True, twice: Sequence[str] = (), *, empty: bool = False
    ) -> None:
        self.lanes = itertools.count()
        self.remove, self.twice, self.empty = remove, tuple(twice), empty

    def __call__(self, body: Json) -> str:
        text = _text(body)
        if "reviews" in dg._schema_keys(body):
            block = text.split("The review boundary token is", 1)[1]
            ids = list(dict.fromkeys(_SHOWN_ID.findall(block)))
            lens = [i for i in ids if not i.startswith("obvious")]
            first = lens[0] if lens and self.remove else None
            out = [_review(i, i == first) for i in ids]
            out += [_review(i, True) for i in self.twice]
            return json.dumps({"reviews": out})
        if "depends_on_quote" in json.dumps(body["output_config"]):
            ideas = [] if self.empty else [_lane_idea(next(self.lanes))]
            return json.dumps({"hypotheses": ideas})
        return json.dumps({"hypotheses": [_today_idea(0), _today_idea(1)]})


def _review(idea: str, infeasible: bool) -> Json:
    return {
        "idea": idea,
        "verdict": "infeasible" if infeasible else "feasible",
        "reason": "precondition_false" if infeasible else "none",
        "duplicate_of": None,
        "change_plan": "" if infeasible else f"Edit {idea} in turn.",
    }


CACHED: Json = {
    "input_tokens": 300,
    "output_tokens": 200,
    "cache_read_input_tokens": 700,
}


def _arm(
    arm: ip.IdeaArm, *, answers: _Answers | None = None, cap: float = 9.0
) -> tuple[ip.ArmRun, dg.Wire, LiveRun]:
    wire = dg.Wire(answers or _Answers(), usages=[CACHED] * 12)
    run = wire.run(cap=cap)
    return ip.run_arm(arm, run, _facts(), base=_base(), reader=_reader), wire, run


def test_count_mode_sends_s1_and_the_first_lens_and_counts_every_stage(
    dry: Path,
) -> None:
    found, wire, run = _arm(ip.ARM_COUNT)
    assert len(wire.bodies) == ip.COUNT_SENT == 2 and len(run.records) == 2
    labels = [e.label for e in found.exchanges]
    assert labels == [
        "obvious",
        *(lane.value for lane in LENS_LANES),
        "leap",
        "reviewer",
        "reviewer-16",
    ]
    sent = [e.label for e in found.exchanges if e.sent]
    assert sent == ["obvious", LENS_LANES[0].value]
    # E0b's reviewer bound is for 16 ideas: S1 and one lens give two here, so
    # the counted reviewer request is repeated under fresh ids up to 16
    reviewer, full = found.exchanges[-2:]
    shown = ip.shown_ideas(reviewer.request)
    padded = ip.shown_ideas(full.request)
    assert len(shown) == 2 and len(padded) == settings.IDEAS_REVIEW_MAX_IDEAS == 16
    assert len({i.id for i in padded}) == 16 and padded[:2] == shown
    assert {i.title for i in padded} == {i.title for i in shown}
    assert full.request.max_tokens == reviewer.request.max_tokens
    assert _text_of(full.request).startswith(_text_of(reviewer.request).split(
        "The review boundary token is")[0])  # fmt: skip
    assert not full.sent and full.counted > 900
    assert all(e.counted > 900 for e in found.exchanges)  # margin and allowance
    assert found.error is None and found.result is not None
    assert run.spent_usd <= ip.arm_usd(ip.ARM_COUNT)
    obvious = found.exchanges[0]
    assert (obvious.stop_reason, obvious.usage[2], obvious.reply) == (
        "end_turn", 700, json.dumps({"hypotheses": [_lane_idea(0)]}),
    )  # fmt: skip
    assert found.exchanges[-1].stop_reason is None and not found.exchanges[-1].reply
    ip.check_spend(run, [found], None)
    record = ip._reply("tomli", "count", found.exchanges[-1])
    assert (record["shown"], record["sent"], record["seconds"]) == (16, False, 0.0)
    assert ip._reply("tomli", "count", obvious)["shown"] == 0


def _text_of(request: object) -> str:
    return ip._request_text(request)  # type: ignore[arg-type]


def test_count_mode_counts_no_padded_reviewer_when_no_idea_was_shown(
    dry: Path,
) -> None:
    found, wire, _run = _arm(ip.ARM_COUNT, answers=_Answers(empty=True))
    assert len(wire.bodies) == 2 and found.error is None
    assert "reviewer" not in [e.label for e in found.exchanges]
    assert ip.padded_review(found.exchanges[0].request, 16) is None  # a lane's


def test_count_mode_refuses_a_send_past_its_real_allowance(dry: Path) -> None:
    """A count above D55's lane bound cannot spend past count mode's cap:
    the tap refuses the send for nothing, the pipeline drops the lane."""
    wire = dg.Wire(_Answers())
    run = wire.run()
    lane = ip.Tap(
        run.transport(_base()), "lane", ("obvious",), sends=2, send_cap_usd=0.01
    )
    request = review_request(
        (), prefix="data", fence=Fence("aa" * 8), reviewer_fence=Fence("bb" * 8),
        max_ideas=1, max_tokens=12_000, effort=None, notes=[],
    )[0]  # fmt: skip
    lane.count_input_tokens(request)
    with pytest.raises(LLMRequestError, match="counted, not sent"):
        lane.send(request)
    assert wire.bodies == [] and lane.exchanges[0].sent is False


def test_a_pipeline_arm_bills_its_role_models_and_keeps_every_reply(dry: Path) -> None:
    found, wire, run = _arm(ip.ARM_C)
    assert found.error is None and found.result is not None
    stats = found.result.stats
    assert stats is not None and stats.cache_read_tokens == 700 * 9
    labels = [e.label for e in found.exchanges]
    assert labels == [
        "obvious",
        *(lane.value for lane in LENS_LANES),
        "leap",
        "reviewer",
    ]
    assert all(e.sent and e.reply for e in found.exchanges)
    models = [b["model"] for b in wire.bodies]
    assert models == [SONNET] * 7 + [OPUS, OPUS]
    assert set(found.models) == set(found.billable) == {SONNET, OPUS}
    efforts = [b["output_config"]["effort"] for b in wire.bodies]
    assert efforts == ["medium"] * 7 + ["high", "high"]
    lanes = [h for h in found.result.hypotheses if "lane:obvious" not in h.tags]
    assert 3 <= len(lanes) <= 5  # the portfolio
    ip.check_spend(run, [found], None)


def test_arm_a_is_todays_generator_on_its_own_schema(dry: Path) -> None:
    found, wire, _run = _arm(ip.ARM_A)
    (body,) = wire.bodies
    assert body["model"] == SONNET and body["max_tokens"] == 16_000
    assert body["output_config"]["effort"] == "medium"
    assert "depends_on_quote" not in json.dumps(body["output_config"])
    assert found.result is not None and found.result.stats is None
    assert [h.title for h in found.result.hypotheses] == ["Today 0", "Today 1"]
    assert [e.label for e in found.exchanges] == ["generator"]


def test_a_failed_arm_is_recorded_with_its_error(dry: Path) -> None:
    wire = dg.Wire(_Answers())
    run = wire.run()
    found = ip.run_arm(ip.ARM_A, run, _facts(), base=_base(), reader=_reader, cap=1e-9)
    assert found.result is None and found.error is not None
    assert found.error.startswith("BudgetExceeded") and wire.bodies == []


# ---------------------------------------------------------------------------
# The auditor and the scores
# ---------------------------------------------------------------------------


def test_the_auditor_reviews_the_pooled_ideas_on_opus_high(dry: Path) -> None:
    c_run, _, _ = _arm(ip.ARM_C)
    a_run, _, _ = _arm(ip.ARM_A)
    pooled = ip.pool([a_run, c_run], _facts())
    assert {p.arm for p in pooled} == {"A", "C"} and len(pooled) <= ip.AUDIT_MAX_IDEAS
    tiers = [ip.tier(p) for p in pooled]
    assert tiers == sorted(tiers) and tiers[0] == 0
    removed = [p for p in pooled if p.own == "infeasible"]
    assert len(removed) == 1 and not removed[0].in_result
    wire = dg.Wire(_Answers(remove=False, twice=("i01",)))
    run = wire.run()
    audit = ip.run_audit(pooled, run, _facts(), base=_base(), reader=_reader)
    (body,) = wire.bodies
    assert body["system"][0]["text"] == REVIEW_SYSTEM_PROMPT
    assert body["model"] == OPUS and body["max_tokens"] == ip.AUDIT_MAX_TOKENS
    assert body["output_config"]["effort"] == "high"
    ids = list(
        dict.fromkeys(_SHOWN_ID.findall(_text(body).split("review boundary")[1]))
    )
    assert sorted(ids) == [f"i{k:02d}" for k in range(1, len(pooled) + 1)]  # neutral
    assert "Today 0" in _text(body) and "lane: obvious" not in _text(body)
    assert audit.error is None and audit.verdicts[0] is None  # reviewed twice
    assert set(audit.verdicts[1:]) == {"feasible"}
    assert audit.cost_usd == run.spent_usd > 0
    scores = ip.scores([a_run, c_run], pooled, audit)
    assert scores["A"].good == 1  # "Today 1"; "Today 0" got two verdicts
    assert (
        scores["C"].good
        == scores["C"].non_obvious
        == len(
            [h for h in c_run.result.hypotheses if "lane:obvious" not in h.tags]  # type: ignore[union-attr]
        )
    )
    assert (scores["C"].own_removed, scores["C"].agreed) == (1, 0)


def test_a_failed_audit_scores_no_arm_and_records_its_error(
    dry: Path, tmp_path: Path
) -> None:
    """An unreadable (or refused, or unaffordable) auditor reply is no
    verdict: every E1 arm's good count is unknown, not 0, and the auditor's
    error is on each row, the note and the summary."""
    c_run, _, _ = _arm(ip.ARM_C)
    a_run, _, _ = _arm(ip.ARM_A)
    pooled = ip.pool([a_run, c_run], _facts())
    wire = dg.Wire(lambda _body: "no json here")
    run = wire.run()
    audit = ip.run_audit(pooled, run, _facts(), base=_base(), reader=_reader)
    assert audit.error is not None and audit.error.startswith("UnusableReplyError")
    assert set(audit.verdicts) == {None} and len(wire.bodies) == 1
    scored = ip.scores([a_run, c_run], pooled, audit)
    assert {k: s.good for k, s in scored.items()} == {"A": None, "C": None}
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(tmp_path / "r.jsonl")})
    plan = ip.ProbePlan((ip.ARM_A, ip.ARM_C), _repos(("tomli",)))
    recorder = ip.ProbeRecorder(plan, sink)
    recorder.record("tomli", [a_run, c_run], pooled, audit, run)
    assert [r.audit_error for r in recorder.rows] == [audit.error] * 2
    assert [r.good for r in recorder.rows] == [None, None]
    assert "audit failed: UnusableReplyError" in run.notes[-1]
    lines = (tmp_path / "r.jsonl").read_text("utf-8").splitlines()
    rows = [json.loads(x) for x in lines if f'"{ip.ROW_EXPERIMENT}"' in x]
    assert [r["audit_error"] for r in rows] == [audit.error] * 2
    echoed: list[str] = []
    recorder.finish(echoed.append)
    assert sum("audit" in line and "UnusableReplyError" in line for line in echoed) == 2
    clean = ip.scores([a_run, c_run], pooled, None)
    assert {k: s.good for k, s in clean.items()} == {"A": None, "C": None}


def test_the_pool_skips_failed_and_non_e1_arms_and_rows_need_no_audit(
    dry: Path,
) -> None:
    c_run, _, _ = _arm(ip.ARM_C)
    low = dataclasses.replace(c_run, arm=ip.ARM_C_LOW)  # E1b: not pooled
    failed = dataclasses.replace(c_run, arm=ip.ARM_B, result=None, error="X: y")
    assert ip.pool([low, failed], _facts()) == []
    assert ip.own_verdicts("not a review") == {}
    plain = dataclasses.replace(
        c_run.exchanges[0].request, messages=({"role": "user", "content": "hi"},)
    )
    assert ip._request_text(plain) == "hi" and ip.shown_ideas(plain) == []
    recorder = ip.ProbeRecorder(ip.ProbePlan((ip.ARM_C_LOW,), _repos(("tomli",))),
                                ResultsSink({}))  # fmt: skip
    echoed: list[str] = []
    recorder.finish(echoed.append)  # no row yet: no table
    assert echoed == []
    run = dg.Wire(_Answers()).run()
    recorder.record("tomli", [low, failed], [], None, run)
    assert [(r.good, r.audit_error, r.error) for r in recorder.rows] == [
        (None, None, None), (None, None, "X: y"),
    ]  # fmt: skip
    assert "audit" not in run.notes[-1]
    recorder.finish(echoed.append)
    assert any("| tomli | B |" in line and "X" in line for line in echoed)


def test_the_pool_keeps_scored_ideas_first_and_stops_at_48() -> None:
    def item(
        arm: str, k: int, *, result: bool, own: str | None, lane: str
    ) -> ip.Pooled:
        line = ip.ShownIdea(
            id=f"{lane}-{k:02d}", lane=lane, title=f"{arm} {k}", change_class="efficiency",
            anchor=f"{PATH}:slow_sum", change_summary="s", precondition="p",
            equivalence_summary="e", depends_on_path=PATH, depends_on_quote="q",
        )  # fmt: skip
        return ip.Pooled(arm, line, own, result)

    items = [
        item(arm, k, result=k < 5, own="infeasible" if k == 9 else None,
             lane="obvious" if k in (3, 4) else "far")
        for arm in "BCDE" for k in range(16)
    ]  # fmt: skip
    kept = ip.ranked(items)
    assert len(kept) == ip.AUDIT_MAX_IDEAS
    assert [ip.tier(p) for p in kept[:12]] == [0] * 12  # 3 lens results x 4 arms
    assert [p.arm for p in kept[:4]] == list("BCDE")  # round robin
    assert [ip.tier(p) for p in kept[12:16]] == [1] * 4  # the own removals next


# ---------------------------------------------------------------------------
# Facts: recorded, reloaded on a fresh clone
# ---------------------------------------------------------------------------


def test_facts_round_trip_through_the_results_file(tmp_path: Path) -> None:
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(tmp_path / "r.jsonl")})
    facts = _facts()
    sink.write({"experiment": "other", "repo": LIB.name})
    sink.write(facts.record())
    lines = (tmp_path / "r.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    assert record["experiment"] == ip.FACTS_EXPERIMENT and record["repo"] == LIB.name
    assert all(len(c) <= 500 for c in record["chunks"]) and len(record["chunks"]) > 1
    loaded = ip.load_facts(tmp_path / "r.jsonl")
    body = loaded[LIB.name]
    assert (body.commit, body.run_id, body.hotspots) == (
        SHA,
        "run-1",
        facts.facts.hotspots,
    )
    assert body.project == facts.facts.project
    sink.write(facts.record())
    with pytest.raises(ValueError, match="twice"):
        ip.load_facts(tmp_path / "r.jsonl")


def test_recorded_facts_rebind_to_a_fresh_clone_at_the_same_head(
    upstream: og.Upstream, tmp_path: Path
) -> None:
    url, commit = upstream({PATH: SOURCE, "LICENSE": "Permission is hereby granted\n"})
    repo = og._local_repo(url, commit, LIB)
    (tmp_path / "a").mkdir()
    first = oss.prepare_repo(repo, tmp_path / "a" / "user", policy=og.LOCAL)
    body = ip.FactsBody.of(_facts(repo.project(first.path)))
    body = body.model_copy(update={"commit": first.base})
    facts = ip.clone_facts(repo, body, tmp_path / "b" / "user", og.LOCAL)
    assert facts.facts.project.root_path == str(tmp_path / "b" / "user")
    assert facts.facts.project.id == body.project.id and facts.commit == first.base
    stale = body.model_copy(update={"commit": SHA})
    with pytest.raises(ValueError, match="not the recorded"):
        ip.clone_facts(repo, stale, tmp_path / "c" / "user", og.LOCAL)
    other = body.model_copy(update={"project": _project("idna")})
    with pytest.raises(ValueError, match="recorded for"):
        ip.clone_facts(repo, other, tmp_path / "d" / "user", og.LOCAL)


def test_a_recorder_on_recorded_facts_refuses_a_library_it_has_none_for(
    tmp_path: Path,
) -> None:
    path = tmp_path / "facts.jsonl"
    ResultsSink({"LIVE_RESULTS_PATH": str(path)}).write(_facts().record())
    plan = ip.ProbePlan((ip.ARM_C_LOW,), _repos(("tomli",)), path)
    assert set(ip.ProbeRecorder(plan, ResultsSink({})).recorded) == {"tomli"}
    with pytest.raises(ValueError, match="no recorded facts for idna"):
        ip.ProbeRecorder(replace_repos(plan, ("tomli", "idna")), ResultsSink({}))


def replace_repos(plan: ip.ProbePlan, names: Sequence[str]) -> ip.ProbePlan:
    return ip.ProbePlan(plan.arms, _repos(names), plan.facts)


# ---------------------------------------------------------------------------
# One library: rows, replies, notes and guards
# ---------------------------------------------------------------------------


def _starter(wire: dg.Wire) -> tuple[list[LiveRun], StartLive]:
    runs: list[LiveRun] = []

    def start(cap_usd: float) -> LiveRun:
        run = LiveRun(f"dry[{len(runs)}]", cap_usd, wire=httpx2.MockTransport(wire))
        runs.append(run)
        return run

    return runs, start


def test_one_library_on_recorded_facts_records_rows_replies_and_audit(
    upstream: og.Upstream, tmp_path: Path, dry: Path
) -> None:
    url, commit = upstream({PATH: SOURCE, "LICENSE": "Permission is hereby granted\n"})
    repo = og._local_repo(url, commit, LIB)
    (tmp_path / "rec").mkdir()
    head = oss.prepare_repo(repo, tmp_path / "rec" / "user", policy=og.LOCAL).base
    facts = _facts(repo.project(tmp_path / "rec" / "user"))
    record = ip.FactsBody.of(facts).model_copy(update={"commit": head})
    results = tmp_path / "results.jsonl"
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(results)})
    plan = ip.ProbePlan((ip.ARM_A, ip.ARM_C), (repo,), Path("recorded"))
    recorder = ip.ProbeRecorder(plan, sink, {repo.name: record})
    runs, start = _starter(dg.Wire(_Answers(), usages=[CACHED] * 20))
    ip.run_library(
        repo, live=start, root=tmp_path / "live", isolation=dg.REQUIRED,
        recorder=recorder, policy=og.LOCAL, base=_base(), reader=repo_reader,
    )  # fmt: skip
    (run,) = runs
    assert run.cap_usd == plan.library_cap()
    lines = [json.loads(line) for line in results.read_text("utf-8").splitlines()]
    kinds = [line["experiment"] for line in lines]
    assert kinds.count(ip.ROW_EXPERIMENT) == 2 and kinds.count(ip.FACTS_EXPERIMENT) == 0
    assert kinds.count(ip.REPLY_EXPERIMENT) == 1 + 9 + 1  # A, C's nine, the auditor
    rows = {
        line["arm"]: line for line in lines if line["experiment"] == ip.ROW_EXPERIMENT
    }
    assert rows["C"]["stats"]["cache_read_tokens"] == 700 * 9
    assert rows["C"]["stops"]["reviewer"] == "end_turn" and rows["A"]["stats"] is None
    assert rows["C"]["good"] >= 3 and rows["C"]["auditor_infeasible"] == 0
    # the auditor's first shown id (i01, arm A's first idea) is infeasible
    assert (rows["A"]["good"], rows["A"]["auditor_infeasible"]) == (1, 1)
    assert rows["C"]["counted"]["obvious"] > 900
    assert rows["A"]["audit_error"] is None is rows["C"]["audit_error"]
    replies = [line for line in lines if line["experiment"] == ip.REPLY_EXPERIMENT]
    assert all(r["seconds"] >= 0 for r in replies)
    shown = {(r["arm"], r["label"]): r["shown"] for r in replies}
    assert shown[("C", "reviewer")] > 0 and shown[("C", "obvious")] == 0
    assert shown[("auditor", "auditor")] == len(audits := [
        line for line in lines if line["experiment"] == ip.AUDIT_EXPERIMENT
    ])  # fmt: skip
    assert {a["arm"] for a in audits} == {"A", "C"}
    assert run.notes[0].startswith(f"IDEAS {repo.name}: A 2 idea(s)")
    assert all(len(note) <= ip.NOTE_CHARS for note in run.notes)
    assert recorder.rows and [r.arm for r in recorder.rows] == ["A", "C"]
    echoed: list[str] = []
    recorder.finish(echoed.append)
    assert any("| tomli | C |" in line for line in echoed)


def test_a_phase_one_failure_is_noted_on_its_run_then_raised(
    upstream: og.Upstream, tmp_path: Path, dry: Path
) -> None:
    url, commit = upstream()
    repo = og._local_repo(url, commit, LIB)  # file://: production refuses it
    recorder = ip.ProbeRecorder(
        ip.probe_plan({ip.REPOS_ENV: LIB.name}), ResultsSink({})
    )
    runs, start = _starter(dg.Wire(_Answers()))
    with pytest.raises(oss.CloneRefusedError):
        ip.run_library(
            repo, live=start, root=tmp_path, isolation=dg.REQUIRED, recorder=recorder
        )
    (run,) = runs
    assert run.records == [] and recorder.rows == []
    assert run.notes == [run.notes[0]]
    assert run.notes[0].startswith(f"IDEAS {LIB.name}: breach: CloneRefusedError: ")


def test_the_spend_guards_catch_a_foreign_model_and_an_overrun(dry: Path) -> None:
    found, _, run = _arm(ip.ARM_A)
    ip.check_spend(run, [found], None)
    foreign = dataclasses.replace(found, models=(OPUS,))
    with pytest.raises(AssertionError):
        ip.check_spend(run, [foreign], None)
    run.cap_usd = run.spent_usd / 2
    with pytest.raises(AssertionError):
        ip.check_spend(run, [found], None)


# ---------------------------------------------------------------------------
# The live module and ci.yml
# ---------------------------------------------------------------------------


def test_the_live_module_is_marked_parses_its_plan_first_and_runs_libraries() -> None:
    source = (LIVE_DIR / "test_ideas_probe_live.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    marks = [
        ast.unparse(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and [ast.unparse(t) for t in node.targets] == ["pytestmark"]
    ]
    assert marks == ["pytest.mark.live"]
    tests = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    ]
    assert [t.name for t in tests] == ["test_ideas_probe"]
    assert "live" in [a.arg for a in tests[0].args.args]
    assert '@pytest.fixture(scope="module")' in source
    assert "probe_plan(os.environ)" in source and "ProbeRecorder(" in source
    calls = {ast.unparse(n.func) for n in ast.walk(tests[0]) if isinstance(n, ast.Call)}
    assert "run_library" in calls and "live" not in calls
    assert "OSS_SELECTABLE, ids=[r.name for r in OSS_SELECTABLE]" in source


def _dispatch(
    tmp_path: Path,
    arms: str | None,
    cap: str,
    suite: str = "ideas-probe",
    repos: str | None = None,
) -> tuple[int, str, list[str]]:
    """The run step under bash -e with a fake ``uv`` that records the probe's
    exports; ``arms`` or ``repos`` ``None`` leaves the input unset (an older
    caller)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    called = tmp_path / "called.txt"
    fake = bin_dir / "uv"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" "${{LIVE_IDEAS_ARMS-unset}}" '
        f'"${{LIVE_IDEAS_FACTS-unset}}" "$LIVE_SUITE_CAP_USD" "${{PAIRED_TRIALS-unset}}"'
        f' "${{LIVE_IDEAS_REPOS-unset}}" > "{called}"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    script = tmp_path / "step.sh"
    script.write_text(_run_script(), encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin",
        "HOME": str(tmp_path),
        "ANTHROPIC_API_KEY": "placeholder-not-a-key",
        "INPUT_SUITE": suite,
        "INPUT_ENGINE_MODEL": "claude-opus-5-5",
        "INPUT_SUITE_CAP_USD": cap,
        "INPUT_MODE": "aimed",
        "INPUT_OSS_REPO": "",
        "INPUT_EDITOR_MODEL": "default",
        "INPUT_UPSTREAM_BATCH": "1",
        "LIVE_RESULTS_PATH": str(tmp_path / "results.jsonl"),
    }
    if arms is not None:
        env["INPUT_IDEAS_ARMS"] = arms
    if repos is not None:
        env["INPUT_IDEAS_REPOS"] = repos
    proc = subprocess.run(
        ["bash", "-e", str(script)], env=env, capture_output=True, text=True,
        timeout=120, check=False,
    )  # fmt: skip
    calls = called.read_text(encoding="utf-8").splitlines() if called.exists() else []
    return proc.returncode, proc.stdout + proc.stderr, calls


@pytest.mark.parametrize(
    ("arms", "repos", "need", "exported", "facts"),
    [
        (None, E1_DISPATCH, "46", "A,B,C,D,E", "unset"),
        ("A,B,C,D,E", E1_DISPATCH, "46", "A,B,C,D,E", "unset"),
        ("A,B,C,D,E", "idna", "12", "A,B,C,D,E", "unset"),
        ("count", None, "9", "count", "unset"),
        ("count", "", "9", "count", "unset"),
        ("count", "tomli,idna,mistune", "3", "count", "unset"),
        ("C-low,C-high", "", "20", "C-low,C-high", ip.FACTS_FIXTURE),
        ("C-low,C-high", "tomli,mistune", "10", "C-low,C-high", ip.FACTS_FIXTURE),
    ],
)
def test_the_ideas_inputs_set_the_arms_libraries_their_need_and_the_facts(
    arms: str | None,
    repos: str | None,
    need: str,
    exported: str,
    facts: str,
    tmp_path: Path,
) -> None:
    code, output, calls = _dispatch(tmp_path / "ok", arms, need, repos=repos)
    assert code == 0, output
    argv, got_arms, got_facts, cap, paired, got_repos = calls
    assert (
        argv
        == "run pytest tests/live/test_ideas_probe_live.py -m live --no-cov -n 0 -rA"
    )
    assert (got_arms, got_facts, cap, paired) == (exported, facts, need, "false")
    assert got_repos == (repos or "unset")
    # the shell's need is the module's own, rounded up
    env = {ip.ARMS_ENV: exported, **({ip.REPOS_ENV: repos} if repos else {})}
    plan = ip.ProbePlan(
        ip.probe_arms(env), ip.probe_repos(env, ip.probe_arms(env)),
        Path(facts) if facts != "unset" else None,
    )  # fmt: skip
    assert ip.probe_need(plan) <= int(need) < ip.probe_need(plan) + 1
    below = f"{int(need) - 1}.99"
    code, output, calls = _dispatch(tmp_path / "below", arms, below, repos=repos)
    assert (code, calls) == (1, []) and f"suite_cap_usd {below} is below" in output


def test_the_ideas_inputs_are_strict_and_for_the_probe_only(tmp_path: Path) -> None:
    block = _ci_block("      ideas_arms:", "\n\n")
    assert "type: choice" in block and "default: 'A,B,C,D,E'" in block
    assert "options: ['A,B,C,D,E', count, 'C-low,C-high']" in block
    repos = _ci_block("      ideas_repos:", "\n\n")
    assert "type: string" in repos and "default: ''" in repos
    for index, bad in enumerate(("", "A", "count;id", "C-low")):
        code, output, calls = _dispatch(tmp_path / f"bad-{index}", bad, "88", repos="x")
        assert (code, calls) == (1, []) and "unknown ideas_arms" in output, bad
    for index, bad in enumerate(("Tomli", "tomli,", "a;id", "tomli idna", ",")):
        code, output, calls = _dispatch(
            tmp_path / f"repo-{index}", "count", "88", repos=bad
        )
        assert (code, calls) == (1, []) and "ideas_repos must be" in output, bad
    for index, unset in enumerate((None, "")):  # E1's eight: the module refuses
        code, output, calls = _dispatch(
            tmp_path / f"e1-{index}", None, "46", repos=unset
        )
        assert code == 0 and calls[1] == "A,B,C,D,E" and calls[5] == "unset", output
        with pytest.raises(ValueError, match="past the 240-minute job"):
            ip.probe_plan({ip.ARMS_ENV: calls[1]})
    code, output, calls = _dispatch(tmp_path / "other", "count", "12", "stage-a")
    assert (code, calls) == (1, []) and "ideas_arms is only for" in output
    code, output, calls = _dispatch(tmp_path / "o2", None, "12", "stage-a", "tomli")
    assert (code, calls) == (1, []) and "ideas_repos is only for" in output
    code, output, calls = _dispatch(tmp_path / "default", "A,B,C,D,E", "12", "stage-a")
    assert code == 0 and calls[1:3] == ["unset", "unset"], output
    assert calls[5] == "unset"


def test_the_suite_row_timeout_noise_rule_and_stage_a_ignore() -> None:
    inputs = _ci_block("      suite:", "      mode:")
    assert "ideas-probe" in inputs
    cap_help = _ci_block("      suite_cap_usd:", "\n\n")
    assert (
        "ideas-probe 46 (E1, four libraries of ideas_repos, one 12; "
        "ideas_arms count 9, C-low,C-high 20)" in cap_help
    )
    block = _ci_block("  live-smoke:", "    defaults:")
    assert f"inputs.suite == 'ideas-probe' && {ip.JOB_MINUTES} ||" in block
    assert EXPERIMENT_MINUTES["ideas-probe"] == ip.JOB_MINUTES
    script = _run_script()
    noise = script[script.index('case "${INPUT_SUITE}" in\n  noise |') :]
    noise = noise[: noise.index("esac")]
    step2 = [line for line in noise.splitlines() if "noise_rule=step2" in line]
    assert any(re.search(r"\bideas-probe\b", line) for line in step2)
    assert "--ignore=tests/live/test_ideas_probe_live.py" in script
