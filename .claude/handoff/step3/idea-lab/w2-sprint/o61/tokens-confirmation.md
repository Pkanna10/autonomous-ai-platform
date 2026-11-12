# X2 leap output tokens against the cap (X2-L)

- **Per leap call.** The served model's output tokens against the request's max_tokens (on a fallback, each attempt's beside it), the stop reason and the headroom (cap less output). No reply: the request raised; not recorded: a row from before the token fields.
- **Per arm.** The least, median (lower) and most headroom over the calls that replied, and the calls that stopped at max_tokens.

## 1 Leap calls

| arm | library | file | round | model | output / max | stop reason | headroom |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X2-D | tomli | ideas-x2-X2-D-43159144063.jsonl | 1 | claude-opus-5-5 | 5503 / 12000 | end_turn | 6497 |
| X2-D | tomli | ideas-x2-X2-D-43159144063.jsonl | 2 | claude-opus-5-5 | 5368 / 12000 | end_turn | 6632 |
| X2-D | tomli | ideas-x2-X2-D-43159144063.jsonl | 3 | claude-opus-5-5 | 4297 / 12000 | end_turn | 7703 |
| X2-D | sqlparse | ideas-x2-X2-D-43159144063.jsonl | 1 | claude-opus-5-5 | 5644 / 12000 | end_turn | 6356 |
| X2-D | sqlparse | ideas-x2-X2-D-43159144063.jsonl | 2 | claude-opus-5-5 | 6074 / 12000 | end_turn | 5926 |
| X2-D | sqlparse | ideas-x2-X2-D-43159144063.jsonl | 3 | claude-opus-5-5 | 10033 / 12000 | end_turn | 1967 |
| X2-D | tomli | ideas-x2-X2-D-43159147698.jsonl | 1 | claude-opus-5-5 | 6387 / 12000 | end_turn | 5613 |
| X2-D | tomli | ideas-x2-X2-D-43159147698.jsonl | 2 | claude-opus-5-5 | 6105 / 12000 | end_turn | 5895 |
| X2-D | tomli | ideas-x2-X2-D-43159147698.jsonl | 3 | claude-opus-5-5 | 2338 / 12000 | end_turn | 9662 |
| X2-D | sqlparse | ideas-x2-X2-D-43159147698.jsonl | 1 | claude-opus-5-5 | 9594 / 12000 | end_turn | 2406 |
| X2-D | sqlparse | ideas-x2-X2-D-43159147698.jsonl | 2 | claude-opus-5-5 | 6194 / 12000 | end_turn | 5806 |
| X2-D | sqlparse | ideas-x2-X2-D-43159147698.jsonl | 3 | claude-opus-5-5 | 12000 / 12000 | max_tokens | 0 |
| X2-D | mistune | ideas-x2-X2-D-43159151284.jsonl | 1 | claude-opus-5-5 | 4150 / 12000 | end_turn | 7850 |
| X2-D | mistune | ideas-x2-X2-D-43159151284.jsonl | 2 | claude-opus-5-5 | 8047 / 12000 | end_turn | 3953 |
| X2-D | mistune | ideas-x2-X2-D-43159151284.jsonl | 3 | claude-opus-5-5 | 6872 / 12000 | end_turn | 5128 |
| X2-D | mistune | ideas-x2-X2-D-43159154661.jsonl | 1 | claude-opus-5-5 | 4366 / 12000 | end_turn | 7634 |
| X2-D | mistune | ideas-x2-X2-D-43159154661.jsonl | 2 | claude-opus-5-5 | 12000 / 12000 | max_tokens | 0 |
| X2-D | mistune | ideas-x2-X2-D-43159154661.jsonl | 3 | claude-opus-5-5 | 10891 / 12000 | end_turn | 1109 |
| X2-D | markdown | ideas-x2-X2-D-43159157891.jsonl | 1 | claude-opus-5-5 | 4428 / 12000 | end_turn | 7572 |
| X2-D | markdown | ideas-x2-X2-D-43159157891.jsonl | 2 | claude-opus-5-5 | 4399 / 12000 | end_turn | 7601 |
| X2-D | markdown | ideas-x2-X2-D-43159157891.jsonl | 3 | claude-opus-5-5 | 6166 / 12000 | end_turn | 5834 |
| X2-D | markdown | ideas-x2-X2-D-43159160974.jsonl | 1 | claude-opus-5-5 | 5528 / 12000 | end_turn | 6472 |
| X2-D | markdown | ideas-x2-X2-D-43159160974.jsonl | 2 | claude-opus-5-5 | 3614 / 12000 | end_turn | 8386 |
| X2-D | markdown | ideas-x2-X2-D-43159160974.jsonl | 3 | claude-opus-5-5 | 7925 / 12000 | end_turn | 4075 |

## 2 Headroom per arm

| arm | leap calls | replied | max_tokens stops | least headroom | median headroom | most headroom |
| --- | --- | --- | --- | --- | --- | --- |
| X2-D | 24 | 24 | 2 | 0 | 5895 | 9662 |
