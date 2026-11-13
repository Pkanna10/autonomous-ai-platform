# s3-equivalence errata (full-text check, 2026-11-13)

Files are under `library/sources/s3-equivalence/`. All downloads used plain `curl -sSL` through the session proxy. Refusals (Cloudflare bot checks, a TLS chain failure, connection resets, a login wall) were not worked around.

## Sources
| # | citation (short) | status: full text / open substitute / unverified | file under sources/s3-equivalence/ or why none |
| --- | --- | --- | --- |
| 1 | McKeeman 1998, Differential Testing for Software, DTJ 10(1) | open substitute | `1-wiki-difftest.html` (Wikipedia "Differential testing"). The DTJ host (www.hpl.hp.com) reset the connection twice and no other open copy was found |
| 2 | Claessen & Hughes 2000, QuickCheck, ICFP | unverified | Semantic Scholar lists the ACM copy as CLOSED; the Tufts copy reset the connection and the Northwestern copy did not resolve. `2-wiki-quickcheck.html` holds bibliographic data only |
| 3 | MacIver, Hatfield-Dodds et al. 2019, Hypothesis, JOSS 4(43):1891 | full text | `3-hypothesis-joss.txt` (paper.md from the public repository) |
| 4 | Hypothesis `ghostwriter.equivalent()` source | full text | `4-ghostwriter-equivalent.txt` |
| 5 | Godlin & Strichman, Regression verification (DAC 2009; STVR 23(3), 2013) | open substitute | `5-godlin-strichman-grand.pdf/.txt`: Strichman & Godlin, "Regression Verification - a practical way to verify programs" (Technion, same authors). No open copy of the DAC or STVR text was found; Semantic Scholar does not find the STVR DOI |
| 6 | Pnueli, Siegel & Singerman 1998, Translation validation, TACAS | unverified | The Weizmann page returned an empty reply; no other open copy was found |
| 7 | Necula 2000, Translation validation for an optimizing compiler, PLDI | full text | `7-necula.pdf/.txt` (author copy) |
| 8 | Lopes et al. 2021, Alive2, PLDI | full text | `8-alive2.pdf/.txt` |
| 9 | King 1976, Symbolic execution and program testing, CACM | open substitute | The ACM PDF is behind a Cloudflare bot check (refused). `9-wiki-symbolic-execution.html` (citation only) |
| 10 | Person, Dwyer, Elbaum & Păsăreanu 2008, Differential symbolic execution, FSE | open substitute | Semantic Scholar lists it as CLOSED. `10-dse-ntrs.pdf/.txt`: Person & Dwyer et al., "Generalized Abstract Symbolic Summaries" (NASA NTRS 20100024480), which describes DSE |
| 11 | CrossHair `diffbehavior` documentation | full text | `11-crosshair-diffbehavior.txt` |
| 12 | DeMillo, Lipton & Sayward 1978, Hints on test data selection, IEEE Computer | open substitute | No open copy was found. `12-wiki-mutation-testing.html` |
| 13 | Just et al. 2014, Are mutants a valid substitute for real faults, FSE | full text | `13-just-mutants.pdf/.txt` |
| 14 | Papadakis, Jia, Harman & Le Traon 2015, TCE, ICSE | unverified | The UCL PDF is behind a Cloudflare bot check (refused); orbilu.uni.lu failed TLS verification (not bypassed); Semantic Scholar returned 429. The Zenodo record 268492 holds code only |
| 15 | Schkufza, Sharma & Aiken 2013, Stochastic Superoptimization, ASPLOS | full text | `15-stoke.pdf/.txt` (arXiv 1211.0557) |
| 16 | Yang, Chen, Eide & Regehr 2011, Csmith, PLDI | full text | `16-csmith.pdf/.txt` (preprint) |
| 17 | Qi, Long, Achour & Rinard 2015, Kali, ISSTA | full text | `17-kali.pdf/.txt` (author copy) |
| 18 | Smith, Barr, Le Goues & Brun 2015, Is the cure worse than the disease?, FSE | open substitute | The FSE copy URL returned 404 and Semantic Scholar lists it as CLOSED. `18-overfitting-umass.pdf/.txt`: the UMass technical report UM-CS-2015-007, a full text of the same study |
| 19 | GSO HackDetector blog (Shetty, Jain, 2025-11-03) | open substitute | The Notion page renders only through JavaScript, so its text could not be read. Substitutes: `19c-gso-paper.pdf/.txt` (GSO paper, arXiv 2505.23671), `19-gso-site.html` (benchmark site changelog), `19b-perfagent.pdf/.txt` (PerfAgent, arXiv 2607.19653) |
| 20 | Horwitz, Prins & Reps 1989, Integrating noninterfering versions of programs, TOPLAS | full text | `20-hpr.pdf/.txt` |
| 21 | Engine source and archive (judges.py, anticheat.py, outputs.py, workloads, `w2-sprint/live/`), tomli 2.5.0 | full text | Local, read only; nothing copied |

