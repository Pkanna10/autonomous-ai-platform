# Combine proposal (O61 addendum item 4), 2026-11-12

**Proposal only.** No judge or combine change is made during this reading. Both
items below change the combine or the loop, so each is the owner's call and
would be tested as its own arm against the pool, with the reading
pre-registered before any run. The record-only fate field (`U-fate`) is built
first, so that either arm's effect can be read from its rows.

Evidence: `zero-credit/README.md` (42 run x library rows of X2-0, X2-D, X2-P,
X2-F and X2-SV, replayed byte for byte) and the O61 runs in `o61/`.

## 1 Re-measure a combine whose floor is far above the baseline's

**What happens today.** The combined tip is judged once by the frozen judges
(ABAB, N >= 5, gain above the measured noise floor). The floor is the spread of
that measurement. When the re-test happens to run noisy, the floor rises and a
real gain can fail on noise alone.

**Evidence.**

- The combine floor was above the run's baseline floor in 12 of 42 rows, and at
  least twice it in 4: X2-D tomli 2.50, X2-D mistune 2.59, X2-P mistune 2.97,
  X2-P sqlparse 3.37 (`zero-credit/q3_floors.csv`).
- One combine failed in the sprint: the X2-D re-run on mistune (43145496896).
  It measured a gain of 8.54 % against a floor of 9.76 %, where the baseline
  floor was 3.76 %. The 9.76 is the fallback's single-change re-test, whose own
  trial floor was already 7.38 %. Under the same baseline spread, 8.54 % would
  have cleared the floor by a wide margin.
- One failure in 42 is rare, but each one costs the whole run: that run reads 0
  on the primary measure.

**Proposal.**

- **Trigger:** the combine's measured floor exceeds `k` x the baseline's
  calibrated floor. Proposed k = 2; it fired in 4 of 42 rows.
- **Action:** measure the same tip once more, with the same judges and the same
  N, and judge on the second measurement.
- **The trigger reads only the floor, never the verdict.** A combine that passed
  with a high floor is re-measured too, so this is not "measure until it
  passes". Without that symmetry, a second chance given only to failures would
  bias the delivered gain upward.
- **At most one re-measure per combine,** and the fallback's re-test follows
  the same rule. Both measurements are recorded in the row.
- **Cost:** CI minutes only (measurement runs locally, with no API call). In
  the sprint that would be about 4 extra ABAB blocks in 42 rows.
- **What it touches:** the combine node's decision path. The judges themselves,
  `derive_verdict`, N and the anti-cheat rules stay as they are.
- **Read as:** an arm X2-0R (X2-0 plus the re-measure). Its pre-registered
  measure would be the failed-combine rate and the delivered gain. Failures are
  rare, so the arm would need many runs to show anything. A cheaper reading is a
  replay: re-measure the archived tips of the rows whose floor crossed 2x, with
  no API spend at all.

## 2 Trial later rounds on top of earlier keeps

**What happens today.**

- Every trial in every round is a diff against the run's base commit. Later
  rounds see earlier keeps only as text: titles to avoid and lessons in the
  prompt.
- The combine merges all keeps at the end.

**Evidence.**

- **Repeats become conflicts.** Every left-out keep in a held combine conflicts
  textually with exactly one applied diff. About a third of those conflicts (21
  of 57) are the same technique implemented again. For example, the mistune
  renderer-method cache was found in round 1 and again in round 2, with an
  identical hunk in `core.py`, in four runs across three arms.
- **Unique gains fall fast by round.** Kept per run, with repeats and overlaps
  removed: X2-D gives 1.75 in round 1, then 0.83 in round 2 and 0.42 in round
  3. X2-0 and X2-P give 0.67 and 0.50 in round 2.
- **Depth reads as a weak direction, not a result.** X2-D's third round adds
  little that the combine can use, and the confirmation batch did not confirm
  X2-D against the pool (p 0.477).
- **Standalone points overstate later rounds.** A round-2 trial's gain is
  measured against the base commit, so it can re-count what round 1 already
  delivered.

**Proposal.** Arm X2-S, stacked rounds; everything else as X2-D, 3 rounds:

- **Round r + 1 starts from round r's tip.** At the end of round r, run today's
  combine. If it holds, the held tip becomes round r + 1's base commit, and the
  baseline and the profile are measured again on that tip.
- **Trials and judges run against the tip.** Round r + 1's trials are diffs
  against the tip, and the frozen judges compare each trial against the tip's
  baseline. A gain is then marginal by construction.
- **A failed combine stops the stacking.** If round r's combine does not hold,
  round r + 1 starts from the last held tip (the base commit if none held).
- **Delivery:** the last held tip, re-tested against the original base commit
  with today's ABAB and the test suite on the tip. Its gain is the run's primary
  measure, as today.
- **Equivalence and anti-cheat:** output equivalence is checked against the
  original base's outputs as well as against the tip's, so drift cannot
  accumulate. The protected-path rules apply to every round's diff, as today.
- **Cost:**
  - API: about X2-D's, 3.5 USD a run measured (the same requests).
  - CI: one combine, baseline and profile per round, an estimated 10 more
    minutes a run on today's libraries (not measured). X2-D's 133-minute job limit would need
    re-checking for two runs per dispatch.
- **Risks:**
  - Path dependence: an early keep fixes the code the later rounds see.
  - A noisy round-r combine can stop the stacking early; item 1 reduces this.
  - The prompts see a different code view each round, so idea dedupe keyed on
    the base commit's anchors would need re-keying to the tip.
- **Read as:** X2-S against X2-D and against the pool, with the same bar as
  O59 section 5. Pre-registered secondary measures: the conflict rate at
  delivery (expected near 0) and the unique keeps per round.

## 3 What the owner would decide

1. Item 1: build the re-measure (k = 2, one re-measure, the trigger on the floor
   only), first as an offline replay over the archived tips, or not at all.
2. Item 2: build arm X2-S for a later window, or not.
3. Either way, the record-only fate field lands first, and nothing changes in
   the combine or the judges until the owner rules.
