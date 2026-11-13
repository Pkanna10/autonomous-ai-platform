# fp-measure: first principles (atoms, error budgets, noise floors)

*Access note.* This session's network blocks page fetches: arxiv.org, kar.kent.ac.uk and www.iso.org do not resolve. So every source below was checked through web-search extracts (bibliographic data, abstracts, quoted passages), not by reading the full text. Where a claim rests on a secondary summary I say so. Numbers marked **[computed]** are mine. They come from the read-only archive (`w2-sprint/floors/trials.csv`, `combine_ratios.csv`, `runs.csv`, `live/*.jsonl`, `o62/replay.md`), using `python3 -I` scripts in `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/fp-measure/` (`a1.py`, `fit.py`, `fit2.py`, `post.py`, `l79.py`, `l6.py`). Nothing was written into the repository.

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **JCGM 100:2008 (GUM)** [1]. Type A and Type B uncertainty, the standard deviation of the mean, the law of propagation (root-sum-of-squares of independent components), expanded uncertainty with a coverage factor k, and the warning about correlated observations (4.2.7). It is the international metrology standard, and an uncertainty budget is its central tool.
2. **Taylor & Kuyatt, NIST TN 1297 (1994)** [2]. NIST's operational version of the GUM: Type A/B, combined and expanded uncertainty. It is the standard US lab practice.
3. **Kalibera & Jones, ISMM 2013** [3]. Repetition at several levels (VM, process, iteration), with a cost model that picks the number of repetitions at each level, and effect-size confidence intervals. It is the reference method for benchmark repetition design.
4. **Georges, Buytaert & Eeckhout, OOPSLA 2007** [4]. Confidence intervals in place of "best of N", with a worked case where best-of-30 reverses the verdict. It is the canonical "statistically rigorous" performance paper.
5. **Mytkowicz et al., ASPLOS 2009** [5]. Measurement bias from environment size and link order; none of 133 surveyed papers handled it adequately; setup randomisation and causal analysis as remedies. It is the standard reference on bias as distinct from noise.
6. **Chen & Revels 2016** [6]. Timing noise modelled as additive delays, so a minimum-type estimator is robust; it underlies Julia's BenchmarkTools. It is the standard on robust estimators under OS jitter.
7. **Laaber, Scheuner & Leitner, EMSE 2019** [7]. Cloud benchmark noise has a coefficient of variation from 0.03 % to over 100 %. Running test and control on the same instance in random order still detects slowdowns of 10 % or less. It is the standard empirical study of noise on shared VMs, which describes the engine's GitHub runners.
8. **van Belle, *Statistical Rules of Thumb*, 2nd ed. (2008), Lehr's rule** [8], with the Kohavi/Longbotham form [9]. n ≈ 16σ²/δ² per group for two-sided α = 0.05 and 80 % power. It is the standard minimum-detectable-effect (MDE) atom.
9. **Ioannidis, *Epidemiology* 2008** [10]. When a discovery is defined by crossing a threshold in an underpowered study, the observed effect is expected to be inflated (the "winner's curse"). It is the standard statement of selection inflation.
10. **Efron, JASA 2011** [11]. Tweedie's formula, an empirical-Bayes correction for selection bias among many estimated means. It is the standard de-biasing tool.
11. **Skol et al., *Nature Genetics* 2006** [12]. In two-stage studies, a joint analysis of both stages is almost always more powerful than requiring stage 2 to replicate stage 1, even with a stricter threshold. It is the standard result on how to combine two looks.

Also used: Harter's range constants (d2) [13], Jennison & Turnbull on group-sequential designs [14], and Mahajan on estimating by splitting a quantity into atoms [15].

## Notes (the methods and results, cited inline as [n])

