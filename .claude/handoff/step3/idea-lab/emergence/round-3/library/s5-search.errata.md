# s5-search errata (full-text check, 2026-11-13)

**Method.** Every file below was downloaded with plain `curl -sSL` and read as text with `pdftotext`.
- The notes in `s5-search.md` are unchanged.
- No refusal was worked around. UCL Discovery answered with a Cloudflare challenge page, and `www.cs.ucl.ac.uk` and `www0.cs.ucl.ac.uk` did not resolve, so source 7 has no full text.

**Status before this check:**
- **Read in full:** 1, 2, 4, 5, 6, 10, 11, 13 and 15 (chapter 33).
- **Summary, abstract or snippet only:** 7, 8, 9, 12, 14, 16, 17, 18, 19 and 20.
- **Not accessed:** 3, which the notes knew only second-hand through source 2.

## Sources

| # | citation (short) | status: full text / open substitute / unverified | file under sources/s5-search/ or why none |
| --- | --- | --- | --- |
| 1 | Mouret and Clune 2015, MAP-Elites | full text | `1-map-elites.pdf` (arXiv) |
| 2 | Flageat and Cully 2023, Uncertain QD | full text | `2-uncertain-qd.pdf` (arXiv) |
| 3 | Justesen, Risi and Mouret 2019, adaptive sampling | full text | `3-justesen-adaptive-sampling.pdf` (ITU open copy, via Semantic Scholar `openAccessPdf`) |
| 4 | Whitley, Rana and Heckendorn 1999, island model | full text (the authors' 1998 draft; the journal version's first pages match) | `4-whitley-island.pdf` |
| 5 | Romera-Paredes et al., FunSearch | full text | `5-funsearch.html` (nature.com article page) |
| 6 | Novikov et al. 2025, AlphaEvolve | full text | `6-alphaevolve.pdf` (arXiv) |
| 7 | Langdon and Harman 2015, GISMOE / Bowtie2 | unverified (abstract only) | No open full text reachable. The author's site does not resolve, UCL Discovery serves a bot challenge, and Semantic Scholar does not list the DOI. The abstract was read in the author-maintained GP bibliography. |
| 8 | Petke et al. 2018, GI survey | full text | `8-petke-gi-survey.pdf` (Stirling repository, CC BY) |
| 9 | Blot and Petke 2021, search heuristics for GI | full text | `9-blot-petke-search-heuristics.pdf` (HAL, via Semantic Scholar) |
| 10 | MAGPIE docs, commit b5f0a2e | full text | `10-magpie-docs-b5f0a2e.txt` (`entry_points.md` plus `scenario.md`) |
| 11 | Shypula et al. 2024, PIE | full text | `11-pie.pdf` (arXiv) |
| 12 | Jamieson and Talwalkar 2016 | full text | `12-jamieson-nonstochastic-bai.pdf` (arXiv) |
| 13 | Li et al. 2018, Hyperband | full text | `13-hyperband.pdf` (arXiv; the header reads JMLR 18 (2018) 1-52) |
| 14 | Karnin, Koren and Somekh 2013 | full text | `14-karnin-sh.pdf` (PMLR) |
| 15 | Lattimore and Szepesvári 2020, Bandit Algorithms | full text (the authors' free copy) | `15-lattimore-bandit-algorithms.pdf` |
| 16 | Kaufmann, Cappé and Garivier 2016 | full text | `16-kaufmann-complexity-bai.pdf` (JMLR) |
| 17 | Russo 2016, top-two | full text | `17-russo-top-two.pdf` (arXiv) |
| 18 | Russo et al. 2018, TS tutorial | full text | `18-russo-ts-tutorial.pdf` (arXiv) |
| 19 | Locatelli, Gutzeit and Carpentier 2016, TBP | full text | `19-locatelli-tbp.pdf` (PMLR) |
| 20 | Smith and Winkler 2006, optimizer's curse | full text (the author's own copy) plus the 2007 correction | `20-smith-winkler-optimizers-curse.pdf`, `20-smith-winkler-correction.pdf` (jimsmith.host.dartmouth.edu) |

## Corrections

- **[20] Notes, "The optimizer's curse".**
  - *As written:* the realised value "tends to fall short of its estimate". The remedy is Bayesian shrinkage.
  - *The full text says otherwise in part.* The quotation is not the paper's wording; it came from a search summary. The abstract (p. 311) reads: "we should expect the value of the chosen alternative to be less than its estimate, even if the value estimates are unbiased."
  - *The remedy:* the paper's term is "Bayesian methods to adjust value estimates ... disciplined skepticism", which works by mixing the estimates with a prior. The substance is confirmed.
- **[20] Sources list.**
  - *As written:* the correction revises Figure 3's numbers upward.
  - *Confirmed and made precise.* The 2007 correction says the expected-disappointment numbers in Figure 3 were wrong because of a simulation error. The corrected magnitude is "substantially larger and decreases more slowly as Δ increases".
