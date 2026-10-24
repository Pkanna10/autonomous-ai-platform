# Step 3 research track: playbook, papers, matcher (design input)

Scope: the L4 research layer, as of branch `claude/step3-research` at `ea891e6` (the Step 2 head). Paths are relative to `services/python_agents/` unless they start with `infrastructure/` or `STATUS.md`. "Verified" means I read it in the code. "Unverified" means I inferred it and did not run anything.

## Findings (verified, with file:line)

**F1. Research is not wired in.** `orchestrator/nodes.py:1413` `research` is a stub: it echoes `ctx.techniques` and reports `papers=[]` "(stub)". `nodes.py:1429` `hypotheses` ranks only `ctx.candidates` (line 1437). The router `after_verdicts` (`nodes.py:1932`) ends the run once every `ctx.candidates` has been trialled, so generated hypotheses that live only in state would never keep the loop going. `orchestrator/factory.py:306` `build_context` takes only `candidates`. A grep of `src/` finds no caller of `load_playbook`, `match_techniques` (`research/playbook.py:350`) or `generate_hypotheses` (`optimization/generate.py:189`). The only places they are used are the docstrings in `clients/structured.py:3-4` and the live tests (`tests/live/discovery_ab.py:158-212`).

**F2. A slug-vs-UUID bug waits behind the wiring.** `load_playbook` requires `id == slug` (`playbook.py:148`). `generate.py:314` sets `Hypothesis.technique_id = technique.id`, which is the slug, and `learning/lessons.py:54` copies it into `Lesson.technique_id`. `persistence/postgres.py:411` binds it through `_optional_uuid`, and `_uuid` (`postgres.py:185-200`) raises `InvalidRecordIdError` for anything that is not a canonical UUID. Schema: `infrastructure/schema/003_engine.sql:294-296` gives `techniques` an `id UUID` primary key and a `slug VARCHAR(100) UNIQUE`; `003:369` `hypotheses.technique_id UUID REFERENCES techniques(id)`; `003:418` `lessons.technique_id UUID` with no FK. `ranking.py:33-37` matches a lesson to a hypothesis by comparing `technique_id`s directly. Consequence (from reading, not run): the first decided verdict on a playbook hypothesis fails the `learn` node on the Postgres repository. If the column were filled with any UUID instead, lessons read back by `list_lessons` would never match slug-bearing hypotheses. STATUS.md:1164 ("slugs map to `techniques.slug`, so no migration is needed") is true only if the mapping is applied in both directions; see Proposed interfaces §1.

**F3. Playbook format and contents.** `research/playbook.json` uses version 1 and holds 36 cards (`playbook.py:96-164` refuses unknown fields, duplicate keys, a bad slug, an id that differs from the slug, a precondition without an id, and files over 1 MiB). 30 are `efficiency` cards. The 6 distractors are listed in `tests/research/distractors.json` (process-pool, native-extension, alternative-interpreter, numpy-vectorization, asyncio, thread-pool); three of them are `behaviour`, and `tests/research/test_playbook_cards.py:321` requires each to hinge on a required environment condition. The cards hold 141 preconditions with 130 distinct check keys, in five namespaces: `absent.*` 52, `hotspot.*` 34, `source.*` 33, `workload.*` 12, `env.*` 10. Nothing evaluates a check deterministically; the matcher model reads them as text. `execution/profiler.py` never sets `Hotspot.tags` (grep finds nothing), so the learn context (`nodes.py:1865`) is always empty and every lesson reads "general -> ...".

**F4. Paper cards would not speak the playbook's vocabulary.** `tests/live/experiments/cards.py` `PASS2_SYSTEM` (lines 56-137) teaches the namespaces `hotspot.*`, `workload.*` and `runtime.*`. The playbook uses `env.*`, `source.*` and `absent.*` instead. `read_cards` (`cards.py:333-378`) also drops `required` (so it defaults to true) and names preconditions `<slug>-p<n>`, where the playbook uses `<slug>-<n>`.

