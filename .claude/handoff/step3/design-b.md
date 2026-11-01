# Step 3 design B: one hypothesis-source framework (research, packages, healing)

Base: `claude/step3-research` at `ea891e6` (the Step 2 head). Angle: capability first and discovery maximal. The engine should find more real wins on real code (OSS-sized gains of 3-14 %, the hard corpus). Research, packages and healing are treated as **sources of hypotheses behind one interface**. Every proof rule and every protected-path rule stays as it is.

Paths are relative to `services/python_agents/src/autonomous_ai_agents/` unless they start with `tests/` or `infrastructure/`. "Verified" means I read it at `ea891e6`. "Unverified" means it is inferred.

One correction to the brief: the build-order table in `CLAUDE.md` still lists Steps 0-5 (verified). The approved 3b/3c/4/6 placement exists only in `STATUS.md`'s 2026-10-24 Decisions table. The Step 3 docs unit updates the table.

---

## 0. Decisions

**D1. Every idea comes from a `ProposalSource`.** The sources are the blind generator, playbook-matched generation, paper cards, evolution, package-needing ideas (3b) and heal cases (3c). Each returns plain `Hypothesis` objects, tagged with the existing `HypothesisSource` enum (`novel`, `playbook`, `paper`, `lesson`; 3c adds `heal`).
*Why:* there is one proof path (frozen judges, noise rule, anti-cheat); sources differ only in origin and prerequisites. One interface gives one ranking, budget and parking rule, and makes the E5 switch a weight, not a fork.

**D2. Prerequisites are explicit and engine-fulfilled.** A hypothesis may carry `needs`: a package (3b) or a reproducer (3c). A PREPARE stage meets them: `acquire` for packages, `reproduce` for reproducers. A need that cannot be met parks the hypothesis with a reason, and the report lists it as a proposal.
*Why:* the editor stays barred from manifests, lockfiles and tests (`anticheat.py:47-103`); only checked engine code writes them.

**D3. Generation is wired, and the candidate pool lives in the state.** The new state key is `proposals`. The router reads untried ideas from the state, not from `ctx.candidates` (today `nodes.py:1932` reads `ctx.candidates`, so a run with no caller candidates stops after round 1; verified).
*Why:* a checkpoint resume must not pay for generation twice, and the router must see what the generator produced.

**D4. The generator is Sonnet 5.5 at medium effort.** It runs with no fallbacks, `n=5`, `max_tokens=16000`. The matcher is Sonnet 5.5 at medium with `k=3`. Opus at high is dropped. Fable 5.1 stays an experiment arm until a corpus separates the arms.
*Why:* in E3, hit@5 was 22/22 at 0.014 USD a repo with no false big-gain claim on a control. Opus at high returned nothing twice. Every Opus arm claimed a gain on `lettertally`. Fable cost 7x on a saturated set.

**D5. Generation runs as a portfolio: blind and matched together.** By default both sources run every round. Ranking plus a diversity rule (D8) picks the slots.
*Why:* both arms reach 95-100 % hit@5; on real code the scarce thing is *distinct* ideas. The portfolio costs about 0.05 USD against 0.11-0.30 USD a run (ledger H, O). **Unmeasured**: U6 and L2/L3 measure it per source via `source:` lesson tags. E5 sets the paper weight (D14), not whether the playbook source exists.

**D6. Generation never starves the trial it feeds.** A source runs only when the pool has no untried idea, and only if `remaining - source_worst >= min_trial_budget_usd` (`factory.py:111-116`). All discovery spend in a run stays at or below `DISCOVERY_MAX_SHARE` (0.25) of the cap. Every request still goes through `call()`, which runs `Budget.check` (`transport.py:331`).
*Why:* the trials node offers each trial the whole remaining cap (`nodes.py:1508`; verified). Unbounded discovery would turn into fewer proofs.

**D7. Ranking caps the self-claimed gain.** The ranking score uses `min(expected_gain, cap)`. For a card-backed idea the cap is the card's `expected_gain`; for any other idea it is `GAIN_RANK_CAP` (0.5).
*Why:* Opus claimed big gains on a control. The current score `expected_gain * provability * (1 - risk) * (1 + boost)` (`ranking.py:53-60`) lets an inflated claim win the slot.

**D8. Rounds are diverse.** At most `MAX_PER_SOURCE_PER_ROUND` (2) of the 3 slots come from one source. No two ideas in a round share a `(technique_id, first hotspot)` pair.
*Why:* OSS gains are small and spread out. Three variants of one idea on one hotspot waste two worktrees.

**D9. The editor model gets its own setting.** `EDITOR_MODEL` defaults to Sonnet 5.5 and `EDITOR_EFFORT` to `low`. An escalation tier, Opus 5.5 at high, serves evolution's re-attempts (D12). The understander keeps `ENGINE_MODEL` (Opus 5.5). Today the editor shares the `ENGINE_MODEL` transport (`factory.py`, verified).
*Why:* E8a: 12/12 first pass, 0/3 control wins, about 0.04 USD a run; the saving pays for the portfolio and retries. E8a covered only the easy corpus, so L3 is the gate: fewer OSS wins than Opus minus one sends the default back to Opus.

**D10. The slug is the technique identity in memory; Postgres maps it.** Migration `005_step3_technique_slug.sql` adds `lessons.technique_slug VARCHAR(100)` with a slug `CHECK`.
- `save_lesson` (`postgres.py:402-420`) stores the slug there, plus `technique_id = uuid5(TECHNIQUE_NAMESPACE, slug)`.
- `_LIST_LESSONS` returns `COALESCE(technique_slug, technique_id::text)`.
- The same uuid5 seeds `techniques.id` when that table is first written.

*Why (verified):* the first playbook keep on Postgres fails `learn`: `_optional_uuid` refuses a slug (`postgres.py:411`, `:185-200`); `003_engine.sql:294-296` keys techniques by UUID with a unique slug; `lessons.technique_id` is a bare UUID, no FK. uuid5 needs no lookup or seeding; the stored slug makes read-back independent of a seeded `techniques` table (seeding drift). The pinned refusal test (`tests/persistence/test_postgres.py:193-195`) now refuses only a non-slug: a deliberate, called-out behaviour change, not a weakened test.