- **[17] Notes, "Theory".**
  - *As written:* top-two and Thompson variants reach the best possible exponent.
  - *The full text qualifies this (abstract).* The exponent is best possible "among all allocation rules" only when the single tuning parameter "is set optimally or is tuned adaptively toward the optimal value". At 1/2, the exponent is "within a factor of 2 of best possible across all problem instances".
- **[16] Notes, "Theory".**
  - *As written:* stopping rules "with guaranteed error probabilities".
  - *The verbatim text (abstract)* is "improved sequential stopping rules that have guaranteed error probabilities". The meaning is unchanged; only the quoted words change.
- **[12] and [14] Notes, "Successive halving [12, 13]".**
  - *The attribution needs a fix.* Jamieson and Talwalkar adopt "the Successive Halving algorithm of Karnin et al. (2013)" ([12], section 2). Karnin et al. call it "Sequential Halving" ([14], Algorithm 2).
  - So the algorithm originates in [14], and [12] brings it to the non-stochastic setting.
  - The quote "throw out the worst half, and repeat" is from [13], section 3.1. Confirmed.
- **[11] Notes, PIE.**
  - *As written:* "Best@8 is far above Best@1 (6.86x mean speed-up with eight generations)." This gives no Best@1 figure.
  - *The full text adds the comparison.* For the same model, GPT-3.5 with HQ plus self-play, Best@1 is a 3.02x speed-up at 45.50 % optimized, against Best@8 at 6.86x and 87.63 % (Table 4, the row "HQ + Self-Play GPT-3.5"). The direction is confirmed and the gap is about 2.3x.
