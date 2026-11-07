# Emergence round 2: report

Round 2 ran under the charter (O54), the society rules (O55 as amended by O58)
and the seats of O57 as amended ([1]). The board is `round-2/board.md`, entries
[1] to [95]. Round 1's board is cited as r1[n].

- **Branch:** `claude/step3-emergence-r1`. The tail read the worktree at
  `54b3c3d` ([87], [94], [95]).
- **The round's two builds:** `818a05e` (S1) and `775890d` (S4, unit 1), on
  `fe0d4ca`.
- **Live spend in the round:** 0 USD. Nothing was dispatched ([94], [95]).
- **Window 2** (owner, [5]): a second key with 200 USD. Round 2's live ceiling
  is 120 USD; 80 USD is reserved for the ladder and is not round 2's.

## 1. How the round ran

| Phase                | Agents                            | Board     | Models                                                              |
| -------------------- | --------------------------------- | --------- | ------------------------------------------------------------------- |
| 0 Facts              | 1                                 | [2]       | session model                                                       |
| 1 Proposals, wave 1  | 9, all at once                    | [3]-[21]  | Bounds first and Pre-mortem on Fable; the other seven on Opus ([1]) |
| 1c Contrarian        | 1, after reading wave 1           | [22]-[23] | Fable                                                               |
| 1b Cross-pollination | 10, all at once                   | [24]-[33] | as wave 1, with the Contrarian on Fable                             |
| 2 Debate, round 1    | 10, each critiquing two seats     | [34]-[53] | as 1b                                                               |
| 2 Debate, round 2    | 10: keep, revise, withdraw, merge | [54]-[83] | as 1b                                                               |
| 3 Synthesis          | 1                                 | [84]      | Sonnet, which no proposer used                                      |
| 4 Judging            | 3                                 | [85]-[87] | evidence and reward hacking on Opus, correctness risk on Fable      |
| 5 Build, review, fix | 2 builders, 2 reviewers           | [88]-[93] | builders on Opus, reviewers on Fable                                |
| 6 Verification       | 2, units then measures            | [94]-[95] | Fable, both                                                         |

Seats and models are from `round-2/briefs/seats.json`; the tail's models are
from `round-2/tail.js` (`sonnet` for synthesis, `fable` for the correctness
judge, reviewers and verifiers, the session model elsewhere).

**Lead entries:**

- [1]: the opening, the seats, the order of play.
- [5]: Window 2, the 120 USD ceiling and the variance rule (at least 3 runs per
  library per arm, several libraries, twins wherever arms are compared). No plan
  is costed against the new key until the `ideas-validate` smoke requests
  (Sonnet 5, Fable 5) pass on it.

**Process notes:**

- **Phases 0-2** ran as background agents from the rendered briefs in
  `round-2/briefs/`, as in round 1 (`round-2/LAUNCH.md`).
- **Phases 3-6** ran as one Workflow, `wf_2f6da9da-bfb`, from a byte-identical
  scratch copy of `round-2/tail.js`. Its journal holds 12 agents, each with a
  result: synthesis, three judges, two builds, two reviews, two fixes and two
  verifiers.
- **The survivor rule** (`tail.js:102-111`): not refuted by at least 2 of 3
  judges and no FIXED touch; the top two by rank score are built. That gave S1
  and S4.
- **The verifiers ran to completion.** The Lead completed neither ([94], [95];
  O57).
- **Office hours:** no seat posted a `QUESTION for Facts:` entry.
- **Ids that repeat round 1's:** round 2's EXP-1, EXP-2, EXP-3 and BND-X are new
  proposals under round-1 ids. Round 1's are cited as r1[n].

## 2. The facts card ([2])

Numbers only, recomputed with `python3 -I` over the ten archives (X2 d1-d8 and
E1/E2).

- **Settings now:** S1 `IDEAS_COUNT_CONTRACT=record`; S2 `SITE_STACKS=record`,
  while the X2-S arm still exports `on` (§1).
- **E1/E2 against X2-0:** O52's call "keeps fewer"; combine mean difference
  −6.44 points against the twin's mean gap of 7.14 (§2).
- **S1's labels on 73 trials:** fired 12 of 36 kept, not_fired 0 of 11,
  uncounted 7 of 11 (§4).
  - The 11 uncounted are 3 compounds, 3 non-compound with no anchor, and 5
    anchored with no unit rows. Four of those 5 are `token_next_by`, all kept.
- **The floor:** X2-S's median floor equals X2-0's (2.00 %) on three of four
  libraries (§5).
- **The twin gaps:** pyparsing 2.70 points / 0 kept, tomli 3.94 / 0,
  sortedcontainers 3.22 / 0, sqlparse 18.69 / 2; mean 7.14. X2-S's own sqlparse
  pair is 9.60 / 8 (§7).
- **Money:** balance 21.08 USD; need 9.35 per library-run; X2-S's measured mean
  2.46 per library-run (§8).
- **Points:** no file records halved totals. The arithmetic halves are 3.75,
  3.75, 2.875, 2.775, 1.775, 1.4, 1.375 and 1.3 (§9).

## 3. Every proposal and its fate

Thirty proposals: 18 in wave 1, 2 from the Contrarian, 10 in cross-pollination.
Judges are E (evidence), C (correctness risk), R (reward hacking).

