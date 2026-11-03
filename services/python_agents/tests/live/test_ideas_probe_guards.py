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
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx2
import pytest

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.common.config import (
    IDEA_VIEWS,
    Role,
    Settings,
    role_chain,
    settings,
)
from autonomous_ai_agents.common.errors import LLMRequestError
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Direction,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Objective,
    ObjectiveKind,
    Project,
    Workload,
)
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.optimization import idea_pipeline
from autonomous_ai_agents.optimization.idea_context import (
    IdeaReadLimits,
    ViewSource,
    build_view,
)
from autonomous_ai_agents.optimization.idea_pipeline import framework_labels
from autonomous_ai_agents.optimization.idea_review import (
    REVIEW_SYSTEM_PROMPT,
    review_request,
)
from autonomous_ai_agents.optimization.idea_types import (
    LENS_LANES,
    RELAXING_LANES,
    Lane,
    Mechanism,
    MorphCell,
    RelaxedRule,
)
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator.factory import repo_reader

from . import discovery_ab as ab
from . import ideas_probe as ip
from . import ideas_views as iv
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
    """Re-pinned from E1's recorded seconds (Vd): each stage takes twice its
    slowest request's E1 maximum, a parallel stage the slowest of each round
    of ``IDEAS_LANE_WORKERS``; phase 1 ``PHASE_ONE_MINUTES``. E1 41 minutes
    a library (phase 1 2, then A 23.5 s, B 360.4, C 421.5, D 841.5, E 464.9,
    the auditor 217.2: 38.8 minutes, rounded up), so five fit a 240-minute
    dispatch (205), six are refused (246); E0b's ten at 4, E1b's four at 16
    on recorded facts."""
    assert ip.ProbePlan(ip.E1_ARMS, _repos(("tomli",))).library_minutes() == 41
    assert ip.JOB_MINUTES == 240 and ip.TIME_MARGIN == 2
    assert ip.PHASE_ONE_MINUTES == 2
    seconds = [ip.arm_seconds(a) for a in ip.E1_ARMS]
    assert seconds == pytest.approx([23.544, 360.362, 421.46, 841.504, 464.876])
    assert ip.arm_seconds(ip.ARM_COUNT) == pytest.approx(ip.COUNT_SENT * 47.732)
    assert ip.AUDIT_SECONDS == pytest.approx(217.226)
    assert ip.ProbePlan(ip.E1_ARMS, _repos(("tomli",))).library_minutes() == 41
    assert ip.probe_plan({ip.REPOS_ENV: E1_DISPATCH}).minutes() == 4 * 41 == 164
    assert ip.probe_plan({ip.ARMS_ENV: "count"}).minutes() == 10 * 4
    e1b = ip.ProbePlan((ip.ARM_C_LOW, ip.ARM_C_HIGH), _repos(ip.E1B_REPOS), Path("f"))
    assert e1b.library_minutes() == 16 and e1b.minutes() == 64
    six = ",".join(ip.E1_REPOS[:6])
    for env in ({}, {ip.REPOS_ENV: six}):
        with pytest.raises(ValueError, match="past the 240-minute job"):
            ip.probe_plan(env)
    assert ip.ProbePlan(ip.E1_ARMS, _repos(ip.E1_REPOS[:5])).minutes() == 205
    assert ip.ProbePlan(ip.E1_ARMS, _repos(ip.E1_REPOS[:6])).minutes() == 246
    assert ip.probe_plan({ip.REPOS_ENV: "idna"}).minutes() == 41


E1_RESULTS = TESTS_DIR.parents[2] / ".claude/handoff/step3/idea-lab/e1"


