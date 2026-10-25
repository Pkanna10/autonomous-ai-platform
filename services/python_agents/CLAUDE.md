# Python Agents Service - Claude Code Configuration

**Service:** `python_agents` **Version:** 4.4.0 **Primary Language:** Python
3.11+ **Framework:** LangGraph 1.x **Testing:** pytest **Key Libraries:**
langgraph, langchain, anthropic (1.x), pydantic 2, pydantic-settings, structlog,
psycopg 3 (the `database` extra)

The root `CLAUDE.md` holds the vision, the build order and the stage gate. This
file holds what is specific to the Python engine: its design, its conventions
and the LangGraph gotchas already verified.

---

## Service Purpose

Home of the improvement engine: the LangGraph orchestrator loop (L2), research
(L4), the local execution layer (L5), optimization judges (L6) and the lessons
store (L7). Persistence talks to PostgreSQL through `infrastructure/schema/`.

**Current state (Step 3 Wave 1 built, E2E and live runs next):** the loop runs
for real on CPU-bound Python workloads. `orchestrator/factory.py` wires the real
preflight, Claude understander, cProfile profiler, git baseline and trial
runners (each trial edited by Claude in its own sandboxed worktree), combiner
and branch publisher; the Postgres repository persists runs. Step 3 Wave 1 wires
discovery: the hypotheses node asks the generator
(`optimization/hypothesis_source.py` over `generate.py`) when no caller or
pooled idea is left, so a factory-built run needs no candidates; the `research`
node is no longer a stub: blind retrieval (the default) copies the context's
techniques with no request, matched retrieval (off, D1) asks the matcher over
the playbook. It also adds one fix retry per run, the review branch, the two
output modes with the quality check, and the noise rule (below). `watch` is
still a stub. There is no CLI (Step 4). `default_context()` and the
`langgraph.json` entry point still use the Step 1 stubs.

Models come from settings, never from string literals: `settings.ENGINE_MODEL`
(default `claude-opus-5-5`) and `settings.TRIAGE_MODEL` (default
`claude-haiku-5-5`). Engine knobs live next to them: `MIN_RUNS=5`,
`NOISE_MULTIPLIER=2.0`, `MIN_RELATIVE_GAIN=0.02`, `MAX_TRIAL_ROUNDS=3`,
`MAX_COST_USD=5.0`, `TRIAL_BRANCH_PREFIX="engine/"`. Step 2 added the isolation
modes (`NETWORK_ISOLATION`, `FS_ISOLATION`, default `required`),
`WORKTREE_ROOT`, `ENGINE_API_BASE_URL`, the fallback chain and `MODEL_PRICING`,
the git, test and output limits, the editor and understand limits (and their
`UNDERSTAND_EFFORT` / `EDITOR_EFFORT`, unset by default) and the retry policy;
the README's "Environment Variables" lists them with their defaults. All are
validated at startup (`MODEL_PRICING` must price every model the engine may
bill).

Step 3 settings (`common/config.py`). Each request has a **role**,
`Role = Literal["engine", "editor", "generator", "matcher"]`:
`role_chain(cfg, role)` is every model a request of that role may bill,
`role_settings(base, role)` a validated copy whose engine chain is that role's,
so a transport built from it serves the role. The engine (and the editor while
`EDITOR_MODEL` is unset) keeps the fallback chain; the other roles run their
model alone.

- Discovery: `GENERATOR_MODEL` / `GENERATOR_EFFORT` (`claude-sonnet-5-5`,
  `medium`), `GENERATOR_N=5`, `GENERATOR_MAX_TOKENS=16000`,
  `GENERATOR_MAX_CALLS=2`; `MATCHER_MODEL` / `MATCHER_EFFORT` (Sonnet 5.5,
  `medium`), `MATCHER_K=3`; `RESEARCH_RETRIEVAL` (`blind` or `matched`);
  `GENERATED_CLASSES` (`efficiency`, `behaviour`; never `novel`);
  `DISCOVERY_MAX_SHARE=0.25` of the cap.
- Editor and retry: `EDITOR_MODEL` (`None` = `ENGINE_MODEL`);
  `EDITOR_FIX_RETRIES=1` per trial and `EDITOR_FIX_RETRIES_PER_RUN=1` per run,
  both bounded 0-1 (O8; B-R2 may lift the run bound only);
  `RETRY_CLOSURE_MAX_SOURCE_BYTES` (8 MiB).
- Output and quality: `DEFAULT_OUTPUT_CHECK=True`, `OUTPUT_TOLERANCE_MAX_BYTES`
  (16 MiB), `QUALITY_MAX_FROZEN_BYTES` (64 MiB, a total over the frozen files),
  `QUALITY_MAX_ROWS` (1,000,000), `QUALITY_TIMEOUT_S` (300).
- Noise: `PAIRED_TRIALS=True`, `CONFIRM_WINNERS=True`,
  `NOISE_CALIBRATION_BLOCKS=3` (0-5; 0 keeps Step 2),
  `NOISE_GAP_MULTIPLIER=2.0`.

These defaults are the product's (O8-O10) and only the factory reads them; every
`NodeContext`, constructor, model and serde default reproduces Step 2 (D4). A
test that needs Step 2's behaviour from the factory pins those settings itself,
as `tests/e2e/test_step2.py` does.

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
  judges, protected-path patterns, the noise rule, output fingerprints,
  the quality check's files and scorer (sha256 recorded at baseline)
