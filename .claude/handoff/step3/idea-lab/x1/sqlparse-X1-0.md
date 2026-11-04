# X1 ideas: sqlparse, X1-0

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Specialise token_next_by to avoid lambda and imt call per token in _token_matching | specialised_fast_path | sqlparse/sql.py\:264-266 | - | infeasible | Inline token-type matching in imt and _token_matching to cut per-token call overhead (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Precompute the stripped lexer regex callback with a position-skipping loop instead of enumerate/consume | loop_or_control_flow | sqlparse/lexer.py\:137-140 | - | infeasible | Optimize lexer get_tokens loop with a precompiled combined regex and fewer per-token operations (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Cache upper-cased match values and skip regeneration in Token.match | specialised_fast_path | sqlparse/sql.py\:118-121 | - | feasible | - | inconclusive | 1.5% / 3.0% | 9465281 → 9343917 calls (-1.3%) | obvious | claude-sonnet-5-5 | True |
| 4 | Avoid list copy and redundant checks in _group and _group_matching by precomputing per-pass fast paths | specialised_fast_path | sqlparse/engine/grouping.py\:61-64 | - | feasible | - | keep | 3.4% / 2.6% | 9465281 → 9199169 calls (-2.8%) | obvious | claude-sonnet-5-5 | True |
| 5 | Skip full grouping passes for token lists lacking trigger tokens in _group | remove_work | sqlparse/engine/grouping.py\:499-503 | - | infeasible | Cheap non-matching fast exit in _group before calling match closure and token_next (X1-1) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 6 | Skip trailing-token scans and use token-type check for group passes in _group_matching | specialised_fast_path | sqlparse/engine/grouping.py\:61-64 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Skip the split-level keyword logic for non-keyword tokens and avoid per-token tuple builds in StatementSplitter.process | remove_work | sqlparse/engine/statement_splitter.py\:112-115 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 8 | Make _TokenType containment a fast identity/parent-chain test avoided via is_keyword flags in lexer path | precompute_or_cache | sqlparse/lexer.py\:139-143 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 9 | Skip the sql.Token round trip\: avoid per-token re-stringifying in TokenList.__init__ during splitting | remove_work | sqlparse/engine/statement_splitter.py\:112-115 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 10 | Memoise keyword lookup results in Lexer.is_keyword per distinct word | precompute_or_cache | sqlparse/lexer.py\:100-103 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 11 | Fast path for flatten and __str__ of TokenList via cached leaf iteration without nested generators | loop_or_control_flow | sqlparse/sql.py\:212-216 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 12 | Cache compiled regexes in Token.match regex branch | precompute_or_cache | sqlparse/sql.py\:110-111 | - | unknown | - | - | - | - | assume_less | claude-sonnet-5-5 | True |
| 13 | Lexer\: single combined alternation regex dispatching by lastgroup instead of trying each rule per position | algorithm | sqlparse/lexer.py\:139-143 | - | infeasible | Lexer\: use one combined alternation regex with named groups instead of looping rules per character (X1-3) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 14 | Cache per-token flattened string\: avoid recomputing str() of groups in TokenList init and group_tokens | precompute_or_cache | sqlparse/sql.py\:162-163 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 15 | Statement splitter\: precomputed keyword-type fast reject and skip Token double construction work | specialised_fast_path | sqlparse/engine/statement_splitter.py\:112-115 | - | infeasible | Cache flatten results and slim the statement splitter's per-token work (A) | - | - | - | name_the_problem | claude-sonnet-5-5 | True |
| 16 | Memoise _TokenType.__contains__ via parent-chain set, used by Token init and imt | data_structure | sqlparse/utils.py\:103-105 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 17 | Fuse the lexer's per-position regex loop into one combined alternation regex with lastindex dispatch | algorithm | sqlparse/lexer.py\:139-143 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 18 | Fuse the splitter's Token creation and per-token checks via a keyword-only slow path | specialised_fast_path | sqlparse/engine/statement_splitter.py\:112-115 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 19 | Make _TokenType.__contains__ a precomputed frozenset lookup with ancestry cached per type | precompute_or_cache | sqlparse/utils.py\:103-105 | - | infeasible | Cache token type containment in _TokenType.__contains__ (X1-3) | - | - | - | recombine | claude-sonnet-5-5 | True |
| 20 | Replace the Token constructor's repeated ttype membership tests with a per-ttype flag cache | precompute_or_cache | sqlparse/sql.py\:56-58 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 21 | Skip the Token construction work in the splitter's per-token path by caching split-level decisions per (ttype, value) | specialised_fast_path | sqlparse/engine/statement_splitter.py\:112-115 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 22 | Memoise is_keyword results per lexed word in Lexer.get_tokens/is_keyword | precompute_or_cache | sqlparse/lexer.py\:100-103 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 23 | Make imt fast-path single-type checks and avoid isinstance on list for m/t | specialised_fast_path | sqlparse/utils.py\:89-93 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 24 | Skip recursive _group descent into groups that cannot contain a match, using a cheap flat precheck | remove_work | sqlparse/engine/grouping.py\:499-503 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 25 | Cache compiled regexes in Token.match regex branch and avoid generator wrapping | specialised_fast_path | sqlparse/sql.py\:105-108 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 26 | Skip the splitter's Token construction cost via cached ttype membership in _change_splitlevel | remove_work | sqlparse/engine/statement_splitter.py\:135-137 | - | infeasible | Cache flatten results and slim the statement splitter's per-token work (A) | - | - | - | far | claude-sonnet-5-5 | False |
| 27 | Replace per-token regex scan in lexer with one combined alternation regex dispatched by lastgroup | algorithm | sqlparse/lexer.py\:139-143 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 28 | Memoize per-class grouping predicates by token type in _group via a ttype-keyed cache | specialised_fast_path | sqlparse/engine/grouping.py\:515-517 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 29 | Make tokens.__contains__ checks cheaper by caching ancestor sets on token types | precompute_or_cache | sqlparse/sql.py\:56-58 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 30 | Collapse the sequential SQL_REGEX loop in Lexer.get_tokens into combined alternation regexes dispatched by lastindex | algorithm | sqlparse/lexer.py\:139-140 | - | infeasible | Lexer\: use one combined alternation regex with named groups instead of looping rules per character (X1-3) | - | - | - | leap | claude-opus-5-5 | False |
| 31 | Memoise lexer output per input string so format() and parse() of the same statement text lex only once | precompute_or_cache | sqlparse/lexer.py\:137-140 | - | infeasible | Memoise lexer output per input string in Lexer.get_tokens, invalidated on any syntax reconfiguration (X1-2) | - | - | - | leap | claude-opus-5-5 | False |
| 32 | Build TokenList.value incrementally from children's values instead of re-flattening the whole subtree on every group | algorithm | sqlparse/sql.py\:212-216 | - | unknown | - | inconclusive (graded by opus-5, unvalidated) | -0.1% / 5.2% | 9465281 → 8987483 calls (-5.0%) | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
