# Step 3 design A: incremental, risk-first (Steps 3, 3b, 3c and the engine self-retry)

Base: `claude/step3-research` at `ea891e6` (Step 2 head). Paths are relative to
`services/python_agents/src/autonomous_ai_agents/` unless they start with
`tests/` or `infrastructure/`. Every file:line below was read at this head;
anything marked **unverified** was inferred, not run.

Stance: build the smallest units that keep every Step 2 proof intact. Ship the
measured wins first (wiring, retry, the id fix), defer whatever no measurement
has justified, and give each new trust boundary its own unit with a security
Reviewer.

---

## 0 Decisions

1. **Wave 1 holds only the units that do not depend on the A/B result:** the
   slug/UUID mapping, the generator and matcher wiring (blind by default), the
   engine self-retry, the offline discovery regression eval, and the
   protected-pattern gaps. *Why:* each rests on a measurement (E3, E8a, hard
   corpus 10/10) or fixes a latent bug, and none of them changes when E5 lands.
   Waiting for E5 would add lead time and no information.

2. **A contracts unit (U0) comes first and carries no behaviour.** It adds every
   new setting, state key, model field and protocol, each with a default that
   keeps Step 2 behaviour exactly. *Why:* `config.py`, `models.py`, `state.py`
   and `serde.py` are shared by every later unit. Freezing them first lets
   Builders work in parallel on disjoint files, and the serde allowlist
   reflection test and the "every key always present" rule are checked once.

3. **The slug stays the engine identity; the database maps it** (U1). Verified
   bug: the playbook enforces `id == slug` (`research/playbook.py:148`),
   `generate.py:314` copies it into `Hypothesis.technique_id`, and
   `save_lesson` binds it through `_optional_uuid` (`persistence/postgres.py:411`),
   which raises `InvalidRecordIdError` (pinned by
   `tests/persistence/test_postgres.py:193-195`): the first playbook verdict on
   Postgres fails `learn`. STATUS's "no migration needed" holds for `techniques`
   (`003:294-296`) but misses `lessons.technique_id UUID` (`003:418`). Mapping:
   `technique_id = uuid5(TECHNIQUE_NAMESPACE, slug)` plus a nullable
   `lessons.technique_slug` (005), read back by `_LIST_LESSONS`
   (`postgres.py:170-178`) as `COALESCE(technique_slug, technique_id::text)`.
   *Why not a join on a seeded `techniques` table:* a missed reseed silently
   stops lessons matching and no test fails; the uuid5 still keeps the future
   `hypotheses.technique_id` FK (`003:369`) satisfiable. The pinned test changes
   meaning (slug accepted, `"Set Membership"` refused), reported as a deliberate
   behaviour change, not a weakened test.

4. **The wiring ships as `RESEARCH_RETRIEVAL=blind` and `PAPER_PRIORITY=pending`;
   `matched` mode is built and tested offline but off by default.** *Why:* blind
   is the only arm measured end to end (hard corpus 10/10 with one generic
   hypothesis; E3 hit@5 95-100 % for every arm). E5 is still running.

5. **Generator: Sonnet 5.5 at medium, no fallbacks, n=5, at most 2 calls per
   run. Matcher: Sonnet 5.5 at medium, k=3.** *Why:* in E3 this arm hit 22/22 at
   0.014 USD a repo with no false big-gain claim on the controls. Opus at high
   returned 0 hypotheses twice, every Opus arm claimed a gain on `lettertally`,
   and Fable matched Sonnet at 7x the cost on a saturated set. Fable for the
   matcher waits for the hard corpus v2, which separates the arms.

6. **Generated hypotheses keep the model's order; only lessons reorder them.**
   `rank_generated` (`optimization/ranking.py`) scores
   `(1 + lesson_boost) / (1 + position)`. Caller candidates keep the Step 2
   formula (`ranking.py:53-60`) and rank first. *Why:* the only measured ranking
   signal is the model's order (hit@1 19-21/22). `expected_gain` is
   uncalibrated (Opus claimed gains on a control), so re-sorting by
   `expected_gain × provability × (1 − risk)` would rank by self-reported
   numbers. The pinned Step 2 ranking tests stay untouched.

7. **In Step 3, only generated `efficiency` hypotheses enter a round.**
   `behaviour` and `novel` ones are parked and reported as proposals.
   - *Why:* rule 6 of `derive_verdict` (`optimization/judges.py:674-682`) sends
     both to `needs_approval`, and no unattended run can answer the gate.
     `carry()` in `tests/live/discovery.py:409-420` filters for the same reason.
   - The `needs_package` mark exists, but its set is empty in Step 3. The
     generator prompt forbids new dependencies (`generate.py:139-140`), and the
     only card that uses a package requires NumPy to be declared already
     (`playbook.json:1282`).

8. **Generated hypothesis text is untrusted in the editor prompt.** This is a new
   finding, verified: `_task_text` (`execution/editor.py:455-467`) puts
   `_hypothesis_text` outside the `_untrusted` fence and only the brief inside
   it. Caller candidates were trusted. Generated titles and rationales are
   model text derived from repository content, so they can relay an injection.
   The fix (U5) fences the hypothesis for every source. *Why:* one rule, and no
   flag that could be set wrongly. The existing `_holds` token check covers it.

9. **Generation never spends the money of the trial it feeds.** The node
   generates only when `remaining − generator_worst ≥ min_trial_budget_usd`,
   where `generator_worst` is the `preflight_estimate` over the generator's
   chain. *Why:* `min_trial_budget()` (`orchestrator/factory.py:111-116`) is the
   floor of the trials node. Spending below it leaves the run with ideas but no
   money to test them.

10. **The self-retry is narrow** (§4.4): at most `EDITOR_FIX_RETRIES` (default
    1, max 2), only for the trial's own workload crash with a parsed traceback
    of a fixable type (syntax, import, name, type, attribute errors); it feeds
    back type, worktree frames and a capped message, fenced; never timeouts,
    signals, `AssertionError`, suite results, timings, fingerprints or
    verdicts. *Why:* the vision feeds back execution errors, never judge
    signals (2026-10-24 conflict table). The retry lives in
    `GitTrialRunner._attempt` (`execution/trial_runner.py:502-587`), which
    returns before any judge runs, and the suite runs with `check_exit=False`
    (`execution/measure.py:577`), so the structure enforces it.

