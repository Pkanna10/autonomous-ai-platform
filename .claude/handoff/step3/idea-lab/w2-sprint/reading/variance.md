# X2 variance: the A/A pool with the read arm left out (emergence round 2, S1)

- **The pool.** Per library, the runs of the arms whose requests and delivery are X2-0's (X2-0, X2-0', X2-C), frozen before any run; a run is never read against its own arm's runs.
- **Rank, not range.** Each run prints its position j among the pool's k draws and itself, and the null rate of a position as extreme, 2 min(j, k + 2 - j) / (k + 1); a library call needs k 39 for 0.05.
- **The arm call.** Each run's sign against its library's pool lower median; the exact null deals each library's draws anew, so an arm's runs on one library are not counted as independent; fewer than 6 signs read not tested (n). The call reads one p, two-sided (2 x the smaller tail, at most 1), fixed before any run; the two tails print beside it.
- **Ruling.** O51 as amended and O52 stay the ruling reading (x2.md); this page is printed beside them. O51's form, the arm left out: kept against X2-0's mean beyond the pool's range floored at 1.

## 1 The pool

| library | k | kept | combine |
| --- | --- | --- | --- |
| idna | 1 | 3 | +13.5 |
| markdown | 4 | 4, 5, 6, 7 | +10.1, +10.4, +11.9, +16.6 |
| mistune | 4 | 4, 5, 6, 7 | +13.5, +15.6, +16.2, +18.3 |
| more_itertools | 1 | 2 | +7.8 |
| pyparsing | 2 | 1, 1 | +2.8, +5.5 |
| sortedcontainers | 2 | 2, 2 | +10.2, +13.4 |
| sqlparse | 5 | 4, 5, 7, 7, 9 | +15.2, +18.5, +21.1, +25.7, +39.8 |
| tomli | 5 | 2, 3, 4, 6, 6 | +11.8, +17.4, +18.6, +22.6, +24.8 |

## 2 Each run against the pool, its arm left out

