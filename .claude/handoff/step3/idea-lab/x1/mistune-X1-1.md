# X1 ideas: mistune, X1-1

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Replace per-char Python loop in build_closing_bracket_map with regex-driven scan | algorithm | src/mistune/_inline/links.py\:240-244 | 5.3% | infeasible | Build closing-bracket map lazily or once per inline state instead of per link attempt (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Use regex to split text tokens in emphasis _split_text_token and drop char-wise scanning | algorithm | src/mistune/_inline/emphasis.py\:217-220 | - | infeasible | Streamline emphasis delimiter scanning and text token splitting (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Cache bound renderer methods and skip _get_method indirection in HTMLRenderer.render_token | precompute_or_cache | src/mistune/renderers/html.py\:42-43 | 19.3% | infeasible | Cache bound-method lookups in renderer dispatch (_get_method / render_token) (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Hoist loop invariants and use bound regex in InlineParser.parse fast path | remove_work | src/mistune/inline_parser.py\:281-284 | 5.7% | feasible | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Regex fast path for plain link destinations in helpers._parse_link_href, falling back to the char loop | specialised_fast_path | src/mistune/helpers.py\:155-160 | - | infeasible | Speed up link href parsing with fast path for simple URLs (A) | - | - | - | eliminate | claude-fable-5-1 | True |
| 6 | Reuse _parse_link_href results between link-range indexing and actual link parsing (each href is parsed twice) | precompute_or_cache | src/mistune/helpers.py\:142-146 | - | unknown | - | - | - | - | eliminate | claude-fable-5-1 | False |
| 7 | Stop re-sorting the trigger character set on every InlineParser._find_fast_text_end call | remove_work | src/mistune/inline_parser.py\:277-282 | 5.7% | - | - | - | - | - | eliminate | claude-fable-5-1 | False |
| 8 | Skip bracket map build for inline sources without any '\[' character | remove_work | src/mistune/_inline/links.py\:237-241 | 5.3% | infeasible | Build closing-bracket map lazily or once per inline state instead of per link attempt (A) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | Fast-path _split_text_token for text tokens without emphasis markers | specialised_fast_path | src/mistune/_inline/emphasis.py\:193-197 | - | infeasible | Streamline emphasis delimiter scanning and text token splitting (A) | - | - | - | assume_less | claude-sonnet-5-5 | True |
| 10 | Cache fast-trigger regex lookup in InlineParser._find_fast_text_end | precompute_or_cache | src/mistune/inline_parser.py\:291-292 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 11 | Give emphasis _Delimiter records __slots__ to cut per-instance overhead | representation | src/mistune/_inline/emphasis.py\:213-213 | - | feasible | - | - | - | - | name_the_problem | claude-sonnet-5 | False |
| 12 | ASCII classification lookup table for emphasis can_open/can_close boundary checks | specialised_fast_path | src/mistune/_inline/emphasis.py\:208-209 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5 | False |
| 13 | Replace backward opener scan in _process_emphasis_delimiters with per-key opener stacks | algorithm | src/mistune/_inline/emphasis.py\:238-241 | - | unknown | - | - | - | - | name_the_problem | claude-sonnet-5 | True |
| 14 | Cache per-node emphasis depth instead of rescanning each subtree when checking max_depth in _process_emphasis_delimiters | precompute_or_cache | src/mistune/_inline/emphasis.py\:279-280 | - | - | - | - | - | - | recombine | claude-haiku-5-5 | False |
| 15 | Replace the per-character loop in _parse_link_href with a regex skip over plain link-destination runs | specialised_fast_path | src/mistune/helpers.py\:157-160 | - | - | - | - | - | - | recombine | claude-haiku-5-5 | False |
| 16 | Skip link-range index (and bracket-map build) in label_contains_link when the label span has no '\[' | specialised_fast_path | src/mistune/_inline/links.py\:165-170 | - | - | - | - | - | - | resolve_tradeoff | claude-opus-5-5 | False |
| 17 | Regex-skip ordinary characters in helpers._parse_link_href destination scan | specialised_fast_path | src/mistune/helpers.py\:157-162 | - | infeasible | Speed up link href parsing with fast path for simple URLs (A) | - | - | - | resolve_tradeoff | claude-opus-5-5 | False |
| 18 | Short-circuit label_contains_link with a C-level '\[' scan before building bracket and link-range maps | remove_work | src/mistune/_inline/links.py\:245-248 | 5.3% | - | - | - | - | - | far | claude-fable-5 | False |
| 19 | Memoize HTMLRenderer.safe_url results per URL string across the render | precompute_or_cache | src/mistune/renderers/html.py\:54-57 | 19.3% | - | - | - | - | - | far | claude-fable-5 | False |
| 20 | Bulk-scan ordinary characters in _parse_link_href with a precompiled run regex instead of per-char loop | loop_or_control_flow | src/mistune/helpers.py\:157-162 | - | infeasible | Speed up link href parsing with fast path for simple URLs (A) | - | - | - | far | claude-fable-5 | False |
| 21 | Join token renders from a list comprehension instead of a generator in BaseRenderer.render_tokens | allocation_or_copying | src/mistune/renderers/html.py\:47-48 | 19.3% | feasible | - | - | - | - | far | claude-fable-5 | True |
| 22 | Skip nested-link index construction in label_contains_link when the label span holds no '\[' | remove_work | src/mistune/_inline/links.py\:237-241 | 5.3% | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 23 | Evaluate nested-link check on demand over openers inside the label, not via a whole-source range index | lazy_or_streaming | src/mistune/_inline/links.py\:245-250 | 5.3% | unknown | - | - | - | - | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
