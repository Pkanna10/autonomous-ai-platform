# z3-contrarian errata (full-text check, 2026-11-13)

How this was checked:
- Files were downloaded with `curl -sSL` through the session proxy, with no fake user agent and no mirror of a paywalled copy.
- PDFs were read with `pdftotext`; HTML pages were stripped to text.
- Text extracts are in `work/z3-contrarian/txt/` (scratch).
- Every claim the filed notes attribute to a source was checked against the downloaded text. The archive numbers in the notes are my own computations, not source claims, and are unchanged.

**Status of each source at filing:**
- Read in full: 8 (Scalene, from the authors' repository PDF).
- Read only from a summary, abstract or search snippet: 1-7 and 9-17.
- Not accessed: none.

## Sources

| # | citation (short) | status: full text / open substitute / unverified | file under sources/z3-contrarian/ or why none |
| --- | --- | --- | --- |
| 1 | Thiel and Masters, *Zero to One* (2014) | open substitute | `1-thiel-cs183-class11-secrets.html`: Blake Masters' notes of Thiel's Stanford CS183, Class 11 "Secrets" (2012). The book is commercial; no open full text. |
| 2 | Munger, *Poor Charlie's Almanack*, "invert, always invert" | open substitute (partial) | `2-jacobi-wikipedia.html`: Wikipedia, Carl Gustav Jacob Jacobi, for the Jacobi attribution. The book is commercial; the Stripe Press web edition rendered no text to a plain client. |
| 3 | Pólya, *How to Solve It* (1945/1957) | open substitute | `3-polya-wikipedia.html`: Wikipedia, How to Solve It. The book is commercial. |
| 4 | Mytkowicz et al., "Producing Wrong Data..." (ASPLOS 2009) | full text | `4-mytkowicz-wrongdata-course-copy.pdf`: open copy on a university course page (Vanderbilt CS 8395 readings). Semantic Scholar lists it as closed; the authors' USI page links only ACM Author-Izer (dl.acm.org refuses automated clients). |
| 5 | Mytkowicz et al., "Evaluating the Accuracy of Java Profilers" (PLDI 2010) | full text | `5-mytkowicz-profilers-pldi10.pdf`: from the authors' group page, plv.colorado.edu |
| 6 | Curtsinger and Berger, Stabilizer (ASPLOS 2013) | full text | `6-stabilizer.pdf`: author's site, people.cs.umass.edu |
| 7 | Curtsinger and Berger, Coz (SOSP 2015) | full text | `7-coz.pdf`: arXiv 1608.03676 (the SOSP'15 paper) |
| 8 | Berger, Stern and Altmayer Pizzorno, Scalene (OSDI 2023) | full text | `8b-scalene-osdi23.pdf` (the OSDI version, from the authors' repository) and `8-scalene.pdf` (arXiv 2212.07597) |
| 9 | Kanev et al., "Profiling a Warehouse-Scale Computer" (ISCA 2015) | full text | `9-kanev.pdf`: research.google.com/pubs/archive/44271.pdf. The ACM copy refused automated clients. |
| 10 | Leiserson et al., "There's plenty of room at the Top" (Science 2020) | unverified | Science is paywalled, and MIT DSpace's open copy returned "Web Firewall 429", asking for a login; not worked around. Filed instead: `10-leiserson-top-bib.txt` (the authors' BibTeX, metadata only) and `10-substitute-mit-6172-lec1.pdf` (MIT OCW 6.172 lecture 1, the matrix-multiply case study; an open substitute for that case study only). |
| 11 | Proebsting, "Proebsting's Law" | full text | `11-proebsting.html` |
| 12 | Hipp, SQLite 3.8.7 mail (2014); SQLite "cpu.html" | full text | `12b-sqlite-hipp-2014.html`, `12a-sqlite-cpu.html` |
| 13 | Nethercote, "How to speed up the Rust compiler" series | full text | `13-nethercote-2016.html`, `13b-nethercote-2019-still-faster.html`, `13c-nethercote-2019-last.html` |
| 14 | FBDetect (SOSP 2024) | full text | `14-fbdetect.pdf` |
| 15 | Good (1953), Biometrika 40:237-264 | open substitute | `15-good-turing-wikipedia.html`. Semantic Scholar lists the paper as closed; the gwern copy is a mirror, so it was not used. |
| 16 | Chao (1987), Biometrics 43:783-791 | open substitute | `16-chao2-wiqid.R.txt`: the wiqid R source on CRAN/rdrr.io. Semantic Scholar lists the paper as closed. |
| 17 | Dorfman (1943), Ann. Math. Stat. 14(4):436-440 | full text | `17-dorfman-course-copy.pdf`: copy on a university course page (Tampere). Project Euclid's open copy refused the automated client (Incapsula), and was not worked around. |

## Corrections

**[1] Notes, "Method".** Confirmed from the CS183 Class 11 notes:
- the question "what important truth do very few people agree with you on?";
- "secrets of nature and ... secrets about people".

The wording of *Zero to One* itself was not checked.

**[2] Notes, "Method", inversion.**
- The Jacobi attribution is confirmed by the substitute: "Invert, always invert", German "man muss immer umkehren".
- Munger's own use of the phrase is not confirmed; see unverified.

**[3] Sources list.** "Princeton University Press, 1945; 2nd edition 1957" becomes: Princeton University Press, 1945; the 2nd edition was published by Doubleday in 1957 (Wikipedia). "Work backwards" and Pappus are confirmed.

**[4] Notes, "Measurement folklore".** "Link order alone can make -O3 look 8 % better than -O2 or 7 % worse" is too general.
- The full text (§4.1.1, Fig. 2) gives that range for one benchmark, perlbench on Core 2: O3/O2 runs from 0.92 to 1.10, so "we may think we have a 7% slowdown when in fact we have a 8% speedup".
- Across benchmarks, the median max-min range is 0.02 on Core 2 and 0.08 on Pentium 4.

Confirmed from the abstract:
- 133 surveyed papers (ASPLOS, PACT, PLDI, CGO), none of which adequately considers measurement bias;
- the two remedies, causal analysis and setup randomisation;
- the bias seen on Pentium 4, Core 2 and m5 O3CPU, and with both gcc and icc.

**[5] Notes, "Profilers point to the wrong place".** Confirmed:
- four profilers (xprof, hprof, jprofile, yourkit) disagree on the hot methods (abstract);
- they sample at yield points rather than at random (§6.2);
- the random-sampling profiler found methods the others called cold (abstract).

**[6] Notes, "Measurement folklore".** Confirmed (abstract and §1):
- median overhead under 7 %;
- on SPEC CPU2006, -O2 against -O1 is significant, and -O3 against -O2 is indistinguishable from noise;
- timings become approximately Gaussian, which allows ANOVA.

"It works only with LLVM 3.1" is not in the paper. The paper says its evaluation was built with dragonegg and LLVM 3.1. The "only works" wording came from the project's GitHub README, which was not re-read here.

**[7] Notes, "Profilers point to the wrong place".** Confirmed (abstract and §1):
- Memcached 9 %, SQLite 25 %, six PARSEC programs up to 68 %;
- "in most cases" under 10 lines changed;
- Table 3 gives 9.39 ± 0.95 % and 25.60 ± 1.00 %.

The caveat that "for single-threaded code a virtual speed-up reduces to Amdahl's law" is my own inference, not a claim of the paper. It should read as such.

**[8] Notes, "Profilers point to the wrong place".** Confirmed:
- §6.2: "function bias", with a worst case of 80 % reported against 25 % actual, the profiler not named;
- §8.1: cProfile 1.7x slowdown against 15.1x for `profile`;
- Table 3: medians of 1.73x and 15.1x.

Precision: the paper says the bias affects "profilers that rely on Python's tracing facility". My phrase "built on the tracing or profile hooks" goes slightly further. The paper does not say that cProfile itself is the 80/25 case.

**[9] Notes, "Where speed-ups actually come from".** Confirmed from the abstract and §1:
- the "datacenter tax" can comprise "nearly 30%" of cycles;
- there is "no single 'silver-bullet' application" and "no major intra-application hotspots";
- ISCA'15, Portland.

**[10] Notes, "Where speed-ups actually come from".** "Gains are at the Top: algorithms, software performance engineering and hardware architecture" could not be checked against the full text; it stays unverified. The bib file gives volume 368 and June 2020 only.

**[11] Notes, "Where speed-ups actually come from".** "About 4 % a year against about 60 % a year for hardware" is confirmed. The year "1998" is not on the page; see unverified.

**[12] Notes, "Where speed-ups actually come from".** Confirmed from Hipp's mail of 19 Sep 2014:
- 1,432,835,574 and 953,861,485 cachegrind cycles (3.7.17 and 3.8.7 alpha);
- "as little as 0.05%" and "0.25% ... a huge win";
- "unmeasurable on a real-world system".

Correction: the quote "scarcely repeatable beyond one significant digit" is from SQLite's `cpu.html` §2.3, not from Hipp's mail. My notes attributed it to "Hipp's words". The same page says cachegrind is "repeatable to 7 or more significant digits", and typical micro-optimisations save "0.1% or 0.05% or even less".

**[13] Notes, "Where speed-ups actually come from".** "The 2019 total was 20 to 50 % on most benchmarks" becomes the figures from "The Rust compiler is still getting faster" (2019-07-25):
- wall time on 29 benchmarks, 2019-01-01 to 2019-07-24;
- most average changes of -20 % to -40 %;
- the best case per build kind from -12.4 % to -51.3 %.

These are tracker totals for all compiler changes, not only Nethercote's pull requests, and they are wall time, not instruction counts. Cachegrind, DHAT and the use of instruction counts are confirmed in the 2016 post.

**[14] Sources list and notes.** Three corrections:
- **Authors:** "Tang, C. et al." becomes Yoon, D. Y., Wang, Y., Yu, M., et al., with Tang, C. as last author (Meta Platforms).
- **The 0.005 % figure** is in the paper's own abstract, not only "Meta's stated figure".
- **The example is wrong.** "A 0.05 % application-level change into a 5 % subroutine-level one" becomes the paper's own example (§1): a 0.005 % service-level regression in a subroutine that uses 0.1 % of CPU is a 5 % change at subroutine level.

**[15] Notes, "Estimating what has not been found yet".** Missing mass = N1/N is confirmed (p0 = N1/N) by the substitute.

**[16] Same section.** The bias-corrected Chao2 form, S_obs + ((m-1)/m) · Q1(Q1-1)/(2(Q2+1)), is confirmed by the substitute (wiqid `richChao2`, "Eqn 4", used when `correct = TRUE` or Q2 = 0).

**[17] Same section.** "Split the pool only if it is positive" becomes: the members of a positive pool are each re-tested individually (p. 436). Confirmed: the paper's aims (fewer analyses than individual testing, and the most efficient group size given prevalence).

## Claims still unverified

- **[10]** The Science paper's claim about where gains come from. No open full text was reachable: DSpace answered 429 and asked for a login, and the publisher is paywalled.
- **[2]** Munger's use of "invert, always invert", and the 1986 Harvard School speech. Only Jacobi's phrase is confirmed.
- **[11]** The 1998 date of Proebsting's Law, and Scott (2001) as its empirical test. Neither is on the author's page; neither was re-read.
- **[6]** "Works only with LLVM 3.1": a statement from the project's README, not from the paper.
- **[1], [3], [15], [16]** The original texts themselves (*Zero to One*, *How to Solve It*, Good 1953, Chao 1987). The claims were checked against open substitutes only.

Disclosure for the Lead: the four development libraries' public histories were cloned (no checkout) only to extract the 17 base-file blobs named in the archived trial diffs. `services/python_agents/tests/fixtures/upstream_corpus/` was never opened.

## Overview sources

| # | source (short) | kind: TOC / chapter summaries / syllabus / topic list / reading list | file under sources/z3-contrarian/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | MIT OCW 6.172, Performance Engineering of Software Systems (Fall 2018), calendar and syllabus | syllabus / topic list | `1-mit-6172-calendar.html`, `1b-mit-6172-syllabus.html` |
| 2 | Gregg, *Systems Performance*, 2nd ed., author's page | TOC | `2-gregg-systems-performance-2e.html` |
| 3 | Thiel, Stanford CS183 (2012), class list (Masters' notes) | topic list | `3-cs183-class-list.html` |
| 4 | Jain, *The Art of Computer Systems Performance Analysis* (1991), author's page | TOC | `7-jain-art-of-perf-analysis.html`, `7b-jain-toc.html` |
| 5 | Cornell CS 6120 (2019fa), syllabus and schedule | syllabus | refused: TLS certificate verification failed (not bypassed) |
| 6 | Bakhvalov, *Performance Analysis and Tuning on Modern CPUs*: chapter list through the GitHub API | TOC | refused: 403 |
| 7 | Pólya, *How to Solve It*, Princeton UP page | TOC | not filed: the page carries no table of contents |

## Not yet covered

- **Bentley's rules for work reduction** (overview #1, L2): a catalogue of rules such as precomputation, caching, short-circuiting and hoisting. It may systematise Thesis 2's caller and set-up gates as a playbook. Ledger L10, L1.
- **"What compilers can and cannot do"** (#1, L9): which rewrites CPython never makes for you, such as inlining and hoisting. It may bear on L10.
- **DSLs and autotuning** (#1, L18): search over parameterised realisations. It bears on Thesis 3, realisation search. Ledger L8, L5.
- **Measurement and timing** (#1, L10): timer and noise practice. It bears on L3 and L7, which the stats seat probably covers.
- **Storage allocation** (#1, L11-12): allocation churn as a cost atom. It may bear on L10 for Python object churn.
- **Cache-efficient and cache-oblivious algorithms** (#1, L14-15): probably not relevant for CPython-level gains.
- **Fractional factorial designs (2^(k-p))** (#4, Part IV): testing many sub-floor changes in few runs while estimating their interactions. A stronger design for Thesis 1's bundles than Dorfman pooling. Ledger L3, L5.
- **"Ratio games" and common mistakes** (#4, Parts I-II): how ratio summaries mislead. It bears on comparing combine and trial gains. Ledger L6.
- **Comparing systems using sample data** (#4, Part III): probably covered by the stats seat. Ledger L3, L4.
- **Workload selection and characterisation** (#4, Part II): probably not relevant; the benchmarks are frozen.
- **Methodology chapter** (#2, ch. 2): systematic search methods beyond the profiler. The overview shows only the title, so its content is unread. It may bear on L10.
- **Benchmarking chapter** (#2, ch. 12): benchmark pitfalls. It may bear on L9.
- **CS183's other classes** (#3, e.g. "You Are Not A Lottery Ticket"): planned versus chance outcomes. It bears weakly on L9 (search variance); probably not relevant otherwise.