| file | arm | library | k | kept | kept rank | rate | combine | combine rank | rate | O51's form (kept) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ideas-x2-X2-0-43080309535.jsonl | X2-0 | tomli | 1 | 4 | 1 of 2 | 1.00 | +24.8 | 2 of 2 | 1.00 | n/a |
| ideas-x2-X2-0-43085609944.jsonl | X2-0 | tomli | 1 | 3 | 1 of 2 | 1.00 | +11.8 | 1 of 2 | 1.00 | n/a |
| ideas-x2-X2-0-43085609944.jsonl | X2-0 | mistune | 0 | 4 | - | - | +18.3 | - | - | n/a |
| ideas-x2-X2-0-43085609944.jsonl | X2-0 | sqlparse | 1 | 5 | 1 of 2 | 1.00 | +25.7 | 2 of 2 | 1.00 | n/a |
| ideas-x2-X2-0-43085616371.jsonl | X2-0 | tomli | 1 | 2 | 1 of 2 | 1.00 | +17.4 | 1 of 2 | 1.00 | n/a |
| ideas-x2-X2-0-43085616371.jsonl | X2-0 | mistune | 0 | 7 | - | - | +16.2 | - | - | n/a |
| ideas-x2-X2-0-43085616371.jsonl | X2-0 | markdown | 0 | 7 | - | - | +11.9 | - | - | n/a |
| ideas-x2-X2-0-43093762527.jsonl | X2-0 | mistune | 0 | 5 | - | - | +15.6 | - | - | n/a |
| ideas-x2-X2-0-43093762527.jsonl | X2-0 | sqlparse | 1 | 4 | 1 of 2 | 1.00 | +15.2 | 1 of 2 | 1.00 | n/a |
| ideas-x2-X2-0-43093762527.jsonl | X2-0 | markdown | 0 | 4 | - | - | +10.1 | - | - | n/a |
| ideas-x2-X2-0-43093767768.jsonl | X2-0 | sqlparse | 1 | 7 | 1 of 2 | 1.00 | +18.5 | 1 of 2 | 1.00 | n/a |
| ideas-x2-X2-0-43093767768.jsonl | X2-0 | markdown | 0 | 5 | - | - | +16.6 | - | - | n/a |
| ideas-x2-X2-D-43085621843.jsonl | X2-D | tomli | 5 | 4 | 3 of 6 | 1.00 | +21.1 | 4 of 6 | 1.00 | inside |
| ideas-x2-X2-D-43085621843.jsonl | X2-D | sqlparse | 5 | 2 | 1 of 6 | 0.33 | +36.1 | 5 of 6 | 0.67 | inside |
| ideas-x2-X2-D-43085626757.jsonl | X2-D | mistune | 4 | 3 | 1 of 5 | 0.40 | +18.4 | 5 of 5 | 0.40 | inside |
| ideas-x2-X2-D-43085626757.jsonl | X2-D | markdown | 4 | 3 | 1 of 5 | 0.40 | +9.9 | 1 of 5 | 0.40 | inside |
| ideas-x2-X2-D-43093773731.jsonl | X2-D | tomli | 5 | 4 | 3 of 6 | 1.00 | +18.8 | 4 of 6 | 1.00 | inside |
| ideas-x2-X2-D-43093773731.jsonl | X2-D | sqlparse | 5 | 4 | 2 of 6 | 0.67 | +28.3 | 5 of 6 | 0.67 | inside |
| ideas-x2-X2-D-43093779047.jsonl | X2-D | mistune | 4 | 6 | 3 of 5 | 1.00 | +19.6 | 5 of 5 | 0.40 | inside |
| ideas-x2-X2-D-43093779047.jsonl | X2-D | markdown | 4 | 6 | 3 of 5 | 1.00 | +11.3 | 3 of 5 | 1.00 | inside |
| ideas-x2-X2-D-43093788927.jsonl | X2-D | tomli | 5 | 5 | 4 of 6 | 1.00 | +16.4 | 2 of 6 | 0.67 | inside |
| ideas-x2-X2-D-43093788927.jsonl | X2-D | markdown | 4 | 6 | 3 of 5 | 1.00 | +18.4 | 5 of 5 | 0.40 | inside |
| ideas-x2-X2-F-43100253551.jsonl | X2-F | tomli | 5 | 4 | 3 of 6 | 1.00 | +17.7 | 3 of 6 | 1.00 | inside |
| ideas-x2-X2-F-43104071793.jsonl | X2-F | mistune | 4 | 8 | 5 of 5 | 0.40 | +15.2 | 2 of 5 | 0.80 | inside |
| ideas-x2-X2-F-43104071793.jsonl | X2-F | sqlparse | 5 | 4 | 2 of 6 | 0.67 | +22.9 | 4 of 6 | 1.00 | inside |
| ideas-x2-X2-P-43100257776.jsonl | X2-P | tomli | 5 | 1 | 1 of 6 | 0.33 | +10.2 | 1 of 6 | 0.33 | inside |
| ideas-x2-X2-P-43100257776.jsonl | X2-P | sqlparse | 5 | 3 | 1 of 6 | 0.33 | +14.6 | 1 of 6 | 0.33 | inside |
| ideas-x2-X2-P-43104077245.jsonl | X2-P | mistune | 4 | 6 | 3 of 5 | 1.00 | +13.1 | 1 of 5 | 0.40 | inside |
| ideas-x2-X2-P-43104077245.jsonl | X2-P | markdown | 4 | 6 | 3 of 5 | 1.00 | +22.2 | 5 of 5 | 0.40 | inside |
| ideas-x2-X2-P-43107418692.jsonl | X2-P | tomli | 5 | 2 | 2 of 6 | 0.67 | +7.4 | 1 of 6 | 0.33 | inside |
| ideas-x2-X2-P-43107418692.jsonl | X2-P | sqlparse | 5 | 8 | 5 of 6 | 0.67 | +34.7 | 5 of 6 | 0.67 | inside |
| ideas-x2-X2-P-43111359647.jsonl | X2-P | mistune | 4 | 4 | 2 of 5 | 0.80 | +8.4 | 1 of 5 | 0.40 | inside |
| ideas-x2-X2-P-43111359647.jsonl | X2-P | markdown | 4 | 3 | 1 of 5 | 0.40 | +25.5 | 5 of 5 | 0.40 | inside |
| ideas-x2-X2-P-43114988674.jsonl | X2-P | tomli | 5 | 5 | 4 of 6 | 1.00 | +15.1 | 2 of 6 | 0.67 | inside |
| ideas-x2-X2-P-43114988674.jsonl | X2-P | sqlparse | 5 | 6 | 3 of 6 | 1.00 | +16.7 | 2 of 6 | 0.67 | inside |
| ideas-x2-X2-P-43114992515.jsonl | X2-P | mistune | 4 | 4 | 2 of 5 | 0.80 | +16.3 | 4 of 5 | 0.80 | inside |
| ideas-x2-X2-P-43114992515.jsonl | X2-P | markdown | 4 | 4 | 2 of 5 | 0.80 | +22.9 | 5 of 5 | 0.40 | inside |
| ideas-x2-d1-42149964562.jsonl | X2-0 | pyparsing | 1 | 1 | 1 of 2 | 1.00 | +5.5 | 2 of 2 | 1.00 | n/a |
| ideas-x2-d1-42149964562.jsonl | X2-0 | tomli | 1 | 6 | 1 of 2 | 1.00 | +22.6 | 2 of 2 | 1.00 | n/a |
| ideas-x2-d1-42149964562.jsonl | X2-0 | sortedcontainers | 1 | 2 | 1 of 2 | 1.00 | +13.4 | 2 of 2 | 1.00 | n/a |
| ideas-x2-d2-42156498229.jsonl | X2-0' | pyparsing | 1 | 1 | 1 of 2 | 1.00 | +2.8 | 1 of 2 | 1.00 | inside |
| ideas-x2-d2-42156498229.jsonl | X2-0' | tomli | 4 | 6 | 4 of 5 | 0.80 | +18.6 | 3 of 5 | 1.00 | inside |
| ideas-x2-d2-42156498229.jsonl | X2-0' | sortedcontainers | 1 | 2 | 1 of 2 | 1.00 | +10.2 | 1 of 2 | 1.00 | inside |
| ideas-x2-d3-42160890340.jsonl | X2-V | pyparsing | 2 | 2 | 3 of 3 | 0.67 | +5.7 | 3 of 3 | 0.67 | inside |
| ideas-x2-d3-42160890340.jsonl | X2-V | tomli | 5 | 4 | 3 of 6 | 1.00 | +22.6 | 5 of 6 | 0.67 | inside |
| ideas-x2-d3-42160890340.jsonl | X2-V | sortedcontainers | 2 | 0 | 1 of 3 | 0.67 | +0.0 | 1 of 3 | 0.67 | outside |
| ideas-x2-d4-42165247794.jsonl | X2-0 | more_itertools | 0 | 2 | - | - | +7.8 | - | - | n/a |
| ideas-x2-d4-42165247794.jsonl | X2-0 | mistune | 0 | 6 | - | - | +13.5 | - | - | n/a |
| ideas-x2-d4-42165247794.jsonl | X2-0 | sqlparse | 1 | 9 | 2 of 2 | 1.00 | +39.8 | 2 of 2 | 1.00 | n/a |
| ideas-x2-d5-42171711130.jsonl | X2-0' | sqlparse | 4 | 7 | 3 of 5 | 1.00 | +21.1 | 3 of 5 | 1.00 | inside |
| ideas-x2-d6-42175276141.jsonl | X2-V | more_itertools | 1 | 2 | 1 of 2 | 1.00 | +5.0 | 1 of 2 | 1.00 | inside |
| ideas-x2-d6-42175276141.jsonl | X2-V | mistune | 4 | 4 | 2 of 5 | 0.80 | +25.1 | 5 of 5 | 0.40 | inside |
| ideas-x2-d6-42175276141.jsonl | X2-V | sqlparse | 5 | 5 | 3 of 6 | 1.00 | +26.5 | 5 of 6 | 0.67 | inside |
| ideas-x2-d7-42181939377.jsonl | X2-0 | markdown | 0 | 6 | - | - | +10.4 | - | - | n/a |
| ideas-x2-d7-42181939377.jsonl | X2-0 | idna | 0 | 3 | - | - | +13.5 | - | - | n/a |
| ideas-x2-d8-42186788761.jsonl | X2-V | markdown | 4 | 4 | 2 of 5 | 0.80 | +25.2 | 5 of 5 | 0.40 | inside |
| ideas-x2-d8-42186788761.jsonl | X2-V | idna | 1 | 6 | 2 of 2 | 1.00 | +12.1 | 1 of 2 | 1.00 | outside |