def test_the_seconds_are_e1s_recorded_maxima_per_role_and_model() -> None:
    """Every measured entry is E1's slowest sent request of that role on that
    model (both results files); an unmeasured lane model reads as the
    nearest measured request, and any other is refused."""
    found: dict[tuple[str, str], float] = {}
    arms = {a.key: a for a in ip.E1_ARMS}
    for path in sorted(E1_RESULTS.glob("live-results-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["experiment"] != ip.REPLY_EXPERIMENT or not record["sent"]:
                continue
            role = record["role"]
            if role == "auditor":
                model = OPUS
            else:
                cfg = ip.arm_config(arms[record["arm"]], _project())
                model = role_chain(cfg, role)[0]
            key = (role, model)
            found[key] = max(found.get(key, 0.0), record["seconds"])
    assert found == ip.E1_SECONDS
    assert ip.request_seconds("lane", ip.SONNET_5) == 2 * found[("lane", SONNET)]
    assert ip.request_seconds("lane", OPUS) == 2 * found[("leap", OPUS)]
    for fable in (FABLE, ip.FABLE_5):
        assert ip.request_seconds("lane", fable) == 2 * found[("leap", FABLE)]
    with pytest.raises(ValueError, match="no E1 seconds"):
        ip.request_seconds("leap", ip.FABLE_5)


def test_sequential_lanes_count_one_stage_a_lane() -> None:
    """G4: S1, six lenses and the leap one at a time, then the reviewer."""
    seq = (("IDEAS_SEQUENTIAL_LANES", True),)
    sequential = ip.IdeaArm("C-seq", True, seq, e1=False)  # no auditor stage
    lane, leap, review = 47.732, 195.296, 130.7
    assert ip.arm_seconds(sequential) == pytest.approx(7 * lane + leap + review)
    no_leap = ip.IdeaArm(
        "C-seq0", True, (("IDEAS_SEQUENTIAL_LANES", True), ("IDEAS_LEAP_N", 0))
    )
    assert ip.arm_seconds(no_leap) == pytest.approx(7 * lane + review)
    plan = ip.ProbePlan((sequential,), _repos(("tomli",)), Path("f"))
    assert plan.library_minutes() == ip.CLONE_MINUTES + 12 == 13  # 11.002 up


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
# V7c: the pooled auditor's duplicates (STATUS 2026-10-31, the corrected rule)
# ---------------------------------------------------------------------------

Verdict = tuple[str, str, str | None]  # verdict, reason, duplicate_of
FEASIBLE: Verdict = ("feasible", "none", None)
UNKNOWN: Verdict = ("unknown", "none", None)
REAL_NO: Verdict = ("infeasible", "precondition_false", None)


def _dup(of: str | None) -> Verdict:
    return ("infeasible", "duplicate_of", of)


def _pooled_idea(arm: str, k: int, *, returned: bool = True) -> ip.Pooled:
    line = ip.ShownIdea(
        id=f"far-{k:02d}", lane="far", title=f"{arm} idea {k}",
        change_class="efficiency", anchor=f"{PATH}:slow_sum", change_summary="s",
        precondition="p", equivalence_summary="e", depends_on_path=PATH,
        depends_on_quote="q",
    )  # fmt: skip
    return ip.Pooled(arm, line, None, returned)


def _audit_reply(verdicts: Sequence[Verdict], twice: Sequence[str] = ()) -> str:
    reviews = [
        {"idea": f"i{k:02d}", "verdict": v, "reason": r, "duplicate_of": d,
         "change_plan": "" if v == "infeasible" else "Edit it."}
        for k, (v, r, d) in enumerate(verdicts, 1)
    ]  # fmt: skip
    reviews += [{**reviews[int(i[1:]) - 1], "verdict": "feasible"} for i in twice]
    return json.dumps({"reviews": reviews[::-1]})  # any order, as E1's auditor


_E1_RUNS = [ip.ArmRun(arm, None, None, 0.0, (), (), ()) for arm in ip.E1_ARMS]


def _scored(
    entries: Sequence[tuple[str, Verdict]], twice: Sequence[str] = ()
) -> dict[str, ip.Score]:
    """Scores of the pooled ideas ``(arm, verdict)`` in pool order (ids
    ``i01``...), every idea a returned non-obvious one, per E1 arm."""
    seen: Counter[str] = Counter()
    pooled = []
    for arm, _ in entries:
        seen[arm] += 1
        pooled.append(_pooled_idea(arm, seen[arm]))
    audit = ip.audit_of(_audit_reply([v for _, v in entries], twice), len(pooled))
    return ip.scores(_E1_RUNS, pooled, audit)


def _counts(scored: Mapping[str, ip.Score], arm: str) -> tuple[int | None, ...]:
    s = scored[arm]
    return (s.good, s.good_corrected, s.good_strict)


def test_the_audit_keeps_each_ideas_reason_and_duplicate_of() -> None:
    reply = _audit_reply([FEASIBLE, _dup("i01"), REAL_NO], twice=("i03",))
    reviews = ip.audit_reviews(reply)
    assert reviews == {
        "i01": ip.AuditReview("feasible", "none", None),
        "i02": ip.AuditReview("infeasible", "duplicate_of", "i01"),
    }  # i03 reviewed twice: no single verdict
    assert ip.own_verdicts(reply) == {"i01": "feasible", "i02": "infeasible"}
    assert ip.audit_reviews("not a review") == {}
    audit = ip.audit_of(reply, 4)
    assert audit.verdicts == ("feasible", "infeasible", None, None)
    assert audit.reviews == (reviews["i01"], reviews["i02"], None, None)
    assert (audit.error, audit.cost_usd, audit.exchanges) == (None, 0.0, ())


def test_a_cross_arm_duplicate_inherits_its_roots_feasible_verdict() -> None:
    scored = _scored([("B", FEASIBLE), ("C", _dup("i01"))])
    assert _counts(scored, "B") == (1, 1, 1)
    assert _counts(scored, "C") == (0, 1, 1)  # as coded 0: B proposed it first


def test_a_cross_arm_duplicate_inherits_a_real_infeasible() -> None:
    scored = _scored([("B", REAL_NO), ("C", _dup("i01")), ("D", UNKNOWN)])
    assert _counts(scored, "B") == (0, 0, 0)
    assert _counts(scored, "C") == (0, 0, 0)
    assert _counts(scored, "D") == (1, 1, 1)  # unknown is not infeasible


def test_a_chain_of_duplicates_is_followed_to_its_root() -> None:
    scored = _scored([("B", FEASIBLE), ("C", _dup("i01")), ("D", _dup("i02"))])
    assert _counts(scored, "D") == (0, 1, 1)  # i03 -> i02 -> i01, B's
    # the root decides, not the link: D's idea repeats C's, which repeats D's own
    scored = _scored([("D", FEASIBLE), ("C", _dup("i01")), ("D", _dup("i02"))])
    assert _counts(scored, "D") == (1, 1, 1)  # D idea 1 only
    assert _counts(scored, "C") == (0, 1, 1)
    # a chain ending on a real removal inherits it
    scored = _scored([("B", REAL_NO), ("C", _dup("i01")), ("E", _dup("i02"))])
    assert _counts(scored, "E") == (0, 0, 0)


def test_a_duplicate_of_the_same_arms_own_idea_does_not_count() -> None:
    scored = _scored([("B", FEASIBLE), ("B", _dup("i01")), ("C", FEASIBLE)])
    assert _counts(scored, "B") == (1, 1, 1)
    assert _counts(scored, "C") == (1, 1, 1)


def test_a_root_from_arm_a_counts_when_corrected_but_not_strict() -> None:
    scored = _scored([
        ("A", FEASIBLE), ("B", _dup("i01")), ("C", _dup("i02")), ("D", FEASIBLE),
        ("A", _dup("i01")),
    ])  # fmt: skip
    assert _counts(scored, "B") == (0, 1, 0)
    assert _counts(scored, "C") == (0, 1, 0)  # via B's duplicate, root A's
    assert _counts(scored, "D") == (1, 1, 1)
    # arm A is the baseline the strict count is read against: none of its own
    assert _counts(scored, "A") == (1, 1, None)


def test_a_duplicate_with_no_resolvable_root_does_not_count() -> None:
    scored = _scored(
        [
            ("B", _dup("i99")),  # names no pooled id
            ("C", _dup(None)),  # names none
            ("D", _dup("i04")), ("E", _dup("i03")),  # a cycle
            ("B", FEASIBLE), ("C", _dup("i05")),  # i05 reviewed twice: no verdict
        ],
        twice=("i05",),
    )  # fmt: skip
    assert {arm: _counts(scored, arm) for arm in "BCDE"} == {
        arm: (0, 0, 0) for arm in "BCDE"
    }
    assert (scored["B"].audited, scored["C"].audited) == (1, 2)


def test_only_returned_non_obvious_ideas_count_and_no_audit_scores_none() -> None:
    pooled = [
        _pooled_idea("B", 1), _pooled_idea("C", 1, returned=False), _pooled_idea("C", 2)
    ]  # fmt: skip
    audit = ip.audit_of(_audit_reply([FEASIBLE, FEASIBLE, _dup("i01")]), 3)
    scored = ip.scores(_E1_RUNS, pooled, audit)
    assert _counts(scored, "C") == (0, 1, 1)  # C idea 1 is not in its result
    failed = dataclasses.replace(audit, error="UnusableReplyError: x")
    for unknown in (ip.scores(_E1_RUNS, pooled, failed),
                    ip.scores(_E1_RUNS, pooled, None)):  # fmt: skip
        assert {_counts(unknown, k) for k in unknown} == {(None, None, None)}
    low = ip.scores([dataclasses.replace(_E1_RUNS[2], arm=ip.ARM_C_LOW)], pooled, audit)
    assert _counts(low, "C-low") == (None, None, None)  # not an E1 arm
    # an audit read without its reviews corrects nothing
    bare = dataclasses.replace(audit, reviews=())
    assert _counts(ip.scores(_E1_RUNS, pooled, bare), "C") == (0, 0, 0)


def test_rows_audit_records_and_the_summary_carry_the_corrected_counts(
    tmp_path: Path,
) -> None:
    entries = [("A", FEASIBLE), ("B", _dup("i01")), ("C", FEASIBLE), ("C", _dup("i03"))]
    pooled = [_pooled_idea(arm, k) for k, (arm, _) in enumerate(entries, 1)]
    audit = ip.audit_of(_audit_reply([v for _, v in entries]), len(pooled))
    arms = (ip.ARM_A, ip.ARM_B, ip.ARM_C)
    runs = [ip.ArmRun(arm, None, None, 0.0, (), (), ()) for arm in arms]
    results = tmp_path / "r.jsonl"
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(results)})
    recorder = ip.ProbeRecorder(ip.ProbePlan(arms, _repos(("tomli",))), sink)
    run = dg.Wire(_Answers()).run()
    recorder.record("tomli", runs, pooled, audit, run)
    expected = [(1, 1, None), (0, 1, 0), (1, 1, 1)]
    good = [(r.good, r.good_corrected, r.good_strict) for r in recorder.rows]
    assert good == expected
    lines = [json.loads(x) for x in results.read_text("utf-8").splitlines()]
    rows = [x for x in lines if x["experiment"] == ip.ROW_EXPERIMENT]
    counts = ("good", "good_corrected", "good_strict")
    assert [tuple(r[k] for k in counts) for r in rows] == expected
    audits = [x for x in lines if x["experiment"] == ip.AUDIT_EXPERIMENT]
    review = ("id", "auditor", "reason", "duplicate_of")
    assert [tuple(a[k] for k in review) for a in audits] == [
        ("i01", "feasible", "none", None),
        ("i02", "infeasible", "duplicate_of", "i01"),
        ("i03", "feasible", "none", None),
        ("i04", "infeasible", "duplicate_of", "i03"),
    ]
    # the note stays the cost note it was (it is cut at NOTE_CHARS)
    assert "; B 0 idea(s), good 0, 0.000; " in run.notes[-1]
    echoed: list[str] = []
    recorder.finish(echoed.append)
    header = next(line for line in echoed if line.startswith("| repo"))
    assert "| good | good corrected | good strict |" in header
    assert any(line.startswith("| tomli | B | 0 | 0 | 0 | 1 | 0 |") for line in echoed)
    assert any(line.startswith("| tomli | A | 0 | 0 | 1 | 1 | - |") for line in echoed)


