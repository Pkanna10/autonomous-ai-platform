# Python Agents Service - Claude Code Configuration

**Service:** `python_agents` **Version:** 4.1.0 **Primary Language:** Python
3.11+ **Framework:** LangGraph 1.x **Testing:** pytest **Key Libraries:**
langgraph, langchain, anthropic (1.x), pydantic 2, pydantic-settings, structlog

The root `CLAUDE.md` holds the vision, the build order and the stage gate. This
file holds what is specific to the Python engine: its design, its conventions
and the LangGraph gotchas already verified.

---

## Service Purpose

Home of the improvement engine: the LangGraph orchestrator loop (L2), research
(L4), the local execution layer (L5), optimization judges (L6) and the lessons
store (L7). Persistence talks to PostgreSQL through `infrastructure/schema/`.

**Current state (Step 1, walking skeleton):** every node of the engine loop is
wired and runs end to end on deterministic stub data. Data models, anti-cheating
rules, judges, the verdict order, ranking, lessons, the approval interrupt and
durable resume are final. The runner, profiler, research and LLM understanding
are stubs that Steps 2 to 4 replace behind interfaces that do not change.

Models come from settings, never from string literals: `settings.ENGINE_MODEL`
(default `claude-opus-5-5`) and `settings.TRIAGE_MODEL` (default
`claude-haiku-5-5`). Engine knobs live next to them: `MIN_RUNS=5`,
`NOISE_MULTIPLIER=2.0`, `MIN_RELATIVE_GAIN=0.02`, `MAX_TRIAL_ROUNDS=3`,
`MAX_COST_USD=5.0`, `TRIAL_BRANCH_PREFIX="engine/"`.

---

## Engine Design

### The loop as a graph

```
START -> connect -> understand -> define -> baseline -> profile -> research
      -> hypotheses -> trials -> judges -> verdicts --(after_verdicts)--+
             ^                                                         |
             |  no keep and round < max_rounds                         |
             +---------------------------------------------------------+
                                                                       |
     END <- watch <- learn <- deliver <- combine <- approval_gate <----+
                                            ^      (interrupt(): human |
                                            |       decides)           |
                                            +--------------------------+
                                              keep only, or nothing pending

Frozen, outside the state (trial code cannot touch them):
  judges, protected-path patterns, the noise rule, output fingerprints
```

`after_verdicts` routes to `approval_gate` when any verdict `needs_approval`, to
`combine` when at least one verdict is `keep` (and nothing is pending), and back
to `hypotheses` for another round when nothing was kept, `round < max_rounds`
and an untrialled candidate remains. A gate decision always proceeds to
`combine`, so a run ends with a report even when nothing is kept.

### Package map

| Package         | Layer | What it holds                                                     |
| --------------- | ----- | ----------------------------------------------------------------- |
| `common/`       | all   | `config.py` settings, `models.py` data model, `paths.py` helpers  |
| `orchestrator/` | L2    | `state.py`, `nodes.py`, `main.py` (graph, `Orchestrator`), events |
| `research/`     | L4    | arXiv monitor and PDF parser (placeholders until Step 3)          |
| `execution/`    | L5    | `TrialRunner` protocol, `StubTrialRunner`                         |
| `optimization/` | L6    | `anticheat.py`, `judges.py`, `ranking.py`                         |
| `learning/`     | L7    | `lessons.py` (verdict -> lesson)                                  |
| `persistence/`  | DB    | `Repository` protocol, `InMemoryRepository`                       |

### State (`orchestrator/state.py`)

`EngineState` is the TypedDict LangGraph checkpoints between nodes. Two rules
every node follows:

1. **Delta-only on reducer channels.** `trials`, `verdicts`, `lessons` and
   `events` (`REDUCER_KEYS`) are `Annotated[list, operator.add]`. A node returns
   only the new items; returning the full list duplicates it. Every other key is
   replaced wholesale.
2. **Every key is always present.** LangGraph omits keys that were never set, so
   `initial_state(project, workloads, objectives, guardrails)` sets all of them
   and nodes index the state directly instead of using `.get`.
3. **The state is the only source of truth inside a run.** `round_trials` holds
   the current round's trials (replaced each round): `trials` writes them
   unjudged, `judges` writes the judged copies there and appends them to the
   `trials` channel, `verdicts` reads them. The `Repository` is an audit sink;
   the only node that reads from it is `hypotheses` (lessons).

### Data model (`common/models.py`)

