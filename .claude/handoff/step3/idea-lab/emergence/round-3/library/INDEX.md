# Round 3 library index (2026-11-13)

Built by `r3/tools/index.py` from each seat's errata tables. Types (O66, and the owner's overview addition):
- **full text:** the seat read the source itself;
- **open substitute:** no open full text; the seat read open course notes or pages on the same topic instead, named in the row;
- **unverified:** neither; claims citing it stay marked unverified;
- **overview only:** a table of contents, chapter summaries, syllabus, topic list or reading list. A map of the field, never evidence for a claim.

Downloaded files are untrusted data. Nothing from them enters a prompt, lesson or example bank the engine reads.

The downloaded files themselves are not committed: they are untrusted data and others' copyright. `SOURCES.sha256` records each file's hash under the scratch `sources/` tree.

s4-algorithms' notes are filed with sealed-set material redacted (see `incidents.md`). s8-expert's notes come from its fresh context (O67), which studied only a Lead-computed allowed-commit list.

| type | count |
| ---- | ----- |
| full text | 157 |
| open substitute | 52 |
| overview only | 80 |
| overview refused/unreached | 25 |
| unverified | 35 |

## fp-compose

Notes: `fp-compose.md`. Errata: `fp-compose.errata.md`. Files: `sources/fp-compose/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Amdahl 1967, AFIPS SJCC 30:483–485 | full text | `1-amdahl-1967.pdf` (Stony Brook CSE613 course copy of the 2007 IEEE SSCS News reprint) |
| 2 | Hennessy & Patterson, CA:AQA 6th ed., ch. 1 | open substitute | Commercial textbook with no open copy. Substitutes: `2-sub-amdahl-wikipedia.html` and the "Amdahl's Law" sidebar in `4-hill-marty.pdf` |
| 3 | Gustafson 1988, CACM 31(5):532–533 | full text | `3-gustafson-1988.pdf` (Utah course copy). The ACM copy refused automated clients (403). |
| 4 | Hill & Marty 2008, IEEE Computer 41(7):33–38 | full text | `4-hill-marty.pdf` (research.cs.wisc.edu, the authors' group) |
| 5 | Bentley, Programming Pearls 2nd ed., Column 6 | unverified | Commercial book; the O'Reilly page returned 403. Its numbers are checked against [6] instead. |
| 6 | Appel 1985, SIAM J. Sci. Stat. Comput. 6(1):85–103 | open substitute | `6-appel-cmu-cs-83-118.pdf`: the 1983 CMU technical report CMU-CS-83-118 of the same work, from CMU KiltHub. The SIAM version is paywalled; the montana.edu copy |
| 7 | Knuth 1971, SP&E 1(2):105–133 | unverified | Semantic Scholar reports CLOSED, and no open copy was found. The CWI search hit was a different report (Alanen 1972), so it was deleted. |
| 8 | Curtsinger & Berger 2015, Coz, SOSP | full text | `8-coz.pdf` (arXiv 1608.03676) |
| 9 | Smith & Winkler 2006, Mgmt Sci 52(3):311–322 | open substitute | `9-smith-winkler-correction.pdf`: the authors' own 2007 correction note. Semantic Scholar reports the paper CLOSED. The only full-text copy found is a third-par |
| 10 | Siegmund et al. 2012, ICSE 167–177 | full text | `10-siegmund.pdf` (Saarland University copy, 11 pages) |
| 11 | Chapman 1951, UC Publ. Stat. 1:131–160 | open substitute | `11-sub-mark-recapture-wikipedia.html` (sections on Lincoln–Petersen and Chapman). The original is not online. |
| 12 | Chao 1987, Biometrics 43(4):783–791 | unverified | Semantic Scholar reports CLOSED (JSTOR), and no open copy was found. Only the bibliographic details were checked. |
| 13 | Python docs, "The Python Profilers" | full text | `13-python-profile.html` (now the deprecated `profile` page of the 3.15 docs) and `13b-python-profiling-tracing.html` |
| 14 | Archive (`w2-sprint/`, the live_oss manifest, `combine_node.py`) | full text | Read in full in place, read-only. Not copied. |
| o1 | MIT OCW 6.172, Performance Engineering of Software Systems (Fall 2018, Leiserson and Shun) | overview only | `1-mit-6172-syllabus.html`, `1b-mit-6172-lectures.html` |
| o2 | Hennessy & Patterson, *Computer Architecture: A Quantitative Approach*, 6th ed. (Elsevier page) | overview only | `2-hp-caqa6-toc.html` |
| o3 | Jain, *The Art of Computer Systems Performance Analysis* (author's site) | overview only | `3-jain-perfbook.html`, `3-jain-perfbook-toc.html` |
| o4 | Gregg, *Systems Performance*, 2nd ed. (author's site) | overview only | `4-gregg-sysperf2.html` |
| o5 | UC Berkeley CS267, Applications of Parallel Computers (Spring 2023 course site) | overview only | `7-cs267-syllabus.html` |
| o6 | Bentley, *Programming Pearls*, 2nd ed. TOC | overview refused/unreached | refused: 502 (bell-labs.com proxy tunnel). The O'Reilly page had already returned 403 in the full-text step. |
| o7 | Cooch & White, *Program MARK: a gentle introduction* (open capture–recapture book) | overview refused/unreached | refused: DNS (www.phidot.org does not resolve) |

## fp-ideation

Notes: `fp-ideation.md`. Errata: `fp-ideation.errata.md`. Files: `sources/fp-ideation/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Amdahl 1967, AFIPS | full text | `1-amdahl.pdf` |
| 2 | Gustafson 1988, CACM 31(5) | full text | `2-gustafson.pdf` |
| 3 | Williams, Waterman, Patterson 2009, Roofline, CACM 52(4) | open substitute | `3-sub-roofline-tr2008.pdf` |
| 4 | Hennessy and Patterson 2017, 6th ed. | open substitute | `4-sub-wiki-amdahl.html` |
| 5 | Bentley 1984, "The Back of the Envelope" | full text | `5-bentley.pdf` |
| 6 | Fermi 1945, Trinity observations; OSTI history page | full text | `6-fermi.html`, `6b-osti-trinity.html` |
| 7 | Musk via CleanTechnica 2019 | full text | `7-cleantechnica.html` |
| 8 | Anderson, Wired, Oct 2012 (Musk Q&A) | full text | `8-wired.html` |
| 9 | Isaacson 2023, *Elon Musk* | open substitute | `9-mann-notes.html` |
| 10 | Hanley and Lippman-Hand 1983, JAMA | open substitute | `10-sub-wiki-rule-of-three.html` |
| 11 | Weitzman 1979, Econometrica | open substitute | `11-sub-kleinberg-pandora-arxiv1603.07682.pdf` |
| 12 | Howard 1966, IEEE TSSC | open substitute | `12-sub-wiki-value-of-information.html` |
| 13 | Goldratt and Cox 2004, *The Goal* | open substitute | `13-sub-wiki-theory-of-constraints.html`, `13b-sub-wiki-the-goal.html` |
| o1 | Hennessy and Patterson, 6th ed., Elsevier product page | overview only | `1-elsevier-hp6-toc.html` |
| o2 | Bentley, *Programming Pearls* 2nd ed., InformIT (publisher) | overview only | `2-informit-pearls2e-toc.html` |
| o3 | MIT OCW 6.172 Performance Engineering of Software Systems (Fall 2018), lecture slides | overview only | `3-ocw6172-lecture-list.html` |
| o4 | MIT OCW 6.172, calendar | overview only | `4-ocw6172-calendar.html` |
| o5 | MIT OCW 18.098 Street-Fighting Mathematics (IAP 2008), course home | overview only | `5-ocw18098-streetfighting-math.html` |
| o6 | MIT OCW 2.854 Introduction to Manufacturing Systems (Fall 2016), course home | overview only | `6-ocw2854-manufacturing-systems.html` |
| o7 | MIT OCW 1.011 Project Evaluation (Spring 2011), calendar | overview only | `7-ocw1011-project-evaluation-calendar.html` |

