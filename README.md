# Autonomous AI Platform

> A self-improving optimization engine that uses research findings and novel
> ideas to **provably** improve your existing code, or to build something new
> and then improve it.

[![Status](https://img.shields.io/badge/status-engine_rebuild-yellow)](<>)
[![Step](https://img.shields.io/badge/build_step-2_of_5-blue)](<>)
[![License](https://img.shields.io/badge/license-ISC-lightgrey)](<>)

---

## What It Does

You give the platform code you run (or an English description of what to build)
and one goal: **make it better**. The engine then:

1. **Understands** the code and works out what "better" means: by default faster
   and leaner with outputs unchanged (wall time must drop, and peak memory may
   grow by at most 10%), or a goal you state in plain English ("accuracy may
   drop at most 0.5%", "memory under 16 GB").
2. **Measures** a baseline and **profiles** where time and memory actually go.
3. **Researches** two sources: a playbook of proven engineering techniques, and
   new papers (arXiv, Semantic Scholar) whose claims and preconditions match the
   hotspots it found.
4. **Runs experiments**: each hypothesis is applied in its own git worktree,
   measured over repeated runs, and judged against frozen evaluators (speed,
   memory, output equivalence, your tests, your guardrail metric).
5. **Keeps only proven wins**, combines them, re-tests, and delivers a branch or
   PR with a report: what changed, by how much, which paper or technique it came
   from, and what was rejected and why.
6. **Learns** from every verdict and **keeps watching** for new papers and code
   changes.

Autonomy follows verifiability: efficiency wins ship automatically,
behaviour-changing optimizations are flagged, and novel ideas are proposals for
you to approve. The engine never pushes to your default branch.

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

| Layer                     | Where                                         | Decision                                          |
| ------------------------- | --------------------------------------------- | ------------------------------------------------- |
| L1 Interfaces             | CLI (Step 4), web console, GitHub App, plugin | Integrate with the tools developers already use   |
| L2 Orchestrator           | `services/python_agents/.../orchestrator/`    | LangGraph 1.x: checkpointing, interrupts, retries |
| L3 Capability acquisition | `capabilities/` (planned)                     | Vet and approval-gate packages a trial needs      |
| L4 Research               | `services/python_agents/.../research/`        | **Build**: playbook, papers, claims, matcher      |
| L5 Execution              | local runner, `packages/execution-engine`     | Trials on your hardware (CPU, CUDA, Apple MPS)    |
| L6 Optimization           | `optimization/` (planned)                     | **Build**: hypotheses, trials, judges, verdicts   |
| L7 Self-improvement       | `learning/` (planned)                         | **Build**: lessons store, evaluator-gated         |
| Persistence               | `infrastructure/schema/`                      | PostgreSQL 16 + pgvector; Redis; Qdrant           |

```
CONNECT → UNDERSTAND → DEFINE "BETTER" → BASELINE → PROFILE → RESEARCH
  → HYPOTHESES → TRIALS → JUDGES → VERDICTS → COMBINE → DELIVER → LEARN → WATCH
```

---

## Current State (honest)

Step 2 built the core loop for CPU-bound Python workloads. Every phase that runs
code does so for real, in a sandbox, on your machine. The stage gate for Step 2
has not run yet.

| Area                                                        | State                                                       |
| ----------------------------------------------------------- | ----------------------------------------------------------- |
| Docker Compose (Postgres + pgvector, Redis, Qdrant), schema | Working; migrations 001-004 applied in CI                   |
| CI (lint, typecheck, tests, coverage), security scanning    | Working; Linux and macOS engine jobs                        |
| TypeScript Claude client (`packages/agent-core`)            | Working, 33 tests                                           |
| Python settings (`common/config.py`)                        | Working, validated at startup                               |
| Preflight at connect (git, LFS, submodules, sandbox probe)  | Working (Step 2)                                            |
| Understand (one Claude request, under the cost cap)         | Working (Step 2)                                            |
| Baseline, profile (cProfile), trials in sandboxed worktrees | Working (Step 2), CPU Python workloads                      |
| Claude trial editor and git-side anti-cheating              | Working (Step 2)                                            |
| Judges, verdicts, approval, combine with an ABAB re-test    | Working (Step 2)                                            |
| Delivery to a local `engine/run-<id>` branch                | Working (Step 2); never pushed, no PR yet                   |
| Postgres repository (`persistence/postgres.py`)             | Working (Step 2)                                            |
| Research (playbook, papers, matcher)                        | Not started (Step 3); hypotheses are supplied by the caller |
| CLI, live log, hardware detection, English goals            | Not started (Step 4)                                        |

### Build order

| Step | Deliverable                                                                    | Status                 |
| ---- | ------------------------------------------------------------------------------ | ---------------------- |
| 0    | Repair & upgrade: DB init fix, dependency bumps, current models, truthful docs | done                   |
| 1    | Engine design: typed state and data models, judge and node interfaces          | done                   |
| 2    | Core loop end to end on CPU Python workloads, with an end-to-end fixture test  | built; stage gate next |
| 3    | Research: arXiv monitor, PDF parser, playbook, claim extraction, matcher       |                        |
| 4    | Interfaces and runner: live CLI log, hardware detection, English goals         |                        |
| 5    | Dogfood on fixtures, open-source repos, then a real ML training pipeline       |                        |

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
`build_context(project, candidates=...)` in `orchestrator/factory.py` wires the
real preflight, understander, profiler, runners, combiner and publisher, and
`Orchestrator(context=...).run(project, workloads, objectives, guardrails, max_cost_usd=...)`
runs the loop. Until the research layer exists (Step 3) the caller supplies the
candidate hypotheses. `services/python_agents/tests/e2e/test_step2.py` shows a
complete run on the `dedupe_repo` fixture. The trial editor needs
`ANTHROPIC_API_KEY`; without it `build_context` raises `LLMConfigError` unless
an editor is injected.

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
uv run pytest tests/e2e --no-cov            # the Step 2 E2E scenarios only
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
- **Profiler tests** run the profiler shim under `python3.8` to `python3.12` as
  well as the engine's own Python; an interpreter missing from `PATH` skips.
  `uv python install 3.8 3.9 3.10 3.11 3.12` installs them, as CI does.
- **E2E** (`tests/e2e`, marker `slow`): three scenarios on the `dedupe_repo`
  fixture with scripted Claude replies and real git, sandbox and measurement.
  They use Postgres when `TEST_DATABASE_URL` is set, else the in-memory
  repository.
- **Live smoke test** (marker `live`): one real Claude edit under a $0.50 cap.
  It runs only when selected with `-m live` and `ANTHROPIC_API_KEY` is set. In
  CI it is the `live-smoke` job, started by hand (`workflow_dispatch`: Actions >
  CI > Run workflow), never on push. The job uses the GitHub environment `live`,
  which must have required reviewers and hold `ANTHROPIC_API_KEY` as an
  environment secret, not a repository secret.
- **Live experiments** (`tests/live/experiments/` and the discovery suites in
  `tests/live/`): the Window 0 measurements for Step 3 (API compatibility
  probes, batch triage, cited paper extraction, hosted web research, a sandbox
  pre-screen, the blind hypothesis sweep, the playbook A/B and editor
  escalation). Each is a `suite` choice of `live-smoke`; `STATUS.md` lists each
  suite's cap and expected cost.

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
  `claude-opus-5-5`) and `TRIAGE_MODEL` (default `claude-haiku-5-5`).

### CI and security

GitHub Actions runs on every push and pull request:

- TypeScript: ESLint, `tsc`, Vitest with coverage; Prettier format check
- Python: Ruff lint and format, mypy on `src` and `tests`, pytest with coverage
  against a pgvector Postgres 16 service, after a probe that fails the job when
  the runner cannot sandbox (`unshare`, Landlock)
- macOS: the execution tests with `sandbox-exec` and Apple's `/usr/bin/git` (not
  blocking yet; it must be before the Step 2 PR is marked ready)
- Schema: migrations 001-004 applied in order, then 003 and 004 re-applied to
  prove they are idempotent
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

**Last Updated:** 2026-10-22
