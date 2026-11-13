# s8-expert errata (full-text check, 2026-11-13)

All nine public sources were downloaded as full text in this session before the notes were written. Each claim was checked against the downloaded text before filing.

"Cited sections read" means:
- the abstract and introduction, the result sections and the appendices the notes cite;
- not every page;
- for SWE-Perf, GSO and SWE-fficiency, never the dataset instances, the example trajectories or the expert patches shown in figures and appendices.

## Sources

| # | citation (short) | status: full text / open substitute / unverified | file under sources/s8-expert/ or why none |
| --- | --- | --- | --- |
| 1 | Ma et al., SWE-fficiency, arXiv:2511.06090v3 | full text (cited sections read: abstract, sections 1-2 and 4, Appendix I) | `1-swe-fficiency.pdf` (+ `.txt`, `.raw.txt`) |
| 2 | He et al., SWE-Perf, arXiv:2507.12415v2 | full text (abstract, sections 1-6, Tables 1-2, Appendices A-B) | `2-swe-perf.pdf` (+ `.txt`, `.raw.txt`) |
| 3 | Shetty et al., GSO, arXiv:2505.23671v3 | full text (abstract, sections 1-5, Figure 3 table; the Section F examples not read) | `3-gso.pdf` (+ `.txt`, `.raw.txt`) |
| 4 | Curtsinger and Berger, Coz, arXiv:1608.03676 | full text (abstract, sections 1 and 4: dedup, ferret, SQLite) | `4-coz.pdf` (+ `.txt`, `.raw.txt`) |
| 5 | Bhuiyan et al., ReDoS SoK, arXiv:2406.11618v4 | full text (abstract, section 4.1.5, Figure 3) | `5-redos-sok.pdf` (+ `.raw.txt`) |
| 6 | Leiserson and Shun, MIT 6.172 F18, Lecture 2, "Bentley Rules" | full text (open course slides; Bentley's own book is commercial and not used) | `6-mit6172-lec2-bentley-rules.pdf` (+ `.raw.txt`) |
| 7 | PSF, "The Python Profilers" (3.11) | full text (whole page) | `7-python-profile-docs.html` (+ `.txt`) |
| 8 | Berger, Stern and Altmayer Pizzorno, Scalene, arXiv:2212.07597 | full text (the profiler comparison table and the related-work section on cProfile) | `8-scalene.pdf` (+ `.raw.txt`) |
| 9 | Baltes et al., "Navigate, Understand, Communicate", arXiv:1706.10118 | full text (abstract, the RQ1 results) | `9-locate-perf-bugs.pdf` (+ `.raw.txt`) |
| 10 | the 124 allowed commits (primary data) | full text (every patch read; large diffs read function by function) | none: given material under `r3/s8/patches/` and `trees/` |
| 11 | the engine's archive and source (internal) | full text (the cited files and functions) | none: internal files in `/home/user/step3-emergence-r1` |

A refused download, not used as a source: the ACM copy of Davis et al., FSE 2018 (ReDoS) answered 403. I did not work around it and used the open SoK [5] instead.

## Corrections

**Corrected:**
- **[11] Notes, "Why a profiler hides the location".** The notes said the manifest records "2.8-3.6x". The manifest gives 3.4/1.2, 5.1/1.5, 3.9/1.4 and 1.7/0.6 s, which is 2.8-3.4x. I corrected this in the file seconds after writing it, before this check began, and record it here for transparency.
- **[6] Core sources and Sources.** The notes credit the lecture to "Leiserson and Shun". The slide deck's title page names Julian Shun as the lecturer; the course instructors are Charles Leiserson and Julian Shun (OCW course page). The citation stands as a course citation.

**Confirmed against the full text:**
- **[1]**
  - "over 68% of expert gains occur in functions the LM never edits" and "LM and expert modify the same files over 55% of the time" (section 4).
  - Table 9: ERCfunc 0.246-0.314; WrongFileLoss "roughly 37%-45%".
  - Table 10: depth 4.51-4.89 for experts against 3.83-4.28 for LMs. The text says "4.5-4.9" and "3.8-4.2".
  - The "Shortcut bias" heading.
  - The Figure 7 description: the LM optimizes "a deeper function".
  - 498 tasks.
- **[2]**
  - Table 1 expert-patch means: 131.1 lines, 4.3 files, 7.6 functions edited.
  - 140 instances; ICML 2026, PMLR 306.
  - Section 5.3.3: the gap widens with the number of functions.
- **[3]**
  - The Figure 3 table: 102 tasks; lines mean 250, median 110; files 3.9.
  - The text's "averaging 108 lines" is quoted as the paper's own inconsistency.
  - "lazy optimizations" and "Input-specific fast paths" (sections 1 and 5.2).
- **[4]**
  - The quote "Code that runs for a long time is not necessarily a good choice for optimization."
  - dedup: three lines, 8.95 % ± 0.27 %.
  - SQLite: perf puts the three functions at 0.15 %; the change from indirect to direct calls gave 25.60 % ± 1.00 % (section 4.2.3).
- **[5]** The quote "neither built-in engine optimizations against ReDoS vulnerabilities nor a native timeout-like mechanism" (section 4.1.5).
- **[6]** The four rule groups and their members (slides "New Bentley Rules").
- **[7]** The quote on overhead for Python code against C-level functions (the "Introduction to the profilers" note).
- **[8]** cProfile "1.7× slowdown vs. 15.1×" for profile (related work).
- **[9]** 12 developers in two projects; "chasing the largest quantities of runtime consumption as a main navigation strategy (Prop. 1.2)"; the paraphrase on complex bugs (Prop. 1.3).
- **[10]** Every commit number in the notes and tables was recomputed from `work/classify.tsv`, `funcmap.jsonl`, `l10.json`, `ab.jsonl` and `ab2.jsonl`:
  - 84/6/34 kinds;
  - 48/36 locations;
  - 7 numeric claims;
  - 4,494 lines; 85.4 % and 86.7 %;
  - 52/78 and 42/56 commits;
  - the post-base 12;
  - every timing figure.

## Claims still unverified

- **[10]** The attribution of tomli's "~3%" CHANGELOG line to commit 5aecb99. It is an inference from the CHANGELOG entry and the commit falling on the same day; the notes mark it as inferred.
- **[11]** That the engine's display rule is exactly "30 hotspots by self time, then the top 8 by cumulative time". This is read from the `profiler.py` and `idea_context.py` docstrings and code. I did not run the engine, so the "hot8" sets are my reconstruction from my own cProfile runs, not the engine's recorded contexts.
- **Venues.** The arXiv records give none for Scalene [8] or Baltes et al. [9]; the notes cite the arXiv versions only.

## Overview sources

| # | source (short) | kind: TOC / chapter summaries / syllabus / topic list / reading list | file under sources/s8-expert/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | MIT 6.172 Performance Engineering of Software Systems (Fall 2018), Syllabus | syllabus | `1-mit-6172-syllabus.html` (+ `.txt`) |
| 2 | MIT 6.172, Lecture Slides (23 sessions) | topic list | `2-mit-6172-lectures.html` (+ `.txt`) |
| 3 | Gregg, *Systems Performance*, 2nd ed., the author's book page | TOC | `3-gregg-sysperf2-toc.html` (+ `.txt`) |
| 4 | MIT 6.172, Readings | reading list | `4-mit-6172-readings.html` (+ `.txt`) |
| 5 | Python wiki, "PythonSpeed/PerformanceTips" | topic list | `5-python-wiki-perftips.html` (+ `.txt`) |
| 6 | Bakhvalov, *Performance Analysis and Tuning on Modern CPUs*, book page | TOC | refused: TLS (self-signed certificate on book.easyperf.net); not worked around |
| 7 | O'Reilly, *High Performance Python*, 2nd ed., book page | TOC | refused: 403 |

## Not yet covered

- **Measurement bias from the environment** (#4, Mytkowicz et al., "Producing Wrong Data Without Doing Anything Obviously Wrong", 2009). It bears on L3 and L9: a layout or environment effect can fake the 5-10 % gains the expert commits claim. Probably the stats seat's.
- **What compilers can and cannot do** (#2, lecture 9). The Python analogue is CPython 3.11's specializing interpreter. It may explain why 2021 micro-optimizations (tomli 1852743, "~10%") read +1 % here on 3.11, so expert claims age with the interpreter.
- **High performance in dynamic languages** (#2, lecture 23). It bears directly on which Bentley rules still pay in CPython.
- **Choosing the right data structure** (#5). It bears on L10: the engine has 0 data-structure keeps, while tomli's trie (+80 %) is the largest expert gain measured.
- **String concatenation and building output** (#5). The expert fix markdown 86d1e46 is this class.
- **Import-statement overhead** (#5). It is the expert startup commits' class; the engine's benchmarks time import, but its hot functions never include module level.
- **Flame graphs and call-path visualization** (#3; SWE-fficiency uses them). They show callers, which could widen grounding beyond the 8 hot functions (L1, L10).
- **Workload characterization and methodology** (#3, chapter 2). Choosing inputs that expose superlinear paths bears on the plants that are "visible only at realistic sizes".
- **Autotuning** (#2, lecture 18; #4, OpenTuner). It bears on the search seat rather than this one; probably not relevant to L10.
- **Cache-efficient algorithms and parallelism** (#2, lectures 6-8 and 14-17). Probably not relevant to single-threaded CPython parsers.
