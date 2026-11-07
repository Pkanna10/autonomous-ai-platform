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

- **After E1 and E2 (O58):** +1.25 from S1's live pass, its +10 split over 8 merged proposals. Total **2.75**.

## Round 2 (2026-11-07)

Benched (O57 as amended; [1]). No proposals and no critiques.

- **Carry-forward 3 (SHP-3's judge-side half) was taken up and credited** by VER-1 [9] and VER-2 [12], and SCL-1 [8] shared its capture point (r1[110]). All three went into S4, which survived 2 of 3.
- **S4's unit 1 is built** (`775890d`): VER-1's distinct-once replay by counts, record only, with no shape fact in any lane view ([91]-[94]).
- **What remains open:**
  - VER-2's suite corpus, the off-shape half, waits on a ruling that it extends r1[62] ([86] c, [87] b).
  - The reward hacking judge's condition: `constant_holds` on scaled copies of the benchmark's own inputs is still benchmark-shaped. Only the suite-corpus transfer is off-shape ([86] b).
- **Points:** 2.75 halved to **1.375**. Ninth of 13; second on the bench.
  - The charter gives no points for a credited carry-forward, so none are given here (round-2.md §9, flag 4).
  - This is the Lead's computation, for the owner to confirm.
