# X1 ideas: mistune, X1-2

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Replace char-by-char build_closing_bracket_map loop with regex scan over only backslash and bracket characters | algorithm | src/mistune/_inline/links.py\:240-245 | - | infeasible | Build closing-bracket map lazily or once per inline state instead of per link attempt (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Skip emphasis splitting char scans using regex finditer in _split_text_token and _next_delimiter_run | specialised_fast_path | src/mistune/_inline/emphasis.py\:218-220 | - | infeasible | Streamline emphasis delimiter scanning and text token splitting (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Cache bound renderer methods in render_token to avoid _get_method overhead | precompute_or_cache | src/mistune/renderers/html.py\:42-43 | - | infeasible | Cache bound-method lookups in renderer dispatch (_get_method / render_token) (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Avoid re-sorting trigger chars and re-checking regex per call in InlineParser._find_fast_text_end | precompute_or_cache | src/mistune/inline_parser.py\:281-282 | - | infeasible | Hoist loop invariants and use bound regex in InlineParser.parse fast path (X1-1) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Skip emphasis splitting for text tokens without * or _ in finalize_emphasis_tokens | specialised_fast_path | src/mistune/_inline/emphasis.py\:87-88 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 6 | Avoid per-token source string build when no emphasis delimiter can be opened or closed | remove_work | src/mistune/_inline/emphasis.py\:228-230 | - | feasible | - | - | - | - | eliminate | claude-sonnet-5-5 | True |
| 7 | Skip build_closing_bracket_map and link range index when source has no '\]' after pos | specialised_fast_path | src/mistune/_inline/links.py\:207-208 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 8 | Skip emphasis finalization when text tokens hold no * or _ by checking per-token inline, avoiding full scan | specialised_fast_path | src/mistune/inline_parser.py\:232-234 | - | infeasible | Skip per-call compile_sc lookup and finalize work for pure-text inline strings (X1-3) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | Avoid rebuilding closing-bracket map for sources with no '\[' via early return | remove_work | src/mistune/_inline/links.py\:207-208 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 10 | Emphasis text splitting\: use whole-token fast path when token has no * or _ | specialised_fast_path | src/mistune/_inline/emphasis.py\:193-196 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 11 | Skip emphasis finalization work for text-only inline token lists in InlineParser.parse | specialised_fast_path | src/mistune/inline_parser.py\:269-273 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Avoid link-range and bracket map construction when no bracket and no ref_links precondition is met | remove_work | src/mistune/_inline/links.py\:237-240 | - | infeasible | Build closing-bracket map lazily or once per inline state instead of per link attempt (A) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 13 | Fast-path _parse_link_href with a regex for plain href runs | specialised_fast_path | src/mistune/helpers.py\:158-162 | - | infeasible | Speed up link href parsing with fast path for simple URLs (A) | - | - | - | name_the_problem | claude-sonnet-5-5 | True |
| 14 | Skip link-bracket map build for inline sources without a '\[' character | remove_work | src/mistune/_inline/links.py\:207-209 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 15 | Fuse text-token emission and trigger search\: avoid sc.match after fast scan for plain-text tails | loop_or_control_flow | src/mistune/inline_parser.py\:219-221 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 16 | Fuse _can_open/_can_close emphasis checks into one neighbour computation per delimiter run | loop_or_control_flow | src/mistune/_inline/emphasis.py\:208-209 | - | feasible | - | - | - | - | recombine | claude-sonnet-5-5 | True |
| 17 | Skip the emphasis finalize pipeline for text-only token lists with no markers by cleaning in one pass | specialised_fast_path | src/mistune/inline_parser.py\:269-273 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 18 | Memoize compiled codespan regex per marker string in parse_codespan | precompute_or_cache | src/mistune/inline_parser.py\:177-177 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 19 | Avoid recomputing sorted trigger tuple per call in _get_fast_trigger_re via identity check | remove_work | src/mistune/inline_parser.py\:291-292 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 20 | Skip URL percent-decoding in HTMLRenderer.safe_url when the URL has no percent sign | specialised_fast_path | src/mistune/renderers/html.py\:67-68 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 21 | Render child tokens with a list comprehension instead of a generator in BaseRenderer.render_tokens | loop_or_control_flow | src/mistune/core.py\:274-274 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 22 | Cache compiled codespan regex per backtick marker in InlineParser.parse_codespan | precompute_or_cache | src/mistune/inline_parser.py\:177-177 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 23 | Skip building the link-range index in label_contains_link when the label span contains no '\[' | remove_work | src/mistune/_inline/links.py\:245-248 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 24 | Build trigger-free link/image text children directly in build_link_token without a sub-state and recursive parse | specialised_fast_path | src/mistune/inline_parser.py\:235-240 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
