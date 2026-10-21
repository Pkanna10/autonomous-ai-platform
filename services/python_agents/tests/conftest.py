"""Shared pytest fixtures: the Step 1 walking-skeleton scenario.

The engine loop is tested end to end on deterministic stub data: one project,
one workload, a runtime objective, two guardrails, a scripted baseline and
the four design hypotheses from the Step 1 briefing. Each hypothesis has a
scripted outcome keyed by its *title*, which ``StubTrialRunner`` looks up when
the id-keyed script is absent, so fresh hypothesis ids never matter.

| Hypothesis | Scripted outcome                                  | Verdict        |
| ---------- | ------------------------------------------------- | -------------- |
| H1         | 1.05 s, tests pass, touched src/bridge/encoder.py | keep           |
| H2         | 1.20 s, tests pass, touched tests/test_cache.py   | reject         |
| H3         | 1.76 s (inside the noise floor)                   | inconclusive   |
| H4         | 1.50 s, val_loss +0.6 %, behaviour change         | needs_approval |

Baseline ``wall_time_s``: n=5, mean 1.80, stdev 0.035; noise floor 0.071 s.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Protocol

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver

from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    ChangeClass,
    Direction,
    Guardrail,
    GuardrailKind,
    Hypothesis,
    HypothesisSource,
    Objective,
    ObjectiveKind,
    Project,
    Workload,
)
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization.anticheat import fingerprint
from autonomous_ai_agents.optimization.judges import default_judges
from autonomous_ai_agents.orchestrator.main import (
    EngineGraph,
    build_checkpointer,
    create_graph,
)
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.persistence.repository import InMemoryRepository

VAL_LOSS = "val_loss"
BASELINE_FINGERPRINT = fingerprint("baseline")

H1_TITLE = "Cache frozen-encoder embeddings"
H2_TITLE = "Skip the cache test to save time"
H3_TITLE = "Micro-tweak the collate loop"
H4_TITLE = "Run the encoder under bf16 autocast"

BASELINE_SCRIPT = ScriptedOutcome(
    samples={
        METRIC_WALL_TIME_S: (1.80, 1.75, 1.85, 1.80, 1.80),
        VAL_LOSS: (0.500,) * 5,
    },
    tests_passed=True,
    output_fingerprint=BASELINE_FINGERPRINT,
)

DESIGN_SCRIPTS: dict[str, ScriptedOutcome] = {
    H1_TITLE: ScriptedOutcome(
        touched_paths=("src/bridge/encoder.py",),
        samples={
            METRIC_WALL_TIME_S: (1.05, 1.02, 1.08, 1.05, 1.05),
            VAL_LOSS: (0.500,) * 5,
        },
        output_fingerprint=BASELINE_FINGERPRINT,
        tests_passed=True,
        cost_usd=0.12,
        tokens_used=3400,
    ),
    H2_TITLE: ScriptedOutcome(
        touched_paths=("tests/test_cache.py",),
        samples={
            METRIC_WALL_TIME_S: (1.20, 1.18, 1.22, 1.20, 1.20),
            VAL_LOSS: (0.500,) * 5,
        },
        output_fingerprint=BASELINE_FINGERPRINT,
        tests_passed=True,
        cost_usd=0.08,
        tokens_used=2100,
    ),
    H3_TITLE: ScriptedOutcome(
        touched_paths=("src/bridge/collate.py",),
        samples={
            METRIC_WALL_TIME_S: (1.76, 1.73, 1.79, 1.76, 1.76),
            VAL_LOSS: (0.500,) * 5,
        },
        output_fingerprint=BASELINE_FINGERPRINT,
        tests_passed=True,
        cost_usd=0.05,
        tokens_used=1200,
    ),
    H4_TITLE: ScriptedOutcome(
        touched_paths=("src/bridge/train.py",),
        samples={
            METRIC_WALL_TIME_S: (1.50, 1.48, 1.52, 1.50, 1.50),
            VAL_LOSS: (0.503,) * 5,
        },
        output_fingerprint=BASELINE_FINGERPRINT,
        tests_passed=True,
        cost_usd=0.10,
        tokens_used=2800,
    ),
}
"""Scripted outcomes of the four design hypotheses, keyed by title."""


class ContextFactory(Protocol):
    """Builds a ``NodeContext`` over stub runners for the given candidates."""

    def __call__(
        self,
        candidates: Sequence[Hypothesis] = (),
        scripts: Mapping[str, ScriptedOutcome] | None = None,
        **overrides: Any,
    ) -> NodeContext: ...


class GraphFactory(Protocol):
    """Compiles the engine graph for a context, with a checkpointer."""

    def __call__(
        self,
        context: NodeContext,
        checkpointer: BaseCheckpointSaver[str] | None = None,
    ) -> EngineGraph: ...


# ---------------------------------------------------------------------------
# Project, workload, objective, guardrails
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_project() -> Project:
    """The VLM bridge project from the briefing."""
    return Project(name="bridge", root_path="/home/dev/bridge")


@pytest.fixture
def sample_workload(sample_project: Project) -> Workload:
    """One training-step workload."""
    return Workload(
        project_id=sample_project.id,
        name="train-step",
        command=("python", "train.py", "--steps", "20"),
    )


@pytest.fixture
def sample_objective(sample_project: Project) -> Objective:
    """Minimize wall time, at least 2 % better to count."""
    return Objective(
        project_id=sample_project.id,
        kind=ObjectiveKind.runtime,
        metric=METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        min_relative_gain=0.02,
        description="minimize seconds per training step",
    )


@pytest.fixture
def sample_guardrails(sample_project: Project) -> tuple[Guardrail, Guardrail]:
    """Tests must pass and val_loss may drop at most 1 %."""
    return (
        Guardrail(
            project_id=sample_project.id,
            kind=GuardrailKind.tests_pass,
            description="existing tests must pass",
        ),
        Guardrail(
            project_id=sample_project.id,
            kind=GuardrailKind.metric_bound,
            metric=VAL_LOSS,
            max_drop=0.01,
            direction=Direction.minimize,
            description="val_loss may get at most 1% worse",
        ),
    )


@pytest.fixture
def baseline_script() -> ScriptedOutcome:
    """What the stub baseline runner measures for every workload."""
    return BASELINE_SCRIPT


@pytest.fixture
def design_scripts() -> dict[str, ScriptedOutcome]:
    """The four design hypotheses' scripted outcomes, keyed by title."""
    return dict(DESIGN_SCRIPTS)


