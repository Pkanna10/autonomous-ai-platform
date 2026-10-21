# Project Status - Autonomous AI Platform

**Last Updated:** 2026-10-21

---

## Current Step

**Build step:** 1 of 5 (Engine design) **Branch:**
`claude/adoring-clarke-xpo1py` **Vision:** a self-improving optimization engine
that uses research findings and novel ideas to provably improve existing code,
or build something new and then improve it (see `CLAUDE.md`).

---

## Development Log

One row per build step. "Gate" is the result of `pnpm stage-gate` at the end of
the step.

| Step | Deliverable                                                     | Planned    | Started    | Completed  | PR                                                                | Gate    |
| ---- | --------------------------------------------------------------- | ---------- | ---------- | ---------- | ----------------------------------------------------------------- | ------- |
| 0    | Repair & upgrade (DB init, deps, models, docs, stage gate)      | 2026-10-21 | 2026-10-21 | 2026-10-21 | [#11](https://github.com/Pkanna10/autonomous-ai-platform/pull/11) | passed  |
| 1    | Engine design (typed state, data model, judges, migration 003)  | 2026-10-21 | 2026-10-21 | 2026-10-21 | [#11](https://github.com/Pkanna10/autonomous-ai-platform/pull/11) | passed  |
| 2    | Core loop end to end on CPU Python workloads + E2E fixture test | 2026-10-21 | 2026-10-21 |            |                                                                   | pending |
| 3    | Research: arXiv, PDF, playbook, claim extraction, matcher       |            |            |            |                                                                   |         |
| 4    | Interfaces + runner: live CLI, hardware detection, `--goal`     |            |            |            |                                                                   |         |
| 5    | Dogfood: fixtures, OSS repos, real ML training pipeline         |            |            |            |                                                                   |         |

Recommended Claude Code model and effort per step: 0 Opus 5.5 High; 1 Fable 5.1
Extra; 2-4 Opus 5.5 Ultracode (Fable 5.1 for the paper matcher); 5 Opus 5.5
High, Fable 5.1 Max only when stuck.

### Step 0 summary (2026-10-21)

- Fixed `infrastructure/schema/002_fix_critical_issues.sql`: it constrained
  `research_papers.citation_count` and `applicability_score`, which were never
  created, so a fresh Postgres init aborted. Columns are now added first.
- Upgraded Python dependencies: `anthropic` 0.68 -> 1.17, `langgraph` 0.2 ->
  1.2, `langchain` 0.3 -> 1.4; `uv.lock` regenerated. Existing tests pass
  unchanged on LangGraph 1.x.
- Upgraded `@anthropic-ai/sdk` 0.68 -> 0.137; `pnpm-lock.yaml` regenerated.
- Current models: TypeScript `DEFAULT_MODEL = claude-opus-5-5`; `streamChat`
  accepts a model; `temperature` is only sent when a caller sets it (current
  models reject sampling parameters). Python settings gained `ENGINE_MODEL` and
  `TRIAGE_MODEL`.
- Docs made truthful: root and package `CLAUDE.md` files, README, this file.
  Removed the repeat-every-response rule, unverifiable statistics and
  model-identity claims; fixed references to files that did not exist; added
  `packages/execution-engine/CLAUDE.md`; deleted two identical
  `CLAUDE.md.backup-*` copies (recoverable from git history).
- License aligned to ISC everywhere (`LICENSE`, `package.json`,
  `pyproject.toml`).
- Added the stage-gate workflow: `scripts/stage-gate.sh`, `pnpm stage-gate`,
  `[tool.bandit]` config, and the "Development Workflow" section in `CLAUDE.md`.
- First stage-gate run caught stale lockfiles: `pnpm audit` reported 68
  advisories (1 critical, 43 high) and `pip-audit` 22 (urllib3, requests,
  pydantic-settings, pytest, python-dotenv, pygments, nltk, pip). Fixed by
  `pnpm update -r` (declared ranges bumped to the installed versions) plus an
  explicit `vite >= 7.3.7` dev dependency (vitest's peer stayed on 7.1.12
  otherwise), and `uv lock --upgrade`. Both audits are now clean.
- Removed `cache-dir = "~/.cache/uv"` from `pyproject.toml`: uv does not expand
  `~` in config files and had created a literal `services/python_agents/~/`
  directory inside the repo.

### Step 1 summary (2026-10-21)

The engine loop exists as a walking skeleton: every node from `connect` to
`watch` is wired in LangGraph and runs end to end on deterministic stub data,
with no LLM call, subprocess or git involved. What is final: the data model, the
anti-cheating rules, the five judges and the verdict order, hypothesis ranking
with lessons, the approval interrupt and durable resume, the delivery guard and
the lessons store. What is stubbed behind stable interfaces: `understand`,
`profile`, `research`, both runners and `watch`.

```
START -> connect -> understand -> define -> baseline -> profile -> research
      -> hypotheses -> trials -> judges -> verdicts --(after_verdicts)--+
             ^                                                         |
             +---- another round (nothing kept, round < max_rounds) ---+
                                                                       |
     END <- watch <- learn <- deliver <- combine <- approval_gate <----+
                                                    (interrupt -> human)
```

The seven end-to-end scenarios from the briefing pass on the compiled graph: H1
(efficiency, 41.7% faster) is kept and delivered on an `engine/` branch; H2 is
rejected for touching `tests/test_cache.py` although every judge passed; two
below-noise candidates take two rounds and `max_rounds=1` stops early; H4
(behaviour change) pauses the run with an `ApprovalRequest`, resumes with the
human's decision, and is delivered when approved or reported only when rejected;
a second graph instance over the same checkpointer resumes the same thread; a
graph without a checkpointer cannot resume.

- `common/models.py`: 27 frozen pydantic models and 13 `StrEnum`s (values mirror
  the SQL `CHECK` lists); `ENGINE_SERDE_ALLOWLIST` for the checkpointer.
- `optimization/anticheat.py`: protected paths (tests, benchmarks, CI,
  manifests, lockfiles, interpreter hooks), traversal rejection, the noise
  floor, run-count rule and sha256 output fingerprints.
- `optimization/judges.py`: speed, memory, equivalence, guardrail-metric and
  test-suite judges plus `derive_verdict`.
- `optimization/ranking.py`, `learning/lessons.py`: score with lesson boost;
  verdict to lesson.
- `orchestrator/`: `EngineState` (25 keys, 4 append-only channels), 15 node
  closures over a frozen `NodeContext`, the router,
  `Orchestrator.run / resume / stream`, live `EngineEvent`s.
- `execution/runner.py`, `persistence/repository.py`: `TrialRunner`,
  `BaselineRunner` and `Repository` protocols with stub and in-memory
  implementations.
- `infrastructure/schema/003_engine.sql`: 8 new tables, 3 extended, idempotent;
  verified by two CI jobs: `schema-apply` (psql, idempotence diff) and
  `compose-init`, which runs `docker compose up postgres` on an empty volume
  exactly as a developer does and asserts a clean init log and 14 tables, so the
  manual Docker check is no longer needed.
- Tests: 560 passing, 100% coverage of 1,431 statements; mypy strict on `src`
  and `tests`; the stage gate now type-checks tests too.

Reviewed by the Reviewer role (Opus 5.5) in three passes (wave 1, wave 2, a
verification pass on the wave-2 fixes) plus a `/security-review`; every blocking
finding was fixed test-first in a follow-up commit before the gate. Stage gate:
passed (2 warnings: outdated majors left to Renovate).

---

## What Exists Today

| Component                                                                            | State                              |
| ------------------------------------------------------------------------------------ | ---------------------------------- |
| Docker Compose: Postgres 16 + pgvector, Redis, Qdrant                                | Working                            |
| Schema `001_initial.sql` + `002_fix_critical_issues.sql` + `003_engine.sql`          | Working; applied in CI on every PR |
| CI: lint, typecheck, tests, coverage, Python CI                                      | Working                            |
| Security: OSV, Trivy, Docker Scout, pip-audit, bandit, safety, secret scan, Renovate | Working                            |
| `packages/agent-core` Claude client + shutdown                                       | Working (33 Vitest tests)          |
| `services/python_agents` settings                                                    | Working                            |
| LangGraph orchestrator (`EngineState`, 15 nodes, router, `Orchestrator`)             | Walking skeleton on stub data      |
| `research/arxiv_monitor.py`, `pdf_parser.py`                                         | Placeholders                       |
| `packages/research-engine`, `execution-engine`                                       | TypeScript placeholders            |
| Data model, anti-cheating, judges, ranking, lessons, repository protocol             | Working (Step 1)                   |
| Real runners, profiler, research matcher, Postgres repository, CLI, web console      | Not started                        |

---

## Decisions

### 2026-10-21 (Step 2)

Designed by a research-and-design workflow: four research tracks verified in the
sandbox (process measurement, git worktrees, the Claude editor, Postgres and the
fixture), three independent designs (security-first, smallest testable,
forward-compatible), two judges on different models (both chose the smallest
testable design, 39 and 40 of 50), a synthesis and a completeness critic whose 5
blockers and 12 should-fixes were closed before building.

- **Every external effect sits behind a protocol with a deterministic fake**
  (git, process runner, editor, Claude transport, profiler, combiner, publisher,
  repository): the whole loop must be provable in CI with no API key and no
  network.
- **Workloads start through a tiny launcher process**: on Linux a child's peak
  RSS can never read below the RSS of the process that spawned it (measured: a
  `/bin/true` child of a 311 MiB engine reports 311 MiB; through a fresh
  launcher, 6.5 MiB). Without it the memory judge measures the engine, not the
  workload.
- **Trials run sandboxed and fail closed**: network namespace (`unshare -rn`)
  with a private loopback, Landlock write confinement to the worktree and a
  scratch directory, a PID namespace so orphans die, and a per-run self-check
  that the isolation really applied (macOS: `sandbox-exec` with the same
  checks). The engine runs Claude-edited code on the user's machine; a fresh
  HOME is not a sandbox.
- **The engine never trusts what the editor says it changed**: the diff and the
  touched paths come from git after the edit (`--no-renames`, so a renamed test
  shows up as a protected path), symlinks, mode changes, binaries, git metadata
  and unreported writes are violations, and a violating trial is never executed.
- **The user's repository is fingerprinted before and after every phase that
  runs repo code** (refs, config, hooks): tampering aborts the run.
- **The cost cap is a hard bound**: the SDK's own retries are off, every attempt
  is checked against a worst-case estimate before it is sent, the fallback chain
  that is billed is the chain that is priced, and the trials node keeps a
  running total so three trials cannot each spend the full remainder.
- **Combine always re-tests**: the combined change is measured interleaved with
  a fresh baseline (ABAB) and the test suite runs on its tip; it is delivered
  only if the full verdict rules still say keep, else the best single change is
  re-tested, else the run delivers a report only.
- **Delivery is a create-only ref update**: `refs/heads/engine/run-<id>` is
  created with `update-ref`, never `branch -f`, never on a checked-out or
  default branch, never pushed.
- **Trials run serially**: overlapping measurements disturb each other, and this
  host's run-to-run variation is already 9-28 %.
- **Postgres stores runs, trials and verdicts in the 003 JSONB columns; no new
  tables** (migration 004 only adds a thread index, a lesson sequence and
  `projects.test_command`): one source of truth per run, and the state
  round-trips through a typed serializer that also works on Python 3.11.

- **The measurement report cannot be forged** (wave 2 security review): inside
  `unshare -r` the workload is root in its own user namespace and could write a
  fake report into the launcher's pipe through `/proc/<pid>/fd`, which Landlock
  does not cover. Reproduced, then closed with three measures verified together
  on this host: a namespace-private `/proc` (`--mount-proc`, which also hides
  the `unshare` process), a non-dumpable launcher, and a workload that drops
  every capability before exec. A fresh `/proc` alone still let the forgery
  through. The process runner also cross-checks the report against the kernel's
  accounting of the whole process tree.
- **A trial cannot replace the test runner**: `python -m unittest` and pytest
  put the working directory first on `sys.path`, so an added `unittest.py` would
  make a failing suite pass. Adding a top-level module named after the standard
  library or the test runner is refused by the editor and rejected by the
  capture rules, and every config file pytest reads (including `.pytest.ini` and
  `pytest.toml`) is protected.
- **Threads are allowed, processes are not** (when CPU or memory is judged):
  threads cannot fake per-process CPU or memory accounting and are a legitimate
  optimisation; process pools can.
- **One fallback model and 8,000-token editor turns by default**: the cost cap
  is a hard bound, so each request must fit its worst case (every model in the
  chain billing a full response). With two fallbacks and 16,000 tokens a single
  request was estimated at about $3 with a typical prompt, leaving a $5 run one
  or two requests; now an empty-prompt request is $0.40.
- **`/dev/shm` is not writable inside the sandbox**: it survives between timed
  runs, so a workload could carry results from one run to the next. Workloads
  that need shared memory get a per-run tmpfs in Step 5.

### 2026-10-21 (Step 1)

- **Team and process adopted** (see `CLAUDE.md` "Development Workflow"): Lead,
  Builders, Reviewer (different model, read-only), Verifier, Researcher; Shape
  Up / Kanban / XP / DORA. Evidence from the research pass: DORA 2025 (AI raises
  throughput, hurts stability without small batches and strong version control),
  Google review data (median change ~24 lines, one reviewer), TDD studies
  (40-90% fewer defects), Anthropic's SDLC ("separating agents is critical"),
  self-preference bias of same-model review, and agent test-gaming rates
  (39-76%).
- **Judges live outside the engine state** (in `NodeContext`), and the paths
  that configure them are protected: reward hacking is the dominant failure mode
  of optimisation agents, so nothing a trial writes may reach what judges it.
- **A gain must strictly exceed a measured noise floor** (max of 2 x stdev on
  either side and a minimum relative gain): single timings lie; five runs and a
  floor make "faster" a claim with evidence.
- **Models are frozen and forbid unknown fields; state lists use `operator.add`
  reducers and nodes return deltas**: checkpoints replay state, and Step 2's
  parallel trials append concurrently.
- **Human approval is a LangGraph `interrupt()` inside `approval_gate`**, not
  `interrupt_before`: the decision travels in `Command(resume=...)` and lands in
  state; the node does nothing before the interrupt because that code re-runs on
  resume.
- **No SQLAlchemy/alembic yet**: a `Repository` protocol with an in-memory
  implementation; Postgres via `psycopg` and parameterised SQL in Step 2. Schema
  stays hand-written SQL applied by the Postgres entrypoint.
- **Schema 003**: every project-scoped foreign key cascades on project delete (a
  lesson with `project_id = NULL` means _global_, so SET NULL would have leaked
  one project's lessons into all others); `lessons.hypothesis_id` and
  `technique_id` carry no foreign key because hypotheses and techniques live
  inside the run state (`task_executions.state JSONB`); ranking inputs are
  `NOT NULL` as in the models; unique partial index on `research_papers.doi`.
  Verified locally on PostgreSQL 16 + pgvector and by the `schema-apply` CI job,
  which diffs the catalog before and after a second run to prove idempotence.
- **A secondary objective inside its noise floor is neutral.** With two
  objectives (runtime, memory), an unchanged memory figure must not veto a
  proven speedup; only the primary objective and guardrail judges block, and
  regressions beyond noise still fail.
- **The Reviewer role paid for itself on its first pass**: it found that
  checkpoints dropped enum types on resume (`state["phase"]` became a plain
  string), that the speed judge could pass a workload inside its own noise
  floor, order-sensitive fingerprint pairing, missing path validation on
  `Workload.working_dir`, and unprotected dependency manifests and interpreter
  hooks. All fixed with tests first (`f1c1003`, `da6e30a`).
- **GHA cache export made non-fatal** (`ignore-error=true`) after a build failed
  on `error writing layer blob: not_found` with a fully built image.
- **Nodes are closures over a frozen `NodeContext`** (`make_nodes(ctx)`), not
  module-level functions reading globals: the runner, judges, repository,
  protected patterns and rigour knobs are injected once, so tests script every
  external effect and nothing in the checkpointed state can replace a judge.
- **The round loop is bounded by `max_rounds` and by the candidate pool**: the
  router goes back to `hypotheses` only when nothing was kept, the round cap is
  not reached and untrialled candidates remain; otherwise it proceeds to
  `combine` even with nothing to deliver, so a run always ends with a report.
- **`hypotheses` is a plain key that carries earlier rounds forward**: the
  report and the lessons need every idea the run tried, so each round keeps the
  decided hypotheses and appends the newly ranked ones; `trials` runs only the
  `proposed` ones.
- **Judge results travel through the repository, not the `trials` channel**: the
  channel is append-only, so `judges` saves the judged copy and `verdicts` reads
  it back. The Step 2 Postgres repository makes that path durable; the verdict
  itself carries the judge results, so the state stays self-describing.
- **A failed run is a result, not an exception**: `EngineError` (untrustworthy
  baseline, unknown hypothesis, malformed approval payload) becomes
  `EngineRunResult(status="failed")` with the last checkpointed state and the
  error text; `stream` ends with one error-level event. Any other exception
  propagates, because it is a bug.
- **`mypy` runs on `tests` as well as `src` in the stage gate**: typed tests
  caught two real signature drifts in Step 1; the cost is zero once tests are
  written typed from the start.
- **The state is the only source of truth inside a run** (review wave 2): judge
  results first travelled through the repository because the `trials` channel is
  append-only; a resume on a fresh repository then lost every verdict of the
  round. A plain `round_trials` key (replaced each round) now carries the
  round's trials from `trials` through `judges` to `verdicts`, and the
  repository is an audit sink.
- **Every objective and guardrail metric must be measured exactly once per
  workload**: the run-count rule only checked measurements that existed, so a
  trial could be kept by omitting a secondary metric or listing a fast (or
  healthy) duplicate first. Missing and duplicate measurements are violations;
  an incomplete baseline fails the run. The minimum run count applies to
  objective metrics only, because guardrails are bounded, not proven.
- **The approval gate never raises after `interrupt()`**: LangGraph replays the
  first resume value, so an exception after the interrupt wedges the thread for
  good. A malformed decision re-interrupts with the error on the request.
- **Branch names use full ids and are never nested** (`engine/run-<run_id>`,
  `engine/trial-<run_id>-<hypothesis_id>`): 8-character prefixes collided and
  `engine/<run>` cannot coexist with `engine/<run>/<trial>` in git. Run ids,
  candidate ids, the prefix and every branch are validated as git refnames.
- **One representation of a human decision**: the gate, `combine`, the report
  and the lessons all derive from `decided_verdicts(verdicts, approval)`, and
  the gate saves the decided copies, so the repository, the state and the report
  agree.
- **Trial branches are not idempotent yet**: lesson ids are `uuid5(verdict id)`
  so a re-executed `learn` replaces rather than duplicates rows; trial ids come
  from the runner and get an idempotency key with the real runner in Step 2.
- **The default context fails loudly instead of faking a baseline**: the
  `langgraph.json` entry point compiles over stub runners that measure nothing,
  so a run on it stops at the baseline with `missing_measurement`. A default
  that fabricated numbers would let the engine report "done" on nothing; the
  real runner (Step 2) replaces the stub.
- **Dependency majors wait for their own PRs** (TypeScript 7, ESLint 10, Vitest
  5, Vite 8, redis 8, PyMuPDF 2): none is needed by Step 1 and each changes
  tooling behaviour; Renovate opens them weekly.

### 2026-10-21

- **Vision clarified.** One user-facing goal ("make it better"); internally,
  judges per improvement kind (speed/memory, quality, robustness, novel
  capability); autonomy proportional to verifiability; one loop for all judges.
- **Keep the 7-layer architecture and the repo layout.** Build L4, L6, L7; build
  L3 narrowly later; integrate L1, L2 (LangGraph), L5 (sandboxes). An earlier
  proposal to drop LangGraph, `packages/` and the placeholder modules was
  withdrawn.
- **Keep LangGraph** for checkpointing/resume of long trials, human-in-the-loop
  interrupts, conditional retry edges and streamed node events.
- **Models via settings only.** `ENGINE_MODEL` and `TRIAGE_MODEL`; no model
  strings in code.
- **Stage gate after every step** (upgrades, audits, security review, docs,
  quality, PR). Recorded in the Development Log above.
- **Market research (2026-10-21).** Interfaces, orchestration and sandboxes are
  commoditized (Claude Code, Codex, Cursor, Devin, Lovable, E2B, Modal).
  Paper-to-standalone-repo tools exist (PaperCoder, DeepCode, alphaXiv). No
  product turns research plus experiments into proven improvements of a user's
  own code; systems and algorithms papers are nearly untouched. "PaperForge" as
  a name is taken.

### 2025-11 (summary of the foundation phase)

- Monorepo with pnpm workspaces, Turborepo, Husky and commitlint.
- Docker Compose for Postgres + pgvector, Redis and Qdrant with healthchecks.
- Python 3.11 service with uv, Hatchling, Ruff, mypy strict, pytest-xdist.
- Multi-stage Dockerfiles (non-root, tini, BuildKit secrets), multi-platform
  builds, SBOM and provenance.
- CI with path filtering and caching; security workflows with OSV, Trivy and
  Docker Scout; Renovate.
- Hierarchical `CLAUDE.md` files.

---

## Next: Step 2 (Core loop on CPU Python workloads)

Recommended session setting: **Opus 5.5, Ultracode** (Fable 5.1 for the briefing
and the review of the runner's isolation).

- [ ] Real `BaselineRunner` and `TrialRunner`: git worktree per trial,
      subprocess runs of `Workload.command` (argv, no shell) with warm-up and
      N >= 5 timed runs, peak RSS, output fingerprints, timeouts, network off.
- [ ] `understand` node on `ENGINE_MODEL` with the `--max-cost` cap and token
      accounting into `cost_usd` / `tokens_used`.
- [ ] Trial edits by Claude inside the worktree; diff capture into `Trial.diff`
      and `touched_paths` (the anti-cheating input).
- [ ] `combine` re-tests the combined diff; `deliver` creates the real
      `engine/<run>` branch (never the default branch).
- [ ] Postgres `Repository` with `psycopg` and parameterised SQL
      (`task_executions.user_intent` is `NOT NULL`; fill it from the goal).
- [ ] E2E fixture: a small CPU Python repo with a known win, run through the
      whole loop in CI.
- [ ] Decide whether judged trials get their own state key (see Decisions).
- [ ] Stage gate, development log row, PR, report.

---

## Metrics Snapshot (2026-10-21)

| Metric                         | Value                                                      |
| ------------------------------ | ---------------------------------------------------------- |
| Python tests                   | 560 passed                                                 |
| Python coverage                | 100% of 1,431 statements (placeholders excluded)           |
| TypeScript tests               | 33 passed                                                  |
| Product code (non-placeholder) | ~3,200 lines Python + 450 lines SQL; ~8,000 lines of tests |
| Engine features shipped        | Walking skeleton of the full loop (stub runners)           |

---

## Delivery Metrics (DORA-style, per step)

| Step | Lead time | CI-red pushes                | Rework commits        | Reverts |
| ---- | --------- | ---------------------------- | --------------------- | ------- |
| 0    | ~2 h      | 0                            | 0                     | 0       |
| 1    | ~4.5 h    | 2 (GHA cache; README format) | 6 (regroup, 5 review) | 0       |

## Lessons (retro per step)

### Step 1

- **A Reviewer on a different model earns its cost.** Two passes found seven
  real defects (enum types lost on resume, a judge passing inside its noise
  floor, order-sensitive fingerprint pairing, missing path validation, open
  protected-path gaps, and more) that the authors and the Lead had missed. Keep
  it mandatory for every unit that touches judges, state or security.
- **Split units by source size, not by topic.** U7+U8 (nodes plus graph) grew to
  ~1,100 source lines and ~2,700 test lines in one Builder; it worked but took
  the longest of any unit. Cap a Builder at ~400 source lines and give parallel
  Builders a shared fixture contract (`conftest.py`) up front.
- **Parallel Bash calls share a working directory.** A `cd` inside one call
  moved another Builder's files into the repo root. Lead and Builders now use
  absolute paths only.
- **Guard the commit header length and the pipeline exit code.** Commitlint
  rejected 72+ character headers three times, and `cmd | tail && git commit` let
  a mypy failure through once. The Lead checks `wc -c` on the header and uses
  `set -o pipefail` before every commit.
- **Ruff formats fenced Python in Markdown.** README examples must pass
  `ruff format --check` like code; the gate caught it.
- **Record decisions as they are made.** Writing the "why" into this file while
  the unit was fresh made the Step 1 report a copy job instead of an archaeology
  job.

---

## Technical Debt

- `pyproject.toml` `[project.scripts]` and `[project.entry-points]` reference
  modules that do not exist yet (`cli`, `codegen`, `tools`, `integrations`).
  Implement or remove in Step 4.
- `packages/research-engine` (TypeScript) duplicates the Python research
  module's purpose. Decision (Step 1): it stays a placeholder until TypeScript
  workloads exist; research is built in Python.
- `StubTrialRunner._unit_for` labels `throughput_per_s` as seconds; fix when the
  real runner lands.
- Both pgvector and Qdrant are configured. Pick one when embeddings land (Step
  3).
- `services/python_agents/Dockerfile` installs with pip while CI uses uv.
- Local development may run on Python 3.13 while CI pins 3.11.

---

## Useful Commands

```bash
pnpm stage-gate                               # full gate
pnpm stage-gate:quick                         # quality only
cd services/python_agents && uv run pytest    # Python tests
pnpm test                                     # TypeScript tests
docker compose -f docker-compose.dev.yml up -d
```
