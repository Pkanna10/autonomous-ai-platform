# s5-search: search methods (archives, islands, evolutionary and bandit search)

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **Mouret and Clune 2015, MAP-Elites [1].** An archive that keeps one elite per cell of a descriptor grid. It is the founding quality-diversity paper.
2. **Flageat and Cully 2023, Uncertain QD [2].** MAP-Elites under noisy fitness: "lucky" elites, plus Archive-sampling and Adaptive-sampling. It is the reference for QD with noise.
3. **Whitley, Rana and Heckendorn 1999 [4].** When island models beat one large population. It is the standard analysis of islands.
4. **Romera-Paredes et al. 2024, FunSearch [5], and Novikov et al. 2025, AlphaEvolve [6].** LLM-driven evolutionary search over programs, using island databases and evaluation cascades. They are the field's flagship systems.
5. **Petke et al. 2018 [8], Langdon and Harman 2015 [7], Blot and Petke 2021 [9].** The genetic improvement (GI) survey, the canonical runtime-GI result, and the local-search versus GP comparison.
6. **Shypula et al. 2024, PIE [11].** LLM performance edits, with an A/A measurement-noise study.
7. **Jamieson and Talwalkar 2016 [12], Li et al. 2018, Hyperband [13], Karnin et al. 2013 [14].** Successive halving, and the "n versus B/n" trade-off.
8. **Lattimore and Szepesvári 2020, ch. 33 [15], Kaufmann et al. 2016 [16].** The textbook and the theory of best-arm identification.
9. **Russo et al. 2018 [18], Russo 2016 [17], Locatelli et al. 2016 [19].** Thompson sampling, top-two sampling for picking the best arm, and the thresholding bandit.
10. **Smith and Winkler 2006 [20].** The optimizer's curse, or winner's curse.

**Access note.** WebFetch could not reach arxiv.org or nature.com. I read the papers as PDF and HTML from export.arxiv.org, PMLR, JMLR, nature.com (via curl), gpbib and a read-only clone of MAGPIE. I saw [3], [9] and [20] only as abstracts or second-hand descriptions, so the notes say only what those show.

## Notes

### Archives (quality diversity)

**How MAP-Elites works [1]:**
- It starts from G random genomes.
- It then repeats one step: pick a random filled cell, mutate its elite, and place the child "if the cell is empty or if the offspring is higher-performing than the current occupant".
- The authors find that "the stepping stones that lead to a high-performing elite ... are distributed throughout the feature space."
- Their claim that MAP-Elites also finds a better single best solution is domain-dependent. It is the authors' claim, not a law.

**Under noise, MAP-Elites fails in a known way [2]:**
- "Standard QD algorithms maintain lucky solutions due to their elitism."
- Final collections end up holding "a majority of lucky sub-performing" solutions.

**The remedies [2]:**
- **Archive-sampling.** Periodically empty the archive, re-evaluate every elite once, and re-insert it on its moving-average fitness. Each cell keeps D solutions, so an unlucky solution gets "a second chance" and a lucky one is "rapidly re-evaluated and removed".
- **Adaptive-sampling, after [3].** A challenger must be evaluated as many times as the incumbent before it can replace it. A challenged elite is re-evaluated at once.

### Islands

**FunSearch's design [5]:**
- It runs m islands. Each prompt samples k = 2 programs from one island ("two functions lead to better results compared to just one, with diminishing returns beyond that").
- "Every 4 h, we discard all the programs from the m/2 islands whose best instances have the lowest score." Each such island is reseeded with the best program of a surviving island.
- Within an island, programs are clustered by signature (their score tuple).
- Results are spread widely: in the cap set problem at n = 8, "only four out of 140 experiments" found size 512.
- It drew on the order of 10^6 samples, with typically 15 samplers and 150 CPU evaluators.

**Whitley et al.'s finding [4]:**
- Islands suit problems "loosely composed of many separate problems that can be solved independently". Migration "transfers information between populations".
- On nonseparable functions in the large-population runs, "the single large population still performs best".
- So island superiority is contested and depends on separability.

### LLM evolutionary search and GI

**AlphaEvolve [6]:**
- Its database combines "the MAP elites algorithm and island-based population models".
- An evaluation cascade sends a candidate to the next stage "only if [it achieves] sufficiently promising results in all earlier stages", which prunes faulty programs early.
- It reports a 23 % average kernel speed-up and a 1 % cut in Gemini's training time.
- **Ablation:** "No evolution", which "repeatedly feeds the same initial program", trails the full method on both ablated tasks. Those tasks are tensor decomposition and kissing numbers, not runtime.