## 3 Arm calls

| arm | statistic | libraries | signs |
| --- | --- | --- | --- |
| X2-0 | kept | pyparsing, sortedcontainers, sqlparse, tomli | 1 above, 5 below, 4 ties; two-sided p 0.5600 (above 0.9200, below 0.2800) |
| X2-0 | combine | pyparsing, sortedcontainers, sqlparse, tomli | 6 above, 4 below, 0 ties; two-sided p 0.8200 (above 0.4100, below 0.7500) |
| X2-0' | kept | pyparsing, sortedcontainers, sqlparse, tomli | 2 above, 0 below, 2 ties; not tested (2) |
| X2-0' | combine | pyparsing, sortedcontainers, sqlparse, tomli | 2 above, 2 below, 0 ties; not tested (4) |
| X2-V | kept | idna, markdown, mistune, more_itertools, pyparsing, sortedcontainers, sqlparse, tomli | 2 above, 4 below, 2 ties; two-sided p 0.3067 (above 0.9348, below 0.1533) |
| X2-V | combine | idna, markdown, mistune, more_itertools, pyparsing, sortedcontainers, sqlparse, tomli | 5 above, 3 below, 0 ties; two-sided p 1.0000 (above 0.5158, below 0.7531) |
| X2-D | kept | markdown, mistune, sqlparse, tomli | 4 above, 4 below, 2 ties; two-sided p 0.8834 (above 0.6773, below 0.4417) |
| X2-D | combine | markdown, mistune, sqlparse, tomli | 8 above, 2 below, 0 ties; two-sided p 0.2549 (above 0.1275, below 0.9621) |
| X2-P | kept | markdown, mistune, sqlparse, tomli | 4 above, 8 below, 0 ties; two-sided p 0.2266 (above 0.9351, below 0.1133) |
| X2-P | combine | markdown, mistune, sqlparse, tomli | 5 above, 7 below, 0 ties; two-sided p 0.5755 (above 0.8549, below 0.2878) |
| X2-F | kept | mistune, sqlparse, tomli | 1 above, 1 below, 1 ties; not tested (2) |
| X2-F | combine | mistune, sqlparse, tomli | 1 above, 2 below, 0 ties; not tested (3) |

