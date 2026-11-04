# X1 ideas: sqlparse, X1-4

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip non-matching lexer regexes by dispatching on the first character in Lexer.get_tokens | precompute_or_cache | sqlparse/lexer.py\:139-143 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Fast path in imt for common argument shapes and avoid per-call lambda in token_next_by | loop_or_control_flow | sqlparse/sql.py\:265-266 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Cache token type containment test in _TokenType.__contains__ users via identity fast path | precompute_or_cache | sqlparse/sql.py\:118-121 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Cheaper statement splitter loop\: hoist checks and avoid repeated ttype containment tests | specialised_fast_path | sqlparse/engine/statement_splitter.py\:112-115 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
| Replace per-character regex-table lexer loop with a single combined regex scanner via the 'regex' package | new_dependency | relax_dependency | claude-sonnet-5-5 | True | Add the third-party 'regex' package and compile the whole SQL_REGEX table into one alternation with named or numbered branches, keeping the original priority order. Scan with a single finditer-style … |
| Compile the lexer hot loop and token-list helpers with mypyc or Cython-compiled extension modules | new_dependency | relax_dependency | claude-sonnet-5-5 | True | Compile sqlparse/utils.py and the Token and TokenList classes in sql.py into native extensions (mypyc or Cython in pure-Python mode) as an optional build, falling back to the Python sources. Add type… |
| Build-time combined lexer regex with first-character dispatch table generated at install | install_precompute | relax_precompute | claude-sonnet-5-5 | True | Generate at install or build time a module that holds, for each possible leading character class, the ordered sublist of SQL_REGEX entries that can match there. Lexer.set_SQL_REGEX loads this table, … |
| Let token_next_by accept a prebuilt predicate to avoid per-call lambda and imt dispatch | api_change | relax_api | claude-sonnet-5-5 | True | Change the public signature of TokenList.token_next_by so a caller may pass a ready-made predicate (or precompiled matcher object) instead of i/m/t. Grouping functions such as group_identifier, group… |
| Single-pass grouping API\: change group() to run matching passes with a shared pre-scan of token kinds | api_change | relax_api | claude-sonnet-5-5 | True | Change _group_matching so it takes a list of group classes and handles brackets, parenthesis, case, if, for and begin in one traversal with one stack per class. group_brackets, group_parenthesis and … |
| Lexer yields prebuilt Token objects, so the splitter skips (ttype, value) tuples | api_change | relax_api | claude-sonnet-5-5 | True | Add a lexer entry point that yields sql.Token objects directly, and change StatementSplitter.process to accept them. This removes one tuple allocation and unpack per token and lets the splitter use t… |
