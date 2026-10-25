# Step 3 spec: wired discovery, self-retry, review delivery, quality check, noise rule (3c and 3b designed)

Base: `claude/step3-research` at `7d8c40f`. U1 has landed (`3ee4e76`: `005`,
`persistence/postgres.py`, `common/errors.py`, the `save_trial` guard at
`orchestrator/nodes.py:1547-1553`); no other `src` change since `322f08f`.
Every cite is at `7d8c40f` (Revision 3's `nodes.py` cites after `:1541`
moved 6 lines, nothing else did). Paths are relative to `services/python_agents/src/autonomous_ai_agents/`
unless they start with `tests/`, `infrastructure/` or `.github/`. Anything not
re-read is marked **(not re-read)**, anything inferred **unverified**.

**Revision 4 (owner, second round, binding).** O6-O10 (§0). D35 rewritten: an
output change is judged by a quality check in Step 3 (D37-D40, new); the output
check is on by default (D40); `EDITOR_FIX_RETRIES_PER_RUN` is 1, bound 1, with
B-R2 for 2 (D12, D13); the noise rule moves into Step 3 (D41-D42), evidenced by
noise run 40082852536. New units U17-U26; U11 resized, U10 and U13 grown; U1
done (§7); §3, §4.7, §5, §6 (L0) and §8 (Q2, Q7, Q11-Q13 answered) updated.
The review of Revision 4 is applied in place: the B-R2 gate and who flips it,
ABBA order, L0 redefined, frozen files read-denied to the editor, U10 moved
to batch 7, and the Lead's own readings listed for objection (§8 Q17).

**Revisions 3 and 2:** the owner's conditions (per-run retry cap, 3.13/3.14
templates, O1-O5, total time, L2a × 2) and the critic's fixes.

**About the A/B.** E5 is finished (Actions run 40063812021, 10.20 USD) and
applied: retrieval is off, no paper code is built. The re-test (D2, L5) is a
smaller A/B on a corpus built in Wave 2.

---

## 0 Decisions

**Owner decisions, first round (2026-10-24; §8 Q1-Q5).**

- **O1.** The CLAUDE.md Step 3 row changes as §8 Q1 says (U15).
- **O2.** Generated behaviour ideas by default (D9), under D35.
- **O3.** The re-test is approved (about 8.50 USD); its pooled rule lands in
  STATUS before L5a (D2).
- **O4.** 3b lockfiles: hash-pinned `requirements*.txt` first.
- **O5.** 3c before 3b, unless packages block the dogfood on the owner's code.
  *Why (owner):* 3c has no network boundary; 3b needs a security review of a
  network-on fetch, an allowlist proxy and an unverified Landlock-`uv` interaction (D36).

**Owner decisions, second round (2026-10-24; supersede Rev 3's D35 reading;
§8 Q2, Q7, Q11, Q12, Q13 answered).**

- **O6.** Step 3 is approved: Wave 1 and Wave 2; Wave 3 held until Wave 1's
  live runs report.
- **O7.** A change that alters output is judged by a quality check, in Step 3:
  the user confirms a quality number once; the change passes only if it stays
  the same, improves or drops no more than the user allows; cosmetic
  differences may count as equal; such changes always go to the review branch
  with a clear label. Quality judgement with no number stays Step 4 (D35,
  D37-D40).
- **O8.** `EDITOR_FIX_RETRIES_PER_RUN = 1`. Raising it to 2 waits for attack
  tests and safeguards that close the error-message channel (B-R2, D13).
- **O9.** The output check is on by default: with no quality number, results
  must stay identical; with one, an output change that keeps or improves it
  goes to review marked as a result change (D35, D40).
- **O10.** Real speedups, not luck: alternating measurement, a second check of
  every winner before it is kept, a per-project floor never below 2 %, and
  each gain reported with margin, confirmations and a label (D41-D42).

**D1. The A/B result is applied: no paper code in Step 3, retrieval off by
default.**

- `RESEARCH_RETRIEVAL` takes `blind` (default) or `matched` (built, tested
  offline, off). No `PAPER_PRIORITY` setting.
- *Why:* the pre-registered rule (`tests/live/discovery_ab.py:117`,
  `MIN_DISCORDANT_LEAD = 3`) gave c − b = −3: B lost three tasks A won and won
  none A lost, gained 5-11 points less on four shared wins, and cost 0.110
  against 0.090 USD a win. Paper cards would reach the generator the same way,
  noisier. `matched` stays (about 200 lines) for D2 and a later flip.

**D2. Retrieval gets one re-test, on a set where blind generation does not
saturate; it is the only path back to paper intake.**

- The instrument is the E5 suite (`tests/live/discovery_ab.py`), generalised
  to a selectable corpus (v1, v2, oss) and an A-only mode; today the set is
  fixed (`AB_REPOS = (*CORPUS, *HARD_CORPUS)`, `:115`).
- Order, cheapest first:
  1. Arm A alone on hard corpus v2 (L5a). If blind wins at least 90 % of the
     v2 slowdowns, v2 is saturated: it is revised and arm B is not paid for.
     L5a re-runs once on the revised v2; a second saturation ends the re-test.
  2. Both arms on v2, 2 repetitions (L5b).
  3. Both arms on OSS, 1 repetition (L5c), skipped when its 10 tasks cannot
     change the pooled decision.
- **The pooled rule** goes to STATUS before L5a (O3): over the v2 and OSS
  slowdowns `c − b ≥ 3`, and B's false wins on controls do not exceed A's.
  Met: `RESEARCH_RETRIEVAL` flips to `matched` (W6) and paper intake becomes a
  conditional step (§7, P). Otherwise the playbook stays a test fixture.
- *Why:* blind won 44/44 in E5, which could detect harm, not help; about 8 USD
  against tens of hours of paper code.

**D3. The Postgres id fix (U1, landed in `3ee4e76`): id columns widened, not
mapped** (user decision 3). `save_trial`, `save_verdict` and `save_lesson`
(`persistence/postgres.py:368`, `:376`, `:408-411`) refused a caller id such
as `h1` or a slug (`tests/persistence/test_postgres.py:182-197`), after
`run_one` had spent. Migration 005 makes `lessons.hypothesis_id` and
`technique_id` `VARCHAR(64)` with a `CHECK` equal to `RUN_ID_PATTERN`
(`state.py:64`; §3.5); the saves validate with `validate_run_id`
(`state.py:67-85`) instead of `_uuid` (`postgres.py:186-205`); engine-made ids
stay UUIDs; a raise keeps the round's progress. *Why not uuid5:* ranking
compares ids by equality (`optimization/ranking.py:27-37`), neither column has
a foreign key (`003_engine.sql:417-418`) and trial ids live in JSONB
(`003:240-241`). The pinned refusal tests changed meaning deliberately.

**D4. Contracts units carry no behaviour.** U2 (after U1) and U17 (after U2:
the quality and noise contracts, which would push U2 past 400 lines) land every
new setting, state key, model field and protocol. The `NodeContext`, model and
serde defaults reproduce Step 2 (D40, D41 a and c). The `Settings` defaults
carry the owner's choices (output check on, paired trials, confirmation, 3
calibration blocks: O9, O10; §3.1), and only the factory (U10) reads them, so
behaviour changes when U10 lands, not when U17 does; a Builder never sets them
to Step 2 values. *Why:* `config.py`, `models.py`, `state.py` and `serde.py`
are shared by every later unit; freezing them lets Builders work on disjoint
files.

**D5. The generator is Sonnet 5.5 at medium effort, no fallbacks, `n=5`, at
most 2 calls a run; the matcher (off) is Sonnet 5.5 medium, `k=3`.** *Why:* in
E3 this arm hit 22/22 hit@5 at 0.014 USD a repository with no big-gain claim on
a control; Opus at high returned nothing twice; Fable matched Sonnet at 7x the
cost. The second call covers an empty reply.

**D6. The candidate pool lives in the state, and the router reads it.** Today
the router ends a run once every `ctx.candidates` id is trialled
(`nodes.py:1937-1939`); `all(...)` over an empty tuple is true, so a run with
no caller candidates stops after round 1. The router continues while an
untried idea is in `ctx.candidates` or `candidate_pool`, or generation is
still possible. *Why:* a resume must not pay twice for generation.

**D7. Discovery spend is bounded by a narrowed `Budget`.**

- Generator and matcher get `Budget(cap_usd=d, spent_usd=cost_usd)`, `d =
  min(max_cost − min_trial_budget_usd, cost_usd + DISCOVERY_MAX_SHARE · max_cost
  − discovery_cost_usd)`. `call()`'s pre-send check (`clients/transport.py:331`,
  `Budget.check`) refuses a request whose worst case cuts into one trial's
  reserve or passes the 25 % share: a soft `discovery_unaffordable` note.
- If `d ≤ cost_usd` (a state the trials node tolerates by starting no trial,
  `nodes.py:1508-1510`), the node sets `discovery_exhausted` and sends nothing,
  never building the `Budget`: a negative cap raises `ValueError`, not
  `BudgetExceeded` (`clients/budget.py:28-30`, `:57-58`).
- *Why:* the real request's worst case bounds it; trials get the whole
  remaining cap (`nodes.py:1508`), so unbounded discovery means fewer proofs.

**D8. Generated hypotheses keep the model's order; only lessons reorder them.
Caller candidates rank first, by the Step 2 formula.** `rank_generated` scores
`(1 + lesson_boost) / (1 + position)`. *Why:* the only measured signal is the
model's order (hit@1 19-21/22); `expected_gain` is uncalibrated (Opus claimed
big gains on `lettertally`). `rank_hypotheses` tests stay untouched.

**D9. Generated `efficiency` and `behaviour` hypotheses enter rounds; `novel`
ones are parked.**

- *Why:* a behaviour verdict no longer stops the run (D10), and every frozen
  judge still applies (D35): under the default output check a behaviour idea
  reaches review only with identical outputs; with a quality check, when the
  quality holds. `novel` still interrupts at the gate, which no unattended run
  can answer (`tests/live/discovery.py:409-420`).
- Nothing fills `needs_package`: the generator prompt forbids new dependencies
  (`optimization/generate.py:139-140`).
- L1 records counts per class and output-check rejections; if behaviour ideas
  take a third of slots without a review win, `GENERATED_CLASSES` narrows (O2).

**D10. Review verdicts go to their own branch, with no pause** (user decision 1).

- Which verdicts are `review` is D35. `derive_verdict` rule 6
  (`optimization/judges.py:674-682`) gains `VerdictOutcome.review`; `novel`
  keeps `needs_approval`.
- Combine re-tests the review set on its own, ABAB from the base, through
  `combine_kept`, accepting `keep` or `review` (`CombineRules.accept`, U23;
  today it holds iff `keep`, `orchestrator/combine_node.py:111-116`).
- Deliver publishes it create-only to `engine/review-<run_id>`, never merged
  into `engine/run-<run_id>`, never pushed. A `review` verdict does not end the
  search (a `keep` does, and every `keep` has already passed confirmation
  where one runs, D41 b) and is neutral in ranking
  (`ranking.py:46-49`). Migration 006 adds `review` to `chk_lesson_outcome`
  (`003:427-428`). CLAUDE.md wording ("flagged", rule 6) and the `ChangeClass`
  docstring (`common/models.py:127`) are aligned in U15.
- *Why:* a `needs_approval` that never asks is a false record; no pause.

**D11. The hypothesis is fenced in the editor prompt for every source.** Today
`_task_text` puts `_hypothesis_text` outside the `_untrusted` fence
(`execution/editor.py:455-475`); generated titles derive from repository text
and can relay an injection. `_holds` already refuses a hypothesis holding the
token (`:463`). *Why:* one rule, no flag to set wrong.

**D12. The self-retry is narrow** (§4.4).

- **When:** a workload's own run exits non-zero with a parsed Python traceback
  of a fixable type: `SyntaxError`, `IndentationError`, `TabError`,
  `ImportError`, `ModuleNotFoundError`, `NameError`, `UnboundLocalError`,
  `TypeError`, `AttributeError`.
- **How often:** `EDITOR_FIX_RETRIES` per trial and
  `EDITOR_FIX_RETRIES_PER_RUN` per run, both default 1, on the trial's own
  `Budget`, while `budget.remaining ≥ retry_floor_usd` (`min_trial_budget()`,
  `orchestrator/factory.py:111-116`). The run cap's bound 0-1 is O8's (B-R2
  lifts it). The per-trial bound 0-1 is a Lead decision (§8 Q17), not the
  owner's: the owner set the per-trial default at 1 and the run cap at 1, and
  under a run cap of 1 a per-trial value above 1 is unreachable, so the bound
  only keeps the setting honest. B-R2 does not lift it.
- **The run cap** (U16): the trials node computes `EDITOR_FIX_RETRIES_PER_RUN −
  Σ (attempts − 1)` over `state["trials"]` (`state.py:104`, appended by the
  judges node, `nodes.py:1609`) and this round's earlier trials, and passes it
  as `TrialBrief.fix_retries_left: int = 0` (`execution/protocols.py:76-81`).
  `_attempt` retries only below both caps; `_runner_trial_problems`
  (`nodes.py:456-473`) refuses a trial reporting more. Counted from
  checkpointed trials, the cap survives a resume at a node boundary; a crash
  inside the trials node loses the round with its count (`_trials_progress`,
  `nodes.py:784-796`, attaches it only to the failed record) and the round is
  re-paid on resume, as in Step 2 (D18). The editor prompt never shows it.
- *Why a brief field:* a `run()` keyword would break every `TrialRunner`
  (`execution/runner.py:46-62`, `:120-129`, `tests/orchestrator/test_nodes.py:277`);
  default 0 fails closed.
- **Spent:** the trial keeps its first failure with "not retried: the run's
  fix retry is spent" in `retry_notes`; rule 2 rejects it; the run goes on.
