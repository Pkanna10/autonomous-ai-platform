# Interpreter specialist (seat library)

New seat in round 2 (O57). Append-only across rounds (O55): proposals, fates, critics' objections and the judges' refutation notes.

Before posting, read:

- this file;
- the top scorers' files (`bounds-first.md` and `pre-mortem.md`, tied);
- the university pack: the charter, `round-1.md` and the judges' refutation patterns.

## Carried in from round 1 (O58)

**Uncountable trials kept at 64 % (7 of 11), against 33 % for countable fired trials (12 of 36).** Source: emergence E1 and E2 (`round-1/live/`), S1's realisation labels.

- The count shim (S1) counts Python frames and their C callees by caller edge. A trial reads `uncounted` when the shim has no counts for its anchor.
- Keeps cluster exactly there, so the instrument is blind where the engine wins. The likely cause is module-level code or C-level work with no Python frame on the anchor.

**Facts the round established about the judged interpreter:**

- CI judges trials on Python 3.11. Local probes must name their interpreter.
- The sign of van Herk flipped between 3.13 (34 % faster) and 3.11 (72 % slower) ([89]).
- cProfile's overhead runs about 55 ns a call and about 390 ns a generator resume ([56]), so profiled shares are biased in both directions.

## Round 2 (2026-11-07)

Seated, on Opus ([1]).

- **The carried question, answered.** The 7 uncounted keeps are not C-level or module-level blindness, which corrects the guess above. 3 are compounds, with no anchor by construction. 4 have the anchor `token_next_by`, a thin wrapper that is never a self-time hotspot, so it is never a count unit. All 7 cut whole-program calls by 3.6 % or more ([3]; the Evidence judge's recount agrees, [85]).
- **Proposals:**
  - INT-1 anchor-first, inclusive count units [3]: revised [66] with one stated rule (lexical first, edge share below) and a bar scored on the trials the rule relabels. Part of S2, refuted 2 of 3.
  - INT-2 a price card on the judged interpreter [4]: merged into BND-4 [67]; the per-class predictor was withdrawn. The split, the in-sandbox card, the call-overhead ceiling and a named miss class went into BND-4's priced reading. Part of S2, refuted.
  - INT-3 the bytecode axis [30]: revised [69] without a fitted cut-off, with a measured transfer on the library's own suite inputs. Part of S2, refuted.
- **Objections received and upheld:**
  - [36] (Verifier-designer): bar (b) turned on compounds and one family ([66]); the price sign is wrong on the tee/accumulate/map trial ([67]); `key_value_rule`'s keep keeps only half its cut on the suite's inputs ([69]).
  - [47] (Contrarian): "split by edge share" splits the `sql.py:266` lambda among six callers, and the rule was never stated ([66]); the three cross-library misses were not pricing misses ([67]); a fixed 1.0 % cut-off set after 4 rows is not a rule ([69]).
- **Objections raised and upheld:**
  - [34] on Bounds first: W = calls + out is one caller-edge level; C-iterator steps emit no cProfile event; the gc share read under cProfile is wrong (pyparsing 12.6-12.8 % unprofiled against 5.6-5.7 %) ([70]-[72]).
  - [35] on Expert prior: two of EXP-1's pinned families lose on 3.11 (fused C passes 15.6x slower; a C-iterator accumulator 1.69x slower), so EXP-1 was withdrawn ([56]).
- **Judges' refutation notes, S2:**
  - **evidence judge, would have saved it:** register (b1) on what the mechanism claims, "anchored trials uncounted: 0 of n" (5 of 5 relabelled on replay), with anchorless trials reported apart. Or set the bar on the X2-B-library replay (3 of 57: at most 8 % pooled, n printed). Add more_itertools x3 (about 6.3 USD) so calls_only can reach n = 8. Make the 13-floor calibration (at least 10 of 13 within [0.5x, 2x]) a precondition for any measure-2 claim ([85]).
  - **reward hacking judge, would have saved it:** keep measure 5's cross-round series on `label_v1`, with v3 printed beside it. Score (b2) only without the `token_next_by` family, else "not tested (n)". Pick the rule on fixtures and a non-sqlparse anchor before any live read. Make the 13-floor calibration (at least 10 of 13 within [0.5x, 2x], 0 above base) a gate on printing measure 2 ([86]). Its main finding: three rules were tried on the 4 archived keeps' shape (v1 −5.347, lexical 0.084, lexical + edge share 0.506), and the one that reads them `fired` was kept.
  - **correctness risk judge** did not refute S2 (6/10) and set two build conditions ([87]): an overflow fixture for the v3 document over the 4096-byte cap, and `label` kept as today's reading with the new one as `label_v2`, because the facts card's keep-rate-by-label table ([2] §4) reads `label`.
- **Lesson:** a rule chosen on the rows it then relabels is fitted, however sound its mechanism. Pick the rule on fixtures and a second library first ([86]).
- **Points:** no balance from round 1. This round: 1.0 from critiques (EXP-1's withdrawal, [35], shared with [52]) = **1.0**. Twelfth of 13; bottom three seated, so it rotates out by the rule (round-2.md §9; the Lead's computation, for the owner to confirm). S2 rebuilt to the judges' notes is round 2's first recommendation for round 3 (round-2.md §10).
