# s2-stats errata (full-text check, 2026-11-13)

All files are under `library/sources/s2-stats/`. Every text was read with `pdftotext` or as raw text, and treated as data.

## Sources

| # | citation (short) | status | file under sources/s2-stats/ or why none |
| --- | --- | --- | --- |
| 1 | Kalibera and Jones, ISMM 2013 | full text | `1-kalibera-jones-ismm2013.pdf` (author's manuscript, kar.kent.ac.uk/33611) |
| 2 | Kalibera and Jones, tech report 2012 | full text (was abstract only) | `2-kalibera-jones-techreport2012.pdf` (cs.kent.ac.uk/pubs/2012/3233) |
| 3 | Georges, Buytaert and Eeckhout, OOPSLA 2007 | full text | `3-georges-oopsla2007.pdf` (buytaert.net) |
| 4 | Mytkowicz et al., ASPLOS 2009 | full text (was not accessed) | `4-mytkowicz-asplos2009.pdf`. Neither Semantic Scholar nor an author page had an open copy, and dl.acm.org refused. This is the paper as a reading on a Northwestern University course page (users.cs.northwestern.edu/~robby/courses/322-2013-spring/) |
| 5 | Curtsinger and Berger, STABILIZER, ASPLOS 2013 | full text | `5-stabilizer-asplos2013.pdf` |
| 6 | Bulej et al., Duet, ICPE 2020 | full text | `6-duet-arxiv2001.05811.pdf` |
| 7 | Barrett et al., VM warmup, OOPSLA 2017 | full text | `7-barrett-warmup-arxiv1602.00602.pdf` |
| 8 | Daly et al., ICPE 2020 | full text | `8-daly-changepoint-arxiv2003.00584.pdf` |
| 9 | Fleming et al., Hunter, 2023 | full text | `9-hunter-arxiv2301.03034.pdf` |
| 10 | Chen and Revels, 2016 | full text | `10-chen-revels-arxiv1608.04295.pdf` |
| 11 | pyperf docs and code, commit 63ce439 | full text | `11-pyperf-docs-63ce439.txt` (the docs; the code was read in the clone) |
| 12 | pytest-benchmark docs, commit 97c52d8 | full text | `12-pytest-benchmark-docs-97c52d8.txt` |
| 13 | NIST/SEMATECH e-Handbook, CUSUM | full text | `13-nist-cusum.html` |
| 13' | Page, Biometrika 1954 | open substitute | Not open (Biometrika). The substitute is the NIST page above. Metadata confirmed by Crossref |
| 14a | Wikipedia, "Sign test" | full text (tertiary) | `14a-wikipedia-sign-test.txt` |
| 14b | Wikipedia, "Mann–Whitney U test" | full text (tertiary) | `14b-wikipedia-mann-whitney.txt` |
| 14' | Lehmann, *Elements of Large-Sample Theory*, 1999 | open substitute | A commercial textbook. Substitutes: `14c-bartlett-stat210b-lecture24.pdf` (UC Berkeley Stat 210B lecture notes) and `14e-etests-efficiency-arxiv2208.08925.pdf` (Vovk and Wang, arXiv:2208.08925) |
| 15 | Wikipedia, "Robust measures of scale" | full text (tertiary) | `15-wikipedia-robust-scale.txt`, plus `15b-wikipedia-mad.txt` |
| 15' | Rousseeuw and Croux, JASA 1993 | unverified | No open copy found. The Semantic Scholar DOI lookup returned "not found" and its search was rate-limited. I made no further attempts |
| 16 | Wikipedia, "Crossover study" (cited inline only, no number) | full text (tertiary) | `16-wikipedia-crossover.txt` |
| 16' | Jones and Kenward, cross-over trials textbook | unverified | A commercial textbook. The open course substitute (Penn State STAT 509) failed TLS verification, and I did not bypass it |

## Corrections

- **[1]**, every claim in the Notes is confirmed against the full text:
  - the three kinds of variable (s3);
  - repetition at the highest level that varies (s3);
  - below 1%, not 5%, for overlapping intervals (s4);
  - 71 of 90 papers (s1);
  - "20 may be a good choice but use 30 if possible" (s9.1);
  - eq. 3 and the re-dimensioning recommendation (s9.3);
  - the Fieller interval (s10.1);
  - link-order variation "very small" at reference sizes, and the STABILIZER caution (s2).
- **[2]**, Core sources, "abstract read only" → the full text is now read. "Gives the derivations" is confirmed: the random-effects model derivation is "one of the contributions" (s4.1), with details in s7.3 to s7.6.
- **[3]**, Notes, "a window of k=10 iterations falls below 0.01-0.02" → the method (s4.2) leaves k generic, with thresholds "say 0.01 or 0.02". k=10 with CoV < 0.02 is the paper's own experimental setting in the steady-state evaluation (s6), not part of the method.
- **[3]**, Notes, the quoted phrase "because iterations within a single VM invocation are not independent" is a paraphrase, not verbatim. s4.2 reads: "the various iterations within a single VM invocation are not independent, however, the mean values x̄i across multiple VM invocations are independent."
- **[3]**, Notes, "CoV around 2%; 8% start-up, 20% steady state [3, s5]" → the numbers are confirmed, but they are in s6.1, not s5. s5 is the experimental set-up.
- [3], "misleading in up to 16%; incorrect in more than 3%": confirmed (s6.2).
- **[4]**, Core sources, "I could not reach the full text" → the full text is now read.
- **[4]**, Notes, "all architectures … all compilers … all SPEC CPU2006 C programs" → that wording is the web abstract's (sape.inf.usi.ch). The paper's own abstract says "all architectures that we tried (Pentium 4, Core 2, and m5 O3CPU), **both** compilers that we tried (gcc and Intel's C compiler), and **most** of the SPEC CPU2006 C programs".
- **[4]**, Notes, environment size "up to 300%" → s2 says a change in environment size changes performance "frequently by about 33% and once by almost 300%". 300% is a single extreme case, not a typical bound.
- [4], other claims: the median reported speedup of 10% (s6.2) and "none of the 133 papers" (abstract) are confirmed. Also in the paper: link order moves the O3 speedup by a median 0.02 on Core 2 and 0.08 on Pentium 4 (s4).
- [5]: 500 ms re-randomization (s3.4, default), "30 is typical" (s2), 6.7% median overhead (s5.1), F=3.235 with p=0.0898 and F=1.335 with p=0.264 (s6.1), 36 tests giving 1.8 expected false positives (s6.1), 300% citing [4] and 57% link order (s1): all confirmed.
- **[5]**, Notes, "with 30 runs a configuration" for the -O2/-O3 ANOVA → 30 runs per configuration is stated for the overhead and normality experiments (s5.1, s5.2). It is not restated in s6.
- [6]: 2.3x-12.5x (5.03x) and 23.8x-82.4x (37.4x) in the abstract; the barrier on two virtual cores, geometric mean of ratios and bootstrap (s3); the shuffle giving 1.02 and 1.03 (s4.2, RQ2): all confirmed.
- [7]: 43.5% (abstract), PELT with cpt.meanvar and penalty 15·log n (s4.2), the four classes (s4.3), heuristics' false positives and negatives citing [1] (s4.2), PyPy 5.6.0 studied and CPython not (s3, VM list): all confirmed.
- **[7]**, Sources: add doi:10.1145/3133876. The arXiv journal_ref is "Object-Oriented Programming, Systems, Languages & Applications, October 2017, 52:1-52:27".
- **[8]**, Notes, "needs no distributional assumption" → s2.1: "does not require any distributional assumptions other than a finite mean".
- [8], other claims: permutation sampling (s2.1), noise below 10% with 20% or more on sensitive tests (s1), and the "dramatically dropped" false-positive rate (abstract): confirmed.
- **[8]**, Sources: add doi:10.1145/3358960.3375791. On arXiv the entry is titled "Change Point Detection in Software Performance Testing"; the cited title is the PDF's own.
- [9], "for speed and determinism": confirmed. The switch to Student's t-test cut the runtime "by an order of magnitude as well as providing consistent results when run multiple times on the same data set".
- [10]: the positive-error model and the unimodal minimum, as against the bimodal median and trimmed mean (s IV.B), confirmed.
- [11]: 20×3 plus 1 warm-up, `--fast` 10×2, `--rigorous` 40×3 (runner.rst); the ASLR and hash quote (run_benchmark.rst); the sd ≥ 10% warning (`_cli.py:417-424`); the two-sample pooled t-test at 95% over all values (`_utils.py`, `_compare.py`); median ± MAD offered (analyze.rst): all confirmed.
- **[11]**, Notes, Contested, "pyperf moved to mean ± sd" → the docs show mean ± sd as the default summary and link the "minimum vs average" discussion. That pyperf *moved* from the minimum is not stated in what I read, so this is unverified.
- [12]: min-rounds 5, sorting by min by default, `compare-fail=min:5%`, and "IQR is often better than StdDev": confirmed.
- [13]: shifts of 2σ or less, k=δσ/2, d=(2/δ²)·ln((1−β)/α) and h=d·k (adapted from Montgomery 2000): confirmed.
- [13'], Page's metadata: Crossref gives Biometrika 41(1-2):100-115 (1954), doi:10.1093/biomet/41.1-2.100. Confirmed, but the content was not read.
- **[14a]**, Notes, "2.0 against t for heavy (double-exponential) tails" → Wikipedia says "heavy-tailed (platykurtic distribution)", which mislabels heavy tails; it does not say double-exponential. The open substitute (Bartlett, Stat 210B lecture 24, slide 17) gives the sign test against t as 2 for the Laplace (double-exponential), 2/π ≈ 0.6366 for the normal, π²/12 ≈ 0.822 for the logistic and 1/3 for the uniform. The value and the distribution are therefore confirmed by the substitute.
- [14a], 0.637 against the paired t and 0.67 against the Wilcoxon signed-rank: confirmed. Vovk and Wang (s6) also give 2/π ≈ 0.64 for the sign test, and 3/π ≈ 0.955 for the Wilcoxon signed-rank, "as in the classical case".
- [14b], Mann-Whitney 3/π (about 0.95): confirmed on Wikipedia. The Lehmann ISBN, 0-387-98595-6 (= 978-0-387-98595-4), is confirmed by Crossref; the book itself was not read.
- **[15]**, Notes, "MAD … with a 50% breakdown point" → no accessed source states it; it is moved to "unverified". MAD 37%, Sₙ 58% and Qₙ 82% (and 88% elsewhere on the same page) are confirmed as Wikipedia's text.
- **[16] (inline)**, Bearing L3, condition 4, "Classic 2×2 crossover analysis estimates the period effect and removes it" → the Wikipedia page covers balance, four-period designs and carry-over, not estimating the period effect. This is unverified.

## Claims still unverified

- MAD's 50% breakdown point, and the Qₙ efficiency (82% or 88%): Rousseeuw and Croux 1993 was not accessed.
- Removing the period (order) effect in a 2×2 crossover: Jones and Kenward was not accessed, and the open course page failed TLS.
- That pyperf moved its reported statistic from the minimum to mean ± sd (history, not docs).
- The content of Page 1954 and Lehmann 1999 themselves; only their metadata, plus the open substitutes for the results the notes use.
- Everything I computed myself stands as computed, with the scripts in `work/s2-stats/`: the stratified sign-test null and power, the floor simulations and the K&J worked numbers. They cite no source.

## Overview sources

These pages were used as a map only; no claim is cited from them. The files are under `sources/s2-stats/overview/`.

| # | source (short) | kind | file under sources/s2-stats/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | Jain, *The Art of Computer Systems Performance Analysis* (Wiley 1991), the author's TOC page | TOC | `1-jain-art-of-perf-analysis-toc.html` |
| 2 | Jain, CSE567M Computer Systems Analysis, WUSTL, Fall 2017 | syllabus / topic list | `2-jain-cse567-course.html` |
| 3 | Le Boudec, *Performance Evaluation of Computer and Communication Systems* (EPFL Press 2010), the author's book page and the TOC of the open PDF (only the TOC kept) | TOC | `3-leboudec-perfeval-book.html`, `3-leboudec-perfeval-toc.txt` |
| 4 | Evaluate Collaboratory, Evaluation Anti-Patterns | topic list | `4-evaluate-anti-patterns.html` |
| 5 | Evaluate Collaboratory, the Canon bibliography | reading list | `5-evaluate-canon-reading-list.html` |
| 6 | Truong, Oudre and Vayatis, "Selective review of offline change point detection methods", arXiv:1801.00718 (the section list only) | topic list | `6-truong-changepoint-review-sections.txt` |
| 7 | Hollander, Wolfe and Chicken, *Nonparametric Statistical Methods*, 3rd ed., the Wiley product page | TOC | refused: 403 |
| 8 | Montgomery, *Introduction to Statistical Quality Control*, 8th ed., the Wiley product page (CUSUM, control charts) | TOC | refused: 403 |
| - | perfeval.epfl.ch (Le Boudec's old site) | - | refused: 502 at the proxy. The author's GitHub Pages copy (#3) was used instead |

## Not yet covered

- **Factorial and fractional factorial designs, with interactions** (#1 Part IV, #2): bear on L6. A 2^k design over the keeps would measure their interactions directly, instead of inferring them from a greedy combine.
- **Confidence intervals for the median and quantiles, and the bootstrap** (#3 s2.2.2, s2.2.4): bear on L9 and the X2-DT reading. An effect-size interval on the delivered gain, in the K&J style, beside the sign test.
- **Checking the iid assumption, and what to do when it fails** (#3 s2.3): bears on L3. The time-since-start gradient means looks within a run are not identically distributed.
- **Prediction intervals** (#3 s2.4): bear on L3 and L7. A floor is a prediction bound for the next A/A difference, not a confidence interval for a mean, and the two have different widths.
- **Choosing a distribution, and heavy tails** (#3 s3.4, s3.5): bear on L3 and fix C. They would test the README's spike model (0.4 % noise plus rare 5-20 % slow runs) properly.
- **The Neyman-Pearson framework and likelihood-ratio tests** (#3 s4.1, s4.2): bear on L3 and L4. They let the floor be designed from a stated α and β, not from a constant tuned to read 1.0x.
- **Robust tests** (#3 s4.5.2): bear on L3 and fix C, as a test-level alternative to swapping in MAD.
- **Regression models for attributing causes** (#1 Part III, #2): bear on L3. Regressing floors on minutes since start, CPU model and pressure once the record-only fields exist.
- **ARMA and differencing** (#3 s5): bear on L3. A model of slow drift within a run, which is the part pairing would cancel.
- **Inconsistent and irreproducible measurement contexts** (#4): bear on L9 and L3. Each run is a different VM; record it, and block by it.
- **Changepoint cost functions, penalty choice and estimating the number of changes** (#6 s4, s6): bear on fix B. The penalty sets the false-alarm rate of a settle detector.
- **Blackburn et al. 2016, "The Truth, the Whole Truth…", a pragmatic guide to assessing evaluations** (#5): bears on how claims are worded at a sealed rung.
- **Coz, causal profiling** (#5): bears on L10, where gain lies outside the hot function. It is mostly other seats' ground.
- **Ratio games and summarizing across benchmarks** (#1 Part II): bear on how per-library gains are pooled in arm reads. Probably minor.
- **Queueing models, simulation and fairness indices** (#1 Parts V-VI, #3 s1.2, s6): probably not relevant.
