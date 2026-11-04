# X1 ideas: pyparsing, X1-4

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip ParseResults construction work for unnamed results in _parseNoCache fast path | remove_work | pyparsing/results.py\:214-218 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Fast path in ParseResults.__new__ by reordering type checks | specialised_fast_path | pyparsing/results.py\:192-197 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Cache whitespace skip via a precomputed fast check in preParse | specialised_fast_path | pyparsing/core.py\:902-905 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Hoist _check_operand_follows and reduce_operators closure creation out of the parse loop | loop_or_control_flow | pyparsing/helpers.py\:1317-1321 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
| Compile hot ParseResults construction path with Cython/mypyc extension for results.py | new_dependency | relax_dependency | claude-sonnet-5-5 | True | Compile pyparsing/results.py with mypyc (or Cython) as an optional build-time extension, so ParseResults __new__/__init__ run as C code. Keep the pure-Python module as fallback if the extension is mi… |
| Compile core.py parse engine (_parseNoCache, preParse, parseImpl) with mypyc/Cython | new_dependency | relax_dependency | claude-sonnet-5-5 | True | Build core.py as an optional compiled extension so the dispatch loop in _parseNoCache, preParse's whitespace skipping, and the And/MatchFirst/Forward parseImpl methods avoid interpreter overhead. Ret… |
| Precompute per-element whitespace-skip and fast-path flags at streamline time to drop preParse call overhead | install_precompute | relax_precompute | claude-sonnet-5-5 | True | At build or streamline time, compute for each element a flag saying whether preParse is a no-op (no ignoreExprs and no skipWhitespace). Also precompute a regex-based skipper from whiteChars (a compil… |
| Pre-bind exception templates\: build ParseException instances once per element and reuse for non-debug failures | install_precompute | relax_precompute | claude-sonnet-5-5 | False | - |
| Compile first-character dispatch table for MatchFirst alternatives at streamline time | install_precompute | relax_precompute | claude-sonnet-5-5 | True | During streamline, compute for each MatchFirst alternative the set of possible first characters, or mark it unknown when it is not computable (Regex, Forward and so on). Build a dict from character t… |
| Add a no-results fast-path parse entry point that returns only end loc for lookahead and operand checks | api_change | relax_api | claude-sonnet-5-5 | True | Add a new internal method on ParserElement (a match-only variant of _parseNoCache) that returns just the end location and skips ParseResults construction and parse actions. Change the probe calls in … |
| Replace per-operator dict records in _InfixNotation.parseImpl with tuples or slotted objects | api_change | relax_api | claude-sonnet-5-5 | True | The operator stack currently stores a dict with string keys for each operator and compares enum types by lookup. Replace the dicts with a small __slots__ class or list records, and update _apply_oper… |
| Make ParseBaseException construction lazy by storing only loc and the element, with the message and pstr built on access | api_change | relax_api | claude-sonnet-5-5 | False | - |
