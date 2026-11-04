# X1 ideas: pyparsing, X1-0

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip whitespace scan fast path in ParserElement.preParse | specialised_fast_path | pyparsing/core.py\:902-905 | - | infeasible | Inline whitespace skipping in preParse and skip it when there are no ignorables or whitespace chars (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Skip ParseResults wrapping of tokens already a ParseResults without name in _parseNoCache | remove_work | pyparsing/core.py\:964-966 | - | infeasible | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set (X1-3) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 3 | Avoid redundant second parse of base_expr lookahead and as_list conversions in infix operator handling | allocation_or_copying | pyparsing/helpers.py\:1196-1196 | - | feasible | - | inconclusive | 0.5% / 3.1% | 1890616 → 1894090 calls (+0.2%) | eliminate | claude-sonnet-5-5 | True |
| 4 | Skip IndexError try-block and preParse call when element cannot skip whitespace in _parseNoCache | remove_work | pyparsing/core.py\:962-962 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 5 | Skip ParseResults construction work for no-name, no-action elements in _parseNoCache | specialised_fast_path | pyparsing/core.py\:964-966 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 6 | Avoid deprecate_argument call in ParseResults.__init__ when no kwargs passed | remove_work | pyparsing/results.py\:214-216 | - | infeasible | Cheaper ParseResults construction via a fast path in __new__ and __init__ (A) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 7 | Avoid redundant preParse and exception handling in _InfixNotation loop via cached whitespace loc | loop_or_control_flow | pyparsing/helpers.py\:1317-1318 | - | infeasible | Hoist _check_operand_follows closure out of the infix parse loop in _InfixNotation.parseImpl (X1-1) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 8 | Hoist per-call ParseResults construction checks\: bypass __init__ kwargs deprecation lookup | remove_work | pyparsing/results.py\:214-216 | - | infeasible | Cheaper ParseResults construction via a fast path in __new__ and __init__ (A) | - | - | - | name_the_problem | claude-sonnet-5-5 | True |
| 9 | Skip postParse/ParseResults rebuild when tokens is already ParseResults with no results name in _parseNoCache | specialised_fast_path | pyparsing/core.py\:964-966 | - | infeasible | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set (X1-3) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 10 | Cache the operator-stack record kinds and avoid per-iteration closure creation in infix parseImpl | loop_or_control_flow | pyparsing/helpers.py\:1317-1320 | - | infeasible | Hoist _check_operand_follows closure out of the infix parse loop in _InfixNotation.parseImpl (X1-1) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 11 | Use regex-based whitespace run skipping in preParse (search for first non-space) | algorithm | pyparsing/core.py\:904-905 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Skip ParseResults construction/name handling in _parseNoCache when no results name and tokens already a ParseResults | specialised_fast_path | pyparsing/core.py\:964-966 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 13 | Precompute ParseResults empty-name fast constructor path via __slots__-free lean init for name-less results | remove_work | pyparsing/results.py\:214-218 | - | infeasible | Cheaper ParseResults construction via a fast path in __new__ and __init__ (A) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 14 | Cache the string-length and whitespace-set locals in preParse by single-char peek before loop | specialised_fast_path | pyparsing/core.py\:904-905 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 15 | Replace per-parse dict operator frames and closure creation in _InfixNotation.parseImpl with hoisted helpers | loop_or_control_flow | pyparsing/helpers.py\:1317-1318 | - | infeasible | Hoist _check_operand_follows closure out of the infix parse loop in _InfixNotation.parseImpl (X1-1) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 16 | Skip redundant preParse in infix loop when no ignorables and whitespace skip is a no-op | specialised_fast_path | pyparsing/helpers.py\:1185-1188 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 17 | Skip ParseResults construction work for unnamed elements in _parseNoCache via a lightweight fast path | specialised_fast_path | pyparsing/core.py\:964-966 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 18 | Cache whitespace-skipping state per element to bypass preParse call when nothing to skip | specialised_fast_path | pyparsing/core.py\:925-928 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 19 | Skip ParseResults construction work for unnamed results in _parseNoCache via lightweight path | remove_work | pyparsing/results.py\:214-218 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 20 | Avoid re-creating Empty()+StringEnd() grammar on every parse_string with parse_all | precompute_or_cache | pyparsing/core.py\:1337-1338 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 21 | Cache the whitespace-set emptiness check\: skip preParse call when nothing can be skipped in _parseNoCache | loop_or_control_flow | pyparsing/core.py\:925-929 | - | feasible | - | inconclusive | -0.3% / 3.1% | 1890616 → 1716926 calls (-9.2%) | far | claude-sonnet-5-5 | True |
| 22 | First-character guard for operator attempts in _InfixNotation.parseImpl to skip doomed _parse calls and exceptions | algorithm | pyparsing/helpers.py\:1346-1349 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 23 | Skip redundant ParseResults re-wrap in _parseNoCache when parseImpl already returned an unnamed ParseResults | remove_work | pyparsing/core.py\:964-966 | - | infeasible | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set (X1-3) | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
