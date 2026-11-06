# Emergence round 1: report

Round 1 ran under the charter (O54), with V9 sealed (O53) and the society rules
(O55) applied from round 2. The board is `round-1/board.md`, entries [1] to
[122].

- **Branch:** `claude/step3-emergence-r1`, off `claude/step3-idea-lab` at
  `3814bf5`.
- **The round's two builds:** `553491f` (S1) and `c71c030` (S2).
- **Live spend in the round:** 0 USD. Nothing was dispatched.

## 1. How the round ran

| Phase                 | Agents                                        | Board        | Models                                                                        |
| --------------------- | --------------------------------------------- | ------------ | ----------------------------------------------------------------------------- |
| 0 Facts               | 1                                             | [39]         | session model                                                                 |
| 1 Proposals           | 8, all at once                                | [40]-[57]    | Expert prior, Contradiction and Pre-mortem on Fable 5.1; the rest on Opus 5.5 |
| 1b Cross-pollination  | 8, all at once                                | [58]-[67]    | as Phase 1                                                                    |
| 2 Debate, round 1     | 8, all at once, each critiquing 2 agents      | [68]-[85]    | as Phase 1                                                                    |
| 2 Debate, round 2     | 8, all at once, keep, revise, withdraw, merge | [86]-[110]   | as Phase 1                                                                    |
| 3 Synthesis           | 1                                             | [111]        | Sonnet 5.5, which no proposer used                                            |
| 4 Judging             | 3                                             | [112]-[114]  | evidence and reward hacking on Opus 5.5, correctness risk on Fable 5.1        |
| 5 Build, review, fix  | 2 builders, 2 reviewers                       | [115]-[120]  | builders on Opus 5.5, reviewers on Fable 5.1                                  |
| 6 Verification        | 1                                             | [121]        | Fable 5.1                                                                     |

**Lead entries:**

- [36]-[38]: the charter, path dependence and corrections.
- [47] and [62]: an observation is not a FIXED touch. The owner upheld [47].
- [55]: the owner's rulings on the superseded entries.
- [72]: O28 routing.
- [105]: the markdown prefilter fact.

**Process notes:**

- **Why the agents ran outside the workflow for phases 1 and 2.** The
  workflow runner caps concurrency at CPUs minus 2, which is 2 in this
  container. So phases 1-2 ran as parallel background agents from the
  owner-approved briefs, rendered word for word from the round script. Phases
  3-6 ran as a workflow.
- **The verifier stopped early.** It returned before its own pytest chain
  finished, so the Lead completed its entry [121]. The missing full-suite
  lines come from the Lead's lab gate below.

## 2. The facts card ([39])

Numbers only, with sources: STATUS, spec §6-§9, the X1 report, the X2 report on
d1-d6, and the picks run.

- **Where X1's 9 slice wins came from:**
  - leap 5, all on Opus 5.5 (the largest sqlparse 14.57 / 6.16 %);
  - S1 2;
  - lens 2.
- **X1's levers:** only X1-1 is beyond the A/A spread (non-obvious +0.75,
  cost +2.05), and X1-4 is beyond it negatively. Cost was 62.14 USD.
- **Round seeds:** they never fired in X1 (O50). In X2 they fired in every
  run.
- **The marker's miss:** S20 (rank 5, kept 3.67 / 2.00).
- **The dedupe failure:** O39.
- **S13:** calls −7.7 %, time +5.8 %.
- **The twin band per library:** pyparsing 2.7 points / 0 kept, tomli 3.9 / 0,
  sortedcontainers 3.2 / 0, sqlparse 18.7 / 2.
- **The realisation hit rate:** 59 kept of 202 trialled in X2 d1-d6. A further
  33 trials had an op count identical to base, and 1 of those was kept.

## 3. Every proposal and its fate

