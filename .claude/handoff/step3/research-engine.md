# Step 3 design: engine wiring and the engine self-retry

Track: engine wiring (generator, matcher, research node), the bounded self-retry, the technique id mapping, an offline discovery eval and the combine-failed lesson. Base: `claude/step3-research` at `ea891e6` (Step 2 head). Paths are relative to `services/python_agents/src/autonomous_ai_agents/` unless they start with `tests/` or `infrastructure/`.

## Findings (verified)

### (a) Hypotheses node, context, factory, ranking

- `NodeContext` (`orchestrator/nodes.py:181-237`) is frozen; `candidates`, `hotspots` and `techniques` stand in for research (line 203). It refuses duplicate ids and any id that fails `validate_run_id` (lines 217-228), because the id names a trial branch.
- `research` (`nodes.py:1413-1427`) is a stub: it copies `ctx.techniques` into the state and sets `papers=[]`.
- `hypotheses` (`nodes.py:1429-1460`) drops candidates already seen, reads `list_lessons(project.id)`, runs `rank_hypotheses`, slices to `max_hypotheses_per_round` (3) and appends them as `proposed`. It spends nothing and never sees `hotspots`, `understanding` or `objectives`.
- The router (`nodes.py:1919-1936`) stops when every `ctx.candidates` id has been trialled (line 1932). **Once candidates live in the state, this line has to read them from there**; otherwise a run with no caller candidates goes to combine after round 1.
- The trials node offers each trial `remaining = max_cost_usd - cost_usd` (`nodes.py:1508`, passed at 1478) and stops below `ctx.min_trial_budget_usd`. The factory sets that to `min_trial_budget()` (`factory.py:111-116`): one worst-case editor request.
- The pattern for a paid node is understand (`nodes.py:1262-1286`). It builds `Budget(cap, spent, tokens)` from the state; an `EngineError` ends the run with `keep_progress`, anything else is soft. `_charged` (`nodes.py:576-587`) takes the larger of the reported spend and the budget's record.
- `build_context` (`factory.py:303-395`) builds one transport from `ENGINE_MODEL` plus fallbacks (`clients/cost.py:110`), shared by the understander and the editor. It passes `techniques=()` and has no generator or matcher.
- `generate_hypotheses` (`optimization/generate.py:189-255`) takes a transport, a `Budget`, the project, the understanding, the hotspots, one `Objective`, the techniques, `n` (at most 20), the effort and `max_tokens` (default 16000). It returns hypotheses with fresh uuid4 ids. `hotspot_ids` resolve only from the hotspots shown (lines 360-384), and `technique_id = technique.id` (line 314).
- `match_techniques` (`research/playbook.py:350-402`) returns `TechniqueMatch(slug, fit, justification_summary, unmet_preconditions)`; with no techniques it sends nothing (line 375). E5 arm B (`tests/live/discovery_ab.py:178-209`) matches with k=3, maps slugs to cards with `{t.id: t ...}`, then generates from those cards only (n=3, max_tokens 8000).
- `ranking.py:53-60`: `score = expected_gain * provability * (1 - risk) * (1 + boost)`. The boost is ±0.1·weight per keep or reject lesson matched by `technique_id` or `hypothesis_id`, clamped to ±0.5.
- `common/config.py` has no generator or matcher keys. Its validators (lines 319-353) check pricing and effort only for `ENGINE_MODEL`, its fallbacks and `TRIAGE_MODEL`. Sonnet 5.5 is priced (line 94) and accepts every effort level (line 55).
- `carry()` (`tests/live/discovery.py:409-420`) keeps only `efficiency` hypotheses: any other class pauses the run at `approval_gate`, which no unattended run can answer. The wired engine has the same problem.

### (b) Where a trial failure is detected today