def test_an_audit_shorter_than_its_pool_is_refused_not_cut(tmp_path: Path) -> None:
    """Every pooled idea gets its ``ideas-audit`` record: a verdict per
    idea is required (a short tuple raises), a missing review is ``None``."""
    pooled = [_pooled_idea("B", 1), _pooled_idea("C", 1), _pooled_idea("C", 2)]
    audit = ip.audit_of(_audit_reply([FEASIBLE, _dup("i01"), FEASIBLE]), 3)
    arms = (ip.ARM_B, ip.ARM_C)
    runs = [ip.ArmRun(arm, None, None, 0.0, (), (), ()) for arm in arms]
    results = tmp_path / "r.jsonl"
    recorder = ip.ProbeRecorder(
        ip.ProbePlan(arms, _repos(("tomli",))),
        ResultsSink({"LIVE_RESULTS_PATH": str(results)}),
    )
    run = dg.Wire(_Answers()).run()
    short = dataclasses.replace(audit, verdicts=audit.verdicts[:2])
    with pytest.raises(ValueError, match="zip"):
        recorder.record("tomli", runs, pooled, short, run)
    assert recorder.rows == [] and not results.exists()  # before any write
    bare = dataclasses.replace(audit, reviews=())  # no reviews: all rows, no reason
    recorder.record("tomli", runs, pooled, bare, run)
    lines = [json.loads(x) for x in results.read_text("utf-8").splitlines()]
    audits = [x for x in lines if x["experiment"] == ip.AUDIT_EXPERIMENT]
    assert [(a["id"], a["auditor"], a["reason"]) for a in audits] == [
        ("i01", "feasible", None), ("i02", "infeasible", None),
        ("i03", "feasible", None),
    ]  # fmt: skip


def test_the_auditor_run_carries_each_reason_and_duplicate_of(dry: Path) -> None:
    pooled = [_pooled_idea("B", 1), _pooled_idea("C", 1)]
    wire = dg.Wire(lambda _body: _audit_reply([FEASIBLE, _dup("i01")]))
    audit = ip.run_audit(pooled, wire.run(), _facts(), base=_base(), reader=_reader)
    assert audit.error is None and audit.verdicts == ("feasible", "infeasible")
    assert audit.reviews == (
        ip.AuditReview("feasible", "none", None),
        ip.AuditReview("infeasible", "duplicate_of", "i01"),
    )
    assert _counts(ip.scores(_E1_RUNS, pooled, audit), "C") == (0, 1, 1)


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
        f' "${{LIVE_IDEAS_REPOS-unset}}" "${{LIVE_IDEAS_VIEWS-unset}}" > "{called}"\n',
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
        (
            "X1",
            "more_itertools,pyparsing,tomli,sortedcontainers",
            "65",
            "X1",
            ip.FACTS_FIXTURE,
        ),
        ("X1", "mistune,sqlparse,markdown,idna", "65", "X1", ip.FACTS_FIXTURE),
        ("X1", "tomli", "17", "X1", ip.FACTS_FIXTURE),
        ("X1", "", "65", "X1", ip.FACTS_FIXTURE),
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
    argv, got_arms, got_facts, cap, paired, got_repos, got_views = calls
    assert (
        argv
        == "run pytest tests/live/test_ideas_probe_live.py -m live --no-cov -n 0 -rA"
    )
    assert (got_arms, got_facts, cap, paired) == (exported, facts, need, "false")
    assert got_repos == (repos or "unset")
    assert got_views == (ip.VIEWS_FIXTURE if exported == ip.X1_KEY else "unset")
    # the shell's need is the module's own, rounded up
    env = {ip.ARMS_ENV: exported, **({ip.REPOS_ENV: repos} if repos else {})}
    plan = ip.ProbePlan(
        ip.probe_arms(env), ip.probe_repos(env, ip.probe_arms(env)),
        Path(facts) if facts != "unset" else None,
    )  # fmt: skip
    if exported == ip.X1_KEY and not repos:  # the shell's need is four's
        plan = replace_repos(plan, ip.E1_REPOS[:4])
    assert ip.probe_need(plan) <= int(need) < ip.probe_need(plan) + 1
    below = f"{int(need) - 1}.99"
    code, output, calls = _dispatch(tmp_path / "below", arms, below, repos=repos)
    assert (code, calls) == (1, []) and f"suite_cap_usd {below} is below" in output


def test_the_ideas_inputs_are_strict_and_for_the_probe_only(tmp_path: Path) -> None:
    block = _ci_block("      ideas_arms:", "\n\n")
    assert "type: choice" in block and "default: 'A,B,C,D,E'" in block
    assert "options: ['A,B,C,D,E', count, 'C-low,C-high', X1]" in block
    repos = _ci_block("      ideas_repos:", "\n\n")
    assert "type: string" in repos and "default: ''" in repos
    for index, bad in enumerate(("", "A", "count;id", "C-low", "x1", "X1-0")):
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
    code, output, calls = _dispatch(tmp_path / "x1", "X1", "65", repos="")
    assert code == 0 and calls[1] == "X1" and calls[5] == "unset", output
    env = {ip.ARMS_ENV: calls[1], ip.FACTS_ENV: calls[2], ip.VIEWS_ENV: calls[2]}
    with pytest.raises(ValueError, match="past the 240-minute job"):  # all eight
        ip.probe_plan(env)
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
        "ideas_arms count 9, C-low,C-high 20; X1 65 for four libraries of "
        "ideas_repos, under the 80 USD fuse, one 17)" in cap_help
    )
    assert ip.X1_LIBRARY_CENTS == 1620 and "cents=1620" in _run_script()
    block = _ci_block("  live-smoke:", "    defaults:")
    assert f"inputs.suite == 'ideas-probe' && {ip.JOB_MINUTES} ||" in block
    assert EXPERIMENT_MINUTES["ideas-probe"] == ip.JOB_MINUTES
    script = _run_script()
    noise = script[script.index('case "${INPUT_SUITE}" in\n  noise |') :]
    noise = noise[: noise.index("esac")]
    step2 = [line for line in noise.splitlines() if "noise_rule=step2" in line]
    assert any(re.search(r"\bideas-probe\b", line) for line in step2)
    assert "--ignore=tests/live/test_ideas_probe_live.py" in script


# ---------------------------------------------------------------------------
# G3: quarantined proposals are reported, never scored (spec X1-4, O32)
# ---------------------------------------------------------------------------


def _returned(title: str, *tags: str, rationale: str = "r") -> Hypothesis:
    return Hypothesis(
        project_id="p1", hotspot_ids=("h-slow_sum",), source=HypothesisSource.novel,
        title=title, rationale=rationale, change_class=ChangeClass.efficiency,
        expected_gain=0.1, provability=0.5, risk=0.1, tags=tags,
    )  # fmt: skip


_IDEA = _returned("a far idea", "lane:far")
_LONG = "What the relaxed rule changes: " + "a new wheel. " * 90  # > 1 chunk
_PROPOSAL = _returned(
    "add a dependency", "lane:relax_dependency", "proposal:new_dependency",
    rationale=_LONG,
)  # fmt: skip
_BARE_LANE = _returned("relax the api", "lane:relax_api")  # no proposal tag
_ALL = (_IDEA, _PROPOSAL, _BARE_LANE)


def _shown(title: str, lane: str) -> ip.ShownIdea:
    return ip.ShownIdea(
        id=f"{lane}-01", lane=lane, title=title, change_class="efficiency",
        anchor=f"{PATH}:slow_sum", change_summary="s", precondition="p",
        equivalence_summary="e", depends_on_path=PATH, depends_on_quote="q",
    )  # fmt: skip


