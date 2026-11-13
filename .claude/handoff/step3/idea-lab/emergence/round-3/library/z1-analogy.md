# z1-analogy: zero to one through distant-field analogy

**Access note.** Web search worked, but every page I tried to open in full (pubmed, umich, gwern) was blocked. So each source below is cited from its bibliographic record and from abstract-level summaries returned by search, not from the full text, unless stated otherwise. Where a number is mine, it says "my computation". The script is at `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/z1-analogy/twostage.py`.

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **Gentner 1983 [1].** Structure mapping: an analogy maps relations between objects, not the objects' attributes, and it prefers systems of relations tied together by higher-order relations ("systematicity"). It is the founding theory of analogy in cognitive science, and the Structure-Mapping Engine implements it.
2. **Holyoak and Thagard 1995 [2].** The multiconstraint theory: analogy is shaped by three constraints at once, namely similarity, structure and purpose. It is the standard book-length account, and the companion to [1].
3. **Gick and Holyoak 1980 [3].** The classic experiment on transfer, using Duncker's radiation problem and a military story with the same structure. It is the standard evidence that people rarely transfer an analogy without being prompted.
4. **Fu et al. 2013 [4].** The design-by-analogy study of "near" and "far" sources and how far a source should be. It is the most-cited engineering study on analogical distance.
5. **Altshuller 1997/98 [5].** TRIZ's 40 inventive principles, abstracted from patents across many domains. It is the canonical catalogue of cross-domain design patterns.
6. **Skol et al. 2006 [6]** (genetics, two-stage screens). Analysing both stages jointly is more powerful than requiring stage 2 to replicate on its own. It is the standard result for two-stage GWAS.
7. **Zhang, Chung and Oldenburg 1999 [7]; Brideau et al. 2003 [8]; Malo et al. 2006 [9]** (high-throughput screening, HTS). In order: plate-quality control (the Z'-factor), hit calling with per-plate normalisation (the B-score), and a review of false-negative rates and replicates. These are the field's reference papers on how screens lose true hits.
8. **Padioleau et al. 2008 [10]; Ellis and Gibbs 1989 [11]** (version control). Semantic patches (Coccinelle) and operational transformation: re-applying a change by its intent, not by its text. They are the founding works of each line.
9. **Kulkarni et al. 2006 [12]; Tate et al. 2009 [13]; Caruana et al. 2004 [14]** (compilers and ensembles). The order of optimisation phases changes the result; equality saturation avoids destructive ordering; forward selection is measured on a held-out set. These are the standard works on composing transformations.
10. **Good 1953 [15]** (cryptanalysis and ecology). Good-Turing estimation of the probability mass of unseen species. It is the standard estimator of coverage.

## Notes (the methods and results, cited inline as [n])

**How analogy works, and how it fails.**
- Structure mapping says a good analogy carries over a connected system of relations, such as "A causes B, which limits C". It does not carry over surface features [1].
- The multiconstraint theory adds purpose: the mapping that counts is the one that serves the goal at hand [2].
- Spontaneous transfer is weak. Secondary summaries of [3] report about 10 % solving the radiation problem unaided, about 30 % after reading the analogous story, and 75-92 % once told to use the story. The figures vary between summaries, and I could not check the original.
- The lesson for this seat is to search a field by its relational structure on purpose, not to wait for a resemblance to suggest itself.
- **Contested:** how far the source field should be. Fu et al. propose a sweet spot between too near, which invites fixation and copying, and too far [4]. An earlier study from the same group leaned toward far, less common sources [4, cited there]. TRIZ claims that problems and their solutions repeat across industries [5].

**The method used here.** For each ledger row I wrote the row's relational structure, then looked for a field whose standard practice solves that structure.
- An example structure: "a noisy test screens many candidates; a second noisy test must also pass; true positives are lost at the conjunction".
- Each mapping below is checked against the engine's code (file:function).

**Two-stage screens (genetics).**
- In a two-stage GWAS, stage 1 screens all markers and stage 2 retests the most promising ones.
- The standard practice was to treat stage 2 as a replication, significant on its own. Skol et al. show that a joint test over both stages "almost always" has more power, even though its threshold must be stricter, and even when effect sizes differ between stages [6].
- A related caution: an estimate taken from the same data that selected a hit is biased upward (the winner's curse) [16].

**HTS hit triage.**
- Screens measure each compound on a plate, beside positive and negative controls.
- Plate quality is scored by the Z'-factor, a separation-band statistic: 0.5 to 1 is excellent, 0 to 0.5 marginal, below 0 unusable [7] (interpretation bands via GraphPad's summary).
- Hits are called relative to the plate's own controls, with spatial row and column effects removed (the B-score, median polish) [8].
- Malo et al. stress that screens usually measure each compound once, that false negatives go unquantified, and that replicates with robust statistics are needed. They note it is unclear whether screening's inefficiency comes mostly from false positives or from false negatives [9].
- The mechanism that matters here: **a plate's quality decides whether it is re-run, whatever its hits show.** A failed plate is re-run. Its compounds are not marked inactive.

**Merging by intent (version control).**
- Coccinelle's semantic patches express a change as a pattern over the code's structure and re-apply it wherever the pattern matches. Over 5,800 driver files, they updated over 93 % completely, and they were correct in over 150 files where the human maintainers had made errors [10].
- Operational transformation rewrites one edit against a concurrent edit, so that both apply [11].
- In both, a change is carried as its intent and re-derived against the new text. It is not a fixed hunk that either applies or conflicts.

**Composing optimisations (compilers).**
- Applying the same phases in different orders gives different code, and exhaustive search over phase orders is feasible per function [12].
- Equality saturation turns each rewrite into an addition to a shared graph, so no pass destroys another's opportunity. A profitability heuristic then extracts the best program [13].
- Ensemble selection builds a combination by forward stepwise selection. A model is added only if the measured score on a hold-out set improves. Selection with replacement and bagging reduce overfitting [14].
- The shared lesson: **a combination is chosen by measurement, never by assuming that the parts add up.**

**Coverage of the unseen (Good-Turing).**
- From the counts of how often each class has been seen, the share of probability on unseen classes is about n1/N, where n1 is the number of classes seen exactly once [15]. That gives a stopping and reallocation signal for search.

**Manufacturing yield.**
- Rolled throughput yield (RTY) multiplies the first-pass yields of the stages. The rework hidden inside it is called the "hidden factory" [17]; I could not open Breyfogle's own text.

## Bearing on the ledger (per row you touch: L#, what your field says, numbers)

**L1 (ideas that never become trials).**
- Stage yields (my computation from `o62/README.md`):

  | Stage | Ideas | Yield |
  | ----- | ----- | ----- |
  | read | 163 → 126 | 0.773 |
  | s4a | → 113 | 0.897 |
  | s3 | → 88 | 0.779 |
  | s4b | → 53 | 0.602 |

  RTY = 0.325, which is 53 of 163.
- s4b is the worst stage, but it is a quota choice, not a defect.
- The read stage scraps 31 `ungrounded` ideas with no rework station [17]. `_ground` in `optimization/idea_lanes.py` has five sub-reasons, and the fate records only `read:ungrounded` (I checked the 2 O62 files). So the share that is reworkable is unknown.
- Across populations (illustrative only, my computation): 0.325 x keep rate 0.292 (284 of 972 trials) x delivered share 0.65 (115 of 177) ≈ 6 % from idea to delivered keep.

**L2 (truncated leaps).**
- Framing (RFC 7464 [18]): a stream of independently framed records survives truncation with only the last record lost. Its parsers "need not" fail on an incomplete text.
- The engine's `read_reply` (`clients/structured.py`) raises `stopped` on any `stop_reason` other than `end_turn`. So 3 of 32 Opus leaps (9 %) yield zero ideas instead of the ideas completed before the cut.

**L3 (trials lost to noise).**
- In HTS terms, a trial whose floor is above 1.5x the calibrated floor is a failed plate: 175 of 972, 18 %. Today it gets a verdict anyway (inconclusive) [7, 9].
- The share of high floors falls from 27 % at 0-5 minutes to 10 % at 30-60 minutes (`floors/README.md` s4). The analogue is to re-queue failed plates at the end of the run.
- Cost (my computation): 175 / 63 ≈ 2.8 re-looks a run, at the replay's 5.5-13.3 s per re-test with the suite, so under 40 s a run.

**L4 (failed confirmations).** 49 failed second looks against 284 that held, so 14.7 % fail (my computation).
- Skol's result transfers [6]. I modelled each look as z ~ N(δ, 1), with a first-look threshold of 2 and the conjunction "both looks > 2", whose false-positive rate is 5.2e-4.
- A joint test at the same false-positive rate needs mean-z > 3.19 after first-look selection (my computation).
- Power, conjunction against joint:

  | δ | Conjunction | Joint |
  | --- | --- | --- |
  | 2.0 | 0.250 | 0.294 |
  | 2.5 | 0.478 | 0.547 |
  | 3.0 | 0.708 | 0.776 |

- The gain is modest and real. It assumes Gaussian, independent looks, which the floors page says the VM state breaks.

**L5 and L8 (combine conflicts and repeats).**
- In version-control terms, every one of the 62 left-out keeps was lost to a textual conflict.
- 21 of 57 conflicts re-implement a technique already applied: these are duplicates, to be deduplicated, not merged.
- The other 36 are distinct changes blocked only by their text. These are the candidates for intent-level re-application [10, 11].

**L6 (combine below its best part).**
- The compiler and ensemble view [12, 14]: greedy textual order by hypothesis score is not a measured selection.
- Part of L6 may be the winner's curse [16]. The "best single keep" is the maximum of several selected first looks, so it is biased upward. A fair comparison uses re-measured singles.
- The ledger's parenthetical medians (+17.4 delivered against +11.3 best single) read the wrong way round for a row about "below". I flag this for the Lead to check.

**L7 (combine lost to noise).** The plate-QC rule (combine proposal item 1) is the HTS practice already. Its symmetry, which triggers on the floor and never on the verdict, matches the rule that plate QC is blind to the hits [7].

**L8 (diminishing unique keeps).** Unique keeps per raw keep in X2-D (my computation from `zero-credit` s2, x 12 runs):
- round 2: about 10 of 18, 0.56;
- round 3: about 5 of 13, 0.38.

A Good-Turing coverage estimate [15] per run would make that fall visible during the run, as a signal to retarget.

## Mechanisms the engine does not have

**M1. A joint decision over the first and second looks.**
- **Source:** genetics, two-stage GWAS: Skol et al. 2006 [6]; the winner's curse [16].
- **Mapping:**

  | Genetics | Engine |
  | --- | --- |
  | stage 1 | the trial's own look |
  | stage 2 | the confirmation look |
  | replication-based analysis | each look must clear its own floor |
  | joint analysis | one test on both looks, at a stricter threshold set for the same false-positive rate |

  The reported gain stays the second look alone, or the delivery re-test, which is unbiased.
- **Row:** L4 (49 failed second looks), and the part of L3 that reaches confirmation.
- **Why the engine lacks it:** `orchestrator/confirm.py:confirm_one` calls `retest_one` and turns the verdict into inconclusive whenever the second look alone does not hold. The first look's evidence is discarded. `reported_gain` averages the two looks for reporting only.
- **Caveats:**
  - Changing the decision rule touches `derive_verdict`'s use, not the judges. It is the owner's call.
  - The threshold must be derived for the engine's floor statistic, not for a z-test.

**M2. Verdict-blind plate QC for trials, re-queued to the quiet end of the run.**
- **Source:** HTS: Zhang et al. 1999 (Z'-factor) [7]; Brideau et al. 2003 [8]; Malo et al. 2006 [9].
- **Mapping:**

  | HTS | Engine |
  | --- | --- |
  | a plate | one trial's measured look |
  | plate QC | the trial floor against the calibrated floor (> k x) |
  | a failed plate is re-run, not read as negative | a high-floor trial gets one more look at the end of the run, where floors are lowest (10 % above 1.5x at 30-60 min against 27 % at 0-5) |

  The trigger reads only the floor, so a passing trial with a high floor is re-looked too. This is the combine proposal's symmetry, extended to trials.
- **Rows:** L3 (175 of 972 above 1.5x; 47 between the floors) and L7.
- **Why the engine lacks it:** no trial-level re-measure exists. A search for `re-measure` and `remeasure` in `src/` finds nothing. `combine_node.combine_kept` re-tests only via the fallback, and the k = 2 re-measure is a proposal (`combine-proposal.md` s1).
- **Cost:** about 2.8 re-looks a run, under 40 s (L3 above).

**M3. Re-applying a conflicted keep by its intent on the merged tip.**
- **Source:** semantic patches, Padioleau et al. 2008 [10]; operational transformation, Ellis and Gibbs 1989 [11].
- **Mapping:**

  | Version control | Engine |
  | --- | --- |
  | a change carried as intent | a kept hypothesis (title, mechanism, anchor) |
  | a hunk | its trial diff |
  | re-deriving the change against the new text | on a textual conflict, re-implementing the hypothesis on the greedy tip, then judging it as a marginal trial against that tip |

  Repeats (same technique) are excluded first.
- **Rows:**
  - L5: 36 of 57 conflicts are not repeats, of the 62 left out.
  - L8: repeats stop masquerading as conflicts.
- **Why the engine lacks it:** `execution/combine.py:GitCombiner._merge` records a `CombineSkip` with reason `conflict` and moves on. No editor call or rebase path exists; a search for rebase, reapply and resolve-conflict finds nothing.
- **What it costs, and where X2-DT stops:**
  - Each re-application costs an editor request.
  - X2-DT's stacked rounds (`stacked-plan.md`) cover only cross-round conflicts. Conflicts within a round remain.

**M4. Measured forward selection for the combine.**
- **Source:** compilers, phase ordering: Kulkarni et al. 2006 [12]; equality saturation, Tate et al. 2009 [13]; ensemble selection, Caruana et al. 2004 [14].
- **Mapping:** the keeps are the passes. The combine adds keeps one at a time in gain order (re-measured gains, not first looks) and accepts each one only if the tip's measured gain rises by more than the floor. The final delivery re-test stays unchanged, as the held-out check.
- **Row:** L6 (12 of 63 runs below their best single keep).
- **Why the engine lacks it:**
  - `combine_node.combine_kept` merges all keeps in score order (`kept_changes` sorts by `-score`), measures once, and delivers if the set holds.
  - The best single keep is re-tested only when the set fails (`_fallback_candidate`).
  - `SITE_STACKS=on` (`plan_delivery`, default off) picks a max-sum conflict-free subset by summed gains, which assumes additivity.
- **Cost:** at most 7 additions (markdown's 7 keeps) x 13 s ≈ 1.5 min a run.
- **Risk:** many measured subsets bring their own winner's curse [16]. The final re-test against the base guards it.

**M5. A rework station for ungrounded ideas.**
- **Source:** manufacturing, RTY and rework [17]; approximate matching in diff-match-patch (Bitap, `Match_Threshold`) [19].
- **Mapping:**

  | Manufacturing | Engine |
  | --- | --- |
  | a scrapped unit | an idea whose quote does not match the shown code exactly |
  | rework | locating the quote approximately, and accepting the anchor only if the match is unique, above a threshold, on code (not a comment) and in a shown hot function |
  | scrap | everything else stays scrapped |

  No request is made.
- **Row:** L1 (31 of 163 `read:ungrounded`).
- **Why the engine lacks it:** `optimization/idea_lanes.py:_ground` matches only an exact substring after whitespace collapse (`text.find(target)`). On failure the idea is dropped (`fate(..., "ungrounded")`), as it also is in `idea_portfolio_leap.py`.
- **First, a record:** the sub-reason is not recorded, so the share that is reworkable is unknown. Record it first; this is record-only.

**M6. A coverage estimate as a round-retargeting signal.**
- **Source:** Good-Turing estimation, Good 1953 [15].
- **Mapping:**

  | Ecology | Engine |
  | --- | --- |
  | species | technique classes (the hunk or mechanism signature of every trial, kept or not) |
  | coverage | 1 − n1/N over the run's trials |

  When coverage is high on the current hot functions, the next round is sent to unprofiled callers or set-up code (L10) instead of the same anchors.
- **Rows:** L8 (X2-D unique share 0.56 in round 2, then 0.38 in round 3), and L10.
- **Why the engine lacks it:** the round count is a fixed setting (`GENERATOR_MAX_CALLS`, default 2, max 5, `common/config.py`). Nothing estimates unseen mass. Mechanism dedupe exists, but it is off in the X2 arms (`ideas-fate/README.md`).
- **Contested:** the classes need a reliable "same technique" key. The zero-credit repeat labels were human judgements.

## Open questions for the seminar

1. Is the noise between looks independent enough for M1's joint threshold, or does the VM state shared within a run correlate the two looks? The record-only fields in `floors/README.md` s5 would answer this.
2. Does re-queuing to the run's end (M2) meet the quiet stretch, or the late bursts seen in X2-P 43107418692?
3. How much of L6 is the winner's curse rather than interference? The offline test: re-measure archived best singles and archived tips side by side.
4. Of the 36 non-repeat conflicts, how many re-apply cleanly when the hypothesis is replayed on the tip? This is zero-credit if done by hand on the archived diffs first.
5. Analogical distance: were these sources too near to statistics (M1, M2) to count as "far"? Fu et al.'s sweet spot [4] suggests that near ones transfer best.

## Sources (numbered list, full citations with URL or ISBN)

1. Gentner, D. (1983). Structure-mapping: A theoretical framework for analogy. *Cognitive Science* 7(2), 155-170. https://groups.psych.northwestern.edu/gentner/papers/Gentner83.2b.pdf
2. Holyoak, K. J., and Thagard, P. (1995). *Mental Leaps: Analogy in Creative Thought.* MIT Press. ISBN 0-262-08233-0 (hb), 0-262-58144-2 (pb).
3. Gick, M. L., and Holyoak, K. J. (1980). Analogical problem solving. *Cognitive Psychology* 12(3), 306-355. https://deepblue.lib.umich.edu/handle/2027.42/23210 (figures from secondary summaries, e.g. https://nmoer.pressbooks.pub/cognitivepsychology/?p=925)
4. Fu, K., Chan, J., Cagan, J., Kotovsky, K., Schunn, C., and Wood, K. (2013). The meaning of "near" and "far": the impact of structuring design databases and the effect of distance of analogy on design output. *Journal of Mechanical Design* 135(2), 021007. https://www.lrdc.pitt.edu/Schunn/papers/fuchanetal-near-far-2013.pdf
5. Altshuller, G. (1997/1998). *40 Principles: TRIZ Keys to Technical Innovation.* Technical Innovation Center. ISBN 978-0964074033.
6. Skol, A. D., Scott, L. J., Abecasis, G. R., and Boehnke, M. (2006). Joint analysis is more efficient than replication-based analysis for two-stage genome-wide association studies. *Nature Genetics* 38(2), 209-213. doi:10.1038/ng1706. https://pubmed.ncbi.nlm.nih.gov/16415888/ (corrigendum to Table 1, March 2006)
7. Zhang, J.-H., Chung, T. D. Y., and Oldenburg, K. R. (1999). A simple statistical parameter for use in evaluation and validation of high throughput screening assays. *J. Biomol. Screen.* 4(2), 67-73. https://iccb.med.harvard.edu/publications/simple-statistical-parameter-use-evaluation-and-validation-high-throughput (bands via https://www.graphpad.com/support/faqid/1153)
8. Brideau, C., Gunter, B., Pikounis, B., and Liaw, A. (2003). Improved statistical methods for hit selection in high-throughput screening. *J. Biomol. Screen.* 8(6), 634-647. doi:10.1177/1087057103258285
9. Malo, N., Hanley, J. A., Cerquozzi, S., Pelletier, J., and Nadon, R. (2006). Statistical practice in high-throughput screening data analysis. *Nature Biotechnology* 24(2), 167-175. doi:10.1038/nbt1186
10. Padioleau, Y., Lawall, J., Hansen, R. R., and Muller, G. (2008). Documenting and automating collateral evolutions in Linux device drivers. *EuroSys 2008*, 247-260. doi:10.1145/1352592.1352618. https://homes.cs.aau.dk/~rrh/pubs/eurosys08.pdf
11. Ellis, C. A., and Gibbs, S. J. (1989). Concurrency control in groupware systems. *SIGMOD 1989*, 399-407. doi:10.1145/66926.66963
12. Kulkarni, P. A., Whalley, D. B., Tyson, G. S., and Davidson, J. W. (2006). Exhaustive optimization phase order space exploration. *CGO 2006*, 306-318. https://dblp.org/rec/conf/cgo/KulkarniWTD06
13. Tate, R., Stepp, M., Tatlock, Z., and Lerner, S. (2009). Equality saturation: a new approach to optimization. *POPL 2009*; journal version *LMCS* 7(1), 2011. https://arxiv.org/abs/1012.1802
14. Caruana, R., Niculescu-Mizil, A., Crew, G., and Ksikes, A. (2004). Ensemble selection from libraries of models. *ICML 2004*. doi:10.1145/1015330.1015432. https://icml.cc/Conferences/2004/proceedings/abstracts/345.htm
15. Good, I. J. (1953). The population frequencies of species and the estimation of population parameters. *Biometrika* 40(3-4), 237-264. doi:10.1093/biomet/40.3-4.237
16. Zöllner, S., and Pritchard, J. K. (2007). Overcoming the winner's curse: estimating penetrance parameters from case-control data. *Am. J. Hum. Genet.* 80(4), 605-615. doi:10.1086/512821. https://pmc.ncbi.nlm.nih.gov/articles/PMC1852705
17. Breyfogle, F. W. (2003). *Implementing Six Sigma*, 2nd ed. Wiley. ISBN 978-0471265726 (not accessed; RTY and "hidden factory" from https://isssp.org/first-time-yield-and-rolled-throughput-yield/)
18. Williams, N. (2015). RFC 7464: JavaScript Object Notation (JSON) Text Sequences. IETF. https://www.rfc-editor.org/rfc/rfc7464.html
19. Fraser, N. diff-match-patch (Bitap matching, `Match_Threshold`, `Match_Distance`). API docs: https://docs.jmix.io/api/1.0/ui/name/fraser/neil/plaintext/diff_match_patch.html