| Seat                   | Proposal                              | Debate                                      | Synthesis            | Judges E / C / R    | Built       |
| ---------------------- | ------------------------------------- | ------------------------------------------- | -------------------- | ------------------- | ----------- |
| Interpreter specialist | INT-1 anchor-first count units [3]    | revised [66]                                | S2                   | 5 / 6 / 4, refuted  | no          |
| Interpreter specialist | INT-2 price card [4]                  | merged into BND-4, predictor withdrawn [67] | S2                   | refuted             | no          |
| Interpreter specialist | INT-3 bytecode axis [30]              | revised [69]                                | S2                   | refuted             | no          |
| Expert prior           | EXP-1 family lane [6]                 | withdrawn [56]                              | dropped              | -                   | no          |
| Expert prior           | EXP-2 family record [7]               | revised [59]                                | dropped [84]         | -                   | no          |
| Expert prior           | EXP-3 process-state differential [31] | revised [64]                                | S3                   | 2 / 3 / 2, refuted  | no          |
| Scaling                | SCL-1 engine-scaled copies [8]        | merged into SCL-X [62]                      | S4                   | 4 / 7 / 6, survives | no          |
| Scaling                | SCL-2 growth card [10]                | withdrawn [63]                              | dropped              | -                   | no          |
| Scaling                | SCL-X count slope [24]                | revised [65], host of SCL-1                 | S4                   | survives            | no          |
| Verifier-designer      | VER-1 repetition-free replay [9]      | revised [79]                                | S4                   | survives            | yes, unit 1 |
| Verifier-designer      | VER-2 suite as off-shape corpus [12]  | revised [80]                                | S4                   | survives            | no          |
| Verifier-designer      | VER-3 late-writer audit [32]          | revised [81]                                | S4                   | survives            | no          |
| Memory & allocation    | MEM-1 shadow memory reading [11]      | revised [73]                                | S4                   | survives            | no          |
| Memory & allocation    | MEM-2 memory claim on every idea [13] | withdrawn [83]                              | dropped              | -                   | no          |
| Memory & allocation    | MEM-X the collector's bill [25]       | revised [82], host of INV-6 and ANA-X       | S3                   | refuted             | no          |
| Analogy transfer       | ANA-4 transfer price card [14]        | withdrawn [54]                              | dropped              | -                   | no          |
| Analogy transfer       | ANA-5 reference realisation [17]      | merged into INV-5 [57]                      | S5                   | 3 / 4 / 3, refuted  | no          |
| Analogy transfer       | ANA-X collector card [33]             | merged into INV-6 [60], then MEM-X          | S3                   | refuted             | no          |
| Pre-mortem             | PRM-4 same-site step [15]             | revised into a shadow stacked trial [68]    | S5                   | refuted             | no          |
| Pre-mortem             | PRM-5 site ledger [16]                | revised, park withdrawn [74]                | dropped [84]         | -                   | no          |
| Pre-mortem             | PRM-6 dead-fire re-entry [29]         | revised [75]                                | S5                   | refuted             | no          |
| Bounds first           | BND-3 floor fact [18]                 | revised [70]                                | S2 (record leg only) | refuted             | no          |
| Bounds first           | BND-4 where the work went [19]        | revised [71], host of INT-2                 | S2                   | refuted             | no          |
| Bounds first           | BND-X three bases of a floor [27]     | revised [72]                                | S2                   | refuted             | no          |
| Inversion              | INV-4 the stacked round [20]          | withdrawn [55]                              | dropped              | -                   | no          |
| Inversion              | INV-5 top keep's second draw [21]     | revised [58], host of ANA-5                 | S5 (host)            | refuted             | no          |
| Inversion              | INV-6 collector card [28]             | merged into MEM-X [61]                      | S3                   | refuted             | no          |
| Contrarian             | CON-1 "the twin's band is known" [22] | revised [76]                                | S1                   | 7 / 7 / 6, survives | yes         |
| Contrarian             | CON-2 "one draw is the pool" [23]     | revised [77]                                | S1 (view_sha half)   | survives            | view record |
| Contrarian             | CON-3 "a keep is a win" [26]          | revised, headline withdrawn [78]            | S1                   | survives            | yes         |

### Why each went where it went, one line each

**Withdrawn in debate (5):**

- **EXP-1** (Expert prior): two of its four pinned families lose on 3.11, and
  `far` trials 0.64 ideas a run, too few for its bar ([35], [52]; [56]).
- **SCL-2** (Scaling): a lane-facing growth card is observe mode in kind, and
  `far` trials about 0.2 sqlparse ideas a run ([39], [44]; [63]).
- **MEM-2** (Memory & allocation): a cache's byte bound is a guess about the
  input, and the block's third line was the RSS guard's slack ([48], [51];
  [83]).
- **ANA-4** (Analogy transfer): the price's sign turns on an input statistic the
  lane cannot know, and the losing trials come from a lane the card never
  reaches ([43], [53]; [54]).
- **INV-4** (Inversion): profiling at round 1's tip closes the repair path (6 of
  16 same-site keeps beat their parent) and cannot fit 360 minutes ([37], [46];
  [55]).

**Dropped by the synthesis (2, plus one leg)** ([84]):

- **EXP-2:** no consumer acts on it this round; its hoist split is INT-3's work
  axis and its diff field VER-1's; its fixtures are in-sample.
