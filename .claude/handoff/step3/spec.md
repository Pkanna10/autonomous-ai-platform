# Step 3 spec: wired discovery, engine self-retry, review delivery (3c and 3b designed)

Base: `claude/step3-research` at `9d2482f` (no `src` change since `322f08f`:
`git diff --quiet 322f08f HEAD -- services/python_agents/src`). Built from
design A, with `judges.md`'s blocking flaws fixed, B's recommended items
grafted, the user's decisions (`user-decisions.md`), the E5 result and the
owner's review applied. Paths are relative to
`services/python_agents/src/autonomous_ai_agents/` unless they start with
`tests/`, `infrastructure/` or `.github/`. Every file:line was re-read at
`9d2482f`; anything not re-read is marked **(not re-read)**, anything inferred
**unverified**.

**Revision 3 (owner conditions).** From `owner-step3-review.md`: a per-run
retry cap with the residual restated per run (D12, D13, §3.1, §4.4, §5, U2,
U6, new U16); D35, how a `behaviour` hypothesis passes (D9, D10, §4.5, U11);
3.13 and 3.14 templates, derived by running each error under every
interpreter present (D13, U3, U4); owner decisions O1-O5, so 3c comes before
3b (D36); a total-time line and the retry-crashes-again rule in the report
(§4.4, §4.5); L2a at 2 repetitions, W5 gated over 20 (§6, §7); Wave 3 held
until Wave 1's live runs report (§1, §7).

**Open for the owner in Revision 3.** D35 is the Lead's reading of condition
2, not one of its two options; under it O2 yields review branches only for
behaviour ideas that keep every guarded output. Owner to confirm before U11
(build-order step 6) (§8 Q2). The per-run retry default (1 or 2) is §8 Q13.
The W4 gate restated over 20 is the Lead's (D22).

**Revision 2 (critic fixes):** D13's template rule and its canaries; E3-A
reachable, E3-E; D7's negative cap; 005 equals the id rule; the "not re-tested
together" caveat; live caps from `ab_need`; `NodeContext` owned by U2;
`env_baselines`; the report fenced; blind `techniques=()`.

**About the A/B.** E5 is finished (Actions run 40063812021, 10.20 USD) and
applied: retrieval is off, no paper code is built. The re-test (D2, L5) is a
new, smaller A/B on a corpus built in Wave 2.

---

## 0 Decisions

**Owner decisions (2026-10-24, binding; §8 Q1-Q5 answered).**

- **O1.** The CLAUDE.md Step 3 row changes as §8 Q1 says (U15).
- **O2.** Generated behaviour ideas by default (D9), under D35.
- **O3.** The re-test is approved (about 8.50 USD); its pooled rule lands in
  STATUS before L5a, its first run (D2).
- **O4.** 3b lockfiles: hash-pinned `requirements*.txt` first.
- **O5.** 3c before 3b, unless packages block the dogfood on the owner's code.
  *Why (owner):* 3c has no network boundary and reuses the loop and judges; 3b
  needs a security review of a network-on fetch, an allowlist proxy and an
  unverified Landlock interaction with `uv` (D36).

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
- **The pre-registered pooled rule** is written to STATUS before L5a is
  dispatched (O3). Over the v2 and OSS slowdown tasks, `c − b ≥ 3`, and B's
  false wins on controls must not exceed A's.
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
  judge still applies, equivalence included (D35): a behaviour idea reaches the
  review branch only with unchanged outputs where the run guards them. `novel`
  still interrupts at the gate, which no unattended run can answer
  (`tests/live/discovery.py:409-420` filters for this reason).
- Nothing fills `needs_package` in Step 3: the generator prompt forbids new
  dependencies (`optimization/generate.py:139-140`).
- L1 records counts per class and how many behaviour trials equivalence
  rejected; if behaviour ideas crowd out efficiency wins, `GENERATED_CLASSES`
  narrows (O2, §8 Q2).

**D10. Behaviour keeps go to their own review branch, with no pause** (user
decision 1).