11. **A retried trial is still one commit whose parent is the base.**
    `GitWorkspace.commit` takes HEAD as parent (`execution/git.py:765-774`) and
    combine skips non-children of the base (`execution/combine.py:246-252`), so
    a guarded `reset_head(to=base, expected=commit1)` precedes the re-commit;
    the attempts' `written` maps merge so `unrecorded_write`
    (`optimization/anticheat.py:450-452`) holds. *Why:* capture, combine and
    delivery all assume this shape.

12. **The editor gets its own model setting (`EDITOR_MODEL`); its default
    changes only in a later one-line unit, after a measurement.** U0 adds it
    with the default `ENGINE_MODEL`, so nothing changes. U9 flips it to
    `claude-sonnet-5-5` at `EDITOR_EFFORT=low` once the blind OSS live suite
    has run with both editors. *Why:* E8a (12/12 on the first pass, 0/3 control
    wins, about 0.04 USD a run) measured the saturated benchmark corpus. The OSS
    corpus, with gains of 3-14 % and 4/10 below the noise, ran on Opus only. A
    small-gain regression would be invisible on the saturated set.

13. **E5's result sets a switch; no code path assumes the outcome.**
    `PAPER_PRIORITY ∈ {pending, first_class, deprioritised}`, set by the Lead
    via `research_plan(AbOutcome(b, c))`: `first_class` iff `c − b ≥ 3`
    (`MIN_DISCORDANT_LEAD`, `tests/live/discovery_ab.py:117`). At runtime
    `pending` acts as `deprioritised` (no paper card loaded). The switch sets
    Wave 3 (§7), the `RESEARCH_RETRIEVAL` default and `PAPER_CARD_PRIOR`.
    *Why:* identical code in both variants, so the result reorders priorities
    without a redesign.