```

`after_verdicts` routes, in order: to `approval_gate` when an approval is
pending (only `novel` verdicts pend); to `combine` when the budget is exhausted,
when any verdict is `keep` or when `round >= max_rounds`; back to `hypotheses`
while an untried idea is in `ctx.candidates` or `candidate_pool`, or the
generator can still be called and afforded; otherwise to `combine`. A `review`
verdict never routes. A gate decision always proceeds to `combine`, so a run
ends with a report even when nothing is kept.

### Package map

| Package         | Layer | What it holds                                                                                                                                                                                                                                            |
| --------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `common/`       | all   | `config.py` settings, `models.py` data model, `errors.py` every engine error, `paths.py` path rules and pattern constants, `refnames.py` branch rules                                                                                                    |
| `clients/`      | L2/L5 | `transport.py` (the only SDK client, `call()` retry loop, `ScriptedTransport`), `cost.py` (worst-case estimate, response cost), `budget.py` (`Budget`), `structured.py` (fenced, schema-validated replies)                                               |
| `orchestrator/` | L2    | `state.py`, `nodes.py`, `main.py` (graph, `Orchestrator`), `factory.py` (`build_context`), `understand.py`, `combine_node.py`, `confirm.py`, `serde.py`, `events.py`                                                                                     |
| `research/`     | L4    | `playbook.py` + `playbook.json` (technique cards, matcher); arXiv monitor and PDF parser (placeholders; papers conditional, D2)                                                                                                                          |
| `execution/`    | L5    | `runner.py` and `protocols.py` (seams), `fakes.py`, `git.py`, `sandbox.py`, `launcher.py`, `procrun.py`, `measure.py`, `phase.py`, `profiler.py` (+ `_profile_shim.py`), `editor.py`, `editor_tools.py`, `preflight.py`, `trial_runner.py`, `combine.py` |
|                 | L5    | Step 3: `outputs.py` (tolerant fingerprints, mask), `crash.py` and `retry.py` (closed crash feedback), `quality.py` (frozen scorer)                                                                                                                      |
| `optimization/` | L6    | `anticheat.py` (protected paths, capture rules, tripwire), `judges.py`, `ranking.py`, `generate.py`, `sources.py` and `hypothesis_source.py` (generator, matcher)                                                                                        |
| `learning/`     | L7    | `lessons.py` (verdict -> lesson)                                                                                                                                                                                                                         |
| `persistence/`  | DB    | `Repository` protocol, `InMemoryRepository`, `postgres.py` (`PostgresRepository`)                                                                                                                                                                        |

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

Step 2 keys, all set by `initial_state(..., max_cost_usd=None)` (default
`settings.MAX_COST_USD`; below 0 is a `ValueError`): `base_commit` (the measured
SHA, set at connect), `understanding`, `max_cost_usd`, `combination`,
`budget_exhausted` (the router then goes straight to combine) and
`extra_protected` (repo files the commands name). A node that spends money
rebuilds `Budget(state["max_cost_usd"], state["cost_usd"])`, so the budget
survives a checkpoint. `orchestrator/serde.py` (`dump_state`, `load_state`)
round-trips the state through JSON with one `TypeAdapter` per key, because
`TypeAdapter(EngineState)` fails on Python 3.11.

Step 3 keys (U2): `candidate_pool` (generated ideas not yet sliced into a
round), `parked` (ideas held back with a `parked_reason`, such as a generated
`novel` one), `technique_matches`, `generator_calls`, `discovery_cost_usd` (also
counted in `cost_usd`), `discovery_exhausted`, and the review branch's
`review_combination` and `review_delivery`. The quality check's frozen files and
the noise calibration travel in `Baseline` (`quality_files`, `calibration`), and
the raised floor only in `Baseline.objectives`: `state["objectives"]` stays the
user's.

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
  `sitecustomize.py` and `*.pth`, and since Step 3 install and interpreter
  config (`pip.conf`, `uv.toml`, `requirements*.in`, `constraints*.txt`,
  `pylock*.toml`, `pdm.lock`, `.python-version` and their kin, D23). A trial
  diff touching any of them is a `Violation(protected_path)` and the verdict is
  `reject` whatever the judges say.
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
- Capture rules (Step 2, `check_capture`) judge what git says a trial changed,
  never what the editor reports: `forbidden_file_mode` (symlink, gitlink,
  unusual mode, mode change), `forbidden_file` (`WRITE_DENY_PATTERNS` such as
  `*.pyc` and `*.so`, or a binary blob), `git_metadata` (`.git`,
  `.gitattributes`, `.gitmodules`, `.lfsconfig`), `unrecorded_write`,
  `module_shadow` (a new top-level module named after the stdlib or the test
  runner under a module root) and `process_spawn` (an AST scan, when CPU time or
  memory is judged). A trial with a violation is `failed` with
  `Trial.violations` set and is never executed.
- Quality tripwire (Step 3, `check_quality_references`): with a quality check, a
  trial whose added lines name a frozen file (its basename as a whole token,
  case- and NFC-folded) is a `quality_data_reference` violation. A binary patch
  counts as naming it and a git error fails the trial (closed). A tripwire, not
  closure: a baked table of label values, or a kept line with edited neighbours,
  names nothing git shows as added; the review branch's diff is the backstop.
  Any added mention counts, comments included.

### Judges and the verdict order (`optimization/judges.py`)

```python
@runtime_checkable
class Judge(Protocol):
    @property
    def name(self) -> str: ...
    def applies_to(self, objective: Objective) -> bool: ...
    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult: ...
