# Step 3 spec: wired discovery, engine self-retry, review delivery (3b and 3c designed)

Base: `claude/step3-research` at `322f08f` (master holds Step 2). Built from
design A, with the blocking flaws in `judges.md` fixed, the recommended B items
grafted, every "missing from both" item decided or listed in §8, the user's
binding decisions (`user-decisions.md`) applied and the E5 result applied.
Paths are relative to `services/python_agents/src/autonomous_ai_agents/` unless
they start with `tests/`, `infrastructure/` or `.github/`. Every file:line cited
here was re-read at `322f08f`. Anything not re-read is marked **(not
re-read)**, and anything inferred is marked **unverified**.

**Revision 2 (critic fixes).** D13 sends a crash message only when it matches
a CPython template, and states what that proves (canaries in U4, E3-D, §5).
Also: E3-A made reachable, E3-E added; D7's negative cap (§4.2, U8); 005 equals
the id rule (D3, §3.5, U1); the "not re-tested together" caveat (§4.5, U11);
live caps from `ab_need`, rounded up (D2, §6, Q3); `NodeContext` owned by U2
(§3.4, §7); `env_baselines` (D27); the report fenced (D33, §5); blind
`techniques=()` (U10); Q3's skip option.

**About the A/B.** E5 is finished (GitHub Actions run 40063812021, 10.20 USD)
and applied: retrieval is off and no paper code is built. The "re-test" (D2,
L5) is a new, smaller, optional A/B on a corpus built in Wave 2, not a re-run.

---

## 0 Decisions

**D1. The A/B result is applied. No paper code in Step 3, and retrieval is off
by default.**

- `RESEARCH_RETRIEVAL` takes `blind` (default) or `matched` (built, tested
  offline, off).
- There is no `PAPER_PRIORITY` setting (nothing to switch).
- *Why:* the pre-registered rule (`tests/live/discovery_ab.py:117`,
  `MIN_DISCORDANT_LEAD = 3`) gave c − b = −3. B lost three tasks A won and won
  none A lost. Its gain was 5-11 points lower on four repositories where both
  won, and it cost 0.110 against 0.090 USD a win.
- Paper cards would reach the generator the same way, and are noisier.
  `matched` stays (about 200 lines) because D2 and a later flip need it.

**D2. Retrieval gets one re-test, on a set where blind generation does not
saturate. That re-test is the only path back to paper intake.**

- The instrument is the E5 suite itself (`tests/live/discovery_ab.py`), with two
  generalisations: the corpus is selectable (v1, v2, oss), and an A-only mode.
  The repository set is fixed today (`AB_REPOS = (*CORPUS, *HARD_CORPUS)`,
  `discovery_ab.py:115`).