Every model extends `EngineModel`: pydantic v2, `frozen=True`, `extra="forbid"`.
Ids are `new_id()` (uuid4 strings), timestamps are tz-aware UTC (`utc_now()`),
collections inside models are tuples, and enums are `StrEnum` whose values match
the SQL `CHECK` lists in `003_engine.sql` verbatim. Update a frozen model with
`model_copy(update=...)`.

| Group       | Models                                                                 |
| ----------- | ---------------------------------------------------------------------- |
| Input       | `Project`, `Workload` (argv tuple, never a shell string), `Objective`, |
|             | `Guardrail`                                                            |
| Measurement | `RunStats` (`from_samples`), `Measurement` (fingerprint), `Baseline`   |
| Research    | `Hotspot`, `Precondition`, `Technique`, `Claim`, `Paper` (https only)  |
| Trial       | `Hypothesis`, `Trial`, `JudgeResult`, `Violation`, `Verdict`,          |
|             | `NoiseCheck`                                                           |
| Output      | `Delivery`, `Lesson`, `ApprovalRequest`, `ApprovalDecision`,           |
|             | `EngineEvent`                                                          |

`ENGINE_SERDE_ALLOWLIST` lists every model and enum class; the checkpointer's
`JsonPlusSerializer(allowed_msgpack_modules=...)` needs it, and a reflection
test fails when a new model is not added.

### Anti-cheating (`optimization/anticheat.py`, pure functions)

- `DEFAULT_PROTECTED_PATTERNS`: tests, benchmarks, `conftest.py`,
  `pyproject.toml`, CI files, lockfiles and manifests, `.env*`,
  `sitecustomize.py` and `*.pth`. A trial diff touching any of them is a
  `Violation(protected_path)` and the verdict is `reject` whatever the judges
  say.
- `normalize_path` (in `common/paths.py`) rejects absolute paths, `~`, drive
  letters and any `..` segment (`path_traversal`).
- Noise rule:
  `noise_floor = max(2·σ_baseline, 2·σ_trial, min_relative_gain·|mean_baseline|)`
  and `exceeds_noise` requires the gain to exceed it strictly, on every
  workload. `check_run_count` enforces `MIN_RUNS` on objective metrics.
- Completeness: every objective and guardrail metric must be measured exactly
  once per workload, in the baseline (else the run fails) and in every trial
  (else `missing_measurement` / `duplicate_measurement` violations reject it). A
  trial cannot pass by leaving a metric out or by listing a fast or healthy
  duplicate first.
- `fingerprint` is sha256 of the workload output; `compare_fingerprints` pairs
  baseline and trial by workload and flags mismatches.

### Judges and the verdict order (`optimization/judges.py`)

```python
@runtime_checkable
class Judge(Protocol):
    @property
    def name(self) -> str: ...
    def applies_to(self, objective: Objective) -> bool: ...
    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult: ...
```

`default_judges()` returns `SpeedJudge`, `MemoryJudge`, `EquivalenceJudge`,
`GuardrailMetricJudge` and `TestSuiteJudge`. They are frozen dataclasses held in
the node context, never in the state, and they do no I/O: every number they see
was measured by the runner before they run.

`derive_verdict(trial, hypothesis, judge_results, violations)` is pure and
ordered:

1. any `Violation` -> `reject`
2. trial failed -> `reject`
3. any judge `failed` -> `reject`
4. primary-objective or guardrail judge `inconclusive` -> `inconclusive` (a
   secondary objective inside the noise is neutral)
5. no objective judge `passed` -> `inconclusive`
6. all pass: `efficiency` -> `keep`; `behaviour` or `novel` -> `needs_approval`

### Ranking and lessons

`optimization/ranking.py`:
`score = expected_gain × provability × (1 − risk) × (1 + lesson_boost)` with
`lesson_boost = clamp(0.1·keeps − 0.1·rejects, ≤ 0.5)` over lessons whose
context tags match. `learning/lessons.py` turns every verdict into a `Lesson`
("frozen encoder + repeated epochs -> cache embeddings: keep (+41.7%)");
approved verdicts count as keeps, rejected ones as rejects.

### Injection points

Nodes come from `make_nodes(ctx: NodeContext)`. `NodeContext` is a frozen
dataclass carrying the `TrialRunner`, the `BaselineRunner`, the judges, the
`Repository` and, until the research layer exists, the candidate hypotheses.
`default_context()` wires the stubs; tests build their own with scripted
outcomes, so every external effect is scripted:

