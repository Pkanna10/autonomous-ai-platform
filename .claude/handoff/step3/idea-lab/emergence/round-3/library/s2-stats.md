# s2-stats: benchmarking and measurement statistics

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **Kalibera and Jones, "Rigorous Benchmarking in Reasonable Time", ISMM 2013 [1].** Multi-level experiments (iteration, execution, build), variance components per level, optimal repetition counts, and the Fieller confidence interval for a ratio of times. It is the standard cost-aware design method. The companion tech report [2] (abstract read only) gives the derivations.
2. **Georges, Buytaert and Eeckhout, "Statistically Rigorous Java Performance Evaluation", OOPSLA 2007 [3].** Confidence intervals over independent invocations, ANOVA and Tukey HSD, and how often "best of N" style reporting misleads. It is the founding paper on rigour in this field.
3. **Mytkowicz, Diwan, Hauswirth and Sweeney, "Producing Wrong Data Without Doing Anything Obviously Wrong!", ASPLOS 2009 [4].** Setup-induced measurement bias, and setup randomization as the cure. I could not reach the full text; its numbers below come from [1] and [5], and its claims from the abstract.
4. **Curtsinger and Berger, "STABILIZER", ASPLOS 2013 [5].** Re-randomizing the memory layout at run time turns layout bias into Gaussian noise. It is the canonical answer to [4].
5. **Bulej et al., "Duet Benchmarking", ICPE 2020 [6].** Paired, synchronized A/B measurement on shared cloud machines. It is the direct evidence on when pairing helps.
6. **Barrett et al., "Virtual Machine Warmup Blows Hot and Cold", OOPSLA 2017 [7].** Changepoint analysis (PELT) of benchmark time series, and how unreliable steady-state heuristics are.
7. **Daly et al., ICPE 2020 [8], and Fleming et al., "Hunter", 2023 [9].** E-divisive changepoint detection over noisy continuous-integration performance histories. These are the industrial references.
8. **Chen and Revels, "Robust benchmarking in noisy environments", 2016 [10].** A model of noise in which delays only ever add time, and the case for the minimum as the location estimator.
9. **The pyperf [11] and pytest-benchmark [12] documentation (code read at commit).** What the Python tooling actually does.
10. **The NIST/SEMATECH e-Handbook on CUSUM [13], plus tertiary statistics pages [14][15].** CUSUM design, relative efficiencies and robust scale estimators.

## Notes

**Levels of variation, and where to repeat.**
- Kalibera and Jones sort the variables of an experiment into three kinds [1, s3]:
  - controlled;
  - random;
  - uncontrolled: fixed during a run but outside your control. These cause bias, and must be turned into controlled or random variables.
- Repetition is needed "at least … at the highest level that has random variation"; repeating at lower levels only saves time [1, s3].
- From an initial experiment (20 to 30 repetitions a level) they estimate an unbiased variance component T²ᵢ per level. The optimal count at level i is r_i = ⌈√(c_{i+1}·T²ᵢ / (c_i·T²_{i+1}))⌉, where c is the cost of one repetition at that level [1, eq. 3, s9].
- They recommend dimensioning once per benchmark, VM and platform, and again only if the platform changes [1, s9.3].
- They report changes as an effect size with a confidence interval (for example "5.5% ± 2.5% at 95%"), not as a bare significance test. Their reasons: significance tests "confuse sample size and practical relevance", and the test of whether two intervals overlap has an unknown error rate (below 1%, not 5%, for two 95% intervals) [1, s4].
- Their survey: 71 of 90 papers that measured execution time gave no measure of variation [1, s1].

**Independent repetitions, and how plain reporting misleads.** Georges et al. [3, s4]:
- Each VM invocation is treated as one independent observation. Steady-state iterations within an invocation are averaged, and the confidence interval is taken across invocations, "because iterations within a single VM invocation are not independent".
- Steady state is detected when the coefficient of variation over a window of k=10 iterations falls below 0.01-0.02.
- Typical coefficient of variation is around 2%. The gap between the fastest and slowest run is around 8% at start-up and 20% at steady state [3, s5].
- "Best", "mean" and "median of a few invocations" methods were misleading in up to 16% of comparisons, and drew the opposite conclusion in more than 3% for some methods [3, s6].