- How a behaviour hypothesis can pass every judge is D35.
- `derive_verdict` rule 6 (`optimization/judges.py:674-682`) splits:
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
- **How often:** at most `EDITOR_FIX_RETRIES` per trial (default 1, at most
  2) and `EDITOR_FIX_RETRIES_PER_RUN` per run (default 2 until the owner
  answers §8 Q13, which offers 1; at most 4), on the
  trial's own `Budget`, and only while `budget.remaining ≥ retry_floor_usd`
  (the factory's `min_trial_budget()`, `orchestrator/factory.py:111-116`).
- **Where the run cap is checked** (U16): the trials node computes what is
  left, `EDITOR_FIX_RETRIES_PER_RUN − Σ (attempts − 1)` over `state["trials"]`
  (`orchestrator/state.py:104`; earlier rounds, appended by the judges node's
  delta, `nodes.py:1603`) and this round's earlier trials, and passes it
  as `TrialBrief.fix_retries_left: int = 0` (`execution/protocols.py:76-81`).
  `_attempt` retries only while its retries are below both caps, and
  `_runner_trial_problems` (`nodes.py:456-473`) refuses a trial whose
  `attempts − 1` exceeds what it was given. Counted from checkpointed trials,
  the cap survives a resume at a node boundary (`interrupt_before`); a crash
  inside the trials node loses that round's count along with its trials,
  which `_trials_progress` (`nodes.py:784-796`) attaches only to the failed
  record, and the round is re-run and re-paid on resume, as in Step 2 (D18).
  The runner reads the field; the editor prompt
  never shows it.
- *Why a brief field:* a new `run()` keyword would break every
  `TrialRunner` (`execution/runner.py:46-62`): `StubTrialRunner` (`:120-129`)
  and the test fakes (e.g. `tests/orchestrator/test_nodes.py:277`). The
  default 0 fails closed.
- **When the run's retries are spent:** the trial keeps its first failure,
  with the note "not retried: the run's N fix retries are spent" in
  `retry_notes`; rule 2 rejects it like any failed trial, and the run goes on.
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
    `READ_DENY_PATTERNS` entry (`common/paths.py:74-92`), `function` is in
    the closure set, and `1 ≤ line ≤` the line count of `path` at the
    trial's commit (the blob is already read for the name-slot check); any
    other frame is dropped. A trial diff controls all three
    (`f.__code__ = f.__code__.replace(co_firstlineno=123456789)` makes
    python3.13 and 3.14 print `line 123456790`), so none is a free value.
    Source lines are never sent: the editor can `view` them.
  - **a message** only when it fully matches a template for the parsed type,
    pinned per CPython version in `retry.py`. Each was derived by raising the
    error uncaught under 3.8.20, 3.9.25, 3.10.20, 3.11.17, 3.12.3, 3.13.16
    and 3.14.6 (all in this container; 3.14.6 through `uv python install
    3.14`) and reading stderr's last line. Under 3.14.6 the 33-case probe is
    identical to 3.13.16 on every case but the installation `PATH`; carets
    and no colour on a pipe are the same, and `TERM` alone does not colour.
    CI proof still comes from U3 (3.13 and 3.14 installed and on PATH) and
    U4's live-template tests (`ci.yml:380-383` installs only 3.8-3.12
    today). `PATH` is always dropped.
    - `NameError`: `name 'X' is not defined` (+ `. Did you mean: 'Z'?` 3.10+,
      `. Did you forget to import 'Z'?` 3.12+); `free variable 'X' referenced
      before assignment in enclosing scope` ≤ 3.10, `cannot access free
      variable 'X' where it is not associated with a value in enclosing scope`
      3.11+.
    - `UnboundLocalError`: `local variable 'X' referenced before assignment`
      ≤ 3.10, `cannot access local variable 'X' where it is not associated
      with a value` 3.11+.
    - `ImportError`: `cannot import name 'X' from 'Y' (PATH)` (+ `. Did you
      mean: 'Z'?` 3.12+); `… from partially initialized module 'Y' (most
      likely due to a circular import) (PATH)`; 3.13+ `… from 'Y' (consider
      renaming 'PATH' if it has the same name as a library you intended to
      import)`. On 3.13 and 3.14 the `consider renaming` form replaces the
      circular-import form only when `Y` is a top-level module in the
      script directory (`sys.path[0]`); inside a package (`pkg.a`) both
      still print `partially initialized module` (re-run here under 3.12,
      3.13.16 and 3.14.6). U4 pins both forms for 3.13 and 3.14: a repository
      with top-level modules hits the first.
    - `ModuleNotFoundError`: `No module named 'X'`, `…; 'Y' is not a package`.
    - `AttributeError`: `'T' object`, `module 'Y'` or `type object 'T'`, then
      `has no attribute 'X'` (+ `. Did you mean: 'Z'?` 3.10+; 3.13 ` (consider
      renaming 'PATH' since it has the same name as the standard library module
      named 'Y' and prevents importing that standard library module)`).
    - `TypeError`: `F() takes N positional argument(s) but M were given` (`F`
      qualified from 3.10: `C.m()`), `unsupported operand type(s) for OP: 'T'
      and 'U'`, `F() got an unexpected keyword argument 'X'` (+ 3.13 `. Did
      you mean 'Z'?`, no colon).
    - Syntax phrases, one line number at most: `invalid syntax`, `unexpected
      indent`, `unindent does not match any outer indentation level`,
      `inconsistent use of tabs and spaces in indentation`; ≤ 3.9 `unexpected
      EOF while parsing`, `expected an indented block`; 3.10+ `expected ':'`,
      `'(' was never closed`, `invalid syntax. Perhaps you forgot a comma?`,
      `expected an indented block after … on line N`.
    - Against 3.12, 3.13 changed only the keyword suggestion and the two
      `consider renaming` forms. Frame caret lines (`~^^`) appear from 3.11
      (PEP 657: 3.11 and 3.12 print `~~~~~~^^^^^` under
      `return d["a"]["b"] + undefined_name`) and are skipped by the parser on
      every version; 3.13 only widened the cases (it also underlines a
      whole-line call such as `f({"a": {}})`, which 3.11 and 3.12 leave
      bare), so U4's parse fixtures carry carets for 3.11-3.14. An ESC byte
      is a miss (3.13 colours under `FORCE_COLOR`,
      which `child_env` drops, `execution/sandbox.py:58-60`).

    Every captured name (each dotted part) is in the closure set. A name slot
    (`X`, `Y`, `F`) also appears on the innermost repository frame's source
    line at the trial's commit; a type slot (`T`, `U`) may instead be a builtin
    (`dir(builtins)`, `NoneType` and the like). At most two numbers of at most
    4 digits, and 300 printable characters. Otherwise: type and frames only.
- *What the templates prove:* every character sent is fixed interpreter text,
  a name the API has already seen, or one of two short numbers, so no
  verbatim, digit-encoded or alphabet-encoded copy of a file passes (a picked
  name is not on the raising line). The residual is a selection channel among
  seen values, each slot chosen by the trial diff:
  - up to 3 frames, each a path among the tracked and touched ones, a closure
    name and a line within that file: about log2(files) + log2(closure) +
    log2(file lines) bits, about 35 bits on a 1,000-file repository with an
    8 MiB closure (10 + 15 + 10);
  - 2 numbers of at most 4 digits, 13.3 bits each;
  - up to 3 names, each among the identifiers on the raising line (a few bits
    each);
  - the type and template, under a byte.

  That is about 105 + 27 + 9 + 6 ≈ 147 bits: **about 18 bytes per attempt at
  worst** (the earlier 16 left the frame line unbounded; the line rule above
  bounds it).
- **Residual per run** (condition 1), bounded by `EDITOR_FIX_RETRIES_PER_RUN`:
  1 × 18 = 18 bytes at 1, 2 × 18 = 36 at the spec's default 2, 72 at the
  bound 4 (§8 Q13 asks the owner to choose 1 or 2). Uncapped at the defaults
  it was 3 rounds (`config.py:243`) × 3 trials (`nodes.py:209`) × 1 retry ×
  18 = 162 bytes (324 at 2 retries; the owner's 480 assumed 5 trials a
  round). 36 bytes holds one short key under a perfect encoding (a
  40-character base64 secret is 30 bytes) and 18 does not, and runs on one
  repository add up (§5).
