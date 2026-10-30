"""The factory's idea-pipeline wiring and the lesson tags (Step 3 Wave 2,
N4b; amendment D43, D54, D57, 3.4, appendix C11).

With ``IDEA_PIPELINE`` off the factory builds today's generator at
``DISCOVERY_MAX_SHARE``; on, ``IdeaPipelineGenerator`` on the ``lane``,
``leap`` and ``reviewer`` transports (all three, or the build is refused by
name), today's generator as its no-code fallback, a reader of the project's
git objects, and ``IDEAS_DISCOVERY_MAX_SHARE``. ``PORTFOLIO_ROUNDS`` is
passed either way. Lessons gain the hypothesis's tags in ``context`` only.

Nothing here talks to the Claude API: a key is a fake ``SecretStr`` and
every transport a ``ScriptedTransport`` on its role's settings (standing for
``AnthropicTransport``). The last test runs the hypotheses node of a
factory-built context on a real git repository (the factory's
``GitWorkspace`` is the real reader) with scripted replies for every stage.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import cast

import pytest
from pydantic import SecretStr

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import (
    LLMTransport,
    ScriptedReply,
    ScriptedTransport,
)
from autonomous_ai_agents.common.config import (
    Role,
    Settings,
    role_chain,
    role_settings,
    settings,
)
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Direction,
    EngineEvent,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Objective,
    ObjectiveKind,
    Project,
    Verdict,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.protocols import CodeEditor, EditResult, EditTask
from autonomous_ai_agents.learning.lessons import (
    lesson_from_verdict,
    lessons_from_verdicts,
)
from autonomous_ai_agents.optimization.hypothesis_source import (
    ClaudeHypothesisGenerator,
)
from autonomous_ai_agents.optimization.idea_pipeline import (
    NO_CODE_CONTEXT,
    IdeaPipelineGenerator,
)
from autonomous_ai_agents.optimization.idea_types import LENS_LANES
from autonomous_ai_agents.orchestrator import factory
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.nodes import NodeContext, make_nodes
from autonomous_ai_agents.orchestrator.state import initial_state

FAKE_KEY = "sk-ant-test-not-a-real-key-0000"  # nosec B105: a test value
SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"
PIPELINE_ROLES: tuple[Role, ...] = ("lane", "leap", "reviewer")
Calls = list[tuple[tuple[object, ...], dict[str, object]]]


@pytest.fixture(autouse=True)
def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    base = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", base / "wt-root")
    (base / "user").mkdir()
    return Project(id="p1", name="texttools", root_path=str(base / "user"))


@pytest.fixture
def pipeline_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "IDEA_PIPELINE", True)
    monkeypatch.setattr(settings, "PORTFOLIO_ROUNDS", 2)


def _on(role: Role, replies: Sequence[ScriptedReply] = ()) -> ScriptedTransport:
    return ScriptedTransport(replies, cfg=role_settings(settings, role))


def _no_factory(cfg: Settings) -> LLMTransport:
    raise AssertionError("an injected engine transport means no transport is built")


def _spy(monkeypatch: pytest.MonkeyPatch, name: str) -> Calls:
    """Replace ``factory.<name>`` by a wrapper recording each call's arguments."""
    seen: Calls = []
    real = getattr(factory, name)

    def recording(*args: object, **kwargs: object) -> object:
        seen.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(factory, name, recording)
    return seen


class _NeverEdits:
    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        raise AssertionError("no trial runs here")


def _no_edits(
    *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
) -> CodeEditor:
    return _NeverEdits()


# ---------------------------------------------------------------------------
# Off: today's generator, today's share; PORTFOLIO_ROUNDS either way
# ---------------------------------------------------------------------------


