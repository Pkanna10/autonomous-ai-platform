# s7-cpython errata (full-text check, 2026-11-13)

## Sources

How I read them when writing the notes: 15 of 16 sources were read in full from read-only clones or downloads. Only [11] was read from an abstract and search snippets. Every file below is a copy of the text I checked.

| # | citation (short) | status: full text / open substitute / unverified | file under sources/s7-cpython/ or why none |
| --- | --- | --- | --- |
| 1 | PSF, profiling / profiling.tracing / profile docs (CPython main `ab48ba8`) | full text | `1-cpython-profiling-docs.txt` (the rst sources; docs.python.org itself did not resolve from my fetch tool) |
| 2 | PSF, profiling.sampling (Tachyon) docs and What's New 3.15 | full text | `2-cpython-sampling-tachyon-docs.txt` |
| 3 | Shannon, PEP 659 | full text | `3-pep659.txt` (python/peps `155e5be`) |
| 4 | Galindo Salgado (ed.), What's New 3.11 | full text | `4-whatsnew-3.11.txt` |
| 5 | Shannon, PEP 669 | full text | `5-pep669.txt` |
| 6 | CPython `Modules/_lsprof.c`, 3.11, 3.12 and main | full text | `6-lsprof-c-3.11-3.12-main.txt` |
| 7 | Berger, Stern, Altmayer Pizzorno, Scalene, OSDI 2023 | full text | `7-scalene-osdi23.pdf` (usenix.org) |
| 8 | Curtsinger, Berger, Coz, SOSP 2015 | full text | `8-coz-sosp15.pdf` (sigops.org) |
| 9 | Jin et al., performance bugs, PLDI 2012 | full text | `9-jin-pldi12.pdf` (open course copy, ece.uwaterloo.ca) |
| 10 | Graham, Kessler, McKusick, gprof, 1982 | full text | `10-gprof-1982.pdf` (FreeBSD PSD:18 copy) |
| 11 | Mytkowicz, Diwan, Hauswirth, Sweeney, PLDI 2010 | full text (downloaded for this check) | `11-mytkowicz-pldi10.pdf`. Semantic Scholar lists it as CLOSED; this is the authors' copy at plv.colorado.edu/papers/mytkowicz-pldi10.pdf |
| 12 | Frederickson, py-spy README | full text | `12-py-spy-readme.txt` (`c53bfe1`) |
| 13 | Austin README (P403n1x87) | full text | `13-austin-readme.txt` (`9e6cc09`) |
| 14 | Python Wiki, PythonSpeed/PerformanceTips | full text | `14-python-wiki-performancetips.html` (the moin URL now redirects to wiki.python.org/python/performance/PythonSpeed/PerformanceTips.html) |
| 15 | faster-cpython/ideas, pystats docs | full text | `15-faster-cpython-pystats-docs.txt` (`e697f50`) |
| 16 | CPython InternalDocs, inlined comprehensions, and What's New 3.12 | full text | `16-inlined-comprehensions-whatsnew-3.12.txt` |

## Corrections

### Core sources

- **[7], item 5.** I wrote "measures the overhead of 16 Python profilers".
  - Table 3 has 17 rows, which are configurations of 12 profilers: py-spy, cProfile, yappi, pprofile, line_profiler, profile, pyinstrument, Austin, Memray, Fil, memory_profiler and Scalene.
  - Read: "17 configurations of 12 Python profilers".

### Notes, Overhead

- **[7], measured overheads.** The cProfile median of 1.73x and its range of 1.35x (fannkuch) to 2.63x (pprint) are confirmed. So are profile 15.1x, line_profiler 2.21x, yappi 3.17x (wall) and 3.62x (CPU), py-spy 1.02x, Austin 1.00x and Scalene CPU 1.02x (Table 3, section 6.4).
  - The "3.2-3.6x" for yappi is those two medians, rounded.

### Notes, cProfile and sys.monitoring