- **Which messages the per-run figure covers:** trial retries, and from 3c
  the reproducer rewrite (D33), which is a D13 message too. 3c counts each
  rewrite against the same `EDITOR_FIX_RETRIES_PER_RUN` (D36), so the
  per-run figure holds for heal runs; counted separately it would be the
  figure above + 18 × `REPRO_RETRIES` bytes.

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
it to Sonnet 5.5 at `low` only if L2a (2 repetitions) passes W5's gate. *Why:* E8a (12/12, about 0.04 USD a
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
into one new trial, judged from scratch. *Gate:* at least 4 of L2a's 20 OSS
runs (2 of 10 per repetition) have two or more such near misses; restated
proportionally by the Lead in Rev 3 (the owner asked only for W5's gate over
20), and 2 of 10 in either repetition also satisfies the original rule, so
the owner can object to the stricter reading. *Why:* nothing measured
supports it yet.

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
3c, 008 for 3b (O5 order). U1 also makes the CI re-apply loop cover every
file from `003` on (`ci.yml:765` lists only 003 and 004), so later migrations
need no workflow edit.

**D26. New node tests go in new files** (`test_hypotheses_node.py`,
`test_research_node.py`): `tests/orchestrator/test_nodes.py` is 5,661 lines.

**3b (designed here, built as its own step with its own approval, after 3c,
O5; D numbers kept):**

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

**3c (designed here, built as its own step with its own approval, before 3b,
O5):**

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

**Step 3 (owner conditions):**

**D35. How a `behaviour` hypothesis passes (owner condition 2; settled before
U11): no judge is exempted or replaced in Step 3.**

- *Code today:* no judge reads the class, only rule 6
  (`optimization/judges.py:630-682`). `EquivalenceJudge` applies to every
  objective (`:300-302`) under an `output_equivalence` guardrail (`:304-312`)
  and fails on a changed, missing or unstable fingerprint (`:324-337`,
  `anticheat.py:236-273`); rule 3 then rejects every class (`judges.py:646-651`).
- *No replacement exists:* replacing it needs a measured quality bound
  ("accuracy may drop ≤ 0.5 %"), but the runner measures only wall time, CPU
  time, peak RSS (`execution/measure.py:366-368`) and the suite flag (`:595`).
  A `metric_bound` on another metric has no baseline row, so the guardrail
  judge is inconclusive (`judges.py:408`, `:445-450`) and rule 4 blocks.
  Exempting it with only the suite in its place would let wrong-but-fast output
  reach review on tests written for other purposes, with a human the only
  check; CLAUDE.md says autonomy comes from automatic checks.
- **The rule:**
  - Under an `output_equivalence` guardrail (every live suite through
    `tests/live/conftest.py:826-839` and `CorpusRepo.guardrails`,
    `tests/live/corpus.py:206-221`, which OSS reuses, `tests/live/oss.py:143-146`;
    the Step 2 E2E, `tests/e2e/test_step2.py:241-246`), a behaviour hypothesis
    reaches review only with identical stdout and declared output file on
    every workload. The fingerprint is sha256 over (length, sha256) of stdout
    plus the workload's `output_file` when set (`execution/measure.py:199-210`,
    `:290-300`); stderr, logging and any undeclared file are not compared, so a
    behaviour change confined to them passes equivalence. One that alters a
    workload's stdout or declared output file is rejected by rule 3. "Behaviour" means what
    the generator prompt says (`generate.py:125-127`, `:141`): results may
    change on inputs the workloads do not exercise, which is why it is reviewed.
  - Without that guardrail (`define` adds only the RSS bound,
    `nodes.py:1300-1313`), equivalence is `not_applicable` (`judges.py:306-312`)
    and behaviour passes on the efficiency gates (§8 Q12).
  - Still gating every class: rules 1-5 (violations, trial failure, any failed
    judge, an inconclusive primary or guardrail judge, a passed objective).
- **Status (U2, U11):** a `review` verdict sets `HypothesisStatus.trialled`,
  as `needs_approval` does: no new status, so `chk_hypothesis_status`
  (`003:391-392`) is unchanged. `_STATUS_AFTER_VERDICT` (`nodes.py:280-285`)
  lists only keep, reject, inconclusive and needs_approval, and the verdicts
  node (`:1655`) and the approval gate's resume (`:1730`) index it, so U11
  adds the `review` entry (without it the first review verdict raises
  `KeyError`).
- **Code (U11):** rule 6, plus the `_STATUS_AFTER_VERDICT` entry and the
  verdicts event text (`nodes.py:1659-1664`, which names four outcomes) in
  `nodes.py`. Combine re-judges the review set as
  `efficiency` (`orchestrator/combine_node.py:231-246`, `holds` iff `keep`,
  `common/models.py:740`); with no class-reading judge that is the same test.
  U11's tests pin the three cases and that combine.
- *Later:* a quality bound could replace equivalence for behaviour (reported,
  not gating, only when that bound passes): a frozen-rule change with its own
  decision (§8 Q11). 3c's exemption (D34) covers only the reproducer's
  workloads.
- *Why:* the default objective says outputs must not change; a user who has not
  said how much quality may drop has not allowed output to change.

**D36. 3c before 3b (O5): what 3c would have had from 3b.**

- *The rewrite's closure budget:* each reproducer rewrite (`REPRO_RETRIES`,
  D33) is a D13 message, so it is counted against the run's
  `EDITOR_FIX_RETRIES_PER_RUN` like a trial retry; when none is left, the
  rewrite is not sent and the heal is refused with that note. One per-run
  figure (D13) then bounds every channel from run output to the API (C3
  counts it, C4's retry exclusion keeps the reproducer's workloads out of
  trial retries).
- *Packages:* a heal whose fix needs a missing third-party module (a
  `ModuleNotFoundError` for a module outside the repository and the standard
  library) is refused before the reproducer request and listed as a
  `needs_package` proposal, so the user is asked.