def _proposal_run(arm: ip.IdeaArm = ip.ARM_C, *, shown: bool = False) -> ip.ArmRun:
    exchanges: tuple[ip.Exchange, ...] = ()
    if shown:
        ideas = [ip.candidate(_shown(_IDEA.title, "far"), "far-01"),
                 ip.candidate(_shown(_PROPOSAL.title, "relax_dependency"), "rx-01")]  # fmt: skip
        request = review_request(
            ideas, prefix="data", fence=Fence("aa" * 8), reviewer_fence=Fence("bb" * 8),
            max_ideas=16, max_tokens=12_000, effort=None, notes=[],
        )[0]  # fmt: skip
        exchanges = (ip.Exchange("reviewer", "reviewer", 0, request),)
    return ip.ArmRun(arm, GenerateResult(hypotheses=_ALL), None, 0.0, (), (), exchanges)


def test_a_pooled_relaxing_lane_idea_becomes_a_valid_candidate() -> None:
    for lane, rule in (("relax_dependency", RelaxedRule.new_dependency),
                       ("relax_api", RelaxedRule.api_change)):  # fmt: skip
        built = ip.candidate(_shown("t", lane), "i01")
        assert (built.lane, built.proposal) == (Lane(lane), rule)
    assert ip.candidate(_shown("t", "far"), "i01").proposal is None


def test_proposals_are_never_pooled_for_the_auditor(dry: Path) -> None:
    for shown in (False, True):
        pooled = ip.pool([_proposal_run(shown=shown)], _facts())
        assert [p.idea.title for p in pooled] == [_IDEA.title], shown
        assert [ip.tier(p) for p in pooled] == [0]
        wire = dg.Wire(_Answers(remove=False))
        audit = ip.run_audit(pooled, wire.run(), _facts(), base=_base(), reader=_reader)
        assert (audit.error, audit.verdicts) == (None, ("feasible",))
        (body,) = wire.bodies
        assert _IDEA.title in _text(body)
        assert _PROPOSAL.title not in _text(body) and "relax_" not in _text(body)
    assert ip.scored_hypotheses(_proposal_run().result) == (_IDEA,)
    assert ip.proposals_of(_proposal_run().result) == (_PROPOSAL, _BARE_LANE)
    assert ip.scored_hypotheses(None) == () == ip.proposals_of(None)


def test_proposals_count_toward_no_score_and_are_recorded_apart(
    tmp_path: Path,
) -> None:
    runs = [_proposal_run(ip.ARM_B), _proposal_run(ip.ARM_C, shown=True)]
    pooled = ip.pool(runs, _facts())
    assert len(pooled) == 2  # one idea an arm, no proposal
    audit = ip.audit_of(_audit_reply([FEASIBLE, FEASIBLE]), len(pooled))
    scored = ip.scores(runs, pooled, audit)
    for arm in ("B", "C"):
        assert scored[arm].non_obvious == 1
        assert _counts(scored, arm) == (1, 1, 1)
    results = tmp_path / "r.jsonl"
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(results)})
    recorder = ip.ProbeRecorder(
        ip.ProbePlan((ip.ARM_B, ip.ARM_C), _repos(("tomli",))), sink
    )
    run = dg.Wire(_Answers()).run()
    recorder.record("tomli", runs, pooled, audit, run)
    assert [(r.ideas, r.proposals, r.non_obvious) for r in recorder.rows] == [
        (1, 2, 1), (1, 2, 1),
    ]  # fmt: skip
    lines = [json.loads(x) for x in results.read_text("utf-8").splitlines()]
    rows = [x for x in lines if x["experiment"] == ip.ROW_EXPERIMENT]
    assert [(r["ideas"], r["proposals"]) for r in rows] == [(1, 2), (1, 2)]
    kept = [x for x in lines if x["experiment"] == ip.PROPOSAL_EXPERIMENT]
    assert [(k["arm"], k["title"], k["relaxes"]) for k in kept] == [
        (arm, title, rules)
        for arm in ("B", "C")
        for title, rules in ((_PROPOSAL.title, ["new_dependency"]),
                             (_BARE_LANE.title, ["api_change"]))
    ]  # fmt: skip
    assert all(k["lane"].startswith("relax_") for k in kept)
    assert ["".join(k["rationale"]) for k in kept[:2]] == [_LONG, "r"]  # whole
    audits = [x for x in lines if x["experiment"] == ip.AUDIT_EXPERIMENT]
    assert {a["title"] for a in audits} == {_IDEA.title}
    assert "B 1 idea(s), 2 proposal(s), good 1" in run.notes[-1]
    echoed: list[str] = []
    recorder.finish(echoed.append)
    header = next(line for line in echoed if line.startswith("| repo"))
    assert "| own removed (agreed) | proposals | USD |" in header
    assert any(line.startswith("| tomli | B | 1 | 1 | 1 |") and "| 2 |" in line
               for line in echoed)  # fmt: skip


def test_an_arm_with_no_proposal_keeps_its_note_and_counts_none() -> None:
    plain = dataclasses.replace(
        _proposal_run(), result=GenerateResult(hypotheses=(_IDEA,))
    )
    recorder = ip.ProbeRecorder(ip.ProbePlan((ip.ARM_C,), _repos(("tomli",))),
                                ResultsSink({}))  # fmt: skip
    run = dg.Wire(_Answers()).run()
    recorder.record("tomli", [plain], [], None, run)
    assert (recorder.rows[0].ideas, recorder.rows[0].proposals) == (1, 0)
    assert "proposal" not in run.notes[-1]


def test_a_relaxing_arms_proposal_is_reported_never_pooled_or_scored(
    dry: Path, tmp_path: Path
) -> None:
    """End to end on the pipeline (G3's patch): an arm with a relaxing lane
    on returns its proposal last; the probe labels its request, records it
    apart and scores, pools and audits only the rest."""
    base = _base().model_copy(update={"IDEAS_RELAX_LANES": (Lane.relax_dependency,)})
    wire = dg.Wire(_Answers(), usages=[CACHED] * 14)
    found = ip.run_arm(ip.ARM_C, wire.run(), _facts(), base=base, reader=_reader)
    assert found.error is None and found.result is not None
    assert [e.label for e in found.exchanges][-3:] == [
        "relax_dependency", "leap", "reviewer",
    ]  # fmt: skip
    (proposal,) = ip.proposals_of(found.result)
    assert found.result.hypotheses[-1] == proposal
    assert "proposal:new_dependency" in proposal.tags
    scored = ip.scored_hypotheses(found.result)
    assert len(scored) == len(found.result.hypotheses) - 1
    pooled = ip.pool([found], _facts())
    assert proposal.title not in {p.idea.title for p in pooled}
    assert all(p.idea.lane not in {"relax_dependency"} for p in pooled)
    audit = ip.run_audit(
        pooled, dg.Wire(_Answers(remove=False)).run(), _facts(), base=base,
        reader=_reader,
    )  # fmt: skip
    assert audit.error is None
    score = ip.scores([found], pooled, audit)["C"]
    assert score.non_obvious == sum(
        not h.tags[0].startswith("lane:obvious") for h in scored
    )
    results = tmp_path / "r.jsonl"
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(results)})
    recorder = ip.ProbeRecorder(ip.ProbePlan((ip.ARM_C,), _repos(("tomli",))), sink)
    recorder.record("tomli", [found], pooled, audit, dg.Wire(_Answers()).run())
    (row,) = recorder.rows
    assert (row.ideas, row.proposals) == (len(scored), 1)
    lines = [json.loads(x) for x in results.read_text("utf-8").splitlines()]
    (kept,) = [x for x in lines if x["experiment"] == ip.PROPOSAL_EXPERIMENT]
    assert (kept["title"], kept["relaxes"]) == (proposal.title, ["new_dependency"])


