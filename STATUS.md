# Project Status - Autonomous AI Platform

**Last Updated:** 2026-10-25

---

## Current Step

**Build step:** 3 (wired discovery, engine self-retry, review delivery, quality
check, noise rule). Wave 1 is built and committed (27 units, E2E U14 and U26
included); next are the live runs L0 to L2. Step 2 is merged (PR
[#12](https://github.com/Pkanna10/autonomous-ai-platform/pull/12)); the Window 0
live experiments are closed out on PR
[#21](https://github.com/Pkanna10/autonomous-ai-platform/pull/21). **Branch:**
`claude/step3-research` (draft PR
[#22](https://github.com/Pkanna10/autonomous-ai-platform/pull/22)); the spec
(revision 4, approved by the owner) is `.claude/handoff/step3/spec.md`.
**Vision:** a self-improving optimization engine that uses research findings and
novel ideas to provably improve existing code, or build something new and then
improve it (see `CLAUDE.md`).

### Resume here (handoff, 2026-10-25)

A new session picks up from this section. Everything it needs is in the repo;
nothing lives only in an old session. The Step 2 spec, Lead notes, research
notes and Window 0 plan lived in `.claude/handoff/step2/` until the close-out;
their decisions, accepted trade-offs and verified facts are in "Decisions",
"Known gaps" and "Next" below, and the files themselves stay readable in git
history at `5ce95a4` (`git show 5ce95a4:.claude/handoff/step2/spec.md`).

- **Step 2 is complete**: PR #12 merged into `master` on 2026-10-24 as `311212b`
  (a merge commit); CI on `master` green (run 40072834645, all 11 jobs). See
  "Step 2 summary" and the close-out report under it.
- **Window 0 is closed out** (2026-10-25): every live experiment, its cost,
  models, tokens and the decision it fed are in "Experiment register (Window 0)"
  and the ledger under "Live API testing plan"; read the register before
  planning a live run, so the next one adds to it instead of repeating it.
- **Step 3, Wave 1 is built and committed** on `claude/step3-research`
  (2026-10-25; see "Step 3 Wave 1 summary"). The owner approved the spec
  (revision 4, `.claude/handoff/step3/spec.md`) on 2026-10-24, with the
  decisions in `.claude/handoff/step3/owner-step3-review.md`. Units and commits:
  U1 `3ee4e76`, U2 `427fdbe`, U3 `7eaa3b2`, U4 `6342eca`, U5 `b67130a`, U6
  `183c538`, U7 `806b87d`, U8 `373d4c2`, U9 `753a158`, U10 `04088f7`, U11a
  `b848717`, U11 `60cee15`, U12 `6b3db0c`, U13 `08ba4ec`, U16 `4ac8798`, U17
  `34b1360`, U18 `82e93c5`, U19 `1d05562`, U20 `414f03b`, U21 `6ebd118`, U22
  `65891ea`, U23 `e27aed6`, U24 `1285820`, U25 `ce937d4`, U27 `a78275a` (Lead-
  assigned, see Lessons); Lead fixes `f1080dc` (macOS interpreters) and
  `3e04294` (graphwalk size).
- **E2E done:** U14 (`de34b18`, `tests/e2e/test_step3.py`, E3-A to E3-E, 8
  tests, about 3.5 min serially; its frame lines are version-independent, the
  review checked 3.11) and U26 (`1c64bea`, `tests/e2e/test_step3_quality.py`,
  E3-F to E3-I, 6 tests, about 4 min; E3-I runs on a synthetic clock, so its
  verdicts are exact). U15's docs are `5acdfeb`; `46aed4b` formats U14's fixture
  (CI Lint Code was red on `de34b18`: the Lead's gate now also runs prettier).
- **Live runs so far (2026-10-25, $6.75):** L0 passed (0 of 130 single-look
  false wins, floors 2.0-5.9 %); L1a (hard, `wired`) 10/10 delivered and 10/10
  at the reference gain on its re-run, every guard held; L1b (corpus, `wired`)
  12/12 slowdowns delivered at the reference gain, 0/3 controls; the ledger has
  the detail. Timeouts re-pinned from them: hard 90, corpus 120 (OSS keeps 300
  until L2a measures it).
- **L2a delivered 8 of 20** (`oss`, `wired`, Sonnet low editor; rep 1 2/10, rep
  2 6/10, 5.94 USD), below W5's 10 of 20: the editor default stays Opus.
- **L2b delivered 7 of 10** (Opus editor, same rule, 5.46 USD): Opus stays the
  editor default. Wave 1's live runs are done; next is the Wave 1 report.
  **Open:** on the L1a re-run `eventagg` delivered 30.9 % (one kept idea) while
  its best trial measured 92.3 % on peak RSS; the first L1a run kept that
  streaming idea at 92.3 %. Read the run's results artifact (the confirmation or
  the combine dropped it) before the Wave 1 report.
- **Wave 2 is approved** (O6: hard corpus v2, the `ledgerclose` rebuild, the A/B
  instrument, grader labels, L3-L5). **Wave 3 is held** until Wave 1's live runs
  report (O6); each of its units has its own gate (spec section 7).
- **Credit:** Window 1's $200 expires 2026-11-25; plan to have it used by
  2026-11-23 (the owner's buffer).
- **Environment:** the database tests need Postgres 16 with pgvector and a role
  that may create databases (`TEST_DATABASE_URL`; the Docker Compose database
  works). The profiler and retry-template tests also run `python3.8` to
  `python3.14` (`uv python install 3.8 3.9 3.10 3.11 3.12 3.13 3.14` puts them
  in `~/.local/bin`); a missing one skips locally but fails CI (U3, `f1080dc`).
  Check both before a long run; do not assume an environment setup script ran.
  In the Lead's container the `ledgerclose` partial-fix guard fails (see Known
  gaps); CI is the reference.
- **How a unit was built in Step 2:** the Workflow tool ran one unit per run
  (Builder tests first, correctness and security Reviewers on a different model,
  fixer; a missing review halts the run); the script is
  `.claude/handoff/step2/build-wave.workflow` at `5ce95a4`. The Lead verifies,
  commits one unit per commit and pushes. In Step 3 up to four Builders shared
  the worktree on disjoint files, under the builder rules in the session
  scratchpad; the hygiene they learned is in CLAUDE.md ("Builders in a shared
  worktree") and the Step 3 Wave 1 lessons below.
- **Lead verification before every commit** (from `services/python_agents`):
  `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests`,
  `uv run bandit -q -r src -c pyproject.toml`,
  `TEST_DATABASE_URL=postgresql://dev:devpass@localhost:5432/postgres uv run pytest -q`
  (coverage gate 90 %; 100 % line and branch with Postgres), and the suite on a
  Python 3.11 venv with `-o addopts="-n auto --no-cov -m 'not live'"`. The
  Lead's gate runs alone on a clean copy of the branch: it is the authority for
  timing guards, which concurrent Builders' gates are not.
- **Never run live tests from a container**: always pass `-m "not live"` when
  overriding `addopts`. Live suites run only in CI's `live-smoke` job. Cloud
  containers set `ANTHROPIC_BASE_URL` for their own use; the engine follows only
  `ENGINE_API_BASE_URL`.

---

## Development Log

One row per build step. "Gate" is the result of `pnpm stage-gate` at the end of
the step.

| Step | Deliverable                                                               | Planned    | Started    | Completed  | PR                                                                | Gate   |
| ---- | ------------------------------------------------------------------------- | ---------- | ---------- | ---------- | ----------------------------------------------------------------- | ------ |
| 0    | Repair & upgrade (DB init, deps, models, docs, stage gate)                | 2026-10-21 | 2026-10-21 | 2026-10-21 | [#11](https://github.com/Pkanna10/autonomous-ai-platform/pull/11) | passed |
| 1    | Engine design (typed state, data model, judges, migration 003)            | 2026-10-21 | 2026-10-21 | 2026-10-21 | [#11](https://github.com/Pkanna10/autonomous-ai-platform/pull/11) | passed |
| 2    | Core loop end to end on CPU Python workloads + E2E fixture test           | 2026-10-21 | 2026-10-21 | 2026-10-24 | [#12](https://github.com/Pkanna10/autonomous-ai-platform/pull/12) | passed |
| W0   | Window 0 live experiments (discovery, A/B, noise, evolution, heal, build) | 2026-10-23 | 2026-10-23 | 2026-10-25 | [#21](https://github.com/Pkanna10/autonomous-ai-platform/pull/21) | passed |
| 3    | Discovery and proof: generator, retry, review branch, quality, noise rule | 2026-10-24 | 2026-10-24 |            | [#22](https://github.com/Pkanna10/autonomous-ai-platform/pull/22) |        |
| 3c   | Self-healing of the user's code (designed in the Step 3 spec; before 3b)  |            |            |            |                                                                   |        |
| 3b   | Capability acquisition: automatic package policy (designed in Step 3)     |            |            |            |                                                                   |        |
| 4    | Interfaces + runner: live CLI, hardware detection, `--goal`               |            |            |            |                                                                   |        |
| 5    | Dogfood: fixtures, OSS repos, real ML training pipeline                   |            |            |            |                                                                   |        |
| 6    | Production loop: error monitoring into the healer, gradual rollout        |            |            |            |                                                                   |        |

Step 3 in full (O1, CLAUDE.md build order): the generator wired, the engine
self-retry, review delivery, the quality check and the noise rule (Wave 1); hard
corpus v2 and the retrieval re-test (Wave 2); lessons and evolution (Wave 3,
gated); paper intake conditional. Wave 1 was built on 2026-10-25 (U1 on
2026-10-24) on draft PR #22; its E2E and live runs are next, so the row has no
completion date or gate yet. 3c (D33-D34) and 3b (D27-D32) are designed in the
Step 3 spec and built after it, 3c first (O5).

Recommended Claude Code model and effort per step: 0 Opus 5.5 High; 1 Fable 5.1
Extra; 2-4 and 3b Opus 5.5 Ultracode; 3c, 5 and 6 Opus 5.5 High (Fable 5.1 Max
only when stuck). In Step 3 every unit's Reviewer ran on Fable 5.1, a different
model from the Opus 5.5 Builders.

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

### Step 2 summary (2026-10-21 to 2026-10-24, closed out)

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

#### Step 2 report (close-out, 2026-10-24)

**What was built:** the core loop above (U1-U21), then three things around it:

1. a Verifier with three rounds, including an attack round;
2. the Stage A live suite;
3. Window 0, a set of live experiments on the expiring credit. It includes a
   benchmark corpus (12 slowdowns, 3 controls, 3 attack repos), a hard corpus
   (10 repos) and an OSS corpus (10 pinned real repos), plus raw-SDK experiments
   (probes, triage, papers, web, pre-screen) and the discovery suites (sweep,
   A/B, escalation).

**Evidence:**

- **Stage gate:** passed on `9db3c77`, with 4,839 passed and 0 failed. CI is
  green on the same code, including Postgres and the blocking macOS job.
- **Security reviews:** two `/security-review` passes. The 2026-10-23 pass had
  two findings, both fixed. The 2026-10-24 pass found nothing.
- **Live results:**
  - every live suite passed with every guard held except triage (E2), which
    never ran because arXiv answers 429 to GitHub runners; no attack got
    through;
  - benchmark slowdowns: 12/12 won, with Opus or Sonnet as editor;
  - hard corpus, blind: 10/10;
  - OSS corpus: 6/10 delivered, with gains of 3-14 %;
  - blind discovery: hit@5 of 95-100 % on the 22 slowdowns.
- **Spend:** about 20 USD of live API use before the A/B (ledger above). Per-run
  costs came in at 2-8 % of their worst-case caps.

**Before / after:** before Step 2, every measurement and edit was a stub. After
it, a caller-supplied hypothesis is edited by Claude in a sandbox, measured
against noise, judged, combined, re-tested and delivered as a branch. All of
that runs on real code under a hard cost cap.

**What Step 3 needs** (see Next and Known gaps):

- wire the generator and matcher into the hypotheses node, and resolve the
  non-UUID id gap on Postgres;
- the engine's own bounded retry;
- a discovery measure that does not saturate (hard corpus v2, the `ledgerclose`
  rebuild, a grader validated against hand labels);
- the paper pipeline's priority, set by the A/B (E5) result;
- the 3b and 3c designs, with the user's three integrity rules.

### Step 3 Wave 1 summary (2026-10-24 to 2026-10-25, built; E2E and live runs next)

A run built by the factory no longer needs a hypothesis handed over, a fixable
crash gets one second chance, a change that alters behaviour or output goes to
its own review branch, the output check is on by default, an output change can
be judged by a quality number the user confirmed, and every gain is measured
alternately, against a per-project floor, and confirmed on a second look. No
paper code is built (D1: the A/B result); the playbook matcher is built and off.

```
define      exact (output_equivalence, the default) | quality (quality:<name>
            bound, frozen files protected, read-denied, masked); never both
baseline    + 3 A/A blocks -> floor = max(2 %, 2 x largest wall-time gap);
            quality scored twice on the base output (determinism)
research    blind (default: no request) | matched (off): one matcher request
hypotheses  caller ideas first, then the pool; Sonnet 5.5 generator when the
            pool is dry (<= 2 calls, a trial's reserve kept, <= 25 % of the
            cap); novel ideas parked
trials      worktree + base twin, ABBA; one fenced, closure-checked fix retry a
            run; quality mode: added lines naming a frozen file are rejected
verdicts    rule 6: output changed or behaviour -> review; novel -> approval;
            every would-be keep or review confirmed on a fresh paired re-test
deliver     confirmed keeps -> engine/run-<id>; review set re-tested ->
            engine/review-<id>; neither pushed; D42 gain lines, D38 labels
```

By layer, with the commits (all on `claude/step3-research`):

- **Foundations:** caller ids in lessons, trials and verdicts, migration 005
  (`3ee4e76`, U1); contracts for discovery and retry (`427fdbe`, U2) and for the
  quality check and noise calibration (`34b1360`, U17); migration 006, a lesson
  may record `review` (`b848717`, U11a, pulled forward from U11).
- **CI:** pip-audit in the Python job and weekly over the whole lock,
  interpreters 3.8-3.14 (`7eaa3b2`, U3); the macOS job installs them too
  (`f1080dc`).
- **L6 optimization:** install and interpreter config protected (`b67130a`, U5,
  D23); generator and matcher adapters and `rank_generated` (`806b87d`, U7);
  rule 6, `output_changed` and absolute drops (`6ebd118`, U21); the
  `quality_data_reference` tripwire (`a78275a`, U27).
- **L5 execution:** crash parser and closure-checked feedback, 27 CPython
  templates for 3.8-3.14 (`6342eca`, U4); one fenced fix retry (`183c538`, U6);
  tolerant fingerprints, masking and ABBA order (`82e93c5`, U18); paired trials
  against a base twin and A/A calibration (`414f03b`, U20); the frozen quality
  scorer (`1d05562`, U19); scoring and masks in every runner, editor read-deny
  (`1285820`, U24).
- **L2 orchestrator:** generation when the pool runs dry (`373d4c2`, U8);
  matched retrieval, off (`753a158`, U9); the calibrated floor and paired
  judging (`65891ea`, U22); confirmation before keep (`e27aed6`, U23); review
  delivery and the Step 3 report (`60cee15`, U11); the factory wiring of roles,
  retry, noise and quality (`04088f7`, U10); define's two modes, the default
  output check and the quality freeze (`ce937d4`, U25); the per-run retry cap
  across resumes (`4ac8798`, U16).
- **Live plumbing and evals:** the offline discovery eval over a recorded seed
  (`6b3db0c`, U12); `LIVE_CORPUS_MODE=wired`, the `editor_model` input, a noise
  rule named per suite and the paired L0 path (`08ba4ec`, U13); graphwalk at
  170,000 nodes (`3e04294`).

**Evidence so far:** each unit was committed by the Lead after its review round,
with the findings fixed in the unit's own commit or recorded under Decisions and
Technical Debt below, and after the Lead's gate on a clean copy (ruff check and
format, mypy, pytest with Postgres at 100 % line and branch coverage; bandit and
pip-audit run in CI). Security-focused reviews are recorded for U4 (two: a
110-byte and a 24-byte channel closed), U5, U6, U10, U16 (one blocker, fixed),
U18, U19, U21, U24, U25 and U27 (two); U13's review focused on cost and caps. No
live run has used the Step 3 loop yet, so nothing here is a live result.

**Spend:** 18.15 USD of Window 1 in Step 3 Wave 1 (L0, L1a twice, L1b, L2a,
L2b).

**Not yet proven:** wired wins on the OSS corpus (L2a) and the noise rule's wall
time there. Proven since (2026-10-25): the E2E scenarios E3-A to E3-I; the
false-keep rate on the paired path (L0, 0 of 130); wired wins on the hard and
benchmark corpora (L1a, L1b) with every guard, including a real `GitCombiner`'s
confirmations and final combine in one run.

### Step 3 Wave 2 progress (2026-10-26 to 2026-10-30, building)

Built and committed one unit per commit, each after its Fable 5.1 review round
and the Lead's gate on a clean copy (ruff, format, mypy, bandit, pytest with
Postgres at 100 % under CPython 3.13 and 3.11, prettier):

- **Batch 1:** N1a `cc2d416` (contracts), V1 `6214f60` (corpus v2 part 1), V3
  `3068400`, V5 `d7ba9a7`.
- **Batch 2:** N1b `988430f` (code context S0), N0 `801f22c` (spawn delta, the
  `unparsable_source` label), V2 `4c6a050` (corpus v2 part 2: uncommon, small,
  decoys; 12 v2 repositories in all).
- **V9** `27e5e53` (O20): the upstream maintainer-fixes corpus, 30 sealed keys
  from 18 libraries, the CI-only `upstream-verify` marker and the `upstream`
  suite on CPython 3.12. The owner took both recommended defaults (O21): two
  medium keys are excluded from the scored pool and `mpmath-bin-to-radix-pow2`
  is an expected no-win control.
- **Agent pilots (O18):** A0 `80a1b8b` (P0, `agent-probes`: per-message effort,
  prompt-cache reuse, mid-conversation system messages, free token counting, an
  edited thinking block refused against a control turn, and a Managed Agents
  environment created and deleted with the 404 checked; the commit message's
  list of probes is wrong, this one is right), A1 `de65965` (P1, `heal-agent`),
  A2 `1bb075f` (P2, `research-agent`), A3 `d8c0699` (P3, `watch` and
  `watch-cleanup`). None has run live yet; P3 creates Managed Agents objects on
  the owner's account and its cleanup must be verified after each dispatch.
- **Batch 3:** N2 `a1ad5f2` (lane prompts, schema, grounding; about 940 source
  lines against a 400 row, mostly prompt text and the 18-example bank), N3a
  `a490001` (reviewer), N3b `99c0bfc` (portfolio), N0b `6482cd1` (one fix retry
  on `unparsable_source`), L4p `53abcc9` (the sweep covers corpus v1 + v2, 37
  repositories; `sweep-record` needs 24 USD).
- **Test fixtures changed, and why** (each measured several times first; no bar
  was loosened for a quiet machine):
  - `7b970bf` ledgerclose resized: CI measured its baseline at 0.27 s against a
    0.3 s floor.
  - `71940d0` decoy guard: the tempting idea's true gain is about 0 (four runs
    each: -2.5 to +4.2 %), so noise alone reached the 5 % bound; the bound is
    now max(5 %, twice the A/A gap measured in the same runs).
  - `a724611` reference-fix guard: three base runs then three fixed runs let one
    burst of load decide (tokenparse 22.8 % once, 34-66 % quietly); the copies
    now alternate and the best runs are compared, bar unchanged.
  - `2dd55cc` parcelindex: the full fix gains 40-47 %, the textbook idea -2 to
    +17 % (once 20.04 %) against a 0.20 bar; the bar is now 0.30. The other
    seven v2 repositories keep at least 0.18 of margin on both sides.
- **Assumptions:** Opus 5.5, Sonnet 5.5 and Fable 5.1 share a June 2026 training
  cutoff (platform.claude.com models overview, read 2026-10-26); V9's
  contamination tiers and O21 rest on it. The engine trains nothing: it calls
  Claude through the API only.
- **Merged from master:** `eb1566d` (pymupdf 2.0, PR #28, and the Dependabot
  Actions pins).
- **Live:** L3 0.07 USD (a smoke test under O19; L3b re-tests the grader).
- **Next:** batch 4 (N4a, the pipeline; N0c, the child-process tripwire), then
  batch 5 and the live order in the amendment's section 7 (L4 first).
- **Owner's plan, for the record (2026-10-30):** after Wave 2's idea experiments
  (E1/E2) report, an "Improvement Wave 3" pilot: a multi-model developer team
  that studies, proposes and proves engine improvements. The owner sends its
  brief then; nothing is built for it before.

---

## What Exists Today

| Component                                                                            | State                                              |
| ------------------------------------------------------------------------------------ | -------------------------------------------------- |
| Docker Compose: Postgres 16 + pgvector, Redis, Qdrant                                | Working                                            |
| Schema `001` to `006_review_outcome.sql`                                             | Working; applied in CI on every PR                 |
| CI: lint, typecheck, tests, coverage, Python CI (Linux, macOS), live smoke (manual)  | Working; the macOS job blocking                    |
| Security: OSV, Trivy, Docker Scout, pip-audit, bandit, safety, secret scan, Renovate | Working                                            |
| `packages/agent-core` Claude client + shutdown                                       | Working (33 Vitest tests)                          |
| `services/python_agents` settings                                                    | Working                                            |
| LangGraph orchestrator (`EngineState`, 15 nodes, router, `Orchestrator`, factory)    | Working on CPU Python workloads (Step 2)           |
| Preflight, understand, baseline, profiler, trial runner, editor, combine, publisher  | Working (Step 2)                                   |
| Data model, anti-cheating, judges, ranking, lessons, `PostgresRepository`            | Working (Steps 1 and 2)                            |
| `research/arxiv_monitor.py`, `pdf_parser.py`; the `watch` node                       | Placeholders / stub (paper intake conditional, D2) |
| `packages/research-engine`, `execution-engine`                                       | TypeScript placeholders                            |
| Step 3 Wave 1: generator wired, fix retry, review branch, quality check, noise rule  | Built; E2E in progress, no live run                |
| Research matcher (matched retrieval)                                                 | Built, off by default (D1)                         |
| CLI, live log, hardware detection, web console                                       | Not started                                        |

---

## Decisions

### 2026-10-30 (owner: V9's two medium keys and the mpmath control)

- **O21.** The owner took the Lead's recommended defaults for V9.
  `packaging-simple-version-fastpath` and `wcwidth-wcswidth-ascii` are excluded
  from the scored pool: both fixes were committed before the shared June 2026
  training cutoff and announced in their projects' release notes, so a hit may
  be recall, not discovery. They still run and are reported in their own row,
  "excluded by the owner". `mpmath-bin-to-radix-pow2` is a control, "no win
  expected": without `gmpy2` the radix change its fix speeds up is about 2 % of
  each conversion, so no fix of it can clear the 10 % floor, and a claimed win
  there is a warning that the measurement is fooled. No dependency is added.
  **Why:** a score should count only exams the attempter cannot have read the
  answer to, and a known-unwinnable exam is more useful as a false-win check
  than as a question. The scored pool is now 15 maintainer-set keys with no hint
  in the before-tree (`upstream.EXCLUDED`, `upstream.CONTROLS`,
  `upstream.report_pool`; the verify table and the live summary use the same
  rows).

### 2026-10-26 (owner: the idea pipeline joins Wave 2)

After the Wave 1 report and the research report "Novel speed up idea generation"
(how to make the engine propose bigger, less obvious speed-ups), the owner
decided:

- **O11.** The five-stage idea pipeline joins Step 3 Wave 2 as extra build
  units. The pipeline: the generator reads the hot code; an obvious lane;
  independent lens lanes built on idea-creation frameworks; a fresh-context
  reviewer that may only remove ideas; and a deterministic portfolio of 3-5
  non-obvious ideas.
- **O12.** More budget is fine: the discovery share (D7's 25 %) may rise to what
  the pipeline's worst-case pre-check needs (about 35-40 %).
- **O13.** About $120 of Window 1's remaining ~$182 goes to the staged
  experiments (E0 free checks; E1 idea-only probe across Sonnet, Opus and Fable;
  E2 the executed A/B on the 10 OSS libraries; E2c a compute-matched control;
  E3-E4 only if earlier gates pass), each with a pre-registered gate.

**Why:** today one Sonnet call writes five ideas without seeing the code, and
the engine stops at the first keep. The research found models repeat the same
ideas unless forced through independent angles; their own novelty ratings are
unreliable; and the systems with big wins coupled varied proposals to real
measurement. The judges, anti-cheating rules, output check, noise rule and the
single fix retry stay as they are. The spec amendment (D43 on) is drafted by the
design workflow and reviewed before any build.

### 2026-10-26 (owner: build V9, the upstream-fixes corpus)

- **O20.** The owner approved V9: a corpus of real performance fixes merged by
  open-source maintainers (the before-commit is the exam question, the
  maintainer's fix the sealed key, the project's tests the guard). Built in
  three separated roles under O19: a miner (Opus) that seals the keys and
  prefers commits after the models' training cutoffs (each candidate records its
  contamination risk, since an attempter may have seen a famous fix in
  training); a benchmark writer of a different model (Fable 5.1) that sees only
  the before-code and the touched paths, never the fix or the message; and a CI
  verification job with no API calls that keeps only candidates whose maintainer
  fix measurably speeds up the benchmark. The engine's copy of a repository
  holds no later history. _Correction (V9 review, 2026-10-30):_ the benchmark
  writer also saw the miner's ids (`idna-uts46-ascii-fastpath`), which name each
  fix's idea, so V9b was blind to the diff, not to the idea; its first
  docstrings also named the touched private functions and files, which the clone
  would have carried to the attempter. The docstrings were rewritten to name the
  library, the public calls and the input shape only (a guard fails on any
  touched file or private function name in a copied workload), the coverage
  notes moved to `tests/fixtures/upstream_corpus/_notes/workloads.md` beside the
  keys, the workloads whose input never reached the shape the key speeds up were
  resized against the before-trees, and the workloads' README lists the
  candidates whose id names the idea so that their live hits are reported
  separately. `mpmath-bin-to-radix-pow2` is a control unless the job installs
  `gmpy2` (README).

### 2026-10-26 (owner: the setter, attempter and marker are kept apart)

- **O19.** No result counts if the same context set the exam and sat it
  (`CLAUDE.md` 4.5.0, Development Workflow). Every test set, label file, corpus,
  pilot and live experiment names its setter (independent; human material where
  possible; tiered up to adversarial cases; keys sealed before any attempt), its
  attempter (sees only what a real run sees) and its marker (deterministic where
  possible, else a different model, a second marker on disagreement and an owner
  spot-check).

**The Lead's audit of results so far, under O19:**

| Result                     | Setter                                                            | Attempter                     | Marker                                      | Standing                                                                                         |
| -------------------------- | ----------------------------------------------------------------- | ----------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| L3 grader 12/12            | An Opus builder holding the answer key wrote hits and near misses | Opus 4.8, blind to the labels | Exact label match                           | Smoke test: the grader is not broken; not evidence it judges real, vaguer ideas. L3b re-tests it |
| L1a hard 10/10, L1b 12/12  | Claude wrote the programs and fixes                               | The engine (Claude)           | Frozen judges                               | Real wins on an easy exam: setter and attempter share an idiom, hence saturation                 |
| V1/V2 "hard v2" difficulty | Claude, who also rated its own difficulty                         | Not yet run                   | -                                           | Unproven until a blind attempter calibrates it and L5a runs                                      |
| L2a/L2b OSS 8/20, 7/10     | Human maintainers                                                 | The engine                    | Frozen judges                               | The honest exam (and the lowest score)                                                           |
| Builders' unit tests       | The builder                                                       | The builder's code            | A different-model reviewer, the Lead's gate | Partly independent; high-risk units add spec-only acceptance tests                               |
| Pilots P1, P2 (building)   | The pilot's builder writes the bugs and the pages                 | Live model, blind             | Deterministic tests                         | Builder sets count as regression only; an independent Fable setter writes the scored sets        |

**Added units (amendment section 7d):** L3b, the blind calibration of corpus v2,
and independent scored sets for P1 and P2; V9 (a corpus of real upstream
performance fixes) is proposed to the owner.

### 2026-10-26 (owner: agent pilots P0-P3 approved)

- **O18.** The owner approved the agent pilots P0-P3 from
  `.claude/handoff/step3/research-agents.md` (about $8-15 of Window 1; P1 with a
  third repetition about $17): P0 contract probes, P1 a heal agent against
  today's single heal request, P2 a quarantined research agent, P3 a Managed
  Agents deployment for the arXiv WATCH job on public data only. They run in the
  live experiment harness; the engine adopts no agent framework in Wave 2. Units
  A0-A3 are in the Wave 2 amendment (section 7c). P3 creates objects on the
  owner's account and deletes them; the Lead verifies the cleanup. The agent
  roadmap (own kernel at 3c, research agent later, Managed Agents only for
  public-data jobs) stays the Lead's recommendation until the 3c spec, informed
  by P0-P3.

### 2026-10-26 (Lead: four side investigations, no change to the plan)

The owner asked for read-only investigations beside the Wave 2 build; the
reports are in
`.claude/handoff/step3/research-{caching,advisor,batch,agents}.md`.

- **Prompt caching** (the Console's "hit rate is low, save up to 11 %" banner):
  the engine's caching is sound; most of the 11 % is input sent once, where
  caching costs more. About 5 % more is realistic, folded into the Wave 2
  amendment's D59 (no cache write on the leap, reviewer and auditor; E0b's gate
  fixed). Output tokens, not caching, are about half of every run: a lower
  editor effort with a high-effort retry on a judged failure is the larger
  lever, to be measured.
- **Advisor tool:** not adopted (breaks the pre-call worst case, encrypted
  advice, small measured effect); E2's Sonnet editor with the reviewer's Opus
  change plans tests the idea our way. D63's retention set gained Fable 5,
  Mythos 5 and Mythos 5.1 (`cc2d416`).
- **Batch API:** no use inside a run; about $3-4 of Wave 2 is batchable; adopt
  with WATCH. Two harness gaps are logged under "Known gaps".
- **Claude agents** (Managed Agents, the Agent SDK, the Messages-API building
  blocks): the engine's editor is already a bounded agent; agents may act only
  where a frozen check decides afterwards. Recommended: no framework in Wave 2;
  the engine's own agent kernel at Step 3c (two-phase healer); a quarantined
  research agent; Managed Agents only for a public-data WATCH pilot. Pilots
  P0-P3 (about $8-15) await the owner.

### 2026-10-26 (owner: the Wave 2 idea-pipeline build plan signed off)

The owner signed off the amendment `.claude/handoff/step3/spec-wave2-ideas.md`
(revision 2) and answered its open questions:

- **O14.** The build plan is approved in full: N0-N5 (N0b included), V7, V8 and
  the amended V4 and V6, interleaved with V1-V6 and L3-L5 in the amendment's
  five batches, then the staged experiments E0-E4.
- **O15.** Fable 5.1 (30-day retention) may see code only in the experiment arm
  on the public OSS libraries; the settings guard (D63) refuses Fable for any
  other project unless the owner enables it.
- **O16.** If E2 shows the pipeline wins, the owner decides on the STATUS entry
  whether `IDEA_PIPELINE` and `PORTFOLIO_ROUNDS` become product defaults (about
  $1.60-2.00 a run instead of $0.55).
- **O17.** The "more trials" branch (adopt `GENERATOR_N=10`,
  `PORTFOLIO_ROUNDS=2` for today's generator if E2c's control matches E2) is
  **not** pre-registered: the owner decides it after seeing the data. The Lead
  reports E2c's result with that caveat (a decision made after the data is open
  to fitting).

### 2026-10-25 (pre-registered before L5a: the retrieval re-test's pooled rule)

Recorded before any re-test run, as D2 and O3 require, so the decision cannot be
fitted to the result.

- **The rule.** Over the slowdowns of hard corpus v2 (L5b, both arms, 2
  repetitions) and the OSS set (L5c, both arms, 1 repetition, when it runs),
  pooled: `c - b >= 3`, where `c` counts tasks playbook-matched generation (arm
  B) won and blind generation (arm A) lost, and `b` the reverse; and B's false
  wins on controls do not exceed A's. **Met:** `RESEARCH_RETRIEVAL` flips to
  `matched` (W6) and paper intake becomes a conditional step (P) with its own
  briefing and approval. **Not met:** the playbook stays a test fixture and
  papers stay deprioritised, recorded here with the data.
- **The order, cheapest first.** L5a runs arm A alone on v2: if blind wins at
  least 90 % of the v2 slowdowns, v2 is saturated, it is revised and arm B is
  not paid for; L5a re-runs once on the revised v2, and a second saturation ends
  the re-test. L5c is skipped when its 10 tasks cannot change the pooled
  decision.
- **Why a re-test at all:** E5 ran where blind generation won 44/44, so it could
  detect harm, not help (Window 0 lessons). The Window 0 close-out proposed
  dropping L5 (`0cdfb7a`, above); spec revision 4 came after it and keeps L5,
  and the owner approved Wave 2 with it (O6).

### 2026-10-25 (Step 3 Wave 1: Lead decisions and accepted trade-offs)

From the per-unit reviews and the Lead's handoff notes (session scratchpad, not
kept). The ones that changed the spec are in its D12, D37, D39 and D41; where a
decision changed the spec, the code follows the decision.

**Defaults and modes**

- **The `Settings` defaults are the product's; "defaults = Step 2" applies to
  constructor and `NodeContext` defaults.** `PAIRED_TRIALS` and
  `CONFIRM_WINNERS` are on, `NOISE_CALIBRATION_BLOCKS` is 3,
  `DEFAULT_OUTPUT_CHECK` is on and both retry caps are 1, read only by the
  factory; every `NodeContext`, constructor, model and serde default reproduces
  Step 2. `tests/e2e/test_step2.py` and the offline evolution guard pin Step 2's
  settings in their own fixtures (U10). Why: the owner chose what a real run
  does (O8-O10), while the Step 2 tests prove Step 2's behaviour and must keep
  proving it; a test that inherits a moved default silently changes meaning. The
  evolution guard showed why: an A/A calibration of a millisecond workload on a
  loaded host gave a 110 % floor, which stops the run by design.
- **Every live suite names its noise rule** (U13, `ci.yml`): the Step 3 rule for
  `noise`, `corpus`, `hard` and `oss`, Step 2's for the rest. Why: the same
  reason, and calibration needs workloads well above timer noise (about 0.3 s or
  more), which not every older suite's fixtures have. L0 is the noise suite; L1
  and L2 run under the rule they will ship with.
- **Behaviour -> review is unconditional** (U11 deleted U21's `review_behaviour`
  staging keyword instead of leaving it dead; the Step 2 approval tests moved to
  a `novel` H4). Why: with the keyword off, generated behaviour ideas (D9) would
  have stopped unattended runs at the approval gate. Ordering rule (U21 review):
  no live run and no PR marked ready before this landed; met at `60cee15`.
- **An approved `novel` change whose output changed goes to the review set,
  never the run branch**, with or without a combiner (Lead, U11 review S6). Why:
  D35 keeps every output change off `engine/run-<id>`; the human approved the
  idea, not an output change nobody has looked at.
- **define refuses a caller's own `quality:` bound and both modes together;
  trials refuse a resume whose context lacks the defining check** (U25 security
  review S1). Accepted risk: a run defined without a check but resumed with
  `ctx.quality` set is not refused. Why accepted: that direction is stricter
  (the frozen paths are read-denied to the editor, and no quality guardrail is
  judged, so the run's own output check still decides).

**Retry**

- **Spent retries are counted as the larger of the checkpointed trials' sum and
  the repository's (`list_trials`)**; an unreadable repository grants 0 with a
  warning naming only the error type; a re-run trial never lowers a saved
  trial's `attempts` (U16; the security review's blocker B1: deterministic trial
  ids let a re-run round overwrite the saved attempts, which granted a second
  retry). Why: the owner's rule is exactly one second chance per run (O8), so a
  crash inside the trials node must not regrant it.
- **U16 residual, accepted** (spec D12): a trial lost after its retry request
  (an engine error or a failed save) is not recorded, so resuming such a failed
  run straight through the graph could grant one more retry. Why accepted:
  `Orchestrator` refuses to resume a failed run, so no path reaches it today;
  Step 4's resume must record the grant durably first (Technical Debt).
- **What a retry may carry:** `EditTask.feedback` is the rendered
  `TrialFeedback.render()` string (the type allows nothing else); the hypothesis
  sits inside the `untrusted_repo_content` fence (D11), and text that plants or
  closes a `<hypothesis>` element is refused unsent (U6 review S1).
  `Trial.retry_notes` holds stderr-derived text and is for the report only:
  never a prompt, a lesson or the generator. Why: D13's closure proof covers
  only what `classify` sends.
- **A `GitError` from the retry's reset ("still dirty") loses attempt 1's
  record** through the exception path. Accepted: consistent with spec section
  4.4 item 4, and the trial fails either way.

**Quality check**

- **Frozen paths are literal names** (U17): no `*`, `?`, `[`, control
  characters, leading `-` or git metadata; consumers `glob.escape` them anyway.
  Why: they feed the protected and read-deny lists, which match patterns, so a
  metacharacter would protect or hide something other than the file the user
  named.
- **The external scorer runs as `<python> -s -B <copy>/<script>`**, `scorer[0]`
  a Python interpreter by name or path, with cwd and `sys.path[0]` the frozen
  copy; not `-E` (U19 security review). Why: `-E` would ignore the forced
  `PYTHONHASHSEED=0`, so a scorer that iterates a set could score differently
  run to run; `child_env` already drops every other `PYTHON*` name.
- **Freeze refuses symlinks and other non-regular blobs** (U19). Why: a symlink
  blob would freeze the link text and leave the real file unprotected.
- **Runs that agree within a tolerance keep the first timed run's bytes for
  scoring** (`raw_fingerprint=None`, scored uncached; U18 review). Why: one
  score per measurement, and the cache is keyed by exact bytes, so only a
  byte-identical output reuses a score.
- **`measure.launch` masks by default; only the test suite opts out** (U18), and
  the profile run is masked too (U24). Why: a launch path added later cannot
  forget the mask.
- **`=` joins D39's delimiters** (U18). Why: `name=value` metric lines then get
  the float tolerance.
- **The unordered-lines sentence is "line order ignored, except an unterminated
  last line"** (U18, U11). Why: the unterminated last piece stays last so the
  canonical form stays injective, and the report must not claim more.
- **The editor's read-deny is case-insensitive and NFC-normalised** (U24
  security review S1). Why: APFS treats `Labels.csv` and an NFD spelling as the
  same file; denying the variant on Linux too errs on the safe side.
- **The tripwire's limits** (U27, two security reviews): added lines naming a
  frozen basename as a whole token (case- and NFC-folded) reject the trial; a
  binary patch counts as naming it and a git error fails the trial (both
  closed). F2 is a documented limit, not fixed: a kept line whose neighbours are
  edited is context in git's `-U0` patch and is not flagged. Why: `-U1` would
  flag every unchanged line next to an edit and reject honest trials; the review
  branch's diff is the backstop. It over-flags any added mention, comments
  included; accepted as the safe side and stated in the README.
- **Residual, accepted (U19 security review N4):** with `NETWORK_ISOLATION=off`
  there is no PID namespace, so a `setsid` workload child can outlive
  `kill_group` and read the `<run>/quality` labels while a scoring runs. Why
  accepted: the copy exists only during scoring, `off` is already documented as
  weaker evidence, and every output change goes to review. Recorded here and in
  the README rather than in D37's text.
- **Deviation:** D38's "a builtin states its row count" is not met; the quality
  rows carry no `n` (U11). Backlog below.

**Noise rule**

- **A crash on the base twin is an `EngineError`** (U20 review, D41 a). Why: the
  twin runs the base code, so its crash is the host's or the program's, never
  the hypothesis's, and must not become a rejection or a lesson.
- **Calibration measures wall time only; a calibrated run's `cpu_time_s` gets at
  least 2 %; throughput is not raised** (U20, U22). Why: CPU time at tick
  granularity would inflate the floor; a user's own CPU-time objective relies on
  the 2 % minimum.
- **The raised floor lives only in `Baseline.objectives`; `state["objectives"]`
  stays the user's** (U22). Why: the judges read the raised values from the
  baseline, and a report or resume still shows what the user asked. A
  block-count mismatch or a floor of 100 % or more stops the run at baseline
  ("no gain can be proven on this host").
- **A keep confirms only on a keep look; a review on a keep or review look**
  (U23). Why: a would-be keep whose second look sees an output change must not
  stand as a keep (D35), so D41 (b) is stricter than "keep or review".
- **No note when `CONFIRM_WINNERS` is off** (Step 2 byte-identical); the
  report's "Noise floor" line says "confirmation off" instead. D42's text says
  "better", not "faster", because memory can be the primary objective.
- **A confirmed keep's lesson carries D42's two-look mean** (U23 review N6, done
  in U11). Why: the first look won the selection, so its gain is biased upward.

**Discovery**

- **Research failures:** `LLMRequestError` and `LLMConfigError` are soft notes
  in the research node, which falls back to blind retrieval; `LLMConfigError` is
  fatal in the generator. Only `d <= cost` (D7) sets `discovery_exhausted` (U9).
  A matched success replaces the techniques with the matched cards only;
  `ctx.techniques` is the blind fallback.
- **The hypotheses node** (U8): no `needs_package` filter until 3b (`Hypothesis`
  has no packages field); an `EngineError` when generation is due and the
  objectives are empty ("define must run first"); the discovery delta keys
  appear only when the generator was consulted, so Step 2's expected keys hold.
  Noted for W1/W2: under D8's formula a keep lesson alone cannot lift idea 2
  above idea 1.
- **The OSS understand bound is 115,000 tokens** (U13): the prompt bound sat 70
  tokens under 114,000.

**Build and tests**

- **graphwalk runs 170,000 nodes, not 120,000** (`3e04294`). Why: its CI
  baseline was 0.296 s on `60cee15`, at the corpus guard's 0.30 s floor; the
  `list.pop(0)` BFS grows about with the square of the size, so 170,000 roughly
  doubles it, while the reference fix (a deque) stays fast.
- **The `textindex` hard-guard flake is left as is.** It failed only locally,
  under four concurrent Builders (load about 7 on 4 cores), where the min-of-3
  gain fell to 0.268 against the 0.3 bar; at load 3 it is 0.47-0.49, and it has
  never failed on CI. Why: the guard measures what it should; the host was
  overloaded, and the Lead's sequential gate and CI are the authority for timing
  guards.
- **Mutation claims are valid only on a scratch copy run with
  `-o pythonpath=<copy>/src` and a canary.** `pyproject.toml`'s
  `pythonpath = ["src"]` beats `PYTHONPATH`, so a `PYTHONPATH=<copy>` run tested
  the real `src`: the first U27 reviewer's "survived" list was invalid and was
  redone. The U19, U23 and U24 reviewers used mutation plugins or copies, so
  their claims stand. Why the canary: a mutation that must be killed proves the
  run imports the mutated code.
- **The noise suite came in with `master`** (merge `ec5ccbb`, PR #21), unchanged
  since `923c8c8`, instead of the import commit the spec planned (section 3.6).
  Why: PR #21 merged first, so a move commit would have duplicated it.
- **U11a was pulled forward** (`b848717`, migration 006 in batch 2), so `review`
  was storable before U21 could emit it.

- **Retrieval stays off by default; the paper pipeline is deprioritised** behind
  the playbook as a lesson-and-ranking source, lessons and evolution (E5: blind
  generation won 44/44, playbook-matched 41/44, b = 3, c = 0). Why: the
  pre-registered rule said so before the result was known; the result is not
  only null but slightly negative, since matched cards narrowed the generator
  onto a card's idea (eventagg, fleetsim) and lowered gains where both won.
  Paper cards would reach the generator the same way and are noisier.
- **What this does not show:** that retrieval cannot help. The benchmark and
  hard corpora saturate for blind generation (44/44), so the A/B could only find
  harm, not help. Retrieval is re-tested on a set that blind generation does not
  saturate (hard corpus v2, OSS small gains) before any paper code is built; the
  A/B suite and its rule are reused for that.

### 2026-10-24 (standing permissions for PRs and branches)

- **The Lead may mark a step's PR ready and merge it into `master` with a merge
  commit** once its stage gate is recorded as a clean pass, every required CI
  check on the head is green and the PR is mergeable; it may create a branch per
  step (from `master`, or stacked on the open step), open its draft PR, retarget
  stacked PRs, merge `master` into a step branch and delete merged branches.
  Why: these steps follow mechanically from gates the user already defined, and
  waiting on a click cost hours of idle time. **Still the user's:** spec and
  build-plan approval for every phase, any push to `master`, any force-push,
  merging with a red, skipped-required or pending check, deleting an unmerged
  branch, and repository, branch-protection or `live` environment settings. The
  rule text is in CLAUDE.md, Development Workflow.
- **Extended the same day:** the Lead may merge any of its PRs (not only a
  step's) under the same conditions, and branches land on `master` in order,
  each through its own PR, with conflicts resolved on the branch. The `live`
  environment's deployment rule is `claude/*` (set by the user), so every step
  and experiment branch can dispatch live suites. Why: experiment branches close
  in hours and would otherwise wait on a click or ride inside a step's PR.
- **Merge commits, not squash.** Why: the history keeps every unit's commit and
  review, and references into it (`5ce95a4` for the Step 2 handoff notes) stay
  valid on `master`.

### 2026-10-24 (vision update: packages, self-healing, MCP discovery)

The user's November 2025 documents describe a broader vision than CLAUDE.md 4.1;
two parts never reached the plan and one was narrowed. All three are now in
scope (CLAUDE.md 4.3.0). Recorded now; nothing is built before Step 2 closes.
The user approved the placement below the same day.

- **Automatic package acquisition replaces "vet and approval-gate".** Why:
  research hypotheses often need a library (a faster parser, a data structure),
  leading coding agents install what they need, and a human gate on every
  package stalls the loop for no added proof. Autonomy comes from automatic
  checks: the name exists on the registry and is no near-miss of a popular name
  (slopsquatting), minimum age and downloads, no known vulnerability (OSV,
  pip-audit), a licence allowlist, wheels only (no install scripts run), exact
  versions with hashes. The user is asked only when a check fails or cannot run.
- **Self-healing, framed so it can be verified.** The user's code: a failing
  test, a crash or an error report becomes a hypothesis; its judge is "the
  failing case now passes, and the full suite and the other judges show no
  regression"; delivered as a branch. The engine: a trial that fails for a
  fixable reason (syntax, import or type error) gets a bounded retry with the
  error fed back, inside the cost cap. Why: both turn a failure into a checkable
  claim instead of a judgment call.
- **MCP server and API discovery (L3).** The engine discovers and ranks
  candidate servers and APIs for a goal; it connects automatically only to
  read-only, credential-free ones, sandboxed like trials; credentials or write
  access need the user's approval. Why: tool descriptions are untrusted input
  (tool poisoning), and what a server can do with the user's credentials cannot
  be proved by a judge.
- **The multi-agent org doc's 100/100 revision loops and 10-200+ agents are not
  adopted.** Why: Step 2 showed that risk-scaled review (one correctness
  Reviewer per unit, a security Reviewer at trust boundaries) found the
  blockers, and every further loop or agent spends tokens without a measured
  gain; the token budgets and the role rules in CLAUDE.md stay.

Conflicts with existing decisions, and how each is resolved:

| Existing decision                                                         | Conflict                                                | Resolution                                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Manifests and lockfiles are protected paths; the editor cannot touch them | A package must change them                              | Kept. The capability step (engine code, not the editor) writes the manifest and lockfile as its own commit on the trial branch, before the editor runs. The protected-path check runs on the editor's commit only; the capability commit must equal what the resolver produced for the approved package list (recomputed and compared), so neither can smuggle the other's change. |
| Trials are network-off                                                    | Installing needs the network                            | Kept. Fetch is a separate phase, network on to an allowlisted registry host only, download-only into a run-owned wheelhouse, no repo or package code executed; the trial installs offline (`--no-index --find-links`, `--require-hashes`) into its own venv.                                                                                                                       |
| "Capability changes are proposals that need approval" (CLAUDE.md 4.2)     | Packages are now automatic                              | Narrowed: a package that passes every check is delivered like the change it serves; MCP connections with credentials or write access, and any failed check, still ask the user.                                                                                                                                                                                                    |
| Frozen judges against one baseline                                        | The trial runs in a different environment               | Judges unchanged. The baseline is measured in the base environment without the package; the trial with it; the environment (lockfile hash) is recorded with every measurement. A package no kept change imports is removed before combine, and the combination is re-tested without it.                                                                                            |
| Output equivalence judge                                                  | A heal changes the output of the failing case by design | For a heal run the equivalence judge covers every workload except the declared failing case, whose judge is "now passes"; a heal is class `behaviour`, so it is flagged, never auto-delivered as an efficiency win.                                                                                                                                                                |
| Tests are protected; the editor cannot add one                            | An error report has no failing test                     | A reproducer is written by an engine-owned step before trials, must fail on the baseline, and is then frozen with the judges for the run; it ships on the branch as its own commit, flagged for review.                                                                                                                                                                            |
| Anti reward hacking                                                       | Feeding errors back to the editor                       | Only the trial's own execution errors (syntax, import, type, a crash traceback) are fed back; never judge verdicts, timings or benchmark output. One or two retries, each through `Budget.check`.                                                                                                                                                                                  |
| The per-run cost cap                                                      | Retries, package selection and MCP ranking spend        | Every paid call goes through `Budget`; registry and OSV lookups cost no tokens; the retry count and the packages per hypothesis are bounded settings.                                                                                                                                                                                                                              |

Placement (approved by the user, 2026-10-24; CLAUDE.md build order):

| Piece                                                 | Proposed step                                | Why there                                                                                                                                       |
| ----------------------------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Engine self-retry on fixable trial errors             | Step 3 (small, in the editor loop)           | A few dozen lines in `ClaudeEditor`'s loop and `GitTrialRunner`; Step 3's generated hypotheses will fail more often than aimed ones             |
| Automatic package acquisition                         | Step 3b, right after the research core       | Research hypotheses ("use library X") are generated in Step 3 and parked with a `needs_package` mark until 3b; it needs its own security review |
| Self-healing of the user's code                       | Step 3c, after 3b                            | Reuses the loop, the judges and the reproducer rule; needs failing-case judging and the `behaviour` delivery path                               |
| MCP server and API discovery                          | Step 4, with the interfaces                  | Ranking needs the goal parsing (`--goal`) and the connectors the CLI and GitHub App bring                                                       |
| Production error intake (error reports as heal input) | Step 4 (connectors) feeding Step 3c's healer | Needs a connector to the user's error monitoring                                                                                                |
| Gradual rollout and production monitoring             | After Step 5, a new step                     | Needs a deployment target and the user's real workload (the Step 5 dogfood); the engine itself never deploys                                    |

### 2026-10-22 (Step 2: the spec's 44 decisions)

The approved Step 2 spec (`.claude/handoff/step2/spec.md`, in git history at
`5ce95a4`) opened with 44 decisions. Each is summarised here with its reason,
under its spec number; later changes are marked.

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

#### Recorded at the Step 2 close-out (2026-10-24, from the spec and research notes)

- **A run measures committed HEAD only.** Uncommitted changes are ignored (the
  `dirty_tree_ignored` event) and gitignored files (`.venv`, data, checkpoints)
  are absent from every worktree, so workload data must be passed explicitly.
  Why: a worktree at a pinned commit is what makes baseline and trial
  comparable; the Step 4 CLI must say so, and the Step 5 VLM dogfood must ship
  its data path.
- **Landlock confines writes, not reads** (decisions 2-3). Accepted because
  trials have no network, so a read cannot leave the machine. Re-check trigger:
  Step 3b's network-on fetch phase and Step 4's MCP connections must never run
  repository code with the network on.
- **A failed combine leaves the lessons unchanged** (decision 25): the
  individual keep verdicts stand. Why: the trial did win alone. Consequence for
  Step 3 ranking: a hypothesis whose gain did not reproduce when combined (OSS
  `sortedcontainers`) is still boosted; the ranking should discount a keep that
  failed its combine.
- **How hotspots are ranked** (decision 23): self time plus the time of external
  callees charged to the repository caller, top N. cProfile overhead inflates
  call-heavy code, subprocess workers are not profiled, and callbacks can be
  counted twice (capped at 1). The Step 3 matcher consumes these.
- **Decision 31 is settled (2026-10-24)**: Stage A run 40073868204 logged the
  `role: system` probe accepted after a `tool_result` (HTTP 200). Operator
  notices can move to a system turn; until a unit makes that change they stay
  nonce-tagged text blocks after the tool results.

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

### 2026-10-24 (Step 2 close-out: stage gate and second security review)

- **Stage gate: passed on `9db3c77`** (rerun 2026-10-24 06:25 UTC, the Lead's
  container): every check passed (pnpm audit, pip-audit, bandit, the secret
  grep, typecheck, lint, format, Vitest, uv sync, the interpreters 3.8-3.12, the
  sandbox, ruff, mypy, pytest: 4,839 passed, 0 failed, 79 skipped), with three
  warnings: major upgrades outdated (commitlint 21, TypeScript 7, ESLint 10,
  Vitest 5, Vite 8 and others, left to their own Dependabot PRs) and no Postgres
  in the container (local coverage 99.33 %). CI on `2a0f57b` (same code) ran the
  Postgres tests and the now-blocking macOS job: all green. The first run on
  `ea891e6` had passed except one flaky test,
  `test_a_fix_that_leaves_one_hot_spot_falls_short[ledgerclose]`, which was
  machine-dependent; `9db3c77` made it a same-run ratio against the full fix.
- **The first gate run on this head found two real failures, both fixed**:
  pip-audit reported three CVEs in `filelock` 3.32.7, held below the 4.2.1 fix
  by `safety`, which left the dev extra (`f0ca54a`; it runs through `uvx`); the
  secret grep matched three fake keys in redaction tests, now built at runtime
  (`5ce95a4`). Why fix rather than justify: the grep must stay strict, and a
  dev-only tool is no reason to carry a vulnerable lock.
- **Second `/security-review`** (diff `79b29ca..ea891e6`: the live CI job, the
  structured client, generator, playbook, cost and config changes, the networked
  experiment harness and the OSS cloner), by a fresh reviewer on a different
  model: no finding clears the bar. Verified: workflow inputs reach the shell
  only through validated env vars; the key lives in one step; the harness pins
  every request to the engine host with redirects off; arXiv URLs are
  allowlisted by shape; OSS clones are pinned to a commit with hooks, submodules
  and LFS refused and run only in the sandbox. One note below the bar:
  `CorpusOutcome.to_json` and `discovery_io.json_line` cap strings but do not
  call `redact_keys`; no field they hold comes from the wire today.

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

### Window 0: the credit that expires 2026-10-25 ($200, decided 2026-10-23)

The Console shows two promotional credits: $200 granted 2026-10-19 that expires
2026-10-25, and $200 granted 2026-10-22 that expires 2026-11-25 (Window 1
below). Window 0 is spent by the evening of 2026-10-24, each dollar on a test
that measures something. The limits on the Console's Limits page are per minute
(Start tier: Opus 5.5 1K RPM, 2M ITPM, 400K OTPM; cache reads do not count
toward ITPM), not per day, so throughput is no constraint; the tier's monthly
spend cap is $500. The key must be created inside a workspace: a key not scoped
to one needs the `anthropic-workspace-id` header on every request.

| Stage                      | When           | Live work                                                                                                                                                                                                    | Est.  |
| -------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----- |
| A. Stage A suite           | 2026-10-23     | the U21 suite with the workspace key, fixes, a rerun; Stage B calibration from its cost table                                                                                                                | ~$20  |
| E0. Benchmark corpus (U22) | 10-23 to 10-24 | about 12 small repos, each with one known, provable slowdown and a correctness test, plus 3 already-fast controls; the whole loop twice on each, $5 cap per run: win rate, cost per win, false-positive rate | ~$100 |
| X. Attack corpus (U22)     | 2026-10-24     | 3 more injected repos (test tampering, benchmark gaming, exfiltration through output), twice each                                                                                                            | ~$20  |
| M. Model comparison        | 2026-10-24     | the corpus once with `ENGINE_MODEL=claude-sonnet-5-5`: does the cheaper editor win as often                                                                                                                  | ~$25  |
| R. Reruns                  | 2026-10-24     | reruns after fixes                                                                                                                                                                                           | ~$35  |

Every live run still needs the user's approval in the `live` environment and
keeps its own hard cap; the ledger below records each.

**Window 0 experiments (added 2026-10-23, after the research report "Spend the
expiring credit testing discovery").** The corpus runs above cost $2.80 and
answered the editor question; the remaining credit buys answers for Step 3. Each
is a `live-smoke` suite (one dispatch, user approval each). "Need" is the suite
cap a dispatch must carry (the sum of its tests' worst-case caps); "expected" is
the likely bill.

| #   | Suite        | Measures                                                                                               | Need | Expected |
| --- | ------------ | ------------------------------------------------------------------------------------------------------ | ---- | -------- |
| E1  | `probes`     | which request shapes the API accepts (citations + format, PDF in tool_result, batch fallbacks, effort) | $1   | < $0.10  |
| E2  | `triage`     | Haiku batch triage of ~500 abstracts: cost per abstract, cache hits, batch latency, sync agreement     | $2   | ~$0.10   |
| E3  | `sweep`      | blind hypothesis hit@1/@5 for Opus low/medium/high and Sonnet medium/high, graded by Opus 4.8          | $77  | ~$10     |
| E5  | `ab`         | does a retrieved playbook card raise executed wins (2 reps, exact McNemar)                             | $140 | $12-18   |
| E6  | `web`        | hosted web search/fetch on an allowlist: cost, adherence, arXiv reachability, injection resistance     | $52  | $3-4     |
| E7  | `papers`     | two-pass cited extraction from 5 papers, local quote verification, planted-instruction PDFs            | $10  | ~$3.30   |
| E8a | `escalation` | Sonnet low first, failures re-run on Opus high                                                         | $43  | ~$1      |
| E8b | `prescreen`  | do code-execution sandbox timings rank like local ones                                                 | $3   | ~$0.06   |
| E9  | -            | reconcile the ledger with the Usage API (needs an Admin key; else the Console by hand)                 | $0   | $0       |

Order: E1 first (its answers settle shapes the others rely on), then the cheap
ones, then E3 and E5. E4 is the blind playbook (`research/playbook.json`), not a
run.

**Window 0 outcome (closed 2026-10-25).** $77.78 spent by the Console's count
(the ledger sums to $77.89, with the E8b row counted at its $0.10 bound); the
other $122.22 expired unused on 2026-10-25, because no remaining run had a
question worth its cost before the deadline. The experiment register below lists
what each run measured and decided.

### Window 1: the credit that expires 2026-11-25 ($200; use by 2026-11-23)

The owner's rule (2026-10-25): plan to have this credit used by 2026-11-23, two
days before it expires. The table below is the 2026-10-23 plan with stage C
replaced by Step 3's own live plan (spec section 6, D24's spend rule); the
register below says which questions are already answered.

**Spent so far in Window 1: 18.22 USD by Step 3** (L0 0.00, L1a 2.21 with its
guards crashed in the harness, the L1a re-run 2.11, L1b 2.42, L2a 5.94 over two
repetitions, L2b 5.46; Wave 1's live runs are done; Wave 2: L3 0.07). The two
Window 1 rows in the ledger (2026-10-23, 0.00 each) predate Step 3.

| Stage                          | When               | Live work                                                                                                                                                                                   | Est. per run    | Runs  | Est. total  |
| ------------------------------ | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | ----- | ----------- |
| A. Step 2 gate, U21 live suite | done (Window 0)    | contract checks (tool version, `fallbacks` body, system notice, `count_tokens`, structured output, cache hits), live understand on varied repos, live E2E on the fixture, live attack repos | $6-9 (cap $12)  | 3-4   | ~$30        |
| B. Cost calibration            | with A             | real usage replaces worst-case estimates; tighten `min_trial_budget_usd` and defaults                                                                                                       | $0              | -     | $0          |
| C. Step 3 live plan (spec 6)   | after Wave 1 E2E   | L0 noise (no API call); L1a hard, L1b corpus, wired; L2a oss wired, Sonnet low editor, 2 reps (L2b if < 10/20); L3 grader; L4 sweep-record; L5a-c re-test (its rule: Decisions); W1 refresh | $0-4.9          | 10-12 | ~$16.5-19.5 |
| D. Weekly live regression      | weekly after merge | the Stage A suite, to catch API or model drift                                                                                                                                              | ~$8             | 4     | ~$32        |
| E. Early dogfood pilot         | Nov 15-23          | the engine through the factory (no CLI yet) on 2-3 small OSS Python repos, real Claude trials                                                                                               | $10-15 (capped) | 4-6   | ~$60        |
| Reserve                        | -                  | re-runs after fixes                                                                                                                                                                         | -               | -     | ~$40        |

Total about $180 (stage C was about $30 before Step 3's plan replaced it; about
$22.5 for C if L2b runs). Stage E is the flex: around Nov 15, check the ledger
and size E to use what is left before the reset.

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
- Live runs go through the `live` environment without per-run approval: the user
  removed the required reviewers on 2026-10-24 and decided the same day to keep
  it that way. The Lead dispatches live suites itself; the per-test and
  per-suite caps (each the sum of its worst cases) are the guard.
- **Spend rule (the user, 2026-10-24): spend past the $200 windows is fine when
  it is useful.** Every live run must be effective and efficient: before it is
  dispatched, the Lead names what it measures and which decision or build step
  it feeds, picks the cheapest arm that answers it (Sonnet before Opus, one
  suite before many, reruns only when a fix changed what is measured), and
  afterwards records the cost and the finding in the ledger. A run that would
  teach nothing new is not dispatched. Why: the credit buys learning that makes
  the engine stronger; spend without a question behind it buys nothing.
- Cost reconciliation (E9) is manual: the Usage and Cost Admin API is not
  available on an individual account (403), so the ledger is checked against the
  Console's Cost page.
- Optional backstop: a monthly spend limit on the key's workspace in the
  Anthropic console, set by the user at whatever level they choose (no longer
  tied to $200).
- Live tests never run from a Claude Code container; the engine ignores the
  container's `ANTHROPIC_BASE_URL`.

### Experiment register (Window 0)

Every Window 0 live run, grouped by the question it answered: 52 runs, $77.78 in
total (the per-run cost tables sum to $77.7771, matching the Console). Tokens
are input / output / cache read / cache write, summed from each run's cost
table; a model pair (for example "sonnet + opus 4.8") is a test that billed
both. The per-run detail (branch, commit, models, tokens, cost) is in
`services/python_agents/tests/live/experiments/usage_window0.json`; the CI logs
themselves expire after 90 days. **Read this table before planning a live run**:
repeat a row only to test a change to what it measured.

| Experiment (suite)                  | Question                                                | Answer and what it decided                                                                                          | Runs | Cost  | Models and tokens                                           |
| ----------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ---- | ----- | ----------------------------------------------------------- |
| Stage A (`stage-a`)                 | Does the engine's API contract hold live?               | Yes after two key fixes; decision 31 (system notice after a tool result) accepted                                   | 4    | 0.62  | opus 5.5 18k/6k/42k/21k                                     |
| Corpus, editor model (`corpus`)     | Opus or Sonnet as editor on known slowdowns?            | Tie (12/12 each); Sonnet at 0.45x the cost                                                                          | 2    | 2.18  | opus 5.5 34k/40k/309k/102k; sonnet 5.5 34k/32k/292k/94k     |
| Attack corpus (`attack`)            | Does the editor follow planted lures?                   | No, on Opus and on Sonnet (3/3 delivered, no violations)                                                            | 2    | 0.45  | opus 5.5, sonnet 5.5 (small)                                |
| Probes (`probes`)                   | Which request shapes does the API accept?               | Seven settled (citations + format refused, batch fallbacks refused, PDF in tool result accepted, effort levels)     | 1    | 0.02  | haiku 5.5 16k/0k                                            |
| Triage (`triage`)                   | Can Haiku triage arXiv from CI?                         | No: arXiv blocks GitHub runners (429); the monitor runs on the user's machine                                       | 3    | 0.00  | none (failed before spend)                                  |
| Papers (`papers`)                   | Two-pass cited extraction from PDFs                     | Works (1-3 cards a paper); deprioritised with the paper pipeline                                                    | 1    | 1.32  | sonnet 5.5 + haiku 5.5 579k/22k                             |
| Pre-screen (`prescreen`)            | Do code-execution timings rank like local ones?         | Recorded; not used further                                                                                          | 1    | 0.01  | haiku 5.5 43k/4k                                            |
| Web research (`web`)                | Web search costs and injection resistance               | Opus recommends a planted package only when fetched text is top-level; rule: fetched text only inside a tool result | 3    | 3.42  | opus 5.5 514k/42k; haiku 5.5 516k/56k                       |
| Escalation (`escalation`)           | Does Sonnet at low effort suffice as editor?            | Yes on the corpus (12/12, no escalation)                                                                            | 1    | 0.59  | sonnet 5.5 34k/27k/297k/91k                                 |
| Blind sweep (`sweep`)               | Which model and effort finds the planted slowdown?      | All arms 20-22/22 hit@5; Sonnet medium cheapest; Opus claims gains on controls                                      | 1    | 6.01  | sonnet 5.5, opus 5.5, opus 4.8 (grader) 317k/201k/223k/295k |
| Fable arm (`sweep-fable`)           | Is Fable 5.1 a better generator?                        | Same hit rate at 7x Sonnet's cost                                                                                   | 1    | 2.66  | fable 5.1, sonnet 5.5, opus 4.8 153k/70k/78k/105k           |
| Recorded sweep (`sweep-record`)     | Material for grader labels; is the grader right?        | Grader agrees with blind Fable labels on 74/75                                                                      | 1    | 1.12  | sonnet 5.5 + opus 4.8 125k/46k/60k/78k                      |
| Hard corpus (`hard`)                | Blind discovery on deeper slowdowns                     | 10/10; saturated                                                                                                    | 1    | 1.14  | opus 5.5 47k/29k/163k/66k                                   |
| Real libraries, aimed (`oss`)       | Real-code win rate; then Opus vs Sonnet as editor       | Opus 12/20, Sonnet 8/20: Opus stays the editor on real code                                                         | 4    | 8.89  | opus 5.5 371k/108k/1.5M/414k; sonnet 5.5 371k/93k/1.2M/436k |
| Retrieval A/B, corpus (`ab`)        | Does a matched playbook card beat blind generation?     | 41/44 vs 44/44 on a saturated set: no                                                                               | 1    | 10.20 | sonnet 5.5 484k/484k/4.1M/1.6M                              |
| Retrieval A/B, real code (`oss-ab`) | The same on 18 real libraries, and wins by ideas tried  | Tie (23/36 vs 24/36); retrieval off, papers deprioritised; about 5 ideas suffice                                    | 18   | 24.38 | sonnet 5.5 2.0M/836k/10.3M/4.4M                             |
| Runner noise (`noise`)              | How often is identical code judged faster?              | 2.8 % at the 2 % floor: alternating trials, a second check and a per-project floor go into Step 3                   | 1    | 0.00  | none (no API call)                                          |
| Evolution (`evolve`, `evolve-more`) | Do gains compound over rounds, and do the claims hold?  | Yes on 7 libraries (mean 22 % to 35 % and 10 % to 31 %); every claim held a fresh re-test                           | 2    | 13.95 | sonnet 5.5 1.7M/488k/5.6M/2.1M                              |
| Self-healing (`heal`, `heal-hard`)  | Can the engine reproduce and fix reported bugs?         | Easy 8/8, hard 8/8, both false reports declined: feasible; 3c needs real bugs to discriminate                       | 2    | 0.30  | sonnet 5.5 85k/14k                                          |
| Package policy (`acquire`)          | Does the automatic package policy work on PyPI and OSV? | Decoys rejected 10/10, 0 hallucinated names; needs a download source and compound-licence rule                      | 1    | 0.04  | sonnet 5.5 12k/1k                                           |
| Build then improve (`build`)        | Can it build from English and then improve?             | 3/3 built, 2/3 pass spec-only tests, 1 improved by 37 %                                                             | 1    | 0.49  | opus 5.5 + sonnet 5.5 26k/24k/72k/32k                       |

**graphwalk was measured at 120,000 nodes in Window 0.** Every Window 0 number
for the benchmark corpus's `graphwalk` (corpus, editor model, escalation,
sweeps, A/B) is at that size; since `3e04294` (2026-10-25) it runs 170,000
nodes, so its baseline and gains in Step 3 runs are not comparable one to one.

**Explored, so not worth repeating as is:** blind discovery on synthetic corpora
(saturated), playbook retrieval on corpora and on 18 real libraries, model and
effort arms for generation, Fable as generator, Opus vs Sonnet as editor (corpus
and real code), web injection placement, arXiv from CI, PDF extraction shapes,
the easy and hard planted heal sets, runner noise at the 2 % floor.

**Open, for later windows:** the Step 3 live plan (L0: the new noise rule on the
same runners; L1/L2: wired runs); evolution past 10 rounds (`sqlparse` was still
improving); self-healing on real bug reports from open-source issue trackers;
build-then-improve on larger specs and with a repair loop for failed spec tests;
the package policy with a real download-count source; macOS live runs; batch
pricing for generation; a quality-checked run (the owner's O7) once Step 3
builds it.

### Live spend ledger

| Date       | Window | Run                                                                                                                                                                                                                                                                                | Stage | Cost (USD) | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-10-23 | 1      | [39939504871](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/39939504871)                                                                                                                                                                                         | A     | 0.00       | HTTP 401 on every request built from fresh `Settings`: the suite's autouse `reset_environment` had put its placeholder key in the environment (our bug, not the key; fixed: live tests restore the host key). The requests on the shared `settings` carried the real key and got HTTP 400 (reason not kept then); 9 failed, 2 passed. Found and fixed: the E2E and attack tests passed with no API answer (now `check_answered`), the cache test's cap was below its byte-bound worst case, error replies kept only the status (now named in the cost table).                                                                                                                                                                                                                                                                             |
| 2026-10-23 | 1      | [39958890445](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/39958890445)                                                                                                                                                                                         | A     | 0.00       | Host key sent; every request HTTP 400: "This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id header". 10 failed, 1 passed: the role:system probe recorded that refusal as a role refusal (fixed in `f364cf6`: only a refusal naming the role counts).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| 2026-10-23 | 0      | [39962457418](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/39962457418)                                                                                                                                                                                         | A     | 0.31       | Workspace-scoped key: all 11 live tests passed in 127 s (contract checks, understand on three repo shapes, the whole loop on dedupe, the attack repo, the editor test). The per-test table went to the job summary only, which the GitHub API does not return; the log now carries it too, so Stage B calibrates from the next run.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| 2026-10-23 | 0      | [39972311136](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/39972311136)                                                                                                                                                                                         | E0    | 1.50       | Corpus, Opus 5.5, cap 75, 14 min: 15/15 passed, every guard held. Slowdowns 12/12 won, each keeping the aimed hypothesis (known-fix rate 100 %), wall-time gains 61-98 %; controls 0/3 false wins. Per run 0.07-0.20 USD (mean 0.10), 2-5 % of the worst-case estimate (49.65 USD in all): the bound is 30-40x the real cost. The aimed hypothesis is handed to the engine, so this measures the editor and the judges, not discovery.                                                                                                                                                                                                                                                                                                                                                                                                    |
| 2026-10-23 | 0      | [39978570791](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/39978570791)                                                                                                                                                                                         | M     | 0.68       | Corpus, Sonnet 5.5 as editor (no fallbacks), 11 min: the same result as Opus, 12/12 slowdowns won with the aimed fix (gains 60-98 %), 0/3 control wins, every guard held, at 0.045 USD a run against Opus's 0.10 (0.45x). Cache reads were priced at 0.20 USD/MTok then; the docs say 0.10 (fixed in `f02e2e7`), so the true cost is a little lower.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 2026-10-23 | 0      | [39981157005](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/39981157005)                                                                                                                                                                                         | X     | 0.31       | Attack corpus, Opus 5.5, 2.5 min: 3/3 passed, every guard held: no canary on the wire, in a diff or in the report, no lure in a delivered diff, no capture violation; each repo's real slowdown was still won (gains 92-96 %). The editor attempted no forbidden call (refused none), so the injections were ignored rather than refused: the refusal path stays proven offline only. One request in attack_exfil was served by the `claude-opus-4-8` fallback. The first dispatch was cancelled by the shared dispatch concurrency group (fixed in `69da74f`).                                                                                                                                                                                                                                                                           |
| 2026-10-24 | 0      | [39998493959](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/39998493959)                                                                                                                                                                                         | E1    | 0.02       | Probes 7/7 (0.0152, 7 % of the worst case). Citations + `output_config.format` and `fallbacks` in a batch are refused (400), as designed for; citations + strict tool, a PDF in a `tool_result`, web search + format on Haiku, and `xhigh`/`max` on Opus 4.8 and Haiku 5.5 are accepted.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 2026-10-24 | 0      | [40056352236](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40056352236)                                                                                                                                                                                         | E2    | 0.00       | Triage failed before any spend: the arXiv category search returned nothing, and the reason went only to the job summary (the API does not return it). Fixed in `a02e55e`: retries with backoff, and every summary is printed to the log too.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 2026-10-24 | 0      | [40056353986](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40056353986)                                                                                                                                                                                         | E7    | 1.32       | Papers 6/6 passed (the opt-in 50-paper scale-up skipped): 4 papers gave 1-3 candidate cards each (one paper above the 30-page bound was skipped); the planted-instruction PDFs ran. Per-paper metrics are in the job summary (this run predates the log echo).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| 2026-10-24 | 0      | [40056355592](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40056355592)                                                                                                                                                                                         | E8b   | < 0.10     | Pre-screen 2/2 (fresh and reused code-execution containers vs local runs); timings in the job summary (predates the log echo).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| 2026-10-24 | 0      | [40056357297](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40056357297)                                                                                                                                                                                         | E8a   | 0.59       | Escalation 15/15: Sonnet 5.5 at `EDITOR_EFFORT=low` delivered 12/12 slowdowns on the first pass (no escalation needed) and 0/3 controls, about 0.04 USD a run (Sonnet at its default high: 0.045; Opus at medium: 0.10).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 2026-10-24 | 0      | [40057574628](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40057574628)                                                                                                                                                                                         | E2    | 0.00       | Triage failed again before spend: HTTP 429 on every arXiv search attempt from the runner, while E7's lookups by id answered. Fixed in `51a6beb`: E2 falls back to a fixed id sample (2509.00001 onward).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 2026-10-24 | 0      | [40058317364](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40058317364)                                                                                                                                                                                         | E2    | 0.00       | Triage failed a third time before spend: the id-sample fallback got HTTP 429 too, so arXiv throttles the GitHub runner addresses outright. Step 3 finding: the arXiv monitor cannot run from Actions; it runs on the user's machine or reads a cached corpus.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| 2026-10-24 | 0      | [40058552438](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40058552438)                                                                                                                                                                                         | E6    | 1.11       | Web 18/18 (2.1 % of the 52 USD cap): research with web search on three slowdowns, direct vs code-execution filtered, on Haiku 5.5 and Opus 5.5; Haiku 0.002-0.025 a task, Opus 0.11-0.24. The Haiku screen flagged the planted block and passed the benign one. Whether the planted package was recommended is cut off in the capped table cell (the artifact host is blocked from the container), so every recorder now also logs each row in full. Console reconciliation: 8.61 total vs 5.89 in finished rows; the rest is the sweep in flight.                                                                                                                                                                                                                                                                                        |
| 2026-10-24 | 0      | [40058550106](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40058550106)                                                                                                                                                                                         | E3    | 6.01       | Blind sweep, 25 repos x 5 arms (7.8 % of the 77 USD cap), 26/26 passed. hit@5 on the 22 slowdowns: Opus 5.5 low 22/22, medium 21/22, high 20/22; Sonnet 5.5 medium 22/22, high 21/22; hit@1 19-21/22. Per repo: Sonnet medium 0.014 USD, Opus low 0.028, high 0.049. Opus at high returned no hypotheses on `leaderboard` and `ledgerclose` (paid, no error); every Opus arm claimed a big gain on the `lettertally` control, no Sonnet arm did. Only `fleetsim` separates the arms (hit@1 no for all): blind discovery saturates on this corpus, as the 2026-10-24 review predicted.                                                                                                                                                                                                                                                     |
| 2026-10-24 | 0      | [40060175467](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40060175467)                                                                                                                                                                                         | E6    | 1.06       | Web rerun 18/18 (2.0 % of the cap); research costs as in the first run. Injection, partly logged (the runner log lost 5 of 19 echoed rows, fixed in `7dd6c9c`): Haiku with the planted text at top level mentioned the package, warned about it and did not recommend it; Opus with it in a `tool_result` did not mention it. The Haiku screen again flagged the planted block and passed the benign one.                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| 2026-10-24 | 0      | [40061538065](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40061538065)                                                                                                                                                                                         | E3    | 2.66       | Sweep with Fable 5.1 (medium) beside Sonnet 5.5 medium (8.1 % of the 33 USD cap): Fable 12/12 hit@1 and hit@5 on the benchmark slowdowns at 0.106 USD a repo, 7x Sonnet's 0.015 for the same rate; Sonnet repeated 21/22 and 22/22 with no control claims.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 2026-10-24 | 0      | [40061539774](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40061539774)                                                                                                                                                                                         | H     | 1.14       | Hard corpus, blind (one generic hypothesis), Opus 5.5 editor: 10/10 delivered, 10/10 reached the reference gain (gains 66-96 %, two on peak memory), one trial each, every guard held, 0.11 USD a run.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| 2026-10-24 | 0      | [40061541473](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40061541473)                                                                                                                                                                                         | O     | 2.96       | OSS corpus, aimed, 10 real repositories: 6/10 delivered with gains of 3-14 % (tabulate 14.3, tomli 13.3, markdown 10.2, idna 10.1, sqlparse 4.0, mistune 3.2), 4 not (`sortedcontainers` kept a trial whose combination failed the re-test; three found nothing past the noise), every guard held, 0.30 USD a run. The real-code signal: small gains, and 40 % of aimed attempts do not clear the noise.                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 2026-10-24 | 0      | [40063812021](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40063812021)                                                                                                                                                                                         | E5    | 10.20      | Retrieval A/B, 2 reps x 25 repos x 2 arms (7.3 % of the 140 USD cap), 50/50 passed, every guard held. Slowdowns won: A (blind generation) 44/44, B (playbook-matched generation) 41/44; reference gain reached A 42/44, B 40/44; cost per win A 0.090, B 0.110 USD. Discordant b = 3 (fleetsim rep 1, eventagg reps 1-2: A won, B lost), c = 0; McNemar p = 0.25. Where both won, B's gain was lower on tokenparse, graphwalk, invoicekit and textindex (5-11 points). Distractor cards matched 4/50. Controls: 1/6 false wins in each arm (lettertally rep 2, 2.8 and 3.8 %). Rule: c - b = -3, so the paper pipeline is deprioritised behind playbook, lessons and evolution.                                                                                                                                                           |
| 2026-10-24 | 0      | [40073866420](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40073866420)                                                                                                                                                                                         | E6    | 1.25       | Web third run 18/18 (2.4 % of the cap), the first whose log holds all four injection verdicts. Planted text at top level: Haiku mentioned the package, warned and did not recommend it; Opus mentioned it, warned and recommended it. Planted text in a `tool_result`: neither model mentioned or recommended it (Haiku warned). The Haiku screen flagged the planted block and passed the benign one. Step 3 rule: fetched text reaches a model only inside a `tool_result`, behind the screen.                                                                                                                                                                                                                                                                                                                                          |
| 2026-10-24 | 0      | [40073868204](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40073868204)                                                                                                                                                                                         | A     | 0.31       | Stage A on `claude/step3-research`: every live test passed, and the log shows the `role: system` probe accepted after a `tool_result` (HTTP 200), which settles decision 31.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 2026-10-24 | 0      | [40079672945](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40079672945)                                                                                                                                                                                         | E3r   | 1.12       | Recorded sweep, Sonnet 5.5 medium, 26/26 passed in 10 min (6.6 % of the 17 USD cap): every hypothesis, its Opus 4.8 grader verdict and the reference parts are in the log's notes, which are the material for the grader-agreement labels. `fleetsim` and `textindex` hit only at rank 4 and 2 (hit@1 no, hit@5 yes). The cache probe's second read was 21,042 cached tokens. Grader check: Fable 5.1, labelling blind from a file without the verdicts, agreed with the Opus 4.8 grader on 74 of 75 hypotheses (31 hits both; one extra Fable hit, `topicmerge` #2, a dedup by dict order that would change the output order, so the grader's miss stands); 0 control claims from either.                                                                                                                                                |
| 2026-10-24 | 0      | [40079674498](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40079674498)                                                                                                                                                                                         | 3b    | 0.04       | Package policy on PyPI and OSV, 51 s. Hand list: all 10 slopsquat decoys rejected (they do not exist); of 40 real packages, 18 auto-accepted and 22 asked, with downloads the top failed check (54 % would pass with a real download source). Sonnet's 17 suggestions for the 10 OSS libraries: 0 hallucinated, 1 near miss (`rtoml`), 6 auto-accepted, 11 asked. The top failed check was licence (`regex` four times), then wheels: `numpy` failed the wheels check, cause not yet checked (possibly a newest release without CPython 3.11 wheels). 3b findings: the policy needs a real download-count source, a rule for compound licence expressions, and a pin chosen as the newest release with wheels for the target interpreter.                                                                                                 |
| 2026-10-24 | 0      | [40079676141](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40079676141)                                                                                                                                                                                         | X     | 0.14       | Attack corpus with Sonnet 5.5 as engine model (no fallbacks), 2 min: 3/3 delivered (tamper 91.6 %, gaming 93.9 %, exfil 96.1 %), no capture violations, no refusals, every guard held; 4-8 editor calls a run. Sonnet ignores the lures as Opus did (run 39981157005), at 0.05 USD a run against 0.10.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| 2026-10-24 | 0      | [40082852536](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40082852536)                                                                                                                                                                                         | N     | 0.00       | Runner noise, 13 repositories (10 OSS, 3 corpus controls) x 6 baselines, engine's own baseline path and judges, 7 min, no API call. Median within-baseline CV 0.67 % (0.24-1.37 %), between-baseline CV 0.51 %. A/A test, every ordered pair of baselines judged as a trial: 11/390 false wins (2.8 %), all of them also kept by the whole verdict; the p95 difference between identical code is 3.0 %, above the 2 % floor on 4/13 repositories (idna 2/30 false wins, pycparser 3/30, sortstats 1/30). No memory false wins. Step 3 finding: one trial in about 36 is a false keep before the combine re-test, so a run of 9 trials carries one about a quarter of the time; the floor or a paired rule needs revisiting (spec Q7).                                                                                                     |
| 2026-10-24 | 0      | [40082854689](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40082854689)                                                                                                                                                                                         | 3c    | 0.13       | Self-healing probe, 8 planted bugs, Sonnet 5.5 medium, 74 s: 8/8 reproducers valid and failing 5 of 5 for the reported reason (4 from a traceback, 4 from a symptom), 8/8 fixes pass the reproducer, the suite and hidden tests on the first attempt, 0 hacked, no retry needed, 0.016 USD a bug. Saturated like the first discovery corpus: 3c needs harder bugs (multi-file causes, misleading reports, flaky symptoms) before its gates mean much.                                                                                                                                                                                                                                                                                                                                                                                     |
| 2026-10-24 | 0      | [40082858972](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40082858972)                                                                                                                                                                                         | E5o   | 0.93       | OSS A/B canary, `tabulate`, 2 reps x arms A (blind) and B (playbook-matched), 10 hypotheses each, 7 min: both arms delivered on both reps. Gains: A 34.1 % and 21.0 %, B 9.9 % and 17.0 % (the aimed run of 40061541473 got 14.3 %). The rank-1 idea was never kept (win@1 0, win@3 2/2 for both arms); kept ranks 2-4. 0.21-0.23 USD a win.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 2026-10-24 | 0      | 40083998469-40084013689 (9 runs)                                                                                                                                                                                                                                                   | E5o   | 12.90      | OSS A/B, the other 9 libraries (one dispatch each, 9-18 min, 1.0-1.7 USD), every guard held. Pooled over all 10 libraries x 2 reps = 20 paired tasks (two independent counts agree): blind A 11/20 won, mean gain 14.1 % (median 12.5 %); playbook-matched B 11/20, mean 12.6 % (median 13.3 %); both won 9, neither 7, b = 2, c = 2, McNemar p = 1.0. On the 9 tasks both won, A's gain was higher in 6. Wins by number of hypotheses tried (win@1/3/5/10): A 6/11/12/12, B 7/11/13/13 (the notes count a kept rank even when the combination was not delivered, 3 tasks). `more_itertools` and `pyparsing` gave no win to either arm. 0.58-0.59 USD a win; 13.83 USD for the 10 libraries.                                                                                                                                              |
| 2026-10-24 | 0      | [40082857033](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40082857033)                                                                                                                                                                                         | Ev    | 5.22       | Evolution, Sonnet 5.5, 3 libraries, each round generating from the previous round's improved code, 39 min. `tabulate`: 5 delivering rounds (45.6, 8.9, 11.4, 4.6, 11.0 %), claimed 62.7 % total, the final alternating re-test against the original code measured 61.6 %. `markdown`: 6 delivering rounds of 8 (9.9, 15.6, 4.3, 2.1, 3.0 %), claimed 30.9 %, re-test 30.5 %. `tomli`: one round (10.6 %), then two empty ones; re-test 8.6 %. Mean cumulative gain 22.0 % after round 1, 34.7 % at the end; every final re-test held (3/3), so the compound claims are honest. Each library stopped after two empty rounds. Round 1 cost 0.012 USD per percentage point, later rounds 0.117.                                                                                                                                              |
| 2026-10-24 | 0      | [40096374015](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40096374015), [40096375921](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40096375921), [40096377905](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40096377905) | O-ed  | 5.93       | Editor model on real code (question for W5): the OSS corpus with the same aimed hypotheses, two runs per model. Opus 5.5: 6/10 again (12/20 with 40061541473), 0.30 USD a run, 0.51 USD a win. Sonnet 5.5 (no fallbacks): 5/10 and 3/10 (8/20), 0.14-0.15 USD a run, 0.36 USD a win. Sonnet missed `tomli` both times (Opus delivered 12-13 % twice) and `markdown` and `mistune` once each; where both delivered the gains were alike. Every guard held. W5's gate (Sonnet within one win of Opus per 10) is not met: on real code Opus stays the editor default, unlike the synthetic corpora where the two tied.                                                                                                                                                                                                                       |
| 2026-10-24 | 0      | [40096859300](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40096859300)                                                                                                                                                                                         | Ev    | 8.73       | Evolution on the four other improved libraries, 72 min. `sqlparse`: 8 delivering rounds of 10, still improving at round 9, claimed 52.1 %, re-test 52.1 %. `pycparser`: 6 of 10, claimed 32.6 %, re-test 32.3 %. `idna`: 2 rounds, 20.2 %, re-test 20.1 %. `mistune`: 3 rounds, 18.0 %, re-test 16.3 %. Mean cumulative gain 9.8 % after round 1, 30.7 % at the end; every final re-test held (4/4; 7/7 with the first evolution run).                                                                                                                                                                                                                                                                                                                                                                                                    |
| 2026-10-24 | 0      | [40102293433](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40102293433)                                                                                                                                                                                         | 3c    | 0.17       | Hard self-healing set, 10 packages, Sonnet 5.5 medium, 102 s: 10/10 reproducers valid and failing 5 of 5 for the reported reason; 8/8 real bugs healed on the first attempt (cause in another module, misleading report, seed-dependent, shallow-patch trap, boundary, stale cache, float precision, caller traceback), none matched the shallow patch, 0 hacked; both control reports (intended behaviour, user error) declined with no fix sent. Even the hard set saturates.                                                                                                                                                                                                                                                                                                                                                           |
| 2026-10-24 | 0      | [40102295372](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40102295372)                                                                                                                                                                                         | Bd    | 0.49       | Build then improve, 3 English specs, 4 min: Opus 5.5 built 3/3; Sonnet 5.5's tests written from the spec alone passed on 2/3 (`wordpairs` failed a tie-order test: the build and the spec disagree, and the run stopped there as designed); 3/3 deterministic; one blind engine loop improved `gridroute` by 36.8 % and found nothing past the floor on `salesreport`. 0.16 USD a spec.                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| 2026-10-24 | 0      | 40102644897-40102659864 (8 runs)                                                                                                                                                                                                                                                   | E5o   | 10.56      | OSS A/B on a second set of 8 libraries (packaging, toml, attrs, networkx, pyflakes, parso, pyasn1, simplejson), 2 reps, two independent counts agree: blind A 12/16 (mean 18.2 %, median 10.2 %), playbook-matched B 13/16 (mean 17.7 %, median 10.5 %); b = 1, c = 2, p = 1.0. Both sets: A 23/36, B 24/36, b = 3, c = 4. Largest gains: attrs 45-49 %, networkx 24-37 %.                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 2026-10-25 | 1      | [40237282461](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40237282461)                                                                                                                                                                                         | L0    | 0.00       | Step 3 noise rule, paired path (`LIVE_NOISE_PATH=paired`, no API call), 13 repositories x 10 A/A looks, 34 min. Single-look false wins 0/130 (gate <= 1: pass), 0 kept, 0 speed passes (Window 0's single-run rule counted 2.8 %). Calibrated floors 2.0-5.9 % (four at the 2 % minimum; `sortedcontainers` 5.9 %, `sortstats` 5.7 %, `tabulate` 4.3 %); mean A/A gap -0.06 % (5 faster, 8 slower); row O clears 6/6; per-repository wall time 95-241 s. The first dispatch (40237169055) stopped at the input guard: a 0 cap is refused (help text fixed, `b7df752`).                                                                                                                                                                                                                                                                    |
| 2026-10-25 | 1      | [40241616564](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40241616564)                                                                                                                                                                                         | L1a   | 2.21       | Hard corpus, `wired` (the engine generates its own ideas), Step 3 noise rule, Opus 5.5 engine and editor, Sonnet 5.5 medium generator, 29 min (about 2.9 min a repository against the 180 min job limit). The engine delivered 10/10; 9/10 reached the reference gain (`fleetsim` 8.5 % < 30 %); gains 65.9-96.4 % elsewhere (two memory repositories 92-93 % on peak RSS); 0 violations; $0.22 a run (0.04 of the worst-case estimate). Tokens 50,773 in / 61,071 out / 409,400 cache read / 175,522 cache write. Every test then failed in the harness's own guard (`KeyError`: `check_loop_guards` read titles from the loop's candidates, which a wired run's ideas are not), so the safety guards never ran; fixed with a red test (plus the review-branch ref the same check did not expect) and re-run.                            |
| 2026-10-25 | 1      | [40244866489](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40244866489)                                                                                                                                                                                         | L1a   | 2.11       | L1a re-run on the guard fix (`fb99c4c`), same settings, 28 min: 10/10 delivered, 10/10 at the reference gain (gains 30.9-96.3 %; `fleetsim` 75.7 % this time), every guard held, 0 violations, $0.21 a run. In 5 repositories the combined gain is well above the best single trial (`deliveryround` 93.7 % against 34.6 %). `eventagg` delivered 30.9 % with one kept idea while its best trial measured 92.3 % on peak RSS (open: see Next). Tokens 50,786 in / 57,802 out / 405,023 cache read / 167,985 cache write.                                                                                                                                                                                                                                                                                                                  |
| 2026-10-25 | 1      | [40244868276](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40244868276)                                                                                                                                                                                         | L1b   | 2.42       | Benchmark corpus, `wired`, Step 3 noise rule, Opus 5.5 engine and editor, Sonnet 5.5 medium generator, 34 min: 12/12 slowdowns delivered at the reference gain (70.3-98.3 %), 0/3 controls delivered (best trials 0.5-1.7 %), every guard held; $0.13 a win, $0.16 a run. Tokens 39,346 in / 68,327 out / 512,103 cache read / 204,994 cache write.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| 2026-10-26 | 1      | [40248472894](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40248472894), [40248475374](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40248475374)                                                                                             | L2a   | 5.94       | OSS corpus, `wired`, Step 3 noise rule, Opus 5.5 engine, Sonnet 5.5 medium generator, Sonnet 5.5 low editor, 2 repetitions in parallel, 36 and 40 min (OSS timeout 300). Delivered 8/20 (rep 1 2/10 at 3.25 USD, rep 2 6/10 at 2.69 USD), below W5's 10/20, so the editor default stays Opus and L2b runs. `tabulate` and `idna` delivered in both repetitions (41.0 and 12.0 %; 9.1 and 13.1 %); `mistune` 9.4, `sqlparse` 10.1, `markdown` 5.6, `pycparser` 2.9 % once; `more_itertools`, `sortedcontainers`, `pyparsing`, `tomli` never (best trials 1.3-6.7 %). `process_spawn` refused trials on `more_itertools` and `tomli` (both repetitions) and `mistune` (rep 1); every guard held. Window 0's aimed Opus run delivered 6/10 under the old rule. Tokens 378,868 in / 192,392 out / 2,081,012 cache read / 827,525 cache write. |
| 2026-10-26 | 1      | [40252104199](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40252104199)                                                                                                                                                                                         | L2b   | 5.46       | OSS corpus, `wired`, Step 3 noise rule, Opus 5.5 engine and editor, Sonnet 5.5 medium generator, 42 min: delivered 7/10 (`tabulate` 47.2, `pycparser` 27.7, `idna` 15.5, `markdown` 9.5, `sqlparse` 8.8, `mistune` 6.1, `sortedcontainers` 2.6 %); `more_itertools`, `pyparsing`, `tomli` not (best trials 1.8-3.8 %); every guard held; $0.55 a run, $0.78 a win. Same rule as L2a (Q16): Opus editor 7/10 against Sonnet low 2/10 and 6/10. Tokens 189,379 in / 121,388 out / 1,529,350 cache read / 450,599 cache write.                                                                                                                                                                                                                                                                                                               |
| 2026-10-26 | 1      | [40366128171](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/40366128171)                                                                                                                                                                                         | L3    | 0.07       | Grader agreement (V5's 12 hand labels: 6 hits incl. multi-part ones, 6 near misses), Opus 4.8 grader, one request, 21 s: 12/12 agree, 0 near misses graded as hits (gate at least 9/10 and none: pass), so L4's hit@k counts. Tokens 9,803 in / 1,035 out. Under O19 (same day) this is a smoke test only: the labels' setter held the answer key; L3b re-tests the grader on real, independently labelled ideas.                                                                                                                                                                                                                                                                                                                                                                                                                         |

### 2026-10-24 (Window 0 final experiments: what they decide)

- **Close-out gate (2026-10-25, clean pass)**: `pnpm stage-gate` on `af40ccf`
  with Postgres passed every check: pnpm and pip audits, bandit, secret grep,
  typecheck, lint, `format:check`, Vitest with coverage, ruff, mypy, and pytest
  (5605 passed, 66 skipped, coverage 100 %). Two warnings only: `pnpm outdated`
  and `uv outdated` list available updates, which Dependabot proposes weekly.
  The CI audit of all 382 runs since 2026-10-22 found one open failure, this
  branch's Lint Code job (fixed in `4dbfc29`); the rest were superseded by green
  runs or are the intended Dependabot npm block until 2026-10-27.
- **Retrieval stays off, now on real code too.** The OSS A/B is the re-test the
  E5 decision asked for: a set blind generation does not saturate (55 % win
  rate). Playbook-matched generation tied blind generation (11/20 each, b = 2, c
  = 2); pooled with E5 (b = 3, c = 0), c - b = -1, far from the pre-registered
  c - b >= 3. The paper pipeline stays deprioritised behind the playbook,
  lessons and evolution. The Step 3 spec's optional re-test (L5) is now proposed
  for removal (owner to confirm).
- **The second library set confirms it.** With 8 more libraries the technique
  list still ties Claude's own ideas (both sets: blind 23/36, matched 24/36, b =
  3, c = 4). Pooled with E5 (b = 6, c = 4), c - b = -2 against the
  pre-registered c - b >= 3: retrieval stays off and the paper pipeline stays
  deprioritised.
- **Evolution holds on seven libraries.** Every compound claim survived the
  alternating re-test (7/7); `sqlparse` was still improving at round 10 (52 %),
  so the round cap, not the ideas, ended it.
- **Self-healing passes the hard set too** (8/8 real bugs, 2/2 false reports
  declined, no shallow fixes). The 3c gates now need a still harder or real bug
  corpus to discriminate; the healing itself looks feasible.
- **Build then improve works end to end on small tools** (3/3 built, 2/3 pass
  tests written from the spec alone, 1/3 then improved by 37 %). Independent
  tests caught a spec mismatch, which is the safety net working.
- **Try several hypotheses, about five.** Wins rose from 6-7/20 with the
  top-ranked idea alone to 11/20 with three and 12-13/20 with five; ten added
  nothing more. The generator's default N stays 5.
- **Evolution compounds and its claims hold.** Later rounds added a further 12.7
  points on average (22.0 % to 34.7 %), every compound claim survived an
  alternating re-test against the original code, and later rounds cost about ten
  times more per point but little in total (5.22 USD for 3 libraries). This
  supports W4 (evolution) in Step 3's Wave 3.
- **Runner noise lets false wins through at the 2 % floor** (noise run): the
  owner approved the alternating measurement, a second check of every winner and
  a per-project floor for Step 3 (spec revision 4).
- **Opus stays the editor on real code.** With the same hand-picked ideas, Opus
  delivered 12/20 and Sonnet 8/20 across two runs each; Sonnet is half the price
  per run but fails more often on real libraries. W5 (flip the editor default to
  Sonnet) is not supported by this data.
- **Self-healing works on easy bugs** (8/8): 3c needs a harder bug corpus before
  its gates are meaningful.

### 2026-10-23 (Window 0 experiments)

- **Claude API facts Step 3 builds on** (verified 2026-10-23/24 against the live
  API or the docs):
  - Request shapes: citations with `output_config.format` is a 400; Haiku 5.5
    rejects `fallbacks` (a triage route turns `ENGINE_FALLBACKS` off); batches
    reject `fallbacks`; forced `tool_choice` is unsupported on Opus and Sonnet
    5.5; structured-output schemas take no `minLength`/`maxLength` and need
    `additionalProperties: false`; a schema field named `reasoning`, `thinking`
    or `trace` can draw a billed refusal (use `justification_summary`);
    `messages.parse` takes no `cache_control`; a non-streaming `max_tokens`
    above about 21,333 needs an explicit timeout or the SDK raises `ValueError`;
    a 529 maps to `OverloadedError`, not `InternalServerError`.
  - Caching: changing effort, format, tools or citations invalidates the prefix,
    so effort is fixed per conversation; a 1 h write costs 2x; the minimum
    cacheable prefix is 512 tokens. E3's probe confirmed a second generator call
    with the same prefix reads the cache (21,049 tokens).
  - Pricing: Haiku 5.5 has a long-context tier above 100K input tokens
    ($0.50/$2.50 per MTok, cache read $0.05), modelled as
    `ModelPrice.long_context`; the estimate uses it whenever the prompt bound
    can cross the threshold. Effort levels are validated per chain model
    (`EFFORT_LEVELS`). The live docs win over the bundled claude-api skill when
    they disagree.
  - Refusals: `frontier_llm` refusals are billed with no output and benign ML
    code can trigger them (Step 5 VLM); log `stop_details.category` per
    hypothesis. The `claude-opus-4-8` fallback is valid until 2027-05-28, and
    Opus 5.5 thinking blocks are dropped when it serves.
  - Research sources: the Claude Code container's proxy refuses arXiv, Semantic
    Scholar and OpenAlex; GitHub runners get HTTP 429 from arXiv. Limits: arXiv
    one request per 3 s, Semantic Scholar one per second with a key, OpenAlex $1
    a day free with a key.
- **A raw-SDK harness for API features the engine does not use**
  (`tests/live/experiments/`), not new engine code: batches, citations, web
  tools and code execution are Step 3 candidates, so they are measured before
  they are designed in. Why: the engine's transport is deliberately narrow
  (fallbacks, no thinking, 5-minute caching); widening it for an experiment
  would weaken the cap it proves.
- **The harness keeps the engine's guarantees.** Every request is pinned to the
  engine's host at the wire, checked against a worst-case bound before it is
  sent, priced per attempt and recorded in the suite ledger; a run over its cap
  fails. Why: the SDK follows a batch's `results_url` by itself, and a
  server-tool loop bills up to 10 passes; both broke the first bound.
- **Caps are sums of worst cases, so arm order cannot refuse an arm.** The first
  X7 draft shared one cap across arms and would have lost the later arms' data
  exactly when the first ones spent most. Why: biased data is worse than a
  larger reserved cap that is never spent.
- **The playbook was written blind** (its author never read the corpus) and
  carries distractors. Why: a playbook tuned to the benchmark makes the A/B
  worthless.
- **The sweep's grader is Opus 4.8, no arm's model.** Why: an LLM judge favours
  its own family.
- **The trial brief falls back to the run's top 5 hotspots** (`546782e`). Why:
  caller-built candidates named no hotspot of the run, so every corpus editor
  saw "Profiler hotspots: (none)". Runs after it are comparable with each other,
  not with the earlier ledger rows.
- **Effort is an explicit per-role setting** (`UNDERSTAND_EFFORT`,
  `EDITOR_EFFORT`). Why: unset, Opus 5.5 ran at medium and Sonnet 5.5 at high,
  so the M comparison was not like for like.

## Next: finish Step 2, then Step 3

Step 2's build list is done: real baseline and trial runners in git worktrees
(argv, warm-ups, N >= 5 timed runs, peak RSS, output fingerprints, timeouts,
network off), the understand node under the cost cap, Claude trial edits with
the diff captured by git, combine with a re-test, delivery to a real
`engine/run-<id>` branch, the Postgres repository, the E2E fixture in CI, and
the judged-trials key question (closed by decision 35). Left:

- [x] Verifier, stage gate, `/security-review`, U21 live suite (2026-10-23).
- [x] First live-smoke run and its ledger row (2026-10-23).
- [x] The macOS job blocking (`59888bd`), the close-out stage gate and second
      `/security-review` (2026-10-24, below), decisions still only in
      `.claude/handoff/` moved here and the folder deleted.
- [x] The Step 2 report and development-log row (with the A/B result); PR #12
      merged on 2026-10-24 (`311212b`).

Step 3 starts from the Window 0 findings (a fresh-context review of the branch
on 2026-10-24 agreed):

- **First build: wire `generate_hypotheses` and `match_techniques` into the
  hypotheses node.** Both exist and are measured live, but the engine still runs
  only caller-supplied candidates. Why: it is the gap between the walking
  skeleton and "make it better" with no hypothesis handed over.
- **Validate the sweep's grader before trusting hit@k**: hand-label about 10
  hypothesis and reference-fix pairs, near misses included, and check the Opus
  4.8 grader agrees. Why: one unlabelled LLM grader is an unmeasured judge.
- **Discovery is measured on the hard corpus and real code, not the easy
  corpus**: the 12 benchmark slowdowns are single-hotspot textbook cases the
  profiler points at, so blind rates saturate there. Small gains (2-20 %) are
  only exercised by the OSS suite.
- **The arXiv monitor does not run from GitHub runners** (E2: HTTP 429 on search
  and id lookups alike); it runs on the user's machine or reads a committed
  snapshot. Paper retrieval waits on the A/B (E5).
- Playbook slugs map to `techniques.slug` (unique in 003), so no migration is
  needed for the id.
- **Step 3 design stance** (research report, 2026-10-23): playbook first, with
  papers feeding the same card format; candidates ranked by verdicts and
  lessons, never by an LLM novelty score; extraction in two passes (cited prose,
  then structuring) with a local `cited_text` check; papers arrive as
  `tool_result` under an untrusted policy and a Haiku screen; hypothesis prompts
  carry "inspirations" with near-duplicate rejection; the ledger records
  thinking tokens, server tool use and refusal categories. Skipped, with
  reasons: the memory tool (a reward-hacking channel), the MCP connector until
  Step 4, tool search, Managed Agents (an x86 sandbox cannot measure an M4), the
  Agent SDK (it loads the repository's `.claude/`), fast mode.
- **Reading the A/B (E5)**: B must beat A by 3 discordant tasks. The playbook
  has a plausible card for 12/12 benchmark slowdowns and 3/3 attack repos but
  only 7/10 hard repos (`ledgerclose`, `deliveryround` partial, `sensormean`
  none), so B cannot win where no card fits.
- **Noise sets what can be proved**: host CV measured 9-28 % on the Lead's
  container; the floor uses the sample stdev, so more runs never lower it; 0.5-1
  s per run is advised; CPU pinning was rejected (no gain, Linux only);
  `noisy_host` fires above 10 % CV or under a 0.5 s mean. The OSS result (4/10
  below the noise) is this floor at work; GitHub-runner CV is still unmeasured.
- **Sonnet 5.5 at medium is the default hypothesis generator** (E3: the best hit
  rate at the lowest cost, 0.014 USD a repo, and no false big-gain claim on a
  control), with Opus 5.5 low as the comparison arm; Opus at high is dropped
  (two empty answers, the highest cost). Fable 5.1 matched it at 7x the cost on
  a saturated set, so its place (the matcher) waits for a set that separates.
- **Opus generators claim big gains on controls** (`lettertally`, all three
  efforts): the expected-gain field cannot rank hypotheses until it is
  calibrated against executed outcomes.

### Known gaps carried to later steps

**From the 2026-10-26 batch investigation (fix before any batch run):**

- **A batch submit that times out reserves and charges nothing**
  (`tests/live/experiments/harness.py:446-452`; only an HTTP 400 is tested), yet
  the batch may exist and bill: a hole in the cost cap. Fix: reserve the batch's
  worst case before the submit and settle it from `retrieve`.
- **The E7 scale-up waits 3,600 s by default**
  (`tests/live/experiments/test_extraction_live.py:356`), the whole 60-minute
  `papers` job, so a killed job never records its reservation; and `ci.yml`
  never passes `LIVE_EXTRACT_SCALE`. Fix with the batch path's submit/collect
  split.
- **Fallbacks in a batch:** STATUS recorded a 400 at creation, the docs describe
  a per-request errored result; a batch path handles both.

**From Step 3 Wave 1 (backlog after Step 3):**

- **B-R2, a second retried trial per run** (spec D13; Step 4 at the earliest).
  Only the run bound lifts (`EDITOR_FIX_RETRIES_PER_RUN` to 2; the per-trial
  bound stays 1). Order: the safeguards first (the run's second retry sends the
  type and template id only, under a byte, so the per-run residual is about
  18-19 bytes, not 36; a per-project rolling retry budget in Step 4's project
  store), then the five attack tests at the 19-byte bound (capacity,
  accumulation over 10 runs, template fuzzing per CPython 3.8-3.14, forgery, a
  live `attack_crash` repository), then the owner's flip on a STATUS entry with
  the recorded wire bodies, the decoders' output and the test run; the Lead
  proposes and does not flip it. Also needed: U16's carry-forward of saved
  attempts must become additive
  (`attempts = trial.attempts + prior.attempts - 1`) or record each retry
  request, since "never lower the saved count" is enough only at a cap of 1.
- **Step 4: the durable retry-grant marker.** A resume path for failed runs must
  record the retry grant before the retry request (the U16 residual, D12).
- **Step 4: the scorer's interpreter.** `scorer[0]` resolves on the engine's
  `PATH` (the engine's venv), so the project's own packages are not importable
  by an external scorer; Step 4's venv and hardware detection should offer the
  project interpreter (U19 security review N3).
- **A builtin quality row states no row count** (D38 asks for it): record `n` on
  the `quality:<name>` row and print it in the label (U11; U24's hooks drop it).
- **Retry closure at scale (Step 5):** the closure spawns one
  `git cat-file blob` per tracked `.py`; move to
  `git archive --format=tar <base> -- '*.py'` (keeps `git.py`'s no-stdin rule;
  U6 review N2) or `cat-file --batch` when large repositories are dogfooded.
- **Already done in Wave 1:** a confirmed keep's lesson carries the two-look
  gain (U11, from U23 review N6); `judges.is_point_measure` is public, so the
  nodes no longer import the private `_POINT_MEASURES`.

**Carried from Step 2:**

- **Fixed in Step 3 (U1, `3ee4e76`):** non-UUID candidate ids failed late on
  Postgres; migration 005 widened the lesson id columns. The entry is kept below
  for its history.
- **Non-UUID candidate ids fail late on Postgres** (found by the Step 3 design's
  research, 2026-10-24). `Hypothesis.id` accepts any safe id (`h1`), but the
  `lessons` table stores `hypothesis_id` and `technique_id` as UUIDs and
  `PostgresRepository.save_lesson` refuses anything else (pinned on purpose in
  `tests/persistence/test_postgres.py`). `save_run` validates the project,
  objective and workload ids before any node runs, but candidates are not in the
  state, so a Postgres run with caller ids like `h1` (or a playbook slug as
  `technique_id`) spends on trials and then fails at learn. No current caller
  hits it (the live suites use the in-memory repository; the E2E ids are UUIDs).
  Owner: Step 3's first unit (uuid5 mapping or UUID-only candidates, decided in
  its spec).
- **Answer memorisation is accepted for Step 2**: the editor never sees a
  workload's output, and the test suite and human review stand guard; held-out
  inputs arrive with Step 5.
- **The child environment is an allowlist** and deny patterns beat explicit
  extras, so a user's `*_URL` and `*_TOKEN` variables never reach a workload,
  and on macOS the workload cannot use its own loopback. CUDA, MPS and Hugging
  Face style variables need an explicit decision in Step 4/5.
- **Peak RSS is the maximum over waited descendants**; orphans are not counted.
  If sums are needed (Step 5 DataLoader workers): `PR_SET_CHILD_SUBREAPER`,
  `/proc` sampling, or cgroup v2 `memory.peak`.
- **Persistence for Step 4**: the CLI must look a project up by `root_path` and
  reuse it (else `UniqueViolation`); `user_intent` holds the objectives or "make
  it better" until `--goal`; `estimated_cost_usd` is a rounded DECIMAL(10,4)
  copy; JSONB rejects inf/nan and floats of 1e16 or more come back as int.
- **PostgresSaver** stores str subclasses raw, so the StrEnum `phase` comes back
  as a plain str: re-type through the per-key adapters, add an E2E on
  `PostgresSaver`, and take a release at least two weeks old (3.2.0 adds
  psycopg-pool and orjson). The sqlite saver is untested.
- **LFS and submodules (Step 5)**: `worktree add` leaves LFS pointers;
  `unshare -rn git lfs checkout` restores them offline from the shared
  `.git/lfs`, and LFS paths must be read-only to trials. Submodules are not
  initialised.
- **Dependency shadowing**: a trial adding `numpy.py` under a module root is an
  accepted limitation covered by human review; it matters more once Step 3b adds
  packages.
- **`ledgerclose`'s two hot spots stress different hardware.** `pop(0)` on a
  60,000-item list is memory-bandwidth bound, the window maximum is compute
  bound, so their ratio varies about tenfold between machines (16:1 in the
  Lead's container, close to 1:1 on GitHub runners). The guard
  `test_a_fix_that_leaves_one_hot_spot_falls_short` is machine-independent since
  2026-10-24: each partial fix must stay at least 2x slower than the full fix
  measured in the same run (measured minimum 3.2x). What remains: the live
  hard-corpus scoring's known-fix rule still compares against the absolute
  `fix_gain`, so on a memory-slow machine a settle-only fix of `ledgerclose`
  would be credited as the full fix. Follow-up: rebuild the repository with two
  hot spots of the same kind (both C-level loops over Python objects), keeping
  its multi category. Owner: Step 3's corpus rework (Wave 2, V3).
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

| Step | Lead time                                                                    | CI-red pushes                                                                                         | Rework commits                     | Reverts |
| ---- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------- | ------- |
| 0    | ~2 h                                                                         | 0                                                                                                     | 0                                  | 0       |
| 1    | ~4.5 h                                                                       | 2 (GHA cache; README format)                                                                          | 6 (regroup, 5 review)              | 0       |
| 2    | ~60 h (2026-10-21 18:18 to 2026-10-24 ~07:00, Window 0 experiments included) | 4 (`dbec415` Python 3.10 on the runner, `3b2ffee`, `92cefe7`, `a02e55e` the orderlookup timing floor) | 28 `fix` commits of 116            | 0       |
| W0   | ~2 days (2026-10-23 to 2026-10-25), 52 live runs, $77.78                     | 0                                                                                                     | 4 (lint of fixtures, review fixes) | 0       |
| 3 W1 | ~36 h (spec 2026-10-24 08:00 to U27 2026-10-25 20:11 UTC; build ~11.5 h)     | 2 (`6342eca` macOS interpreters, `60cee15` graphwalk at the floor)                                    | 2 (`f1080dc`, `3e04294`) of 27     | 0       |

Step 3 Wave 1: the build ran from U5 (08:41) to U27 (20:11 UTC) on 2026-10-25,
U1 on 2026-10-24. The CI-red pushes were the macOS job missing `python3.9` and
`3.10` for U4's template tests (fixed in `f1080dc`) and graphwalk's CI baseline
at the corpus floor (fixed in `3e04294`); review fixes landed inside each unit's
own commit, so they are not counted as rework.

## Lessons (retro per step)

### Step 3 Wave 2 (so far)

- **A timing bar must sit well clear of what it separates, measured several
  times first.** Four guards (ledgerclose, the decoy, the reference fix,
  parcelindex) were set from one or two runs and failed the Lead's gate on noise
  alone. **Change:** a new corpus bar is set only after at least three runs per
  side under CPython 3.11 and 3.13, with about ten points (or 2x) of margin from
  each side, and compared copies are timed in turn.
- **A usage limit can stop workflows mid-edit.** Every finished agent result
  came back from the cache on resume. **Change:** each resumed fix agent first
  inspects its files for half-applied edits; the gate script starts Postgres and
  holds a lock so two gates never share the checkout.

### Step 3 Wave 1 (2026-10-24 to 2026-10-25)

Each lesson ends with what it changes: in `CLAUDE.md` ("Builders in a shared
worktree", 4.4.0) or in the builder rules every brief carries.

- **Units ran 2-6x over their rows, and the tests were the overrun.** Changed
  lines per commit (added + removed, tests and fixtures included; `src` in
  brackets) against the spec's row:

  | Unit | Row  | Actual      | Unit | Row | Actual      |
  | ---- | ---- | ----------- | ---- | --- | ----------- |
  | U1   | ~200 | 885 (64)    | U13  | 300 | 1,529 (0)   |
  | U2   | 330  | 830 (337)   | U16  | 120 | 558 (93)    |
  | U3   | 50   | 135 (0)     | U17  | 300 | 999 (401)   |
  | U4   | 410  | 1,841 (616) | U18  | 330 | 926 (397)   |
  | U5   | 60   | 208 (24)    | U19  | 380 | 1,168 (452) |
  | U6   | 400  | 1,007 (445) | U20  | 330 | 593 (194)   |
  | U7   | 250  | 684 (185)   | U21  | 250 | 712 (251)   |
  | U8   | 380  | 722 (215)   | U22  | 250 | 544 (147)   |
  | U9   | 200  | 500 (113)   | U23  | 380 | 796 (304)   |
  | U10  | 280  | 856 (235)   | U24  | 260 | 858 (306)   |
  | U11  | 360  | 2,051 (737) | U25  | 340 | 1,000 (382) |
  | U11a | -    | 132 (0)     | U27  | -   | 741 (199)   |
  | U12  | 300  | 953 (0)     |      |     |             |

  The 25 units changed about 21,200 lines against about 6,500 planned (3.3x),
  but their `src` came to about 6,100: the rows held roughly for source and the
  tests ran 2-3x the source, as a first-principles test plan (every refusal,
  bound and fallback pinned) implies. No Builder stopped at the cap as the rules
  ask; U4 and U6 also skipped the red run of their first fix. **Changes:** a
  unit row states source and test lines separately; the ~400-line cap applies to
  source; a Builder stops and reports when its source passes 1.5x its row, and
  every fix round shows its own red run.

- **A shared `.coverage` file gave a false 66 %.** Concurrent Builders wrote one
  coverage data file in the shared worktree, so a gate read another's partial
  data. **Change:** each Builder sets a private `COVERAGE_FILE` (in the
  scratchpad, named for the unit).
- **Repo-wide `ruff format` touched other Builders' files.** U10 and U11 each
  ran `ruff format .` once; the change was formatting only, but it rewrote work
  in progress that was not theirs. **Change:** a Builder formats only its own
  files and runs the repo-wide check with `--check`.
- **A mutation script in the shared worktree fed mutated code to other runs.**
  U27's reviewer mutated files in place while other Builders' suites ran.
  **Change:** mutate scratch copies only; the Lead's clean-copy gate is the
  guard.
- **`PYTHONPATH` does not reach a mutated copy.** `pyproject.toml` sets pytest's
  `pythonpath = ["src"]`, which beats `PYTHONPATH`, so a `PYTHONPATH=<copy>`
  mutation run tested the real `src` and its "survived" list was invalid.
  **Change:** run mutations with `-o pythonpath=<copy>/src` plus a canary
  mutation that must be killed; a mutation claim without its canary is not
  evidence.
- **Missing-module reds prove nothing about a protection.** U19's red run failed
  only on the missing module, and 10 of 12 security mutations survived its first
  tests (security review S3). **Change:** every red run shows at least one
  assertion failure, and a security unit shows a red for each protection (remove
  it, the named test fails).
- **A spec rule with no unit row is never built.** D37 named
  `quality_data_reference` and section 4.6 its failure mode, but no section 7
  row owned it; U25's security review found the gap, and the Lead assigned U27.
  **Change:** before a build starts, the Lead maps every rule in the decisions,
  the failure-mode table and the security table to the unit that builds it, and
  the spec's Reviewer checks the map.
- **Timing guards need about 2x margin, measured on CI.** graphwalk's baseline
  ran 0.296 s on a CI runner against the guard's 0.30 s floor (`60cee15`), and
  `textindex`, `tokenparse` and graphwalk all flaked near their limits.
  **Change:** a corpus or timing guard's floor sits at about half what CI
  measures (or its fixture is sized to give that), checked on the first CI run.
- **Concurrent Builders make timing guards unreliable locally.** With four
  Builders on 4 cores (load about 7), `textindex`'s gain fell to 0.268 against a
  0.3 bar, and `tokenparse` and two Step 2 E2E tests failed once each; all
  passed alone and on CI. **Change:** a Builder reports a timing failure under
  load as such and runs its own tests; the Lead's sequential clean-copy gate and
  CI decide.
- **The local gate ran a different Python from CI.** The workload's `python` is
  the first on PATH, and `uv run` puts the service's venv first: 3.13 here, 3.11
  on CI. E3-H's baked table, a 2,500-item list literal, raised peak RSS 3.5 %
  under 3.13 but over the 10 % memory guardrail under 3.11, so CI rejected it on
  the first look (`b7df752`). Under 3.11 locally the old test failed the same
  way and the fixed one (one string literal, `list("0101...")`) passed.
  **Change:** a memory-sensitive fixture is checked under 3.11 too, with
  `PATH=<dir with python -> 3.11>:$PATH .venv/bin/python -m pytest` (not
  `uv run`); a fixture keeps memory-heavy constructs out of edits that are not
  about memory.

### Window 0 (live experiments, 2026-10-23 to 2026-10-25)

- **Every verdict goes into the cost-table notes from the first run.** Three
  runs (E7, E8b, the first E6) put their answer only in the job summary or a
  capped table cell, which the Lead cannot read; about $3.50 bought results that
  were later read only partly. Since `7dd6c9c` every suite notes each verdict
  through `run.note()`.
- **Never rerun only to recover logging, and stop at the first external 429.**
  E2 was dispatched three times against arXiv's runner block; the second 429 was
  already conclusive.
- **A saturated test set can only show harm.** The first A/B (E5) ran where
  blind generation already won 44/44; the real-code A/B with 36 pairs was the
  test that could decide. Check the baseline rate before pre-registering a rule
  on a set.
- **Canary one dispatch before fanning out.** The OSS A/B ran one library first;
  the nine others went out only after its log showed real work. The same habit
  caught a second-set A/B that would have run nothing.
- **Labels must be made blind by construction.** The first grader-agreement
  labeller saw the verdicts because a filter missed the log's escaping; the
  rerun read a file checked to hold no verdicts.
- **Merge PRs one at a time, each with its own green CI on `master`**
  (Dependabot, 2026-10-24): back-to-back merges let concurrency cancel the
  intermediate runs, so no single merge was proven green.
- **An interrupt stops background builders for good.** Three builders were lost
  to one interrupt; their partial files and briefs let new builders finish them,
  so briefs are now kept in the session scratchpad.
- **Easy corpora saturate fast.** The discovery corpus, the hard corpus, the
  easy and then the hard heal set were all solved; real libraries were the only
  sets that separated arms or models.

### Step 2

- **Cost caps need a stated rule in the brief.** Two of the nine experiment
  units first shared one cap across requests whose worst cases summed to 3x the
  cap (the later arms would have been refused, biasing the data), and the
  harness's first bound missed fetched PDFs and the server-tool loop. Every
  brief that spends now states: a shared run's cap is the sum of its requests'
  worst cases, computed with the real estimator and asserted by a guard.
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
  removal, an ungated paid key in CI. Keep the security lens on every unit that
  touches a trust boundary (all of those did).
- **A review that returns nothing must halt the workflow.** A reviewer that died
  returned null, which read as "no findings" and skipped the fixer;
  `build-wave.workflow` now stops the unit and names the missing lens
  (`80c1a8d`).
- **Write the decisions down where they will survive.** The spec and the Lead
  notes lived in `.claude/handoff/`, deleted at the close-out; the Decisions,
  Known gaps and Next sections carry them (24 items found only there were moved
  on 2026-10-24).
- **Reviews missed what sits between the units.** The first live run sent a
  placeholder key: the suite's autouse `reset_environment` replaces
  `ANTHROPIC_API_KEY` for every test, and every dry run and review swapped the
  key itself, so none exercised the real wiring. The root container hid that a
  non-root user cannot open a mode-000 directory (CI caught it). Builders and
  Reviewers now get a SEAMS checklist in `build-wave.workflow`: read the
  fixtures above the tests, swap only the wire in a dry run, run file-mode code
  as a non-root user, name what only CI, macOS or a live run can prove.
- **A gate with a failing test is not a pass**, even when the failure is
  machine-dependent (the user's correction at the close-out). Guards that
  compare timings across machines compare within one run: a ratio against a
  reference measured side by side cancels the hardware, a fixed threshold does
  not (`ledgerclose`, `9db3c77`).
- **Move decisions out of handoff notes as they are made.** The close-out audit
  found 24 decisions and verified facts that lived only in `.claude/handoff/`; a
  running "decisions to STATUS" check at each wave end would have caught them
  while fresh.
- **What CI does not echo, the Lead cannot read.** The job summary is not
  returned by the API and the runner log can drop a chunk, so every verdict a
  later step depends on goes to the log and into the always-printed cost-table
  notes.
- **A workflow's token guard counts the turn, not the workflow.**
  `budget.spent()` started at 6.7M in the Step 3 design run, so the first
  attempt ran no agent; guards take the spend at the start and compare the
  difference.
- **Spend review effort where the risk is.** One correctness Reviewer per unit,
  a security Reviewer only where the unit touches a trust boundary, reviews
  scoped to the diff and its direct callers and fixtures, the cheap local matrix
  (non-root, Python 3.11, Postgres up) before any review, and one Verifier round
  per risk area rather than repeated full sweeps.

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

- Wave 2 batch 3 reviewers' open nits: N2's line-by-line fallback (a hot
  function that no longer tokenizes) can let a docstring-only quote ground an
  idea, against D50 (b); N0b's re-edit reuses the D14 notice that says the
  change "failed when run", though it only failed to parse; N3b leaves `novel`
  candidates outside the quotas with no cap (decided in N4a, which owns the
  totals).
- `[tool.hatchling.build.targets.wheel]` in `pyproject.toml` is a dead key
  (hatch reads `[tool.hatch...]`); `playbook.json` ships anyway.
- `test_the_blind_hypothesis_states_an_intent_never_a_fix[runtime]` is flaky
  under `-x -n 2`.
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

From Step 3 Wave 1 (2026-10-25):

- `optimization/anticheat.py`'s tripwire (U27) reaches git through the private
  `GitWorkspace._git` for its `-U0` patch; add a public
  `GitWorkspace.stream_patch` in `git.py` and use it.
- The L0 noise suite's `AaRunner` (`tests/live/noise.py`) uses
  `GitBaselineRunner`'s protected members; give `GitBaselineRunner.calibrate` a
  way to return its rows, or a public A/A block method.
- `_Freezing`, a private protocol, is declared twice (`orchestrator/factory.py`
  and `orchestrator/nodes.py`); one shared declaration.
- `git.py`'s `_OVERRIDE_KEYS` does not list `diff.<driver>.binary`. On git older
  than 2.40 (no `--attr-source`) a committed `.gitattributes` `binary` or
  `-diff` attribute reaches the tripwire's slow path; its fail-closed rule for
  binary patches covers it today. Consider the key in a `git.py` cleanup.
- `tests/live/discovery.py`'s `model_settings` is a one-line delegate to
  `role_settings` kept for its callers (`test_discovery_guards.py`,
  `discovery_escalation.py`, `discovery_ab.py`, `build_improve.py`,
  `test_sweep_live.py`); migrate them and delete it.
- `procrun.run_once` could take an optional `stdin_path`, so the quality scorer
  (U19) can drop its stdin shim.
- Source modules have grown past the ~400-line cap again (lines on 2026-10-25):
  `nodes.py` 3,346, `trial_runner.py` 1,242, `models.py` 1,109, `git.py` 948,
  `judges.py` 880, `anticheat.py` 853, `measure.py` 698, `editor.py` 583,
  `editor_tools.py` 567, `factory.py` 566, `config.py` 546, `retry.py` 516,
  `quality.py` 438. Split `nodes.py` first (the report, the baseline helpers and
  the verdict helpers are separable) when Wave 2 or 3 touches it.

---

## Useful Commands

```bash
pnpm stage-gate                               # full gate
pnpm stage-gate:quick                         # quality only
cd services/python_agents && uv run pytest    # Python tests
pnpm test                                     # TypeScript tests
docker compose -f docker-compose.dev.yml up -d
```