| Seat                 | Proposal                                | Fate in debate                                    | Synthesis         | Judges (E / C / R) | Built      |
| -------------------- | --------------------------------------- | ------------------------------------------------- | ----------------- | ------------------ | ---------- |
| Bounds first         | BND-1 floor card [49]                   | merged into BND-X [89]                            | S1                | 7 / 6 / 6, survives | yes, part  |
| Bounds first         | BND-2 gap ledger [50]                   | merged into PRM-2, acting parts withdrawn [90]    | dropped           | -                  | no         |
| Bounds first         | BND-X count contract [67]               | revised [95]                                      | S1 (host)         | survives           | yes, part  |
| Expert prior         | EXP-1 shared inputs [51]                | revised into a `dispatch` view [102]              | S3                | 3 / 4 / 3, refuted | no         |
| Expert prior         | EXP-2 record view [54]                  | withdrawn [103]                                   | dropped           | -                  | no         |
| Expert prior         | EXP-3 footprint [63]                    | merged into PRM-3 [104]                           | S1                | survives           | yes        |
| Inversion            | INV-1 invert lens [40]                  | merged into BND-X [96]                            | S1                | survives           | no (field) |
| Inversion            | INV-2 pessimisation probe [41]          | withdrawn after its own probes [107]              | dropped           | -                  | no         |
| Inversion            | INV-3 combine conflicts [58]            | merged into TNX-3 [106]                           | S2                | 5 / 6 / 6, survives | yes        |
| Contradiction        | TRZ-1 contradiction lanes [42]          | revised [87]                                      | dropped (capped)  | -                  | no         |
| Contradiction        | TRZ-2 rejects re-enter [43]             | part 1 merged, parts 2-3 withdrawn [93]           | S2 (part 1)       | survives           | yes        |
| Contradiction        | TRZ-3 reconcile [64]                    | withdrawn [65], merged into TNX-3 [97]            | S2                | survives           | record only |
| Analogy transfer     | ANA-1 structure atlas [52]              | revised [91]; markdown bet killed by [105]        | dropped (capped)  | -                  | no         |
| Analogy transfer     | ANA-2 transfer ledger [53]              | merged into ANA-1 [94]                            | dropped           | -                  | no         |
| Analogy transfer     | ANA-3 realisation path [61]             | B to S1, C to S2, A withdrawn [101]               | S1 and S2         | survives           | B and C    |
| Shape specialisation | SHP-1 shape probe [44]                  | revised [108]                                     | S4                | 4 / 6 / 4, refuted | no         |
| Shape specialisation | SHP-2 coverage checks [45]              | merged into BND-X [109]                           | S1                | survives           | yes (shim) |
| Shape specialisation | SHP-3 off-shape check [60]              | revised [110]                                     | S4                | refuted            | no         |
| Ten-x                | TNX-1 chains [46]                       | merged into TNX-2 [86]                            | S5                | 2 / 3 / 2, refuted | no         |
| Ten-x                | TNX-2 finish the transformation [48]    | revised into "the stacked step" [88]              | S5                | refuted            | no         |
| Ten-x                | TNX-3 site stacks [59]                  | revised into the combine unit [92]                | S2 (host)         | survives           | yes        |
| Pre-mortem           | PRM-1 per-call budget [56]              | revised [98]                                      | S1 (price list)   | survives           | no         |
| Pre-mortem           | PRM-2 dead anchors [57]                 | revised [99]                                      | dropped           | -                  | no         |
| Pre-mortem           | PRM-3 realisation record [66]           | revised [100], host of the record                 | S1                | survives           | yes        |

**The judges' reasons for the three refuted proposals** ([112]-[114], with the
mentoring notes in the seats' library files):

- **S3, the dispatch view.**
  - Its size claim rests on 2 archived instances, both leap lanes that never
    saw the fact.
  - Its auditor rule can zero the lane on its first live run, with no shadow
    stage.
  - Its skip is sound only on the generator's input.
- **S4, the shape shim.**
  - It is one post-hoc mistune pair.
  - Observe mode feeds the benchmark's input shape into the lane view (the
    shape-tuning channel of [47]).
  - The off-shape counter-check is shadow only.
- **S5, the stacked step.**
  - It expects about 0.25 qualifying keeps a run.
  - "A step supersedes its parent in combine" is false today: a step and its
    parent conflict (`combine.py:207-212`).
  - It reads a single tomli run as a gain.

**Repetition, said plainly** (synthesis [111], and the Lead from the board):

