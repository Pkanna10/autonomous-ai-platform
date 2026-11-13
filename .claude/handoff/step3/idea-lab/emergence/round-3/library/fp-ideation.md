# fp-ideation: first principles (cost atoms, Fermi, speed of light, Amdahl)

**Access note.** Page fetches were blocked in this session (`lawwu.github.io` and `webarchive.library.unt.edu` failed DNS). So every public source below was checked through web-search abstracts and summaries, not read in full. Where only a secondary account was available, I say so. Archive numbers marked [A] come from the round's own files or from my read-only scripts over `w2-sprint/live/*.jsonl` (63 runs, X2-SV left out). The scripts are in `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/fp-ideation/` (`a.py`, `b.py`, `c.py`).

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **Amdahl (1967).** The serial fraction bounds the speedup. It is the origin of "speed-up is limited by the part you do not touch" [1].
2. **Gustafson (1988).** The counter-argument that the problem size grows, so the serial fraction is not fixed. It is the standard rebuttal to Amdahl [2].
3. **Williams, Waterman and Patterson (2009), Roofline.** A speed-of-light bound: attainable performance = min(peak compute, bandwidth × intensity). It is the canonical bound model in HPC courses [3].
4. **Hennessy and Patterson, 6th ed. (2017).** The quantitative design textbook. Its chapter 1 is where Amdahl's law is usually taught; I could not confirm the passage [4].
5. **Bentley, "The Back of the Envelope" (CACM column, 1984; Programming Pearls 2nd ed.).** Fermi estimation for programmers, the rule of 72 and safety factors [5].
6. **Fermi (1945), Trinity observations.** The documented Fermi estimate: a yield of 10 kt from paper scraps dropped into the blast wave [6].
7. **Musk's first-principles cost breakdowns.** Battery $/kWh priced from commodity materials; rocket materials as a small share of the price. Primary recordings were not accessed; only secondary accounts [7][8][9].
8. **Hanley and Lippman-Hand (1983).** The rule of three: 0 events in n trials gives a 95 % upper bound of about 3/n. It is the standard zero-numerator bound [10].
9. **Weitzman (1979), Pandora's box.** The optimal order and stopping rule for costly inspection of alternatives: each box gets a reservation price [11].
10. **Howard (1966), information value theory.** Price an experiment by the decision gain it buys. It is the founding paper of decision analysis [12].
11. **Goldratt and Cox, The Goal (2004).** Theory of constraints: throughput is set by the bottleneck, and gains elsewhere are a "mirage" (secondary summaries only) [13].

## Notes (the methods and results, cited inline as [n])

**Method.** Break a loss into atoms, price each atom, take the sum as the floor, and read the gap as measured minus floor.
- Musk's battery case: packs cost about $600/kWh around 2006; the constituent materials priced on the London Metal Exchange came to about $80/kWh. The gap was process, not physics [7] (secondary accounts only).
- Rockets: propellant is put at about 0.3 % of a Falcon 9's price [8], and materials at about 2 % of a typical rocket price [9] (secondary).
- The "idiot index" is the ratio of a finished part's cost to its raw materials. A high ratio marks a process gap [9] (secondary).
- Read for the engine: the floor is what physics or statistics forces, and anything above it is process.

**Fermi estimation.**
- Fermi got about 10 kt from roughly 2.5 m of paper drift [6]. A later radiochemical figure of about 18.6 kt is quoted in secondary coverage, which I did not verify at primary.
- Lesson: a factor-of-two estimate is enough to rank options. Bentley teaches the same, with safety factors from Vyssotsky: derate by 2, 4 or 6, and be conservative by 2 to 4 on size and cost [5].

**Speed of light and Amdahl.**
- Speed of light: bound the attainable result first, then measure the distance to the bound [3].
- Amdahl: editing a fraction f of the runtime yields at most a 1/(1−f) speed-up [1].
- Gustafson: the fraction moves with problem size, so the bound is only as good as the workload [2]. This bears directly on L10 and on the exam's "visible only at realistic sizes" plants.

**Zero numerators.** When nothing was seen in n tries, the 95 % upper bound on its rate is about 3/n (valid for n > 30) [10]. This sizes truncation tails and rare failures.

**Pricing an untried idea.**
- Howard: the value of information is the gain from acting with knowledge minus the gain from acting without it [12].
- Weitzman: give each box a reservation price z where c = E[max(X − z, 0)]; open boxes in order of z; stop when the best reward found exceeds every unopened z [11].
- Goldratt: rank stages by the throughput they cap, not by local efficiency [13].