- *A lockfile environment:* 3c measures in the ambient environment, as Step 2
  does; heal runs move to E0 when 3b lands (D27).
- *Migrations* swap: 007 is 3c's, 008 is 3b's (D25, §3.5). Nothing else in
  D33-D34 or D10 uses a 3b part.
- *The exception:* if preparing the Step 5 dogfood shows the owner's code
  needs a new package to improve, the Lead proposes 3b first at the 3c briefing.

---

## 1 Scope and non-goals

**Step 3:** Wave 1 (U1-U16, independent of the A/B) and Wave 2 (the A/B
follow-up, V1-V6 and the re-test) are approved (owner, 2026-10-24). Wave 3
(lessons and evolution, W1-W6, each gated) is **held until Wave 1's live runs
(L1a, L1b, L2a and, when it runs, L2b) report**, as listed in §7.

**3c, then 3b** (O5) are designed in D33-D34 and D27-D32 and outlined in §7.
Each is built after Step 3 as its own step, with its own briefing, approval
and security review.

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
      |          ^-- fixable own crash, closure-checked, <= 1 retry a trial, 2 a run (Q13) +
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
| `EDITOR_FIX_RETRIES` | 1 (per trial) | 0-2 |
| `EDITOR_FIX_RETRIES_PER_RUN` | 2 until §8 Q13 is answered (1 is offered: 18 bytes a run against 36, D13) | 0-4; checked in the trials node (D12, U16); 3c's rewrites count against it (D36) |
| `RETRY_CLOSURE_MAX_SOURCE_BYTES` | 8 MiB | ≥ 1 |

- Role chains run without fallbacks, except the editor when `EDITOR_MODEL` is
  unset, which keeps today's chain (`clients/cost.py:110-119`).
- `_every_billed_model_is_priced` (`config.py:319-326`) and
  `_effort_accepted_by_every_serving_model` (`:328-351`) are extended to every
  role.
- `role_settings(base, model, *, fallbacks)` moves from
  `tests/live/discovery.py:163-171` (`model_settings`) into `common/config.py`.
- 3c adds `REPRO_MODEL` / `REPRO_EFFORT` (Sonnet 5.5 / `medium`, unmeasured),
  `REPRO_VARIANTS=2` and `REPRO_RETRIES=1`.
- 3b adds `ACQUIRE_ENABLED=False`, `UV_EXECUTABLE`, `UV_VERSION`, `UV_SHA256`,
  `PACKAGE_MIN_PROJECT_AGE_DAYS=90`, `PACKAGE_MIN_VERSION_AGE_DAYS=14`,
  `PACKAGE_LICENCES`, `PACKAGES_PER_HYPOTHESIS=1` and
  `ACQUIRE_MAX_BYTES=500 MiB`.

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

3c adds `run_kind`, `heal_case` and `reproducer`. 3b adds
`env_baselines: dict[str, Baseline]` and `capabilities: list[CapabilityRecord]`.

### 3.3 Models (`common/models.py`, U2)

- `VerdictOutcome.review = "review"`. No new `HypothesisStatus`: a reviewed
  hypothesis is `trialled`, as for `needs_approval` (D35; U11 adds the
  `_STATUS_AFTER_VERDICT` entry).
- `Trial.attempts: int = 1` and `Trial.retry_notes: tuple[str, ...] = ()`. Both
  are serde-safe, and both are stored in the JSONB trials array.
- `Hypothesis.parked_reason: str | None = None`.
- 3c: `HealCase(kind, target, signature)`;
  `ExceptionSignature(type, message, frames)`;
  `Reproducer(path, sha256, variants_sha256, signature, baseline_failures)`.
- 3b: `Hypothesis.packages: tuple[PackageRequest, ...] = ()` (a name and a
  reason, never a version or a URL) and `Trial.env_lock_sha256: str | None`.

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
  `generator_n`, `generator_max_calls`, `matcher_k`, `discovery_max_share`,
  `fix_retries_per_run: int = 0` (Step 2 has no retry) and
  `playbook: tuple[Technique, ...] = ()`. U2 owns these fields and their
  `__post_init__` checks (it freezes the shared contracts, D4); U8, U9, U11 and
  U16 only read them.

**Retry (U4, U6):**

- `procrun.RunFailure` (`procrun.py:112-117`) gains `kind: str = "other"`,
  `exit_tail: bytes | None = None` and `workload_id: str | None = None`. Only
  `measure.launch`'s exit branch (`measure.py:255-259`) sets
  `kind="exit"`, the tail and the workload. Today only the tail's last line
  survives.
- `execution/crash.py`: `parse_traceback(tail: bytes) -> CrashReport | None`.
  It handles chained exceptions, the `SyntaxError` caret and frame caret
  lines (`~^^`), for Python 3.8-3.14.
- `execution/retry.py`:
  - `ClosureIndex.build(diff: str, sources: Mapping[str, bytes])`;
  - `classify(failure, *, closure, tracked, touched, excluded_workloads) -> TrialFeedback | None`;
  - `TrialFeedback(exc_type, frames, message | None)`.
- `EditTask.feedback: TrialFeedback | None = None` (`execution/protocols.py:137-146`).
- `TrialBrief.fix_retries_left: int = 0` (`protocols.py:76-81`; U6 adds and
  reads it, U16 sets it).
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