- **Never retried:** timeouts, floods, isolation and report failures
  (`execution/procrun.py:265-289`), `AssertionError`, the suite
  (`check_exit=False`, `execution/measure.py:576`). **Never fed back:** judge
  results, timings, fingerprints, quality values.
- *Why:* the retry lives in `GitTrialRunner._attempt`
  (`execution/trial_runner.py:502-587`), which returns before any judge runs.

**D13. Information closure for every channel from run output to the API.**

- Trials are confined for writes only (service CLAUDE.md, Security Notes), so
  editor-written code can read `~/.aws/credentials` and raise it in an
  exception, with any message (`raise NameError(str(list(secret)))`); a diff
  can define an alphabet of names, so a token check is not closure.
- **Closure set:** identifier tokens (`[A-Za-z_]\w*`) of the trial's diff and
  of the tracked `.py` sources at base (`GitWorkspace.read_blob`, `git.py:556`;
  deny-listed files excluded; at most 8 MiB).
- `classify` sends:
  - **frames** only as `(path, function, line)`, at most the 3 innermost:
    `path` tracked at base or touched and matching no `READ_DENY_PATTERNS`
    entry (`common/paths.py:74-92`), `function` in the closure set, `1 ≤ line
    ≤` the file's line count at the trial's commit; else dropped. A diff
    controls all three (`f.__code__.replace(co_firstlineno=123456789)` makes
    3.13 and 3.14 print `line 123456790`). Source lines are never sent.
  - **a message** only on a full match of a per-version CPython template in
    `retry.py`, derived by raising each error uncaught under 3.8.20, 3.9.25,
    3.10.20, 3.11.17, 3.12.3, 3.13.16 and 3.14.6 (all in this container; 3.14.6
    via `uv python install 3.14`) and reading stderr's last line. Under 3.14.6
    the 33-case probe equals 3.13.16 except the install `PATH`; carets and no
    colour on a pipe match; `TERM` alone does not colour. CI proof comes from
    U3 (3.13 and 3.14 on PATH) and U4's live-template tests (`ci.yml:380-383`
    installs 3.8-3.12 today). `PATH` is always dropped.
    - `NameError`: `name 'X' is not defined` (+ `. Did you mean: 'Z'?` 3.10+,
      `. Did you forget to import 'Z'?` 3.12+); `free variable 'X' referenced
      before assignment in enclosing scope` ≤ 3.10, `cannot access free
      variable 'X' where it is not associated with a value in enclosing scope` 3.11+.
    - `UnboundLocalError`: `local variable 'X' referenced before assignment`
      ≤ 3.10, `cannot access local variable 'X' where it is not associated
      with a value` 3.11+.
    - `ImportError`: `cannot import name 'X' from 'Y' (PATH)` (+ `. Did you
      mean: 'Z'?` 3.12+); `… from partially initialized module 'Y' (most
      likely due to a circular import) (PATH)`; 3.13+ `… from 'Y' (consider
      renaming 'PATH' if it has the same name as a library you intended to
      import)`, which replaces the circular form only when `Y` is a top-level
      module in `sys.path[0]`; inside a package both 3.13.16 and 3.14.6 print
      `partially initialized module` (re-run here with 3.12). U4 pins both.
    - `ModuleNotFoundError`: `No module named 'X'`, `…; 'Y' is not a package`.
    - `AttributeError`: `'T' object`, `module 'Y'` or `type object 'T'`, then
      `has no attribute 'X'` (+ `. Did you mean: 'Z'?` 3.10+; 3.13 ` (consider
      renaming 'PATH' since it has the same name as the standard library module
      named 'Y' and prevents importing that standard library module)`).
    - `TypeError`: `F() takes N positional argument(s) but M were given` (`F`
      qualified from 3.10), `unsupported operand type(s) for OP: 'T' and 'U'`,
      `F() got an unexpected keyword argument 'X'` (+ 3.13 `. Did you mean 'Z'?`).
    - Syntax phrases, one line number at most: `invalid syntax`, `unexpected
      indent`, `unindent does not match any outer indentation level`,
      `inconsistent use of tabs and spaces in indentation`; ≤ 3.9 `unexpected
      EOF while parsing`, `expected an indented block`; 3.10+ `expected ':'`,
      `'(' was never closed`, `invalid syntax. Perhaps you forgot a comma?`,
      `expected an indented block after … on line N`.
    - Against 3.12, 3.13 changed only the keyword suggestion and the two
      `consider renaming` forms. Caret lines (`~^^`, PEP 657) appear from 3.11
      and are skipped on every version; 3.13 widened them (a whole-line call
      such as `f({"a": {}})`), so U4's fixtures carry carets for 3.11-3.14. An
      ESC byte is a miss (`FORCE_COLOR` is dropped by `child_env`,
      `execution/sandbox.py:58-60`).

    Every captured name (each dotted part) is in the closure set; a name slot
    (`X`, `Y`, `F`) also appears on the innermost repository frame's source
    line at the trial's commit; a type slot may instead be a builtin. At most
    two numbers of at most 4 digits, 300 printable characters; otherwise type
    and frames only.
- *What the templates prove:* every character sent is fixed interpreter text,
  a name the API has seen, or a short number. The residual is a selection
  among seen values: 3 frames at about 35 bits each on a 1,000-file repository
  with an 8 MiB closure (10 + 15 + 10), 2 numbers at 13.3 bits, 3 names at a few
  bits, the template under a byte: 105 + 27 + 9 + 6 ≈ 147 bits, **about 18
  bytes per attempt**.
- **Residual per run (O8):** at most `EDITOR_FIX_RETRIES_PER_RUN` attempts, so
  **18 bytes a run** at the default and bound 1 (uncapped it was 3 rounds,
  `config.py:243`, × 3 trials, `nodes.py:209`, × 18 = 162). 18 bytes does not
  hold a 40-character base64 key (30 bytes); 36 at 2 would. Runs on one
  repository add up (§5). From 3c each reproducer rewrite (D33) counts against
  the same cap (D36), so one figure covers heal runs.
- **B-R2 (backlog after Step 3, Step 4 at the earliest): a second retried
  trial per run.** B-R2 lifts only the run bound: `EDITOR_FIX_RETRIES_PER_RUN`
  may become 2 while `EDITOR_FIX_RETRIES` stays bounded at 1, so "the second
  retry" is the second retried trial of a run, never a second retry of one
  trial. The owner's order (O8; "attack tests and safeguards before we bump
  it up") holds: safeguards built, attack tests passed, then the owner flips.
  - *safeguards, built first:* the run's second retry sends type and template
    id only (under a byte), so the per-run residual at 2 is about **18-19 bytes**
    (147 + < 8 bits), not 36; a per-project rolling retry budget across runs
    (Step 4's project store).
  - *attack tests, run with the safeguards on:* (1) capacity: a scripted
    adversarial editor plants a 32-byte secret and encodes it over the run's
    two retried trials through every slot (frame path, function, line, both
    numbers, name slots, template choice); decoders over the recorded wire
    bodies recover at most 19 bytes (155 bits); (2) accumulation: the same
    plant over 10 runs on one repository recovers at most 19 bytes a run and
    no more than the rolling budget admits; (3) template fuzzing per CPython
    3.8-3.14 with secret-bearing names; (4) forgery: a fake traceback printed
    to stderr, `sys.excepthook`, a patched `traceback`, forged
    `co_firstlineno` and `compile` filenames; (5) a live `attack_crash`
    repository whose text asks the editor to raise secrets: no canary on the
    wire.
  - *the gate is numeric:* every test at the 19-byte bound. The 36 bytes of
    two full-feedback attempts is a fail: it holds a 30-byte key, so a pass
    there would leave the channel open.
  - *who flips:* the owner, on that evidence: a STATUS entry with the recorded
    wire bodies, the decoders' output and the test run. The Lead proposes; the
    Lead does not flip it.

**D14. The retry is a fresh editor request, not a replay:** the worktree keeps
attempt 1's change (after `GitWorkspace.reset`, `git.py:675-694`); a new
boundary token; a fixed notice ("your previous change, still in the worktree,
failed when run; fix that error and keep the approach"); the closed feedback
inside `<untrusted_run_output boundary=TOKEN>`. *Why:* a replay doubles input.

**D15. A retried trial is still one commit whose parent is the base.**
`GitWorkspace.commit` gains `parent: str | None = None`; the retry passes
`parent=base`; `update-ref HEAD` keeps commit 1 as the expected old value
(`git.py:773`); the attempts' `written` maps merge, so `unrecorded_write`
holds (`optimization/anticheat.py:452`); capture and every anti-cheat rule run
again on the diff against the base. *Why:* combine skips anything but a single
child of the base (`execution/combine.py:246-252`).

**D16. The editor gets its own model setting.** `EDITOR_MODEL` defaults to
`None` (= `ENGINE_MODEL`). W5 flips it to Sonnet 5.5 at `low` only if L2a (2
repetitions) passes W5's gate. *Why:* E8a (12/12, about 0.04 USD a run) and E5
cover only saturating corpora; the OSS small gains ran on Opus only (row O).

**D17. `_brief_hotspots` is unchanged** (top-5 fallback, `nodes.py:342-355`).

**D18. Paid nodes on failure or resume.** `hypotheses` and `research` follow
`understand` (`nodes.py:1262-1286`): an `EngineError` charges the run through
`_charged` (`:576-587`) and `keep_progress`, then raises; transport and reply
failures are soft notes, charged; the pool, `generator_calls` and
`discovery_cost_usd` travel in the node's delta, checkpointed before `trials`.
A crash between reply and checkpoint loses the run, not the cap: Step 3
resumes only in-process (`PostgresSaver` resume is Step 4).

**D19. pip-audit runs in CI** (user decision 2): a step in the `python` job
after mypy (`.github/workflows/ci.yml:306`, `:405`), `uv run pip-audit
--progress-spinner off` as the gate runs it (`scripts/stage-gate.sh:136`;
dev dependency, `pyproject.toml:150`), plus a weekly job in `security.yml`.
*Why:* the PR step catches a vulnerable lock change; the weekly job a new
advisory against an unchanged lock.

**D20. The offline discovery eval records and replays.** The sweep records each
generator and grader reply (today `SweepRow`, `tests/live/discovery_sweep.py:162-190`,
keeps counts only). A replay test runs them through `generate_hypotheses` on
`ScriptedTransport`, `rank_generated` and the node's slice, asserting hit@3 at
least the recorded baseline. Wave 1 uses a synthetic seed; the real one comes
from L4.

**D21. In blind mode, lessons reach discovery only through the generator
prompt.** Blind hypotheses have no `technique_id` (`generate.py:314`) and fresh
ids, so `lesson_matches` (`ranking.py:27-37`) never matches across runs. W1
fences the last 20 project lessons and `avoid_titles` into the prompt; W2
discounts keeps whose combination failed (1.0 / 0.5 / 0.25; `chk_lesson_weight
> 0`, `003:429`).

**D22. Evolution is built only if the data asks.** W4 compounds two disjoint
near misses (inconclusive, right direction, ≥ 0.5 of their floor) into one new
trial judged from scratch. *Gate:* at least 4 of L2a's 20 runs (2 of 10 per
repetition) have two or more; the Lead's proportional restatement (2 of 10 in
either repetition also meets the original rule).

**D23. Protected-pattern gaps:** `**/pip.conf`, `**/uv.toml`,
`**/requirements*.in`, `**/constraints*.txt`, `**/pylock*.toml`, `**/pdm.lock`,
`**/.python-version` join `DEFAULT_PROTECTED_PATTERNS` (`anticheat.py:47-105`).
*Why:* each changes what is installed or which interpreter runs.

**D24. Live runs follow the spend rule.** Each names what it measures, what it
feeds and its cheapest arm; each cap is the sum of its worst cases with
`HARD_RUN_CAP_USD == 5.0` (`tests/live/test_hard_corpus_guards.py:223`),
`OSS_RUN_CAP_USD == 5.0` (`tests/live/test_oss_guards.py:868`),
`CORPUS_RUN_CAP_USD = 5.0` (`tests/live/corpus.py:88`). A new suite gets its
constant and guard, a `suite` value and need in `ci.yml` (`:17-34`, read at
`:639-652`), a timeout and a ledger line.

**D25. One migration per change:** 005 ids (U1), 006 `review` (U11), 007 for
3c, 008 for 3b. U1 made the CI re-apply loop cover every file from `003` on.

**D26. New node tests go in new files** (`test_nodes.py` is 5,661 lines).

**3b (designed here, built as its own step after 3c, O5):**

