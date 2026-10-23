# Python Agents Service - Claude Code Configuration

**Service:** `python_agents` **Version:** 4.2.0 **Primary Language:** Python
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

**Current state (Step 2 built, stage gate pending):** the loop runs for real on
CPU-bound Python workloads. `orchestrator/factory.py` wires the real preflight,
Claude understander, cProfile profiler, git baseline and trial runners (each
trial edited by Claude in its own sandboxed worktree), combiner and branch
publisher; the Postgres repository persists runs. Research (`research` node,
candidates supplied through `NodeContext.candidates`) and `watch` are still
stubs (Step 3), and there is no CLI (Step 4). `default_context()` and the
`langgraph.json` entry point still use the Step 1 stubs.

Models come from settings, never from string literals: `settings.ENGINE_MODEL`
(default `claude-opus-5-5`) and `settings.TRIAGE_MODEL` (default
`claude-haiku-5-5`). Engine knobs live next to them: `MIN_RUNS=5`,
`NOISE_MULTIPLIER=2.0`, `MIN_RELATIVE_GAIN=0.02`, `MAX_TRIAL_ROUNDS=3`,
`MAX_COST_USD=5.0`, `TRIAL_BRANCH_PREFIX="engine/"`. Step 2 added the isolation
modes (`NETWORK_ISOLATION`, `FS_ISOLATION`, default `required`),
`WORKTREE_ROOT`, `ENGINE_API_BASE_URL`, the fallback chain and `MODEL_PRICING`,
the git, test and output limits, the editor and understand limits and the retry
policy; the README's "Environment Variables" lists them with their defaults. All
are validated at startup (`MODEL_PRICING` must price every model the engine may
bill).

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

| Package         | Layer | What it holds                                                                                                                                                                                                                                            |
| --------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `common/`       | all   | `config.py` settings, `models.py` data model, `errors.py` every engine error, `paths.py` path rules and pattern constants, `refnames.py` branch rules                                                                                                    |
| `clients/`      | L2/L5 | `transport.py` (the only SDK client, `call()` retry loop, `ScriptedTransport`), `cost.py` (worst-case estimate, response cost), `budget.py` (`Budget`)                                                                                                   |
| `orchestrator/` | L2    | `state.py`, `nodes.py`, `main.py` (graph, `Orchestrator`), `factory.py` (`build_context`), `understand.py`, `combine_node.py`, `serde.py`, `events.py`                                                                                                   |
| `research/`     | L4    | arXiv monitor and PDF parser (placeholders until Step 3)                                                                                                                                                                                                 |
| `execution/`    | L5    | `runner.py` and `protocols.py` (seams), `fakes.py`, `git.py`, `sandbox.py`, `launcher.py`, `procrun.py`, `measure.py`, `phase.py`, `profiler.py` (+ `_profile_shim.py`), `editor.py`, `editor_tools.py`, `preflight.py`, `trial_runner.py`, `combine.py` |
| `optimization/` | L6    | `anticheat.py` (protected paths, capture rules), `judges.py`, `ranking.py`                                                                                                                                                                               |
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
- Capture rules (Step 2, `check_capture`) judge what git says a trial changed,
  never what the editor reports: `forbidden_file_mode` (symlink, gitlink,
  unusual mode, mode change), `forbidden_file` (`WRITE_DENY_PATTERNS` such as
  `*.pyc` and `*.so`, or a binary blob), `git_metadata` (`.git`,
  `.gitattributes`, `.gitmodules`, `.lfsconfig`), `unrecorded_write`,
  `module_shadow` (a new top-level module named after the stdlib or the test
  runner under a module root) and `process_spawn` (an AST scan, when CPU time or
  memory is judged). A trial with a violation is `failed` with
  `Trial.violations` set and is never executed.

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
`Repository`, the protected patterns, the branch prefix, the rigour knobs and,
until the research layer exists, the candidate hypotheses. Step 2 added five
seams, each defaulting to `None` (the node then keeps its Step 1 behaviour):
`preflight`, `understander`, `profiler`, `combiner` and `publisher`, plus
`min_trial_budget_usd` (default 0; the trials node starts no trial that cannot
afford it).

- `orchestrator/factory.py`: `build_context(project, *, candidates, ...)` builds
  the real context: `GitPreflight`, `ClaudeUnderstander`, `CProfiler`,
  `GitBaselineRunner`, `GitTrialRunner` (with `ClaudeEditor` over
  `WorktreeEditor`), `GitCombiner` and `GitBranchPublisher` on one
  `GitWorkspace`, one pair of isolation modes and one launcher, and
  `min_trial_budget_usd` = one worst-case editor request. Connect rebinds the
  runners to the test command preflight resolved, so a context serves one run at
  a time. Without `ANTHROPIC_API_KEY` there is no transport: understand keeps
  its stub and the trials need an injected `editor`, else `LLMConfigError`.
  Keyword overrides (`transport`, `editor`, `run`, `network`, `fs`, `sleep`)
  exist for tests.
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
  corpus, attack, all; caps needed 9, 75, 12, 96 USD), `engine_model` and
  `suite_cap_usd`.
- **Postgres tests** (`postgres` marker) skip when `TEST_DATABASE_URL` is unset;
  CI always sets it. Each pytest process creates its own database from
  `infrastructure/schema/*.sql` and drops it at the end, so the role must be
  allowed to create databases. The repository contract tests run on both
  backends.
- **Sandbox tests** skip when the host cannot isolate;
  `REQUIRE_NETWORK_SANDBOX=1` / `REQUIRE_FS_SANDBOX=1` (CI) make them fail
  instead. The launcher's setup runs in-process with injected `Ops`, and the
  darwin branches are tested on Linux through an injected `platform`.