def test_a_rows_frameworks_name_only_the_lanes_it_sent(
    dry: Path, tmp_path: Path
) -> None:
    """G5: the pipeline labels every S2 lane's assigned framework, sent or
    not; the row keeps only the sent lanes', so count mode (S1 and the first
    lens sent) never reports the unsent relaxing lane's framework."""
    base = _base().model_copy(update={
        "IDEAS_LANE_FRAMEWORKS": True,
        "IDEAS_RELAX_LANES": (Lane.relax_dependency,),
    })  # fmt: skip
    wire = dg.Wire(_Answers(), usages=[CACHED] * 14)
    run = wire.run()
    found = ip.run_arm(ip.ARM_COUNT, run, _facts(), base=base, reader=_reader)
    assert found.error is None and found.result is not None
    assigned = framework_labels(found.result.notes)
    assert assigned[Lane.relax_dependency] == "rule new_dependency"
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(tmp_path / "r.jsonl")})
    recorder = ip.ProbeRecorder(ip.ProbePlan((ip.ARM_COUNT,), _repos(("tomli",))), sink)
    recorder.record("tomli", [found], [], None, run)
    (row,) = recorder.rows
    assert row.sent == ("obvious", LENS_LANES[0].value)
    assert row.frameworks == {LENS_LANES[0].value: None}


def test_a_sequential_rows_frameworks_keep_every_lane_it_sent(dry: Path) -> None:
    """G5 with G4's sequential lanes: a re-priced lane is sent under a fresh
    tap label (``lane-N``), so the row reads which lanes were answered from
    the pipeline's own stop reasons, keyed by lane in every mode."""
    base = _base().model_copy(update={
        "IDEAS_LANE_FRAMEWORKS": True, "IDEAS_SEQUENTIAL_LANES": True,
        "IDEAS_RELAX_LANES": (Lane.relax_dependency,),
    })  # fmt: skip
    wire = dg.Wire(_Answers(), usages=[CACHED] * 20)
    found = ip.run_arm(ip.ARM_C, wire.run(), _facts(), base=base, reader=_reader)
    assert found.error is None and found.result is not None
    frameworks = ip.sent_frameworks(found)
    assert frameworks["relax_dependency"] == "rule new_dependency"
    assert set(frameworks) == {*(lane.value for lane in LENS_LANES), "leap",
                               "relax_dependency"}  # fmt: skip


# ---------------------------------------------------------------------------
# Vd: X1's configurations on E1's facts and Va's views (spec-idea-lab 6.2)
# ---------------------------------------------------------------------------

X1_FUSE = 80.0  # spec-idea-lab 6.4: each dispatch's worst case stays under it
X1_DISPATCHES = (
    "more_itertools,pyparsing,tomli,sortedcontainers",
    "mistune,sqlparse,markdown,idna",
)
X1_LIBRARY_CAP = 16.20  # 0.27 + 2.475 + 4.206 + 2.539 + 2.675 + 3.335 + 0.69
SQUARE_MODELS = {
    "claude-sonnet-5", HAIKU, OPUS, "claude-fable-5", FABLE, SONNET,
}  # fmt: skip


def _c_dump(project: Project | None = None) -> dict[str, object]:
    return ip.arm_config(ip.ARM_C, project or _project()).model_dump()


def _changed(arm: ip.IdeaArm, project: Project | None = None) -> dict[str, object]:
    """What the arm's settings change against arm C's (X1-0's baseline)."""
    mine = ip.arm_config(arm, project or _project()).model_dump()
    base = _c_dump(project)
    return {k: v for k, v in mine.items() if v != base[k]}


def test_each_x1_configuration_changes_exactly_its_own_lever() -> None:
    """X1-0 is arm C; X1-1 the per-lens models (and the retention flag its
    Fable lanes need); X1-2 sequential lanes with the dedupe; X1-3 a
    different view per lens with frameworks on; X1-4 the four rule-relaxing
    lanes. Every other setting is arm C's, so one lever moves a config."""
    tomli = _project()  # row 2 of the square
    assert _changed(ip.ARM_X1_0) == {}
    assert ip.ARM_X1_0.update == ip.ARM_C.update == ()
    assert _changed(ip.ARM_X1_1) == {
        "IDEAS_LANE_MODELS": {lane: m for lane, m in ip.square_models(2).items()},
        "ALLOW_RETENTION_MODELS": True,
    }
    assert ip.arm_config(ip.ARM_X1_1, tomli).IDEAS_LANE_MODELS == ip.square_models(2)
    assert _changed(ip.ARM_X1_2) == {
        "IDEAS_SEQUENTIAL_LANES": True, "IDEAS_MECHANISM_DEDUPE": True,
    }  # fmt: skip
    assert _changed(ip.ARM_X1_3) == {
        "IDEAS_LANE_VIEWS": dict(ip.X1_VIEWS), "IDEAS_LANE_FRAMEWORKS": True,
    }  # fmt: skip
    assert set(ip.X1_VIEWS) == set(LENS_LANES)
    assert sorted(ip.X1_VIEWS.values()) == sorted(IDEA_VIEWS)  # one view each
    assert _changed(ip.ARM_X1_4) == {"IDEAS_RELAX_LANES": tuple(RELAXING_LANES)}
    assert len(RELAXING_LANES) == 4
    assert ip.X1_ARMS == (ip.ARM_A, *ip.X1_CONFIGS)
    assert [a.key for a in ip.X1_CONFIGS] == ["X1-0", "X1-1", "X1-2", "X1-3", "X1-4"]
    assert [a.e1 for a in ip.X1_ARMS] == [True, True, True, True, True, False]
    assert "two factors" in ip.ARM_X1_3.lever and "split in X2" in ip.ARM_X1_3.lever
    assert "never scored" in ip.ARM_X1_4.lever
    for arm in ip.X1_ARMS:
        cfg = ip.arm_config(arm, tomli)
        assert cfg.IDEA_PIPELINE is arm.pipeline and arm.lever, arm.key


def test_the_latin_square_meets_every_model_with_every_lens_once() -> None:
    """X1-1 (spec 6.2): a 6x6 Latin square, rows 1-6 on the first six of the
    8 development libraries, then rows 1-2 again."""
    rows = [ip.square_models(r) for r in range(6)]
    pairs = Counter((lane, model) for row in rows for lane, model in row.items())
    assert set(pairs.values()) == {1} and len(pairs) == 36
    assert {m for _, m in pairs} == SQUARE_MODELS
    for row in rows:
        assert list(row) == list(LENS_LANES) and set(row.values()) == SQUARE_MODELS
    for lane in LENS_LANES:  # each column too
        assert {row[lane] for row in rows} == SQUARE_MODELS
    assert [ip.square_row(name) for name in ip.E1_REPOS] == [0, 1, 2, 3, 4, 5, 0, 1]
    with pytest.raises(ValueError, match="not one of the 8 development"):
        ip.square_row("requests")
    with pytest.raises(ValueError, match="not one of the 8 development"):
        ip.arm_config(ip.ARM_X1_1, _project("blockhash"))
    for name in ip.E1_REPOS:  # every model is priced and takes medium
        cfg = ip.arm_config(ip.ARM_X1_1, _project(name))
        assert cfg.IDEAS_LANE_MODELS == ip.square_models(ip.square_row(name))
        assert cfg.IDEAS_LANE_EFFORT == "medium" and cfg.ALLOW_RETENTION_MODELS
        assert set(cfg.IDEAS_LANE_MODELS.values()) <= set(cfg.MODEL_PRICING)


