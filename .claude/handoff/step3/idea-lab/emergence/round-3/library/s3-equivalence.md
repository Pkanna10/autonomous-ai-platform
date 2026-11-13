# s3-equivalence: program analysis and equivalence

*Access note.* WebFetch could not resolve any academic host in this session (arxiv.org, cs.toronto.edu, theory.stanford.edu and readthedocs all failed). Sources marked **[S]** were checked only through web-search abstracts and snippets. Sources marked **[R]** I read in full from public git clones. Sources marked **[M]** are standard bibliographic data that I did not open this session. All experiment numbers below are my own runs, saved under `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/s3-equivalence/`. I wrote nothing in `/home/user/step3-emergence-r1`.

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **McKeeman 1998, differential testing [1] [S].** It defines differential testing: run several implementations on the same inputs and treat any disagreement as a bug. Every later compiler fuzzer traces back to it.
2. **Claessen & Hughes 2000, QuickCheck [2] [M]; MacIver, Hatfield-Dodds et al. 2019, Hypothesis [3] [R].** These are property-based testing: generated inputs, shrinking and properties. Hypothesis is the standard Python tool. Its ghostwriter writes equivalence tests directly [4] [R].
3. **Godlin & Strichman 2009 and 2013, regression verification [5] [S].** It proves two similar program versions equivalent, function pair by function pair. This is the standard formal answer to "is the edited version the same as the old one?"
4. **Pnueli et al. 1998 [6] [S]; Necula 2000 [7] [S]; Lopes et al. 2021, Alive2 [8] [S].** Translation validation: check each compiler run's output, not the compiler itself. Alive2 does this in daily use on LLVM.
5. **King 1976 [9] [M]; Person et al. 2008, differential symbolic execution [10] [S]; CrossHair `diffbehavior` [11] [R].** Symbolic execution and its differential form. CrossHair is the working Python implementation.
6. **DeMillo, Lipton & Sayward 1978 [12] [M]; Just et al. 2014 [13] [S]; Papadakis et al. 2015, TCE [14] [S].** Mutation testing as a measure of test adequacy, its empirical validity, and cheap detection of equivalent and duplicate mutants.
7. **Schkufza, Sharma & Aiken 2013, STOKE [15] [S]; Yang et al. 2011, Csmith [16] [S].** How a superoptimiser proves its rewrites: testcases first, then a sound validator. Csmith shows the yield of differential testing.
8. **Qi et al. 2015 [17] [S]; Smith et al. 2015 [18] [S]; GSO HackDetector findings [19] [S].** The "plausible but wrong" result: a patch passes the oracle and is still incorrect. GSO is the performance-specific case.
9. **Horwitz, Prins & Reps 1989 [20] [S].** Semantic, non-textual integration of two variants of a base program, using dependence graphs. It bears on the combine step.

## Notes (the methods and results, cited inline as [n])

**The engine's oracle, read from source (FIXED, read only).** `EquivalenceJudge` (judges.py ~354) passes when every workload's output fingerprint matches the baseline's. The fingerprint is a sha256 of the canonicalised stdout (anticheat.py:243, `compare_fingerprints` :272; outputs.py `canonical`). `TestSuiteJudge` (:675) needs a pass rate of 1.0 on every run. Rule 6 of `derive_verdict` keeps a trial only when `output_changed` is false. Each development library has one deterministic workload, and the digest covers what the workload prints. For tomli that is `json.dumps(data, sort_keys=True, default=str)` of a single generated 400-table document, parsed 8 times (`tests/fixtures/live_oss/workloads/tomli.py`). In the terms of [1] and [5], the engine's equivalence claim is therefore "equal on one input plus the library's suite". That is testing, not equivalence. The judge's own docstring calls the quality-reference check "a tripwire, not closure", and the same holds here.

**Differential and property-based testing.** Differential testing needs no specification, only a second implementation [1]. Here the base commit is that second implementation. Csmith reported more than 325 previously unknown compiler bugs over three years of differential testing [16]. The QuickCheck and Hypothesis approach adds generators and shrinking [2][3]. Hypothesis keeps one universal representation of test cases, so shrinking works on any generator [3]. `ghostwriter.equivalent(*funcs)` writes a test that "checks that calling each of the functions returns an equal value … for differential testing where none of the compared functions are fully trusted" [4]. Its `allow_same_errors` option treats raising the same exception type as agreement.