**GI:**
- The survey [8] covers 1995-2015; 96 % of its core papers use evolutionary algorithms.
- GISMOE made Bowtie2 "70 times faster (on average)" at no functional loss [7].
- Blot and Petke [9]: across 18 search processes and 8 scenarios, "local search approaches achieve better effectiveness and efficiency than genetic programming", with gains of 15-68 %.
- MAGPIE's `minify_patch` [10] is close to the engine's greedy combine. It evaluates each edit alone, rebuilds the patch by re-adding edits "only accepting [each] on fitness improvement", then tries removing each edit. It warns that "noise in fitness measurement may lead to non-optimal patch being returned." MAGPIE also caches results (`cache_maxsize`), so a variant it has already seen is not re-measured.

**PIE [11]:**
- Hyperfine timed 500 A/A pairs of identical programs: mean "speedup" 1.12x, sd 0.36, top 5 % at 1.91x. "With enough samples and variance, benchmarking the same exact program can easily lead us to report significant optimizations."
- Best@8 is far above Best@1 (6.86x mean speed-up with eight generations). Sampling breadth matters.

### Bandits

**Successive halving [12, 13]:**
- Give every arm the same budget, "throw out the worst half, and repeat".
- Hyperband hedges the "n versus B/n" problem by running several brackets. At R = 81 and η = 3 the aggressive bracket goes 81 arms × 1, then 27 × 3, 9 × 9, 3 × 27 and 1 × 81; the last bracket is plain random search, 5 × 81 [13, Table 1].
- The non-stochastic setting [12] needs only that each arm's measured value converges. It assumes no iid noise.

**Theory [14, 15, 16]:**
- Sequential halving has error at most 3 log₂k · exp(−n / (16 H₂ log₂k)), with H₂ = max_i i/Δ_i² [15, Thm 33.10].
- Hard instances are many arms with small gaps Δ.
- Kaufmann et al. give sequential stopping rules "with guaranteed error probabilities" [16].
- The thresholding bandit finds every arm above a threshold τ, with provably optimal fixed-budget allocation [19].
- Top-two and Thompson variants reach the best possible exponent for identifying the best design [17]. Thompson sampling itself is covered in [18].

**The optimizer's curse [20].** Picking the best-looking of several unbiased estimates gives a realised value that "tends to fall short of its estimate". The remedy is Bayesian shrinkage.

### Established and contested

- **Established:**
  - pure-exploration allocation theory for stationary arms [14-17, 19];
  - lucky elites under noise [2];
  - selection bias [20];
  - the size of A/A noise [11].
- **Contested or unproven here:**
  - islands against a single population [4];
  - whether AlphaEvolve's ablation [6] carries over to runtime edits on Python;
  - whether MAP-Elites finds a better optimum [1].
- **The engine's noise is not stationary.** Floors fall with time since the job started (27 % above 1.5x in minutes 0-5, against 10 % in minutes 30-60). That breaks the iid assumption behind [14-17], so the frame in [12] is the safer one.

## Bearing on the ledger

**My worked model.** The numbers below that cite no source are my own arithmetic under a Gaussian model; none comes from a source. With 5 runs a side, the sd of a difference of means is σ_d = 0.632 s, where s is the per-run sd. A floor of 2 sd of one side is then about 3.16 σ_d. Under that model a null trial passes one look with probability 0.08 %.

### L3: trials lost to measurement noise

**What the field says.** This is a thresholding-bandit problem [19]. The question is not which trial is best, but which trials are above τ. Both the optimal allocation and Adaptive-sampling [2, 3] put extra samples on the arms whose intervals straddle τ, and none on the rest.

**Numbers:**
- The ambiguous band is the 47 trials with a gain between the two floors (median gain 3.8 %, 10 of them at 5 % or more) plus the 49 that failed confirmation: 96 of 972 trials (9.9 %).
- Giving only those trials 3x the runs, one halving step at η = 3 [13], adds about 20 % to A/B measurement minutes. That is CI minutes, not USD.

**The validity condition.** Adaptive looks are honest only if the error is controlled across looks [16, 15 §33.2]. The combine proposal's symmetry rule (trigger on the floor, never on the verdict) is the right instinct. Each extra look still goes through the unchanged frozen judge.

### L4: failed confirmations

**What the field says.** This is regression to the mean: the optimizer's curse [20] and lucky elites [2]. A trial whose true gain sits exactly at the floor passes each look with probability 0.5, so half its first passes fail the second look. At z = 1 above the floor, 16 % fail.

