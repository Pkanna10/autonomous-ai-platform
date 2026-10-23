# Project Status - Autonomous AI Platform

**Last Updated:** 2026-10-23

---

## Current Step

**Build step:** 2 of 5 (Core loop), units U1-U21 committed; Verifier, stage gate
and `/security-review` done, first live run pending **Branch:**
`claude/adoring-clarke-xpo1py` (draft PR
[#12](https://github.com/Pkanna10/autonomous-ai-platform/pull/12)) **Vision:** a
self-improving optimization engine that uses research findings and novel ideas
to provably improve existing code, or build something new and then improve it
(see `CLAUDE.md`).

### Resume here (handoff, 2026-10-22)

A new session picks up Step 2 from this section. Everything it needs is in the
repo; nothing lives only in the old session.

- **Built:** every Step 2 unit, U1-U20, is committed (one commit each, each
  reviewed for correctness and security on a different model and fixed
  test-first; U15 was reviewed after it was committed). The list is in "Step 2
  summary" below; the decisions behind them are in "Decisions".
- **Done (2026-10-23):** the Verifier (two rounds plus a PHP2Shell-class attack
  round, findings fixed), the stage gate (passed; minor upgrades in, majors left
  to their own PRs), `/security-review` (two findings, both fixed: see
  Decisions, 2026-10-23 security review) and U21, the Stage A live suite.
- **Next, in order** (the user approves each before it starts):
  1. the first **live-smoke** run (Stage A, user approval in the `live`
     environment), its costs in the ledger below, and any fixes;
  2. remove `continue-on-error` from the `python-macos` job so the macOS job is
     blocking (green since `bb1981a`);
  3. the Step 2 report, docs final (root `CLAUDE.md`: Dependabot instead of
     Renovate in the stage gate, Node.js 22), the draft PR marked ready.
- **Read first** while `.claude/handoff/step2/` still exists: `spec.md` (44
  decisions, interfaces, behaviour, security, test plan) and `lead-notes.md`
  (Lead decisions and per-unit handovers). Both are summarised under "Decisions"
  below, so nothing is lost when the folder goes.
- **Environment:** the database tests need Postgres 16 with pgvector and a role
  that may create databases (`TEST_DATABASE_URL`; the Docker Compose database
  works). The profiler tests also run `python3.8` to `python3.12`
  (`uv python install 3.8 3.9 3.10 3.11 3.12` puts them in `~/.local/bin`); a
  missing one skips locally but runs in CI. Check both before a long run; do not
  assume an environment setup script ran.
- **How a unit was built:** the Workflow tool with
  `scriptPath: .claude/handoff/step2/build-wave.workflow` (absolute path) and
  `args: {maxOutputTokens: 800000, units: [{id, title, files, tests, security, notes}]}`,
  one unit per run: Builder (tests first), correctness and security Reviewers
  (Fable), fixer. The run halts when a review is missing. The Lead then
  verifies, commits one unit per commit and pushes.
- **Lead verification before every commit** (from `services/python_agents`):
  `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests`,
  `uv run bandit -q -r src -c pyproject.toml`,
  `TEST_DATABASE_URL=postgresql://dev:devpass@localhost:5432/postgres uv run pytest -q`
  (100 % line and branch coverage today), and the suite on a Python 3.11 venv
  with `-o addopts="-n auto --no-cov -m 'not live'"`.
- **Never run live tests**: always pass `-m "not live"` when overriding
  `addopts`. Cloud containers set `ANTHROPIC_BASE_URL` for their own use; the
  engine follows only `ENGINE_API_BASE_URL`.
- **Before merging Step 2**, delete `.claude/handoff/`.

---

## Development Log

One row per build step. "Gate" is the result of `pnpm stage-gate` at the end of
the step.

| Step | Deliverable                                                     | Planned    | Started    | Completed  | PR                                                                | Gate    |
| ---- | --------------------------------------------------------------- | ---------- | ---------- | ---------- | ----------------------------------------------------------------- | ------- |
| 0    | Repair & upgrade (DB init, deps, models, docs, stage gate)      | 2026-10-21 | 2026-10-21 | 2026-10-21 | [#11](https://github.com/Pkanna10/autonomous-ai-platform/pull/11) | passed  |
| 1    | Engine design (typed state, data model, judges, migration 003)  | 2026-10-21 | 2026-10-21 | 2026-10-21 | [#11](https://github.com/Pkanna10/autonomous-ai-platform/pull/11) | passed  |
| 2    | Core loop end to end on CPU Python workloads + E2E fixture test | 2026-10-21 | 2026-10-21 |            | [#12](https://github.com/Pkanna10/autonomous-ai-platform/pull/12) | pending |
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

### Step 2 summary (2026-10-21 to 2026-10-22, stage gate pending)

The loop now runs for real on CPU-bound Python workloads: preflight at connect,
one Claude understand request, a measured baseline and a cProfile profile, one
Claude-edited trial per hypothesis in its own sandboxed git worktree, the frozen
judges, a combine re-tested ABAB against a fresh baseline with the test suite on
its tip, and delivery to a local `engine/run-<id>` branch. Research, the CLI and
hardware detection do not exist yet; hypotheses are supplied by the caller
(`NodeContext.candidates`).

```
connect     GitPreflight: git >= 2.38, no submodules / LFS / partial clone,
            merge drivers, commands resolved and protected, sandbox probe
understand  ClaudeUnderstander: git objects at the base commit, one request
baseline    GitBaselineRunner: F0 -> worktree -> warm-ups + N runs + tests -> F1
profile     CProfiler: untimed cProfile run in its own worktree, hotspots
trials      GitTrialRunner (serial, running cost total): F0* -> worktree ->
            ClaudeEditor + WorktreeEditor -> capture + anti-cheat -> commit ->
            own trial ref -> measure + tests -> F1* (* own ref excluded)
combine     GitCombiner: merge-tree greedy -> ABAB + tests on the tip -> judged
            with derive_verdict; else best single change; else report only
deliver     GitBranchPublisher: create-only update-ref, never pushed
every run   unshare -rn -p -f --ipc --mount-proc | sandbox-exec, then the
            launcher: lo up, no_new_privs, Landlock, self-check, exec, report
```

By layer, with the commits (all on this branch):

- **Foundations:** models, settings, errors, budget (`7b00c38`, U1); the
  `dedupe_repo` fixture and its edit sets (`defe5a8`, U2); the protocols, fakes
  and `ScriptedEditor` (`c331a68`, U3).
- **L5 execution:** hardened `GitWorkspace` (`3cf619e`, U4); sandbox policy and
  launcher (`20824ee`, U5) and the report-forgery fixes (`11c116e`, U5b);
  worktree-confined editor tool handler (`b5d6c98`, U7); sandboxed process
  runner (`3bfb28c`, U11); connect-time preflight (`05ea510`, U13); measurement
  and the test-suite pass mark (`3a92c15`, U14); cProfile profiler (`90b08fd`,
  U15, reviewed after commit; fixes `dbec415`, `cd0a3e6`); Claude editor loop
  (`897aa2c`, U16); git trial and baseline runners (`a22d142`, U18); combiner
  and publisher (`fefe698`, U19; `1f5c131`); shared phase cleanup and branch
  guard (`783bf8b`, U20a); merge attributes at connect (`7989626`, U20b); macOS
  EPERM on `killpg` (`ecb24aa`).
- **L6 optimization:** capture rules for what a trial changed (`4b9fb3b`, U9)
  and the module-shadow and recipe-file fixes (`1febcaf`, U9b); unittest's
  `test*.py` protected (`56cb594`); `normalize_path` refuses `./~x` and `./c:x`
  (`d917f30`).
- **Claude clients:** worst-case cost model (`5e7c556`, U6); transport and retry
  loop (`708f288`, U12); one fallback model and 8,000-token editor turns by
  default (`1a862dc`); the API address pinned to `ENGINE_API_BASE_URL`
  (`a17c54a`).
- **L2 orchestrator:** Step 2 behaviour in the nodes (`54e1eb2`, U10); the
  Claude understand node (`d15fc52`, U17); the factory that wires the real
  engine, and the E2E (`4818abf`, U20d).
- **Persistence:** `PostgresRepository`, `orchestrator/serde.py` and migration
  004 (`3adab53`, U8).
- **CI:** the Postgres service, the sandbox probe, the macOS and live-smoke
  jobs, Schema Apply 001-004 (`7e8a4b5`, U20c); pytest 9 floor (`4037201`).
- **Docs and handoff:** `6610603`, `a1717c3`, `dd1c99c`, `a938f3b`, `80c1a8d`,
  `c3fd7d8`.

The three E2E scenarios (`tests/e2e/test_step2.py`, about 20-40 s here) run on
the `dedupe_repo` fixture with real git, sandbox and measurement and scripted
Claude replies:

- **E2E-A, the Claude path:** the editor's attempts on `.GIT/hooks`, `../x`, a
  symlinked path and a test file come back as tool errors; h1 is kept, h3
  (`sorted(set)`) is rejected by the equivalence judge, the profiler finds
  `unique_in_order`, the combination holds and the tip is base + h1.
- **E2E-B, the git-side defence** (on Postgres when `TEST_DATABASE_URL` is set):
  h2 (deletes a test) and h6 (adds a symlink) are rejected and never run, h5 is
  kept and then skipped as a conflict, one `Engine-Trial` commit is delivered.
- **E2E-C, the budget:** the second trial never starts, the router goes to
  combine, and `cost_usd <= max_cost_usd`.

Each also asserts that the user's HEAD, index, status, config, refs, hooks and
`info/` are untouched, that only the expected refs exist, that no worktree is
left, and that every phase that ran repository code was sandboxed.

Tests on 2026-10-22 (Python 3.13, `TEST_DATABASE_URL` set): 3,363 passed, 3
skipped (two macOS-only cases, one that cannot run as root), 100 % line and
branch coverage of 7,297 statements and 2,000 branches.

---

## What Exists Today

| Component                                                                            | State                                    |
| ------------------------------------------------------------------------------------ | ---------------------------------------- |
| Docker Compose: Postgres 16 + pgvector, Redis, Qdrant                                | Working                                  |
| Schema `001` to `004_engine_repository.sql`                                          | Working; applied in CI on every PR       |
| CI: lint, typecheck, tests, coverage, Python CI (Linux, macOS), live smoke (manual)  | Working; the macOS job not blocking yet  |
| Security: OSV, Trivy, Docker Scout, pip-audit, bandit, safety, secret scan, Renovate | Working                                  |
| `packages/agent-core` Claude client + shutdown                                       | Working (33 Vitest tests)                |
| `services/python_agents` settings                                                    | Working                                  |
| LangGraph orchestrator (`EngineState`, 15 nodes, router, `Orchestrator`, factory)    | Working on CPU Python workloads (Step 2) |
| Preflight, understand, baseline, profiler, trial runner, editor, combine, publisher  | Working (Step 2)                         |
| Data model, anti-cheating, judges, ranking, lessons, `PostgresRepository`            | Working (Steps 1 and 2)                  |
| `research/arxiv_monitor.py`, `pdf_parser.py`; the `research` and `watch` nodes       | Placeholders / stubs (Step 3)            |
| `packages/research-engine`, `execution-engine`                                       | TypeScript placeholders                  |
| Research matcher, CLI, live log, hardware detection, web console                     | Not started                              |

---

## Decisions

### 2026-10-22 (Step 2: the spec's 44 decisions)

The approved Step 2 spec (`.claude/handoff/step2/spec.md`, deleted before merge)
opened with 44 decisions. Each is summarised here with its reason, under its
spec number; later changes are marked.

1. **Every external effect behind a Protocol with a deterministic fake.** The
   whole loop must be provable in CI with no key and no network; this design
   scored highest with both judges (39 and 40 of 50).
2. **Writes confined in the launcher** under `FS_ISOLATION=required`: Landlock
   (ABI 1 or later, through `ctypes` syscalls) on Linux, a `sandbox-exec`
   file-write deny on macOS. Claude-steered code would otherwise run with the
   user's write access; a fresh HOME is not a sandbox, and the worktree's `.git`
   file names the user's git dir.
3. **Network: `unshare -rn -p -f`** with the launcher bringing `lo` up
   (`--ipc --mount-proc` added in U5b), `(deny network*)` on macOS, no Landlock
   TCP rules. The namespace already blocks TCP and UDP; Landlock TCP needs ABI 4
   (kernel 6.7).
4. **A PID namespace with the launcher as PID 1.** `setsid` orphans then die
   with the launcher (verified: 0 survivors).
5. **The launcher is a real stdlib-only module run as `python -I -S`.** It is
   lintable, typed and testable in-process, and a fresh interpreter keeps the
   RSS floor of every measurement at a few MiB instead of the engine's size.
6. **The macOS wrapper is built now and runs in a `macos-latest` job against
   `/usr/bin/git`.** maxrss units, Apple git 2.39 and SBPL semantics are caught
   before the M4 dogfood (the first run caught `killpg` EPERM).
7. **Combine with plain `merge-tree --write-tree ACC X` and a single-parent
   `commit-tree`.** `--merge-base` needs git 2.40 and Apple ships 2.39; every
   trial's parent is the base, so the natural merge base is the base. History
   stays linear, one revertable commit per change.
8. **git 2.38 floor; `--attr-source=<empty tree>` only on git 2.40 and later,
   and an empty override for every driver key.** The user's config and
   attributes are untrusted input, and this works on Apple git.
9. **SDK `max_retries=0` and the engine's own retry loop**: only 429, 529, 500,
   502, 503, 504, timeouts and connection errors retry, at most
   `LLM_MAX_RETRIES` times, backoff `min(30 s, 2^k s)` with `retry-after` as a
   floor (above 60 s it gives up); `Budget.check` before every attempt; a
   timeout is charged the full estimate, an HTTP error 0; 400/404/413 raise
   `LLMRequestError`, 401/403 `LLMConfigError`. The SDK retries timeouts
   silently, so the cap would not be a bound.
10. **`budget_usd` is required and the trials node keeps a running total**,
    stopping before a trial when the remainder is below `min_trial_budget_usd`
    (one worst-case editor request). A total computed after the loop let each of
    three trials spend the full remainder; a trial that cannot afford one
    request would only fail at its first check.
11. **`budget_exhausted` sends the router straight to combine.** Otherwise the
    `proposed` hypotheses left behind spin empty rounds.
12. **Capture violations go into `Trial.violations` with status `failed`.** The
    runner statuses stay `{measured, failed}`, so the Step 1 contract holds and
    verdict rule 1 still rejects.
13. **Capture rules `forbidden_file_mode`, `forbidden_file`, `git_metadata`,
    `unrecorded_write`, `process_spawn`** (`module_shadow` added in U9b). The
    engine never trusts what the editor says it changed. No LFS rule: LFS is
    refused at connect.
14. **`process_spawn` is an AST scan of the changed `.py` files**, applied when
    CPU time or peak RSS is judged. Splitting work across processes fakes a
    per-process win; a regex would flag comments and miss `posix_spawn`. It
    guards against honest mistakes, it is not a defence.
15. **No judge changes.** Nondeterministic output under an equivalence guardrail
    and a failing baseline suite fail closed at the baseline: the judges stay
    frozen and failing before the trials spends no money.
16. **User-repo fingerprint F0/F1** of `config`, `config.worktree`, `hooks/`,
    `info/`, the HEAD symref and the `refs/heads` and `refs/tags` refs, around
    every phase that runs repo code (widened in U4: the effective config and
    every ref under `refs/` except `refs/remotes/` and `refs/prefetch/`, because
    `refs/replace` rewrites what the user's git shows and `refs/stash` what
    `stash pop` applies); a trial excludes only its own ref, which must then be
    absent or at `Trial.commit`. The index, status, remotes and logs are left
    out: IDEs rewrite the index and fetch remotes, while tampering shows in
    refs, config and hooks.
17. **Worktree git calls pass `--git-dir`/`--work-tree` from a `WorktreeHandle`
    read right after `worktree add`**, and the `.git` file is compared after
    every run. Sandboxed code can rewrite that link (it sits in the writable
    worktree) to aim a later `clean -ffdx` elsewhere, and git renames admin dirs
    on a collision, so nothing may be assumed.
18. **`engine/trial-<run>-<hyp>` refs are kept** for committed trials, with ids
    `uuid5(branch@round)`; an existing ref moves only when its commit's
    `Engine-Trial:` trailer matches. Trial commits stay alive for combine and
    inspection, and a re-executed node is idempotent.
19. **Commit identity and dates come from the base commit**, so a resumed run
    reproduces the same SHAs.
20. **`Project.test_command` on the model and in `projects.test_command`**; a
    `tests_pass` guardrail without one is a `PreflightError`. It survives a
    resume, and without it the test-suite judge would be inconclusive on every
    trial and the run would silently yield nothing.
21. **Harness paths inside the repo are protected** (`command[0]`,
    `test_command[0]`; later every argument naming a repo file). A harness is
    not the code under optimisation.
22. **The measured worktree is reset before every run**, identically for the
    baseline and each trial, so a workload cannot memoise across runs.
23. **The cProfile profiler ships in Step 2**, in its own worktree, with an
    engine-owned `PYTHONPATH` prefix and an editable-install check. It was the
    last stub on the measurement path, and without the check a trial can
    silently measure the user's checkout.
24. **Trials run serially.** Overlapping measurements disturb each other.
25. **The combination is always re-tested ABAB, even with one change, and the
    suite runs on its tip.** It holds iff `derive_verdict` says keep; else the
    best single kept change (highest gain, then hypothesis id) is re-tested
    once; else the run delivers a report only. Only what reproduced against an
    interleaved baseline, with its tests run, is delivered.
26. **A two-change combine is proven in integration tests, not the E2E.** On the
    fixture's one workload two independent changes cannot both clear the noise
    floor.
27. **`orchestrator/serde.py` with one `TypeAdapter` per state key.**
    `TypeAdapter(EngineState)` fails on Python 3.11, and Step 4 needs this to
    re-type `PostgresSaver` values.
28. **`save_run(initial)` runs before the graph starts**; a `root_path` clash
    becomes `ProjectConflictError`. This fixes the lessons foreign-key
    violation, leaves an audit row if a run crashes, and the caller sees an
    engine error, not a psycopg one.
29. **Trials and verdicts stay in the 003 JSONB arrays; migration 004 adds no
    tables.** One source of truth per run; 004 is idempotent.
30. **Postgres tests use an env-gated skip and `addopts` adds only
    `-m "not live"`.** CI always runs them, so coverage counts them.
31. **Operator notices are nonce-tagged text blocks after the tool results.**
    `role: system` mid-loop waits until the live smoke test confirms the wire
    shape; the caps are enforced in code anyway.
32. **`httpx2.MockTransport` is the transport test seam.** anthropic 1.17 is
    built on httpx2 2.16, which exports it (verified in `.venv`).
33. **`Hotspot.tags` stays free-form.** Existing tests and lessons use other
    tags; a fixed vocabulary belongs to the Step 3 matcher.
34. **`BaselineRunner.measure` still returns a tuple.** Node-level checks report
    noise and nondeterminism, and the Step 1 tests stay unchanged.
35. **The open item "judged trials state key" is closed**: `round_trials`
    already does that job.
36. **CI stays on ubuntu-22.04, behind a probe that fails loudly** without
    `unshare` or Landlock; the fallback is 24.04 with the AppArmor sysctl, and
    `REQUIRE_*` is never weakened. A sandbox test that silently skips proves
    nothing.
37. **Every engine error class lives in `common/errors.py`.** `clients/`,
    `execution/` and `persistence/` cannot import `orchestrator/nodes.py`
    without a cycle, and the errors had to exist before the units that raise and
    map them.
38. **Each phase owns its worktree, `_scratch` and `_probe` dirs and removes
    them in `finally`** (shared as `execution/phase.py` in U20a). One owner per
    path: nothing is guessed and nothing leaks; the E2E asserts it.
39. **The fallback chain is sent explicitly** (`fallbacks=[{"model": m}]`) and
    the estimate prices the worst model in it times its length. The priced chain
    must equal the billed chain or the estimate is not a bound. Changed in
    `1a862dc`: one fallback (`claude-opus-4-8`) and `EDITOR_MAX_TOKENS` 8,000 by
    default, so one request's empty-prompt worst case is $0.40.
40. **`ScriptedEditor` is keyed by hypothesis title, candidate ids stay uuid4,
    and `PostgresRepository` refuses a non-UUID id before any SQL**
    (`InvalidRecordIdError`). The UUID columns would reject it mid-run;
    `InMemoryRepository` keeps accepting any id for the Step 1 tests.
41. **The LFS refusal reads attribute sources directly, never `check-attr`.**
    The engine's own `core.attributesFile=/dev/null` and `--attr-source` hide
    `.gitattributes` from `check-attr`.
42. **The launcher self-checks isolation on every run**: a write in
    `_probe/<phase>` and a connect to the parent's 127.0.0.1 listener must both
    fail, and `LaunchReport` carries `fs_isolated`, `net_isolated` and `error`.
    The connect-time probe proves the host can isolate; only a per-run check
    proves this run was isolated.
43. **`Workload.warmup_runs` is honoured (0 allowed); `Workload.inputs` is not
    passed** and connect warns. No input channel exists yet, and baseline and
    trial ignore inputs alike, so the comparison stays valid.
44. **Path patterns and the matcher live in `common/paths.py`.** The editor
    handler and the capture rules must enforce one definition.

### 2026-10-22 (Step 2: Lead decisions and accepted trade-offs)

From the per-unit reviews and handovers (`lead-notes.md`, deleted before merge).
Where a decision changed the spec, the code follows the decision.

- **The launcher's report is parsed strictly and cross-checked against the
  kernel's accounting** (the wrapper's `wait4` rusage and procrun's own wall
  clock); exit status 125 alone never means a refusal. Inside `unshare -r` the
  workload is root in its own user namespace, so the report must be bounded by
  numbers it cannot touch.
- **A privilege drop that fails under `best_effort` is recorded as isolation not
  applied, never as a failure**, and a non-root launcher that cannot clear its
  bounding set is accepted when it holds no effective or permitted capability:
  with `no_new_privs` set, `execve` cannot gain any.
- **The whole scratch root (HOME, TMPDIR) is fresh before every run**, not per
  phase: a warm-up could otherwise leave an answer for the timed runs.
- **The pass mark of the test suite comes from the runner's own summary**
  (unittest's `Ran N tests` + `OK`, or pytest's JUnit XML written into the
  scratch root), and fewer passing tests than the baseline is 0.0. A suite can
  exit 0 after a trial deletes tests. The worktree is also reset right before
  the suite, so a module a workload dropped cannot shadow the runner.
- **Preflight refuses partial clones** (fix: `git fetch --refetch` or a full
  clone): a lazy fetch would reach the network. **It protects every argument of
  the workload and test commands that names a repo file**, and **refuses an
  editable `.py` file the engine's Python cannot parse**, because the AST checks
  must fail closed.
- **Fallbacks use the `server-side-fallback-2026-06-01` beta**, and an empty
  `ENGINE_FALLBACK_MODELS` sends no field. **Input tokens are counted with the
  free `count_tokens` endpoint per model in the chain, plus a margin**, with the
  byte bound on any failure: a tighter estimate that is still a bound.
  `LLMResult.unpriced_models` names a billing model missing from the table.
- **HTTP 402 is `LLMConfigError`** (billing: the account must act); 409, 422 and
  501 stay `LLMRequestError`. Neither kind is retried.
- **The engine sends the key only to `ENGINE_API_BASE_URL`** and keeps the
  `anthropic` logger at INFO or stricter. The SDK follows `ANTHROPIC_BASE_URL`
  (this container sets it) and its DEBUG log prints request options.
- **Understand is one structured-output request** with no tools, no caching, the
  API's default effort and a 2,000-token allowance for the system prompt the API
  adds. `workload_notes` travels as an array (structured outputs need
  `additionalProperties: false`); reply text with control or bidi characters
  rejects the whole reply; `READ_DENY_PATTERNS` files are neither listed nor
  read.
- **The engine never unmarshals a profile the workload wrote.** `marshal` is
  unsafe on hostile data, so pstats are converted to JSON inside the sandbox and
  parsed strictly with a size cap; hotspots are untrusted hints.
- **Trial runner rules:** a `GitError` during capture fails the trial while
  `RepoTamperedError` propagates; reserved module names include each `-m`
  target, and module roots include each workload's `working_dir` and script
  directory; invoke's `tasks.py` and config are protected when a command runs
  invoke; a foreign `engine/trial-*` ref (no matching trailer) stops the trial
  before any worktree; a re-run that commits nothing deletes its stale ref; an
  own ref that is checked out is never moved.
- **Publisher rules:** the ref is read before anything is checked out, a default
  branch that is a symref to the new engine ref is detected and the create
  undone (`DeliveryError`), and the combiner takes the baseline's passing-test
  count (both reviewers found that the tip's suite only had to pass one test).
- **One shared phase cleanup** (`execution/phase.py`) runs every step in its own
  `finally`, never follows a planted link and never hides an error already on
  its way: a failing removal must not mask tampering.
- **Merge attributes are checked at connect, per git version** (U20b): on git
  2.40 and later only `info/attributes`, `core.attributesFile` and
  `merge.default` reach a combine, so committed `.gitattributes` become one
  note; on older git committed and checked-out copies count too. A custom driver
  is refused; `union` and binary merges are notes, because the tip is re-tested
  anyway.
- **The factory** builds the real context from settings, rebinds both runners to
  the test command connect resolved, refuses a `WORKTREE_ROOT` that overlaps the
  checkout, and sends runner notes to the live stream as `runner_note` warnings.
- **`NETWORK_ISOLATION=off` keeps no namespaces on Linux** (wave 2b, below).
- **Modules above the ~400-line Builder cap were accepted at review** rather
  than split mid-step, which would have reopened reviewed code: `procrun.py`,
  `transport.py`, `measure.py`, `editor.py`, `editor_tools.py`, `preflight.py`,
  `understand.py`, `trial_runner.py` (sizes under "Technical Debt").

### 2026-10-23 (Step 2, Verifier findings fixed)

- **A killed run is recovered by the next connect.** Each phase owner holds a
  shared `flock` on `<WORKTREE_ROOT>/<run>/.aip-run.lock` while it works;
  connect's `sweep_stale_runs` takes the lock of every marked run exclusively
  and runs the shared cleanup on each phase in it. Why: a SIGKILLed run's
  directory still exists, so git never calls its registration prunable, and only
  the kernel knows reliably whether its owner is alive (it drops a `flock` on
  any exit). An unmarked directory is never touched, so a user's own worktree
  inside `WORKTREE_ROOT` is safe. An unmarked worktree of the repository at
  `<run>/<phase>` (an owner whose cleanup failed drops its marker; runs killed
  before the marker existed never had one) is refused at connect with the manual
  recovery, not swept and not called an overlap. Why: no lock proves its owner
  gone (an owner that could not create the marker runs unmarked), so the user
  removes it; the overlap advice ("move `WORKTREE_ROOT`") was wrong there.
- **One call drives a run id at a time per process** (`Orchestrator`
  `_driving`). Why: `resume` checked the gate and invoked the graph later, so
  two resumes both passed, delivered contradicting decisions and raced for the
  fixed `<run>/combine` path. The claim makes check and call one step; the
  in-memory checkpointer is per process, so a process-wide claim is complete
  until a shared checkpointer exists. `stream` releases it before its own last
  event. Why: a generator suspended at that event held the claim, so a consumer
  that stopped there and kept the iterator could not resume the paused run.
- **A failing node keeps what it earned.** The trials node and understand attach
  their running total (and the round's finished trials) to the exception
  (`nodes.keep_progress`); the trial runner notes the money an aborted trial
  spent (`errors.add_spend`) and puts its own ref back, unless a worktree
  checked it out meanwhile (a runner note says the ref stays: deleting it left
  that worktree's HEAD unborn). `Orchestrator` merges it into the failed state,
  adds a `trial_refs_left` event with the cleanup command, and saves a failed
  row before a non-engine exception propagates. Why: a failed run was built from
  the previous checkpoint, so the money spent in the failing node and the trials
  it had saved were missing from the state and the audit row.
- **A trial the cap stops before its first request never started**
  (`TrialUnaffordable`): the trials node treats it as an exhausted budget, not a
  rejected change, so no verdict or lesson is recorded. Why: the factory's floor
  prices an empty prompt and is always below a real first request, and a
  "reject" lesson for a hypothesis that was never tried would lower its ranking
  in later runs.
- **`Project.root_path` is canonical** (`realpath`). Why: the one-project-per-
  root rule compared strings, so a trailing slash or a symlink registered one
  repository under several ids, while git already used the real path.
- **`WORKTREE_ROOT` may not overlap the git common dir or any other worktree**
  of the repository (connect). Why: with a linked worktree as root_path, a
  `WORKTREE_ROOT` inside the main checkout was swept by the user's `git clean`,
  and one in `.git/worktrees` collided with git's admin dirs.
- **A committed `output_file` is refused, and the path is protected.** Why: the
  reset before every run restores a committed copy, so the fingerprint read it
  whether or not the run wrote it, and a change that skipped its work passed the
  equivalence judge.
- **The default objective bounds peak RSS** (a `metric_bound` guardrail, at most
  +10 %, added only when no objective is given and no RSS bound exists). Why:
  the documented default is "faster and leaner", but only wall time was judged,
  so a 27x memory regression shipped. A guardrail, not a second objective, so a
  trial need not also prove a memory gain.
- **The report says whether the test count was verified** ("Test count" in Run
  conditions), and README lists wrapper runners as a limitation.
- **The trial-ref cleanup command names exact refs and commits** in one
  `git update-ref --stdin` transaction. Why: the `xargs` form failed on empty
  input, and the `trial-<run>-*` pattern also matched run `<run>-2`'s refs.
- **The launcher blocks `socket(AF_UNIX)` with a seccomp filter** (Linux,
  whenever network isolation is on), installed in PID 1 of the namespace and
  inherited across exec, with a new self-check that creating an AF_UNIX socket
  must fail. Why: the network namespace isolates AF_INET and abstract AF_UNIX
  but not path-based AF_UNIX, so a kept, delivered trial could still reach a
  host unix-domain service (`/var/run/docker.sock`, a local Postgres/Redis
  socket) and exfiltrate while the engine reported a clean efficiency win.
  Blocking `socket(AF_UNIX)` closes every path-based unix socket regardless of
  its location; `socketpair(AF_UNIX)` (a connected pair, no egress, used by
  multiprocessing's `fork` start method) and AF_INET (the loopback probe) stay
  allowed. Cost: multiprocessing's `spawn` and `forkserver` start methods need
  an AF_UNIX listener and fail under the Linux sandbox (see Known gaps). macOS
  needs nothing new: `sandbox-exec`'s `(deny network*)` already covers AF_UNIX
  `connect`, so the filter and the AF_UNIX self-check are Linux-only.

### 2026-10-23 (Step 2, stage gate and security review)

- **Stage gate passed** with two warnings (outdated packages). Minor upgrades
  went in (langchain 1.4.7, langchain-core 1.7.0, ruff 0.17.2,
  sentence-transformers 6.2.0). Majors wait for their own PRs: anthropic 2,
  redis 8, pymupdf 2, TypeScript 7, ESLint 10, Vitest 5, Vite 8, commitlint 21,
  dotenv 18, @types/node 26. Why: a major bump changes behaviour the Step 2
  tests do not cover on purpose, and one PR per major keeps each revertable.
- **`worktree add` no longer checks out.** It runs with `--no-checkout`, then
  `checkout -f` through `_git` on the new handle. Why (`/security-review`,
  reproduced by a test): `_git` empties the repo-defined drivers it lists from
  the command's own context, but `worktree add` checks out in a child git whose
  git dir is the new admin dir. An `includeIf "gitdir:worktrees/"` defined a
  smudge filter there that the listing never saw, so a malicious repository ran
  a command unsandboxed at every phase's first checkout.
- **Preflight refuses `includeIf`** in the repository config (direct or through
  an include). Why: a `gitdir:` or `onbranch:` condition can hold in a git child
  and not where the engine vets the config; refusing the key closes the class
  for any future child, at the cost of asking the user to inline it.
- **Reset and cleanup never walk through a link.** The scrub holds an fd per
  level, makes each directory u+rwx with `_chmod_at` (Linux: an `O_PATH` fd
  changed through `/proc/self/fd`; macOS: `fchmodat(AT_SYMLINK_NOFOLLOW)`) and
  opens it through its parent's fd with `O_NOFOLLOW`; tree removal uses `fwalk`
  and `rmtree(dir_fd=...)`. Why (reproduced: the reset made an outside directory
  0777): on macOS a `setsid` grandchild survives its run (no PID namespace) and
  could swap a listed directory for a link between the check and the path-based
  chmod and scan, so the unsandboxed engine changed modes and deleted `.git`
  directories and sockets outside the worktree. A directory swapped for a link
  is now `RepoTamperedError`. `_chmod_at` exists because a non-root user cannot
  open a mode-000 directory (CI failed on the first fd version; the root
  container hid it).
- **The older live editor test runs only under exactly `-m live`.** Why: its
  substring guard selected it for `-m "not alive"`. The Stage A suite in
  `tests/live` evaluates the marker expression properly.
- **Below the review bar, kept in mind:** `Settings` reads `.env` from the
  current directory, so the Step 4 CLI must not start from inside the target
  repository (see Known gaps).

### 2026-10-22 (Step 2, wave 2b review fixes)

- **A failed privilege drop is never silent**: the workload drops every
  capability before exec in every isolation mode. If the drop fails, a
  `required` mode refuses the run and `best_effort` records isolation as not
  applied. Before this, a gap between modes let the workload forge the report.
- **Each run gets its own SysV IPC namespace**: shared-memory segments survive
  between runs otherwise, so a warm-up could leave a memoised answer for the
  timed runs.
- **`NETWORK_ISOLATION=off` also drops the PID and IPC namespaces on Linux**: an
  open network is already a channel between runs, so the namespaces would not
  restore trust in the numbers, and they would make write confinement depend on
  user namespaces. Turning the network sandbox off weakens measurement
  integrity, and the docs say so.
- **Test-runner shadowing is checked under every import root, and recipe files
  are protected**: a trial adding `scripts/unittest.py` is rejected when
  `scripts` is on the test command's path, and `Makefile`, `*.mk`, `justfile`
  and `.coveragerc` are protected because a test command reads them.
- **The test suite's pass mark will come from the runner's own summary, not its
  exit code** (lands with the measurement unit): a suite that exits 0 after
  running fewer tests than the baseline does not pass.

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
  with a private loopback, a seccomp filter that blocks `socket(AF_UNIX)` so a
  path-based unix socket to a host service cannot be reached (the namespace does
  not cover those), Landlock write confinement to the worktree and a scratch
  directory, a PID namespace so orphans die, and a per-run self-check that the
  isolation really applied (macOS: `sandbox-exec`, whose `(deny network*)`
  covers AF_UNIX `connect`, with the same checks). The engine runs Claude-edited
  code on the user's machine; a fresh HOME is not a sandbox.
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

## Live API testing plan and credit budget (decided 2026-10-23)

**Decision.** The user's Anthropic API credits ($200 a month, reset on the 24th;
the current window ends 2026-11-24, unused credit does not carry over) fund the
engine's live tests and dogfooding. They pay only for the engine's own API calls
made with that key (CI `live-smoke` job, `live` environment with required
reviewers), never for Claude Code sessions.

**Why.** The spec leaves several API facts unverified until "the live smoke test
confirms before Step 5" (risk 8: text editor tool version, the explicit
`fallbacks` body, the `role: system` notice shape), and the worst-case cost
estimate is deliberately conservative (risk 14) until real usage is measured.
Scripted replies prove the engine's logic; only live runs prove the contract
with the API and calibrate cost. Spending each window's credit on the step in
progress buys evidence that would otherwise wait for Step 5.

**Unit cost basis** (engine price table, `claude-opus-5-5`: $4 input, $20
output, $0.20 cache read per MTok; to be replaced by Stage A measurements):
understand about $0.15-0.20 per call (worst case about $0.30); one trial about
$0.30-0.60 (worst case about $6, always bounded by the run cap); Haiku triage
about $0.0001 per abstract.

### Window 1: 2026-10-23 to 2026-11-24 ($200)

| Stage                          | When               | Live work                                                                                                                                                                                   | Est. per run    | Runs | Est. total |
| ------------------------------ | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | ---- | ---------- |
| A. Step 2 gate, U21 live suite | this week          | contract checks (tool version, `fallbacks` body, system notice, `count_tokens`, structured output, cache hits), live understand on varied repos, live E2E on the fixture, live attack repos | $6-9 (cap $12)  | 3-4  | ~$30       |
| B. Cost calibration            | with A             | real usage replaces worst-case estimates; tighten `min_trial_budget_usd` and defaults                                                                                                       | $0              | -    | $0         |
| C. Step 3 research             | early to mid Nov   | Haiku arXiv triage, Opus claim/precondition extraction (about 50 papers), live matcher tests                                                                                                | $5-10 per batch | 3-4  | ~$30       |
| D. Weekly live regression      | weekly after merge | the Stage A suite, to catch API or model drift                                                                                                                                              | ~$8             | 4    | ~$32       |
| E. Early dogfood pilot         | Nov 15-23          | the engine through the factory (no CLI yet) on 2-3 small OSS Python repos, real Claude trials                                                                                               | $10-15 (capped) | 4-6  | ~$60       |
| Reserve                        | -                  | re-runs after fixes                                                                                                                                                                         | -               | -    | ~$40       |

Total about $190. Stage E is the flex: around Nov 15, check the ledger and size
E to use what is left before the reset.

### Window 2: 2026-11-24 to 2026-12-24 ($200)

| Stage             | Live work                                                                   | Est. total |
| ----------------- | --------------------------------------------------------------------------- | ---------- |
| Step 4 interfaces | `--goal` English to objectives (small requests), live CLI runs              | ~$15       |
| Step 5 dogfood    | 10-15 OSS repo runs at $5-10 each, then the user's VLM bridge on the M4 Pro | ~$120      |
| Weekly regression | as D                                                                        | ~$32       |
| Reserve           | -                                                                           | ~$30       |

### Guardrails

- Every live test carries its own hard cap and the suite one overall; the
  engine's pre-send check refuses any request whose worst case would pass the
  cap.
- Each CI live run writes its real cost to the job summary; the ledger below is
  updated after every run.
- No live run without the user's approval in the `live` environment.
- Recommended backstop: a $200 monthly spend limit on the key's workspace in the
  Anthropic console.
- Live tests never run from a Claude Code container; the engine ignores the
  container's `ANTHROPIC_BASE_URL`.

### Live spend ledger

| Date       | Window | Run                                                                                        | Stage | Cost (USD) | Notes                                                                                                                                                                                                                                                                                                                                              |
| ---------- | ------ | ------------------------------------------------------------------------------------------ | ----- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-10-23 | 1      | [39939504871](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/39939504871) | A     | 0.00       | Key refused: HTTP 401 `authentication_error` on every request but one HTTP 400 (reason not kept then); 9 failed, 2 passed. Found and fixed: the E2E and attack tests passed with no API answer (now `check_answered`), the cache test's cap was below its byte-bound worst case, error replies kept only the status (now named in the cost table). |

## Next: finish Step 2, then Step 3

Step 2's build list is done: real baseline and trial runners in git worktrees
(argv, warm-ups, N >= 5 timed runs, peak RSS, output fingerprints, timeouts,
network off), the understand node under the cost cap, Claude trial edits with
the diff captured by git, combine with a re-test, delivery to a real
`engine/run-<id>` branch, the Postgres repository, the E2E fixture in CI, and
the judged-trials key question (closed by decision 35). Left:

- [x] Verifier, stage gate, `/security-review`, U21 live suite (2026-10-23).
- [ ] First live-smoke run and its ledger row, the macOS job blocking, the Step
      2 report, development-log row, PR ready.

### Known gaps carried to later steps

- **Multiprocessing `spawn`/`forkserver` fail in the Linux sandbox.** The
  seccomp filter that closes path-based AF_UNIX egress refuses every
  `socket(AF_UNIX)`, and those start methods need an AF_UNIX listener; `fork`
  (socketpair-based) works. Python 3.14 makes `forkserver` the Linux default, so
  a 3.14 workload using multiprocessing fails at baseline. Follow-up: allow
  AF_UNIX sockets bound inside the worktree or scratch dir only (Landlock scoped
  unix sockets where the kernel has them, else a connect/bind filter), so local
  IPC works and host sockets stay unreachable. Owner: Step 4 (runner).
- **Runner notes reach the live stream only.** `RunNotes` emits them as
  `runner_note` events, but they are not appended to `state["events"]` or the
  audit row. Step 4's CLI live log is the place to keep them.
- **`EditResult` has no notes**, so the editor's fallback and unpriced-model
  notes are not surfaced.
- **Profiler shadowing:** a repository module named like a stdlib module the
  profiler shim imports (`json.py`, `runpy.py`, ...) leaves that workload "not
  profiled", and its editable-install check does not run (the note says so).
- **`Settings` reads `.env` from the current directory.** A `.env` inside the
  target repository could set `ENGINE_API_BASE_URL` if the engine were started
  there. Today there is no CLI; the Step 4 CLI must read settings from its own
  location or the user's config dir, never the target's working directory.
- **A context serves one run at a time**: connect rebinds the runners of the
  context `build_context` returned.
- **A resume on a context with other isolation modes** re-tests the combination
  with those modes while the report shows connect's. The `Combiner` protocol
  does not expose its modes yet; Step 4's resume should refuse the mismatch.
- **A trial over its budget is charged exactly the budget**; the overrun the
  editor reported is in the trial's error text, not the run total (the estimate
  is a bound, so this only happens if the API bills above it).
- **The run-id claim is per process** (`Orchestrator` with the in-memory
  checkpointer); `PostgresSaver` resume (Step 4) needs it in the database.
- From the spec, deferred by design: research and LLM-generated candidates (Step
  3); the CLI, `--max-cost`/`--goal`/`--test-command`, test-command inference,
  the live log, hardware detection, `PostgresSaver` resume and a `clean` command
  for trial refs (Step 4); M4 dogfood, submodules, LFS, held-out inputs,
  `Workload.inputs`, `metrics_file`, process-tree RSS and a per-run tmpfs for
  `/dev/shm` (Step 5); PR creation and package installs (later).

---

## Metrics Snapshot (2026-10-22)

| Metric                         | Value                                                                                      |
| ------------------------------ | ------------------------------------------------------------------------------------------ |
| Python tests                   | 3,363 passed, 3 skipped (macOS-only or root-only)                                          |
| Python coverage                | 100% of 7,297 statements and 2,000 branches (placeholders excluded)                        |
| TypeScript tests               | 33 passed                                                                                  |
| Product code (non-placeholder) | ~16,000 lines Python in `src` + ~930 lines SQL; ~44,000 lines of tests (fixtures excluded) |
| Engine features shipped        | The full loop on CPU Python workloads; research and CLI not yet                            |

---

## Delivery Metrics (DORA-style, per step)

| Step | Lead time                     | CI-red pushes                                                                                | Rework commits        | Reverts |
| ---- | ----------------------------- | -------------------------------------------------------------------------------------------- | --------------------- | ------- |
| 0    | ~2 h                          | 0                                                                                            | 0                     | 0       |
| 1    | ~4.5 h                        | 2 (GHA cache; README format)                                                                 | 6 (regroup, 5 review) | 0       |
| 2    | ~23.5 h so far (gate pending) | 1 (Python 3.10 on the runner, `dbec415`); the non-blocking macOS job failed once (`7e8a4b5`) | 10 `fix` commits      | 0       |

## Lessons (retro per step)

### Step 2

- **Real runners find what local runs cannot.** CI's runner had Python 3.10,
  whose missing `-P` broke a profiler test (`cd0a3e6`), and the first macOS run
  found that `killpg` answers EPERM there once the group has exited (`ecb24aa`).
  Install the CI interpreters locally and push early to every platform job.
- **Do not assume the environment is set up.** In this cloud container the
  environment setup script had not run (the Lead's observation), so Postgres and
  the old interpreters had to be installed by hand, and a missing one only skips
  locally. Check `pg_isready` and `python3.8 --version` before relying on a
  green local suite.
- **Reviewers on a different model found real defects in every unit they
  reviewed**, security bugs among them: report forgery through `/proc` in the
  launcher, test-runner shadowing with an added `unittest.py`, the API address
  following a stray `ANTHROPIC_BASE_URL`, planted links reaching git's worktree
  removal, an ungated paid key in CI. Keep two lenses (correctness, security) on
  every unit.
- **A review that returns nothing must halt the workflow.** A reviewer that died
  returned null, which read as "no findings" and skipped the fixer;
  `build-wave.workflow` now stops the unit and names the missing lens
  (`80c1a8d`).
- **Write the decisions down where they will survive.** The spec and the Lead
  notes lived in `.claude/handoff/`, which is deleted before merge; the
  Decisions section above now carries them.

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
- `StubTrialRunner._unit_for` labels `throughput_per_s` as seconds; the real
  runner never produces that metric.
- Both pgvector and Qdrant are configured. Pick one when embeddings land (Step
  3).
- `services/python_agents/Dockerfile` installs with pip while CI uses uv.
- Local development may run on Python 3.13 while CI pins 3.11.
- Source modules above the ~400-line cap (lines on 2026-10-22): `nodes.py`
  1,728, `preflight.py` 1,003, `git.py` 843, `models.py` 760, `launcher.py` 709,
  `judges.py` 682, `anticheat.py` 675, `procrun.py` 664, `understand.py` 661,
  `measure.py` 605, `trial_runner.py` 575, `editor_tools.py` 550, `editor.py`
  524, `profiler.py` 511, `transport.py` 491, `postgres.py` 430, `fakes.py` 402.
  Split when a later step touches them.
- The report's trial-ref cleanup command pipes into
  `xargs -n1 git update-ref -d`; run with nothing left to delete, GNU `xargs`
  still calls `git update-ref -d` once and it prints its usage. The README's
  `update-ref --stdin` form is a no-op then, and deletes in one transaction.

---

## Useful Commands

```bash
pnpm stage-gate                               # full gate
pnpm stage-gate:quick                         # quality only
cd services/python_agents && uv run pytest    # Python tests
pnpm test                                     # TypeScript tests
docker compose -f docker-compose.dev.yml up -d
```