- **PRM-5:** with the park withdrawn, a ledger of two paid losses stands in for
  a bound; offered back as a rider.
- **BND-3's lane-facing gap line** (`IDEAS_BOUNDS=on`): it changes requests,
  claims no gain and needs S2's calibration; round 3.

**Into S1, survived 2 of 3, built:**

- **CON-1:** one A/A pair is not a band; the third request-identical draw falls
  outside the kept band on 4 of 4 libraries (tomli 6, 6, 4; sqlparse 9, 7,
  11, 3) ([22]). Revised to the rank and sign test after [45] and [49] ([76]).
- **CON-2:** the half that records `view_sha` and `served_model` was built. The
  second ideation draw (`IDEAS_DRAWS=2`) was not carried: its bar is set from
  one pair on one library ([85]), and it lacked a fakes test ([87]).
- **CON-3:** the delivered-mass column and the rider-minutes ledger were built;
  `KEEP_STOP=mass` and `LESSON_GAIN_WEIGHT` were cut by CON-3 itself ([78]).

**Into S4, survived 2 of 3, unit 1 built:**

- **VER-1:** built as unit 1, the distinct-once replay by counts ([91]).
- **SCL-X with SCL-1, VER-2, VER-3, MEM-1:** not built; the builder stopped at
  the line budget after unit 1 ([91]). VER-2 waits on a ruling about r1[62]
  ([86], [87]).

**Into S2, refuted 2 of 3** (INT-1, INT-2, INT-3, BND-3's record leg, BND-4,
BND-X):

- The inclusive rule was chosen on the four archived `token_next_by` keeps it
  then relabels ([86]).
- The uncounted bar fails on X2-B's own libraries, 3 of 57 is 5.3 % ([85]).
- Measure 2 would rest on uncalibrated, model-written floors ([85], [86]).

**Into S3, refuted 3 of 3** (MEM-X, INV-6, ANA-X, EXP-3):

- The gain leg's own numbers give about 1.8 % wall, under the floor ([85]).
- Its flagged delivery goes through `_rule_6` (a frozen judge), and
  `PROCESS_STATE=on` withholds a keep after the frozen verdict. All three judges
  say those legs are reported, not built ([85]-[87]).

**Into S5, refuted 3 of 3** (INV-5, ANA-5, PRM-4, PRM-6):

- Its 0.35 acceptance rate is cross-run spread on one library ([85]).
- Its +10 bar counts in-run events, not the combine against the twin ([86]).
- A second trial under one hypothesis id misreports the row writer ([87]).

### The synthesis ([84])

Five proposals, ranked by effect × grounding × testability / (11 − cost).

| Rank | Proposal                           | Merged                                              | Score | Kind                      |
| ---- | ---------------------------------- | --------------------------------------------------- | ----- | ------------------------- |
| S1   | variance accounting in the harness | CON-1, CON-3, CON-2's view_sha half                 | 144.0 | record-only               |
| S2   | one counted reading, v3            | INT-1, INT-3, BND-4 with INT-2, BND-X, BND-3 record | 128.0 | record-only               |
| S3   | collector and process-state shims  | MEM-X (INV-6, ANA-X), EXP-3                         | 74.7  | record leg R, gain leg G  |
| S4   | shadow verification                | SCL-X (SCL-1), VER-1, VER-2, VER-3, MEM-1           | 42.0  | record-only               |
| S5   | second realisation, three triggers | INV-5 (ANA-5), PRM-6, PRM-4                         | 35.0  | gain-bearing (REDRAW_TOP) |

The synthesiser's round plan came to about 67 USD of expected spend, about 78
with the optional draw leg, of 120.

### The three judges ([85]-[87])

| Proposal | Evidence (Opus) | Correctness risk (Fable) | Reward hacking (Opus) | Result          |
| -------- | --------------- | ------------------------ | --------------------- | --------------- |
| S1       | survives, 7     | survives, 7              | refuted, 6            | survives 2 of 3 |
| S2       | refuted, 5      | survives, 6              | refuted, 4            | refuted         |
| S3       | refuted, 2      | refuted, 3               | refuted, 2            | refuted         |
| S4       | refuted, 4      | survives, 7              | survives, 6           | survives 2 of 3 |
| S5       | refuted, 3      | refuted, 4               | refuted, 3            | refuted         |

**What the judges asked of the two survivors:**

- **S1** ([86], refuting): runs that share one pool median are correlated, so
  the exact binomial understates the null. 7 of 8 prints 0.035 against a true
  0.086. It also asked that X2-S's kept counts leave the pool, frozen before any
  run.
- **S1** ([87], conditions): size the ledger on max(declared, last measured);
  read signs against the lower median; build no `IDEAS_DRAWS` leg without a
  fakes test.
- **S1** ([85]): state whether the sign test is one- or two-sided.
- **S4** ([85], refuting): "protects delivery" changed 0 deliveries on the
  archive; the one replayed member was already undelivered.
- **S4** ([86], conditions): the +5 counts only if the memo-family leg is read;
  `constant_holds` on scaled benchmark inputs must not print as verified; the
  suite corpus extends r1[62] and needs a ruling.
- **S4** ([87], conditions): a dying capture launch leaves every verdict
  untouched, by a fakes case; test the whole settings dict together.

The judges' "would have saved" notes for every refuted proposal are in the
seats' library files.

## 4. Found again: round 1 and earlier

