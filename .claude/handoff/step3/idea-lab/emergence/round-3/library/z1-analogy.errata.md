# z1-analogy errata (full-text check, 2026-11-13)

Method: `curl -sSL` through the session proxy, `pdftotext` for the PDFs, and plain tag-stripping for the HTML and XML. My text extracts are under `scratchpad/r3/work/z1-analogy/txt/`.
- **Refusals were not worked around:** Sage returned 403, deepblue 403, pressbooks 403, PMC a reCAPTCHA page, and the GitHub wiki 403.
- **One TLS failure was not bypassed:** cs.cornell.edu failed certificate verification.
- **Europe PMC's REST full-text endpoint** was used only for open-access articles.

## Sources

| # | Citation (short) | Status | File under `sources/z1-analogy/`, or why none |
|---|---|---|---|
| 1 | Gentner 1983, Cogn. Sci. | full text | `1-gentner1983.pdf` |
| 2 | Holyoak and Thagard 1995, *Mental Leaps* | open substitute (chapter 3 and front matter only, open course copy, Waterloo CS886) | `2-mentalleaps-ch3.pdf` |
| 3 | Gick and Holyoak 1980, Cogn. Psych. | unverified | deepblue 403, pressbooks summary 403, Semantic Scholar rate-limited (429); no open copy found |
| 4 | Fu et al. 2013, JMD | unverified | the author URL from my notes now returns 404; Semantic Scholar lists DOI 10.1115/1.4023158 as CLOSED |
| 5 | Altshuller, *40 Principles* | open substitute (commercial book) | `5-substitute-wikipedia-triz.html` |
| 6 | Skol et al. 2006, Nat. Genet. | open substitute (Semantic Scholar CLOSED, not open access in Europe PMC) | `6-substitute-sha2011.xml` (Sha, Zhang and Zhang 2011, PLoS ONE, PMC3142116, which restates Skol's result) |
| 7 | Zhang, Chung and Oldenburg 1999, JBS | open substitute (Sage PDF 403) | `7-substitute-wikipedia-zfactor.html` (its table is "a modification of Table 1 shown in Zhang et al. (1999)") |
| 8 | Brideau et al. 2003, JBS | open substitute (Sage PDF 403) | `8-substitute-pmc6015058.xml` (Shterev et al. 2018, Sci. Rep., which describes the B-score) |
| 9 | Malo et al. 2006, Nat. Biotech. | unverified | Semantic Scholar CLOSED, not open access in Europe PMC, PMC returned a reCAPTCHA page |
| 10 | Padioleau et al. 2008, EuroSys | full text | `10-padioleau2008.pdf` |
| 11 | Ellis and Gibbs 1989, SIGMOD | full text (course reading copy, UCSC CSE290S) | `11-ellis1989.pdf` |
| 12 | Kulkarni et al. 2006, CGO | open substitute: the same authors' extended TACO 2009 version, from the author's site | `12-substitute-kulkarni-taco09.pdf`, `12-kulkarni-page.html`; no open CGO 2006 PDF found |
| 13 | Tate et al. 2009/2011, equality saturation | full text (LMCS 7(1:10) 2011 version, arXiv 1012.1802) | `13-eqsat.pdf` |
| 14 | Caruana et al. 2004, ICML | unverified beyond the abstract | `14-caruana-abstract.html`; the author copy at cs.cornell.edu failed TLS verification (not bypassed); the icml.cc paper PDF returned 404; Semantic Scholar CLOSED |
| 15 | Good 1953, Biometrika | open substitute (Semantic Scholar CLOSED) | `15-substitute-wikipedia-goodturing.html`; the UPenn course page returned 403 |
| 16 | Zöllner and Pritchard 2007, AJHG | full text (PMC HTML) | `16-zollner2007.html` |
| 17 | Breyfogle 2003, *Implementing Six Sigma* | open substitute, partial (commercial book) | `17-substitute-wikipedia-rty.html` |
| 18 | RFC 7464 (Williams 2015) | full text | `18-rfc7464.txt` |
| 19 | diff-match-patch (Fraser) | full text (the library's own README and Python source, from the GitHub repo) | `19-diffmatchpatch-readme.md`, `19-diffmatchpatch.py`; the wiki API page returned 403 |

**Totals:** 7 full text, 8 open substitute, 4 unverified.

## Corrections

**[1] Gentner 1983**
- **Core sources, "the Structure-Mapping Engine implements it":** the 1983 paper does not mention SME (0 occurrences). The claim came from a QRG web page and is not supported by [1]. Drop it, or cite SME's own paper.
- **Notes, "relations, not attributes; systematicity":** confirmed (abstract, p. 155: "Relations between objects, rather than attributes of objects, are mapped... determined by systematicity, as defined by the existence of higher-order relations").
- **Sources, "*Cognitive Science* 7(2)":** the PDF header reads "COGNITIVE SCIENCE 7, 155-170 (1983)". The issue number is not shown, so "(2)" is unverified. Cite it as 7, 155-170.

**[2] Holyoak and Thagard 1995**
- **Notes, "three constraints: similarity, structure and purpose":** confirmed (ch. 3, "the basic constraints postulated by our multiconstraint theory of analogy - similarity, structure, and purpose").
- **ISBNs 0-262-08233-0 (HB) and 0-262-58144-2 (PB):** confirmed (copyright page).

**[3] Gick and Holyoak 1980**
- **Notes, "about 10 % unaided, 30 % after the story, 75-92 % with a hint":** still unverified. No open text was reached, and the notes already mark these figures as secondary.

**[4] Fu et al. 2013**
- **Sources:** add DOI 10.1115/1.4023158. Semantic Scholar dates it 2012, presumably the online date.
- **The sweet-spot claim and the "earlier study leaned far" claim:** unverified (no open text).

**[5] Altshuller (via the substitute)**
- **Notes, "TRIZ claims that problems and their solutions repeat across industries":** confirmed by the substitute ("Problems and solutions are repeated across industries and sciences").
- **"40 principles abstracted from patents":** confirmed by the substitute ("Altshuller screened patents... developed a set of 40 inventive principles").

**[6] Skol et al. 2006 (via the substitute)**
- **Notes, the core claim "a joint test over both stages has more power than replication-based analysis":** confirmed by the substitute (Sha et al. 2011: joint analysis "is more powerful than replication-based analysis in which the test used in the second stage is based on the second sample only").
- **The qualifiers "almost always", "its threshold must be stricter" and "even when effect sizes differ between stages":** downgrade these to unverified. They came from abstract-level search text, and the substitute does not state them.
- My own power table in "Bearing on the ledger, L4" stands as my computation. It uses the same joint-statistic construction the substitute attributes to Skol's equation (2).

**[7] Zhang et al. 1999 (via the substitute)**
- **Notes, the Z' bands "0.5 to 1 excellent, 0 to 0.5 marginal, below 0 unusable":** confirmed (1.0 > Z ≥ 0.5 excellent; 0.5 > Z > 0 marginal; < 0 "screening essentially impossible"). Z' = 1 − 3(σp + σn)/|μp − μn| is defined on the controls alone, "a characteristic parameter of the assay itself".
- **An addition the substitute supports:** the field also uses a "Robust Z-prime", with the median and the MAD in place of the mean and sd. That bears on `floors/README.md` fix C.

**[8] Brideau et al. 2003 (via the substitute)**
- **Notes, "Hits are called relative to the plate's own controls, with spatial row and column effects removed (the B-score, median polish)":** this is wrong about the controls. The substitute says: "The B-score, R-score and Z-score do not use controls in the normalization process, while the NPI makes use of both positive and negative controls." The B-score is the median-polish residual over a plate's rows and columns divided by that plate's MAD.
- **Corrected sentence:** "Hits are called per plate, relative to the plate's own sample distribution with its row and column effects removed (B-score [8]). Control-based normalisation (NPI) is a separate method."

**[7] and [9], HTS practice**
- **Notes, "a plate's quality decides whether it is re-run, whatever its hits show; a failed plate is re-run, its compounds are not marked inactive":** found in no text I could open. Downgrade it to unverified practice.
- **M2's source therefore rests only on:**
  - the verified Z' definition, which measures assay quality from controls without samples;
  - the analogy.
- The mechanism itself (a verdict-blind re-look triggered on the floor) is unchanged. Its claimed provenance in HTS re-run practice is unverified.

**[9] Malo et al. 2006**
- **Notes, every claim (single measurements, unquantified false negatives, replicates recommended, the false-positive or false-negative uncertainty):** still unverified (no open text).

**[10] Padioleau et al. 2008**
- **Notes, "over 5,800 driver files, over 93 % updated completely, over 150 files where maintainers erred and Coccinelle is correct":** confirmed (abstract, p. 1). The paper also says "over 60" evolutions in its contributions list and 62 in its abstract.

**[11] Ellis and Gibbs 1989**
- **Notes, "OT rewrites one edit against a concurrent edit so that both apply":** confirmed (s4.1: "The transformation matrix is the key to resolving conflicting operations... Each component of T is a function which transforms operations into other operations").
- **First page 399:** confirmed (the copyright line).

**[12] Kulkarni et al. (via the TACO 2009 substitute)**
- **Notes, "exhaustive search over phase orders is feasible per function":** this overstates the result. The text says it is possible "for each function on the ARM-Linux platform in a reasonable amount of time for most of the functions in our benchmark suite", in their compiler back end, after pruning the space.
- **Corrected sentence:** "feasible for most functions, in one back end, after pruning".
- **"Different orders give different code":** confirmed ("phase interaction often causes different orders of applying optimizations phases to produce different output code, with potentially significant performance variation").

**[13] Tate et al.**
- **Notes, every claim (sequential destructive passes; equality analyses that add to a common IR; a profitability heuristic that picks the final program):** confirmed (LMCS abstract and s1).
- **Citation "LMCS 7(1), 2011":** confirmed, as 7(1:10), pp. 1-37.

**[14] Caruana et al. 2004**
- **"Forward stepwise selection... adds the models that maximise its performance":** confirmed (abstract).
- **Notes, "a model is added only if the measured score on a hold-out set improves" and "selection with replacement and bagging reduce overfitting":** downgrade both to unverified. They are not in the abstract; they came from a third-party slide summary.
- **M4:** its "held-out check" is my design choice, not a citation of [14].

**[15] Good 1953 (via the substitute)**
- **Notes, "unseen mass ≈ n1/N, n1 the number of classes seen exactly once":** confirmed by the substitute ("p0 = N1/N"; "N1 is the number of species for which only one individual was observed").
- **The page range 237-264 and the DOI:** not checked against the original.

**[16] Zöllner and Pritchard 2007**
- **Notes, "an estimate from the data that selected a hit is biased upward":** confirmed ("the odds ratio of a disease variant is usually overestimated in the study that first describes the variant"; "This overestimation... may cause replication studies to fail").
- **AJHG 80(4):605-615:** confirmed.

**[17] Breyfogle (via the substitute)**
- **Notes, "RTY multiplies the stages' first-pass yields":** confirmed by the substitute ("the product of yields for each process step").
- **"Hidden factory":** not in the substitute. Downgrade it to unverified.

**[18] RFC 7464**
- **Notes, "its parsers need not fail on an incomplete text":** confirmed (s2.3: parsers "should not abort when an octet string contains a malformed JSON text. Instead... should skip to the next RS").
- **"Survives truncation with only the last record lost":** this is my inference for a stream cut at its end, as at max_tokens. The RFC does not say it, so label it as an inference.

**[19] diff-match-patch**
- **Notes, "Bitap, `Match_Threshold`, `Match_Distance`":** confirmed (`Match_Threshold = 0.5`, "0.0 = perfection, 1.0 = very loose"; `match_bitap`).
- **A caveat to add to M5:** `Match_MaxBits = 32` caps the Bitap pattern length, so a multi-line quote must be matched in chunks or with another approximate matcher.
- **Sources:** replace the jmix URL with the repository, https://github.com/google/diff-match-patch.

**Count:** 12 corrections. They change a claim, a citation or a provenance, or they downgrade a claim:
1. [1] SME;
2. [1] the issue number;
3. [4] the DOI;
4. [6] the qualifiers;
5. [8] the B-score and controls;
6. [7]/[9] the plate re-run rule;
7. [12] "most functions";
8. [14] hold-out and replacement;
9. [17] the hidden factory;
10. [18] the inference label;
11. [19] the MaxBits caveat;
12. [19] the URL.

The remaining claims are confirmed.

## Claims still unverified

- **[3]** Gick and Holyoak's transfer percentages (10 %, 30 %, 75-92 %).
- **[4]** Fu et al.'s near/far sweet spot, and that an earlier study from the same group leaned toward far sources.
- **[6]** Skol's qualifiers: "almost always", the stricter joint threshold, robustness to effect sizes that differ between stages, and the corrigendum to Table 1.
- **[7], [9]:** that HTS practice re-runs a plate that fails QC regardless of its hits. This was M2's claimed provenance.
- **[9]:** every Malo et al. claim.
- **[14]:** the hold-out set, selection with replacement and bagged selection in Caruana et al.
- **[15]:** the page range and the DOI of Good 1953 (the result itself is confirmed by the substitute).
- **[17]:** "hidden factory" as Six Sigma usage.
- **[1]:** the issue number (2).

## Overview sources

These are used as a map only; no claim above or in the notes rests on them.

| # | Source (short) | Kind | File under `sources/z1-analogy/overview/`, or "refused: <code>" |
|---|---|---|---|
| 1 | Stanford Encyclopedia of Philosophy, "Analogy and Analogical Reasoning" (rev. 2019), entry contents | TOC | `1-sep-analogy.html` |
| 2 | NIST/SEMATECH e-Handbook of Statistical Methods, ch. 2 "Measurement Process Characterization" | TOC (chapter topic list) | `2-nist-ehandbook-mpc.html` (the handbook's top-level `toc.htm` redirects (302) to the ITL landing page, so it was not filed) |
| 3 | UCSC CSE290S (Winter 2023), "Distributed Software Systems: Global-First and Local-First" | syllabus and reading list | `3-ucsc-cse290s-crdt.html`, `3b-ucsc-cse290s-schedule.html` |
| 4 | MIT OCW 6.035 Computer Language Engineering (Spring 2010) | syllabus and topic list | `4-mit-6035-syllabus.html` |
| 5 | triz40.com, "40 TRIZ Principles" | topic list | `5-triz40-principles.html` |
| - | NCBI Bookshelf, NCATS *Assay Guidance Manual* TOC (HTS) | TOC | refused: reCAPTCHA bot check |
| - | Stanford CS243 Program Analysis and Optimization course page | syllabus | refused: TLS certificate verification failed (not bypassed) |
| - | Northwestern HTS overview PDF | topic list | refused: TLS alert (internal error) |
| - | MIT OCW 2.009 syllabus (design process) | syllabus | not found: 404 (not a refusal) |

## Not yet covered

- **Check standards** (from overview #2): a stable reference artefact measured in every session to track drift. This maps onto VM drift within and between runs (L3, L9), and my notes did not cover it.
- **Gauge R&R** (#2): splits variance into repeatability (within a run) and reproducibility (between runners). That is the right frame for L9's spread between identical runs.
- **Type A and Type B evaluations, and error budgets** (#2): an error budget is how a floor is built from its parts. It bears on L3 and on the first-principles seats' floor column.
- **Calibration designs, with a catalogue of designs** (#2): the choice of block design (ABBA and others) for measuring differences. It bears on L3 and L4.
- **Hesse's material criteria: positive, negative and neutral analogy** (#1): a checklist for where a transferred mechanism's preconditions fail, for example M1's independence of looks. It is useful for vetting the proposals.
- **Philosophical justification of analogical inference** (#1, s4): probably not relevant to the ledger.
- **CRDTs, Shapiro et al. 2011** (#3): changes designed to commute, so merges never conflict. It bears on L5. I covered OT, not CRDTs.
- **Mergeable replicated data types, Kaki et al. 2019** (#3): a three-way merge defined per data type. It bears on L5's textual conflicts.
- **"Merge what you can, fork what you can't", Schiefer et al. 2022** (#3): keep the conflicting alternatives as forks and measure them separately. It bears on L5 and L6, and fits M4.
- **Content addressability and DHTs** (#3): probably not relevant. Hunk hashing already exists as `hunk_signature`.
- **Data-flow analysis and data-flow optimisations** (#4): an analysis that crosses functions could locate hoisting and set-up costs outside the hot function. It bears on L10.
- **Instruction scheduling and register allocation** (#4): probably not relevant to Python-level edits.
- **TRIZ principle 1, Segmentation** (#5): split one long leap request into independent parts. It bears on L2, alongside the framing in [18].
- **The TRIZ contradiction matrix** (#5): probably for the contradiction seat (z2), not this one.