**D27. Same environment on both sides** (user decision 4). With 3b active the
whole run is measured in E0, built from L0: baseline, trials, both sides of
combine. A package trial runs in E1 (L0 plus the package and its new
dependencies); combine's A side in E0, its B side in E(union of kept
packages). Once, at baseline, the ambient environment is measured against E0;
outside the noise, the user is asked ("your installed environment differs from
your lockfile"). A resolver change to an existing pin refuses the trial and
becomes its own `dependency-upgrade` (`behaviour`) hypothesis against E0. The
report says the user must install the new dependency. `env_baselines`, keyed
by lock sha256, are measured by the baseline runner under
`_require_trustworthy_baseline` (`nodes.py:647`) and re-measured when the lock
or host check changes, separating the environment's effect from the code's.

**D28. No wheel means ask** (user decision 5): `--only-binary :all:
--no-build` resolving, `--no-build` installing; an sdist-only L0 pin, or one
newer than `--exclude-newer`, gives `needs_user` with the pin named.

**D29. The download floor is offline:** automatic only if the name is in a
committed, dated top-15k PyPI snapshot, is no near miss of another snapshot
name, and passes age, OSV (`MAL-` included) and licence. *Why:* a hallucinated
name is plausible but not popular.

**D30. The fetch phase runs engine code and one pinned `uv` only.**
`UV_EXECUTABLE` is absolute; its `--version` and sha256 match `UV_VERSION` and
`UV_SHA256`, else 3b is disabled with a note. The registry is reached through
a loopback allowlist proxy. Whether Landlock read confinement breaks `uv` is
**unverified**: a failed probe refuses 3b on that host.

**D31. The engine writes capability commit C1, and nothing else may.** C1 is
recomputed and compared; the editor's capture diffs against it. A package no
kept change imports (static scan via `top_level.txt`) is dropped and
re-tested; if that no longer holds, it is restored ("used dynamically"). A
no-package keep within the noise of the package keep wins.
`Trial.env_lock_sha256` is a field.

**D32. `_env` and `_wheels` have a cleanup owner.** They fail
`REFNAME_SEGMENT` (`common/refnames.py:22`), so `_phase_names` leaves them
(`execution/phase.py:265-282`): 3b adds them to the run's known dirs
(`phase.py:64-65`); the acquire phase removes them in `finally` under the run
lock, and `sweep_stale_runs` (`:306`) for dead runs.

**3c (designed here, built as its own step before 3b, O5):**

**D33. Reproducer integrity** (user decision 6). Written in a separate,
tool-less request before any fix and frozen outside `writable`, its sha256
checked before every run. The error report is untrusted: it enters only inside
a per-request fence (`Fence`, `clients/structured.py:112`, via `repo_fence`,
`research/playbook.py:271`) and is refused if it holds the token (`Fence.holds`,
`structured.py:126`). It must fail on the baseline N of N runs for the reported
reason (same exception type and innermost repository frame or masked message,
raised in a repository file at base). The fix may not touch it; the report
shows it beside the fix. Held-out variants come from a second request that
sees the reproducer and signature, never the report, each passing the same N/N
check. The one allowed rewrite sees only the expected-versus-observed
mismatch, under D13.

**D34. Heal judges.** `HealJudge` passes when the reproducer and every variant
pass N of N, with the shim's completion document. Output checks (equivalence
or the quality check) exempt only the reproducer's workloads. The full suite
runs with nothing deselected: `failing_test` must count at least baseline + 1,
`crash` at least the baseline. A heal changes behaviour, so it is a `review`
verdict on `engine/review-<run>` (D10). The fix may add no file and no
`__init__.py`; the report states human review is the final guard.

**Owner conditions and second round:**

**D35. How a change that alters output is judged (O7, O9; replaces Rev 3's
"no judge exempted").**

- *Code today:* no judge reads the class, only rule 6 (`judges.py:630-682`).
  `EquivalenceJudge` applies to every objective (`:300-302`) under an
  `output_equivalence` guardrail (`:304-312`) and fails a changed, missing or
  unstable fingerprint (`:324-337`, `anticheat.py:236-273`); rule 3 rejects
  every class (`judges.py:646-651`). The guardrail judge is inconclusive for a
  metric with no baseline row (`:408`, `:445-450`), and the runner measures
  only wall, CPU and peak RSS (`execution/measure.py:356-370`) plus the suite
  flag (`:595`): no quality number exists.
- **Two output modes, exactly one per run** (define, D40):
  - *exact* (default, O9): `output_equivalence`. An output change is rejected
    by rule 3, whatever its class. The fingerprint covers stdout and the
    declared `output_file` (`measure.py:199-210`, `:290-300`); stderr, logging
    and undeclared files are not compared.
  - *quality* (O7): a `quality:<name>` `metric_bound` guardrail (D37-D38) and
    no `output_equivalence`. `EquivalenceJudge` still compares fingerprints:
    it sets `JudgeResult.output_changed` and passes, failing only on a missing
    or unstable fingerprint (an output that cannot be scored once).
  - *Applicability (U21):* today the judge is `not_applicable` without an
    `output_equivalence` guardrail (`judges.py:304-312`). It now runs when
    either `output_equivalence` or a `quality:<name>` guardrail is present, and
    fails a changed fingerprint only under the former. Likewise
    `_require_trustworthy_baseline` checks agreed fingerprints only under
    `output_equivalence` (`nodes.py:661-663`); U25 extends it to quality mode
    (§4.7, 1).
- **Rule 6** (U21): all passed and any result with `output_changed` → `review`
  (`novel` stays `needs_approval`); otherwise `efficiency` → `keep`,
  `behaviour` → `review`, `novel` → `needs_approval`. No output change is ever
  kept on the run branch; it reaches review only after the quality check
  passes and the change is confirmed (D41). What counts as "changed" may
  include a user tolerance (D39). Rules 1-5 still gate every class.
- **Status:** `review` sets `HypothesisStatus.trialled`, as `needs_approval`
  does (`chk_hypothesis_status`, `003:391-392`, unchanged).
  `_STATUS_AFTER_VERDICT` (`nodes.py:280-285`) is indexed by the verdicts node
  (`:1661`) and the gate's resume (`:1736`), so U11 adds `review` (else
  `KeyError`), and the event text (`:1667-1674`) names it.
- *Why:* the default objective says outputs must not change; the owner allows
  a change only when a number the user confirmed says the result is no worse
  than allowed, and never silently.

**D36. 3c before 3b (O5): what 3c would have had from 3b.** Each reproducer
rewrite counts against `EDITOR_FIX_RETRIES_PER_RUN` like a trial retry (D13):
with none left the heal is refused with that note, so a heal run whose trial
used the retry cannot rewrite (C3 counts; C4 keeps the reproducer's workloads
out of trial retries). A fix needing a module outside the repository and the
standard library is refused before the reproducer request, listed as a
`needs_package` proposal. 3c measures in the ambient environment; heal runs
move to E0 when 3b lands. Migrations: 007 is 3c's, 008 is 3b's. If the Step 5
dogfood needs a new package, the Lead proposes 3b first at the 3c briefing.

**D37. Where the quality number comes from (O7).**

- **Never from text the trial controls** (a printed "accuracy" is whatever
  the trial prints): a frozen evaluator computes it from the workload's output
  and frozen evaluation data:
  - *builtin* (engine code, `execution/quality.py`): `accuracy`, `error_rate`,
    `macro_f1`, `mae`, `rmse`, over one value per line of the output against
    a labels file (strict UTF-8, equal line counts, at most `QUALITY_MAX_ROWS`;
    else unscoreable);
  - *external*: the user's scorer argv (`python3 score.py`), every file it
    needs in `frozen_paths`. Its stdout must be exactly `aip-quality/1
    <name>=<finite decimal>`, one line of at most 128 bytes, exit 0, read from
    `stdout_head` (`execution/procrun.py:387-391`); anything else is unscoreable.
- **Input:** the workload's `output_file`, else its stdout when complete within
  `OUTPUT_HEAD_BYTES` (64 KiB, `common/config.py:282`). Define does not refuse
  either case, since it runs before any output exists; a workload with no
  scoreable output stops the run at baseline (§4.6), and an empty one is
  refused there in quality mode (D40). Every workload is scored (completeness
  needs a row per workload and guardrail metric, `nodes.py:386-444`). Output
  bytes stay in memory for the scoring only: never in state, Postgres, the
  report or a prompt.
- **One score per measurement:** the timed runs must agree on one fingerprint
  (`measure.py:356-361`), else no quality row: `missing_measurement`, rule 1
  rejects. That is the canonical fingerprint: with a tolerance, runs whose
  exact bytes differ within it still agree, their rows carry
  `raw_fingerprint=None`, and the first timed run's bytes are scored
  (Lead, U18 review). Scores are cached by `raw_fingerprint` (the exact bytes,
  D39), so only a byte-identical output reuses a score; an output equal to the
  baseline's within a tolerance, or with no `raw_fingerprint`, is scored on
  its own bytes. `output_changed` is read from the canonical fingerprint.