**Established and contested.**
- Established: the Amdahl bound itself [1]; roofline as a bound [3]; the rule of three [10]; Weitzman's index under his assumptions [11].
- Contested:
  - Amdahl against Gustafson on which fraction to use [2].
  - Roofline is described as "insightful rather than perfect" [3].
  - The Musk figures rest on secondary retellings [7][8][9].
  - Weitzman assumes independent boxes, known distributions and a payoff equal to the best single box. The engine's payoff is additive, with conflicts. So the index is a heuristic here, not an optimum.

## Bearing on the ledger (per row you touch: L#, what your field says, numbers)

**Atoms priced from the archive [A]:**
- **Marginal trial cost.**
  - Editor cost: 0.083 USD median, computed as (cost − discovery cost) / trials.
  - Measured time: 70.6 s median per trial.
  - Trials: 15.5 per run.
  - The run's cap is 12.9 USD against 3.07 USD spent. That leaves 8.9 USD of headroom, and no run was unaffordable [A ideas-fate].
- **Value of an extra applied keep.**
  - (delivered − best single keep) / (applied − 1) has a median of **+3.45 pp** (54 runs with 2 or more applied). This assumes the best single keep is among those applied.
  - The median single keep gains about 5.7 pp, so keeps compose at about 0.6.
- **Fraction of keeps applied.** 3.0 of 4.51 per run (0.67). The round-2 unique-to-raw ratio is 0.45 [A zero-credit s2].
- **Value of a raw extra keep from a late idea.** 0.45 × 3.45 ≈ **1.6 pp** (2.3 pp at 0.67).
- **Keep rate per trial by lane, all arms.**

| Lane | Keep rate | Median keep gain |
| --- | --- | --- |
| leap | 0.57 | 10.9 |
| obvious | 0.30 | 5.3 |
| recombine | 0.28 | 6.3 |
| name_the_problem | 0.26 | 8.3 |
| far | 0.22 | 10.6 |
| resolve_tradeoff | 0.21 | 3.3 |
| assume_less | 0.14 | 3.5 |
| eliminate | 0.04 | 9.8 |

- **L1, Weitzman/Howard.**
  - A typical idea dropped at s4b would have kept with p ≈ 7.67/35 = 0.22, worth 0.22 × 1.6 ≈ 0.35 pp.
  - At 0.083 USD that is **0.24 USD per point**, against the engine's average of 0.176 USD per point (3.07 / 17.4).
  - The reservation price differs widely by lane: a leap idea costs about 0.09 USD per point, an eliminate idea about 1.3 USD per point.
  - So L1 is a pricing and budget choice, not a correctness floor.
- **L2, Bentley and the rule of three.**
  - The cap was 12,000 against a longest Opus reply of 10,891: a safety factor of only 1.1.
  - Bentley's factor of 2 or more gives the 24,000 that o62 proposes (2.2×).
  - The rate is 3/32 = 9.4 %, with an exact 95 % CI of 2.0 % to 25 %.
- **L10, Amdahl/Gustafson.** If the edited hot set is a fraction F of benchmark time, the engine's ceiling is F, whatever the ideation. The expert-practice seat's share s of expert gain outside the edited functions is exactly the 1−F atom.
- **Ranking, Goldratt.** Rank rows by the gain they cap. L9 is not a stage: it is the run-to-run sum of L1, L3 and L5.

## Floors (L1, L2) and ranking

### L1: ideas that never become trials (110 of 163)

**Atoms and their floor:**

| Atom | Ideas | Floor | Why |
| --- | --- | --- | --- |
| True duplicates: s3 `duplicate_of`, s4a `duplicate` + obvious signature | 24 + 9 + 4 = 37 | 37 in count, about 0 pp | A duplicate carries no unique gain; L5 shows repeats come back as conflicts, so dedupe is under-applied, not over-applied |
| Ideas with no locatable anchor (u = share of the 31 `ungrounded` truly unanchorable) | 31u | 0 pp | No anchor, nothing to edit |
| Reply field errors | 6 | 0 pp | Re-asking the lane costs about 0.08 USD a call (my estimate: 1.68 USD discovery cost over about 20 calls a run) |
| Budget-bound drops (s4b quotas) | 35 | 0 pp under the USD cap | All 35 cost about 2.9 USD over 4 runs (0.73 USD a run) against 8.9 USD of headroom |

- **Wall-clock price of the s4b atom:** about +22 minutes per run, about 8.75 trials at about 2.5 minutes each all-in.
- **If the trial count is held fixed (about 15.5) instead:** the best lane-level allocation would add only about 1.9 keeps over 4 runs, ≈ **0.75 pp a run**. Under that constraint the floor is about 2.3 pp a run.

**Floor:** about **0 pp of delivered gain** (37 + 31u ideas in count) under the current USD cap; about 2.3 pp a run if the trial count is frozen.