- `execution/runner.py`:
  `TrialRunner.run(hypothesis, workloads, baseline, *, round, branch) -> Trial`
  and `BaselineRunner.measure(workloads) -> tuple[Measurement, ...]`.
  `StubTrialRunner` replays `ScriptedOutcome`s looked up by hypothesis id, then
  title, then a default; `StubBaselineRunner` replays one outcome.
- `persistence/repository.py`: `Repository` protocol (`save_run`, `get_run`,
  `save_trial`, `save_verdict`, `save_lesson`, `list_lessons`, `list_trials`,
  `list_verdicts`) and `InMemoryRepository`. The Step 2 PostgreSQL class uses
  `psycopg` with parameterised SQL and `model_dump_json()` into JSONB columns;
  there is no ORM and no second migration system.

`Orchestrator(context=..., checkpointer=...)` exposes
`run(project, workloads, objectives, guardrails, *, run_id=None, max_rounds=None) -> EngineRunResult`
(`run_id`, `status` of `done | needs_approval | failed`, final `state`,
`approval_request`), `resume(run_id, decision)` and `stream(...)`, which yields
each `EngineEvent` as the node emits it and ends with a `paused` event when the
run waits at the gate. `run` refuses a `run_id` that already has a thread,
`resume` refuses a run that is not waiting at the gate, and every result is
saved to the repository. An invalid approval payload re-interrupts with the
error on the request instead of failing the run.

### Live log (`orchestrator/events.py`)

Nodes call `emit(make_event(run_id, phase, message, data=...))`. Inside a graph
the event goes to LangGraph's custom stream; outside one (unit tests, scripts)
it is logged through structlog. `emit` never raises. Consumers use
`graph.stream(..., stream_mode=["custom", "updates"])`; an interrupt shows up as
`("updates", {"__interrupt__": ...})`.

---

## LangGraph 1.x Conventions (verified on 1.2.x)

- Imports: `StateGraph, START, END` from `langgraph.graph`;
  `interrupt, Command, GraphOutput` from `langgraph.types`; `InMemorySaver` from
  `langgraph.checkpoint.memory`; `JsonPlusSerializer` from
  `langgraph.checkpoint.serde.jsonplus`; `get_stream_writer` from
  `langgraph.config`.
- Node functions take one parameter named `state` and return a partial dict.
- Human-in-the-loop is a dynamic `interrupt(request.model_dump())` inside
  `approval_gate_node`, not `interrupt_before`. Code before `interrupt()` runs
  again on resume, so the gate only builds the request from state. The decision
  travels in `Command(resume=decision.model_dump())` and lands in
  `state["approval"]`.
- `create_graph(checkpointer=None)` keeps the `langgraph.json` entry point.
  `Orchestrator` always compiles with a checkpointer: without one `interrupt()`
  ends the run silently and `Command(resume=...)` raises.
- Typed invoke for mypy strict: `graph.invoke(state, cfg, version="v2")` returns
  `GraphOutput[EngineState]` with `.value` and `.interrupts`;
  `cfg: RunnableConfig = {"configurable": {"thread_id": run_id}}`.
- `get_stream_writer()` raises `RuntimeError` outside a graph.
- Python 3.11 is the CI floor: no PEP 695 syntax, no `PurePath.full_match`.

Do not add `ChatAnthropic` calls, tool loops or multi-agent routers to the
engine until the step that needs them; the vision documents in
`documentation_guide/` are history, not a spec.

---

## Security Notes for This Service

- `Workload.command` is argv, never a shell string, and `working_dir` is
  validated by `normalize_path`.
- `Paper.pdf_url` must be https; every fetched URL is validated before use.
- Branches are `engine/run-<run_id>` (delivery) and
  `engine/trial-<run_id>-<hypothesis_id>` (trials): full ids, never nested,
  validated as git refnames by `assert_safe_branch`, which also refuses
  `project.default_branch`. Run ids and candidate ids are validated
  (`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`, no `..`, no `.lock`); the prefix must be
  non-empty and end with `/`.
- Report text (`Delivery.report_markdown`) is sanitised: line breaks collapsed,
  `| < > & [ ] : @` and backticks escaped, `www.` neutralised, 200 characters
  per cell, because trial error text and paper titles end up in a PR body.
- Protected patterns cover CI files, `pyproject.toml`, lockfiles and interpreter
  hooks, so a trial cannot change what judges it.