def test_with_the_pipeline_off_the_factory_builds_todays_generator(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a key, ``IDEA_PIPELINE`` off and ``PORTFOLIO_ROUNDS=2``
    WHEN the factory builds the context
    THEN today's generator at share 0.25, the rounds passed, and no
         transport built for a pipeline role
    """
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))
    monkeypatch.setattr(settings, "PORTFOLIO_ROUNDS", 2)
    built: list[Settings] = []

    def make(cfg: Settings) -> LLMTransport:
        built.append(cfg)
        return ScriptedTransport([], cfg=cfg)

    pipelines = _spy(monkeypatch, "IdeaPipelineGenerator")
    ctx = build_context(project, transport_factory=make)

    assert isinstance(ctx.generator, ClaudeHypothesisGenerator)
    assert ctx.discovery_max_share == 0.25 and ctx.portfolio_rounds == 2
    assert built == [settings, *(role_settings(settings, r) for r in
                                 ("editor", "generator"))]  # fmt: skip
    assert not pipelines


def test_with_the_pipeline_off_given_pipeline_transports_are_accepted_unused(
    project: Project,
) -> None:
    """A harness may wire the three roles on both arms; off, they are unused."""
    given: dict[Role, LLMTransport] = {r: _on(r) for r in PIPELINE_ROLES}
    ctx = build_context(project, transport=ScriptedTransport([]), role_transports=given)
    assert ctx.generator is None and ctx.portfolio_rounds == 0


# ---------------------------------------------------------------------------
# On: the pipeline on three role transports, all or refuse
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("pipeline_on")
def test_with_a_key_the_pipeline_gets_each_role_transport_from_its_settings(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a key and ``IDEA_PIPELINE`` on
    WHEN the factory builds the context
    THEN each pipeline role's transport is built from ``role_settings``, the
         pipeline gets them with today's generator as its fallback, the
         settings and the backoff, and the share is 0.40
    """
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))
    made: list[tuple[Settings, ScriptedTransport]] = []

    def make(cfg: Settings) -> LLMTransport:
        transport = ScriptedTransport([], cfg=cfg)
        made.append((cfg, transport))
        return transport

    def nap(seconds: float) -> None:
        raise AssertionError("no test here backs off")

    pipelines = _spy(monkeypatch, "IdeaPipelineGenerator")
    todays = _spy(monkeypatch, "ClaudeHypothesisGenerator")
    ctx = build_context(project, transport_factory=make, sleep=nap)

    assert isinstance(ctx.generator, IdeaPipelineGenerator)
    ((args, kwargs),) = pipelines
    transports = cast(Mapping[Role, LLMTransport], args[0])
    order: tuple[Role, ...] = ("editor", "generator", *PIPELINE_ROLES)
    assert [cfg for cfg, _ in made] == [
        settings, *(role_settings(settings, r) for r in order)
    ]  # fmt: skip
    built = {role: made[1 + i][1] for i, role in enumerate(order)}
    assert set(transports) == set(PIPELINE_ROLES)
    for role in PIPELINE_ROLES:
        assert transports[role] is built[role]
        assert tuple(transports[role].chain) == role_chain(settings, role)
    ((today_args, today_kwargs),) = todays
    assert today_args[0] is built["generator"]
    assert len({id(t) for _, t in made}) == len(made) == 6
    assert isinstance(kwargs["fallback"], ClaudeHypothesisGenerator)
    assert kwargs["config"] is settings and kwargs["sleep"] is nap
    assert today_kwargs["sleep"] is nap
    assert callable(kwargs["reader"])
    assert ctx.discovery_max_share == settings.IDEAS_DISCOVERY_MAX_SHARE == 0.40
    assert ctx.portfolio_rounds == 2