# ---------------------------------------------------------------------------
# The four design hypotheses
# ---------------------------------------------------------------------------


def _hypothesis(
    project: Project,
    title: str,
    change_class: ChangeClass,
    *,
    expected_gain: float,
    provability: float,
    risk: float,
) -> Hypothesis:
    return Hypothesis(
        project_id=project.id,
        source=HypothesisSource.playbook,
        title=title,
        rationale=f"{title}: scripted for the walking skeleton",
        change_class=change_class,
        expected_gain=expected_gain,
        provability=provability,
        risk=risk,
    )


@pytest.fixture
def h1_cache(sample_project: Project) -> Hypothesis:
    """H1: efficiency change that wins cleanly (keep)."""
    return _hypothesis(
        sample_project,
        H1_TITLE,
        ChangeClass.efficiency,
        expected_gain=0.4,
        provability=0.9,
        risk=0.1,
    )


@pytest.fixture
def h2_protected(sample_project: Project) -> Hypothesis:
    """H2: faster, but it edits a test file (reject: protected_path)."""
    return _hypothesis(
        sample_project,
        H2_TITLE,
        ChangeClass.efficiency,
        expected_gain=0.3,
        provability=0.8,
        risk=0.2,
    )


@pytest.fixture
def h3_noise(sample_project: Project) -> Hypothesis:
    """H3: gain inside the noise floor (inconclusive)."""
    return _hypothesis(
        sample_project,
        H3_TITLE,
        ChangeClass.efficiency,
        expected_gain=0.05,
        provability=0.7,
        risk=0.1,
    )


@pytest.fixture
def h4_behaviour(sample_project: Project) -> Hypothesis:
    """H4: behaviour-changing win within the guardrail (needs_approval)."""
    return _hypothesis(
        sample_project,
        H4_TITLE,
        ChangeClass.behaviour,
        expected_gain=0.2,
        provability=0.8,
        risk=0.3,
    )


# ---------------------------------------------------------------------------
# Context, repository and graph factories
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_repo() -> InMemoryRepository:
    """A fresh repository the test can inspect afterwards."""
    return InMemoryRepository()


@pytest.fixture
def make_context(
    baseline_script: ScriptedOutcome, in_memory_repo: InMemoryRepository
) -> ContextFactory:
    """Return a factory for ``NodeContext`` over stub runners.

    ``candidates`` stand in for research output; ``scripts`` (default: the
    design scripts) feed the stub trial runner; keyword ``overrides`` replace
    any other ``NodeContext`` field. The repository is ``in_memory_repo``.
    """

    def factory(
        candidates: Sequence[Hypothesis] = (),
        scripts: Mapping[str, ScriptedOutcome] | None = None,
        **overrides: Any,
    ) -> NodeContext:
        base = NodeContext(
            runner=StubTrialRunner(
                dict(DESIGN_SCRIPTS if scripts is None else scripts)
            ),
            baseline_runner=StubBaselineRunner(baseline_script),
            judges=default_judges(),
            repository=in_memory_repo,
            candidates=tuple(candidates),
        )
        return replace(base, **overrides)

    return factory


@pytest.fixture
def engine_graph() -> GraphFactory:
    """Return a factory compiling the engine graph with a checkpointer.

    ``checkpointer`` defaults to a fresh ``build_checkpointer()``; pass one
    to share it between graph instances.
    """

    def factory(
        context: NodeContext,
        checkpointer: BaseCheckpointSaver[str] | None = None,
    ) -> EngineGraph:
        saver = build_checkpointer() if checkpointer is None else checkpointer
        return create_graph(saver, context=context)

    return factory


# ---------------------------------------------------------------------------
# Environment and legacy fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_arxiv_paper() -> dict[str, Any]:
    """Sample arXiv paper metadata for the research placeholders."""
    return {
        "id": "2301.12345",
        "title": "HyperLogLog: A Practical Algorithm for Streaming Aggregation",
        "authors": ["Author One", "Author Two"],
        "abstract": "This paper presents a novel approach to streaming aggregation...",
        "published": "2023-01-15",
        "categories": ["cs.DS", "cs.DB"],
    }


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the environment variables so tests never leak host configuration."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-12345")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test_db")