**D11. The engine retries itself on fixable errors.** The rules are below; §4.2 gives the flow.
- **When.** Only when the failure kind is `exit` and stderr holds a parsed Python traceback of a fixable type: `SyntaxError`, `IndentationError`, `TabError`, `ImportError`, `ModuleNotFoundError`, `NameError`, `UnboundLocalError`, `TypeError`, `AttributeError`.
- **How many.** `EDITOR_FIX_RETRIES=1` (at most 2), on the same `Budget`.
- **What the editor gets back.** Feedback under the information-closure rule (D23).
- **Never retried:** timeouts, floods, isolation failures, `AssertionError`, the test suite, judge results or timings.

*Why:* generated ideas fail more often than aimed ones, and a typo should not cost an idea. The retry lives in `GitTrialRunner._attempt` (`trial_runner.py:502-587`), which returns before any judge runs, so it cannot learn from a verdict.

**D12. Evolution turns near misses into new, freshly judged trials.**
- **Compound.** When at least two trials ended `inconclusive` with the gain in the right direction (at least `NEAR_MISS_FRACTION` = 0.5 of their noise floor), no failed judge and no violation, on disjoint files, the engine merges their commits (the combine machinery) into one new trial. That trial is judged from scratch.
- **Escalate.** A hypothesis whose editor stopped without a usable change, or that came close, gets one re-attempt on the escalation tier.
- Both are `source=lesson` with `parent_trial_ids`.

*Why:* 4/10 OSS repos found nothing past the noise; small gains are what real code offers. A compound is a new hypothesis measured fresh (N ≥ 5, same judges, full capture on the merged diff); selection uses old measurements, the proof new ones, so no rule weakens.

**D13. A keep that fails combine is discounted in the lessons.** The weight is 1.0 when held or skipped, 0.5 when unconfirmed and 0.25 when not reproduced (the research-engine W4 table). The outcome itself is unchanged.
*Why:* the `sortedcontainers` win failed its re-test; it should not count as a full keep. `chk_lesson_weight > 0` allows it.

**D14. Paper priority is a switch E5 sets, not a code path.**
- `PAPER_PRIORITY` (`first_class` or `deprioritised`) and `PAPER_CARD_PRIOR` (1.0 or 0.5) live in `Settings`.
- `research_plan(AbOutcome | None)` maps `c - b >= 3` to `first_class`. Anything else, including `None`, maps to `deprioritised`.
- The code is identical in both branches. The switch changes the wave order (§7), whether paper cards join the card pool, and whether intake runs on a schedule or as a manual tool.

*Why:* the rule was registered before the run. Nothing in this design assumes the outcome.

**D15. Paper intake never contacts arXiv from CI or a container.** CI reads a committed snapshot of metadata, abstracts and sha256 values. PDFs are fetched on the user's machine.
*Why:* E2 got HTTP 429 three times. The container's proxy refuses arXiv, Semantic Scholar and OpenAlex.

**D16. Extraction runs in two passes on Sonnet 5.5 at medium.**
- **Pass 1:** the PDF goes in as a document block with citations on and no `output_config.format`. Quotes are verified locally (move `tests/live/experiments/extraction.py` `match` and `judge`).
- **Pass 2:** structured output over the verified items only.
- A human approves each card before any matcher sees it.

*Why:* citations combined with a format is a 400 (E1). E7 gave 1-3 cards a paper at 0.2-0.3 USD. CLAUDE.md's "Opus for extraction" line changes to match.

**D17. Same environment on both sides (3b, user point 1).** The baseline and the trial run in environments built from the same lockfile. They differ only by the acquired package and its new dependencies.
- A resolver upgrade or downgrade of any existing dependency is a separate change. It is shown in the report and measured on its own: a `dependency-upgrade` hypothesis, class `behaviour`, measured alone against E0.
- The delivered branch's report says the user must install the new dependency.

**D18. No wheel means ask (3b, user point 2).** A package or transitive dependency that exists only as an sdist fails the automatic policy, because building runs code. It goes to the user, never to an automatic build. The resolver runs with `--only-binary :all: --no-build`.

**D19. Only popular names are acquired automatically.** A package is auto-acquired only if its name is in the committed, dated snapshot of the top 15k PyPI projects, and every other check passes too (§5). Any other name asks the user.
*Why:* a hallucinated name is plausible but, by construction, not popular. The snapshot also answers the download floor offline, removing pypistats (unverified reachability).

**D20. The network-on fetch phase runs only engine code and a pinned `uv`.**
- No repository code and no package code runs in it.
- Repository bytes never enter it. The constraints are `name==version` lines the engine generates from L0, which it reads from git objects at `base_commit`.
- Traffic goes through an engine CONNECT proxy on loopback that allows only `pypi.org`, `files.pythonhosted.org` and `api.osv.dev` on port 443.
- `uv` runs read-confined (§5, read-confinement row).

*Why:* until now the only network was the engine's API client; a resolver reading user or repo config could redirect or exfiltrate.

**D21. The engine writes its own capability commit; nothing else may.**
- The capability step commits L1 and the manifest line as C1, before the editor runs.
- Capture diffs against C1, so the editor is still barred from lockfiles.
- C1 must equal an offline re-resolve of `(L0, approved packages)`.
- Combine re-resolves the union of the kept packages. It never merges lockfile text.

*Why:* otherwise every package trial fails `protected_path` (`trial_runner.py:539` diffs against the base); the recompute stops either side smuggling the other's change.

**D22. Reproducer integrity (3c, user point 3).**
- The reproducer is written in a separate request, before any fix is attempted, and frozen as a protected file.
- It must fail on the baseline N of N runs.
- It must fail for the reported reason: the same exception type, and the same frame or message as the error report.
- The fix's trial may not touch it.
- The report shows the reproducer next to the fix.

**D23. Information closure for every channel from run output to the API.** Run output reaches the API through retry feedback (D11) and through heal error text (3c). Two rules apply:
- **Frames:** only frames inside the worktree, and never in a `READ_DENY_PATTERNS` file.
- **Messages:** sent only when every identifier in the message (`[A-Za-z_]\w*`) appears in the trial's diff or in the base's tracked sources, every number has at most 4 digits, and the message is at most 300 printable characters. Otherwise only the type and the frames go back.

*Why:* a new channel: editor-written code could read `~/.aws/credentials` and raise it; the retry would carry it to the API. The rule returns only what the API has already seen. Landlock read confinement for trials is defence in depth (Q4).

