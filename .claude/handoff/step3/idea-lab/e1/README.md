# E1 raw results (idea lab inputs)

The two results files of E1 (2026-10-31, `ideas-probe`, arms A-E plus the
auditor), copied from their CI artifacts before they expire on 2026-11-30:

| File | Run | Libraries | Artifact digest (sha256 of the zip) |
| --- | --- | --- | --- |
| `live-results-41186544846.jsonl` | [41186544846](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/41186544846) | more_itertools, pyparsing, tomli, sortedcontainers | `5f63f735…7bab` |
| `live-results-41190431186.jsonl` | [41190431186](https://github.com/Pkanna10/autonomous-ai-platform/actions/runs/41190431186) | mistune, sqlparse, markdown, idna | `d284a10f…b4e4` |

Each holds 4 `ideas-facts`, 20 `ideas-probe`, 152 `ideas-reply` and 192
`ideas-audit` records. The 8 `ideas-facts` records are also committed as the
probe's fixture, `services/python_agents/tests/fixtures/ideas_probe/facts.jsonl`
(read by `ideas_probe.load_facts`, strictly), so X1-0 re-runs on E1's facts
and the views pass reads E1's hotspots. The idea lists (`ideas-reply`,
`ideas-audit`) feed the owner's novelty sample, the dedupe labels and X1's
comparison with E1.
