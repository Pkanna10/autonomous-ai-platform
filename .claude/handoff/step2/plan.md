# Step 2 plan: the real core loop on CPU Python workloads

Full spec (44 decisions, interfaces, behaviour, security, tests, 20 units):
`.claude/handoff/step2/spec.md`
Research (verified in the sandbox): `.claude/handoff/step2/research-{execution,git,claude,persistence-fixture-ci}.md`
Produced by workflow wf_9ebacd6a-27c: 4 research tracks, 3 designs (security-first, mvp-testability, forward-compat),
2 judges (both picked mvp-testability, 39/40 of 50), synthesis, completeness critic (5 blockers + 12 should-fixes closed).

## Waves (one workflow per wave; Lead verifies the full suite, commits one commit per unit, pushes)

| Wave | Units |
|---|---|
| 0 | U1 models/settings/state/budget/errors/paths · U2 dedupe_repo fixture (+ mypy exclude, collect-ignore) |
| 1 | U3 protocols, fakes (ScriptedEditor), markers |
| 2 | U4 git · U5 sandbox+launcher · U6 cost · U7 editor handler · U8 Postgres+serde+004 · U9 capture anti-cheat · U10 nodes+orchestrator |
| 3 | U11 procrun · U12 transport · U13 preflight |
| 4 | U14 measure · U15 profiler · U16 editor loop · U17 understand |
| 5 | U18 trial+baseline runners · U19 combine+publish |
| 6 | U20 Lead integration: factory, CI (Postgres service, blocking mypy, sandbox probe, macOS job, Schema Apply 003+004 re-apply), E2E-A/B/C, docs |

Each unit: Builder (Opus 5.5) tests-first on its own files → Reviewer (Fable 5.1, read-only; plus a security reviewer for
U4, U5, U7, U9, U11, U13, U18) → fixer for blocker/should-fix findings. Then Verifier, stage gate, /security-review, draft PR.

## Lead decisions on top of the spec
- ScriptedEditor edit-dir format (U2 writes it, U3 reads it): `dedupe_edits/<title>/files/<repo-relative path>` copied over;
  optional `_delete` (one repo-relative path per line); optional `_symlink` (`<link path>\t<target>` per line).
- U2 owns `[tool.mypy] exclude = ["tests/fixtures/"]`, ruff `extend-exclude` for the fixture edit copies if needed, and
  `collect_ignore_glob = ["fixtures/*"]` in `tests/conftest.py`, so wave 0 stays green.
- No live Claude calls anywhere in dev or CI (no API key here); the live smoke test is `workflow_dispatch` only.

## Verification
Per wave: `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest` (coverage ≥ 90 %).
End: E2E-A/B/C green in CI, macOS job, `pnpm stage-gate`, `/security-review`, CI green on the draft PR.
