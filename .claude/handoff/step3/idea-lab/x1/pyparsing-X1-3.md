# X1 ideas: pyparsing, X1-3

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hoist closures and per-iteration state out of _InfixNotation.parseImpl main loop | remove_work | pyparsing/helpers.py\:1317-1320 | - | infeasible | Hoist _check_operand_follows closure out of the infix parse loop in _InfixNotation.parseImpl (X1-1) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Fast path in ParseResults.__init__ for unnamed results to skip deprecate_argument call | specialised_fast_path | pyparsing/results.py\:214-218 | - | infeasible | Cheaper ParseResults construction via a fast path in __new__ and __init__ (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Skip whitespace with a precompiled regex or lstrip-style scan in preParse | specialised_fast_path | pyparsing/core.py\:902-905 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Skip ParseResults rewrap in _parseNoCache when postParse returns an unnamed ParseResults and no names are needed | remove_work | pyparsing/core.py\:964-966 | - | infeasible | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set (X1-3) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 5 | Hoist debug/failAction check into a precomputed flag to skip the debugging branch setup in _parseNoCache | remove_work | pyparsing/core.py\:919-920 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 6 | Skip postParse call and ParseResults rewrap in _parseNoCache when postParse is the base identity | specialised_fast_path | pyparsing/core.py\:962-966 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 7 | Hoist debug/failAction check into a precomputed flag so _parseNoCache takes a lean path | loop_or_control_flow | pyparsing/core.py\:949-954 | - | infeasible | Slim down _parseNoCache fast path for the no-packrat, no-debug case (A) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 8 | Skip ParseResults construction when parseImpl already returns an unnamed ParseResults | allocation_or_copying | pyparsing/core.py\:964-966 | - | infeasible | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set (X1-3) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set | specialised_fast_path | pyparsing/core.py\:964-966 | - | feasible | - | inconclusive | 3.0% / 3.3% | 1890616 → 1805629 calls (-4.5%) | name_the_problem | claude-sonnet-5-5 | True |
| 10 | Split _parseNoCache into a specialised non-debug, no-failAction path chosen at element setup | specialised_fast_path | pyparsing/core.py\:925-929 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 11 | Skip the preParse call entirely for elements that cannot skip anything at this location | specialised_fast_path | pyparsing/core.py\:925-928 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Split _parseNoCache into a lean non-debug path with inlined no-action ParseResults shortcut | specialised_fast_path | pyparsing/core.py\:925-929 | - | infeasible | Slim down _parseNoCache fast path for the no-packrat, no-debug case (A) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 13 | Skip preParse call entirely when element has no ignoreExprs and does not skip whitespace or inline the scan | specialised_fast_path | pyparsing/core.py\:898-902 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 14 | MatchFirst.parseImpl\: avoid exception-object bookkeeping with locals and first-element fast path | precompute_or_cache | pyparsing/core.py\:4872-4875 | - | unknown | - | inconclusive | -3.6% / 10.0% | 1890616 → 1909192 calls (+1.0%) | recombine | claude-sonnet-5-5 | True |
| 15 | Avoid ParseResults allocation of throwaway list/set in __new__ via lazily created _all_names | allocation_or_copying | pyparsing/results.py\:188-191 | - | unknown | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | True |
| 16 | Fast-path operand wrapping in _InfixNotation.parseImpl final result to avoid redundant ParseResults construction | remove_work | pyparsing/helpers.py\:1231-1233 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 17 | Split _parseNoCache into a specialised no-debug, no-failAction path with parse-action fast loop | specialised_fast_path | pyparsing/core.py\:919-922 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 18 | Skip ParseResults construction when tokens is already an unnamed ParseResults in _parseNoCache | allocation_or_copying | pyparsing/core.py\:964-966 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 19 | Cache a precomputed per-element 'plain' flag so _parseNoCache skips parseAction/postParse checks | remove_work | pyparsing/core.py\:962-964 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 20 | Pre-check operator/paren candidates in _InfixNotation.parseImpl with the element's own matcher before calling _parse | specialised_fast_path | pyparsing/helpers.py\:1345-1349 | - | infeasible | Skip exception-and-reduction scaffolding\: hoist per-iteration preParse try/except in infix loop to first-char dispatch (X1-2) | keep (graded by opus-5, unvalidated) | 4.4% / 3.0% | 1890616 → 1738447 calls (-8.0%) | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