## fp-measure

Notes: `fp-measure.md`. Errata: `fp-measure.errata.md`. Files: `sources/fp-measure/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | JCGM 100:2008 (GUM) | full text | `1-gum.pdf` (BIPM), `1-gum.txt`, `1-gum-raw.txt` |
| 2 | Taylor & Kuyatt, NIST TN 1297 (1994) | full text | `2-tn1297.html`, `2-tn1297-nist-tn-1297-{3,4,5,6}-*.html` |
| 3 | Kalibera & Jones, ISMM 2013 | full text | `3-kalibera-jones.pdf`, `.txt` |
| 4 | Georges, Buytaert & Eeckhout, OOPSLA 2007 | full text | `4-georges.pdf`, `.txt`, `4-georges-raw.txt` |
| 5 | Mytkowicz et al., ASPLOS 2009 | unverified | `5-mytkowicz-page.html` (abstract) |
| 6 | Chen & Revels 2016, arXiv:1608.04295 | full text | `6-chen-revels.pdf`, `.txt`, `6-raw.txt` |
| 7 | Laaber, Scheuner & Leitner, EMSE 2019 | full text | `7-laaber.pdf`, `.txt`, `7-raw.txt` |
| 8 | van Belle, *Statistical Rules of Thumb* (Lehr's rule) | open substitute | `8-rpubs-vanbelle.html` |
| 9 | Zhou, Lu & Shallah, CIKM 2023, arXiv:2305.16459 | full text | `9-zhou-sample-size.pdf`, `.txt`, `9-raw.txt` |
| 10 | Ioannidis, *Epidemiology* 2008 | unverified | `10-ioannidis-europepmc.json` |
| 11 | Efron, JASA 2011 | full text | `11-efron-pmc.html` |
| 12 | Skol et al., *Nature Genetics* 2006 | unverified | `12-skol-europepmc.json`, `12-skol-umich.html` |
| 13 | Harter 1960, d2 constants | open substitute | `13-minitab-d2.html` |
| 14 | Jennison & Turnbull 1999 | unverified | none |
| 15 | Mahajan, *Street-Fighting Mathematics* | open substitute | `15-mahajan-ocw-toc.pdf`, `15-mahajan-ocw-reading1.pdf`, `.txt` |
| o1 | NIST/SEMATECH e-Handbook, ch. 2, Measurement Process Characterization | overview only | `overview/1-nist-handbook-mpc.html` |
| o2 | BIPM JCGM publications (the GUM suite: JCGM 100, 101, 102, 106, GUM-1, GUM-5, GUM-6, VIM) | overview only | `overview/2-jcgm-publications.html` |
| o3 | MIT OCW 18.098 Street-Fighting Mathematics (Mahajan, 2008) | overview only | `overview/3-ocw-18098-syllabus.html` |
| o4 | MIT OCW 6.055J The Art of Approximation in Science and Engineering (Mahajan, 2008) | overview only | `overview/4-ocw-6055j-art-of-approx.html` |
| o5 | MIT OCW 6.172 Performance Engineering of Software Systems (2018), lecture list | overview only | `overview/5-ocw-6172-lectures.html` |
| o6 | Kohavi, Tang & Xu, *Trustworthy Online Controlled Experiments* (Cambridge) | overview only | `overview/6-cambridge-kohavi.html` |

## s1-perf-eng

Notes: `s1-perf-eng.md`. Errata: `s1-perf-eng.errata.md`. Files: `sources/s1-perf-eng/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Gregg, *Systems Performance*, 2nd ed., 2020 | open substitute | Commercial textbook, no open full text. Substitutes: Gregg's own method pages [2] `2-gregg-use.html` and [3] `3-gregg-tsa.html`. The notes attribute no claim to |
| 2 | Gregg, "The USE Method" (web page) | full text | `2-gregg-use.html` |
| 3 | Gregg, "The TSA Method" (web page) | full text | `3-gregg-tsa.html` |
| 4 | Bentley, *Writing Efficient Programs*, 1982 | open substitute | Commercial book, no open full text. Substitute: MIT 6.172 Lecture 2 "Bentley Rules for Optimizing Work" [6], `6-mit6172-lec2.pdf`. The notes already took the ru |
| 5 | MIT 6.172 F18, Lecture 1 (Leiserson) | full text | `5-mit6172-lec1.pdf` (+ `.txt`) |
| 6 | MIT 6.172 F18, Lecture 2 (Shun) | full text | `6-mit6172-lec2.pdf` (+ `.txt`) |
| 7 | Leiserson et al., *Science* 2020 | unverified | Open copy exists (Semantic Scholar: GREEN, MIT DSpace hdl 1721.1/159445), but dspace.mit.edu answered 429 twice, 15 min apart (retry-after 900); not worked arou |
| 8 | Amdahl, AFIPS 1967 | full text | `8-amdahl.pdf`. The IEEE SSCS News reprint, from a Stony Brook course page. |
| 9 | Gustafson, *CACM* 1988 | full text | `9-gustafson.pdf`, from a University of Utah course page |
| 10 | Williams, Waterman and Patterson, Roofline, *CACM* 2009 | full text | `10-roofline.pdf`, the LBNL copy on OSTI |
| 11 | Knuth, *Computing Surveys* 1974 | unverified | No allowed open copy. Semantic Scholar lists `openAccessPdf` as CLOSED, and dl.acm.org answered 403 (not worked around). The University of Oslo hit was an exhib |
| 12 | Jin et al., PLDI 2012 | full text | `12-jin-pldi12.pdf`, from a University of Waterloo course page |
| 13 | Curtsinger and Berger, Coz, SOSP 2015 | full text | `13-coz.pdf` (arXiv:1608.03676) |
| 14 | Graham, Kessler and McKusick, gprof, 1982 | full text | `14-gprof.pdf`: the "Best of PLDI 1979-1999" reprint, with the 2003 retrospective plus the original paper as scanned pages, from a University of Michigan course |
| 15 | Mytkowicz et al., PLDI 2010 | full text | `15-mytkowicz-pldi10.pdf`, from the authors' group site (plv.colorado.edu) |
| 16 | Ousterhout, *CACM* 2018 | full text | `16-ousterhout.pdf`, from a University of Waterloo course page |
| 17 | Shetty et al., GSO, arXiv 2025 | full text | `17-gso.pdf` (arXiv:2505.23671v3). Only the paper's findings were read: no dataset instances and no expert patches. |
| o1 | Gregg, *Systems Performance* 2nd ed., author's book page | overview only | `1-gregg-sysperf2-toc.html` |
| o2 | Gregg, "Performance Analysis Methodology" (author's site) | overview only | `2-gregg-methodology.html` |
| o3 | MIT 6.172 Fall 2018, OCW syllabus | overview only | `3-mit6172-syllabus.html` |
| o4 | MIT 6.172 Fall 2018, OCW calendar | overview only | `4-mit6172-calendar.html` |
| o5 | Bakhvalov et al., *Performance Analysis and Tuning on Modern CPUs* (open book, public repo, read-only clone of file names only) | overview only | `5-bakhvalov-perfbook-toc.txt` |
| o6 | Slotin, *Algorithms for Modern Hardware* (en.algorithmica.org/hpc) | overview only | `6-algorithmica-hpc-toc.html` |

## s2-stats

Notes: `s2-stats.md`. Errata: `s2-stats.errata.md`. Files: `sources/s2-stats/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Kalibera and Jones, ISMM 2013 | full text | `1-kalibera-jones-ismm2013.pdf` (author's manuscript, kar.kent.ac.uk/33611) |
| 2 | Kalibera and Jones, tech report 2012 | full text | `2-kalibera-jones-techreport2012.pdf` (cs.kent.ac.uk/pubs/2012/3233) |
| 3 | Georges, Buytaert and Eeckhout, OOPSLA 2007 | full text | `3-georges-oopsla2007.pdf` (buytaert.net) |
| 4 | Mytkowicz et al., ASPLOS 2009 | full text | `4-mytkowicz-asplos2009.pdf`. Neither Semantic Scholar nor an author page had an open copy, and dl.acm.org refused. This is the paper as a reading on a Northwes |
| 5 | Curtsinger and Berger, STABILIZER, ASPLOS 2013 | full text | `5-stabilizer-asplos2013.pdf` |
| 6 | Bulej et al., Duet, ICPE 2020 | full text | `6-duet-arxiv2001.05811.pdf` |
| 7 | Barrett et al., VM warmup, OOPSLA 2017 | full text | `7-barrett-warmup-arxiv1602.00602.pdf` |
| 8 | Daly et al., ICPE 2020 | full text | `8-daly-changepoint-arxiv2003.00584.pdf` |
| 9 | Fleming et al., Hunter, 2023 | full text | `9-hunter-arxiv2301.03034.pdf` |
| 10 | Chen and Revels, 2016 | full text | `10-chen-revels-arxiv1608.04295.pdf` |
| 11 | pyperf docs and code, commit 63ce439 | full text | `11-pyperf-docs-63ce439.txt` (the docs; the code was read in the clone) |
| 12 | pytest-benchmark docs, commit 97c52d8 | full text | `12-pytest-benchmark-docs-97c52d8.txt` |
| 13 | NIST/SEMATECH e-Handbook, CUSUM | full text | `13-nist-cusum.html` |
| 13' | Page, Biometrika 1954 | open substitute | Not open (Biometrika). The substitute is the NIST page above. Metadata confirmed by Crossref |
| 14a | Wikipedia, "Sign test" | full text | `14a-wikipedia-sign-test.txt` |
| 14b | Wikipedia, "Mann–Whitney U test" | full text | `14b-wikipedia-mann-whitney.txt` |
| 14' | Lehmann, *Elements of Large-Sample Theory*, 1999 | open substitute | A commercial textbook. Substitutes: `14c-bartlett-stat210b-lecture24.pdf` (UC Berkeley Stat 210B lecture notes) and `14e-etests-efficiency-arxiv2208.08925.pdf`  |
| 15 | Wikipedia, "Robust measures of scale" | full text | `15-wikipedia-robust-scale.txt`, plus `15b-wikipedia-mad.txt` |
| 15' | Rousseeuw and Croux, JASA 1993 | unverified | No open copy found. The Semantic Scholar DOI lookup returned "not found" and its search was rate-limited. I made no further attempts |
| 16 | Wikipedia, "Crossover study" (cited inline only, no number) | full text | `16-wikipedia-crossover.txt` |
| 16' | Jones and Kenward, cross-over trials textbook | unverified | A commercial textbook. The open course substitute (Penn State STAT 509) failed TLS verification, and I did not bypass it |
| o1 | Jain, *The Art of Computer Systems Performance Analysis* (Wiley 1991), the author's TOC page | overview only | `1-jain-art-of-perf-analysis-toc.html` |
| o2 | Jain, CSE567M Computer Systems Analysis, WUSTL, Fall 2017 | overview only | `2-jain-cse567-course.html` |
| o3 | Le Boudec, *Performance Evaluation of Computer and Communication Systems* (EPFL Press 2010), the author's book page and the TOC of the open PDF (only the TOC kept) | overview only | `3-leboudec-perfeval-book.html`, `3-leboudec-perfeval-toc.txt` |
| o4 | Evaluate Collaboratory, Evaluation Anti-Patterns | overview only | `4-evaluate-anti-patterns.html` |
| o5 | Evaluate Collaboratory, the Canon bibliography | overview only | `5-evaluate-canon-reading-list.html` |
| o6 | Truong, Oudre and Vayatis, "Selective review of offline change point detection methods", arXiv:1801.00718 (the section list only) | overview only | `6-truong-changepoint-review-sections.txt` |
| o7 | Hollander, Wolfe and Chicken, *Nonparametric Statistical Methods*, 3rd ed., the Wiley product page | overview refused/unreached | refused: 403 |
| o8 | Montgomery, *Introduction to Statistical Quality Control*, 8th ed., the Wiley product page (CUSUM, control charts) | overview refused/unreached | refused: 403 |

## s3-equivalence

Notes: `s3-equivalence.md`. Errata: `s3-equivalence.errata.md`. Files: `sources/s3-equivalence/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | McKeeman 1998, Differential Testing for Software, DTJ 10(1) | open substitute | `1-wiki-difftest.html` (Wikipedia "Differential testing"). The DTJ host (www.hpl.hp.com) reset the connection twice and no other open copy was found |
| 2 | Claessen & Hughes 2000, QuickCheck, ICFP | unverified | Semantic Scholar lists the ACM copy as CLOSED; the Tufts copy reset the connection and the Northwestern copy did not resolve. `2-wiki-quickcheck.html` holds bib |
| 3 | MacIver, Hatfield-Dodds et al. 2019, Hypothesis, JOSS 4(43):1891 | full text | `3-hypothesis-joss.txt` (paper.md from the public repository) |
| 4 | Hypothesis `ghostwriter.equivalent()` source | full text | `4-ghostwriter-equivalent.txt` |
| 5 | Godlin & Strichman, Regression verification (DAC 2009; STVR 23(3), 2013) | open substitute | `5-godlin-strichman-grand.pdf/.txt`: Strichman & Godlin, "Regression Verification - a practical way to verify programs" (Technion, same authors). No open copy o |
| 6 | Pnueli, Siegel & Singerman 1998, Translation validation, TACAS | unverified | The Weizmann page returned an empty reply; no other open copy was found |
| 7 | Necula 2000, Translation validation for an optimizing compiler, PLDI | full text | `7-necula.pdf/.txt` (author copy) |
| 8 | Lopes et al. 2021, Alive2, PLDI | full text | `8-alive2.pdf/.txt` |
| 9 | King 1976, Symbolic execution and program testing, CACM | open substitute | The ACM PDF is behind a Cloudflare bot check (refused). `9-wiki-symbolic-execution.html` (citation only) |
| 10 | Person, Dwyer, Elbaum & Păsăreanu 2008, Differential symbolic execution, FSE | open substitute | Semantic Scholar lists it as CLOSED. `10-dse-ntrs.pdf/.txt`: Person & Dwyer et al., "Generalized Abstract Symbolic Summaries" (NASA NTRS 20100024480), which des |
| 11 | CrossHair `diffbehavior` documentation | full text | `11-crosshair-diffbehavior.txt` |
| 12 | DeMillo, Lipton & Sayward 1978, Hints on test data selection, IEEE Computer | open substitute | No open copy was found. `12-wiki-mutation-testing.html` |
| 13 | Just et al. 2014, Are mutants a valid substitute for real faults, FSE | full text | `13-just-mutants.pdf/.txt` |
| 14 | Papadakis, Jia, Harman & Le Traon 2015, TCE, ICSE | unverified | The UCL PDF is behind a Cloudflare bot check (refused); orbilu.uni.lu failed TLS verification (not bypassed); Semantic Scholar returned 429. The Zenodo record 2 |
| 15 | Schkufza, Sharma & Aiken 2013, Stochastic Superoptimization, ASPLOS | full text | `15-stoke.pdf/.txt` (arXiv 1211.0557) |
| 16 | Yang, Chen, Eide & Regehr 2011, Csmith, PLDI | full text | `16-csmith.pdf/.txt` (preprint) |
| 17 | Qi, Long, Achour & Rinard 2015, Kali, ISSTA | full text | `17-kali.pdf/.txt` (author copy) |
| 18 | Smith, Barr, Le Goues & Brun 2015, Is the cure worse than the disease?, FSE | open substitute | The FSE copy URL returned 404 and Semantic Scholar lists it as CLOSED. `18-overfitting-umass.pdf/.txt`: the UMass technical report UM-CS-2015-007, a full text o |
| 19 | GSO HackDetector blog (Shetty, Jain, 2025-11-03) | open substitute | The Notion page renders only through JavaScript, so its text could not be read. Substitutes: `19c-gso-paper.pdf/.txt` (GSO paper, arXiv 2505.23671), `19-gso-sit |
| 20 | Horwitz, Prins & Reps 1989, Integrating noninterfering versions of programs, TOPLAS | full text | `20-hpr.pdf/.txt` |
| 21 | Engine source and archive (judges.py, anticheat.py, outputs.py, workloads, `w2-sprint/live/`), tomli 2.5.0 | full text | Local, read only; nothing copied |
| o1 | CMU 17-355/665/819 Program Analysis (Spring 2025 and Fall 2026 pages) | overview only | `overview/1-cmu-17355-2025.html`, `overview/1-cmu-17355-2026.html` |
| o2 | Zeller et al., The Fuzzing Book | overview only | `overview/2-fuzzingbook-toc.html` |
| o3 | Ammann & Offutt, Introduction to Software Testing (author site, cs.gmu.edu) | overview refused/unreached | refused: TLS certificate verification failure (curl 60), not bypassed |
| o4 | MIT OCW 6.820 Fundamentals of Program Analysis (Fall 2015) | overview only | `overview/4-mit-6820-ocw.html` |
| o5 | Cornell CS 6120 Advanced Compilers (2023fa) | overview refused/unreached | refused: TLS certificate verification failure (curl 60) |
| o6 | Kroening & Strichman, Decision Procedures (book site) | overview refused/unreached | refused: DNS resolution failure (curl 6) |
| o7 | Zeller, The Debugging Book | overview only | `overview/7-debuggingbook-toc.html` |
| o8 | UW CSE 507 Computer-Aided Reasoning for Software | overview refused/unreached | refused: login wall (UW NetID identity-provider page); the bare course URLs returned 404 |

## s4-algorithms

Notes: `s4-algorithms.md`. Errata: `s4-algorithms.errata.md`. Files: `sources/s4-algorithms/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Cormen et al., *Introduction to Algorithms* 4e, 2022 | open substitute | commercial book with no open full text; substitute is [5], `5-mit6046-lec05.pdf` |
| 2 | Skiena, *Algorithm Design Manual* 3e, 2020 | open substitute | book has no open full text; author's lectures `2-skiena-lec4.pdf`, `2-skiena-lec5.pdf`, `2-skiena-lec6.pdf` |
| 3 | Sedgewick and Wayne, *Algorithms* 4e, 2011 | open substitute | book has no open full text; authors' booksite `3-algs4-13stacks.html`, `3-algs4-14analysis.html` |
| 4 | Tarjan, "Amortized Computational Complexity", 1985 | unverified | Semantic Scholar reports CLOSED. The only copies found are course-site reposts of the publisher PDF, not downloaded (treated as mirrors). Secondary source filed |
| 5 | MIT 6.046J S15 Lecture 5 notes | full text | `5-mit6046-lec05.pdf` |
| 6 | Python docs, time complexity of built-in types; psf/wiki e069e07 | full text | `6-python-time-complexity.html`, `6-psfwiki-timecomplexity-e069e07.txt`; also `6-substitute-python-bisect.html` (see corrections) |
| 7 | CPython source ab48ba8 | full text | `7-cpython-ab48ba8-excerpts.txt` (the seven files named in [7]) |
| 8 | Python docs: re, collections, Design FAQ | full text | `8-python-re.html`, `8-python-collections.html`, `8-python-design-faq.html` |
| 9 | Cox, regexp1, 2007 | full text | `9-cox-regexp1.html` |
| 10 | Davis, Coghlan, Servant, Lee, ESEC/FSE 2018 | full text | `10-davis-redos-fse18.pdf`, the author's own copy (davisjam.github.io). The ACM PDF returned 403 and was not retried |
| 11 | CommonMark Spec 0.31.2 | full text | `11-commonmark-0.31.2.html` |
| 12 | Ford, "Packrat Parsing", ICFP 2002 | full text | `12-ford-packrat.pdf` (arXiv cs/0603077) |
| 13 | Crosby and Wallach, USENIX Security 2003 | full text | `13-crosby-wallach.pdf` (USENIX open PDF) |
| 14 | Library git histories (commits still listed in the filed [14]) | full text | not copied: the git objects are in my read-only clones under `work/s4-algorithms/src/`. I did not re-dump commits, to avoid re-studying history next to the seal |
| 15 | Aho, Lam, Sethi, Ullman, *Compilers* 2e, 2006 | open substitute | commercial book with no open full text. Stanford CS143 notes failed TLS verification (not worked around); MIT 6.035 lectures 2, 3 and 3b have no longest-match p |
| 16 | Bentley, *Programming Pearls* 2e, 2000 | unverified | commercial book with no open full text; the notes attribute no claim to it |
| 17 | PEP 8 | full text | `17-pep8.html` |
| o1 | Sedgewick and Wayne, *Algorithms* 4e booksite home | overview only | `1-algs4-home.html` |
| o2 | Skiena, algorist.com (author's site, 3e) | overview only | `2-algorist-home.html` |
| o3 | Springer page for *The Algorithm Design Manual* 3e | overview only | `3-springer-adm3.html` |
| o4 | MIT Press page for CLRS 4e | overview refused/unreached | refused: 403 |
| o5 | MIT 6.046J Spring 2015, lecture notes list | overview only | `5-mit6046-s15-lecture-notes.html` |
| o6 | MIT 6.006 Spring 2020, lecture notes list | overview only | `6-mit6006-s20-lecture-notes.html` |
| o7 | Princeton COS 226 Spring 2024 | overview only | `7-princeton-cos226-syllabus.html` |
| o8 | MIT 6.851 Advanced Data Structures, Spring 2012, lectures | overview only | `8-mit6851-s12-lectures.html` |

## s5-search

Notes: `s5-search.md`. Errata: `s5-search.errata.md`. Files: `sources/s5-search/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Mouret and Clune 2015, MAP-Elites | full text | `1-map-elites.pdf` (arXiv) |
| 2 | Flageat and Cully 2023, Uncertain QD | full text | `2-uncertain-qd.pdf` (arXiv) |
| 3 | Justesen, Risi and Mouret 2019, adaptive sampling | full text | `3-justesen-adaptive-sampling.pdf` (ITU open copy, via Semantic Scholar `openAccessPdf`) |
| 4 | Whitley, Rana and Heckendorn 1999, island model | full text | `4-whitley-island.pdf` |
| 5 | Romera-Paredes et al., FunSearch | full text | `5-funsearch.html` (nature.com article page) |
| 6 | Novikov et al. 2025, AlphaEvolve | full text | `6-alphaevolve.pdf` (arXiv) |
| 7 | Langdon and Harman 2015, GISMOE / Bowtie2 | unverified | No open full text reachable. The author's site does not resolve, UCL Discovery serves a bot challenge, and Semantic Scholar does not list the DOI. The abstract  |
| 8 | Petke et al. 2018, GI survey | full text | `8-petke-gi-survey.pdf` (Stirling repository, CC BY) |
| 9 | Blot and Petke 2021, search heuristics for GI | full text | `9-blot-petke-search-heuristics.pdf` (HAL, via Semantic Scholar) |
| 10 | MAGPIE docs, commit b5f0a2e | full text | `10-magpie-docs-b5f0a2e.txt` (`entry_points.md` plus `scenario.md`) |
| 11 | Shypula et al. 2024, PIE | full text | `11-pie.pdf` (arXiv) |
| 12 | Jamieson and Talwalkar 2016 | full text | `12-jamieson-nonstochastic-bai.pdf` (arXiv) |
| 13 | Li et al. 2018, Hyperband | full text | `13-hyperband.pdf` (arXiv; the header reads JMLR 18 (2018) 1-52) |
| 14 | Karnin, Koren and Somekh 2013 | full text | `14-karnin-sh.pdf` (PMLR) |
| 15 | Lattimore and Szepesvári 2020, Bandit Algorithms | full text | `15-lattimore-bandit-algorithms.pdf` |
| 16 | Kaufmann, Cappé and Garivier 2016 | full text | `16-kaufmann-complexity-bai.pdf` (JMLR) |
| 17 | Russo 2016, top-two | full text | `17-russo-top-two.pdf` (arXiv) |
| 18 | Russo et al. 2018, TS tutorial | full text | `18-russo-ts-tutorial.pdf` (arXiv) |
| 19 | Locatelli, Gutzeit and Carpentier 2016, TBP | full text | `19-locatelli-tbp.pdf` (PMLR) |
| 20 | Smith and Winkler 2006, optimizer's curse | full text | `20-smith-winkler-optimizers-curse.pdf`, `20-smith-winkler-correction.pdf` (jimsmith.host.dartmouth.edu) |
| o1 | Lattimore and Szepesvári, Bandit Algorithms: contents pages (from the authors' free PDF) | overview only | `1-lattimore-toc.txt` |
| o1r | The same book, publisher front matter (assets.cambridge.org) | overview refused/unreached | refused: proxy 502 on CONNECT |
| o1s | The same book, banditalgs.com (the authors' site) | overview refused/unreached | refused: TLS, certificate expired (not bypassed) |
| o2 | Quality-Diversity optimisation algorithms site (quality-diversity.github.io): papers, about, tutorials | overview only | `2-qd-papers.html`, `2b-qd-home.html`, `2c-qd-tutorials.html` |
| o3 | Genetic Improvement of Software community site, with its Living Survey | overview only | `3-gi-site.html`, `3b-gi-living-survey.html` |
| o4 | UW CSE 541, Interactive Learning, Spring 2024 (Jamieson) | overview only | `4-uw-cse541-24sp.html` |
| o5 | Hutter, Kotthoff and Vanschoren (eds.), AutoML: Methods, Systems, Challenges (automl.org/book) | overview only | `5-automl-book.html` |
| o6 | Eiben and Smith, Introduction to Evolutionary Computing, 2nd ed. (Springer book page) | overview only | `6-eiben-smith-springer.html` |
| o6r | The same book's companion site, evolutionarycomputation.org | overview refused/unreached | refused: redirect loop (more than 50 redirects) |
| o7r | Luke, Essentials of Metaheuristics (cs.gmu.edu) | overview refused/unreached | refused: TLS, issuer not verifiable (not bypassed) |

## s6-merge

Notes: `s6-merge.md`. Errata: `s6-merge.errata.md`. Files: `sources/s6-merge/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Mens 2002, survey of software merging | unverified | Semantic Scholar's open link (hiper.cis.udel.edu) does not resolve; IEEE copy not open |
| 2 | Khanna, Kunal, Pierce 2007, diff3 | full text | `2-diff3.pdf` (author copy, UPenn) |
| 3 | Apel et al. 2011, semistructured merge | full text | `3-apel-ssmerge.pdf` |
| 4 | Cavalcanti, Borba, Accioly 2017 | full text | `4-cavalcanti-s3m.pdf`, `4b-s3m-project.html`; dl.acm.org refused (403) |
| 5 | Shen et al. 2019, IntelliMerge | unverified | dl.acm.org refused (403); no arXiv copy found |
| 6 | Ellis, Nadi, Dig 2021, RefMerge evaluation | full text | `6-ellis-refmerge.pdf` (arXiv 2112.10370) |
| 7 | Zhu et al. 2022, Mastery (SETTA) | open substitute | `7-mastery-jsa.pdf` (Na Meng's page, VT); SETTA paper itself not open |
| 8 | Horwitz, Prins, Reps 1989 | open substitute | `8b-horwitz-abstract.html`, `8-horwitz.pdf` (scan, not read); ACM copy is "bronze" on dl.acm.org, which refuses automated clients |
| 9 | Sousa, Dillig, Lahiri 2018, SafeMerge | full text | `9-safemerge.pdf`; the author's own utexas copy failed TLS verification (not worked around) |
| 10 | Brun et al. 2013, Crystal | full text | `10-brun-crystal.pdf` |
| 11 | Da Silva, Borba et al. 2024, SAM | full text | `11-dasilva-sam.pdf` |
| 12 | Ellis and Gibbs 1989, OT | open substitute | not found in Semantic Scholar; no open copy found |
| 12b | Wikipedia, "Operational transformation" | full text | `12b-wikipedia-ot.html` |
| 13 | Shapiro et al. 2011, CRDTs | full text | `13-crdt-sss2011.pdf` (HAL hal-00932836) |
| 14 | Roundy 2005 (Haskell Workshop) and "Theory of patches" | open substitute | `14-darcs-mergers-doc.html`; the Tufts copy of the 2009 manual reset the connection twice; the 2005 paper is closed |
| 15 | Mimram, Di Giusto 2013 | full text | `15-mimram.pdf` |
| 16 | Pijul manual and blog | full text | `16-pijul-why.html`, `16b-pijul-partials.html` |
| 17 | Le Goues et al. 2012, GenProg | full text | `17-genprog.pdf` (author copy) |
| 18 | Renzullo et al. 2018 | unverified | dl.acm.org refused (403); the GI workshop copy on www.cs.ucl.ac.uk does not resolve |
| 19 | Liou et al. 2022, GEVO | full text | `19-gevo.pdf` (arXiv 2208.12350) |
| 20 | Langdon, Harman 2015 | full text | `20-langdon-bowtie2.pdf` (UCL Discovery) |
| 21 | Petke et al. 2018 | full text | `21-petke-gi-survey.pdf` (UCL Discovery) |
| 22 | Zeller 1999 | full text | `22-zeller.pdf` |
| 23 | Tate et al. 2009/2011 | full text | `23-eqsat.pdf` |
| 24 | Whitfield, Soffa 1997 | unverified | the Tufts copy reset the connection twice; ACM copy not open |
| 25 | Kulkarni et al. 2006 (+ TACO 2008) | full text | `25-kulkarni-cgo06.pdf` (FSU), `25b-kulkarni-taco08.html` |
| 26 | Pan, Eigenmann 2006 | unverified | engineering.purdue.edu returned 503 three times; core.ac.uk refused (403) |
| 27 | Lerner, Grove, Chambers 2002 | unverified | closed per Semantic Scholar; the authors' UCSD and Cornell copies failed TLS verification (not worked around) |
| o1 | UCSC CSE290S (Kuper), Winter 2023, "Distributed Software Systems: Global-First and Local-First" | overview only | `1b-ucsc-cse290s-home.html`, `1-ucsc-cse290s-schedule.html` (`readings.html` was 404) |
| o2 | Cambridge Part IB, Concurrent and Distributed Systems 2023-24 | overview only | `2-cam-concdissys.html` |
| o3 | CMU 15-745 Optimizing Compilers | overview only | no file |
| o4 | MIT OCW 6.035 Computer Language Engineering (Spring 2010) | overview only | `4-mit-6035-syllabus.html` (`calendar/` was 404) |
| o5 | Monperrus, "The Living Review on Automated Program Repair" (HAL) | overview only | `5-apr-living-review.pdf` |
| o6 | Shen, Xiao, Meng, He 2021, "Automatic Detection and Resolution of Software Merge Conflicts: Are We There Yet?" | overview only | `6-merge-survey.pdf` (arXiv 2102.11307) |
| o7 | darcs.net "Theory" index | overview only | `7-darcs-theory-index.html` |
| o8 | Cooper and Torczon, Engineering a Compiler, 3rd ed. (Elsevier) | overview only | `8-engineering-a-compiler-toc.html` |

## s7-cpython

Notes: `s7-cpython.md`. Errata: `s7-cpython.errata.md`. Files: `sources/s7-cpython/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
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
| 11 | Mytkowicz, Diwan, Hauswirth, Sweeney, PLDI 2010 | full text | `11-mytkowicz-pldi10.pdf`. Semantic Scholar lists it as CLOSED; this is the authors' copy at plv.colorado.edu/papers/mytkowicz-pldi10.pdf |
| 12 | Frederickson, py-spy README | full text | `12-py-spy-readme.txt` (`c53bfe1`) |
| 13 | Austin README (P403n1x87) | full text | `13-austin-readme.txt` (`9e6cc09`) |
| 14 | Python Wiki, PythonSpeed/PerformanceTips | full text | `14-python-wiki-performancetips.html` (the moin URL now redirects to wiki.python.org/python/performance/PythonSpeed/PerformanceTips.html) |
| 15 | faster-cpython/ideas, pystats docs | full text | `15-faster-cpython-pystats-docs.txt` (`e697f50`) |
| 16 | CPython InternalDocs, inlined comprehensions, and What's New 3.12 | full text | `16-inlined-comprehensions-whatsnew-3.12.txt` |
| o1 | Gorelick and Ozsvald, *High Performance Python*, 2nd ed., O'Reilly book page | overview refused/unreached | refused: 403 (oreilly.com) |
| o2 | Shaw, *CPython Internals*, Real Python book page | overview refused/unreached | refused: 403 (realpython.com) |
| o3 | MIT OCW 6.172, Performance Engineering of Software Systems, Fall 2018 (Leiserson, Shun), syllabus | overview only | `3-mit-6172-syllabus.html` |
| o3b | MIT OCW 6.172, lecture-slides list | overview only | `3b-mit-6172-lectures.html` |
| o4 | Guo, "CPython internals" video course page (pgbovine.net) | overview refused/unreached | not filed: the proxy returned 502 twice (CONNECT tunnel failed), so this is not a refusal by the site; not retried further |
| o5 | Gregg, *Systems Performance*, 2nd ed. (2020), the author's book page | overview only | `5-gregg-systems-performance-2e.html` |
| o6 | CPython `InternalDocs/README.md` (main) | overview only | `6-cpython-internaldocs-readme.md` |
| o7 | *High Performance Python*, 2nd ed., the authors' companion repository (mynameisfiber/high_performance_python_2e), chapter directories | overview only | `7-hpp2e-companion-repo-chapters.txt` (substitute for #1) |
| o8 | Stinner, pyperf documentation index | overview only | `8-pyperf-docs-index.html` |

## s8-expert

Notes: `s8-expert.md`. Errata: `s8-expert.errata.md`. Files: `sources/s8-expert/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Ma et al., SWE-fficiency, arXiv:2511.06090v3 | full text | `1-swe-fficiency.pdf` (+ `.txt`, `.raw.txt`) |
| 2 | He et al., SWE-Perf, arXiv:2507.12415v2 | full text | `2-swe-perf.pdf` (+ `.txt`, `.raw.txt`) |
| 3 | Shetty et al., GSO, arXiv:2505.23671v3 | full text | `3-gso.pdf` (+ `.txt`, `.raw.txt`) |
| 4 | Curtsinger and Berger, Coz, arXiv:1608.03676 | full text | `4-coz.pdf` (+ `.txt`, `.raw.txt`) |
| 5 | Bhuiyan et al., ReDoS SoK, arXiv:2406.11618v4 | full text | `5-redos-sok.pdf` (+ `.raw.txt`) |
| 6 | Leiserson and Shun, MIT 6.172 F18, Lecture 2, "Bentley Rules" | full text | `6-mit6172-lec2-bentley-rules.pdf` (+ `.raw.txt`) |
| 7 | PSF, "The Python Profilers" (3.11) | full text | `7-python-profile-docs.html` (+ `.txt`) |
| 8 | Berger, Stern and Altmayer Pizzorno, Scalene, arXiv:2212.07597 | full text | `8-scalene.pdf` (+ `.raw.txt`) |
| 9 | Baltes et al., "Navigate, Understand, Communicate", arXiv:1706.10118 | full text | `9-locate-perf-bugs.pdf` (+ `.raw.txt`) |
| 10 | the 124 allowed commits (primary data) | full text | none: given material under `r3/s8/patches/` and `trees/` |
| 11 | the engine's archive and source (internal) | full text | none: internal files in `/home/user/step3-emergence-r1` |
| o1 | MIT 6.172 Performance Engineering of Software Systems (Fall 2018), Syllabus | overview only | `1-mit-6172-syllabus.html` (+ `.txt`) |
| o2 | MIT 6.172, Lecture Slides (23 sessions) | overview only | `2-mit-6172-lectures.html` (+ `.txt`) |
| o3 | Gregg, *Systems Performance*, 2nd ed., the author's book page | overview only | `3-gregg-sysperf2-toc.html` (+ `.txt`) |
| o4 | MIT 6.172, Readings | overview only | `4-mit-6172-readings.html` (+ `.txt`) |
| o5 | Python wiki, "PythonSpeed/PerformanceTips" | overview only | `5-python-wiki-perftips.html` (+ `.txt`) |
| o6 | Bakhvalov, *Performance Analysis and Tuning on Modern CPUs*, book page | overview refused/unreached | refused: TLS (self-signed certificate on book.easyperf.net); not worked around |
| o7 | O'Reilly, *High Performance Python*, 2nd ed., book page | overview refused/unreached | refused: 403 |

## z1-analogy

Notes: `z1-analogy.md`. Errata: `z1-analogy.errata.md`. Files: `sources/z1-analogy/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Gentner 1983, Cogn. Sci. | full text | `1-gentner1983.pdf` |
| 2 | Holyoak and Thagard 1995, *Mental Leaps* | open substitute | `2-mentalleaps-ch3.pdf` |
| 3 | Gick and Holyoak 1980, Cogn. Psych. | unverified | deepblue 403, pressbooks summary 403, Semantic Scholar rate-limited (429); no open copy found |
| 4 | Fu et al. 2013, JMD | unverified | the author URL from my notes now returns 404; Semantic Scholar lists DOI 10.1115/1.4023158 as CLOSED |
| 5 | Altshuller, *40 Principles* | open substitute | `5-substitute-wikipedia-triz.html` |
| 6 | Skol et al. 2006, Nat. Genet. | open substitute | `6-substitute-sha2011.xml` (Sha, Zhang and Zhang 2011, PLoS ONE, PMC3142116, which restates Skol's result) |
| 7 | Zhang, Chung and Oldenburg 1999, JBS | open substitute | `7-substitute-wikipedia-zfactor.html` (its table is "a modification of Table 1 shown in Zhang et al. (1999)") |
| 8 | Brideau et al. 2003, JBS | open substitute | `8-substitute-pmc6015058.xml` (Shterev et al. 2018, Sci. Rep., which describes the B-score) |
| 9 | Malo et al. 2006, Nat. Biotech. | unverified | Semantic Scholar CLOSED, not open access in Europe PMC, PMC returned a reCAPTCHA page |
| 10 | Padioleau et al. 2008, EuroSys | full text | `10-padioleau2008.pdf` |
| 11 | Ellis and Gibbs 1989, SIGMOD | full text | `11-ellis1989.pdf` |
| 12 | Kulkarni et al. 2006, CGO | open substitute | `12-substitute-kulkarni-taco09.pdf`, `12-kulkarni-page.html`; no open CGO 2006 PDF found |
| 13 | Tate et al. 2009/2011, equality saturation | full text | `13-eqsat.pdf` |
| 14 | Caruana et al. 2004, ICML | unverified | `14-caruana-abstract.html`; the author copy at cs.cornell.edu failed TLS verification (not bypassed); the icml.cc paper PDF returned 404; Semantic Scholar CLOSE |
| 15 | Good 1953, Biometrika | open substitute | `15-substitute-wikipedia-goodturing.html`; the UPenn course page returned 403 |
| 16 | Zöllner and Pritchard 2007, AJHG | full text | `16-zollner2007.html` |
| 17 | Breyfogle 2003, *Implementing Six Sigma* | open substitute | `17-substitute-wikipedia-rty.html` |
| 18 | RFC 7464 (Williams 2015) | full text | `18-rfc7464.txt` |
| 19 | diff-match-patch (Fraser) | full text | `19-diffmatchpatch-readme.md`, `19-diffmatchpatch.py`; the wiki API page returned 403 |
| o1 | Stanford Encyclopedia of Philosophy, "Analogy and Analogical Reasoning" (rev. 2019), entry contents | overview only | `1-sep-analogy.html` |
| o2 | NIST/SEMATECH e-Handbook of Statistical Methods, ch. 2 "Measurement Process Characterization" | overview only | `2-nist-ehandbook-mpc.html` (the handbook's top-level `toc.htm` redirects (302) to the ITL landing page, so it was not filed) |
| o3 | UCSC CSE290S (Winter 2023), "Distributed Software Systems: Global-First and Local-First" | overview only | `3-ucsc-cse290s-crdt.html`, `3b-ucsc-cse290s-schedule.html` |
| o4 | MIT OCW 6.035 Computer Language Engineering (Spring 2010) | overview only | `4-mit-6035-syllabus.html` |
| o5 | triz40.com, "40 TRIZ Principles" | overview only | `5-triz40-principles.html` |

## z2-contradiction

Notes: `z2-contradiction.md`. Errata: `z2-contradiction.errata.md`. Files: `sources/z2-contradiction/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Altshuller, *The Innovation Algorithm* (1999) | open substitute | `1-triz-wiki-substitute.html` (Wikipedia "TRIZ"). The book is commercial, with no open copy. |
| 2 | Altshuller, *40 Principles* (1997) | open substitute | `5-rea2001-part1-metodolog.html`, `5-rea2001-part2-metodolog.html` (Altshuller's 40 principles listed by number) and `1-triz-wiki-substitute.html`. The book is  |
| 3 | Savransky, *Engineering of Creativity* (2000) | unverified | CRC Press, commercial, with no open copy. Only its bibliographic data is confirmed, by Rea's endnotes. |
| 4 | Haines-Gadd, *TRIZ For Dummies* (2016), App. D; Lean Methods page | unverified | oreilly.com answered 403 (Access Denied), and wiley.com answered 403. leanmethods.com timed out twice (60 s and 90 s). |
| 5 | Rea, "TRIZ and Software: 40 Principle Analogies", Parts 1-2 (2001); Mann (2008) | full text | `5-rea2001-part1-metodolog.html` (archives/2001/09/e), `5-rea2001-part2-metodolog.html` (archives/2001/11/e). These are the free TRIZ Journal archive on metodol |
| 6 | Goldratt, *What Is This Thing Called TOC* (1990) | open substitute | `15-evaporating-cloud.html`, which reports Goldratt 1990 pp. 43-51 for the batch case, and `8-tp-wiki-substitute.html` for the ISBN. maaw.info (the Martin guide |
| 7 | Goldratt, *It's Not Luck* (1994) | unverified | Commercial, with no open copy. The ISBN is confirmed by both Wikipedia pages. |
| 8 | Dettmer, *Goldratt's TOC* (1997) | unverified | Commercial, and no open page names this book. `8-tp-wiki-substitute.html` lists only Dettmer 2003 and 2007. |
| 9 | Mason (1969), *Management Science* | unverified | Closed: Semantic Scholar and OpenAlex both say closed, and pubsonline.informs.org answered 403. The publisher elides the abstract in S2. |
| 10 | Cosier and Aplin (1980), *SMJ* | unverified | `10-cosier-aplin-repec-abstract.html` (RePEc abstract). The full text is closed (S2 and OpenAlex). |
| 11 | Ilevbare, Probert and Phaal (2013), *Technovation* | unverified | Closed. OpenAlex lists a submitted version at publications.eng.cam.ac.uk, but that host does not resolve. The abstract is elided in S2. |
| 12 | Wald (1945), *Ann. Math. Stat.* | open substitute | `12-sprt-wiki-substitute.html` (Wikipedia "Sequential probability ratio test"). The open Project Euclid PDF returned an Incapsula bot block, so it was not retri |
| 13 | Pocock (1977), *Biometrika* | open substitute | `13-pocock-boundary-wiki.html`. The paper is closed (S2 and OpenAlex). online.stat.psu.edu failed TLS verification through the proxy, so it was not accessed. |
| 14 | Johari, Koomen, Pekelis and Walsh (2017), KDD | open substitute | `14-johari-pekelis-walsh-arxiv1512.04922v3.pdf`, a companion paper and not the KDD text; see the correction below. dl.acm.org answered 403. |
| 15 | "Evaporating cloud", Wikipedia | full text | `15-evaporating-cloud.html` (oldid 1346671759). |
| o1 | Savransky, *Engineering of Creativity*, Routledge product page | overview only | `1-savransky-toc.html` |
| o2 | MATRIZ, "Detailed descriptions of the topics required for Levels 1-3" | overview only | `2-matriz-L1-L3-outlines.pdf` |
| o3 | Ramdas, Grünwald, Vovk and Shafer, "Game-theoretic statistics and safe anytime-valid inference", arXiv:2210.01948 abstract page | overview only | `3-ramdas2022-savi-abs.html` |
| o4 | MIT OCW ESD.33 Systems Engineering (Frey, Summer 2004), calendar | overview only | `4-ocw-esd33-calendar.html` |
| o5 | triz40.com, "40 TRIZ Principles: List with Examples" | overview only | `5-triz40-principles.html` |
| o6 | Wiley, *TRIZ For Dummies* product page (TOC) | overview refused/unreached | refused: 403 |
| o7 | ASQ Quality Press, Dettmer, *The Logical Thinking Process* | overview refused/unreached | refused: 403 |
| o8 | Taylor & Francis, Jennison and Turnbull, *Group Sequential Methods* | overview refused/unreached | refused: 403 |
| o9 | Penn State STAT 509 (interim analysis lessons); Ramdas's Stanford page (course list) | overview refused/unreached | not reached: TLS verification failed through the proxy (not a refusal; not retried) |

## z3-contrarian

Notes: `z3-contrarian.md`. Errata: `z3-contrarian.errata.md`. Files: `sources/z3-contrarian/`.

| # | source | type | file, or why none |
| - | ------ | ---- | ----------------- |
| 1 | Thiel and Masters, *Zero to One* (2014) | open substitute | `1-thiel-cs183-class11-secrets.html`: Blake Masters' notes of Thiel's Stanford CS183, Class 11 "Secrets" (2012). The book is commercial; no open full text. |
| 2 | Munger, *Poor Charlie's Almanack*, "invert, always invert" | open substitute | `2-jacobi-wikipedia.html`: Wikipedia, Carl Gustav Jacob Jacobi, for the Jacobi attribution. The book is commercial; the Stripe Press web edition rendered no tex |
| 3 | Pólya, *How to Solve It* (1945/1957) | open substitute | `3-polya-wikipedia.html`: Wikipedia, How to Solve It. The book is commercial. |
| 4 | Mytkowicz et al., "Producing Wrong Data..." (ASPLOS 2009) | full text | `4-mytkowicz-wrongdata-course-copy.pdf`: open copy on a university course page (Vanderbilt CS 8395 readings). Semantic Scholar lists it as closed; the authors'  |
| 5 | Mytkowicz et al., "Evaluating the Accuracy of Java Profilers" (PLDI 2010) | full text | `5-mytkowicz-profilers-pldi10.pdf`: from the authors' group page, plv.colorado.edu |
| 6 | Curtsinger and Berger, Stabilizer (ASPLOS 2013) | full text | `6-stabilizer.pdf`: author's site, people.cs.umass.edu |
| 7 | Curtsinger and Berger, Coz (SOSP 2015) | full text | `7-coz.pdf`: arXiv 1608.03676 (the SOSP'15 paper) |
| 8 | Berger, Stern and Altmayer Pizzorno, Scalene (OSDI 2023) | full text | `8b-scalene-osdi23.pdf` (the OSDI version, from the authors' repository) and `8-scalene.pdf` (arXiv 2212.07597) |
| 9 | Kanev et al., "Profiling a Warehouse-Scale Computer" (ISCA 2015) | full text | `9-kanev.pdf`: research.google.com/pubs/archive/44271.pdf. The ACM copy refused automated clients. |
| 10 | Leiserson et al., "There's plenty of room at the Top" (Science 2020) | unverified | Science is paywalled, and MIT DSpace's open copy returned "Web Firewall 429", asking for a login; not worked around. Filed instead: `10-leiserson-top-bib.txt` ( |
| 11 | Proebsting, "Proebsting's Law" | full text | `11-proebsting.html` |
| 12 | Hipp, SQLite 3.8.7 mail (2014); SQLite "cpu.html" | full text | `12b-sqlite-hipp-2014.html`, `12a-sqlite-cpu.html` |
| 13 | Nethercote, "How to speed up the Rust compiler" series | full text | `13-nethercote-2016.html`, `13b-nethercote-2019-still-faster.html`, `13c-nethercote-2019-last.html` |
| 14 | FBDetect (SOSP 2024) | full text | `14-fbdetect.pdf` |
| 15 | Good (1953), Biometrika 40:237-264 | open substitute | `15-good-turing-wikipedia.html`. Semantic Scholar lists the paper as closed; the gwern copy is a mirror, so it was not used. |
| 16 | Chao (1987), Biometrics 43:783-791 | open substitute | `16-chao2-wiqid.R.txt`: the wiqid R source on CRAN/rdrr.io. Semantic Scholar lists the paper as closed. |
| 17 | Dorfman (1943), Ann. Math. Stat. 14(4):436-440 | full text | `17-dorfman-course-copy.pdf`: copy on a university course page (Tampere). Project Euclid's open copy refused the automated client (Incapsula), and was not worke |
| o1 | MIT OCW 6.172, Performance Engineering of Software Systems (Fall 2018), calendar and syllabus | overview only | `1-mit-6172-calendar.html`, `1b-mit-6172-syllabus.html` |
| o2 | Gregg, *Systems Performance*, 2nd ed., author's page | overview only | `2-gregg-systems-performance-2e.html` |
| o3 | Thiel, Stanford CS183 (2012), class list (Masters' notes) | overview only | `3-cs183-class-list.html` |
| o4 | Jain, *The Art of Computer Systems Performance Analysis* (1991), author's page | overview only | `7-jain-art-of-perf-analysis.html`, `7b-jain-toc.html` |
| o5 | Cornell CS 6120 (2019fa), syllabus and schedule | overview refused/unreached | refused: TLS certificate verification failed (not bypassed) |
| o6 | Bakhvalov, *Performance Analysis and Tuning on Modern CPUs*: chapter list through the GitHub API | overview refused/unreached | refused: 403 |
| o7 | Pólya, *How to Solve It*, Princeton UP page | overview refused/unreached | not filed: the page carries no table of contents |
