# s1-perf-eng errata (full-text check, 2026-11-13)

## Sources

| # | citation (short) | status: full text / open substitute / unverified | file under sources/s1-perf-eng/ or why none |
| --- | --- | --- | --- |
| 1 | Gregg, *Systems Performance*, 2nd ed., 2020 | open substitute | Commercial textbook, no open full text. Substitutes: Gregg's own method pages [2] `2-gregg-use.html` and [3] `3-gregg-tsa.html`. The notes attribute no claim to [1] alone. |
| 2 | Gregg, "The USE Method" (web page) | full text | `2-gregg-use.html` |
| 3 | Gregg, "The TSA Method" (web page) | full text | `3-gregg-tsa.html` |
| 4 | Bentley, *Writing Efficient Programs*, 1982 | open substitute | Commercial book, no open full text. Substitute: MIT 6.172 Lecture 2 "Bentley Rules for Optimizing Work" [6], `6-mit6172-lec2.pdf`. The notes already took the rules from [6]. |
| 5 | MIT 6.172 F18, Lecture 1 (Leiserson) | full text | `5-mit6172-lec1.pdf` (+ `.txt`) |
| 6 | MIT 6.172 F18, Lecture 2 (Shun) | full text | `6-mit6172-lec2.pdf` (+ `.txt`) |
| 7 | Leiserson et al., *Science* 2020 | unverified | Open copy exists (Semantic Scholar: GREEN, MIT DSpace hdl 1721.1/159445), but dspace.mit.edu answered 429 twice, 15 min apart (retry-after 900); not worked around. The notes were written from a gwern.net copy, which this check does not accept. |
| 8 | Amdahl, AFIPS 1967 | full text | `8-amdahl.pdf`. The IEEE SSCS News reprint, from a Stony Brook course page. |
| 9 | Gustafson, *CACM* 1988 | full text | `9-gustafson.pdf`, from a University of Utah course page |
| 10 | Williams, Waterman and Patterson, Roofline, *CACM* 2009 | full text | `10-roofline.pdf`, the LBNL copy on OSTI |
| 11 | Knuth, *Computing Surveys* 1974 | unverified | No allowed open copy. Semantic Scholar lists `openAccessPdf` as CLOSED, and dl.acm.org answered 403 (not worked around). The University of Oslo hit was an exhibition poster, not the paper. The notes were written from a gwern.net copy, a third-party mirror that this check does not accept. |
| 12 | Jin et al., PLDI 2012 | full text | `12-jin-pldi12.pdf`, from a University of Waterloo course page |
| 13 | Curtsinger and Berger, Coz, SOSP 2015 | full text | `13-coz.pdf` (arXiv:1608.03676) |
| 14 | Graham, Kessler and McKusick, gprof, 1982 | full text | `14-gprof.pdf`: the "Best of PLDI 1979-1999" reprint, with the 2003 retrospective plus the original paper as scanned pages, from a University of Michigan course page. I checked the original's abstract (reprint p. 51) from a rendered image, because the scan has no text layer. |
| 15 | Mytkowicz et al., PLDI 2010 | full text | `15-mytkowicz-pldi10.pdf`, from the authors' group site (plv.colorado.edu) |
| 16 | Ousterhout, *CACM* 2018 | full text | `16-ousterhout.pdf`, from a University of Waterloo course page |
| 17 | Shetty et al., GSO, arXiv 2025 | full text | `17-gso.pdf` (arXiv:2505.23671v3). Only the paper's findings were read: no dataset instances and no expert patches. |

## Corrections

- **[1]/[3] Core sources item 1.** As written: "[2] and [3], which Gregg says the book's Applications chapter covers".
  - The TSA page says the TSA Method "is also covered in the Applications chapter of my Systems Performance book".
  - The USE page says only "It is covered in my book on Systems Performance, published by Prentice Hall (2013)", which is the 1st edition.
  - So the chapter claim holds for TSA only, and both pages refer to the 2013 edition, not the 2nd edition cited as [1].
- **[2] USE.** These quotes and examples are confirmed:
  - "For every resource, check utilization, saturation, and errors";
  - "solves about 80% of server issues with 5% of the effort";
  - "can approach finding 100%";
  - the mutex definition;
  - the five-minute-average CPU example.
- **[3] TSA.** Confirmed:
  - "For each thread of interest, measure total time in different thread states";
  - the six states;
  - the MySQL Runnable example ("misleading").
- **[5] Notes table, "Parallel loops + tiling" row.** As written: "62 % fewer cache references, 68 % fewer cache misses than parallel loops alone".
  - That is the slide's sentence (Lecture 1, slide 48), but the slide's own table does not support it:

    | Counter | Parallel loops | + tiling | Change |
    | --- | ---: | ---: | --- |
    | Cache references (millions) | 104,090 | 64,690 | about 38 % fewer (tiled is 62 % of the original) |
    | L1-d misses (millions) | 17,220 | 11,777 | about 32 % fewer (68 % of the original) |
    | Last-level misses (millions) | 8,600 | 416 | about 95 % fewer |

  - The slide's "62%" and "68%" are the remaining ratios, not reductions. Read the table, not the sentence.
