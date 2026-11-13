# z2-contradiction: zero to one through contradiction resolution

**Access note.** Web fetch was blocked in this session: `metodolog.ru` and `the-trizjournal.com` did not resolve, and I stopped trying further hosts as the tool told me to. Everything below comes from web-search result summaries and catalogue records, plus a read-only pass over the engine code at `/home/user/step3-emergence-r1` (head `7578d00`). I did not read the full text of any book. Each source carries one of two tags:
- **[cat]:** checked against a catalogue record or a bibliographic summary only;
- **[sum]:** the content was taken from a search-result summary of the page.

No file was written.

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **Altshuller, *The Innovation Algorithm* (1999) [1] [cat].** ARIZ, technical and physical contradictions, the ideal final result. It is the founder's own text, first published in 1973.
2. **Altshuller, *40 Principles: TRIZ Keys to Technical Innovation* (1997) [2] [cat].** The 40 inventive principles. It is the canonical list.
3. **Savransky, *Engineering of Creativity* (2000) [3] [cat].** A systematic Western textbook of TRIZ. It is widely used for teaching. I could not confirm its chapter on separation principles.
4. **Haines-Gadd, *TRIZ For Dummies* (2016), Appendix D [4] [sum].** A table that assigns inventive principles to separation in time and in space. It is the only principle-by-separation mapping I could reach.
5. **Rea, "TRIZ and Software: 40 Principle Analogies", Parts 1 and 2 (2001) [5] [sum].** Software analogues for each of the 40 principles. It is the standard TRIZ-for-software reference and was later extended by Fulbright (2004).
6. **Goldratt, *What Is This Thing Called Theory of Constraints* (1990) [6], and *It's Not Luck* (1994) [7] [cat/sum].** The thinking processes, including the evaporating cloud (EC), also called the conflict resolution diagram. These are the origin texts.
7. **Dettmer, *Goldratt's Theory of Constraints* (1997) [8] [cat].** The first systematic textbook of the thinking processes.
8. **Mason, "A dialectical approach to strategic planning" (1969) [9] [sum].** Dialectical inquiry as a way to surface the assumptions behind a plan. It is the founding paper.
9. **Cosier and Aplin (1980) [10] [sum].** A controlled test of dialectical inquiry. It is the standard counter-evidence.
10. **Ilevbare, Probert and Phaal (2013) [11] [sum].** A practitioner survey of TRIZ's benefits and challenges. It is a highly cited review.
11. **Wald (1945) [12]; Pocock (1977) [13]; Johari et al. (2017) [14] [sum].** Sequential testing. It is the statistical machinery that "separation upon condition" needs whenever the condition is a measured result.

## Notes (the methods and results, cited inline as [n])

**Two kinds of contradiction.**
- **Technical contradiction:** improving one parameter worsens another; strength against weight is the usual example. Classical TRIZ attacks it with the 40 principles and the contradiction matrix [1][2].
- **Physical contradiction:** one element must take opposite values of the same parameter, as in "a part must be large and small". TRIZ resolves it directly with separation principles [4].
- **The usual route:** state the technical contradiction, sharpen it into a physical one, then separate [4].
- **The landing-gear case:** the gear must be present for landing and absent for drag. It is solved by separation in time: retract it [4].

**Separation principles.** The common simplification has four [4]:
- **time:** the property holds at one moment and not at another;
- **space:** the property holds in one place and not in another;
- **condition:** the property holds when a stated condition is met;
- **scale, or parts versus whole:** the system has a property that its parts do not, or the reverse.

Some courses list six, adding the move to the supersystem or a subsystem and conversion back to a technical contradiction [4].

The Dummies table [4] assigns these principles:
- **to time:** 1 segmentation, 7 nested doll, 9 prior counteraction, 10 prior action and 11 cushion in advance;
- **to space:** 1, 2 taking out and 3 local quality.

I could not verify the full table.

**TRIZ for software.** Rea [5] maps all 40 principles onto software constructs. Mann (2008) argues that software contradictions cluster at interfaces between the software and the outside world [sum]. For this engine, those interfaces are the model reply, the measurement VM and git.

**The evaporating cloud** [6][7][15] has five boxes:
- A is the common objective;
- B and C are two needs, each required for A;
- D and D' are the conflicting prerequisites: D serves B, and D' serves C.