- The editor never runs code. `ClaudeEditor.edit` (`execution/editor.py:217-239`) returns an `EditResult` with a `stop` reason. It sees no execution errors.
- A crash surfaces in `GitTrialRunner._attempt` (`execution/trial_runner.py:502-587`). The steps are: edit (line 524), capture, anti-cheat, commit (line 565), then `_measure`. `except RunFailure as failure: return _failed(trial, failure.reason)` (lines 582-583) records the failure.
- `measure.launch` (`execution/measure.py:233-260`) turns a non-zero exit into `RunFailure("...: the command ended with exit N: <last stderr line>")`. Only the last line of `RunSample.stderr_tail` survives (lines 256-259). Timeouts, floods, missing isolation and report problems are also `RunFailure`s (`procrun.py:243-289`), and nothing marks which kind is which.
- The test suite runs with `check_exit=False` (`measure.py:577`). A failing suite becomes `tests_passed = 0.0`, which is a judge input, not a `RunFailure`.
- Any re-commit must stay one commit whose parent is the base. The combiner skips anything else as `NOT_A_CHILD` (`execution/combine.py:246-252`). `GitWorkspace.commit` uses the worktree's HEAD as parent (`execution/git.py:765-774`), so a naive second commit would have the first one as parent.
- `check_capture` flags every changed path that is missing from `EditResult.written` as `unrecorded_write` (`optimization/anticheat.py:450-452`). A retry's diff against the base also contains the first attempt's writes, so the two `written` maps have to be merged.
- The trial's `Budget(budget_usd)` (`trial_runner.py:443`) is passed to the editor. `call()` runs `budget.check(estimate)` before every attempt (`clients/transport.py:331`). A retry on the same `Budget` is therefore gated per request automatically.

### (c) Technique ids

- The playbook enforces `id == slug` (`research/playbook.py:148`; 36 cards, e.g. `set-membership-test`). That id flows to `Hypothesis.technique_id` (`generate.py:314`), then `Lesson.technique_id` (`learning/lessons.py:128`), then the ranking's equality match (`ranking.py:33-36`).
- `003_engine.sql:294-296` defines `techniques.id UUID` and `slug VARCHAR(100) UNIQUE`. It also defines `hypotheses.technique_id UUID REFERENCES techniques(id)` (line 369) and **`lessons.technique_id UUID`** with no FK (line 418).
- `PostgresRepository.save_lesson` binds `_optional_uuid("lesson.technique_id", ...)` (`persistence/postgres.py:411`). That raises `InvalidRecordIdError` for a slug, and the existing test `tests/persistence/test_postgres.py:193-195` pins exactly this refusal for `"set-membership"`.
- So **the first playbook keep on Postgres would fail the learn node.** The STATUS line "Playbook slugs map to `techniques.slug`, so no migration is needed" covers the `techniques` table but misses `lessons`. Nothing writes the `hypotheses` table (no `INSERT INTO hypotheses` in `postgres.py`), so only the lessons table is affected today.

### (d) Grader and recordings

- `grade()` (`tests/live/discovery_grader.py:233-283`) needs a `LiveRun`: it calls `run.transport(cfg)` and reads `run.records`. Its parsing is already testable offline with `ScriptedTransport` (`tests/live/test_discovery_guards.py:491`).
- `SweepRow` (`tests/live/discovery_sweep.py:161-190`) records counts and hits, **not hypothesis texts or replies**. The E3 rows cannot be replayed. Whether CI artifacts kept the wire captures is unverified.

### (e) Combine failure and lessons

- `combine_kept` (`orchestrator/combine_node.py:151-188`) keeps verdict ids only for a re-test that held. With one kept change there is no fallback (the OSS `sortedcontainers` case).
- `learn` (`nodes.py:1862-1891`) builds lessons from `decided_verdicts`, ignoring `state["combination"]` and `kept_verdict_ids`. Every lesson gets `weight=1.0` (`lessons.py:59`).
- `Combination` (`common/models.py:737-752`) records the final `applied_trial_ids`, every `skipped`, `fallback_trial_id` and `holds`. It does not record the greedy applied set when a fallback ran, but that set can be derived.
- `chk_lesson_weight CHECK (weight > 0)` (003) allows a reduced weight with no schema change.