**D24. Heal is a run mode, not a mixed-in hypothesis.**
- `RunMode.heal` uses the same graph plus a `reproduce` node.
- Its objective is `Objective(custom, "heal_passed", maximize)`. Wall time and RSS become `metric_bound` guardrails.

*Why:* a heal's objective is not "faster"; mixing it into an efficiency combine muddies the branch's class and the equivalence judge.

**D25. Behaviour delivery is a switch; the frozen verdict order is unchanged.**
- `derive_verdict` rule 6 (`judges.py:674-682`) keeps sending `behaviour` to `needs_approval`.
- `BEHAVIOUR_DELIVERY=gate` (the default) keeps today's interrupt.
- `review_branch` resolves the gate itself. It delivers behaviour keeps on a separate local branch, `engine/review-<run>`, with a review header in the report and never merged into `engine/run-<run>`. Novel ideas still interrupt.

*Why:* CLAUDE.md says flag, the code gates; the user picks (Q2). Until then unattended Step 3 runs park generated `behaviour`/`novel` ideas as proposals, so nothing stalls at the gate.

**D26. Waves start with the units that do not depend on the A/B result.** Generator and matcher wiring, the self-retry, the slug mapping and the offline eval come first. The paper units wait for E5.
*Why:* E5 is still running. Nothing in those first units changes with its outcome.

---

## 1. Scope and non-goals

**Step 3.** `ProposalSource` wiring (blind, matched, evolution), the pool in state, ranking caps and diversity; self-retry; slug mapping (005); combine discount; `EDITOR_MODEL`; offline discovery eval, grader labels, hard corpus v2 and the `ledgerclose` rebuild; check registry; the paper pipeline in D14's order.

**Step 3b.** Package hypotheses, policy, fetch, environments, C1, combine and delivery for packages, and migration 006.

**Step 3c.** Heal cases supplied by the caller, the reproducer, the heal judges, the review-branch delivery, and migration 007.

**Non-goals.** MCP/API discovery, error-monitoring intake, the CLI, `--goal`, hardware detection, trial read confinement and `spawn` (Step 4); held-out inputs (Step 5); rollout (Step 6); building sdists even when approved; private, CUDA or MPS indexes; npm; fine-tuning; LLM novelty scores; batches and 1 h caching (cents a week at Haiku prices); any change to the noise rule (Q6).

---

## 2. Architecture

```
START → connect → understand → define → baseline → profile → research
                                             │        │ cards: playbook.json (+ papers.json if PAPER_PRIORITY)
                                             │        │ matches: TechniqueMatchRecord (Sonnet, k=3)
                     [mode=heal] reproduce ◄─┘        ▼
                     (separate request, frozen,  hypotheses ◄──────────────────────────┐
                      fails N/N, same reason)    pool = state.proposals                 │
                                                 sources: blind | matched | paper |     │
                                                   evolution | heal  (ProposalSource)   │
                                                 rank(capped gain, lessons) + diversity │
                                                 park: needs unmet / class not allowed  │
                                                        ▼                               │
                                                 ACQUIRE (3b)                           │
                                                 policy(offline facts) → FETCH          │
                                                 [network ON: engine + pinned uv only,  │
                                                  proxy allowlist, read-confined]       │
                                                 → wheelhouse(sha256) → env E1 (offline)│
                                                 → C1 capability commit (recomputed)    │
                                                        ▼                               │
                                                 trials (one worktree each, network OFF)│
                                                 editor → capture vs C1 → anti-cheat    │
                                                 → measure ─ fixable error? ─► HEAL-SELF│
                                                   (retry ≤1, closure-filtered feedback)│
                                                        ▼                               │
                                                 judges (frozen; HealJudge in heal mode)│
                                                        ▼                               │
                                                 verdicts ──after_verdicts── no keep, ──┘
                                                        │                  pool/sources left,
                                                        │                  round < max
                                    needs_approval ─────┤ (evolution adds compounds/escalations)
                                    approval_gate ◄─────┤ BEHAVIOUR_DELIVERY=review_branch:
                                          │             │   gate resolves itself, novel interrupts
                                          ▼             ▼
                                        combine (ABAB re-test; re-resolve lock; drop unused pkgs)
                                          ▼
                                        deliver: [C-cap: lockfile + why] [R: reproducer] [code]
                                          ▼
                                        learn (weights from combine; source:/card tags)
                                          ▼
                                        watch → END
Frozen outside the state: judges, protected patterns (+ reproducer, + C1 paths), noise rule,
popular-name snapshot, policy config, reproducer sha256.
```

---

## 3. Interfaces

### 3.1 Proposal sources (`optimization/sources.py`, new)

```python
@dataclass(frozen=True)
class ProposalRequest:
    project: Project
    understanding: ProjectUnderstanding | None
    hotspots: tuple[Hotspot, ...]
    objective: Objective                 # state["objectives"][0]; define always sets one
    techniques: tuple[Technique, ...]    # the cards this source may show
    lessons: tuple[Lesson, ...]          # the project's last 20, fenced as untrusted
    avoid_titles: tuple[str, ...]        # titles already tried or pooled
    near_misses: tuple[TrialSummary, ...]  # evolution only: id, files, gain/floor ratio
    n: int

@dataclass(frozen=True)
class ProposalBatch:
    hypotheses: tuple[Hypothesis, ...]
    notes: tuple[str, ...]
    cost_usd: float
    tokens_used: int

class ProposalSource(Protocol):
    @property
    def kind(self) -> HypothesisSource: ...
    def worst_case_usd(self, request: ProposalRequest) -> float: ...
    def propose(self, request: ProposalRequest, budget: Budget) -> ProposalBatch: ...
```

The implementations:
- `BlindSource(transport)`: wraps `generate_hypotheses` with `techniques=()`.
- `MatchedSource(gen, matcher)`: runs `match_techniques(k)`, then `generate_hypotheses` on the matched cards (E5 arm B).
- `PaperSource`: the same as matched, over the paper cards, weighted by `PAPER_CARD_PRIOR`.
- `EvolutionSource()`: makes no LLM call. It builds compound and escalate hypotheses.
- `HealSource(case)`: one generic `source=heal`, class `behaviour` hypothesis.

`generate_hypotheses` (`generate.py:189`) gains `lessons=` and `avoid_titles=`, rendered as fenced lines through `_fenced_line`. Lessons reach only the generator, never the editor.