**Gap, as expected keeps × 1.6 pp:**
- s4b: 7.67 keeps / 4 runs × 1.6 ≈ **3.1 pp a run**.
- Fixable ungrounded ideas: 2.3 keeps a run × 1.6 × (1−u). With 1−u between 0.25 and 0.5 this is 0.9 to 1.9 pp.
- Reviewer false positives: 0.2 pp or less (assuming at most 10 %).
- **Gap ≈ 3 pp a run (range 1 to 5)**, against a median delivered +17.4.
- This leans high: the keep rates are in-sample, and the marginal value falls as the applied count rises. The X2-P hint that 24 of 36 untrialled ideas share a function with a trialled idea points the same way.

### L2: truncated leaps (Opus 3 of 32; Fable 1 of 6)

**Atoms:**

| Atom | Value |
| --- | --- |
| Truncation rate (Opus at 12k) | p = 0.094 (CI 0.02 to 0.25) |
| Leap calls per run | X2-0: 2; X2-D: 3 |
| Loss per truncation | The round's leap trial: 0.56 keep rate (X2-0 9/16, X2-D 16/28) × 1.6 pp × 11/5.7 (leap keeps are larger) ≈ 1.7 to 2.5 pp, less a replacement slot (≈ 0.3 pp), so ≈ **1.8 pp net** |
| Measured loss | 2 × 0.094 × 1.8 ≈ **0.34 pp a run** (X2-0); ≈ 0.5 pp (X2-D); 0.07 to 1.35 pp over the CI |

**What a correct engine needs to remove it:**
- a cap at 2× or more the longest reply;
- a retry on `max_tokens`;
- or a parse that keeps the complete ideas from a cut reply.

Today `read_reply` discards any reply whose stop is not `end_turn` (`clients/structured.py`).

**Prices:**
- **A bigger cap:** billed only as produced. At most 0.24 USD per stopped call, an expected 0.023 USD per call, plus a 0.24 USD pre-flight reservation against 8.9 USD of headroom.
- **A longer timeout:** 951 s against 300 s today.

**Residual risk:**
- The engine's own config says thinking counts toward `max_tokens`, so a cut reply may hold no text at all, and salvage is not guaranteed.
- No uncensored reply above 16,886 has been seen in the E1 probes (0 of 32). The rule of three then bounds the tail beyond that only at 9.4 % or less, which is weak at this n.
- The Fable stop at 32k hints at a heavy or degenerate tail.

**Floor ≈ 0.0 to 0.05 pp a run** (it costs at most a retry, ≤ 0.3 USD). **Gap ≈ the whole measured loss, about 0.35 to 0.5 pp a run.** It is small, but the cheapest row to close.

### Ranking by estimated gap in delivered gain (pp per run)

| Rank | Row | Gap | Basis | Confidence |
| --- | --- | --- | --- | --- |
| 1 | L9 (composite, not additive) | ~9 | Max minus median per library: 19.6, 8.9, 7.6, 8.9; floor about 2 pp from the combine's measurement noise | High that it is largest; it double-counts L1, L3, L5 |
| 2 | L10 | unknown | Amdahl: the ceiling is F; awaits the expert-practice seat | Low |
| 3 | L1 | ~3 (1 to 5) | Above | Medium |
| 4 | L5 | ~1.7 (0.8 to 3.5) | 62/39 runs = 1.59 a run × 63 % not same-technique × ~0.5 of 3.45 (overlapping hunks compose worse); O62 markdown lost keeps of 15.97 and 15.3 to conflicts and delivered 10.56 | Medium |
| 5 | L3 | ~0.7 (1.2 against quiet floors) | 0.75 a run × ~0.6 real × 0.67 × 2.3 | Medium |
| 6 | L4 | ~0.8 (0.2 to 1.5) | 0.78 a run; gains unrecorded | Low |
| 7 | L6 | ~0.3 to 0.6 | 12 runs, mean shortfall 3.28, gives 0.62 a run as an upper bound; part is regression to the mean of the best single, about 1σ ≈ 1.2 pp | High on the bound |
| 8 | L2 | ~0.35 to 0.5 | Above | Medium-high |
| 9 | L8 (beyond L5) | ~0.15 | ~0.4 repeat slots a run × 0.35 pp; exhaustion of opportunities is the floor | Medium |
| 10 | L7 | ~0.13 | 8.5 pp / 63 runs | High |

- The order of L1 against L5, and of L3 against L4, is within the error.
- L9 should be read through reviewer seed (a), the union of proven diffs, which measures how much of it is recoverable.

## Open questions for the seminar