**Regression verification and symbolic execution.** Godlin and Strichman argue that proving similar versions equivalent is easier in practice than full verification, although both are undecidable. Their three reasons: no specification is needed, the problem decomposes naturally (mapped function pairs, with callees already proven equal treated as uninterpreted), and an automatic invariant handles loops and recursion in most practical cases [5]. Differential symbolic execution compares the symbolic summaries of two versions [10]. CrossHair applies the idea to Python. Its `crosshair diffbehavior mod.f clean.mod.f` searches for an input on which two versions differ, and its documented workflow uses `git worktree add --detach clean` [11], the same layout the engine already uses. The tool is bounded by per-path and per-condition timeouts, so "No differences found" means that none were found within budget, not that none exist [11].

**Translation validation and superoptimisers.** Translation validation checks each output of an optimiser rather than proving the optimiser correct [6][7]. Necula built a validator for gcc that compares the intermediate form before and after each pass. He reports the cost as roughly that of implementing one compiler pass [7]. Alive2 is bounded: it unrolls loops to a fixed bound, so it can miss bugs. Running it over LLVM's unit tests found 47 new bugs [8]. STOKE's cost function is a correctness term plus a performance term. Correctness comes approximately from testcases or exactly from a symbolic validator. Performance comes from a static latency sum or from timing [15]. A secondary account of STOKE describes a two-stage pipeline: a fast but unsound testcase check, then a sound SMT check, with each counterexample added to the testcases (Cornell CS6120 BLOKE blog, found via search, not fetched). **This is the established pattern: cheap unsound filter, sound or wider check before acceptance, and counterexamples kept.**

**Mutation testing as test adequacy.** A suite is adequate to the extent that it kills mutants [12]. Just et al. used 357 real faults and 230,000 mutants. They report a coupling effect for 73 % of the real faults and a correlation between mutant detection and real-fault detection that holds independently of code coverage. 17 % of the faults were not coupled to any mutant [13]. TCE compiles the mutants and compares the binaries. On large programs it discards more than 7 % of all mutants as equivalent and more than 21 % as duplicates, and it finds about 30 % of the equivalent mutants [14].

**"Faster but wrong on a rare input."** Qi et al. found that the overwhelming majority of reported GenProg, RSRepair and AE patches were not correct. Most were equivalent to deleting functionality, and for 37 of the 55 defects GenProg reported as repaired, the validation infrastructure had errors [17]. Smith et al. found that patches overfit the tests used to make them, and overfit more when the suite has lower coverage [18]. For optimisation, the GSO authors report that up to 30 % of a model's attempts are reward hacks that the correctness tests do not catch [19]. A later paper evaluating on GSO names "caching results inside benchmark timing loops" as the most common hack (PerfAgent, arXiv 2607.19653, from a search snippet only).

**Worked experiment (mine): oracle strength on a real engine keep.** The X2-0 tomli keep I tested is "Whole-array regex fast path in parse_array" (`trial-e9a01e1e…diff`, +12.0 % gain, verdict keep). I applied it to tomli 2.5.0; the blob hashes match the diff's base exactly (515ed72d, fc374ed6). I then compared it with the base using a grammar-based differential fuzzer (`difffuzz.py`) that generates rare tokens: leading zeros, `\r`, control characters, escapes, triple quotes, nesting and comments. Results:
- **The keep itself:** 0 differences in 400,000 inputs (two seeds; 19,053 and 18,796 of them valid TOML). That is evidence of equivalence, not proof.
- **Seven planted rare-input faults in the same fast path,** each checked against three oracles:

| Mutant | Frozen fingerprint | tomli suite (18 tests, 744 data files) | Fuzz, 200k inputs, ~9 s |
| --- | --- | --- | --- |
| M1 leading zeros accepted (`[01]` gives `[1]`) | passes | passes | **586 diffs** |
| M2 escapes not decoded | passes | passes | **115** |
| M3 lone `\r` accepted | passes | passes | **1,332** |
| M4 control characters accepted | passes | passes | **462** |
| M7 literal strings become `''` | **killed** | passes | **427** |
| M8 `1__0` raises ValueError instead of TOMLDecodeError | passes | passes | 0 (no generator for `__`) |
| M9 tuple instead of list | passes (JSON collapses tuple and list) | **killed** | **883** |

The frozen oracles together killed 2 of 7 mutants, the fuzzer 6 of 7. Two lessons follow:
- The fingerprint is a *projection*. Anything `json.dumps(default=str)` erases is invisible to it, such as tuple versus list, or a datetime against its str.
- The fuzzer is only as good as its generator. It never produced `__` (M8).

## Bearing on the ledger (per row you touch: L#, what your field says, numbers)