- **[5], the `INSTRUMENTED_CALL` quote.** Confirmed verbatim, in the implementation section.
- **[5], "Slowdowns by an order of magnitude are common".** Confirmed verbatim, in the Abstract.
- **[6], the counts.** On 3.11: 0 `PY_MONITORING_EVENT` and 3 `PyEval_SetProfile`. On 3.12: 9 `PY_MONITORING_EVENT`. These are `grep -c` counts of matching lines, not of individual references. Otherwise confirmed.

### Notes, PEP 659 and What's New 3.11

- **[3] and [4].** All confirmed:
  - "The largest contributors are speedups to attribute lookup, global variables, and calls" (PEP 659, Performance);
  - speed-ups estimated at 10-60%;
  - 1.25x on pyperformance, and "10-60%" by workload;
  - per-operation figures: builtin calls 20%, method loads 10-20%, subscript 10-25%;
  - inlined calls: 1.7x on recursive fibonacci, and 1-3% on pyperformance.

### Notes, cost location and fix location

- **[10], the gprof quote.** Confirmed verbatim. The venue, "SIGPLAN '82 Symposium on Compiler Construction, June, 1982", is confirmed from the paper's footnote.
- **[8], Coz dedup case.** All confirmed in section 4.2.1:
  - 14.38% for hashtable_search;
  - "changing just three lines of code";
  - +8.95% ± 0.27%;
  - 1.1% afterwards;
  - "Gprof's call graph actually obscured the importance of this code".
- **[9], Jin et al.**
  - Confirmed:
    - root causes: 42 uncoordinated functions, 34 skippable functions;
    - exposure: 71 bugs need large-scale inputs and 75 special-feature inputs;
    - patches: the median is 8 lines, and 42 of 109 are 5 lines or fewer;
    - both quotes, "performance is mostly lost at call sites and function boundaries" and the "difficult to use profiling alone" quote.
  - Wording fix: I wrote "an input-dependent loop or event handler". The text says "an input-dependent loop or an input-event handler" (section 4.5, Location).

### Notes, Sampling profilers

- **[11], previously read from the abstract only.** The claims are now confirmed from the full text (Abstract; section 1):
  - "four commonly-used Java profilers (xprof, hprof, jprofile, and yourkit) often disagree on the identity of the hot methods";
  - "to be correct, a sampling-based profiler must collect samples randomly".
  - The full text adds the observer effect: "dynamic optimizations interact with a profiler's sampling mechanism to produce profiler disagreement" (section 1, contribution 4). This supports the notes' point that cProfile's hooks change specialisation.
  - Drop the caveat "I read only the abstract, through search snippets".
- **[2], Tachyon.** All confirmed:
  - up to 1,000,000 Hz;
  - ±0.5% at 100,000 samples, and 3-7% at 1,000 samples;
  - the `--native` default, "No `<native>` frames (C code time attributed to caller)";
  - `--opcodes` showing `LOAD_ATTR_INSTANCE_VALUE`;
  - the advice to use tracing or timeit for differences of 1-2%.
- **[7], Scalene's method.** Confirmed: Python defers signals during native code, and Scalene uses the signal delay to split Python time from native time (section 2.1).
- **[12], py-spy.** Confirmed: it reads memory with `process_vm_readv` on Linux. Ben Frederickson holds the copyright (LICENSE).

### Notes, Idioms

- **[14], the wiki.** All confirmed:
  - "100MHz Pentium running BSDI";
  - 3.47 s, 2.45 s, 1.79 s, and 0.54 s for map;
  - "about four times faster" in the data-aggregate example.

### Sources list

- **[7], pages 51-64.** Confirmed from the PDF's page footers.
- **[16], editors.** "What's New 3.12" (ed. A. Turner) and "What's New 3.15" (ed. H. van Kemenade) are confirmed from the files' headers.

## Claims still unverified

- **[11], pages 187-197.** This comes from bibliographic records in search results (bibtex.github.io and the USI listing). The authors' PDF carries no page numbers.
- **The fixture measurements and the sqlparse lexer count.** They are my own measurements, not source claims, so this check does not cover them. Their scripts are under `work/s7-cpython/exp/`.

## Overview sources

These pages are a map of the field only; none of them is cited as evidence for a claim.