**Measurement bias.**
- Mytkowicz et al. find that innocuous setup choices bias results "in all architectures … all compilers … all SPEC CPU2006 C programs" they tried. None of the 133 papers they surveyed handled this. Their remedies are causal analysis and setup randomization [4, abstract].
- Reported effects of the setup:
  - the size of the environment variables can change performance by up to 300% [5, s1, citing 4];
  - the median gain reported in the field is about 10% [1, s1, citing 4];
  - STABILIZER's own measurement: link order alone, up to 57% [5, s1].
- Kalibera and Jones repeated the link-order experiment at SPEC's full reference input sizes and found the effect "very small". They also caution that STABILIZER may add more variation than real systems show [1, s2].

**Randomization makes the noise Gaussian.**
- STABILIZER re-randomizes the code, stack and heap layout every 500 ms. The execution time is then a sum over many independent layouts, so the central limit theorem applies ("30 is typical") [5, s2].
- With 30 runs a configuration and ANOVA within subjects, LLVM -O2 against -O1 gives F=3.235, p=0.0898 (significant only at 90%). -O3 against -O2 gives F=1.335, p=0.264: indistinguishable from noise. The median overhead is 6.7% [5, s6].
- Their point about multiplicity: 36 t-tests at α=0.05 give 1.8 false positives expected by chance [5, s6.1].

**Pairing works only when the noise is shared.**
- Duet runs A and B at the same moment on two virtual cores behind a barrier. Each pair yields a ratio; the ratios are averaged geometrically and a bootstrap interval is taken [6, s3].
- Gains in accuracy: 2.3x to 12.5x (5.03x on average) on ScalaBench and DaCapo, and 23.8x to 82.4x on SPEC CPU 2017 [6, abstract].
- The control experiment is the decisive one: they shuffled the pairs so that ratios came from unrelated measurements. The gain fell to 1.02x and 1.03x. The whole benefit is synchronized interference [6, s4.2].

**Changepoints and CUSUM.**
- Barrett et al. run PELT (cpt.meanvar, penalty 15·log n) on each process's iteration series. They classify each as flat, warmup, slowdown or no steady state. At most 43.5% of (VM, benchmark) pairs consistently reached a steady state of peak performance [7, abstract, s4]. CPython was not among the VMs studied; PyPy was.
- They note that simple steady-state heuristics give false positives and false negatives [7, s4.2, citing 1]. Kalibera and Jones found the DaCapo and Georges coefficient-of-variation heuristics "often lead to either too few … or far too many" iterations [1, s2].
- MongoDB replaced static thresholds with E-divisive means, which needs no distributional assumption and tests by permutation. Its false-positive rate "dramatically dropped". Their noise is up to 10% between runs, and 20% or more on sensitive tests [8, abstract, s1-3].
- Hunter replaced the permutation test with a Student t-test, for speed and determinism [9, s3].
- CUSUM (Page; the 1954 original not accessed) is the classic detector of shifts of 2σ or less. With δ the shift to detect, k=δσ/2 and h is set from α and β [13].

**Robust estimators.**
- Chen and Revels model timing error as a sum of non-negative delays. The minimum then minimizes the error, and its spread across trials is unimodal, while the median and trimmed mean keep the bimodality [10, s4B].
- pytest-benchmark's FAQ: with poor isolation, use the IQR and median; "IQR is often better than StdDev". Its defaults are at least 5 rounds, sorting by min, and failure rules like `--benchmark-compare-fail=min:5%` [12].
- pyperf offers median ± MAD when results are unstable [11, analyze.rst].
- MAD is 37% as efficient as the sd at the Gaussian, with a 50% breakdown point. Sₙ is 58% efficient. Qₙ is given as 82% or 88% on the same tertiary page, which contradicts itself, so this is unresolved [15].

**What pyperf does.**
- It spawns 20 worker processes, each with 1 warm-up and 3 values, so 60 values. `--fast` gives 10×2 and `--rigorous` 40×3 [11, runner.rst].
- The number of processes must be "large enough to reduce the effect of … ASLR and the Python randomized hash function" [11, run_benchmark.rst]. This is Mytkowicz's point, applied to Python.
- It warns when sd ≥ 10% of the mean (`_cli.py`).
- `compare_to` uses an unpaired two-sample t-test at 95% (`_utils.is_significant`) and treats all values as independent. Kalibera and Jones and Georges would object to that, because values within one process are not independent.

