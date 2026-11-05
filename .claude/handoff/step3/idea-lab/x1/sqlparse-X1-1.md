# X1 ideas: sqlparse, X1-1

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip regex attempts at each position via first-character dispatch in Lexer.get_tokens | precompute_or_cache | sqlparse/lexer.py\:139-143 | 21.4% | unknown | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Replace lambda/imt in token_next_by with specialised inline scan loop | specialised_fast_path | sqlparse/sql.py\:265-266 | - | infeasible | Inline token-type matching in imt and _token_matching to cut per-token call overhead (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Speed up Token.match\: avoid generator and upper() for keyword comparisons | specialised_fast_path | sqlparse/sql.py\:118-121 | - | infeasible | Cache upper-cased match values and skip regeneration in Token.match (X1-0) | inconclusive | 1.6% / 3.0% | 9465281 → 9343917 calls (-1.3%) | obvious | claude-sonnet-5-5 | True |
| 4 | Cheap non-matching fast exit in _group before calling match closure and token_next | remove_work | sqlparse/engine/grouping.py\:511-515 | 20.8% | unknown | - | inconclusive | 0.4% / 3.0% | 9465281 → 9468689 calls (+0.0%) | obvious | claude-sonnet-5-5 | True |
| 5 | Cache Token.__init__ type flags per ttype in the statement splitter | precompute_or_cache | sqlparse/engine/statement_splitter.py\:135-137 | - | infeasible | Cache flatten results and slim the statement splitter's per-token work (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Skip group_functions pre-scan upper() calls\: compute flags only when CREATE/TABLE present | remove_work | sqlparse/engine/grouping.py\:385-389 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Avoid list(tlist) copy and per-token work in _group_matching by pre-checking token presence | remove_work | sqlparse/engine/grouping.py\:61-64 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 8 | Skip recursion into groups in _group when cls/match cannot apply (leaf-only guard) | loop_or_control_flow | sqlparse/engine/grouping.py\:511-513 | 20.8% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 9 | Statement splitter\: avoid repeated tuple builds and upper() for non-keyword tokens | remove_work | sqlparse/engine/statement_splitter.py\:135-137 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 10 | Merge Lexer keyword dictionaries into one dict for single-lookup keyword classification | precompute_or_cache | sqlparse/lexer.py\:100-105 | - | - | - | - | - | - | assume_less | claude-sonnet-5 | False |
| 11 | Defer TokenList string-value computation in sql.py to first access instead of eager flatten() at construction | lazy_or_streaming | sqlparse/sql.py\:159-163 | - | - | - | - | - | - | assume_less | claude-sonnet-5 | False |
| 12 | Replace throwaway list-comprehension parent-assignment in TokenList.__init__ with a plain loop | remove_work | sqlparse/sql.py\:159-163 | - | - | - | - | - | - | assume_less | claude-sonnet-5 | False |
| 13 | Flatten TokenList via an explicit stack instead of nested recursive generators in sql.py | loop_or_control_flow | sqlparse/sql.py\:212-216 | - | infeasible | Cache flatten results and slim the statement splitter's per-token work (A) | - | - | - | name_the_problem | claude-haiku-5-5 | True |
| 14 | Use one merged keyword-to-type dictionary in the lexer instead of scanning nine dictionaries per keyword | data_structure | sqlparse/lexer.py\:146-147 | 21.4% | - | - | - | - | - | name_the_problem | claude-haiku-5-5 | False |
| 15 | Lexer.get_tokens\: advance by match end instead of enumerate+consume, and memoise keyword lookups by uppercased text | loop_or_control_flow | sqlparse/lexer.py\:137-140 | 21.4% | - | - | - | - | - | recombine | claude-opus-5-5 | False |
| 16 | Lexer\: compile SQL_REGEX into one ordered alternation and map the matched outer group to its action | algorithm | sqlparse/lexer.py\:139-143 | 21.4% | - | - | - | - | - | recombine | claude-opus-5-5 | False |
| 17 | TokenList.flatten\: replace recursive yield-from generators with an explicit iterator stack | loop_or_control_flow | sqlparse/sql.py\:212-216 | - | - | - | - | - | - | recombine | claude-opus-5-5 | False |
| 18 | Specialised whitespace-skipping scan in TokenList.token_next instead of a closure through _token_matching | specialised_fast_path | sqlparse/sql.py\:297-300 | - | - | - | - | - | - | recombine | claude-opus-5-5 | False |
| 19 | StatementSplitter.process\: identity-set ttype tests and an inline fast path skipping _change_splitlevel | specialised_fast_path | sqlparse/engine/statement_splitter.py\:135-137 | - | - | - | - | - | - | recombine | claude-opus-5-5 | False |
| 20 | Replace enumerate+consume with explicit position loop in Lexer.get_tokens | loop_or_control_flow | sqlparse/lexer.py\:137-140 | 21.4% | - | - | - | - | - | resolve_tradeoff | claude-fable-5 | False |
| 21 | Skip grouping passes whose opening token never occurs, via one presence scan per statement | remove_work | sqlparse/engine/grouping.py\:61-64 | - | infeasible | Skip whole grouping passes whose trigger tokens are absent, using a per-statement token inventory in grouping.group (X1-1) | - | - | - | resolve_tradeoff | claude-fable-5 | False |
| 22 | Compute TokenList.value lazily to avoid O(n²) string joins during grouping | lazy_or_streaming | sqlparse/engine/grouping.py\:71-73 | - | unknown | - | - | - | - | resolve_tradeoff | claude-fable-5 | True |
| 23 | Skip _change_splitlevel and end-of-statement checks for whitespace tokens in StatementSplitter.process | specialised_fast_path | sqlparse/engine/statement_splitter.py\:112-115 | - | - | - | - | - | - | resolve_tradeoff | claude-fable-5 | False |
| 24 | Fast skip-whitespace scan in TokenList.token_next when comments are not skipped | specialised_fast_path | sqlparse/sql.py\:297-300 | - | - | - | - | - | - | resolve_tradeoff | claude-fable-5 | False |
| 25 | Memoize per-ttype boolean flags in sql.Token.__init__ with a module-level dict | precompute_or_cache | sqlparse/engine/statement_splitter.py\:114-115 | - | - | - | - | - | - | resolve_tradeoff | claude-fable-5 | False |
| 26 | Drive Lexer.get_tokens by an explicit position instead of enumerate plus consume() | loop_or_control_flow | sqlparse/lexer.py\:137-140 | 21.4% | - | - | - | - | - | far | claude-fable-5-1 | False |
| 27 | Fuse consecutive backreference-free SQL_REGEX patterns into alternation regexes in Lexer.set_SQL_REGEX | algorithm | sqlparse/lexer.py\:139-143 | 21.4% | - | - | - | - | - | far | claude-fable-5-1 | False |
| 28 | Build TokenList value from children's values, bypassing recursive flatten and Token.__init__ in TokenList.__init__ | precompute_or_cache | sqlparse/sql.py\:212-216 | - | - | - | - | - | - | far | claude-fable-5-1 | False |
| 29 | In _group, take the next non-whitespace token from the snapshot list instead of tlist.token_next | remove_work | sqlparse/engine/grouping.py\:515-517 | 20.8% | - | - | - | - | - | far | claude-fable-5-1 | False |
| 30 | Skip whole _group_matching passes when the statement contains no M_OPEN token at all | remove_work | sqlparse/engine/grouping.py\:61-64 | - | infeasible | Skip whole grouping passes whose trigger tokens are absent, using a per-statement token inventory in grouping.group (X1-1) | - | - | - | far | claude-fable-5-1 | False |
| 31 | Turn grouping.py ttype tuples into frozensets so imt's type membership is a hash lookup | data_structure | sqlparse/utils.py\:103-105 | 14.7% | feasible | - | - | - | - | far | claude-fable-5-1 | True |
| 32 | Skip whole grouping passes whose trigger tokens are absent, using a per-statement token inventory in grouping.group | remove_work | sqlparse/engine/grouping.py\:511-513 | 20.8% | feasible | - | keep (graded by opus-5, unvalidated) | 14.6% / 6.2% | 9465281 → 7698473 calls (-18.7%) | leap | claude-opus-5-5 | True |
| 33 | Lex with one ordered alternation regex (named groups, lastgroup dispatch) instead of looping over SQL_REGEX per position | algorithm | sqlparse/lexer.py\:137-140 | 21.4% | infeasible | Lexer\: use one combined alternation regex with named groups instead of looping rules per character (X1-3) | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