- **[5] Bearing on L10.** As written: "tiling removes 68 % of cache misses".
  - Correct to: tiling cuts L1-d misses by about 32 % and last-level misses by about 95 % (slide 48 table).
  - The rest of the row is confirmed: Python 21,041.67 s; Java 2,387.32 s; C 1,155.77 s; interchange 177.68 s (6.50x); AVX intrinsics 0.39 s, 53,292x, 41.677 % of peak.
  - "With the same operations" is my inference from what loop interchange is. The slide does not state it.
  - Lecture 1's title slide names Charles E. Leiserson; the notes' "6.172 Lecturers" may be replaced by his name.
- **[6] Lecture 2.** Confirmed:
  - the "New Bentley Rules" list (slide 47);
  - the precomputation definition;
  - the closing advice (slide 48).
  - The title slide names Julian Shun.
- **[8] Amdahl.** Confirmed: "accounts for 40% of the executed instructions in production runs"; "an upper limit on throughput of five to seven times the sequential processing rate" (reprint, p. 483).
  - The reprint's editors note the original "has no equations". The notes correctly take the formula from Gustafson [9].
- **[9] Gustafson, p. 532.** Confirmed:
  - 1021 for beam stress and 1020 for baffled surface wave;
  - "One does not take a fixed-size problem and run it on various numbers of processors";
  - the s components (vector startup, program loading, serial bottlenecks, I/O);
  - scaled speedup = s' + p' x N.
  - Two additions:
    - the paper credits the scaled-speedup expression to E. Barsis at Sandia;
    - a third result is 1016 (fluid flow), with s = 0.4 to 0.8 percent in the three applications.
- **[10] Roofline.** Confirmed:
  - "Attainable GFlops/sec = Min(Peak Floating Point Performance, Peak Memory Bandwidth x Operational Intensity)" (Section 3);
  - ceilings (Section 4);
  - demonstrated on "four key floating-point kernels" (abstract).
- **[12] Bearing on L10.** As written: "over a third of loss is uncoordinated calls; over a quarter is skippable calls".
  - The paper counts bugs, not lost performance: "More than a third of the performance bugs" (42 of 109) and "More than a quarter of bugs" (34 of 109) (Section 4.1, Table 2).
  - Correct to "of bugs". The paper gives no share of lost time.
  - Every other number from [12] is confirmed (Sections 4.1, 4.3 and 4.4, Table 2):
    - 109 bugs from five suites;
    - "performance is mostly lost at call sites and function boundaries";
    - 42 / 34 / 12 root causes;
    - 47 / 35 / 13 fixes;
    - 33 of 47 call-sequence fixes use only existing functions;
    - median patch 8 lines, and 42 of 109 patches at 5 lines or fewer;
    - about two thirds need large-scale inputs;
    - 29 were "not born buggy";
    - the profiling quote (Section 4.5).
- **[13] Coz.** Confirmed (abstract and Section 1):
  - Memcached 9 %, SQLite 25 %, six PARSEC applications "by as much as 68%";
  - "Optimizing fa away entirely will only speed up the program by 4.5%".
  - Addition: "in most cases, these optimizations involve modifying under 10 lines of code".
- **[14] gprof.** Status upgraded from summary-only to confirmed. The 1982 abstract (reprint p. 51) says an execution profiler "must attribute execution time in a way that is significant for the logical structure of a program" and that gprof "accounts for the running time of called routines in the running time of the routines that call them".
  - Add DOI 10.1145/800230.806987.
  - The 2003 retrospective in the same file adds: "function boundaries did not correspond to abstraction boundaries".
- **[15] Notes, "Four Java profilers disagreed on the hottest method".** The paper says they "often disagree on the identity of the hot methods" and on "the time spent in methods"; "If two profilers disagree, at least one must be incorrect" (abstract and Section 1).
  - Correct "the hottest method" to "the hot methods", and drop "abstract-level summary only".
- **[16] Ousterhout.** Confirmed: "I have been involved in dozens of performance-measurement projects and cannot recall a single one in which the first results were correct". Also confirmed: "Rule 4: Always measure one level deeper ... measure not just that level but also the next level deeper".
- **[17] GSO.** Confirmed:
  - "less than 5% success rate", measured by Opt@1 (abstract, Section 1), with Opt@10 "remaining around 15%";
  - "agents frequently misdiagnose the root cause of performance issues";
  - "lazy optimizations" (Sections 1 and 5.2).
  - Addition that bears on L10 (Section 5.2): "in over 60% of incorrect trajectories, the agent made ≤ 15% of the edits compared to the corresponding human developer commit". Gold patches hold "4-15× more lines edited than previous benchmarks" (Section 1).