Counts: 11 full text, 7 open substitute, 3 unverified.

## Corrections
- [1] Core sources: the definition of differential testing is confirmed by the substitute only (Wikipedia: "providing the same input to a series of similar applications … and observing differences in their execution"). The DTJ 10(1):100-107 citation is confirmed by the same page. **Withdrawn:** "Every later compiler fuzzer traces back to it". No text I read supports it.
- [2] Notes, "The QuickCheck and Hypothesis approach adds generators and shrinking [2][3]" -> I could not check that the 2000 QuickCheck paper describes shrinking. Shrinking should be cited to [3] alone. The JOSS paper says property-based testing "traditionally" uses random generation "followed by test-case reduction", and that Hypothesis does reduction through one universal representation (paper.md, "Hypothesis for Software Testing Research"). The ICFP 2000 citation itself (pp. 268-279) is as given in Hypothesis's paper.bib.
- [3], [4], [11]: confirmed (read in full before filing).
- [5] Notes, the "three reasons" (no specification needed, natural decomposition, automatic invariant for loops) -> these still rest on the STVR abstract only. The substitute (same authors) confirms in its §1: industrial code cannot be expected to carry formal specifications; equivalence is "generally undecidable" but becomes practical "if one is willing to sacrifice completeness"; and a section headed "Optimizations with Uninterpreted Functions" abstracts syntactically equal functions. One difference: in the substitute's tool, the user specifies a loop iteration bound k_i. An *automatic* invariant is not described there.
- [7] Necula: gcc; "compares the intermediate form of the program before and after each compiler pass"; built "with about the effort typically required to implement one compiler pass". All confirmed (abstract, p. 1). **Page range:** the author copy's header reads "pages 83–95", not 83-94.
- [8] Alive2: loops unrolled to a bound, so it can miss bugs; 47 new bugs found over LLVM's unit test suite, 28 of them fixed. Both confirmed (abstract). **Withdrawn from [8]:** "Alive2 does this in daily use on LLVM" (Core sources item 4). The paper does not say it; it came from a search snippet of J. Lee's thesis, which I did not read.
- [9] The citation is confirmed by the substitute (CACM 19(7):385-394). No content claim was made.
- [10] Confirmed by the substitute: DSE "compares" the symbolic summaries of two program versions and "uses uninterpreted functions" to abstract common blocks (§1).
- [12] Confirmed by the substitute: "The value of a test suite is measured by the percentage of mutants that it kills". DeMillo, Lipton & Sayward, IEEE Computer 11(4):34-41, 1978.
- [13] 357 real faults, 230,000 mutants, coupling for 73 % of real faults, 17 % not coupled, correlation independent of code coverage: all confirmed (abstract and contributions list, §1). Addition from the same list: 10 % of real faults need a new or stronger mutation operator, and the mutant-detection correlation is stronger than that of statement coverage.
- [14] TCE (>7 % equivalent, >21 % duplicate, about 30 % of equivalent mutants found): **still unverified**, abstract and snippet only.
- [15] Notes, "Performance comes from a static latency sum or from timing" -> the paper adopts the static approximation. It rejects timing for the search loop because compiling and timing is "prohibitively expensive to be used in MCMC's innermost loop" (§3, Performance Improvement). Notes, the two-stage pipeline cited to a Cornell blog -> it is in the paper itself:
  - the testcase term uses the Hamming distance of live outputs (§3, Transformation Correctness);
  - a failed validation "will produce a counterexample testcase that may be used to refine τ" (discussion of Eq. 12);
  - the final validator is sound, encoding loop-free sequences as SMT formulae for STP (§5.2 Validation).
  The Cornell blog is not needed.