Ideas round 2 re-found from round 1 (r1[n]) or round 0 (`library/round-0.md`).
Most were taken up as credited carry-forwards, not found blind.

| Round-2 proposal    | Re-finds                                                                       | How                                             |
| ------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------- |
| INV-4, INV-5, PRM-4 | carry-forward 1: TNX-1 r1[46], TNX-2 r1[88]; REAL-2 (round 0)                  | taken up and credited ([15], [20], [21])        |
| PRM-6               | carry-forward 2: BND-X's re-entry r1[67]/[95], PRM-3 r1[66]; REAL-1            | taken up and credited ([29])                    |
| BND-3               | the seat's own BND-1 r1[49] and BND-X r1[67]; ALGO-1 (round 0)                 | credited ([18])                                 |
| VER-1, VER-2        | carry-forward 3: SHP-3 r1[60]; SKEP-1 (round 0)                                | taken up and credited ([9], [12])               |
| SCL-1               | SHP-3's capture point r1[110]                                                  | credited ([8])                                  |
| INT-2, BND-4        | PRM-1's price list on 3.11 r1[56]; REPR-1 (round 0)                            | BND-4 credits PRM-1 ([19])                      |
| ANA-5               | ANA-1's trap, r1[105]: the "known structure" is the harness's aimed hypothesis | conceded in its own revision ([57], after [43]) |

**Repetition inside the round, said plainly** ([84]):

- **Seventeen readings on one launch.** About 17 of the 25 surviving proposals
  are record-only readings on S1's counted launch. Each pre-registers the same
  +5, the same byte-identity test and the same X2-0 band, and each asks for the
  same sqlparse, tomli and mistune runs.
- **One pyparsing edit, four times.** Four pyparsing plans ([6], [46], [51],
  [52]) pre-registered the same +8.2 to +8.3 bar on the same one-line edit.
- **One collector card, three seats.** The collector card was found three times
  in cross-pollination (MEM-X [25], INV-6 [28], ANA-X [33]), and BND-X [27]
  added a gc basis to the same shim.
- **Little on yield.** No proposal on the board raises the yield of kept ideas,
  except S5, whose power is 0.44 at best.

No judge, reviewer or verifier called any number fabricated. The numbers that
were wrong were corrected by their own authors:

- ANA-4's "8 of 20" became 7 ([54]);
- INV-6's "never in `MatchFirst`" was corrected ([61], found by [51]);
- MEM-2's measure-1 share was about 4x too high ([83], found by [48]);
- BND-X's parcelindex floor was corrected ([72], after [41]).

## 5. The two builds

**S1: variance accounting for X2 (`818a05e`, 9 files, +888/−19).**

- **The mechanism.** The report gains a `--variance` page, which:
  - reads each run against its library's A/A pool, with the read arm left out,
    and prints its rank with the null rate;
  - calls an arm with a stratified sign test under an exact re-dealing null
    ([86]); the p is two-sided, fixed before any run ([89], [90]);
  - prints delivered mass (refit ratios 0.92-1.54, median 1.16; X2-S 0.151 USD
    per delivered point);
  - prints the rider-minutes ledger, which `check_plan` reads (312 minutes pass,
    416 are refused).
  - `IDEAS_VIEW_RECORD` adds `view_sha` rows to every arm, record only and off
    by default ([88]).
- **The pool:** frozen before any run, with X2-S out ([88]). It holds X2-0,
  X2-0', X2-C and, after the Lead's ruling below, X2-SV.
- **Not built:**
  - `IDEAS_DRAWS=2` ([85], [87]);
  - the ledger's measured half, which is a hand step (`RIDER_MEASURED = {}`,
    [89], [90]).
- **Tests:**
  - `tests/live/test_ideas_x2_variance.py` (20 after the fixes);
  - +3 in `tests/optimization/test_idea_pipeline.py`;
  - 1 line in `test_ideas_x2_guards.py` ([88], [90]).
- **Review** (Fable [89]):
  - should_fix: the sign test's sidedness was not pre-registered. Fixed: the
    test is two-sided, and the archive's X2-V kept reads 0.0926 ([90]).
  - should_fix: `seconds_measured` started after the clone. Fixed ([90]).
  - Two nits left: the measured half of the ledger, and twin bar (ii), which
    cannot fail at the planned n.
- **The commit** carries `ci-E1-S1` (one `ci.yml` line) and a `STATUS.md` note.
  The note says S1 is "proposed to the owner, not ruled"; O51 as amended and O52
  stay the ruling reading.

**S4 unit 1: shadow verification record (`775890d`, 24 files, +2043/−13).**

- **The mechanism:** `SHADOW_VERIFY=off|record`, default off ([91]).
  - With `record`, each runner adds one capture launch per workload and side.
  - `_capture_shim.py` records the benchmark's direct plain-typed calls to the
    package and replays them in fresh imports: a sequence leg, and a
    distinct-once leg per point, both read by cProfile counts.
  - `shadow_verify.py` labels each trial `repetition_fit`, `partial` or `clear`,
    or `no_count_gain`, `corpus_mismatch` or `uncapturable`.
  - Labels go to X2 rows only.
- **The X2 arm:** X2-SV, which is X2-C plus `SHADOW_VERIFY=record` on sqlparse,
  tomli and mistune.
