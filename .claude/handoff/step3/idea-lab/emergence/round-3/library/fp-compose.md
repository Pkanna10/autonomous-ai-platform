# fp-compose: first principles (cost atoms, Amdahl, composed speed-ups)

Seat note: web search worked but page fetch was blocked (ar5iv.arxiv.org and ir.cwi.nl do not resolve in this session). Where a number comes from a search-result summary of a paper and not from its full text, the note says so. All archive numbers were computed read-only with `python3 -I`. The scripts are in `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/fp-compose/` (`l5all.py`, `l6b.py`, `l10.py`, `l10b.py`). To map diff lines to functions I cloned the four upstream pins named in `tests/fixtures/live_oss/manifest.json` read-only into that folder. All 284 kept diffs pass `git apply --check` against those pins. No library code was executed; it was parsed with `ast` only. No sealed or held-out file was read.

## Core sources

1. **Amdahl 1967 [1].** The founding bound: the overall gain is capped by the share of time the improved part takes. It is the standard atom for composed speed-ups.
2. **Hennessy & Patterson, *Computer Architecture: A Quantitative Approach*, 6th ed. [2].** Chapter 1 states Amdahl's law in fractions (fraction enhanced, speedup enhanced) and works it as cost accounting. It is the standard textbook form.
3. **Gustafson 1988 [3]; Hill & Marty 2008 [4].** The scaled-workload rebuttal of Amdahl, and Amdahl's law applied to composed resources. Both are standard companions that set the limits of the fixed-workload reading.
4. **Bentley, *Programming Pearls*, 2nd ed., Column 6 [5], with Appel 1985 [6].** The canonical case of gains multiplying across design levels: the n-body run went from "a year to a day", a factor of 400. Improvement does not live at one level or in one function.
5. **Knuth 1971 [7].** The first empirical profile study: a small share of code dominates running time. Full text not accessed.
6. **Curtsinger & Berger 2015, Coz [8].** Causal profiling. Where a profile shows time is not always where an optimization pays, and the paper measures that.
7. **Smith & Winkler 2006 [9].** The optimizer's curse: the alternative chosen as best is, on average, worse than its estimate, even when every estimate is unbiased. This is the formal atom of "re-measured lower".
8. **Siegmund et al. 2012 [10].** Measured performance interactions between composed features. It is the standard reference on non-additive composition.
9. **Chapman 1951 [11]; Chao 1987 [12].** Capture–recapture estimation of an unseen population size, and its bias when items differ in how easy they are to catch. These give a principled floor for "unique finds per round".

## Notes

**Composition atom (Amdahl in saved-time form).** The engine's gain is the time saved divided by base time (`anticheat.relative_gain`). Two changes measured against the same base that act on disjoint time therefore compose by **adding saved fractions**, G = Σgᵢ, not by multiplying speed-ups [1][2]. A change confined to a component with share s can save at most s.

Worked example from the archive: X2-0 43080309535 tomli applied three keeps of +12.0, +5.4 and +6.8. Amdahl predicts +24.2; the combine delivered +24.8. Across 61 held combines, delivered over Σ(applied standalone gains) has a median of 0.94 (IQR 0.82–1.01, range 0.48–1.24) and an aggregate of 0.88 (1,123 of 1,277 points). The additive model is right to about 6–12 %, the same order as the interaction error Siegmund et al. report for ignoring interactions. Their headline is about 95 % accuracy with interactions modelled, about 15 points above a model that ignores them (search summary) [10].

