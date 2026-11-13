# Why live floors sit above quiet ones (O63 item 4), 2026-11-13

**How this was made.** Zero-credit and read-only, from the archives, the
workflow and the code: no API call, no dispatch, and only read-only GitHub
listings.
- **Data:** 63 runs and 972 trials with a floor: the O59 sprint, O61 (the X2-D
  re-run, X2-L and the confirmation batch) and O62's X2-0 runs. X2-SV is left
  out; with it nothing changes (47 trials, 3 above 1.5x).
- **Files:** scripts in `scripts/`, tables as CSVs here.
  - To reproduce: `python3 -I scripts/load.py ../live .`, then each script with
    `.`.
  - The Lead re-derived the headline (175 of 972 above 1.5x, 86 above 2x)
    independently from the archives.

## 0 The two floors

| Floor                              | Rule                                                                                                 | Code                                                     |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Calibrated baseline floor          | 3 A/A blocks, each ABBA with 1 warm-up and 5 timed runs a side; floor = max(2 %, 2 x the largest gap between 5-run means) | `trial_runner.py:816-859`, `models.py:58`, `config.py:676-681` |
| Trial floor (also combine, confirm) | max(2 sd_A, 2 sd_B, the calibrated floor x mean_A) / mean_A, with sample sd over 5 runs a side      | `anticheat.py:207-217, 231-232`, from `judges.py:191`; the calibration reaches it via `nodes.py:1610-1652` |

**They measure different things:**
- The calibration measures the noise of a difference of 5-run means.
- The trial floor measures the per-run spread of the larger side.
- A trial sits at 1.00x only when both sides' 2 sd fall below the
  calibration.

## 1 What runs during a measurement: nothing

| Suspect                               | Finding                                                    | Evidence                                                                                                                             |
| ------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Second run of a two-run dispatch      | Sequential, never concurrent                               | one parametrised test (`test_ideas_x2_live.py:46-66`), `-n 0` (`ci.yml:1350`); step time minus summed `seconds_measured` is 3-6 s in 5 dispatches, including a three-run one |
| Parallel trials                       | None                                                       | `nodes.py:3115-3138`; the graph is linear; no concurrency setting                                                                  |
| Generator and reviewer requests       | Before the trials                                          | the lane pool (4 workers) is joined inside the hypotheses node (`idea_pipeline.py:867-904`)                                          |
| Editor requests                       | Before each trial's measurement, blocking, not streamed    | `trial_runner.py:1234`, then `:627`; `transport.py:246`                                                                              |
| The library's test suite              | After A/B                                                  | `trial_runner.py:635`, `combine.py:282`                                                                                              |
| cProfile, op-count shim               | Never inside A/B                                           | the profile node runs once before the trials; the shim runs after the suite (`trial_runner.py:646`)                                 |
| git work, artifact work               | Outside the timed interval / after the run                 | `measure.py:345-353`; `ideas_x2.py:811-920`; the upload comes after pytest                                                           |
| Other jobs, concurrent dispatches     | None on the runner; separate VMs show no link              | the job log shows no orphan processes; Spearman 0.10 between concurrency and floors                                                 |

**Not answerable from the records:** host contention, in-guest services, the
CPU model per VM, per-look timestamps and per-side samples. The samples exist
in `Measurement.samples` but are not archived.

## 2 Trial floor against the run's calibrated floor

The calibrated floor is the run's `baseline_floor_pct` where recorded, else the
run's least trial floor. That stand-in equals the recorded value on all 4 O62
runs, and the floor rule keeps it from ever falling below the calibration.