**007** (3c): `heal` in `chk_hypothesis_source` (`003:384`) and `reproduce` in
`chk_task_phase` (`003:253-257`). **008** (3b): new `packages` columns, a
`run_packages` table, and `acquire` in `chk_task_phase`.

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
   - `trial.attempts ≤ fix_retries` (per trial);
   - `trial.attempts − 1 < brief.fix_retries_left` (the run's cap, D12);
   - `budget.remaining ≥ retry_floor_usd`.
3. The retry:
   1. `GitWorkspace.reset(handle)`.
   2. A fresh `EditTask` with the feedback and a new token, on the same `Budget`.
   3. A merge of `written` maps, under the file and byte limits for the union.
   4. `stage_all`, capture against the base, every anti-cheat rule.
   5. `commit(..., parent=base)`, then `update_ref(own_ref, commit2, commit1)`
      and `progress.moved = commit2`.
   6. A fresh measurement.
4. An unaffordable retry, a spent run cap, an editor stop, a capture violation
   or a retry that crashes again keeps the first failure. The note goes in
   `retry_notes`, and the result is never `TrialUnaffordable`. An exception
   takes `_undo_own_ref` (`:465-487`).
   - **A retry that crashes with another fixable error** is not retried at
     the default `EDITOR_FIX_RETRIES=1` (the limit is per trial). At 2, the
     second retry is fed the latest crash, closure-checked; if it crashes too,
     the first failure is still kept. Each later crash's type is a
     `retry_notes` entry, shown in the trial's report row (U11): "NameError;
     retry: TypeError, first failure kept".
5. Wall time: a retried trial measures twice. The per-workload timeouts and
   `TEST_TIMEOUT_S` (`config.py:279`) bound each run, `EDITOR_FIX_RETRIES ≤ 2`
   the factor; live timeouts grow in U13. No run-level wall cap until the
   Step 4 CLI (owner, §8 Q8); the report's total-time line (§4.5) shows it now.

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
     passed (identical stdout and declared output file on every workload where
     the run guards them; stderr and other files not compared, D35), re-tested
     together; review before merging; not merged into
     `engine/run-<id>`, never pushed. Not re-tested together with
     `engine/run-<id>`; merging both is unproven."
   - The main report lists the review branch, and the parked ideas as
     proposals, with the same sentence: "`engine/review-<id>` was not re-tested
     together with this branch; merging both is unproven."
4. Learn: review lessons carry outcome `review`, which ranking treats as
   neutral.
5. Both reports (U11, `_report`, `nodes.py:1117`) gain each trial's
   `retry_notes` in its row (§4.4) and a total-time line, "Total time: H:MM,
   first event to delivery, any approval pause included; N trial(s) retried",
   from the first `EngineEvent.at` (`common/models.py:658`; state events,
   `orchestrator/state.py:112`) to when the report is built.

### 4.5b 3c and 3b behaviour

D33-D34, D27-D32, A §4.5-4.6 and B §4.4 (1-8) and §4.5 (1-6), as corrected above;
each step's briefing restates it.

### 4.6 Failure modes

| Situation | Result |
| --- | --- |
| `save_trial` refuses or raises | The run fails with the round's progress kept (U1); `h1` and slugs no longer trigger it |
| The generator is empty, refuses or is unusable; the matcher fails | Soft note, spend charged; the router ends the run when nothing is left |
| Discovery is unaffordable (pre-send, or `d ≤ cost_usd`) | `discovery_exhausted`; the run trials the pool, then combines |
| The retry is not fixable, unaffordable, over the run cap or crashes again | The first failure is kept, with a note shown in the report; timeouts, `AssertionError` and suite failures are never retried |
| A behaviour trial changes a guarded output (stdout or the declared output file) | Rejected by rule 3 (equivalence failed, D35); never on the review branch. A change confined to stderr, logging or an undeclared file is not seen by equivalence |
| The crash message fails a template or closure | Type and frames only, noted in `retry_notes` |
| The review combination does not hold | No review branch, said in the report; the run branch is unaffected |
| A novel hypothesis | Caller ones interrupt as in Step 2; generated ones are parked |

---

## 5 Security

| Threat | Controls |
| --- | --- |
| Injection relayed by generated hypotheses into the editor | D11: fence plus token refusal (`editor.py:463`); the generator already fences repository text (`generate.py:215-242`) |
| Run output carrying secrets to the API (retry, 3c rewrite) | D13: a message only on a per-version CPython template with closure-checked names (name slots on the raising line), ≤ 2 numbers of ≤ 4 digits, ≤ 300 characters, else type and frames; ≤ 3 tracked or touched frames, no deny-listed paths or source lines; fenced; never stdout, timings, fingerprints, suite output or verdicts; canaries in U4 and E3-D; a frame's line must lie within its file. Residual: about 18 bytes per attempt × `EDITOR_FIX_RETRIES_PER_RUN` (36 bytes a run at the default 2, 18 at 1, 72 at the bound; §8 Q13), adding up across runs. The per-run figure covers trial retries and 3c's rewrites only because 3c counts each rewrite against the same cap (D36); counted separately a heal run would add 18 × `REPRO_RETRIES` |
| 3c: injection through the error report | D33: the report is fenced with a per-request token and refused if it holds it (`Fence.holds`, `structured.py:126`); the variant writer never sees it |
| Retry as a reward-hacking channel | Own workload crash only; it runs before any judge (`trial_runner.py:502-587`); a full re-capture and anti-cheat pass on the union diff; one commit on the base |
| Discovery spend starving proofs | D7 narrowed budget enforced by `Budget.check` before send; `DISCOVERY_MAX_SHARE`; `discovery_cost_usd` reported |
| Output-changing behaviour reaching review on weak evidence | D35: equivalence gates every class wherever an `output_equivalence` guardrail is set (every live suite and E2E), over stdout and the declared output file only; with no guardrail nothing checks output for any class (§8 Q12, STATUS Known gap); no exemption until a measured quality bound exists |
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
(retry, fence), U10 (transports), U16 (run retry cap), plus every 3c and 3b
unit named in §7.

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
  rejects; a `novel` entry in `GENERATED_CLASSES` is refused;
  `EDITOR_FIX_RETRIES_PER_RUN` outside 0-4 is refused;
  `NodeContext.fix_retries_per_run` defaults to 0.
- **U4:**
  - `parse_traceback` on 3.8-3.14 stderr (chained, `SyntaxError` caret, frame
    caret lines, cut tail);
  - `classify` gives `None` for a timeout, a signal, `AssertionError`, the
    suite and an excluded workload;
  - each template, per supported version, passes with closure-checked names;
  - **live templates** (new `tests/execution/test_retry_templates.py`): each
    template's snippet runs under every `python3.N` on PATH (3.8-3.14) and
    stderr's last line must match that version's template; a missing
    interpreter skips locally (as `tests/execution/test_profiler.py:480-483`),
    never in CI once U3's PATH check (`ci.yml:385-397`, 3.8-3.12 today)
    covers 3.13 and 3.14, so 3.14 is proven there from U3's commit on (U3
    lands before U4);
  - the 3.13 forms pass with the path dropped; an ESC byte gives type and
    frames only;
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
    most 3 frames are sent;
  - a frame whose line is 0 or exceeds its file's line count at the trial's
    commit (a forged `co_firstlineno`) is dropped;
  - the 3.13 and 3.14 `ImportError` forms: a circular import between two
    top-level script-directory modules gives the `consider renaming` form, one
    inside a package the `partially initialized` form; both pass.
