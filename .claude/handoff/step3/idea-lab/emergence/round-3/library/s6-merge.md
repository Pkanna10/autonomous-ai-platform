# s6-merge: patch composition and merging

**Access note.** WebFetch could not reach arxiv.org or uni-saarland.de from this session, so I read no full texts. Every literature number below comes from the abstract or a search-engine summary of the cited page. Numbers marked **[A]** are my own zero-credit computations on `w2-sprint/live/` and `zero-credit/*.csv`, read only. The scripts are in `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/s6-merge/` (`blk.py`, `l6.py`, `additive.py`, `union.py`, `mwis.py`).

## Core sources (5-12, each: citation, what it covers, why it is standard)
1. **Mens 2002 [1].** The standard survey of software merging. It sorts merge tools as textual, syntactic or semantic, and as state-based or operation-based.
2. **Khanna, Kunal and Pierce 2007 [2].** A formal model of diff3, the line-based 3-way merge that git's merge descends from.
3. **Apel et al. 2011 [3]; Cavalcanti, Borba and Accioly 2017 [4].** These founded semistructured merge (FSTMerge) and evaluated it.
4. **Shen et al. 2019 [5]; Zhu et al. 2022 [7].** IntelliMerge (refactoring-aware merge) and Mastery (merge that handles moved code). These are the current structured-merge baselines.
5. **Horwitz, Prins and Reps 1989 [8]; Sousa, Dillig and Lahiri 2018 [9].** The classic and the verified treatments of semantic merge.
6. **Ellis and Gibbs 1989 [12]; Shapiro et al. 2011 [13].** The founding papers of operational transformation (OT) and CRDTs. Both give conditions under which concurrent edits compose in any order.
7. **Roundy [14]; Mimram and Di Giusto 2013 [15]; the Pijul manual [16].** Patch theory: commutation, and merge as a pushout.
8. **Le Goues et al. 2012 [17]; Renzullo et al. 2018 [18]; Liou et al. 2022 [19].** Patch representations in program repair and genetic improvement (GI), and measured interactions between edits ("epistasis").
9. **Zeller 1999 [22].** Delta debugging: isolating which of many changes matter.
10. **Tate et al. 2009 [23]; Pan and Eigenmann 2006 [26].** The phase-ordering problem, with one remedy that keeps every alternative and one that searches by elimination.

## Notes (the methods and results, cited inline as [n])

**Textual 3-way merge.**
- Mens separates textual merge (lines), syntactic merge (trees) and semantic merge (behaviour). He also separates state-based merge (compare versions) from operation-based merge (replay edits) [1].
- Khanna et al. formalise diff3 and analyse its properties; a third-party summary calls its behaviour surprisingly unpredictable [2].
- How git 2.43 treats four cases (my own toy test, **[A]**):
  - two identical edits merge cleanly;
  - edits on adjacent lines conflict;
  - edits with one line between them merge cleanly;
  - an edit that extends another edit's hunk conflicts.
- `execution/combine.py` (FIXED) works as follows:
  - It merges greedily in the order the caller gives, with `merge-tree --write-tree ACC X` and the base as merge base.
  - A conflict skips the keep. A keep already contained in the tip is skipped as `nothing left to apply`.
  - The tip is then measured ABAB, and the test suite runs on it.
- `combine_node` chooses the order:
  - `SITE_STACKS=off` (the default, and every archived arm) orders by hypothesis score.
  - `on` first offers each conflict component's best subset by summed gain: exact search up to 9 nodes, greedy above that.
  - A failed greedy combine falls back to the single best keep by gain.

**Structured and semistructured merge.**
- Apel et al. merge the program's outline (classes and methods) as a tree and merge method bodies as lines. On 24 projects and 180 merge scenarios, this cut conflicts in 60 % of scenarios, by 34 % on average. Renaming is its main weakness [3].
- Cavalcanti et al. found that semistructured merge cuts false positives but may add false negatives (missed real conflicts). Their tool s3m halves reported conflicts, adds no false positives, and has at least 8 % fewer false negatives than unstructured merge [4].
- IntelliMerge, on 1,070 scenarios from 10 Java projects [5]:
  - 58.90 % fewer conflicts than git merge and 11.84 % fewer than jFSTMerge;
  - precision 88.48 % and recall 90.22 % on the conflicting files only.