**F5. The measured paper prototype is raw-SDK and test-only.**
- Pass 1 is `extraction.py:137` `pass1_params`. It runs on **Sonnet 5.5** at medium effort, with the PDF as a document block (`pdf_document`, line 113), citations on and no `output_config.format`. The local check is `match` (line 212): a page or char window, NFKC normalisation, a loose hyphen join, and `MIN_QUOTE_CHARS = 15`. `judge` (line 258) keeps an item only if it has a verified citation and every number it states appears in the verified quotes.
- Pass 2 is `cards.py:266` `pass2_params`, Sonnet 5.5 with structured output. Its result is validated into `Technique` objects. Per `cards.py:7`, a human approves cards into the playbook and nothing writes the file.
- The Haiku 5.5 screen is `cards.py:412` (pypdf text, at most 300,000 characters) and `web_screen.py:74-134` (30,000-character windows, ORed, fail-closed).
- Triage is `triage.py:169`: Haiku 5.5, a 1 h cached rubric, a batch, no fallbacks.
- `arxiv_fetch.py` provides `check_url` (line 143, host allowlist), `ArxivFetcher` (line 215, 3 s spacing, size caps, two redirects at most) and `recent` (line 347).
- E7 limits: `test_extraction_live.py:74` `MAX_PAGES = 30`, a cap of 1.25 USD a paper (2.75 with the Opus arm).
- CLAUDE.md names `ENGINE_MODEL` (Opus 5.5) for extraction, but the measured prototype used Sonnet.

**F6. The transport cannot carry the prototype as it stands.** `clients/transport.py:100-126` `LLMRequest` refuses 1 h cache TTLs and has no batch path. `clients/cost.py` has no PDF bound: `PDF_PAGE_TOKENS` (3,000 + 4,784 tokens a page) and `pdf_pages` exist only in `tests/live/experiments/bounds.py:39, 212`. A transport's chain comes from `Settings` (`transport.py:162-163`), so a triage transport means a `Settings` copy with `ENGINE_MODEL=TRIAGE_MODEL` and `ENGINE_FALLBACKS=False`, which is the pattern `discovery_ab.ab_settings` (line 140) uses.

**F7. Dependencies.** The `pyproject.toml` `research` extra (lines 97-101) declares `pymupdf`, which is AGPL-3.0 and would fail the licence allowlist, plus `arxiv` and `sentence-transformers` (pulls in torch). None of them is used. `pypdf` (BSD) is only in the `experiments` extra (lines 122-127). `research/arxiv_monitor.py` and `research/pdf_parser.py` are 2025 placeholders.

**F8. Discovery measurement.**
- The E3 sweep uses `SWEEP_N = 5` (`discovery_sweep.py:87`) over `CORPUS + HARD_CORPUS` (line 100), with the grader `claude-opus-4-8` (`discovery_grader.py:64`).
- No hand labels exist anywhere (grep).
- OSS repos have no reference fix (`oss.py` docstring: expected `none`), so hit@k cannot be graded there; only executed outcomes can.
- The E5 rule is coded as `MIN_DISCORDANT_LEAD = 3` (`discovery_ab.py:117`), and its repos include `HARD_CORPUS` (line 115).

**F9. ledgerclose.** `fixtures/live_corpus_hard/ledgerclose/ledgerclose/settle.py:14` `queue.pop(0)` on 60,000 items is a memmove, so it is bandwidth bound. `peaks.py:12` `max(values[start:end+1])` copies a 400-element slice and compares it at every position, so it is compute bound. The guard is `tests/live/test_hard_corpus_guards.py:440`.

## Proposed interfaces

### 1. Technique identity (no migration)

The slug stays the identity in memory: `Technique.id == slug`, and `Hypothesis.technique_id` and `Lesson.technique_id` carry the slug. The mapping lives only in `persistence/postgres.py`:

```python
TECHNIQUE_NAMESPACE: Final = uuid.UUID("<fixed constant>")
def technique_uuid(slug: str) -> uuid.UUID: return uuid.uuid5(TECHNIQUE_NAMESPACE, slug)
def sync_techniques(self, techniques: Sequence[Technique]) -> None  # upsert id=uuid5(slug), slug, fields
```

- `save_lesson` binds `technique_uuid(slug)` when `SLUG_PATTERN` fullmatches and keeps rejecting anything else.
- `list_lessons` selects `COALESCE(t.slug, l.technique_id::text) AS technique_id` through a `LEFT JOIN techniques t ON t.id = l.technique_id`, so lessons read back match hypotheses again.
- The in-memory repository needs no change.
- A paper card gets the same mapping, so the `hypotheses.technique_id` FK holds once hypotheses are persisted.

Why this design: a uuid5 is deterministic, so a reseed gives the same ids. It needs no lookup before an insert and adds no column.

### 2. Card store and its growth