**Power of sign and rank tests.**
- The asymptotic relative efficiency of the sign test is 2/π ≈ 0.637 against the t-test and 0.67 against Wilcoxon, both at the normal. It is 2.0 against t for heavy (double-exponential) tails [14a].
- Mann-Whitney's efficiency against t is 3/π ≈ 0.955 at the normal [14b, citing Lehmann 1999].
- Exact small-sample facts (my arithmetic): with 5 pairs, the smallest two-sided p is 2/32 = 0.0625 for both the sign test and the signed-rank test. Neither can reach 0.05 within one five-pair look.

**Well established:** independent repetition at the top level that varies; effect sizes with intervals; setup bias, and randomization against it; pairing helps exactly as far as the noise is shared [6]; statistics on sd are fragile under heavy tails.

**Contested:**
- how large layout bias is at realistic sizes ([4][5] against [1]);
- the minimum as estimator: [10] argues for it, Georges et al. show "best of" misleads [3], and pyperf moved to mean ± sd [11];
- t-based tests against nonparametric ones on timing data [3][9].

## Bearing on the ledger

**L3 (trials lost to noise) and `floors/README.md` proposal A, the paired floor.**
- **Literature verdict: sound in principle, with four conditions.**
  1. **It helps only if the noise in A_k and B_k is correlated** [6, s4.2]. The engine's pairs are sequential, adjacent ABBA launches, not simultaneous, so only slow, minute-scale VM state is shared. The README's time-since-start gradient (27% → 10% of trials above 1.5x) suggests such slow noise; this is not proven. Record-only field 2 (per-side samples) lets ρ = corr(A_k, B_k) be estimated offline.
     - *Kill criterion: median ρ ≤ 0.3 across trials.*
  2. **Set k from a stated error rate, not "so a steady machine reads 1.0x".**
     - My simulation (5 pairs, Gaussian noise, `work/s2-stats/floors.py`, `floors2.py`): today's rule, 2·max(sd_A, sd_B), has a false-keep rate of 0.0034 per look at ρ=0, and its power is 0.39 at a true gain of 2σ.
     - Paired, with k = t₀.₉₅,₄ = 2.132: false-keep rate 0.049, power 0.83 at ρ=0, 0.975 at ρ=0.5 and ≈1.0 at ρ=0.9.
     - At a *matched* false-keep rate of 0.0034, the paired floor is weaker at ρ=0 (power 0.20 against 0.39), because a t with 4 degrees of freedom has a critical value of 5.22.
     - So the gain needs both a conventional α per look and shared noise.
     - The engine already confirms with a second look. Two independent looks at α=0.05 give about 0.0025 overall. At 2σ, power falls to 0.83² ≈ 0.68, against 0.39² ≈ 0.15 for today's rule over its two looks.
  3. **The estimate of sd(d) stays volatile.** With 4 degrees of freedom, its 90% range is 0.42 to 1.54 of the true value; I confirmed by simulation the README's figures. Pairing removes the bias from taking the larger of two sides, not this volatility.
  4. **The ABBA order alternates.** Each d_k therefore carries a ± order effect, with 3 AB pairs against 2 BA. Classic 2×2 crossover analysis estimates the period effect and removes it (Wikipedia, "Crossover study", on balance and carry-over; Jones and Kenward not accessed).
- **Status this round:** the floor is in `anticheat.noise_floor`, and the round-3 brief lists anticheat and the judges as **FIXED**. Proposal A is therefore not proposable here. The README itself calls it a judge change and the owner's call. Its record-only fields can still be evaluated offline.
- **Fixes B (settle) and C (robust spread):**
  - The literature replaces "2 sd < 2% for two blocks" with a changepoint or CUSUM test on the A/A probe stream [7][13]. Heuristic steady-state detectors misfire both ways [1, s2][7].
  - The README's best-fitting noise model (about 0.4% noise with 2-5% of runs slowed by 5-20%) is the positive-delay model of [10]. The sd has breakdown 0, so one slow run moves the floor. The median, MAD or minimum are robust (MAD at 37% efficiency [15]), but at n=5 MAD is coarse.

**L4 (failed confirmations).** Regression to the mean is the default explanation; this is my derivation, not a sourced claim.
- A trial whose true gain equals the floor passes each look with probability about 0.5. Selecting on a first-look pass then guarantees some second-look failures.
- Here 49 of 333 first-look passes failed (284 keeps plus 49), or 15%.
- Separating that from noise that differs between looks needs the per-look timestamps and samples (record-only fields 1 and 2).