## Proposed interfaces

### Unit W1: wire the generator and matcher (about 350 lines plus tests)

- **State** (`orchestrator/state.py`, every key set in `initial_state`):
  - `candidate_pool: list[Hypothesis]`: ideas not yet sliced into a round (a plain key).
  - `technique_matches: list[TechniqueMatchRecord]`: a new `EngineModel` added to `ENGINE_MODEL_CLASSES` for the report. The `TechniqueMatch` dataclass is not on the serde allowlist.
  - `generator_calls: int`.
- **NodeContext** gains three fields. Each `None` keeps the Step 2 behaviour (the seam rule in the `nodes.py` docstring).
  - `generator: HypothesisSource | None`, a protocol in `execution/protocols.py`: `generate(*, project, understanding, hotspots, objective, techniques, lessons, avoid_titles, n, budget) -> GenerateResult(hypotheses, notes, cost_usd, tokens_used)`.
  - `matcher: TechniqueMatcher | None`: `match(*, understanding, hotspots, techniques, k, budget) -> MatchResult(...)`.
  - `research_policy: ResearchPolicy`: `retrieval` (`blind`/`playbook`/`matched`), `papers` (`off`/`deprioritised`/`on`), `generated_classes` (default `{efficiency}`), `n`, `k`, `max_calls`.

  The Claude-backed versions live in a new `optimization/hypothesis_source.py`, thin wrappers that each own a transport.
