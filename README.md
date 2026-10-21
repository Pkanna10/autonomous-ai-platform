# Autonomous AI Platform

> A self-improving optimization engine that uses research findings and novel
> ideas to **provably** improve your existing code, or to build something new
> and then improve it.

[![Status](https://img.shields.io/badge/status-engine_rebuild-yellow)](<>)
[![Step](https://img.shields.io/badge/build_step-1_of_5-blue)](<>)
[![License](https://img.shields.io/badge/license-ISC-lightgrey)](<>)

---

## What It Does

You give the platform code you run (or an English description of what to build)
and one goal: **make it better**. The engine then:

1. **Understands** the code and works out what "better" means: by default faster
   and leaner with outputs unchanged, or a goal you state in plain English
   ("accuracy may drop at most 0.5%", "memory under 16 GB").
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

| Area                                                        | State                                                     |
| ----------------------------------------------------------- | --------------------------------------------------------- |
| Docker Compose (Postgres + pgvector, Redis, Qdrant), schema | Working                                                   |
| CI (lint, typecheck, tests, coverage), security scanning    | Working                                                   |
| TypeScript Claude client (`packages/agent-core`)            | Working, 33 tests                                         |
| Python settings (`common/config.py`)                        | Working                                                   |
| LangGraph orchestrator                                      | Walking skeleton: every node of the loop wired, stub data |
| Research engine (`arxiv_monitor.py`, `pdf_parser.py`)       | Placeholders                                              |
| Data model, anti-cheating, judges, ranking, lessons         | Working (Step 1), stub runner                             |
| Research matcher, real runner, profiler, CLI                | Not started                                               |

### Build order

| Step | Deliverable                                                                    | Status      |
| ---- | ------------------------------------------------------------------------------ | ----------- |
| 0    | Repair & upgrade: DB init fix, dependency bumps, current models, truthful docs | done        |
| 1    | Engine design: typed state and data models, judge and node interfaces          | in progress |
| 2    | Core loop end to end on CPU Python workloads, with an end-to-end fixture test  | next        |
| 3    | Research: arXiv monitor, PDF parser, playbook, claim extraction, matcher       |             |
| 4    | Interfaces and runner: live CLI log, hardware detection, English goals         |             |
| 5    | Dogfood on fixtures, open-source repos, then a real ML training pipeline       |             |

See [STATUS.md](./STATUS.md) for the development log.

---

## Quick Start

### Prerequisites

- macOS or Linux
- Docker (PostgreSQL, Redis, Qdrant)
- Node.js 20+ and pnpm 10.20
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)

### Installation

```bash
git clone https://github.com/Pkanna10/autonomous-ai-platform.git
cd autonomous-ai-platform

# Node.js
pnpm install

# Python
cd services/python_agents
uv sync --extra dev
cd ../..

# Environment
cp .env.example .env            # add your ANTHROPIC_API_KEY

# Infrastructure
docker compose -f docker-compose.dev.yml up -d
```

### Verify

```bash
docker ps                                                     # postgres, redis, qdrant
psql postgresql://dev:devpass@localhost:5432/ai_platform -c '\dt'   # 14 tables

pnpm typecheck && pnpm lint && pnpm test
cd services/python_agents && uv run pytest
```

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
uv run pytest             # coverage >= 90% enforced

# Security
pnpm security             # pnpm audit, OSV, Trivy, Docker scans
uv run pip-audit && uv run bandit -r src -c pyproject.toml

# Stage gate (run at the end of every build step)
pnpm stage-gate           # outdated + audits + full quality checks
pnpm stage-gate:quick     # quality checks only
```

### Development workflow

Every build step ends with the same stage gate before its PR is marked ready:

1. **Upgrades:** review outdated dependencies and upgrade within the step.
   Renovate opens weekly PRs for anything missed.
2. **Audits:** `pnpm audit`, `pip-audit` and `bandit` must be clean;
   `security.yml` (OSV, Trivy, secret scanning) runs on every push and every
   Monday.
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
- Python: Ruff lint and format, mypy, pytest with coverage
- Security: `pnpm audit`, OSV scanner, Trivy (filesystem and images), Docker
  Scout, secret scanning; SBOM and provenance attestations on image builds
- Dependencies: Renovate with grouped, scheduled upgrade PRs

---

## Environment Variables

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...                         # required
DATABASE_URL=postgresql://dev:devpass@localhost:5432/ai_platform
REDIS_URL=redis://localhost:6379
QDRANT_URL=http://localhost:6333
NODE_ENV=development
ENGINE_MODEL=claude-opus-5-5                               # optional override
TRIAGE_MODEL=claude-haiku-5-5                              # optional override
```

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

**Last Updated:** 2026-10-21