- Ellis et al. reproduced IntelliMerge to within 10 % of those numbers. On 2,001 harder refactoring scenarios it reduced conflicts in 24 % and increased conflicting lines in 30 % [6].
- Mastery, on 40,533 scenarios: the highest accuracy of the tools compared, and 2.4x as fast as a state-of-the-art structured merger. Moved ("shifted") code occurs in 38.54 % of scenarios [7].
- **Well established:** structure removes conflicts that come from reformatting, reordering, renaming and moved code.
- **Contested:** the false-negative cost, and how far the results carry beyond Java.

**Semantic conflicts.**
- **Textual cleanliness is neither necessary nor sufficient for a correct merge.** Two edits that touch different lines can still break each other's behaviour, and two edits that clash textually can be compatible in behaviour.
- Horwitz et al. integrate variants A and B of a base program using program dependence graphs and slicing. Integration succeeds only when the changes "do not interfere" [8].
- SafeMerge checks conflict-freedom one edit at a time and composes the results into a proof. On 52 GitHub scenarios it verified 75 % and found 11 real violations [9].
- Brun et al. (Crystal), on 9 systems, 3.4 MLOC and 550,000 versions: conflicts are frequent and persistent, and they show up as build and test failures as well as textual clashes [10].
- Test-based detection is weak. The best configuration of SAM found 9 of 29 known semantic conflicts [11].

**Operational transformation and CRDTs as composition theory.**
- OT rewrites a concurrent operation so that it still means the same thing after the other operation has run [12].
  - Convergence requires the transformation properties TP1 and TP2, which came after Ellis and Gibbs. Several published transformation functions were later shown to violate TP2 (secondary source: [12b]).
