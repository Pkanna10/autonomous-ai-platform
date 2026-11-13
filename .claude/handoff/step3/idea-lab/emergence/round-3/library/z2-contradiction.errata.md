# z2-contradiction errata (full-text check, 2026-11-13)

Step 1 classification of the filed notes: none of the 15 sources was read in full. [1], [2], [3], [7] and [8] were catalogue records only; [4], [5], [6], [9]-[15] were search summaries only. Not accessed at all: the Martin study guide for [6], Mann (2008) in [5], and Penn State STAT 509 in [13].

All files are under `library/sources/z2-contradiction/`. Downloads went through the session proxy with plain `curl -sSL`. Refusals were not worked around.

## Sources
| # | citation (short) | status: full text / open substitute / unverified | file under sources/z2-contradiction/ or why none |
|---|---|---|---|
| 1 | Altshuller, *The Innovation Algorithm* (1999) | open substitute (partial) | `1-triz-wiki-substitute.html` (Wikipedia "TRIZ"). The book is commercial, with no open copy. |
| 2 | Altshuller, *40 Principles* (1997) | open substitute (partial) | `5-rea2001-part1-metodolog.html`, `5-rea2001-part2-metodolog.html` (Altshuller's 40 principles listed by number) and `1-triz-wiki-substitute.html`. The book is commercial. |
| 3 | Savransky, *Engineering of Creativity* (2000) | unverified | CRC Press, commercial, with no open copy. Only its bibliographic data is confirmed, by Rea's endnotes. |
| 4 | Haines-Gadd, *TRIZ For Dummies* (2016), App. D; Lean Methods page | unverified | oreilly.com answered 403 (Access Denied), and wiley.com answered 403. leanmethods.com timed out twice (60 s and 90 s). |
| 5 | Rea, "TRIZ and Software: 40 Principle Analogies", Parts 1-2 (2001); Mann (2008) | full text (Rea); unverified (Mann) | `5-rea2001-part1-metodolog.html` (archives/2001/09/e), `5-rea2001-part2-metodolog.html` (archives/2001/11/e). These are the free TRIZ Journal archive on metodolog.ru, not a paywalled copy. The Mann PDF at aitriz.org answered 403 (Cloudflare). |
| 6 | Goldratt, *What Is This Thing Called TOC* (1990) | open substitute | `15-evaporating-cloud.html`, which reports Goldratt 1990 pp. 43-51 for the batch case, and `8-tp-wiki-substitute.html` for the ISBN. maaw.info (the Martin guide) returned a provider error page. |
| 7 | Goldratt, *It's Not Luck* (1994) | unverified | Commercial, with no open copy. The ISBN is confirmed by both Wikipedia pages. |
| 8 | Dettmer, *Goldratt's TOC* (1997) | unverified | Commercial, and no open page names this book. `8-tp-wiki-substitute.html` lists only Dettmer 2003 and 2007. |
| 9 | Mason (1969), *Management Science* | unverified | Closed: Semantic Scholar and OpenAlex both say closed, and pubsonline.informs.org answered 403. The publisher elides the abstract in S2. |
| 10 | Cosier and Aplin (1980), *SMJ* | unverified (abstract only) | `10-cosier-aplin-repec-abstract.html` (RePEc abstract). The full text is closed (S2 and OpenAlex). |
| 11 | Ilevbare, Probert and Phaal (2013), *Technovation* | unverified | Closed. OpenAlex lists a submitted version at publications.eng.cam.ac.uk, but that host does not resolve. The abstract is elided in S2. |
| 12 | Wald (1945), *Ann. Math. Stat.* | open substitute | `12-sprt-wiki-substitute.html` (Wikipedia "Sequential probability ratio test"). The open Project Euclid PDF returned an Incapsula bot block, so it was not retried. S2 has no record of the DOI. |
| 13 | Pocock (1977), *Biometrika* | open substitute | `13-pocock-boundary-wiki.html`. The paper is closed (S2 and OpenAlex). online.stat.psu.edu failed TLS verification through the proxy, so it was not accessed. |
| 14 | Johari, Koomen, Pekelis and Walsh (2017), KDD | open substitute | `14-johari-pekelis-walsh-arxiv1512.04922v3.pdf`, a companion paper and not the KDD text; see the correction below. dl.acm.org answered 403. |
| 15 | "Evaporating cloud", Wikipedia | full text | `15-evaporating-cloud.html` (oldid 1346671759). |

## Corrections
- [1] Core sources 1, "first published in 1973" -> not found in any open source I could reach. Unverified.
- [1] Sources, "1999, Technical Innovation Center, ISBN 0-9640740-4-4" -> confirmed. Wikipedia "TRIZ" (Further reading) gives 1999, Worcester MA, ISBN 978-0-9640740-4-0, the same number. Rea's endnote dates his copy "July 2000", probably a later printing. The translators (Shulyak and Rodman) are unverified.
- [1][2] Notes, "technical contradiction: improving one parameter worsens another ... 40 principles and the contradiction matrix" -> confirmed. Wikipedia "TRIZ" (History and Basic principles) says Altshuller "developed a set of 40 inventive principles and, later, a matrix of contradictions". "Physical contradiction" and the separation principles do not appear in the substitute, so they remain unverified.
- [2] Notes, the principle numbers 1 segmentation, 2 taking out, 3 local quality, 7 nested doll, 9 prior counteraction, 10 prior action, 11 cushion in advance -> confirmed as Altshuller's numbering. Rea Part 1 lists 1 Segmentation, 2 Extraction, 3 Local Quality, 7 Nesting (Matrioshka), 9 Prior counteraction, 10 Prior action and 11 Cushion in advance. Which of them Dummies assigns to time or to space is still unverified ([4]). The ISBN 0-9640740-3-6 is unverified; Wikipedia lists only the 2005 Extended Edition.
- [3] Sources, "CRC Press, 2000, ISBN 0-8493-2255-3" -> confirmed by Rea Part 1, Endnotes. The content claims stay unverified.
- [5] Notes, "Rea maps all 40 principles onto software constructs", Parts 1 and 2 (Sept. and Nov. 2001) -> confirmed. Part 1 gives principles 1-20 (Sept. 2001), and Part 2 "the remaining 21 - 40" (Part 2, intro, at archives/2001/11). Rea himself calls the analogies "works in progress ... from my perspective" (Part 1, intro), so "the standard TRIZ-for-software reference" is my assessment, not his claim. "Later extended by Fulbright (2004)" is not in either text and is unverified.
- [5] L2 and C3, "principle 1, segmentation [2][5]" as the basis for splitting a cut reply into complete parts -> consistent with Rea Part 1, principle 1a and 1b ("Divide a system into autonomous components"; "self-contained program elements (modules)"). That the analogy fits C3 is my inference.
- [5] Notes, Mann (2008): "software contradictions cluster at interfaces" -> unverified (403).
- [6] Notes, the batch conflict "small batches lower inventory and lead time" -> the source frames need C as "reduce carrying cost per unit" and the objective A as "reduce cost per unit" (Wikipedia EC, Applications, citing Goldratt 1990 p. 43). Lead time is not mentioned.
- [6] Notes, "first invalid assumption: setup cost is fixed" -> confirmed: "setup cost is fixed and it cannot be reduced" (Goldratt 1990 pp. 48-50, via Wikipedia EC). The same arrow carries a second assumption that the notes omit: "the machine being set up is a bottleneck with no spare capacity". The injection "setup time can be cut" is not stated in the substitute and is unverified.
- [6] Notes, "batch has one meaning ... the process batch (between setups) and the transfer batch (between stations)" -> confirmed (Goldratt 1990 pp. 50-51, via Wikipedia EC). The page says "production batch size (between setups) and transfer batch size (between workstations)".
- [6] Sources, title "What Is This Thing Called Theory of Constraints" -> the full title has a subtitle, "...and how should it be implemented?" (Wikipedia "Thinking processes", ref. 1; the EC page gives "...and how is it implemented?"). North River Press and ISBN 0-88427-166-8 are confirmed.
- [6][7][15] Notes, the EC structure (five boxes A, B, C, D, D'; B and C needed for A; D serves B and D' serves C; each arrow rests on an assumption; also called the conflict resolution diagram) -> confirmed (Wikipedia EC, lead and "Building a cloud"). "These are the origin texts" is not stated on the page and is unverified.
- [7] Sources, ISBN 0-88427-115-3 -> confirmed (both Wikipedia pages). The content is unverified.
- [10] Notes, "32 United Way planners randomly assigned to conditions; DI reports inferior" -> confirmed at the abstract level only. The RePEc abstract says "Thirty-two organizational planners from the United Way of America were randomly assigned to a DIS and three other planning conditions" and that DIS report quality was "in general ... inferior". The full text was not read. The 1986 AMJ and 1989 studies are uncited and unverified.
- [10][11][9] Sources, bibliographic details -> confirmed from OpenAlex metadata: SMJ 1(4) 343-356; Technovation 33(2-3) 30-37; Management Science 15(8). Mason's page range B403-B414 is unconfirmed, because OpenAlex's page fields are malformed.
- [12] Notes, "Wald's SPRT [12]: among sequential tests with given error rates, it minimises the expected sample size" -> misattributed. The optimality was "later proven ... by Wald and Jacob Wolfowitz", in Wald and Wolfowitz (1948), "Optimum Character of the Sequential Probability Ratio Test", *Ann. Math. Stat.* 19(3) 326-339, doi:10.1214/aoms/1177730197 (Wikipedia SPRT, lead and ref. 2). Wald (1945) introduced the test. The "about half" saving remains unverified. The bibliographic data of [12], 16(2) 117-186, is confirmed.
- [13] Notes, "0.0294 a look with 2 looks and 0.0158 a look with 5, for an overall 0.05" -> confirmed (Wikipedia "Pocock boundary", table; 3 looks give 0.0221 and 4 give 0.0182). The page says "overall p-value for the trial is 0.05" and does not say two-sided, so "two-sided" is unverified.
- [13] Notes, "each extra look must be stricter" -> imprecise. Under Pocock the threshold is the same at every look. It is stricter the more looks are planned, and "the number of interim analyses must be fixed at the start and it is not possible ... to add analyses after the trial has started" (Wikipedia "Pocock boundary", Details). This bears on open question 2: a Pocock correction would need C1's re-look count fixed in advance.
- [13] Sources, "Biometrika 64(2), 191-199 ... from memory, not confirmed" -> now confirmed (Wikipedia ref. 3: 64(2):191-9; S2 and OpenAlex agree on 64(2)).
- [14] Sources, "Preprint: https://arxiv.org/abs/1512.04922" -> wrong. arXiv:1512.04922 is a different paper by three of the four authors, without Koomen: Johari, Pekelis and Walsh, "Always Valid Inference: Bringing Sequential Analysis to A/B Testing" (v1, 15 Dec 2015), retitled in v3 (16 Jul 2019) "Always Valid Inference: Continuous Monitoring of A/B Tests". It is not the KDD '17 paper, which is closed (ACM 403). The KDD pages 1517-1525 are confirmed from OpenAlex.
- [14] Notes, "naive peeking inflates false positives; always-valid p-values hold at any data-dependent stopping time" -> confirmed in the companion paper, but not in [14] itself. Section 1 says "Very high false positive probabilities are obtained ... Type I error can easily increase fivefold" even at 10,000 samples. Section 1, contribution 1, and Definition 1 give p-values that "control Type I error at any data-dependent stopping time". This should be cited as the arXiv paper, not as KDD '17.
- [15] -> confirmed (see the EC structure entry above).

## Claims still unverified
- [1] "First published in 1973"; ARIZ and the physical contradiction as presented in the book itself; the translators' names.
- [2] "It is the canonical list" (this is an assessment); the 1997 ISBN.
- [3] Every content claim, including "widely used for teaching".
- [4] Every claim: the four separation principles as "the common simplification", the six-principle variant, the landing-gear example, the route from technical to physical contradiction, and the whole Appendix D table (time: 1, 7, 9, 10, 11; space: 1, 2, 3).
- [5] Fulbright (2004); Mann (2008) and its "interfaces" claim.
- [6] The injection "setup time can be cut"; "origin texts".
- [7] Content; [8] "the first systematic textbook of the thinking processes".
- [9] Both criteria for a planning technique, and the thesis, counter-plan and synthesis description.
- [10] Anything beyond the abstract; the 1986 AMJ and 1989 studies (no citation).
- [11] The quote "prominent despite its negatives", and complexity and organisational barriers as the named challenges.
- Notes, uncited: the systematic review that calls the TRIZ evidence limited, and the "matrix revised in 2003".
- [12] The "about half of a fixed-sample size" saving.
- [13] "Two-sided"; everything in Pocock (1977) itself, beyond the boundary values reported on Wikipedia.
- [14] The text of the KDD '17 paper itself.

## Overview sources
| # | source (short) | kind: TOC / chapter summaries / syllabus / topic list / reading list | file under sources/z2-contradiction/overview/, or "refused: <code>" |
|---|---|---|---|
| 1 | Savransky, *Engineering of Creativity*, Routledge product page | TOC | `1-savransky-toc.html` |
| 2 | MATRIZ, "Detailed descriptions of the topics required for Levels 1-3" | syllabus | `2-matriz-L1-L3-outlines.pdf` |
| 3 | Ramdas, Grünwald, Vovk and Shafer, "Game-theoretic statistics and safe anytime-valid inference", arXiv:2210.01948 abstract page | topic list | `3-ramdas2022-savi-abs.html` |
| 4 | MIT OCW ESD.33 Systems Engineering (Frey, Summer 2004), calendar | syllabus | `4-ocw-esd33-calendar.html` |
| 5 | triz40.com, "40 TRIZ Principles: List with Examples" | topic list | `5-triz40-principles.html` |
| 6 | Wiley, *TRIZ For Dummies* product page (TOC) | TOC | refused: 403 |
| 7 | ASQ Quality Press, Dettmer, *The Logical Thinking Process* | TOC | refused: 403 |
| 8 | Taylor & Francis, Jennison and Turnbull, *Group Sequential Methods* | TOC | refused: 403 |
| 9 | Penn State STAT 509 (interim analysis lessons); Ramdas's Stanford page (course list) | syllabus | not reached: TLS verification failed through the proxy (not a refusal; not retried) |

The Oxford Creativity home page, the MATRIZ certification page and the TOCICO pages (404) were downloaded or tried, then dropped because they held no topic map.

## Not yet covered
- Cause-effect chain analysis, including vicious circles (overview #2, L1 s3 and L2 s3): a structured root-cause chain for the noise rows L3, L4 and L7 before any separation is chosen.
- Resource analysis (#2, L1 s7; #1, "Substance-Field Resources"): idle resources, such as the quiet VM time at a run's end, are what C1 spends. The topic may sharpen C1's cost case.
- Separation by "relations" and "system level", plus "satisfaction and bypass" as alternatives to separation (#2, L1 s6.2): bypass may fit C2 (avoid the conflict instead of merging through it).
- System operator / 9 screens (#2, L1 s10): super-system, system and sub-system across time. It may frame C4's cross-round backlog.
- ARIZ-85C mini-problem and the ideal final result (#2, L2 s6; #1, "ARIZ"): IFR is in the notes only by name. "The result achieved by itself" frames C3's zero-token salvage.
- Feature transfer between competing systems (#2, L2 s5): it is close to C2's re-port of a keep onto the tip (L5, L8).
- Trimming (#2, L1 s4): removing components while keeping their function. It may be a lane prompt for L1 idea diversity rather than a ledger fix.
- E-processes, test martingales and confidence sequences (#3): anytime-valid evidence that survives optional continuation. This bears directly on C1 and open question 2 (L3, L4, L7), as an alternative to a Pocock correction with fixed looks.
- Nonparametric, composite-hypothesis testing (#3): runtime samples are skewed, which bears on how a fresh look is judged (L3, L7).
- Design of experiments and robust design (#4, lectures 10, 11 and 13): blocking and interleaving against VM state bear on L3, L7 and C5's interleaved block.
- Set-based design and Pugh controlled convergence (#4, lectures 3 and 7): keeping several alternatives alive bears on L1 and L8 (quota-blocked ideas, C4).
- Substance-field models and the standard solutions (#1; #2, L2 s4): probably not relevant.
- Trends of engineering-system evolution and S-curves (#2, L3; #1, "Evolution of Technique"): probably not relevant.