### 3.2 Models (`common/models.py`, all with serde-safe defaults)

- `Hypothesis` gains:
  - `needs: tuple[Need, ...] = ()`, where `Need = PackageNeed(name, reason) | ReproducerNeed(case_id)`;
  - `parent_trial_ids: tuple[str, ...] = ()`;
  - `attempt: AttemptMode = AttemptMode.default`, one of `default`, `escalate` or `compound`.
- `Trial` gains:
  - `attempts: int = 1`;
  - `retry_reasons: tuple[str, ...] = ()`;
  - `env_lock_sha256: str | None = None`.
- New models:
  - `TechniqueMatchRecord(slug, fit, justification_summary, unmet)`;
  - `ParkedProposal(hypothesis_id, title, reason)`;
  - `Acquisition` (3b);
  - `HealCase` and `Reproducer` (3c).

  All of them go into `ENGINE_SERDE_ALLOWLIST`; the reflection test enforces it.
- `HypothesisSource.heal` arrives in 3c.
- `RunPhase.acquire` arrives in 3b and `RunPhase.reproduce` in 3c. Each enum change ships with its SQL `CHECK` migration.

### 3.3 State keys (`orchestrator/state.py`; every key set in `initial_state`)

| Key | Type | Channel | Set by |
| --- | --- | --- | --- |
| `proposals` | `list[Hypothesis]` | replace | hypotheses (pool not yet sliced) |
| `parked` | `list[ParkedProposal]` | replace | hypotheses, acquire, reproduce |
| `technique_matches` | `list[TechniqueMatchRecord]` | replace | research |
| `discovery_calls` | `int` | replace | hypotheses |
| `discovery_cost_usd` | `float` | replace | research, hypotheses (also counted in `cost_usd`) |
| `run_mode` | `RunMode` | replace | `initial_state(..., heal_case=None)` |
| `env_baselines` | `dict[str, Baseline]` | replace | acquire (3b), keyed by lock sha |
| `acquisitions` | `list[Acquisition]` | replace | acquire (3b) |
| `heal_case`, `reproducer` | `HealCase \| None`, `Reproducer \| None` | replace | `initial_state`, reproduce (3c) |

### 3.4 Context, factory and router

- `NodeContext` (`nodes.py:181-237`) gains:
  - `sources: tuple[ProposalSource, ...] = ()` (empty keeps the Step 2 behaviour);
  - `research_policy: ResearchPolicy`;
  - `acquirer: Acquirer | None` (3b);
  - `reproducer_writer: ReproducerWriter | None` (3c).
- `build_context` (`factory.py:303`) gains `generator_transport`, `matcher_transport`, `editor_transport`, `techniques` (default `load_cards()`) and `research_policy`. Each transport comes from `model_settings(settings, MODEL, fallbacks=...)`, promoted from `tests/live/discovery.py`.
- **Router change, `after_verdicts` (`nodes.py:1919-1936`).** Replace the `ctx.candidates` test (line 1932) with `untried(state, ctx)`. That is true while an untried idea is left in `ctx.candidates` or `state["proposals"]`, or while a source is still affordable under D6 and `discovery_calls < GENERATOR_MAX_CALLS`.

### 3.5 Settings (`common/config.py`, validated)

The validators (lines 319-353) are extended so that every new model is priced and every effort level is valid for its model chain.

| Setting | Default | Source of the value |
| --- | --- | --- |
| `GENERATOR_MODEL` / `_EFFORT` / `_FALLBACKS` | `claude-sonnet-5-5` / `medium` / `False` | E3 |
| `GENERATOR_N` / `_MAX_TOKENS` / `_MAX_CALLS` | 5 / 16000 / 3 | E3 |
| `MATCHER_MODEL` / `_EFFORT` / `_K` | `claude-sonnet-5-5` / `medium` / 3 | E5 arm B |
| `RESEARCH_SOURCES` | `("blind", "matched")` | D5 |
| `PAPER_PRIORITY` / `PAPER_CARD_PRIOR` | `deprioritised` / 0.5 until E5 is recorded | D14 |
| `DISCOVERY_MAX_SHARE` / `GAIN_RANK_CAP` / `MAX_PER_SOURCE_PER_ROUND` | 0.25 / 0.5 / 2 | D6-D8 |
| `EDITOR_MODEL` / `EDITOR_EFFORT` | `claude-sonnet-5-5` / `low` | E8a |
| `EDITOR_ESCALATION_MODEL` / `_EFFORT` | `claude-opus-5-5` / `high` | E8a escalation arm |
| `EDITOR_FIX_RETRIES` | 1 (0 ≤ n ≤ 2) | D11 |
| `EVOLUTION_ENABLED` / `NEAR_MISS_FRACTION` / `EVOLUTION_MAX_PER_RUN` | `True` / 0.5 / 2 | D12 |
| `EXTRACT_MODEL` / `_EFFORT`, `SCREEN_MODEL` | `claude-sonnet-5-5` / `medium`, `claude-haiku-5-5` (no fallbacks) | E7, E6 |
| `ACQUIRE_*` (3b) | `ENABLED=False`, `MAX_PACKAGES=1`, `MIN_PROJECT_AGE_DAYS=90`, `MIN_VERSION_AGE_DAYS=14`, `LICENCES=(MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0)`, `INDEX_HOSTS`, `POPULAR_SNAPSHOT` | D17-D20 |
| `HEAL_REPRO_MODEL` / `_EFFORT` / `_RETRIES` (3c) | `claude-sonnet-5-5` / `medium` / 1 (**unmeasured**) | Q8 |
| `BEHAVIOUR_DELIVERY` | `gate` | D25 |

### 3.6 Trial runner and editor

- `TrialBrief` (`protocols.py:76`) gains:
  - `env: EnvHandle | None = None`;
  - `capability_commit: str | None = None`;
  - `retry_excluded: tuple[str, ...] = ()` (the reproducer paths);
  - `exempt_workloads: tuple[str, ...] = ()`.
- `EditTask` (`protocols.py:137`) gains `feedback: TrialFeedback | None = None`, where `TrialFeedback(kind, exc_type, frames, message | None)`.
- `procrun.RunFailure` (`procrun.py:112`) gains:
  - `kind: Literal["exit", "timeout", "flood", "isolation", "report", "path", "other"]`;
  - `crash: CrashReport | None`, filled by `measure.launch` (`measure.py:233-260`) from `stderr_tail`, which today keeps only the last line (verified).