## 4 Delivered mass (measures 3 and 6)

| file | arm | library | kept | combine | keeps at 2x floor | top keep share | combine - top keep | delivered sum / combine | USD per delivered point |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ideas-x2-X2-0-43080309535.jsonl | X2-0 | tomli | 4 | +24.8 | 4 | 0.38 | +12.7 | - | 0.084 |
| ideas-x2-X2-0-43085609944.jsonl | X2-0 | tomli | 3 | +11.8 | 1 | 0.59 | +1.9 | - | 0.150 |
| ideas-x2-X2-0-43085609944.jsonl | X2-0 | mistune | 4 | +18.3 | 3 | 0.37 | +7.0 | - | 0.131 |
| ideas-x2-X2-0-43085609944.jsonl | X2-0 | sqlparse | 5 | +25.7 | 3 | 0.32 | +16.5 | - | 0.108 |
| ideas-x2-X2-0-43085616371.jsonl | X2-0 | tomli | 2 | +17.4 | 1 | 0.76 | +2.6 | 1.124 | 0.105 |
| ideas-x2-X2-0-43085616371.jsonl | X2-0 | mistune | 7 | +16.2 | 2 | 0.27 | +8.6 | - | 0.147 |
| ideas-x2-X2-0-43085616371.jsonl | X2-0 | markdown | 7 | +11.9 | 5 | 0.27 | -1.5 | - | 0.205 |
| ideas-x2-X2-0-43093762527.jsonl | X2-0 | mistune | 5 | +15.6 | 2 | 0.29 | +7.8 | - | 0.170 |
| ideas-x2-X2-0-43093762527.jsonl | X2-0 | sqlparse | 4 | +15.2 | 2 | 0.54 | -2.3 | - | 0.177 |
| ideas-x2-X2-0-43093762527.jsonl | X2-0 | markdown | 4 | +10.1 | 4 | 0.60 | -11.7 | - | 0.219 |
| ideas-x2-X2-0-43093767768.jsonl | X2-0 | sqlparse | 7 | +18.5 | 2 | 0.37 | +0.7 | - | 0.166 |
| ideas-x2-X2-0-43093767768.jsonl | X2-0 | markdown | 5 | +16.6 | 3 | 0.45 | +0.7 | - | 0.151 |
| ideas-x2-d1-42149964562.jsonl | X2-0 | pyparsing | 1 | +5.5 | 1 | 1.00 | -0.1 | - | 0.385 |
| ideas-x2-d1-42149964562.jsonl | X2-0 | tomli | 6 | +22.6 | 4 | 0.25 | +14.8 | - | 0.088 |
| ideas-x2-d1-42149964562.jsonl | X2-0 | sortedcontainers | 2 | +13.4 | 2 | 0.54 | +5.1 | 1.144 | 0.175 |
| ideas-x2-d4-42165247794.jsonl | X2-0 | more_itertools | 2 | +7.8 | 2 | 0.51 | -0.3 | - | 0.223 |
| ideas-x2-d4-42165247794.jsonl | X2-0 | mistune | 6 | +13.5 | 3 | 0.28 | +5.8 | - | 0.184 |
| ideas-x2-d4-42165247794.jsonl | X2-0 | sqlparse | 9 | +39.8 | 2 | 0.36 | +22.1 | - | 0.075 |
| ideas-x2-d7-42181939377.jsonl | X2-0 | markdown | 6 | +10.4 | 4 | 0.30 | -3.2 | - | 0.266 |
| ideas-x2-d7-42181939377.jsonl | X2-0 | idna | 3 | +13.5 | 2 | 0.45 | +1.9 | - | 0.130 |
| ideas-x2-d2-42156498229.jsonl | X2-0' | pyparsing | 1 | +2.8 | 0 | 1.00 | +0.5 | - | 0.864 |
| ideas-x2-d2-42156498229.jsonl | X2-0' | tomli | 6 | +18.6 | 4 | 0.26 | +10.8 | - | 0.103 |
| ideas-x2-d2-42156498229.jsonl | X2-0' | sortedcontainers | 2 | +10.2 | 2 | 0.64 | +0.4 | - | 0.223 |
| ideas-x2-d5-42171711130.jsonl | X2-0' | sqlparse | 7 | +21.1 | 3 | 0.25 | +11.4 | - | 0.131 |
| ideas-x2-d3-42160890340.jsonl | X2-V | pyparsing | 2 | +5.7 | 1 | 0.69 | -0.4 | 1.538 | 0.566 |
| ideas-x2-d3-42160890340.jsonl | X2-V | tomli | 4 | +22.6 | 3 | 0.33 | +12.3 | - | 0.097 |
| ideas-x2-d3-42160890340.jsonl | X2-V | sortedcontainers | 0 | +0.0 | 0 | - | +0.0 | - | n/a |
| ideas-x2-d6-42175276141.jsonl | X2-V | more_itertools | 2 | +5.0 | 2 | 0.65 | -3.4 | - | 0.357 |
| ideas-x2-d6-42175276141.jsonl | X2-V | mistune | 4 | +25.1 | 3 | 0.37 | +14.1 | 1.179 | 0.089 |
| ideas-x2-d6-42175276141.jsonl | X2-V | sqlparse | 5 | +26.5 | 4 | 0.42 | +5.7 | - | 0.108 |
| ideas-x2-d8-42186788761.jsonl | X2-V | markdown | 4 | +25.2 | 4 | 0.31 | +10.1 | - | 0.102 |
| ideas-x2-d8-42186788761.jsonl | X2-V | idna | 6 | +12.1 | 6 | 0.22 | +0.4 | - | 0.180 |
| ideas-x2-X2-D-43085621843.jsonl | X2-D | tomli | 4 | +21.1 | 1 | 0.31 | +12.0 | - | 0.131 |
| ideas-x2-X2-D-43085621843.jsonl | X2-D | sqlparse | 2 | +36.1 | 1 | 0.50 | +17.6 | 1.023 | 0.108 |
| ideas-x2-X2-D-43085626757.jsonl | X2-D | mistune | 3 | +18.4 | 2 | 0.44 | +7.2 | - | 0.193 |
| ideas-x2-X2-D-43085626757.jsonl | X2-D | markdown | 3 | +9.9 | 1 | 0.46 | -10.8 | - | 0.314 |
| ideas-x2-X2-D-43093773731.jsonl | X2-D | tomli | 4 | +18.8 | 2 | 0.41 | +6.3 | - | 0.140 |
| ideas-x2-X2-D-43093773731.jsonl | X2-D | sqlparse | 4 | +28.3 | 4 | 0.27 | +10.5 | - | 0.154 |
| ideas-x2-X2-D-43093779047.jsonl | X2-D | mistune | 6 | +19.6 | 3 | 0.35 | +9.1 | 1.548 | 0.192 |
| ideas-x2-X2-D-43093779047.jsonl | X2-D | markdown | 6 | +11.3 | 6 | 0.21 | +2.8 | - | 0.332 |
| ideas-x2-X2-D-43093788927.jsonl | X2-D | tomli | 5 | +16.4 | 4 | 0.28 | +7.6 | - | 0.168 |
| ideas-x2-X2-D-43093788927.jsonl | X2-D | markdown | 6 | +18.4 | 2 | 0.29 | +5.6 | - | 0.177 |
| ideas-x2-X2-P-43100257776.jsonl | X2-P | tomli | 1 | +10.2 | 0 | 1.00 | -0.8 | - | 0.209 |
| ideas-x2-X2-P-43100257776.jsonl | X2-P | sqlparse | 3 | +14.6 | 2 | 0.51 | +5.8 | - | 0.214 |
| ideas-x2-X2-P-43104077245.jsonl | X2-P | mistune | 6 | +13.1 | 2 | 0.32 | +5.2 | - | 0.213 |
| ideas-x2-X2-P-43104077245.jsonl | X2-P | markdown | 6 | +22.2 | 6 | 0.28 | +8.6 | - | 0.127 |
| ideas-x2-X2-P-43107418692.jsonl | X2-P | tomli | 2 | +7.4 | 2 | 0.54 | -0.1 | - | 0.308 |
| ideas-x2-X2-P-43107418692.jsonl | X2-P | sqlparse | 8 | +34.7 | 4 | 0.33 | +17.4 | - | 0.090 |
| ideas-x2-X2-P-43111359647.jsonl | X2-P | mistune | 4 | +8.4 | 1 | 0.42 | +1.2 | - | 0.281 |
| ideas-x2-X2-P-43111359647.jsonl | X2-P | markdown | 3 | +25.5 | 3 | 0.69 | +4.5 | - | 0.109 |
| ideas-x2-X2-P-43114988674.jsonl | X2-P | tomli | 5 | +15.1 | 2 | 0.31 | +7.9 | - | 0.145 |
| ideas-x2-X2-P-43114988674.jsonl | X2-P | sqlparse | 6 | +16.7 | 4 | 0.39 | -0.2 | - | 0.191 |
| ideas-x2-X2-P-43114992515.jsonl | X2-P | mistune | 4 | +16.3 | 1 | 0.38 | +8.7 | - | 0.159 |
| ideas-x2-X2-P-43114992515.jsonl | X2-P | markdown | 4 | +22.9 | 4 | 0.42 | +7.8 | - | 0.111 |
| ideas-x2-X2-F-43100253551.jsonl | X2-F | tomli | 4 | +17.7 | 3 | 0.33 | +11.0 | 1.149 | 0.189 |
| ideas-x2-X2-F-43104071793.jsonl | X2-F | mistune | 8 | +15.2 | 3 | 0.24 | +6.7 | - | 0.323 |
| ideas-x2-X2-F-43104071793.jsonl | X2-F | sqlparse | 4 | +22.9 | 2 | 0.61 | +5.5 | - | 0.199 |