**Numbers:**
- Of 333 first-look passes (284 keeps plus 49), 49 failed, 14.7 %. That matches an average margin of about 1.05 σ above the floor.
- So much of L4 may be expected selection, not VM noise. This is an inference, and the per-look samples would test it.
- An arithmetic fix the archive data could check: decide on the mean of both looks, as `reported_gain` already reports. That uses Archive-sampling's moving average [2] instead of requiring two passes in a row.

### L1: ideas that never become trials

**What the field says:**
- Hyperband's n versus B/n [13]: with about 15 trials a run (972 / 63), the trial is the scarce arm pull. Cheap early filters let a run try more ideas.
- AlphaEvolve's cascade [6] is the published pattern for those filters.
- MAP-Elites [1] keeps one elite per cell but never discards the other cells' candidates. Today's portfolio quotas drop 35 ideas at s4b (19 of them `quota_several`) for good.
- In QD terms, an idea passed over by a quota would be parked in its cell's archive and drawn in a later round.
- The 24 `duplicate_of` verdicts and the identical mistune hunk across runs are what FunSearch's signature clusters [5] and MAGPIE's evaluation cache [10] collapse before anything is spent.

**The limit.** The 31 `ungrounded` replies are a reading failure. No search method recovers them.

### L8: diminishing unique keeps per round

**What the field says:**
- Re-trialling from the base each round is AlphaEvolve's "No evolution" ablation, which loses on both tasks it was tested on [6]. FunSearch's best-shot prompting [5] builds on elites.
- GI's local-search result [9] supports hill-climbing from the current best, which is what X2-DT does.
- Diminishing returns are expected in local search.
- The literature shows the program itself in the prompt (k = 2 [5]), not titles. That predicts the 21 re-implementation conflicts out of 57 shrink when lanes see the tip's code.

**What is contested.** Neither [5] nor [6] measures this on runtime edits.

### L9: spread between identical runs

**What the field says:**
- Heavy-tailed outcomes are normal for stochastic program search: 4 of 140 FunSearch experiments [5].
- Islands with reset [5] are successive halving across runs: run several, cut the worse half, reseed from the best.

**My arithmetic (normality assumed):**
- The sqlparse range of +14.6 to +43.9 over 16 runs implies a per-run sd of about 8.3 points, since the expected range of 16 normals is 3.53σ.
- Best-of-2 then adds about 4.7 points to the mean, and best-of-5 about 9.6. Every best-of-k figure is a cursed estimate [20] and has to be re-measured.
- Union beats best-of when patches compose. In the separable case [4], that is reviewer seed (a).

### Reviewer seed (c): a proven-patch archive carried across runs

**What the field says.** This is island migration [4, 5] combined with a MAP-Elites archive [1, 6]. A design the sources support:
- **Cells:** per library, keyed by (file, function, technique family).
- **Elite:** the patch itself. Never trust its stored gain [20].
- **Replacement:** only after a same-session paired re-measure, with a challenger measured as often as the incumbent (Adaptive-sampling [2, 3]).
- **Every run:** re-evaluate the inherited elites on that run's machine before use (Archive-sampling [2]).
- **Bloat:** minify the composed elites MAGPIE-style [10], knowing noise can mislead that step.

**Expected effect:**
- It turns the L9 spread into a ratchet.
- It removes repeat trials (L5, L8): a cached signature skips the trial [10].

**Caveats:**
- An archive makes runs dependent, so the pool's exchangeable rank test [variance.md] no longer applies. It needs its own labelled baseline.
- It starts empty on every unseen library, so it adds nothing at a sealed rung. It is a product gain (re-runs, WATCH), not a benchmark gain.

## Open questions for the seminar

1. Is the noise shared between A and B within a pair, which a paired floor handles, or one-sided bursts, which call for Adaptive-sampling? The per-look samples decide it.
2. Does deciding on the mean of two looks cut L4 without raising false keeps? This can be replayed on the archive at zero credit.
3. Which archive descriptor fits patches best, and is a technique family stable enough to key on?
4. Does Hyperband's hedge justify a cheaper first look for more ideas, given that editor tokens and not CI minutes are the binding cost?
5. Are the libraries' patches separable enough [4] for a union (seed a) to beat best-of-k?

## Sources