- **Not built:**
  - SCL-X's scaled mode, MEM-1's traced launch, VER-3's audit and the report
    column;
  - VER-2's suite corpus, which waits on the r1[62] ruling ([91]).
- **Tests:**
  - `tests/execution/test_capture_shim.py`;
  - `tests/execution/test_capture_measure.py`;
  - `tests/optimization/test_shadow_verify.py`;
  - `tests/live/test_ideas_x2_shadow.py`;
  - `tests/fixtures/capture_words/` (6 files, a toy package) ([91], [93]).
- **Review** (Fable [92]):
  - should_fix: an `lru_cache` on the capture point read `corpus_mismatch`.
    Fixed by following `__wrapped__` ([93]).
  - should_fix: the shadow rider was missing from `RIDER_SECONDS`. Fixed:
    `Rider(run_s=8.0, trial_s=16.0)` ([93]).
  - Two nits left: `raised` is not compared across sides, and the `clear` leg is
    proven on the toy fixture only.
- **The commit** carries:
  - `ci-E1-S4`;
  - S1's pin move (`S1-pin-E1-S4.patch`, [93]);
  - the X2-SV listing.

**The Lead's two rulings while committing** (checked against
`git show 775890d`):

1. **Listing X2-SV in `EVERY_ARM` moved four arm-list pins.**
   - `EVERY_RUN` went from 32 to 35.
   - The stacks test reads `ARMS[-3:]` and the count test `ARMS[-2:]`.
   - The variance pool and its `aa` map now include X2-SV.
   - `test_corpus_guards` gained `"X2-SV:sqlparse"`.
   - S4's own `test_ideas_x2_shadow.py` dropped its monkeypatch fixture and
     asserts `x2.EVERY_ARM[-1] is x2.X2_SV`.
2. **X2-SV is built `aa="full"`.** Its requests are identical to X2-C's, record
   only, so it joins S1's A/A pool before any run. `STATUS.md` amends S1's note:
   the pool is X2-0, X2-0', X2-C and X2-SV. Section 11 asks the owner to rule.

**Correction to the commit messages.** `818a05e` cites S1's build and review as
[88]-[91] and `775890d` cites S4's as [92]-[93]. The board has S1 at [88]-[90]
and S4 at [91]-[93]. The commits are pushed and are not rewritten; this report
is the record.

**Verification and gate:**

- **Verifier A** ([94]) ran on the uncommitted state at `54b3c3d`.
  - Tests: 9,806 passed, 10 failed, 155 skipped. The 10 were the 9 export-guard
    cases waiting on `ci-E1-S1` and S1's pin waiting on `S1-pin-E1-S4`. Both
    patches are in the commits.
  - Coverage: 100.00 % on the seven source files the units touch. The total is
    99.64 %, and every miss is in `persistence/postgres.py`, whose Postgres
    cases skip without `TEST_DATABASE_URL`.
  - Gate: ruff, format and mypy clean.
- **Verifier A also reproduced:**
  - S1's offline bar: 4 of 5 X2-S runs outside, the 7 refit ratios, the
    stratified null;
  - S4's offline bar: base A/A byte-identical at hash seeds 7 and 14, and both
    memos `repetition_fit`, share 1.0, bench cut 6.27 %, distinct −1.41 % ([94]
    §2-§3).
- **FIXED untouched:** the blobs of `judges.py`, `anticheat.py` and
  `heldout.sha256` equal HEAD's ([94] §4).
- **Default requests byte-identical:** checked with each record setting alone
  and with all four together ([94] §5).
- **The lab gate on each committed state** passed every line: ruff, format,
  mypy, bandit, pytest on 3.13 and 3.11 plus timed, and prettier, at 100 %
  coverage on touched source. This is the Lead's run and is not a board entry.
- **Not proven offline** ([94] §6):
  - the ledger's measured half;
  - twin bar (ii), which cannot fail at n = 6 ([90]);
  - S4's `clear` label on a real diff;
  - the `raised` nit.

## 6. Dispatch plans, for approval

**Before any plan:** the `ideas-validate` smoke on the Window 2 key must show
that Sonnet 5 and Fable 5 are served and retention is allowed ([5]). It has not
run. Until it passes, no plan is costed against Window 2 ([5], [95]).

| Plan | Proposal        | Arm and libraries                  | Runs | Dispatches (need each)                     | Minutes a dispatch | Expected USD |
| ---- | --------------- | ---------------------------------- | ---- | ------------------------------------------ | ------------------ | ------------ |
| P1   | S1              | X2-0 twins: tomli x3, sqlparse x3  | 6    | 3 × `X2-0:tomli,sqlparse` (18.70)          | 178                | about 14.7   |
| P2   | S4 unit 1       | X2-SV: sqlparse, tomli, mistune x3 | 9    | 3 × `X2-SV:sqlparse,tomli,mistune` (28.05) | 285                | about 21.9   |
| P2a  | S4 unit 1, lean | X2-SV: sqlparse x3                 | 3    | 3 × `X2-SV:sqlparse` (9.35)                | 95                 | about 8.6    |

- **Sources.** Expected spend is [95]'s run-row means: tomli 2.02, sqlparse 2.87
  and mistune 2.41 USD per library-run. Minutes are 89 a run for X2-0 and 95 for
  X2-SV, with 360 for the job ([95]).
