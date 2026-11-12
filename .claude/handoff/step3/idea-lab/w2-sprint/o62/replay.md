# Combine replay (O62 item 5): run 43194422719, 2026-11-12

`combine-replay` on `a8fd421`, GitHub Actions, no Claude request (0 USD).
- **Duration:** 6 minutes, conclusion success.
- **Coverage:** every tip case had three measured looks.
- **Integrity:** every patch's sha256 and base commit matched the archive.

Results file: `combine-replay-43194422719.jsonl` beside this page.

**What each look is.** One re-test of the archived tip against the base,
through the combine node's own path (`combine_node.retest_one`, the factory's
judges, settings pinned to the X2 arms'), after one baseline calibration on
the same runner.

## 1 The four rows whose combine floor was 2x or more the baseline's

| Row (arm, dispatch, library)  | Archived: gain / floor / baseline floor / held | Replay: baseline floor | m1 gain / floor    | m2 gain / floor    | m3 gain / floor    | Held      |
| ----------------------------- | ---------------------------------------------- | ---------------------- | ------------------ | ------------------ | ------------------ | --------- |
| X2-D 43093773731 tomli        | +18.8 / 6.45 / 2.58 / yes (ratio 2.50)         | 3.56                   | +19.8 / 3.56       | +18.5 / 3.56       | +18.6 / 3.56       | 3 of 3    |
| X2-P 43104077245 mistune      | +13.1 / 5.94 / 2.00 / yes (ratio 2.97)         | 2.00                   | +18.4 / 2.00       | +18.3 / 2.00       | +19.2 / 2.06       | 3 of 3    |
| X2-P 43107418692 sqlparse     | +34.7 / 6.74 / 2.00 / yes (ratio 3.37)         | 2.00                   | +33.6 / 2.00       | +33.8 / 2.00       | +33.5 / 2.00       | 3 of 3    |
| X2-D 43145496896 mistune, the fallback change d11a38da | +8.5 / 9.76 / 3.76 / **no** (ratio 2.59) | 2.72  | +11.8 / 2.72       | +10.5 / 2.72       | +10.5 / 2.72       | **3 of 3** |

- **The tips' own spread is small.** On a quiet runner each tip's floor stayed
  at its baseline floor (ratio 1.00 to 1.03), and its gain moved by at most
  1.3 points across three looks. The archived floors of 2.5x to 3.4x were not
  a property of the tips. They came from the conditions of those runs' own
  combine measurements: the same CPU and runner state the run's trials and
  editor had just used.
- **The one failed combine would very likely have been delivered.** The
  fallback change failed its live re-test at +8.5 against a floor of 9.76. Its
  three replays measure +10.5 to +11.8 against 2.72. The X2-D re-run's mistune
  row scores 0 on the primary measure, and it stays 0: the replay does not
  change any reading.
- **The proposed rule never fires on the replay,** because no m1 floor exceeds
  2x its baseline floor. That is the expected result where the noise was
  in-run. It says only that a second measurement in a quieter moment reads
  lower, not what the in-run second measurement would have read.
- **Limit:**
  - The replay cannot reproduce the live runs' contention, so it cannot show
    how often an in-run re-measure would itself be noisy.
  - The greedy combination of the failed mistune run is not replayed: its
    order is not recorded, and two sets are possible.

**What this suggests, for the owner:**
- **The trigger is sound,** and no change is made (O62: no combine-node
  change until the owner has read this).
- **The re-measure should run where the noise is lowest:** immediately, with
  nothing else running, as the combine re-test already does.
- **Alternatively, the threshold could be lower than 2x.** The sprint's floor
  ratios were 1.00 in 30 of 42 rows, so a ratio above 1.5 is already unusual
  (6 of 42 rows).
- Either version is the owner's call.

## 2 Measured CI time on a GitHub runner (for X2-DT, O62 item 6)

| Library  | Calibration (s) | Baseline step incl. calibration (s) | One combine re-test incl. suite (s) | Suite alone (s) | Profile (s) |
| -------- | --------------- | ----------------------------------- | ----------------------------------- | --------------- | ----------- |
| tomli    | 17.4            | 21.7                                | 5.5-5.7                             | 0.15            | 1.4         |
| mistune  | 31.0-31.4       | 42.0-43.3                           | 12.2-13.0                           | 2.6-3.1         | 2.6         |
| sqlparse | 38.9            | 51.1                                | 13.1-13.3                           | 2.1-2.3         | 3.2         |
| markdown | 29.7            | 38.0                                | not measured (no tip)               | -               | 2.2         |

- **One adopted round** (combine re-test + baseline at the tip + profile) costs
  29 s on tomli, 58 s on mistune and 68 s on sqlparse. Markdown is about 52 s,
  taking mistune's re-test as a stand-in.
- **The worst case for an X2-DT run** is under 3 minutes:
  - two adopted rounds, each with a fallback re-test;
  - one final re-test against the original base;
  - on sqlparse, 2 x (68 + 13) + 13 = 175 s.
- **These are quiet-runner times.** In a live run the trials have finished
  by the time the combine runs. Wall times should therefore be close, though
  in-run floors were noisier, as section 1 shows. The pilot measures them
  in-run.
