# Window 2 sprint report (O59), 2026-11-11

All runs are on key 2 (Window 2) unless marked W1. The archives are in `live/`
(one results file per dispatch, plus each run's kept diffs and delivered
patch under `patches-*`). The reading pages are in `reading/`: `variance.md`,
`rounds.md` and `frameworks.md`, built over the X2 archives plus these runs.
X2-SV is left out of the pool (O60).

## 1 What was built

| Unit        | Commit    | What                                                                                       |
| ----------- | --------- | ------------------------------------------------------------------------------------------ |
| U-key       | `26ea631` | `key_slot` picks `ANTHROPIC_API_KEY` or `_2`; ledger rows and the artifact name carry W1/W2 |
| U-patch     | `e152c16` | each kept diff and the delivered patch in the artifact, with base, commit and sha256       |
| U-depth     | `b0840bd` | arm X2-D (3 rounds, with `GENERATOR_MAX_CALLS=3`), `--rounds`, X2-SV out of the pool        |
| U-fable52   | `196ad3a` | Fable 5.2 rows, the Fable leap shape (high, 32,000, 951 s, Opus 4.8 fallback), `leap_shape` |
| U-portfolio | `718b98b` | the framework catalogue, the portfolio leap, arms X2-P and X2-F, `--frameworks`            |

Each unit: tests first, an Opus builder, a Fable review and a fix round, the
lab gate on every line at 100 % coverage, one commit.

## 2 Runs and spend

| Arm         | Runs with results       | Spent (USD)            | Ceiling | Held combines |
| ----------- | ----------------------- | ---------------------- | ------- | ------------- |
| Pilots      | 2 (X2-0 and X2-F tomli) | 5.41                   | 8       | 2 of 2        |
| X2-0        | 12 (3 a library)        | 28.78 (pilot included) | 35      | 12 of 12      |
| X2-D        | 10 of 12                | 33.85 + the lost one   | 45      | 10 of 10      |
| X2-P        | 12 (3 a library)        | 31.90                  | 42      | 12 of 12      |
| X2-F        | 3 (stopped)             | 12.82 (pilot included) | 60      | 3 of 3        |
| P2a (W1)    | 3 (X2-SV sqlparse)      | 8.88                   | -       | 3 of 3        |

- **Key 2:** 107.37 USD measured, plus dispatch 43093783855 (X2-D sqlparse,
  mistune), whose spend only the console shows (estimate about 7.8). Balance
  about 85, or 66.6 counting that dispatch at its 26 cap.
- **Key 1:** 8.88 spent on P2a; 12.20 left.
- **Lost dispatch:** 43093783855 passed its tests at 20:55; its artifact upload
  hung until GitHub ended the job at 21:40, with no artifact and no log (404).
  Not re-run: it would take X2-D to about 49.5 against its 45 ceiling.
- **X2-F stopped** on O46 condition 2 (dispatch 43104071793): the Fable 5.2
  leap on mistune, round 2, stopped at max_tokens (32,000), so its three
  procedures read no_reply. Six more Fable procedure ideas were dropped by the
  existing length checks (cost model over 300 characters five times, title
  over 120 once). O59: a failure stops that arm only.
- **No run** recorded a refusal, an unaffordable stage, a history-editing 400
  or a 429; every artifact carries W2 and its diffs with matching hashes.

## 3 The pre-registered reading (O59 section 5)

Primary measure: delivered combine gain per run (0 without a held combine),
each arm against the pool (X2-0, X2-0', X2-C; the sprint's X2-0 runs join it).

| Arm  | Sign test, combine vs pool          | Libraries with a higher median | Call                        |
| ---- | ----------------------------------- | ------------------------------ | --------------------------- |
| X2-D | 8 above, 2 below; two-sided p 0.255 | 4 of 4                         | not distinguishable (p)     |
| X2-P | 5 above, 7 below; two-sided p 0.576 | 1 of 4                         | not distinguishable         |
| X2-F | 3 runs; not tested (needs 6 signs)  | 1 of 3                         | not tested (arm stopped)    |

Per library, median delivered combine gain (n):

| Library  | Pool      | X2-D      | X2-P      | X2-F      |
| -------- | --------- | --------- | --------- | --------- |
| sqlparse | 21.1 (5)  | 32.2 (2)  | 16.7 (3)  | 22.9 (1)  |
| tomli    | 18.6 (5)  | 18.8 (3)  | 10.2 (3)  | 17.7 (1)  |
| mistune  | 15.9 (4)  | 19.0 (2)  | 13.1 (3)  | 15.2 (1)  |
| markdown | 11.2 (4)  | 11.3 (3)  | 22.9 (3)  | -         |

- **X2-P against the pool reads the prompt:** not distinguishable; it is
  below the pool's median on three of four libraries.
- **X2-F against X2-P reads the model:** not readable at 3 runs. X2-F's single
  run is above X2-P's median on all three of its libraries; that is a
  direction, not a call.
- **X2-D:** the most consistent arm (8 of 10 signs above, 4 of 4 medians up),
  but p 0.255 does not meet 0.10. Its two missing runs are on sqlparse and
  mistune, where it is highest.
- O51 and O52 are printed beside the call in `reading/variance.md`.

## 4 The other measures

| Arm  | Runs | Kept a run | Combine a run | USD a run | USD per delivered point |
| ---- | ---- | ---------- | ------------- | --------- | ----------------------- |
| X2-0 | 12   | 4.75       | +16.8         | 2.40      | 0.142                   |
| X2-D | 10   | 4.30       | +19.8         | 3.39      | 0.171                   |
| X2-P | 12   | 4.33       | +17.3         | 2.66      | 0.154                   |
| X2-F | 3    | 5.33       | +18.6         | 4.28      | 0.229                   |

- **Gain by round (X2-D, `reading/rounds.md`):** kept per run 1.8 fresh in
  round 1, 1.2 + 0.2 compound in round 2, 0.9 + 0.2 in round 3; standalone
  points (not additive) +16.0, +10.8 and +7.8.
- **By framework (`reading/frameworks.md`):** X2-P dealt 72 procedures; 51
  ideas passed the checks, 15 were trialled and 7 kept (bentley, polya 2,
  from_spec, ifr, trim, sit). Adherence 79-100 %. X2-F: 18 dealt, 9 ideas,
  2 trialled, 1 kept (from_spec), 3 no_reply.
- **Best-of-pool per library (best single run, labelled best-of):** sqlparse
  X2-D 36.1, tomli X2-0 24.8, mistune X2-D 19.6, markdown X2-P 25.5.
- **Hit rate by lane:** the default `x2.md` page refuses an arm recorded
  twice on a library, which the sprint's design does; the per-lane table is
  not produced for the sprint yet.

## 5 Decisions for the owner

1. **The lost X2-D dispatch:** re-run X2-D on sqlparse and mistune (about 7.8
   USD, past the 45 ceiling; X2-0 left 6.2 of its 35), or close X2-D at 10
   runs.
2. **X2-F:** stays stopped, or resumes after a fix. The two candidate fixes
   change the arm, so they are the owner's: state the length limits in the
   portfolio prompt (cost model at most 300 characters, title at most 120),
   and either a larger output cap for a Fable portfolio leap or effort medium.
   Nine X2-F runs remain at about 4.3 USD each.
3. **Window 1:** 12.20 USD left on key 1, usable until 2026-11-20; no plan.