def test_x1_caps_are_each_configurations_worst_case_and_a_dispatch_fits() -> None:
    """D55's bounds per request: X1-1 each lens on its model; X1-2 each S2
    lane with the 48-line mechanisms block; X1-3 each viewed lane and the
    reviewer (the views' extra code) on wider bounds; X1-4 four more lanes.
    A library's cap is equal on every row of the square; four libraries a
    dispatch stay under the 80 USD fuse."""
    lane = ip.request_usd(ip.LANE_PROMPT_BOUND, 12_000, SONNET)
    leap = ip.request_usd(ip.LANE_PROMPT_BOUND, 12_000, OPUS)
    review = ip.request_usd(ip.REVIEW_PROMPT_BOUND, 16_000, OPUS)
    assert ip.arm_usd(ip.ARM_X1_0) == ip.arm_usd(ip.ARM_C) == pytest.approx(2.475)
    lenses = [ip.request_usd(ip.LANE_PROMPT_BOUND, 12_000, m) for m in SQUARE_MODELS]
    for name in ip.E1_REPOS:
        assert ip.arm_usd(ip.ARM_X1_1, repo=name) == pytest.approx(
            lane + sum(lenses) + leap + review
        )
    assert ip.arm_usd(ip.ARM_X1_1) == pytest.approx(4.20575)
    taken = ip.LANE_PROMPT_BOUND + ip.TAKEN_PROMPT_EXTRA
    assert ip.arm_usd(ip.ARM_X1_2) == pytest.approx(
        lane + 6 * ip.request_usd(taken, 12_000, SONNET)
        + ip.request_usd(taken, 12_000, OPUS) + review
    )  # fmt: skip
    assert ip.arm_usd(ip.ARM_X1_3) == pytest.approx(
        lane + 6 * ip.request_usd(ip.VIEW_PROMPT_BOUND, 12_000, SONNET) + leap
        + ip.request_usd(ip.VIEW_REVIEW_PROMPT_BOUND, 16_000, OPUS)
    )  # fmt: skip
    assert ip.arm_usd(ip.ARM_X1_4) == pytest.approx(2.475 + 4 * lane)
    assert ip.TAKEN_PROMPT_EXTRA >= 48 * 60  # MAX_TAKEN_LINES lines
    facts = Path(ip.SERVICE_DIR / ip.FACTS_FIXTURE)
    for dispatch in X1_DISPATCHES:
        plan = ip.ProbePlan(ip.X1_ARMS, _repos(dispatch.split(",")), facts, facts)
        assert [plan.library_cap(r.name) for r in plan.repos] == [X1_LIBRARY_CAP] * 4
        assert ip.probe_need(plan) == pytest.approx(4 * X1_LIBRARY_CAP)
        assert ip.probe_need(plan) <= ip.X1_FUSE_USD == X1_FUSE
    assert ip.X1_LIBRARY_CENTS == round(X1_LIBRARY_CAP * 100) == 1620


def test_the_rule_relaxing_lanes_count_in_a_pipeline_calls_cap() -> None:
    """G3's lanes are sent like any lens (X1-4), so the cap holds them."""
    base = settings.model_copy(update={"IDEAS_RELAX_LANES": tuple(RELAXING_LANES)})
    cfg = ip.arm_config(ip.ARM_C, _project(), base)
    lane = ip.request_usd(ip.LANE_PROMPT_BOUND, 12_000, SONNET)
    assert ip.pipeline_usd(cfg) == pytest.approx(2.475 + 4 * lane)


def test_x1_minutes_fit_the_job_four_libraries_a_dispatch() -> None:
    """E1's seconds (Vd): X1-1's Fable lenses dominate a round (twice E1's
    Fable 5.1 leap), so a row with both Fables in one round of four is
    shorter (52 minutes) than one with them in both rounds (57)."""
    facts = ip.SERVICE_DIR / ip.FACTS_FIXTURE
    plan = ip.ProbePlan(ip.X1_ARMS, _repos(ip.E1_REPOS), facts, facts)
    minutes = {name: plan.library_minutes(name) for name in ip.E1_REPOS}
    assert minutes == {
        "more_itertools": 57, "pyparsing": 52, "tomli": 52, "sortedcontainers": 52,
        "mistune": 57, "sqlparse": 52, "markdown": 57, "idna": 52,
    }  # fmt: skip
    assert ip.arm_seconds(ip.ARM_X1_1, repo="more_itertools") == pytest.approx(
        47.732 + 2 * 468.566 + 130.7
    )
    assert ip.arm_seconds(ip.ARM_X1_4) == pytest.approx(
        47.732 + 47.732 + 195.296 + 47.732 + 130.7
    )  # 11 S2 lanes on 4 workers: three rounds, the leap in the second
    for dispatch, total in zip(X1_DISPATCHES, (213, 218), strict=True):
        env = {ip.ARMS_ENV: "X1", ip.REPOS_ENV: dispatch,
               ip.FACTS_ENV: str(facts), ip.VIEWS_ENV: str(facts)}  # fmt: skip
        found = ip.probe_plan(env)
        assert found.arms == ip.X1_ARMS and found.minutes() == total <= ip.JOB_MINUTES
    for repos in ({}, {ip.REPOS_ENV: ",".join(ip.E1_REPOS[:5])}):  # 8, 5: refused
        with pytest.raises(ValueError, match="past the 240-minute job"):
            ip.probe_plan({ip.ARMS_ENV: "X1", ip.FACTS_ENV: str(facts),
                           ip.VIEWS_ENV: str(facts), **repos})  # fmt: skip


def test_x1_needs_e1s_facts_and_vas_views_before_any_spend(tmp_path: Path) -> None:
    four = {ip.ARMS_ENV: "X1", ip.REPOS_ENV: X1_DISPATCHES[0]}
    facts = str(ip.SERVICE_DIR / ip.FACTS_FIXTURE)
    with pytest.raises(ValueError, match=f"X1 reads E1's facts: set {ip.FACTS_ENV}"):
        ip.probe_plan(four)
    with pytest.raises(ValueError, match=f"X1 reads Va's views: set {ip.VIEWS_ENV}"):
        ip.probe_plan({**four, ip.FACTS_ENV: facts})
    with pytest.raises(ValueError, match="no recorded views at"):
        ip.probe_plan({**four, ip.FACTS_ENV: facts, ip.VIEWS_ENV: "none.jsonl"})
    for arms in ("X1-3", "A,X1-0"):  # one X1 configuration alone, too
        with pytest.raises(ValueError, match="X1 reads"):
            ip.probe_plan({ip.ARMS_ENV: arms, ip.REPOS_ENV: "tomli"})
    with pytest.raises(ValueError, match="distinct entries"):
        ip.probe_plan({ip.ARMS_ENV: "X1,A"})
    over = dataclasses.replace(
        ip.ARM_X1_1, update=(("IDEAS_LANE_MAX_TOKENS", 128_000),)
    )
    plan = ip.ProbePlan((ip.ARM_A, over), _repos(X1_DISPATCHES[0].split(",")))
    assert ip.probe_need(plan) > X1_FUSE
    with pytest.raises(ValueError, match="past the 80 USD fuse"):
        ip.check_fuse(plan)
    ip.check_fuse(ip.ProbePlan(ip.E1_ARMS, _repos(ip.E1_REPOS)))  # E1: no fuse


# ---- the views: recorded rows, the seam, the pre-spend check --------------


def _workload(body: ip.FactsBody) -> Workload:
    return iv.recorded_workload(LIB, body)


def _views_file(
    path: Path,
    body: ip.FactsBody,
    reader: Any,
    *,
    limits: IdeaReadLimits | None = None,
    protected: tuple[str, ...] | None = None,
) -> Path:
    """Va's rows for ``body``, built by ``build_view`` with ``reader`` (as
    the views pass builds them at the recorded commit)."""
    limits = limits or IdeaReadLimits.from_settings(settings)
    source = ViewSource(
        reader, body.commit, body.hotspots, Fence.new(),
        body.protected if protected is None else protected, (), limits,
        (_workload(body),),
    )  # fmt: skip
    digest = iv.source_digest(source)
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(path)})
    for name in IDEA_VIEWS:
        notes: list[str] = []
        view = build_view(name, source, notes)
        sink.write(iv.ViewRow(body.project.name, iv.ViewBody(
            view=name, commit=body.commit, run_id=body.run_id, source_sha256=digest,
            limits=limits, commits=0, context=None if view is None else view.context,
            facts=() if view is None else ('recorded: "Va"', *view.facts),
            notes=tuple(notes),
        )).record())  # fmt: skip
    return path


def _x1_plan(views: Path | None) -> ip.ProbePlan:
    return ip.ProbePlan(ip.X1_ARMS, _repos(("tomli",)), Path("recorded"), views)