- New `execution/retry.py`:
  - `classify(failure, *, closure: ClosureIndex) -> TrialFeedback | None`;
  - `ClosureIndex.from_sources(diff, tracked_texts)`.
- `GitWorkspace.commit(handle, message, *, base, parent=None)`. Today the parent is always the worktree HEAD (`git.py:765-774`, verified). A retry passes `parent=base`, so the trial stays one child of the base and passes combine's `_unfit` check (`combine.py:246-252`).

### 3.7 Card store and the paper pipeline (`research/`)

- `load_cards(paths=(PLAYBOOK_PATH, PAPER_CARDS_PATH)) -> tuple[Technique, ...]` refuses a slug that appears in more than one file. `papers.json` adds `provenance {arxiv_id, sha256, quotes[], screened, approved_by}`, read through an opt-in `extra_fields` of the strict loader.
- `research/checks.json` is the check-key registry: the 130 keys in use, plus a `new.*` escape that a reviewer renames on approval.
- `research/sources.py`:
  - `PaperFeed` is a protocol.
  - `SnapshotFeed(path)` serves CI from a committed JSONL of metadata, abstracts and sha256 values.
  - `ArxivFeed` raises `SourceUnavailable` under `GITHUB_ACTIONS`. It keeps `check_url`, 3 s spacing and size caps.
- `research/screen.py`: `screen_text(...) -> ScreenVerdict`, fail-closed.
- `research/extract.py`: pass 1 plus local verification.
- `research/cards.py`: `to_cards(..., registry)`.
- `research/ingest.py`: `ingest(...) -> IngestResult`. Its output goes to `research/cards/pending/`, which the engine never loads.
- `clients/cost.py` gains `PDF_PAGE_TOKENS` and `pdf_pages`, moved from `tests/live/experiments/bounds.py`.
- `pyproject.toml`: the `research` extra becomes `pypdf>=6,<7`. `pymupdf` (AGPL), `arxiv` and `sentence-transformers` are dropped.

### 3.8 Step 3b (`capabilities/`, new package)

```python
names.near_miss(name: str, popular: PopularSnapshot) -> str | None   # DL<=2, -_. folding, affixes, confusables
policy.evaluate(facts: PackageFacts, cfg: AcquirePolicy) -> PolicyResult  # pure; ok | needs_user(reason)
registry.PypiClient(proxy: AllowlistProxy).facts(name) -> PackageFacts     # JSON API + OSV querybatch
lockfile.read_base_lock(git, base) -> BaseLock                    # uv.lock or hash-pinned requirements; else needs_user
lockfile.resolve(base: BaseLock, wanted: Sequence[str], *, online: bool) -> ResolvedLock
lockfile.diff_locks(l0, l1) -> LockDiff(added, changed, removed)  # changed/removed non-empty → D17 split
wheels.inspect_wheel(path) -> WheelReport                          # RECORD, METADATA, entry points; no extraction
fetch.Fetcher.download(lock: ResolvedLock, store: Path) -> tuple[Path, ...]  # sha256 checked
envs.EnvBuilder.build(lock, store) -> EnvHandle(path, lock_sha256, python)   # offline, --require-hashes --no-build
class Acquirer(Protocol):
    def acquire(self, hypothesis, base_lock, *, run_dir) -> AcquireOutcome  # ready(EnvHandle, C1 tree) | parked(reason)
```

- `make_phase(..., env: EnvHandle | None)` puts `VIRTUAL_ENV` and an env-first `PATH` into `child_env`'s `extra` (`sandbox.py:145-152`).
- `phase._phase_names` (`phase.py:265-282`) skips `_env` and `_wheels`; today it would sweep them as worktrees (verified).
- `_host` records `env_lock_sha256` and the workload's Python.
- Migration `006_step3b_packages.sql` adds to `packages`: `sha256`, `license_expression`, `first_release_at`, `policy_result`, `checked_at`. It adds a `run_packages(run_id, package_id, hypothesis_id, reason, outcome, gain)` table and puts `acquire` into `chk_task_phase`.
- New protected patterns (verified missing): `pip.conf`, `uv.toml`, `requirements*.in`, `constraints*.txt`, `pylock*.toml`, `pdm.lock`, `.python-version`.

### 3.9 Step 3c (`healing/`, new package)

```python
HealCase(kind: failing_test|crash|error_report, test_node_id|workload_id, signature: Signature)
Signature(exc_type: str, message: str, frames: tuple[Frame(file, function, line), ...])  # never locals
class ReproducerWriter(Protocol):
    def write(self, case: HealCase, sources: BaseSources, budget: Budget) -> ReproducerDraft  # own request, no tools
check_reproducer(draft, tracked) -> tuple[str, ...]        # static: stdlib+repo imports, _spawn_problem, no try round target, size
confirm_failure(phase, repro, case, runs=MIN_RUNS) -> ReproCheck  # N/N, same type, repo-frame or masked message
HealJudge(metric="heal_passed"); EquivalenceJudge(exempt_workloads=reproducer_ids)
```

- `healing/_heal_shim.py` is stdlib-only and modelled on `_profile_shim.py`.
- A new capture rule, `heal_tamper`, joins `check_capture`.
- Migration `007_step3c_heal.sql` adds `heal` to `chk_hypothesis_source` and `reproduce` to `chk_task_phase`.

---

## 4. Behaviour

### 4.1 Research and hypotheses (Step 3)

