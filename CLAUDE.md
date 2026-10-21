# Autonomous AI Platform - Claude Code Configuration

**Version:** 4.0.0 **Last Updated:** 2026-10-21 **Status:** Engine rebuild, Step
0 (repair & upgrade) in progress

---

## Core Principles

1. **TDD, red-green-refactor.** Write the failing test before the
   implementation. Every change ships with its tests.
2. **Explicit types.** No `any` in TypeScript. Python runs mypy in strict mode.
3. **90%+ test coverage before commit.** CI enforces it (`--cov-fail-under=90`,
   Vitest thresholds).
4. **Monorepo conventions.** Code goes in `packages/`, `services/`, `apps/`,
   `infrastructure/`. Never in the repo root.

These four rules are stable. They do not need repeating in responses; follow
them.

---

## What We Are Building

> A self-improving optimization engine that uses research findings and novel
> ideas to **provably** improve your existing code, or to build something new
> and then improve it.

The user gives the platform code they run (or an English description of what to
build) and one goal: "make it better". The engine considers every kind of
improvement it can **prove** and keeps only what wins.

### The engine loop

```
CONNECT -> UNDERSTAND -> DEFINE "BETTER" -> BASELINE -> PROFILE -> RESEARCH
  -> HYPOTHESES -> TRIALS (one git worktree each) -> JUDGES -> VERDICTS
  -> COMBINE + re-test -> DELIVER (branch/PR + report) -> LEARN -> WATCH
```

- **Define "better".** Default objective: minimize runtime and peak memory;
  outputs and quality must not change. The user can override it in plain English
  ("accuracy may drop <= 0.5%"), which becomes an `Objective` plus `Guardrail`s.
- **Research** draws on two sources: a curated **playbook** of known techniques
  with preconditions, and **papers** (arXiv, Semantic Scholar) with claims and
  preconditions extracted by Claude.
- **Judges** are frozen evaluators: speed, memory, output equivalence, a
  guardrail metric, the existing test suite. A trial diff that touches
  benchmark, test or judge files is rejected automatically (anti reward
  hacking). Results need N >= 5 runs and a gain larger than the measured noise.
- **Autonomy is proportional to verifiability.** Efficiency wins are delivered
  automatically; changes that alter model or algorithm behaviour are flagged;
  novel or capability changes are proposals that need human approval. The engine
  never pushes to the default branch.