def test_a_missing_or_mismatched_views_file_refuses_before_any_spend(
    tmp_path: Path,
) -> None:
    body = ip.FactsBody.of(_facts())
    good = _views_file(tmp_path / "good.jsonl", body, _Reader())
    recorder = ip.ProbeRecorder(_x1_plan(good), ResultsSink({}), {LIB.name: body})
    assert set(recorder.views) == {LIB.name}
    wrong = {
        "limits": _views_file(tmp_path / "limits.jsonl", body, _Reader(),
                              limits=IdeaReadLimits(hot_functions=2)),
        "source": _views_file(tmp_path / "source.jsonl", body, _Reader(),
                              protected=("tests/",)),
    }  # fmt: skip
    for what, path in wrong.items():
        with pytest.raises(ValueError, match="not the source this run builds"):
            ip.ProbeRecorder(_x1_plan(path), ResultsSink({}), {LIB.name: body})
        assert what
    other = body.model_copy(update={"run_id": "run-2"})
    with pytest.raises(ValueError, match="not the recorded facts'"):
        ip.ProbeRecorder(_x1_plan(good), ResultsSink({}), {LIB.name: other})
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match=f"{ip.VIEWS_ENV}: no recorded views for"):
        ip.ProbeRecorder(_x1_plan(empty), ResultsSink({}), {LIB.name: body})
    with pytest.raises(ValueError, match="views are never built live"):
        ip.ProbeRecorder(_x1_plan(None), ResultsSink({}), {LIB.name: body})
    plain = ip.ProbeRecorder(ip.ProbePlan((ip.ARM_C,), _repos(("tomli",))),
                             ResultsSink({}))  # fmt: skip
    assert plain.views == {}


