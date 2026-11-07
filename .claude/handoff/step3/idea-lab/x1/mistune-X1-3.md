# X1 ideas: mistune, X1-3

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Cache bound renderer methods per token type in render_token | precompute_or_cache | src/mistune/core.py\:258-260 | - | infeasible | Cache bound-method lookups in renderer dispatch (_get_method / render_token) (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Use regex-based scanning in build_closing_bracket_map instead of a per-char Python loop | algorithm | src/mistune/_inline/links.py\:241-245 | 5.3% | infeasible | Build closing-bracket map lazily or once per inline state instead of per link attempt (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Skip delimiter splitting loops using regex in emphasis _split_text_token | algorithm | src/mistune/_inline/emphasis.py\:218-220 | - | infeasible | Streamline emphasis delimiter scanning and text token splitting (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Cache the fast trigger regex in InlineParser to avoid per-call sorting | precompute_or_cache | src/mistune/inline_parser.py\:281-282 | 5.7% | infeasible | Hoist loop invariants and use bound regex in InlineParser.parse fast path (X1-1) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Fast path for common link hrefs in _parse_link_href using a compiled regex | algorithm | src/mistune/helpers.py\:158-161 | - | infeasible | Speed up link href parsing with fast path for simple URLs (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Skip per-call compile_sc lookup and finalize work for pure-text inline strings | specialised_fast_path | src/mistune/inline_parser.py\:229-232 | 57.0% | feasible | - | - | - | - | eliminate | claude-sonnet-5-5 | True |
| 7 | Avoid slicing and process_text call for each fast-text run by accumulating adjacent text spans | batching | src/mistune/inline_parser.py\:236-238 | 57.0% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 8 | Hoist per-iteration lookups and len() out of InlineParser.parse loop | loop_or_control_flow | src/mistune/inline_parser.py\:231-234 | 57.0% | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | Hoist len(state.src) and state.src into locals in InlineParser.parse loop | loop_or_control_flow | src/mistune/inline_parser.py\:231-234 | 57.0% | infeasible | Cut per-call overhead in inline parse, process_text and fast text end search (A) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 10 | Hoist trigger-char regex lookup out of InlineParser.parse loop and bind locals | precompute_or_cache | src/mistune/inline_parser.py\:232-234 | 57.0% | infeasible | Hoist loop invariants and use bound regex in InlineParser.parse fast path (X1-1) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 11 | Buffer text pieces in process_text and join once per text token | specialised_fast_path | src/mistune/inline_parser.py\:217-219 | 3.2% | infeasible | Cut per-call overhead in inline parse, process_text and fast text end search (A) | - | - | - | recombine | claude-sonnet-5-5 | True |
| 12 | Skip bracket-map build when the source has no closing bracket (condition-separated fast path) | specialised_fast_path | src/mistune/_inline/links.py\:237-241 | 5.3% | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 13 | Hoist attribute lookups and len(state.src) out of InlineParser.parse main loop | loop_or_control_flow | src/mistune/inline_parser.py\:231-234 | 57.0% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 14 | Skip link-range index building in label_contains_link when the link label holds no '\[' character | remove_work | src/mistune/_inline/links.py\:245-248 | 5.3% | feasible | - | - | - | - | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
