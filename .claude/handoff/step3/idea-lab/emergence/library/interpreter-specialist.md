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