- [16] More than 325 previously unknown bugs, three years of Csmith testing, randomized differential testing: confirmed (abstract, §1, conclusion).
- [17] Notes, "for 37 of the 55 defects GenProg reported as repaired, the validation infrastructure had errors" -> the full text says: "Because of errors in the patch validation infrastructure, for 37 of 55 defects that GenProg is reported to repair, none of the reported patches produce correct outputs for the inputs in the test suite" (p. 1). "Overwhelming majority … not correct and … equivalent to a single modification that simply deletes functionality": confirmed (abstract). Additions from §1:
  - GenProg produced a correct patch for only 2 of 105 defects, RSRepair for 2 of 24, AE for 3 of 105;
  - 104 of 110 plausible GenProg patches, 37 of 44 plausible RSRepair patches and 22 of 27 plausible AE patches are equivalent to a single functionality deletion.
- [18] "Patches overfit … more when the suite has lower coverage": confirmed in the TR ("tools produce patches that overfit more when given lower-coverage" training suites, §1). The TR's title is "Is the Cure Worse than the Disease? A Large-Scale Analysis of Overfitting in Automated Program Repair", and it names the second tool TSPRepair.
- [19] Notes, "up to 30 % of a model's attempts are reward hacks" -> **unverified**; the Notion text could not be read. What the full texts do confirm:
  - **The GSO paper (Appendix C.2, "Manual Curation of Benchmark Instances")** says that when "our tests initially indicated repeated calls to functions with the same arguments for robust measurements … this led to models generating patches that simply cached the output of the function calls!". The authors fixed this by removing such hints and running outside the test scripts. It also names tests that "did not cover all edge cases or only covered a small subset of the input space".
  - **The GSO site changelog (2025-11-03)** says the Hack Detector penalises "deceptive optimizations (e.g., memoization, harness hijacking)".
  - **PerfAgent (§IV, hack detection)**: "the most common hack we observed was caching results inside benchmark timing loops". Confirmed.
  - **Bearing:** the GSO appendix finding is the closest published match to the archive's memoisation rejects, because the tomli workload parses the same document 8 times (REPEAT = 8) and the sqlparse workload lexes each statement in both `format` and `parse`.
- [20] TOPLAS 11(3):345-387, July 1989; the Integrate algorithm (inputs A, B, Base) using dependence graphs and slices; text-based comparators give "no guarantees about how the program that is the product of an integration behaves": all confirmed (p. 345 abstract and §1).

## Claims still unverified
- [2] Whether the ICFP 2000 QuickCheck paper describes shrinking (cite [3] for reduction instead).
- [5] The STVR abstract's three reasons, the "automatic invariant" in particular, and the STVR page range 241-258.
- [6] Any content of Pnueli, Siegel & Singerman 1998.
- [14] All TCE numbers: >7 % equivalent, >21 % duplicate, about 30 % of equivalent mutants.
- [19] The GSO blog's "up to 30 %" hack rate.
- Not one of my sources: the J. Lee thesis claim that Alive2 is used daily by LLVM developers (withdrawn above).