Each arrow rests on a hidden assumption. Resolution means finding an invalid assumption and an "injection" that makes it false. Goldratt's worked case is batch size [6, via Martin's study guide] [sum]:
- **The conflict:** large batches lower the setup cost per unit, while small batches lower inventory and lead time.
- **First invalid assumption:** setup cost is fixed. It is not; setup time can be cut.
- **Second invalid assumption:** "batch" has one meaning. It has two: the process batch (between setups) and the transfer batch (between stations). Separating them dissolves the conflict.

That second injection is a separation by scale. One word named two units, and the two units can take different values.

**Dialectical design.** Mason [9] sets two criteria for a planning technique: it must surface the assumptions behind a plan, and it must generate new, more relevant ones. A thesis and its counter-plan are built on opposite assumptions, and a synthesis is drawn from the debate [sum; I could not confirm the thesis-antithesis wording in the full text].

**Sequential testing.** This is where "separation upon condition" meets measurement.
- **Wald's SPRT [12]:** among sequential tests with given error rates, it minimises the expected sample size. A secondary summary puts the saving at about half of a fixed-sample test's size; I could not check that figure against the paper.
- **The price of peeking [13][14]:** each extra look must be stricter. Pocock's constant nominal level for an overall two-sided 0.05 is 0.0294 a look with 2 looks and 0.0158 a look with 5 (Wikipedia, "Pocock boundary"; Penn State STAT 509).
- **Naive peeking:** looking repeatedly at accumulating data and stopping on the first pass inflates false positives. Johari et al. [14] give always-valid p-values that hold at any data-dependent stopping time.
- **Fresh looks:** an independent new measurement after a selection step is a different case from peeking, because its error rate is not inflated by the selection. The run-level multiplicity still grows with the number of candidates given a look.