def test_x1_3_sees_the_recorded_views_through_the_seam_never_built_live(
    dry: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = ip.FactsBody.of(_facts())
    path = _views_file(tmp_path / "views.jsonl", body, _Reader())
    recorded = iv.load_views(path, {LIB.name: body})[LIB.name]

    def never(*_args: object) -> None:
        raise AssertionError("a view was built live")

    monkeypatch.setattr(idea_pipeline, "build_view", never)
    wire = dg.Wire(_Answers(), usages=[CACHED] * 12)
    found = ip.run_arm(ip.ARM_X1_3, wire.run(), _facts(), base=_base(),
                       reader=_reader, views=recorded.build,
                       workloads=(_workload(body),))  # fmt: skip
    assert found.error is None and found.result is not None
    built = {n for n, b in recorded.bodies.items() if b.context is not None}
    assert built  # the fake repository gives some views, not all
    texts = {_lens(b): _text(b) for b in wire.bodies}
    for lane, view in ip.X1_VIEWS.items():
        assert ('recorded: "Va"' in texts[lane.value]) is (view in built), lane
    frameworks = ip.sent_frameworks(found)
    assert {k: v for k, v in frameworks.items() if v} == {
        lane.value: f"view {view}" for lane, view in ip.X1_VIEWS.items()
        if view in built
    }  # fmt: skip
    with pytest.raises(ValueError, match="views are never built live"):
        ip.run_arm(ip.ARM_X1_3, dg.Wire(_Answers()).run(), _facts(), base=_base(),
                   reader=_reader)  # fmt: skip


_LENS_TAG = re.compile(r'<lens name=\\?"([a-z_]+)\\?"')


def _lens(body: Json) -> str:
    """The lane a request body is for (S1 has no lens; the reviewer's)."""
    if "reviews" in dg._schema_keys(body):
        return "reviewer"
    content = body["messages"][0]["content"]
    found = _LENS_TAG.search(content[-1]["text"])
    return "obvious" if found is None else found.group(1)


def test_x1_1_sends_each_lens_on_its_square_model(dry: Path) -> None:
    wire = dg.Wire(_Answers(), usages=[CACHED] * 12)
    found = ip.run_arm(ip.ARM_X1_1, wire.run(), _facts(), base=_base(), reader=_reader)
    assert found.error is None and found.result is not None
    models = {_lens(b): b["model"] for b in wire.bodies}
    row = ip.square_models(ip.square_row(LIB.name))
    assert models == {
        "obvious": SONNET, **{lane.value: m for lane, m in row.items()},
        "leap": OPUS, "reviewer": OPUS,
    }  # fmt: skip
    efforts = {_lens(b): b["output_config"]["effort"] for b in wire.bodies}
    assert {efforts[lane.value] for lane in LENS_LANES} == {"medium"}
    assert set(found.billable) == SQUARE_MODELS | {OPUS}
    assert {e.label: e.model for e in found.exchanges if e.role == "lane"} == {
        "obvious": SONNET, **{lane.value: m for lane, m in row.items()},
    }  # fmt: skip


def test_x1_4_proposals_are_reported_never_pooled_or_scored(
    dry: Path, tmp_path: Path
) -> None:
    wire = dg.Wire(_Answers(), usages=[CACHED] * 16)
    relaxed = ip.run_arm(ip.ARM_X1_4, wire.run(), _facts(), base=_base(),
                         reader=_reader)  # fmt: skip
    base = ip.run_arm(ip.ARM_X1_0, dg.Wire(_Answers(), usages=[CACHED] * 12).run(),
                      _facts(), base=_base(), reader=_reader)  # fmt: skip
    kept = ip.proposals_of(relaxed.result)
    assert {ip._lane(h) for h in kept} == {lane.value for lane in RELAXING_LANES}
    pooled = ip.pool([base, relaxed], _facts())
    assert pooled and {p.arm for p in pooled} == {"X1-0"}  # X1-4: never pooled
    audit = ip.audit_of(_audit_reply([FEASIBLE] * len(pooled)), len(pooled))
    scored = ip.scores([base, relaxed], pooled, audit)
    assert scored["X1-4"].good is scored["X1-4"].good_corrected is None
    assert scored["X1-0"].good is not None
    results = tmp_path / "r.jsonl"
    recorder = ip.ProbeRecorder(
        ip.ProbePlan((ip.ARM_X1_0, ip.ARM_X1_4), _repos(("tomli",))),
        ResultsSink({"LIVE_RESULTS_PATH": str(results)}),
    )
    recorder.record(LIB.name, [base, relaxed], pooled, audit, wire.run(),
                    read=_read)  # fmt: skip
    rows = {r.arm: r for r in recorder.rows}
    assert rows["X1-4"].proposals == 4 and rows["X1-4"].good is None
    lines = [json.loads(x) for x in results.read_text("utf-8").splitlines()]
    proposals = [x for x in lines if x["experiment"] == ip.PROPOSAL_EXPERIMENT]
    assert sorted(r for x in proposals for r in x["relaxes"]) == sorted(
        rule.value for rule in RELAXING_LANES.values()
    )
    audits = [x for x in lines if x["experiment"] == ip.AUDIT_EXPERIMENT]
    assert {a["arm"] for a in audits} == {"X1-0"}
    ideas = [x for x in lines if x["experiment"] == ip.IDEA_EXPERIMENT]
    flagged = [(x["lane"], x["relaxes"]) for x in ideas if x["proposal"]]
    assert sorted(flagged) == sorted(
        (lane.value, rule.value) for lane, rule in RELAXING_LANES.items()
    )
    assert all(x["arm"] == "X1-4" for x in ideas if x["proposal"])


def _read(path: str) -> str | None:
    return SOURCE if path == PATH else None


def test_the_records_carry_every_idea_with_its_mechanism_target_and_model(
    dry: Path, tmp_path: Path
) -> None:
    """Every lane reply's every idea (S1, the lenses, the leap; returned or
    not) and every returned idea of today's generator, one ``ideas-idea``
    row each: title, mechanism, cells, target lines (the quote's first
    match in the file at the commit), lane, model, proposal flag."""
    arms = [ip.run_arm(arm, dg.Wire(_Answers(), usages=[CACHED] * 12).run(),
                       _facts(), base=_base(), reader=_reader)
            for arm in (ip.ARM_A, ip.ARM_X1_1)]  # fmt: skip
    results = tmp_path / "r.jsonl"
    recorder = ip.ProbeRecorder(
        ip.ProbePlan((ip.ARM_A, ip.ARM_X1_1), _repos(("tomli",))),
        ResultsSink({"LIVE_RESULTS_PATH": str(results)}),
    )
    recorder.record(LIB.name, arms, [], None, dg.Wire(_Answers()).run(), read=_read)
    lines = [json.loads(x) for x in results.read_text("utf-8").splitlines()]
    ideas = [x for x in lines if x["experiment"] == ip.IDEA_EXPERIMENT]
    today = [x for x in ideas if x["arm"] == "A"]
    assert [(x["title"], x["lane"], x["model"], x["returned"]) for x in today] == [
        ("Today 0", "today", SONNET, True), ("Today 1", "today", SONNET, True),
    ]  # fmt: skip
    assert all(x["mechanism"] is None and x["target"] is None for x in today)
    assert {x["label"] for x in today} == {"generator"}
    assert [x["change"] for x in today] == ["Sum with the builtin."] * 2
    mine = [x for x in ideas if x["arm"] == "X1-1"]
    sent = [e for e in arms[1].exchanges if e.role in ("lane", "leap") and e.sent]
    assert len(mine) == len(sent) == 1 + 6 + 1  # one idea a lane reply
    assert {x["label"] for x in mine} == {e.label for e in sent}
    row = ip.square_models(ip.square_row(LIB.name))
    models = {"obvious": SONNET, "leap": OPUS, **{k.value: v for k, v in row.items()}}
    assert {x["lane"]: x["model"] for x in mine} == models
    returned = {h.title for h in arms[1].result.hypotheses}  # type: ignore[union-attr]
    assert {x["title"] for x in mine if x["returned"]} == returned
    assert any(not x["returned"] for x in mine)  # the full list, not the result
    for x in mine:
        k = int(x["title"].split()[1].rstrip(":"))
        idea = _lane_idea(k)
        symbol = list(QUOTES)[k % 2]
        line = SOURCE.splitlines().index(f"        {QUOTES[symbol]}") + 1
        assert (x["mechanism"], x["cells"], x["path"]) == (
            idea["mechanism"], idea["morph_cells"], PATH,
        )  # fmt: skip
        assert x["target"] == {"first": line, "last": line}
        assert x["proposal"] is False and x["relaxes"] is None
        assert x["change"] == idea["change_summary"]
    rows = {r.arm: r for r in recorder.rows}
    assert rows["X1-1"].lane_models == {k.value: v for k, v in row.items()}
    assert rows["X1-1"].lever == ip.ARM_X1_1.lever and rows["A"].lane_models == {}
    assert rows["X1-1"].cost_usd == arms[1].cost_usd > 0  # cost per configuration


def test_a_sequential_idea_joins_its_reply_by_label(dry: Path, tmp_path: Path) -> None:
    """X1-2's re-priced lanes are sent under a generic ``lane-N`` label, so
    each idea row carries its exchange's label: (repo, arm, label) names
    exactly one sent ``ideas-reply`` row, whose text holds the idea."""
    wire = dg.Wire(_Answers(), usages=[CACHED] * 20)
    found = ip.run_arm(ip.ARM_X1_2, wire.run(), _facts(), base=_base(), reader=_reader)
    assert found.error is None
    labels = [e.label for e in found.exchanges if e.sent]
    assert any(x.startswith("lane-") for x in labels)  # a re-priced lane
    results = tmp_path / "r.jsonl"
    recorder = ip.ProbeRecorder(ip.ProbePlan((ip.ARM_X1_2,), _repos(("tomli",))),
                                ResultsSink({"LIVE_RESULTS_PATH": str(results)}))  # fmt: skip
    recorder.record(LIB.name, [found], [], None, dg.Wire(_Answers()).run(), read=_read)
    lines = [json.loads(x) for x in results.read_text("utf-8").splitlines()]
    ideas = [x for x in lines if x["experiment"] == ip.IDEA_EXPERIMENT]
    replies = [x for x in lines if x["experiment"] == ip.REPLY_EXPERIMENT and x["sent"]]
    assert ideas and len({x["label"] for x in replies}) == len(replies)
    assert all({"label", "change"} <= x.keys() for x in ideas)
    by_label = {x["label"]: "".join(x["chunks"]) for x in replies}
    for x in ideas:
        text = by_label[x["label"]]
        assert x["title"] in text and x["change"] in text
    assert {x["lane"] for x in ideas} == {"obvious", "leap",
                                          *(lane.value for lane in LENS_LANES)}  # fmt: skip


def test_an_unreadable_reply_or_an_unknown_file_records_no_target() -> None:
    reply = json.dumps({"hypotheses": [{**_lane_idea(0), "depends_on_path": "../x"},
                                       {**_lane_idea(1), "depends_on_path": "a.py"},
                                       {**_lane_idea(2), "depends_on_quote": "zz"}]})  # fmt: skip
    targets = [t for _, t in ip.reply_ideas(reply, _read)]
    assert targets == [None, None, None]
    assert ip.reply_ideas("not json", _read) == []
    assert ip.reply_ideas(json.dumps({"hypotheses": [{"title": "t"}]}), _read) == []
    assert ip.read_text_of(_Reader(), SHA)("missing/file.py") is None
    assert ip.read_text_of(_Reader(), SHA)(PATH) == SOURCE
    assert ip.read_text_of(_Reader(), "e" * 40)(PATH) is None  # GitError
    assert ip.read_text_of(_Unreadable(), SHA)(PATH) is None  # a tracked blob too
    plain = dataclasses.replace(_proposal_run(shown=True).exchanges[0].request,
                                messages=({"role": "user", "content": "hi"},))  # fmt: skip
    assert ip.request_lane(plain) is Lane.obvious


class _Unreadable(_Reader):
    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        raise GitError("bad object")


def test_one_x1_library_on_recorded_facts_and_views_records_every_row(
    upstream: og.Upstream, tmp_path: Path, dry: Path
) -> None:
    url, commit = upstream({PATH: SOURCE, "LICENSE": "Permission is hereby granted\n"})
    repo = og._local_repo(url, commit, LIB)
    (tmp_path / "rec").mkdir()
    head = oss.prepare_repo(repo, tmp_path / "rec" / "user", policy=og.LOCAL).base
    facts = _facts(repo.project(tmp_path / "rec" / "user"))
    body = ip.FactsBody.of(facts).model_copy(update={"commit": head})
    views = _views_file(tmp_path / "views.jsonl", body,
                        repo_reader(facts.facts.project))  # fmt: skip
    results = tmp_path / "results.jsonl"
    arms = (ip.ARM_A, ip.ARM_X1_0, ip.ARM_X1_3)
    plan = ip.ProbePlan(arms, (repo,), Path("recorded"), views)
    recorder = ip.ProbeRecorder(plan, ResultsSink({"LIVE_RESULTS_PATH": str(results)}),
                                {repo.name: body})  # fmt: skip
    runs, start = _starter(dg.Wire(_Answers(), usages=[CACHED] * 40))
    ip.run_library(
        repo, live=start, root=tmp_path / "live", isolation=dg.REQUIRED,
        recorder=recorder, policy=og.LOCAL, base=_base(), reader=repo_reader,
    )  # fmt: skip
    (run,) = runs
    assert run.cap_usd == plan.library_cap(repo.name)
    lines = [json.loads(x) for x in results.read_text("utf-8").splitlines()]
    kinds = Counter(x["experiment"] for x in lines)
    assert kinds[ip.ROW_EXPERIMENT] == 3 and kinds[ip.AUDIT_EXPERIMENT] > 0
    ideas = [x for x in lines if x["experiment"] == ip.IDEA_EXPERIMENT]
    assert {x["arm"] for x in ideas} == {"A", "X1-0", "X1-3"}
    assert all(x["target"] is not None for x in ideas if x["arm"] != "A")
    rows = {x["arm"]: x for x in lines if x["experiment"] == ip.ROW_EXPERIMENT}
    assert rows["X1-3"]["views"] == {k.value: v for k, v in ip.X1_VIEWS.items()}
    assert rows["X1-0"]["views"] == {} and rows["X1-3"]["lever"]
