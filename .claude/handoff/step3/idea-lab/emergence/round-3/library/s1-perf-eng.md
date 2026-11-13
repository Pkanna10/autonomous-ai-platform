# s1-perf-eng: performance engineering

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **Gregg, *Systems Performance*, 2nd ed., 2020 [1], with his public method pages USE [2] and TSA [3].** These are the industry's standard checklist methods: resource-oriented (USE) and thread-oriented (TSA). I could not read the book itself because it is not public. Everything below comes from [2] and [3], which Gregg says the book's Applications chapter covers.
2. **Bentley, *Writing Efficient Programs*, 1982 [4], taught through MIT 6.172 Lecture 2, "Bentley Rules for Optimizing Work" [6].** This is the catalogue of work-reducing transformations. I did not access the book. The rules below are the 6.172 revision.
3. **MIT 6.172, Fall 2018, Lectures 1 and 2 [5][6].** This is the standard university course. It has a measured case study of 4096x4096 matrix multiply.
4. **Leiserson et al., "There's plenty of room at the Top", *Science* 2020 [7].** Performance engineering as the main source of speed after Moore's law. It also gives the "bloat" argument.
5. **Amdahl 1967 [8] and Gustafson 1988 [9].** The two bounds on speedup: fixed-size and scaled.
6. **Williams, Waterman and Patterson, "Roofline", *CACM* 2009 [10].** A bound-and-ceiling model for kernels.
7. **Knuth, "Structured Programming with go to Statements", 1974 [11].** The origin of the "critical 3 %" and "measure first" rules.
8. **Jin et al., "Understanding and Detecting Real-World Performance Bugs", PLDI 2012 [12].** An empirical study of where real performance loss sits. It is the most direct evidence for L10.
9. **Curtsinger and Berger, "Coz", SOSP 2015 [13].** It shows that time spent in a piece of code is not the gain available there.
10. **Ousterhout, "Always Measure One Level Deeper", *CACM* 2018 [16].** Measurement discipline.

## Notes (the methods and results, cited inline as [n])

**Method 1: the USE checklist.** "For every resource, check utilization, saturation, and errors" [2].
- Gregg says it "solves about 80% of server issues with 5% of the effort" [2].
- Latency-based methods "can approach finding 100%" but take longer [2].
- It extends to software resources. For a mutex, utilization is the time the lock is held; saturation is the threads queued on it [2].
- One example from [2]: a CPU averaged at most 80 % over five-minute samples, yet hit 100 % for seconds at a time. Averages hide saturation.

**Method 2: TSA.** "For each thread of interest, measure total time in different thread states" [3].
- The six states are Executing, Runnable, Anonymous Paging, Sleeping, Lock and Idle [3].
- Gregg's warning, relevant to a shared runner VM: "time spent in MySQL" can really be Runnable time stolen by another tenant. Reporting it as MySQL time is "misleading" [3].

**Method 3: Amdahl.** In [8], data-management "housekeeping" was 40 % of executed instructions. Because that overhead is sequential, it would "place an upper limit on throughput of five to seven times" the sequential rate [8].
- In formula form, as Gustafson writes it, speedup = 1/(s + p/N) [9].
- Knuth's version for a single program: "speeding up the inner loop by 10 % speeds up everything by almost 10 %". Running time is "concentrated in about 3 % of the source text" [11].
- Knuth also warns that a priori guesses fail: "the universal experience of programmers who have been using measurement tools has been that their intuitive guesses fail" [11].

**Method 4: Gustafson.** Under scaling, "One does not take a fixed-size problem and run it on various numbers of processors" [9].
- Scaled speedup = s' + p'N [9].
- The serial part s is made of "vector startup, program loading, serial bottlenecks and I/O" [9]. In other words, s is set-up cost.
- Results on 1024 processors: 1021x for beam stress and 1020x for surface-wave simulation [9].
- **Lesson:** which code is "hot" depends on the input size the benchmark uses. Fixed set-up cost dominates at small sizes and vanishes at large ones.

**Method 5: Roofline.** Attainable performance = min(peak compute, peak bandwidth x operational intensity) [10].
- "Ceilings" mark the optimizations needed to climb towards each roof [10].
- It is built for floating-point kernels [10]. Interpreted Python parsers sit far below both roofs, so its direct use here is small. Its transferable idea is a ceiling per optimization, which the engine already has as an Amdahl ceiling.

**Method 6: Bentley's rules, as revised in 6.172 [6].**

