# X1 ideas: pyparsing, X1-2

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip ParseResults construction when parse action returns a fresh result in _parseNoCache fast path | specialised_fast_path | pyparsing/core.py\:964-967 | - | infeasible | Slim down _parseNoCache fast path for the no-packrat, no-debug case (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Inline whitespace skipping in preParse using a precomputed flag and avoid redundant length lookups | specialised_fast_path | pyparsing/core.py\:904-905 | - | infeasible | Inline whitespace skipping in preParse and skip it when there are no ignorables or whitespace chars (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Lighter ParseResults.__init__/__new__ for the unnamed-token case | specialised_fast_path | pyparsing/results.py\:214-216 | - | infeasible | Cheaper ParseResults construction via a fast path in __new__ and __init__ (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Hoist _check_operand_follows and reduce_operators closures out of the infix parse loop | loop_or_control_flow | pyparsing/helpers.py\:1317-1318 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Avoid cost in ParseElementEnhance.parseImpl by moving the except handling off the success path | specialised_fast_path | pyparsing/core.py\:5155-5156 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Skip the throwaway StringEnd grammar construction in parse_string when parse_all is set | precompute_or_cache | pyparsing/core.py\:1336-1338 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Avoid redundant as_list() calls on ParseResults in infix operator token extraction | remove_work | pyparsing/helpers.py\:1196-1196 | - | infeasible | Avoid redundant second parse of base_expr lookahead and as_list conversions in infix operator handling (X1-0) | inconclusive | 1.2% / 2.5% | 1890616 → 1890616 calls (+0.0%) | eliminate | claude-sonnet-5-5 | True |
| 8 | Skip packrat-style Exception object creation on infix base_expr failure by avoiding repeated ParseResults emptiness test | loop_or_control_flow | pyparsing/helpers.py\:1317-1320 | - | infeasible | Hoist _check_operand_follows closure out of the infix parse loop in _InfixNotation.parseImpl (X1-1) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | Skip exception-and-reduction scaffolding\: hoist per-iteration preParse try/except in infix loop to first-char dispatch | specialised_fast_path | pyparsing/helpers.py\:1346-1349 | - | unknown | - | inconclusive | 1.7% / 3.3% | 1890616 → 1909232 calls (+1.0%) | name_the_problem | claude-sonnet-5-5 | True |
| 10 | Skip the per-parse Empty()+StringEnd() construction in parse_string by caching one shared end matcher | precompute_or_cache | pyparsing/core.py\:1337-1338 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 11 | Cache whitespace-skip decision in infix parse loop\: avoid preParse call when next char is not whitespace | specialised_fast_path | pyparsing/helpers.py\:1185-1188 | - | feasible | - | inconclusive | -0.0% / 2.0% | 1890616 → 1859830 calls (-1.6%) | recombine | claude-sonnet-5-5 | True |
| 12 | Replace operator-stack dicts in infix parse with tuples/lists is risky; instead precompute per-level constants once per parseImpl call | precompute_or_cache | pyparsing/helpers.py\:1173-1174 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 13 | Skip building a result container twice for parse actions that return None in _parseNoCache | specialised_fast_path | pyparsing/core.py\:967-968 | - | infeasible | Slim down _parseNoCache fast path for the no-packrat, no-debug case (A) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 14 | Replace per-exception __init__ tuple building with lazy args in ParseBaseException | lazy_or_streaming | pyparsing/exceptions.py\:65-66 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 15 | Skip postParse call-through and ParseResults rewrap when tokens already a ParseResults without name in _parseNoCache | specialised_fast_path | pyparsing/core.py\:962-967 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 16 | Avoid repeated state-dict allocation for operator stack entries in infix parseImpl by using tuples/lists | representation | pyparsing/helpers.py\:1366-1370 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 17 | Cache the 'in (LPAR, TERNARY...)' tuple as a module-level frozenset check in reduce_operators | precompute_or_cache | pyparsing/helpers.py\:1173-1173 | - | feasible | - | - | - | - | far | claude-sonnet-5-5 | False |
| 18 | First-character dispatch index for operator attempts in _InfixNotation.parseImpl, skipping _parse calls that must fail | data_structure | pyparsing/helpers.py\:1193-1196 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
