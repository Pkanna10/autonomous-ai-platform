# X1 ideas: tomli, X1-4

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip the regex attempts in parse_value for digit/sign-led values by trying RE_NUMBER-first dispatch | specialised_fast_path | src/tomli/_parser.py\:750-753 | 50.6% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Inline the whitespace skip in skip_chars hot callers, using a regex or a direct char comparison | loop_or_control_flow | src/tomli/_parser.py\:379-381 | 10.1% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Avoid generator and tuple building in key_value_rule for single-part keys | specialised_fast_path | src/tomli/_parser.py\:435-436 | 80.5% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
| Compile tomli's _parser.py and _re.py with mypyc as a build-time dependency | new_dependency | relax_dependency | claude-sonnet-5-5 | True | Add mypy/mypyc as a build dependency and compile the parser and regex modules into native extension modules, keeping the annotated source as is. The Python fallback stays for environments where the e… |
| Defer table-flag bookkeeping for plain dotted-key-free pairs by batching pending flags | output_order | relax_output_order | claude-sonnet-5-5 | True | In key_value_rule, skip the flags.is_(abs_key_parent, FROZEN) lookup when the current table (header) is known to contain no frozen ancestors, caching a per-header 'frozen-free' marker in Output that … |
| Precompute 256-entry first-character dispatch table for parse_value at import time | install_precompute | relax_precompute | claude-sonnet-5-5 | True | Build once at import a table mapping each possible first character to a small handler code (basic string, literal string, true, false, array, inline table, digit or sign start, other). parse_value do… |
| Cache parsed key tuples and parts for repeated key text across tables | install_precompute | relax_precompute | claude-sonnet-5-5 | True | Add a per-loads memo (or a process-wide bounded cache) keyed by the source text of a bare-key segment starting at a position. A single compiled regex match for a whole bare key (parts joined by dots,… |
| Pass a precomputed Flags-free fast path\: drop nest_lvl and parse_float threading via a parser-state object | api_change | relax_api | claude-sonnet-5-5 | True | Change the internal signatures of parse_value, parse_key_value_pair, parse_array and parse_inline_table to take a single parser-state object (holding src, parse_float and nest level) instead of four … |
| Make skip_chars take a precompiled regex-based whitespace skipper with changed internal signature | api_change | relax_api | claude-sonnet-5-5 | True | Replace the generic skip_chars(src, pos, chars) with specialised helpers that take no character-set argument, such as skip_ws and skip_ws_newline, each implemented as a precompiled pattern's match(sr… |