- **[5] Sources list.**
  - *As written:* "Nature 625:468-475, 2024".
  - *The full text adds a date.* The article page reads "Published: 14 December 2023", and volume 625 is the 2024 issue (AlphaEvolve's reference list cites it as 2023). Both years refer to the same paper; cite it as 2024 (online 14 December 2023).
- **[3] Sources list and Notes.**
  - *As written:* "Not read; described only through [2]".
  - *Now read and confirmed.* A new solution is evaluated until one of three things happens: it lands in an empty cell; it "has been evaluated the same number of times as the corresponding elite and ... has a higher mean performance"; or its mean falls below the elite's. In the last case it stops early.
  - The elite is re-evaluated once per comparison (Algorithm 1, lines 11-13), and a drifting elite is moved.
  - The bibliographic details are confirmed: GECCO '19 Companion, 2 pages.
- **[1] confirmed.** The random-cell mutate-and-replace loop, the "stepping stones" passage and the claim of a better single solution (section 3, Fig. 4 caption).
- **[2] confirmed.** "maintain lucky solutions due to their elitism"; "a majority of lucky sub-performing" solutions; Archive-sampling's re-evaluation, depth D, "second chance" and "rapidly re-evaluated" (sections II-B and V-D). The notes cite the arXiv version only, which is correct.
- **[4] confirmed.** All three quotes, from the draft's introduction and sections 4 and 5.
- **[6] confirmed.**
  - The database "inspired by a combination of the MAP elites algorithm and island-based population models" (section 2.5).
  - The cascade "only if they achieve sufficiently promising results in all earlier stages" (section 2.4).
  - 23 % kernel speed-up and 1 % of Gemini training time (section 3.3.2).
  - "No evolution" in the ablation on two tasks; the paper says "each of the components is responsible for a significant improvement" (section 4, Fig. 8).
- **[8] confirmed.** 1995-2015, and "96% of which use evolutionary algorithms (genetic programming in particular)" (abstract).
- **[9] confirmed.** 18 search processes, 8 scenarios, "local search approaches achieve better effectiveness and efficiency than genetic programming approaches", and 15 % to 68 % (abstract).
- **[10] confirmed.** The `minify_patch` text and the noise caveat (`entry_points.md`); `cache_maxsize` (`scenario.md`).
- **[11] confirmed.** 500 identical pairs, mean 1.12x, sd 0.36, top 5 % at 1.91x, and the "same exact program" sentence (section 2).
- **[12] confirmed.** It assumes only that "νi = lim ℓi,τ exists", with "no information about the rate of convergence" (sections 1-2).
- **[13] confirmed.** Table 1 (R = 81, η = 3) and "n versus B/n" (section 3.1).
- **[15] confirmed.** Theorem 33.10, with H₂(µ) = max over i with Δᵢ > 0 of i/Δᵢ², and the sequential-halving description (section 33.3).
- **[18] confirmed.** Foundations and Trends in Machine Learning 11(1); cited only for general coverage.
- **[19] confirmed.** It finds the arms whose means are above a threshold, at fixed budget, and is proved optimal by matching bounds (abstract and section 1).
- **[5] confirmed.** k = 2 with "diminishing returns beyond that"; "Every 4 h ... m/2 islands"; signature clusters; "four out of 140 experiments"; on the order of 10^6 samples; 15 samplers and 150 CPU evaluators (Methods).

## Claims still unverified

- **[7]:** "70 times faster (on average)" and "at least as good functionally" for Bowtie2 / GISMOE. They are checked against the abstract only, as it appears in the author-maintained GP bibliography entry. No open full text could be reached without working around a refusal.
- **The notes' own arithmetic** comes from no source, and was labelled as such in the notes: the Gaussian two-look model, the 14.7 % failure fit, the per-run sd of about 8.3 from the range, the best-of-k increments and the extra 20 % in measurement minutes. These are inferences and stay unverified until the per-look samples are archived.

## Overview sources

These were used as a map only, and none is cited for a claim. Files are under `sources/s5-search/overview/`.

| # | source (short) | kind: TOC / chapter summaries / syllabus / topic list / reading list | file under sources/s5-search/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | Lattimore and Szepesvári, Bandit Algorithms: contents pages (from the authors' free PDF) | TOC | `1-lattimore-toc.txt` |
| 1r | The same book, publisher front matter (assets.cambridge.org) | TOC | refused: proxy 502 on CONNECT |
| 1s | The same book, banditalgs.com (the authors' site) | TOC | refused: TLS, certificate expired (not bypassed) |
| 2 | Quality-Diversity optimisation algorithms site (quality-diversity.github.io): papers, about, tutorials | reading list / topic list | `2-qd-papers.html`, `2b-qd-home.html`, `2c-qd-tutorials.html` |
| 3 | Genetic Improvement of Software community site, with its Living Survey | topic list / reading list | `3-gi-site.html`, `3b-gi-living-survey.html` |
| 4 | UW CSE 541, Interactive Learning, Spring 2024 (Jamieson) | syllabus | `4-uw-cse541-24sp.html` |
| 5 | Hutter, Kotthoff and Vanschoren (eds.), AutoML: Methods, Systems, Challenges (automl.org/book) | TOC | `5-automl-book.html` |
| 6 | Eiben and Smith, Introduction to Evolutionary Computing, 2nd ed. (Springer book page) | TOC | `6-eiben-smith-springer.html` |
| 6r | The same book's companion site, evolutionarycomputation.org | chapter slides / reading list | refused: redirect loop (more than 50 redirects) |
| 7r | Luke, Essentials of Metaheuristics (cs.gmu.edu) | TOC | refused: TLS, issuer not verifiable (not bypassed) |

## Not yet covered

- **Non-stationary bandits** (from overview 1, ch. 31). Floors fall with time since the job started, which breaks the iid arms my notes assume. This bears on L3, L4 and L7.
- **Combinatorial bandits** (overview 1, ch. 30). Choosing a set, not one arm, fits the portfolio's pick of ideas (L1) and the combine's subset of keeps (L5, L6).
- **Linear and structured bandits, and optimal experimental design** (overview 1, Part V; overview 4, lectures 7-12). Shared features (lane, function, technique) would let one trial inform the ranking of untrialled ideas (L1).
- **Contextual bandits** (overview 1, ch. 18; overview 4, lectures 13-18). Picking a lane or technique given a library's profile, carried across runs, bears on L1 and L8 and on the L7 lessons store.
- **Lower bounds for best-arm and pure exploration** (overview 1, Part IV and ch. 33; overview 4, lecture 4). They give the least number of re-measures any correct engine needs, a candidate floor for L3 and L4.
- **Nonstationary and noisy function optimisation in evolutionary computation** (overview 6, the chapter of that name). The resampling and averaging practice in EAs bears on L3 and L4.
- **Multi-fidelity and Bayesian optimisation beyond Hyperband** (overview 5, ch. 1). Cheap early looks spend more of the budget on ideas, which bears on L1 and L3.
- **Meta-learning and warm-starting across tasks** (overview 5, ch. 2). Transfer between runs and libraries is the theory behind seed (c) and the lessons store, which bears on L8 and L9.
- **Surrogate-assisted QD** (overview 2, papers list). A model that predicts a trial's gain before spending on it bears on L1.
- **Archive geometry: CVT-MAP-Elites and CMA-ME** (overview 2, papers list). How to define cells in a large descriptor space bears on the design of the seed (c) archive.
- **Memetic algorithms, global plus local search** (overview 6). Idea generation followed by local refinement of a keep bears on L8.
- **LLM-driven GI agents, for example GI-Agent and ShinkaEvolve** (overview 3, Living Survey 2026). These are the systems nearest the engine, for comparison on L1 and L8.
- **Benchmarks for improving non-functional properties**, Blot and Petke's survey in ACM CSUR (overview 3, Living Survey). Measurement practice in GI bears on L3 and L9.
- **Multi-objective EAs and multi-objective QD** (overview 6; overview 2, MOME). The objective is runtime plus peak memory, so the bearing is minor.
- **Coevolutionary systems** (overview 6): probably not relevant.
