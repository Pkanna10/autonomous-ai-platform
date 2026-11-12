# Zero-credit analysis of the sprint archive (O61 addendum item 3)

Read-only, from the archived diffs and rows of X2-0, X2-D, X2-P, X2-F and X2-SV
(42 run x library rows; X2-L was still running and is left out). No dispatch on
either key. The X2-D re-run's mistune run stays 0 on the primary measure.

**Method.** Every trial diff is against the run's `base_commit` (all 224 files
present, sha256 match, none truncated). A sparse base is rebuilt per file from
the old side of the run's diffs; each diff is applied with no fuzz and the
combine replayed with `git merge-file`, the same 3-way merge the combiner uses
(`execution/combine.py:_merge`). Replaying each run's `applied_trial_ids` in
order reproduces all 36 `delivered.patch` files byte for byte. Repeat (R: the
same technique on the same code) and overlap (O: a different change on
overlapping hunks) labels are judgments from reading the diffs; the metrics
behind them are in `pairs.csv`. Scripts: `analyse.py`, `summarise.py`,
`perrun.py`.

## 1 Kept against applied, and why each left-out keep was left out

| arm   | runs | kept | delivered | left out | conflict with an applied diff | of which the same technique re-implemented | dropped at re-test | repeat (nothing left) | cannot tell |
| ----- | ---- | ---- | --------- | -------- | ----------------------------- | ------------------------------------------ | ------------------ | --------------------- | ----------- |
| X2-0  | 12   | 57   | 39        | 18       | 18                            | 6                                          | 0                  | 0                     | 0           |
| X2-D  | 12   | 52   | 27        | 25       | 20                            | 10                                         | 5                  | 0                     | 0           |
| X2-P  | 12   | 52   | 35        | 17       | 17 (1 may be re-test)         | 5                                          | 0                  | 0                     | 0           |
| X2-F  | 3    | 16   | 14        | 2        | 2                             | 0                                          | 0                  | 0                     | 0           |
| X2-SV | 3    | 18   | 14        | 4        | -                             | -                                          | -                  | -                     | 4 (no diffs archived) |

- In every held combine each left-out keep conflicts textually with exactly one
  applied diff; none was dropped at the re-test and none was a no-op repeat.
- About a third of the conflicts (21 of 57) are the same technique implemented
  again, so repeats show up as conflicts, not as duplicates.
- The five "dropped at re-test" are the X2-D re-run's mistune run (43145496896):
  neither the greedy set nor the fallback held. Its row's `applied` = 1 is the
  failed fallback's single trial; nothing was delivered.
- Which applied diff blocked each left-out keep, in which file and hunk:
  `q1_left_out.csv`, `pairs.csv`.

## 2 Keeps per run per round, raw and with repeats and overlaps removed

| arm   | round 1 | round 2 raw -> unique (R / O) | round 3 raw -> unique (R / O) |
| ----- | ------- | ----------------------------- | ----------------------------- |
| X2-0  | 3.25    | 1.50 -> 0.67 (4 / 6)          | -                             |
| X2-D  | 1.75    | 1.50 -> 0.83 (6 / 2)          | 1.08 -> 0.42 (5 / 3)          |
| X2-P  | 2.83    | 1.50 -> 0.50 (4 / 8)          | -                             |
| X2-F  | 3.00    | 2.33 -> 2.00 (0 / 1)          | -                             |
| X2-SV | 4.00    | 2.00 -> 1.33 (target paths only) | -                          |

- Removing only repeats (not overlaps): X2-0 round 2 1.17; X2-D round 2 1.00,
  round 3 0.67; X2-P round 2 1.17; X2-F round 2 2.33.
- The owner's example holds: in 43145496896 mistune, b741a3ad (round 1) and
  f0efa548 (round 2) share an identical hunk in `core.py` (the renderer-method
  cache). The same pattern appears in X2-0 43093762527, X2-D 43085626757 and,
  within round 2, X2-P 43104077245. Other re-found techniques: tomli's
  single-part key fast path in `key_value_rule` (three versions across three
  rounds in X2-D 43093773731), mistune's `build_closing_bracket_map` regex scan,
  and the abbr "skip when no match" change. Pairs: `q2_cross_round_pairs.csv`.

## 3 The combine's floor against the run's baseline floor

| arm   | combine floor above baseline | median ratio | max ratio | mean combine / baseline floor | failed combines | failed while above the baseline floor |
| ----- | ---------------------------- | ------------ | --------- | ----------------------------- | --------------- | ------------------------------------- |
| X2-0  | 3 of 12                      | 1.00         | 1.35      | 2.20 / 2.11                   | 0               | 0                                     |
| X2-D  | 6 of 12                      | 1.18         | 2.59      | 4.89 / 3.65                   | 1               | 1                                     |
| X2-P  | 2 of 12                      | 1.00         | 3.37      | 3.16 / 2.44                   | 0               | 0                                     |
| X2-F  | 1 of 3                       | 1.00         | 1.82      | 2.55 / 2.00                   | 0               | 0                                     |
| X2-SV | 0 of 3                       | 1.00         | 1.00      | 2.09 / 2.09                   | 0               | 0                                     |

- The one failed combine (43145496896 mistune: gain 8.54 %, floor 9.76 %,
  baseline floor 3.76 %) is the fallback's single-change re-test, not the
  combination: with five keeps a fallback ran, re-testing the best-gain change
  (inferred d11a38da, 12.51 %, whose own trial floor was already 7.38 %). The
  9.76 is that re-test's own spread, not the calibration.
- The baseline floor here is the minimum of the run's hypothesis floors (the
  calibrated floor; most trials sit exactly on it); the calibrated floor itself
  is not in the rows. The greedy combination's own gain and floor are in no row
  either (only as text in `Combination.summary`).

## 4 Record-only fields that would close the gaps

Harness only (`X2Recorder.record`), the engine unchanged: `fallback_trial_id`;
`combine_summary` (`comb.summary`); `skipped` (`comb.skipped`: id, reason,
paths); `baseline_floor_pct` (the baseline's calibrated floor); `conflicts`
always (today only with SITE_STACKS on or record). These feed O61 addendum item
4 (the fate field extended to the combine), which is built after the last key-2
dispatch.
