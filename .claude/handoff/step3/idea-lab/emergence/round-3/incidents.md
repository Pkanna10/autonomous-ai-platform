# Round 3 incident log: sealed-set (V9, O53) exposure, 2026-11-13

V9 = `services/python_agents/tests/fixtures/upstream_corpus/` (30 sealed maintainer-fix tasks, 18 libraries; 9 of the 30 are on the four development libraries). O53 seals `_keys` and `_notes`; the charter's limits say sealed sets are never read. The upstream commits named in the manifest are the public form of the sealed fixes.

| # | seat | what happened | contents of `_keys`/`_notes` read? | Lead action |
| - | ---- | ------------- | ---------------------------------- | ----------- |
| 1 | s4-algorithms | a grep over `tests/` printed V9 workload file names and one manifest `commit_url`; its notes then cited 6 of the 9 dev-library V9 commits (found independently in the public histories), with worked numbers and fix sites; it read their messages and diffs with `git show`, but did not check them out or benchmark them | no | self-reported; notes filed with that material redacted; unredacted copy in `r3/quarantine/s4-algorithms.raw.md` |
| 2 | s8-expert | listed `_keys`/`_notes` (names only), read STATUS lines saying V9 is sealed, then extracted the four libraries' `commit_url`s from `manifest.json` and checked out and A/B-timed 7 of the 9 commits | no | agent stopped before filing; its work moved to `r3/quarantine/s8-expert-work/`; no notes filed |
| 3 | fp-compose | a content grep over `tests/` printed 8 lines of `manifest.json` (3 Python-Markdown commit ids, a PR number, workload file names) | no | self-reported; nothing used in its notes or errata (checked: no V9 id in its files) |
| 4 | s7-cpython | cloned the four libraries at their default heads without checking the manifest | no | heads 09dbe1e, f7ec702, 43a86ad, a4d4428 checked: none is a V9 commit |
| 5 | s3-equivalence | a `grep -rln sqlparse` over the service listed 3 V9 file names (two sqlparse workloads and the manifest) | no | self-reported; tomli clone at tag 2.5.0 (tomli is not a V9 library); no V9 id in its files |

Checks run: every file under `r3/library/` and `r3/work/` grepped for all 30 V9 commit prefixes; hits only in s8's work (now quarantined) and s4's raw notes (now redacted).

**For the owner:** whether incident 2 counts as misconduct (-3), whether V9's 9 dev-library tasks are still valid as the K4 rung for proposals from this round, and whether the quarantined material is deleted or kept sealed. s8-expert restarts only after that ruling, with an allowed-commit list the Lead computes.