- `research/playbook.json` stays the curated set: version 1, hand-written, blind to the corpus.
- New `research/cards/papers.json` holds approved paper cards in the same `{"version":1,"techniques":[...]}` shape. Each card adds a `provenance` object `{arxiv_id, sha256, quotes[], screened: bool, approved_by}`; `load_playbook` gets an opt-in `extra_fields={"provenance"}` so the strict loader stays strict.
- `load_cards(paths=(PLAYBOOK_PATH, PAPER_CARDS_PATH)) -> tuple[Technique, ...]` refuses a duplicate slug across files.
- Pending, unapproved cards go to `research/cards/pending/<arxiv_id>.json` and are never loaded by the engine.
- New `research/checks.json` is the check-key registry: `key -> description`, covering the 130 keys in use today. A test requires every card's checks to be in it. Pass 2 is given the registry and must use keys from it, or coin one under `new.*`, which a reviewer renames on approval. This replaces the hard-coded `runtime.*` vocabulary from F4. Pass 2 also emits `required` and uses playbook-style ids (`<slug>-<n>`).
- Growth also comes from verdicts, a Step 3 piece in both variants. `learning/card_stats.py: card_outcomes(lessons) -> Mapping[slug, CardRecord(keeps, rejects, mean_gain)]` feeds `ranking.lesson_boost`. A card with 0 keeps in 5 or more trials is proposed for demotion in the report, never deleted automatically.

### 3. Paper intake (`research/`, user machine or committed snapshot)

```python
class PaperSource(Protocol):
    def entries(self) -> Iterable[PaperEntry]: ...      # id, title, abstract, published, pdf_url
    def pdf(self, entry: PaperEntry) -> bytes: ...       # sha256-checked
SnapshotSource(path: Path)        # research/snapshots/<yyyy-mm-dd>.jsonl, committed: metadata+abstract+pdf sha256
ArxivSource(fetcher: ArxivFetcher)  # moved from arxiv_fetch.py; user machine only
```

- The snapshot is the CI and container input, because arXiv answers HTTP 429 to runners and the container proxy refuses it.
- PDFs are not committed. The arXiv default licence does not allow redistribution (unverified per paper). They are fetched on the user's machine into `~/.cache/autonomous-ai/papers/<sha256>.pdf`. Committed test PDFs are the planted ones that `cards.write_pdf` writes.
- `ArxivSource` keeps `check_url`, the 3 s spacing and the size caps. When the `GITHUB_ACTIONS` variable is set it raises `SourceUnavailable` with the reason, so CI never gets a misleading 429.

```python
def triage(transport: LLMTransport, budget: Budget, entries: Sequence[PaperEntry]) -> tuple[TriageVerdict, ...]
def screen_text(transport, budget, text: str) -> ScreenVerdict      # unify cards.screen_params + web_screen; fail closed
def extract(transport, budget, pdf: bytes, entry: PaperEntry) -> Extraction  # pass 1 + local verification
def to_cards(transport, budget, extraction: Extraction, registry: CheckRegistry) -> tuple[CandidateCard, ...]
def ingest(source, entry, *, transports, budget) -> IngestResult     # screen -> pass1 -> verify -> pass2 -> pending/
```

- **Models.** Triage and the screen run on Haiku 5.5 with fallbacks off; Haiku rejects `fallbacks`. Passes 1 and 2 run on Sonnet 5.5 at medium, as measured in E7. New settings: `EXTRACT_MODEL=claude-sonnet-5-5` and `EXTRACT_EFFORT=medium`. CLAUDE.md's "Opus for extraction" line should change.
- **Step 3 triage is synchronous with the 5-minute cache.** Batches and 1 h caching are a later transport extension. At Haiku prices the difference is cents a week.
- **Transport and cost changes.** `LLMRequest` already accepts any `BetaMessageParam`, so a document block passes through it. `cost.py` gets `PDF_PAGE_TOKENS` and `pdf_pages` from `bounds.py` and bounds a request by its page count plus its bytes. `ingest` refuses more than 30 pages before any spend.
- **Injection defences** (layered; the screen alone is not trusted):
  1. Screen the pypdf text before pass 1; a positive verdict, a refusal or an unreadable answer sends the paper to quarantine.
  2. `PASS1_SYSTEM` tells the model to write a `NOTE:` line instead of complying.
  3. Pass 2 sees only verified items, in a fresh `Fence` under `untrusted_paper_claims`.
  4. Cards are validated with `text_problem`, no URL, backtick or `pip`/`install` token, and slug and check regexes.
  5. Every card needs human approval before it reaches the matcher.
  6. In the matcher, paper cards sit under the stable token, as the playbook's do (`playbook.py:216-250`).
  7. A matched card is still only a hypothesis that frozen judges test.