**Selection atom (optimizer's curse).** Pick the largest of k noisy gains and re-measure it, and it regresses downward in expectation [9]. The judges' floor is 2 sd of single runs, or the 2 % minimum (`noise_floor`). With N = 5 a side, the standard error of a gain is about 0.63 sd, so the floor is about 3.2 SE. Any "re-measure is lower by less than the floor" result is therefore expected, not a defect.

**Location atom (profile vs causality).** Knuth's study made profile concentration the basis of tuning [7]. Coz shows the profile can mislead: guided by virtual speed-ups, the authors gained 9 % on Memcached, 25 % on SQLite and up to 68 % on PARSEC, mostly with changes under 10 lines (search summary of the abstract) [8]. Bentley and Appel show the large factors come from several levels at once (algorithm, data structure, code tuning, hardware), multiplying to about 400 [5][6].

**Distortion atom.** cProfile inflates call-heavy code. The dev-set manifest's own numbers give profiled/plain ratios of 2.8x (tomli 1.7/0.6 s), 3.4x (sqlparse 5.1/1.5 s), 2.8x (mistune) and 2.8x (markdown). Shares of small hot helpers (`skip_chars`, `imt`) are therefore overstated as Amdahl shares of plain runtime. Python's profiler documentation treats this overhead as something to calibrate [13].

**Finite-pool atom (capture–recapture).** If a run's lanes draw keepable sites from a pool of N sites, the share of round-2 keeps that re-find round-1 sites estimates n₁/N. The Lincoln–Petersen / Chapman estimate is N ≈ (n₁+1)(n₂+1)/(m+1) − 1 [11]. Unequal catchability (some sites are very easy to find) biases this estimate **low** [12], so any N computed this way is a lower bound.

**Established and contested.** Established: Amdahl's bound and additivity of saved fractions on disjoint work [1][2]; the optimizer's curse [9]; non-additivity under interaction [10]. Contested: how much a fixed-workload Amdahl reading understates gains when the workload scales [3]; whether profile shares predict payoff [8]. My profile shares are cProfile summaries, not causal measurements.

## Bearing on the ledger

- **L5.** Saved-time additivity holds within about 12 %, so combine loss is a selection problem, not an arithmetic one. Floor and gap are in the section below.
- **L6.** This is the optimizer's curse plus selection order. 4 of the 12 rows are curse, 7 are order, 1 is L7.
- **L7.** The curse and noise atoms apply here too. The replay (`o62/replay.md`) puts the tips' own spread at ≤1.3 points across 3 looks, so the archived 2.5–3.4x floors were in-run contention.

  Inference from the rows only: X2-D 43159154661 mistune delivered 1 of 7 keeps, the best one (+7.7 standalone, +6.9 delivered). At least three of its keeps are pairwise disjoint (the range proxy gives a max-sum subset of 27.6), so this looks like a failed greedy combine rescued by the fallback. The row has no `fallback_trial_id` field to confirm it. If so, L7's count is 2 of 63, not 1.
- **L8.** The finite-pool atom: see the next section.
- **L10.** The location and distortion atoms: see the next section.

**Correction for the ledger's L6 cell.** Its medians (+17.4 delivered, +11.3 best keep) are over **all 63 runs**. I reproduce 17.4 over 63, and 11.6 over the 62 runs with keeps. On the 12 below-best rows themselves, the medians are 10.1 delivered against 13.4 best.

## Open questions for the seminar

1. How much do overlapping keeps (O: a different change on the same hunks) add on top of each other? Amdahl gives a range from 0 to the smaller standalone gain. Only stacking (X2-DT) or an offline re-apply-and-measure on the archive can say.
2. Is the visible pool really about 4–6 keepable sites per run? Heterogeneity biases this low [12]. A cross-run union per library (seed a) would give a direct count.
3. What is each library's speed-of-light bound? The X2-F/X2-P diagnoses state a `least_work` but no time, so no row has an absolute ceiling yet.
4. Would a causal (Coz-style) or plain-time profile move the ranking of hot components? The cProfile inflation is 2.8–3.4x.

## Floors (L5, L6, L8, L10) and ranking

Common unit: **delivered percentage points of runtime per run (pp/run)**. The gap is the measured loss minus the floor.

**L5, combine conflicts and repeats.**
- Atom (a), true repeats. 21 of 57 conflicts in the 38 rows with replayed pairs are the same technique re-implemented. Their marginal gain is about 0 once the blocker is applied. They are floor: the count must be left out, at 0 pp lost.
- Atom (b), selection order. The archive's greedy order is hypothesis score, with `SITE_STACKS` off. I computed the max-sum conflict-free subset exactly, using a hunk-range overlap proxy that agrees with zero-credit's `git merge-file` replay on 363 of 365 pairs. Over 61 held rows, that subset sums to 1,464 standalone points against 1,277 applied. That is +3.06 points per row (median 0; 21 rows gain more than 1 pp). At the 0.88 composition rate this is about **2.7 pp/run**. The same subset already exists in code as `plan_delivery(by_gain=True)` with `SITE_STACKS="on"`.
- Atom (c), overlaps. 36 left-out keeps carry 336 standalone points (about 8.8 per row) in the 38 replayed rows. Their marginal gain lies between 0 and that figure.
- Floor: about 0 pp (repeats only). **Gap: about 2.7 pp/run measured (selection), plus an unmeasured overlap share with a ceiling of about 7.7 pp/run.** The 2.7 is a little optimistic, because the subset is chosen on noisy single looks [9].

**L6, combine below its best part.** The 12 rows break down into three atoms:
- **4 rows are curse (floor).** The best keep was applied alone and re-measured 0.1–0.8 pp lower, each below its row's floor (2.0–6.6). This is expected under [9]: 4 of the 5 rows where the best keep was applied alone came in lower.
- **7 rows are order (gap).** The best keep was blocked by a conflict with a higher-scored keep. The shortfalls are 1.5, 2.3, 11.7, 5.4, 10.8, 1.5 and 0.2 pp: 33.4 pp in total.
- **1 row is L7.** X2-D 43145496896 mistune lost 12.5 pp.

Floor: about 2 pp in total, about 0.03 pp/run. **Gap: about 0.53 pp/run.** This is the visible tip of L5(b), so do not add it to L5.

**L8, diminishing unique keeps per round.** Recapture share in round 2: 10 of 18 (X2-0), 8 of 18 (X2-D), 12 of 18 (X2-P). The per-run pool comes to N ≈ 5.9, 3.9 and 4.3 sites. A memoryless searcher predicts X2-D's round-3 unique keeps as 1.08 × (1 − 2.58/3.9) = 0.37; measured is 0.42.
- So the measured decay roughly matches memoryless re-sampling of a small pool. The "titles to avoid" memory buys little.
- Floor: the pool's exhaustion. X2-D had found 3.0 of about 3.9 sites by round 3.
- **Gap:** the re-found keeps (1.33 per X2-D run over rounds 2–3; 0.83 and 1.0 for X2-0 and X2-P) could at most become the remaining 0.9–1.9 unfound sites. At about 6.0 pp marginal per applied keep (mean standalone 6.8 × 0.88), that is **about 3–6 pp/run, central about 4**. This applies to multi-round arms, and is larger if N is underestimated [12]. It is the opportunity cost of L5(a), not an extra loss at combine.

**L10, edits confined to the hot function.**

Locality of the 284 kept diffs, mapped to functions by `ast`:

| Library | Functions per diff (median / mean) | Distinct functions | Diffs inside their own target function | Gain share of those diffs |
| --- | --- | ---: | --- | ---: |
| tomli | 1 / 1.3 | 8 | 41 of 53 | 70 % |
| sqlparse | 1 / 1.9 | 29 | 36 of 75 | 30 % |
| mistune | 1 / 1.9 | 22 | 29 of 80 | 25 % |
| markdown | 3 / 2.5 | 19 | 22 of 76 | 19 % |

So edits do reach callers, `__init__` and registration code. What stays confined is which *components* get edited. Against the manifest's cProfile:
- **tomli:** the whitespace helpers (`skip_comments_and_array_ws` 11 % and `skip_chars` 7 % of profiled time) have 0 kept diffs.
- **mistune:** emphasis finalisation (19 %) has at most 1 diff.
- **sqlparse:** `_group` (20 %) has 1 diff. Meanwhile `Lexer.get_tokens` (24 % of profile) takes 34 of 75 diffs and 56 % of standalone gain.
- **markdown:** the serializer (6 %) has 0 diffs, and about 34 % of profiled time is not named in the profile summary at all.

Pricing:
- The engine's kept edits remove about 20 % of the component they attack. For example, tomli's median delivered gain is +15.9 with `key_value_rule` at 83 % of profiled time.
- At that rate, the untouched components of 10 % share or more are worth about 2–4 pp each (about 2 for tomli, 3.8 for mistune, 4 for sqlparse; markdown unknown, up to about 7).
- Floor: at f ≈ 0.2 and the 2 % minimum gain, a component below about 10 % share cannot carry a provable single edit, about 1 pp/run (for example the markdown serializer, 6 % × 0.2 ≈ 1.2).
- **Gap: about 3 pp/run, range 1.5–5.** Ceiling, if the untouched components became free: 6–20 pp. These shares are inflated 2.8–3.4x by the profiler, so they are rough.

**Ranking by estimated gap (pp/run, central; confidence in brackets).** Rows outside my four are rough estimates of mine, and the other first-principles seats own their floors.

| Rank | Row | Gap | Basis |
| ---: | --- | ---: | --- |
| 1 | L9, spread between identical runs | about 10–20 (low) | Median-to-best spread per library (sqlparse median 24.3, best 43.9) against a tip measurement spread of ≤1.3 pp. It is search variance, recoverable only by a cross-run archive or union (seeds a and c). |
| 2 | L8, diminishing unique keeps | about 4 (3–6) (medium) | Capture–recapture above. |
| 3 | L10, edits confined to the hot function | about 3 (1.5–5) (low-medium) | Above. |
| 4 | L5, combine conflicts and repeats | about 2.7 measured, overlap ceiling 7.7 (medium-high) | Above. |
| 5 | L1, ideas that never become trials | about 1–3 (low) | Bounded by the same small visible pool as L8. |
| 6 | L3, trials lost to measurement noise | about 1.2 (low) | 47 trials ≈ 0.75 per run, half assumed real, × 3.8 × 0.88. |
| 7 | L4, failed confirmations | about 0.5–1 (low) | Mostly optimizer's curse, which is floor. |
| 8 | L6, combine below its best part | about 0.5 (high) | A symptom of L5(b); not additive with it. |
| 9 | L2, truncated leaps | about 0.4 (low) | 9 % of Opus leaps truncated × 2–3 leaps per run × about 0.3 keeps per leap × 6 pp. |
| 10 | L7, combine lost to noise | about 0.2–0.5 (medium) | 12.5 pp over 63 runs, plus about 20 pp if the inferred second failure is real. |

Overlaps: L5 and L6 share mechanism (b), and L5(a) and L8 are one mechanism seen at combine and at ideation.

## Sources

1. Amdahl, G. M. (1967). Validity of the single processor approach to achieving large scale computing capabilities. AFIPS SJCC 30, 483–485. https://doi.org/10.1145/1465482.1465560
2. Hennessy, J. L., & Patterson, D. A. (2017). *Computer Architecture: A Quantitative Approach*, 6th ed. Morgan Kaufmann. ISBN 978-0-12-811905-1. (Chapter 1, Amdahl's law.)
3. Gustafson, J. L. (1988). Reevaluating Amdahl's law. CACM 31(5), 532–533. https://doi.org/10.1145/42411.42415
4. Hill, M. D., & Marty, M. R. (2008). Amdahl's Law in the Multicore Era. IEEE Computer 41(7), 33–38. https://doi.org/10.1109/MC.2008.209
5. Bentley, J. (2000). *Programming Pearls*, 2nd ed., Column 6 "Perspective on Performance". Addison-Wesley. ISBN 0-201-65788-0. https://www.oreilly.com/library/view/programming-pearls-2nd/9780134498058/ch06.html (seen via search summary only)
6. Appel, A. W. (1985). An Efficient Program for Many-Body Simulation. SIAM J. Sci. Stat. Comput. 6(1), 85–103. https://doi.org/10.1137/0906008 (factor 400 for N = 10,000, from the abstract via search summary)
7. Knuth, D. E. (1971). An empirical study of FORTRAN programs. Software: Practice and Experience 1(2), 105–133. https://doi.org/10.1002/spe.4380010203 (full text not accessed: fetch blocked. The comp.compilers discussion at https://compilers.iecc.com/comparch/article/04-01-059 notes that the oft-quoted 90 % figure comes from one example and many examples sit around 50 %.)
8. Curtsinger, C., & Berger, E. D. (2015). Coz: Finding Code that Counts with Causal Profiling. SOSP '15, 184–197. https://doi.org/10.1145/2815400.2815409 ; https://arxiv.org/abs/1608.03676 (numbers from search summaries of the abstract; full text not fetched)
9. Smith, J. E., & Winkler, R. L. (2006). The Optimizer's Curse: Skepticism and Postdecision Surprise in Decision Analysis. Management Science 52(3), 311–322. https://doi.org/10.1287/mnsc.1050.0451 (2007 correction to Fig. 3: https://jimsmith.host.dartmouth.edu/wp-content/uploads/2022/04/pds_correction.pdf)
10. Siegmund, N., Kolesnikov, S. S., Kästner, C., Apel, S., Batory, D., Rosenmüller, M., & Saake, G. (2012). Predicting Performance via Automated Feature-Interaction Detection. ICSE 2012, 167–177. https://www.se.cs.uni-saarland.de/publications/docs/ICSE2012.pdf
11. Chapman, D. G. (1951). Some properties of the hypergeometric distribution with applications to zoological sample censuses. University of California Publications in Statistics 1, 131–160. (Citation confirmed via search; text not accessed.)
12. Chao, A. (1987). Estimating the population size for capture-recapture data with unequal catchability. Biometrics 43(4), 783–791. https://doi.org/10.2307/2531532 (not accessed; details from memory, so confirm before relying on it)
13. Python Software Foundation. *The Python Profilers* (`profile`/`cProfile`, including "Calibration"). https://docs.python.org/3/library/profile.html
14. Archive (read-only): `w2-sprint/live/` (63 run × library rows, patches), `w2-sprint/zero-credit/` (`pairs.csv`, `q2_rounds.csv`, R labels in `perrun.py`), `w2-sprint/o62/replay.md`, `services/python_agents/tests/fixtures/live_oss/manifest.json` (cProfile summaries and upstream pins), `orchestrator/combine_node.py` (`plan_delivery`, `SITE_STACKS`).