```

`default_judges(noise_multiplier, *, quality=None)` returns `SpeedJudge`,
`MemoryJudge`, `EquivalenceJudge`, `GuardrailMetricJudge` and `TestSuiteJudge`;
keep `EquivalenceJudge` in any judge set, since it is the only judge that sets
`JudgeResult.output_changed`. They are frozen dataclasses held in the node
context, never in the state, and they do no I/O: every number they see was
measured by the runner before they run.

`derive_verdict(trial, hypothesis, judge_results, violations)` is pure and
ordered:

1. any `Violation` -> `reject`
2. trial failed -> `reject`
3. any judge `failed` -> `reject`
4. primary-objective or guardrail judge `inconclusive` -> `inconclusive` (a
   secondary objective inside the noise is neutral)
5. no objective judge `passed` -> `inconclusive`
6. all pass (rule 6, D35): any result with `output_changed` -> `review` (`novel`
   stays `needs_approval`); otherwise `efficiency` -> `keep`, `behaviour` ->
   `review`, `novel` -> `needs_approval`. Behaviour goes to review, novel needs
   approval, and an output change is never kept on the run branch.

A `review` verdict sets the hypothesis `trialled`, never pauses the run and is
delivered on `engine/review-<run_id>` (below).

### Output modes, the quality check and the noise rule (Step 3)

- **Exactly one output mode per run** (define, D35, D40):
  - _exact_ (the default; `NodeContext.default_output_check`, which the factory
    sets from `DEFAULT_OUTPUT_CHECK`): an `output_equivalence` guardrail. A
    change to stdout or the declared `output_file` fails rule 3, whatever its
    class; stderr, logging and undeclared files are not compared.
  - _quality_: the caller's confirmed `QualityCheck`
    (`build_context(..., quality=)`; Step 4 asks it as one question) becomes a
    `metric_bound` guardrail `quality:<name>` and there is no
    `output_equivalence`. `EquivalenceJudge` still compares fingerprints: a
    changed output passes with `output_changed` set (so rule 6 sends it to
    review); a missing or unstable one fails. A caller passing both, or its own
    `quality:` bound, is refused.
- **The quality number** comes from a frozen evaluator, never from text the
  trial prints: a builtin (`accuracy`, `error_rate`, `macro_f1`, `mae`, `rmse`,
  one value per output line against a labels file) or an external scorer
  (`python -s -B <copy>/<script>`, its stdout exactly
  `aip-quality/1 <name>=<decimal>`). The frozen paths are read at the base
  commit and their sha256 recorded (`Baseline.quality_files`); they are
  protected, read-denied to the editor ("evaluation data, off limits"), deleted
  from every worktree before each workload launch but the suite's, and copied
  into `<run>/quality` only while a scoring runs. The input is the workload's
  `output_file`, else its complete stdout; an `output_file` over
  `OUTPUT_TOLERANCE_MAX_BYTES` is unscoreable. `max_drop` is in points of the
  metric by default (`DropUnit.absolute`).
- **Tolerance** (`Workload.output_tolerance`, a caller option): `float_digits`
  (6-15 significant digits, whole-token decimals only) and `unordered_lines`
  ("line order ignored, except an unterminated last line").
  `Measurement.raw_fingerprint` keeps the exact one; scores are cached by it.
- **The noise rule** (D41): with `PAIRED_TRIALS` each trial attempt is measured
  ABBA against a twin worktree at the base (`Trial.base_measurements`) and
  judged against those A rows; a twin crash is an `EngineError`. With
  `NOISE_CALIBRATION_BLOCKS` the baseline runs A/A blocks and raises the
  wall-time objective's `min_relative_gain` to
  `max(2 %, NOISE_GAP_MULTIPLIER x the largest gap)` (`cpu_time_s` to at least 2
  %); a floor of 100 % or more stops the run ("no gain can be proven on this
  host"). With `CONFIRM_WINNERS` every would-be keep or review gets one fresh
  paired re-test through the combiner (`orchestrator/confirm.py`): a keep stands
  only on a keep look, a review on a keep or review look; otherwise
  `inconclusive` ("did not confirm"). Reports give each gain with its margin,
  confirmations and a small (< 5 %), solid (5-20 %) or large (> 20 %) label
  (D42).
- **Branches:** confirmed keeps whose outputs are unchanged combine onto
  `engine/run-<run_id>`; the review set (reviews, plus an approved keep whose
  output changed) is re-tested from the same base with `accept={keep, review}`
  and published create-only to `engine/review-<run_id>`. Neither is merged into
  the other or pushed; the report says merging both is unproven.

### Ranking and lessons

`optimization/ranking.py`:
`score = expected_gain × provability × (1 − risk) × (1 + lesson_boost)` with
`lesson_boost = clamp(0.1·keeps − 0.1·rejects, ≤ 0.5)` over lessons whose
context tags match. Generated ideas keep the model's order and only lessons
reorder them: `rank_generated` scores `(1 + lesson_boost) / (1 + position)`
(D8); caller candidates rank first. `learning/lessons.py` turns every verdict
into a `Lesson` ("frozen encoder + repeated epochs -> cache embeddings: keep
(+41.7%)"); approved verdicts count as keeps, rejected ones as rejects, and
`review` lessons are neutral. A confirmed keep's lesson carries D42's two-look
gain.

### Injection points

Nodes come from `make_nodes(ctx: NodeContext)`. `NodeContext` is a frozen
dataclass carrying the `TrialRunner`, the `BaselineRunner`, the judges, the
`Repository`, the protected patterns, the branch prefix, the rigour knobs and
the caller's candidate hypotheses (optional since Step 3). Step 2 added five
seams, each defaulting to `None` (the node then keeps its Step 1 behaviour):
`preflight`, `understander`, `profiler`, `combiner` and `publisher`, plus
`min_trial_budget_usd` (default 0; the trials node starts no trial that cannot
afford it). Step 3 adds, each defaulting to Step 2's behaviour: `generator`,
`matcher`, `retrieval`, `generated_classes`, `generator_n`,
`generator_max_calls`, `matcher_k`, `discovery_max_share`, `fix_retries_per_run`
(0), `playbook`; `quality` (`None`), `default_output_check` (False),
`calibrator` (`None`), `calibration_blocks` (0) and `confirm_winners` (False).

- `orchestrator/factory.py`:
  `build_context(project, *, candidates=(), quality=None, ...)` builds the real
  context: `GitPreflight`, `ClaudeUnderstander`, `CProfiler`,
  `GitBaselineRunner`, `GitTrialRunner` (with `ClaudeEditor` over
  `WorktreeEditor`), `GitCombiner` and `GitBranchPublisher` on one
  `GitWorkspace`, one pair of isolation modes and one launcher, and
  `min_trial_budget_usd` = one worst-case editor request (priced on the editor's
  chain, also the retry floor). In Step 3 it builds each role's transport from
  `role_settings` (engine, editor, generator; the matcher and the playbook only
  under matched retrieval), feeds the settings above into the runners and the
  context, and with a quality check shares one `FrozenScorer` among the runners
  and the profiler. `role_transports={"generator": ...}` injects a role's
  transport; with `transport=` injected and no role transports it builds none,
  so there is no generator. Connect rebinds the runners to the test command
  preflight resolved, so a context serves one run at a time. Without
  `ANTHROPIC_API_KEY` there is no transport: understand keeps its stub and the
  trials need an injected `editor`, else `LLMConfigError`. Keyword overrides
  (`transport`, `editor`, `run`, `network`, `fs`, `sleep`) exist for tests.
- `execution/runner.py`:
  `TrialRunner.run(hypothesis, workloads, baseline, *, round, branch, budget_usd, brief) -> Trial`
  and
  `BaselineRunner.measure(workloads, *, run_id, commit) -> tuple[Measurement, ...]`.
  `StubTrialRunner` replays `ScriptedOutcome`s looked up by hypothesis id, then
  title, then a default; `StubBaselineRunner` replays one outcome.
- `execution/protocols.py`: `Preflight`, `Profiler`, `CodeEditor`,
  `ProjectUnderstander`, `Combiner`, `BranchPublisher` and their frozen carriers
  (`TrialBrief`, `WorktreeHandle`, `PreflightReport`, `EditTask`, `EditResult`,
  `KeptChange`, `CombineMeasured`, `LaunchReport`). `execution/fakes.py` has a
  deterministic double for each, plus `ScriptedEditor` (edit sets from disk,
  keyed by hypothesis title).
- `clients/transport.py`: `LLMTransport.send`; `AnthropicTransport` is the only
  code that builds an SDK client, `ScriptedTransport` replays responses. Every
  paid request goes through `call(transport, request, budget, ...)`.
- `persistence/repository.py`: `Repository` protocol (`save_run`, `get_run`,
  `save_trial`, `save_verdict`, `save_lesson`, `list_lessons`, `list_trials`,
  `list_verdicts`) and `InMemoryRepository`. `persistence/postgres.py`:
  `PostgresRepository(dsn)`, psycopg with literal SQL and `%(name)s` parameters,
  state through `serde`, trials and verdicts in the 003 JSONB arrays; there is
  no ORM and no second migration system.

`Orchestrator(context=..., checkpointer=...)` exposes
`run(project, workloads, objectives, guardrails, *, run_id=None, max_rounds=None, max_cost_usd=None) -> EngineRunResult`
(`run_id`, `status` of `done | needs_approval | failed`, final `state`,
`approval_request`), `resume(run_id, decision)` and `stream(...)`, which yields
each `EngineEvent` as the node emits it and ends with a `paused` event when the
run waits at the gate. `run` and `stream` call `save_run` on the initial state
before the graph starts, so an `EngineError` from the repository
(`ProjectConflictError`, `InvalidRecordIdError`) propagates before any node
runs. `run` refuses a `run_id` that already has a thread, `resume` refuses a run
that is not waiting at the gate (also while another call in the process drives
that run id), and every result is saved to the repository. A failed state keeps
what the failing node had spent and run (`nodes.keep_progress`) and lists the
trial refs left (`trial_refs_left`); a non-engine exception is saved as a failed
run, then propagates. An invalid approval payload re-interrupts with the error
on the request instead of failing the run. With no objectives, `define` uses
"minimize wall time" plus a peak-RSS `metric_bound` guardrail (at most +10 %).

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
- Branches are `engine/run-<run_id>` (delivery), `engine/review-<run_id>` (the
  review set, Step 3) and `engine/trial-<run_id>-<hypothesis_id>` (trials): full
  ids, never nested, validated as git refnames by `assert_safe_branch`, which
  also refuses `project.default_branch`. Run ids and candidate ids are validated
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

Step 2 (repository code now runs on the user's machine):

- **Sandbox, fail closed.** Every launch (preflight probe, baseline, profile,
  trials, combine, test suites) goes through `procrun.run_once`: on Linux
  `unshare -rn -p -f --ipc --mount-proc` around `python -I -S launcher.py`,
  which brings `lo` up, installs a seccomp filter that fails `socket(AF_UNIX)`
  with EACCES (the network namespace isolates AF_INET and abstract AF_UNIX but
  not path-based AF_UNIX, so without it a workload could reach a host
  unix-domain service such as `/var/run/docker.sock` or a local database socket;
  `socketpair(AF_UNIX)` and AF_INET are untouched), sets `no_new_privs`, applies
  Landlock (writes only to the worktree, its `_scratch` dir and `/dev/null`;
  `/dev/shm` is not writable), drops every capability in the child and
  self-checks before exec (a write in `_probe`, a connect to the parent's
  127.0.0.1 listener and creating an AF_UNIX socket must all fail). macOS uses
  `sandbox-exec` with `(deny network*)` (which also covers AF_UNIX `connect`)
  and a write allowlist. Under `required` a failed step refuses the run; procrun
  parses the report strictly and cross-checks it against the wrapper's `wait4`
  accounting. `NETWORK_ISOLATION=off` on Linux runs without namespaces.
- **Child environment** (`sandbox.child_env`): an allowlist (`PATH` with
  relative entries dropped, locale, `TZ`, venv vars) plus deny patterns that win
  over explicit extras; forced `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`,
  a fresh `HOME`/`TMPDIR` per run and an engine-owned `PYTHONPATH` of the
  worktree (and its `src`).
- **Worktree ownership** (`execution/phase.py`): each phase owns
  `<WORKTREE_ROOT>/<run>/<phase>`, `_scratch/<phase>` and `_probe/<phase>` and
  removes them in `finally`; planted links are unlinked, never followed; a
  cleanup failure never hides an error already raised. While it works it holds a
  shared `flock` on `<run>/.aip-run.lock`; connect's `sweep_stale_runs` cleans
  every marked run no live owner holds (a `kill -9` leftover). `WORKTREE_ROOT`
  may not overlap the checkout, the git common dir or another worktree of the
  repository.
- **Git is untrusted input** (`execution/git.py`): a scratch environment, no
  hooks, fsmonitor, signing, network or credential helpers, every
  `filter`/`diff`/`merge` driver key emptied, `--attr-source=<empty tree>` on
  git 2.40 and later, `--git-dir`/`--work-tree` from the `WorktreeHandle` (the
  `.git` link is compared after every run), `--` before paths, capped output.
  `worktree add --no-checkout`, then `checkout -f` on the handle, so the driver
  listing and the checkout read the same config. Reset and cleanup walk
  directory fds with `O_NOFOLLOW` (a directory swapped for a link is
  `RepoTamperedError`, never followed). Preflight refuses submodules, LFS,
  partial clones, dubious ownership, custom merge drivers and `includeIf`.
- **Git gotchas verified in research**: a plain `git status` or
  `git stash create` rewrites the user's index (run with
  `GIT_OPTIONAL_LOCKS=0`); a dirty snapshot works through a copied
  `GIT_INDEX_FILE` plus `write-tree` and `commit-tree`;
  `git apply --check --3way` exits 0 on conflicts, so it never detects them.
- **Fingerprint.** `repo_fingerprint` (config, `config.worktree`, `hooks/`,
  `info/`, the effective config, the HEAD symref, and every ref under `refs/`
  except remote-tracking and prefetch refs, so `refs/replace`, `refs/stash` and
  `refs/notes` count) is taken before and after every phase that runs repo code;
  a trial excludes only its own ref, which must be absent or at `Trial.commit`.
  A difference is `RepoTamperedError`.
- **Editor confinement** (`execution/editor_tools.py`): Claude sees only
  `/repo`; `GIT_METADATA_NAMES` (case-insensitive), symlinks on any component,
  `READ_DENY_PATTERNS` (secrets: `.env*`, keys, `.netrc`, ...; never viewed,
  since a view reaches the API), `WRITE_DENY_PATTERNS`, protected patterns and
  reserved module names are refused. Repository text travels inside
  `<untrusted_repo_content boundary=TOKEN>` with a per-trial token; content
  holding the token is refused. The understander reads git objects at the base
  commit only and skips `READ_DENY_PATTERNS` files.
- **Capture before execution**: the capture rules above run on git's view of the
  change (`--no-renames`, strict UTF-8); a violating trial never runs.
- **Claude API.** The key is a `SecretStr` unwrapped only in
  `AnthropicTransport`, sent only to `ENGINE_API_BASE_URL` (https, never the
  SDK's `ANTHROPIC_BASE_URL`); SDK retries and redirects are off; the
  `anthropic` logger stays at INFO or stricter; mapped errors keep status, type
  and request id only. Every attempt passes `Budget.check` with a worst-case
  estimate over the whole fallback chain first.
- **Profiles are untrusted**: workload-written pstats are never unmarshalled in
  the engine; the shim emits JSON that is parsed strictly with a size cap.
- **Postgres**: literal SQL with parameters only; ids bound for UUID columns are
  validated before any SQL (`InvalidRecordIdError`); U+0000 in stored text is
  escaped as U+E000 + `0` and restored on read.
- **Delivery**: create-only `update-ref` under the prefix, never on a
  checked-out or default branch (or one it symrefs to), never pushed.

Step 3:

- **Retry feedback is closed** (D13, `execution/retry.py`): only a workload's
  own run exiting with a fixable Python error is retried, once a run. What
  reaches the editor is the exception type, a message that fully matches one of
  the per-version CPython templates (3.8-3.14) with every name in the closure
  set (identifiers of the diff and of the tracked base sources), at most two
  numbers of at most 4 digits, and at most three innermost frames as (path,
  function, line); never source lines, stdout, timings, fingerprints, quality
  values or verdicts. The residual is about 18 bytes a run; a second retried
  trial a run waits for B-R2's safeguards and attack tests. Feedback travels in
  its own `untrusted_run_output` fence, and the hypothesis sits inside the
  repository fence for every source (D11).
- **The run's retry cap survives resumes**: the trials node counts spent retries
  over the checkpointed trials and the repository's saved trials, the larger
  count winning; an unreadable repository grants 0.
- **The quality scorer** runs from an engine copy of the recorded blobs (sha256
  re-checked, written `O_EXCL|O_NOFOLLOW`), under its own sandbox policy
  (network off, writes confined to the copy and its scratch), with the output on
  stdin, `-s -B` and the forced hash seed; symlinks and other non-regular blobs
  are refused at freeze. Errors never carry output, label or scorer text.
  Residual: confinement is write-only, so code can still read the labels through
  the main repository, the object store or an unfrozen input that carries them,
  and with `NETWORK_ISOLATION=off` a `setsid` child can outlive its run while a
  scoring copy exists; every output change goes to review for that reason.
- **Editor read-deny**: frozen paths are refused to `view` and omitted from
  listings, case-insensitively and NFC-normalised (APFS-safe).
- **Generated hypotheses are untrusted**: titles and descriptions derive from
  repository text, so they enter the editor prompt only inside the fence, and a
  text holding the fence token is refused unsent.

---

## Testing Conventions

- TDD: the test file lands before the module. Tests are typed too
  (`mypy src tests` from this directory; from the repo root pass
  `--config-file services/python_agents/pyproject.toml` or the pydantic plugin
  and strict settings are lost).
- Layout mirrors `src/`: `tests/common`, `tests/clients`, `tests/orchestrator`,
  `tests/optimization`, `tests/execution`, `tests/learning`,
  `tests/persistence`, plus `tests/e2e`. Shared fixtures live in
  `tests/conftest.py` (`sample_project`, `sample_workload`, `sample_objective`,
  `sample_guardrails`, `sample_state`, `scripted_runner`, `in_memory_repo`,
  `engine_graph`); `tests/fixtures/` holds the `dedupe_repo` fixture, its edit
  sets and scripted transcripts (excluded from collection and from mypy).
- Coverage threshold is 90% (`--cov-fail-under=90`; 100% line and branch today,
  no `pragma: no cover`); `__init__.py` files and the research placeholders are
  omitted, so package inits stay re-export only.
- `addopts` runs xdist (`-n auto`) and adds `-m "not live"`. A `-m` you pass
  replaces it, and `-o addopts=""` drops it: always keep `-m "not live"` then.
  To run serially use `uv run pytest -o addopts="" -m "not live"` rather than
  `-p no:xdist`.
- **Live tests** (`live` marker) call the real API and cost money; CI runs them
  only in the manual `live-smoke` job (environment `live`, `-n 0`). The Stage A
  suite lives in `tests/live` (contract checks, understand on three repo shapes,
  the whole loop, the injected-repository attack; fixtures in
  `tests/fixtures/live_repos`). Its `conftest.py` skips a live test unless the
  marker expression needs `live` to select it and `ANTHROPIC_API_KEY` is set,
  fails under xdist or without the sandbox, refuses a test once the suite ledger
  would pass `LIVE_SUITE_CAP_USD` (12), and writes the cost table to the job
  summary; `tests/live/test_guards.py` tests all of it offline. The older editor
  live test in `tests/execution/test_editor.py` runs only under exactly
  `-m live`. The benchmark corpus (`tests/fixtures/live_corpus`: 12 slowdowns
  with reference fixes kept outside the repos in `_solutions`, 3 controls, 3
  attack repos; `manifest.json`) runs through `tests/live/test_corpus_live.py`
  and `test_attack_corpus_live.py`, records one `CorpusOutcome` JSON line per
  run in `LIVE_RESULTS_PATH` and a summary (win rate, known-fix rate, false-win
  rate on controls, cost per win); `tests/live/test_corpus_guards.py` proves
  offline that every slowdown is winnable. `live-smoke` takes `suite` (stage-a,
  corpus, attack, hard, oss; caps needed 9, 75, 12, 50, 50 USD, one at a time
  under the 150 USD ceiling), `mode` (aimed, blind, decoy: what each corpus run
  is handed), `engine_model` and `suite_cap_usd`. A hypothesis that names none
  of the run's hotspots (every caller-built candidate, so every corpus run) gets
  the run's top 5 by share in the editor brief (`BRIEF_FALLBACK_HOTSPOTS`).
- **Postgres tests** (`postgres` marker) skip when `TEST_DATABASE_URL` is unset;
  CI always sets it. Each pytest process creates its own database from
  `infrastructure/schema/*.sql` and drops it at the end, so the role must be
  allowed to create databases. The repository contract tests run on both
  backends.
- **Sandbox tests** skip when the host cannot isolate;
  `REQUIRE_NETWORK_SANDBOX=1` / `REQUIRE_FS_SANDBOX=1` (CI) make them fail
  instead. The launcher's setup runs in-process with injected `Ops`, and the
  darwin branches are tested on Linux through an injected `platform`.
- **Profiler and retry-template tests** run under `python3.8` to `python3.14`
  when they are on `PATH`
  (`uv python install 3.8 3.9 3.10 3.11 3.12 3.13 3.14`); a missing one skips
  locally and fails CI. `-P` cases are generated only for 3.11 and later.
- **E2E** (`tests/e2e/test_step2.py`, marker `slow`): E2E-A to E2E-C on the
  `dedupe_repo` fixture with real git, sandbox and measurement and scripted
  Claude replies; Postgres when `TEST_DATABASE_URL` is set. Its fixture pins
  Step 2's settings (no pairing, confirmation or calibration), so it keeps
  proving Step 2's behaviour under the Step 3 factory. Step 3's E3-A to E3-I
  (`tests/e2e/test_step3.py`, `tests/e2e/test_step3_quality.py`, fixtures under
  `tests/fixtures/step3*`) are in progress. The Step 1 graph scenarios on stubs
  stay in `tests/orchestrator/test_graph_e2e.py`. Graph tests use
  `InMemorySaver` and a unique `thread_id` per test.
- **New node tests go in new files** (`test_nodes.py` is past 5,000 lines):
  `test_hypotheses_node.py`, `test_research_node.py`, `test_noise_rule.py`,
  `test_confirm.py`, `test_review_delivery.py`, `test_define_modes.py`,
  `test_run_retry_cap.py`, `test_factory_roles.py` in `tests/orchestrator`.
- **Live suites in Step 3**: `LIVE_CORPUS_MODE=wired` hands over no candidates
  and turns the generator on through captured role transports; the
  `editor_model` input picks the editor; every suite names its noise rule in
  `ci.yml` (the Step 3 rule for `noise`, `corpus`, `hard`, `oss`), and the
  `noise` suite's paired path is L0. The offline discovery eval
  (`tests/optimization/test_discovery_eval.py`) replays recorded generator
  replies; its seed is synthetic until L4 records a real one.

---

## Key Files

Paths are relative to `src/autonomous_ai_agents/` unless they start with
`tests/`.

| File                                        | Status      | Purpose                                                                                   |
| ------------------------------------------- | ----------- | ----------------------------------------------------------------------------------------- |
| `common/config.py`                          | real        | pydantic-settings: models, pricing, isolation, limits, DB                                 |
| `common/models.py`                          | real        | Data model, enums, serde allowlist                                                        |
| `common/errors.py`                          | real        | Every engine error class                                                                  |
| `common/paths.py`                           | real        | `normalize_path`, `matches_pattern`, deny lists, reserved modules                         |
| `common/refnames.py`                        | real        | Git refname rules, `assert_safe_branch`                                                   |
| `clients/transport.py`                      | real        | `AnthropicTransport`, `ScriptedTransport`, `call()` retry loop                            |
| `clients/cost.py`, `clients/budget.py`      | real        | Worst-case estimate, response cost, `Budget`                                              |
| `orchestrator/state.py`                     | real        | `EngineState`, `initial_state`, `REDUCER_KEYS`                                            |
| `orchestrator/nodes.py`                     | real        | One function per node, `after_verdicts`; `research` blind or matched; `watch` stub        |
| `orchestrator/confirm.py`                   | real        | `confirm_one` (the second look), D42's gain, margin and label                             |
| `orchestrator/main.py`                      | real        | `create_graph`, `Orchestrator`; `default_context()` uses stubs                            |
| `orchestrator/factory.py`                   | real        | `build_context`: the real engine for one project                                          |
| `orchestrator/understand.py`                | real        | `ClaudeUnderstander`                                                                      |
| `orchestrator/combine_node.py`              | real        | Re-judge the combination, fall back once                                                  |
| `orchestrator/serde.py`                     | real        | Typed JSON round trip of `EngineState`                                                    |
| `orchestrator/events.py`                    | real        | `make_event`, `emit`                                                                      |
| `execution/runner.py`                       | stub        | `TrialRunner`, `BaselineRunner` protocols and their stubs                                 |
| `execution/protocols.py`                    | real        | The Step 2 seams and carriers                                                             |
| `execution/fakes.py`                        | test double | Fakes for every seam, `ScriptedEditor`                                                    |
| `execution/git.py`                          | real        | Hardened `GitWorkspace`, `repo_fingerprint`                                               |
| `execution/sandbox.py`, `launcher.py`       | real        | Sandbox policy and environment; the measuring launcher                                    |
| `execution/procrun.py`                      | real        | `run_once`: one sandboxed, measured run                                                   |
| `execution/measure.py`                      | real        | Warm-ups, timed runs, fingerprints, ABBA order, the mask, the test suite                  |
| `execution/outputs.py`                      | real        | Tolerant fingerprints (D39), output retention, the frozen-path mask                       |
| `execution/crash.py`, `execution/retry.py`  | real        | `parse_traceback`; `classify`, the closure set and the CPython templates                  |
| `execution/quality.py`                      | real        | `FrozenScorer`: freeze, builtins, the external scorer, `label_column_leaks`               |
| `execution/phase.py`                        | real        | Phase dirs and their shared cleanup                                                       |
| `execution/profiler.py`, `_profile_shim.py` | real        | `CProfiler` and the shim it runs in the workload's interpreter                            |
| `execution/editor.py`, `editor_tools.py`    | real        | `ClaudeEditor` loop; `WorktreeEditor` tool handler                                        |
| `execution/preflight.py`                    | real        | `GitPreflight`                                                                            |
| `execution/trial_runner.py`                 | real        | `GitTrialRunner`, `GitBaselineRunner`                                                     |
| `execution/combine.py`                      | real        | `GitCombiner`, `GitBranchPublisher`                                                       |
| `optimization/anticheat.py`                 | real        | Protected paths, capture rules, noise rule, fingerprints                                  |
| `optimization/judges.py`                    | real        | Judge protocol, five judges, `derive_verdict`                                             |
| `optimization/ranking.py`                   | real        | Hypothesis score with lesson boost; `rank_generated`                                      |
| `optimization/generate.py`                  | real        | `generate_hypotheses`                                                                     |
| `optimization/sources.py`                   | real        | `HypothesisGenerator`, `TechniqueMatcher` protocols                                       |
| `optimization/hypothesis_source.py`         | real        | `ClaudeHypothesisGenerator`, `ClaudeTechniqueMatcher` (each refuses another role's chain) |
| `clients/structured.py`                     | real        | Fenced untrusted input, strict JSON replies (`UnusableReplyError` in `common/errors.py`)  |
| `research/playbook.py`, `playbook.json`     | real        | Technique cards with preconditions, `match_techniques`                                    |
| `learning/lessons.py`                       | real        | Verdict -> `Lesson`                                                                       |
| `persistence/repository.py`                 | real        | `Repository` protocol, `InMemoryRepository`                                               |
| `persistence/postgres.py`                   | real        | `PostgresRepository` (003 to 006 schema)                                                  |
| `research/arxiv_monitor.py`                 | placeholder | arXiv monitoring (only if D2's re-test calls for papers; not from GitHub runners)         |
| `tests/live/experiments/`                   | test only   | Window 0 raw-SDK harness: probes, triage, papers, web, prescreen                          |
| `research/pdf_parser.py`                    | placeholder | PDF parsing (conditional, D2)                                                             |
| `tests/e2e/test_step2.py`                   | real        | E2E-A, E2E-B, E2E-C on the `dedupe_repo` fixture                                          |
| `tests/e2e/test_step3*.py`                  | in progress | E3-A to E3-I (U14, U26)                                                                   |
| `tests/orchestrator/test_graph_e2e.py`      | real        | The Step 1 graph scenarios on stubs (11 tests)                                            |
| `tests/conftest.py`                         | real        | Shared fixtures                                                                           |

"stub" means the module holds a deterministic stand-in kept for tests and the
default context; "test double" means it exists for tests only.

---

## Commands

```bash
uv sync --extra dev --extra database
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
TEST_DATABASE_URL=postgresql://dev:devpass@localhost:5432/ai_platform uv run pytest
uv run pytest tests/e2e --no-cov                # the E2E scenarios only
uv run pytest -o addopts="" -m "not live" -n 2  # without coverage, keeps live off
uv run pip-audit && uv run bandit -q -r src -c pyproject.toml
```

---

**Version:** 4.4.0 **Last Updated:** 2026-10-25

**Changelog:**

- **4.4.0 (2026-10-25):** Step 3 Wave 1: the current state (discovery wired,
  research no longer a stub, `watch` still one), the role keys and Step 3
  settings with the defaults rule, the router, the package map's new modules,
  the Step 3 state keys, D23's patterns and the quality tripwire, rule 6
  (behaviour goes to review, novel needs approval, an output change is never
  kept on the run branch), the output modes, the quality check, the noise rule
  and the two branches, `rank_generated` and neutral review lessons, the
  `NodeContext` fields and factory roles, Step 3 security notes, test
  conventions (3.8-3.14, new node test files, wired live suites), key files
- **4.3.0 (2026-10-24):** Step 2 close-out: the generator, playbook, matcher and
  structured client in the current state, package map and key files (not yet
  wired); the Window 0 experiment harness; git gotchas from the research notes
- **4.2.0 (2026-10-22):** Step 2 core loop: current state, package map (clients,
  the execution modules, factory, understand, combine node, serde, Postgres),
  Step 2 state keys, capture rules, `NodeContext` seams and the factory, Step 2
  security notes (sandbox, worktree ownership, git hardening, fingerprint,
  editor confinement, API key handling), test conventions (Postgres, live,
  sandbox, profiler interpreters, E2E), key-file statuses
- **4.1.0 (2026-10-21):** Step 1 engine design: loop graph, state rules, data
  model, anti-cheating, judges and verdict order, injection points, verified
  LangGraph 1.x conventions, security notes; removed the generic
  LangGraph/SQLAlchemy/tool-use boilerplate that no longer matched the code
- **4.0.0 (2026-10-21):** Engine purpose and current state; LangGraph 1.x and
  anthropic 1.x; models via settings; truthful key-files table
- **3.0.0 (2025-11-19):** Added advanced prompting technique references
- **2.0.0 (2025-11-19):** Initial hierarchical structure