1. J.-B. Mouret, J. Clune. "Illuminating search spaces by mapping elites." 2015. https://arxiv.org/abs/1504.04909
2. M. Flageat, A. Cully. "Uncertain Quality-Diversity: Evaluation methodology and new methods for Quality-Diversity in Uncertain Domains." 2023. https://arxiv.org/abs/2302.00463
3. N. Justesen, S. Risi, J.-B. Mouret. "MAP-Elites for Noisy Domains by Adaptive Sampling." GECCO '19 Companion, pp. 121-122, 2019. doi:10.1145/3319619.3321904. Not read; described only through [2].
4. D. Whitley, S. Rana, R. B. Heckendorn. "The Island Model Genetic Algorithm: On Separability, Population Size and Convergence." Journal of Computing and Information Technology 7(1):33-47, 1999. https://neo.lcc.uma.es/Articles/WRH98.pdf
5. B. Romera-Paredes et al. "Mathematical discoveries from program search with large language models." Nature 625:468-475, 2024. https://www.nature.com/articles/s41586-023-06924-6
6. A. Novikov et al. "AlphaEvolve: A coding agent for scientific and algorithmic discovery." 2025. https://arxiv.org/abs/2506.13131
7. W. B. Langdon, M. Harman. "Optimising Existing Software with Genetic Programming." IEEE Transactions on Evolutionary Computation 19(1):118-135, 2015. doi:10.1109/TEVC.2013.2281544. Abstract read via https://gpbib.pmacs.upenn.edu/gp-html/Langdon_2013_ieeeTEC.html
8. J. Petke, S. O. Haraldsson, M. Harman, W. B. Langdon, D. R. White, J. R. Woodward. "Genetic Improvement of Software: a Comprehensive Survey." IEEE Transactions on Evolutionary Computation 22(3):415-432, 2018. doi:10.1109/TEVC.2017.2693219
9. A. Blot, J. Petke. "Empirical Comparison of Search Heuristics for Genetic Improvement of Software." IEEE Transactions on Evolutionary Computation, 2021. doi:10.1109/TEVC.2021.3070271. Abstract only; the full text, https://discovery.ucl.ac.uk/10126812/, was blocked.
10. A. Blot et al. MAGPIE, docs `entry_points.md` and `scenario.md`, commit b5f0a2e. https://github.com/bloa/magpie
11. A. Shypula et al. "Learning Performance-Improving Code Edits." ICLR 2024. https://arxiv.org/abs/2302.07867
12. K. Jamieson, A. Talwalkar. "Non-stochastic Best Arm Identification and Hyperparameter Optimization." AISTATS 2016, PMLR 51:240-248. https://proceedings.mlr.press/v51/jamieson16.html
13. L. Li, K. Jamieson, G. DeSalvo, A. Rostamizadeh, A. Talwalkar. "Hyperband: A Novel Bandit-Based Approach to Hyperparameter Optimization." JMLR 18:1-52, 2018. http://jmlr.org/papers/v18/16-558.html
14. Z. Karnin, T. Koren, O. Somekh. "Almost Optimal Exploration in Multi-Armed Bandits." ICML 2013, PMLR 28:1238-1246. https://proceedings.mlr.press/v28/karnin13.html
15. T. Lattimore, C. Szepesvári. Bandit Algorithms. Cambridge University Press, 2020, ch. 33. ISBN 9781108486828. https://tor-lattimore.com/downloads/book/book.pdf
16. E. Kaufmann, O. Cappé, A. Garivier. "On the Complexity of Best-Arm Identification in Multi-Armed Bandit Models." JMLR 17:1-42, 2016. https://www.jmlr.org/papers/v17/kaufman16a.html
17. D. Russo. "Simple Bayesian Algorithms for Best Arm Identification." 2016. https://arxiv.org/abs/1602.08448
18. D. Russo, B. Van Roy, A. Kazerouni, I. Osband, Z. Wen. "A Tutorial on Thompson Sampling." Foundations and Trends in Machine Learning 11(1):1-96, 2018. https://arxiv.org/abs/1707.02038
19. A. Locatelli, M. Gutzeit, A. Carpentier. "An optimal algorithm for the Thresholding Bandit Problem." ICML 2016, PMLR 48:1690-1698. https://proceedings.mlr.press/v48/locatelli16.html
20. J. E. Smith, R. L. Winkler. "The Optimizer's Curse: Skepticism and Postdecision Surprise in Decision Analysis." Management Science 52(3):311-322, 2006. doi:10.1287/mnsc.1050.0451. Abstract only; a 2007 correction revises Figure 3's numbers upward.

Scratch downloads are in /tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/s5-search/. Nothing in /home/user/step3-emergence-r1 was written.
