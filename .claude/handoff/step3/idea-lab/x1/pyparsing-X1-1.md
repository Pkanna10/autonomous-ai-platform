# X1 ideas: pyparsing, X1-1

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hoist _check_operand_follows closure out of the infix parse loop in _InfixNotation.parseImpl | remove_work | pyparsing/helpers.py\:1317-1320 | 67.8% | feasible | - | inconclusive | 1.7% / 3.5% | 1890616 → 1890616 calls (+0.0%) | obvious | claude-sonnet-5-5 | True |
| 2 | Replace per-character whitespace loop in ParserElement.preParse with a precomputed skip | algorithm | pyparsing/core.py\:904-904 | 4.8% | infeasible | Replace char-by-char whitespace skipping in ParserElement.preParse with a precompiled character-class regex (X1-1) | - | - | - | eliminate | claude-haiku-5-5 | False |
| 3 | Skip infix operator attempts whose first character cannot match, in _InfixNotation.parseImpl | specialised_fast_path | pyparsing/helpers.py\:1195-1195 | 67.8% | infeasible | Skip exception-and-reduction scaffolding\: hoist per-iteration preParse try/except in infix loop to first-char dispatch (X1-2) | keep | 3.5% / 3.5% | 1890616 → 1763198 calls (-6.7%) | eliminate | claude-haiku-5-5 | True |
| 4 | Avoid rebuilding ParseResults when a parsed result is already a ParseResults with no name, in _parseNoCache | remove_work | pyparsing/core.py\:965-965 | 75.7% | infeasible | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set (X1-3) | - | - | - | eliminate | claude-haiku-5-5 | False |
| 5 | Skip ParseResults re-wrapping in _parseNoCache when tokens already is a ParseResults and no resultsName | specialised_fast_path | pyparsing/core.py\:962-966 | 75.7% | - | - | - | - | - | assume_less | claude-opus-5-5 | False |
| 6 | Early-return in ParseResults.__init__ before deprecate_argument when kwargs is empty and name is None | specialised_fast_path | pyparsing/results.py\:214-218 | - | infeasible | Cheaper ParseResults construction via a fast path in __new__ and __init__ (A) | - | - | - | assume_less | claude-opus-5-5 | False |
| 7 | Cache the parse_all end-of-text checker instead of building Empty()+StringEnd() on every parse_string call | precompute_or_cache | pyparsing/core.py\:1335-1338 | - | - | - | - | - | - | assume_less | claude-opus-5-5 | False |
| 8 | Pre-filter simple literal operators by startswith in _InfixNotation.parseImpl to avoid failed _parse calls | specialised_fast_path | pyparsing/helpers.py\:1193-1195 | 67.8% | - | - | - | - | - | assume_less | claude-opus-5-5 | False |
| 9 | Replace char-by-char whitespace skipping in ParserElement.preParse with a precompiled character-class regex | loop_or_control_flow | pyparsing/core.py\:901-905 | 4.8% | unknown | - | reject | -5.3% / 3.5% | 1890616 → 2113713 calls (+11.8%) | name_the_problem | claude-fable-5 | True |
| 10 | Skip redundant ParseResults re-wrap in _parseNoCache when tokens is already a ParseResults and no results name | remove_work | pyparsing/core.py\:964-966 | 75.7% | infeasible | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set (X1-3) | - | - | - | name_the_problem | claude-fable-5 | False |
| 11 | Replace per-operator dict records on the operator stack with slotted record objects in _InfixNotation.parseImpl | data_structure | pyparsing/helpers.py\:1366-1371 | 67.8% | unknown | - | - | - | - | name_the_problem | claude-fable-5 | False |
| 12 | Exact-type list fast path in ParseResults.__new__ to skip double isinstance checks | specialised_fast_path | pyparsing/results.py\:192-197 | 7.8% | - | - | - | - | - | name_the_problem | claude-fable-5 | False |
| 13 | Hoist bound-method and attribute lookups out of the main while loop in _InfixNotation.parseImpl | loop_or_control_flow | pyparsing/helpers.py\:1184-1188 | 67.8% | - | - | - | - | - | name_the_problem | claude-fable-5 | False |
| 14 | Reuse parseImpl's ParseResults in _parseNoCache when the element has no results name (skip __new__/__init__) | remove_work | pyparsing/core.py\:964-966 | 75.7% | infeasible | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set (X1-3) | - | - | - | recombine | claude-fable-5-1 | False |
| 15 | Precompute per-element flags for default preParse/postParse and inline whitespace skip in _parseNoCache | remove_work | pyparsing/core.py\:925-929 | 75.7% | - | - | - | - | - | recombine | claude-fable-5-1 | False |
| 16 | ParseResults construction fast path\: skip deprecate_argument when no kwargs and use exact-type list check in __new__ | specialised_fast_path | pyparsing/results.py\:214-216 | - | infeasible | Cheaper ParseResults construction via a fast path in __new__ and __init__ (A) | - | - | - | recombine | claude-fable-5-1 | True |
| 17 | Skip redundant preParse in _InfixNotation sub-expression calls when whitespace settings match the already-skipped loc | remove_work | pyparsing/helpers.py\:1214-1216 | 67.8% | - | - | - | - | - | recombine | claude-fable-5-1 | False |
| 18 | Skip ParseResults construction in _parseNoCache when tokens is already a ParseResults and no name is set | specialised_fast_path | pyparsing/core.py\:964-966 | 75.7% | infeasible | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set (X1-3) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 19 | Replace per-character whitespace-skip loop in preParse with a single precompiled regex match | specialised_fast_path | pyparsing/core.py\:901-905 | 4.8% | infeasible | Replace char-by-char whitespace skipping in ParserElement.preParse with a precompiled character-class regex (X1-1) | - | - | - | far | claude-sonnet-5 | False |
| 20 | First-character dispatch table for operator/paren attempts in _InfixNotation.parseImpl to skip doomed _parse calls | specialised_fast_path | pyparsing/helpers.py\:1346-1349 | 67.8% | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 21 | Bypass ParseResults.__init__ for unnamed results in _parseNoCache by calling __new__ directly and setting _modal | specialised_fast_path | pyparsing/core.py\:964-966 | 75.7% | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