- **U5:** each new pattern refuses a diff.
- **U6** (new `tests/execution/test_trial_retry.py`):
  - `NameError` then a fixing edit gives `attempts == 2` and one commit whose
    parent is the base (`combine._unfit` passes), with no `unrecorded_write`;
  - a reset removes a file the failed run wrote;
  - an unaffordable retry keeps the first failure;
  - the per-trial cap holds; `fix_retries_left=0` gives no retry and the
    "spent" note, and never reaches the editor prompt;
  - a retry crashing with another fixable error keeps the first failure and
    notes the second type;
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
  generator's research block stays empty (`generate.py:215-243`); the factory
  sets `fix_retries_per_run` from `EDITOR_FIX_RETRIES_PER_RUN`.
- **U11:**
  - rule 6 for all three classes;
  - a `review` verdict passes `verdicts` (status `trialled`, a `review` count
    in the event text) and `approval_gate`'s resume with no `KeyError`;
  - D35: under `output_equivalence`, changed output rejects (rule 3) and
    identical output gives `review`; without it, `review`; the review set's
    combine holds under the same judges;
  - both reports carry the total-time line and the rows' retry notes;
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
- **U16** (new `tests/orchestrator/test_run_retry_cap.py`): at a cap of 2 the
  node passes 2, 1, then 0, and a third fixable crash keeps its first failure
  with the "spent" note; a resume counts from the checkpointed `trials`; a
  runner reporting more retries than it was given is refused; a cap of 0
  reproduces Step 2.

**E2E** (`tests/e2e/test_step3.py`, marker `slow`, real git and sandbox, scripted
Claude):

- **E3-A:** `candidates=()`, plus a scripted generator reply, reaches a delivered
  branch. A second run stopped with `interrupt_before=["trials"]` (the same
  mechanism as `tests/orchestrator/test_graph_e2e.py:431`, which stops before
  `verdicts`, here with `trials`) and resumed by a fresh graph
  records exactly one generator request. (With `candidates=()` no run reaches
  the gate: only caller `novel` ideas do.)
- **E3-E:** one caller `novel` candidate beside the scripted generator pauses
  at `approval_gate` and is resumed; the generator count is unchanged by the
  resume (zero: caller ideas go first, and the gate leads to `combine`).
- **E3-B:** a `NameError` from the first edit is fixed by the retry, and the run
  delivers with `attempts=2`; with `EDITOR_FIX_RETRIES_PER_RUN=0` the same run
  keeps the first failure.
- **E3-C:** under an `output_equivalence` guardrail, a behaviour change with
  identical outputs lands on `engine/review-<id>` with no pause; a second
  behaviour change that alters output is rejected by rule 3; a novel one is
  parked.
- **E3-D:** injected crash messages are withheld from the wire: one holding a
  canary verbatim, one carrying a planted file's bytes as decimal numbers in a
  `NameError` message, and one picking diff-defined alphabet names per byte.
  The scripted transport records the bodies; no body holds the canary, its
  decimal byte string, and no `<untrusted_run_output>` block holds an
  alphabet name.

**Live** (CI `live-smoke` only, one suite at a time under the 150 USD ceiling;
every run lands its cost and finding in the ledger). Expected costs come from
Window 0 rows: E5 about 0.10 USD per task-arm (Sonnet engine, 10.20 / 100); H
0.11 and O 0.30 USD a run (Opus); M 0.45x Opus; E3 0.048 USD per repo-arm with
the grader. Each A/B cap is `ab_need(plan)` (`tests/live/discovery_ab.py:134-137`):
per task `AB_GEN_CAP_USD` (a `ceil_usd` constant, `:108-114`; 0.8 at E5's
settings, as the `ab` need 140 = 2 × 25 × 2.8 shows) plus both run caps,
rounded up to a whole USD as `ci.yml:636-637` does; the ledger admits a test
only if it fits with earlier spend and open caps (`tests/live/conftest.py:12-17`).

