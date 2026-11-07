# Ten-x (seat library)

Model in round 1: Opus 5.5.

Append-only across rounds (O55): proposals, fates, critics' objections and the judges' refutation notes. Before posting, a seat reads this file, the round's top scorer's file and the university pack: the charter, the last round report and the judges' refutation patterns.

## Round 0: the superseded first Phase 1

No seat owned these. See `round-0.md`; they are part of round 2's Contrarian pack.

## Round 1 (2026-11-06)

- **Proposals:**
  - TNX-1 chains [46]: merged into TNX-2 [86].
  - TNX-2 the stacked step [88]: became S5, refuted 3 of 3.
  - TNX-3 site stacks [59]: revised into the combine unit [92], host of S2 (built).
- **Critics' objections:**
  - [74]: stacked acceptance reads a difference of two confirmed looks against a single-look floor; part 2 loses the better alternative.
  - [84]: each step's size is set by the benchmark's input shape; after the master regex, 76-81 % of the lexer's time is in C.
- **Judges' refutation notes, S5:**
  - **evidence judge, would have saved it:** Three things. First, S1's per-unit shim built and its counts reproduced at the pins (gate a), so the qualifier count comes from engine counts, not a probe. Second, an archive showing qualifiers on at least 3 libraries at 0.5 or more a run, so (c) can reach '>= 3 tried'. Third, an offline editor-free replay of the two tomli qualifiers stacked on their parents, timed on 3.11 at N >= 5 with a combined gain above X2-0's +22.6% by more than 4.0 points, which shows the tomli plateau is not a ceiling.
  - **correctness risk judge, would have saved it:** A fake-git fixture on execution/fakes.py with a kept parent at score 0.6 and an accepted step at score 0.0 whose tree edits the parent's hunk: assert the step is delivered, the parent recorded superseded_by and skipped, and the pair counted once in kept; the same fixture with a replay start showing NOTHING_LEFT; and the dependency on S2 part 2 (or an explicit exclusion in kept_changes) stated in the unit, with combine_node.py in its file list.
  - **reward hacking judge, would have saved it:** Four pieces of evidence. (1) A second tagged tomli A/A pair, so the band is not n = 1, together with a pre-registered bar of >= 2 accepted steps over >= 2 tomli runs, each above X2-0 by more than the larger of the two measured tomli gaps. (2) A fake-git test that an accepted step marks its parent superseded_by (S2), so wins per run count it once. (3) An acceptance clause on an engine-computed count floor, not the lane's. (4) An offline replay of the 4 archived qualifiers ([88]) on the per-label shim, showing their remaining counted gap is above 2 % of base calls on CI's 3.11.
- **Points:** 0.8 (S2) + 2.0 from critiques (EXP-2's withdrawal, EXP-3's merge) = **2.8**. The Lead carries S5, rebuilt on S2, into round 2.

- **After E1 and E2 (O58):** no change: none of this seat's proposals had a live pass. Total **2.8**.

- **Round 2 (O57 as amended):** benched, first in line. S5, the stacked step, is a carry-forward in every seat's university pack (`round-2/university-pack.md`), so any seat may take it up.

## Round 2 (2026-11-07)

Benched (O57 as amended; [1]). No proposals and no critiques.

- **Carry-forward 1 (S5) was taken up three times, credited:** PRM-4 [15], INV-4 [20] and INV-5 [21].
  - INV-4 was withdrawn [55].
  - INV-5 and PRM-4 went into S5, with ANA-5 and PRM-6, and S5 was refuted 3 of 3 again ([85]-[87]).
- **Why, this time:**
  - the 0.35 acceptance rate is cross-run spread on one library ([85]);
  - the +10 bar counted in-run events, not the combine against the twin ([86]);
  - a second trial under one hypothesis id misreports the row writer and writes a second lesson ([87]).
- **What would save it** (`pre-mortem.md` and `inversion.md` hold the full notes):
  - sqlparse x5 against x5 twins with a combine bar ([85], [86]);
  - a same-diff control ([86]);
  - the two-trial row-writer fixture ([87]).
- **Points:** 2.8 halved to **1.4**. Eighth of 13; first on the bench (round-2.md §9; the Lead's computation, for the owner to confirm).
