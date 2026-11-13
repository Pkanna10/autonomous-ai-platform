# s6-merge errata (full-text check, 2026-11-13)

When the notes were filed, every source was read only from a search summary or an abstract (WebFetch could not reach arxiv.org or uni-saarland.de). This check downloaded the texts with `curl -sSL` and searched them with `pdftotext`. The numbers below refer to the notes' Sources list.

## Sources
| # | citation (short) | status: full text / open substitute / unverified | file under sources/s6-merge/ or why none |
|---|---|---|---|
| 1 | Mens 2002, survey of software merging | unverified | Semantic Scholar's open link (hiper.cis.udel.edu) does not resolve; IEEE copy not open |
| 2 | Khanna, Kunal, Pierce 2007, diff3 | full text | `2-diff3.pdf` (author copy, UPenn) |
| 3 | Apel et al. 2011, semistructured merge | full text | `3-apel-ssmerge.pdf` |
| 4 | Cavalcanti, Borba, Accioly 2017 | full text (authors' preprint) | `4-cavalcanti-s3m.pdf`, `4b-s3m-project.html`; dl.acm.org refused (403) |
| 5 | Shen et al. 2019, IntelliMerge | unverified (only the scenario count, through [6]) | dl.acm.org refused (403); no arXiv copy found |
| 6 | Ellis, Nadi, Dig 2021, RefMerge evaluation | full text | `6-ellis-refmerge.pdf` (arXiv 2112.10370) |
| 7 | Zhu et al. 2022, Mastery (SETTA) | open substitute: the extended journal version, "On the Methodology of Three-Way Structured Merge..." (same authors) | `7-mastery-jsa.pdf` (Na Meng's page, VT); SETTA paper itself not open |
| 8 | Horwitz, Prins, Reps 1989 | open substitute: the authors' abstract page; the UW technical report is a scanned image with no text layer, and no OCR is available here | `8b-horwitz-abstract.html`, `8-horwitz.pdf` (scan, not read); ACM copy is "bronze" on dl.acm.org, which refuses automated clients |
| 9 | Sousa, Dillig, Lahiri 2018, SafeMerge | full text (arXiv preprint, titled "Verifying Semantic Conflict-Freedom in Three-Way Program Merges") | `9-safemerge.pdf`; the author's own utexas copy failed TLS verification (not worked around) |
| 10 | Brun et al. 2013, Crystal | full text | `10-brun-crystal.pdf` |
| 11 | Da Silva, Borba et al. 2024, SAM | full text of the arXiv preprint (2310.02395 v1); JSS version not accessed | `11-dasilva-sam.pdf` |
| 12 | Ellis and Gibbs 1989, OT | open substitute: [12b] | not found in Semantic Scholar; no open copy found |
| 12b | Wikipedia, "Operational transformation" | full text | `12b-wikipedia-ot.html` |
| 13 | Shapiro et al. 2011, CRDTs | full text | `13-crdt-sss2011.pdf` (HAL hal-00932836) |
| 14 | Roundy 2005 (Haskell Workshop) and "Theory of patches" | open substitute: Roundy's old theory document on darcs.net ("Merges Documentation") | `14-darcs-mergers-doc.html`; the Tufts copy of the 2009 manual reset the connection twice; the 2005 paper is closed |
| 15 | Mimram, Di Giusto 2013 | full text | `15-mimram.pdf` |
| 16 | Pijul manual and blog | full text | `16-pijul-why.html`, `16b-pijul-partials.html` |
| 17 | Le Goues et al. 2012, GenProg | full text | `17-genprog.pdf` (author copy) |
| 18 | Renzullo et al. 2018 | unverified | dl.acm.org refused (403); the GI workshop copy on www.cs.ucl.ac.uk does not resolve |
| 19 | Liou et al. 2022, GEVO | full text | `19-gevo.pdf` (arXiv 2208.12350) |
| 20 | Langdon, Harman 2015 | full text | `20-langdon-bowtie2.pdf` (UCL Discovery) |
| 21 | Petke et al. 2018 | full text | `21-petke-gi-survey.pdf` (UCL Discovery) |
| 22 | Zeller 1999 | full text | `22-zeller.pdf` |
| 23 | Tate et al. 2009/2011 | full text (LMCS version, arXiv 1012.1802) | `23-eqsat.pdf` |
| 24 | Whitfield, Soffa 1997 | unverified | the Tufts copy reset the connection twice; ACM copy not open |
| 25 | Kulkarni et al. 2006 (+ TACO 2008) | full text (CGO 2006); TACO 2008 abstract only | `25-kulkarni-cgo06.pdf` (FSU), `25b-kulkarni-taco08.html` |
| 26 | Pan, Eigenmann 2006 | unverified | engineering.purdue.edu returned 503 three times; core.ac.uk refused (403) |
| 27 | Lerner, Grove, Chambers 2002 | unverified | closed per Semantic Scholar; the authors' UCSD and Cornell copies failed TLS verification (not worked around) |

## Corrections
- [2] Notes, textual 3-way merge, "a third-party summary calls its behaviour surprisingly unpredictable" -> the abstract and section 1 say something stronger:
  - "a number of seemingly natural intuitions are incorrect in general";
  - the paper formalises idempotence, stability, and near-complete success when both sides changed in similar ways, and shows "none of these properties hold in general";
  - its main result is a separation condition under which edits to well-separated regions never conflict.
- [2] Core sources, "the line-based 3-way merge that git's merge descends from" -> not in [2], which names CVS and Subversion as its users (section 1), not git. Unverified.
- [3] confirmed:
  - 24 projects and 180 scenarios;
  - conflicts cut in 60 % of scenarios, by 34±21 %;
  - renaming as the main weakness (abstract, section 5.4);
  - method bodies "as plain text", merged by unstructured merge (section 3).
- [4] Notes, "semistructured merge ... may add false negatives" -> the abstract says the authors "find no evidence that semistructured merge leads to fewer false negatives", and argue those false negatives are harder to detect and resolve. It is "no fewer", not "more". The sample is more than 30,000 merges from 50 projects. Confirmed for s3m: half the reported conflicts, no added false positives, at least 8 % fewer false negatives.
- [5] Notes, "IntelliMerge, on 1,070 scenarios from 10 Java projects" -> [6] (dataset section) confirms that "these 10 projects contained 1,070 conflicting merge scenarios". The 58.90 %, 11.84 %, 88.48 % and 90.22 % figures remain unverified.
- [6] Notes, "On 2,001 harder refactoring scenarios it reduced conflicts in 24 %" -> the abstract says "2,001 merge scenarios with refactoring-related conflicts from 20 open-source projects". "Harder" was my word, not the paper's. Confirmed: IntelliMerge reduces or resolves conflicts in 478 (24 %) of them and increases conflicting LOC in 597 (30 %), and the reproduction landed "within 10%" of the original precision and recall.
- [7] Notes, Mastery "2.4x as fast" -> the extended journal version says "2.5 x as fast as a state-of-the-art structured merge tool" (abstract). The SETTA figure of 2.4x is unverified. The journal version confirms 40,533 scenarios from 78 projects, and shifted code in 38.54 % of them (section 1).
- [8] Notes, "using program dependence graphs and slicing" -> the authors' abstract says only "a program representation that is similar, but not identical, to the program dependence graphs". "Slicing" is unverified. The abstract also limits the problem to a "greatly simplified" language: scalar variables, assignments, conditionals and while loops only. "Do not interfere" is confirmed.
- [9] confirmed (arXiv version, section 1 and evaluation): 52 scenarios, conflict-freedom verified for 39 of 52 (75 %), "eleven real violations", and a compositional algorithm. The paraphrase of conflict-freedom matches section 1: no new behaviour beyond the variants, and no semantically incompatible changes.
- [10] confirmed: nine systems, 3.4 million lines, and "over 550,000 development versions". Conflicts are frequent, persistent, and appear as build and test failures too.
- [11] Notes, "SAM found 9 of 29" -> arXiv v1 (abstract) says "nine detected conflicts out of 28", with Differential EvoSuite and EvoSuite plus Testability Transformations. The 29 came from a summary of the JSS version, which was not accessed. Use 9 of 28 unless the journal text says otherwise.
- [12b] Notes, "Several published transformation functions were later shown to violate TP2" -> withdrawn: the page does not say this. It says that, after Ellis and Gibbs, "some correctness issues were identified", and that several approaches fixed them (History). It defines CP1/TP1 and CP2/TP2, with the precondition that CP2/TP2 is required only when an OT system can transform two operations in two different contexts. The claim came from a personal note page found by the search.
- [13] confirmed: Definition 4 (a monotonic semilattice object is SEC) and Definition 6 (commutativity). Commutation of all concurrent operations is a sufficient condition (a CmRDT).
- [14] confirmed by the substitute: commutation is "the process of changing the order of two sequential patches", and for filepatches "trivial if they modify different files", else to be checked.
- [15] confirmed: merge as pushout; a pushout need not exist; the free completion under finite colimits ("free finite cocompletion").
- [16] confirmed (why_pijul): "either A and B can be applied in any order, or A depends on B, or B depends on A", application is associative, and both sides of a conflict are applied without resolving it. The 2020 post says "any two changes that could have been written independently always commute".
- [17] confirmed (abstract): structural differencing and delta debugging reduce the variant to a minimal repair.
- [19] confirmed: 88.2 % of a 17 % improvement from edits 5, 6, 8 and 10, with 8 and 10 depending on 6; prior EC work "rarely discovers epistasis".
- [19] Bearing on L6, "Modest sub-additivity agrees with [18][19], where strong interaction is rare" -> wrong for [19]:
  - GEVO calls "multiple interdependent code modifications" "a key source of the impressive performance improvements";
  - for ADEPT-V1, 12 of 17 significant edits are epistatic and give 17 %, against 7 % for the 5 independent ones (section VI-B);
  - for ADEPT-V0 and SIMCoV it found no performance-impactful epistatic edits.

  So [19] shows that strong interaction varies by program, not that it is rare. The archive's 0.91 additivity ratio stands as my own measurement; [18] is unverified.
- [20] confirmed (abstract): "70 times faster (on average)" on a 50,000-line C++ system.
- [21] confirmed: core papers 1995 to 2015; 96 % use evolutionary algorithms.
- [22] confirmed: 178,000 changed GDB lines; interference and inconsistency handled (section 1).
- [23] confirmed: an optimisation "will irrevocably prevent another optimization ... from triggering" (section 1).
- [25] confirmed and sharpened: the CGO 2006 paper exhaustively enumerated the phase orderings for "more than 98% of the functions in our benchmark suite". The TACO 2008 abstract confirms "a reasonable amount of time for most of the functions", with pruning.

## Claims still unverified
- [1] Mens's taxonomy: textual, syntactic and semantic merge; state-based and operation-based merge.
- [2]/[git] That git's merge descends from diff3.
- [5] IntelliMerge's −58.90 % against git, −11.84 % against jFSTMerge, precision 88.48 % and recall 90.22 %.
- [7] The SETTA 2022 version's "2.4x".
- [8] "Slicing" as Integrate's method, beyond the abstract.
- [11] "29" known conflicts in the JSS version.
- [12] The content of Ellis and Gibbs itself; [12b] supports only GROVE, the first OT algorithm, and the two consistency properties.
- [18] Renzullo et al.: 4.63 %, 9 % for `look`, 62.5 % of unique repairs.
- [24] Whitfield and Soffa's enabling and disabling analysis.
- [26] Combined Elimination, and its 0.2 % gap to the exhaustive optimum. The seed (a) protocol cites it, so treat that protocol as my proposal until [26] is read.
- [27] Lerner et al.'s claim that composing analyses avoids iteration's precision loss.
- The archive computations marked [A] in the notes are mine. They are not sources and are unchanged by this check.

## Overview sources
| # | source (short) | kind: TOC / chapter summaries / syllabus / topic list / reading list | file under sources/s6-merge/overview/, or "refused: <code>" |
|---|---|---|---|
| 1 | UCSC CSE290S (Kuper), Winter 2023, "Distributed Software Systems: Global-First and Local-First" | syllabus + reading list (schedule) | `1b-ucsc-cse290s-home.html`, `1-ucsc-cse290s-schedule.html` (`readings.html` was 404) |
| 2 | Cambridge Part IB, Concurrent and Distributed Systems 2023-24 | syllabus / topic list | `2-cam-concdissys.html` |
| 3 | CMU 15-745 Optimizing Compilers | none: `/~15745/` serves an empty directory index | no file |
| 4 | MIT OCW 6.035 Computer Language Engineering (Spring 2010) | syllabus with lecture list | `4-mit-6035-syllabus.html` (`calendar/` was 404) |
| 5 | Monperrus, "The Living Review on Automated Program Repair" (HAL) | TOC / reading list | `5-apr-living-review.pdf` |
| 6 | Shen, Xiao, Meng, He 2021, "Automatic Detection and Resolution of Software Merge Conflicts: Are We There Yet?" | TOC / topic list (survey outline: conflict kinds, tools, related work) | `6-merge-survey.pdf` (arXiv 2102.11307) |
| 7 | darcs.net "Theory" index | topic list | `7-darcs-theory-index.html` |
| 8 | Cooper and Torczon, Engineering a Compiler, 3rd ed. (Elsevier) | TOC | `8-engineering-a-compiler-toc.html` |

## Not yet covered
- Conflict taxonomy: textual, compiling and dynamic conflicts (overview #6). The combine re-runs the suite on the tip but records only textual skips, so an L5 ledger that counts only textual conflicts may undercount.
- Resolving a conflict by taking one side, which developers do (overview #6). This bears on L5 and L6: choose-one is what the combine does, and the open question is how the side is chosen.
- Conflict prediction from change features (overview #6). It could rank keeps before the combine (L5), or flag likely repeats before trials (L8).
- Partial merge, "merge what you can" (Schiefer et al., overview #1). This bears on L5: apply the hunks of a blocked keep that do not conflict, then re-measure.
- Mergeable replicated data types (Kaki et al., overview #1). Probably not relevant: they merge data, not code.
- Collaborative text-editing CRDTs (overview #2). These could bear on an OT/CRDT-style "rewrite B over A" for blocked keeps (L5).
- Causal ordering and vector clocks (overview #2). These may bear on recording the dependencies of stacked rounds (X2-DT, L8); otherwise probably not relevant.
- Darcs 2 conflictors and the Camp formalisation (overview #7). Probably not relevant beyond the theory already in the notes.
- Patch overfitting in program repair (overview #5, section 5.2). This bears on L6 and L9: keeps validated on one benchmark may not compose, or may not generalise.
- Fix patterns and templates (overview #5, section 1.5.2). These may bear on the playbook and on L1 rather than on merging.
- Data-flow analysis foundations and scalar optimisation (overviews #4 and #8). The formal account of how transformations enable and disable each other may explain the archive's sub-additivity (L6).
- Instruction scheduling and register allocation as interacting phases (overview #8). Probably not relevant to Python libraries.
- Runtime optimisation (overview #8, chapter 14). Probably not relevant to merging; it may bear on L10.