| # | source (short) | kind: TOC / chapter summaries / syllabus / topic list / reading list | file under sources/s7-cpython/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | Gorelick and Ozsvald, *High Performance Python*, 2nd ed., O'Reilly book page | TOC | refused: 403 (oreilly.com) |
| 2 | Shaw, *CPython Internals*, Real Python book page | TOC | refused: 403 (realpython.com) |
| 3 | MIT OCW 6.172, Performance Engineering of Software Systems, Fall 2018 (Leiserson, Shun), syllabus | syllabus | `3-mit-6172-syllabus.html` |
| 3b | MIT OCW 6.172, lecture-slides list | topic list | `3b-mit-6172-lectures.html` |
| 4 | Guo, "CPython internals" video course page (pgbovine.net) | topic list | not filed: the proxy returned 502 twice (CONNECT tunnel failed), so this is not a refusal by the site; not retried further |
| 5 | Gregg, *Systems Performance*, 2nd ed. (2020), the author's book page | TOC | `5-gregg-systems-performance-2e.html` |
| 6 | CPython `InternalDocs/README.md` (main) | topic list | `6-cpython-internaldocs-readme.md` |
| 7 | *High Performance Python*, 2nd ed., the authors' companion repository (mynameisfiber/high_performance_python_2e), chapter directories | TOC (chapter names only) | `7-hpp2e-companion-repo-chapters.txt` (substitute for #1) |
| 8 | Stinner, pyperf documentation index | topic list | `8-pyperf-docs-index.html` |

## Not yet covered

- **Memory profiling and peak memory** (from #7, chapter 11 "less RAM"; #5, chapter 7). The engine's default objective includes peak memory, but my notes cover CPU attribution only. tracemalloc and Scalene's memory sampler are the tools to study next.
- **Garbage-collector cost** (from #6, garbage collector design). Allocation-heavy plants show up as `<GC>` time in a sampler and not in cProfile. GC pauses also add run-to-run spread (L3, L9).
- **Measurement and timing practice** (from #3b, "Measurement and Timing"; #8, "Tune the system for benchmarks"; #5, chapter 12). Worker processes, calibration and system tuning bear on the noise floors (L3, L4, L7, L9). This is mostly the statistics seat's ground.
- **Linux perf with CPython's perf support** (from #5, chapter 13; the CPython howto `perf_profiling`). It could split interpreter overhead from C regex or str time inside a project function, the gap my notes found in the shim's dropped `~` entries.
- **Flame graphs as a whole-stack view** (from #5's site). A folded-stack view would show callers and set-up to the lanes, which bears on L1 (ungrounded ideas) and L10.
- **Lists, tuples, dicts and sets internals** (from #7, chapters 3-4). Data-structure plants beyond list-against-set membership: resizing, hashing cost and key sharing.
- **Iterators and generators** (from #7, chapter 5; #6, generators). Generator frames stay separate under PEP 709 and were the top self-time frame in my fixture D. Their per-item cost is not studied yet.
- **Frames and code objects** (from #6). These are the mechanism behind call overhead, which my notes cite only through PEP 659 and What's New 3.11.
- **The JIT** (from #6). Version-dependent cost models on 3.13 and later. Probably not relevant unless the runner enables the JIT.
- **String interning** (from #6). It bears on str and dict lookup costs in tokenizers (sqlparse, mistune, markdown). The bearing is minor.
- **"High Performance in Dynamic Languages" and "Bentley Rules for Optimizing Work"** (from #3b). These are taxonomies of work-reducing moves, relevant to lane design (L1). They are not yet read.
- **Compiling: Cython, mypyc, Numba** (from #7, chapter 7). Probably not relevant: it needs new dependencies and build changes (Step 3b's policy) and protected manifests.
- **Concurrency and multiprocessing** (from #7, chapters 8-10; #3b). Probably not relevant: the development workloads are single-threaded CPU code.

Sealed-set rule: I never opened `services/python_agents/tests/fixtures/upstream_corpus/`. The four development libraries were cloned at their GitHub default-branch heads, which I did not check against that corpus. I only read them and never executed them.