- **Research node.** Under `matched`, it runs the matcher over `ctx.techniques` (the factory's `load_playbook()`, plus paper cards when `papers != "off"`) and writes the matched cards and `technique_matches`. Under `playbook` it writes all cards; under `blind`, none. Matcher failures (budget, config, unusable reply) are soft: a `research_unavailable` note, then blind. Spend goes through `_charged`.
- **Hypotheses node.**
  1. The pool is `candidate_pool` plus unseen `ctx.candidates`.
  2. It generates only when the pool has no untried candidate, calls are left, and `remaining - generator_worst >= min_trial_budget_usd`, so generation never takes the money of the trial it feeds.
  3. Inputs: hotspots, understanding, `objectives[0]` (define always sets one), `state["techniques"]`, the project's last 20 lessons, and the titles already tried as `avoid_titles`.
  4. Classes outside `generated_classes` are dropped as `parked_hypothesis` notes, which are proposals in the report. Duplicate titles are dropped and every id is re-checked with `validate_run_id`.
  5. It ranks the pool, slices 3 into the round and returns the rest as `candidate_pool`. Failures are soft (`generate_unavailable`).

  Generated `hotspot_ids` name this run's hotspots, so `_brief_hotspots` (`nodes.py:342-355`) no longer falls back to the top 5.
- **Router** (`nodes.py:1932`): rounds continue while the pool or `ctx.candidates` has an untried idea, or generation is still possible. `max_rounds` still bounds the loop.
- **`generate_hypotheses`** gains `lessons` and `avoid_titles`, rendered as fenced untrusted lines. A line holding a boundary token is withheld (`_fenced_line`).

**Settings** (`common/config.py`), with validators extended to the generator and matcher models and their efforts:
- `GENERATOR_MODEL="claude-sonnet-5-5"`, `GENERATOR_EFFORT="medium"`: E3 measured 22/22 hit@5 at 0.014 USD a repo and no false big-gain claim on the controls. Opus high returned nothing twice, and every Opus arm claimed a gain on `lettertally`.
- `GENERATOR_FALLBACKS=False`: E3 ran with none, and an Opus 4.8 fallback roughly triples the worst case, from about 0.21 to about 0.65 USD (computed from the prices, not measured).
- `GENERATOR_N=5`, the value E3 measured. Three go to a round and two seed round 2 at no extra cost.
- `GENERATOR_MAX_TOKENS=16000`, `GENERATOR_MAX_CALLS=2`.
- `MATCHER_MODEL="claude-sonnet-5-5"`, `MATCHER_EFFORT="medium"`, `MATCHER_K=3` (E5 arm B).
- `RESEARCH_RETRIEVAL` and `RESEARCH_PAPERS` (below).

**Factory:** `build_context` gains:
- `generator_transport: LLMTransport | None` and `matcher_transport: LLMTransport | None`, defaulting to `transport_factory(model_settings(settings, GENERATOR_MODEL, fallbacks=GENERATOR_FALLBACKS))` and the same with `MATCHER_MODEL`. These are built only when a key is set, like `engine_transport` (`factory.py:119-127`). This promotes `tests/live/discovery.py:163-170` (validated copy) to `common/config.py`.
- `techniques: Sequence[Technique] | None`, defaulting to `load_playbook()`.
- `research_policy: ResearchPolicy | None`.

**The A/B result sets a switch; nothing in the code assumes the outcome.** The Lead edits the defaults after E5:

| E5 result (c − b) | `RESEARCH_RETRIEVAL` | `RESEARCH_PAPERS` |
| --- | --- | --- |
| ≥ 3 | `matched` | `on`: the paper cards join `ctx.techniques` before matching |
| < 3 | `blind` or `playbook` (Lead's call; blind is the measured, cheaper arm) | `deprioritised`: paper cards are never loaded into a run; the paper units go behind the playbook, lessons and evolution |

Until E5 lands, the shipped default is `blind`/`off`, the only arm measured end to end (hard corpus 10/10). Tests run both retrieval modes.

### Unit W2: bounded self-retry (about 250 lines plus tests)

- **Detection.** `procrun.RunFailure` gains `kind` (`exit`, `timeout`, `flood`, `isolation`, `report`, `path`, `other`) and `crash: CrashReport | None`. `measure.launch` (lines 255-259) fills them from `stderr_tail`. A `CrashReport` holds the exception type, at most 20 frames inside the worktree, and a message of at most 300 printable characters.
- **Classification.** `execution/retry.py: classify(failure) -> RetryReason | None` accepts only `kind == "exit"` with a parsed Python traceback.
  - Syntax, import, name and type errors (`SyntaxError`, `IndentationError`, `TabError`, `ImportError`, `ModuleNotFoundError`, `NameError`, `UnboundLocalError`, `TypeError`, `AttributeError`) send back the type, the message and the frames.
  - Any other crash sends the type and frames only. The message is withheld because it may carry workload data, and the editor never sees workload output.
  - Never retried: timeouts, signals, floods, isolation or report failures, `AssertionError`, the test suite, nondeterminism, verdicts and timings. The structure enforces the last two: the retry lives in `_attempt`, which returns before the judges run.
- **Feedback.** `EditTask` gains `feedback: TrialFeedback | None`. `_task_text` adds an engine notice ("your previous change, still in the worktree, failed when run; fix that error, keep the approach"), with the crash report fenced as untrusted data (`_holds` applies).
- **Flow.** The retry runs in `_attempt` on an accepted failure, while `attempts <= EDITOR_FIX_RETRIES` (default 1, at most 2) and `budget.remaining >= retry_floor_usd` (the factory passes `min_trial_budget()`):
  1. Edit again on the same `Budget`, on the worktree that already holds attempt 1.
  2. Merge the `written` maps, with the editor's file and byte limits enforced over the union.
  3. Re-capture the full diff against the base and re-run every anti-cheat check.
  4. Commit with a new `GitWorkspace.commit(..., parent=base)` keyword, so it stays one child of the base. Move the ref with `update_ref(own_ref, commit2, commit1)` and set `progress.moved`.
  5. Measure again.

  An unaffordable or failed retry returns the first failure with a note, and is never `TrialUnaffordable`. `Trial` gains `attempts: int = 1` and `retry_reasons` (serde-safe defaults), listed under "Run conditions".
- **Cost.** One more edit session on the cached system prompt and tool. A whole run costs about 0.04 USD on Sonnet low (E8a) and about 0.10 on Opus (E0), so a retry costs at most about one trial's edit. Every one of its at most 16 requests is checked before it is sent (`call()`), and the re-measurement adds wall time.

### Unit W3: technique id mapping (migration 005)

**Decision:** the slug stays the engine identity (`Technique.id == slug`) and the database maps it.
- `infrastructure/schema/005_lesson_technique_slug.sql` (idempotent):
  - `ALTER TABLE lessons ADD COLUMN IF NOT EXISTS technique_slug VARCHAR(100)`;
  - a `DO`-guarded `CHECK (technique_slug ~ '^[a-z0-9][a-z0-9-]{1,62}$')`;
  - a comment.
- `save_lesson` (`postgres.py:402-420`) validates `lesson.technique_id` against `playbook.SLUG_PATTERN` (otherwise `InvalidRecordIdError`, before connecting). It writes it to `technique_slug`, and writes `technique_id = uuid5(TECHNIQUE_NAMESPACE, slug)`. That UUID is deterministic, so seeding `techniques` later with the same uuid5 makes it a valid join key and FK target.
- `_LIST_LESSONS` returns `COALESCE(technique_slug, technique_id::text) AS technique_id`.
- `hypotheses.technique_id` follows the same uuid5 rule when that table is first written (not in this step).
- Why not a lookup in `techniques`: it needs the table seeded before every save, and a missing row silently turns a slug into a UUID that never matches in `ranking.lesson_matches`.
- **`tests/persistence/test_postgres.py:193-195` changes meaning:** a slug is accepted, and a non-slug such as `"Set Membership"` is refused. This is a deliberate behaviour change of a pinned test and must be called out as such, not counted as a weakened test.

### Unit W4: discount a keep whose combine failed

`learn` derives a factor per kept verdict from `state["combination"]` and `kept_verdict_ids`. `lesson_from_verdict` gains `weight: float = 1.0` and `note: str | None`.

| Case | weight | context tag |
| --- | --- | --- |
| Delivered (in `kept_verdict_ids`) | 1.0 | `combine:held` |
| Skipped for conflict or nothing left (in `combination.skipped`) | 1.0 | `combine:skipped` |
| Applied in a failed greedy re-test while another fallback held | 0.5 | `combine:unconfirmed` |
| Not reproduced: in a failed re-test, no fallback held (`sortedcontainers`), or its own fallback failed | 0.25 | `combine:not_reproduced` |
| No combiner (`combination is None`) | 1.0 | none |

The outcome stays the verdict's, and the text gets `(combine: not reproduced)`. No schema change: weight > 0 holds. This amends decision 25 and needs a STATUS Decisions row with its reason: a single noisy win should not count as a full keep for the next ranking.

## Tests that would prove it

- **W1.** In `tests/orchestrator/test_nodes.py`, with a recording fake generator:
  - one generation on an empty pool, receiving hotspots, understanding, `objectives[0]`, techniques, lessons and `avoid_titles`;
  - behaviour and novel parked; 3 sliced, 2 kept in the pool; no regeneration while the pool has an untried candidate;
  - generation skipped when `remaining - worst < min_trial_budget_usd`; a generator `BudgetExceeded` is soft and its spend charged;
  - `generator=None` gives exactly the Step 2 output, with every existing test unchanged.

  Also: a router test (empty `ctx.candidates`, non-empty pool → `"hypotheses"`); the research node in all three modes, with matcher failure falling back to blind; fenced lessons in `test_generate.py`; the settings validators; the generator chain in `test_factory.py`; and `tests/e2e/test_step2.py` with `candidates=()` and a scripted generator reply reaching a delivered branch.
- **W2.**
  - `test_measure.py`: `CrashReport` parsing; out-of-repo frames dropped; message capped.
  - `test_retry.py`: the classification table; timeout, signal, `AssertionError` and the suite give `None`.
  - `test_trial_runner.py`, next to line 941: a SyntaxError followed by a fixing edit gives `attempts == 2`, one commit whose parent is the base (`_unfit` passes) and no `unrecorded_write`. Also: an unaffordable retry keeps the first failure; the retry cap holds; an aborted retry restores the own ref; the feedback carries no stdout and no timing.
  - `test_editor.py`: the feedback is fenced and a token in it is refused.
- **W3.** `test_postgres.py`: a slug round-trips; a non-slug is refused before connecting; a legacy UUID row reads back; 005 runs twice cleanly.
- **W4.** `test_lessons.py` and the learn tests: each table row, and a ranking flip between a held and a not-reproduced technique.

**Offline discovery eval (W5, test-only):**
- Split `discovery_grader.grade` into `grade_with(transport, budget, repo, patches, hypotheses, cfg)`, which needs no `LiveRun`. `grade()` becomes a wrapper.
- Make the live sweep record the per-(repo, arm) raw generator reply JSON, the phase-1 hotspots (file, symbol, share), the objective and the grader reply.
- Commit a sanitised snapshot to `tests/fixtures/discovery_eval/<corpus>.json`, with a label per hypothesis keyed by sha256 of the normalised title and rationale, and with the ~10 hand labels from the grader-validation task.
- `tests/optimization/test_discovery_eval.py` (not live):
  - replays each recorded generator reply through `generate_hypotheses` on a `ScriptedTransport`, then through the wired hypotheses node's ranking and slice;
  - looks up labels and asserts hit@3 (the per-round slice) is at least the recorded baseline;
  - fails with "unlabelled: refresh in live-smoke" on an unknown key;
  - replays the recorded grader replies through `grade_with` and asserts the recorded hits (shuffle and id mapping).
- This catches regressions in validation, slug mapping, hotspot resolution, ranking and slicing. It cannot catch prompt changes; those need a live refresh, about 0.5 USD for the Sonnet-medium arm over 25 repos plus the grader.

## Risks and open questions

- **Approval stalls.** Unattended runs would stop on generated behaviour and novel hypotheses, so they are parked until the Step 4 CLI can answer the gate. The generator prompt forbids new dependencies, so 3b's `needs_package` parking set is empty today.
- **Constraints the wiring leaves to 3b.**
  - Same environment on both sides: baseline and trial environments are built from the same lockfile and differ only by the acquired package and its new dependencies. A resolver upgrade or downgrade of any existing dependency is a separate change, shown in the report and measured on its own. The delivered branch's report says the user must install the new dependency.
  - No wheel means ask: a package or transitive dependency available only as an sdist fails the automatic policy, because building runs code. It goes to the user, never to an automatic build.
- **3c reproducer integrity, and its interplay with W2.** The reproducer is written in a separate request before any fix is attempted, then frozen as a protected file. It must fail on the baseline N of N runs, and for the reported reason (same exception type and same frame or message). The fix's trial may not touch it, and the report shows it next to the fix. In a heal trial the reproducer's failure is the judge's input, so W2 must never retry on it: give the brief `retry_excluded_paths`.
- **Open questions.**
  - Expected-gain calibration: Opus inflated gains on controls. Cap generated gains at the card's value, or rank by model order plus lessons?
  - Novel lessons never match across runs (uuid4 `hypothesis_id`). Match them by normalised title within a project?
- **Retry and the budget.** A trial may spend the whole remaining cap, so a retry can starve later trials in its round. `EDITOR_FIX_RETRIES=1` and the floor bound this.
- **Lessons in the generator prompt.** They are fenced untrusted text and reach only the generator, never the editor.
- **Unverified.** The ~0.21/0.65 USD worst cases are hand-computed from prices, not `preflight_estimate`. It is unknown whether E3's CI artifacts hold replayable wire captures.