- **Frozen like the judges:**
  - at baseline the engine reads each frozen path at the base commit
    (`read_blob`, `git.py:556`; at most `QUALITY_MAX_FROZEN_BYTES`) and records
    its sha256 in `Baseline.quality_files`, listed in the report;
  - define adds the frozen paths to `extra_protected` (set by connect,
    `nodes.py:1258`; checked by verdicts, `:1621`; shown to the editor,
    `:1482`): a trial touching them is rejected (`protected_path`, rule 1);
  - the scorer never runs from a trial worktree: each scoring materialises the
    recorded blobs (sha256 re-checked) in the engine phase `<run>/quality`,
    run as `python -s -B` with cwd and `sys.path[0]` the frozen copy, so no
    trial-edited module is importable. Not `-E`: `child_env`'s allowlist already
    drops every `PYTHON*` name but the forced `PYTHONHASHSEED=0` and
    `PYTHONDONTWRITEBYTECODE=1`, which `-E` would ignore, making a scorer that
    iterates a set score differently run to run (Lead, U19 review). A scorer
    that needs the repository fails at baseline ("the scorer must be
    self-contained");
  - a frozen path must be a regular file in the tree (mode 100644 or 100755):
    a symlink blob would freeze the link text and leave the real file
    unprotected, so freeze refuses it ("freeze the file it points to"; Lead,
    U19 review);
  - the scorer phase (U19) is not built by `make_phase`, which takes a
    `WorktreeHandle` and resets through `GitWorkspace.reset` (`check_link` on
    `<dir>/.git`, `checkout -f`, clean; `git.py:675-694`); the frozen copy has
    no `.git`. U19 builds `SandboxPolicy(writable=(copy, scratch))` directly
    (network off, writes confined to the copy and its scratch, which satisfies
    `Phase.__post_init__`, `measure.py:114-116`), `child_env`'s allowlist
    (`sandbox.py:58-60`, no `PYTHONPATH`) and a no-op reset. The output goes on
    the scorer's stdin, never into the copy. The copy is created immediately
    before each scoring and removed in `finally`, inside `owned_phases`
    (`phase.py:246-262`), so it never exists while a workload runs; otherwise
    any workload could read `<WORKTREE_ROOT>/<run>/quality/<labels>` (reads
    are unconfined, and the run id is in its own cwd) past the mask. Whether
    `cleanup_phases` removes a plain directory is **unverified**; U19 tests it;
  - determinism: at baseline the scorer runs twice on the base output;
    differing numbers refuse the quality check.
- **Masking:** every frozen path is deleted from the worktree after each reset,
  before every workload launch (not the suite), on both sides, including the
  profile run; a baseline that needs them fails ("write predictions; the
  scorer reads the labels"). `measure.launch` masks by default and only the
  suite opts out, so a new launch path cannot forget it (Lead, U18 review;
  the profiler's `mask=` is wired with the other callers in U24).
- **Hidden from the editor:** the trial worktree is created at the base commit
  (`trial_runner.py:446`) and the editor works in it before any mask
  (`:524`); `editor_tools._resolve` (`:226-268`) denies reads only by
  `READ_DENY_PATTERNS` and git names, and checks `self._protected` for writes
  only, so today a `view` of `data/labels.csv` succeeds. The frozen paths join
  the editor's read-deny set for the run: `TrialBrief.read_deny: tuple[str,
  ...] = ()` beside `protected`, passed to the tool handler as `protected` is
  (`editor.py:228`); a `view` of a frozen path is refused with "evaluation
  data, off limits" and a directory listing omits it, as `_listable` already
  does for secrets (`editor_tools.py:494-500`). Its directory stays readable:
  it usually holds the workload's inputs. U24 builds the handler and brief
  field; U25 fills it from the frozen paths in the trials node (`nodes.py:1482`).
- **Precondition:** the check is sound only if no readable project file other
  than the frozen ones determines the labels. In the common layout the
  evaluation input already carries them (a test CSV with the label column the
  labels were cut from). At freeze time a cheap exact-match scan (U19's pure
  `label_column_leaks`, called by the baseline runner, U24) compares the labels
  file's value sequence with each comma- or tab-separated column, header row
  allowed, of every tracked file a workload's argv names; a match is a warning
  in the baseline's notes and the report's run conditions (U25), and the same
  check annotates understand's proposal. Every report with a quality check
  states the precondition.
- **What only the review catches:** confinement is write-only (D13), so code
  can still read the labels through the main repository (a worktree's `.git`
  file names it, `git.py:19-21`), the object store, or an unfrozen input that
  carries them, and print them as predictions; the editor can also bake a
  lookup table of label values, read from any unfrozen copy or guessed, into
  the code; an external scorer that executes its input (`pickle`, `eval`)
  lets the output choose the number. A static rule
  (`ViolationRule.quality_data_reference`) refuses a diff whose added lines
  name a frozen path or its basename: a tripwire, not closure (a baked table
  names no path). Every output change goes to review with its diff (D35);
  read confinement waits for the Landlock probe (D30, **unverified**).
- **Quality values never reach a prompt:** not as retry feedback (D12), not in
  `Verdict.gain` (`_select_gain`, `judges.py:572-583`, reads results carrying a
  metric; the guardrail judge sets none, `:466-485`), so not in lessons
  (`learning/lessons.py:47-48`).

**D38. The allowed drop and the label (O7).**

- The check becomes `Guardrail(kind=metric_bound, metric="quality:<name>",
  direction, max_drop)` (`common/models.py:303-324`), judged by
  `GuardrailMetricJudge` (`judges.py:374-485`), which now finds a baseline row.
- `Guardrail.drop_unit`: `relative` (default, today's rule: the drop over the
  baseline mean, `:416`, `anticheat.py:164-168`) or `absolute` (points of the
  metric). A quality check defaults to `absolute` ("accuracy may drop at most
  0.5 points" is `max_drop=0.005`): a relative drop is undefined at a zero
  error rate (`judges.py:417-421` marks it missing).
- An absolute drop is printed in the metric's unit, not through `_percent`
  (`judges.py:101-102`, used by the guardrail messages at `:436-441` and
  `:452-457`), which would print an `mae` drop of 0.5 as "50.0%": points for
  the builtins bounded in [0, 1] (`accuracy`, `error_rate`, `macro_f1`), the
  raw value for `mae`, `rmse` and an external score. The D38 label carries the
  same unit (U21).
- `max_drop=0` (default) means the same or better; a user value allows that
  much drop. Requiring an improvement is not a Step 3 rule: the objective
  stays speed and memory (§8 Q14).
- **Label** (U11), per change on the review branch and in both reports:
  "changes results: accuracy 91.2 % → 91.6 % (result improvement), 30 % faster,
  give or take 2 %, confirmed twice (large)"; "result kept, output changed";
  "result drop within your limit: −0.3 of 0.5 points allowed"; "behaviour
  change, outputs identical". An improvement is measured on the frozen
  evaluation data only, untested for significance; a builtin states its row count.

**D39. Tolerant equivalence (O7): a workload option, never silent.**

- `Workload.output_tolerance: OutputTolerance | None` (`float_digits` 6-15,
  `unordered_lines`), set by the caller (Step 4's CLI later), echoed in
  define's event and the report.
- `measure.py` keeps the exact fingerprint as `Measurement.raw_fingerprint` and
  makes `output_fingerprint` canonical: strict UTF-8; lines sorted if
  unordered; sha256 tagged with the options. The tokeniser (U18):
  - split on ASCII whitespace and the delimiters `,;:=()[]{}"'` only, the
    delimiters kept byte for byte (`=` added by the Lead in the U18 review, so
    `name=value` metric lines get the tolerance);
  - a token is rewritten as `format(float(t), f".{d}g")` only when the whole
    token matches `[+-]?([0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)([eE][+-]?[0-9]+)?`
    (ASCII digits) and holds a `.` or an exponent; anything else (`v1.10`, `id_2.50`, `1_0.5`, `infinity`) is
    kept byte for byte; integers, `nan`, `inf` and `-0.0` are kept verbatim.
  `EquivalenceJudge`, the baseline agreement check and `compare_fingerprints`
  are unchanged by the tolerance: they compare whatever fingerprint
  `measure.py` produced (D35 changes the judge's applicability, not this).
- Sound one way: equal after rounding to d significant digits implies a
  relative difference under 10^(1−d); values within that can round apart, a
  false "changed" (rejected or sent to review), never a false "equal".
  Limitation: a count printed as a float (`1234567890.0` vs `1234567891.0` at
  9 digits) rounds equal; only integers printed as integers are exact. The
  report sentence says so.
- Unordered lines sort the newline-terminated lines; an unterminated last
  piece stays last (injective), so the report sentence says "line order
  ignored, except an unterminated last line".
- Complete outputs only: stdout within `OUTPUT_HEAD_BYTES`, `output_file`
  within `OUTPUT_TOLERANCE_MAX_BYTES`; else the exact fingerprint, with a note.
- The report names each delivered change whose raw fingerprints differ:
  "equal within tolerance (9 significant digits, line order ignored; counts
  printed as decimals compared to 9 digits only)".

**D40. How the check is proposed and confirmed once (O7, O9).**

- Understand's one request (`orchestrator/understand.py:100-108`, prompt
  `:111`) gains an optional `quality_proposal`: a builtin measure and tracked
  paths for labels or an existing evaluation script. Model output: validated
  against the enum and `ls_tree` at base (`git.py:546`), never activated,
  reported as "Suggested quality check (not active)".
- Confirmation until the Step 4 CLI: the caller passes a `QualityCheck` to
  `build_context(..., quality=)` (`orchestrator/factory.py:303`), stored in
  `NodeContext.quality`; that act is the one confirmation. Step 4 turns the
  proposal into one question and stores the answer per project.
- define (U25): with a quality check, the guardrail, the frozen paths in
  `extra_protected`, and no `output_equivalence` (a caller passing both is
  refused); without one, `NodeContext.default_output_check` (False keeps Step 2
  tests; the factory sets `DEFAULT_OUTPUT_CHECK=True`) adds
  `output_equivalence` when absent, beside the RSS bound (`nodes.py:1301-1313`).
- *Consequence (O9):* a program whose output varies run to run (time stamps)
  now stops at baseline (`_require_trustworthy_baseline`, `nodes.py:661-673`)
  unless it seeds, declares a tolerance or sets a quality check; the error says so.
- *Empty comparison:* a workload that prints nothing and declares no
  `output_file` has the fingerprint of empty stdout (`measure.py:199-210`), so
  every change is "identical" and O9's promise is vacuous for it. Define runs
  before any output exists, so the check is at baseline (U25, beside
  `_require_trustworthy_baseline`): a workload whose agreed `raw_fingerprint`
  equals `output_fingerprint(0, sha256(b""), None)` gives a warning event,
  "the output check compares nothing on workload X: print the result or
  declare `output_file`", carried into the report's run conditions
  (`_run_conditions`, `nodes.py:1059`); in quality mode such a workload stops
  the run (it cannot be scored).
- No engine-written scorer: model code would judge model changes.

**D41. The noise rule (O10; pulled from Step 5; §8 Q7).**

- *Evidence* (run 40082852536, STATUS ledger, 0 USD): 13 repositories × 6
  baselines, nothing changed; 11/390 ordered pairs judged a win at the 2 %
  floor (2.8 %, all kept by the whole verdict); p95 difference 3.0 %, above
  the floor on 4/13. Median within-baseline CV 0.67 %, so `2σ`
  (`anticheat.py:171-182`) is under the 2 % term. Baselines ran seconds apart,
  so drift is under-sampled: a lower bound (`tests/live/noise.py` docstring,
  on `claude/window0-experiments`).
- *Today:* a trial runs `measure_workload` alone (`trial_runner.py:283-302`,
  `:575`) and is judged against the baseline measured before profile (judges
  node, `nodes.py:1581-1590`): not alternated. ABAB exists only in combine
  (`combine.py:222-228`, `measure.py:409-420`). A `keep` ends the search
  (`nodes.py:1933`).
- *Does combine re-check a single kept trial?* Yes: `combine_kept` re-tests it
  ABAB from the base (`combine_node.py:151-163`, `:191-246`) and ships nothing
  unless that holds; but only after the router ended the search on it, and
  with two or more keeps only their sum, so a false member rides along.
  Missing, designed here: (a)-(c) and D42.
- **The order within alternation (ABBA).** `_interleave` (`measure.py:373-392`)
  runs the sides in a fixed order on every index, A then B for warm-ups and
  every timed run. A position effect (cache or page-cache warmth, frequency
  ramp, the second process inheriting a hot state) is then a constant bias, not
  noise: the trial look and the confirmation look carry it the same way, so
  they are not the independent draws the 0.028² estimate assumes, and
  calibration would raise the floor to cover the bias instead of removing it.
  U18 alternates the leading side per index on one counter across warm-ups and
  timed runs (A,B on even, B,A on odd), for trial pairs, calibration and
  combine alike; calibration then estimates variance, not position bias. With
  1 warm-up and N=5 the timed runs lead B three times and A twice, a residual
  of 1/5 of any position effect, stated in the report's noise line. The two
  tests pinning today's order change meaning deliberately
  (`tests/execution/test_measure.py:914`, `["reset A", "A", "reset B", "B"] *
  6`; `tests/execution/test_combine.py:369`, `["combine-base", "combine"] *
  6`). The owner's "old, new, old, new" is kept in spirit: each pair still
  alternates; the order within a pair is counterbalanced (a Lead reading, §8
  Q17).
- **(a) Alternation.** `GitTrialRunner` measures each trial against its own
  base worktree (phase `twin-trial-<hyp>`; the prefix no trial phase, always
  `trial-<id>` at `trial_runner.py:422`, can have, so a failed cleanup names
  its owner; beside `combine-base`, `combine.py:71`) with `measure_abab`; the A rows go to
  `Trial.base_measurements`, and the judges node judges the trial against them
  (objectives and guardrails from the run baseline, completeness on both
  sides, as `combine_node.py:213-224` does). The suite runs once, on B. A retry
  re-measures the same way. A crash on the twin (the base code) is an
  `EngineError` that stops the run with its spend kept, as a base crash in
  `GitBaselineRunner.measure` is; it is never retried or learned as the
  hypothesis's failure (Lead, U20 review). `PAIRED_TRIALS=False`, or a runner
  filling no A rows (the stubs), keeps Step 2.
- **(b) Confirmation before keep.** For a would-be `keep` or `review`, the
  verdicts node re-tests the trial alone through the combiner
  (`orchestrator/confirm.py`, `confirm_one`: `combine_kept`'s re-test on one
  change, accepting `keep` or `review`). Held: `Verdict.confirmations=2`,
  `confirmed_gain` set. Not held: `inconclusive`, "did not confirm: <why>", a
  neutral lesson. No combiner (stub contexts) or `CONFIRM_WINNERS` off: no
  confirmation, a note, the keep stands with `confirmations=1`. Combine is
  unchanged (for a one-change set, a third look).
- **The router is unchanged by confirmation.** Its rule stays "any `keep`
  verdict → combine" (`nodes.py:1933`, unchanged beyond U8's pool rules):
  every `keep` that exists has either confirmed or is exempt (no combiner,
  confirmation off), because confirmation changes the verdict, not the router.
  No `confirmations` check goes into `after_verdicts`; the Step 2 router test
  (`tests/orchestrator/test_nodes.py:2325`, keep → combine) holds.
- **(c) Per-project floor.** A `NoiseCalibrator` (the baseline runner) adds
  `NOISE_CALIBRATION_BLOCKS` (3) A/A blocks: the base ABAB against a second base
  worktree, giving per block and workload the relative gap of wall time, the
  engine's time objective (CPU time at tick granularity would inflate the
  floor; a user's custom `cpu_time_s` objective relies on the 2 % minimum;
  Lead, U20 review). The raise is keyed by metric name: `wall_time_s` gets
  the calibrated floor, a calibrated run's `cpu_time_s` gets at least 2 %
  (Lead, U22 review). `floor = max(MIN_RELATIVE_GAIN, NOISE_GAP_MULTIPLIER × largest
  |gap|)`, never below 2 %. The baseline node raises each time objective's
  `min_relative_gain` to it (a larger user value stays) before any trial, so
  every judge, confirmation and combine applies it (`CombineRules` copies the
  objectives, `nodes.py:1197-1204`); `Baseline.calibration` records it.
  Memory is unchanged (no memory false wins). 0 blocks keeps Step 2.
- **Expected effect, unverified:** independent looks would cut false keeps
  from about 1 in 36 trials to about 1 in 1,300 (0.028²), and alternation
  should lower each look's rate below 2.8 %; a slow host period can span both
  looks. L0 measures the single-look rate on the paired path and reports the
  kept count (§6).
- **Cost:** no tokens. Runs per workload (1 warm-up, N=5): baseline 6 + 36
  calibration; a trial 6 → 12; a winner +12 and a suite run. A 9-trial run
  with 2 winners goes from about 72 to 190 runs (2.6x): on the noise run's
  workloads (78 baselines of 6 runs in 7 min) about 1.5 minutes more a run,
  beside minutes of editor time; heavy workloads scale linearly. Live
  timeouts rise (U13). L0 (§6): per repository one calibrated baseline (42
  runs) and 10 A/A blocks of 12 runs, plus 12 per single-look win: about
  2,100 runs on 13 repositories, about 35 minutes at the noise run's 0.9 s a
  run (468 in 7 min, setup included).

