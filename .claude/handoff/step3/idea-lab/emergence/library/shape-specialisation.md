# Shape specialisation (seat library)

Model in round 1: Opus 5.5.

Append-only across rounds (O55): proposals, fates, critics' objections and the judges' refutation notes. Before posting, a seat reads this file, the round's top scorer's file and the university pack: the charter, the last round report and the judges' refutation patterns.

## Round 0: the superseded first Phase 1

No seat owned these. See `round-0.md`; they are part of round 2's Contrarian pack.

## Round 1 (2026-11-06)

- **Proposals:**
  - SHP-1 shape probe [44]: revised [108], became S4, refuted 2 of 3.
  - SHP-2 coverage checks [45]: merged into BND-X [109], part of S1. Its caller edges are built: 99.6 % of `re.Pattern.match` is from `get_tokens`.
  - SHP-3 off-shape check [60]: revised [110], part of S4.
- **Critics' objections:**
  - [71] and [73]: coverage selects for the benchmark's shape; the idna PVALID predicate was false as written.
- **Judges' refutation notes, S4:**
  - **evidence judge, would have saved it:** Two offline results on 3.11, at 0 USD. First, the base-vs-base A/A pass on the 8 libraries at their pins, posted with per-class spread under 2.5%, so the max(5%, 2x spread) threshold can be crossed, and a non-vacuous class on at least 6 of 8 libraries. Second, the coverage and penalty reading reproduced on a second library with a known right-grain vs wrong-grain pair (for example sqlparse's _group_matching skips), or on DC's 20 patches, where a known benchmark-shaped patch is labelled and the sound ones are not. Both tied to a named charter measure, rather than a K3 prediction.
  - **reward hacking judge, would have saved it:** Ship perturb and observe as a pure detector, with no shape facts in any lane prompt and no coverage gate. Then three pieces of evidence. (1) An offline, 0 USD replay of X2's 59 archived keeps under perturb, with the A/A spread measured first on base against base on the 8 libraries. It must show the divergent and miss_penalty labels firing above that spread on keeps known to be shape-fit and not on the rest. (2) In any later facts arm, a pre-registered bar: the share of keeps labelled shape_fit, divergent or miss_penalty does not rise against X2-0 beyond the A/A spread. (3) Keeps so labelled are excluded from the arm's kept and combine counts when it is read against the twin band.
- **Points:** 0.5 (S1) + 1.0 from critiques (BND-1's merge) = **1.5**. Round 2: bottom three, rotates against the bench. The Lead carries SHP-3's perturb half alone into round 2.