1. **research** loads the cards (`playbook.json`, plus `papers.json` when `first_class`), runs the matcher once if `matched` is enabled and writes `technique_matches`. A matcher failure (`BudgetExceeded`, `UnusableReplyError`, `LLMUnavailable`) is a `research_unavailable` note; the run continues blind. Spend goes through `_charged` (`nodes.py:576-587`).
2. **hypotheses, round r.** The pool is unseen `ctx.candidates` plus `proposals`. With no untried idea, it calls each enabled source under D6 (ids checked by `validate_run_id`; evolution from round 2 on round r-1's near misses), drops duplicate titles, parks classes outside `GENERATED_CLASSES` (default `{efficiency}`), unmet `needs` and anything over the share, ranks (D7, D8), slices 3 into the round and keeps the rest. Generated hotspot ids end `_brief_hotspots`' top-5 fallback (`nodes.py:342-355`).
3. **Failures.** A source error or empty answer is a note (no retry); all sources failing on an empty pool routes to combine ("no hypotheses"); an `EngineError` ends the run with `keep_progress`, as understand does (`nodes.py:1262-1286`).

### 4.2 The self-retry (Step 3)

When `_measure` raises `RunFailure` and `classify` returns feedback, while `attempts <= EDITOR_FIX_RETRIES` and `budget.remaining >= min_trial_budget()`:

1. `phase.reset()` (the worktree equals commit 1);
2. edit with `feedback` on the same `Budget`; the notice says "your previous change, still in the worktree, failed when run; fix that error, keep the approach", with the crash fenced under D23;
3. merge the `written` maps, enforcing the file and byte limits over the union;
4. re-capture against the base (or C1) and re-run every anti-cheat check;
5. `commit(..., parent=base)`, `update_ref(own_ref, c2, c1)`, `progress.moved = c2`;
6. measure again.

An unaffordable or failed retry returns the first failure with a note (never `TrialUnaffordable`); an exception takes the existing `_undo_own_ref` path; a failure inside `retry_excluded` (the reproducer) is never retried.

### 4.3 Evolution

- **Compound:** up to two disjoint near misses are re-applied onto the base with the `GitCombiner` tree merge as one child commit: a trial with no editor and zero tokens, through full capture, anti-cheat and fresh N-run measurement.
- **Escalate:** the same text, a new id, `attempt=escalate`; the runner uses the escalation transport.
- Both bounded by `EVOLUTION_MAX_PER_RUN`; lessons tagged `source:lesson`, `evolution:<kind>`.

### 4.4 ACQUIRE (Step 3b)

This runs for each hypothesis with a `PackageNeed`. It needs a supported base lock; with none, it parks (Q3).

1. **Facts.** The snapshot checks run first, offline: popularity and near miss. Then the proxied JSON API: the name exists, the project is at least 90 days old, the version at least 14 days. Then OSV, `MAL-` advisories included. A check that cannot run fails, and a failed check asks the user.
2. **Resolve online** with `uv pip compile --no-config --no-sources --only-binary :all: --no-build --generate-hashes --default-index https://pypi.org/simple --exclude-newer <now-14d> --python-version <workload> -c <L0 as ==>`. The command runs in `<run>/_wheels/` with the environment scrubbed. An sdist-only package or dependency gives `needs_user` (D18). A pin that changed or was removed gives the separate `dependency-upgrade` trial (D17).
3. **Download and vet.** Each wheel is fetched and its sha256 checked into the content-addressed store. Then `inspect_wheel` runs and the licence is checked against the allowlist.
4. **Build E0 from L0 and E1 from L1, offline**, under `<run>/_env/<sha>`, which trials can read but not write. If the run has no E0 baseline yet, it measures one into `env_baselines`.
5. **Write C1** (D21) and pass `env` and `capability_commit` in the brief. The editor may view the package's top-level `.py` and `.pyi` files read-only under `/deps/<name>`, fenced as untrusted and size-capped.
6. **Judge** only against the baseline with the same `env_lock_sha256`. Any other pairing is `inconclusive`.
7. **Combine.**
   - Each kept package trial is rebuilt as X′, a single child of the base, and one re-resolved capability commit goes first.
   - Packages that no kept change imports (an AST scan through `top_level.txt`) are dropped, then the lock is re-resolved and the combination re-tested.
   - If a no-package keep on the same hotspot is within the noise of the package keep, the no-package change wins.
8. **Deliver.** The capability commit goes first, with the lockfile diff and, per package: the reason, the importing change, the gain and the policy evidence. The report says: "This branch adds `<name>==<ver>` and N dependencies; you must install them (`uv sync` or `pip install --require-hashes -r <lock>`)."

### 4.5 Heal (Step 3c)

1. **Define** sets `heal_passed` as the objective. **Baseline** measures everything except the failing case: pytest runs with `--deselect <node>`, and unittest asks the user. A failing suite would otherwise abort the run at `_require_trustworthy_baseline` (`nodes.py:647-692`; verified).
2. **Reproduce** follows D22.
   - It is written in its own request, with no tools and the report fenced: a stdlib-only script asserting the expected *value*, plus 2-3 held-out variants the editor never sees. For `failing_test`, the user's test is the reproducer.
   - It is checked statically, then frozen at `<run>/_heal/repro_<id>.py`, outside `writable`, with its sha256 checked before every run and its delivered path in `extra_protected`.
   - It runs `MIN_RUNS` times under the shim. Every run must raise the reported qualified type, in a repository file at base (not in the reproducer). The innermost repo `(file, function)` must match, or the message with numbers, addresses and ids masked.
   - A mismatch gets one rewrite, then the run asks the user.
3. **Trial.** One generic heal hypothesis. The editor sees the report and the public reproducer.
4. **Judges.**
   - `heal_tamper` checks the capture.
   - `HealJudge` needs the reproducer and every variant to exit 0 on N of N runs, with the shim document present.
   - Equivalence exempts only the reproducer ids.
   - The full suite runs with nothing deselected: at least the baseline count plus 1 for `failing_test`, otherwise at least the baseline count.
   - A broad `except` on a reported frame is flagged.
5. **Deliver** under `BEHAVIOUR_DELIVERY`. Commit R adds the reproducer at `tests/engine_heal/test_<slug>.py`, then commit F adds the fix. The report shows the reproducer next to the fix, with the signature, N/N failures on the baseline and N/N passes on the trial.
6. **Controls.** A case that cannot be reproduced, intended behaviour, or a stack outside the repo ends with "ask the user" and no branch.

### 4.6 Other failure modes

A policy check that cannot run: `needs_user`, parked, listed in the report (Q7). C1 differing from its recompute: `RepoTamperedError`. A compound that conflicts: skipped with a note.

---

## 5. Security

| Threat | Control |
| --- | --- |
| **Prompt injection from papers** | Haiku screen of the pypdf text (fail closed) → `NOTE:` lines in pass 1 → pass 2 sees only verified quotes in a fresh fence → card validators (no URL, backtick, `pip`/`install`; slug, check and registry rules) → human approval → stable-token fence in the matcher (`playbook.py:216-250`) → a card is only a hypothesis for frozen judges. Residual: an instruction in a figure skips the screen. |
| **Injection through lessons and titles in the generator prompt** | Fenced untrusted lines; a line holding the boundary token is withheld. The editor never sees lessons. |
| **Slopsquatting** | D19 popular-snapshot membership plus near-miss distance; existence, age and OSV checks; a model names a package, never a version or URL. |
| **Dependency confusion** | One public index, `--no-config --no-sources`. A repository naming another index, or holding a local package of the same name, asks. |
| **A compromised popular package** | The 14-day version age, OSV `MAL-` advisories and `--exclude-newer` on every transitive dependency. |
| **A malicious wheel** | Wheels only, no code at install; RECORD, `.pth`, scripts and entry points inspected; imported only in network-off trials. Residual: the user's machine after install, hence the per-package evidence in the report. |
| **Time of check to time of use** | Content-addressed store plus `--require-hashes`; E1 is rebuilt from the store, never re-fetched. |
| **Read confinement once network-on phases exist** | Only engine code and pinned `uv` run network-on (D20), through the allowlist proxy; `uv` under Landlock (read: uv, system CA and libs, `_wheels`; write: `_wheels`) or macOS `sandbox-exec` with a read allowlist; no repository bytes enter the phase; trials stay network-off; every run-output → API channel follows D23; trial read rules in Step 4 (Q4). |
| **Reward hacking through the retry** | Only the trial's own crash goes back (type, worktree frames, closure-checked message). Never stdout, timings, verdicts or suite results. The retry returns before the judges run, and the full anti-cheat re-runs on the merged diff. |
| **Reproducer gaming** | Writer: raise in a repo frame at base, same type and frame or message, N/N. Editor special-casing: held-out variants plus `heal_tamper`. Suppression: flag plus review. In-process shim forgery: exit code, shim document and variants all required (rest is the accepted memorisation gap). Tampering: frozen outside `writable`, sha256 per run, protected on the branch. |
| **Injected error text** | Fenced; locals are never sent; D23 applies. |
| **A smuggled lockfile or manifest** | The editor is still refused on protected paths (capture against C1); C1 is recomputed and compared; the protected-pattern gaps in §3.8 are closed. |
| **Cost exhaustion** | D6 share cap, `GENERATOR_MAX_CALLS`, `EDITOR_FIX_RETRIES ≤ 2`, `EVOLUTION_MAX_PER_RUN`. Every request is checked first by `Budget.check`. Registry and OSV lookups cost no tokens. |

---

## 6. Test plan

The coverage gate stays at 90 % (today 100 % line and branch). Builders get the SEAMS checklist.

**Unit (offline).**
- **Sources and wiring:** recording fakes; the D6 guard and share cap; `sources=()` keeps every Step 2 test unchanged; a `lettertally`-style inflated gain loses its slot; a resume makes no second generator request; the router goes to `hypotheses` with empty `ctx.candidates` and a non-empty pool; a matcher failure falls back to blind.
- **Retry:** `CrashReport` parsing; the classification table (timeout, signal, `AssertionError`, suite → `None`); D23 withholds a message with an identifier found in no diff or source; SyntaxError then fix gives `attempts == 2`, one commit parented on the base (`_unfit` passes), no `unrecorded_write`; the cap, the unaffordable path, an aborted retry restoring the own ref.
- **005:** a slug round-trips; a non-slug is refused before connecting; a legacy UUID row reads back; the migration runs twice.
- **Discount and evolution:** each weight row; a compound is judged fresh; a compound touching a protected path is rejected.
- **3b:** `reqeusts`, `numpi`, a Cyrillic homoglyph and an off-snapshot name ask; each policy check passes and fails; an unreachable host gives `needs_user`; a forced pin change gives a separate trial (D17); an sdist-only transitive dependency gives `needs_user` (D18); resolving twice gives the same bytes; `../`, `.pth`, `*.data/scripts` and a `pytest` script are refused; offline installs under `unshare -rn`, a read-only env, E0/E1 differing only by additions; an editor `uv.lock` edit after C1 is `protected_path`; a tampered C1 is refused; the sweep removes `_env` and `_wheels`.
- **3c:** 5/5 matching is accepted; 3/5, a wrong type, a raise inside the reproducer or a sha change is refused; `HealJudge` on a flaky run and a missing shim document; equivalence exempts only reproducer ids; each `heal_tamper` token is rejected; pytest deselect works and unittest asks.

**E2E (offline, `tests/e2e/`).**
- `test_step2.py` with `candidates=()` and a scripted generator reaching a delivered branch.
- A retry fixture: an edit set with a SyntaxError, then its fix.
- A compound fixture: two 3 % edits that together clear the floor on the scripted runner.
- 3b: a fixture wheel built with `zipfile` speeds up a loop and is delivered with the install line. In a control where it does not help, it is dropped.
- 3c: 5 planted bugs (KeyError, off-by-one, None, encoding, mutable default) and 3 controls.

**Offline discovery regression eval (U6, test-only).**
- `discovery_grader.grade` splits into `grade_with(transport, budget, ...)`.
- The sweep records the raw generator reply, the hotspots, the objective and the grader reply per (repo, arm). Today `SweepRow` keeps only counts (`discovery_sweep.py:161-190`; verified), so the E3 rows cannot be replayed.
- A sanitised snapshot goes into `tests/fixtures/discovery_eval/`, with a label per hypothesis keyed by the sha256 of the normalised title.
- The replay goes through `generate_hypotheses` on `ScriptedTransport`, then through the wired ranking and slice, and asserts hit@3 is at least the recorded baseline.
- An unknown key fails with "unlabelled: refresh in live-smoke".

**Live suites (CI `live-smoke` only, never from a container; each test capped; a suite's cap is the sum of its worst cases, asserted by a guard).**

| Suite | Measures | Cap |
| --- | --- | --- |
| L1 grader validation (10 hand labels, at least 3 near misses) | hit@k is "validated" only at ≥ 9/10 agreement and no near-miss false positive | 2 USD |
| L2 hard corpus v2 sweep, portfolio vs blind | hit@1 plus executed wins | 15 USD |
| L3 OSS blind, wired engine, Sonnet-low editor vs Opus | delivered above the noise vs aimed 6/10; gates D9 | 12 USD |
| L4 retry on a planted-typo corpus | first-pass vs retry delivery | 3 USD |
| L5 E7 rerun through the src modules | ≤ 0.35 USD a paper, injection PDFs quarantined | 6 USD |
| L6 3b network-on job | one real wheel fetched and vetted; a recorded slopsquat refused; host reachability (Q5) | 1 USD |
| L7 3c heal corpus | reproducer acceptance and fix rate (Q8) | 6 USD |

---

## 7. Work breakdown by wave

Each unit is at most about 400 lines, on disjoint files, tests first, with one correctness Reviewer. A security Reviewer is added at the units marked †.

**Wave 1: independent of the A/B (start now).**

| Unit | Files | Content |
| --- | --- | --- |
| U1 slug/UUID mapping † | `infrastructure/schema/005_step3_technique_slug.sql`, `persistence/postgres.py`, `tests/persistence/` | D10 |
| U2 retry detection † | `execution/procrun.py`, `execution/measure.py`, new `execution/retry.py` | `RunFailure.kind`, `CrashReport`, `classify`, D23 closure |
| U3 retry flow † | `execution/trial_runner.py`, `execution/git.py` (`parent=`), `execution/editor.py` (`feedback`), `protocols.py` | D11 flow, `Trial.attempts` |
| U4 sources and settings | new `optimization/sources.py`, `optimization/generate.py` (lessons, `avoid_titles`), `common/config.py` | D4, D5, D9 settings and their validators |
| U5 graph wiring | `orchestrator/nodes.py` (research, hypotheses, router), `state.py`, `serde.py`, `factory.py` | D3, D6, parking; per-role transports (generator, matcher, editor) |
| U6 offline discovery eval | `tests/live/discovery_grader.py`, `discovery_sweep.py` (recording), `tests/optimization/test_discovery_eval.py` | §6 |
| U7 protected-pattern gaps | `optimization/anticheat.py` | §3.8 list |

**Wave 2: still independent of the A/B.**

| Unit | Content |
| --- | --- |
| U8 ranking | Capped gains (`ranking.py`) and the diversity slice (new `optimization/portfolio.py`) |
| U9 lessons | D13 discount and the `source:` tags (`nodes.py` learn, `learning/lessons.py`) |
| U10 evolution | Compound and escalate (`optimization/evolution.py`, the trial runner's transport choice) |
| U11 grader labels | Grader labels plus the L1 suite |
| U12 hard corpus v2 and `ledgerclose` rebuild | Both hot spots become C-level compare loops; a ratio guard between 0.5 and 2. **Only after E5 finishes**, because E5's repos include `HARD_CORPUS`. |
| U13 check registry and profiler tags | `checks.json`, `Hotspot.tags` from the profiler (verified never set, so every lesson reads "general") |
| Docs | The CLAUDE.md build order (3b, 3c, 6), the extraction model line, STATUS decisions |

**Wave 3: the paper pipeline (order set by the A/B).** P1 moves the sources and snapshot feed. P2 adds the screen and moves extraction. P3 adds pass-2 cards and the registry use. P4 adds the card store and the review flow (`load_cards`, `pending/`). P5 adds the local weekly monitor on the user's machine.

**Wave 4: Step 3b** (own security review). B1 names and policy (pure). B2 the registry client and the allowlist proxy †. B3 lockfile resolve and diff, and wheel inspection †. B4 environments, `make_phase(env)` and the phase sweep †. B5 the acquire node, C1 and capture against C1 †. B6 combine re-resolve, dropping packages, delivery and migration 006. B7 the generator's `packages` field and card `packages`, with a strict-loader version bump.

**Wave 5: Step 3c** (own security review). H1 `HealCase`, the writer and the static checks †. H2 the heal shim and N/N same-reason confirmation †. H3 `HealJudge`, the equivalence exemption and `heal_tamper` †. H4 heal mode in the nodes, the baseline deselect, delivery and migration 007. H5 `BEHAVIOUR_DELIVERY` routing.

**The A/B switch.**

| | E5 `c - b >= 3` | E5 `c - b < 3` (or no result recorded) |
| --- | --- | --- |
| `PAPER_PRIORITY` / `PAPER_CARD_PRIOR` | `first_class` / 1.0 | `deprioritised` / 0.5 |
| Paper cards in the card pool | Yes, from P4 | Never loaded into a run |
| Wave order | 1 → 2 → **3 (P1-P5)** → 4 → 5 | 1 → 2 → 4 → 5 → 3 (P1-P4 as a manual tool; P5 moves to the Step 4 CLI) |
| `RESEARCH_SOURCES` default | `("blind", "matched", "paper")` | `("blind", "matched")`; matched stays, because the rule deprioritises papers, not the playbook |
| Effort moved instead | n/a | U10 evolution and U13 lessons are deepened first (card stats `card_outcomes` feeding the boost; demotion proposals for cards with 0 keeps in 5 or more trials) |
| Follow-up | Matcher model chosen on v2 data (Fable vs Sonnet) | Propose one pre-registered E5 re-run on hard corpus v2 (a ceiling effect is possible at 95-100 % hit@5); it needs the user's approval and does not reopen the first result |

---

## 8. Open questions

1. **Portfolio default (D5) is unmeasured.** Blind plus matched until L2/L3 report, or blind only?
2. **"Flagged" (D25).** Make `review_branch` the default once 3c lands, or keep the interrupt for behaviour changes? The code gates them; CLAUDE.md says flag.
3. **No lockfile.** Ask the user (recommended), or let the engine create L0 from the environment?
4. **Trial read confinement.** Is D23 enough until the Step 4 runner, or pull Landlock read rules into 3b, the first network-on step?
5. **Reachability and proxy shape.** Unverified that `pypi.org`, `files.pythonhosted.org` and `api.osv.dev` answer from runners and the container proxy; probe before L6. Proxy around `uv` in the host namespace, or `pasta`/`slirp4netns`?
6. **A paired/interleaved noise rule** could prove the 2-5 % OSS gains now under the floor, but it changes a frozen judge. Scope it for Step 5?
7. **Policy failures mid-run:** park and ask in the end report (recommended), or interrupt?
8. **Reproducer writer model:** unmeasured; Sonnet 5.5 medium is a guess. Let L7 decide?
9. **Caller candidate ids:** a non-UUID id such as `h1` also fails `save_lesson` (`lesson.hypothesis_id`, pinned at `tests/persistence/test_postgres.py:182-186`; verified). Map with uuid5 in U1, or require UUIDs?
10. **Novel lessons never match across runs** (uuid4 id, no technique). Match by normalised title within a project?
