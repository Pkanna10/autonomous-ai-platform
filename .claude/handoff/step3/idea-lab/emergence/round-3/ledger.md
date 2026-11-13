# Round 3, stage 0: the loss ledger (the Lead, 2026-11-13)

**Where proven gain is lost, stage by stage.** Each row is measured and names
its source.
- Paths are relative to `.claude/handoff/step3/idea-lab/`.
- **Archive:** 63 run x library rows from the O59 sprint, O61 and O62
  (`w2-sprint/live/`). X2-SV is left out.
- **The "floor" column is for the first-principles seats:** the least loss
  any correct engine must accept at that stage. "Gap" is the measured loss
  minus that floor.
- Ranking the rows by gap is their task.

| #   | Stage where gain is lost                                   | Measured loss                                                                                                                                                                                                              | Source                                                           | Floor | Gap |
| --- | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- | ----- | --- |
| L1  | **Ideas that never become trials**                          | 110 of 163 ideas read (67 %) in 4 X2-0 runs never became a hypothesis. By stage: read 37 (31 of them `ungrounded`), s4a 13, s3 25 (24 reviewer `duplicate_of`), s4b 35 (19 blocked by several quotas). X2-P: 36 of 51 framework ideas untrialled | `w2-sprint/o62/README.md` s2; `w2-sprint/ideas-fate/README.md`   |       |     |
| L2  | **Truncated leaps**                                         | Opus 5.5 leap stopped at 12,000 tokens in 3 of 32 recorded calls (2 of them mistune round 2). Fable 5.2 at 32,000 in 1 of 6 (X2-L) and in X2-F's stop. A truncated reply yields no idea at all                          | `w2-sprint/o62/README.md` s3; `w2-sprint/o61/README.md`          |       |     |
| L3  | **Trials lost to measurement noise**                        | 18 % of 972 trials have a floor above 1.5x the run's calibrated floor (8.8 % above 2x). 47 inconclusive trials had a gain above the baseline floor but below their own (median 3.8 %, 10 at 5 % or more; 84 against the quiet floors) | `w2-sprint/floors/README.md` s2, s3                              |       |     |
| L4  | **Failed confirmations**                                    | 49 inconclusive trials cleared their own floor on the first look, then failed the second (an inference: the row does not record the reason)                                                                              | `w2-sprint/floors/README.md` s3                                  |       |     |
| L5  | **Combine conflicts and repeats**                           | 62 of 177 keeps in held combines were left out (X2-0 18 of 57, X2-D 25 of 52, X2-P 17 of 52, X2-F 2 of 16), every one by a textual conflict with an applied keep. 21 of 57 conflicts are the same technique re-implemented | `w2-sprint/zero-credit/README.md` s1                             |       |     |
| L6  | **Combine below its best part** | In 12 of 63 runs the delivered combine gain is below that run's own best single kept change (mean shortfall 3.28 points, fp-ideation). Across all runs the combine usually exceeds it: the median delivered is +17.4 and the median best single keep is +11.3. Part of the shortfall may be the winner's curse, since the best single keep is the maximum of selected first looks (z1-analogy) | the Lead's computation on `w2-sprint/live/` (this page); round-3 library | | |
| L7  | **Combine lost to noise**                                   | 1 of 63 combines failed (X2-D re-run, mistune, +8.5 against a 9.76 floor). The replay held it 3 of 3 at +10.5 to +11.8 against 2.72 (`o62/replay.md`). Combine floors run above 1.5x the baseline in 9 of 62           | `w2-sprint/o62/replay.md`; `w2-sprint/floors/README.md` s2       |       |     |
| L8  | **Diminishing unique keeps per round**                      | Keeps per run with repeats and overlaps removed: X2-D 1.75 in round 1, then 0.83, then 0.42; X2-0 and X2-P 0.67 and 0.50 in round 2                                                                                        | `w2-sprint/zero-credit/README.md` s2                             |       |     |
| L9  | **Spread between identical runs**                           | The same arm on the same library: sqlparse +14.6 to +43.9 (16 runs), tomli +6.1 to +24.8, mistune 0 to +23.7, markdown +9.9 to +25.5. The pool's A/A spread on sqlparse alone is +15.2 to +39.8 (5 runs)                 | `w2-sprint/live/`; `w2-sprint/reading/variance.md` s1            |       |     |
| L10 | **Edits confined to the hot function**                      | Not yet measured: the share of expert gain in functions the engine never edits. It is the expert-practice seat's task, from the four development libraries' own performance commits                                       | to be measured (the expert-practice seat)                         |       |     |

**Notes for the seats:**
- **L1 dominates by count, not necessarily by gain.** The fate record says where
  ideas go; nothing yet says what the lost ideas would have gained. The
  inconclusive-diff archive (O63 item 5) will start to say it for L3.
- **L3 and L7 share one cause** (O63 item 4): the runner VM's state and the
  mismatch between the floor statistics.
- **L5 and L8 are the same loss seen twice.** Repeats become conflicts.
