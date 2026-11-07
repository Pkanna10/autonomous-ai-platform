# X1 ideas: mistune, X1-4

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Replace char-by-char bracket scan in build_closing_bracket_map with regex-driven jumps | loop_or_control_flow | src/mistune/_inline/links.py\:240-245 | 5.3% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Use regex to split text tokens in _split_text_token and _next_delimiter_run | loop_or_control_flow | src/mistune/_inline/emphasis.py\:218-220 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Cache bound renderer methods in HTMLRenderer.render_token and skip _get_method try/except | precompute_or_cache | src/mistune/core.py\:258-260 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Speed up _parse_link_href scanning with a regex for plain destination characters | loop_or_control_flow | src/mistune/helpers.py\:158-162 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Hoist per-call lookups in InlineParser.parse and _find_fast_text_end | precompute_or_cache | src/mistune/inline_parser.py\:291-292 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
| Use the third-party 'regex'-free alternative\: compile hot scanners with mypyc-style Cython extension for emphasis delimiter code | new_dependency | relax_dependency | claude-sonnet-5-5 | False | - |
| Skip building the closing-bracket map when a text has no '\[' character | output_order | relax_output_order | claude-sonnet-5-5 | True | In build_closing_bracket_map, return an empty dict immediately if the source contains no '\[' (a cheap substring test). Since the order lens does not really apply to this hot path, this is stated as a… |
| Precompute the fast-trigger regex and char set once per rule set instead of sorting chars on every call | install_precompute | relax_precompute | claude-sonnet-5-5 | False | - |
| Precompute per-token-type renderer dispatch table at renderer setup, bypassing _get_method | install_precompute | relax_precompute | claude-sonnet-5-5 | True | Build, lazily or when the renderer is finalized by Markdown.__init__, a dict from token type to bound method, covering the class's public render methods and the registered plugin methods. Invalidate … |
| Skip emphasis finalization state\: cache per-token trigger scan by returning flat tokens from InlineParser.parse | api_change | relax_api | claude-sonnet-5-5 | True | Change InlineParser.parse so that, when the source contains none of the trigger characters, it returns early with a single text token. Add a public helper that checks the source once with the compile… |