- The combine-conflict mechanism was found four times, independently and
  within minutes: INV-3, TNX-3, ANA-3 C and TRZ-3.
- The realisation record and count shim were found five times: EXP-3, PRM-3,
  ANA-3 B, BND-X and SHP-2.
- After revision, most entries cite "the shared shim" and "one cost_model".
  So S1 rests on agreement as much as on new independent evidence.
- No fabricated number was found.

## 4. The superseded first Phase 1 ([3]-[34]), one line each

Under [55] these carry no points. A ✓ marks a round-1 proposal that found the
same mechanism again, independently.

| Proposal  | What it proposed                                                         | Found again by                        |
| --------- | ------------------------------------------------------------------------ | ------------------------------------- |
| ALGO-1    | cost-shape facts in every lane's view                                    | ✓ BND-1, BND-X (floor and count facts) |
| ALGO-2    | a required, engine-checked cost model on every idea                      | ✓ BND-1, INV-1, EXP-1 (`cost_model`)   |
| ALGO-3    | realisation check: did the trial remove the named cost term?             | ✓ PRM-3, EXP-3, BND-X, ANA-3 B (S1)    |
| COMP-1    | near-miss compounds that can fire: hunk-level disjointness               | partly: TNX-3 and S2's hunk identity  |
| COMP-2    | record why the combine drops a keep, then re-port conflicting keeps      | ✓ INV-3, TNX-3, TRZ-3, ANA-3 C (S2)    |
| COMP-3    | seeds that breed and stack; the round's keeps as a fence                 | partly: PRM-2's fence, BND-2          |
| REPR-1    | the judged-interpreter price card                                        | ✓ PRM-1's price list on 3.11           |
| REPR-2    | argument shape from the run (a bounded `setprofile` pass)                | ✓ SHP-1                                |
| REPR-3    | realisation check: the target's self time before and after               | ✓ S1                                   |
| TOOL-1    | the call graph and C callees cProfile already collects                   | ✓ SHP-2 and BND-X caller edges (S1)    |
| TOOL-2    | per-line time from a low-overhead sampler                                | none                                  |
| SKEP-1    | keep the diffs; a held-out readout on a second seed and a shifted input  | ✓ SHP-3 (off-shape)                    |
| SKEP-2    | declare the domain: `holds_when` and an off-domain cost                  | ✓ SHP-1's precondition                 |
| SKEP-3    | a lab-side scaling leg with its own A/A band                             | partly: SHP-2 part 2, withdrawn       |
| REAL-1    | a second look for near misses                                            | partly: BND-X's gated re-entry        |
| REAL-2    | stacked rounds: round 2 judged against round 1's held combine            | ✓ TNX-1 and TNX-2 (S5)                 |
| REAL-3    | hand the editor the grounded quote and record whether the diff landed    | ✓ PRM-3 part 1, EXP-3 unit 2           |

12 of the 17 were found again in full by round 1, with no access to the
superseded text. The two builds sit on the two mechanisms both rounds found
first: ALGO-3/REPR-3 became S1 and COMP-2 became S2.

## 5. The two builds

**S1: count units and a realisation record per trial (`553491f`).**

- **The mechanism:**
  - It runs behind `IDEAS_COUNT_CONTRACT=off|record`, default off.
  - Shim version 2 counts up to 4 named units with their caller edges.
  - Unit counts go to their own `unit_calls` rows, never `op_calls`.
  - Each trial gets a realisation record: files, hunks, AST functions touched,
    `anchor_touched`, and counted work at base and trial.
  - Each trial also gets a label: fired, weak, not_fired, reversed or
    uncounted, plus kept_not_fired.
  - X2 harness arm X2-C.
- **Not built:** the lane-written count contract (so measure 1 is still
  unmeasured), the park and the re-entry.
- **Tests:**
  - `tests/execution/test_opcount_units.py` (13);
  - `tests/optimization/test_realisation.py` (9);
  - `tests/live/test_ideas_x2_count.py` (7);
  - 4 new tests in `tests/execution/test_trial_runner_opcount.py`.
  - +1541/−42 over 12 files; engine source +375/−31.
