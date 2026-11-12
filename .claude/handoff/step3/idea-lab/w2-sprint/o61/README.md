# O61 readings: X2-L and the X2-D confirmation batch, 2026-11-12

Archives: `../live/ideas-x2-X2-L-*.jsonl` (12 runs) and the confirmation batch
`../live/ideas-x2-X2-D-<id>.jsonl` for ids 43159144063, 43159147698,
43159151284, 43159154661 (key 2) and 43159157891, 43159160974 (key 1). Each
run's kept diffs and delivered patch are in `../live/patches-<arm>-<id>/`. The
pool is unchanged from the sprint reading: X2-0, X2-0' and X2-C from
`../../x2/` plus the sprint's X2-0 runs. Pages are built with
`python -m live.ideas_x2_report <pool> <arm files> --variance` and
`python -m live.ideas_x2_tokens <files>`.

## 1 The three conditions, the spend and the paying key

| Dispatch    | Arm  | Libraries         | Key | USD   | Cond. 1 | Cond. 2                                 | Cond. 3 |
| ----------- | ---- | ----------------- | --- | ----- | ------- | --------------------------------------- | ------- |
| 43159100367 | X2-L | sqlparse          | 2   | 4.32  | ok      | ok                                      | ok      |
| 43159103908 | X2-L | tomli             | 2   | 3.32  | ok      | ok                                      | ok      |
| 43159107354 | X2-L | mistune           | 2   | 4.51  | ok      | **round-2 Fable leap at 32,000 tokens** | ok      |
| 43159144063 | X2-D | sqlparse, tomli   | 2   | 6.94  | ok      | ok                                      | ok      |
| 43159147698 | X2-D | sqlparse, tomli   | 2   | 6.86  | ok      | **sqlparse round-3 Opus leap at 12,000** | ok      |
| 43159151284 | X2-D | mistune           | 2   | 3.78  | ok      | ok                                      | ok      |
| 43159154661 | X2-D | mistune           | 2   | 3.84  | ok      | **round-2 Opus leap at 12,000**          | ok      |
| 43159157891 | X2-D | markdown          | 1   | 3.51  | ok      | ok                                      | ok      |
| 43159160974 | X2-D | markdown          | 1   | 3.38  | ok      | ok                                      | ok      |

- No refusal, no unaffordable stage, every combine held, every artifact on
  `9e8d2e5` with its window and diffs.
- **X2-L:** 12 of 12 runs; 44.54 USD against its 48 ceiling. The max_tokens
  stop came in the last of the 12 runs, so "a stop at the cap ends the arm"
  leaves nothing to stop.
- **Confirmation:** 8 of 8 runs; 28.30 USD against its 30 ceiling (key 2 21.42
  over 6 runs, key 1 6.89 over 2).
- **The two Opus leap stops are new to see, not new to happen.** The 12,000
  output cap on the Opus leap is unchanged since X2. Before U-tokens (`c909427`)
  the rows recorded no stop reason, so an Opus leap that stopped at the cap
  could not be seen in any earlier run. Here 2 of 24 Opus leap calls stopped;
  the least headroom among the rest was 1,109 tokens (`tokens-confirmation.md`).
  A stopped leap loses only that lane's ideas for the round; the round's other
  seven lanes, the trials and the judges are untouched.

## 2 X2-L against the pool (O59 section 5)

| Measure          | Signs                     | Two-sided p | Libraries with a higher median | Call                |
| ---------------- | ------------------------- | ----------- | ------------------------------ | ------------------- |
| combine (primary) | 8 above, 4 below          | 0.661       | 2 of 4                         | not distinguishable |
| kept             | 2 above, 8 below, 2 ties  | 0.077       | -                              | printed only        |

| Library  | Pool median (k) | X2-L runs          | X2-L median |
| -------- | --------------- | ------------------ | ----------- |
| sqlparse | 21.1 (5)        | 26.2, 27.3, 19.4   | 26.2        |
| tomli    | 18.6 (5)        | 6.1, 15.4, 22.5    | 15.4        |
| mistune  | 15.9 (4)        | 15.9, 0, 20.9      | 15.9 (tie)  |
| markdown | 11.2 (4)        | 18.9, 11.8, 24.9   | 18.9        |

- Other measures: kept 3.75 a run (X2-0 4.75), combine +17.4 a run (X2-0
  +16.8), 3.71 USD a run, 0.213 USD per delivered point (X2-0 0.142).
  Best-of per library: sqlparse 27.3, tomli 22.5, mistune 20.9, markdown 24.9.
- **Fable leap output tokens** (`tokens-x2-l.md`): the 9 runs before U-tokens
  read "not recorded". In the last 3 runs: 19,499, 17,622, 14,476, 16,175 and
  15,515 tokens, plus the one stop at 32,000. The least headroom among the five
  that replied is 12,501.

## 3 The X2-D confirmation batch (pre-registered: the 8 alone)

| Reading                                     | Signs            | Two-sided p | Higher median | Bar met |
| ------------------------------------------- | ---------------- | ----------- | ------------- | ------- |
| **The 8 alone (pre-registered)**            | 6 above, 2 below | 0.477       | 2 of 4        | **no**  |
| All 20 X2-D runs (**not pre-registered**)   | 14 above, 6 below | 0.384      | 4 of 4        | no (p)  |
| The 8 less the two leap stops (sensitivity) | 5 above, 1 below | 0.354       | -             | no (p)  |

| Library  | Pool median | Confirmation runs | Its median | All 20: median (n) |
| -------- | ----------- | ----------------- | ---------- | ------------------ |
| sqlparse | 21.1        | 33.7, 43.9        | 38.8       | 33.7 (5)           |
| tomli    | 18.6        | 10.5, 20.2        | 15.3       | 18.8 (5)           |
| mistune  | 15.9        | 20.8, 6.9         | 13.9       | 18.4 (5)           |
| markdown | 11.2        | 21.4, 14.0        | 17.7       | 14.0 (5)           |

- **Call: X2-D is not confirmed.** The batch's direction agrees with the sprint
  (6 of 8 above), but its p is 0.477 and its median is higher on only 2 of 4
  libraries.
- The sensitivity row drops the two runs whose leap stopped (mistune 6.9 and
  sqlparse 43.9), one below the pool and one above. It is printed for the
  record and is not a reading. Its page reads a copy of 43159147698 with the
  sqlparse rows removed, kept in the Lead's scratch area; the file name in the
  page is the archive's.
- Other measures for the 8: kept 5.50 a run, combine +21.4 a run, 3.54 USD a
  run, 0.165 USD per point. For all 20: kept 4.80, +19.2, 3.50 USD, 0.182 USD
  per point.

## 4 Credit after the last dispatch (measured spend; the console is the truth)

- **Key 2:** 84.85 at the console read, less 12.14 (the last 3 X2-L runs) and
  21.42 (6 confirmation runs) = **51.29 at most**; **40.75 at least** if the
  three X2-L runs in flight at the read (10.54) had not been charged yet. No new
  key-2 dispatch after 2026-11-14 12:00 UTC; the key expires 2026-11-15.
- **Key 1:** 12.18 less 6.89 = **5.29**, usable until 2026-11-20.
