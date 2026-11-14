# O65 item 2: combine-order replay, 2026-11-14

**Choices compared.** (a) is today's score order. (b) is the `SITE_STACKS="on"` gain-ordered choice. The archived held combines were replayed offline on GitHub runners, with no request and no spend.

**Runs.** Dispatches 43567670887 (sqlparse), 43567673362 (markdown) and 43567675481 (mistune, tomli), on `2aa8bed`. The rows are in `live/combine-order-43567670887-43567673362-43567675481.jsonl`.

**Scope.**
- 60 held-or-failed archived runs had two or more keeps (X2-SV aside). Of these, 58 were measured.
- 2 were excluded because today's set failed its re-test: X2-D-43159154661 mistune (its fallback was delivered) and X2-D-43145496896 mistune (nothing was delivered). The gain-ordered choice cannot be measured on them, and the exclusion does not favour it.
- All 58 runs completed.
- Two tomli runs (X2-L-43151990527, X2-P-43107418692) cannot be proven greedy deliveries. They are measured and flagged.

**How it was measured.** Both choices go through the combine node's own re-test, hold and fallback rules. Delivered gain is the set's gain if it held, else the fallback single's, else 0. Looks run a, b, b, a. A difference counts as "clear" only when it is past the largest floor among both choices' looks.

**Caveat.** (b) orders on each keep's first-look gain, because the archive has no `confirmed_gain`. That is noisier than the engine's mean-of-two order.

## Results

| | today's order (a) | gain order (b) |
| --- | --- | --- |
| mean delivered gain over 58 runs | 19.06 % | 21.35 % |
| sum of delivered gains | 1105.5 | 1238.5 (+12.0 %) |
| runs preferring it, of the 27 that differ | 5 (1 clear) | 22 (12 clear) |
| set re-tests that did not hold | 0 of 116 | 0 of 54 |
| stronger single of a conflict pair kept (decided pairs) | 43 of 88 | 76 of 89 |
| stronger single kept, past the floor | 16 of 37 | 39 of 40 |

- In 31 of the 58 runs both choices select the same tree.
- Over the 27 runs that differ, b − a is +4.93 points on average (median +1.77). b is higher in 22 runs and a in 5.
- No fallback was used, and no look lost its rows, so delivered gain equals raw set gain on both sides.

| library | runs | same | b preferred (clear) | a preferred (clear) | b − a over differing runs | mean a / b |
| --- | --- | --- | --- | --- | --- | --- |
| sqlparse | 16 | 9 | 6 (4) | 1 (0) | +8.18 | 24.7 / 28.3 |
| tomli | 14 | 10 | 4 (0) | 0 | +1.21 | 16.2 / 16.6 |
| mistune | 13 | 7 | 3 (1) | 3 (0) | +0.91 | 17.0 / 17.5 |
| markdown | 15 | 5 | 9 (7) | 1 (1) | +6.55 | 17.5 / 21.8 |

- **Runs where a was preferred:** X2-P-43104077245 markdown (−2.8, clear), and four inside the floor: X2-D-43145496896 sqlparse (−1.4), and three mistune runs (−0.2, −0.5, −0.4).
- **Largest b wins:** +17.0 (X2-0-43093762527 markdown), +14.4 (X2-0-43093762527 sqlparse), +13.9 (X2-L-43151986627 sqlparse), +13.9 (X2-0-43093767768 sqlparse), +13.2 (X2-P-43114988674 sqlparse).

## Reading
- The gain-ordered choice delivers more in 22 of the 27 runs where the two differ. It is clearly better in 12, and clearly worse in 1.
- Its edge sits in sqlparse and markdown, the two libraries with the most conflicts. tomli and mistune differ little.
- It keeps the stronger side of a conflict far more often: 39 of 40 resolvable pairs past the floor, against 16 of 37 for today's order. Today's score order is close to a coin flip on conflicts.
- Neither choice ever failed to hold. In this archive, ordering by gain cost no delivery.