- **Review** (Fable [116]):
  - should_fix: hunk ranges counted context lines. Fixed [117]; all 20 DC
    patches now match [104] exactly.
  - nit: parser errors. Fixed.
  - 2 report-wording nits, left.
- **Offline gate (a)**, reproduced by the verifier at the pins on python3.11:
  - `re.Pattern.match` from `get_tokens`: 1,759,677;
  - mistune `build_closing_bracket_map`: 4,031;
  - tomli `parse_array`: 6,400;
  - DC: examboard 8, tripsheet 9, booklist 3, stockbook 2, the rest 1-2.
  - Version 1 equals version 2 only under the sandbox's forced hash seed.
- **Lab gate on S1 alone** (`3814bf5` plus S1): ruff, format, mypy, bandit,
  pytest313 and pytest313timed, pytest311 and pytest311timed, prettier, all
  PASS; total coverage 100.00 %.

**S2: record and deliver the combine by confirmed gain (`c71c030`).**

- **The mechanism:**
  - It runs behind `SITE_STACKS=off|record|on`, default off.
  - A dry pairwise merge-tree runs after confirm, on git objects only.
  - Every keep records `delivered`, `skip_reason`, `blocked_by` and
    `duplicate_of` (by hunk identity).
  - With on, keeps are ordered by confirmed gain, and each conflict component
    delivers its largest-sum conflict-free subset (exact up to 9 keeps).
  - The tip is still re-tested by the frozen judges.
  - Part 3 records reconcile eligibility and trials none.
  - X2 harness arm X2-S.
- **Tests:**
  - `tests/optimization/test_combine_identity.py` (6);
  - `tests/execution/test_combine_dry_merge.py` (4);
  - `tests/orchestrator/test_combine_order.py` (9);
  - `tests/live/test_ideas_x2_stacks.py` (6).
  - +1308/−14 over 12 files.
- **Review** (Fable [119]):
  - should_fix: the duplicate-never-reconciled bar had no test. Fixed [120];
    the verifier reran the mutation and got 1 failed, as it should.
  - nit, left: `hunk_signature` ignores indentation.
- **Lab gate on S2 over S1** (`553491f` plus S2): ruff, format, mypy, bandit,
  pytest313 and pytest313timed, pytest311 and pytest311timed, prettier, all
  PASS; total coverage 100.00 %.

**Both units:**

- off by default;
- no request byte changes;
- no FIXED path touched (the verifier checked `git status` on the judges,
  anticheat, benchmarks, library tests and sealed sets);
- `heldout.sha256` is unchanged since `f8bfb94`.

## 6. Dispatch plan, for approval

Both builds are measured by one arm, **X2-S**. It is X2-0's settings plus
`IDEAS_COUNT_CONTRACT=record` (S1) and `SITE_STACKS=on` (S2).

- **Prerequisite:** the Lead's `ci.yml` patches `ci-E1-S1` and `ci-E1-S2`,
  each one case of the dispatch switch plus one guard row. They are gated and
  committed before the dispatch.