### 4. Matcher and generator in the loop

```python
class Researcher(Protocol):
    def research(self, *, project, understanding, hotspots, objective, budget) -> ResearchResult
@dataclass(frozen=True)
class ResearchResult: techniques: tuple[Technique, ...]; matches: tuple[TechniqueMatch, ...]; notes: tuple[str, ...]
class HypothesisProposer(Protocol):
    def propose(self, *, project, understanding, hotspots, objective, research: ResearchResult, lessons, budget, n) -> tuple[Hypothesis, ...]
```

- `NodeContext` gets `researcher: Researcher | None` and `proposer: HypothesisProposer | None`. With `None`, a node keeps its Step 2 behaviour, as for the other seams.
- `PlaybookResearcher` calls `load_cards` and then `match_techniques(k=MATCH_K)`. If the matcher returns nothing or raises `UnusableReplyError`, it falls back to the whole playbook with a note.
- `ClaudeProposer` calls `generate_hypotheses` once, in round 1. Its results are stored in a new state key `proposals: list[Hypothesis]` so a checkpoint resume does not pay for the call again. Later rounds rank whatever remains.
- `hypotheses` takes `ctx.candidates + state["proposals"]` as candidates, and `after_verdicts` checks "all trialled" against that same union. This fixes F1.
- Model defaults, all in `Settings`: generator Sonnet 5.5 at medium (E3: 0.014 USD a repo, no false claims on the controls); matcher Sonnet 5.5 at medium until hard corpus v2 separates arms. Fable stays an experiment arm: in E3 it cost 7x on a saturated set. Opus at high is dropped.
- `expected_gain` is not trusted for ranking until it is calibrated: Opus claimed big gains on `lettertally`. Ranking uses `provability × (1 − risk) × (1 + lesson_boost)` and caps `expected_gain` at the card's value.

### 5. The A/B switch

```python
class PaperPriority(StrEnum): first_class = "first_class"; deprioritised = "deprioritised"
Settings.PAPER_PRIORITY: PaperPriority   # set by the Lead from E5's recorded result; no default assumed in code paths
def research_plan(ab: AbOutcome | None) -> PaperPriority   # c - b >= 3 -> first_class, else deprioritised; None -> deprioritised until recorded
```