- **Profiler tests** run the shim under `python3.8` to `python3.12` when they
  are on `PATH` (`uv python install 3.8 3.9 3.10 3.11 3.12`); `-P` cases are
  generated only for 3.11 and later.
- **E2E** (`tests/e2e/test_step2.py`, marker `slow`): E2E-A to E2E-C on the
  `dedupe_repo` fixture with real git, sandbox and measurement and scripted
  Claude replies; Postgres when `TEST_DATABASE_URL` is set. The Step 1 graph
  scenarios on stubs stay in `tests/orchestrator/test_graph_e2e.py`. Graph tests
  use `InMemorySaver` and a unique `thread_id` per test.

---

## Key Files

Paths are relative to `src/autonomous_ai_agents/` unless they start with
`tests/`.

| File                                        | Status      | Purpose                                                           |
| ------------------------------------------- | ----------- | ----------------------------------------------------------------- |
| `common/config.py`                          | real        | pydantic-settings: models, pricing, isolation, limits, DB         |
| `common/models.py`                          | real        | Data model, enums, serde allowlist                                |
| `common/errors.py`                          | real        | Every engine error class                                          |
| `common/paths.py`                           | real        | `normalize_path`, `matches_pattern`, deny lists, reserved modules |
| `common/refnames.py`                        | real        | Git refname rules, `assert_safe_branch`                           |
| `clients/transport.py`                      | real        | `AnthropicTransport`, `ScriptedTransport`, `call()` retry loop    |
| `clients/cost.py`, `clients/budget.py`      | real        | Worst-case estimate, response cost, `Budget`                      |
| `orchestrator/state.py`                     | real        | `EngineState`, `initial_state`, `REDUCER_KEYS`                    |
| `orchestrator/nodes.py`                     | real        | One function per node, `after_verdicts`; `research`, `watch` stub |
| `orchestrator/main.py`                      | real        | `create_graph`, `Orchestrator`; `default_context()` uses stubs    |
| `orchestrator/factory.py`                   | real        | `build_context`: the real engine for one project                  |
| `orchestrator/understand.py`                | real        | `ClaudeUnderstander`                                              |
| `orchestrator/combine_node.py`              | real        | Re-judge the combination, fall back once                          |
| `orchestrator/serde.py`                     | real        | Typed JSON round trip of `EngineState`                            |
| `orchestrator/events.py`                    | real        | `make_event`, `emit`                                              |
| `execution/runner.py`                       | stub        | `TrialRunner`, `BaselineRunner` protocols and their stubs         |
| `execution/protocols.py`                    | real        | The Step 2 seams and carriers                                     |
| `execution/fakes.py`                        | test double | Fakes for every seam, `ScriptedEditor`                            |
| `execution/git.py`                          | real        | Hardened `GitWorkspace`, `repo_fingerprint`                       |
| `execution/sandbox.py`, `launcher.py`       | real        | Sandbox policy and environment; the measuring launcher            |
| `execution/procrun.py`                      | real        | `run_once`: one sandboxed, measured run                           |
| `execution/measure.py`                      | real        | Warm-ups, timed runs, fingerprints, ABAB, the test suite          |
| `execution/phase.py`                        | real        | Phase dirs and their shared cleanup                               |
| `execution/profiler.py`, `_profile_shim.py` | real        | `CProfiler` and the shim it runs in the workload's interpreter    |
| `execution/editor.py`, `editor_tools.py`    | real        | `ClaudeEditor` loop; `WorktreeEditor` tool handler                |
| `execution/preflight.py`                    | real        | `GitPreflight`                                                    |
| `execution/trial_runner.py`                 | real        | `GitTrialRunner`, `GitBaselineRunner`                             |
| `execution/combine.py`                      | real        | `GitCombiner`, `GitBranchPublisher`                               |
| `optimization/anticheat.py`                 | real        | Protected paths, capture rules, noise rule, fingerprints          |
| `optimization/judges.py`                    | real        | Judge protocol, five judges, `derive_verdict`                     |
| `optimization/ranking.py`                   | real        | Hypothesis score with lesson boost                                |
| `learning/lessons.py`                       | real        | Verdict -> `Lesson`                                               |
| `persistence/repository.py`                 | real        | `Repository` protocol, `InMemoryRepository`                       |
| `persistence/postgres.py`                   | real        | `PostgresRepository` (003 + 004 schema)                           |
| `research/arxiv_monitor.py`                 | placeholder | arXiv monitoring (Step 3)                                         |
| `research/pdf_parser.py`                    | placeholder | PDF parsing (Step 3)                                              |
| `tests/e2e/test_step2.py`                   | real        | E2E-A, E2E-B, E2E-C on the `dedupe_repo` fixture                  |
| `tests/orchestrator/test_graph_e2e.py`      | real        | The Step 1 graph scenarios on stubs (11 tests)                    |
| `tests/conftest.py`                         | real        | Shared fixtures                                                   |

"stub" means the module holds a deterministic stand-in kept for tests and the
default context; "test double" means it exists for tests only.

---

## Commands

```bash
uv sync --extra dev --extra database
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
TEST_DATABASE_URL=postgresql://dev:devpass@localhost:5432/ai_platform uv run pytest
uv run pytest tests/e2e --no-cov                # the Step 2 E2E only
uv run pytest -o addopts="" -m "not live" -n 2  # without coverage, keeps live off
uv run pip-audit && uv run bandit -q -r src -c pyproject.toml
```

---

**Version:** 4.2.0 **Last Updated:** 2026-10-22

**Changelog:**

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