@pytest.mark.usefixtures("pipeline_on")
def test_given_pipeline_transports_are_used_and_the_reader_reads_the_project(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller's captured transports go to the pipeline as given; its
    reader is a ``GitWorkspace`` on the project's checkout."""
    given: dict[Role, LLMTransport] = {r: _on(r) for r in PIPELINE_ROLES}
    given["generator"] = _on("generator")
    pipelines = _spy(monkeypatch, "IdeaPipelineGenerator")

    build_context(
        project,
        transport=ScriptedTransport([]),
        role_transports=given,
        transport_factory=_no_factory,
    )

    ((args, kwargs),) = pipelines
    transports = cast(Mapping[Role, LLMTransport], args[0])
    assert {r: transports[r] for r in PIPELINE_ROLES} == {
        r: given[r] for r in PIPELINE_ROLES
    }
    reader = kwargs["reader"]
    assert callable(reader)
    git = reader(project)
    assert isinstance(git, GitWorkspace)
    assert git.repo == Path(os.path.realpath(project.root_path))


@pytest.mark.usefixtures("pipeline_on")
@pytest.mark.parametrize("role", PIPELINE_ROLES)
def test_a_pipeline_transport_on_another_chain_is_refused(
    project: Project, role: Role
) -> None:
    given: dict[Role, LLMTransport] = {r: _on(r) for r in PIPELINE_ROLES}
    given[role] = ScriptedTransport([])  # the engine chain
    with pytest.raises(ValueError, match=f"the {role} transport bills"):
        build_context(project, transport=ScriptedTransport([]), role_transports=given)


@pytest.mark.usefixtures("pipeline_on")
@pytest.mark.parametrize("missing", PIPELINE_ROLES)
def test_an_injected_engine_transport_without_a_pipeline_transport_is_refused(
    project: Project, monkeypatch: pytest.MonkeyPatch, missing: Role
) -> None:
    """
    GIVEN an injected engine transport (a captured run, even with a key) and
          every pipeline role but one wired
    WHEN the factory builds the context
    THEN the build is refused naming the missing role: never today's
         generator, never no generator, never a transport built from the key
    """
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))
    given: dict[Role, LLMTransport] = {
        r: _on(r) for r in (*PIPELINE_ROLES, "generator") if r != missing
    }
    with pytest.raises(ValueError, match=f"needs a {missing} transport"):
        build_context(
            project,
            transport=ScriptedTransport([]),
            role_transports=given,
            transport_factory=_no_factory,
        )


@pytest.mark.usefixtures("pipeline_on")
def test_without_a_key_or_any_transport_the_pipeline_is_refused_by_name(
    project: Project,
) -> None:
    """An injected editor and no key: the first pipeline role is named."""
    with pytest.raises(ValueError, match="needs a lane transport"):
        build_context(project, editor=_no_edits)