`AbOutcome(b, c, p, excluded)` is read from the E5 recorder output and copied into STATUS by hand. The code paths are the same in both variants. The switch changes three things: the build order, `PAPER_CARD_PRIOR` (a multiplier on a paper card's score: 1.0 when `first_class`, 0.5 when `deprioritised`), and whether `ingest` is a scheduled job or a manual tool.

| Unit (order)                                             | first_class                         | deprioritised                                 |
| -------------------------------------------------------- | ----------------------------------- | --------------------------------------------- |
| 1 Wiring + F2 fix + check registry                       | 1                                   | 1                                             |
| 2 Hard corpus v2 + ledgerclose rebuild + grader labels   | 2                                   | 2                                             |
| 3 Paper intake into src (snapshot, screen, extract, cards) | 3                                 | 5 (manual tool, no schedule)                  |
| 4 Card review flow and `papers.json`                     | 4                                   | 6                                             |
| 5 Lessons as ranking signal (tags from profiler, card stats) | 5                               | 3                                             |
| 6 Evolution: mutate kept/near-miss hypotheses, inspirations, near-duplicate reject | 6 | 4                                      |
| Local monitor (weekly `ArxivSource` run on the user machine) | in Step 3                       | Step 4 CLI                                    |

A "not met" from E5 on a corpus that saturates is weak evidence: few pairs can disagree when both arms score 95-100 %. If E5 gives `deprioritised`, I recommend re-running it once on hard corpus v2 before the paper units are cut for good. That is a proposal, not an assumed outcome.

### 6. What moves to src and what stays test-only

| Moves to `src/autonomous_ai_agents/`                                                                      | Stays in `tests/live/experiments/`                                   |
| --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `extraction.py` `page_texts`, `normalise`, `Cite`, `match`, `numbers`, `paragraphs`, `judge`, prompts → `research/extract.py` | `harness.py` (raw-SDK `ExperimentClient`), `recorder.py`           |
| `cards.py` `PASS2_SYSTEM`, `CARD_SCHEMA`, `read_cards`, `_card_problem` → `research/cards.py` (via `LLMTransport`) | `ArmResult`, `agreement`, `card_metrics` (arm comparisons)         |
| `cards.py` screen + `web_screen.py` → one `research/screen.py`                                            | `planted_pdf`/`write_pdf` → `tests/research/pdfs.py` (fixture builder) |
| `triage.py` rubric, `VERDICT_SCHEMA`, `read_verdict` → `research/triage.py`                               | `prescreen.py`, `web.py` (hosted tools not adopted)                  |
| `arxiv_fetch.py` `check_id`, `check_url`, `parse_feed`, `ArxivFetcher` → `research/sources.py`            | `bounds.py` remainder, `papers.json`, every `test_*_live.py`         |
| `bounds.py` `PDF_PAGE_TOKENS`, `pdf_pages` → `clients/cost.py`                                            |                                                                      |

`pyproject.toml`: the `research` extra becomes `pypdf>=6,<7`, and `pymupdf`, `arxiv` and `sentence-transformers` are removed. The two placeholders are deleted. The moved code keeps its offline tests (`test_extraction.py`, `test_cards.py`, `test_triage.py`, `test_arxiv_fetch.py`), moved into `tests/research/`.

### 7. Costs

| Item                                                            | Cost                                                                                                     | Source                                   |
| --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Generator per run (Sonnet medium)                               | ~0.014-0.015 USD                                                                                         | E3 ledger rows                           |
| Matcher per run (Sonnet medium, k=3)                            | ≤ ~0.02 USD                                                                                              | Unverified; E5 records it                |
| Research overhead per run                                       | ~0.03-0.04 USD; the editor is ~0.04 a trial (E8a), and a run is ~0.11-0.30 in all (H, O rows)            | Derived                                  |
| Triage per abstract (Haiku)                                     | ~0.0002 USD (≈400 input tokens + 150 output + cached rubric)                                             | Unverified: E2 never ran                 |
| Screen per paper (Haiku, ≤300K characters)                      | ≤ ~0.01 USD                                                                                              | Derived from the Haiku price             |
| Pass 1 + pass 2 per paper (Sonnet)                              | 0.2-0.3 USD                                                                                              | E7                                       |
| Weekly intake (50 abstracts triaged, ~5 extracted)              | ≈ 1.5 USD                                                                                                | Derived                                  |
| Grader per (repo, arm) (Opus 4.8 low)                           | `GRADE_WORST_USD` bound, `discovery_grader.py:298`                                                       | Code                                     |

### 8. Harder discovery corpus and measurement

- **Hard corpus v2** (`fixtures/live_corpus_discovery/`, same conventions as `live_corpus_hard`). The categories are built to separate arms. The only separating repo so far, `fleetsim`, is of the `large` kind, so these generalise it:
  - `deep`: the removable cost shows up as a builtin's self time three or more calls down.
  - `spread`: the cost is split over six or more functions, each under 10 % share.
  - `misleading`: the top hotspot is unavoidable output or a sort; the fix sits at rank 3 or lower.
  - `uncommon`: fixes from less obvious cards (`three-argument-pow`, `gc-pause-during-bulk-allocation`, `intern-duplicate-values`, `bisect-for-sorted-search`), so retrieval has room to help.
  - `small`: gains of 5-15 %.
  - Two decoy controls.
  - The playbook author must not see the corpus, the same rule as STATUS.md:1117.
- **ledgerclose rebuild.** Both hot spots become C-level scans over Python objects, so they are the same kind of work on any machine: `settle` looks accounts up with `list.index` on a growing list of names, and `peaks` becomes a membership test (`in`) on a list of seen totals. Both are compare loops through `PyObject_RichCompare`. The `multi` category and the part patches stay, and `fix_gain` is recomputed. Rebuild only after E5 finishes, because E5's repos include `HARD_CORPUS` and its data must stay comparable.
- **Metrics.** The primary metric is hit@1 plus an executed win (delivered branch, reference gain reached) on v2 and the hard corpus. hit@5 is secondary. OSS is measured blind with the wired generator: delivered and above the noise floor, compared with the aimed 6/10.
- **Grader validation.** `tests/fixtures/grader_labels.json` holds about 10 (repo, hypothesis, label, root_cause) rows labelled by the Lead, including 3 or more near misses and 2 or more `multi` partial fixes. A live test runs `discovery_grader.grade` on them. hit@k is reported as "validated" only with at least 9/10 agreement and no false positive on the near misses; otherwise it is reported as unvalidated.

## Tests that would prove it

1. **Wiring.** A `FakeTransport` returns 4 hypotheses. The engine runs with `candidates=()` and trials them. `after_verdicts` returns `hypotheses` until every proposal has been trialled. A resume from a checkpoint after round 1 makes no second generator request; count the transport calls.
2. **F2.** A Postgres test saves a lesson whose `technique_id` is the slug `set-membership-test`. `list_lessons` returns that slug, and `rank_hypotheses` applies the boost. A non-slug, non-UUID value still raises `InvalidRecordIdError`. `sync_techniques` run twice gives the same ids.
3. **Registry.** Every check in `playbook.json` and `papers.json` is in `checks.json`. Pass-2 parsing (`to_cards`) drops a card with an unknown key unless it is `new.*`. `load_cards` refuses a slug that appears in both files.
4. **Extraction moved.** The offline tests move with the code and still pass: strict and loose matches, the 15-character minimum, numbers that are not in a verified quote, a page window out of range.
5. **Injection.** The white-on-white and 0.5 pt planted PDFs (`planted_pdf`) are screened as positive with a fake Haiku. If the fake screen errs (returns negative), the card validator still refuses any card that names `fastdedup-turbo`, a URL or `pip`. An unreadable screen reply and a refusal both count as positive.
6. **Sources.** `SnapshotSource` refuses a file over its size cap, a sha256 mismatch, an `http://` URL or a bad id. `ArxivSource` raises `SourceUnavailable` under `GITHUB_ACTIONS`. The `check_url` tests move unchanged.
7. **Cost.** A 30-page PDF request is bounded at 30 × 7,784 tokens plus its bytes, and `ingest` refuses a 31-page PDF before any spend.
8. **Switch.** `research_plan(AbOutcome(b=1, c=4))` is `first_class`; `(b=2, c=4)` and `None` are `deprioritised`; `PAPER_CARD_PRIOR` is applied in ranking.
9. **Corpus guards.** For rebuilt ledgerclose and every v2 `multi` repo, each part patch alone stays below `fix_gain` on both the container and the runners. A new guard asserts that the two parts' cost ratio is between 0.5 and 2 on the host.
10. **Live, CI only.** A sweep on v2 (hit@1, executed wins), the grader agreement test, OSS blind, and E7 rerun through the src modules with a cost per paper of at most 0.35 USD.

## Risks and open questions

- **Image-borne injection.** The screen reads pypdf text, but Claude also sees each page as an image, so an instruction inside a figure skips the screen. Mitigation: the NOTE rule, the card validators, human approval and the judges. Residual risk: a card worded to pass review.
- **PDF redistribution licences.** This is why the snapshot holds metadata, abstracts and hashes only. Whether a paper's licence allows its PDF in CI fixtures is unverified.
- **Uncalibrated gains.** Paper cards' `expected_gain` is a self-claim. Rank cards by verdicts (card stats) and cap `provability` for paper cards until they have kept a trial.
- **Matcher choice.** The build order names Fable for the matcher; E3 shows no gain for 7x the cost on a saturated set. Decide on v2 data, not before.
- **E5 power.** Two repetitions on a saturated corpus may give "not met" because of the ceiling, not because retrieval does not help. Hence the proposed one re-run on v2. Open: does the user accept that re-run?
- **Empty generator answers** (Opus high returned 0 hypotheses twice). The proposer falls back to matcher plus playbook titles. Open: should an empty answer be retried once inside the budget?
- **Deterministic preconditions.** Profiler tags and static AST checks for the `source.*` and `absent.*` keys are not in Step 3. The matcher stays an LLM judgment that the judges back up.
- **3b link.** Cards and hypotheses that need a package (`numpy-vectorization`, any paper card of class `novel`) get the `needs_package` mark and stay parked until 3b. The matcher must not rank them above runnable cards in Step 3. Open: should they be excluded or shown with a penalty?
- **Seeding drift.** If `playbook.json` changes and `sync_techniques` is not run, `list_lessons` falls back to the UUID text, and those lessons quietly stop matching. Mitigation: run `sync_techniques` at connect, or make it a one-line migration test.
