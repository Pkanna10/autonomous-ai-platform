# X1 ideas: mistune, X1-0

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Rewrite build_closing_bracket_map as a regex-driven scan over bracket and backslash characters only | algorithm | src/mistune/_inline/links.py\:240-244 | 5.3% | infeasible | Build closing-bracket map lazily or once per inline state instead of per link attempt (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Skip bracket-map and link-range construction when the source has no closing bracket after the opener | remove_work | src/mistune/_inline/links.py\:207-209 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 3 | Skip _split_text_token character scanning for text tokens without emphasis markers | specialised_fast_path | src/mistune/_inline/emphasis.py\:196-198 | - | infeasible | Streamline emphasis delimiter scanning and text token splitting (A) | - | - | - | eliminate | claude-sonnet-5-5 | True |
| 4 | Cache bound render methods per token type in the HTML renderer's render_token | precompute_or_cache | src/mistune/core.py\:258-260 | - | infeasible | Cache bound-method lookups in renderer dispatch (_get_method / render_token) (A) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 5 | Cache the compiled fast-trigger regex lookup in InlineParser._find_fast_text_end | precompute_or_cache | src/mistune/inline_parser.py\:281-282 | 5.7% | infeasible | Hoist loop invariants and use bound regex in InlineParser.parse fast path (X1-1) | - | - | - | assume_less | claude-sonnet-5-5 | True |
| 6 | Skip the character-by-character scan in _split_text_token using a precompiled regex split | algorithm | src/mistune/_inline/emphasis.py\:218-220 | - | infeasible | Streamline emphasis delimiter scanning and text token splitting (A) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 7 | Resolve renderer methods once per token type in render_token | precompute_or_cache | src/mistune/core.py\:258-258 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 8 | Skip building the closing-bracket map for sources without a '\[' or '\]' | specialised_fast_path | src/mistune/_inline/links.py\:240-244 | 5.3% | infeasible | Build closing-bracket map lazily or once per inline state instead of per link attempt (A) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | Cache per-name renderer method lookup in HTMLRenderer.render_token via a dict | precompute_or_cache | src/mistune/core.py\:258-258 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 10 | Replace char-by-char _next_delimiter_run with a precompiled regex search | algorithm | src/mistune/_inline/emphasis.py\:218-220 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 11 | Skip the fast-trigger sorted/tuple key rebuild on every _find_fast_text_end call | precompute_or_cache | src/mistune/inline_parser.py\:291-292 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Short-circuit build_closing_bracket_map when the source has no brackets | remove_work | src/mistune/_inline/links.py\:237-239 | 5.3% | infeasible | Build closing-bracket map lazily or once per inline state instead of per link attempt (A) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 13 | Cache per-token-type render method and fast-path text rendering in HTMLRenderer.render_token | precompute_or_cache | src/mistune/renderers/html.py\:42-43 | 19.3% | infeasible | Cache bound-method lookups in renderer dispatch (_get_method / render_token) (A) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 14 | Skip bracket-map build for inline sources with no '\[' and cache escape-free scans | specialised_fast_path | src/mistune/_inline/links.py\:240-244 | 5.3% | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 15 | Replace char-by-char _split_text_token scans with regex split over runs and cheaper delimiter flanking | algorithm | src/mistune/_inline/emphasis.py\:197-200 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 16 | Fuse fast-trigger search into InlineParser.parse by caching the compiled trigger regex locally | loop_or_control_flow | src/mistune/inline_parser.py\:281-284 | 5.7% | infeasible | Hoist loop invariants and use bound regex in InlineParser.parse fast path (X1-1) | - | - | - | recombine | claude-sonnet-5-5 | True |
| 17 | Skip the bracket-map build for sources with no '\[' via a cheap membership test | specialised_fast_path | src/mistune/_inline/links.py\:237-241 | 5.3% | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 18 | Cache bound renderer methods per token type in render_token to skip repeated _get_method lookups | precompute_or_cache | src/mistune/core.py\:258-260 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 19 | Replace per-character delimiter-free text scanning in _split_text_token with a regex split | algorithm | src/mistune/_inline/emphasis.py\:218-220 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 20 | Skip bracket-map build when source has no closing bracket candidates | remove_work | src/mistune/_inline/links.py\:237-241 | 5.3% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 21 | Cache bound renderer methods per token type in HTMLRenderer.render_token | precompute_or_cache | src/mistune/core.py\:258-260 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 22 | Replace char loop in _next_delimiter_run with a precompiled regex search | algorithm | src/mistune/_inline/emphasis.py\:218-220 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 23 | Fold the linebreak back-off into the trigger regex and hoist the cached search out of InlineParser.parse's loop | precompute_or_cache | src/mistune/inline_parser.py\:281-284 | 5.7% | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 24 | Memoise renderer dispatch per token type in BaseRenderer._get_method, avoiding repeated AttributeError raising for plugin types | precompute_or_cache | src/mistune/core.py\:257-260 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 25 | Segment emphasis text tokens with one precompiled marker-run regex instead of per-character Python loops | algorithm | src/mistune/_inline/emphasis.py\:195-200 | - | infeasible | Streamline emphasis delimiter scanning and text token splitting (A) | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
