# The X2-DT comparator: 20 X2-D runs, replay-measured under gain order (fixed 2026-11-16)

Fixed before any X2-DT run (O71 item 1, O72 item 2). These values are not changed afterwards.

- **What each value is:** the run's delivered gain (%) as replayed on a quiet runner under gain order (`SITE_STACKS="on"`), through the combine node's own re-test, hold and fallback rules: the set's gain if it held, else the fallback single's if it held, else 0; the mean over the replay's looks of that side (`order_readings.RunReading.mean`).
- **Where a run had one tree** (no conflict choice, so both orders give the same set), the value is that tree's replayed gain (O65 `mean_a_pct`).
- **Labels:** the comparator is replay-measured; X2-DT's primary is live-measured (O71 item 1). The O72 item 3 secondary compares X2-DT's delivered trees, replayed the same way, against these values.
- **Sources:** `live/combine-order-43567670887-43567673362-43567675481.jsonl` (O65, 17 runs, at `2aa8bed`) and `live/combine-order-43852494468.jsonl` (O72 item 2, `order_batch=b`, 3 runs, at `4ebc2f4`; no API spend).

| Library | X2-D run | Comparator (replayed, %) | How | Live delivered (archived, %) |
| --- | --- | ---: | --- | ---: |
| markdown | `43085626757` | 21.24 | gain order, O65 | 9.88 |
| markdown | `43093779047` | 17.07 | gain order, O65 | 11.29 |
| markdown | `43093788927` | 19.21 | gain order, O65 | 18.45 |
| markdown | `43159157891` | 22.60 | gain order, O65 | 21.37 |
| markdown | `43159160974` | 15.80 | one tree (a = b), O65 | 14.03 |
| mistune | `43085626757` | 17.81 | one tree (a = b), O65 | 18.43 |
| mistune | `43093779047` | 20.09 | one tree (a = b), O65 | 19.64 |
| mistune | `43145496896` | 10.09 | gain order, O72 item 2; set did not hold, fallback single delivered | 8.54 |
| mistune | `43159151284` | 20.86 | one tree (a = b), O65 | 20.76 |
| mistune | `43159154661` | 7.87 | gain order, O72 item 2; set did not hold, fallback single delivered | 6.91 |
| sqlparse | `43085621843` | 34.74 | one tree (a = b), O65 | 36.11 |
| sqlparse | `43093773731` | 29.95 | one tree (a = b), O65 | 28.33 |
| sqlparse | `43145496896` | 11.87 | gain order, O65 | 14.67 |
| sqlparse | `43159144063` | 34.87 | gain order, O65 | 33.68 |
| sqlparse | `43159147698` | 42.19 | one tree (a = b), O65 | 43.88 |
| tomli | `43085621843` | 23.05 | one tree (a = b), O65 | 21.15 |
| tomli | `43093773731` | 19.36 | one tree (a = b), O65 | 18.75 |
| tomli | `43093788927` | 19.29 | gain order, O65 | 16.39 |
| tomli | `43159144063` | 12.10 | gain order, O72 item 2 | 10.52 |
| tomli | `43159147698` | 19.24 | one tree (a = b), O65 | 20.19 |

| Library | n | Median (replayed) | Median (live) |
| --- | ---: | ---: | ---: |
| markdown | 5 | 19.21 | 14.03 |
| mistune | 5 | 17.81 | 18.43 |
| sqlparse | 5 | 34.74 | 33.68 |
| tomli | 5 | 19.29 | 18.75 |

All 20: mean replayed 20.97, mean live 19.65. No value is 0: in the two mistune runs whose gain-ordered set did not hold, the engine's fallback single held on every look.