**What is established, and what is contested.**
- **Established:** the vocabulary (technical against physical contradiction, the separation principles, the EC's structure) is consistent across sources [1][4][15]. Sequential-testing error control is mathematics [12][13][14].
- **Contested:** evidence that TRIZ works is mostly practitioner reports. Ilevbare et al. [11] find that benefits are "prominent despite its negatives" but name complexity and organisational barriers. A systematic review of TRIZ in innovation management calls the evidence limited [sum, source not opened]. The contradiction matrix's reliability has been questioned, and it was revised in 2003 [sum].
- **Dialectical inquiry:** Cosier and Aplin [10] found reports written under dialectical inquiry inferior to the other conditions, with 32 United Way planners randomly assigned to conditions. A 1986 *Academy of Management Journal* study found it better than consensus, and a 1989 study found no difference from devil's advocacy [sum].
- **Reading for the seminar:** treat these methods as generators of candidate mechanisms that still need the engine's own offline test, not as evidence.

**Worked EC for the engine (L3 and L4).**
- A: deliver only proven gain.
- B: never keep a false gain. D: judge each trial strictly, on one look at N = 5, whenever it happens to run.
- C: do not lose true small gains. D': accept gains below the trial's own floor.

The arrow D -> B assumes that the moment of measurement is neutral. The floors page refutes that: 27 % of trials sit above 1.5x the calibrated floor in minutes 0-5 against 10 % in minutes 30-60, and the noisiest 10 runs hold 90 of the 175 such trials (`floors/README.md` s4). The injection is a separation in time and upon condition, built out in C1 below. The judge stays strict; what changes is when and for whom a fresh look is taken.

## Bearing on the ledger (per row you touch: L#, what your field says, numbers)

- **L1 and L8 (quota-blocked ideas; falling unique keeps).**
  - The contradiction: the portfolio must be diverse within a round (the quotas), yet it must not discard distinct ideas.
  - The separation: in time. Enforce diversity per round, and give coverage across rounds.
  - The numbers: 35 of 163 ideas are lost at S4b, of which 19 are `quota_several` and 9 `quota_primary_cell`. Meanwhile 24 are reviewer duplicates and 21 of 57 combine conflicts are re-found techniques. Later rounds re-find old techniques while distinct ideas that already passed review are thrown away. See C4.
- **L2 (truncated leaps).**
  - The contradiction: the cap must be high, so the reply completes, and low, for the reservation and the timeout.
  - The separation: parts versus whole (principle 1, segmentation [2][5]). A reply cut short as a whole can still hold complete parts.
  - The numbers: 3 of 32 Opus leaps hit 12,000 tokens. Each yields 0 ideas today. See C3.
- **L3, L4 and L7 (noise).**
  - The contradiction: N must be large and must be small. Separation in time and upon condition resolves it (the EC above; see C1).
  - Field rule from [13][14]: any second chance must be triggered by something other than the verdict, or it must be corrected for multiplicity. This rules out re-looking the 49 failed confirmations of L4 because they failed. It matches the combine proposal's own "the trigger reads only the floor" (`combine-proposal.md` s1).
- **L5 and L8 (conflicts).**
  - The contradiction: a keep must be cut from the base (to be judged alone) and from the tip (to compose).
  - The separation: in time, the way Goldratt's process and transfer batches separate [6]. Discover on the base; re-implement on the tip.
  - The numbers: 62 of 177 keeps were left out; 36 of the 57 analysed conflicts are not repeats. See C2.
- **L6 (combine below its best part, 12 of 63 runs).**
  - The finding: the tip and the best single keep were measured at different moments, so the comparison is confounded with the VM's state.
  - The separation: in time between selection and estimation, the winner's-curse logic behind [12][14]. See C5.

## Mechanisms the engine does not have

**What is not touched.** None of these changes `judges.py`, anticheat, the protected paths, the benchmarks or N. The floors page's "paired floor" (its fix A) is a judge change and so is excluded here. Each mechanism changes only which measurement the frozen judges see, when it is taken, or what an editor is asked to do. Whether "judge on the fresh look" counts as a judge change is the owner's call, as it already is for combine-proposal item 1.

**C1. N must be large for ambiguous trials and small for the rest (L3; also L4 and L7).**
- **Separation:** upon condition (only noisy looks are repeated), and in time (the repeat runs at the run's quietest stretch, the end).
- **Mechanism: a deferred, verdict-blind re-look.**
  - The trigger: any trial whose own floor exceeds k x the calibrated baseline floor, keeps included. With k = 1.5 that is 175 of 972 trials, about 2.8 a run.
  - The look: after the last round's trials and before the combine, each triggered trial gets one fresh `retest_one` look. That is the confirmation's own path, with the frozen judges and the suite on the tip.
  - The verdict: it is judged on the fresh look. A keep still needs its confirmation.
  - Why it is symmetric: a noisy keep can be lost, so this is not "measure until it passes".
  - The cost: a re-test takes 5.5-13.3 s including the suite (`o62/replay.md` s2). At 2.8 a run that is about 40 s a run on sqlparse, with 0 USD of API spend.
  - The target: the 47 between-floor inconclusives (median gain 3.8 % against a median own floor of 6.6 %; 10 of them at 5 % or more).
- **Why it is missing today:**
  - `orchestrator/confirm.py` confirms only `CONFIRMABLE = {keep, review}`, so `inconclusive` is terminal.
  - The near-miss compounds (`optimization/evolve.py`, on in the X2 arms) replay at most one *pair* a round, on disjoint files. They never re-measure a single trial.
  - The floor-triggered re-measure exists only as a proposal for the combine (`combine-proposal.md` s1).
- **Offline experiment and kill result:** on a replay runner, re-look the archived diffs of the 47. **The mechanism dies if fewer than 5 of the 47 clear their own floor on the quiet re-look.**

**C2. A keep must be cut from the base and from the tip (L5, L8).**
- **Separation:** in time. Discover and judge on the base, then re-implement on the tip. Goldratt's process batch and transfer batch [6] are the analogue: the unit of discovery need not be the unit of delivery.
- **Mechanism: re-port on conflict.**
  - Which keeps: each one the greedy merge skips for a textual conflict, and that is not a repeat of its blocker. A repeat is dropped, which is separation upon condition.
  - What happens: the keep goes first to a mechanical rebase, git's `diff3`/`zdiff3` merge style. Failing that, the editor gets one request: re-apply this change on the tip, with the blocker's diff shown.
  - How it is judged: the result is a new trial against the tip, with a marginal gain, the frozen judges and the protected-path checks.
  - Scale: there are 36 non-repeat conflicts in 39 held rows, about 0.9 a run.
- **Why it is missing today:**
  - `execution/combine.py:_merge` records the skip with reason `CONFLICT` and moves on.
  - `SITE_STACKS=on` only picks a max-sum conflict-free subset, so it selects and never merges.
  - X2-DT (`STACKED_ROUNDS`, being built) moves later rounds onto the tip. Its round-end combine is still today's (`stacked-plan.md` s2 step 1), so same-round conflicts are still skipped.
  - A search for rebase or re-apply paths found none.
- **Offline experiment and kill result:** replay `zero-credit`'s `q1_left_out.csv` pairs with `git merge-file --diff3` and with a re-diff at zero context lines (no API spend). **The mechanism dies if fewer than 9 of the 36 merge cleanly.** The editor tier would then need a live arm, and its case would be weak.

**C3. The leap needs a long reply, but its cap is fixed (L2).**
- **Separation:** parts versus whole (principle 1, segmentation [2][5]), and in time (continuation).
- **Mechanism: salvage complete ideas from a cut reply.**
  - The prompt asks the leap to emit ideas as self-contained objects, one after another.
  - On `max_tokens`, a strict parser keeps every complete object before the cut. Each is validated alone against the same strict schema, and the cut tail is dropped.
  - Salvaged ideas then pass S4a, S3 and S4b as usual.
  - It costs 0 extra tokens. The 24k-token alternative costs up to +0.24 USD a leap (`o62/README.md` s3).
- **Why it is missing today:**
  - `clients/structured.py:read_reply` raises `UnusableReplyError("stopped")` for any `stop_reason` other than `end_turn`.
  - `optimization/idea_pipeline.py` (around line 936) catches it and returns `[]` for the lane.
- **Offline experiment and kill result:**
  - **First check whether the archives keep the cut text at all.** `o62` s2 says only `stop_reason` is recorded. If the text is not kept, this experiment needs a recording field first.
  - **The mechanism dies if, in the 3 truncated Opus replies, the cut falls inside thinking or inside the first idea.** In either case there is nothing to salvage.
  - **Security:** a partial parse of untrusted model text must stay as strict as today's (no duplicate keys, no NaN, depth limits).

**C4. The portfolio must be diverse, yet must not discard distinct ideas (L1, L8).**
- **Separation:** in time. The quotas hold within each round, and coverage is reached across rounds.
- **Mechanism: a per-run backlog.**
  - What enters it: ideas blocked only by an S4b quota. They have already passed S4a and the reviewer.
  - How it is used: the next round's portfolio fills from the backlog first, under the same quotas against that round's picks. Fresh lane calls then fill only the remaining slots, or a lane call is skipped, which saves tokens.
  - Anchors are re-checked against the round's base, which matters under X2-DT.
- **Why it is missing today:**
  - `optimization/idea_portfolio.py:portfolio` returns the picks plus parked *novel* ideas only. The other unpicked ideas get a fate and nothing more.
  - A second `generate` call sends fresh lane requests (the `idea_pipeline.py` docstring).
  - A search for a backlog or carry-over found none.
- **Offline experiment and kill result:** use the `idea_fates` of the 4 X2-0 runs. **The mechanism dies if most of the 35 S4b ideas were re-proposed or trialled in a later round anyway** (matching mechanism key, file and function), because then the backlog adds nothing.

**C5. Deliver the sum, yet never deliver less than the best part (L6).**
- **Separation:** upon condition (choose by measurement), and in time (select on one look, estimate on a later one).
- **Mechanism: a side-by-side tip and best single.**
  - The tip and the best single keep are measured in one interleaved block against the base, so they share the VM's state.
  - The better one is delivered, and its gain is reported from a further fresh look, which avoids the winner's curse.
- **Why it is missing today:** `orchestrator/combine_node.py:combine_kept` re-tests the best single change only when the combination fails (`if not greedy.holds`, around line 360).
- **Offline experiment and kill result:** replay the 12 rows' archived tips and best singles side by side, at 0 USD, as in `o62/replay.md`. **The mechanism dies if the tip is at least as good as the best single in at least 10 of the 12 rows.** L6 would then be a measurement artifact, and C1's timing fix is the remedy instead.

## Open questions for the seminar

1. **C1:** is "judge on the fresh look" a judge change, or a node choice? Who rules?
2. **Run-level multiplicity:** what false-keep rate across all the trials C1 re-looks is acceptable? Should it get a Pocock-style correction [13], or is the existing two-pass keep rule (first look plus confirmation) enough?
3. **C2:** does a re-ported keep count as the same idea or as a new trial in lessons and fates?
4. **C3:** do lanes emit ideas before or after their reasoning? Only the cut text says whether salvage can work.
5. **C4 and X2-DT:** a backlog carried across rounds conflicts with stacking's moving base. Which anchors survive the re-keying?
6. **Evidence:** the TRIZ evidence base is thin [10][11]. Should proposals that cite it carry a stricter pre-registered bar?

## Sources (numbered list, full citations with URL or ISBN)

1. Altshuller, G. (1999). *The Innovation Algorithm: TRIZ, systematic innovation and technical creativity*. Trans. L. Shulyak and S. Rodman. Technical Innovation Center. ISBN 0-9640740-4-4. [cat]
2. Altshuller, G. (1997). *40 Principles: TRIZ Keys to Technical Innovation*. Technical Innovation Center, Worcester MA. ISBN 0-9640740-3-6. [cat]
3. Savransky, S. D. (2000). *Engineering of Creativity: Introduction to TRIZ Methodology of Inventive Problem Solving*. CRC Press. ISBN 0-8493-2255-3. [cat]
4. Haines-Gadd, L. (2016). *TRIZ For Dummies*. Wiley. ISBN 978-1-119-10747-7. Appendix D: https://www.oreilly.com/library/view/triz-for-dummies/9781119107477/29_9781119107477-bapp04.xhtml. Also Lean Methods, "Split Your Innovation Problem Four Ways: Separation Principles", https://leanmethods.com/?p=1328. [sum]
5. Rea, K. C. (2001). "TRIZ and Software: 40 Principle Analogies", Parts 1 and 2. *The TRIZ Journal*, Sept. and Nov. 2001. https://metodolog.ru/triz-journal/archives/2001/09/e/index.htm (host blocked; [sum]). Mann (2008) on TRIZ for software: https://www.aitriz.org/articles/TRIZFeatures/323031312D30382D4D616E6E.pdf. [sum]
6. Goldratt, E. M. (1990). *What Is This Thing Called Theory of Constraints*. North River Press. ISBN 0-88427-166-8. Study guide by J. R. Martin: https://maaw.info/ArticleSummaries/ArtSumGoldratt90WhatTOC.htm. [sum]
7. Goldratt, E. M. (1994). *It's Not Luck*. North River Press. ISBN 0-88427-115-3. [cat]
8. Dettmer, H. W. (1997). *Goldratt's Theory of Constraints: A Systems Approach to Continuous Improvement*. ASQ Quality Press. ISBN 0-87389-370-0. [cat]
9. Mason, R. O. (1969). "A dialectical approach to strategic planning". *Management Science* 15(8), B403-B414. https://doi.org/10.1287/mnsc.15.8.B403. [sum]
10. Cosier, R. A., and Aplin, J. C. (1980). "A critical view of dialectical inquiry as a tool in strategic planning". *Strategic Management Journal* 1(4), 343-356. https://ideas.repec.org/a/bla/stratm/v1y1980i4p343-356.html. [sum]
11. Ilevbare, I. M., Probert, D., and Phaal, R. (2013). "A review of TRIZ, and its benefits and challenges in practice". *Technovation* 33(2-3), 30-37. https://doi.org/10.1016/j.technovation.2012.11.003. [sum]
12. Wald, A. (1945). "Sequential tests of statistical hypotheses". *Annals of Mathematical Statistics* 16, 117-186. https://doi.org/10.1214/aoms/1177731118. [sum]
13. Pocock, S. J. (1977). "Group sequential methods in the design and analysis of clinical trials". *Biometrika* 64(2), 191-199. The figures are from https://en.wikipedia.org/wiki/Pocock_boundary and https://online.stat.psu.edu/stat509/book/export/html/704. [sum; the volume and page details are from memory, not confirmed by a search result]
14. Johari, R., Koomen, P., Pekelis, L., and Walsh, D. (2017). "Peeking at A/B tests: why it matters, and what to do about it". KDD '17, 1517-1525. https://doi.org/10.1145/3097983.3097992. Preprint: https://arxiv.org/abs/1512.04922. [sum]
15. "Evaporating cloud". Wikipedia. https://en.wikipedia.org/wiki/Evaporating_cloud. [sum]

Engine evidence (read-only, `/home/user/step3-emergence-r1`):
- `orchestrator/confirm.py`
- `orchestrator/combine_node.py`
- `execution/combine.py`
- `optimization/evolve.py`
- `optimization/idea_portfolio.py`
- `optimization/idea_pipeline.py`
- `clients/structured.py`
- `common/config.py`
- `tests/live/ideas_x2.py`

The loss data come from the `w2-sprint/` pages and the ledger named above.
