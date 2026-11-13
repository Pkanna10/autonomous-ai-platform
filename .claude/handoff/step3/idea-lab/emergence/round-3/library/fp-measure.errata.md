# fp-measure errata (full-text check, 2026-11-13)

When the notes were written, all 15 sources had been read only through search extracts or abstracts, or not at all. None had been read in full. This file records the check against open full texts, made with `curl` through the session proxy. Files are under `library/sources/fp-measure/`. The archive computations marked [computed] in the notes are not affected.

## Sources
| # | citation (short) | status: full text / open substitute / unverified | file under sources/fp-measure/ or why none |
| --- | --- | --- | --- |
| 1 | JCGM 100:2008 (GUM) | full text | `1-gum.pdf` (BIPM), `1-gum.txt`, `1-gum-raw.txt` |
| 2 | Taylor & Kuyatt, NIST TN 1297 (1994) | full text (NIST web edition, sections 3-6 and contents; the legacy PDF URL returned 404) | `2-tn1297.html`, `2-tn1297-nist-tn-1297-{3,4,5,6}-*.html` |
| 3 | Kalibera & Jones, ISMM 2013 | full text (Kent repository author copy) | `3-kalibera-jones.pdf`, `.txt` |
| 4 | Georges, Buytaert & Eeckhout, OOPSLA 2007 | full text (co-author Buytaert's own copy, 20 pages) | `4-georges.pdf`, `.txt`, `4-georges-raw.txt` |
| 5 | Mytkowicz et al., ASPLOS 2009 | unverified beyond the abstract: ACM DL answered 403; Semantic Scholar lists no open PDF; the authors' page has the abstract only | `5-mytkowicz-page.html` (abstract) |
| 6 | Chen & Revels 2016, arXiv:1608.04295 | full text | `6-chen-revels.pdf`, `.txt`, `6-raw.txt` |
| 7 | Laaber, Scheuner & Leitner, EMSE 2019 | full text (Chalmers repository copy) | `7-laaber.pdf`, `.txt`, `7-raw.txt` |
| 8 | van Belle, *Statistical Rules of Thumb* (Lehr's rule) | open substitute: a commercial book with no open full text; vanbelle.org does not resolve; the Columbia page answered 403. Substitute: RPubs notes summarising the book, which say they are "taken verbatim" | `8-rpubs-vanbelle.html` |
| 9 | Zhou, Lu & Shallah, CIKM 2023, arXiv:2305.16459 | full text | `9-zhou-sample-size.pdf`, `.txt`, `9-raw.txt` |
| 10 | Ioannidis, *Epidemiology* 2008 | unverified beyond the abstract: the publisher (LWW) answered 403; PubMed served a bot check; abstract taken from the Europe PMC API | `10-ioannidis-europepmc.json` |
| 11 | Efron, JASA 2011 | full text (PMC author manuscript, HTML; the PMC PDF link served a bot check) | `11-efron-pmc.html` |
| 12 | Skol et al., *Nature Genetics* 2006 | unverified beyond the abstract: closed access; nature.com did not serve a PDF; abstract from Europe PMC and the Abecasis lab page | `12-skol-europepmc.json`, `12-skol-umich.html` |
| 13 | Harter 1960, d2 constants | open substitute: Project Euclid served a bot check (Incapsula), not worked around. Substitute: Minitab's d2 table, which cites Harter | `13-minitab-d2.html` |
| 14 | Jennison & Turnbull 1999 | unverified: a commercial book, no open full text; not accessed | none |
| 15 | Mahajan, *Street-Fighting Mathematics* | open substitute: the 2008 MIT OCW draft (table of contents and chapter 1). The OAPEN copy of the 2010 book answered 429 | `15-mahajan-ocw-toc.pdf`, `15-mahajan-ocw-reading1.pdf`, `.txt` |

Totals: 8 full text, 3 open substitutes, 4 unverified.

## Corrections
- [1] Notes s3, "about 35 % at n = 5 ... unverified against [1]" -> GUM E.4.3 gives the relative sd of s as about [2(n−1)]^(−1/2). Table E.1 gives **36 %** at n = 5 and 24 % at n = 10. The value changes from about 35 % to 36 %, and the claim is now verified.
- [1] Notes s2, Type A uncertainty of a mean = s/√n -> confirmed (4.2.3, Eq. 5).
- [1] Notes s3, GUM 4.2.4 prefers a pooled sd for a process under statistical control -> confirmed (4.2.4: "estimated better by s_p²/n than by s²(q_k)/n").
- [1] Notes s1, root-sum-of-squares propagation -> confirmed (5.1.2). The warning about correlated observations -> confirmed (4.2.7). k = 2 giving about 95 % -> confirmed (6.3.3).
- [2] Type A/B, combined and expanded uncertainty -> confirmed (sections 3 to 6). Section 5 names the method the "root-sum-of-squares" or RSS method; section 6 gives k = 2 for about 95 % and k = 3 for more than 99 %.
- [3] Repetition at several levels with a cost model, and effect-size confidence intervals -> confirmed. Section 9.3, Eq. 3: r_i = ⌈√(c_{i+1}·T²_i / (c_i·T²_{i+1}))⌉. The intervals use Fieller's method. My line "when between-VM variance dominates, extra runs inside one VM buy little" is an inference. It is consistent with the text ("no need to repeat at a level if the variation introduced by that level is small"; "the confidence interval uses only the variance estimate at the highest level"), but the paper does not state it in those words.
- [4] Notes, "a worked case where best-of-30 reverses the verdict" -> more precisely, Figure 1 (db, 120 MB heap) misleads in both directions:
  - the best-of method shows CopyMS and GenCopy as about the same, while the rigorous method shows that "GenCopy significantly outperforms CopyMS";
  - best-of says SemiSpace "clearly outperforms" GenCopy, while their confidence intervals overlap.
- [5] The 133-paper survey ("none of the papers with experimental results adequately consider measurement bias") and the two methods (causal analysis, setup randomisation) -> confirmed from the authors' abstract. Environment size and link order as the studied sources -> still unverified (not in the abstract).
- [6] "Noise modelled as additive delays, so a minimum-type estimator is robust" -> confirmed, with two qualifications from the full text:
  - The errors are always positive only "in the limit where the delay factor time scales are greater than τ_acc", the timer accuracy.
  - The minimum is preferred because its distribution across trials is unimodal, while the median and trimmed mean "still capture bimodality".

  The method is built to pick the number of executions per timing measurement for microbenchmarks, so applying it to whole-library 5-run means is my extension. Use in production CI through BenchmarkTools -> confirmed.
- [7] CoV "0.03 % to > 100 %" -> confirmed; the text gives a maximum of 100.68 %. Same instances in randomised order detecting "slowdowns of 10 % or less with high confidence" with Wilcoxon rank-sum and overlapping bootstrapped intervals -> confirmed.
- [8] n = 16/Δ², with Δ the standardised difference and a numerator of 8 for one sample -> confirmed in the substitute. The substitute does not state α and power for this formula; two-sided α = 0.05 and 80 % power are confirmed by [9] instead.
- [9] "α = 0.05 and 1 − β = 0.8 leads to n ≈ 16σ²/δ², a widely adopted rule of thumb", citing Kohavi & Longbotham 2007 and Kohavi et al. 2009 (its refs 23 and 24) -> confirmed. The test is two-sided.
- [10] Inflation of effects first discovered by crossing a significance threshold in underpowered studies -> confirmed from the abstract. The abstract adds that discovered effects can also be deflated, for example after late discovery in sequential, overpowered evidence.
- [11] Notes s6, "Efron's empirical Bayes ... I used its nonparametric form: a grid prior fitted by EM" -> **correction**. Efron's paper is about Tweedie's formula, first reported by Robbins in 1956, which corrects selection bias using the marginal density and its derivative. My fit is a different empirical-Bayes method: nonparametric maximum-likelihood deconvolution, a grid prior fitted by EM. It addresses the same selection-bias problem, but it is not "its nonparametric form". Efron's framing of selection bias as "regression to the mean" among the largest z_i -> confirmed.
- [12] Joint analysis "almost always results in increased power ... despite the need to use more stringent significance levels" -> confirmed from the abstract.
- [13] d2(16) = 3.532 -> confirmed. The citation is now complete: Harter, H. L. (1960), "Tables of Range and Studentized Range", *Annals of Mathematical Statistics* 31(4), 1122-1147, as cited by Minitab.
- [15] Notes s1, "Fermi-style estimation [15] uses the same decomposition" -> **not supported by [15]**. The 2008 draft's chapters are Dimensions, Extreme cases, Discretization, Picture proofs, Taking out the big part, Analogy and Operators; it has no divide-and-conquer chapter. Divide and conquer appears in Mahajan's 6.055J course description, which is an overview, not evidence. Withdraw [15] as the source for that sentence; the GUM budget [1] alone carries it.

Corrections: 6, to [1], [4], [6], [11], [13] and [15]. The rest are confirmed.

## Claims still unverified
- [5] Environment size and link order as the two sources of bias studied: no open full text.
- [10] Anything beyond the abstract, including the table that uses the term "winner's curse": publisher 403.
- [12] Anything beyond the abstract, including the thresholds and the corrigendum to Table 1: closed access.
- [14] Group-sequential designs: cited only for the class of design; not accessed.
- [8] The book's own wording: substitute only.
- [6] Whether the minimum estimator suits multi-second whole-library runs; the paper targets microbenchmarks.

## Overview sources
| # | source (short) | kind: TOC / chapter summaries / syllabus / topic list / reading list | file under sources/fp-measure/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | NIST/SEMATECH e-Handbook, ch. 2, Measurement Process Characterization | TOC | `overview/1-nist-handbook-mpc.html` |
| 2 | BIPM JCGM publications (the GUM suite: JCGM 100, 101, 102, 106, GUM-1, GUM-5, GUM-6, VIM) | topic list | `overview/2-jcgm-publications.html` |
| 3 | MIT OCW 18.098 Street-Fighting Mathematics (Mahajan, 2008) | syllabus | `overview/3-ocw-18098-syllabus.html` |
| 4 | MIT OCW 6.055J The Art of Approximation in Science and Engineering (Mahajan, 2008) | topic list (course description) | `overview/4-ocw-6055j-art-of-approx.html` |
| 5 | MIT OCW 6.172 Performance Engineering of Software Systems (2018), lecture list | topic list | `overview/5-ocw-6172-lectures.html` |
| 6 | Kohavi, Tang & Xu, *Trustworthy Online Controlled Experiments* (Cambridge) | TOC (partial, as extracted) | `overview/6-cambridge-kohavi.html` |
| - | Montgomery, *Introduction to Statistical Quality Control* (Wiley) | TOC | refused: 403 (Cloudflare check) |
| - | Jennison & Turnbull (Routledge product page) | TOC | not found: 404 (not a refusal) |

## Not yet covered
- Gauge R&R, repeatability against reproducibility (overview #1): it splits within-VM from between-VM variance, which is the variance component L9 and L3 need.
- Check standards and measurement-process control charts (overview #1): a fixed A/A probe tracked across runs would flag a noisy VM before trials (L3, L7).
- Uncorrected bias (overview #1): systematic offsets between worktree and base, such as layout effects, that more runs cannot remove (L3, L4).
- Error budget as a named procedure (overview #1): the formal form of the ledger's floor column.
- Monte Carlo propagation of distributions, JCGM 101 (overview #2): floors for heavy-tailed, spiky noise where the normal approximations in my L3/L4 fits are weakest.
- Conformity assessment and guard bands, JCGM 106 (overview #2): the keep/reject rule framed as specific false-accept and false-reject risks; directly the L3/L4 threshold choice.
- Developing measurement models, GUM-6 (overview #2): probably not relevant.
- Divide and conquer, successive approximation (overview #4): the method behind breaking a cost into atoms; replaces the withdrawn [15] citation once a full text is read.
- Measurement and Timing lecture (overview #5): timers, frequency scaling, quiescing the machine; bears on the settle-step proposal (`floors/README.md` fix B).
- Choosing a randomization unit (overview #6): which unit is paired in ABBA, and what is independent (L3, L4).
- Institutional memory and meta-analysis (overview #6): pooling verdicts across runs, which bears on L8 and a proven-patch archive (seed c).
- Scaling experiment analyses (overview #6): probably not relevant at this engine's volume.

Note on the sealed set: I have never opened `services/python_agents/tests/fixtures/upstream_corpus/` or any commit it names.