| Group | Rules |
| --- | --- |
| Data structures | packing and encoding; augmentation; precomputation; compile-time initialization; caching; lazy evaluation; sparsity |
| Logic | constant folding; common-subexpression elimination; algebraic identities; short-circuiting; ordering tests; creating a fast path; combining tests |
| Loops | hoisting; sentinels; unrolling; fusion; eliminating wasted iterations |
| Functions | inlining; tail-recursion elimination; coarsening recursion |

- Precomputation is defined as doing calculations "in advance so as to avoid doing them at 'mission-critical' times" [6].
- Closing advice: "Reducing the work of a program does not necessarily decrease its running time, but it is a good heuristic" [6].
- **Several rules move cost out of the hot function by construction.** Precomputation and compile-time initialization move it to set-up. Hoisting moves it to the caller's loop. Augmentation and packing move it into the data structure.

**Worked numbers: 6.172 Lecture 1 [5], 4096x4096 matrix multiply.**

| Version | Time | Note |
| --- | ---: | --- |
| Python | 21,041.67 s | |
| Java | 2,387.32 s | |
| C | 1,155.77 s | |
| C + loop interchange | 177.68 s | 6.50x over C, with the same operations, only the access order changed |
| Parallel loops + tiling | | 62 % fewer cache references, 68 % fewer cache misses than parallel loops alone |
| AVX intrinsics | 0.39 s | 53,292x over Python, 41.677 % of peak |

- [7] gives a different machine's table:
  - Java is 10.8x over Python, and C a further 4.4x ("47 times faster").
  - The final version takes 0.41 s, "more than 60,000 times faster" (62,806x in its table).
  - The optimized code is "more than 20 times longer" than the Python [7].
- [7]'s bloat argument: layered reductions compound. "80% × 80% = 64%", and 20 more layers leave "less than 1%" efficiency [7]. Layered abstraction is cost that no single hot function owns.

**Where real loss sits [12].** The study covers 109 bugs from Apache, Chrome, GCC, Mozilla and MySQL; "performance is mostly lost at call sites and function boundaries" [12].

| Root cause | Bugs |
| --- | ---: |
| Uncoordinated functions (efficient calls combined inefficiently) | 42 |
| Skippable function (a call whose results go unused) | 34 |
| Synchronization | 12 |

| Fix strategy | Bugs |
| --- | ---: |
| Change call sequence | 47 |
| Change condition | 35 |
| Change a parameter | 13 |

- 33 of the 47 call-sequence fixes use only existing functions.
- The median patch is 8 lines; 42 of 109 patches change 5 lines or fewer.
- About two thirds of the bugs need large-scale inputs to show.
- 29 bugs "were not born buggy". They became inefficient later, through workload shift.
- On profiling: "It is difficult to use profiling alone to locate the root cause of a performance bug that has a long propagation chain or wastes computation time at function boundaries" [12].

**Profilers mislead [13][14][15].**
- "Code that runs for a long time is not necessarily a good choice for optimization." In Coz's two-thread example, removing fa entirely gives 4.5 % [13].
- Coz's results: Memcached +9 %, SQLite +25 %, PARSEC up to +68 % [13].
- **Caveat:** Coz's mechanism concerns concurrency. For a single-threaded CPU workload, Amdahl's accounting holds exactly.
- gprof charges callees' time to their callers so that the profile reflects program structure [14]. I saw only the abstract and man-page text; the PDF did not download.
- Four Java profilers disagreed on the hottest method [15]. I read this only as an abstract-level summary.
- Ousterhout "cannot recall a single [project] in which the first results were correct". His rule 4: measure the next level down to check the top-level number [16].
- GSO (paper findings only): agents reach under 5 % success, "misdiagnose the root cause", and practise "lazy optimization" [17]. I read this only as abstract-level text.

**Well established:**
- Amdahl's accounting.
- Locality and data-layout effects of the size [5] measures.
- Fixes are small and sit at call boundaries [12].
- Profile time is not the same as available gain [12][13].

**Contested:**
- Whether Amdahl and Gustafson differ in substance. A search summary of Shi says they are equivalent; I did not read Shi, so I give no citation.
- How far Coz's critique carries to single-threaded code.
- Whether USE's 80 % is more than Gregg's own estimate [2].

## Bearing on the ledger (per row you touch: L#, what your field says, numbers)

**L1: ideas that never become trials.**
- **Engine fact, from reading the code.** The grounding check `idea_lanes._ground` drops an idea whose quote "lies outside every hot function", names "no shown document", or is not found. The context shows the top 8 hotspots by cumulative time (`idea_context.py`, `hot_functions=8`). So module-level tables, set-up code, and callers outside a hot span cannot ground an idea.
- **What the field says.** Bentley's precomputation and compile-time initialization [6], Gustafson's s [9], and Jin's call-boundary losses [12] are exactly that code.
- **My count from the O62 rows** (`live/ideas-x2-X2-0-4318*.jsonl`):
  - 23 of the 31 `read:ungrounded` ideas are from the one sqlparse run (7, then 16, in row order);
  - mistune has 6, tomli 2, markdown 0.