| Split                                  | n   | median | p90  | max  | above 1.5x | above 2x |
| -------------------------------------- | --- | ------ | ---- | ---- | ---------- | -------- |
| All trials                             | 972 | 1.00   | 1.91 | 7.59 | 175 (18.0 %) | 86 (8.8 %) |
| One-run dispatches                     | 272 | 1.00   | 1.81 | 6.31 | 18.4 %     | 23       |
| Multi-run dispatches                   | 700 | 1.00   | 1.93 | 7.59 | 17.9 %     | 63       |
| First case of two / second case of two | 299 / 285 |  | 2.29 / 1.78 |  | 25.4 % / 13.0 % |   |
| Cases 1 / 2 / 3 of three               |     |        |      |      | 16 / 10 / 5 % |       |
| Rounds 1 / 2 / 3                       |     |        |      |      | 21 / 14 / 18 % |      |
| Trial index 1-3 / 4-6 / 7-10 / 11+     |     |        |      |      | 21 / 20 / 18 / 16 % |  |
| X2-0 / X2-D / X2-P / X2-F / X2-L        |     |        |      |      | 12 / 23 / 8 / 20 / 23 % | |
| sqlparse / tomli / mistune / markdown  |     |        |      |      | 27 / 19 / 16 / 9 % |  |
| Combine re-tests (62)                  | 62  | 1.00   | 1.82 | 5.70 | 9          | 6        |

- **Against the replay's quiet floors:** 27 % of trials are above 1.5x and 17 %
  above 2x.
- **Live calibrations range from the 2 % clamp to 12.2 %;** at least half sit
  at the clamp. The quiet values fall inside that range, and the quiet floor
  is itself one draw: the same replay VM calibrated mistune at 2.00 and 2.72.

## 3 Inconclusive trials with a gain between the two floors

Verdicts: 641 inconclusive, 284 keep, 49 reject (no review).

| Arm  | sqlparse | tomli | mistune | markdown | Total (own floor) | Total (quiet floors) |
| ---- | -------- | ----- | ------- | -------- | ----------------- | -------------------- |
| X2-0 | 0        | 0     | 2       | 0        | 2                 | 2                    |
| X2-D | 11       | 5     | 7       | 3        | 26                | 51                   |
| X2-P | 1        | 0     | 3       | 0        | 4                 | 7                    |
| X2-F | 0        | 1     | 1       | -        | 2                 | 2                    |
| X2-L | 6        | 3     | 3       | 1        | 13                | 22                   |
| All  | 18       | 9     | 16      | 4        | **47**            | **84**               |

- **The 47:** median gain 3.8 % (range 2.0 to 7.8), median own floor 6.6 %,
  median baseline floor 2.4 %. 10 of them gained 5 % or more
  (`q3_list.csv`).
- **Another 49 inconclusives cleared their own floor on the first look,** most
  likely as failed second looks (`confirm.py:73-80`). That is an inference,
  because the row does not record the reason.
- **13 rejects had a gain above the baseline floor.** 12 cleared their own
  floor and were rejected by another judge. Only one sits between the two
  floors: X2-D 43085621843 sqlparse `fc57f8b6`.

## 4 Causes, ranked

**1. The runner VM and its time since start (strong).**
- **The high floors cluster by run.** The noisiest 10 runs hold 90 of the 175;
  in 2,000 random permutations the most was 67 (p < 0.0005). 13 of the 63 runs
  have no trial above 1.5x.
- **The share above 1.5x falls with time since the job started:** 27 % in
  minutes 0-5, 22 % in 5-10, 18 % in 10-15, 16 % in 15-20, 15 % in 20-30 and
  10 % in 30-60. One-run dispatches show the same fall.
- **At the same trial index, later cases are quieter:** trials 1-4 run 25 % in
  a first case against 16 % later.
- **Within a run:** the last third is quieter than the first in 43 of 63
  runs.
- **Only 5 of the 63 live runs show 12 looks in a row as quiet as the
  replay.** The replay VM was a quiet draw.
- **Open:** X2-P 43107418692 sqlparse had all 14 trials at 1.00, yet its
  combine read 3.37x at about minute 23. Late bursts also happen. The
  mechanism (host contention, in-guest services, the CPU model) cannot be
  identified from today's records.

