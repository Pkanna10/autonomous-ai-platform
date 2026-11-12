# X2 leap output tokens against the cap (X2-L)

- **Per leap call.** The served model's output tokens against the request's max_tokens (on a fallback, each attempt's beside it), the stop reason and the headroom (cap less output). No reply: the request raised; not recorded: a row from before the token fields.
- **Per arm.** The least, median (lower) and most headroom over the calls that replied, and the calls that stopped at max_tokens.

## 1 Leap calls

| arm | library | file | round | model | output / max | stop reason | headroom |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X2-L | sqlparse | ideas-x2-X2-L-43151986627.jsonl | 1 | claude-fable-5-2 | not recorded | - | - |
| X2-L | sqlparse | ideas-x2-X2-L-43151986627.jsonl | 2 | claude-fable-5-2 | not recorded | - | - |
| X2-L | tomli | ideas-x2-X2-L-43151990527.jsonl | 1 | claude-fable-5-2 | not recorded | - | - |
| X2-L | tomli | ideas-x2-X2-L-43151990527.jsonl | 2 | claude-fable-5-2 | not recorded | - | - |
| X2-L | mistune | ideas-x2-X2-L-43151994247.jsonl | 1 | claude-fable-5-2 | not recorded | - | - |
| X2-L | mistune | ideas-x2-X2-L-43151994247.jsonl | 2 | claude-fable-5-2 | not recorded | - | - |
| X2-L | markdown | ideas-x2-X2-L-43154378817.jsonl | 1 | claude-fable-5-2 | not recorded | - | - |
| X2-L | markdown | ideas-x2-X2-L-43154378817.jsonl | 2 | claude-fable-5-2 | not recorded | - | - |
| X2-L | markdown | ideas-x2-X2-L-43154382141.jsonl | 1 | claude-fable-5-2 | not recorded | - | - |
| X2-L | markdown | ideas-x2-X2-L-43154382141.jsonl | 2 | claude-fable-5-2 | not recorded | - | - |
| X2-L | markdown | ideas-x2-X2-L-43154385525.jsonl | 1 | claude-fable-5-2 | not recorded | - | - |
| X2-L | markdown | ideas-x2-X2-L-43154385525.jsonl | 2 | claude-fable-5-2 | not recorded | - | - |
| X2-L | sqlparse | ideas-x2-X2-L-43154389364.jsonl | 1 | claude-fable-5-2 | not recorded | - | - |
| X2-L | sqlparse | ideas-x2-X2-L-43154389364.jsonl | 2 | claude-fable-5-2 | not recorded | - | - |
| X2-L | tomli | ideas-x2-X2-L-43154393116.jsonl | 1 | claude-fable-5-2 | not recorded | - | - |
| X2-L | tomli | ideas-x2-X2-L-43154393116.jsonl | 2 | claude-fable-5-2 | not recorded | - | - |
| X2-L | mistune | ideas-x2-X2-L-43154396382.jsonl | 1 | claude-fable-5-2 | not recorded | - | - |
| X2-L | mistune | ideas-x2-X2-L-43154396382.jsonl | 2 | claude-fable-5-2 | not recorded | - | - |
| X2-L | sqlparse | ideas-x2-X2-L-43159100367.jsonl | 1 | claude-fable-5-2 | 19499 / 32000 (attempts claude-fable-5-2=19499) | end_turn | 12501 |
| X2-L | sqlparse | ideas-x2-X2-L-43159100367.jsonl | 2 | claude-fable-5-2 | 17622 / 32000 (attempts claude-fable-5-2=17622) | end_turn | 14378 |
| X2-L | tomli | ideas-x2-X2-L-43159103908.jsonl | 1 | claude-fable-5-2 | 14476 / 32000 (attempts claude-fable-5-2=14476) | end_turn | 17524 |
| X2-L | tomli | ideas-x2-X2-L-43159103908.jsonl | 2 | claude-fable-5-2 | 16175 / 32000 (attempts claude-fable-5-2=16175) | end_turn | 15825 |
| X2-L | mistune | ideas-x2-X2-L-43159107354.jsonl | 1 | claude-fable-5-2 | 15515 / 32000 (attempts claude-fable-5-2=15515) | end_turn | 16485 |
| X2-L | mistune | ideas-x2-X2-L-43159107354.jsonl | 2 | claude-fable-5-2 | 32000 / 32000 (attempts claude-fable-5-2=32000) | max_tokens | 0 |

## 2 Headroom per arm

| arm | leap calls | replied | max_tokens stops | least headroom | median headroom | most headroom |
| --- | --- | --- | --- | --- | --- | --- |
| X2-L | 24 | 6 | 1 | 0 | 14378 | 17524 |