- **[7] Leiserson et al.** No correction could be checked: there is no allowed full text this session (see Sources). Bibliographic details confirmed by Semantic Scholar: the title, DOI 10.1126/science.aam9744, and PubMed 32499413. The notes' Sources entry should read "read from a third-party copy (gwern.net); MIT DSpace open copy rate-limited (429)".

## Claims still unverified

- **[11] Knuth.** All three quotes stay unverified against an allowed copy:
  - "concentrated in about 3 % of the source text";
  - "speeding up the inner loop by 10 % speeds up everything by almost 10 %";
  - "their intuitive guesses fail".

  The volume and issue (6(4), 1974) and the DOI resolve on Semantic Scholar. The notes' Sources entry should read "read from a third-party copy (gwern.net); no open full text found".
- **[1] and [4].** No claim in the notes rests on the books themselves; they rest on the substitutes [2], [3] and [6].
- **Shi on Amdahl and Gustafson.** The notes give no citation for it and it stays unverified (not downloaded).
- **[7] Leiserson et al.** Every number stays unverified until the MIT DSpace copy can be read:
  - Java 10.8x;
  - C a further 4.4x ("47 times");
  - 0.41 s, "more than 60,000 times" (62,806x in Table 1);
  - "more than 20 times longer";
  - "80% × 80% = 64%" and "less than 1%" after 20 more reductions.

  The 6.172 Lecture 1 table [5] (full text) independently confirms the same kind of Python-to-AVX progression, on different hardware with different numbers.

## Overview sources

| # | source (short) | kind: TOC / chapter summaries / syllabus / topic list / reading list | file under sources/s1-perf-eng/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | Gregg, *Systems Performance* 2nd ed., author's book page | TOC (16 chapters) | `1-gregg-sysperf2-toc.html` |
| 2 | Gregg, "Performance Analysis Methodology" (author's site) | topic list (methods and anti-methods) | `2-gregg-methodology.html` |
| 3 | MIT 6.172 Fall 2018, OCW syllabus | syllabus | `3-mit6172-syllabus.html` |
| 4 | MIT 6.172 Fall 2018, OCW calendar | topic list (23 lectures, recitations, homeworks) | `4-mit6172-calendar.html` |
| 5 | Bakhvalov et al., *Performance Analysis and Tuning on Modern CPUs* (open book, public repo, read-only clone of file names only) | TOC (section file list) | `5-bakhvalov-perfbook-toc.txt` |
| 6 | Slotin, *Algorithms for Modern Hardware* (en.algorithmica.org/hpc) | TOC | `6-algorithmica-hpc-toc.html` |
| - | Gorelick and Ozsvald, *High Performance Python*, O'Reilly page | TOC | refused: 403 |
| - | Bentley, *Programming Pearls* site (cs.bell-labs.com) | TOC | refused: 502 (host unreachable through the proxy; not a bot refusal) |

## Not yet covered

- **"Quantify: estimate speedup if problem fixed" and the Time Division / Drill-Down methods (#2).** This is the engine's Amdahl-ceiling gate stated as a method. It bears on L1: drilling down from caller to callee is how a gain outside the hot function gets priced.
- **Anti-methods, especially Random Change and Streetlight (#2).** Ideas not anchored to measured cost resemble Random Change, and looking only where the profiler shines is Streetlight. Both bear on L1 and L10.
- **Workload Characterization (#2).** It bears on whether the benchmark's input sizes make set-up or per-element cost "hot" (L10; Gustafson in the notes).
- **Stack Profile Method and flame graphs (#2, #5 ch. 7).** These are caller-context views. They bear on L10's proposal to show callers by inclusive time.
- **Noise in modern systems, regression detection, microbenchmarks and active benchmarking (#5 ch. 2, #2).** These bear on L3, L4, L7 and L9. They belong to the statistics seat and are not in my notes.
- **Dynamic memory and storage allocation (#4 L11–L12, #5 §8-3).** Object-allocation churn in Python parsers may be gain that sits in the data layout rather than in a loop (L10).
- **Memory profilers (#5 §7-8).** The engine's default objective includes peak memory, which my notes do not cover. Its judges are frozen, so this is a note only.
- **"What compilers can and cannot do" (#4 L9).** The analogue is what CPython's own optimizations already do (the CPython seat). It bears on decoys: code that looks slow and is not.
- **DSLs and autotuning (#4 L18).** Parameter search is related to the search seat's L8 and the unique keeps per round.
- **Cache-efficient and cache-oblivious algorithms (#4 L14–L15, #6).** Probably not relevant: interpreted Python parsers are dominated by interpreter overhead, not cache misses.
- **Top-Down Microarchitecture Analysis (#5 ch. 6).** Probably not relevant for pure-Python workloads.
- **Branch prediction, machine code layout and PGO (#5 ch. 10–11, #6).** Probably not relevant: these act below the interpreter, outside the editable library code.
- **Off-CPU analysis (#2, #1 ch. 5).** Probably not relevant for CPU-bound benchmarks. It may matter only for runner-VM stalls (L9).
