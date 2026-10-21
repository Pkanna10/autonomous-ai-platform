# Autonomous AI Agents - Python Service

The improvement engine: a LangGraph orchestrator that measures a baseline, runs
hypotheses as trials, judges them against frozen evaluators and delivers only
proven wins. See the root [README](../../README.md) for the vision and
[CLAUDE.md](./CLAUDE.md) for the engine design.

## Project Structure

```
services/python_agents/
├── src/autonomous_ai_agents/
│   ├── common/          # config.py (settings), models.py (data model), paths.py
│   ├── orchestrator/    # state.py, nodes.py, main.py (graph + Orchestrator), events.py
│   ├── optimization/    # anticheat.py, judges.py, ranking.py
│   ├── execution/       # TrialRunner protocol, StubTrialRunner
│   ├── learning/        # lessons.py
│   ├── persistence/     # Repository protocol, InMemoryRepository
│   └── research/        # arXiv monitor, PDF parser (placeholders until Step 3)
├── tests/               # mirrors src/; conftest.py holds shared fixtures
├── pyproject.toml       # uv, Hatchling, ruff, mypy strict, pytest, coverage
└── langgraph.json       # LangGraph entry point (create_graph)
```

## Quick Start

```bash
cd services/python_agents
uv sync --extra dev
cp ../../.env.example ../../.env      # add ANTHROPIC_API_KEY (not needed for tests)
uv run pytest
```

## Usage (Step 1: scripted run)

The skeleton runs the whole loop on deterministic stub data. A real runner,
profiler and research arrive in Steps 2 to 4 behind the same interfaces.

```python
from autonomous_ai_agents.common.models import (
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
from autonomous_ai_agents.optimization.judges import default_judges
from autonomous_ai_agents.orchestrator.main import Orchestrator
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.persistence.repository import InMemoryRepository

project = Project(name="demo", root_path="/abs/path/to/repo")
workload = Workload(
    project_id=project.id,
    name="train",
    command=("python", "train.py", "--steps", "200"),
    working_dir=".",
)
objective = Objective(
    kind=ObjectiveKind.runtime, metric="wall_time_s", direction=Direction.minimize
)
guardrails = [Guardrail(kind=GuardrailKind.tests_pass)]

# Until Step 2 the research node takes its candidates from the context and
# the runners replay scripted measurements instead of executing anything.
h1 = Hypothesis(
    project_id=project.id,
    title="Cache frozen-encoder embeddings",
    source=HypothesisSource.playbook,
    change_class=ChangeClass.efficiency,
    expected_gain=0.4,
    provability=0.9,
    risk=0.1,
)
context = NodeContext(
    runner=StubTrialRunner(
        {
            h1.title: ScriptedOutcome(
                touched_paths=("src/encoder.py",),
                samples={"wall_time_s": (1.05, 1.02, 1.08, 1.05, 1.05)},
                tests_passed=True,
            )
        }
    ),
    baseline_runner=StubBaselineRunner(
        ScriptedOutcome(
            samples={"wall_time_s": (1.80, 1.75, 1.85, 1.80, 1.80)},
            tests_passed=True,
        )
    ),
    judges=default_judges(),
    repository=InMemoryRepository(),
    candidates=(h1,),
)

engine = Orchestrator(context=context)
result = engine.run(project, [workload], [objective], guardrails)
print(result.status)  # done | needs_approval | failed
for verdict in result.state["verdicts"]:
    print(verdict.outcome, verdict.summary)  # keep  "... 41.7% faster ..."

if result.status == "needs_approval":  # a behaviour-changing hypothesis
    request = result.approval_request  # show it to the human
    result = engine.resume(result.run_id, decision_from_human)
```

Every node emits `EngineEvent`s; `engine.stream(...)` yields them live together
with state updates, which is what the Step 4 CLI log renders.

## Testing and Quality

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run pytest                                   # coverage >= 90% enforced
uv run pytest tests/orchestrator/test_graph_e2e.py -v
uv run pip-audit && uv run bandit -q -r src -c pyproject.toml
```

Tests run in parallel with pytest-xdist; use `uv run pytest -o addopts=""` for a
serial run.

## Dependencies

| Package        | Version          | Purpose                             |
| -------------- | ---------------- | ----------------------------------- |
| langgraph      | >=1.2,<2         | Orchestrator graph, checkpointing   |
| langchain      | >=1.4,<2         | LangChain core used by LangGraph    |
| anthropic      | >=1.17,<2        | Claude Messages API (Steps 2 and 3) |
| pydantic       | 2.x              | Frozen data model, settings         |
| structlog      | >=23             | Event logging outside a graph       |
| pymupdf, arxiv | `research` extra | Research (Step 3)                   |
| psycopg        | `database` extra | PostgreSQL repository (Step 2)      |

Dev: pytest, pytest-cov, pytest-xdist, mypy, ruff, pip-audit, bandit.

## Documentation

- [CLAUDE.md](./CLAUDE.md): engine design and conventions for this service
- [Root CLAUDE.md](../../CLAUDE.md): vision, build order, stage gate
- [STATUS.md](../../STATUS.md): development log and decisions

## License

ISC. See the root [LICENSE](../../LICENSE).
