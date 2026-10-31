# Autonomous AI Platform - Claude Code Configuration

**Version:** 4.5.0 **Last Updated:** 2026-10-26 **Status:** Engine rebuild, Step
3 Wave 1 built on `claude/step3-research` (draft PR #22); its E2E and live runs
next

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
  -> HYPOTHESES -> ACQUIRE (packages, tools) -> TRIALS (one git worktree each)
  -> JUDGES -> VERDICTS -> COMBINE + re-test -> DELIVER (branch/PR + report)
  -> LEARN -> WATCH

HEAL enters the same loop: a failing test, a crash or an error report becomes
a hypothesis whose judge is "the failing case now passes, nothing regresses".
```

- **Define "better".** Default objective: minimize runtime and peak memory;
  outputs must not change (the output check is on by default). With a quality
  number the user confirms once (a frozen scorer over frozen evaluation data), a
  change that alters output may pass when the number stays within the drop the
  user allows ("accuracy may drop at most 0.5 points"); it then goes to review,
  labelled. Plain-English goals become an `Objective` plus `Guardrail`s (Step
  4).
- **Research** draws on two sources: a curated **playbook** of known techniques
  with preconditions, and **papers** (arXiv, Semantic Scholar) with claims and
  preconditions extracted by Claude.
- **Judges** are frozen evaluators: speed, memory, output equivalence, a
  guardrail metric, the existing test suite. A trial diff that touches
  benchmark, test or judge files is rejected automatically (anti reward
  hacking). Results need N >= 5 runs and a gain larger than the measured noise:
  each trial is measured alternately against an unchanged copy of the base,
  against a per-project floor (never below 2 %), and every winner is confirmed
  on a second look before it stands.
- **Autonomy is proportional to verifiability.** Efficiency wins with identical
  outputs are delivered automatically (`engine/run-<id>`); changes that alter
  behaviour or output go to a separate review branch (`engine/review-<id>`) with
  a label, never merged into the run branch and with no pause; novel changes are
  proposals that need human approval. Autonomy comes from automatic checks, not
  from a human: the user is asked when a check fails or cannot run. The engine
  never pushes to the default branch.
- **Acquire capabilities automatically** (vision update 2026-10-24). When a
  hypothesis needs a dependency, an engine-owned capability step finds, vets,
  pins and installs it into the trial's own environment, never the user's:
  fetching is a separate network-on step (exact versions with hashes, wheels
  only), trials stay network-off. The policy is automatic (the name exists and
  is no near-miss of a popular one, minimum age and downloads, no known
  vulnerability, licence allowlist); the user is asked only when a check fails.
  The editor still cannot touch manifests or lockfiles; the delivered branch
  shows the lockfile diff and why each package was added, and a package with no
  proven gain against a baseline without it is dropped. MCP servers and APIs are
  discovered and ranked the same way: read-only, credential-free servers are
  connected automatically and sandboxed like trials; credentials or write access
  need the user's approval, and every tool description is untrusted input.
- **Self-healing.** The user's code: a failing test, a crash or an error report
  becomes a hypothesis judged by "the failing case passes, and the full suite
  and the other judges show no regression"; a fix changes behaviour, so it is
  delivered on the review branch. The engine itself: a trial that fails for a
  fixable reason (syntax, import, name, type or attribute error) gets one retry
  per run with that error fed back through a closure check (only interpreter
  text and names the API has already seen), inside the cost cap.
- **Learn.** Every verdict becomes a lesson ("frozen encoder + repeated epochs
  -> cache embeddings") that feeds the next hypothesis ranking.

### The 7 layers and where they live

| Layer                     | Repo home                                                                                   | Decision                                                                                                                                                                                                           |
| ------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| L1 Interfaces             | `services/python_agents` CLI (planned), `apps/` (later)                                     | Integrate: CLI first, then web console, GitHub App, plugin                                                                                                                                                         |
| L2 Orchestrator           | `services/python_agents/.../orchestrator/`                                                  | Build on LangGraph 1.x (checkpointing, interrupts, retries)                                                                                                                                                        |
| L3 Capability acquisition | `capabilities/` (planned) + `packages` table                                                | **Build**: automatic package acquisition under an automatic policy (user asked only on a failed check); MCP server and API discovery, auto-connect only read-only and credential-free                              |
| L4 Research               | `services/python_agents/.../research/`                                                      | **Build**: a generator wired into the hypotheses node (Step 3); playbook and matcher built, off by default; paper search and claim extraction only if the retrieval re-test calls for them                         |
| L5 Execution              | `services/python_agents/.../execution/` (built, Step 2)                                     | Local runner on the user's hardware; cloud sandbox later; per-trial environments with offline installs; bounded self-retry on fixable trial errors                                                                 |
| L6 Optimization           | `services/python_agents/.../optimization/` (Steps 1-3)                                      | **Build**: hypotheses, trials, judges, verdicts, combine                                                                                                                                                           |
| L7 Self-improvement       | `services/python_agents/.../learning/` + `lessons` table (`user_feedback` table unused yet) | **Build**: lessons store; evaluator-gated, no fine-tuning; self-healing of the user's code (failing case -> hypothesis -> review branch); production error intake and gradual rollout later (Steps 4-5 interfaces) |
| Persistence               | `infrastructure/schema/` (Postgres + pgvector), Redis, Qdrant                               | Existing tables reused and extended via new migrations                                                                                                                                                             |

---

## Project Status and Build Order

**Reality check (2026-10-25, Step 3 Wave 1 built, E2E and live runs next):** the
repository contains working infrastructure (Docker, CI with a Postgres service,
a sandbox probe, a blocking macOS job, pip-audit, a manual live smoke test,
security scanning, schema 001-006), a working TypeScript Claude client, and the
engine's loop in `services/python_agents`, running for real on CPU-bound Python
workloads: preflight at connect, one Claude understand request, baseline,
cProfile profile and Claude-edited trials in sandboxed git worktrees (network
and write isolation, checked on every run), git-side anti-cheating, the frozen
judges, a combine re-tested ABAB with the test suite on its tip, delivery to a
local `engine/run-<id>` branch, and a Postgres repository, all under a hard
per-run cost cap. Step 3 Wave 1 adds (committed on its branch, not on `master`
yet; offline-tested, no live run yet): hypotheses generated by Claude when the
caller hands none over (novel ones parked); one fenced, closure-checked fix
retry per run; the `engine/review-<id>` branch for changes that alter behaviour
or output; the output check on by default, or a quality check the caller
confirms (`build_context(quality=...)`) with frozen, masked evaluation files;
and the noise rule (paired ABBA trials against a base twin, a calibrated
per-project floor of at least 2 %, a second look before any keep). Paper intake,
the CLI, the live log and hardware detection do not exist; the playbook matcher
is built and off. Treat anything else described in older docs as a plan, not a
feature.

| Step | Deliverable                                                                                                                                                                                                     | Model / setting to select               |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| 0    | Repair & upgrade: DB init fix, dependency bumps, current model IDs, truthful docs (PR #11)                                                                                                                      | Opus 5.5, High                          |
| 1    | Engine design: typed state, data models, judges, anti-cheating, migration 003 (PR #11)                                                                                                                          | Fable 5.1, Extra                        |
| 2    | Core loop end to end on CPU Python workloads, with an E2E fixture test (done 2026-10-24, PR #12)                                                                                                                | Opus 5.5, Ultracode                     |
| 3    | Generator wired, engine self-retry, review delivery, quality check, noise rule, hard corpus v2 and the retrieval re-test, lessons and evolution; paper intake conditional (Wave 1 built, PR #22)                | Opus 5.5, Ultracode (Fable 5.1 reviews) |
| 3c   | Self-healing of the user's code: failing test or crash -> hypothesis, engine-written reproducer frozen with the judges, "now passes, nothing regresses" judge, review-branch delivery (before 3b)               | Opus 5.5, High                          |
| 3b   | Capability acquisition: automatic package policy, network-on fetch into a hash-pinned wheelhouse, offline per-trial installs, engine-owned lockfile commit, drop a package with no proven gain                  | Opus 5.5, Ultracode                     |
| 4    | Interfaces + runner: live CLI log, hardware detection (CPU/CUDA/MPS), `--goal` English parsing; MCP server and API discovery (auto-connect read-only, credential-free only); error-report intake for the healer | Opus 5.5, Ultracode                     |
| 5    | Dogfood on fixtures, OSS repos, then the user's VLM bridge on an M4 Pro                                                                                                                                         | Opus 5.5, High                          |
| 6    | Production loop: error monitoring into the healer, gradual rollout through the user's deployment (the engine never deploys)                                                                                     | Opus 5.5, High                          |

3c comes before 3b (the owner, O5): it has no network boundary, while 3b needs a
security review of a network-on fetch. Wave 3 of Step 3 is held until Wave 1's
live runs report.

Runtime models called by the engine itself (`services/python_agents` settings):
`ENGINE_MODEL=claude-opus-5-5` for understanding and trial edits (`EDITOR_MODEL`
unset keeps the editor on it); `GENERATOR_MODEL` and `MATCHER_MODEL`
`claude-sonnet-5-5` at medium effort for discovery (the matcher runs only under
`RESEARCH_RETRIEVAL=matched`, off); `TRIAGE_MODEL=claude-haiku-5-5` for paper
triage, if paper intake is built. Every run carries a hard cost cap
(`max_cost_usd`; `--max-cost` with the Step 4 CLI) and logs its token cost.

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

Check before generating code. The project runs pip-audit, bandit, OSV and Trivy
in CI (safety on demand through `uvx`); keep them green.

**OWASP Top 10 for LLM applications:**

1. Prompt injection: validate and constrain all user and paper-derived input.
2. Sensitive data: no API keys, passwords or secrets in code. `.env` only.
3. Supply chain: audit dependencies (`pnpm audit`, `pip-audit`); any package a
   trial needs passes the automatic capability policy (registry existence and
   near-miss names against slopsquatting, age, downloads, OSV, licence, wheels
   only, hash-pinned) and installs only into the trial's environment; a failed
   check asks the user.
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
Python, `uv run ruff check . && uv run mypy src tests && uv run pytest`.

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

## Development Workflow

### Team and reporting line

```
User (product owner): vision, priorities, approvals, merges
└─ Lead (main session): design, briefings and reports, integration,
   review routing, commits, PRs, CI
   ├─ Builders: one unit each (<= ~400 source lines, disjoint files), tests
   │  first, report with evidence
   ├─ Reviewer: fresh context, read-only, a different model from the
   │  author; reports correctness, spec, security and weakened-test
   │  findings only
   ├─ Verifier: tries to break integrated increments (E2E, edge cases,
   │  the stage gate)
   └─ Researcher: read-only investigation when a decision needs evidence
```

Rules: spawn a role only when it adds separable value; the author never reviews
their own work; parallel Builders only on disjoint files; reports carry commands
and outputs, not claims; the Lead is the only writer to the branch. Every brief
carries the seams checklist (fixtures above the tests, real-vs-fake swap points,
root vs non-root, what only CI, macOS or a live run proves; `STATUS.md` Lessons,
Step 2), and review effort follows risk: one correctness Reviewer per unit, a
security Reviewer only at trust boundaries, scoped to the diff and its callers.
Every design decision gets a first-principles "why" in `STATUS.md`.

**Setter, attempter, marker (owner, 2026-10-26, O19).** No result counts if the
same context set the exam and sat it. For every test set, eval, label file,
corpus, pilot or live experiment, name the three roles and keep them apart:

- **Setter:** a different context from whoever built the thing under test, and a
  different model where possible; best of all, human-authored material (real
  open-source code, fixes that maintainers merged). Exams are tiered: basic
  checks, hard cases, and adversarial "god mode" cases. Answer keys are sealed
  (committed, with their hash recorded) before any attempt.
- **Attempter:** sees only what a real run would see, never the keys, rubric or
  labels.
- **Marker:** deterministic where possible (the frozen judges); where judgement
  is needed, a different model from the attempter with an adversarial rubric, a
  second marker on disagreement, and a small sample for the owner to spot-check.

A result whose setter and attempter share a context is reported as a smoke test,
not as evidence. Builders still write tests first, but high-risk units (judges,
anti-cheating, budget, security, the idea portfolio) also get acceptance tests
written from the spec by a separate agent that never sees the implementation.

### Process

Shape Up for bets, Kanban for flow, XP for engineering, DORA for measurement.

- A step is a sprint. **Briefing before** (what, why, one diagram, one example,
  ordered changes); the user objects or redirects, otherwise work proceeds.
  **Report after** (what was built, evidence, before/after, what the next step
  needs). Both crisp.
- One wave of work in progress at a time; the task list is the board.
- **Definition of done:** tests first with 90%+ coverage; no test weakened or
  skipped; Reviewer has no blocking findings; stage gate green; docs updated
  (README, STATUS development log, CLAUDE.md); draft PR with CI green;
  revertable in one commit.
- Trunk-based: short-lived branch, one commit per unit (commitlint header <= 72
  chars), PR, CI; `/security-review` before a PR is marked ready.
- Retro at the end of each step: a "Lessons" entry in `STATUS.md` that changes
  this file or the hooks when needed.
- DORA-style tracking per step in `STATUS.md`: lead time, CI-red pushes, rework
  commits, reverts.

### Builders in a shared worktree (Step 3 lessons, `STATUS.md`)

Parallel Builders share one worktree on disjoint files. Each brief carries these
rules:

- **Size by source.** A unit row states source and test lines separately; the
  ~400-line cap is on source. A Builder stops and reports when its source passes
  1.5x its row.
- **Reds that prove something.** Every red run shows at least one assertion
  failure, not only a missing module, and every fix round shows its own red. A
  security unit shows a red per protection: remove it, and the named test fails.
- **Private coverage data.** Each Builder sets its own `COVERAGE_FILE` (in the
  scratchpad, named for the unit); a shared `.coverage` mixes runs.
- **Format only your files** (`ruff format <files>`); run the repo-wide check
  with `--check` only.
- **Mutations on scratch copies only**, run with `-o pythonpath=<copy>/src`
  (`pyproject.toml`'s `pythonpath` beats `PYTHONPATH`) plus a canary mutation
  that must be killed; a mutation claim without its canary is not evidence.
- **Timing guards keep about 2x margin, measured on CI**: a fixture's baseline
  sits at about twice the guard's floor on a CI runner, not only locally. A
  timing failure under concurrent Builders' load is reported as such; the Lead's
  sequential gate on a clean copy and CI decide.
- **Every spec rule has a unit.** Before a build, the Lead maps each decision,
  failure mode and security control in the spec to the unit row that builds it.

### Standing permissions for PRs and branches (user, 2026-10-24)

Phase approvals are unchanged: the user approves each step's spec and build plan
before building starts. Within that, the Lead may, without asking:

- mark a PR ready and merge it into `master` with a merge commit (a step's PR or
  any other Lead PR, such as experiment branches; extended by the user on
  2026-10-24), once its stage gate is recorded as a clean pass in `STATUS.md`,
  every required CI check on the PR head is green, and the PR is mergeable with
  no conflicts;
- create a branch per step (`claude/<step-name>`) from the latest `master`, or
  stacked on the open step's head when the previous step is not merged yet, and
  open a draft PR for it;
- retarget a stacked PR after its base merges, and merge `master` into a step
  branch to keep it current;
- delete a branch after its PR is merged.

Branches merge into `master` in order, each through its own PR; conflicts are
resolved on the branch (by merging `master` into it and re-running the tests),
never on `master`. The `live` environment accepts dispatches from `claude/*`
branches.

Still ask the user first: any direct push to `master`; any force-push; merging
with a red, skipped-required or pending check; deleting an unmerged branch;
changing repository or branch-protection settings, or the `live` environment.
After each merge, report the PR number, the merge commit and the CI result on
`master`.

### Stage gate (end of every step)

1. **Upgrades.** Review `pnpm outdated -r` and `uv tree --outdated --depth 1`
   (the gate reports both). Upgrade inside the step unless a major bump needs
   its own PR. Dependabot opens weekly PRs (Actions, npm, uv, Docker) for
   anything missed.
2. **Audits.** `pnpm audit --audit-level=moderate`, `pip-audit` and `bandit`
   must be clean. `security.yml` (OSV, Trivy, secret scanning) runs on every
   push and every Monday. Fix or justify each finding in the PR.
3. **Security review of the new code** against the OWASP list above; add the
   protections the step needs (worktree isolation, URL validation, the automatic
   capability policy for package installs and MCP connections).
4. **Docs.** `README.md` (what and how), `STATUS.md` (development-log row:
   planned, started, completed, PR, gate; decisions; lessons), the relevant
   `CLAUDE.md` if conventions changed.
5. **Quality.** `pnpm stage-gate` runs typecheck, lint, format, tests and
   coverage for both ecosystems (`pnpm stage-gate:quick` skips the slower audit
   and outdated checks).
6. **PR.** Draft, CI green, then ready for review.

---

## Technology Stack

- **Python 3.11+** with `uv`, Hatchling, Ruff, mypy strict, pytest
- **LangGraph 1.x** for the orchestrator loop; **anthropic 1.x** SDK
- **Node.js 22.12+**, TypeScript 5.9, pnpm 10, Vitest, ESLint, Prettier
- **Claude** via the Messages API: `claude-opus-5-5` (engine and editor),
  `claude-sonnet-5-5` (hypothesis generator, matcher), `claude-haiku-5-5`
  (triage)
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
uv run mypy src tests
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

- **4.5.0 (2026-10-26):** The setter/attempter/marker rule (O19) under
  Development Workflow: no result counts if one context set the exam and sat it.
- **4.4.0 (2026-10-25):** Step 3 Wave 1 built: the reality check (generated
  hypotheses, one fix retry per run, the review branch, the default output check
  and the quality check, the noise rule; schema 001-006); the Step 3 build-order
  row in the owner's wording (O1) and 3c before 3b (O5); "flagged" replaced by
  the `engine/review-<id>` branch in the vision, L7 and 3c (D10); the quality
  check (O7), the default output check (O9), one retry per run (O8) and the
  noise rule (O10) in the vision; Sonnet 5.5 as the discovery model; a new
  "Builders in a shared worktree" section from the Step 3 Wave 1 lessons.
- **4.3.0 (2026-10-24):** Vision update from the user: automatic package
  acquisition (an automatic policy replaces the approval gate), self-healing of
  the user's code and of the engine's own trials, and MCP server and API
  discovery join the vision, the loop (ACQUIRE, HEAL) and the L3, L5 and L7
  rows; the build order gains Steps 3b (capability acquisition), 3c
  (self-healing) and 6 (production loop), Step 3 the engine self-retry and Step
  4 MCP/API discovery (approved by the user the same day). Standing permissions
  for PRs and branches (mark ready, merge with a merge commit, branch per step,
  retarget, delete merged branches) under Development Workflow.
- **4.2.0 (2026-10-22):** Step 2 built: reality check updated to the real core
  loop on CPU Python workloads; build-order row 2 marks the pending gate and PR
  #12; the layer table points L5-L7 at the built service packages.
- **4.1.0 (2026-10-21):** Step 1 delivered: reality check updated to the walking
  skeleton; `mypy` covers tests in the gate; build-order rows point at PR #11.
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