- **Not recorded:** the grounding sub-reason.
- **Hypothesis, unverified:** the sqlparse drops quote set-up or table code outside hot spans, such as module-level regex tables.
- **Field verdict.** A gate that admits only ideas grounded in the profile's hot spans encodes the "hot spot" view that [12] and [13] say misses much of the real gain.

**L6: combine below its best part.**
- **Amdahl accounting, my derivation from [8][9].** The engine's gain is time saved over base time (`anticheat.relative_gain`).
  - Keeps on disjoint code add exactly: g = gA + gB.
  - Keeps on the same fraction p compose at best: p = 0.3 with two 1.5x changes gives 0.10 each but 0.167 together, not 0.20.
  - If they remove the same redundancy, they are substitutes: 0.10 together.
  - So a textual conflict marks substitutes. The rational pick is the larger measured saving. With non-negative parts, a combine below its best part needs either the best part left out or a negative interaction.
- **My recount on `live/`.** 12 of 65 runs with keeps deliver below the best keep's first-look gain. In those 12 the median delivered is +10.1 against +13.4.
  - This does not match the ledger's "+17.4 against +11.3". The ledger's medians may cover all runs, or be swapped.
- **Cause, by run:**
  - **Best keep left out by a textual conflict with a lower-gain applied keep (6 runs):** five in `zero-credit/q1_left_out.csv`, one more in its run row's `skipped`. The shortfalls in points:

    | Run | Best keep | Delivered |
    | --- | ---: | ---: |
    | X2-0 markdown, 316a634f | 21.8 | 10.1 |
    | X2-D markdown, af0d2b9a | 20.7 | 9.9 |
    | X2-0 markdown, 8de73b17 | 16.0 | 10.6 |
    | X2-0 sqlparse | 17.5 | 15.2 |
    | X2-0 markdown, cdccc54d | 13.4 | 11.9 |
    | X2-P sqlparse | 16.8 | 16.7 |

  - **The failed combine (1 run):** this is L7.
  - **Best keep not recorded as left out (5 runs):** the shortfall is 0.1 to 1.5 points. That is re-measurement shrinkage, for the statistics seat.
- **Engine fact.** Without a dry merge (X2-0), the greedy order is by hypothesis score, not measured gain (`combine_node.py`, the score sort). The by-gain max-sum plan (`plan_delivery`, S2) exists but X2-0 does not run it.

**L10: edits confined to the hot function.**
- **What the field says** [12]:
  - over a third of loss is uncoordinated calls;
  - over a quarter is skippable calls;
  - the commonest fix (47 of 109) changes the caller's call sequence;
  - patches are small (median 8 lines).
- Loop interchange gives 6.5x with the same operations, and tiling removes 68 % of cache misses [5]: the gain is in access order and data layout, not in the operations.
- Bloat lives across layers [7].
- **Prediction for the expert-practice seat's count:** much of the expert gain will be in callers, set-up and data structures. The archive agrees in part: the largest blocked keeps are prefilters and dispatch tables, the "change condition" and "augmentation" fixes of [12] and [6].

**Also touched: L3 and L9.** TSA's Runnable state is the measurable form of VM noise [3]. Ousterhout's rule 4 [16] argues for recording per-run steal time.

## Open questions for the seminar

1. **Grounding sub-reason (record-only).** Of the 31 ungrounded ideas, how many quote code outside every hot function, and how many name an unshown file? Kill: if fewer than 25 % are "outside hot function", L1 is not a hot-spot-confinement loss.
2. **L6 offline replay.** In the 6 conflict runs, swap the blocker for the best keep, or use S2's by-gain plan, and re-measure the tip. Kill, stated before the run: the delivered gain improves by more than its floor in fewer than 3 of 6.
3. **Caller and set-up spans in context.** Can callers and set-up code be shown without crowding out the hot code? Showing callers by inclusive time (gprof [14]) is one option.
4. **Benchmark input size.** Does it match realistic use? Gustafson [9] and Jin's two-thirds "large-scale" finding [12] say input size decides what is hot.
5. **L6's medians.** Which run set does the ledger's L6 medians row describe?

## Sources (numbered list, full citations with URL or ISBN)