@pytest.mark.usefixtures("pipeline_on")
def test_without_a_generator_transport_the_pipeline_has_no_fallback(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The three pipeline roles wired and no generator's: the pipeline is
    built with no fallback (its no-code path returns nothing, noted)."""
    given: dict[Role, LLMTransport] = {r: _on(r) for r in PIPELINE_ROLES}
    pipelines = _spy(monkeypatch, "IdeaPipelineGenerator")
    ctx = build_context(project, transport=ScriptedTransport([]), role_transports=given)
    assert isinstance(ctx.generator, IdeaPipelineGenerator)
    assert pipelines[0][1]["fallback"] is None


# ---------------------------------------------------------------------------
# Lessons: the hypothesis's tags join the context, never the text (D57)
# ---------------------------------------------------------------------------


def _hypothesis(tags: tuple[str, ...] = ()) -> Hypothesis:
    return Hypothesis(
        project_id="p1",
        source=HypothesisSource.novel,
        title="Use a frozenset for the keywords",
        rationale="generated",
        change_class=ChangeClass.efficiency,
        expected_gain=0.1,
        provability=0.5,
        risk=0.1,
        tags=tags,
    )


def _verdict(hypothesis: Hypothesis) -> Verdict:
    return Verdict(
        trial_id="t",
        hypothesis_id=hypothesis.id,
        outcome=VerdictOutcome.keep,
        change_class=hypothesis.change_class,
        summary="s",
        gain=0.12,
    )


TAGS = ("lane:far", "review:feasible", "claimed_tier:transformational", "cpu")


def test_a_lesson_merges_the_tags_into_its_context_sorted_and_deduplicated() -> None:
    hypothesis = _hypothesis()
    lesson = lesson_from_verdict(
        _verdict(hypothesis),
        hypothesis,
        project_id="p1",
        context=("python", "cpu"),
        extra_context=TAGS,
    )
    assert lesson.context == (
        "claimed_tier:transformational", "cpu", "lane:far", "python",
        "review:feasible",
    )  # fmt: skip
    assert lesson.text == (
        "python, cpu -> Use a frozenset for the keywords: keep (+12.0%)"
    )


def test_a_lesson_without_tags_is_unchanged() -> None:
    hypothesis = _hypothesis()
    verdict = _verdict(hypothesis)
    plain = lesson_from_verdict(
        verdict, hypothesis, project_id="p1", context=("python", "cpu")
    )
    empty = lesson_from_verdict(
        verdict, hypothesis, project_id="p1", context=("python", "cpu"),
        extra_context=(),
    )  # fmt: skip
    assert plain.model_dump(exclude={"created_at"}) == empty.model_dump(
        exclude={"created_at"}
    )
    assert plain.context == ("python", "cpu")


def test_lessons_from_verdicts_passes_each_hypothesis_its_own_tags() -> None:
    tagged, plain = _hypothesis(TAGS[:2]), _hypothesis()
    lessons = lessons_from_verdicts(
        [_verdict(tagged), _verdict(plain)],
        {tagged.id: tagged, plain.id: plain},
        project_id="p1",
        context=("python",),
    )
    assert [lesson.context for lesson in lessons] == [
        ("lane:far", "python", "review:feasible"),
        ("python",),
    ]
    assert lessons[0].text.startswith("python -> ")


# ---------------------------------------------------------------------------
# A factory-built run reaches the pipeline's stages (not the fallback)
# ---------------------------------------------------------------------------

PATH = "pkg/text.py"
SOURCE = '''"""Text tools."""

KEYWORDS = ("if", "else", "while", "for", "return")


def parse_tokens(text, keywords=KEYWORDS):
    found = []
    for word in text.split():
        if word.strip().casefold() in keywords:
            found.append(word.upper())
    return found


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
'''
QUOTES = {
    "parse_tokens": "if word.strip().casefold() in keywords:",
    "merge_runs": "for item in sorted(items):",
    "join_lines": 'result = result + line + "\\n"',
}
USAGE = {"input_tokens": 3000, "output_tokens": 900}


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed git arguments, a test repository
        [settings.GIT_EXECUTABLE, "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def _commit(root: Path) -> str:
    (root / "pkg").mkdir()
    (root / PATH).write_text(SOURCE, encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "-m", "base")  # fmt: skip
    return _git(root, "rev-parse", "HEAD")


def _message(payload: dict[str, object], model: str) -> dict[str, object]:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": "end_turn", "stop_sequence": None, "usage": dict(USAGE),
    }  # fmt: skip


def _idea(title: str, symbol: str, mechanism: str, cell: str) -> dict[str, object]:
    return {
        "title": title, "technique_slug": None,
        "hotspots": [{"file_path": PATH, "symbol": symbol}],
        "change_summary": f"Change {symbol} as the title says.",
        "justification_summary": f"{symbol} holds a third of the time.",
        "depends_on_path": PATH, "depends_on_quote": QUOTES[symbol],
        "precondition": "the inputs are plain strings",
        "equivalence_summary": "the same values come out in the same order",
        "mechanism": mechanism, "morph_cells": [cell], "tier": "combinational",
        "typicality": "uncommon", "change_class": "efficiency",
        "expected_gain": 0.2, "provability": 0.8, "risk": 0.1,
    }  # fmt: skip


OBVIOUS = _idea("Use a frozenset for the keywords", "parse_tokens",
                "data_structure", "representation:indexed")  # fmt: skip
ELIMINATE = _idea("Skip the sort when items arrive sorted", "merge_runs",
                  "remove_work", "work:eliminate")  # fmt: skip
REVIEWS = [
    {"idea": idea, "verdict": "feasible", "reason": "none", "duplicate_of": None,
     "change_plan": f"Edit {idea} in turn."}
    for idea in ("obvious-01", "eliminate-01")
]  # fmt: skip


def _hotspots(project: Project, workload: Workload) -> list[Hotspot]:
    return [
        Hotspot(
            id=f"h-{name}", project_id=project.id, workload_id=workload.id,
            file_path=PATH, symbol=name, self_time_s=1.0, total_time_s=2.0,
            share=0.1,
        )
        for name in QUOTES
    ]  # fmt: skip


@pytest.mark.usefixtures("pipeline_on")
def test_a_factory_built_run_sends_every_stage_on_scripted_replies(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a real git repository, ``IDEA_PIPELINE`` on with one lane worker,
          and scripted replies for S1, the six lenses, the leap and the
          reviewer on the captured role transports
    WHEN the hypotheses node of the factory-built context runs at the base
         commit
    THEN the pipeline reads the code at the commit and sends every stage
         (seven lane requests, one leap, one review), never today's
         generator; the S1 and the lens idea come back tagged with their
         lane and verdict; one generator call is counted
    """
    monkeypatch.setattr(settings, "IDEAS_LANE_WORKERS", 1)
    root = Path(project.root_path)
    sha = _commit(root)
    lens = [
        _message({"hypotheses": [ELIMINATE] if lane.value == "eliminate" else []},
                 SONNET)
        for lane in settings.IDEAS_LENSES
    ]  # fmt: skip
    transports: dict[Role, ScriptedTransport] = {
        "lane": _on("lane", [_message({"hypotheses": [OBVIOUS]}, SONNET), *lens]),
        "leap": _on("leap", [_message({"hypotheses": []}, OPUS)]),
        "reviewer": _on("reviewer", [_message({"reviews": REVIEWS}, OPUS)]),
        "generator": _on("generator"),
    }
    ctx: NodeContext = build_context(
        project,
        transport=ScriptedTransport([]),
        role_transports=dict(transports),
        transport_factory=_no_factory,
    )
    workload = Workload(
        project_id=project.id, name="w", command=("python", "-c", "pass")
    )
    objective = Objective(
        project_id=project.id, kind=ObjectiveKind.runtime, metric="wall_time_s",
        direction=Direction.minimize, min_relative_gain=0.043,
        description="make the text tools faster",
    )  # fmt: skip
    state = initial_state(project, [workload], [objective], [], run_id="run-n4b",
                          max_rounds=3, max_cost_usd=10.0)  # fmt: skip
    state["base_commit"] = sha
    state["hotspots"] = _hotspots(project, workload)

    delta = make_nodes(ctx)["hypotheses"](state)

    assert len(transports["lane"].requests) == 1 + len(LENS_LANES)
    assert len(transports["leap"].requests) == 1
    assert len(transports["reviewer"].requests) == 1
    assert transports["generator"].requests == []
    assert all(t.remaining == 0 for t in transports.values())
    lanes_seen = transports["lane"].requests[0].messages[0]["content"]
    assert "def parse_tokens" in json.dumps(lanes_seen)  # the code at the commit
    events = cast(list[EngineEvent], delta["events"])
    assert not any(NO_CODE_CONTEXT in event.message for event in events)
    ideas = cast(list[Hypothesis], delta["hypotheses"])
    ideas += cast(list[Hypothesis], delta.get("candidate_pool", []))
    tags = {h.title: h.tags for h in ideas}
    assert set(tags) == {OBVIOUS["title"], ELIMINATE["title"]}
    assert {"lane:obvious", "review:feasible"} <= set(tags[str(OBVIOUS["title"])])
    assert {"lane:eliminate", "review:feasible"} <= set(tags[str(ELIMINATE["title"])])
    assert delta["generator_calls"] == 1