| Run | Measures | Feeds | Cap (sum of worst cases) | Expected | Cheapest arm |
| --- | --- | --- | --- | --- | --- |
| L1a `hard`, `wired` | Wired engine wins with no hypothesis handed over; attempts per trial (retry rate); counts per class; behaviour trials rejected by equivalence; discovery cost | Wave 1 acceptance; the D9 class default | 10 × 5 = 50 | ~1.0 | Sonnet engine (E5 ran it on this corpus) |
| L1b `corpus`, `wired` | Control false wins with generation in the loop | The same | 15 × 5 = 75 | ~0.8 | Sonnet engine |
| L2a `oss`, `wired`, Sonnet low editor, 2 reps (owner) | Delivered against aimed-Opus 6/10 per rep; near-miss counts; retry rate | W5 (`EDITOR_MODEL`; ≥ 10 of 20), the W4 gate | 20 × 5 = 100 | ~3.0 | Sonnet first |
| L2b `oss`, `wired`, Opus editor | Only if L2a < 10/20 | W5 | 10 × 5 = 50 | ~3.0 | - |
| L3 `grader` | Opus 4.8 grader agreement on about 10 hand labels (≥ 9/10, no false positive on near misses) | Whether L4's hit@k counts as validated | 10 × `GRADE_WORST_USD` (`discovery_grader.py:298`) | < 0.5 | - |
| L4 `sweep-record`, Sonnet medium, v1 + v2 | Recorded replies; v2 blind hit@1 | U12's real fixture; the v2 saturation pre-check | Sweep need for 1 arm × 37 repos (guard-computed; about 23) | ~1.8 | One arm only |
| L5a `ab-v2`, arm A only, 1 rep | Is v2 saturated for executed wins (≥ 90 % means revise) | Whether L5b runs | `ab_need`: 12 × (0.8 + 1) = 21.6, need 22 | ~0.6 (+0.6 for the one rerun on a revised v2) | A only |
| L5b `ab-v2`, both arms, 2 reps | c, b, gains, controls | D2 pooled rule | `ab_need`: 24 × (0.8 + 2) = 67.2, need 68 | ~4.9 | Run only after L5a |
| L5c `ab-oss`, both arms, 1 rep, 2 USD run cap | The same on small gains | D2 pooled rule | `ab_need`: 10 × (0.8 + 4) = 48, need 48 | ~3.0 | Skipped if it cannot change the decision |
| W1 refresh | The eval fixture after the prompt change | W1 | `sweep_need` for 1 arm × the 25 v1 repos (`discovery_sweep.py:139-143`, guard-computed; about 25/37 of L4's 23, need about 16) | ~0.6 | One arm |

The Step 3 expected total is about 16.5-19.5 USD (about 22.5 with L2b), all
in Window 1, with L2a's second repetition (about 1.50 USD, owner) and the one L5a rerun (0.6) if v2 is revised; L5a is not repeated a
second time. It replaces Window 1 row C (`STATUS.md` "Window 1", about 30 USD of Opus
extraction). Reruns happen only when a fix changes what is measured. 3c's L7
(the heal corpus) and 3b's L6 (the network job, 0 tokens) are planned with their
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
| U3 | pip-audit in CI; interpreters 3.13 and 3.14 | `.github/workflows/ci.yml` (python job: pip-audit, and the workload-interpreter install and PATH check at `:380-397` extended to 3.8-3.14), `.github/workflows/security.yml` | ~50 | U1 | correctness (CI) |
| U4 | Crash parser, classifier, closure, templates 3.8-3.14 | `execution/procrun.py`, `execution/measure.py` (`launch`), `execution/crash.py`, `execution/retry.py` + tests, `tests/execution/test_retry_templates.py` | ~410 | U1, U3 (commit order) | security |
| U5 | Protected-pattern gaps | `optimization/anticheat.py` + tests | ~60 | U1 | security |
| U6 | Retry flow and fence | `execution/trial_runner.py`, `execution/git.py`, `execution/protocols.py` (`EditTask.feedback`, `TrialBrief.fix_retries_left`), `execution/editor.py`, `tests/execution/test_trial_retry.py` | ~400 | U2, U4 | security; correctness |
| U7 | Adapters and `rank_generated` | `optimization/hypothesis_source.py`, `optimization/ranking.py` + tests | ~250 | U2 | correctness |
| U8 | Hypotheses node and router | `orchestrator/nodes.py` (`hypotheses`, `after_verdicts`), `tests/orchestrator/test_hypotheses_node.py` | ~380 | U7 | correctness; spec |
| U9 | Research node (matched, off) | `orchestrator/nodes.py` (`research`), `tests/orchestrator/test_research_node.py` | ~200 | U8 | correctness |
| U10 | Factory: roles, playbook, retry floor and run retry cap | `orchestrator/factory.py`, `tests/orchestrator/test_factory_roles.py` | ~220 | U6, U7 | security (transports) |
| U11 | Review-branch delivery (D10, D35), total-time line, retry notes | `optimization/judges.py` (rule 6 only), `orchestrator/nodes.py` (`_STATUS_AFTER_VERDICT`, `verdicts` and its event text, `combine`, `deliver`, `_report`), `infrastructure/schema/006_review_outcome.sql`, `tests/orchestrator/test_review_delivery.py`, `tests/optimization/test_judges.py` (rule 6, D35) | ~410 | U9 | spec (user decision 1, D35); correctness |
| U12 | Offline discovery eval | `tests/live/discovery_grader.py`, `tests/live/discovery_sweep.py`, `tests/optimization/test_discovery_eval.py`, `tests/fixtures/discovery_eval/seed.json` | ~300 | U7 | weakened-test |
| U13 | Live plumbing | `tests/live/corpus.py`, `tests/live/oss.py`, `tests/live/test_*_guards.py`, `.github/workflows/ci.yml` (live-smoke) | ~250 | U3, U10 | cost (caps) |
| U14 | E2E E3-A to E3-E | `tests/e2e/test_step3.py`, `tests/fixtures/step3/` | ~350 | U13, U16 | correctness |
| U15 | Docs (Lead) | `CLAUDE.md` (D10 wording, Step 3 row per O1, 3c before 3b per O5), `services/python_agents/CLAUDE.md` (rule 6, branches, state keys), `README.md`, `STATUS.md` (dev-log rows 3c, 3b and 6, today 0-5 at `STATUS.md:62-70`; Window 1 row C; D2's rule before L5a; §8 Q12 as a Known gap) | ~150 | all | spec |
| U16 | Run retry cap (D12) | `orchestrator/nodes.py` (`trials`, `run_one`, `_runner_trial_problems` only), `tests/orchestrator/test_run_retry_cap.py` | ~120 | U10, U11 | security; correctness |

Build order:

1. U1, alone.
2. U2, U3, U4 and U5, in parallel (disjoint files); U3's commit lands before
   U4's, so U4's live-template tests never skip 3.13 or 3.14 in CI.
3. U6 and U7.
4. U8 and U12.
5. U9 and U10.
6. U11 and U13.
7. U16.
8. U14.
9. U15.
10. The live runs: L1a, then L1b, then L2a, 2 repetitions (L2b only if
    needed). They report before Wave 3 starts (owner).

`nodes.py` (U1, U2, U8, U9, U11, U16) and `ci.yml` (U1, U3, U13) never share
a batch; U8 branches from U2's commit, U9 from U8's, U11 from U9's, U16 from
U11's, U13 from U3's. Until U16 lands, `fix_retries_left` stays 0 and no retry
runs (fail closed).

That is 16 units, about 4,100 lines (U4, U6 and U11 at about 400-410). After step 5 of this order, a run needs no
hypothesis handed to it; after step 7, a fixable crash recovers.

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

**Wave 3** (lessons and evolution; held until Wave 1's live runs L1a, L1b,
L2a and, when it runs, L2b report (owner), then each unit gated):

| # | Unit | Files | Lines | Gate |
| --- | --- | --- | --- | --- |
| W1 | Lessons and `avoid_titles` in the generator prompt (fenced) | `optimization/generate.py` + tests | ~220 | Wave 1; a W1 refresh afterwards |
| W2 | Combine-failed lesson discount | `learning/lessons.py`, `orchestrator/nodes.py` (`learn`) | ~150 | Wave 1 |
| W3 | Profiler `Hotspot.tags` (never set in `src` today) | `execution/profiler.py`, `execution/_profile_shim.py` (not re-read) | ~200 | lowest priority; dropped if Wave 3 runs long |
| W4 | Evolution: near-miss compounds | `optimization/evolve.py`, `orchestrator/nodes.py` (a hook in `hypotheses`) | ~380 | L2a: ≥ 4/20 runs (2/10 per rep) with ≥ 2 disjoint near misses |
| W5 | `EDITOR_MODEL` default flip to Sonnet low | `common/config.py` | ~10 | L2a: Sonnet delivers on ≥ 10 of 20 runs (2 reps; the Opus-aimed 6/10 − 1 per rep), with 0 control wins in L1b |
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

**3c outline** (its own step, built first, O5; about 7 units):

- C0: contracts and 007; the `needs_package` refusal (D36).
- C1: the shim and signature matching.
- C2: the reproducer writer, the separate variant writer and the static checks
  (security).
- C3: the reproduce node, freeze, the N/N baseline and `--deselect`
  (`_require_trustworthy_baseline`, `nodes.py:647`); each rewrite counted
  against `EDITOR_FIX_RETRIES_PER_RUN` (D36).
- C4: `HealJudge`, the equivalence exemption, `heal_tamper`, the no-new-file
  rule and the retry exclusion (security).
- C5: delivery of commit R, then commit F, on the review branch, and the report.
- C6: the E2E corpus (5 planted bugs, 3 controls) and L7.

**3b outline** (its own step, built after 3c, O5; about 10 units):

- B0: contracts and 008.
- B1: the name snapshot and near miss.
- B2: the pure policy.
- B3: wheel inspection.
- B4: registry and allowlist proxy (security).
- B5: `uv` provenance, lockfile and fetch under read confinement, plus the
  Landlock probe (security).
- B6: offline envs, `make_phase(env=)` (`execution/measure.py:132`), the
  `_env`/`_wheels` owner and `_host` (`measure.py:321`) (security).
- B7: the acquire node, C1, capture from C1, the whole-run E0 baseline (heal
  runs included, D36) and the ambient ratio (security).
- B8: combine with packages, the drop with dynamic fallback, the tie-break and
  the install line.
- B9: E2E and L6.

---

## 8 Open questions (Q1-Q5 and Q8 answered by the owner, 2026-10-24; Q2's D35 reading to confirm; Q13 open)

1. **The CLAUDE.md Step 3 row.** *Answered (O1):* "generator wired, engine
   self-retry, review delivery, hard corpus v2 and the retrieval re-test,
   lessons and evolution; paper intake conditional (STATUS)", Sonnet for
   discovery (U15).
2. **Behaviour ideas by default** (D9). *Answered (O2):* yes, under D35; narrow
   to efficiency if they take over a third of slots without a review win.
   *To confirm:* D35 is the Lead's reading of condition 2, not one of its two
   options; under it O2 yields review branches only for behaviour ideas that
   keep every guarded output. Owner to confirm before U11 (build-order step
   6).
3. **The re-test (L5, about 8.50 USD, caps up to 68).** *Answered (O3):* yes.
4. **3b lockfiles.** *Answered (O4):* hash-pinned `requirements*.txt` first;
   `uv.lock` only after probing `uv lock --no-build` on dynamic metadata
   (**unverified**); no lockfile means asking the user.
5. **3b and 3c order.** *Answered (O5), reversing the recommendation:* 3c
   first (D36).
6. **The reproducer model.** Sonnet 5.5 medium is a guess. *Recommended:* L7
   compares it with Opus in 3c.
7. **Small OSS gains under the noise floor** (4/10). A paired, interleaved rule
   would change a frozen judge. *Recommended:* scope it for Step 5, not Step 3.
8. **A run-level wall-time cap.** *Answered:* a total-time line now (§4.5);
   `--max-time` with the Step 4 CLI.
9. **Review branches and learning.** A merge of `engine/review-<id>` is not
   detected, so review lessons stay neutral. *Recommended:* accept until the
   Step 4 GitHub App observes merges.
10. **Novel lessons across runs** (fresh ids, no technique). *Recommended:* rely
    on W1's prompt channel; no title-key matching in Step 3.
11. **A quality bound in place of equivalence for behaviour** (D35).
    *Recommended:* decide it with a workload-reported quality metric and
    `--goal` parsing (Step 4).
12. **No default output check.** `define` adds only the RSS bound
    (`nodes.py:1300-1313`), so a caller passing no guardrails gets no output
    check for any class, unlike CLAUDE.md's default objective; every live
    suite and E2E passes one. *Recommended:* a STATUS Known gap now (U15); the
    Step 4 CLI adds `output_equivalence` by default (it needs a deterministic
    output, `nodes.py:661-673`).
13. **The per-run retry default** (condition 1; the owner said only "a small
    default"). `EDITOR_FIX_RETRIES_PER_RUN=1` leaves about 18 bytes a run,
    below a 40-character base64 key (30 bytes); `2` leaves about 36 bytes,
    which holds one, and gives L1a twice the retry data. The bound stays 0-4
    either way (72 bytes). The spec builds 2 until answered; the value is one
    constant in U2 and one factory line in U10. *Recommended:* 1, since the
    owner's stated concern was a short key.
