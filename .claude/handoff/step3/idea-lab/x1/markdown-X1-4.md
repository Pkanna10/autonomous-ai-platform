# X1 ideas: markdown, X1-4

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hoist inline pattern list lookup out of the __handleInline loop in InlineProcessor | precompute_or_cache | markdown/treeprocessors.py\:136-138 | 49.6% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Replace stack.pop(0) with a deque in InlineProcessor.run | data_structure | markdown/treeprocessors.py\:376-376 | 62.1% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Skip the abbr regex and list() copies for elements without text in AbbrTreeprocessor.iter_element | remove_work | markdown/extensions/abbr.py\:119-121 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
| Use the third-party 'regex' module to compile inline patterns for faster scanning in __applyPattern | new_dependency | relax_dependency | claude-sonnet-5-5 | True | Add the 'regex' package as a dependency. Where inline patterns compile their regexes, have getCompiledRegExp use regex.compile instead of re.compile, with the same flags, so finditer in __applyPatter… |
| Cache inline pattern registry as a plain list once per run, bypassing Registry.__getitem__ sorting | output_order | relax_output_order | claude-sonnet-5-5 | True | In InlineProcessor.run, take a snapshot list of the inline patterns (via iteration of the registry) once per run and use that list for indexing in __handleInline and the length check, instead of goin… |
| Cache Registry sorted snapshot as a list so InlineProcessor indexing skips _sort and dict lookups | install_precompute | relax_precompute | claude-sonnet-5-5 | True | Keep a materialised list of the registered items in priority order, built once at the first read after any register or deregister (or at the end of Markdown construction). Integer-key __getitem__ the… |
| Precompute per-pattern ANCESTOR_EXCLUDES lowercase tuples and skip empty check in __applyPattern | install_precompute | relax_precompute | claude-sonnet-5-5 | True | At InlineProcessor setup, or lazily once per pattern object, cache for each pattern a flag for whether it is the new-style class and a tuple of lowercased ancestor excludes. In __applyPattern use the… |
| Cache a plain list of sorted inline patterns instead of indexing the Registry per step | api_change | relax_api | claude-sonnet-5-5 | True | Give InlineProcessor a snapshot tuple of the sorted patterns, built once at the start of run(), and have __handleInline index that tuple instead of calling Registry.__getitem__ (which calls _sort and… |
| Precompute per-pattern ancestor-exclude test and skip flags to avoid per-call checks in __applyPattern | api_change | relax_api | claude-sonnet-5-5 | False | - |
| Pass the parent map to __build_ancestors as a maintained ancestor chain instead of rebuilding by walking | api_change | relax_api | claude-sonnet-5-5 | True | Change run's work stack to carry each element's ancestor tag list (already computed for the parent plus the element's own lowercased tag) so __build_ancestors need not walk the parent_map to the root… |