- **Learn.** Every verdict becomes a lesson ("frozen encoder + repeated epochs
  -> cache embeddings") that feeds the next hypothesis ranking.

### The 7 layers and where they live

| Layer                     | Repo home                                                     | Decision                                                     |
| ------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------ |
| L1 Interfaces             | `services/python_agents` CLI (planned), `apps/` (later)       | Integrate: CLI first, then web console, GitHub App, plugin   |
| L2 Orchestrator           | `services/python_agents/.../orchestrator/`                    | Build on LangGraph 1.x (checkpointing, interrupts, retries)  |
| L3 Capability acquisition | `capabilities/` (planned) + `packages` table                  | Vet and approval-gate any package a trial needs              |
| L4 Research               | `services/python_agents/.../research/`                        | **Build**: playbook, paper search, claim extraction, matcher |
| L5 Execution              | `execution/` (planned), `packages/execution-engine` (TS)      | Local runner on the user's hardware; cloud sandbox later     |
| L6 Optimization           | `optimization/` (planned)                                     | **Build**: hypotheses, trials, judges, verdicts, combine     |
| L7 Self-improvement       | `learning/` (planned) + `user_feedback` table                 | **Build**: lessons store; evaluator-gated, no fine-tuning    |
| Persistence               | `infrastructure/schema/` (Postgres + pgvector), Redis, Qdrant | Existing tables reused and extended via new migrations       |

---

## Project Status and Build Order

**Reality check (2026-10-21):** the repository contains working infrastructure
(Docker, CI, security scanning, schema), a working TypeScript Claude client, a
settings module, and a LangGraph graph whose three nodes are placeholders. The
research modules are placeholders. Treat anything else described in older docs
as a plan, not a feature.

| Step | Deliverable                                                                                       | Model / setting to select               |
| ---- | ------------------------------------------------------------------------------------------------- | --------------------------------------- |
| 0    | Repair & upgrade: DB init fix, dependency bumps, current model IDs, truthful docs (this PR)       | Opus 5.5, High                          |
| 1    | Engine design: typed state and data models, judge/node interfaces, anti-cheating rules, migration | Fable 5.1, Extra                        |
| 2    | Core loop end to end on CPU Python workloads, with an E2E fixture test                            | Opus 5.5, Ultracode                     |
| 3    | Research: arXiv monitor, PDF parser, playbook, claim/precondition extraction, matcher             | Opus 5.5, Ultracode (Fable for matcher) |
| 4    | Interfaces + runner: live CLI log, hardware detection (CPU/CUDA/MPS), `--goal` English parsing    | Opus 5.5, Ultracode                     |
| 5    | Dogfood on fixtures, OSS repos, then the user's VLM bridge on an M4 Pro                           | Opus 5.5, High                          |

Runtime models called by the engine itself (`services/python_agents` settings):
`ENGINE_MODEL=claude-opus-5-5` for understanding, extraction and trial edits;
`TRIAGE_MODEL=claude-haiku-5-5` for high-volume paper triage. Every run carries
a `--max-cost` cap and logs its token cost.

**Decision tree: "Should I implement this feature?"**

```
Is it part of the current step?
|- YES -> TDD workflow
`- NO  -> explain where it sits in the build order, offer to document it
```

---

## Think Before Acting

Before any significant change, work through:

1. **Understand:** what is being asked, and what is ambiguous?
2. **Validate:** does it fit the current step? Does it break a core principle?
   Any security implications (checklist below)?
3. **Plan:** which tools, what order, what can run in parallel?
4. **Risks:** what could go wrong, which edge cases, do I need to ask first?

For multi-step work, decompose into independent sub-tasks, run the independent
ones in parallel, then integrate.

---

## Tool Use

| Task                  | Tool  | Why                  |
| --------------------- | ----- | -------------------- |
| Read a specific file  | Read  | Direct access        |
| Find files by pattern | Glob  | Filesystem search    |
| Search file contents  | Grep  | Content-aware        |
| Edit an existing file | Edit  | Preserves formatting |
| Create a new file     | Write | Explicit creation    |
| Git, package managers | Bash  | Terminal operations  |

- Prefer the dedicated file tools over `cat`/`grep`/`echo >` in Bash.
- Independent operations go in one parallel batch; dependent ones run in order.
- For more than five similar edits, batch them in one pass.
- On a non-zero exit code: read the error, propose a fix, apply it, retry (max
  three attempts), then report.

---

## Security Requirements

Check before generating code. The project runs pip-audit, bandit, safety, OSV,
Trivy and Docker Scout in CI; keep them green.

**OWASP Top 10 for LLM applications:**

1. Prompt injection: validate and constrain all user and paper-derived input.
2. Sensitive data: no API keys, passwords or secrets in code. `.env` only.
3. Supply chain: audit dependencies (`pnpm audit`, `pip-audit`); any package a
   trial wants to install is vetted and approval-gated (slopsquatting defence).
4. Data and model poisoning: validate inputs, sanitize data from papers and
   registries.
5. Insecure output handling: sanitize outputs; no XSS or SQL injection.
6. SSRF: validate every URL; network isolation for trial runs.
7. Insecure plugin design: audit MCP servers; OAuth 2.1 with PKCE.
8. Excessive agency: sandboxed trials, user confirmation for sensitive
   operations, never push to the default branch.
9. Overreliance: human review for security-critical code and for any
   behaviour-changing optimization.
10. Model theft: API key rotation, rate limiting.

**Final checklist for every code change:**

```
[ ] SQL: parameterized queries only
[ ] XSS: sanitize inputs, encode outputs
[ ] Command injection: never exec() with user input
[ ] Path traversal: validate every file path
[ ] Secrets: none hard-coded
```

After generating code, review it against this list and fix what you find before
finishing.

---

## Critical Rules

### 1. Test-driven development

```
RED      write a failing test
GREEN    write the minimal code to pass
REFACTOR improve without changing behaviour
```

Pre-commit: `pnpm run pre-commit` (typecheck, lint, test, coverage) and, for
Python, `uv run ruff check . && uv run mypy src && uv run pytest`.

### 2. Explicit types

```typescript
// GOOD
interface TaskRequest {
  userInput: string;
  intent: Intent;
  context: Record<string, unknown>;
}

// BAD
function processTask(data: any) {}
```

### 3. Never commit secrets

`.env` is git-ignored. Before committing, grep for `api_key|password|secret`.

### 4. Documentation: three files plus package CLAUDE.md files

- `CLAUDE.md` (this file, plus one per package or service)
- `STATUS.md` (progress tracking)
- `README.md` (user-facing)
- `SECURITY.md` (security policy, already present)

Do not create ARCHITECTURE.md, DESIGN.md, SPECS.md, API.md, CHANGELOG.md or
similar. The original vision documents live in `documentation_guide/` and are
historical reference.

### 5. Monorepo structure

```
packages/agent-core        TypeScript Claude client and shared agent utilities
packages/research-engine   TypeScript placeholder (research lives in Python)
packages/execution-engine  TypeScript placeholder (ts-morph work, later)
services/python_agents     LangGraph orchestrator, research, engine (Python)
infrastructure/            Docker, database schema
documentation_guide/       Original 2025 vision documents
```

---

## Development Workflow: Stage Gate After Every Step

Every step in the build order ends with the same gate. A step is not done until
all of it passes, and the result is recorded in `STATUS.md`.

1. **Upgrades.** Review `pnpm outdated -r` and `uv tree --outdated --depth 1`
   (the gate reports both). Upgrade inside the step unless a major bump needs
   its own PR. Renovate opens weekly PRs for anything missed.
2. **Audits.** `pnpm audit --audit-level=moderate`, `pip-audit` and `bandit`
   must be clean. `security.yml` (OSV, Trivy, secret scanning) runs on every
   push and every Monday. Fix or justify each finding in the PR.
3. **Security review of the new code.** Walk the OWASP list above for what the
   step added and add the protections it needs (worktree isolation for trials,
   URL validation for paper fetching, approval gates for package installs).
4. **Docs.** Update `README.md` (what the feature does, how to use it),
   `STATUS.md` (a Development log row: planned, started, completed, PR, summary,
   gate result) and the relevant `CLAUDE.md` if conventions changed.
5. **Quality.** `pnpm stage-gate` runs typecheck, lint, format, tests and
   coverage for both ecosystems and fails on any red check
   (`pnpm stage-gate:quick` skips the slower audit and outdated checks).
6. **PR.** Open as draft, let CI run, fix until green, then mark ready.

---

## Technology Stack

- **Python 3.11+** with `uv`, Hatchling, Ruff, mypy strict, pytest
- **LangGraph 1.x** for the orchestrator loop; **anthropic 1.x** SDK
- **Node.js 20+**, TypeScript 5.9, pnpm 10, Vitest, ESLint, Prettier
- **Claude** via the Messages API: `claude-opus-5-5` (engine),
  `claude-haiku-5-5` (triage)
- **PostgreSQL 16 + pgvector**, Redis 7, Qdrant (Docker Compose)
- **CI:** GitHub Actions with Trivy, Docker Scout, OSV, pip-audit, SBOM and
  provenance attestations

---

## Environment Setup and Commands

```bash
docker compose -f docker-compose.dev.yml up -d   # Postgres, Redis, Qdrant
cp .env.example .env                              # add ANTHROPIC_API_KEY

# Python
cd services/python_agents
uv sync --extra dev
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest

# TypeScript
pnpm install
pnpm typecheck && pnpm lint && pnpm test
pnpm format:check
```

**Commit message format:**

```
<type>(<scope>): <subject>

<body>
```

Types: feat, fix, docs, style, refactor, test, chore, perf, ci, build, revert.
Commitlint enforces this through Husky.

---

## Context Management

- Save architectural decisions to STATUS.md as they are made.
- Use `/compact` around 70% context usage, keeping decisions, error patterns and
  the current feature's details.
- Long tasks: write intermediate state to STATUS.md so work survives a reset.

---

## Package-Specific Guidelines

More specific files take precedence over this one when working inside their
directory:

- `packages/agent-core/CLAUDE.md` (TypeScript, Vitest, Claude client)
- `packages/research-engine/CLAUDE.md` (placeholder package; research patterns)
- `packages/execution-engine/CLAUDE.md` (placeholder package)
- `services/python_agents/CLAUDE.md` (Python, LangGraph, pytest, engine)

---

## Changelog

- **4.0.0 (2026-10-21):** Vision clarified as the improvement engine; 7-layer
  map onto the repo; build order with model guidance; removed unverifiable
  statistics, the repeat-every-response rule and model-identity claims; fixed
  references to files that did not exist.
- **3.0.0 (2025-11-19):** Advanced prompting techniques, hierarchical CLAUDE.md
  files.
- **2.0.0 (2025-11-19):** Hierarchical structure, OWASP checklist, tool
  guidance.
- **1.5.0 (2025-11-12):** Python 3.11 upgrade.
- **1.0.0 (2025-11-01):** Initial release.