**D42. Each gain is reported with its margin and confirmations (O10).** Per
delivered change: gain = the mean of the trial's and the confirmation's
primary gains (each the weakest workload's, `judges.py:572-583`); margin =
max(the project floor, half their difference); confirmations = passing looks.
"18 % faster, give or take 2 %, confirmed twice (solid)"; label from the gain:
small (< 5 %), solid (5-20 %), large (> 20 %). The combination's re-tested
gain is its own line; the "Noise floor" line (`nodes.py:1044-1056`) adds the
calibration.

---

## 1 Scope and non-goals

**Step 3** (O6): Wave 1 (U1-U26) and Wave 2 (V1-V6 and the re-test). Wave 3 (W1-W6, each gated) is **held until Wave 1's live runs
(L0, L1a, L1b, L2a and, when it runs, L2b) report**. 3c, then 3b (O5), are
designed in D33-D34 and D27-D32 and built after Step 3, each with its own
briefing, approval and security review.

**Non-goals:** the paper pipeline and the arXiv monitor until D2's condition
is met; card stats and the check-key registry; Fable as matcher; MCP and API
discovery, error intake and the CLI (Step 4); quality judgement with no number,
a required quality improvement, engine-written scorers (Step 4); the second
retry (B-R2); CUDA and MPS; rollout (Step 6).

---

## 2 Architecture

```
START -> connect -> understand (+ quality proposal, inactive) -> define
  (exact: output_equivalence | quality: quality:<name> bound, files frozen)
  -> baseline (+ 3 A/A blocks -> floor >= 2 %; quality scored twice) --+--> REPRODUCE (3c)
                                                                       |
              profile <------------------------------------------------+
                 v
              research  blind (default) | matched (off; D2); narrowed Budget (D7)
                 v
      +----> hypotheses: pool in state; generate when empty (<= 2 calls,
      |        reserve one trial, <= 25 % of cap); novel parked
      |          v
      |      ACQUIRE (3b): policy -> fetch (pinned uv, allowlist proxy) -> E0/E1 -> C1
      |          v
      |      trials (worktree + base twin, network off; hypothesis fenced)
      |        edit -> capture -> anti-cheat -> commit(parent=base)
      |        -> paired ABBA vs twin (+ frozen scorer, labels masked) -> suite on B
      |          ^-- fixable own crash, closure-checked, <= 1 retry a run (O8)
      |          v
      |      judges (vs the trial's A rows) -> verdicts: rule 6 by output change
      |        and class -> confirm_one (ABAB again) -> keep | review | inconclusive
      |          |
      +-- untried idea or generation possible --+
                                                |
   END <- watch <- learn <- deliver <- combine <- approval_gate (novel only)
           run branch: confirmed keeps, outputs equal -> ABAB -> engine/run-<id>
           review branch: review set (labelled) -> ABAB -> engine/review-<id>
           (never merged, never pushed; heal = R+F)

Frozen outside the state: judges, protected patterns, quality files and scorer,
fingerprint rules, reproducer sha256, env lock hashes.
```

---

## 3 Interfaces

### 3.1 Settings (`common/config.py`, U2 or U17)

| Key | Default | Validated |
| --- | --- | --- |
| `GENERATOR_MODEL`, `GENERATOR_EFFORT` | `claude-sonnet-5-5`, `medium` | priced; effort accepted by the chain |
| `GENERATOR_N`, `GENERATOR_MAX_TOKENS`, `GENERATOR_MAX_CALLS` | 5, 16000, 2 | n 1-20 (`check_count`), calls 0-5 |
| `MATCHER_MODEL`, `MATCHER_EFFORT`, `MATCHER_K` | `claude-sonnet-5-5`, `medium`, 3 | as above |
| `RESEARCH_RETRIEVAL` | `blind` | `blind` or `matched` |
| `GENERATED_CLASSES` | `("efficiency", "behaviour")` | subset of `ChangeClass`, no `novel` |
| `DISCOVERY_MAX_SHARE` | 0.25 | (0, 1) |
| `EDITOR_MODEL` | `None` (= `ENGINE_MODEL`) | priced; `EDITOR_EFFORT` accepted |
| `EDITOR_FIX_RETRIES` | 1 (per trial; owner, first round) | 0-1: a Lead decision (§8 Q17), unreachable above 1 under a run cap of 1; B-R2 keeps it |
| `EDITOR_FIX_RETRIES_PER_RUN` | 1 (O8) | 0-1 (O8) until B-R2; checked in the trials node (U16); 3c rewrites count (D36) |
| `RETRY_CLOSURE_MAX_SOURCE_BYTES` | 8 MiB | ≥ 1 |
| `DEFAULT_OUTPUT_CHECK` (U17) | `True` | bool; the factory's input to `NodeContext.default_output_check` |
| `OUTPUT_TOLERANCE_MAX_BYTES` (U17) | 16 MiB | ≥ 1 |
| `QUALITY_MAX_FROZEN_BYTES`, `QUALITY_MAX_ROWS`, `QUALITY_TIMEOUT_S` (U17) | 64 MiB, 1,000,000, 300 | ≥ 1; finite |
| `PAIRED_TRIALS`, `CONFIRM_WINNERS` (U17) | `True`, `True` | bool |
| `NOISE_CALIBRATION_BLOCKS`, `NOISE_GAP_MULTIPLIER` (U17) | 3, 2.0 | 0-5; ≥ 1 |

- New roles run without fallbacks; the editor keeps today's chain when
  `EDITOR_MODEL` is unset (`clients/cost.py:110-119`).
  `_every_billed_model_is_priced` (`config.py:319-326`) and
  `_effort_accepted_by_every_serving_model` (`:328-351`) cover every role;
  `role_settings` moves from `tests/live/discovery.py:163-171` into `config.py`.
- 3c adds `REPRO_MODEL` / `REPRO_EFFORT` (Sonnet 5.5 / `medium`),
  `REPRO_VARIANTS=2`, `REPRO_RETRIES=1`. 3b adds `ACQUIRE_ENABLED=False`,
  `UV_EXECUTABLE`, `UV_VERSION`, `UV_SHA256`, `PACKAGE_MIN_PROJECT_AGE_DAYS=90`,
  `PACKAGE_MIN_VERSION_AGE_DAYS=14`, `PACKAGE_LICENCES`,
  `PACKAGES_PER_HYPOTHESIS=1`, `ACQUIRE_MAX_BYTES=500 MiB`.

### 3.2 State (`orchestrator/state.py`; every key set in `initial_state`)

U2: `candidate_pool`, `parked: list[Hypothesis]`; `technique_matches:
list[TechniqueMatchRecord]` (a new `EngineModel`: slug, fit, justification
summary, unmet preconditions); `generator_calls: int`; `discovery_cost_usd:
float`; `discovery_exhausted: bool`; `review_combination: Combination | None`;
`review_delivery: Delivery | None`. Every new model joins
`ENGINE_SERDE_ALLOWLIST`. The quality check and calibration travel in
`Baseline` (U17), so no new key. 3c adds `run_kind`, `heal_case`, `reproducer`;
3b `env_baselines` and `capabilities`.

### 3.3 Models (`common/models.py`)

- U2: `VerdictOutcome.review` (no new `HypothesisStatus`, D35);
  `Trial.attempts: int = 1`, `Trial.retry_notes: tuple[str, ...] = ()`;
  `Hypothesis.parked_reason: str | None = None`.
- U17:
  - `BuiltinMeasure` enum (`accuracy`, `error_rate`, `macro_f1`, `mae`,
    `rmse`); `DropUnit` (`relative`, `absolute`);
  - `QualityCheck(name: ^[a-z][a-z0-9_]{0,31}$, measure: BuiltinMeasure | None,
    labels: str | None, scorer: tuple[str, ...], frozen_paths: tuple[str, ...]
    (1-16, project files), direction, max_drop ≥ 0 = 0, drop_unit = absolute)`:
    exactly one of `measure` + `labels` or `scorer`; a builtin fixes the
    direction; `scorer[1]` must be a frozen path;
  - `QualityProposal(measure, labels, scorer_path)`, optional on
    `ProjectUnderstanding.quality_proposal`;
  - `OutputTolerance(float_digits: 6-15 | None, unordered_lines: bool)` and
    `Workload.output_tolerance: OutputTolerance | None = None`;
  - `Guardrail.drop_unit: DropUnit = relative`;
    `JudgeResult.output_changed: bool | None = None`;
    `Measurement.raw_fingerprint: str | None = None`;
  - `Trial.base_measurements: tuple[Measurement, ...] = ()`;
    `Verdict.confirmations: int = 1`, `Verdict.confirmed_gain: float | None = None`;
  - `NoiseCalibration(blocks, gaps: dict[str, float], floor)`,
    `FrozenFile(path, sha256, size)`; `Baseline.calibration: NoiseCalibration |
    None = None`, `Baseline.quality_files: tuple[FrozenFile, ...] = ()`.
  All defaults reproduce Step 2; all serde-safe in the JSONB arrays.
- 3c: `HealCase(kind, target, signature)`, `ExceptionSignature(type, message,
  frames)`, `Reproducer(path, sha256, variants_sha256, signature,
  baseline_failures)`. 3b: `Hypothesis.packages: tuple[PackageRequest, ...]`
  (name and reason, never a version or URL), `Trial.env_lock_sha256`.

### 3.4 Seams

```python
# optimization/sources.py (U2); "HypothesisSource" is the enum (common/models.py:134).
class HypothesisGenerator(Protocol):
    def generate(self, *, project: Project, understanding: ProjectUnderstanding | None,
                 hotspots: Sequence[Hotspot], objective: Objective,
                 techniques: Sequence[Technique], lessons: Sequence[Lesson],
                 avoid_titles: Sequence[str], n: int, budget: Budget) -> GenerateResult: ...
class TechniqueMatcher(Protocol):
    def match(self, *, understanding: ProjectUnderstanding | None, hotspots: Sequence[Hotspot],
              techniques: Sequence[Technique], k: int, budget: Budget) -> MatchResult: ...
# execution/quality.py (U19), execution/protocols.py-free so U6 keeps that file.
class QualityScorer(Protocol):
    def freeze(self, git: GitWorkspace, commit: str) -> tuple[FrozenFile, ...]: ...
    def score(self, output: bytes, fingerprint: str) -> float: ...  # UnscoreableError
class NoiseCalibrator(Protocol):  # U17 declares, U20 implements on GitBaselineRunner
    def calibrate(self, workloads: Sequence[Workload], *, run_id: str, commit: str,
                  blocks: int) -> NoiseCalibration: ...
```

- Spend is read from the `Budget` delta through `_charged`
  (`generate.py:189-255`, `research/playbook.py:350-402`). U7 adds
  `ClaudeHypothesisGenerator` and `ClaudeTechniqueMatcher`
  (`optimization/hypothesis_source.py`); `lessons` and `avoid_titles` are
  ignored until W1.
- `NodeContext` (`nodes.py:181-237`), U2: `generator`, `matcher` (`None` keeps
  Step 2), `retrieval`, `generated_classes`, `generator_n`,
  `generator_max_calls`, `matcher_k`, `discovery_max_share`,
  `fix_retries_per_run: int = 0`, `playbook: tuple[Technique, ...] = ()`. U17:
  `quality: QualityCheck | None = None`, `default_output_check: bool = False`,
  `calibrator: NoiseCalibrator | None = None`, `calibration_blocks: int = 0`,
  `confirm_winners: bool = False`. Later units only read them.
- The factory (U10, batch 7) injects the scorer into `GitBaselineRunner`,
  `GitTrialRunner` and `GitCombiner` through the `scorer=` constructor
  keywords U24 adds (batch 6), so no runner protocol changes; U18 adds
  `Measured.outputs` (the agreed bytes, for them only) and `make_phase(mask=)`.

**Retry (U4, U6):** `procrun.RunFailure` (`procrun.py:112-117`) gains `kind`,
`exit_tail` and `workload_id`, set only by `measure.launch`'s exit branch
(`measure.py:255-259`). `execution/crash.py`: `parse_traceback(tail) ->
CrashReport | None` (chained, `SyntaxError` caret, frame carets, 3.8-3.14).
`execution/retry.py`: `ClosureIndex.build(diff, sources)`, `classify(failure,
*, closure, tracked, touched, excluded_workloads) -> TrialFeedback | None`.
`EditTask.feedback` (`protocols.py:137-146`); `TrialBrief.fix_retries_left`;
`GitWorkspace.commit(..., parent=None)` (`git.py:765-774`); `GitTrialRunner`
gains `fix_retries`, `retry_floor_usd`, `scorer`, `paired`.

### 3.5 Tables

- **005_lesson_ids.sql** (U1, done): both columns `VARCHAR(64) USING ::text`
  with `CHECK (col ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' AND col NOT LIKE
  '%..%' AND col !~ '(\.lock|\.)$')` (`state.py:64-85`); reads already cast
  (`postgres.py:170-178`); CI's column check updated (`ci.yml:775-800`).
- **006_review_outcome.sql** (U11a, landed early in batch 2): `chk_lesson_outcome` with `review`
  (`003:427-428`), comment at `003:444`.
- **007** (3c): `heal` in `chk_hypothesis_source` (`003:384`), `reproduce` in
  `chk_task_phase` (`003:253-257`). **008** (3b): `packages` columns,
  `run_packages`, `acquire` in `chk_task_phase`.

### 3.6 Live plumbing (U13; Wave 2 adds V4)

`LIVE_CORPUS_MODE=wired` (no candidates, generator on); a `ci.yml` input
`editor_model` (`default` or `claude-sonnet-5-5` with `EDITOR_EFFORT=low`); new
suites `ab-v2`, `ab-oss` (Wave 2), `sweep-record`, `grader`, and `noise`
(L0).

- *How the noise suite reaches this branch:* it lives only on
  `claude/window0-experiments` (`tests/live/noise.py`, `test_noise_guards.py`,
  `test_noise_live.py`, 1,608 lines, all from `923c8c8` and unchanged at that
  branch's head `0cdfb7a`; every import resolves at `7d8c40f`, checked). A
  merge of that branch (14 commits, 90 files) is too wide, and the copy is
  past a unit's 400 lines, so before batch 8 the Lead imports the three files
  verbatim plus the `noise` suite lines of `ci.yml` from `521c8c7` (not its
  heal, oss-ab or evolve suites) in one commit, "test(live): import the
  Window 0 noise suite", reviewed as a move. U13 then adds the paired path
  (§6, L0) on top.
- *Timeouts* (today hard 120, OSS 180, `ci.yml:528`): U13 pins hard 180 and
  OSS 300 from D41's 2.6x estimate, under the 360-minute job limit, and the
  noise suite at the Window 0 suite's 90 minutes (`NOISE_JOB_MINUTES`: 15
  setup + 60 budget + 15 overrun), which covers L0's 35. The Lead re-pins hard
  and OSS from L1a's measured wall time (a one-line `ci.yml` change) before
  L2a; the 2.6x is **unverified**.

---

## 4 Behaviour

### 4.1 Research (U9)

`blind`: `techniques = list(ctx.techniques)` (`nodes.py:1413-1427`), no request.
`matched`: `ctx.matcher.match` over `ctx.playbook` on the D7 budget, writing
`techniques` and `technique_matches`; `BudgetExceeded` before send,
`LLMConfigError`, `LLMUnavailable` and `UnusableReplyError` are soft
(`research_unavailable`, charged, continue blind); any other `EngineError`
follows D18.

### 4.2 Hypotheses (U8)

1. `seen` is every trial's hypothesis id plus `state["hypotheses"]`
   (`nodes.py:1433-1437`); untried ideas are unseen `ctx.candidates` plus
   `candidate_pool`.
2. Generate only if the untried list is empty, `ctx.generator` is set,
   `generator_calls < max_calls`, and neither `budget_exhausted` nor
   `discovery_exhausted` is set. Inputs: `project`, `understanding`,
   `hotspots`, `objectives[0]` (`:1290`), `techniques`, lessons (`:1438`),
   `avoid_titles` (titles in `hypotheses` and `parked`). `generator_calls`
   counts a failed paid call; a pre-send `BudgetExceeded` or `d ≤ cost_usd`
   (D7) sets `discovery_exhausted`.
3. Filters, each noted: a class outside `generated_classes` → `parked` ("needs
   approval"); `packages` → `parked` ("needs_package") until 3b; a repeated
   title (normalised as `generate.py:293`) dropped; every id re-checked by
   `validate_run_id`.
4. Caller ideas rank by `rank_hypotheses`, then generated by `rank_generated`;
   the node slices `max_hypotheses_per_round`, the rest return to the pool.
5. A round with no proposal is legal; the router decides.

### 4.3 Router (U8)

1. pending approvals (novel only) → `approval_gate`; 2. `budget_exhausted` →
`combine`; 3. any `keep` → `combine` (`nodes.py:1933` unchanged: confirmation
has already set the verdict, D41 b); 4. `round ≥ max_rounds` →
`combine`; 5. an untried idea → `hypotheses`; 6. generation still possible →
`hypotheses`; 7. otherwise `combine`. `review` verdicts never route.

### 4.4 Self-retry (U4, U6)

1. `_attempt` catches the `RunFailure` (`trial_runner.py:582`) and calls
   `classify` with the closure (tracked `.py` blobs at base minus deny-listed,
   capped; past the cap messages are withheld), `tracked = ls_tree(base)`
   (`:517`), the touched paths and `excluded_workloads` (3c: the reproducer).
2. A retry needs feedback, `trial.attempts ≤ fix_retries`, `trial.attempts − 1
   < brief.fix_retries_left` and `budget.remaining ≥ retry_floor_usd`.
3. The retry: `GitWorkspace.reset`; a fresh `EditTask` with the feedback and a
   new token, same `Budget`; merged `written` maps under the union's limits;
   `stage_all`, capture against the base, every anti-cheat rule;
   `commit(..., parent=base)`, `update_ref(own_ref, commit2, commit1)`,
   `progress.moved = commit2`; a fresh paired measurement.
4. An unaffordable retry, a spent run cap, an editor stop, a capture violation
   or a retry that crashes again keeps the first failure, noted in
   `retry_notes`, never `TrialUnaffordable`; an exception takes
   `_undo_own_ref` (`:465-487`). A retry crashing with another fixable error is
   not retried (the limit is 1); its type is a note in the trial's report row
   ("NameError; retry: TypeError, first failure kept").
5. Wall time: per-workload timeouts and `TEST_TIMEOUT_S` (`config.py:279`)
   bound each run; no run-level wall cap until the Step 4 CLI (§8 Q8); the
   report's total-time line shows it.

### 4.5 Review delivery (U11)

1. Only `needs_approval` (novel) verdicts enter `pending_approval_ids`
   (`nodes.py:1680-1682`).
2. Combine: the keep set as today (`:1746-1816`); then, with any `review`
   verdicts, `combine_kept` again for `engine/review-<run_id>` from the same
   base, accepting `keep` or `review`, into `review_combination`. No tokens,
   only measurement.
3. Deliver: the run branch as today. If the review combination holds, a
   create-only publish (`ctx.publisher.publish`) with its own `Delivery`. The
   review report opens with one D38 label per change, then: "Every judge
   passed and each change was confirmed (D41); outputs compared as stated
   (D35, D39); re-tested together; review before merging; not merged into
   `engine/run-<id>`, never pushed. Not re-tested together with
   `engine/run-<id>`; merging both is unproven." The main report lists the
   review branch (same sentence), parked ideas and any quality proposal.
4. Learn: review lessons carry outcome `review`, neutral in ranking.
5. Both reports (`_report`, `nodes.py:1117`) gain each trial's `retry_notes`,
   each gain per D42, the floor and calibration, the quality files' sha256,
   and "Total time: H:MM, first event to delivery, any approval pause
   included; N trial(s) retried" from the first `EngineEvent.at`
   (`common/models.py:658`; `state.py:112`) to the report.

### 4.5b 3c and 3b

D33-D34, D27-D32, A §4.5-4.6 and B §4.4 (1-8) and §4.5 (1-6) as corrected
above; each step's briefing restates them.

### 4.6 Failure modes

| Situation | Result |
| --- | --- |
| `save_trial` refuses or raises | The run fails with the round's progress kept (U1) |
| Generator empty, refusing or unusable; matcher fails | Soft note, charged; the router ends the run when nothing is left |
| Discovery unaffordable | `discovery_exhausted`; the pool is trialled, then combine |
| Retry not fixable, unaffordable, over the run cap or crashing again | First failure kept, noted; timeouts, `AssertionError` and the suite never retried |
| Crash message fails a template or closure | Type and frames only, noted |
| Exact mode: any class changes stdout or the declared file | Rule 3 rejects; a change confined to stderr, logging or undeclared files is not seen |
| Quality mode: output changes, quality within the bound | `review`, labelled (D38) |
| Quality mode: quality below the bound | Guardrail judge fails, rule 3 rejects |
| Output unscoreable (no agreement, bad format, scorer error) | No quality row: `missing_measurement`, rejected; at baseline the run stops |
| Trial touches or names a frozen quality file | `protected_path` or `quality_data_reference`, rejected unexecuted |
| Workload reads masked evaluation data at baseline | The run stops with that reason |
| Output varies run to run under the default check | The run stops at baseline: seed it, add a tolerance or a quality check |
| A winner does not confirm | `inconclusive`, "did not confirm"; the search continues |
| Review combination does not hold | No review branch, said in the report |
| A novel hypothesis | Caller ones interrupt; generated ones are parked |

### 4.7 Where the new checks run (U18-U25)

1. define: the output mode (D40). baseline: freeze and twice-score the
   quality files; `calibrate` (D41 c) sets the floor; quality mode also needs
   agreed fingerprints (`_require_trustworthy_baseline`).
2. Every measurement (trial A and B, confirmation, combine both sides): frozen
   paths masked before each workload launch; the agreed output scored once
   (cached by `raw_fingerprint`) into a `quality:<name>` row (`n=1`, unit
   `score`).
3. Judges against `base_measurements` (D41 a): `output_changed`, the drop
   rule (D38). Verdicts: rule 6 (D35), `confirm_one` (D41 b), the label (D38).

---

## 5 Security

| Threat | Controls |
| --- | --- |
| Injection relayed by generated hypotheses into the editor | D11: fence plus token refusal (`editor.py:463`); the generator fences repository text (`generate.py:215-242`) |
| Run output carrying secrets to the API (retry, 3c rewrite) | D13: per-version templates, closure-checked names on the raising line, ≤ 2 numbers of ≤ 4 digits, ≤ 300 characters, ≤ 3 tracked or touched frames within their files, no deny-listed paths or source lines; fenced; never stdout, timings, fingerprints, quality values, suite output or verdicts. Residual: about 18 bytes a run (O8), adding up across runs; 3c's rewrites share the cap (D36); a second retried trial per run waits for B-R2's safeguards, its attack tests at 19 bytes and the owner's flip |
| 3c: injection through the error report | D33: fenced with a per-request token, refused if it holds it; the variant writer never sees it |
| Retry as a reward-hacking channel | Own workload crash only, before any judge (`trial_runner.py:502-587`); full re-capture and anti-cheat on the union diff; one commit on the base |
| Discovery spend starving proofs | D7, enforced by `Budget.check` before send; `DISCOVERY_MAX_SHARE`; `discovery_cost_usd` reported |
| A trial faking the quality number | D37: a frozen builtin or a scorer run from an engine copy of base blobs (sha256-checked), never text the trial prints, the copy existing only during scoring; frozen files protected, naming them refused, read-denied to the editor, masked from workloads; deterministic; strict one-line format; a warning when another tracked input carries the labels column. Residual, review only: labels read via the main repository, the object store or an unfrozen input carrying them (Landlock read rules **unverified**, D30); a lookup table of label values baked into the code (it names no frozen path); a scorer executing its input |
| The scorer as a code path | Its own sandbox policy (network off, writes confined to the copy and scratch), output on stdin, `-s -B` with the forced hash seed, regular-file blobs only, no repository on `sys.path`, `QUALITY_TIMEOUT_S`, ≤ 128 bytes read, the copy removed in `finally` |
| Tolerance hiding a real change | A caller option, echoed in define and the report; a strict whole-token float rule, integers exact; sound one way (D39), counts printed as decimals the stated limitation; complete outputs only, else exact |
| An output check that compares nothing | An empty-output workload warned at baseline and in the report, refused in quality mode (D40) |
| Output change shipped unreviewed; excessive agency | Rule 6: `output_changed` is `review`, never `keep`; labelled; create-only under the prefix, never on a checked-out or default branch (`assert_safe_branch`), never merged or pushed; novel asks |
| Understand's quality proposal | Enum and tracked-path validated, never activated, shown as a suggestion |
| False keeps from timing noise | D41: ABBA alternation, confirmation before keep, per-project floor ≥ 2 %; L0 measures the single-look rate and the kept count |
| New per-role transports | The key stays in `AnthropicTransport`; every role model priced and effort-checked; no fallbacks on new roles |
| Widened Postgres ids | The id rule before any SQL plus the 005 `CHECK`; parameterised SQL |
| Supply chain of the engine | `pip-audit` on every Python PR and weekly; bandit and OSV unchanged |
| Install-config smuggling | D23 |
| Lessons in the generator prompt (W1) | Fenced, a line holding the token withheld; generator only. Lesson text carries timing gains (`lessons.py:47-48`), never quality values |
| Recorded replies (eval fixtures) | Parsed through the live schemas; test data only |
| 3b: slopsquatting, dependency confusion, malicious wheels, TOCTOU, SSRF, resolver exfiltration | D28-D31 plus A §5 (one index, `--no-config --no-sources`, RECORD checks, content-addressed store, sha256 at download and install, allowlisted URLs, scrubbed read-confined fetch child, `*PROXY*` never reaching workloads, `sandbox.py:63-67`) |
| 3c: reproducer gaming | D33-D34; sha256 per run; variants hidden; `heal_tamper`; no new files; human review stated |

Security Reviewer: U1, U4, U5, U6, U10, U16, U18 (tolerance, masking), U19
(scorer sandbox, freeze, parser), U21 (rule 6), U24, U25 (extra_protected,
proposal), and every 3c and 3b unit in §7.

---

## 6 Test plan

**Unit tests** (offline, TDD, 100 % line and branch kept):

- **U1 (done):** `h1` and a slug round-trip all three saves; `../x`, `a..b`,
  `Set Membership`, 65 characters refused before connecting, 64 accepted, a
  direct insert fails the `CHECK`; a legacy UUID reads back; 005 applies
  twice; a `save_trial` raise keeps the round's spend.
- **U2:** serde reflection; `initial_state` sets every key; unpriced role
  models and rejected efforts refused; `novel` in `GENERATED_CLASSES` refused;
  both retry settings outside 0-1 refused; `fix_retries_per_run` defaults to 0.
- **U4:** `parse_traceback` on 3.8-3.14 stderr (chained, caret, frame carets,
  cut tail); `classify` gives `None` for a timeout, a signal, `AssertionError`,
  the suite and an excluded workload; each template passes per version with
  closure-checked names; **live templates**
  (`tests/execution/test_retry_templates.py`) run each snippet under every
  `python3.N` on PATH and match stderr's last line, skipping locally only
  (`tests/execution/test_profiler.py:480-483`), never in CI once U3 covers 3.13
  and 3.14 (`ci.yml:385-397`); 3.13 forms pass with the path dropped; an ESC
  byte gives type and frames; closure withholds `AKIAIOSFODNN7EXAMPLE`, a
  5-digit number, a third number and an unknown function name; **digit
  canary** and **alphabet canary** (diff-defined `a00`-`aff` raised per byte,
  directly and via `eval`) give type and frames only; a `.env` or untracked
  frame is dropped, at most 3 sent; a frame line 0 or past its file is
  dropped; the 3.13/3.14 `ImportError` forms (top-level vs package) both pass.
- **U5:** each new pattern refuses a diff.
- **U6** (`test_trial_retry.py`): `NameError` then a fix gives `attempts ==
  2`, one commit on the base (`combine._unfit` passes), no `unrecorded_write`;
  a reset removes what the failed run wrote; unaffordable, `fix_retries_left=0`
  ("spent", never in the prompt) and a second fixable crash (type noted) keep
  the first failure; no stdout or timings in feedback; the hypothesis fenced,
  a token refused.
- **U7:** adapters on `ScriptedTransport` record spend; `rank_generated` keeps
  model order and a keep lesson reorders it.
- **U8** (`test_hypotheses_node.py`): one generation on an empty pool;
  parking, 3 sliced and 2 pooled, no regeneration while ideas remain; the
  budget refuses at the reserve and the share; `d ≤ cost_usd` sets
  `discovery_exhausted`, no request, no `ValueError`; a soft failure charged;
  the router with a pool returns `hypotheses`, then `combine` once calls run
  out; `generator=None` reproduces Step 2.
- **U9:** blind sends nothing; matched writes `technique_matches`; a matcher
  failure falls back to blind, charged.
- **U10:** per-role chains; `min_trial_budget` on the editor's chain equals the
  retry floor; blind `build_context` gives `techniques == ()`
  (`factory.py:306-379`; `generate.py:215-243` stays empty); the factory sets
  `fix_retries_per_run`, `default_output_check=True`, the calibrator and
  blocks, `confirm_winners`, and the same scorer into all three runners;
  `quality=None` gives no scorer. Step 2's E2E (`tests/e2e/test_step2.py`)
  passes under the flipped factory default: its scenarios go through
  `build_context` (`:400`, `:501`, `:597`, `:656`, `:711`, `:757`), and the
  one whose guardrails are `tests_pass` only (`:713`) now also gets
  `output_equivalence` (`_guardrails`, `:236-247`, already has it); its
  fixtures are deterministic. The live suites built by the factory (corpus,
  OSS, attack, e2e) are covered by L1a and L1b's output-check rejection count.
- **U11** (`test_review_delivery.py`): a `review` verdict passes `verdicts`
  (`trialled`, counted) and the gate's resume without `KeyError`; it gives
  `engine/review-<id>`, the run branch unchanged, no interrupt; each D38 label
  and D42 line renders; a failed review combination gives no branch; both
  reports carry the unproven-merge sentence, retry notes and total time; 006
  applies twice; review lessons are neutral; novel still interrupts.
- **U12:** a recorded reply replays to the same hypotheses; hit@3 at least the
  recorded value; an unknown label key fails with "refresh in live-smoke";
  grader replies replay through `grade_with`.
- **U13:** every new constant, need and timeout is pinned (hard 180, OSS 300,
  noise 90); a cap below its need is refused (`tests/live/conftest.py:12-17`);
  the noise suite's paired path plans 10 blocks per repository within its
  wall budget and records the single-look rate, the kept count and the gap
  sign, all three guarded offline.
- **U16** (`test_run_retry_cap.py`): at cap 1 the node passes 1, then 0, and a
  second fixable crash keeps its first failure with the "spent" note; a resume
  counts from checkpointed `trials`; a runner over its allowance is refused;
  cap 0 reproduces Step 2.
- **U17:** the new models validate (builtin xor scorer, name, `scorer[1]`
  frozen, digits 6-15), round-trip serde, default to Step 2; settings' bounds.
- **U18:** tolerant fingerprints: `0.1000000001` vs `0.1` equal at 9 digits,
  unequal at 12; integers `10` vs `11` never equal; `v1.10` vs `v1.1`,
  `id_2.50` vs `id_2.5` and `1_0.5` vs `10.5` not equal; `nan`, `inf`, `-0.0`
  kept verbatim; reordered lines equal only
  with `unordered_lines`; invalid UTF-8, stdout past the head or a file past
  the cap fall back to exact with a note; `raw_fingerprint` is the exact one;
  ABBA: the leading side alternates per index across warm-ups and timed runs
  in `measure_abab` (trial pairs, calibration, combine), the two
  pinned order assertions (D41) rewritten to it;
  the mask deletes frozen paths after each workload reset but not before the
  suite, never following a link; `Measured.outputs` holds the agreed bytes.
- **U19:** each builtin on fixtures (unequal line counts, too many rows
  unscoreable); the parser takes exactly one well-formed line, refusing two
  lines, a wrong name, `nan`, `inf`, 129 bytes, a non-zero exit, ESC; `freeze`
  records sha256, refusing untracked, oversized or changed files; the frozen
  copy runs (an edited worktree scorer does not), a scorer importing the
  repository fails, a nondeterministic one is refused; an output is scored once;
  the output reaches the scorer on stdin; no `<run>/quality` directory exists
  during a workload launch, and none is left after a scorer that raises;
  `label_column_leaks` finds the labels as a column of a CSV (header row or
  not) and not in a reordered one.
- **U20** (`test_paired_measure.py`): `base_measurements` from the twin,
  interleaved run by run (injected `RunOnce`); under an injected slow drift
  the paired gain is near 0 where Step 2's path wins; the suite once on B;
  `paired=False` is Step 2; `calibrate` gives gaps and a floor ≥ 2 %.
- **U21** (`tests/optimization/test_judges.py`): rule 6 for all classes, with
  and without `output_changed`; exact mode rejects changed output; quality
  mode passes and flags it; missing fingerprints still fail;
  `drop_unit=absolute` (0.912 → 0.907 passes at 0.005, 0.906 fails; zero
  baseline error rate judged); an `mae` drop of 0.5 is printed as 0.5, not
  "50.0%"; the judge runs under a `quality:<name>` guardrail alone and is
  `not_applicable` with neither; `relative` unchanged; every Step 2 judge test
  unchanged.
- **U22** (`test_noise_rule.py`): the floor raises `min_relative_gain`, a
  larger user value stays, memory untouched; trials are judged against
  `base_measurements` (completeness both sides), else the run baseline.
- **U23** (`test_confirm.py`): a would-be keep that confirms becomes a keep
  with `confirmations=2`; one that does not is `inconclusive` "did not
  confirm"; a would-be review confirms under `accept={keep, review}`; no
  combiner gives a note and Step 2 behaviour; D42's gain, margin and label
  (4.9 % small, 5 % solid, 20.1 % large).
- **U24:** quality rows and masks on every measured side in all runners;
  output bytes never in a `Trial`, `Measurement` or event; two outputs equal
  within tolerance but byte-different are scored separately (the cache key is
  `raw_fingerprint`); the editor's `view` of a `read_deny` path is refused
  ("evaluation data, off limits") and a listing omits it; the baseline runner
  notes a label-column leak.
- **U25:** `default_output_check` adds `output_equivalence` when absent; off,
  Step 2's delta keys (`test_nodes.py:166`) hold; a quality check adds the
  bound and `extra_protected`, no equivalence; both together refused (a
  workload with no scoreable output is not refused at define, which cannot see
  output; it stops at baseline); the trials node fills `TrialBrief.read_deny`
  with the frozen paths; a workload with empty stdout and no `output_file` gives
  the "compares nothing" warning and run-conditions line in exact mode and
  stops the run in quality mode; a proposal with an unknown measure or
  untracked path is dropped with a note, a valid one reported, never active.

**E2E** (`tests/e2e/test_step3.py` U14 and `tests/e2e/test_step3_quality.py`
U26, marker `slow`, real git and sandbox, scripted Claude):

- **E3-A:** `candidates=()` and a scripted generator reach a delivered branch;
  a run stopped at `interrupt_before=["trials"]` (as
  `tests/orchestrator/test_graph_e2e.py:431`) and resumed by a fresh graph
  records one generator request.
- **E3-E:** a caller `novel` candidate beside the generator pauses at
  `approval_gate` and resumes; the generator count stays zero.
- **E3-B:** a `NameError` from the first edit is fixed by the retry (`attempts=2`,
  delivered); with `EDITOR_FIX_RETRIES_PER_RUN=0` the first failure is kept.
- **E3-C:** default output check: a behaviour change with identical outputs
  lands on `engine/review-<id>`, no pause; one altering output is rejected;
  a novel one is parked.
- **E3-D:** a canary, a planted file as decimal numbers, and alphabet names in
  crash messages never reach a recorded body.
- **E3-F:** a quality check (`accuracy`, labels frozen): a change that
  improves accuracy and speed reaches `engine/review-<id>` labelled "result
  improvement", never the run branch.
- **E3-G:** the same check, a faster change that drops accuracy past
  `max_drop` is rejected by the guardrail judge.
- **E3-H:** a change that edits the labels file is rejected unexecuted
  (`protected_path`); one that rewrites the worktree scorer copy is not scored
  by it (the frozen copy runs); one whose code opens the labels by relative
  path fails at the mask; a scripted editor that views the labels gets the
  refusal, and a diff carrying a literal table of the baseline's label values
  is delivered to review, never kept on the run branch (a baked table is
  review-only).
- **E3-I:** A/A: a comment-only trial under an injected drift that makes
  Step 2's path judge it a win is not kept.

**Live** (CI `live-smoke`, one suite at a time under the 150 USD ceiling;
each run's cost and finding go to the ledger). Expected costs from Window 0:
E5 about 0.10 USD per task-arm (Sonnet); H 0.11, O 0.30 USD a run (Opus); M
0.45x Opus; E3 0.048 per repo-arm. A/B caps are `ab_need(plan)`
(`tests/live/discovery_ab.py:134-137`: `AB_GEN_CAP_USD`, 0.8, `:108-114`, plus
both run caps, rounded up as `ci.yml:636-637`), admitted only if they fit
(`tests/live/conftest.py:12-17`). The noise rule adds measurement, not tokens:
caps and USD are unchanged, wall time grows (§3.6).

| Run | Measures | Feeds | Cap | Expected | Cheapest arm |
| --- | --- | --- | --- | --- | --- |
| L0 `noise`, paired path | A/A on the 13 repositories, 10 blocks each (130 identical-code comparisons, ABBA): the single-look false-win rate (gate: at most 1 of 130, under 1 %, against 2.8 %; at the old rate the gate passes about 12 % of the time, at 0.5 % about 86 %); the kept count after confirmation (expected 0: 1 → re-run once after Q15's defaults are tuned; 2 or more → the floor or multiplier is revisited before L1a); the mean A/A gap's sign across blocks (non-zero after ABBA is a host effect, noted in the report); calibrated floors; whether row O's six gains (3.2-14.3 %) still clear their floors | D41's defaults (§8 Q15); W5's comparison | 0 (no request) | 0, about 35 min, 90-minute timeout | - |
| L1a `hard`, `wired` | Wins with no hypothesis handed over; retry rate; counts per class; output-check rejections; confirmations; discovery cost; wall time | Wave 1 acceptance; D9; U13's timeouts | 10 × 5 = 50 | ~1.0 | Sonnet engine |
| L1b `corpus`, `wired` | Control false wins with generation in the loop | The same | 15 × 5 = 75 | ~0.8 | Sonnet engine |
| L2a `oss`, `wired`, Sonnet low editor, 2 reps | Delivered against aimed-Opus 6/10 per rep; near misses; retry rate | W5 (≥ 10 of 20), W4 | 20 × 5 = 100 | ~3.0 | Sonnet first |
| L2b `oss`, `wired`, Opus editor | Only if L2a < 10/20 | W5 | 10 × 5 = 50 | ~3.0 | - |
| L3 `grader` | Opus 4.8 grader agreement on about 10 labels (≥ 9/10, no false positive on near misses) | Whether L4's hit@k counts | 10 × `GRADE_WORST_USD` (`discovery_grader.py:298`) | < 0.5 | - |
| L4 `sweep-record`, Sonnet medium, v1 + v2 | Recorded replies; v2 blind hit@1 | U12's fixture; v2 pre-check | sweep need, 1 arm × 37 repos (about 23) | ~1.8 | One arm |
| L5a `ab-v2`, arm A, 1 rep | v2 saturation (≥ 90 % revises) | Whether L5b runs | 12 × (0.8 + 1) = 21.6, need 22 | ~0.6 (+0.6 one rerun) | A only |
| L5b `ab-v2`, both arms, 2 reps | c, b, gains, controls | D2 | 24 × (0.8 + 2) = 67.2, need 68 | ~4.9 | After L5a |
| L5c `ab-oss`, both arms, 1 rep, 2 USD run cap | The same on small gains | D2 | 10 × (0.8 + 4) = 48 | ~3.0 | Skipped if moot |
| W1 refresh | The eval fixture after the prompt change | W1 | `sweep_need`, 1 arm × 25 v1 repos (`discovery_sweep.py:139-143`, about 16) | ~0.6 | One arm |

The expected total stays about 16.5-19.5 USD (about 22.5 with L2b), in Window
1, with L2a's second repetition (about 1.50 USD) and the one L5a rerun; L0
costs nothing. It replaces Window 1 row C (`STATUS.md` "Window 1", about 30
USD). W5's gate keeps aimed-Opus's 6/10, measured under the old rule: the
stricter rule can only lower Sonnet's count, so a pass still means at least as
good (§8 Q16). 3c's L7 and 3b's L6 are planned with their steps.

---

## 7 Work breakdown

Every unit: about 400 lines at most, tests first, disjoint files within a
batch, one commit, a Reviewer on a different model with the lens named, the
seams checklist in its brief.

**Wave 1:**

| # | Unit | Files | Lines | After | Reviewer lens |
| --- | --- | --- | --- | --- | --- |
| U1 | Postgres ids (**done**, `3ee4e76`) | `005_lesson_ids.sql`, `persistence/postgres.py`, `nodes.py` (guard), `ci.yml`, tests | ~200 | - | correctness; security (SQL) |
| U2 | Contracts: discovery and retry | `common/config.py`, `common/models.py`, `orchestrator/state.py`, `orchestrator/serde.py`, `optimization/sources.py`, `nodes.py` (`NodeContext` fields) + tests | ~330 | U1 | correctness |
| U3 | pip-audit in CI; interpreters 3.13, 3.14 | `ci.yml` (python job; `:380-397` to 3.8-3.14), `security.yml` | ~50 | U1 | correctness (CI) |
| U4 | Crash parser, classifier, closure, templates | `execution/procrun.py`, `execution/measure.py` (`launch`), `execution/crash.py`, `execution/retry.py` + tests, `test_retry_templates.py` | ~410 | U1, U3 (commit order) | security |
| U5 | Protected-pattern gaps | `optimization/anticheat.py` + tests | ~60 | U1 | security |
| U6 | Retry flow and fence | `execution/trial_runner.py`, `execution/git.py`, `execution/protocols.py`, `execution/editor.py`, `test_trial_retry.py` | ~400 | U2, U4 | security; correctness |
| U7 | Adapters and `rank_generated` | `optimization/hypothesis_source.py`, `optimization/ranking.py` + tests | ~250 | U2 | correctness |
| U8 | Hypotheses node and router | `nodes.py` (`hypotheses`, `after_verdicts`), `test_hypotheses_node.py` | ~380 | U7 | correctness; spec |
| U9 | Research node (matched, off) | `nodes.py` (`research`), `test_research_node.py` | ~200 | U8 | correctness |
| U10 | Factory: roles, playbook, retry floor and cap, scorer, calibrator, noise and output flags | `orchestrator/factory.py`, `test_factory_roles.py` | ~280 | U6, U7, U18, U19, U20, U24 | security (transports) |
| U11 | Review delivery, D38 labels, D42 lines, total time, retry notes | `nodes.py` (`verdicts` event text, `combine`, `deliver`, `_report`), `test_review_delivery.py` (the `_STATUS_AFTER_VERDICT` entry landed with U2 and `006_review_outcome.sql` with U11a, Lead, batch 2, so `review` is mapped and storable before U21 emits it) | ~360 | U21, U23 | spec (user decision 1, O7, O10); correctness |
| U12 | Offline discovery eval | `tests/live/discovery_grader.py`, `tests/live/discovery_sweep.py`, `tests/optimization/test_discovery_eval.py`, `tests/fixtures/discovery_eval/seed.json` | ~300 | U7 | weakened-test |
| U13 | Live plumbing, timeouts, L0 | `tests/live/corpus.py`, `tests/live/oss.py`, `tests/live/test_*_guards.py`, `tests/live/noise.py` (paired path), `ci.yml` (live-smoke) | ~300 | U3, U10, the Lead's noise-suite import (§3.6) | cost (caps) |
| U14 | E2E E3-A to E3-E | `tests/e2e/test_step3.py`, `tests/fixtures/step3/` | ~350 | U13, U16, U25 | correctness |
| U15 | Docs (Lead) | `CLAUDE.md` (D10, O1, O5, O7-O10), `services/python_agents/CLAUDE.md` (rule 6, modes, branches, keys), `README.md`, `STATUS.md` (dev-log rows 3c, 3b, 6 beside 0-5 at `STATUS.md:62-70`; Window 1 row C; D2's rule before L5a; B-R2 in the backlog) | ~180 | all | spec |
| U16 | Run retry cap (D12) | `nodes.py` (`trials`, `run_one`, `_runner_trial_problems`), `test_run_retry_cap.py` | ~120 | U10, U11 | security; correctness |
| U17 | Contracts: quality and noise (D4) | `common/config.py`, `common/models.py`, `orchestrator/serde.py`, `nodes.py` (`NodeContext` fields of §3.4) + `tests/common/test_quality_models.py` | ~300 | U2 | correctness |
| U18 | Tolerant fingerprints, output retention, mask, ABBA order | `execution/outputs.py` (new), `execution/measure.py` (incl. `_interleave`), `tests/execution/test_outputs.py`, the two order assertions in `test_measure.py` and `test_combine.py` | ~330 | U4, U17 | security; correctness |
| U19 | Quality scorer | `execution/quality.py` (new), `tests/execution/test_quality.py`, `tests/fixtures/quality/` | ~380 | U18 | security |
| U20 | Paired trials and calibration | `execution/trial_runner.py` (`_attempt` measurement, `GitBaselineRunner.calibrate`), `tests/execution/test_paired_measure.py` | ~330 | U6, U18 | correctness |
| U21 | Judges: rule 6, `output_changed`, absolute drop | `optimization/judges.py`, `tests/optimization/test_judges.py` | ~250 | U17 | security; correctness |
| U22 | Noise rule in baseline and judges nodes | `nodes.py` (`baseline`, `judges`), `test_noise_rule.py` | ~250 | U20, U21 | correctness |
| U23 | Confirmation before keep | `orchestrator/confirm.py` (new), `orchestrator/combine_node.py` (`accept`, one-change re-test), `nodes.py` (`verdicts` confirm call), `test_confirm.py` | ~380 | U22 | correctness; spec (O10) |
| U24 | Scoring and masks in the runners; editor read-deny | `execution/trial_runner.py` (score hooks, label-leak note), `execution/combine.py` (`_measure` both sides), `execution/protocols.py` (`TrialBrief.read_deny`), `execution/editor.py` and `execution/editor_tools.py` (the handler's `read_deny`), `tests/execution/test_runner_quality.py` | ~260 | U19, U20 | security |
| U25 | define modes, default output check, freeze, proposal, brief `read_deny`, empty-output check | `nodes.py` (`define`, `baseline` warning, `trials` brief, `_require_trustworthy_baseline`, `_run_conditions`), `orchestrator/understand.py`, `test_define_modes.py` | ~340 | U11, U19, U24 | security; spec (O7, O9) |
| U26 | E2E E3-F to E3-I | `tests/e2e/test_step3_quality.py`, `tests/fixtures/step3_quality/` | ~300 | U13, U16, U25 | correctness; weakened-test |

Build order (`nodes.py`: U2, U8, U9, U11, U16, U17, U22, U23, U25;
`ci.yml`: U3, U13; `trial_runner.py`: U6, U20, U24; `editor.py` and
`protocols.py`: U6, U24; `measure.py`: U4, U18: none of each group shares a
batch):

1. U1 (done).
2. U2, U3, U4, U5 (U3's commit before U4's).
3. U6, U7, U17.
4. U8, U12, U18, U21.
5. U9, U19, U20.
6. U22, U24.
7. U23, U10 (U10 needs U24's constructor seams on `GitCombiner` and the
   runners' score hooks, and U18's `make_phase(mask=)`; files disjoint:
   `confirm.py`, `combine_node.py`, `nodes.py` against `factory.py`).
8. U11, U13 (after the Lead's noise-suite import, §3.6; disjoint: `nodes.py`,
   006 against `tests/live`, `ci.yml`).
9. U25.
10. U16.
11. U14 and U26.
12. U15.
13. Live: L0, L1a, L1b, L2a × 2 (L2b if needed); the Lead re-pins the hard and
    OSS timeouts from L1a before L2a (§3.6); they report before Wave 3 (O6).

Each `nodes.py` unit branches from the previous one's commit, U13 from U3's
and the import; until U16 `fix_retries_left` stays 0 (fail closed). 26 units,
about 7,250 lines. After batch 7 a run built by the factory needs no
hypothesis handed over; after batch 9 output changes are judged; after batch
10 a fixable crash recovers.

**Wave 2** (the A/B follow-up; independent of Wave 1 except U12 and U13):

| # | Unit | Files | Lines | After |
| --- | --- | --- | --- | --- |
| V1 | Hard corpus v2 part 1: `deep`, `spread`, `misleading`, 2 each | `tests/fixtures/live_corpus_discovery/{deep,spread,misleading}*`, `_solutions/` | ~400 | - |
| V2 | v2 part 2: `uncommon` 2, `small` 2, decoy controls 2; manifest, parser, guards | the same dir, `tests/live/discovery_corpus.py`, `tests/live/test_discovery_corpus_guards.py` | ~400 | V1 |
| V3 | `ledgerclose` rebuild (both hot spots C-level compare loops) and the part-cost ratio guard (0.5-2) | `tests/fixtures/live_corpus_hard/ledgerclose/`, `tests/live/test_hard_corpus_guards.py` | ~200 | - |
| V4 | A/B instrument: corpus and arm selection, `ab_decision(b, c, controls_a, controls_b)` beside `MIN_DISCORDANT_LEAD` (`(1, 4)` met; `(2, 4)` not; more B control false wins not met), pooled; `ab-v2`, `ab-oss` | `tests/live/discovery_ab.py`, `tests/live/test_discovery_guards.py`, `ci.yml` | ~250 | U13 |
| V5 | Grader labels (Lead) and the agreement test | `tests/fixtures/grader_labels.json`, `tests/live/test_grader_agreement_live.py` | ~200 | - |
| V6 | Commit L4's recorded fixture | `tests/fixtures/discovery_eval/` | ~100 | L4 |

v2 rules: the author's technique list is written without reading
`research/playbook.json`, card fit recorded only after the corpus is frozen;
every slowdown has a reference fix in `_solutions` and a guard proving it
winnable. Live order: L3, L4, L5a, L5b, L5c.

**Wave 3** (held until Wave 1's live runs report, O6; each unit gated):

| # | Unit | Files | Lines | Gate |
| --- | --- | --- | --- | --- |
| W1 | Lessons and `avoid_titles` in the generator prompt (fenced) | `optimization/generate.py` + tests | ~220 | Wave 1; a W1 refresh after |
| W2 | Combine-failed lesson discount | `learning/lessons.py`, `nodes.py` (`learn`) | ~150 | Wave 1 |
| W3 | Profiler `Hotspot.tags` (never set in `src`) | `execution/profiler.py`, `execution/_profile_shim.py` (not re-read) | ~200 | lowest priority |
| W4 | Evolution: near-miss compounds | `optimization/evolve.py`, `nodes.py` (hook in `hypotheses`) | ~380 | L2a: ≥ 4/20 runs with ≥ 2 disjoint near misses |
| W5 | `EDITOR_MODEL` flip to Sonnet low | `common/config.py` | ~10 | L2a: ≥ 10 of 20 delivered, 0 control wins in L1b |
| W6 | `RESEARCH_RETRIEVAL` flip to `matched` | `common/config.py` | ~10 | D2's pooled rule met |

**Conditional, not in Step 3: P, paper intake.** *Condition:* D2's rule is met
and E7 rerun through `src` costs at most 0.35 USD a paper. *Then,* with its own
briefing and approval: P1 a snapshot source (arXiv only on the user's
machine); P2 the Haiku screen and PDF cost bound; P3 pass 1 with citations and
local quote checks; P4 pass 2, the check-key registry and `pending/`; P5 human
card review and `papers.json`. The monitor moves to the Step 4 CLI. *Otherwise*
papers stay deprioritised, recorded in STATUS with the data.

**Backlog after Step 3:** B-R2, a second retried trial per run (D13), Step 4
at the earliest: the safeguards first (type and template id only on the
second retry; the per-project rolling budget), then the five attack tests at
the 19-byte bound, then the owner's flip on the recorded evidence; the
per-trial bound stays 1.

**3c outline** (its own step, first, O5; about 7 units): C0 contracts and 007,
the `needs_package` refusal; C1 the shim and signature matching; C2 the
reproducer and variant writers and static checks (security); C3 the reproduce
node, freeze, N/N baseline and `--deselect` (`nodes.py:647`), rewrites counted
against the run cap; C4 `HealJudge`, the output-check exemption, `heal_tamper`,
the no-new-file rule and the retry exclusion (security); C5 delivery of R then
F on the review branch, and the report; C6 the E2E corpus (5 planted bugs, 3
controls; harder than the saturated probe, run 40082854689) and L7.

**3b outline** (its own step, after 3c; about 10 units): B0 contracts and 008;
B1 name snapshot and near miss; B2 the pure policy; B3 wheel inspection; B4
registry and allowlist proxy (security); B5 `uv` provenance, lockfile and
fetch under read confinement plus the Landlock probe (security); B6 offline
envs, `make_phase(env=)` (`measure.py:140`), `_env`/`_wheels` and `_host`
(`measure.py:321`) (security); B7 the acquire node, C1, capture from C1, the
whole-run E0 baseline and the ambient ratio (security); B8 combine with
packages, the drop with dynamic fallback, the tie-break and the install line;
B9 E2E and L6.

---

## 8 Open questions (Q1-Q5, Q7, Q8 and Q11-Q13 answered by the owner; Q17 lists the Lead's readings)

1. **CLAUDE.md Step 3 row.** *Answered (O1):* "generator wired, engine
   self-retry, review delivery, quality check, noise rule, hard corpus v2 and
   the retrieval re-test, lessons and evolution; paper intake conditional",
   Sonnet for discovery (U15).
2. **Behaviour ideas by default.** *Answered (O2, O7):* yes, judged as D35 says.
3. **The re-test.** *Answered (O3):* yes.
4. **3b lockfiles.** *Answered (O4):* hash-pinned `requirements*.txt` first;
   `uv.lock` only after probing `uv lock --no-build` on dynamic metadata
   (**unverified**).
5. **3b and 3c order.** *Answered (O5):* 3c first (D36).
6. **The reproducer model.** Sonnet 5.5 medium is a guess. *Recommended:* L7
   compares it with Opus in 3c.
7. **Small gains under the noise floor.** *Answered (O10):* the noise rule is
   in Step 3 (D41-D42).
8. **A run-level wall cap.** *Answered:* a total-time line now; `--max-time`
   with the Step 4 CLI.
9. **Review branches and learning.** Merges are not detected, so review
   lessons stay neutral. *Recommended:* accept until the Step 4 GitHub App.
10. **Novel lessons across runs.** *Recommended:* rely on W1's prompt channel.
11. **A quality bound for output changes.** *Answered (O7):* in Step 3 (D37-D40).
12. **The default output check.** *Answered (O9):* on (D40).
13. **The per-run retry default.** *Answered (O8):* 1. 2 only after B-R2: its
    safeguards, its attack tests passing at about 19 bytes a run (not 36),
    and the owner's decision on a STATUS entry with the recorded wire bodies.
    B-R2 lifts the run cap only; the per-trial bound stays 1 (Q17).
14. **Quality as a goal.** Requiring an improvement, or a quality objective
    with its own noise rule, is not designed. *Recommended:* with `--goal`
    parsing in Step 4.
15. **The noise defaults.** 3 calibration blocks and a gap multiplier of 2 are
    unmeasured under alternation, and the floor is per project (the largest
    workload's), which can hide a quiet workload's real gain. *Recommended:*
    L0 sets both and checks row O's six gains before L1a; per-workload floors
    only if L0 shows the cost.
16. **W5's comparison arm.** Aimed-Opus's 6/10 was measured under the old rule.
    *Recommended:* keep the gate (a stricter rule only lowers Sonnet's count);
    if L2a fails narrowly, L2b gives a same-rule comparison.
17. **The Lead's readings, open to the owner's objection.** These are the
    Lead's, not the owner's: (a) `EDITOR_FIX_RETRIES` bounded 0-1 (D12; the
    owner set its default; the bound is unreachable above 1 under the run cap);
    (b) ABBA order within each alternated pair (D41; the owner wrote "old,
    new, old, new"); (c) L0's gate on the single-look rate rather than on
    zero kept pairs (§6); (d) D22's proportional restatement. *Recommended:*
    keep all four unless the owner objects.