| Dispatch | `x2_dispatch`                    | Runs | Need (9.35 / run) | Cap | Expected spend (X2-0's measured rates) |
| -------- | -------------------------------- | ---- | ----------------- | --- | -------------------------------------- |
| E1       | `X2-S:sqlparse,tomli,mistune`    | 3    | 28.05             | 29  | about 7.5                              |
| E2       | `X2-S:sqlparse,more_itertools`   | 2    | 18.70             | 19  | about 4.7                              |

- **The balance:** 33.37 USD (O56: reserved for these plans). E1's need is at
  or below the balance. After E1 the balance is about 25.9, which still covers
  E2's 19. If it is not, E2 waits; no cap is lowered below its need.
- **Expected total:** about 12.2 USD, leaving about 21.2.
- **Time:** 3 runs × 89 minutes = 267 of the suite's 360 (`ci.yml:693`).
- **Between dispatches:** O46's three conditions, as for X2.

**Pre-registered bars**, read per library against its own twin gap (tomli 3.9
points / 0 kept, sqlparse 18.7 / 2; mistune and more_itertools about 4
points / 1 kept, no twin), with O52's arm-level call:

- **S1, records only (no gain is claimed):**
  - every trial row carries a realisation record;
  - the share of non-S1 ideas with a counted anchor is read and reported,
    with no pass mark (it is a measurement);
  - fired ideas keep at at least twice the not_fired rate with at least 10 on
    each side, else "not tested";
  - no library falls below X2-0 by more than its band.
- **S2, record plus correctness:**
  - 100 % of undelivered keeps carry a reason;
  - 100 % of conflict components deliver their max-sum subset;
  - no library below X2-0 by more than its band;
  - reconcile reads "not tested", since no reconcile is trialled.
- **Path dependence (measure 8):** sqlparse runs twice, in E1 and E2. That is
  X2-S's own A/A pair. Its combine gap is read against X2-0's 18.7. With one
  pair it can say "consistent with" at most.
- **Kill:** any library below X2-0 by more than its band in both of its X2-S
  runs means the on path is withdrawn back to record.

## 7. The engine measures before the live run

Computed by the verifier's `measures.py` over X1 and X2 d1-d8:
`python3 -I measures.py x1/ x2/ideas-x2-d*.jsonl`. The full output is in
`scratchpad/emergence/measures-d1-d8.txt`.

| #   | Measure                                       | Value now                                                                                                              |
| --- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| 1   | Ideas with a named cost model (share)         | not measurable: no row carries a cost-model field, and S1's contract was not built                                     |
| 2   | Share of the physical gap closed by kept ideas | not measurable: no floor or ceiling on X2 rows. S1's counted gap is the proxy, readable after E1-E2                    |
| 3   | Wins per run and size against the floor       | 78 / 20 = 3.90 a run (X2-0 4.38, X2-0' 4.00, X2-V 3.38); gain/floor median 2.62x, 52 of 78 at 2x or more               |
| 4   | Compounding curve                             | round 1 → round 2 kept: X2-0 19 → 16, X2-0' 11 → 5, X2-V 18 → 9; compounds 5 tried, 3 kept. No inter-round point yet  |
| 5   | Idea → working-diff hit rate                  | not measurable: no diff in any row. Idea → kept: S1 41/122, lens 26/110, leap 8/17, compound 3/5. 33 trials identical to base |
| 6   | Cost per win                                  | 46.81 / 78 = 0.60 USD (X2-0 0.52, X2-0' 0.59, X2-V 0.71); 22 of 78 keeps not delivered                                 |
| 7   | Marker misses                                 | 1 (S20, rank 5); not measurable on X2, which has no marker                                                             |
| 8   | Twin gap on combine (path dependence)         | pyparsing 2.70 / 0, tomli 3.94 / 0, sortedcontainers 3.22 / 0, sqlparse 18.69 / 2; mean 7.14                           |

## 8. What the society found that one session would not have

**Measured against my earlier session.** The Lead's own X2 work had treated
the sqlparse twin gap as noise to band around, and had read X2's cost and
wins arm against arm.

**What the society did differently.** Eight frameworks, each with a different
evidence pack, converged within minutes on two engine defects that no row
records:

- the combine resolves same-site keeps by pre-trial score, not measured gain,
  and silently drops 22 of 78 keeps;
- nothing says whether an edit actually did what its idea claimed.

That convergence is what made S1 and S2 the builds.

**The debate also corrected the round's own grounding more than once:**

- Re-measuring on the judged interpreter turned van Herk from "34 % faster"
  (3.13) to "72 % slower" (3.11). That matches X2's three rejects.
- A critic showed the sqlparse twin gap forms in round 1 and at combine, not
  in round 2. That withdrew BND-2's reordering.
- The Lead found that ANA-1's best new structure was the harness's own aimed
  hypothesis, already kept at +13.64 %.

One session would have built the first plausible lever. The society built the
two instruments that every other proposal needed.

## 9. Points (O55), seeded from round 1's verified outcomes

**Rules applied:**

- +1 for surviving the judges and +3 for built, reviewed and gated: S1 and S2
  score 4 each, split equally across their merged proposals.
- +2 per withdrawal, or per merge the judges kept, split between the critics
  whose critiques led to it.
- No −3: synthesis found no fabricated number, and nothing touched FIXED.

These are the Lead's computation, for the owner to confirm.

| Seat                 | From S1/S2 | From critiques | Total |
| -------------------- | ---------- | -------------- | ----- |
| Bounds first         | 1.0        | 4.0            | 5.0   |
| Pre-mortem           | 1.0        | 4.0            | 5.0   |
| Expert prior         | 0.5        | 4.0            | 4.5   |
| Inversion            | 1.3        | 3.0            | 4.3   |
| Ten-x                | 0.8        | 2.0            | 2.8   |
| Contradiction        | 1.6        | 1.0            | 2.6   |
| Analogy transfer     | 1.3        | 1.0            | 2.3   |
| Shape specialisation | 0.5        | 1.0            | 1.5   |

**What the points imply for round 2:**

- **Rotation:** the bottom three (Contradiction, Analogy transfer, Shape
  specialisation) rotate out against the bench's first three (Memory &
  allocation, Verifier-designer, Interpreter specialist).
- **The Fable budget:** the top two are Bounds first and Pre-mortem.
- **Tie:** Bounds first and Pre-mortem tie for top scorer, so both library
  files are required reading unless the owner picks one.

**Library files:** `emergence/library/<seat>.md` (8 seats) and
`library/round-0.md` (the superseded proposals, for the Contrarian's pack).

## 10. Three proposals to carry into round 2

1. **S5, the stacked step, rebuilt on S2.** This is the owner's question:
   compounding with less path dependence. It failed because a step and its
   parent conflict in combine.
   - S2's records now name every conflict and its blocker, so "a step
     supersedes its parent" can be built as an S2 rule.
   - S1's unit counts can gate which keeps qualify, which answers [112].
   - Pre-register it against X2-S's own A/A, not one tomli run.
2. **S1's acting parts.** The lane-written count contract (measure 1) and the
   gated re-entry. Both need E1-E2's realisation labels first, to show whether
   not_fired keeps exist in the numbers PRM-3 and BND-X predicted.
3. **SHP-3's off-shape check, without observe mode.** The charter's state-of-
   the-art claim needs a defence against shape-fit keeps before K3. The
   judges refuted S4 for feeding the benchmark's shape to lanes, not for the
   perturbation check. Round 2 should take the judge-side half alone: shadow,
   with [72]'s routing.

**The open question no proposal took up.** Round 1 trials the whole pool, so
the sqlparse gap that forms in round 1 comes from what ideation produced, not
from which ideas were selected. Variance in ideation is the unaddressed source
of path dependence. It is the natural question for round 2's Contrarian.

## 11. Open questions for the owner

1. **Approve E1 and E2.** The plan is in §6, with caps of 29 and 19 against a
   balance of 33.37.
2. **SHP-3's hold mode** (a shadow reading deciding delivery as a flagged
   proposal) is withdrawn this round. It needs a ruling beyond [62] if it
   returns.
3. **EXP-2's author offered a defensive-only scanner** under [72]. Under O28 a
   human owns disclosure, so whether to build one is the owner's decision. The
   Lead did not commission it.
4. **The points** in §9, and the top-scorer tie.
5. **Merging the lab branch into the emergence branch.** The lab branch now
   carries the X2 archives d7-d8, V-x2band, V-x2rep4 and O53-O56. Merging it
   needs one conflict resolution in `ideas_x2_report.py`: S1 and S2 add report
   sections 6 and 7, and V-x2rep4 adds section 6. The Lead will do it
   (renumbered, then gated) before the dispatch, unless the owner prefers to
   keep the branches apart.

## 12. The live runs (E1, E2) and what they show

**The dispatches:**

- **E1:** [run 42264126014](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/42264126014), `X2-S:sqlparse,tomli,mistune`, 7.61 USD.
  - The first attempt, [run 42232651527](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/42232651527), ran no case and cost 0 USD. The harness bug behind it was fixed in `5b09306`, and `4da4402` now turns such a run red.
- **E2:** [run 42272888210](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/42272888210), `X2-S:sqlparse,more_itertools`, 4.68 USD.
- **Total:** 12.29 USD. The balance is now 21.08.
- **O46's three conditions held on both:**
  - every case ran;
  - every hypothesis was judged, with no `max_tokens` stop and no refusal;
  - each part's cost was within X2-0's range.

**Per library, against X2-0.** Each library is read against its own twin gap (O51 amended), or the fixed band where it has no twin.

| Library        | X2-S kept, combine      | X2-0 kept, combine | Kept, reading                    | Combine (points), reading                   |
| -------------- | ----------------------- | ------------------ | -------------------------------- | ------------------------------------------- |
| tomli          | 4, +16.3 %              | 6, +22.6 %         | −2, outside its twin gap (0)     | −6.3, outside its twin gap (3.9)            |
| mistune        | 4, +18.1 %              | 6, +13.5 %         | −2, outside the fixed band       | +4.6, outside the fixed band (better)       |
| sqlparse (E1)  | 11, +28.3 %             | 9, +39.8 %         | +2, inside its twin gap (2)      | −11.5, inside its twin gap (18.7)           |
| sqlparse (E2)  | 3, +18.7 %              | 9, +39.8 %         | −6, outside its twin gap         | −21.1, outside its twin gap (18.7)          |
| more_itertools | 0, none (no combine)    | 2, +7.8 %          | −2, outside the fixed band       | −7.8, outside the fixed band                |

**O52's arm-level call**, X2-S against X2-0 over 4 libraries, with sqlparse as the mean of its two runs:

- **Kept count:** X2-S keeps fewer, on 4 of 4 libraries.
- **Combine:** the mean difference is −6.4 points against the twin's mean gap of 7.1, so it reads "within the twin's mean gap".

**X2-S's own A/A pair** (sqlparse, E1 against E2):

- combine gap 9.6 points, against X2-0's 18.7;
- kept gap 8, against X2-0's 2.

With one pair this is "consistent with" at most, and the two halves point opposite ways. The combine gap is smaller; the kept gap is much larger.

**The pre-registered bars:**

- **S1, records:**
  - every trial row carries a record: 73 of 73. **Pass.**
  - fired ideas keep at at least twice the not_fired rate, with at least 10 on each side: fired 12 of 36 kept (33 %), not_fired 0 of 11 (0 %). **Pass.**
- **S2, records:**
  - every undelivered keep names a reason and a blocker: 7 of 7. **Pass.**
  - every conflict component delivered its max-sum subset: all of them. **Pass.**
- **The no-harm bar, shared by the arm** (no library below X2-0 by more than its band): **fails** on tomli, more_itertools and sqlparse's E2 run.
- **The kill** (a library below X2-0 beyond its band in both of its X2-S runs, which applies only to sqlparse): **not triggered.** E1 sits inside the band and E2 outside.

**What can and cannot be attributed:**

- S1's `record` mode changes no request and no verdict. Its fields came back on every row, and it sends the same requests as X2-0.
- The harm is therefore S2's `on` delivery, or run-to-run variance in ideation, which is the path dependence the charter measures.
- One run per library cannot tell them apart. The record does show that S2 always delivered the max-sum conflict-free subset of the confirmed gains. Yet the delivered tips combined lower than X2-0's on 3 of 4 libraries.

**New facts for round 2:**

- **Measure 5, idea to working diff, is now readable.** Of 73 trials:
  - 36 fired (49 %);
  - 8 were weak, 11 not_fired and 7 reversed;
  - 11 were uncounted.
  - The uncounted trials kept at 64 % (7 of 11). Keeps cluster where S1's counts cannot see, which is probably C-level or module-level work. That is a gap in the shim.
- **Measure 8, path dependence:** X2-S's sqlparse twin gap is 9.6 points on combine and 8 on kept.

**Points (O57's recompute):**

- No proposal earns +10. Its live run had to beat its pre-registered bar, and the arm's no-harm bar failed.
- S1's own record and premise bars passed, and S1 is behaviour-neutral by construction. Whether that earns S1's merged proposals the +10 is the owner's call.
- Unless the owner rules otherwise, the points stand as in §9.

**The Lead's recommendation:**

- Keep `SITE_STACKS` at `record`, not `on`, until a matched X2-0 and X2-S pair on the same libraries separates S2's delivery from ideation variance.
- Keep `IDEAS_COUNT_CONTRACT=record`. It is free and it made measure 5 readable.