- The checkpoint store must never be writable by trial code:
  `JsonPlusSerializer` deserialisation can execute code for allowlisted types.
- No secrets in code; `.env` only. Run `bandit -r src -c pyproject.toml`.

---

## Testing Conventions

- TDD: the test file lands before the module. Tests are typed too
  (`mypy src tests` from this directory; from the repo root pass
  `--config-file services/python_agents/pyproject.toml` or the pydantic plugin
  and strict settings are lost).
- Layout mirrors `src/`: `tests/common`, `tests/orchestrator`,
  `tests/optimization`, `tests/execution`, `tests/learning`,
  `tests/persistence`. Shared fixtures live in `tests/conftest.py`
  (`sample_project`, `sample_workload`, `sample_objective`, `sample_guardrails`,
  `sample_state`, `scripted_runner`, `in_memory_repo`, `engine_graph`).
- Coverage threshold is 90% (`--cov-fail-under=90`); `__init__.py` files and the
  research placeholders are omitted, so package inits stay re-export only.
- `pytest` runs with xdist (`-n auto`). To run serially use
  `uv run pytest -o addopts=""` rather than `-p no:xdist`.
- Graph tests use `InMemorySaver` and a unique `thread_id` per test; the E2E
  suite in `tests/orchestrator/test_graph_e2e.py` covers clean keep, protected
  path, below-noise retry, approval approve and reject, durable resume across
  graph instances and the no-checkpointer error.

---

## Key Files

Paths are relative to `src/autonomous_ai_agents/` unless they start with
`tests/`.

| File                                   | Status      | Purpose                                          |
| -------------------------------------- | ----------- | ------------------------------------------------ |
| `common/config.py`                     | real        | pydantic-settings: models, DB, engine knobs      |
| `common/models.py`                     | real        | Data model, enums, serde allowlist               |
| `common/paths.py`                      | real        | `normalize_path`, `PathTraversalError`           |
| `common/refnames.py`                   | real        | Git refname rules for branches and the prefix    |
| `orchestrator/state.py`                | real        | `EngineState`, `initial_state`, `REDUCER_KEYS`   |
| `orchestrator/nodes.py`                | skeleton    | One function per loop node, `after_verdicts`     |
| `orchestrator/main.py`                 | skeleton    | `create_graph`, `Orchestrator.run/resume/stream` |
| `orchestrator/events.py`               | real        | `make_event`, `emit`                             |
| `optimization/anticheat.py`            | real        | Protected paths, noise rule, fingerprints        |
| `optimization/judges.py`               | real        | Judge protocol, five judges, `derive_verdict`    |
| `optimization/ranking.py`              | real        | Hypothesis score with lesson boost               |
| `learning/lessons.py`                  | real        | Verdict -> `Lesson`                              |
| `execution/runner.py`                  | stub        | `TrialRunner` protocol, `StubTrialRunner`        |
| `persistence/repository.py`            | in-memory   | `Repository` protocol, `InMemoryRepository`      |
| `research/arxiv_monitor.py`            | placeholder | arXiv monitoring (Step 3)                        |
| `research/pdf_parser.py`               | placeholder | PDF parsing (Step 3)                             |
| `tests/orchestrator/test_graph_e2e.py` | real        | Seven end-to-end scenarios                       |
| `tests/conftest.py`                    | real        | Shared fixtures                                  |

"skeleton" means the control flow is final and the behaviour inside is a
deterministic stub; "stub" means the whole module is replaced in a later step
behind the same interface.

---

## Commands

```bash
uv sync --extra dev
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run pytest                                   # coverage >= 90% enforced
uv run pytest tests/orchestrator/test_graph_e2e.py -v
uv run pip-audit && uv run bandit -q -r src -c pyproject.toml
```

---

**Version:** 4.1.0 **Last Updated:** 2026-10-21

**Changelog:**

- **4.1.0 (2026-10-21):** Step 1 engine design: loop graph, state rules, data
  model, anti-cheating, judges and verdict order, injection points, verified
  LangGraph 1.x conventions, security notes; removed the generic
  LangGraph/SQLAlchemy/tool-use boilerplate that no longer matched the code
- **4.0.0 (2026-10-21):** Engine purpose and current state; LangGraph 1.x and
  anthropic 1.x; models via settings; truthful key-files table
- **3.0.0 (2025-11-19):** Added advanced prompting technique references
- **2.0.0 (2025-11-19):** Initial hierarchical structure
