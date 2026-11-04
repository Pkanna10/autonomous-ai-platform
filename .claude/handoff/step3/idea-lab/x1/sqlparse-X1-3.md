# X1 ideas: sqlparse, X1-3

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip whitespace-only regexes\: dispatch lexer on first character to a prefiltered rule list | loop_or_control_flow | sqlparse/lexer.py\:137-140 | - | infeasible | Skip regex attempts at each position via first-character dispatch in Lexer.get_tokens (X1-1) | keep | 3.6% / 2.0% | 9465281 → 9399845 calls (-0.7%) | obvious | claude-sonnet-5-5 | True |
| 2 | Fast-path imt and token_next_by to avoid lambda and repeated isinstance checks | specialised_fast_path | sqlparse/sql.py\:265-266 | - | infeasible | Inline token-type matching in imt and _token_matching to cut per-token call overhead (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Avoid generator and tuple rebuilds in Token.match for keyword values | allocation_or_copying | sqlparse/sql.py\:118-121 | - | infeasible | Cache upper-cased match values and skip regeneration in Token.match (X1-0) | inconclusive | 1.3% / 2.0% | 9465281 → 9343917 calls (-1.3%) | obvious | claude-sonnet-5-5 | True |
| 4 | Streamline StatementSplitter.process per-token checks | loop_or_control_flow | sqlparse/engine/statement_splitter.py\:135-137 | - | infeasible | Cache flatten results and slim the statement splitter's per-token work (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Cache token type containment in _TokenType.__contains__ | precompute_or_cache | sqlparse/utils.py\:101-104 | - | unknown | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Skip per-character enumerate and consume in lexer by using a manual position loop | loop_or_control_flow | sqlparse/lexer.py\:137-140 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Memoise keyword lookup results in lexer per uppercase value | precompute_or_cache | sqlparse/lexer.py\:146-147 | - | feasible | - | - | - | - | eliminate | claude-sonnet-5-5 | True |
| 8 | Avoid isinstance check on action by pre-tagging rules in the lexer rule list | specialised_fast_path | sqlparse/lexer.py\:144-146 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 9 | Lexer\: replace enumerate/consume skipping with a manual position loop | loop_or_control_flow | sqlparse/lexer.py\:137-140 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 10 | Lexer\: jump over text with a position-driven while loop instead of enumerate plus consume | loop_or_control_flow | sqlparse/lexer.py\:137-140 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 11 | Memoize keyword lookup in Lexer.is_keyword with a per-instance dict cache | precompute_or_cache | sqlparse/lexer.py\:100-103 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 12 | Lexer\: skip per-character enumerate and consume by using a position-driven while loop | loop_or_control_flow | sqlparse/lexer.py\:137-140 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 13 | Hoist per-token whitespace and group checks out of _group's loop via a precomputed match gate | specialised_fast_path | sqlparse/engine/grouping.py\:511-513 | - | infeasible | Reduce grouping pass overhead in _group and _group_matching (A) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | True |
| 14 | Specialise imt for the common single-TokenType and single-class call shapes by splitting it into separate fast helpers | loop_or_control_flow | sqlparse/utils.py\:95-98 | - | infeasible | Inline token-type matching in imt and _token_matching to cut per-token call overhead (A) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 15 | Lexer\: use one combined alternation regex with named groups instead of looping rules per character | algorithm | sqlparse/lexer.py\:139-143 | - | unknown | - | keep | 9.5% / 2.0% | 9465281 → 7795167 calls (-17.6%) | far | claude-sonnet-5-5 | True |
| 16 | Lexer\: skip the enumerate/consume machinery by jumping pos with a while loop | loop_or_control_flow | sqlparse/lexer.py\:149-152 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 17 | Lexer\: fuse all SQL_REGEX rules into one ordered-alternation regex and dispatch on lastindex | algorithm | - | - | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