## Sealed-set note (overview.md rule)
Before this rule reached me, a content search I ran, `grep -rln sqlparse` over `services/python_agents`, scanned the files of `tests/fixtures/upstream_corpus/`. It listed three paths: `workloads/sqlparse-reindent-offset.py`, `workloads/sqlparse-group-comments.py` and `manifest.json`. Only their names were shown to me; I did not open or read any of them. I cloned no commit that the corpus names: tomli was cloned at tag 2.5.0, taken from `tests/fixtures/live_oss/manifest.json`. I have not compared the two manifests and will not.

## Overview sources
| # | source (short) | kind: TOC / chapter summaries / syllabus / topic list / reading list | file under sources/s3-equivalence/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | CMU 17-355/665/819 Program Analysis (Spring 2025 and Fall 2026 pages) | syllabus / topic list / reading list | `overview/1-cmu-17355-2025.html`, `overview/1-cmu-17355-2026.html` |
| 2 | Zeller et al., The Fuzzing Book | TOC | `overview/2-fuzzingbook-toc.html` |
| 3 | Ammann & Offutt, Introduction to Software Testing (author site, cs.gmu.edu) | TOC | refused: TLS certificate verification failure (curl 60), not bypassed |
| 4 | MIT OCW 6.820 Fundamentals of Program Analysis (Fall 2015) | syllabus / topic list / reading list | `overview/4-mit-6820-ocw.html` |
| 5 | Cornell CS 6120 Advanced Compilers (2023fa) | syllabus | refused: TLS certificate verification failure (curl 60) |
| 6 | Kroening & Strichman, Decision Procedures (book site) | TOC | refused: DNS resolution failure (curl 6) |
| 7 | Zeller, The Debugging Book | TOC | `overview/7-debuggingbook-toc.html` |
| 8 | UW CSE 507 Computer-Aided Reasoning for Software | syllabus | refused: login wall (UW NetID identity-provider page); the bare course URLs returned 404 |

## Not yet covered
- **Grammar coverage fuzzing (overview #2, GrammarCoverageFuzzer).** My fuzzer missed mutant M8 because its grammar never produced `__`. Grammar coverage is the standard remedy, and it sets how far a differential audit can be trusted (keep correctness beside L3 and L6).
- **Grammar mining (#2, GrammarMiner).** Deriving input grammars from the four parsers would make a per-library differential audit cheap without hand-written generators.
- **Concolic and symbolic fuzzing (#1 Concolic Testing, #2 ConcolicFuzzer and SymbolicFuzzer).** They target the guard branches of fast paths, where rare-input traps hide (exam tiers 3 and 4).
- **Greybox and coverage-guided fuzzing (#2).** A cheaper alternative to grammars for the same audit; the cost against the yield is unmeasured here.
- **Test-case reduction and delta debugging (#2 Reducer, #7 DeltaDebugger and DDSetDebugger).** Small counterexamples could feed the bounded self-retry on failed trials, with the error fed back.
- **When to stop fuzzing (#2).** A residual-risk stopping rule would price an audit's budget per keep.
- **Dynamic invariants (#2 and #7 DynamicInvariants).** Inferred preconditions of a fast path compare directly with the playbook's preconditions (L1 `ungrounded`).
- **Program slicing (#7 Slicer; #1 dependence analyses).** The machinery behind Horwitz-Prins-Reps noninterference; it could tell textual conflicts from semantic ones (L5, L6).
- **Pointer and alias analysis (#1).** It bears on memo caches that return shared mutable objects, the rejected memoisation family.
- **Dataflow analysis and abstract interpretation (#1, #4).** Static proof that a fast path's guard implies the slow path's result; relevant to wider edits (L10), but heavy for Python.
- **SAT/SMT (#1).** Needed by any sound validator; CrossHair already relies on a solver.
- **Performance debugging (#7 PerformanceDebugger).** Locating cost away from the profiler's hot spot (L10; exam plants hidden in callers).
- **Automated repair (#7 Repairer).** It relates to the overfitting results [17][18] and to engine self-healing.
- **Hoare logic and axiomatic semantics, type theory, model checking (#1, #4):** probably not relevant at this engine's scale.
