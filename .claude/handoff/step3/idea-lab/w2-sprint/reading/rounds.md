# X2 keeps by round: where each run's keeps came from (Window 2, X2-D)

- **Not a contribution.** Each round's standalone points are its keeps' own gains against the base (each hypothesis row's gain), summed under the round that first trialled them; standalone gains overlap and a compound holds its parents' sites, so the points are neither additive nor a round's share of the delivered gain.
- **The third round's delivered gain.** What a third round adds to delivered gain is read only from X2-D's delivered combine against the pool on the variance page (``--variance``; O59 section 5's primary measure). This page says where the keeps came from, nothing more.
- **Fresh ideas + near-miss compounds.** Each round's keeps and points are split into fresh ideas and near-miss compounds (the round row's compounds kept, the hypothesis rows' compound flag), so a round that kept only a compound reads 0 + 1.
- **Delivered.** Where the rows carry per-keep combine records (S2), the round's keeps that reached the tip, of its keeps; else -. The run's delivered combine (0 when it did not hold) is printed beside.
- **Runs.** As the variance page, each file alone: every (arm, library) run of every file is one run; a round it did not reach reads -, and an arm's per-run figures for a round are over the runs that reached it.

## 1 Each run

| file | arm | library | rounds | round 1 kept, ideas + compounds | round 1 standalone points, ideas (vs base, not additive) | round 1 standalone points, compounds (vs base, not additive) | round 1 delivered | round 2 kept, ideas + compounds | round 2 standalone points, ideas (vs base, not additive) | round 2 standalone points, compounds (vs base, not additive) | round 2 delivered | round 3 kept, ideas + compounds | round 3 standalone points, ideas (vs base, not additive) | round 3 standalone points, compounds (vs base, not additive) | round 3 delivered | standalone points, every keep (vs base, not additive) | delivered combine |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ideas-x2-X2-0-43080309535.jsonl | X2-0 | tomli | 2 | 3 + 0 | +24.2 | +0.0 | - | 1 + 0 | +7.1 | +0.0 | - | - | - | - | - | +31.3 | +24.8 |
| ideas-x2-X2-0-43085609944.jsonl | X2-0 | tomli | 2 | 1 + 0 | +4.1 | +0.0 | - | 2 + 0 | +12.8 | +0.0 | - | - | - | - | - | +16.9 | +11.8 |
| ideas-x2-X2-0-43085609944.jsonl | X2-0 | mistune | 2 | 4 + 0 | +30.8 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | - | - | - | - | +30.8 | +18.3 |
| ideas-x2-X2-0-43085609944.jsonl | X2-0 | sqlparse | 2 | 3 + 0 | +16.3 | +0.0 | - | 2 + 0 | +12.0 | +0.0 | - | - | - | - | - | +28.3 | +25.7 |
| ideas-x2-X2-0-43085616371.jsonl | X2-0 | tomli | 2 | 1 + 0 | +14.8 | +0.0 | - | 1 + 0 | +4.8 | +0.0 | - | - | - | - | - | +19.6 | +17.4 |
| ideas-x2-X2-0-43085616371.jsonl | X2-0 | mistune | 2 | 5 + 0 | +21.9 | +0.0 | - | 2 + 0 | +6.6 | +0.0 | - | - | - | - | - | +28.5 | +16.2 |
| ideas-x2-X2-0-43085616371.jsonl | X2-0 | markdown | 2 | 4 + 0 | +26.8 | +0.0 | - | 2 + 1 | +17.9 | +4.4 | - | - | - | - | - | +49.1 | +11.9 |
| ideas-x2-X2-0-43093762527.jsonl | X2-0 | mistune | 2 | 3 + 0 | +15.3 | +0.0 | - | 2 + 0 | +11.6 | +0.0 | - | - | - | - | - | +26.9 | +15.6 |
| ideas-x2-X2-0-43093762527.jsonl | X2-0 | sqlparse | 2 | 4 + 0 | +32.4 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | - | - | - | - | +32.4 | +15.2 |
| ideas-x2-X2-0-43093762527.jsonl | X2-0 | markdown | 2 | 4 + 0 | +36.2 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | - | - | - | - | +36.2 | +10.1 |
| ideas-x2-X2-0-43093767768.jsonl | X2-0 | sqlparse | 2 | 4 + 0 | +31.6 | +0.0 | - | 3 + 0 | +15.7 | +0.0 | - | - | - | - | - | +47.3 | +18.5 |
| ideas-x2-X2-0-43093767768.jsonl | X2-0 | markdown | 2 | 3 + 0 | +17.1 | +0.0 | - | 2 + 0 | +18.4 | +0.0 | - | - | - | - | - | +35.4 | +16.6 |
| ideas-x2-X2-D-43085621843.jsonl | X2-D | tomli | 3 | 2 + 0 | +15.2 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | 2 + 0 | +13.9 | +0.0 | - | +29.1 | +21.1 |
| ideas-x2-X2-D-43085621843.jsonl | X2-D | sqlparse | 3 | 1 + 0 | +18.5 | +0.0 | - | 1 + 0 | +18.5 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | +37.0 | +36.1 |
| ideas-x2-X2-D-43085626757.jsonl | X2-D | mistune | 3 | 1 + 0 | +7.9 | +0.0 | - | 1 + 0 | +6.3 | +0.0 | - | 1 + 0 | +11.2 | +0.0 | - | +25.4 | +18.4 |
| ideas-x2-X2-D-43085626757.jsonl | X2-D | markdown | 3 | 1 + 0 | +15.1 | +0.0 | - | 1 + 0 | +9.2 | +0.0 | - | 1 + 0 | +20.7 | +0.0 | - | +45.0 | +9.9 |
| ideas-x2-X2-D-43093773731.jsonl | X2-D | tomli | 3 | 2 + 0 | +18.8 | +0.0 | - | 1 + 0 | +6.5 | +0.0 | - | 1 + 0 | +5.0 | +0.0 | - | +30.3 | +18.8 |
| ideas-x2-X2-D-43093773731.jsonl | X2-D | sqlparse | 3 | 1 + 0 | +17.8 | +0.0 | - | 1 + 0 | +17.5 | +0.0 | - | 1 + 1 | +16.6 | +15.1 | - | +67.0 | +28.3 |
| ideas-x2-X2-D-43093779047.jsonl | X2-D | mistune | 3 | 4 + 0 | +24.6 | +0.0 | - | 1 + 0 | +3.3 | +0.0 | - | 1 + 0 | +2.5 | +0.0 | - | +30.4 | +19.6 |
| ideas-x2-X2-D-43093779047.jsonl | X2-D | markdown | 3 | 2 + 0 | +13.7 | +0.0 | - | 2 + 1 | +13.4 | +7.8 | - | 0 + 1 | +0.0 | +5.6 | - | +40.5 | +11.3 |
| ideas-x2-X2-D-43093788927.jsonl | X2-D | tomli | 3 | 3 + 0 | +22.8 | +0.0 | - | 1 + 0 | +6.4 | +0.0 | - | 1 + 0 | +2.6 | +0.0 | - | +31.7 | +16.4 |
| ideas-x2-X2-D-43093788927.jsonl | X2-D | markdown | 3 | 1 + 0 | +5.9 | +0.0 | - | 3 + 1 | +27.0 | +6.0 | - | 1 + 0 | +5.4 | +0.0 | - | +44.3 | +18.4 |
| ideas-x2-X2-F-43100253551.jsonl | X2-F | tomli | 2 | 2 + 0 | +12.2 | +0.0 | - | 2 + 0 | +8.1 | +0.0 | - | - | - | - | - | +20.4 | +17.7 |
| ideas-x2-X2-F-43104071793.jsonl | X2-F | mistune | 2 | 3 + 0 | +16.7 | +0.0 | - | 4 + 1 | +14.3 | +4.3 | - | - | - | - | - | +35.3 | +15.2 |
| ideas-x2-X2-F-43104071793.jsonl | X2-F | sqlparse | 2 | 4 + 0 | +28.4 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | - | - | - | - | +28.4 | +22.9 |
| ideas-x2-X2-P-43100257776.jsonl | X2-P | tomli | 2 | 1 + 0 | +11.1 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | - | - | - | - | +11.1 | +10.2 |
| ideas-x2-X2-P-43100257776.jsonl | X2-P | sqlparse | 2 | 2 + 0 | +11.8 | +0.0 | - | 1 + 0 | +5.6 | +0.0 | - | - | - | - | - | +17.4 | +14.6 |
| ideas-x2-X2-P-43104077245.jsonl | X2-P | mistune | 2 | 3 + 0 | +8.2 | +0.0 | - | 2 + 1 | +8.9 | +7.9 | - | - | - | - | - | +25.1 | +13.1 |
| ideas-x2-X2-P-43104077245.jsonl | X2-P | markdown | 2 | 4 + 0 | +29.7 | +0.0 | - | 2 + 0 | +18.9 | +0.0 | - | - | - | - | - | +48.6 | +22.2 |
| ideas-x2-X2-P-43107418692.jsonl | X2-P | tomli | 2 | 2 + 0 | +13.7 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | - | - | - | - | +13.7 | +7.4 |
| ideas-x2-X2-P-43107418692.jsonl | X2-P | sqlparse | 2 | 6 + 0 | +46.2 | +0.0 | - | 2 + 0 | +6.8 | +0.0 | - | - | - | - | - | +53.0 | +34.7 |
| ideas-x2-X2-P-43111359647.jsonl | X2-P | mistune | 2 | 3 + 0 | +14.2 | +0.0 | - | 1 + 0 | +2.8 | +0.0 | - | - | - | - | - | +17.0 | +8.4 |
| ideas-x2-X2-P-43111359647.jsonl | X2-P | markdown | 2 | 1 + 0 | +5.1 | +0.0 | - | 2 + 0 | +25.4 | +0.0 | - | - | - | - | - | +30.5 | +25.5 |
| ideas-x2-X2-P-43114988674.jsonl | X2-P | tomli | 2 | 4 + 0 | +20.3 | +0.0 | - | 1 + 0 | +2.8 | +0.0 | - | - | - | - | - | +23.1 | +15.1 |
| ideas-x2-X2-P-43114988674.jsonl | X2-P | sqlparse | 2 | 3 + 0 | +26.8 | +0.0 | - | 2 + 1 | +12.3 | +4.4 | - | - | - | - | - | +43.5 | +16.7 |
| ideas-x2-X2-P-43114992515.jsonl | X2-P | mistune | 2 | 3 + 0 | +16.1 | +0.0 | - | 1 + 0 | +3.9 | +0.0 | - | - | - | - | - | +20.0 | +16.3 |
| ideas-x2-X2-P-43114992515.jsonl | X2-P | markdown | 2 | 2 + 0 | +14.0 | +0.0 | - | 2 + 0 | +22.1 | +0.0 | - | - | - | - | - | +36.1 | +22.9 |
| ideas-x2-d1-42149964562.jsonl | X2-0 | pyparsing | 2 | 1 + 0 | +5.6 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | - | - | - | - | +5.6 | +5.5 |
| ideas-x2-d1-42149964562.jsonl | X2-0 | tomli | 2 | 3 + 0 | +20.9 | +0.0 | - | 3 + 0 | +10.8 | +0.0 | - | - | - | - | - | +31.7 | +22.6 |
| ideas-x2-d1-42149964562.jsonl | X2-0 | sortedcontainers | 2 | 2 + 0 | +15.3 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | - | - | - | - | +15.3 | +13.4 |
| ideas-x2-d2-42156498229.jsonl | X2-0' | pyparsing | 2 | 1 + 0 | +2.3 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | - | - | - | - | +2.3 | +2.8 |
| ideas-x2-d2-42156498229.jsonl | X2-0' | tomli | 2 | 5 + 0 | +25.1 | +0.0 | - | 1 + 0 | +5.4 | +0.0 | - | - | - | - | - | +30.5 | +18.6 |
| ideas-x2-d2-42156498229.jsonl | X2-0' | sortedcontainers | 2 | 1 + 0 | +9.7 | +0.0 | - | 1 + 0 | +5.4 | +0.0 | - | - | - | - | - | +15.1 | +10.2 |
| ideas-x2-d3-42160890340.jsonl | X2-V | pyparsing | 2 | 1 + 0 | +2.7 | +0.0 | - | 1 + 0 | +6.0 | +0.0 | - | - | - | - | - | +8.7 | +5.7 |
| ideas-x2-d3-42160890340.jsonl | X2-V | tomli | 2 | 2 + 0 | +16.7 | +0.0 | - | 2 + 0 | +14.1 | +0.0 | - | - | - | - | - | +30.8 | +22.6 |
| ideas-x2-d3-42160890340.jsonl | X2-V | sortedcontainers | 2 | 0 + 0 | +0.0 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | - | - | - | - | +0.0 | +0.0 |
| ideas-x2-d4-42165247794.jsonl | X2-0 | more_itertools | 2 | 1 + 0 | +8.1 | +0.0 | - | 1 + 0 | +7.9 | +0.0 | - | - | - | - | - | +16.1 | +7.8 |
| ideas-x2-d4-42165247794.jsonl | X2-0 | mistune | 2 | 4 + 0 | +16.0 | +0.0 | - | 2 + 0 | +11.9 | +0.0 | - | - | - | - | - | +27.9 | +13.5 |
| ideas-x2-d4-42165247794.jsonl | X2-0 | sqlparse | 2 | 4 + 0 | +33.5 | +0.0 | - | 4 + 1 | +12.0 | +3.0 | - | - | - | - | - | +48.4 | +39.8 |
| ideas-x2-d5-42171711130.jsonl | X2-0' | sqlparse | 2 | 4 + 0 | +23.4 | +0.0 | - | 3 + 0 | +14.5 | +0.0 | - | - | - | - | - | +37.9 | +21.1 |
| ideas-x2-d6-42175276141.jsonl | X2-V | more_itertools | 2 | 1 + 0 | +4.5 | +0.0 | - | 1 + 0 | +8.4 | +0.0 | - | - | - | - | - | +12.9 | +5.0 |
| ideas-x2-d6-42175276141.jsonl | X2-V | mistune | 2 | 3 + 0 | +23.0 | +0.0 | - | 0 + 1 | +0.0 | +6.6 | - | - | - | - | - | +29.6 | +25.1 |
| ideas-x2-d6-42175276141.jsonl | X2-V | sqlparse | 2 | 4 + 0 | +44.7 | +0.0 | - | 0 + 1 | +0.0 | +5.2 | - | - | - | - | - | +49.9 | +26.5 |
| ideas-x2-d7-42181939377.jsonl | X2-0 | markdown | 2 | 3 + 0 | +13.6 | +0.0 | - | 3 + 0 | +31.4 | +0.0 | - | - | - | - | - | +44.9 | +10.4 |
| ideas-x2-d7-42181939377.jsonl | X2-0 | idna | 2 | 1 + 0 | +10.6 | +0.0 | - | 2 + 0 | +14.9 | +0.0 | - | - | - | - | - | +25.5 | +13.5 |
| ideas-x2-d8-42186788761.jsonl | X2-V | markdown | 2 | 3 + 0 | +35.8 | +0.0 | - | 1 + 0 | +12.4 | +0.0 | - | - | - | - | - | +48.3 | +25.2 |
| ideas-x2-d8-42186788761.jsonl | X2-V | idna | 2 | 4 + 0 | +36.5 | +0.0 | - | 2 + 0 | +15.9 | +0.0 | - | - | - | - | - | +52.5 | +12.1 |

## 2 Each arm

| arm | runs | round 1 runs | round 1 kept per run, ideas + compounds | round 1 standalone points, ideas (vs base, not additive) per run | round 1 standalone points, compounds (vs base, not additive) per run | round 1 delivered | round 2 runs | round 2 kept per run, ideas + compounds | round 2 standalone points, ideas (vs base, not additive) per run | round 2 standalone points, compounds (vs base, not additive) per run | round 2 delivered | round 3 runs | round 3 kept per run, ideas + compounds | round 3 standalone points, ideas (vs base, not additive) per run | round 3 standalone points, compounds (vs base, not additive) per run | round 3 delivered | standalone points, every keep (vs base, not additive) per run | delivered combine per run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| X2-0 | 20 | 20 | 2.9 + 0.0 | +19.8 | +0.0 | - | 20 | 1.6 + 0.1 | +9.8 | +0.4 | - | 0 | - | - | - | - | +29.9 | +16.4 |
| X2-0' | 4 | 4 | 2.8 + 0.0 | +15.1 | +0.0 | - | 4 | 1.2 + 0.0 | +6.3 | +0.0 | - | 0 | - | - | - | - | +21.5 | +13.2 |
| X2-V | 8 | 8 | 2.2 + 0.0 | +20.5 | +0.0 | - | 8 | 0.9 + 0.2 | +7.1 | +1.5 | - | 0 | - | - | - | - | +29.1 | +15.3 |
| X2-D | 10 | 10 | 1.8 + 0.0 | +16.0 | +0.0 | - | 10 | 1.2 + 0.2 | +10.8 | +1.4 | - | 10 | 0.9 + 0.2 | +7.8 | +2.1 | - | +38.1 | +19.8 |
| X2-P | 12 | 12 | 2.8 + 0.0 | +18.1 | +0.0 | - | 12 | 1.3 + 0.2 | +9.1 | +1.0 | - | 0 | - | - | - | - | +28.3 | +17.3 |
| X2-F | 3 | 3 | 3.0 + 0.0 | +19.1 | +0.0 | - | 3 | 2.0 + 0.3 | +7.5 | +1.4 | - | 0 | - | - | - | - | +28.0 | +18.6 |