| arm | runs | kept per run | combine per run | keeps at 2x floor per run | USD per kept | USD per delivered point |
| --- | --- | --- | --- | --- | --- | --- |
| X2-0 | 20 | 4.6 | +16.4 | 2.6 | 0.5104 | 0.143 |
| X2-0' | 4 | 4.0 | +13.2 | 2.2 | 0.5862 | 0.178 |
| X2-V | 8 | 3.4 | +15.3 | 2.9 | 0.7130 | 0.158 |
| X2-D | 10 | 4.3 | +19.8 | 2.6 | 0.7875 | 0.171 |
| X2-P | 12 | 4.3 | +17.3 | 2.6 | 0.6134 | 0.154 |
| X2-F | 3 | 5.3 | +18.6 | 2.7 | 0.8017 | 0.229 |

7 runs with 2 or more delivered keeps: median 1.15, range 1.02-1.55, 7 at 0.9 or more

## 5 Bars and their n

| bar | needs | has | status |
| --- | --- | --- | --- |
| X2-0 sign test, kept | 6 signs | 6 | read, two-sided p 0.5600 |
| X2-0 sign test, combine | 6 signs | 10 | read, two-sided p 0.8200 |
| X2-0' sign test, kept | 6 signs | 2 | not tested (2) |
| X2-0' sign test, combine | 6 signs | 4 | not tested (4) |
| X2-V sign test, kept | 6 signs | 6 | read, two-sided p 0.3067 |
| X2-V sign test, combine | 6 signs | 8 | read, two-sided p 1.0000 |
| X2-D sign test, kept | 6 signs | 8 | read, two-sided p 0.8834 |
| X2-D sign test, combine | 6 signs | 10 | read, two-sided p 0.2549 |
| X2-P sign test, kept | 6 signs | 12 | read, two-sided p 0.2266 |
| X2-P sign test, combine | 6 signs | 12 | read, two-sided p 0.5755 |
| X2-F sign test, kept | 6 signs | 2 | not tested (2) |
| X2-F sign test, combine | 6 signs | 3 | not tested (3) |
| rank call, idna | k 39 | 1 | not tested (k 1) |
| rank call, markdown | k 39 | 4 | not tested (k 4) |
| rank call, mistune | k 39 | 4 | not tested (k 4) |
| rank call, more_itertools | k 39 | 1 | not tested (k 1) |
| rank call, pyparsing | k 39 | 2 | not tested (k 2) |
| rank call, sortedcontainers | k 39 | 2 | not tested (k 2) |
| rank call, sqlparse | k 39 | 5 | not tested (k 5) |
| rank call, tomli | k 39 | 5 | not tested (k 5) |