**1. A floor is a budget of atoms.** The GUM [1][2] prices each independent source of uncertainty as a standard uncertainty and combines them in quadrature. Fermi-style estimation [15] uses the same decomposition. For a speed trial the atoms are:
- (a) per-run noise σ;
- (b) runs per side n;
- (c) the test statistic, which sets how many standard errors (SE) the threshold sits at;
- (d) the minimum effect of interest (the engine's 2 % clamp);
- (e) the number of looks and how they are combined.

The floor of any loss stage is whatever these atoms force on a *correct* engine at the same budget of runs.

**2. Standard error, not spread.**
- The Type A uncertainty of a mean is s/√n [1]. For a difference of two independent 5-run means it is s·√(2/5) = 0.632 s.
- The engine's trial floor is 2·max(sd_A, sd_B), an expanded uncertainty with k = 2 applied to *single runs*, not to the means (`anticheat.py:207-217`).
- **[computed]** In SE units that threshold sits at 2/0.632 = 3.16 SE. For a normal null that is a one-sided false-pass rate near 0.08 % per look, before the max over two sides and the volatility of s are counted.
- Lehr's rule [8][9], inverted, gives MDE = 4σ/√n per group, which is 1.79σ at n = 5.
- **[computed]** The engine's 80 %-power MDE is about 2σ + 0.84·0.632σ = 2.53σ. That is 1.41 times Lehr's MDE. Since n scales with MDE², the rule behaves as if it threw away about half of its timed runs.

**3. The spread estimate itself is noisy at n = 5.**
- For normal data the relative sd of s is about 1/√(2(n−1)), about 35 % at n = 5. This is a textbook result. The search extract confirmed it from memory, not from the GUM's own table, so treat it as unverified against [1].
- The chi-square interval for s/σ with 4 degrees of freedom is 0.42 to 1.54 (90 %), matching `floors/README.md` s4.
- GUM 4.2.4 [1] recommends a *pooled* sd from a process under statistical control over the per-measurement s. That is the metrology case for a calibrated or pooled floor over a fresh 5-run sd.

**4. Noise on VMs is heavy-tailed and positive.**
- Chen & Revels [6] model jitter as additive delays, so minimum or robust statistics are stable. This rests on secondary summaries; the paper's text could not be fetched.
- Laaber et al. [7] measure coefficients of variation over three orders of magnitude across cloud instances. They recover sensitivity by running both arms on the same instance in random order, which is what ABBA does.
- The archive's best-fitting model (about 0.4 % Gaussian noise plus a rare 5-20 % slow run) reproduces the observed 18 % of trials above 1.5x (`floors/sim.csv`, outlier rows: 16.7-18.7 %).

**5. Bias is not noise.** Mytkowicz et al. [5] show that setup changes such as environment size or link order shift results systematically; more repetitions do not remove that. Randomising the setup turns the bias into variance that can be measured. Kalibera & Jones [3] price repetition at each level: when between-VM variance dominates, extra runs inside one VM buy little.

**6. Selection inflates first looks.**
- A result kept because it crossed a threshold is biased upward, most strongly when power is low [10].
- Efron's empirical Bayes [11] corrects this from the distribution of all estimates. I used its nonparametric form: a grid prior fitted by EM to all 972 trial gains.
- **[computed]** The fitted prior puts 18-23 % of true gains at or below 0, 34-38 % in 0-2 %, 21-23 % in 2-5 %, 16 % in 5-10 % and 5 % above 10 %.

**7. Two looks: joint beats replication.**
- Skol et al. [12] show that requiring stage 2 to replicate stage 1 on its own loses power. Pooling both stages is almost always more powerful at the same error rate.
- Group-sequential designs [14] formalise multi-look thresholds.
- The engine's confirmation is replication-based: each look must clear its own floor (`confirm.py`).

**8. Range of k identical draws.** The expected range of k normal draws is d2(k)·σ, with d2(16) = 3.532 [13]. This gives the measurement-only floor for the spread between identical runs.

**Well established:** notes 2, 3, 6 and 7, the GUM atoms, and same-machine randomised pairing. **Contested:**
- whether the mean, the median or the minimum is the right timing estimator ([6] argues for the minimum; [4] uses means with confidence intervals);
- how much VM-level noise cancels in a paired difference. My fit in L3/L4 below suggests the high floors are partly real noise in the gain.

## Bearing on the ledger (per row you touch: L#, what your field says, numbers)

- **L3, L4 (statistic and looks).** The threshold is 3.16 SE per look, the MDE is 1.41x Lehr's, and each look must clear on its own. Notes 2, 6 and 7 apply directly.
- **Fit of the per-look gain noise from confirmation outcomes [computed].**
  - Confirmation failure rate by first-look gain/floor ratio:

    | Gain/floor | Failed | Rate |
    | --- | --- | --- |
    | 1-1.25 | 25 of 54 | 46 % |
    | 1.25-1.5 | 13 of 44 | 30 % |
    | 1.5-2 | 10 of 67 | 15 % |
    | 2-3 | 1 of 75 | 1 % |
    | 3+ | 0 of 93 | 0 % |

  - An empirical-Bayes model with per-look gain sd k·floor fits best at k = 0.35-0.40 for trials at the calibrated floor, which is 0.7-0.8 points at a 2 % floor. The model predicts 26, 14, 12, 1.5 and 0 failures in the five bins.
  - For trials whose floor is above 1.2x the calibrated floor, k = 0.2-0.4 fits (best 0.3; k = 0.1 is rejected: log-likelihood −65 against −23).
  - If both sides had independent noise at sd = floor/2, k would be 0.316.
  - **Caveat:** the second look's own floor is not recorded, so its volatility is folded into k.
- **L6 (winner's curse).** Of the 12 runs whose combine fell below the best single keep, 8 have a shortfall of 2.3 points or less. That is within about 2 sd of the difference of two looks (√2 × 0.7-0.8 points). The best keep is a maximum of selected first looks [10].
- **L7.** Combine margins are large, so the floor is about one failure in 63 (see below).
- **L9.** Measurement explains at most (0.7/5.5)², under 2 %, of the variance between identical runs [computed].

## Floors (L3, L4, L7, L9) and ranking

**Definition used.** A correct engine is one with the same timed-run budget, a statistic matched to the noise (SE-based, pooled over looks), the 2 % minimum effect kept, and a false-keep rate that stays near zero. Its floor is the correct rejections (true gain at or below 2 %) plus the real gains it still misses.

**L3, trials lost to noise (47).**
- Atoms: own floor median 6.6 %, calibrated floor 2.4 %, n = 5, threshold 3.16 SE.
- Posterior [computed]: E[number with true gain above 2 %] = 29-32 of 47, posterior mean gain 2.9-3.3 %. So 15-18 are correct rejections.
- A correct engine gives one more look to every trial whose gain lies between the floors and keeps on the pooled mean at α = 0.01 one-sided, with the 2 % clamp. It keeps:
  - 22-33 of the 47 if the high noise was real (k = 0.2-0.3);
  - 36-40 if the second look is quiet.
- **Floor ≈ 15-28 (central 20). Gap ≈ 19-32 trials (central 27); at most about 1.2 points per run if additive.**

**L4, failed confirmations (49).**
- Atoms: first-look margin median 0.5 points over a floor of about 2.1 %, per-look sd 0.7-0.8 points, and a rule that needs both looks to clear.
- Posterior: E[number above 2 %] = 36-39 of 49, posterior mean 3.4-3.5 %. So 10-13 are correct rejections.
- Simulation from the fitted prior, per 974 trials: the current rule loses 31-37 real gains (true gain at least 2 %); a pooled rule (mean of the two looks above the floor) loses 15-17. Both keep fewer than 0.01 trials whose true gain is at or below 0 (the simulation did not count keeps whose true gain is 0-2 %). This is the effect Skol et al. [12] describe.
- **Floor ≈ 10-13 + 17-18 ≈ 27-31. Gap ≈ 18-22 trials; at most about 1.1 points per run.**

**L7, combine lost to noise (1 of 63).**
- Expected failures = Σ Φ((F − G)/(k·F)) over the combines, with k = 0.3-0.4 [computed].
- That gives 1.0-1.25 failures at the recorded combine floors, or 0.4-0.6 if the run's calibrated floor were used.
- **Floor ≈ 0.4-1.2. Gap ≈ 0-0.6 combines, about 0-0.1 points per run.**

**L9, spread between identical runs.**
- Measurement atom: the per-look sd of a combine is 0.58 points on a quiet VM (pooled from the replay's three looks per tip) and about 0.7-0.8 points in-run.
- Floor of the range over 16 runs = d2(16) × σ = 3.532 × 0.58-0.8 ≈ 2.0-2.8 points [13]. Floor of the sd ≈ 0.6-0.8 points.
- Observed delivered sd and range [computed]:

  | Library | sd (points) | Range (points) |
  | --- | --- | --- |
  | sqlparse | 8.7 | 29.3 |
  | mistune | 6.2 | 23.7 |
  | tomli | 5.6 | 18.6 |
  | markdown | 5.7 | 15.6 |

- **Gap ≈ 13-27 points of range.** The median run trails the best identical run by 7.6-19.6 points. Almost all of this is search variance, not measurement.

**Ranking by estimated gap (mine; units differ, so a range is given where it can be priced):**

| Rank | Row | Estimated gap | Basis |
| --- | --- | --- | --- |
| 1 | L9 | 13-27 points of range; median run 7.6-19.6 points behind the best identical run | composite of L1, L5 and L8 (search), not an independent stage |
| 2 | L5/L8 | about 36 distinct-change conflicts (57 minus 21 repeats; repeats are the floor), about 0.9 per run; at most about 6 points per run if additive at the keeps' posterior mean of 6.9 %, likely far less | `zero-credit` s1 |
| 3 | L1 | about 55 ideas in 4 runs (floor = 24 duplicates + 31 ungrounded, if those labels are right); value unpriced and capped by L8's diminishing unique keeps | fate counts |
| 4 | L3 | about 27 trials (19-32), at most about 1.2 points per run | above |
| 5 | L4 | about 20 trials (18-22), at most about 1.1 points per run | above |
| 6 | L6 | 3 runs beyond the noise floor (shortfalls 5.4, 10.8, 11.7; the 12.5 is L7's failure), about 0.44 points per run | `live/` |
| 7 | L2 | floor 0 (a token cap is a setting); 3 of 32 plus 1 of 6 calls; small | o62 |
| 8 | L7 | about 0-0.6 combines, about 0.1 points per run or less | above |
| – | L10 | unmeasured, so unranked | |

## Open questions for the seminar

1. Is the high-floor noise shared, so that it cancels in the gain? The confirmation fit (k ≈ 0.3 ≈ 0.316) says it is mostly real, which weakens the premise of the paired floor (`floors/README.md` fix A). Only the per-side samples and each look's floor can settle it.
2. Would a pooled two-look rule [12][14] at a matched false-keep rate recover the roughly 15-20 trials of L4 that the simulation predicts? It is testable offline only once the second looks' gains are archived.
3. Mean, minimum or median [4][6] for this engine's heavy-tailed noise?
4. L9: how much of the run-to-run spread does a union of proven diffs across runs (reviewer seed a) remove?
5. My mean L6 shortfall is 4.0 points over 12 runs, against the ledger's 3.28. The definition of "best keep" probably differs.

## Sources (numbered list, full citations with URL or ISBN)

1. JCGM (2008). *Evaluation of measurement data: Guide to the expression of uncertainty in measurement*, JCGM 100:2008. https://www.iso.org/sites/JCGM/GUM/JCGM100/C045315e-html/C045315e_FILES/MAIN_C045315e/04_e.html (read only through search extracts; fetching was blocked).
2. Taylor, B. N., & Kuyatt, C. E. (1994). *Guidelines for Evaluating and Expressing the Uncertainty of NIST Measurement Results*, NIST TN 1297. https://doi.org/10.6028/NIST.tn.1297
3. Kalibera, T., & Jones, R. (2013). Rigorous benchmarking in reasonable time. ISMM '13, 63-74. https://doi.org/10.1145/2464157.2464160 (abstract only).
4. Georges, A., Buytaert, D., & Eeckhout, L. (2007). Statistically rigorous Java performance evaluation. OOPSLA '07, 57-76. https://doi.org/10.1145/1297027.1297033
5. Mytkowicz, T., Diwan, A., Hauswirth, M., & Sweeney, P. F. (2009). Producing wrong data without doing anything obviously wrong! ASPLOS '09, 265-276. https://doi.org/10.1145/1508244.1508275
6. Chen, J., & Revels, J. (2016). Robust benchmarking in noisy environments. arXiv:1608.04295. https://arxiv.org/abs/1608.04295 (claims about the minimum come from secondary summaries).
7. Laaber, C., Scheuner, J., & Leitner, P. (2019). Software microbenchmarking in the cloud. How bad is it really? *Empirical Software Engineering* 24(4), 2469-2508. https://doi.org/10.1007/s10664-019-09681-1
8. van Belle, G. (2008). *Statistical Rules of Thumb*, 2nd ed., Wiley, ch. 2 (Lehr's equation); checked through https://rstudio-pubs-static.s3.amazonaws.com/201750_c17bc51d8553452d997ba4d258b0249f.html and https://www.columbia.edu/~cjd11/charles_dimaggio/DIRE/styled-4/code-12/ (ISBN not verified).
9. Zhou, Lu & Shallah (2023). All about sample-size calculations for A/B testing (gives n ≈ 16σ²/δ², after Kohavi and Longbotham). arXiv:2305.16459. https://arxiv.org/abs/2305.16459
10. Ioannidis, J. P. A. (2008). Why most discovered true associations are inflated. *Epidemiology* 19(5), 640-648. https://pubmed.ncbi.nlm.nih.gov/18633328/
11. Efron, B. (2011). Tweedie's formula and selection bias. *JASA* 106(496), 1602-1614. https://doi.org/10.1198/jasa.2011.tm11181
12. Skol, A. D., Scott, L. J., Abecasis, G. R., & Boehnke, M. (2006). Joint analysis is more efficient than replication-based analysis for two-stage genome-wide association studies. *Nature Genetics* 38, 209-213. https://doi.org/10.1038/ng1706
13. Harter, H. L. (1960). Tables of range and studentized range. *Annals of Mathematical Statistics*; d2(16) = 3.532 as tabulated at https://support.minitab.com/minitab/help-and-how-to/quality-and-process-improvement/control-charts/how-to/time-weighted-charts/ewma-chart/methods-and-formulas/unbiasing-constants-d2-d3-and-d4
14. Jennison, C., & Turnbull, B. W. (1999). *Group Sequential Methods with Applications to Clinical Trials*. Chapman & Hall/CRC. ISBN 978-0-8493-0316-6 (not read; cited for the design class only).
15. Mahajan, S. (2010). *Street-Fighting Mathematics*. MIT Press (open access). ISBN 978-0-262-51429-3 (not read; cited for the method only).
