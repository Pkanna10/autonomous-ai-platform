# X1 ideas: sqlparse, X1-2

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip whitespace-only regex attempts via first-char dispatch in Lexer.get_tokens | loop_or_control_flow | sqlparse/lexer.py\:137-140 | - | infeasible | Optimize lexer get_tokens loop with a precompiled combined regex and fewer per-token operations (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Make imt avoid redundant work and fast-path single-ttype checks | specialised_fast_path | sqlparse/utils.py\:89-93 | - | infeasible | Inline token-type matching in imt and _token_matching to cut per-token call overhead (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Cache upper-cased match values and avoid generator in Token.match | specialised_fast_path | sqlparse/sql.py\:118-121 | - | infeasible | Cache upper-cased match values and skip regeneration in Token.match (X1-0) | inconclusive | 1.4% / 2.0% | 9465281 → 9343917 calls (-1.3%) | obvious | claude-sonnet-5-5 | True |
| 4 | Inline token matching in token_next_by and avoid per-call lambda and funcs normalization | loop_or_control_flow | sqlparse/sql.py\:265-266 | - | not reviewed | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Avoid enumerate and repeated list copies in StatementSplitter.process hot loop | specialised_fast_path | sqlparse/engine/statement_splitter.py\:112-115 | - | infeasible | Cache flatten results and slim the statement splitter's per-token work (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Skip no-op grouping passes in group_functions' pre-scan by avoiding double upper() per token | remove_work | sqlparse/engine/grouping.py\:385-388 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Avoid recomputing str(self) via flatten in TokenList.__init__ for new groups | remove_work | sqlparse/sql.py\:161-162 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 8 | Replace slicing-based token_index with list.index plus start in sql.py | allocation_or_copying | sqlparse/sql.py\:305-305 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 9 | Skip recurse-wrapped grouping passes via a single flattening-free sublist check in recurse wrapper | loop_or_control_flow | sqlparse/utils.py\:71-73 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 10 | Replace Token.__init__ T.Keyword/Whitespace/Newline containment checks with identity-based lookups | precompute_or_cache | sqlparse/sql.py\:56-58 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 11 | Avoid recomputing str(self) via flatten in TokenList.__init__ | remove_work | sqlparse/sql.py\:161-162 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 12 | Fast-path token_next for the default skip_ws case without closure and funcs wrapping | specialised_fast_path | sqlparse/sql.py\:297-300 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 13 | Single combined-regex lexer dispatch via lastgroup instead of sequential regex attempts | algorithm | sqlparse/lexer.py\:139-143 | - | infeasible | Lexer\: use one combined alternation regex with named groups instead of looping rules per character (X1-3) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 14 | Memoise Token.parent-free flatten string\: make TokenList.__str__ and group value construction avoid recursive generator | remove_work | sqlparse/sql.py\:161-162 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 15 | Skip per-pass _group recursion into subtrees without any possible match using a cheap token-type precheck | remove_work | sqlparse/engine/grouping.py\:499-501 | - | infeasible | Cheap non-matching fast exit in _group before calling match closure and token_next (X1-1) | inconclusive | 2.6% / 2.0% | 9465281 → 9410505 calls (-0.6%) | name_the_problem | claude-sonnet-5-5 | True |
| 16 | Replace Token.__init__ repeated T.Keyword containment checks with a ttype-keyed memo | precompute_or_cache | sqlparse/sql.py\:56-58 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 17 | Replace token_index slice-copy search with a bounded list.index in TokenList.token_index | allocation_or_copying | sqlparse/sql.py\:304-305 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 18 | Skip group_tokens-driven rescans\: precheck statement token types to skip grouping passes that cannot match | remove_work | sqlparse/engine/grouping.py\:499-503 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 19 | Replace token_index slicing copy with identity scan in TokenList.token_index | allocation_or_copying | sqlparse/sql.py\:304-305 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 20 | Fuse token_first/get_token scans\: replace token_next closure creation with specialised non-lambda paths | specialised_fast_path | sqlparse/sql.py\:297-300 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 21 | Cache SQL keyword lookup results per value in Lexer.is_keyword | precompute_or_cache | sqlparse/lexer.py\:100-103 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 22 | Skip recursion into non-matching groups in _group_matching passes via a cheap pre-scan of the token list | remove_work | sqlparse/engine/grouping.py\:41-45 | - | unknown | - | inconclusive | 0.5% / 2.0% | 9465281 → 9386369 calls (-0.8%) | resolve_tradeoff | claude-sonnet-5-5 | True |
| 23 | Precompute per-group keyword-presence check in group_functions without double upper() calls per token | remove_work | sqlparse/engine/grouping.py\:385-388 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 24 | Fast-path _group\: avoid per-token match call for tokens whose ttype cannot match by hoisting recursion and match | loop_or_control_flow | sqlparse/engine/grouping.py\:511-513 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 25 | Skip recursion into group-free sublists in the recurse decorator via a precomputed has-group check | loop_or_control_flow | sqlparse/utils.py\:70-74 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 26 | Cache the compiled regexes in Token.match regex path and the group_functions upper() scans | remove_work | sqlparse/engine/grouping.py\:385-390 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 27 | Avoid O(n) slice copy in TokenList.token_index | allocation_or_copying | sqlparse/sql.py\:304-305 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 28 | Skip grouping passes whose trigger token cannot occur, using a per-statement leaf inventory in group() | remove_work | sqlparse/engine/grouping.py\:511-513 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 29 | Replace the per-position regex loop in Lexer.get_tokens with one ordered master alternation regex | algorithm | sqlparse/lexer.py\:138-143 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 30 | Memoise lexer output per input string in Lexer.get_tokens, invalidated on any syntax reconfiguration | precompute_or_cache | sqlparse/lexer.py\:144-147 | - | feasible | - | - | - | - | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
