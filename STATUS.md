# Project Status - Autonomous AI Platform

**Last Updated:** 2026-10-21

---

## Current Step

**Build step:** 0 of 5 (Repair & upgrade) **Branch:**
`claude/adoring-clarke-xpo1py` **Vision:** a self-improving optimization engine
that uses research findings and novel ideas to provably improve existing code,
or build something new and then improve it (see `CLAUDE.md`).

---

## Development Log

One row per build step. "Gate" is the result of `pnpm stage-gate` at the end of
the step.

| Step | Deliverable                                                     | Planned    | Started    | Completed  | PR  | Gate   |
| ---- | --------------------------------------------------------------- | ---------- | ---------- | ---------- | --- | ------ |
| 0    | Repair & upgrade (DB init, deps, models, docs, stage gate)      | 2026-10-21 | 2026-10-21 | 2026-10-21 |     | passed |
| 1    | Engine design (typed state, data model, judges, migration 003)  | next       |            |            |     |        |
| 2    | Core loop end to end on CPU Python workloads + E2E fixture test |            |            |            |     |        |
| 3    | Research: arXiv, PDF, playbook, claim extraction, matcher       |            |            |            |     |        |
| 4    | Interfaces + runner: live CLI, hardware detection, `--goal`     |            |            |            |     |        |
| 5    | Dogfood: fixtures, OSS repos, real ML training pipeline         |            |            |            |     |        |

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

---

## What Exists Today

| Component                                                                            | State                                   |
| ------------------------------------------------------------------------------------ | --------------------------------------- |
| Docker Compose: Postgres 16 + pgvector, Redis, Qdrant                                | Working                                 |
| Schema `001_initial.sql` + `002_fix_critical_issues.sql`                             | Working after Step 0 fix                |
| CI: lint, typecheck, tests, coverage, Python CI                                      | Working                                 |
| Security: OSV, Trivy, Docker Scout, pip-audit, bandit, safety, secret scan, Renovate | Working                                 |
| `packages/agent-core` Claude client + shutdown                                       | Working (33 Vitest tests)               |
| `services/python_agents` settings                                                    | Working                                 |
| LangGraph orchestrator                                                               | Graph compiles; three placeholder nodes |
| `research/arxiv_monitor.py`, `pdf_parser.py`                                         | Placeholders                            |
| `packages/research-engine`, `execution-engine`                                       | TypeScript placeholders                 |
| Optimization, judges, learning, CLI, web console                                     | Not started                             |

---

## Decisions

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

## Next: Step 1 (Engine design)

Recommended session setting: **Fable 5.1, Extra**.

- [ ] Typed engine state (`AgentState` evolves into the engine state) and
      pydantic data models: Project, Workload, Objective, Guardrail,
      Measurement, Hotspot, Technique, Paper, Claim, Precondition, Hypothesis,
      Trial, Verdict, Delivery, Lesson.
- [ ] Judge and node interfaces (Protocols) with test skeletons.
- [ ] Anti-cheating rules: frozen evaluators, diff touching tests/benchmarks is
      rejected, N >= 5 runs, noise threshold, output fingerprinting.
- [ ] Migration `003_engine.sql` extending the existing tables.
- [ ] "Engine design" section in `services/python_agents/CLAUDE.md`.
- [ ] Stage gate, development log row, PR.

---

## Metrics Snapshot (2026-10-21)

| Metric                         | Value                                                       |
| ------------------------------ | ----------------------------------------------------------- |
| Python tests                   | 47 passed, 3 expected failures                              |
| Python coverage                | 100% of 64 statements (placeholders excluded from coverage) |
| TypeScript tests               | 33 passed                                                   |
| Product code (non-placeholder) | ~600 lines                                                  |
| Engine features shipped        | 0 (Step 0 is groundwork)                                    |

---

## Technical Debt

- `pyproject.toml` `[project.scripts]` and `[project.entry-points]` reference
  modules that do not exist yet (`cli`, `codegen`, `tools`, `integrations`).
  Implement or remove in Step 4.
- `[tool.uv.workspace] members` lists directories that do not exist; uv
  tolerates it. Remove or create the members in Step 1.
- `packages/research-engine` (TypeScript) duplicates the Python research
  module's purpose. Decide in Step 1 whether it stays.
- Both pgvector and Qdrant are configured. Pick one when embeddings land (Step
  3).
- `services/python_agents/Dockerfile` installs with pip while CI uses uv.
- `test_settings_requires_anthropic_api_key` is an empty test.
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