**L7 (combine lost to noise).**
- The combine re-test is the same paired design, so condition 1 above applies.
- The replay moved each tip by at most 1.3 points over three looks against quiet floors, so a quiet look's variance at the delivered level is small.
- Kalibera and Jones's rule: re-measure at a level, or a moment, whose noise is independent of the failed look. An immediate in-run re-measure meets the same VM state, a correlated repeat. That limit is already stated in `o62/replay.md`.

**L9 (spread between identical runs): a variance-components reading [1].**
- X2-D's delivered gain over 20 runs has a per-library sd of 4.25 (tomli), 10.86 (sqlparse), 9.22 (mistune) and 4.83 (markdown) points; pooled 7.81.
- The quiet replay's look-to-look sd is about 0.15 to 0.75 points.
- Measurement is therefore under 1% of the variance at the run level (≈0.35/61). The spread comes from the stochastic search, not the timer.
- With a combine look at c₁ ≈ 13 s and a run at c₂ ≈ 2,400 s, eq. 3 gives r₁ = ⌈√(2400/13 × 0.0057)⌉ = ⌈1.03⌉ = 2.
- So more looks at a delivered tip buy nothing. Only more runs narrow an arm comparison.
- Kalibera and Jones's premise of dimensioning once fails on GitHub runners: each run is a new VM, an uncontrolled variable [1, s3]. Recording the CPU model (field 5) makes it a blocking factor.

**The smallest effect X2-DT can detect.** The rule is pre-registered in `stacked-plan.md` s1 and implemented in `ideas_x2_report.sign_call`:
- each X2-DT run's sign against its library's X2-D lower median;
- the null re-deals each library's 10 values into 5 and 5, so the libraries are convolved;
- two-sided p ≤ 0.10, and a higher median on at least 3 of 4 libraries.

*The exact null* (`work/s2-stats/power.py`, continuous data, no ties):
1. Per library, over C(10,5)=252 splits, the sign sum S_l is ±5, ±3, ±1 with counts 21, 45, 60 each. Var S_l = (2·21·25 + 2·45·9 + 2·60·1)/252 = 7.857, against 5 under independence. Sharing a 5-draw median costs a design effect of 1.57.
2. Convolved over 4 libraries (252⁴ = 4,032,758,016 splits), S is even:
   - P(S ≥ 10) = 0.0540, two-sided 0.108 (fails);
   - P(S ≥ 12) = 0.0233, two-sided 0.0465 (passes).
3. **The bar is S ≥ 12, that is at least 16 of the 20 X2-DT runs above X2-D's medians.** A naive binomial would need 15 (P(X ≥ 15) = 0.0207, two-sided 0.041).
4. The real one-sided size is 0.023 against a nominal 0.05, so discreteness wastes half the α.

*Power* (location shift; 20,000 simulations a point; "the medians on 3 of 4 libraries" never bound):

| Model of the effect | 50% power | 80% power |
| --- | --- | --- |
| Normal noise, shift in each library's sd | ≈0.85 sd | ≈1.2 sd |
| Common shift at X2-D's sds | +5.4 points | ≈+8 points (0.806 at +8) |
| Bootstrap from X2-D's own residuals | — | +7.5 points (0.717 at +6, 0.835 at +8) |

- Against X2-D's median of +18.6, **X2-DT must add about 8 points (about 43% more delivered gain) to be detected 4 times in 5.**
- A plausible stacking effect of 2 to 4 points is detected 11 to 32% of the time.
- With the same data, a stratified rank-sum test (exact null, critical W ≥ 127, size 0.042 one-sided) reaches 80% at about +5.5 points (0.842 at +6). That is consistent with the efficiency ratio 0.637/0.955 [14].
- The rule is pre-registered and stays as it is. This note only says what it can see.

## Open questions for the seminar

1. Is ρ(A_k, B_k) high in the live records? That decides whether proposal A has value beyond changing α. It could also be tested on the X2-SV or replay samples, if they are archived.
2. Do A and B run from directories whose paths, environments or `sys.path` differ in length? That is the bias of Mytkowicz et al. [4]. pyperf's answer is many processes, and PYTHONHASHSEED and ASLR as random factors [11].
3. Is a per-look α of 0.05 with two confirming looks acceptable, given about 15 trials a run (about 0.04 false keeps a run)? This is the owner's trade between multiplicity and the 47 lost trials.
4. Could the next pre-registered arm comparison use a stratified rank-sum test, or more runs? Today's bar needs 16 of 20.
5. Does a changepoint test on the A/A probe (fix B) find a settle point within the 5-minute cap, on how many VMs?

## Sources