1. Should the floor be set under a fixed USD cap, a fixed trial count or a fixed wall clock? L1's floor moves from 0 to about 2.3 pp a run with that choice.
2. Does a truncated leap reply hold complete ideas, or only thinking? A record of thinking against text tokens would price L2's salvage atom.
3. What is F, the hot set's share of benchmark time, per library at realistic sizes (Gustafson)? It is L10's speed-of-light.
4. Does the lane keep rate hold for the ideas the quotas drop? An offline replay of ranked fates would test Weitzman's ordering.
5. How much of L9 is ideation variance and how much measurement? The combine floors put the measurement part at about 2 pp.

## Sources (numbered list, full citations with URL or ISBN)

1. Amdahl, G. M. "Validity of the single processor approach to achieving large scale computing capabilities." AFIPS Spring Joint Computer Conference, 1967, pp. 483-485. doi:10.1145/1465482.1465560; https://www3.cs.stonybrook.edu/~rezaul/Spring-2019/CSE613/reading/Amdahl-1967.pdf (abstract and metadata only).
2. Gustafson, J. L. "Reevaluating Amdahl's law." Communications of the ACM 31(5), 1988. doi:10.1145/42411.42415; https://users.cs.utah.edu/~hari/teaching/paralg/Gustafson88.pdf (summary only).
3. Williams, S., Waterman, A., Patterson, D. "Roofline: an insightful visual performance model for multicore architectures." Communications of the ACM 52(4), 2009, pp. 65-76. doi:10.1145/1498765.1498785; https://escholarship.org/content/qt78h8v7mr/qt78h8v7mr.pdf.
4. Hennessy, J. L., Patterson, D. A. *Computer Architecture: A Quantitative Approach*, 6th ed. Morgan Kaufmann, 2017. ISBN 978-0-12-811905-1 (chapter text not verified).
5. Bentley, J. "Programming Pearls: The Back of the Envelope." Communications of the ACM, 1984 (the search sources disagree on February or March); scan at https://gwern.net/doc/math/1984-bentley.pdf; reprinted in *Programming Pearls*, 2nd ed., Addison-Wesley, 2000, ISBN 0-201-65788-0.
6. Fermi, E. "My Observations During the Explosion at Trinity on July 16, 1945." https://www.atomicarchive.com/resources/documents/trinity/fermi.html; OSTI history page https://osti.gov/opennet/manhattan-project-history/Events/1945/trinity.htm.
7. Musk, E., interview with Kevin Rose (Foundation, about 2012), as reported in "Elon Musk Lifted A Problem-Solving Skill From Aristotle," CleanTechnica, 2019. https://cleantechnica.com/2019/10/12/elon-musk-borrowed-problem-solving-skill-aristotle/ (secondary; primary not accessed).
8. Anderson, C. "Elon Musk's Mission to Mars." Wired, October 2012. http://www.wired.com/2012/10/ff-elon-musk-qa/all (archived copy not reachable; the 0.3 % figure comes via secondary search summaries).
9. Isaacson, W. *Elon Musk*. Simon & Schuster, 2023. ISBN 978-1-9821-8128-4 (the idiot index and 2 % figures come via secondary summaries, e.g. https://grahammann.net/book-notes/elon-musk-walter-isaacson).
10. Hanley, J. A., Lippman-Hand, A. "If nothing goes wrong, is everything all right? Interpreting zero numerators." JAMA 249(13), 1983, pp. 1743-1745. https://jamanetwork.com/journals/jama/article-abstract/389714.
11. Weitzman, M. L. "Optimal Search for the Best Alternative." Econometrica 47(3), 1979, pp. 641-654. https://scholar.harvard.edu/sites/scholar.harvard.edu/files/weitzman/files/optimalsearchbestalternative.pdf.
12. Howard, R. A. "Information Value Theory." IEEE Transactions on Systems Science and Cybernetics SSC-2(1), 1966 (metadata and secondary definition only).
13. Goldratt, E. M., Cox, J. *The Goal: A Process of Ongoing Improvement*, 3rd rev. ed. North River Press, 2004. ISBN 978-0-88427-178-9 (secondary summaries only).

[A] The engine's archive (`.claude/handoff/step3/idea-lab/`):
- `emergence/round-3/ledger.md`
- `w2-sprint/o62/README.md`
- `w2-sprint/o61/README.md`
- `w2-sprint/ideas-fate/README.md`
- `w2-sprint/floors/README.md`
- `w2-sprint/zero-credit/README.md`
- `w2-sprint/live/*.jsonl`, with my computations in the scratch scripts named above.
- Engine code: `services/python_agents/src/autonomous_ai_agents/clients/structured.py` (`read_reply`) and `common/config.py`.