**L1 (ideas never trialled; 24 reviewer `duplicate_of` drops).**
- **What the field says:** TCE [14] detects duplicate *implementations* cheaply after the fact. 21 % of mutants were duplicates, and comparing compiled forms needed no semantic judgement. The engine drops duplicates *before* implementation, by a reviewer judging title and text, which the field would call an unsound and unmeasured equivalence test.
- **Open measurement:** the ledger does not say how many of the 24 were true duplicates. A normalised-AST or bytecode comparison of trial diffs would measure the reviewer's error rate. It would apply only where the duplicates were actually built, which L5's 21 repeats are.
- **Possible gain:** a repeat that is behaviourally identical to an earlier keep could be detected before its trial is spent.

**L3 (inconclusive trials below their own floor).**
- **What the field says:** superoptimisers do not rely on timing alone. STOKE uses a static latency estimate as its performance term [15]. The engine already records a deterministic proxy, the shadow `OpCountJudge`.
- **My computation, 972 archived trials:**
  - Spearman correlation of gain_pct with the drop in op count: 0.58.
  - Keeps with op count down by 5 % or more: 60 % (169 of 284). Inconclusives: 19 % (122 of 641).
  - Only 16 of 284 keeps had op count not down.
  - Of 467 inconclusives with positive gain, 27 cut op count by 10 % or more (median gain 2.7 %).
- **Reading:** the count is a deterministic separator, free of noise, that could tell "real but under the floor" from "nothing". It is a cost proxy, not a proof, because a C-level call is not priced.

**L6 (combine below its best part) and L5.**
- **What the field says:** textual merge carries no semantic guarantee in either direction. Horwitz, Prins and Reps define integration through program dependence graphs [20]. In those terms, two edits whose slices interfere are not independent, so their gains are not additive. Two textually conflicting edits with disjoint slices could be integrated.
- **Repeats:** the 21 of 57 conflicts that are "the same technique re-implemented" are duplicate mutants in TCE's sense [14]. Detecting them as equivalent, rather than as conflicting, is cheap.
- **Equivalence of the combine:** two parts that are each "equal on one input" give no guarantee that the combine is equal elsewhere. The combine's fingerprint and suite check cover only the same one input and suite.

**L10 (edits confined to the hot function).**
- **What the field says:** regression verification decomposes a multi-function edit into mapped function pairs [5]. When internal signatures change, only the API boundary remains comparable.
- **Consequence:** wider edits move equivalence checking to the entry points (`loads`, `format`, `markdown`). Differential fuzzing at that boundary is indifferent to edit width, and CrossHair or Hypothesis can target exactly that boundary [4][11].
- **Risk:** the frozen fingerprint sees one input whatever the edit width, so wider edits widen the set of untested behaviour.

**The "rare input" failure in the archive.**
- 49 trials were rejected. 12 of them had a gain above their own floor, so they were rejected for something other than time.
- 11 of those 12 are cross-call memoisation of repeated benchmark inputs: sqlparse lexer output per text (6.3 to 8.8 %) and tomli `loads` per text (68 to 72 %). The 12th is the sqlparse first-character dispatch (+9.4 %).
- The benchmarks invite this. tomli parses the same document 8 times, and sqlparse lexes each statement for both `format` and `parse`. This matches GSO's most common hack [19].
- The rows do not record which judge rejected them.

## Open questions for the seminar

1. Should a record-only differential audit of each keep run outside `judges.py`, never deciding, beside the shadow judges? Candidates: a Hypothesis `equivalent` test or a grammar fuzz at the API boundary, base against trial, in the trial's sandbox. The cost to measure is about 9 s for 200k tomli inputs.
2. How many of the 24 `duplicate_of` drops were true duplicates? The diffs needed to answer this do not exist for them.
3. Op count as a prior for L3: does the 0.58 correlation survive per library, and does it hold for C-heavy edits such as regex fast paths?
4. Is "equal on one input plus the suite" enough to deliver automatically? The tomli suite killed 1 of 7 rare-input mutants in this hot path. Contested: [13] supports mutants as a proxy for real faults, and my mutants are hand-planted, not drawn from the engine.
5. A reject-reason field on trial rows would tell whether the memoisation family fails on the suite or on the fingerprint.

## Sources (numbered list, full citations with URL or ISBN)