- CRDTs converge (strong eventual consistency) when all concurrent operations commute, or when states form a semilattice whose merge is monotone [13].
- **Lesson:** a combine is order-independent only if its patches commute. Hunks that rewrite the same lines do not commute, so the order of the greedy merge is a policy that decides which keep survives.
- An OT-style remedy would rewrite B against A (B' = T(B, A)). Here T would have to be an editor call followed by a new measurement, because no transformation function is proven for code.

**Patch theory.**
- Darcs keeps patches in sequence and computes commutation: whether two adjacent patches can be swapped, and how. Patches to different files commute trivially; two hunks in one file must be checked [14].
- Mimram and Di Giusto model a merge as a pushout. Conflicting patches have no pushout, so the category is completed freely to represent conflicted files [15].
- Pijul: two changes either commute or one depends on the other, and changes written independently always commute. Application is associative, and conflicts are stored as first-class state [16].
- **Lesson:** what turns a conflict into an ordered dependency is writing B after A, against A's result. Stacked rounds (X2-DT) do exactly that.

**Program repair and genetic improvement: combining edits.**
- GenProg evolves edits to programs and then minimises the result with structural differencing and delta debugging [17].
- Delta debugging isolated 1 failure-inducing change among 178,000 changed lines of GDB. It assumes some changes interfere and some combinations are inconsistent [22].
- How often edits interact:
  - Renzullo et al.: positive epistasis is rare in the search space as a whole. It produced 4.63 % of repairs across all programs (9 % for `look`), yet 62.5 % of the unique repairs [18].
  - GEVO (GPU code): four edits explain 88.2 % of a 17 % improvement, and two of them depend on a third. The authors note that earlier evolutionary work rarely found epistasis [19].
- GI can deliver large gains: Langdon and Harman report Bowtie2 70x faster on average on their workload [20]. Petke et al. survey the field from 1995 to 2015 [21].
- **Contested:** how common interaction between edits is. Both [18] and [19] are small studies.

**Phase ordering.**
- Tate et al.: an optimisation can irrevocably prevent another from triggering. Equality saturation keeps every alternative in one structure and chooses only at the end [23].
- Whitfield and Soffa analyse which transformations enable or disable which others [24].
- Kulkarni et al. enumerate every distinct function instance that phase orders can produce. The TACO 2008 version reports this as feasible for most functions with pruning [25].
- Pan and Eigenmann's Combined Elimination starts from all optimisations on and repeatedly removes those with a negative relative improvement. It comes within 0.2 % of the exhaustive optimum on average [26].
- Lerner et al. compose analyses so that each helps the others, avoiding the precision lost by iterating them separately [27].

## Bearing on the ledger (per row you touch: L#, what your field says, numbers)

**L5: combine conflicts and repeats.**
- The archive's conflicts are true overlaps (from `pairs.csv`, **[A]**):
  - Of 365 pairs of keeps within a run, 277 are disjoint, 72 conflict, 14 touch the same function but merge cleanly, and 2 overlap but merge cleanly.
  - Every one of the 72 conflicts changes overlapping lines inside a function both keeps edit.
  - 36 of the 72 delete exactly overlapping sets of lines (`del_cov` 1.0). None has added-line similarity of 0.9 or more.
  - So these are alternative rewrites of the same lines. Neither keep is an extension of the other.
- **Consequence:** neither FSTMerge-style nor tree merge would recover any of them, because semistructured merge merges method bodies as text [3] and tree merge targets conflicts that come from moved or reordered code [5][7]. This is my inference from the data, not a published result.
- Score order chooses the stronger side of a conflict only about half the time (**[A]**). In 57 conflict skips, the left-out keep's standalone gain was higher than its blocker's in 30 and not higher in 27, with a median difference of +0.11 percentage points.
- Three remedies exist for alternatives that cannot be merged:
  - choose by gain: the best conflict-free subset, as `SITE_STACKS=on` does;
  - rewrite one against the other: OT style, an editor call followed by a new measurement;
  - sequence them: stacked rounds.

**L6: combine below its best part.**
- The 12 runs break down as follows (**[A]**, the count matches the ledger):
  - In **7**, the best keep was left out by a conflict. The largest gaps are markdown 10.1 against 21.8 and 9.9 against 20.7.
  - In **4**, the best keep was applied, and the shortfall is 0 to 1.1 percentage points, within the noise.
  - **1** is the failed mistune combine.
- When the merge is textually clean, gains nearly add (**[A]**):
  - In 54 held combines with 2 or more applied keeps, delivered gain divided by the sum of the applied keeps' standalone gains has a median of 0.91 (IQR 0.82 to 1.00, range 0.48 to 1.24).
  - 14 of the 54 exceed the sum.
  - mistune is lowest, at 0.80 with 4.5 applied keeps on average.
  - No held combine fell below its best applied part.
- So L6 comes mainly from the policy that resolves conflicts, not from negative interaction between the merged changes. Modest sub-additivity agrees with [18][19], where strong interaction is rare.

**L8: diminishing unique keeps; X2-DT [`stacked-plan.md`].**
- Patch theory supports the plan: writing round r+1 against the tip turns concurrent alternatives into dependent patches [14][16]. A re-implemented technique then shows up as no gain measured against the tip, not as a conflict.
- Phase ordering predicts the cost: a greedy choice disables later options [23][24].
- Section 3 of the plan refuses `SITE_STACKS` beside `STACKED_ROUNDS`. Each round's combine would therefore resolve conflicts by score, which chose the weaker side in 30 of 57 archived conflicts, and stacking would then fix that choice in place.
- **This is a design risk for the seminar.** The plan does not change `combine.py` either way.

**Reviewer's seed (a): the union of proven diffs as the ceiling.**
- Each library has a single base commit across all runs (**[A]**), so the union is well defined. Keeps are de-duplicated by identical hunks, conflicts come from pairwise `git merge-file`, and the best conflict-free set by summed gain is solved exactly by branch and bound.

| library | runs | keeps -> distinct | conflict density | best set size | sum of standalone gains | never applied in any run | best archived delivery |
|---|---|---|---|---|---|---|---|
| sqlparse | 16 | 75 -> 75 | 0.26 | 11 | 82.3 | 2 | +43.9 |
| tomli | 16 | 53 -> 41 | 0.26 | 9 | 78.0 | 2 | +24.8 |
| mistune | 15 | 80 -> 70 | 0.19 | 15 | 76.7 | 3 | +23.7 |
| markdown | 15 | 76 -> 69 | 0.42 | 9 | 77.6 | 4 | +25.5 |

- Each best set merges cleanly when applied in sequence.
- The sums assume the gains add, which nothing supports at 9 to 15 changes: they are standalone gains selected from noisy measurements on different VMs. They give the ceiling's structure, not its value. Only measuring the merged tip, with the test suite, gives the value [8][9][11].
- A protocol from compiler autotuning [26]:
  1. measure the union tip;
  2. remove each member in turn and re-measure (n+1 ABAB measurements, CI minutes only);
  3. drop the members whose removal helps;
  4. repeat.

## Open questions for the seminar
1. Do the 7 L6 runs whose best keep was left out recover under a replay ordered by gain (`SITE_STACKS=on`), with no API spend?
2. Should X2-DT allow the round combine to choose by gain? The plan refuses that pairing today.
3. Does the 0.91 additivity hold for unions of 9 to 15 changes, or does it fall as mistune's 0.80 at 4.5 applied keeps suggests?
4. Is an OT-style "rewrite B over its blocker" request worth an editor call? 36 of 57 skipped conflicts are overlaps rather than repeats.
5. As printed, L6's medians (+17.4 delivered against +11.3 best single keep) seem to contradict the row's own claim. What population is each median taken over?

## Sources (numbered list, full citations with URL or ISBN)
1. T. Mens, "A state-of-the-art survey on software merging," IEEE TSE 28(5):449-462, 2002. doi:10.1109/TSE.2002.1000449
2. S. Khanna, K. Kunal, B. C. Pierce, "A Formal Investigation of Diff3," FSTTCS 2007, LNCS 4855. https://www.cis.upenn.edu/~sanjeev/papers/fsttcs07_diff3.pdf
3. S. Apel, J. Liebig, B. Brandl, C. Lengauer, C. Kästner, "Semistructured Merge: Rethinking Merge in Revision Control Systems," ESEC/FSE 2011, 190-200. https://www.se.cs.uni-saarland.de/publications/docs/FSE2011.pdf
4. G. Cavalcanti, P. Borba, P. Accioly, "Evaluating and Improving Semistructured Merge," OOPSLA 2017. doi:10.1145/3133883; https://pauloborba.cin.ufpe.br/project/s3m/
5. B. Shen et al., "IntelliMerge: A Refactoring-Aware Software Merging Technique," OOPSLA 2019. doi:10.1145/3360596
6. M. Ellis, S. Nadi, D. Dig, "Operation-based Refactoring-aware Merging: An Empirical Evaluation," arXiv:2112.10370, 2021. https://arxiv.org/abs/2112.10370
7. F. Zhu, X. Xie, D. Feng, N. Meng, F. He, "Mastery: Shifted-Code-Aware Structured Merging," SETTA 2022. doi:10.1007/978-3-031-21213-0_5; https://thufv.github.io/research/setta22a-artifact
8. S. Horwitz, J. Prins, T. Reps, "Integrating Noninterfering Versions of Programs," ACM TOPLAS 11(3):345-387, 1989. https://research.cs.wisc.edu/wpis/abstracts/toplas89.abs.html
9. M. Sousa, I. Dillig, S. K. Lahiri, "Verified Three-Way Program Merge," OOPSLA 2018 (PACMPL 2, art. 165). https://www.cs.utexas.edu/~isil/verified-merge.pdf
10. Y. Brun, R. Holmes, M. D. Ernst, D. Notkin, "Early Detection of Collaboration Conflicts and Risks," IEEE TSE 39(10):1358-1375, 2013. https://homes.cs.washington.edu/~mernst/pubs/vc-conflicts-tse2013.pdf
11. L. Da Silva, P. Borba et al., "Detecting semantic conflicts with unit tests," Journal of Systems and Software 214, 2024. https://research.chalmers.se/publication/541567
12. C. A. Ellis, S. J. Gibbs, "Concurrency Control in Groupware Systems," SIGMOD 1989, SIGMOD Record 18(2):399-407. doi:10.1145/66926.66963. [12b] Wikipedia, "Operational transformation" (secondary source, for TP1 and TP2). https://en.wikipedia.org/wiki/Operational_transformation
13. M. Shapiro, N. Preguiça, C. Baquero, M. Zawirski, "Conflict-free Replicated Data Types," SSS 2011, 386-400. https://www.cs.tufts.edu/~nr/cs257/archive/marc-shapiro/CRDTs_SSS-2011.pdf
14. D. Roundy, "Darcs: distributed version management in Haskell," Haskell Workshop 2005, 1-4; and D. Roundy, "Theory of patches" (manual appendix, 2009). https://www.cs.tufts.edu/~nr/cs257/archive/david-roundy/theory-patches-2009.pdf
15. S. Mimram, C. Di Giusto, "A Categorical Theory of Patches," arXiv:1311.3903, 2013. https://arxiv.org/abs/1311.3903
16. Pijul manual, "Why Pijul?" https://pijul.org/manual/why_pijul; and Pijul blog, "Commutation and scalability," 2020-12-19. https://pijul.org/posts/2020-12-19-partials
17. C. Le Goues, T. Nguyen, S. Forrest, W. Weimer, "GenProg: A Generic Method for Automatic Software Repair," IEEE TSE 38(1):54-72, 2012. https://clairelegoues.com/assets/papers/genprog12tse.pdf
18. J. Renzullo, W. Weimer, M. Moses, S. Forrest, "Neutrality and Epistasis in Program Space," GI@ICSE 2018. doi:10.1145/3194810.3194812; https://gpbib.cs.ucl.ac.uk/gp-html/Renzullo_2018_GI.html
19. J.-Y. Liou, M. Awan, S. Hofmeyr, S. Forrest, C.-J. Wu, "Understanding the Power of Evolutionary Computation for GPU Code Optimization," IISWC 2022, 185-198. https://arxiv.org/abs/2208.12350
20. W. B. Langdon, M. Harman, "Optimizing Existing Software with Genetic Programming," IEEE TEVC, 2015. doi:10.1109/TEVC.2013.2281544
21. J. Petke, S. Haraldsson, M. Harman, W. B. Langdon, D. White, J. Woodward, "Genetic Improvement of Software: a Comprehensive Survey," IEEE TEVC 22(3):415-432, 2018. doi:10.1109/TEVC.2017.2693219
22. A. Zeller, "Yesterday, my program worked. Today, it does not. Why?" ESEC/FSE 1999, LNCS 1687, 253-267. https://www.st.cs.uni-saarland.de/publications/files/zeller-esec-1999.pdf
23. R. Tate, M. Stepp, Z. Tatlock, S. Lerner, "Equality Saturation: A New Approach to Optimization," POPL 2009; LMCS 2011. https://arxiv.org/abs/1012.1802
24. D. L. Whitfield, M. L. Soffa, "An Approach for Exploring Code-Improving Transformations," ACM TOPLAS 19(6), 1997. https://www.cs.tufts.edu/~nr/cs257/archive/mary-lou-soffa/p120-whitfield.pdf
25. P. A. Kulkarni, D. B. Whalley, G. S. Tyson, J. W. Davidson, "Exhaustive Optimization Phase Order Space Exploration," CGO 2006. https://dblp.org/rec/conf/cgo/KulkarniWTD06; TACO 2008 version: https://ittc.ku.edu/~kulkarni/CARS/taco08/taco08.html
26. Z. Pan, R. Eigenmann, "Fast and Effective Orchestration of Compiler Optimizations for Automatic Performance Tuning," CGO 2006. https://engineering.purdue.edu/~eigenman/reports/cgo06.pdf
27. S. Lerner, D. Grove, C. Chambers, "Composing Dataflow Analyses and Transformations," POPL 2002, 270-282. https://bibtex.github.io/POPL-2002-LernerGC.html