**2. The two floors are different statistics (certain; it amplifies cause 1).**
- **A simulated steady machine with no contention** (`scripts/simulate.py`):
  at 1.5 to 3 % per-run noise, 38 to 46 % of trials land above 1.5x; below
  0.5 % noise, none do.
- **Noise of about 0.4 % with a rare 5-20 % slow run** (2-5 % of runs) best
  fits what was observed: 62 % of trials exactly at the floor and a heavy
  tail.
- **N = 5 makes the sd volatile:** its 90 % interval runs from 0.42 to 1.54 of
  the true value, and taking the larger of two sides biases it upward.
- **The gain is a difference of adjacent A and B launches,** so slow noise
  shared by both largely cancels in it. The floor counts that noise on each
  side.

**3. The calibration measured at a quieter moment (weak).** It runs first,
which is the noisiest stretch; its real difference is its statistic.

**Ruled out:**
- editor or generator overlap;
- the test suite between A and B;
- xdist and coverage;
- artifact work;
- other jobs on the runner;
- concurrent dispatches;
- thermal throttling, which would make floors rise through a run, while they
  fall.

## 5 Proposed fixes (proposal only; nothing changed)

**A. A paired floor (no CI minutes).**
- Floor = max(calibrated floor, k x sd(B_k - A_k) / sqrt(n)), from the pairs
  the ABBA design already produces, with the calibration computed the same way
  over its A/A blocks.
- The constant is set from the new records, so that a steady machine reads
  about 1.0x.
- It removes VM-level noise shared by A and B, which already cancels in the
  gain, and it removes the mismatch between the two statistics. A burst that
  hits only one side still widens sd(B - A).
- **It is a judge change,** so it is the owner's call. It should wait until
  the records show the noise is shared.

**B. A settle step before a dispatch's first case.**
- A request-free A/A probe, repeated until 2 sd stays under 2 % for two blocks,
  capped at 5 minutes.
- Cost: at most 5 minutes a dispatch, about 12 to 15 % of a 35 to 45 minute
  dispatch.
- It targets minutes 0 to 10 (the 27 % and 22 % above). It does nothing for
  differences between VMs or for late bursts.

**C. Only if the records show single-run spikes.**
- A robust spread (median absolute deviation, or the sd with the worst pair
  dropped): no CI minutes.
- Or N of 7 to 9 for combine and confirmation looks only: about +1 to 2
  minutes a run.

**The combine re-measure threshold.** Combine floors behave like trial floors
(15 % above 1.5x, 10 % above 2x). An immediate re-measure would mostly meet the
same VM state; fix A would make most re-measures unnecessary. The threshold
stays the owner's call.

**Record-only fields to confirm the cause on the next live run.** Proposed for
the X2-DT harness unit; they need the owner's go, since items 1 to 4 touch the
measurement path's records, not its decisions:
1. the start and end time of every look: trial, confirmation, combine greedy
   and fallback, and each calibration block;
2. per side, the wall and CPU samples already in `Measurement.samples`, plus
   the warm-up's wall time;
3. `/proc/loadavg`, `/proc/pressure/cpu` and `/proc/stat` deltas (including
   iowait and steal) before and after each look;
4. the top 3 non-engine processes by CPU ticks during each look;
5. per run, the CPU model and clock, CPU count, memory, `RUNNER_NAME` and
   `ImageVersion`;
6. each calibration block's gap and per-side sd; today only the largest gap is
   kept.

**How to read the next run:**

| What the records show                                                   | What it means                       |
| ----------------------------------------------------------------------- | ----------------------------------- |
| a large per-side sd with a small paired sd                               | A removes the cause                 |
| high floors that track minutes since boot, other processes' ticks or CPU pressure | B, or the named process   |
| high floors concentrated on one CPU model                                | choose the runner type              |
| one spiked run out of five                                               | C                                   |