1. Kalibera, T., Jones, R. (2013). Rigorous Benchmarking in Reasonable Time. ISMM 2013, pp. 63-74. doi:10.1145/2464157.2464160. Author's manuscript: https://kar.kent.ac.uk/33611/ (read in full).
2. Kalibera, T., Jones, R. (2012). Quantifying Performance Changes with Effect Size Confidence Intervals. Tech. report, University of Kent. https://www.cs.kent.ac.uk/pubs/2012/3233/ (abstract only).
3. Georges, A., Buytaert, D., Eeckhout, L. (2007). Statistically Rigorous Java Performance Evaluation. OOPSLA 2007. doi:10.1145/1297027.1297033. https://buytaert.net/files/oopsla07-georges.pdf (read).
4. Mytkowicz, T., Diwan, A., Hauswirth, M., Sweeney, P. F. (2009). Producing Wrong Data Without Doing Anything Obviously Wrong! ASPLOS 2009, pp. 265-276. doi:10.1145/1508244.1508275. Abstract: https://sape.inf.usi.ch/publications/asplos09 (**full text not accessed**).
5. Curtsinger, C., Berger, E. D. (2013). STABILIZER: Statistically Sound Performance Evaluation. ASPLOS 2013, pp. 219-228. doi:10.1145/2451116.2451141. https://plasma-seminar.github.io/readings/p219-curtsinger.pdf (read).
6. Bulej, L., Horký, V., Tůma, P., Farquet, F., Prokopec, A. (2020). Duet Benchmarking: Improving Measurement Accuracy in the Cloud. ICPE 2020. doi:10.1145/3358960.3379132. arXiv:2001.05811.
7. Barrett, E., Bolz-Tereick, C. F., Killick, R., Mount, S., Tratt, L. (2017). Virtual Machine Warmup Blows Hot and Cold. OOPSLA 2017. arXiv:1602.00602v6.
8. Daly, D., Brown, W., Ingo, H., O'Leary, J., Bradford, D. (2020). The Use of Change Point Detection to Identify Software Performance Regressions in a Continuous Integration System. ICPE 2020. arXiv:2003.00584.
9. Fleming, M., Kołaczkowski, P., Kumar, I., Das, S., McCarthy, S., et al. (2023). Hunter: Using Change Point Detection to Hunt for Performance Regressions. arXiv:2301.03034.
10. Chen, J., Revels, J. (2016). Robust benchmarking in noisy environments. arXiv:1608.04295.
11. pyperf documentation and source, psf/pyperf, commit 63ce439 (2026-11-08): doc/run_benchmark.rst, doc/analyze.rst, doc/runner.rst, pyperf/_utils.py, pyperf/_cli.py. https://github.com/psf/pyperf ; https://pyperf.readthedocs.io
12. pytest-benchmark documentation, ionelmc/pytest-benchmark, commit 97c52d8 (2026-11-01): docs/calibration.rst, docs/usage.rst, docs/faq.rst, docs/comparing.rst. https://github.com/ionelmc/pytest-benchmark
13. NIST/SEMATECH e-Handbook of Statistical Methods, s6.3.2.3, CUSUM Control Charts. https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm (Page, E. S. (1954), Biometrika 41:100-115, not accessed).
14. (a) Wikipedia, "Sign test", https://en.wikipedia.org/wiki/Sign_test ; (b) Wikipedia, "Mann–Whitney U test", https://en.wikipedia.org/wiki/Mann%E2%80%93Whitney_U_test (citing Lehmann, *Elements of Large-Sample Theory*, Springer 1999, ISBN 978-0-387-98595-4, not accessed). Accessed 2026-11-13; tertiary sources.
15. Wikipedia, "Robust measures of scale", https://en.wikipedia.org/wiki/Robust_measures_of_scale (citing Rousseeuw and Croux 1993, JASA 88:1273-1283, doi:10.2307/2291267, not accessed). Accessed 2026-11-13.

**Engine-side data and computations.**
- X2-D's 20 delivered gains are from `w2-sprint/o61/variance-x2-d-20-not-preregistered.md` s2.
- The sign rule is from `services/python_agents/tests/live/ideas_x2_report.py:872-917`.
- The floor rule is from `optimization/anticheat.py:207-240`, and the ABBA order from `execution/measure.py:522-576`.
- My scripts are in `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/s2-stats/` (`power.py`, `power2.py`, `floors.py`, `floors2.py`). Every simulated number above comes from them.
- No file in `/home/user/step3-emergence-r1` was written.