- **Dispatch counts and P1's need are the Lead's arithmetic.** `x2_plan` refuses
  a library twice in one dispatch, so "x3" means three dispatches ([95]), and
  P1's need is 2 × 9.35. [95] also calls P2a "one dispatch", which its own
  `x2_plan` finding rules out.
- **Totals:** P1 + P2 is about 36.6 of 120; P1 + P2a about 23.3.
- **The pyparsing variant.** [95]'s variant adds pyparsing twins to P1, as three
  `X2-0:tomli,sqlparse,pyparsing` dispatches (need 28.05, about 22.4 USD).
  pyparsing's twins only served S3-G and S5, both refuted, so the Lead does not
  recommend it.
- **One dispatch outstanding at a time.** A dispatch goes only when its need is
  covered ([5]).
- **The variance rule.** Both plans have at least 3 runs per library per arm,
  and P2 covers several libraries. Neither compares arms: P1 is the twin, and
  P2's runs are pool draws by request identity ([95]).

**Pre-registered bars:**

- **P1, S1, record-only (+5).**
  - Bar: rank, k and rate printed on 100 % of read runs, and the twin sign test
    two-sided p > 0.05.
  - The bar cannot fail at n = 6: 6 of 6 against a 2-draw pool reads 0.32
    ([90]). The content is the kill.
  - Kill: all three tomli twins at 6 kept within 3.94 points of 22.58 with the
    rank row the only addition, or `seconds_measured` over `minutes_planned`.
  - The +5 counts only if the kill does not fire ([94]).
- **P2 / P2a, S4 unit 1, record-only (+5).**
  - Bar: a reading on at least 90 % of in-scope keeps and near misses; base A/A
    exactly 0 in every run; the sqlparse lexer-memo family reads
    `repetition_fit`, else "not tested (0)".
  - Kill: any A/A count difference, or a memo-family row reading `clear`.
  - The +5 counts only if the memo-family leg is read ([86] (a), [94]).
  - Only sqlparse carries that leg. tomli and mistune buy coverage rows and pool
    draws, about 13.3 USD ([95]).
- **No gain-bearing plan exists.** S3-G and S5 were refuted, and S2, S3 and S5
  have no arm to dispatch ([95]).

**If the Window 2 smoke fails**, Window 1's 21.08 USD covers one P1 dispatch
(need 18.70), and then not the next. It covers all three P2a dispatches: about
21.08 → 18.2 → 15.3 → 12.5, each above the 9.35 need. This is the Lead's
arithmetic from [2] §8 and [95]'s sqlparse mean of 2.87.

## 7. The engine measures before the live run

From Verifier B ([95] §2), over the ten archives (327 hypothesis rows, 25 runs,
100 keeps).