1. Gregg, B. *Systems Performance: Enterprise and the Cloud*, 2nd ed. Addison-Wesley/Pearson, 2020. ISBN 978-0-13-682015-4. (Not read: not public.)
2. Gregg, B. "The USE Method." https://www.brendangregg.com/usemethod.html (read).
3. Gregg, B. "The TSA Method." https://www.brendangregg.com/tsamethod.html (read).
4. Bentley, J. L. *Writing Efficient Programs*. Prentice-Hall, 1982. ISBN 0-13-970244-X. (Not accessed; via [6].)
5. MIT 6.172 Lecturers. "Introduction and Matrix Multiplication", Lecture 1, *Performance Engineering of Software Systems*, Fall 2018. MIT OCW. https://ocw.mit.edu/courses/6-172-performance-engineering-of-software-systems-fall-2018/d0c73dd51c79b95196a2e6faa824e1b4_MIT6_172F18_lec1.pdf (read).
6. Shun, J. (6.172 Lecturers). "Bentley Rules for Optimizing Work", Lecture 2, 6.172 Fall 2018. MIT OCW. https://ocw.mit.edu/courses/6-172-performance-engineering-of-software-systems-fall-2018/1a57adbec9520270d4485b42a2e1a316_MIT6_172F18_lec2.pdf (read).
7. Leiserson, C. E., Thompson, N. C., Emer, J. S., Kuszmaul, B. C., Lampson, B. W., Sanchez, D., Schardl, T. B. "There's plenty of room at the Top: What will drive computer performance after Moore's law?" *Science* 368, eaam9744, 2020. DOI 10.1126/science.aam9744 (read: accepted manuscript, https://www.gwern.net/doc/cs/hardware/2020-leiserson.pdf).
8. Amdahl, G. M. "Validity of the single processor approach to achieving large scale computing capabilities." AFIPS Spring Joint Computer Conference, vol. 30, 1967, pp. 483–485. DOI 10.1145/1465482.1465560 (read: reprint, https://www3.cs.stonybrook.edu/~rezaul/Spring-2019/CSE613/reading/Amdahl-1967.pdf).
9. Gustafson, J. L. "Reevaluating Amdahl's Law." *CACM* 31(5), 1988, pp. 532–533. DOI 10.1145/42411.42415 (read: https://users.cs.utah.edu/~hari/teaching/paralg/Gustafson88.pdf).
10. Williams, S., Waterman, A., Patterson, D. "Roofline: an insightful visual performance model for multicore architectures." *CACM* 52(4), 2009, pp. 65–76. DOI 10.1145/1498765.1498785 (read: https://www.osti.gov/servlets/purl/963540).
11. Knuth, D. E. "Structured Programming with go to Statements." *ACM Computing Surveys* 6(4), 1974. DOI 10.1145/356635.356640 (read: https://www.gwern.net/doc/cs/algorithm/1974-knuth.pdf).
12. Jin, G., Song, L., Shi, X., Scherpelz, J., Lu, S. "Understanding and Detecting Real-World Performance Bugs." PLDI 2012, pp. 77–88. DOI 10.1145/2254064.2254075 (read: https://ece.uwaterloo.ca/~wshang/soen691/current/papers/pldi118-jin.pdf).
13. Curtsinger, C., Berger, E. D. "Coz: Finding Code that Counts with Causal Profiling." SOSP 2015. DOI 10.1145/2815400.2815409; arXiv:1608.03676 (read: abstract and introduction).
14. Graham, S. L., Kessler, P. B., McKusick, M. K. "gprof: a Call Graph Execution Profiler." SIGPLAN Notices 17(6), 1982, pp. 120–126. https://web.eecs.umich.edu/~weimerw/2009-4610/reading/graham-gprof.pdf (download failed; abstract and man-page text via search only).
15. Mytkowicz, T., Diwan, A., Hauswirth, M., Sweeney, P. F. "Evaluating the Accuracy of Java Profilers." PLDI 2010, pp. 187–197. DOI 10.1145/1806596.1806618 (abstract via search only).
16. Ousterhout, J. "Always Measure One Level Deeper." *CACM* 61(7), 2018, pp. 74–83. DOI 10.1145/3213770 (read: https://rcs.uwaterloo.ca/~ali/cs854-f23/papers/onelevel.pdf).
17. Shetty, M. et al. "GSO: Challenging Software Optimization Tasks for Evaluating SWE-Agents." arXiv:2505.23671, NeurIPS 2025 Datasets and Benchmarks (published findings via abstract and search only; no instances or patches read).

*Access note:* WebFetch could not resolve several hosts (brendangregg.com, arxiv.org, ocw.mit.edu, gwern.net), but `curl` through the proxy reached them. Downloads and extracted text are in `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/s1-perf-eng/dl/`. Nothing was written to `/home/user/step3-emergence-r1`.
