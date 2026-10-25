# Autonomous AI Platform

> A self-improving optimization engine that uses research findings and novel
> ideas to **provably** improve your existing code, or to build something new
> and then improve it.

[![Status](https://img.shields.io/badge/status-engine_rebuild-yellow)](<>)
[![Step](<https://img.shields.io/badge/build_step-3_(wave_1)-blue>)](<>)
[![License](https://img.shields.io/badge/license-ISC-lightgrey)](<>)

---

## What It Does

You give the platform code you run (or an English description of what to build)
and one goal: **make it better**. The engine then:

1. **Understands** the code and works out what "better" means: by default faster
   and leaner with outputs unchanged (wall time must drop, and peak memory may
   grow by at most 10%). With a quality number you confirm once (accuracy, an
   error rate, your own scorer), a change may alter the output as long as the
   number holds within the drop you allow ("accuracy may drop at most 0.5
   points"). Goals in plain English ("memory under 16 GB") come with the Step 4
   CLI.
2. **Measures** a baseline and **profiles** where time and memory actually go.
3. **Generates hypotheses** from the profile with Claude when you hand it none.
   A playbook of known techniques can be matched to the hotspots (built, off by
   default); papers (arXiv, Semantic Scholar) come only if a planned re-test
   shows retrieval helps.
4. **Runs experiments**: each hypothesis is applied in its own git worktree,
   measured over repeated runs alternately with an unchanged copy of your code,
   and judged against frozen evaluators (speed, memory, output equivalence or
   your quality number, your tests, your guardrail metric). A trial that crashes
   on a fixable error (a typo, a missing import) gets one second chance per run.
5. **Keeps only proven wins**: every winner is checked a second time, then the
   wins are combined, re-tested, and delivered as a branch with a report: what
   changed, by how much, give or take how much, and what was rejected and why.
6. **Learns** from every verdict and **keeps watching** for new papers and code
   changes.

Autonomy follows verifiability: efficiency wins with identical outputs go to
`engine/run-<id>`; changes that alter behaviour or output go to a separate
review branch, `engine/review-<id>`, with a label; novel ideas are proposals for
you to approve. The engine never pushes, and never touches your default branch.

### Example

```
$ aip improve ./vlm-llm-bridge --run "python train_bridge.py --steps 200"

[00:06] GOAL        minimize s/step · guardrails: val-loss ±1%, mem ≤ 36 GB
[00:31] BASELINE    5 runs → 1.82 s/step ± 0.04
[01:10] PROFILE     42% encoder.forward (frozen, recomputed) · 21% image decode
[02:40] RESEARCH    playbook: 4 matches · papers: FastV (arXiv 2403.06764) ✓
[06:12] TRIAL H1    cache frozen-encoder embeddings → 1.05 s/step   ✅ KEEP
[09:40] TRIAL H4    bf16 autocast on MPS → 0.79 s/step, val-loss +2.7%  ❌ REJECT
[21:05] COMBINE     H1+H2+H3+H5 → 0.74 s/step (2.5×) · all guardrails ✓
[21:30] DELIVER     PR #12 opened · report attached
```

The CLI above is the target for build Step 4; the numbers are illustrative.

---

## Architecture: 7 Layers

The 2025 design (`documentation_guide/`) defined seven layers. All seven are
kept. The table says where each lives and whether we build it, buy it or
integrate it.

| Layer                     | Where                                         | Decision                                                                                                    |
| ------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| L1 Interfaces             | CLI (Step 4), web console, GitHub App, plugin | Integrate with the tools developers already use                                                             |
| L2 Orchestrator           | `services/python_agents/.../orchestrator/`    | LangGraph 1.x: checkpointing, interrupts, retries                                                           |
| L3 Capability acquisition | `capabilities/` (planned)                     | Acquire packages, MCP servers and APIs automatically under an automatic policy; ask only when a check fails |
| L4 Research               | `services/python_agents/.../research/`        | **Build**: generator (Step 3), playbook and matcher (off); papers only if the re-test calls for them        |
| L5 Execution              | local runner, `packages/execution-engine`     | Trials on your hardware (CPU, CUDA, Apple MPS)                                                              |
| L6 Optimization           | `optimization/`                               | **Build**: hypotheses, trials, judges, verdicts                                                             |
| L7 Self-improvement       | `learning/`                                   | **Build**: lessons store, evaluator-gated; self-healing (a failing test or crash becomes a hypothesis)      |
| Persistence               | `infrastructure/schema/`                      | PostgreSQL 16 + pgvector; Redis; Qdrant                                                                     |

```
CONNECT → UNDERSTAND → DEFINE "BETTER" → BASELINE → PROFILE → RESEARCH
  → HYPOTHESES → TRIALS → JUDGES → VERDICTS → COMBINE → DELIVER → LEARN → WATCH
```

---

## Current State (honest)

Step 2 built the core loop for CPU-bound Python workloads; every phase that runs
code does so for real, in a sandbox, on your machine. Step 3's first wave is
built on its branch (`claude/step3-research`, draft PR #22) and tested offline;
its end-to-end tests are in progress and no live run of it has happened yet.

| Area                                                        | State                                                   |
| ----------------------------------------------------------- | ------------------------------------------------------- |
| Docker Compose (Postgres + pgvector, Redis, Qdrant), schema | Working; migrations 001-006 applied in CI               |
| CI (lint, typecheck, tests, coverage), security scanning    | Working; Linux and macOS engine jobs                    |
| TypeScript Claude client (`packages/agent-core`)            | Working, 33 tests                                       |
| Python settings (`common/config.py`)                        | Working, validated at startup                           |
| Preflight at connect (git, LFS, submodules, sandbox probe)  | Working (Step 2)                                        |
| Understand (one Claude request, under the cost cap)         | Working (Step 2)                                        |
| Baseline, profile (cProfile), trials in sandboxed worktrees | Working (Step 2), CPU Python workloads                  |
| Claude trial editor and git-side anti-cheating              | Working (Step 2)                                        |
| Judges, verdicts, approval, combine with an ABAB re-test    | Working (Step 2)                                        |
| Generated hypotheses, one fix retry a run, review branch    | Built (Step 3 Wave 1); E2E in progress, no live run yet |
| Output check by default, quality check, noise rule          | Built (Step 3 Wave 1); E2E in progress, no live run yet |
| Delivery to a local `engine/run-<id>` branch                | Working (Step 2); never pushed, no PR yet               |
| Postgres repository (`persistence/postgres.py`)             | Working (Step 2)                                        |
| Playbook matcher; papers                                    | Matcher built, off; papers conditional on a re-test     |
| CLI, live log, hardware detection, English goals            | Not started (Step 4)                                    |

### Build order

| Step | Deliverable                                                                    | Status       |
| ---- | ------------------------------------------------------------------------------ | ------------ |
| 0    | Repair & upgrade: DB init fix, dependency bumps, current models, truthful docs | done         |
| 1    | Engine design: typed state and data models, judge and node interfaces          | done         |
| 2    | Core loop end to end on CPU Python workloads, with an end-to-end fixture test  | done         |
| 3    | Generated hypotheses, self-retry, review branch, quality check, noise rule     | Wave 1 built |
| 3c   | Self-healing: a failing test or crash becomes a hypothesis                     |              |
| 3b   | Automatic package acquisition under an automatic policy                        |              |
| 4    | Interfaces and runner: live CLI log, hardware detection, English goals         |              |
| 5    | Dogfood on fixtures, open-source repos, then a real ML training pipeline       |              |
| 6    | Production loop: error monitoring into the healer, gradual rollout             |              |

See [STATUS.md](./STATUS.md) for the development log.

---

## Quick Start

### Prerequisites

- macOS or Linux
- git 2.38 or later (Apple's git 2.39 works)
- Linux: `unshare` (util-linux) and Landlock (kernel 5.13 or later; 5.19 or
  later recommended). macOS: `/usr/bin/sandbox-exec`, which ships with the OS
- Docker (PostgreSQL, Redis, Qdrant)
- Node.js 22 (`.nvmrc`; Node 20 is end of life) and pnpm 10.20
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)

### Installation

```bash
git clone https://github.com/Pkanna10/autonomous-ai-platform.git
cd autonomous-ai-platform

# Node.js
pnpm install

# Python (the database extra installs psycopg for the Postgres repository)
cd services/python_agents
uv sync --extra dev --extra database
cd ../..

# Environment
cp .env.example .env            # add your ANTHROPIC_API_KEY

# Infrastructure (Postgres, Redis, Qdrant on 127.0.0.1 only; images pinned by digest)
docker compose -f docker-compose.dev.yml up -d
```

### Verify

```bash
docker ps                                                     # postgres, redis, qdrant
psql postgresql://dev:devpass@localhost:5432/ai_platform -c '\dt'   # 14 tables

pnpm typecheck && pnpm lint && pnpm test
cd services/python_agents
TEST_DATABASE_URL=postgresql://dev:devpass@localhost:5432/ai_platform uv run pytest
```

### Running the engine

There is no CLI yet (Step 4). The engine is driven from Python:
`build_context(project)` in `orchestrator/factory.py` wires the real preflight,
understander, profiler, hypothesis generator, runners, combiner and publisher,
and
`Orchestrator(context=...).run(project, workloads, objectives, guardrails, max_cost_usd=...)`
runs the loop. Hypotheses you pass as `candidates=` are tried first; when none
is left the generator proposes more.
`services/python_agents/tests/e2e/test_step2.py` shows a complete run on the
`dedupe_repo` fixture. The trial editor needs `ANTHROPIC_API_KEY`; without it
`build_context` raises `LLMConfigError` unless an editor is injected.

### What Step 3 adds (Wave 1)

- **Hypotheses with none handed over.** When no caller idea is left, Claude
  Sonnet 5.5 proposes five from the profile, at most twice a run, within a
  quarter of the cost cap and never into the money reserved for one trial. Ideas
  classed `novel` are parked in the report, never tried unattended.
- **One second chance per run.** A trial whose workload crashes with a fixable
  Python error (`SyntaxError`, `NameError`, `ImportError`, `TypeError`,
  `AttributeError` and their kin) is retried once, with only the exception type,
  a message matching a known CPython template and up to three frames fed back.
  Timeouts, failing assertions and the test suite are never retried.
- **The review branch.** A change that alters behaviour or output, and passes
  every judge, goes to `engine/review-<id>` with a label per change ("changes
  results: accuracy 91.2 % → 91.6 % (result improvement), 30.0% better, give or
  take 2.0%, confirmed twice (large)"; "behaviour change, outputs identical"),
  re-tested on its own; it is never merged into `engine/run-<id>`, and the run
  does not stop for it. Merging both branches is unproven, and the report says
  so.
- **The output check is on by default.** With no quality check, outputs (stdout
  and the declared `output_file`) must stay identical, so a program whose output
  varies run to run stops at baseline: seed it, declare a tolerance or set a
  quality check. A workload that prints nothing and declares no `output_file` is
  warned about, because the check then compares nothing.
- **Real speedups, not luck.** Each trial is measured alternately (ABBA) against
  an unchanged copy of your code; the baseline runs three A/A blocks to set a
  per-project bar, never below 2 %; every winner is re-tested once more before
  it is kept. Each gain is reported as "18.0% better, give or take 2.0%,
  confirmed twice (solid)": small under 5 %, solid 5-20 %, large over 20 %. This
  costs measurement time (about 2.6x the runs of Step 2, an estimate not yet
  measured live), not tokens.
- **A total-time line** in the report, and each trial's retry notes.

### Using a quality check

A quality check lets a change alter the output when a number you trust stays
within what you allow. You confirm it once by passing it to `build_context`
(Step 4 will ask it as one question). It is scored by a frozen evaluator from
the workload's output, never from text the trial prints:

```python
from autonomous_ai_agents.common.models import BuiltinMeasure, QualityCheck
from autonomous_ai_agents.orchestrator.factory import build_context

accuracy = QualityCheck(
    name="accuracy",
    measure=BuiltinMeasure.accuracy,  # also error_rate, macro_f1, mae, rmse
    labels="data/test_labels.txt",  # one label per line
    frozen_paths=("data/test_labels.txt",),
    max_drop=0.005,  # at most 0.5 points of accuracy
)
context = build_context(project, quality=accuracy)
```

- **The workload's output is what is scored**: its `output_file` if it declares
  one, else its stdout (complete within 64 KiB), one prediction per line, as
  many lines as the labels file.
- **Your own scorer** instead of a builtin:
  `scorer=("python3", "eval/score.py")` with every file it reads in
  `frozen_paths` and a `direction`. It gets the output on stdin, runs from a
  frozen copy of those files (so it must be self-contained), and prints exactly
  one line, `aip-quality/1 <name>=<number>`. It runs on the interpreter found on
  the engine's `PATH`, so your project's installed packages may not be
  importable from it.
- **The frozen files are evaluation data**: recorded by sha256 at baseline,
  protected (a trial that edits one is rejected), hidden from the editor, and
  deleted from the worktree before every workload run, so code that opens the
  labels fails. Write predictions; let the scorer read the labels.
- **Check the labels are not in your inputs.** The check is sound only if no
  other readable project file carries the labels (a test CSV with the label
  column still in it). The engine warns when a file a workload names holds the
  labels as a column; every report with a quality check states this.
- **What still needs your review.** Confinement is for writes only, so code
  could read the labels another way, or bake a table of label values into the
  source. That is why every output change goes to the review branch with its
  diff, never to the run branch.
- **Cosmetic differences** can count as equal with
  `Workload(output_tolerance=OutputTolerance(float_digits=9, unordered_lines=True))`:
  decimals compared to 9 significant digits, and line order ignored, except an
  unterminated last line. Integers are always exact; a count printed as a
  decimal (`1234567890.0`) is compared to the stated digits only.

### Keep workloads at about 0.3 s or longer

The noise rule sets the bar from how much your timings wobble. A workload that
runs in a few milliseconds is dominated by start-up noise, so its bar can rise
so high that no gain can be proven: the run then says so ("no gain can be proven
on this host") and stops at baseline, or finds nothing. Give each workload
enough work to run for at least about 0.3 s per run (0.5-1 s is better).

---

## Development

### Project structure

```
autonomous-ai-platform/
├── packages/
│   ├── agent-core/        # TypeScript Claude client, shared Node utilities
│   ├── research-engine/   # TypeScript placeholder (research lives in Python)
│   └── execution-engine/  # TypeScript placeholder (ts-morph work, later)
├── services/
│   └── python_agents/     # LangGraph orchestrator, research, engine (Python)
├── infrastructure/
│   ├── docker/            # Node Dockerfile, healthcheck
│   └── schema/            # PostgreSQL migrations
├── scripts/               # Security scans, stage gate
├── documentation_guide/   # Original 2025 vision documents
├── CLAUDE.md              # Conventions and build order (plus one per package)
├── STATUS.md              # Development log
└── SECURITY.md            # Security policy
```

### Commands

```bash
# TypeScript
pnpm typecheck            # tsc --noEmit
pnpm lint                 # ESLint
pnpm test                 # Vitest
pnpm test:coverage        # Vitest with coverage thresholds
pnpm format:check         # Prettier

# Python (from services/python_agents)
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run pytest             # -m "not live" by default; coverage >= 90% enforced
uv run pytest tests/e2e --no-cov            # the E2E scenarios only
uv run pytest -m "not live and not slow"    # everything except the E2E

# Security
pnpm security             # pnpm audit, OSV, Trivy, Docker scans
uv run pip-audit && uv run bandit -r src -c pyproject.toml

# Stage gate (run at the end of every build step)
pnpm stage-gate           # outdated + audits + full quality checks
pnpm stage-gate:quick     # quality checks only
```

### Tests

- **Default:** `pyproject.toml` adds `-m "not live"`, so a plain `pytest` never
  calls the Claude API. A `-m` you pass replaces it: keep `not live` in it.
- **Database tests** (`postgres` marker) run against PostgreSQL 16 with pgvector
  at `TEST_DATABASE_URL` and skip when it is unset. The role must be allowed to
  create databases: each pytest worker creates its own database, applies
  `infrastructure/schema/*.sql` and drops it at the end. The Docker Compose
  database above works.
- **Sandbox tests** skip when the host cannot isolate a run.
  `REQUIRE_NETWORK_SANDBOX=1` and `REQUIRE_FS_SANDBOX=1` (set in CI) turn those
  skips into failures.
- **Profiler and retry-template tests** run under `python3.8` to `python3.14` as
  well as the engine's own Python; an interpreter missing from `PATH` skips
  locally and fails CI. `uv python install 3.8 3.9 3.10 3.11 3.12 3.13 3.14`
  installs them, as CI does.
- **E2E** (`tests/e2e`, marker `slow`): Step 2's three scenarios on the
  `dedupe_repo` fixture with scripted Claude replies and real git, sandbox and
  measurement, pinned to Step 2's settings. They use Postgres when
  `TEST_DATABASE_URL` is set, else the in-memory repository. Step 3's scenarios
  (E3-A to E3-I: generation, the retry, the review branch, the quality check,
  the noise rule) are in progress.
- **Live smoke test** (marker `live`): one real Claude edit under a $0.50 cap.
  It runs only when selected with `-m live` and `ANTHROPIC_API_KEY` is set. In
  CI it is the `live-smoke` job, started by hand (`workflow_dispatch`: Actions >
  CI > Run workflow), never on push. The job uses the GitHub environment `live`,
  which holds `ANTHROPIC_API_KEY` as an environment secret, not a repository
  secret.
- **Live experiments** (`tests/live/experiments/` and the discovery suites in
  `tests/live/`): the Window 0 measurements for Step 3 (API compatibility
  probes, batch triage, cited paper extraction, hosted web research, a sandbox
  pre-screen, the blind hypothesis sweep, the playbook A/B and editor
  escalation). Each is a `suite` choice of `live-smoke`; `STATUS.md` lists each
  suite's cap and expected cost. Step 3 adds the `wired` corpus mode (no
  hypothesis handed over: the engine generates them), an `editor_model` choice,
  and a paired path for the `noise` suite.

### Development workflow

Every build step ends with the same stage gate before its PR is marked ready:

1. **Upgrades:** review outdated dependencies and upgrade within the step.
   Dependabot opens weekly grouped PRs for anything missed (seven-day release
   cooldown; security updates open immediately); `renovate.json` is ready for
   when the Renovate app is installed.
2. **Audits:** `pnpm audit`, `pip-audit` and `bandit` must be clean;
   `security.yml` (OSV, npm audit, licenses, zizmor workflow lint) runs on every
   push and every Monday.
3. **Security review** of the code the step added, against the OWASP checklist
   in `CLAUDE.md`, adding protections where the step needs them.
4. **Docs:** README (what and how), STATUS.md development log, CLAUDE.md if
   conventions changed.
5. **Quality:** `pnpm stage-gate` runs typecheck, lint, format, tests and
   coverage for both ecosystems.
6. **PR:** draft, CI green, then ready for review.

### Conventions

- Test-driven development: tests before implementation, 90%+ coverage.
- Explicit types: no `any` in TypeScript; mypy strict in Python.
- Conventional commits, enforced by commitlint through Husky.
- Models are configured, never hard-coded: `ENGINE_MODEL` (default
  `claude-opus-5-5`), `GENERATOR_MODEL` (default `claude-sonnet-5-5`) and
  `TRIAGE_MODEL` (default `claude-haiku-5-5`).

### CI and security

GitHub Actions runs on every push and pull request:

- TypeScript: ESLint, `tsc`, Vitest with coverage; Prettier format check
- Python: Ruff lint and format, mypy on `src` and `tests`, pytest with coverage
  against a pgvector Postgres 16 service, after a probe that fails the job when
  the runner cannot sandbox (`unshare`, Landlock)
- macOS: the execution tests with `sandbox-exec` and Apple's `/usr/bin/git`
  (blocking)
- Schema: migrations 001-006 applied in order, then 003 onward re-applied to
  prove they are idempotent
- `pip-audit` in the Python job, and weekly over every package in `uv.lock`
- Live Claude smoke test: manual only (see Tests above)
- Security: `pnpm audit` (blocking), OSV scanner (reporting), Trivy (config and
  images), zizmor workflow lint (blocking); every action pinned to a commit SHA,
  every base, BuildKit and dev-stack image to a digest, least-privilege workflow
  tokens; SBOM and provenance attestations on image builds
- Dependencies: Dependabot with grouped, scheduled upgrade PRs and a seven-day
  release cooldown (`renovate.json` equivalent kept for Renovate)

---

## Environment Variables

The Python settings
(`services/python_agents/src/autonomous_ai_agents/common/config.py`) come from
the environment or a `.env` file in the current directory. Names are
case-sensitive; lists and tables are JSON. Every value is validated at startup,
so a bad one fails at import, not in the middle of a run.

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...    # needed by understand and the trial editor
ENGINE_API_BASE_URL=https://api.anthropic.com
DATABASE_URL=postgresql://dev:devpass@localhost:5432/ai_platform
REDIS_URL=redis://localhost:6379
QDRANT_URL=http://localhost:6333
NODE_ENV=development
ENGINE_MODEL=claude-opus-5-5          # optional override
TRIAGE_MODEL=claude-haiku-5-5         # optional override
```

Engine settings added in Step 2 (defaults shown):

| Setting                                                               | Default                       | What it does                                                                                                                                                                                                                                              |
| --------------------------------------------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ENGINE_API_BASE_URL`                                                 | `https://api.anthropic.com`   | The only address the key and prompts go to: https, a host, no credentials. The engine ignores the SDK's `ANTHROPIC_BASE_URL`, which a host or tool may set for its own use.                                                                               |
| `MAX_COST_USD`                                                        | `5.0`                         | Hard cap on Claude spend per run (0 allows no paid call). `Orchestrator.run(max_cost_usd=...)` sets it per run.                                                                                                                                           |
| `NETWORK_ISOLATION`, `FS_ISOLATION`                                   | `required`                    | `required` fails the run when the sandbox did not apply (checked on every run); `best_effort` runs anyway and records what applied in each measurement; `off` runs unsandboxed. The report shows both modes.                                              |
| `WORKTREE_ROOT`                                                       | `~/.cache/aip/worktrees`      | Where every phase's worktree lives. Absolute or starting with `~`; it must not overlap (be inside or contain) the checkout, the repository's `.git` directory or any other worktree of the repository.                                                    |
| `ENGINE_FALLBACKS`, `ENGINE_FALLBACK_MODELS`                          | `true`, `["claude-opus-4-8"]` | The server-side fallback chain sent with every request. The cost estimate prices the same chain, so each extra model raises the worst case of one request.                                                                                                |
| `MODEL_PRICING`                                                       | built-in table                | USD per million tokens per model (`input`, `output`, `cache_write`, `cache_read`, optional `long_context` tier: Haiku 5.5 bills a prompt over 100K tokens at its long rates). Startup fails if `ENGINE_MODEL`, a fallback or `TRIAGE_MODEL` has no price. |
| `GIT_EXECUTABLE`                                                      | `git`                         | A bare name looked up on `PATH`, or an absolute path.                                                                                                                                                                                                     |
| `GIT_TIMEOUT_S`, `TEST_TIMEOUT_S`                                     | `60`, `900`                   | Per git call; per test-suite run.                                                                                                                                                                                                                         |
| `MAX_OUTPUT_BYTES`, `OUTPUT_HEAD_BYTES`                               | 256 MiB, 64 KiB               | A run printing more than the first is killed ("output flood"); the second is the stdout head kept.                                                                                                                                                        |
| `STDERR_TAIL_BYTES`, `MAX_DIFF_BYTES`                                 | 8 KiB, 1 MiB                  | The stderr tail kept; the cap on a trial's diff and on the delivered diff.                                                                                                                                                                                |
| `EDITOR_MAX_TOKENS`, `UNDERSTAND_MAX_TOKENS`                          | `8000`, `8000`                | `max_tokens` per editor request and for the understand request.                                                                                                                                                                                           |
| `UNDERSTAND_EFFORT`, `EDITOR_EFFORT`                                  | unset                         | `output_config.effort` (`low` to `max`) for the understand request and every editor turn. Unset sends none (the model default: `medium` on Opus 5.5, `high` on Sonnet 5.5); startup fails if a model in the chain does not take the level.                |
| `EDITOR_MAX_TURNS`, `EDITOR_MAX_TOOL_CALLS`                           | `16`, `40`                    | Per trial.                                                                                                                                                                                                                                                |
| `EDITOR_MAX_FILES`, `EDITOR_MAX_FILE_BYTES`, `EDITOR_MAX_TOTAL_BYTES` | `10`, 256 KiB, 1 MiB          | What one trial's editor may write.                                                                                                                                                                                                                        |
| `LLM_MAX_RETRIES`, `LLM_TIMEOUT_S`                                    | `2`, `300`                    | Extra attempts after a transient API failure (the SDK's own retries are off); timeout per attempt in seconds.                                                                                                                                             |

Engine settings added in Step 3 (defaults shown; they are the product defaults,
read by `build_context`):

| Setting                                                              | Default                                     | What it does                                                                                                               |
| -------------------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `GENERATOR_MODEL`, `GENERATOR_EFFORT`                                | `claude-sonnet-5-5`, `medium`               | The hypothesis generator, run alone (no fallbacks).                                                                        |
| `GENERATOR_N`, `GENERATOR_MAX_CALLS`, `GENERATOR_MAX_TOKENS`         | `5`, `2`, `16000`                           | Ideas per call, calls per run, `max_tokens` per call.                                                                      |
| `GENERATED_CLASSES`                                                  | `["efficiency", "behaviour"]`               | Generated classes that are tried; any other is parked. `novel` is refused.                                                 |
| `DISCOVERY_MAX_SHARE`                                                | `0.25`                                      | Most of the cost cap the generator and matcher may spend together.                                                         |
| `RESEARCH_RETRIEVAL`, `MATCHER_MODEL`, `MATCHER_EFFORT`, `MATCHER_K` | `blind`, `claude-sonnet-5-5`, `medium`, `3` | `matched` asks the playbook matcher before generating (off by default).                                                    |
| `EDITOR_MODEL`                                                       | unset                                       | The trial editor's model; unset keeps `ENGINE_MODEL` and its fallbacks.                                                    |
| `EDITOR_FIX_RETRIES`, `EDITOR_FIX_RETRIES_PER_RUN`                   | `1`, `1`                                    | Fix retries per trial and per run, each 0 or 1.                                                                            |
| `RETRY_CLOSURE_MAX_SOURCE_BYTES`                                     | 8 MiB                                       | Most tracked source read to check a retry's feedback; past it, messages are withheld.                                      |
| `DEFAULT_OUTPUT_CHECK`                                               | `true`                                      | Without a quality check, outputs must stay identical.                                                                      |
| `OUTPUT_TOLERANCE_MAX_BYTES`                                         | 16 MiB                                      | Largest `output_file` compared under a tolerance; a larger one is compared exactly, and is unscoreable by a quality check. |
| `QUALITY_MAX_FROZEN_BYTES`, `QUALITY_MAX_ROWS`, `QUALITY_TIMEOUT_S`  | 64 MiB, `1000000`, `300`                    | All frozen files together; lines a builtin scores; one scoring's time limit.                                               |
| `PAIRED_TRIALS`, `CONFIRM_WINNERS`                                   | `true`, `true`                              | Alternate each trial with an unchanged copy; re-test every winner once more.                                               |
| `NOISE_CALIBRATION_BLOCKS`, `NOISE_GAP_MULTIPLIER`                   | `3`, `2.0`                                  | A/A blocks at baseline (0-5; 0 turns calibration off) and the multiple of the largest gap that sets the bar.               |

Test-only variables: `TEST_DATABASE_URL`, `REQUIRE_NETWORK_SANDBOX`,
`REQUIRE_FS_SANDBOX` (see Tests above).

---

## Troubleshooting

**Services won't start**

```bash
docker ps
docker compose -f docker-compose.dev.yml down
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml logs -f
```

**Database init failed**

Schema files in `infrastructure/schema/` run once, on first start of an empty
volume. If a migration failed, remove the volume and start again:

```bash
docker compose -f docker-compose.dev.yml down -v
docker compose -f docker-compose.dev.yml up -d postgres
docker compose -f docker-compose.dev.yml logs postgres | grep -i error
```

CI runs this same init on every push (`Compose Init (Postgres)` job).

**Port conflicts** (5432, 6379, 6333): `lsof -i :5432`, then stop the
conflicting service or change the port in `docker-compose.dev.yml`.

**Connect fails: "unshare could not create its namespaces"**

Ubuntu 23.10 and later block unprivileged user namespaces through AppArmor.
Either allow them (a system-wide setting) or run without network isolation;
`best_effort` does not help here, because it still starts `unshare`:

```bash
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
# or: NETWORK_ISOLATION=off
```

**Connect fails on write isolation (Linux)**

Landlock needs Linux 5.13 or later with `landlock` in the kernel's `lsm=` list.
`FS_ISOLATION=best_effort` still applies write isolation when the kernel can; it
only records a failure to apply it (the report shows `fs_isolated`) instead of
refusing. Kernels 5.13 to 5.18 (Landlock ABI 1) always refuse renaming or
linking a file into another directory, so workloads that do that fail under
`required` and `best_effort` alike. Use `FS_ISOLATION=off` or, better, kernel
5.19 or later.

**Connect refuses the repository**

Preflight names the problem and the fix. It refuses git older than 2.38,
submodules, Git LFS, partial clones, dubious ownership (it never sets
`safe.directory`), a `tests_pass` guardrail without a test command, a
`WORKTREE_ROOT` that overlaps the checkout (or, for a linked worktree, the main
checkout, the `.git` directory or another worktree of the repository), a
committed `output_file` (the reset before every run would restore it, so a run
that never writes it would still look right: `git rm --cached` it and ignore
it), a custom merge driver the combine would run, and an `includeIf` in the
repository config (a conditional include can hold in a linked worktree's
checkout and not where the engine checks the config: copy what it includes into
`.git/config`).

**A run was killed (`kill -9`, a crash, a reboot)**

Each phase marks its run directory, `<WORKTREE_ROOT>/<run>`, with a lock held
while it works. The next run's connect removes what an unlocked run left behind
(its worktrees, their registration in your `.git/worktrees`, the scratch and
probe dirs) and says so in a `preflight_note`; a run still working elsewhere
keeps its lock and is left alone. A killed trial that had committed keeps its
trial ref for review, like every committed trial (see below). A worktree at
`<WORKTREE_ROOT>/<run>/<phase>` that no run marks (a run whose own cleanup
failed, or one killed before run markers existed) is not removed, because the
same layout is common for your own worktrees: connect refuses, claims no owner
and names the commands below. Plain `git worktree remove` refuses while a
worktree holds uncommitted work, so look at that work before you add `--force`:

```bash
git worktree list                         # the engine's are under WORKTREE_ROOT
git -C <WORKTREE_ROOT>/<run>/<phase> status   # anything of yours in there?
git worktree remove <WORKTREE_ROOT>/<run>/<phase>
rm -rf <WORKTREE_ROOT>/<run>              # then: git worktree prune
```

**Delete the trial refs**

Every committed trial keeps its ref,
`refs/heads/engine/trial-<run>-<hypothesis>`, so you can inspect it. The run's
report prints a cleanup command naming exactly that run's refs and the commit
each was left at (one `git update-ref --stdin` transaction); a failed run, which
has no report, lists the same command in its `trial_refs_left` event. Prefer it
to a pattern: when one run id is another's prefix followed by `-` (`nightly` and
`nightly-2`), `trial-nightly-*` matches both runs' refs. To review and then
delete the trial refs by pattern (replace `RUN_ID`; keep the quotes so the shell
does not expand it; check the listing first):

```bash
git for-each-ref --format='%(refname)' 'refs/heads/engine/trial-RUN_ID-*'
git for-each-ref --format='delete %(refname) %(objectname)' \
  'refs/heads/engine/trial-RUN_ID-*' | git update-ref --stdin
```

`'refs/heads/engine/trial-*'` matches the trial refs of every run. The delete is
one transaction: if a ref moved after it was listed, nothing is deleted. It
never matches the delivery branch `engine/run-<run>`. Both commands assume the
default `TRIAL_BRANCH_PREFIX` (`engine/`).

### Known limitations (Step 2)

- **macOS** uses `sandbox-exec`, which Apple has deprecated but still ships.
  Network isolation there denies all networking, the workload's own loopback
  included, so a workload that talks to a local server fails.
- **macOS has no PID namespace**: a `setsid` grandchild can outlive its run. It
  stays in the sandbox, and the reset before the next run never follows a link
  it plants (a directory swapped for one stops the run).
- **`NETWORK_ISOLATION=off` on Linux keeps no namespaces**: no PID namespace (a
  `setsid` grandchild survives the run), no private IPC, and an open network is
  a channel between runs. Measurements taken that way are weaker evidence; the
  report shows the modes.
- **Commands that pass `-I` (or `-E`) are unsupported.** Python then ignores the
  engine's `PYTHONPATH`, so a run may import an installed copy of your project
  instead of the trial's worktree. The profiler refuses a run whose code comes
  from your checkout (an editable install), but cannot see a copy installed
  elsewhere.
- **A test command that names the package directory** (`pytest mypkg`) protects
  the whole directory, so no trial can edit it. Point the test command at the
  test folder (`pytest tests`).
- **`python_files` patterns in your pytest config are not protected** unless the
  test command names the test directory. The defaults (`test_*.py`, `test*.py`,
  `*_test.py`, `tests/`, `conftest.py` and the like) always are.
- **Dependency shadowing.** A trial that adds a module named like a
  standard-library module or the test runner is refused, but one named like a
  third-party dependency (`numpy.py`) is not. Human review of the delivered
  branch covers it.
- **Peak RSS is per process**: the largest single process among the waited-for
  descendants of each run, not the sum over its process tree. When CPU time or
  memory is judged, a trial that adds process spawning (`subprocess`,
  `multiprocessing`, `os.fork` and the like) is rejected.
- **Committing, switching branches, `git stash` or `git notes` in your
  repository during a run aborts it**: every ref except remote-tracking and
  prefetch refs, the config and the hooks are fingerprinted around every phase
  that runs repository code.
- **Nondeterministic output** fails the baseline when an output-equivalence
  guardrail is set: add a seed, or an `output_file` the workload writes (an
  untracked file; connect refuses a committed one and protects the path).
- **The test count is verified for unittest and pytest only.** A test command
  run directly as `python -m unittest ...`, `python -m pytest ...` or `pytest`
  must pass at least as many tests as at the base. Any other runner (a script
  such as `./run_tests.sh`, `make test`, `tox`, `nox`) passes on its exit code
  alone, so a trial that makes a failing test skip is not caught by the count;
  the report's "Test count" line says which applied. Run the test runner
  directly where you can.
- **Concurrent calls on one run id are refused per process.** `run`, `stream`
  and `resume` claim the run id for the call, so a second `resume` of a run
  being resumed is told it is not waiting for approval. The checkpointer is in
  memory today; a shared checkpointer (Step 4) will need the claim in the
  database.
- **Workload inputs are not passed yet**: `Workload.inputs` is ignored with a
  warning; put inputs in the command's arguments.
- **NUL characters in stored text.** Postgres text and JSONB cannot hold U+0000,
  which a diff or stderr tail can carry. The repository stores it as U+E000
  followed by `0` (and a literal U+E000 doubled) and restores it on read; a
  direct SQL query sees the escaped form.
- **Merge attributes.** On git 2.40 and later the combine ignores `merge=`
  attributes in committed `.gitattributes` files (connect notes them once);
  `info/attributes` still counts. On older git (Apple's 2.39) committed and
  checked-out `.gitattributes` count too. A custom merge driver selected by an
  attribute source the combine reads is refused at connect; `union` and binary
  merges are notes. The combined tip is re-tested either way.

### Known limitations (Step 3, Wave 1)

- **Workloads under about 0.3 s** may let the noise rule conclude that no gain
  can be proven (see "Keep workloads at about 0.3 s or longer").
- **The quality tripwire over-flags.** With a quality check, a trial whose added
  lines mention a frozen file's name as a whole word is rejected, even in a
  comment or a docstring. Leave the evaluation files unnamed in changed code. It
  is a tripwire, not a wall: a line that was already there is not flagged when
  its neighbours change, and a baked-in table of label values names no file;
  both are left to your review of the review branch.
- **An `output_file` over 16 MiB is unscoreable** by a quality check
  (`OUTPUT_TOLERANCE_MAX_BYTES`): at baseline the run stops, in a trial the
  trial is rejected.
- **Unordered lines:** with `unordered_lines`, line order is ignored, except an
  unterminated last line, which stays last.
- **A count printed as a decimal** is compared to the tolerance's digits only;
  integers printed as integers are always exact.
- **A quality improvement is measured on the frozen evaluation data only** and
  is not tested for significance; the label does not yet state the builtin's row
  count.
- **Exact mode compares stdout and the declared `output_file` only**: a change
  confined to stderr, logging or undeclared files is not seen.
- **`NETWORK_ISOLATION=off` and the quality labels**: with no PID namespace, a
  workload's `setsid` child can outlive its run and could read the frozen labels
  while a scoring copy exists. Prefer the default isolation with a quality
  check.
- **One fix retry per run.** A second retried trial waits for further safeguards
  against the error message carrying data out (about 18 bytes a run is the bound
  today).
- **The Step 3 loop has not run live yet**; its live runs follow its end-to-end
  tests.

---

## Documentation

- [CLAUDE.md](./CLAUDE.md): conventions, the engine loop, the 7-layer map, the
  build order and the stage gate. Package-specific files sit next to each
  package.
- [STATUS.md](./STATUS.md): development log and decisions.
- [SECURITY.md](./SECURITY.md): security policy and scanning.
- [documentation_guide/](./documentation_guide/): the original 2025 vision and
  implementation guide (historical reference).

---

## License

ISC. See [LICENSE](./LICENSE).

---

**Last Updated:** 2026-10-25