| #   | Measure                                        | Value now                                                                                                                     |
| --- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 1   | Ideas with a named cost model (share)          | not measurable: no row carries a cost-model field; the lane-written field (S2's `IDEAS_BOUNDS=on`) is not built               |
| 2   | Share of the physical gap closed by kept ideas | not measurable: no floor per hotspot. S1's proxy `moved` exists on 15 of 22 X2-S keeps, median 0.333                          |
| 3   | Wins per run and size against the floor        | 4.00 a run (X2-0 4.38, X2-0' 4.00, X2-V 3.38, X2-S 4.40); gain/floor median 2.64x, 65 of 100 at 2x or more                    |
| 4   | Compounding curve                              | round 1 → round 2 kept: X2-0 19 → 16, X2-0' 11 → 5, X2-V 18 → 9, X2-S 13 → 9; compounds 8 tried, 6 kept. No inter-round point |
| 5   | Idea → working-diff hit rate                   | on S1's labels: fired 36 of 73 (49.3 %); idea → kept 100 / 327 = 30.6 %; 42 trials identical to base, 1 kept                  |
| 6   | Cost per win                                   | 59.10 / 100 = 0.591 USD (X2-0 0.519, X2-0' 0.586, X2-S 0.559, X2-V 0.713); 0.143 USD per delivered combine point              |
| 7   | Marker misses                                  | not measurable: the X2 arms trial the whole pool; X1's 1 (S20, rank 5) is the only reading                                    |
| 8   | Twin gap on combine (path dependence)          | pyparsing 2.70 / 0, sortedcontainers 3.22 / 0, sqlparse 18.69 / 2, tomli 3.94 / 0; mean 7.14; X2-S sqlparse 9.60 / 8          |

- **Readable now:** measures 3, 5, 6 and 8. Measures 1, 2 and 7 stay "not
  measurable", and measure 4 has no inter-round point until a round-2 engine run
  exists ([95] §4).
- **Pool depth:** k is 2 on four libraries and 1 on the other four. No library
  is near the k of 39 that a per-library rank call needs ([95] §2.8).

## 8. What the society found that one session would not have

**On measurement, the answer is real.**

- **The band.** The Contrarian named the belief every wave-1 bar shared, that
  one A/A pair is the band. It showed from rows already on disk that a third
  request-identical draw lands outside the kept band on 4 of 4 libraries ([22]).
- **The critics corrected the Contrarian.** Its pooled range was no better: a
  range rule puts a no-effect draw outside with probability 2/(n+1) ([45],
  [49]).
- **A judge corrected the corrected version.** One shared pool median correlates
  the signs, so 7 of 8 reads 0.086, not 0.035 ([86]). A reviewer then caught
  that the test's sidedness was not pre-registered ([89]).
- **Four layers.** Each layer fixed a statistical error the layer before had
  made. Round 1's own bars all read against the one-pair band (round-1.md §6).
- **The interpreter question.** INT-1 overturned round 1's own carried guess
  about the 64 % uncounted keeps. They are a unit-selection miss, not C-level
  blindness ([3]; `library/interpreter-specialist.md`).
- **The capture shim.** A reviewer found the gap that an `lru_cache` on the
  capture point would have opened ([92]).

**On yield, the answer is thin.**

- Both builds are record-only instruments.
- The only gain-bearing proposals (S3-G, S5) were refuted 3 of 3.
- The synthesiser said plainly that most survivors were the same reading on the
  same launch, aimed at the same runs ([84]).
- The round improves how the engine is read, not what it delivers.

## 9. Points (O55 as amended by O58)

**Rules applied, from the charter:**

- **Halving:** points halve each round. The previous balance is the post-O58
  total (round-1.md §12), halved as in [2] §9.
- **Survival and build:** +1 for surviving the judges and +3 for built, reviewed
  and gated. Each is split equally across the merged proposals, as in round 1
  (round-1.md §9).
  - S1: 4 points over CON-1, CON-2 and CON-3, all the Contrarian's.
  - S4: 4 points over SCL-X, SCL-1, VER-1, VER-2, VER-3 and MEM-1, 0.667 each.
- **Critiques:** +2 per withdrawal, or per debate merge into a proposal the
  judges kept, split between the critics the author credited:
  - EXP-1 withdrawn [56]: [35] Interpreter specialist, [52] Pre-mortem;
  - SCL-2 withdrawn [63]: [39] Expert prior, [44] Analogy transfer;
  - MEM-2 withdrawn [83]: [48] Analogy transfer, [51] Contrarian;
  - ANA-4 withdrawn [54]: [43] Inversion, [53] Pre-mortem;
  - INV-4 withdrawn [55]: [37] Expert prior, [46] Bounds first;
  - SCL-1 merged into SCL-X [62], kept in S4: [39] Expert prior, [44] Analogy
    transfer.
- **Live passes:** none this round, so no +5 or +10.
- **Penalties:** no −3. No number was called fabricated (§4), and nothing
  touched FIXED ([94] §4).
- **Judges** earn nothing.

| Seat                         | After E1/E2 (O58) | Halved | S1 / S4 | Critiques | Round-2 award | New total |
| ---------------------------- | ----------------: | -----: | ------: | --------: | ------------: | --------: |
| Expert prior                 |              5.75 |  2.875 |       0 |       3.0 |           3.0 |     5.875 |
| Pre-mortem                   |               7.5 |   3.75 |       0 |       2.0 |           2.0 |      5.75 |
| Contrarian (new)             |                 0 |      0 |     4.0 |       1.0 |           5.0 |       5.0 |
| Analogy transfer             |              3.55 |  1.775 |       0 |       3.0 |           3.0 |     4.775 |
| Bounds first                 |               7.5 |   3.75 |       0 |       1.0 |           1.0 |      4.75 |
| Inversion                    |              5.55 |  2.775 |       0 |       1.0 |           1.0 |     3.775 |
| Verifier-designer (new)      |                 0 |      0 |     2.0 |         0 |           2.0 |       2.0 |
| Ten-x (bench)                |               2.8 |    1.4 |       - |         - |             0 |       1.4 |
| Shape specialisation (bench) |              2.75 |  1.375 |       - |         - |             0 |     1.375 |
| Scaling (new)                |                 0 |      0 |   1.333 |         0 |         1.333 |     1.333 |
| Contradiction (bench)        |               2.6 |    1.3 |       - |         - |             0 |       1.3 |
| Interpreter specialist (new) |                 0 |      0 |       0 |       1.0 |           1.0 |       1.0 |
| Memory & allocation (new)    |                 0 |      0 |   0.667 |         0 |         0.667 |     0.667 |

These are the Lead's computation, for the owner to confirm.

**What the points imply for round 3, by the rule:**

- **Top two and the Fable budget:** Expert prior and Pre-mortem.
- **Top scorer:** Expert prior. Its library file becomes required reading.
- **Rotation:** the bottom three seated are Memory & allocation, Interpreter
  specialist and Scaling. They rotate out against the bench's first three:
  Ten-x, Shape specialisation and Contradiction. The seats are the owner's to
  confirm, as in round 1 (round-1.md §12).

**Rules the Lead found ambiguous; not guessed, flagged for the owner:**

1. **Partial withdrawals.** These would change the ranking if they count; they
   are not counted above.
   - CON-3's headline and its `KEEP_STOP`/`LESSON_GAIN_WEIGHT` parts, after [45]
     and [49] ([78]).
   - PRM-5's park, after [40] ([74]).
   - INT-2's predictor, after [36] and [47] ([67]).
   - ANA-5's part B, after [43] ([57]).
   - If they count: Inversion +3 (6.775), the Contrarian +1 (6.0),
     Verifier-designer +3 (5.0) and Scaling +1 (2.333). The top two would then
     be Inversion and the Contrarian; the bottom three would not change.
2. **Partly built proposals.** S4 is 1 of 4-5 units. The table splits its +3
   equally, as round 1 did for its partly built S1. Giving the +3 to VER-1 alone
   instead gives Verifier-designer 3.5, Scaling 0.333 and Memory & allocation
   0.167. The bottom three and the top two do not change.
3. **Synthesis merges.** Merges made at synthesis, not declared in debate, earn
   no critic +2 here, following round 1's practice. An example is MEM-1 and
   VER-1 sharing one launch after [38] and [50].
4. **Credited carry-forwards.** VER-1 and VER-2 take up SHP-3 (Shape
   specialisation, benched), credited ([9], [12]). The charter gives no points
   for that, so none are given.
5. **Proposed FIXED changes.** S3's legs would need a FIXED change. Its
   proposers flagged this themselves and nothing was built ([64], [82]). By
   r1[47]'s precedent ("an observation is not a FIXED touch"), no −3 is given.
6. **The halving's timing.** The halving is applied to the post-O58 totals,
   which include S1's +10 from E1/E2, as [2] §9 computed. If O58's +10 was meant
   to escape this halving, Bounds first and Pre-mortem would be 1.25 higher, and
   Expert prior, Inversion, Analogy transfer and Shape specialisation 0.625
   higher. The top two would then be Pre-mortem (7.0) and Expert prior (6.5),
   and the bottom three would not change.

## 10. Three proposals for round 3

1. **S2 rebuilt to the judges' notes** (INT-1, INT-3, BND-3/4/X).
   - It is the only proposal that closes the 15.1 % uncounted hole and can make
     measure 2 readable. The correctness judge passed it ([87]).
   - It needs:
     - `label` kept as today, with a new `label_v2` ([87]);
     - the bar set on anchored trials, 0 of n ([85]);
     - (b2) scored without the `token_next_by` family ([86]);
     - the 13-floor calibration (about 2 USD) as a gate on printing measure 2
       ([85], [86]).
2. **S4's remaining units on X2-SV.** These are SCL-X with SCL-1, MEM-1 and
   VER-3, then VER-2 once r1[62]'s extension is ruled.
   - S4 is the board's main anti-reward-hacking instrument and survived 2 of 3
     ([86], [87]).
   - Restate its effect as record coverage, and add idna x3 for the two
     predicted memo keeps ([85]).
3. **S5 as a combine bar** (carry-forward 1, a third time).
   - It is the only yield-raising mechanism on the board ([84]), and compounding
     with less path dependence is still the owner's question (round-1.md §10).
   - It needs sqlparse x5 against x5 twins ([85], [86]), the two-trial
     row-writer fixture and the closure-rule fixture ([87]).
   - Retire it if those notes cannot be met.

**Not proposed:** the defensive scanner. The owner parked it (O57) until after
K2, with a scope spec and a security review required first
(`library/expert-prior.md`).

## 11. Open questions for the owner

1. **Window 2's key.** What is the secret's name in the `live` environment, and
   does it replace `ANTHROPIC_API_KEY` or sit beside it?
2. **The smoke.** May the full `ideas-validate` suite run as the Window 2 smoke?
   - Its cap need is 8 USD (`STATUS.md`, V suite wave A).
   - The last run cost 1.27 USD in 6.9 minutes (`STATUS.md` ledger, 2026-11-03,
     run 41642625225).
   - Beyond the Sonnet 5 and Fable 5 smokes, it also sends 17 Opus 5
     dedupe-label requests.
3. **Window 2's expiry.** It is not on the board. Window 1's credit expires
   2026-11-25 (`STATUS.md`).
4. **The live plans.** Approve P1, and P2 or P2a (§6), in that order, one
   dispatch outstanding at a time.
5. **S1's pool ruling.**
   - Adopt the rank row and the stratified sign test beside O51 and O52, keep
     them printed only, or drop them.
   - Confirm the pool X2-0, X2-0', X2-C, X2-SV. [86] warned that a record arm
     joins on request identity, which does not test live timing with riders.
     X2-SV adds about 5.6 minutes a run ([92]).
6. **VER-2's suite corpus.** Running a library's own suite as an off-shape
   corpus reads its tests without changing them. That extends r1[62] from the
   benchmark's inputs to the suite's ([86] (c), [87] (b)). It needs a ruling
   before it is built.
7. **S3's two legs** need a FIXED change: the flagged delivery through
   `_rule_6`, and `PROCESS_STATE=on`. They are reported, not built ([85]-[87]).
   The correctness judge's route is an owner ruling that such a keep may be
   withheld at `plan_delivery` in `combine_node.py` and listed for review
   ([87]).
8. **The points.** Confirm §9, the six flagged rules and round 3's seats.

## 12. Live plans, awaiting approval

Nothing was dispatched in round 2. Window 1's balance is 21.08 USD, untouched
([2] §8). In order:

1. **The Window 2 smoke.** It waits on questions 1 and 2. Nothing is costed
   against Window 2 before it passes ([5]).
2. **P1, S1's X2-0 twins.** X2-0 is in `EVERY_ARM`, and `IDEAS_VIEW_RECORD`'s
   export is in `818a05e`. It is dispatchable after the smoke and the owner's
   approval.
3. **P2 or P2a, X2-SV.** The arm and its `ci.yml` case are in `775890d`. It is
   dispatchable after P1, or alone, on approval.
4. **After each dispatch:**
   - O46's three conditions are checked, as in round 1;
   - its readings go into round 3's facts card;
   - points move under O58 only on a pass that meets the conditions in §6.
