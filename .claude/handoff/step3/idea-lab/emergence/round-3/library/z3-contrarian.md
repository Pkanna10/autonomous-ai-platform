# z3-contrarian: zero to one, "what is true here that few believe"

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **Thiel and Masters, *Zero to One* (2014) [1].** The contrarian question ("What important truth do very few people agree with you on?") and the chapter on secrets. It is the canonical statement of looking where consensus is not looking.
2. **Pólya, *How to Solve It* (1945/1957) [3]; Munger, "invert, always invert" [2].** Working backwards (Pappus's analysis) and inversion: ask what would guarantee failure, then avoid it. These are the standard heuristics for busting assumptions.
3. **Mytkowicz et al., "Producing Wrong Data Without Doing Anything Obviously Wrong!" (ASPLOS 2009) [4].** Innocuous set-up details (environment size, link order) bias results. It is the standard warning about measurement bias.
4. **Mytkowicz et al., "Evaluating the Accuracy of Java Profilers" (PLDI 2010) [5].** Four profilers often name different hot methods, so at least one of them is wrong.
5. **Curtsinger and Berger, Stabilizer (ASPLOS 2013) [6] and Coz (SOSP 2015) [7].** Randomised layout for sound statistics, and causal profiling ("optimise what counts").
6. **Berger, Stern and Altmayer Pizzorno, Scalene (OSDI 2023) [8].** The current reference on accuracy and overhead for Python profilers. I read it in full: the PDF is in the public Scalene repository.
7. **Kanev et al., "Profiling a Warehouse-Scale Computer" (ISCA 2015) [9].** Google's fleet has no single application to optimise and no major hotspots inside applications. Common routines (the "datacenter tax") take about 30 % of cycles.
8. **Practitioners on where speed-ups come from:**
   - Leiserson et al., "There's plenty of room at the Top" (Science 2020) [10];
   - Proebsting's Law [11];
   - SQLite's cachegrind practice [12];
   - Nethercote's rustc series [13];
   - Meta's FBDetect [14].
9. **Estimating what has not been seen yet, and testing in pools:**
   - Good (1953), the Good-Turing estimate [15];
   - Chao (1987), the Chao2 estimate [16];
   - Dorfman (1943), group testing [17].

## Notes (the methods and results, cited inline as [n])

**Method: how to find a secret.**
- Thiel's test [1]: a secret is an important truth that most people do not yet see. Look where the consensus method cannot see.
- Inversion [2][3]: "How would we make sure the engine loses gain?" The archive answers it four times. The engine:
  - judges each idea alone at N = 5, so small gains vanish;
  - shows the lanes only the hot functions, so gains in callers stay invisible;
  - keeps the first realisation of an idea and drops the others by textual conflict;
  - forgets every site when a run ends.
  Each answer becomes one thesis below.

**Measurement folklore that was overturned.**
- [4] Link order alone can make -O3 look 8 % better than -O2 or 7 % worse. None of 133 surveyed papers handled measurement bias adequately. The paper's remedies are setup randomisation and causal analysis. (I saw only the abstract and excerpts; the full-text fetch was blocked.)
- [6] Stabilizer re-randomises code, stack and heap layout at run time, which makes timings close to Gaussian. Under it, -O3 against -O2 on SPEC CPU2006 is indistinguishable from noise. Median overhead is under 7 %. It works only with LLVM 3.1, so the result is tied to its era.
- The common lesson: a bias tied to set-up is not removed by more runs. It is removed by randomising or blocking the set-up.

**Profilers point to the wrong place.**
- [5] Java profilers disagree on which method is hot, because they sample at yield points rather than at random. A random-sampling profiler found important methods that the others labelled cold.
- [8] Deterministic Python profilers, built on the tracing or profile hooks, show "function bias": the apparent time of function calls is inflated. In the worst case one profiler (not named) reported 80 % of the time in a function that took 25 %. cProfile has a median slowdown of 1.7x; `profile` has 15.1x.
- The engine ranks hotspots by cProfile's cumulative time (`idea_context.py`). Its view is therefore biased towards functions with many small calls, and it shows callers only "while the cap allows".
- [7] Coz measures how much the program speeds up when one line is virtually sped up. Guided by it, the authors made Memcached 9 % faster and SQLite 25 % faster, and six PARSEC programs up to 68 % faster. Most changes touched fewer than 10 lines.
  - **Contested for this engine:** for single-threaded code, a virtual speed-up reduces to Amdahl's law, so Coz's own advantage applies mainly to concurrent code.

**Where speed-ups actually come from.**
- [9] Google's fleet profile is flat: no killer application and no major hotspots inside applications. Shared "tax" routines take about 30 % of cycles.
- [10] After Moore's law, the gains are at the "Top": algorithms, software performance engineering and hardware architecture. I could not confirm the matrix-multiply speed-up figure from what I could access, so I give none.
- [11] Proebsting's Law: compilers contribute about 4 % a year, against about 60 % a year for hardware. The author meant it half in jest; Scott (2001) tested it.
- [12] SQLite went from about 1.43 billion to about 954 million cachegrind cycles between 3.7.17 and 3.8.7. In Hipp's words, the gain came from many micro-optimisations:
  - each worth "as little as 0.05 %", with 0.25 % "a huge win";
  - "unmeasurable on a real-world system";
  - wall-clock times "scarcely repeatable beyond one significant digit".

  So the project measures with instruction counts. (I saw this through search excerpts only; the fetch was blocked.)
- [13] Nethercote's rustc work is a catalogue of small pull requests found with Cachegrind and DHAT and reported in instruction counts. The 2019 total was 20 to 50 % on most benchmarks.
- [14] FBDetect catches regressions as small as 0.005 % (Meta's stated figure). It does so by measuring at subroutine level, which turns a 0.05 % application-level change into a 5 % subroutine-level one.
- **Well established:** gain is often spread over many small changes, and the instrument has to be noise-free or local to see them. **Contested:** how far this carries from C and C++ to CPython, where the counted unit is a call or a bytecode, not an instruction.

**Estimating what has not been found yet.**
- [15] The Good-Turing missing mass is f1/N: the share of observations that are singletons estimates the chance that the next observation is new.
- [16] The bias-corrected Chao2 estimate of the total is S_obs + ((m-1)/m) · Q1(Q1-1)/(2(Q2+1)). It is unstable when doubletons are few.
- [17] Dorfman's pooled testing: test many items in one pool and split the pool only if it is positive. It is efficient when positives are rare. Here the positives are real but sub-floor gains.

## Bearing on the ledger (per row you touch: L#, what your field says, numbers)

All archive numbers were computed with `python3 -I` from `w2-sprint/live/` (63 runs and 974 trials; X2-SV left out). Diffs were mapped to functions with `ast`, on base blobs taken from the public upstream repositories (every old-side blob hash in the diffs was found upstream). Scripts are `a.py` to `g.py` in `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/z3-contrarian/`.

**L3 and L4 (inconclusive and failed confirmations).**
- The inconclusives are not null results:
  - 467 of 641 (73 %) have a positive gain; mean +1.10 %, sign test z = 11.6.
  - The 58 with exactly no change in call count average +0.12 %, so the measurement bias is at most about 0.1 to 0.2 points.
  - The gain follows the deterministic call count: inconclusives that cut calls by 10 % or more average +3.78 % (27 of 27 positive); a 1-10 % cut averages +1.54 % (83 % positive); no cut averages +0.36 %.
  - Across all trials, Spearman(call change, gain) = -0.58.
- [12][13][14] say what this means: such gains need a noise-free proxy or pooled measurement, not N = 5 timings of each one alone.

**L10 and L1 (edits confined to the hot function).**
- 150 of 284 keeps (53 %) edit a function other than their target's, and they carry 63 % of the summed keep gain. 45 keeps do not touch the target function at all.
- Median keep gain is +4.9 when the keep edits one function and +7.7 when it edits two or more.
- In mistune, sqlparse and markdown, 10 of 19, 13 of 26 and 9 of 15 of the functions that keeps edit were never any trial's target.
- [5][8] say why: the profiler's ranking is biased, and the gain sits elsewhere in the call graph.

**L5, L6 and L8 (combine conflicts, combine below its best part, fewer unique keeps).**
- Distinct keeps add up nearly linearly. In 54 delivered runs with two or more applied keeps:
  - the delivered gain divided by the sum of standalone gains has a median of 0.91 (IQR 0.81 to 1.01);
  - the delivered gain is a median 8.3 points above the best single applied keep.
- The loss is therefore exclusivity, not semantic overlap. A textual conflict discards a keep that would have added about 0.9 of its gain.

**L9 (spread between identical runs).**
- The replay re-measured four archived tips and found each tip's gain moving by at most 1.3 points across three looks. The spread is mostly search variance.
- Good-Turing over runs, counting the functions that keeps edit:

  | Library  | Functions found | Found in one run only | Runs | Missing mass | Chao2 estimate | Note |
  | -------- | --------------- | --------------------- | ---- | ------------ | -------------- | ---- |
  | tomli    | 7               | 0                     | 16   | 0            | 7              | `key_value_rule` re-found in 15 of 16 runs |
  | sqlparse | 26              | 14                    | 16   | 0.14         | 54             | |
  | mistune  | 19              | 7                     | 15   | 0.06         | 29             | |
  | markdown | 15              | 2                     | 15   | 0.02         | 15             | |

**Floor column.** My field says the floor for L3 is not what one 5-run look can resolve. It is what a pooled or proxy-screened bundle can resolve [12][14][17].

## Mechanisms the engine does not have

**Thesis 1. The gain is below the floor, and a noise-free proxy can see it (sub-floor bundles).**
- **Evidence:**
  - L3's numbers above: 73 % of inconclusives are positive, and their gain rises with the cut in calls.
  - Per run, a median of 5 inconclusives cut calls by 1 % or more. Together they sum to a median of +6.7 points (IQR 4.2 to 10.2).
  - Leaving out those whose target function an applied keep already edits, the sum is still +4.5 points per run (IQR 1.7 to 8.1). The median delivered gain is +17.4.
  - The engine's own pairing of near misses already works: 12 of 16 X2-D compounds were kept, against 84 of 378 single X2-D trials.
  - Literature: SQLite [12], rustc [13], FBDetect [14] and Dorfman's pooled testing [17].
- **Mechanism:**
  1. Choose bundle members by the deterministic call-count reduction, not by the noisy gain. That avoids the winner's curse.
  2. Apply the members together on the tip, k of them, not only two in disjoint files.
  3. Time the bundle once with the frozen judges.
  4. Bisect it only if it fails (delta-style).
- **Ledger:** L3 (and L4).
- **Kill test:** run on the coming inconclusive-diff archive (O63 item 5). The thesis dies if bundles chosen only by call count, replayed on archived tips, fail to clear the tip's floor in at least half of the runs.

**Thesis 2. The hot function is not where the gain is; the caller and the set-up are.**
- **Evidence:**
  - L10's numbers above: 53 % of keeps reach past their target and carry 63 % of the gain.
  - The two sites that best separate strong runs from weak ones were never the target of any trial:
    - sqlparse `grouping.group`: runs whose keeps edit it deliver a median +29.9, against +18.0 without. The technique gates whole grouping passes once per statement; the targets were `_group` and `_group_matching`.
    - markdown `InlineProcessor.__init__`: +21.4 against +11.6. The technique precomputes trigger-character prefilters once per run; the target was `__handleInline`.
  - These are a dispatcher and a constructor, exactly the "caller or set-up" hiding place in the exam addendum.
  - Literature: profilers disagree [5]; cProfile-style function bias [8]; flat profiles [9].
- **Mechanism:**
  - Show the lanes the caller-to-callee edges with their call counts, and let an idea anchor on the caller.
  - Ask two questions in the prompt: "Which caller can avoid this call?" and "What can be computed once at set-up?"
  - Rank hotspots with a sampling profiler that has no function bias, rather than with cProfile's cumulative time.
- **Ledger:** L10, and L1. **This part is a guess:** some of the 31 `read:ungrounded` ideas may name callers that were not shown.
- **Kill test:** dies if fewer than 25 % of the ungrounded ideas name a function outside the shown hotspots, and the expert-practice seat finds less than 30 % of expert gain outside the profiled top functions.

**Thesis 3. The idea is not the unit of gain; its realisation is.**
- **Evidence:**
  - One technique, many keeps, gains that differ several-fold:
    - sqlparse "skip grouping passes absent their trigger": 8 keeps, from +3.4 to +18.5;
    - markdown "trigger-character prefilter or pattern-list hoist": 21 keeps, from +4.3 to +21.0.
  - 21 of 57 conflicts are the same technique re-implemented.
  - Distinct keeps add up at a median of 0.91, so the losses are the realisations that never got made.
  - Coz [7]: changes of fewer than 10 lines gave the large speed-ups.
- **Mechanism (realisation search):**
  - When a keep lands, spend trials on k realisations of the same idea at different scopes: in the callee, hoisted to the caller, or precomputed at set-up. Judge them against each other on the tip.
  - At combine time, a repeat conflict picks the best realisation instead of the first that applied.
- **Ledger:** L5, L8 and L6.
- **Kill test:** a replay with no API spend re-measures every archived realisation in these two families on one runner. The thesis dies if their spread is within twice the replay floor, which would mean the spread is noise.

**Thesis 4. The spread between runs is an option; a union is worth more than any one run.**
- **Evidence:**
  - Tips re-measure within 1.3 points, yet identical arms span +14.6 to +43.9 on sqlparse.
  - Missing mass (table under L9): 0 on tomli, 0.14 on sqlparse.
  - A run's delivered gain depends on whether it found one rare site (Thesis 2).
  - Literature: Good [15] and Chao [16]. The contrast with [4]: here the variance comes from the search, not the machine.
- **Mechanism:**
  - Keep a proven-patch archive across runs; this is the reviewer's seed (c).
  - Seed each new run with the archived sites.
  - Allocate runs by missing mass: stop spending on tomli, spend on sqlparse.
- **Ledger:** L9 and L8.
- **Kill test:** seed (a). The thesis dies if the measured union of distinct proven diffs on sqlparse fails to beat the best single run (+43.9) by more than the replay floor.

## Open questions for the seminar

1. Is a call count (or an instruction count from a cachegrind-style tool) an acceptable proxy for screening only, while the frozen judges still decide?
2. Does the 0.91 additivity hold for keeps that touch the same function?
3. How should an idea be keyed to its realisations without hiding real repeats?
4. Is Chao2 meaningful with 1 or 2 doubletons? I report it as a direction, not as a number to build on.
5. Should Stabilizer-style setup randomisation (hash seed, environment size) be applied across the ABBA blocks?

## Sources (numbered list, full citations with URL or ISBN)

1. Thiel, P. and Masters, B. *Zero to One.* Crown Business, 2014. ISBN 978-0804139298. Read through reviews and outlines only, e.g. https://sive.rs/book/ZeroToOne.
2. Munger, C. T. *Poor Charlie's Almanack*, ed. P. Kaufman (Stripe Press edition, 2023); "invert, always invert" after Jacobi. I did not verify the ISBN. Secondary source: https://www.stockopedia.com/content/invert-always-invert-69794.
3. Pólya, G. *How to Solve It.* Princeton University Press, 1945; 2nd edition 1957. I did not verify the ISBN. https://en.wikipedia.org/wiki/How_to_Solve_It.
4. Mytkowicz, T., Diwan, A., Hauswirth, M. and Sweeney, P. F. "Producing Wrong Data Without Doing Anything Obviously Wrong!" ASPLOS 2009. doi:10.1145/1508244.1508275. https://sape.inf.usi.ch/publications/asplos09 (abstract and excerpts only).
5. Mytkowicz, T., Diwan, A., Hauswirth, M. and Sweeney, P. F. "Evaluating the Accuracy of Java Profilers." PLDI 2010, pp. 187-197. doi:10.1145/1806596.1806618. https://plv.colorado.edu/papers/profilers-pldi10.html.
6. Curtsinger, C. and Berger, E. D. "STABILIZER: Statistically Sound Performance Evaluation." ASPLOS 2013, pp. 219-228. doi:10.1145/2451116.2451141. https://people.cs.umass.edu/~emery/pubs/stabilizer-asplos13.pdf.
7. Curtsinger, C. and Berger, E. D. "Coz: Finding Code that Counts with Causal Profiling." SOSP 2015. doi:10.1145/2815400.2815409. https://arxiv.org/abs/1608.03676 (summaries only).
8. Berger, E. D., Stern, S. and Altmayer Pizzorno, J. "Triangulating Python Performance Issues with Scalene." OSDI 2023, pp. 51-64. https://www.usenix.org/conference/osdi23/presentation/berger (read in full from `docs/osdi23-berger.pdf` in https://github.com/plasma-umass/scalene).
9. Kanev, S. et al. "Profiling a Warehouse-Scale Computer." ISCA 2015. doi:10.1145/2749469.2750392. https://research.google/pubs/pub44271/ (abstract and excerpts).
10. Leiserson, C. E., Thompson, N. C., Emer, J. S., Kuszmaul, B. C., Lampson, B. W., Sanchez, D. and Schardl, T. B. "There's plenty of room at the Top." Science 368 (2020). doi:10.1126/science.aam9744.
11. Proebsting, T. "Proebsting's Law: Compiler Advances Double Computing Power Every 18 Years." 1998. https://proebsting.cs.arizona.edu/law.html.
12. Hipp, D. R. SQLite 3.8.7 announcement, sqlite-users mailing list, 2014 (https://mail-archive.com/sqlite-users@sqlite.org/msg86235.html), and "Measuring and Reducing CPU Usage in SQLite" (https://www.sqlite.org/cpu.html). Read through search excerpts only: direct fetch was blocked by the session's network policy.
13. Nethercote, N. "How to speed up the Rust compiler" (series, 2016 onward). https://blog.mozilla.org/nnethercote/2016/10/14/how-to-speed-up-the-rust-compiler/.
14. Tang, C. et al. (Meta). "FBDetect: Catching Tiny Performance Regressions at Hyperscale through In-Production Monitoring." SOSP 2024. https://tangchq74.github.io/FBDetect-SOSP24.pdf. The 0.005 % figure is Meta's own, as stated in the paper's extended version and on its engineering blog.
15. Good, I. J. "The population frequencies of species and the estimation of population parameters." Biometrika 40(3-4):237-264, 1953. https://www.gwern.net/doc/statistics/order/capture/1953-good.pdf.
16. Chao, A. "Estimating the population size for capture-recapture data with unequal catchability." Biometrics 43:783-791, 1987. The bias-corrected form is as implemented in https://rdrr.io/cran/wiqid/src/R/richEstimators.R.
17. Dorfman, R. "The Detection of Defective Members of Large Populations." Annals of Mathematical Statistics 14(4):436-440, 1943.

**Limits:**
- WebFetch could not reach www.sqlite.org, mail-archive.com or arxiv.org (the session's network policy). Claims from [4], [7], [9], [12] and [14] rest on search excerpts, and are marked as such above.
- No file under `/home/user/step3-emergence-r1` was written. Upstream repositories were cloned read-only into the scratchpad.