## 6 Lane views

| library | round | lane | runs | distinct views | served models |
| --- | --- | --- | --- | --- | --- |
| markdown | 1 | assume_less | 9 | 9 | claude-sonnet-5-5 |
| markdown | 1 | eliminate | 9 | 9 | claude-haiku-5-5 |
| markdown | 1 | far | 9 | 9 | claude-sonnet-5-5 |
| markdown | 1 | leap | 9 | 9 | claude-opus-5-5 |
| markdown | 1 | name_the_problem | 9 | 9 | claude-sonnet-5-5 |
| markdown | 1 | obvious | 9 | 9 | claude-sonnet-5-5 |
| markdown | 1 | recombine | 9 | 9 | claude-sonnet-5-5 |
| markdown | 1 | resolve_tradeoff | 9 | 9 | claude-sonnet-5-5 |
| markdown | 2 | assume_less | 9 | 9 | claude-sonnet-5-5 |
| markdown | 2 | eliminate | 9 | 9 | claude-haiku-5-5 |
| markdown | 2 | far | 9 | 9 | claude-sonnet-5-5 |
| markdown | 2 | leap | 9 | 9 | claude-opus-5-5 |
| markdown | 2 | name_the_problem | 9 | 9 | claude-sonnet-5-5 |
| markdown | 2 | obvious | 9 | 9 | claude-sonnet-5-5 |
| markdown | 2 | recombine | 9 | 9 | claude-sonnet-5-5 |
| markdown | 2 | resolve_tradeoff | 9 | 9 | claude-sonnet-5-5 |
| markdown | 3 | assume_less | 3 | 3 | claude-sonnet-5-5 |
| markdown | 3 | eliminate | 3 | 3 | claude-haiku-5-5 |
| markdown | 3 | far | 3 | 3 | claude-sonnet-5-5 |
| markdown | 3 | leap | 3 | 3 | claude-opus-5-5 |
| markdown | 3 | name_the_problem | 3 | 3 | claude-sonnet-5-5 |
| markdown | 3 | obvious | 3 | 3 | claude-sonnet-5-5 |
| markdown | 3 | recombine | 3 | 3 | claude-sonnet-5-5 |
| markdown | 3 | resolve_tradeoff | 3 | 3 | claude-sonnet-5-5 |
| mistune | 1 | assume_less | 9 | 9 | claude-sonnet-5-5 |
| mistune | 1 | eliminate | 9 | 9 | claude-haiku-5-5 |
| mistune | 1 | far | 9 | 9 | claude-sonnet-5-5 |
| mistune | 1 | leap | 9 | 9 | claude-fable-5-2, claude-opus-5-5 |
| mistune | 1 | name_the_problem | 9 | 9 | claude-sonnet-5-5 |
| mistune | 1 | obvious | 9 | 9 | claude-sonnet-5-5 |
| mistune | 1 | recombine | 9 | 9 | claude-sonnet-5-5 |
| mistune | 1 | resolve_tradeoff | 9 | 9 | claude-sonnet-5-5 |
| mistune | 2 | assume_less | 9 | 9 | claude-sonnet-5-5 |
| mistune | 2 | eliminate | 9 | 9 | claude-haiku-5-5 |
| mistune | 2 | far | 9 | 9 | claude-sonnet-5-5 |
| mistune | 2 | leap | 9 | 9 | claude-fable-5-2, claude-opus-5-5 |
| mistune | 2 | name_the_problem | 9 | 9 | claude-sonnet-5-5 |
| mistune | 2 | obvious | 9 | 9 | claude-sonnet-5-5 |
| mistune | 2 | recombine | 9 | 9 | claude-sonnet-5-5 |
| mistune | 2 | resolve_tradeoff | 9 | 9 | claude-sonnet-5-5 |
| mistune | 3 | assume_less | 2 | 2 | claude-sonnet-5-5 |
| mistune | 3 | eliminate | 2 | 2 | claude-haiku-5-5 |
| mistune | 3 | far | 2 | 2 | claude-sonnet-5-5 |
| mistune | 3 | leap | 2 | 2 | claude-opus-5-5 |
| mistune | 3 | name_the_problem | 2 | 2 | claude-sonnet-5-5 |
| mistune | 3 | obvious | 2 | 2 | claude-sonnet-5-5 |
| mistune | 3 | recombine | 2 | 2 | claude-sonnet-5-5 |
| mistune | 3 | resolve_tradeoff | 2 | 2 | claude-sonnet-5-5 |
| sqlparse | 1 | assume_less | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 1 | eliminate | 9 | 9 | claude-haiku-5-5 |
| sqlparse | 1 | far | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 1 | leap | 9 | 9 | claude-fable-5-2, claude-opus-5-5 |
| sqlparse | 1 | name_the_problem | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 1 | obvious | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 1 | recombine | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 1 | resolve_tradeoff | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 2 | assume_less | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 2 | eliminate | 9 | 9 | claude-haiku-5-5 |
| sqlparse | 2 | far | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 2 | leap | 9 | 9 | claude-fable-5-2, claude-opus-5-5 |
| sqlparse | 2 | name_the_problem | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 2 | obvious | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 2 | recombine | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 2 | resolve_tradeoff | 9 | 9 | claude-sonnet-5-5 |
| sqlparse | 3 | assume_less | 2 | 2 | claude-sonnet-5-5 |
| sqlparse | 3 | eliminate | 2 | 2 | claude-haiku-5-5 |
| sqlparse | 3 | far | 2 | 2 | claude-sonnet-5-5 |
| sqlparse | 3 | leap | 2 | 2 | claude-opus-5-5 |
| sqlparse | 3 | name_the_problem | 2 | 2 | claude-sonnet-5-5 |
| sqlparse | 3 | obvious | 2 | 2 | claude-sonnet-5-5 |
| sqlparse | 3 | recombine | 2 | 2 | claude-sonnet-5-5 |
| sqlparse | 3 | resolve_tradeoff | 2 | 2 | claude-sonnet-5-5 |
| tomli | 1 | assume_less | 10 | 10 | claude-sonnet-5-5 |
| tomli | 1 | eliminate | 10 | 10 | claude-haiku-5-5 |
| tomli | 1 | far | 10 | 10 | claude-sonnet-5-5 |
| tomli | 1 | leap | 10 | 10 | claude-fable-5-2, claude-opus-5-5 |
| tomli | 1 | name_the_problem | 10 | 10 | claude-sonnet-5-5 |
| tomli | 1 | obvious | 10 | 10 | claude-sonnet-5-5 |
| tomli | 1 | recombine | 10 | 10 | claude-sonnet-5-5 |
| tomli | 1 | resolve_tradeoff | 10 | 10 | claude-sonnet-5-5 |
| tomli | 2 | assume_less | 10 | 10 | claude-sonnet-5-5 |
| tomli | 2 | eliminate | 10 | 10 | claude-haiku-5-5 |
| tomli | 2 | far | 10 | 10 | claude-sonnet-5-5 |
| tomli | 2 | leap | 10 | 10 | claude-fable-5-2, claude-opus-5-5 |
| tomli | 2 | name_the_problem | 10 | 10 | claude-sonnet-5-5 |
| tomli | 2 | obvious | 10 | 10 | claude-sonnet-5-5 |
| tomli | 2 | recombine | 10 | 10 | claude-sonnet-5-5 |
| tomli | 2 | resolve_tradeoff | 10 | 10 | claude-sonnet-5-5 |
| tomli | 3 | assume_less | 3 | 3 | claude-sonnet-5-5 |
| tomli | 3 | eliminate | 3 | 3 | claude-haiku-5-5 |
| tomli | 3 | far | 3 | 3 | claude-sonnet-5-5 |
| tomli | 3 | leap | 3 | 3 | claude-opus-5-5 |
| tomli | 3 | name_the_problem | 3 | 3 | claude-sonnet-5-5 |
| tomli | 3 | obvious | 3 | 3 | claude-sonnet-5-5 |
| tomli | 3 | recombine | 3 | 3 | claude-sonnet-5-5 |
| tomli | 3 | resolve_tradeoff | 3 | 3 | claude-sonnet-5-5 |