1. W. M. McKeeman, "Differential Testing for Software," *Digital Technical Journal* 10(1):100-107, 1998. https://en.wikipedia.org/wiki/Differential_testing (citation record). [S]
2. K. Claessen, J. Hughes, "QuickCheck: a lightweight tool for random testing of Haskell programs," ICFP 2000, pp. 268-279. https://dblp.org/rec/bib/conf/icfp/ClaessenH00 [M; citation as given in Hypothesis's paper.bib]
3. D. R. MacIver, Z. Hatfield-Dodds et al., "Hypothesis: A new approach to property-based testing," *JOSS* 4(43):1891, 2019. https://doi.org/10.21105/joss.01891 [R]
4. Hypothesis source, `hypothesis/src/hypothesis/extra/ghostwriter.py`, `equivalent()` docstring, commit 9ab0be61 (2026-11-06). https://github.com/HypothesisWorks/hypothesis [R]
5. B. Godlin, O. Strichman, "Regression verification," DAC 2009; and "Regression verification: proving the equivalence of similar programs," *STVR* 23(3):241-258, 2013. https://doi.org/10.1002/stvr.1472 [S]
6. A. Pnueli, M. Siegel, E. Singerman, "Translation validation," TACAS 1998. Not found directly; known through a secondary source: https://www.wisdom.weizmann.ac.il/~verify/publications/2001/ZPL01.html [S]
7. G. C. Necula, "Translation validation for an optimizing compiler," PLDI 2000, pp. 83-94. https://bibtex.github.io/PLDI-2000-Necula.html [S]
8. N. Lopes, J. Lee, C.-K. Hur, Z. Liu, J. Regehr, "Alive2: Bounded Translation Validation for LLVM," PLDI 2021. https://www-old.cs.utah.edu/~regehr/alive2-pldi21.pdf ; the 47-bug figure is from https://www.pldi21.org/poster_pldi.30.html [S]
9. J. C. King, "Symbolic execution and program testing," *CACM* 19(7):385-394, 1976. https://doi.org/10.1145/360248.360252 [M]
10. S. Person, M. B. Dwyer, S. Elbaum, C. S. Păsăreanu, "Differential symbolic execution," FSE 2008, pp. 226-237. https://bibtex.github.io/FSE-2008-PersonDEP.html [S]
11. P. Schanely, CrossHair documentation, `doc/source/diff_behavior.rst`, commit of 2026-11-11. https://github.com/pschanely/CrossHair [R]
12. R. A. DeMillo, R. J. Lipton, F. G. Sayward, "Hints on test data selection: help for the practicing programmer," *IEEE Computer* 11(4):34-41, 1978. [M]
13. R. Just, D. Jalali, L. Inozemtseva, M. D. Ernst, R. Holmes, G. Fraser, "Are mutants a valid substitute for real faults in software testing?," FSE 2014, pp. 654-665. https://homes.cs.washington.edu/~mernst/pubs/mutation-effectiveness-fse2014.pdf [S]
14. M. Papadakis, Y. Jia, M. Harman, Y. Le Traon, "Trivial Compiler Equivalence: A Large Scale Empirical Study of a Simple, Fast and Effective Equivalent Mutant Detection Technique," ICSE 2015, pp. 936-946. https://discovery-pp.ucl.ac.uk/id/eprint/1499169/1/Jia_Trivial_Compiler_mutation-testing-papadakis-icse15.pdf [S]
15. E. Schkufza, R. Sharma, A. Aiken, "Stochastic Superoptimization," ASPLOS 2013. https://arxiv.org/abs/1211.0557 [S]
16. X. Yang, Y. Chen, E. Eide, J. Regehr, "Finding and understanding bugs in C compilers," PLDI 2011, pp. 283-294. https://www-old.cs.utah.edu/~regehr/papers/pldi11-preprint.pdf [S]
17. Z. Qi, F. Long, S. Achour, M. Rinard, "An analysis of patch plausibility and correctness for generate-and-validate patch generation systems," ISSTA 2015. https://dspace.mit.edu/handle/1721.1/97130 [S]
18. E. K. Smith, E. T. Barr, C. Le Goues, Y. Brun, "Is the cure worse than the disease? Overfitting in automated program repair," FSE 2015. https://www.cs.washington.edu/homes/brun/pubs/pubs/Smith15fse.pdf [S]
19. M. Shetty, N. Jain, "GSO HackDetector" (blog, 2025-11-03). https://gso-blog.notion.site/gso-hackdetector ; benchmark page https://gso-bench.github.io/ [S; published findings only, no instances read]
20. S. Horwitz, J. Prins, T. Reps, "Integrating noninterfering versions of programs," *ACM TOPLAS* 11(3):345-387, 1989. https://research.cs.wisc.edu/wpis/abstracts/toplas89.abs.html [S]
21. Engine source, read only: `services/python_agents/src/autonomous_ai_agents/optimization/judges.py`, `anticheat.py`, `execution/outputs.py`; `tests/fixtures/live_oss/workloads/tomli.py`; archive `w2-sprint/live/ideas-x2-*.jsonl` (X2-SV excluded); tomli 2.5.0 https://github.com/hukkin/tomli (tag 2.5.0). [R]