- Order, cheapest first:
  1. Arm A alone on hard corpus v2 (L5a). If blind wins at least 90 % of the v2
     slowdowns, v2 is saturated: it is revised and arm B is not paid for. L5a
     re-runs once on the revised v2 (counted in §6's total); a second
     saturation ends the re-test, and retrieval stays off.
  2. Both arms on v2, 2 repetitions (L5b).
  3. Both arms on OSS, 1 repetition (L5c). Skipped when its 10 tasks cannot
     change the pooled decision.
- **The pre-registered pooled rule** is written to STATUS before L5b is
  dispatched. Over the v2 and OSS slowdown tasks, `c − b ≥ 3`, and B's false
  wins on controls must not exceed A's.
  - If it is met, `RESEARCH_RETRIEVAL` flips to `matched` (a one-line unit), and
    paper intake becomes a later conditional step (§7, P).
  - Otherwise, the playbook stays a test fixture and retrieval stays off.
- *Why:* blind generation won 44/44 in E5 (STATUS 2026-10-24), so E5 could
  detect harm but not help. A second suite costs about 8 USD, against tens of
  hours to build paper code.

**D3. First unit: the Postgres id fix. The id columns are widened, not mapped**
(user decision 3).

- The defect is wider than STATUS records. Three calls refuse a caller id such
  as `h1`:
  - `save_trial` (`persistence/postgres.py:368`), on `trial.hypothesis_id`;
  - `save_verdict` (`:376`), on `verdict.hypothesis_id`;
  - `save_lesson` (`:408-411`), on `hypothesis_id`, and on `technique_id` for a
    playbook slug (`tests/persistence/test_postgres.py:182-197` pins both).
- The trials node calls `save_trial` (`orchestrator/nodes.py:1544`) after
  `run_one` has spent, outside its `try`. A refusal therefore also drops that
  trial's cost from the failed state (no `keep_progress`).
- The fix:
  - Migration 005 turns `lessons.hypothesis_id` and `lessons.technique_id` into
    `VARCHAR(64)`, with a `CHECK` that encodes the engine's id rule exactly
    (`RUN_ID_PATTERN`, `state.py:64`: at most 64 characters, no `..`, no
    trailing `.lock` or `.`; §3.5).
  - The three save methods validate those fields with the engine's id rule
    (`validate_run_id`, `orchestrator/state.py:67-85`; slugs pass), instead of
    `_uuid` (`postgres.py:186-205`).
  - Engine-made ids (`lesson.id`, `project_id`, `verdict_id`) stay UUIDs.
  - The trials node wraps `save_trial` so that a raise keeps the round's
    progress.
- *Why not uuid5 (both designs):* ranking compares
  `lesson.hypothesis_id == hypothesis.id` and the technique ids by equality
  (`optimization/ranking.py:27-37`). A mapped UUID would need a second column
  per id to read the caller's text back, plus a namespace constant, and drift is
  possible.
  - Neither column has a foreign key (`003_engine.sql:417-418`), and the
    trial/verdict ids live in JSONB (`003:240-241`). The UUID type only asserts
    something false.
- The pinned refusal tests change meaning: `h1` and `set-membership` are now
  accepted, and `../x`, `a..b`, `Set Membership` and a 65-character value are
  refused, by the code before SQL and by the `CHECK` on a direct insert.
  This is reported as a deliberate behaviour change, not a weakened test.

**D4. A contracts unit (U2) comes right after U1, and carries no behaviour.**
Every new setting, state key, model field and protocol lands at once, with
defaults that reproduce Step 2. *Why:* `config.py`, `models.py`, `state.py` and
`serde.py` are shared by every later unit. Freezing them lets Builders work on
disjoint files, and the serde reflection test runs once.

**D5. The generator is Sonnet 5.5 at medium effort, with no fallbacks, `n=5`
and at most 2 calls a run. The matcher (off) is Sonnet 5.5 at medium with
`k=3`.**

- *Why:* in E3 this arm hit 22/22 hit@5 at 0.014 USD a repository, with no
  big-gain claim on a control.
- Opus at high returned nothing twice; Fable matched Sonnet at 7x the cost.
- The second call covers an empty reply (design A Q6) in the next round.

**D6. The candidate pool lives in the state, and the router reads it.**

- Today the router ends a run once every `ctx.candidates` id is trialled
  (`nodes.py:1931-1933`). `all(...)` over an empty tuple is true, so a run with
  no caller candidates stops after round 1.
- The router now continues while an untried idea is in `ctx.candidates` or
  `candidate_pool`, or while generation is still possible.
- *Why:* a resume must not pay for generation twice, and the router must see
  what the generator produced.

**D7. Discovery spend is bounded by a narrowed `Budget`, not by a pinned
estimate.**

- The generator and the matcher receive `Budget(cap_usd=d, spent_usd=cost_usd)`,
  where `d = min(max_cost − min_trial_budget_usd, cost_usd + DISCOVERY_MAX_SHARE
  · max_cost − discovery_cost_usd)`.
- `call()`'s own pre-send check (`clients/transport.py:331`, `Budget.check`)
  refuses any request whose worst case would cut into one trial's reserve or
  pass the 25 % share. The refusal is a soft `discovery_unaffordable` note.
- If `d ≤ cost_usd` (the run cap is below one worst-case editor request plus
  what is spent, a state the trials node tolerates by starting no trial,
  `nodes.py:1508-1510`), the node sets `discovery_exhausted` with the same note
  and sends nothing. It never constructs the `Budget`, because a negative cap
  raises `ValueError` there, not `BudgetExceeded` (`clients/budget.py:28-30`,
  `:57-58`).
- *Why:* the bound comes from the real request's worst case, so no unmeasured
  matcher number is needed (judges, "missing").
- It also grafts B's `DISCOVERY_MAX_SHARE` beside A's reservation. The trials
  node offers each trial the whole remaining cap (`nodes.py:1508`), so
  unbounded discovery would mean fewer proofs.

**D8. Generated hypotheses keep the model's order, and only lessons reorder
them. Caller candidates rank first, by the Step 2 formula.**

- `rank_generated` scores `(1 + lesson_boost) / (1 + position)`.
- *Why:* the only measured ranking signal is the model's order (hit@1 19-21/22).
  `expected_gain` is uncalibrated: Opus claimed big gains on `lettertally`.
- The Step 2 tests for `rank_hypotheses` stay untouched.

**D9. Generated `efficiency` and `behaviour` hypotheses enter rounds; `novel`
ones are parked.**

- *Why:* with D10, a behaviour keep no longer stops the run, and every frozen
  judge still applies. `novel` still interrupts at the gate, which no unattended
  run can answer (`tests/live/discovery.py:409-420` filters for this reason).
- Nothing fills `needs_package` in Step 3: the generator prompt forbids new
  dependencies (`optimization/generate.py:139-140`).
- L1 records counts per class; if behaviour ideas crowd out efficiency wins,
  `GENERATED_CLASSES` narrows (§8 Q2).

**D10. Behaviour keeps go to their own review branch, with no pause** (user
decision 1).

- `derive_verdict` rule 6 (`optimization/judges.py:673-682`) splits:
  - `efficiency` gives `keep`;
  - `behaviour` gives the new `VerdictOutcome.review`;
  - `novel` gives `needs_approval`, as today.
- Combine re-tests the review set on its own, ABAB, from the base, through the
  same `combine_kept`. That function re-judges any combination as
  `efficiency`-class, so it holds only if every judge passes
  (`orchestrator/combine_node.py:231-246`).
- Deliver publishes it create-only to `engine/review-<run_id>`. It is never
  merged into `engine/run-<run_id>` and never pushed.
- A `review` verdict does not end the search (only `keep` does) and is neutral
  in ranking (`ranking.py:46-49` counts only `keep` and `reject`).
- Migration 006 adds `review` to `chk_lesson_outcome` (`003:427-428`).
- The CLAUDE.md files ("flagged", verdict rule 6) and the `ChangeClass`
  docstring (`common/models.py:127`) are aligned in U15.
- *Why:* a stored `needs_approval` that never produces a request is a false
  record; the user asked for no pause; efficiency delivery stays clean.

**D11. The hypothesis is fenced in the editor prompt for every source.**

- Today `_task_text` puts `_hypothesis_text` outside the `_untrusted` fence and
  only the brief inside it (`execution/editor.py:455-475`).
- Generated titles and rationales derive from repository text, so they can
  relay an injection.
- `_holds` already refuses a hypothesis holding the token (`:463`). *Why:* one
  rule for every source, and no flag that could be set wrong.

**D12. The self-retry is narrow** (§4.4).

- **When:** only when a workload's own run exits non-zero with a parsed Python
  traceback of a fixable type: `SyntaxError`, `IndentationError`, `TabError`,
  `ImportError`, `ModuleNotFoundError`, `NameError`, `UnboundLocalError`,
  `TypeError`, `AttributeError`.
- **How often:** at most `EDITOR_FIX_RETRIES` times (default 1, at most 2), on
  the trial's own `Budget`, and only while `budget.remaining ≥ retry_floor_usd`
  (the factory's `min_trial_budget()`, `orchestrator/factory.py:111-116`).
- **Never retried:** timeouts, floods, isolation and report failures
  (`execution/procrun.py:265-289`), `AssertionError`, and the test suite, which
  runs with `check_exit=False` (`execution/measure.py:576`): a judge input,
  never a `RunFailure`.
- **Never fed back:** judge results, timings or fingerprints.
- *Why:* the retry lives in `GitTrialRunner._attempt`
  (`execution/trial_runner.py:502-587`), which returns before any judge runs:
  structure, not a promise, keeps verdicts out.

**D13. Information closure for every channel from run output to the API**
(graft of B's D23; fixes A's blocking flaw).

- Trials are confined for writes only (service CLAUDE.md, Security Notes:
  Landlock "writes only to the worktree…"). Code the editor wrote can therefore
  read `~/.aws/credentials` and raise its contents in an exception.
- User code can raise a fixable type with any message
  (`raise NameError(str(list(secret)))`): digits are no identifiers, and a diff
  can define an alphabet of names to pick from, so a token check is not closure.
- **Closure set:** the identifier tokens (`[A-Za-z_]\w*`) of the trial's diff
  and of the tracked `.py` sources at base (read with `GitWorkspace.read_blob`,
  `git.py:556`, deny-listed files excluded, at most 8 MiB in all).
- `classify` sends:
  - **frames** only as `(path, function, line)`, at most the 3 innermost, where
    `path` is a tracked base path or a touched path that matches no
    `READ_DENY_PATTERNS` entry (`common/paths.py:74-92`) and `function` is in
    the closure set. Source lines are never sent: the editor can `view` them.
  - **a message** only when it fully matches a CPython template for the parsed
    type (3.8-3.12 wording, pinned in `retry.py`, one test each): `NameError`
    `name 'X' is not defined` (and the free-variable forms, and the 3.10+
    `. Did you mean: 'Z'?`); `UnboundLocalError` `local variable 'X'
    referenced before assignment` and its 3.11 form; `ImportError` `cannot
    import name 'X' from 'Y'` (location dropped); `ModuleNotFoundError` `No
    module named 'X'`; `AttributeError` `'T' object has no attribute 'X'`,
    `module 'Y' …` and `type object 'T' …`; `TypeError` `F() takes N
    positional argument(s) but M were given`, `unsupported operand type(s)
    for OP: 'T' and 'U'` and `F() got an unexpected keyword argument 'X'`;
    and fixed `SyntaxError`/`IndentationError`/`TabError` phrases (`invalid
    syntax`, `unexpected indent`, …, one line number at most).
    Every captured name (each dotted part) is in the closure set. A name slot
    (`X`, `Y`, `F`) also appears on the innermost repository frame's source
    line at the trial's commit; a type slot (`T`, `U`) may instead be a builtin
    (`dir(builtins)`, `NoneType` and the like). At most two numbers of at most
    4 digits, and 300 printable characters. Otherwise: type and frames only.
- *What the templates prove:* every character sent is fixed interpreter text,
  a name the API has already seen, or one of two short numbers, so no
  verbatim, digit-encoded or alphabet-encoded copy of a file passes (a picked
  name is not on the raising line). The residual is a selection channel among
  seen values (3 frames, 3 names, 2 numbers): about 16 bytes per attempt at
  worst, times `EDITOR_FIX_RETRIES` (≤ 2); §5 lists it. The same rule governs
  3c's rewrite request (D33).

**D14. The retry's conversation shape.** A fresh editor request, not a replay:

- the worktree still holds attempt 1's change (after `GitWorkspace.reset`,
  `git.py:675-694`, which removes whatever the failed run wrote);
- a new boundary token;
- a fixed notice ("your previous change, still in the worktree, failed when run;
  fix that error and keep the approach");
- the closed feedback inside `<untrusted_run_output boundary=TOKEN>`.

*Why:* a replay would double the input tokens; the system and tools prefix
still reads from the cache. The worst case is one more editor conversation in
the trial's budget, which `call()` checks per request.

**D15. A retried trial is still one commit whose parent is the base.**

- `GitWorkspace.commit` gains `parent: str | None = None` (graft of B §3.6). The
  retry passes `parent=base`.
- The `update-ref HEAD` keeps HEAD (commit 1) as the expected old value
  (`git.py:773`).
- The attempts' `written` maps are merged, so `unrecorded_write` holds
  (`optimization/anticheat.py:452`). The full capture and every anti-cheat rule
  run again on the diff against the base.
- *Why:* combine skips anything but a single child of the base (`execution/combine.py:246-252`).

**D16. The editor gets its own model setting.** `EDITOR_MODEL` defaults to
`None`, meaning `ENGINE_MODEL`, so nothing changes. A one-line unit (W5) flips
it to Sonnet 5.5 at `low` only after L2. *Why:* E8a (12/12, about 0.04 USD a
run) and E5 (Sonnet engine, 44/44) cover only corpora that saturate. The OSS
small gains ran on Opus only (ledger row O).

**D17. `_brief_hotspots` is unchanged.** It falls back to the top 5 only when a
hypothesis names none of this run's hotspots (`nodes.py:342-355`), so a
generated hypothesis gets its resolved ids or a useful fallback (A §4.2 would
have blanked the brief for every corpus run).

**D18. How paid nodes behave on failure or resume.**

- `hypotheses` and `research` follow `understand` (`nodes.py:1262-1286`).
  - An `EngineError` charges the run through `_charged` (`:576-587`) and
    `keep_progress`, then raises.
  - Transport and reply failures are soft notes, and their spend is charged.
  - The new pool, `generator_calls` and `discovery_cost_usd` travel in the
    node's delta, so they are checkpointed before `trials` starts.
- A crash between the API reply and the checkpoint loses the run, not the cap:
  Step 3 resumes only in-process (a `PostgresSaver` resume is Step 4, STATUS
  Known gaps). No path pays twice.

**D19. pip-audit runs in CI** (user decision 2).

- It is a step in the `python` job, after mypy (`.github/workflows/ci.yml:306`,
  `:405`): `uv run pip-audit --progress-spinner off`, as the stage gate runs it
  (`scripts/stage-gate.sh:136`; `pip-audit` is a dev dependency,
  `pyproject.toml:150`).
- A weekly `pip-audit` job is also added to `security.yml`.
- *Why:* today only the stage gate runs it. The PR step catches a vulnerable
  lock change; the weekly job, a new advisory against an unchanged lock.

**D20. The offline discovery eval records and replays.**

- The sweep records each generator reply and each grader reply. Today `SweepRow`
  (`tests/live/discovery_sweep.py:162-190`) keeps counts only, so E3 cannot be
  replayed.
- A replay test runs the recorded replies through `generate_hypotheses` on
  `ScriptedTransport`, then `rank_generated` and the node's slice, and asserts
  hit@3 is at least the recorded baseline.
- Wave 1 uses a synthetic seed fixture; the real one comes from L4.
- *Why:* it catches validation, ranking and slicing regressions for free;
  prompt changes still need a refresh.

**D21. In blind mode, lessons reach discovery only through the generator
prompt.**

- Blind hypotheses have no `technique_id` (`generate.py:314`) and fresh uuid4
  ids. `lesson_matches` (`ranking.py:27-37`) therefore never matches them
  across runs: the ranking boost is inert in the default mode.
- STATUS's "playbook, lessons and evolution" priority is met by:
  - W1: the last 20 project lessons, plus `avoid_titles`, fenced into the
    generator prompt;
  - W2: a lesson discount for keeps whose combination failed (1.0 / 0.5 /
    0.25; `chk_lesson_weight > 0`, `003:429`).

**D22. Evolution is built only if the data asks for it.** W4 compounds two
disjoint near misses (inconclusive, right direction, ≥ 0.5 of their noise floor)
into one new trial, judged from scratch. *Gate:* L2 shows at least 2 of 10 OSS
runs with two or more such near misses. *Why:* nothing measured supports it yet.

**D23. Protected-pattern gaps are closed.** The patterns to add:

- `**/pip.conf`, `**/uv.toml`, `**/requirements*.in`, `**/constraints*.txt`;
- `**/pylock*.toml`, `**/pdm.lock`, `**/.python-version`.

None is in `DEFAULT_PROTECTED_PATTERNS` (`anticheat.py:47-105`). *Why:* each
changes what is installed or which interpreter runs.

**D24. Live runs follow the spend rule.**

- Each run names what it measures, what it feeds, and its cheapest arm.
- Each cap is the sum of its worst cases, using the existing per-run constants:
  - `HARD_RUN_CAP_USD == 5.0` (`tests/live/test_hard_corpus_guards.py:223`);
  - `OSS_RUN_CAP_USD == 5.0` (`tests/live/test_oss_guards.py:868`);
  - `CORPUS_RUN_CAP_USD = 5.0` (`tests/live/corpus.py:88`).
- A new suite gets the full plumbing: its constant and guard test, a `suite`
  value and its need in `ci.yml` (`:17-34`, the needs table read at `:639-652`),
  a timeout, and a ledger line (§6).

**D25. One migration per change:** 005 ids (U1), 006 `review` (U11), 007 for
3b, 008 for 3c. U1 also makes the CI re-apply loop cover every file from `003`
on (`ci.yml:765` lists only 003 and 004), so later migrations need no workflow
edit.

**D26. New node tests go in new files** (`test_hypotheses_node.py`,
`test_research_node.py`): `tests/orchestrator/test_nodes.py` is 5,661 lines.

**3b (designed here, built as its own step with its own approval):**

**D27. Same environment on both sides** (user decision 4).

- When 3b is active, the whole run is measured in E0, which is built from L0:
  the baseline, every trial, and both sides of combine.
- A package trial runs in E1, which is L0 plus the package and its new
  dependencies.
- Combine's A side runs in E0. Its B side runs in E(union of the kept packages).
- Once, at baseline, the engine measures the ambient environment against E0. If
  the ratio is outside the noise, it asks the user ("your installed environment
  differs from your lockfile"), so a gain is never proven only in an environment
  the user does not run.
- A resolver change to any existing pin refuses the package trial. The change is
  emitted as its own `dependency-upgrade` hypothesis (`behaviour`), measured
  against E0.
- The report says the user must install the new dependency.
- `env_baselines`, keyed by lock sha256: each entry is measured by the baseline
  runner under `_require_trustworthy_baseline` (`nodes.py:647`) with the run's
  N, noisy-host and completeness checks, and is re-measured when its lock sha
  or the host check changes. It separates the environment's effect (E1 at the
  base against E0) from the code change (the trial against E1's baseline).

**D28. No wheel means ask** (user decision 5). The flags are
`--only-binary :all: --no-build` when resolving and `--no-build` when
installing. L0's own pins fall under the same rule: an sdist-only pin, or a pin
newer than `--exclude-newer`, gives `needs_user` with the pin named.

**D29. The download floor is offline.** A package is acquired automatically
only if all of these hold:

- its name is in a committed, dated top-15k PyPI snapshot (graft of B's D19);
- it is no near miss of another snapshot name;
- it passes the age, OSV (`MAL-` included) and licence checks.

*Why:* a hallucinated name is plausible but not popular; no pypistats host.

**D30. The fetch phase runs engine code and one pinned `uv` only.**

- `UV_EXECUTABLE` is an absolute path. Its `--version` and its sha256 are
  checked against the settings `UV_VERSION` and `UV_SHA256`. A mismatch, or a
  missing binary, disables 3b for the run, with a note.
- The phase reaches the registry through a loopback allowlist proxy.
- Whether Landlock read confinement breaks `uv` is **unverified**: a failed
  probe refuses 3b on that host, with no weaker fallback.

**D31. The engine writes capability commit C1, and nothing else may.**

- C1 is recomputed and compared, and the editor's capture diffs against C1.
- A package that no kept change imports (a static scan via `top_level.txt`) is
  dropped and re-tested without it. If that re-test no longer holds, the package
  is restored with the note "used dynamically".
- If a no-package keep on the same hotspot is within the noise of the package
  keep, the no-package change wins (graft of B §4.4 step 7).
- `Trial.env_lock_sha256` is a field.

**D32. `_env` and `_wheels` have a cleanup owner.**

- Leading-underscore names fail `REFNAME_SEGMENT` (`common/refnames.py:22`), so
  `_phase_names` leaves them as "not an engine phase"
  (`execution/phase.py:265-282`): a leak.
- 3b adds them to the run's known dirs (`phase.py:64-65,269`).
- The acquire phase removes them in `finally`, under the run lock, and
  `sweep_stale_runs` (`:306`) removes them for dead runs.

**3c (designed here, built as its own step with its own approval):**

**D33. Reproducer integrity** (user decision 6).

- The reproducer is written in a separate, tool-less request, before any fix,
  and frozen outside `writable` with its sha256 checked before every run.
- The error report (a production error or a pasted traceback) is untrusted. It
  enters that request only inside an untrusted fence with a per-request
  boundary token (`Fence`, `clients/structured.py:112`, through `repo_fence`,
  `research/playbook.py:271`), and a report holding the token is refused before
  sending (`Fence.holds`, `structured.py:126`), as for repository text.
- It must fail on the baseline N of N runs. It must fail for the reported
  reason: the same exception type, and the same innermost repository frame or
  masked message, raised in a repository file at base.
- The fix's trial may not touch it. The report shows the reproducer next to the
  fix.
- The held-out variants come from a second request. That request sees the public
  reproducer and the signature, never the report text, and each variant must
  pass the same N/N check.
- The one allowed rewrite sees only the expected-versus-observed mismatch, under
  D13, and never trial output.

**D34. Heal judges.**

- `HealJudge` passes when the reproducer and every variant pass N of N, with the
  shim's completion document.
- Equivalence exempts only the reproducer's workloads.
- The full suite runs with nothing deselected:
  - for `failing_test`, it must count at least the baseline's tests + 1;
  - for `crash`, at least the baseline's count (graft of B §4.5; fixes A's 4.6,
    under which every crash heal failed closed).
- A heal is `behaviour`, so it is delivered on `engine/review-<run>` (D10).
- Capture rules beyond `heal_tamper`: the fix may add no file and no
  `__init__.py`. The report states that human review of the review branch is the
  final guard.

---

## 1 Scope and non-goals

**Step 3 (this approval):** Wave 1 (U1-U15, independent of the A/B), Wave 2
(the A/B follow-up, V1-V6 and the re-test) and Wave 3 (lessons and evolution,
W1-W6, each gated), as listed in §7.

**3b and 3c** are designed in D27-D34 and outlined in §7. Each is built after
Step 3 as its own step, with its own briefing, approval and security review.

**Non-goals:**

- the paper pipeline (PDF parser, triage, extraction, card review, `papers.json`)
  and the arXiv monitor, until D2's condition is met;
- card stats and the check-key registry (they serve retrieved cards only);
- Fable as the matcher;
- MCP and API discovery, error intake and the CLI (Step 4);
- CUDA and MPS;
- a paired noise rule (Step 5, §8 Q7);
- rollout (Step 6).

---

## 2 Architecture

```
START -> connect -> understand -> define -> baseline --+------------> REPRODUCE (3c)
                                     (3b: in E0;       |   separate request, frozen,
                                      ambient vs E0)   |   N/N fail, same reason,
                                                       |   variants from a 2nd request
              profile <--------------------------------+            |
                 |                                                  |
                 v                                                  |
              research  blind (default) | matched (off; D2 decides) |
                 |      narrowed Budget (D7)                        |
                 v                                                  v
      +----> hypotheses: pool in state; generate when empty (<= 2 calls,
      |        reserve one trial, <= 25 % of cap); efficiency+behaviour in,
      |        novel parked; caller first, then model order (+ lessons)
      |          |
      |          v
      |      ACQUIRE (3b, packages only): policy -> fetch (engine code + pinned uv,
      |          |   allowlist proxy, read-confined) -> E0/E1 offline -> C1
      |          v
      |      trials (one worktree each, network off; hypothesis fenced)
      |        edit -> capture -> anti-cheat -> commit(parent=base) -> measure
      |          ^--- fixable own crash, closure-checked feedback, <= 1 retry ---+
      |          v
      |      judges -> verdicts:  efficiency->keep | behaviour->review | novel->needs_approval
      |          |
      +-- untried idea or generation possible (after_verdicts) --+
                                                                 |
   END <- watch <- learn <- deliver <------- combine <- approval_gate (novel only)
           (review    run branch: keeps      keep set  -> ABAB -> engine/run-<id>
            neutral;  review branch: review  review set -> ABAB -> engine/review-<id>
            discount) (never merged, never   (3b: A side E0, B side E(union);
                       pushed; heal = R+F)    unimported packages dropped)

HEAL enters the same loop: the failing case is one source=heal, behaviour
hypothesis judged by HealJudge + the full suite + every other judge -> review branch.
Frozen outside the state: judges, protected patterns, noise rule, fingerprints,
reproducer sha256, env lock hashes.
```

---

## 3 Interfaces

### 3.1 Settings (`common/config.py`, U2 unless noted)

| Key | Default | Validated |
| --- | --- | --- |
| `GENERATOR_MODEL`, `GENERATOR_EFFORT` | `claude-sonnet-5-5`, `medium` | priced; effort accepted by the role's chain |
| `GENERATOR_N`, `GENERATOR_MAX_TOKENS`, `GENERATOR_MAX_CALLS` | 5, 16000, 2 | n 1-20 (`generate.py` `check_count`), calls 0-5 |
| `MATCHER_MODEL`, `MATCHER_EFFORT`, `MATCHER_K` | `claude-sonnet-5-5`, `medium`, 3 | as above |
| `RESEARCH_RETRIEVAL` | `blind` (`blind` or `matched`) | enum |
| `GENERATED_CLASSES` | `("efficiency", "behaviour")` | a subset of `ChangeClass`; `novel` refused until approvals run unattended |
| `DISCOVERY_MAX_SHARE` | 0.25 | in (0, 1) |
| `EDITOR_MODEL` | `None` (= `ENGINE_MODEL`) | priced; `EDITOR_EFFORT` accepted by its chain |
| `EDITOR_FIX_RETRIES` | 1 | 0-2 |
| `RETRY_CLOSURE_MAX_SOURCE_BYTES` | 8 MiB | ≥ 1 |

- Role chains run without fallbacks, except the editor when `EDITOR_MODEL` is
  unset, which keeps today's chain (`clients/cost.py:110-119`).
- `_every_billed_model_is_priced` (`config.py:319-326`) and
  `_effort_accepted_by_every_serving_model` (`:328-351`) are extended to every
  role.
- `role_settings(base, model, *, fallbacks)` moves from
  `tests/live/discovery.py:163-171` (`model_settings`) into `common/config.py`.
- 3b adds `ACQUIRE_ENABLED=False`, `UV_EXECUTABLE`, `UV_VERSION`, `UV_SHA256`,
  `PACKAGE_MIN_PROJECT_AGE_DAYS=90`, `PACKAGE_MIN_VERSION_AGE_DAYS=14`,
  `PACKAGE_LICENCES`, `PACKAGES_PER_HYPOTHESIS=1` and
  `ACQUIRE_MAX_BYTES=500 MiB`.
- 3c adds `REPRO_MODEL` / `REPRO_EFFORT` (Sonnet 5.5 / `medium`, unmeasured),
  `REPRO_VARIANTS=2` and `REPRO_RETRIES=1`.

### 3.2 State (`orchestrator/state.py`; every key set in `initial_state`)

Step 3 (U2):

- `candidate_pool: list[Hypothesis]`: generated, not yet in a round.
- `parked: list[Hypothesis]`: listed as proposals in the report, with the reason
  in `Hypothesis.status`'s companion note.
- `technique_matches: list[TechniqueMatchRecord]`.
- `generator_calls: int`.
- `discovery_cost_usd: float`.
- `discovery_exhausted: bool`.
- `review_combination: Combination | None`.
- `review_delivery: Delivery | None`.

`TechniqueMatchRecord(slug, fit, justification_summary, unmet_preconditions)` is
a new `EngineModel`. It and every new model join `ENGINE_SERDE_ALLOWLIST`.

3b adds `env_baselines: dict[str, Baseline]` and
`capabilities: list[CapabilityRecord]`. 3c adds `run_kind`, `heal_case` and
`reproducer`.

### 3.3 Models (`common/models.py`, U2)

- `VerdictOutcome.review = "review"`.
- `Trial.attempts: int = 1` and `Trial.retry_notes: tuple[str, ...] = ()`. Both
  are serde-safe, and both are stored in the JSONB trials array.
- `Hypothesis.parked_reason: str | None = None`.
- 3b: `Hypothesis.packages: tuple[PackageRequest, ...] = ()` (a name and a
  reason, never a version or a URL) and `Trial.env_lock_sha256: str | None`.
- 3c: `HealCase(kind, target, signature)`;
  `ExceptionSignature(type, message, frames)`;
  `Reproducer(path, sha256, variants_sha256, signature, baseline_failures)`.

### 3.4 Seams

```python
# optimization/sources.py (U2). "HypothesisSource" is taken by the enum
# (common/models.py:134), so the protocol is named HypothesisGenerator.
class HypothesisGenerator(Protocol):
    def generate(self, *, project: Project, understanding: ProjectUnderstanding | None,
                 hotspots: Sequence[Hotspot], objective: Objective,
                 techniques: Sequence[Technique], lessons: Sequence[Lesson],
                 avoid_titles: Sequence[str], n: int, budget: Budget) -> GenerateResult: ...
class TechniqueMatcher(Protocol):
    def match(self, *, understanding: ProjectUnderstanding | None, hotspots: Sequence[Hotspot],
              techniques: Sequence[Technique], k: int, budget: Budget) -> MatchResult: ...
@dataclass(frozen=True)
class GenerateResult: hypotheses: tuple[Hypothesis, ...]; notes: tuple[str, ...]
@dataclass(frozen=True)
class MatchResult: matches: tuple[TechniqueMatch, ...]; notes: tuple[str, ...]
```

- Spend is read from the `Budget` delta, through `_charged`.
  `generate_hypotheses` and `match_techniques` record into the budget they get
  (`generate.py:189-255`, `research/playbook.py:350-402`).
- U7 adds `ClaudeHypothesisGenerator` and `ClaudeTechniqueMatcher` in
  `optimization/hypothesis_source.py`. Each owns its transport. `lessons` and
  `avoid_titles` are accepted and ignored until W1.
- `NodeContext` (`nodes.py:181-237`) gains `generator`, `matcher` (both `None`
  by default, which keeps Step 2 behaviour), `retrieval`, `generated_classes`,
  `generator_n`, `generator_max_calls`, `matcher_k`, `discovery_max_share` and
  `playbook: tuple[Technique, ...] = ()`. U2 owns these fields and their
  `__post_init__` checks (it freezes the shared contracts, D4); U8, U9 and U11
  only read them.

**Retry (U4, U6):**

- `procrun.RunFailure` (`procrun.py:112-117`) gains `kind: str = "other"`,
  `exit_tail: bytes | None = None` and `workload_id: str | None = None`. Only
  `measure.launch`'s exit branch (`measure.py:255-259`) sets
  `kind="exit"`, the tail and the workload. Today only the tail's last line
  survives.
- `execution/crash.py`: `parse_traceback(tail: bytes) -> CrashReport | None`.
  It handles chained exceptions and the `SyntaxError` caret, for Python
  3.8-3.12.
- `execution/retry.py`:
  - `ClosureIndex.build(diff: str, sources: Mapping[str, bytes])`;
  - `classify(failure, *, closure, tracked, touched, excluded_workloads) -> TrialFeedback | None`;
  - `TrialFeedback(exc_type, frames, message | None)`.
- `EditTask.feedback: TrialFeedback | None = None` (`execution/protocols.py:137-146`).
- `GitWorkspace.commit(handle, message, *, base, parent=None)` (`git.py:765-774`).
- `GitTrialRunner` gains `fix_retries` and `retry_floor_usd`.

### 3.5 Tables

**005_lesson_ids.sql** (U1, idempotent, `DO`-guarded like `004`):

- `ALTER COLUMN hypothesis_id TYPE VARCHAR(64) USING hypothesis_id::text`, and
  the same for `technique_id` (legacy UUIDs are 36 characters and pass).
- On both: `CHECK (col ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' AND col NOT LIKE
  '%..%' AND col !~ '(\.lock|\.)$')`, the same rule as `validate_run_id`
  (`state.py:64-85`). The code check stays the gate; the `CHECK` refuses a
  direct insert of `a..b` or a 65-character id.
- Reads are unchanged: `_LIST_LESSONS` already casts `::text`
  (`postgres.py:170-178`).
- U1 also updates the column check in CI's "Verify engine tables" step
  (`ci.yml:775-800`).

**006_review_outcome.sql** (U11): drop and re-add `chk_lesson_outcome` with
`review` (`003:427-428`). The comment at `003:444` is updated.

**007** (3b): new `packages` columns, a `run_packages` table, and `acquire` in
`chk_task_phase`. **008** (3c): `heal` in `chk_hypothesis_source` (`003:384`) and
`reproduce` in `chk_task_phase` (`003:253-257`).

### 3.6 Live plumbing (U13; Wave 2 adds `V4`)

- `LIVE_CORPUS_MODE=wired`: no candidates, the generator on.
- A new `ci.yml` input, `editor_model` (`default`, or `claude-sonnet-5-5` with
  `EDITOR_EFFORT=low`).
- New `suite` values:
  - `ab-v2`, `ab-oss` (Wave 2);
  - `sweep-record`, `grader`.
- Each suite gets a need and a timeout (hard 150 min, OSS 240 min); guards pin
  every constant.

---

## 4 Behaviour

### 4.1 Research (U9)

- **`blind`**: `techniques = list(ctx.techniques)` (Step 2, `nodes.py:1413-1427`).
  No request.
- **`matched`**: `ctx.matcher.match` over `ctx.playbook`, on the D7 budget.
  - It writes the matched cards to `techniques` and to `technique_matches`.
  - `BudgetExceeded` from the pre-send check, `LLMConfigError`, `LLMUnavailable`
    and `UnusableReplyError` are soft: the node notes `research_unavailable`,
    charges what was spent, and continues blind.
  - Any other `EngineError` follows D18.

### 4.2 Hypotheses (U8)

1. `seen` is the hypothesis ids of every trial plus `state["hypotheses"]`, as
   today (`nodes.py:1433-1437`). The untried ideas are the unseen
   `ctx.candidates` plus `candidate_pool`.
2. The node generates only if all of these hold:
   - the untried list is empty;
   - `ctx.generator` is set;
   - `generator_calls < max_calls`;
   - neither `budget_exhausted` nor `discovery_exhausted` is set.

   Inputs: `project`, `understanding`, `hotspots`; `objectives[0]` (`define`
   always sets one, `nodes.py:1290`); `techniques`; lessons (`list_lessons`,
   already read at `:1438`); `avoid_titles`, every title in `hypotheses` and
   `parked`.

   `generator_calls` is incremented even when the call fails after spending. A
   pre-send `BudgetExceeded` sets `discovery_exhausted`, and so does `d ≤
   cost_usd` (D7), checked before any `Budget` is built; no request is sent.
3. Filters, each with a note:
   - a class outside `generated_classes` goes to `parked`
     (`parked_reason="needs approval"`);
   - a hypothesis with `packages` goes to `parked` (`"needs_package"`) until 3b;
   - a title already seen, or repeated (normalised as in `generate.py:293`), is
     dropped;
   - every id is checked again with `validate_run_id`.
4. Ranking: caller ideas through `rank_hypotheses`, then generated ones through
   `rank_generated`. The node slices `max_hypotheses_per_round` and puts the
   rest back in `candidate_pool`.
5. A round with no proposal is legal: the trials node runs nothing, and the
   router decides.

### 4.3 Router (U8)

The order is:

1. pending approvals (novel only) go to `approval_gate`;
2. `budget_exhausted` goes to `combine`;
3. any `keep` goes to `combine`;
4. `round ≥ max_rounds` goes to `combine`;
5. an untried idea in `ctx.candidates` or `candidate_pool` goes to `hypotheses`;
6. if generation is still possible (generator set, calls left, not exhausted),
   go to `hypotheses`;
7. otherwise, `combine`.

`review` verdicts never route. They wait for combine.

### 4.4 Self-retry (U4, U6)

1. `_attempt` catches the `RunFailure` (`trial_runner.py:582`). It calls
   `classify` with:
   - `ClosureIndex.build(diff, sources)`: the sources are the tracked `.py`
     blobs at base, minus the deny-listed ones, capped; past the cap, messages
     are withheld;
   - `tracked = ls_tree(base)` (already read at `:517`);
   - the touched paths;
   - `excluded_workloads` (3c: the reproducer).
2. A retry needs all of these:
   - `classify` returned feedback;
   - `trial.attempts ≤ fix_retries`;
   - `budget.remaining ≥ retry_floor_usd`.
3. The retry:
   1. `GitWorkspace.reset(handle)`.
   2. A fresh `EditTask` with the feedback and a new token, on the same `Budget`.
   3. A merge of `written` maps, under the file and byte limits for the union.
   4. `stage_all`, capture against the base, every anti-cheat rule.
   5. `commit(..., parent=base)`, then `update_ref(own_ref, commit2, commit1)`
      and `progress.moved = commit2`.
   6. A fresh measurement.
4. An unaffordable retry, an editor stop, a capture violation or a second crash
   keeps the first failure. The note goes in `retry_notes`, and the result is
   never `TrialUnaffordable`. An exception takes `_undo_own_ref` (`:465-487`).
5. Wall time: a retried trial measures twice. The per-workload timeouts and
   `TEST_TIMEOUT_S` (`config.py:279`) bound each run, `EDITOR_FIX_RETRIES ≤ 2`
   the factor; live timeouts grow in U13. No run-level wall cap (§8 Q8).

### 4.5 Review delivery (U11)

1. The verdicts node puts only `needs_approval` (novel) verdicts in
   `pending_approval_ids` (`nodes.py:1674-1676`).
2. Combine:
   - The keep set behaves exactly as today (`:1740-1810`).
   - Then, if any `review` verdicts exist, `combine_kept` runs a second time.
     The target branch is `engine/review-<run_id>`, the base is the same, and
     the result goes to `review_combination`.
   - Two combinations cost no tokens, only measurement.
3. Deliver:
   - The run branch behaves as today.
   - If the review combination holds, the node publishes create-only through
     `ctx.publisher.publish` with the review branch and its own `Delivery`
     (`kind=branch`). The report starts with: "Behaviour change(s): every judge
     passed, re-tested together; review before merging; not merged into
     `engine/run-<id>`, never pushed. Not re-tested together with
     `engine/run-<id>`; merging both is unproven."
   - The main report lists the review branch, and the parked ideas as
     proposals, with the same sentence: "`engine/review-<id>` was not re-tested
     together with this branch; merging both is unproven."
4. Learn: review lessons carry outcome `review`, which ranking treats as
   neutral.

### 4.5b 3b and 3c behaviour

D27-D34, A §4.5-4.6 and B §4.4 (1-8) and §4.5 (1-6), as corrected above;
each step's briefing restates it.

### 4.6 Failure modes

| Situation | Result |
| --- | --- |
| `save_trial` refuses or raises | The run fails with the round's progress kept (U1); `h1` and slugs no longer trigger it |
| The generator is empty, refuses or is unusable; the matcher fails | Soft note, spend charged; the router ends the run when nothing is left |
| Discovery is unaffordable (pre-send, or `d ≤ cost_usd`) | `discovery_exhausted`; the run trials the pool, then combines |
| The retry is not fixable, unaffordable or fails | The first failure is kept, with a note; timeouts, `AssertionError` and suite failures are never retried |
| The crash message fails a template or closure | Type and frames only, noted in `retry_notes` |
| The review combination does not hold | No review branch, said in the report; the run branch is unaffected |
| A novel hypothesis | Caller ones interrupt as in Step 2; generated ones are parked |

---

## 5 Security

| Threat | Controls |
| --- | --- |
| Injection relayed by generated hypotheses into the editor | D11: fence plus token refusal (`editor.py:463`); the generator already fences repository text (`generate.py:215-242`) |
| Run output carrying secrets to the API (retry, 3c rewrite) | D13 closure: a message only when it matches a CPython template for its type, every captured name in the diff or the base sources (name slots also on the raising line), at most two numbers of at most 4 digits, 300 characters; else type and frames only; at most 3 tracked or touched frames, no deny-listed paths, no traceback source lines; fenced; never stdout, timings, fingerprints, suite output or verdicts. Digit- and alphabet-encoding canaries in U4 and E3-D. Residual: a selection channel of about 16 bytes per attempt, at most 2 attempts |
| 3c: injection through the error report | D33: the report is fenced with a per-request token and refused if it holds it (`Fence.holds`, `structured.py:126`); the variant writer never sees it |
| Retry as a reward-hacking channel | Own workload crash only; it runs before any judge (`trial_runner.py:502-587`); a full re-capture and anti-cheat pass on the union diff; one commit on the base |
| Discovery spend starving proofs | D7 narrowed budget enforced by `Budget.check` before send; `DISCOVERY_MAX_SHARE`; `discovery_cost_usd` reported |
| Excessive agency in behaviour delivery | Review branch: create-only, under the prefix, never on a checked-out or default branch (`assert_safe_branch`), never merged into the run branch, never pushed; novel still asks |
| New per-role transports | The key stays inside `AnthropicTransport`; every role model is priced and its effort validated; no fallbacks on new roles; an unpriced role model is refused at startup |
| Widened Postgres ids | The engine id rule checked before any SQL, plus the 005 `CHECK`; literal SQL with parameters, unchanged |
| Supply chain of the engine | `pip-audit` on every Python PR and weekly; bandit and OSV unchanged |
| Install-config smuggling | D23 protected patterns |
| Lessons in the generator prompt (W1) | Fenced, a line holding the token withheld; only the generator sees them, never the editor |
| Recorded replies (eval fixtures) | Parsed through the same strict schemas as live replies; they are test data only |
| 3b: slopsquatting, dependency confusion, malicious wheels, TOCTOU, SSRF, resolver exfiltration | D28-D31 plus A §5's rows (one index, `--no-config --no-sources`, RECORD checks, content-addressed store, sha256 at download and install, allowlisted URLs, scrubbed read-confined fetch child, `*PROXY*` never reaching workloads, `execution/sandbox.py:63-67`) |
| 3c: reproducer gaming | D33-D34; sha256 per run; variants hidden from the editor; `heal_tamper`; no new files; human review stated |

Units with a security Reviewer: U1 (SQL), U4 (closure), U5 (patterns), U6
(retry, fence), U10 (transports), plus every 3b and 3c unit named in §7.

---

## 6 Test plan

**Unit tests** (offline, TDD, 100 % line and branch kept):

- **U1:**
  - `h1` and a slug round-trip through `save_trial`, `save_verdict` and
    `save_lesson` on Postgres;
  - `../x`, `a..b`, `Set Membership` and 65 characters are refused before
    connecting, and 64 characters are accepted; a direct insert of `a..b` or
    65 characters fails the 005 `CHECK`;
  - a legacy UUID row reads back;
  - 005 applies twice;
  - a `save_trial` raise keeps the round's spend in the failed state.
- **U2:** serde reflection over the new models; `initial_state` sets every new
  key; each validator refuses an unpriced role model and an effort its chain
  rejects; a `novel` entry in `GENERATED_CLASSES` is refused.
- **U4:**
  - `parse_traceback` on 3.8-3.12 stderr (chained, caret, cut tail);
  - `classify` gives `None` for a timeout, a signal, `AssertionError`, the
    suite and an excluded workload;
  - each template, per supported version, passes with closure-checked names;
  - closure withholds a message holding `AKIAIOSFODNN7EXAMPLE`, a 5-digit
    number, a third number, or a function name absent from the diff and the
    sources;
  - **digit canary:** run code raises `NameError` with a planted file's bytes
    as decimal numbers (alone, and after a valid template): type and frames
    only;
  - **alphabet canary:** the diff defines names `a00`-`aff`; the run raises
    `NameError(f"name '{ALPHA[b]}' is not defined")`, and a genuine one through
    `eval(ALPHA[b])`, per byte of the planted file: the name is not on the
    raising line, so the message is withheld;
  - a frame in `.env` or outside the tracked or touched set is dropped, and at
    most 3 frames are sent.
- **U5:** each new pattern refuses a diff.
- **U6** (new `tests/execution/test_trial_retry.py`):
  - `NameError` then a fixing edit gives `attempts == 2` and one commit whose
    parent is the base (`combine._unfit` passes), with no `unrecorded_write`;
  - a reset removes a file the failed run wrote;
  - an unaffordable retry keeps the first failure;
  - the cap holds;
  - the feedback never contains stdout or timings;
  - the hypothesis is fenced, and a token inside it is refused.
- **U7:** the adapters on `ScriptedTransport` record their spend in the budget;
  `rank_generated` keeps the model order, and a keep lesson reorders it.
- **U8** (new file):
  - one generation on an empty pool, with its inputs recorded;
  - parking, 3 sliced and 2 pooled, and no regeneration while the pool has
    ideas;
  - the narrowed budget refuses at the trial reserve and at the 25 % share;
  - a run cap below one editor request (`d ≤ cost_usd`) sets
    `discovery_exhausted` with no request and no `ValueError`;
  - a soft failure is charged;
  - the router with empty `ctx.candidates` and a non-empty pool returns
    `hypotheses`, and returns `combine` once calls run out;
  - `generator=None` reproduces Step 2 with every existing test unchanged.
- **U9:** blind sends nothing; matched writes `technique_matches`; a matcher
  failure falls back to blind and is charged.
- **U10:** per-role chains; `min_trial_budget` priced on the editor's chain; the
  retry floor equals it; the factory passes the playbook only through
  `NodeContext.playbook` and, in blind mode, `build_context` returns
  `techniques == ()` (`factory.py:306-379` never sets it today), so the
  generator's research block stays empty (`generate.py:215-243`).
- **U11:**
  - rule 6 for all three classes;
  - a behaviour keep gives `engine/review-<id>`, with the run branch unchanged
    and no interrupt;
  - a novel caller candidate still interrupts;
  - a review combination that fails gives no review branch;
  - both reports carry "not re-tested together with `engine/run-<id>`;
    merging both is unproven" (the main report's form names the review
    branch);
  - 006 applies twice;
  - a review lesson is neutral in ranking.
- **U12:** a recorded reply replays to the same hypotheses; hit@3 is at least
  the recorded value; an unknown label key fails with "refresh in live-smoke";
  grader replies replay through `grade_with`.
- **U13:** every new constant and need is pinned; a suite cap below its need is
  refused (`tests/live/conftest.py` admission, lines 12-17).

**E2E** (`tests/e2e/test_step3.py`, marker `slow`, real git and sandbox, scripted
Claude):

- **E3-A:** `candidates=()`, plus a scripted generator reply, reaches a delivered
  branch. A second run stopped with `interrupt_before=["trials"]` (as
  `tests/orchestrator/test_graph_e2e.py:431` does) and resumed by a fresh graph
  records exactly one generator request. (With `candidates=()` no run reaches
  the gate: only caller `novel` ideas do.)
- **E3-E:** one caller `novel` candidate beside the scripted generator pauses
  at `approval_gate` and is resumed; the generator count is unchanged by the
  resume (zero: caller ideas go first, and the gate leads to `combine`).
- **E3-B:** a `NameError` from the first edit is fixed by the retry, and the run
  delivers with `attempts=2`.
- **E3-C:** a behaviour hypothesis lands on `engine/review-<id>` with no pause,
  and a novel one is parked.
- **E3-D:** injected crash messages are withheld from the wire: one holding a
  canary verbatim, one carrying a planted file's bytes as decimal numbers in a
  `NameError` message, and one picking diff-defined alphabet names per byte.
  The scripted transport records the bodies; no body holds the canary, its
  decimal byte string, and no `<untrusted_run_output>` block holds an
  alphabet name.

**Live** (CI `live-smoke` only, one suite at a time under the 150 USD ceiling;
every run lands its cost and finding in the ledger). The expected costs come
from Window 0 rows: E5 about 0.10 USD per task-arm on the Sonnet engine
(10.20 / 100); H 0.11 USD a run (Opus); O 0.30 USD a run (Opus); M 0.45x Opus;
E3 0.048 USD per repo-arm including the grader. Each A/B cap is the computed
`ab_need(plan)` (`tests/live/discovery_ab.py:134-137`): per task
`AB_GEN_CAP_USD` (a `ceil_usd` constant, `:108-114`; 0.8 at E5's settings, as
the `ab` need 140 = 2 × 25 × 2.8 shows) plus both run caps, rounded up to a
whole USD as `ci.yml:636-637` does, since the ledger admits a test only if it
fits with earlier spend and open caps (`tests/live/conftest.py:12-17`).

| Run | Measures | Feeds | Cap (sum of worst cases) | Expected | Cheapest arm |
| --- | --- | --- | --- | --- | --- |
| L1a `hard`, `wired` | Wired engine wins with no hypothesis handed over; attempts per trial (retry rate); counts per class; discovery cost | Wave 1 acceptance; the D9 class default | 10 × 5 = 50 | ~1.0 | Sonnet engine (E5 ran it on this corpus) |
| L1b `corpus`, `wired` | Control false wins with generation in the loop | The same | 15 × 5 = 75 | ~0.8 | Sonnet engine |
| L2a `oss`, `wired`, Sonnet low editor | Delivered against aimed-Opus 6/10; near-miss counts; retry rate | W5 (`EDITOR_MODEL`), the W4 gate | 10 × 5 = 50 | ~1.5 | Sonnet first |
| L2b `oss`, `wired`, Opus editor | Only if L2a < 5/10 | W5 | 10 × 5 = 50 | ~3.0 | - |
| L3 `grader` | Opus 4.8 grader agreement on about 10 hand labels (≥ 9/10, no false positive on near misses) | Whether L4's hit@k counts as validated | 10 × `GRADE_WORST_USD` (`discovery_grader.py:298`) | < 0.5 | - |
| L4 `sweep-record`, Sonnet medium, v1 + v2 | Recorded replies; v2 blind hit@1 | U12's real fixture; the v2 saturation pre-check | Sweep need for 1 arm × 37 repos (guard-computed; about 23) | ~1.8 | One arm only |
| L5a `ab-v2`, arm A only, 1 rep | Is v2 saturated for executed wins (≥ 90 % means revise) | Whether L5b runs | `ab_need`: 12 × (0.8 + 1) = 21.6, need 22 | ~0.6 (+0.6 for the one rerun on a revised v2) | A only |
| L5b `ab-v2`, both arms, 2 reps | c, b, gains, controls | D2 pooled rule | `ab_need`: 24 × (0.8 + 2) = 67.2, need 68 | ~4.9 | Run only after L5a |
| L5c `ab-oss`, both arms, 1 rep, 2 USD run cap | The same on small gains | D2 pooled rule | `ab_need`: 10 × (0.8 + 4) = 48, need 48 | ~3.0 | Skipped if it cannot change the decision |
| W1 refresh | The eval fixture after the prompt change | W1 | `sweep_need` for 1 arm × the 25 v1 repos (`discovery_sweep.py:139-143`, guard-computed; about 25/37 of L4's 23, need about 16) | ~0.6 | One arm |

The Step 3 expected total is about 15-18 USD (about 21 with L2b), all in Window
1, including the one L5a rerun (0.6) if v2 is revised; L5a is not repeated a
second time. It replaces Window 1 row C (`STATUS.md` "Window 1", about 30 USD of Opus
extraction). Reruns happen only when a fix changes what is measured. 3b's L6
(the network job, 0 tokens) and 3c's L7 (the heal corpus) are planned with their
steps.

---

## 7 Work breakdown

Every unit: about 400 lines at most, tests first; disjoint files within a
parallel batch; one commit; a Reviewer on a different model, lens named; the
seams checklist in its brief.

**Wave 1** (independent of the A/B):

| # | Unit | Files | Lines | After | Reviewer lens |
| --- | --- | --- | --- | --- | --- |
| U1 | Postgres ids (first) | `infrastructure/schema/005_lesson_ids.sql`, `persistence/postgres.py`, `tests/persistence/test_postgres.py`, `orchestrator/nodes.py` (the `save_trial` guard only), `tests/orchestrator/test_trials_progress.py`, `.github/workflows/ci.yml` (schema re-apply and column check) | ~200 | - | correctness; security (SQL) |
| U2 | Contracts | `common/config.py`, `common/models.py`, `orchestrator/state.py`, `orchestrator/serde.py`, `optimization/sources.py`, `orchestrator/nodes.py` (the `NodeContext` fields of §3.4 only) + tests | ~330 | U1 | correctness |
| U3 | pip-audit in CI | `.github/workflows/ci.yml` (python job), `.github/workflows/security.yml` | ~40 | U1 | correctness (CI) |
| U4 | Crash parser, classifier, closure | `execution/procrun.py`, `execution/measure.py` (`launch`), `execution/crash.py`, `execution/retry.py` + tests | ~380 | U1 | security |
| U5 | Protected-pattern gaps | `optimization/anticheat.py` + tests | ~60 | U1 | security |
| U6 | Retry flow and fence | `execution/trial_runner.py`, `execution/git.py`, `execution/protocols.py`, `execution/editor.py`, `tests/execution/test_trial_retry.py` | ~390 | U2, U4 | security; correctness |
| U7 | Adapters and `rank_generated` | `optimization/hypothesis_source.py`, `optimization/ranking.py` + tests | ~250 | U2 | correctness |
| U8 | Hypotheses node and router | `orchestrator/nodes.py` (`hypotheses`, `after_verdicts`), `tests/orchestrator/test_hypotheses_node.py` | ~380 | U7 | correctness; spec |
| U9 | Research node (matched, off) | `orchestrator/nodes.py` (`research`), `tests/orchestrator/test_research_node.py` | ~200 | U8 | correctness |
| U10 | Factory: roles, playbook, retry floor | `orchestrator/factory.py`, `tests/orchestrator/test_factory_roles.py` | ~220 | U6, U7 | security (transports) |
| U11 | Review-branch delivery | `optimization/judges.py`, `orchestrator/nodes.py` (`verdicts`, `combine`, `deliver`, `_report`), `infrastructure/schema/006_review_outcome.sql`, `tests/orchestrator/test_review_delivery.py`, `tests/optimization/test_judges.py` (rule 6) | ~380 | U9 | spec (user decision 1); correctness |
| U12 | Offline discovery eval | `tests/live/discovery_grader.py`, `tests/live/discovery_sweep.py`, `tests/optimization/test_discovery_eval.py`, `tests/fixtures/discovery_eval/seed.json` | ~300 | U7 | weakened-test |
| U13 | Live plumbing | `tests/live/corpus.py`, `tests/live/oss.py`, `tests/live/test_*_guards.py`, `.github/workflows/ci.yml` (live-smoke) | ~250 | U3, U10 | cost (caps) |
| U14 | E2E E3-A to E3-E | `tests/e2e/test_step3.py`, `tests/fixtures/step3/` | ~350 | U11, U13 | correctness |
| U15 | Docs (Lead) | `CLAUDE.md` (D10 wording, Step 3 row per §8 Q1), `services/python_agents/CLAUDE.md` (rule 6, branches, state keys), `README.md`, `STATUS.md` (dev-log rows 3b, 3c and 6, which today lists 0-5 at `STATUS.md:62-70`; Window 1 row C; the D2 pre-registration) | ~150 | all | spec |

Build order:

1. U1, alone.
2. U2, U3, U4 and U5, in parallel.
3. U6 and U7.
4. U8 and U12.
5. U9 and U10.
6. U11 and U13.
7. U14.
8. U15.
9. The live runs: L1a, then L1b, then L2a (and L2b only if needed).

`nodes.py` (U1, U2, U8, U9, U11) and `ci.yml` (U1, U3, U13) never share a
batch; U8 branches from U2's commit, U9 from U8's, U11 from U9's, U13 from U3's.

That is 15 units, about 3,880 lines. After step 5 of this order, a run needs no
hypothesis handed to it, and a fixable crash recovers.

**Wave 2** (the A/B follow-up; independent of Wave 1 except U12 and U13):

| # | Unit | Files | Lines | After |
| --- | --- | --- | --- | --- |
| V1 | Hard corpus v2, part 1: `deep`, `spread`, `misleading`, 2 each | `tests/fixtures/live_corpus_discovery/{deep,spread,misleading}*`, `_solutions/` | ~400 | - |
| V2 | v2 part 2: `uncommon` 2, `small` 2, decoy controls 2; manifest, parser, guards | the rest of the same dir, `tests/live/discovery_corpus.py`, `tests/live/test_discovery_corpus_guards.py` | ~400 | V1 |
| V3 | `ledgerclose` rebuild (both hot spots C-level compare loops) and the part-cost ratio guard (0.5-2) | `tests/fixtures/live_corpus_hard/ledgerclose/`, `tests/live/test_hard_corpus_guards.py` | ~200 | - |
| V4 | A/B instrument: corpus and arm selection, `ab_decision(b, c, controls_a, controls_b)` next to `MIN_DISCORDANT_LEAD` (tests: `(b=1, c=4)` met; `(2, 4)` not; more B control false wins than A is not met), pooled over corpora; `ab-v2` and `ab-oss` suites | `tests/live/discovery_ab.py`, `tests/live/test_discovery_guards.py`, `.github/workflows/ci.yml` | ~250 | U13 |
| V5 | Grader labels (Lead) and the agreement test | `tests/fixtures/grader_labels.json`, `tests/live/test_grader_agreement_live.py` | ~200 | - |
| V6 | Commit L4's recorded fixture | `tests/fixtures/discovery_eval/` | ~100 | L4 |

v2 rules:

- The author's technique list is written without reading
  `research/playbook.json`; card fit is recorded only after the corpus is
  frozen, as for the hard corpus (7/10).
- Every slowdown carries a reference fix in `_solutions` and a guard proving it
  winnable.

Live order: L3, then L4, then L5a, then L5b, then L5c.

**Wave 3** (lessons and evolution; each unit gated):

| # | Unit | Files | Lines | Gate |
| --- | --- | --- | --- | --- |
| W1 | Lessons and `avoid_titles` in the generator prompt (fenced) | `optimization/generate.py` + tests | ~220 | Wave 1; a W1 refresh afterwards |
| W2 | Combine-failed lesson discount | `learning/lessons.py`, `orchestrator/nodes.py` (`learn`) | ~150 | Wave 1 |
| W3 | Profiler `Hotspot.tags` (never set in `src` today) | `execution/profiler.py`, `execution/_profile_shim.py` (not re-read) | ~200 | lowest priority; dropped if Wave 3 runs long |
| W4 | Evolution: near-miss compounds | `optimization/evolve.py`, `orchestrator/nodes.py` (a hook in `hypotheses`) | ~380 | L2: ≥ 2/10 runs with ≥ 2 disjoint near misses |
| W5 | `EDITOR_MODEL` default flip to Sonnet low | `common/config.py` | ~10 | L2: Sonnet delivers ≥ Opus-aimed 6/10 − 1, with 0 control wins in L1b |
| W6 | `RESEARCH_RETRIEVAL` flip to `matched` | `common/config.py` | ~10 | D2's pooled rule met |

**Conditional, not in Step 3: P, paper intake.**

- *Condition:* D2's pooled rule is met (retrieval helps on a set blind
  generation does not saturate), and E7 rerun through `src` costs at most 0.35
  USD a paper.
- *Then:* its own briefing and approval for:
  - P1: a snapshot source, with arXiv only on the user's machine;
  - P2: the Haiku screen and the PDF cost bound;
  - P3: pass 1 with citations and local quote verification;
  - P4: pass 2, the check-key registry and `pending/`;
  - P5: human card review and `papers.json`.

  The monitor moves to the Step 4 CLI as a manual tool.
- *Otherwise:* papers stay deprioritised, and the decision is recorded in STATUS
  with the data.

**3b outline** (its own step, about 10 units):

- B0: contracts and 007.
- B1: the name snapshot and near miss.
- B2: the pure policy.
- B3: wheel inspection.
- B4: registry and allowlist proxy (security).
- B5: `uv` provenance, lockfile and fetch under read confinement, plus the
  Landlock probe (security).
- B6: offline envs, `make_phase(env=)` (`execution/measure.py:132`), the
  `_env`/`_wheels` owner and `_host` (`measure.py:321`) (security).
- B7: the acquire node, C1, capture from C1, the whole-run E0 baseline and the
  ambient ratio (security).
- B8: combine with packages, the drop with dynamic fallback, the tie-break and
  the install line.
- B9: E2E and L6.

**3c outline** (its own step, about 7 units):

- C0: contracts and 008.
- C1: the shim and signature matching.
- C2: the reproducer writer, the separate variant writer and the static checks
  (security).
- C3: the reproduce node, freeze, the N/N baseline and `--deselect`
  (`_require_trustworthy_baseline`, `nodes.py:647`).
- C4: `HealJudge`, the equivalence exemption, `heal_tamper`, the no-new-file
  rule and the retry exclusion (security).
- C5: delivery of commit R, then commit F, on the review branch, and the report.
- C6: the E2E corpus (5 planted bugs, 3 controls) and L7.

---

## 8 Open questions (each with a recommended answer)

1. **The CLAUDE.md Step 3 row.** It still lists the PDF parser,
   claim/precondition extraction and the arXiv monitor, with "Fable for
   matcher". *Recommended:* change it to "generator wired, engine self-retry,
   review delivery, hard corpus v2 and the retrieval re-test, lessons and
   evolution; paper intake conditional (STATUS)" with Sonnet for discovery. This
   needs your approval, since it edits the build order.
2. **Generated behaviour ideas by default** (D9). *Recommended:* yes, as
   specified, with L1a reporting counts per class. Narrow to efficiency if
   behaviour ideas take more than a third of slots without a review win.
3. **Spend on the re-test (L5, about 8.5 USD expected, caps up to 68).**
   *Recommended:* approve it. It is the only route by which paper code could
   ever be justified, and it is cheaper than building that code speculatively.
   Nothing in Wave 1 waits on it. *Alternative:* skip the re-test; retrieval
   stays off, W6 and P are removed, and V4 shrinks to the corpus and arm
   selection L4 needs.
4. **3b lockfiles.** *Recommended:* hash-pinned `requirements*.txt` first;
   `uv.lock` only after probing `uv lock --no-build` on dynamic metadata
   (**unverified**); no lockfile means asking the user.
5. **The order of 3b and 3c.** 3c has no network-on boundary and could ship
   first. *Recommended:* keep 3b then 3c, unless you want healing sooner.
6. **The reproducer model.** Sonnet 5.5 medium is a guess. *Recommended:* L7
   compares it with Opus in 3c.
7. **Small OSS gains under the noise floor** (4/10). A paired, interleaved rule
   would change a frozen judge. *Recommended:* scope it for Step 5, not Step 3.
8. **A run-level wall-time cap.** None exists, and retries can double trial
   time. *Recommended:* none in Step 3; add `--max-time` with the Step 4 CLI.
9. **Review branches and learning.** A merge of `engine/review-<id>` is not
   detected, so review lessons stay neutral. *Recommended:* accept until the
   Step 4 GitHub App observes merges.
10. **Novel lessons across runs** (fresh ids, no technique). *Recommended:* rely
    on W1's prompt channel; no title-key matching in Step 3.
