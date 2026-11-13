# fp-compose errata (full-text check, 2026-11-13)

Downloads were made with plain `curl -sSL` through the session proxy. Two hosts refused automated clients with a 403: dl.acm.org and oreilly.com. The DTIC copy of Appel's report also returned 403. None of these refusals was worked around. Two further hosts did not resolve: cs.wisc.edu (www) and cs.montana.edu. Text files beside each source are `pdftotext` or tag-stripped extractions.

At filing time, the notes' sources had this status:
- read in full: [14] only;
- read from a search summary only: [5], [6], [8], [9], [10];
- not accessed: [1], [2], [3], [4], [7], [11], [12], [13].

## Sources

| # | citation (short) | status | file under sources/fp-compose/ or why none |
| --- | --- | --- | --- |
| 1 | Amdahl 1967, AFIPS SJCC 30:483–485 | full text | `1-amdahl-1967.pdf` (Stony Brook CSE613 course copy of the 2007 IEEE SSCS News reprint) |
| 2 | Hennessy & Patterson, CA:AQA 6th ed., ch. 1 | open substitute | Commercial textbook with no open copy. Substitutes: `2-sub-amdahl-wikipedia.html` and the "Amdahl's Law" sidebar in `4-hill-marty.pdf` |
| 3 | Gustafson 1988, CACM 31(5):532–533 | full text | `3-gustafson-1988.pdf` (Utah course copy). The ACM copy refused automated clients (403). |
| 4 | Hill & Marty 2008, IEEE Computer 41(7):33–38 | full text | `4-hill-marty.pdf` (research.cs.wisc.edu, the authors' group) |
| 5 | Bentley, Programming Pearls 2nd ed., Column 6 | unverified | Commercial book; the O'Reilly page returned 403. Its numbers are checked against [6] instead. |
| 6 | Appel 1985, SIAM J. Sci. Stat. Comput. 6(1):85–103 | open substitute | `6-appel-cmu-cs-83-118.pdf`: the 1983 CMU technical report CMU-CS-83-118 of the same work, from CMU KiltHub. The SIAM version is paywalled; the montana.edu copy did not resolve and DTIC returned 403. |
| 7 | Knuth 1971, SP&E 1(2):105–133 | unverified | Semantic Scholar reports CLOSED, and no open copy was found. The CWI search hit was a different report (Alanen 1972), so it was deleted. |
| 8 | Curtsinger & Berger 2015, Coz, SOSP | full text | `8-coz.pdf` (arXiv 1608.03676) |
| 9 | Smith & Winkler 2006, Mgmt Sci 52(3):311–322 | open substitute (partial) | `9-smith-winkler-correction.pdf`: the authors' own 2007 correction note. Semantic Scholar reports the paper CLOSED. The only full-text copy found is a third-party mirror (gwern.net), which was not used. |
| 10 | Siegmund et al. 2012, ICSE 167–177 | full text | `10-siegmund.pdf` (Saarland University copy, 11 pages) |
| 11 | Chapman 1951, UC Publ. Stat. 1:131–160 | open substitute | `11-sub-mark-recapture-wikipedia.html` (sections on Lincoln–Petersen and Chapman). The original is not online. |
| 12 | Chao 1987, Biometrics 43(4):783–791 | unverified | Semantic Scholar reports CLOSED (JSTOR), and no open copy was found. Only the bibliographic details were checked. |
| 13 | Python docs, "The Python Profilers" | full text | `13-python-profile.html` (now the deprecated `profile` page of the 3.15 docs) and `13b-python-profiling-tracing.html` |
| 14 | Archive (`w2-sprint/`, the live_oss manifest, `combine_node.py`) | full text | Read in full in place, read-only. Not copied. |

## Corrections

- **[1] Notes ("founding bound").** The notes cite Amdahl for the bound that overall gain is capped by the share of time the improved part takes, with the formula implied.
  - The 1967 paper gives **no equation**. It argues in words that data-management housekeeping, about 40 % of executed instructions and sequential, "would then place an upper limit on throughput of five to seven times the sequential processing rate" (p. 483).
  - Hill & Marty's sidebar [4] says the same: Amdahl argued "without presenting an equation". The fraction form f, S is the later "modern version" stated there.
  - The substance stands. The notes' "saved-time form" (adding saved fractions) is my derivation, not Amdahl's. The derivation matches the multi-part form 1/Σ(pᵢ/sᵢ) in the [2] substitute.
- **[6]/[5] Core sources and Notes ("year to a day", "levels multiplying to about 400").**
  - The report's abstract states that the changes "reduced the running time of a large problem (N=10,000) by a factor of four hundred". This confirms the factor of 400.
  - Table 8-1 lists **six** levels, not the four in my notes: algorithm ×12, problem-specific knowledge ×2, data structure ×2, system-independent code tuning ×2, system-dependent code tuning (hand-coding the hot routine) ×2.5, and hardware (Floating-Point Accelerator) ×2. Their product is 480, not 400.
  - Section 8 also states "from 4000 hours to 20 hours — a factor of two hundred (for ten thousand bodies)", so the report itself gives both 200 and 400.
  - "A year to a day" does not appear in Appel. The report defines "expensive" as "days of Cray-1 time or a year of VAX time". The phrase remains Bentley's [5], unverified.
- **[10] Notes ("about 15 points above a model that ignores them").** The paper (contributions list, §I) says "a 95 percent prediction accuracy when feature interactions are included, which is a 15 percent improvement over an approach that takes no interactions into account". It does not say "points". The 95 % is an average over six case studies (abstract). Those numbers are now confirmed from the full text, not a search summary.
- **[13] Notes, distortion atom ("Python's profiler documentation treats this overhead as something to calibrate").**
  - Calibration belongs to the deprecated pure-Python `profile` module only. The `profile` page says the C implementation's overhead is "negligible", so calibration "is not needed".
  - The `profiling.tracing` page (the cProfile alias) says instrumenting every event "introduces overhead that can slow down program execution". It adds that timing errors "can become significant for functions called many times", but are "less pronounced" in the C extension.
  - So the documentation supports the direction of the claim (call-heavy code is over-charged) but not the calibration remedy for cProfile. The 2.8–3.4x figures rest only on the manifest's measured profiled/plain times.
- **[8] Notes, location atom.** Confirmed from the full text: the abstract says "Memcached by 9%, SQLite by 25%, and accelerate six PARSEC applications by as much as 68%; in most cases ... under 10 lines of code". The results table gives streamcluster 68.4 % ± 1.12 %, SQLite 25.60 % ± 1.00 % and Memcached 9.39 % ± 0.95 %. "Profilers only report where programs spent their time: optimizing that code may have no impact on performance" is confirmed (abstract).
- **[3] Core sources ("scaled-workload rebuttal").** Confirmed: "One does not take a fixed-size problem and run it on various numbers of processors" (p. 532), with 1024-processor speed-ups of 1021 and 1020.
- **[4] Core sources ("Amdahl's law applied to composed resources").** Confirmed, more precisely as a chip budget of n base core equivalents (BCEs) shared among cores (pp. 33–34).
- **[2] Core sources (H&P ch. 1 states the fraction form).** The book could not be checked. The substitutes give the same form: 1/((1−p)+p/s) with a worked example of p = 0.3, s = 2, giving 1.18 (Wikipedia), and Speedup(f, S) = 1/((1−f)+f/S) (Hill & Marty sidebar).
- **[9] Core sources and Notes.** The 2007 Figure-3 correction is confirmed from the authors' note: the expected-disappointment values "are incorrect", and the corrected values are "substantially larger" and decrease more slowly as Δ grows. The core claim (disappointment even with unbiased estimates) is still from the abstract only.
- **[11] Notes, finite-pool atom.** Confirmed via the substitute: the Chapman estimator is (n+1)(K+1)/(k+1) − 1, and Lincoln–Petersen "is biased at small sample sizes".
- **[12] Sources ("details from memory").** The bibliographic details are now confirmed via Semantic Scholar: Biometrics 43(4), 783–791, 1987, DOI 10.2307/2531532. The claim itself is still unverified (see below).

## Claims still unverified

- [5] Bentley, Column 6: Appel's run went "from a year to a day", and the column's framing of design levels.
- [7] Knuth 1971: that profiles show a small share of code dominating running time, and the comp.compilers remark that most examples sit near 50 % rather than 90 %. That remark is secondary in any case.
- [12] Chao 1987: that unequal catchability biases Lincoln–Petersen and Chapman estimates **low**. The Wikipedia substitute does not state it. The L8 statement that N ≈ 4–6 is "a lower bound" depends on this claim and stays provisional.
- [9] Smith & Winkler: the main result itself, which I have from the abstract and summaries only, not the paper body.
- [2] Hennessy & Patterson's own chapter-1 wording. The formula is confirmed only through the substitutes.

## Overview sources

These are used as a map only, never as evidence for a claim. Files are under `sources/fp-compose/overview/`, with a `.txt` tag-stripped extraction beside each.

| # | source (short) | kind | file under sources/fp-compose/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | MIT OCW 6.172, Performance Engineering of Software Systems (Fall 2018, Leiserson and Shun) | syllabus; topic list (23 lectures) | `1-mit-6172-syllabus.html`, `1b-mit-6172-lectures.html` |
| 2 | Hennessy & Patterson, *Computer Architecture: A Quantitative Approach*, 6th ed. (Elsevier page) | TOC | `2-hp-caqa6-toc.html` |
| 3 | Jain, *The Art of Computer Systems Performance Analysis* (author's site) | TOC | `3-jain-perfbook.html`, `3-jain-perfbook-toc.html` |
| 4 | Gregg, *Systems Performance*, 2nd ed. (author's site) | TOC | `4-gregg-sysperf2.html` |
| 5 | UC Berkeley CS267, Applications of Parallel Computers (Spring 2023 course site) | syllabus (motivation and outline only; no topic list on the page) | `7-cs267-syllabus.html` |
| 6 | Bentley, *Programming Pearls*, 2nd ed. TOC | TOC | refused: 502 (bell-labs.com proxy tunnel). The O'Reilly page had already returned 403 in the full-text step. |
| 7 | Cooch & White, *Program MARK: a gentle introduction* (open capture–recapture book) | TOC | refused: DNS (www.phidot.org does not resolve) |

## Not yet covered

- **Bentley rules for optimizing work** (#1, lecture 2). A catalogue of work-removal rules: precompute, cache, short-circuit, fuse, augment the data structure. It could classify the kept diffs and name rules never tried on the untouched components (L10, L1).
- **Measurement and timing** (#1, lecture 10). Quiet-machine and timer practice. It bears on L3, L4, L7 and L9, but belongs to the statistics and measurement seats.
- **High performance in dynamic languages** (#1, lecture 23). Interpreter and call-overhead costs. It bears on how far cProfile shares of Python helpers misstate plain-time Amdahl shares (L10 distortion).
- **Domain-specific languages and autotuning** (#1, lecture 18). Systematic search over variants. It bears on L8 (pool exhaustion against a broader search space).
- **2^k and fractional factorial designs** (#3, Part IV). These estimate pairwise interactions among keeps with few measurements, in place of one greedy combine. They bear directly on L5 and L6 (the overlap atom).
- **Ratio games and common mistakes** (#3, Parts I and II). Percent saved against speed-up ratios, and changing bases. They bear on X2-DT reading gains against a moving tip, where relative gain inflates by 1/(1−G) (L8).
- **Workload characterisation and selection** (#3, Part II). Whether benchmark-shaped gains generalise. Probably not relevant: the benchmarks are frozen.
- **Operational laws and queueing models** (#3, Part VI). Probably not relevant: single-threaded batch benchmarks.
- **Methodology: drill-down, latency analysis, USE** (#4, ch. 2). A systematic descent below the top profile entry. It bears on L10 (the components never attacked).
- **Active benchmarking** (#4, ch. 12). Checking what a benchmark actually exercises while it runs. It bears on L9 and on profile trust.
- **Memory hierarchy and cache-efficient algorithms** (#2, ch. 2; #1, lectures 14–15). Probably not relevant at the Python level, where interpreter overhead dominates.
- **Strong and weak scaling performance models** (#5). Probably not relevant beyond the Gustafson point already in the notes.
- **Capture–recapture models with heterogeneous catchability** (#7, not fetched). This is the evidence the L8 "pool size is a lower bound" claim needs (see [12] above).