14. **If built, the paper pipeline keeps the measured shape:** pass 1 sends the
    PDF as a document block with citations and no `output_config.format` (that
    pair is a 400, E1), then verifies quotes locally; pass 2 structures only
    verified items; both on Sonnet 5.5 medium as in E7 (0.2-0.3 USD a paper;
    CLAUDE.md's "Opus for extraction" line changes). CI and containers read a
    committed snapshot (metadata, abstracts, sha256); `ArxivSource` runs only on
    the user's machine and raises `SourceUnavailable` under `GITHUB_ACTIONS`
    (E2: 429 on search and id lookups; the container proxy refuses all three
    sources). New cards land in `pending/` for human approval. *Why:* only this
    shape was measured.

15. **3b, the user's point 1, same environment on both sides.** Baseline and
    trial run in environments built from the same lockfile, differing only by
    the acquired package and its new dependencies. A resolver upgrade or
    downgrade of any existing dependency is a separate change, shown in the
    report and measured on its own. The delivered branch's report says the user
    must install the new dependency. *Why:* otherwise the gain mixes two causes.
    A pin change refuses the package trial and is emitted as its own
    `dependency-upgrade` hypothesis (`behaviour`), measured against E0.

16. **3b, the user's point 2, no wheel means ask.** A package or transitive
    dependency available only as an sdist fails the automatic policy, because
    building runs code. It goes to the user, never to an automatic build. This
    also covers L0's existing pins, since E0 must be built without a build step.
    It is enforced with `--only-binary :all: --no-build` when resolving and
    `--no-build` when installing.

17. **3b supports hash-pinned `requirements*.txt` first; `uv.lock` waits for a
    probe; a repository with no lockfile means asking the user.** *Why:* the
    `uv pip compile --generate-hashes --no-build` flags were verified offline
    (uv 0.11.32 `--help`). Rewriting a `uv.lock` needs the project's metadata,
    and dynamic metadata would run a build backend. Whether `uv lock --no-build`
    then refuses cleanly is **unverified**. A check that cannot run asks the
    user.

18. **The network-on fetch phase runs only engine code and a pinned `uv`,
    never repository or package code**, through an engine-owned loopback
    CONNECT proxy with a host allowlist, in a scrubbed, read-confined child
    (§5). *Why:* it is the first engine process that is network-on and fed
    untrusted input; a proxy also works on macOS (pasta and slirp4netns do
    not); with read confinement a compromised resolver has nothing to
    exfiltrate.

19. **The engine writes capability commit C1, recomputed and compared; the
    editor's capture diffs against C1** (verified: otherwise the lockfile lands
    in the editor's capture, `trial_runner.py:539`, and is rejected). Combine
    rebuilds each package trial as one child of the base and re-resolves one
    lock from the kept packages, never merging lock text. *Why:* both proofs
    hold: the editor cannot touch manifests, and the lock is the resolver's.

20. **A package with no proven gain is dropped**: the trial must beat the E0
    baseline beyond the noise floor, and after combine a package no kept change
    imports (AST scan via `top_level.txt`) is removed, re-resolved and
    re-tested.

21. **3c, the user's point 3, reproducer integrity.** The reproducer is written
    in a separate request before any fix is attempted, and frozen as a
    protected file. It must fail on the baseline N of N runs. It must fail for
    the reported reason: the same exception type, and the same frame or message
    as the error report. The fix's trial may not touch it. The report shows the
    reproducer next to the fix. Two additions: the exception must be raised in
    a repository file at base, not in the reproducer itself, and there are
    held-out variants the editor never sees. *Why:* a heal's only proof is the
    failing case. That proof is void if the fix can shape the reproducer or the
    reproducer fails for another reason.

22. **A heal is its own run kind, judged "now passes, nothing regresses"**
    (§4.6). *Why:* it reuses the frozen judges and changes only how the
    declared failing case is judged, as the conflict table requires.

23. **One migration per sub-step:** 005 for the lesson slug (Wave 1); 006 for 3b
    (`packages` columns, `run_packages`, `RunPhase.acquire`); 007 for 3c
    (`HypothesisSource.heal`, `RunPhase.reproduce`). *Why:* each sub-step stays
    revertable in one commit. `chk_task_phase` (`003:253-257`) and
    `chk_hypothesis_source` (`003:384`) change with their StrEnums
    (`common/models.py:88-104,134-138`).

24. **The `ledgerclose` rebuild and hard corpus v2 start only after E5
    finishes.** *Why:* E5 runs on `HARD_CORPUS`, so its data must stay
    comparable. In the rebuild, both hot spots are compare loops over Python
    objects, the same kind of work on any machine.

---

## 1 Scope and non-goals

**Step 3:** U0 contracts; wiring `generate_hypotheses`
(`optimization/generate.py:189-255`) and `match_techniques`
(`research/playbook.py:350-402`) into `research`, `hypotheses`
(`orchestrator/nodes.py:1413-1460`) and the router (`nodes.py:1932`); the slug
mapping; the self-retry; protected-pattern gaps (`pip.conf`, `uv.toml`,
`requirements*.in`, `constraints*.txt`, `pylock*.toml`, `pdm.lock`,
`.python-version`); the hypothesis fence; the offline eval; the combine-failed
lesson discount; lessons in the generator prompt; hard corpus v2 and the
`ledgerclose` rebuild; grader validation; then, set by E5, either the paper
pipeline or card stats and evolution.

**3b:** the automatic policy, network-on fetch into a hash-pinned wheelhouse,
offline per-trial environments, the env baseline, C1, combine with packages,
dropping packages with no gain, the install line. **3c:** a caller-supplied
`HealCase` (failing test or crash), the reproducer, the heal judges,
`heal_tamper`, flagged delivery.

**Non-goals:** MCP/API discovery, error-monitoring intake and the CLI (Step 4);
CUDA/MPS and private indexes; building sdists, even when approved; npm;
deterministic precondition checks; profiler tags (`Hotspot.tags` is never set,
so lesson context is "general"); batches and 1 h caching; Fable as matcher
before v2 data; rollout (Step 6).

---

## 2 Architecture

```
                       optimize run                                 heal run (3c)
START -> connect -> understand -> define -> baseline ---------+-----> reproduce
                                                              |  (separate request,
                        profile <-----------------------------+   frozen, N/N fail,
                           |                                      same reason)
                           v                                            |
                        research (blind | playbook | matched;           |
                           |      paper cards only if first_class)      |
                           v                                            v
             +------> hypotheses (pool; generate if empty and one  <----+
             |             |      trial stays affordable; efficiency
             |             |      only, the rest parked)
             |             v
             |         ACQUIRE (3b, only hypotheses with packages)
             |             |  policy -> fetch (network-on: engine code + pinned uv,
             |             |  loopback proxy, read-confined) -> offline envs E0/E1
             |             |  -> env baseline in E0 -> engine commit C1
             |             v
             |         trials (one worktree each, network-off)
             |           edit -> capture (vs base or C1) -> anti-cheat -> commit
             |           -> measure --fixable own crash?--> retry <= 1 (fenced
             |                  ^------------------------- crash; one commit on base)
             |             v
             |         judges -> verdicts --after_verdicts--+
             +---- untried idea in pool / candidates / gen --+
                                                             |
     END <- watch <- learn <- deliver <- combine <- approval_gate
              (combine-    (install line;  (ABAB re-test; packages re-resolved,
               discounted   reproducer      unimported ones dropped;
               lessons)     next to fix)    heal: commit R, then F)

HEAL enters the same loop: the failing case is one source=heal hypothesis
judged by HealJudge plus the full suite and the other judges.
Frozen outside the state: judges, protected patterns, noise rule,
reproducer sha256, env lock hashes.
```

---

## 3 Interfaces

### 3.1 Settings (`common/config.py`, in U0 unless noted)

| Key                                                        | Default                                       | Basis                                                     |
| ---------------------------------------------------------- | --------------------------------------------- | --------------------------------------------------------- |
| `GENERATOR_MODEL` / `_EFFORT` / `_FALLBACKS`               | `claude-sonnet-5-5` / `medium` / `False`      | E3 (ran without fallbacks)                                |
| `GENERATOR_N` / `_MAX_TOKENS` / `_MAX_CALLS`               | 5 / 16000 / 2                                 | E3                                                        |
| `MATCHER_MODEL` / `_EFFORT` / `_K`                         | `claude-sonnet-5-5` / `medium` / 3            | E5 arm B                                                  |
| `RESEARCH_RETRIEVAL`                                       | `blind` (`blind\|playbook\|matched`)          | D4                                                        |
| `PAPER_PRIORITY`                                           | `pending`                                     | D13                                                       |
| `GENERATED_CLASSES`                                        | `("efficiency",)`                             | D7                                                        |
| `EDITOR_MODEL`                                             | `None`, which means `ENGINE_MODEL` (U9 flips it) | D12                                                    |
| `EDITOR_FIX_RETRIES`                                       | 1 (0-2)                                       | D10                                                       |
| 3b: `ACQUIRE_ENABLED`                                      | `False` until the 3b gate                     |                                                           |
| 3b: `PACKAGE_MIN_PROJECT_AGE_DAYS` / `_VERSION_AGE_DAYS`   | 90 / 14                                       |                                                           |
| 3b: `PACKAGE_MIN_DOWNLOADS`                                | Q4                                            | pypistats reachability **unverified**                     |
| 3b: `PACKAGE_LICENCES`                                     | MIT, BSD-2/3-Clause, Apache-2.0, ISC, PSF-2.0 |                                                           |
| 3b: `PACKAGES_PER_HYPOTHESIS` / `ACQUIRE_MAX_BYTES`        | 1 / 500 MiB                                   |                                                           |
| 3c: `REPRO_MODEL` / `_EFFORT`, `REPRO_VARIANTS`, `REPRO_RETRIES` | Sonnet 5.5 / `medium` (unmeasured), 2, 1 | Q8                                                       |

- The validators (`config.py:319-353`) are extended to every per-role model and
  its effort.
- `model_settings` (`tests/live/discovery.py:163-170`) moves to
  `common/config.py` as `role_settings`.

### 3.2 State (`orchestrator/state.py`; every key is set in `initial_state`)

**Step 3:**

- `candidate_pool: list[Hypothesis]`: generated, not yet sliced into a round.
  A plain list.
- `parked: list[Hypothesis]`.
- `technique_matches: list[TechniqueMatchRecord]`: a new `EngineModel` holding
  `slug`, `fit`, `justification_summary` and `unmet_preconditions`, added to
  `ENGINE_SERDE_ALLOWLIST`.
- `generator_calls: int`.

**3b:**

- `env_baselines: dict[str, Baseline]`, keyed by lock sha256.
- `capabilities: list[CapabilityRecord]`.

**3c:**

- `run_kind: RunKind` (`optimize|heal`).
- `heal_case: HealCase | None`.
- `reproducer: Reproducer | None`.

### 3.3 Models (`common/models.py`)

- `Trial.attempts: int = 1` and `Trial.retry_reasons: tuple[str, ...] = ()`.
  Both defaults are serde-safe.
- 3b: `Hypothesis.packages: tuple[PackageRequest(name, reason), ...] = ()`.
  It holds a name, never a version or a URL.
- 3c: `HealCase(kind, test_node_id | workload_id, signature)`.
  - `kind` is `failing_test|crash`.
  - `signature` is an `ExceptionSignature(type, message, frames)` with frames
    as `(file, function, line)`, and never locals.
- 3c: `Reproducer(path, sha256, variants_sha256, signature, baseline_failures)`.

### 3.4 Seams

`optimization/sources.py` (U0):

```python
class HypothesisSource(Protocol):
    def generate(self, *, project: Project, understanding: ProjectUnderstanding | None,
                 hotspots: Sequence[Hotspot], objective: Objective, techniques: Sequence[Technique],
                 lessons: Sequence[Lesson], avoid_titles: Sequence[str], n: int,
                 budget: Budget) -> GenerateResult: ...      # hypotheses, notes, cost_usd, tokens_used
class TechniqueMatcher(Protocol):
    def match(self, *, understanding: ProjectUnderstanding | None, hotspots: Sequence[Hotspot],
              techniques: Sequence[Technique], k: int, budget: Budget) -> MatchResult: ...
@dataclass(frozen=True)
class ResearchPolicy: retrieval: Retrieval; papers: PaperPriority
    generated_classes: frozenset[ChangeClass]; n: int; k: int; max_calls: int
```

- `NodeContext` (`nodes.py:181-237`) gains `generator`, `matcher` (both
  default `None`, which keeps the Step 2 behaviour) and `research_policy`.
- `ClaudeHypothesisSource` and `ClaudeTechniqueMatcher` live in
  `optimization/hypothesis_source.py`; each owns its transport.

**Retry:**

- `procrun.RunFailure` gains `kind` (`exit|timeout|flood|isolation|report|path|other`)
  and `crash: CrashReport | None`.
- `execution/crash.py` has `parse_traceback(stderr_tail, worktree)`.
- `execution/retry.py` has `classify(failure, excluded_workloads) -> TrialFeedback | None`.
- `EditTask.feedback: TrialFeedback | None = None` (`execution/protocols.py:137`).
- `GitTrialRunner` gains `fix_retries` and `retry_floor_usd`.

**3b, in `capabilities/`:**

- `names.near_miss(name, popular)`
- `policy.evaluate(facts, config) -> PolicyResult(ok|needs_user, reasons)`, pure
- `wheels.inspect_wheel`
- `registry.PypiClient`
- `proxy.AllowlistProxy`
- `lockfile.read_base_lock`, `resolve`, `diff_locks`
- `fetch.Fetcher`
- `envs.EnvBuilder.build(lock, store) -> EnvHandle(path, lock_sha256, python)`
- `make_phase(..., env=)` (`measure.py:132-165`)

**3c:**

- `heal/writer.py`: `ReproducerWriter.write(case, sources_at_base, budget)`
- `heal/checks.py`
- `heal/signature.py`: `matches(observed, reported)`
- `execution/_heal_shim.py`
- `HealJudge`
- `EquivalenceJudge(exempt_workloads=)`
- the capture rule `heal_tamper`

### 3.5 Tables

**005** (idempotent):

- `lessons.technique_slug VARCHAR(100)`.
- A `DO`-guarded `CHECK (technique_slug ~ '^[a-z0-9][a-z0-9-]{1,62}$')`.

**006:**

- New `packages` columns: `sha256`, `license_expression`, `first_release_at`,
  `downloads_recent`, `policy_result JSONB` and `checked_at`.
- A new `run_packages` table: `run_id`, `package_id`, `hypothesis_id`,
  `reason`, `outcome` (`kept|dropped|needs_user`) and `gain`.
- `acquire` added to `chk_task_phase`.

**007:**

- `heal` added to `chk_hypothesis_source`.
- `reproduce` added to `chk_task_phase`.

---

## 4 Behaviour

### 4.1 Research node (U6a)

The node's behaviour depends on the retrieval mode:

- **`blind`:** no techniques and no request.
- **`playbook`:** all the cards, no request.
- **`matched`:** calls `ctx.matcher.match` over `load_playbook()`, plus the
  approved paper cards when `first_class`.
  - It writes the matched cards and `technique_matches`.
  - The spend goes through `_charged` (`nodes.py:576`).
  - `BudgetExceeded`, `LLMConfigError`, `LLMUnavailable` and
    `UnusableReplyError` are soft: the node emits `research_unavailable` and
    continues as blind.

### 4.2 Hypotheses node (U6a)

1. The pool is `ctx.candidates` not yet seen, plus `candidate_pool`.
2. The node generates only if:
   - no untried idea is left,
   - `generator_calls < max_calls`, and
   - the D9 reservation holds.

   Inputs: the hotspots, the understanding, `objectives[0]` (`define` always
   sets one), `state["techniques"]`, the last 20 lessons (passed now, rendered
   from U11) and `avoid_titles`. The spend goes through `_charged`.
3. Filters, each with a note:
   - a class outside `generated_classes` goes to `parked`;
   - a hypothesis with `packages` goes to `parked` as `needs_package`, until 3b;
   - duplicate normalised titles are dropped;
   - each id is re-checked with `validate_run_id`.
4. Ranking: caller candidates go through `rank_hypotheses`, then generated ones
   through `rank_generated`. The round takes `max_hypotheses_per_round`; the
   rest go back to `candidate_pool`.
5. A failed generation is soft (`generate_unavailable`). The refusal category
   (`stop_details.category`) is logged.

Generated `hotspot_ids` resolve only against the hotspots shown to the model
(`generate.py:360-384`), so `_brief_hotspots` (`nodes.py:342`) no longer falls
back to the run's top 5.

### 4.3 Router (U6a)

`nodes.py:1932` returns `combine` only when:

- no untried idea is left in `ctx.candidates` or `candidate_pool`, and
- generation is impossible.

`max_rounds` still bounds the loop. This fixes the round-1 exit when the run has
no caller candidates.

### 4.4 Self-retry (U2, U5)

1. `measure.launch` (`measure.py:233-260`) sets `kind="exit"` and parses the
   whole `stderr_tail`. Today only its last line survives (`:256-259`).
2. In `_attempt`, `except RunFailure` (`trial_runner.py:582-583`) calls
   `classify`. A retry needs all of the following:
   - `classify` returns feedback;
   - `attempts ≤ fix_retries`;
   - `budget.remaining ≥ retry_floor_usd`;
   - the failing workload is not excluded (in 3c, the reproducer is excluded).
3. The retry:
   1. Edits again on the same `Budget`, in the worktree that still holds attempt
      1 (`phase.reset` restores commit1). The notice reads: "your previous
      change, still in the worktree, failed when run; fix that error and keep
      the approach".
   2. Merges `written`, then runs `stage_all`, capture against the base and
      every anti-cheat rule.
   3. Runs `reset_head(base, expected=commit1)`, `commit`, then
      `update_ref(own_ref, commit2, commit1)`; this sets `progress.moved`.
   4. Measures again.
4. An unaffordable retry, an editor stop or a second crash returns the first
   failure, with a note. It is never `TrialUnaffordable`. The reason is
   recorded in `Trial.retry_reasons`.

### 4.5 Acquire (3b)

1. Runs only for hypotheses with `packages`, under `ACQUIRE_ENABLED`.
2. L0 is read from git objects at `base_commit`. No supported lock, or a
   second configured index (`[tool.uv.index]`, `--index-url`, `pip.conf`,
   `uv.toml`), gives `needs_user`; the hypothesis is parked and the question
   goes in the end report.
3. Facts: names pass the PEP 508 regex before any URL is built; network-on
   facts (existence, release dates, OSV, downloads) and offline facts
   (near-miss snapshot, licence and RECORD from the wheel) feed the pure
   `policy.evaluate`. A check that cannot run gives `needs_user`.
4. Resolve (network-on, via the proxy): `uv pip compile --no-config
   --no-sources --only-binary :all: --no-build --generate-hashes
   --default-index https://pypi.org/simple --exclude-newer <now−14d>
   --python-version <workload python> -c <L0 pins>`. sdist only gives
   `needs_user` (point 2); a changed or removed pin refuses the trial and emits
   `dependency-upgrade` (point 1).
5. Engine `httpx` downloads each wheel from `files.pythonhosted.org` into
   `<run>/_wheels/sha256/<digest>.whl`, checking its sha256; an offline
   `uv pip compile --offline --no-index --find-links <store>` must reproduce L1
   byte for byte.
6. E0 and E1 are built offline under `<run>/_env/<lock-sha>` (`uv venv
   --no-python-downloads`; `uv pip install --offline --no-index
   --require-hashes --no-deps --no-build --strict`); they are read-only to
   workloads (`measure.py:104-116`), and `phase._phase_names`
   (`execution/phase.py:265-282`) skips and sweeps `_env` and `_wheels`.
7. The env baseline is measured in E0 (`env_baselines`); a trial is judged only
   against the baseline with its parent's lock sha, else `inconclusive`. `_host`
   records `env_lock_sha256` and the workload's Python, not the engine's
   (`measure.py:321-333`).
8. C1 (engine commit with a trailer) precedes the editor; capture diffs against
   C1; C1 is valid only if `base..C1` touches only manifest and lock and equals
   the recompute. `module_shadow` extends to the env's top-level names.
9. Delivery: the capability commit, then the code; the report shows the lock
   diff and, per package, the reason, the importing change, the gain and the
   policy evidence, and says: "This branch adds `<name>==<ver>` and N
   dependencies; you must install them (`pip install --require-hashes -r
   <lock>`)."

### 4.6 Heal (3c)

1. Define: `Objective(custom, "heal_passed", maximize)`; guardrails
   `tests_pass`, `output_equivalence`, wall-time and RSS bounds.
2. Baseline: every workload except the failing case; pytest gets `--deselect
   <node id>`, so `_require_trustworthy_baseline` (`nodes.py:647`) passes;
   unittest asks the user.
3. Reproduce (point 3): a separate tool-less `call()` on sources at base
   (`READ_DENY_PATTERNS` filtered, report fenced) returns a stdlib-plus-repo
   script asserting the expected value plus `REPRO_VARIANTS` held-out variants;
   static checks (allowed imports, `_spawn_problem` at `anticheat.py:560`, no
   `try` around the target, size cap); frozen at `<run>/_heal/repro_<id>.py`
   outside `writable`, sha256 checked before every run; run `MIN_RUNS` times
   under `_heal_shim.py`, it must fail N of N with the same exception type,
   raised in a repository file at base, with the innermost repo frame (file,
   function) or the masked message equal to the report's. A mismatch gets one
   rewrite, then the engine asks and delivers no branch. For `failing_test`,
   the user's test is the reproducer under the same rules.
4. Trial: one generic `source=heal`, `behaviour` hypothesis; the editor sees the
   report and the public reproducer, never the variants; `heal_tamper` rejects a
   diff naming the reproducer path or module, `.engine`, `sys._getframe`,
   `inspect.stack`, `sys.excepthook`, `atexit` or `os._exit`; the retry excludes
   the reproducer workload.
5. Judges: `HealJudge` (reproducer and variants pass N of N, exit 0 and a shim
   completion document; a missing document fails); the full suite without
   deselect, count at least the baseline's + 1; every other workload
   byte-equivalent.
6. Delivery: commit R adds `tests/engine_heal/test_<slug>.py` (protected by
   `**/tests/**`), then commit F; the report shows the reproducer next to the
   fix with the signature, N/N failures on the baseline and N/N passes on the
   trial. Flagging is Q1.

### 4.7 Failure modes

| Situation | Result |
| --- | --- |
| Generator empty, refusing or unusable; matcher failing; generation unaffordable | Soft note (blind for the matcher); the router ends when nothing is left (Q6) |
| Fixable crash and the retry fails; timeout, `AssertionError`, suite failure | First failure kept, reject; no retry for the latter |
| sdist only, near miss, too young, OSV hit, licence, other index | `needs_user`, parked, listed in the report |
| Existing pin would change; C1 differs from the recompute | Trial refused with `dependency-upgrade` emitted; trial fails closed |
| Reproducer flaky, wrong reason, self-raised; sha changed | One rewrite then ask, no branch; run fails closed |

---

## 5 Security

| Threat | Controls |
| --- | --- |
| Injection relayed through generated hypotheses | D8 fence in the editor prompt; the generator already fences repo text (`repo_fence`, `_fenced_line`); titles validated and token-checked |
| Injection from papers | Layered: (1) fail-closed Haiku screen of the pypdf text (positive, refused or unreadable means quarantine); (2) pass 1 writes a `NOTE:` line instead of complying; (3) pass 2 sees only verified quotes, freshly fenced; (4) card validators (no URL, backtick, `pip`/`install`; slug and check-key regexes); (5) human approval into `papers.json`; (6) stable fence in the matcher; (7) frozen judges. Residual: an instruction inside a figure reaches the page image, not the text screen |
| Lessons and error reports in prompts | Fenced, a line holding the token withheld, no locals; they reach only the generator or the reproducer writer, never the editor |
| Retry as a reward-hacking channel | Own crash only; never timings, fingerprints, suite results or verdicts; message capped; runs before any judge (D10) |
| Slopsquatting | The model names a package only; every name (a playbook one too) must exist, be no near miss (Damerau-Levenshtein ≤ 2, `-`/`_`/`.` folding, `python-`/`-py` affixes, confusables) of a dated top-15k snapshot, be ≥ 90 days old with a version ≥ 14 days old (`--exclude-newer` covers transitive dependencies), pass downloads and OSV (incl. `MAL-`) |
| Dependency confusion | One index, `--no-config --no-sources`; another configured index or a same-named local module asks |
| Malicious wheel | Wheels only, `--no-build --require-hashes`; RECORD with no absolute or `..` path, no `*.pth`, no `*.data/scripts`, no console script named like a workload's or the test command's `argv[0]`; package code runs only in the sandboxed trial; the user's exposure after delivery is made visible by the lock diff and the install line |
| Time of check to time of use | Content-addressed store; sha256 at download and install; offline recompute of L1 |
| Read confinement once network-on phases exist | The fetch child runs only engine code and pinned, version-checked `uv`; scrubbed env (deny patterns incl. `*PROXY*`, `*_TOKEN`, `*_URL`, `sandbox.py:63-67`), fresh `HOME`/XDG, keyring disabled, no netrc; Landlock read allowlist on Linux (uv binary, CA bundle, L0 copy, `_wheels`), `sandbox-exec` read allowlist on macOS; egress only through the allowlist proxy, bodies carry names and versions only; no worktree read, only git objects at base. Trials stay network-off and `*PROXY*` never reaches a workload. **Unverified:** uv under a Landlock read allowlist (B5's first probe) |
| SSRF | Allowlisted URLs only; name regex before URL building; at most two same-host redirects; size caps |
| Reproducer gaming | Writer: repository frame at base, N/N, same type plus frame or message, static checks. Fix: file outside `writable`, sha256 per run, `heal_tamper`, held-out variants hidden from the editor, shim document plus exit code; a broad `except` added on the reported frames is flagged |
| Excessive agency and cost | Never push; heals flagged; failed checks ask; `ACQUIRE_ENABLED` off until the 3b gate; every paid call through `Budget` and `call()`; generation reserves one trial; registry checks cost no tokens |
| Engine licences | The `research` extra drops `pymupdf` (AGPL-3.0), `arxiv` and `sentence-transformers`; `pypdf>=6,<7` only if papers are built |

Trust boundaries, each its own unit with a security Reviewer: U5 (feedback,
fence), U6b (transports), P1 (network on the user's machine), P2 (PDF screen),
B4 (registry, proxy), B5 (resolve, confinement), B6 (envs in the sandbox), B7
(C1, capture), C2 (reproducer writer), C4 (heal judges, tamper rules).

---

## 6 Test plan

**Unit tests** (offline, TDD; 100 % line and branch kept).

- **U1:** a slug round-trips on Postgres; a non-slug, non-UUID value is refused
  before connecting; a legacy UUID row reads back; 005 runs twice.
- **U2:** `parse_traceback` on 3.8-3.12 stderr (chained, `SyntaxError` caret,
  out-of-worktree frames dropped, cap); `classify` gives `None` for timeout,
  signal, `AssertionError`, suite and excluded workloads.
- **U3:** sources on `ScriptedTransport` report cost and tokens;
  `rank_generated` keeps model order and a keep lesson flips it.
- **U5** (next to `tests/execution/test_trial_runner.py:941`): `SyntaxError`
  then a fixing edit gives `attempts == 2`, one commit with parent base
  (`combine._unfit`, `combine.py:246`, passes), no `unrecorded_write`; an
  unaffordable retry keeps the first failure; the cap holds; feedback has no
  stdout or timings; the hypothesis is fenced and a token in it refused.
- **U6a:** one generation on an empty pool with its inputs recorded; parking; 3
  sliced, 2 pooled; no regeneration while the pool has ideas; the reservation;
  soft `BudgetExceeded` with spend charged; the router with empty
  `ctx.candidates` and a non-empty pool returns `hypotheses`; three research
  modes, matcher failure falls back to blind; `generator=None` reproduces Step 2
  with every existing test unchanged. **U6b:** per-role chains; an unpriced
  `GENERATOR_MODEL` is refused.
- **3b** (recorded-JSON `FakeRegistry`, `zipfile`-built wheels): near misses
  (`reqeusts`, `numpi`, a homoglyph); each policy check passes and fails, an
  unreachable host gives `needs_user`; a forced pin change gives
  `dependency-upgrade`; an sdist-only transitive gives `needs_user`; two
  resolves give the same bytes; wheel refusals; offline install under
  `unshare -rn`, a changed wheel fails closed, the env is not writable, E0 and
  E1 differ only by the added distributions; an editor edit to
  `requirements.txt` after C1 is `protected_path`, a tampered C1 fails, a lock
  mismatch is `inconclusive`; one re-resolved lock in combine and an unimported
  package dropped; the sweep removes `_env` and `_wheels`.
- **3c:** 5/5 with a matching signature accepted; 3/5, wrong type, an error
  raised in the reproducer, a stack outside the repo and a sha change refused; a
  message-only match accepted with the frame in the repo; `HealJudge` on pass,
  flaky and missing document; equivalence exempts only reproducer ids; each
  `heal_tamper` token refused; the retry ignores a reproducer crash.

**Offline discovery regression eval** (U7, not live):

- `discovery_grader.grade` is split into `grade_with(transport, budget, repo,
  patches, hypotheses, cfg)`.
- The sweep records the raw generator reply, the hotspots, the objective and the
  grader reply per (repo, arm). Today `SweepRow` holds counts only
  (`tests/live/discovery_sweep.py:161-190`), so E3 cannot be replayed.
- One live refresh (L4) commits `tests/fixtures/discovery_eval/<corpus>.json`.
  Its labels are keyed by the sha256 of the normalised title and rationale, and
  it includes the hand labels.
- `tests/optimization/test_discovery_eval.py`:
  - replays each reply through `generate_hypotheses` on `ScriptedTransport`,
    then `rank_generated` and the slice the node uses;
  - asserts hit@3 is at least the recorded baseline;
  - fails with "unlabelled: refresh in live-smoke" on an unknown key;
  - replays the grader replies through `grade_with`.
- It catches regressions in validation, slug mapping, hotspot resolution,
  ranking and slicing. Prompt changes need a refresh.

**E2E** (`tests/e2e/test_step3.py`, marker `slow`; real git and sandbox,
scripted Claude):

- **E3-A:** `candidates=()` plus a scripted generator reply reaches a delivered
  branch. A checkpoint resume makes no second generator request.
- **E3-B:** a `NameError` from the first edit is fixed by the retry, and the run
  delivers with `attempts=2`.
- **E3-C:** `behaviour` hypotheses are parked, and the run ends without pausing.
- **3b:** a fixture wheel that speeds up a hot loop is delivered with the
  install line; in a control it is dropped.
- **3c:** 5 planted bugs (`KeyError`, off-by-one, `None`, encoding, mutable
  default) and 3 controls (cannot reproduce, intended behaviour, a stack
  outside the repository). Every control ends with "ask the user" and no branch.

**Live** (only in `live-smoke` on CI, one suite at a time under the 150 USD
ceiling; each cap is the sum of the worst cases; every run gets a ledger row and
reports `Trial.attempts`, which measures how often the retry fires):

| Suite                                                         | Cap         | Expected        | Gates       |
| ------------------------------------------------------------- | ----------- | --------------- | ----------- |
| L1 wired hard corpus, blind (generator Sonnet medium)         | 25 USD      | ~1.5 USD        | Wave 1      |
| L2 OSS blind, two editor arms (Opus; Sonnet low)              | 50 + 50 USD | ~3 + 1.5 USD    | U9          |
| L3 grader agreement on ~10 hand labels                        | 3 USD       | < 0.5 USD       | U13         |
| L4 eval refresh (Sonnet-medium sweep with recording, + grader) | 10 USD     | ~1 USD          | U7          |
| L5 E7 through the `src` modules (first_class only)            | 10 USD      | ≤ 0.35 USD/paper | P3/P4      |
| L6 network-on 3b job: one real wheel, a slopsquat refused, Q4 probe | 0 USD in tokens | 0     | B4/B5       |
| L7 heal corpus, Sonnet low and Opus arms                      | 30 USD      | ~2 USD          | Wave 5      |

---

## 7 Work breakdown by wave

Rules for every unit:

- at most about 400 lines, including tests;
- files disjoint within a wave;
- one commit;
- a Reviewer on a different model;
- a security Reviewer for each unit listed in §5.

**Wave 1** (independent of the A/B result; it starts now and lists first the
wiring, the retry, the mapping and the eval):

| #   | Unit                                                    | Files                                                                                                     | Lines | After  |
| --- | ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ----- | ------ |
| U0  | Contracts (settings, state, models, protocols, serde)   | `common/config.py`, `common/models.py`, `orchestrator/state.py`, `orchestrator/serde.py`, `optimization/sources.py` | ~300 | -  |
| U1  | Slug/UUID mapping                                       | `infrastructure/schema/005_lesson_technique_slug.sql`, `persistence/postgres.py`, `tests/persistence/test_postgres.py` | ~150 | U0 |
| U2  | Crash report and retry classifier                       | `execution/procrun.py`, `execution/measure.py`, `execution/crash.py`, `execution/retry.py`                | ~250  | U0     |
| U3  | Claude source and matcher, `rank_generated`             | `optimization/hypothesis_source.py`, `optimization/ranking.py`                                            | ~250  | U0     |
| U4  | Protected-pattern gaps                                  | `optimization/anticheat.py`                                                                               | ~60   | -      |
| U5  | Retry flow and hypothesis fence (security)              | `execution/trial_runner.py`, `execution/git.py`, `execution/protocols.py`, `execution/editor.py`          | ~350  | U2     |
| U6a | Wiring: nodes and router                                | `orchestrator/nodes.py`                                                                                   | ~300  | U0, U3 |
| U6b | Wiring: factory (per-role transports, playbook, policy, retry floor) (security) | `orchestrator/factory.py`                                                         | ~150  | U3, U5 |
| U7  | Offline discovery eval                                  | `tests/live/discovery_grader.py`, `tests/live/discovery_sweep.py`, `tests/optimization/test_discovery_eval.py`, `tests/fixtures/discovery_eval/` | ~300 | U3 |
| U8  | E2E E3-A to E3-C, docs                                  | `tests/e2e/test_step3.py`, `tests/fixtures/step3/`                                                        | ~300  | all    |

Order:

1. U0.
2. U1, U2, U3 and U4 in parallel.
3. U5, U6a and U7 in parallel.
4. U6b.
5. U8.
6. L1 and L4.

After step 4, value has shipped: a run needs no hypothesis handed to it, and a
fixable crash recovers.

**Wave 2** (independent of the A/B result):

| #   | Unit                                                              | Files                                                         | After |
| --- | ----------------------------------------------------------------- | ------------------------------------------------------------- | ----- |
| U9  | Flip the `EDITOR_MODEL` default to Sonnet low                     | `common/config.py`                                            | L2: Sonnet delivers at least Opus's count − 1, with 0 control wins |
| U10 | Combine-failed lesson discount (1.0/0.5/0.25, `combine:*` tags; amends decision 25) | `learning/lessons.py`, `orchestrator/nodes.py` (`learn` only) | Wave 1 |
| U11 | Lessons and `avoid_titles` in the generator prompt                | `optimization/generate.py`                                    | Wave 1, then refresh L4 |
| U12 | Hard corpus v2 and `ledgerclose` rebuild (guard: part-cost ratio 0.5-2) | `tests/fixtures/live_corpus_discovery/`, `tests/fixtures/live_corpus_hard/ledgerclose/`, `tests/live/test_hard_corpus_guards.py` | E5 done; the corpus author stays blind to the playbook |
| U13 | Grader hand labels (Lead) and the agreement test                  | `tests/fixtures/grader_labels.json`, `tests/live/test_grader_agreement_live.py` | - |

U10 rests on one measured case (`sortedcontainers`), so it is small and gets
its own STATUS row.

**Wave 3** (depends on the A/B result; this is the switch):

| Item                 | `c − b ≥ 3` (first_class)                                                                                                                                       | `c − b < 3` (deprioritised)                                                                                                                                   |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `RESEARCH_RETRIEVAL` | `matched`                                                                                                                                                       | stays `blind`, the measured and cheaper arm                                                                                                                   |
| `PAPER_PRIORITY`     | `first_class`, `PAPER_CARD_PRIOR = 1.0`                                                                                                                         | `deprioritised`; paper cards never load (prior 0.5 if they ever do)                                                                                           |
| Wave 3 units, in order | P1 sources and snapshot (security); P2 screen plus the PDF bound in `clients/cost.py` (security); P3 pass 1 and verification (`research/extract.py`); P4 pass 2, check-key registry (`research/checks.json`) and `pending/`; P5 review flow, `load_cards`, `papers.json`, extra and placeholders. Then E1 and E2 | E1 card stats (`learning/card_stats.py`, demotion proposals); E2 evolution: mutate kept and near-miss hypotheses, near-duplicate rejection (`optimization/evolve.py`); E3 one E5 re-run on v2 (Q2). The P units come after these, as a manual tool, or move to a later step |
| Matcher model        | Fable arm measured on v2 first                                                                                                                                  | unchanged                                                                                                                                                     |
| arXiv monitor        | user-machine script in Step 3                                                                                                                                   | Step 4 CLI, manual                                                                                                                                            |
| CLAUDE.md            | Step 3 row unchanged                                                                                                                                            | the Step 3 row drops PDF, extraction and monitor (needs the user's approval)                                                                                  |

While E5 is `pending`, Wave 3 does not start, and Waves 1 and 2 fill the time.

**Wave 4** (3b, own briefing and security review): B0 contracts and 006; B1
`names.py` plus the popular-name snapshot, B2 `policy.py`, B3 `wheels.py` (pure,
parallel); B4 `registry.py` and `proxy.py` (security); B5 `lockfile.py` and
`fetch.py` under confinement (security); B6 `envs.py`, `make_phase(env=)`, the
sweep and `_host` (security); B7 acquire node, C1, capture from C1, env
baseline (security); B8 combine with packages, drop, install line; B9 E2E and
L6.

**Wave 5** (3c): C0 contracts and 007; C1 `_heal_shim.py` and `signature.py`;
C2 writer and static checks (security); C3 reproduce node, freeze, N/N baseline,
`--deselect`; C4 `HealJudge`, equivalence exemption, `heal_tamper`, retry
exclusion (security); C5 commits R then F and the report; C6 E2E corpus and L7.

---

## 8 Open questions

1. **Q1, flagged heal delivery.** CLAUDE.md says a behaviour change is
   "flagged", while `derive_verdict` rule 6 says `needs_approval`
   (`judges.py:674-682`).
   - Recommendation: for `source=heal` only, deliver to a local branch that is
     never pushed, with a review header and no interrupt mid-run.
   - The user decides.
2. **Q2, E5 re-run.** If E5 says "deprioritised" on a saturated corpus, do we
   re-run it once on v2 before cutting the paper units? Recommendation: yes,
   once.
3. **Q3, lockfiles.** Two choices:
   - `uv.lock` in 3b, after probing `uv lock --no-build` on dynamic metadata, or
     requirements files only.
   - With no lockfile: ask the user (recommended), or let the engine create L0.
4. **Q4, registry hosts.** It is **unverified** whether pypi.org,
   files.pythonhosted.org, api.osv.dev and pypistats.org are reachable from
   runners and from the container proxy; L6 probes this. If pypistats is
   unreachable, is the downloads check dropped, or does it ask the user?
5. **Q5, order of 3b and 3c.** 3c has no network-on boundary and could ship
   first. The approved order stays unless the user swaps it.
6. **Q6, empty generator reply.** Opus high returned nothing twice. Retry once
   within the budget, or let the router end the run?
7. **Q7, package trial against a kept trial.** Must a package trial also beat a
   kept non-package trial on the same hotspot?
8. **Q8, reproducer model.** Sonnet 5.5 at medium is a guess; L7 measures it.
9. **Q9, small gains.** On OSS, 4/10 runs fell below the floor. Under the
   sample-stdev floor, more runs do not help (STATUS). Recommendation: no change
   in Step 3.
10. **Q10, novel lessons.** Their uuid4 `hypothesis_id` never matches across
    runs. Should U10 match them by normalised title within a project?
