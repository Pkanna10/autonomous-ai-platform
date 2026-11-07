export const meta = {
  name: 'emergence-round-2-tail',
  description: 'Emergence round 2, phases 3-6 (phases 0-2 ran as parallel agents on the round-2 board): synthesis, 3-lens judging, build top 2 offline, review, fix, a two-part verification that runs to completion',
  phases: [
    { title: 'Synthesis', detail: 'at most 5 merged proposals, ranked', model: 'sonnet' },
    { title: 'Judging', detail: 'three refuting judges: evidence, correctness risk, reward hacking' },
    { title: 'Build', detail: 'top 2 survivors, tests first, offline' },
    { title: 'Review', detail: 'read-only reviewers on a different model', model: 'fable' },
    { title: 'Fix', detail: 'builders apply blocker and should_fix findings' },
    { title: 'Verify', detail: 'two verifiers: the units, then the measures and plans; each runs to completion', model: 'fable' },
  ],
}

// Paths: edit these two for a fresh session (gen_briefs.py takes the same two as EMERGENCE_W and EMERGENCE_SCRATCH).
const S = '/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad'  // scratch space for coverage and verifier output
const W = '/home/user/step3-emergence-r1'
const BOARD = W + '/.claude/handoff/step3/idea-lab/emergence/round-2/board.md'
const POST = W + '/.claude/handoff/step3/idea-lab/emergence/round-2/post.sh'
const RULES = W + '/.claude/handoff/step3/idea-lab/emergence/round-2/builder-rules.md'
const H = W + '/.claude/handoff/step3'

const FIXED = `FIXED, no agent may touch or propose changing: the frozen judges, anticheat, protected-path rules, benchmarks, test files of the libraries under test, the sealed sets, O28 (defensive source analysis only; no live or third-party systems, no exploits, the human owns disclosure). A proposal that needs any of these changed must say so plainly and stop: it is reported, not built.`
const SAFETY = `No live API spend: never dispatch a CI workflow, never run pytest with -m live or any test that sends a request, never call the Anthropic API. Do not commit, push, stage or create branches (the Lead is the only writer to the branch). Work in ${W} (branch claude/step3-emergence-r1).`
const BOARDRULE = `The board is ${BOARD}. Communicate only through it: read the WHOLE board at each sync point (now, at the start of your task) and do not rely on any other channel; you may read the repository read-only to ground your claims. Post each message as ONE entry with exactly: bash ${POST} "<agent name>" "<role>" <<'MSG'\\n<message>\\nMSG . Never edit the board any other way. Keep each entry self-contained and concrete; numbers only with their sources.`

const CHARTER = `THE CHARTER (O54; read it in full at ${H}/idea-lab/emergence/charter.md). Level 1, the core engine: a multi-agent, multi-framework ideation-and-realisation engine; lanes on different models with different evidence and thinking frameworks with forcing outputs propose improvements to a codebase, and the realisation path implements, judges, compounds and ships them under frozen judges; the goal is state-of-the-art improvement ideas by design, shipped with proven, substantial gains, claimed only at a sealed rung (K2 unseen problems, K3 held-out OSS, K4 V9, K5 SWE-Perf/GSO/SWE-fficiency), never from the development set. Level 2, this emergence round: a society of agents applies the same diverse thinking to the ENGINE ITSELF and builds what survives. A round produces ENGINE CHANGES, not ideas for libraries; the libraries are evidence. Chain: round N -> engine change units (tests first, different-model review, gate, one commit each) -> an engine run on the development set read against the A/A twin -> round N+1's facts card. Engine measures every round, all read against the twin's band: share of ideas with a named cost model; share of the physical gap closed by kept ideas; wins per run and their size vs the floor; the compounding curve over rounds; idea -> working-diff hit rate; cost per win; marker misses (kept ideas the marker ranked out of its top 3); the twin gap on combine per library (path dependence, board entry [37]).`
const BAND = `The band (O51 as amended, entry [36]): per library, a combine or kept-count difference is read against THAT library's own twin gap where a twin exists (pyparsing 2.7 points / 0 kept, tomli 4.0 / 0, sortedcontainers 3.2 / 0, sqlparse 18.7 / 2); libraries without a twin use about 4 points; the arm-level call is O52's (a sign count on kept, the mean combine difference above the twin's mean gap).`
const LEADNOTES = `Round 2 context (hold proposals to it): (1) CI judges trials on Python 3.11; a local timing must name its interpreter. (2) The live ideas-x2 suite runs under 360 minutes (ci.yml:693). (3) Rulings r1[47], r1[62] and r1[72] (observation of the unchanged benchmark is not a FIXED touch; O28 routing to a security_candidate row flag) still hold. (4) Round 1 built S1 (IDEAS_COUNT_CONTRACT=record: unit counts, a realisation record and label per trial) and S2 (SITE_STACKS=record, staying at record by O58); E1/E2 (X2-S) passed every record bar and failed the arm's no-harm bar, three of four failures being fewer keeps before the combine (round-1.md section 12). (5) Live plans (O58): 21.08 USD for the whole round, a run's cap need 9.35 USD, a dispatch only when the balance covers its need, so at most 2 runs a dispatch and about 3 runs in the round; several runs on fewer libraries; each library against its own twin gap; nothing dispatched without the owner. (6) From round 2 a record-only live pass earns +5 and a gain-bearing one +10 (O58): say which each proposal is.`
const SUPERSEDED = `Round 1's board and report are read-only reference, cited as r1[n]; this round's board is the round-2 board.`
const NOFAST = `Self-rejection rule: before posting, reject any proposal that could be satisfied by a local fast path, caching or hoisting (memoise, bind locals, skip a check, a precomputed table on the same algorithm). Your output shape exists to make such proposals impossible; list in one line at the end of each entry what you rejected this way, or "none".`
const COMMON = `Every proposal targets the ENGINE (what lanes see, what they must produce, how ideas are selected, realised, compounded or judged; shadow judges and the marker may be proposed on, frozen judges may not) and carries these headed parts, so it can be synthesised and judged: Mechanism; Engine files it changes (by repo path); Expected effect and its size, on which charter measure; Pre-registered measure and bar, naming the twin's band it is read against (${BAND}); Cost per run (USD, from the facts card's measured rates); Strongest reason it fails; Fixed items touched (none, or which, in which case say it stops here).`
const FIX = 'tests/fixtures'
const PY = 'services/python_agents'
const STANCES = [
  { name: 'Bounds first', tag: 'BND', model: undefined,
    pack: `the X1 profiles: ${PY}/${FIX}/ideas_probe/facts.jsonl (hotspots, their shares and workloads) and views.jsonl (the recorded function spans and views), the X1 report's ceiling table (${H}/idea-lab/x1/tables.md section 3), the X1 shares, and Amdahl.`,
    shape: `For 3 hot paths (name them, with their measured shares): the physical floor, what an ideal implementation must still do (bytes touched, allocations, C-level calls, each estimated with its basis); the gap between today's measured time and that floor; then the engine change that makes every lane compute this gap before proposing. Ideas are scored by the share of the gap they close, not by percent.` },
  { name: 'Expert prior', tag: 'EXP', model: 'fable',
    pack: `the development corpus's reference fixes (${PY}/${FIX}/live_corpus_discovery/_solutions/*.patch and the corpus manifest), V9's manifest METADATA ONLY (${PY}/${FIX}/upstream_corpus/manifest.json: touched functions and hint_in_before; NEVER read ${PY}/${FIX}/upstream_corpus/_keys or _notes: V9 stays sealed by O53, as O19's held-out exam and the charter's K4 rung, and reading them breaks FIXED; this substitute pack is the owner-approved one), the kept ideas of X1's slice, the picks run and X2 (${H}/idea-lab/x1/ideas-slice-*.jsonl, ideas-picks-42096064178.jsonl, ${H}/idea-lab/x2/*.jsonl), and your own knowledge of public, pre-cutoff upstream performance fixes.`,
    shape: `A taxonomy of the mechanisms experts actually used (each family with examples and the cost model it attacks); which families no X1 lane ever proposed (check the X1 idea lists in ${H}/idea-lab/x1/*-X1-*.md); then the engine change that makes lanes search those families on purpose.` },
  { name: 'Inversion', tag: 'INV', model: undefined,
    pack: `the X1 idea lists (${H}/idea-lab/x1/<library>-<configuration>.md) and the slice verdicts (${H}/idea-lab/x1/ideas-slice-*.jsonl, ideas-picks-42096064178.jsonl).`,
    shape: `For each library you take on: how you would make it slower without changing output (each such move is a hidden cost the code already pays); then the reverse of each as an idea; then the engine change that asks the question this way.` },
  { name: 'Contradiction', tag: 'TRZ', model: 'fable',
    pack: `the X1-4 proposals path (the ideas-proposal rows in ${H}/idea-lab/x1/ideas-probe-x1-run*.jsonl and the report's 'X1-4 proposals by rule relaxed') and the rejects (verdict reject in the slice, picks and X2 rows).`,
    shape: `For each wanted relaxation: the contradiction it hides (speed vs output order, memory vs time, generality vs the input shape); then a way to get the gain while keeping the rule (specialise-then-verify, as the tomli leap did), as an engine lane.` },
  { name: 'Analogy transfer', tag: 'ANA', model: undefined,
    pack: `the hot functions and their roles (parsing, grouping, windowing, lookup) from ${PY}/${FIX}/ideas_probe/facts.jsonl and views.jsonl, and your own knowledge of how the fastest known implementations of those roles work (json's scanstring, re's lazy DFA, van Herk, radix structures).`,
    shape: `The cross-domain prior lanes should carry (known structures from the fastest implementations of these roles), and the cost model that says when it wins; then the engine change that gives lanes this prior.` },
  { name: 'Shape specialisation', tag: 'SHP', model: undefined,
    pack: `the recorded input shapes (the input_shape and schema views in ${PY}/${FIX}/ideas_probe/views.jsonl) and the workloads (each library's benchmark as the OSS harness runs it: ${PY}/tests/live/oss.py and the corpus it names; read-only).`,
    shape: `Where the real input is far from the general case the code handles: approximate-then-verify paths for the real shape, what the scaling judge (G6b, shadow) would show if real (a slope change or not), and the engine change that makes lanes find such paths.` },
  { name: 'Ten-x', tag: 'TNX', model: undefined,
    pack: `the biggest wins so far and why they were big: sqlparse (+14.6 % the slice's leap; combines +39.8 % X2-0, +21.1 % its twin, +26.5 % X2-V), tomli (+22.6 % X2-0's combine), mistune (+25.1 % X2-V's combine), in ${H}/idea-lab/x1/ideas-slice-*.jsonl and ${H}/idea-lab/x2/*.jsonl, with the X1 by-lane wins and the path-dependence entry [37].`,
    shape: `Per library: the one order-of-magnitude change on the workload, even if it needs several judged steps, decomposed into trialable steps each judged by the frozen judges; and what the engine lacks to find and compound such chains.` },
  { name: 'Pre-mortem', tag: 'PRM', model: 'fable',
    pack: `every reject and inconclusive in the slice, the picks run and X2 (${H}/idea-lab/x1/ideas-slice-*.jsonl, ideas-picks-42096064178.jsonl, ${H}/idea-lab/x2/*.jsonl), S13 included (calls -7.7 %, time +5.8 %), and the editor's failures (trial rows whose edit did not apply, did not build, failed the tests or was rejected by anticheat; the editor and retry code in src/autonomous_ai_agents/optimization/ and execution/).`,
    shape: `The ways the next best idea fails at trial (wrong cost model, output changed, slower in C-level terms, the editor cannot realise it); the engine check that catches each before a trial is spent; and which past wins it would wrongly have caught.` },
]

const PROPOSALS = { type: 'object', properties: { ids: { type: 'array', items: { type: 'string' } }, posted_entries: { type: 'array', items: { type: 'integer' } } }, required: ['ids', 'posted_entries'] }
const CRITIQUES = { type: 'object', properties: { critiqued: { type: 'array', items: { type: 'string' } }, posted_entries: { type: 'array', items: { type: 'integer' } } }, required: ['critiqued', 'posted_entries'] }
const REVISION = { type: 'object', properties: { kept: { type: 'array', items: { type: 'string' } }, revised: { type: 'array', items: { type: 'string' } }, withdrawn: { type: 'array', items: { type: 'string' } }, merged_into: { type: 'array', items: { type: 'string' } }, posted_entries: { type: 'array', items: { type: 'integer' } } }, required: ['kept', 'revised', 'withdrawn', 'posted_entries'] }
const SYNTH = {
  type: 'object',
  properties: {
    proposals: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' }, title: { type: 'string' }, merges: { type: 'array', items: { type: 'string' } },
      mechanism: { type: 'string' }, files: { type: 'array', items: { type: 'string' } },
      expected_effect: { type: 'string' }, measure: { type: 'string' }, bar: { type: 'string' }, aa_band: { type: 'string' },
      cost_per_run_usd: { type: 'string' }, needs_live_to_judge: { type: 'boolean' }, dispatch_plan: { type: 'string' },
      touches_fixed: { type: 'boolean' }, fixed_note: { type: 'string' }, grounding: { type: 'string' },
      score_effect: { type: 'number' }, score_grounding: { type: 'number' }, score_testability: { type: 'number' }, score_cost: { type: 'number' }, rank_score: { type: 'number' },
    }, required: ['id', 'title', 'merges', 'mechanism', 'files', 'expected_effect', 'measure', 'bar', 'aa_band', 'cost_per_run_usd', 'needs_live_to_judge', 'touches_fixed', 'grounding', 'rank_score'] } },
    dropped: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, why: { type: 'string' } }, required: ['id', 'why'] } },
    repetition_note: { type: 'string' },
    posted_entries: { type: 'array', items: { type: 'integer' } },
  },
  required: ['proposals', 'dropped', 'repetition_note', 'posted_entries'],
}
const VERDICTS = { type: 'object', properties: { verdicts: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, refuted: { type: 'boolean' }, score: { type: 'number' }, reason: { type: 'string' }, would_have_saved: { type: 'string' } }, required: ['id', 'refuted', 'score', 'reason', 'would_have_saved'] } }, posted_entries: { type: 'array', items: { type: 'integer' } } }, required: ['verdicts', 'posted_entries'] }
const FINDINGS = { type: 'object', properties: { verdict: { type: 'string', enum: ['clean', 'findings'] }, findings: { type: 'array', items: { type: 'object', properties: { severity: { type: 'string', enum: ['blocker', 'should_fix', 'nit'] }, file: { type: 'string' }, problem: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['severity', 'file', 'problem', 'evidence', 'fix'] } } }, required: ['verdict', 'findings'] }

// ---------------- Phase 3: synthesis
phase('Synthesis')
const synth = await agent(`You are the Synthesiser (role: synthesis) of emergence round 2, on a model none of the proposers used. ${CHARTER} ${LEADNOTES} ${SAFETY} ${FIXED} ${BOARDRULE}
Sync point: read the whole board. ${SUPERSEDED} Only engine changes count (a proposal that is an idea for a library, not a change to the engine, is dropped). Merge the surviving proposals (KEPT, REVISED or merge targets; never WITHDRAWN ones) into AT MOST 5, deduplicated by mechanism (two proposals with the same mechanism are one, whatever their stances). For each: the merged ids; mechanism; files changed (repo paths); expected effect and size; the pre-registered measure and bar with the twin's band named (${BAND}); which charter measure it moves; whether it is record-only or gain-bearing (O58); a live plan that obeys the round's rule (21.08 USD, about 3 runs, several runs on fewer libraries) or none; cost per run; whether judging it needs a live run (and if so a dispatch plan: suite, libraries, cap, bar, band); whether it touches a FIXED item (then it is reported, not built); grounding in the facts card (cite the numbers); and scores 0-10 for expected effect, grounding, testability and cost (10 = cheap), rank_score = effect x grounding x testability / (11 - cost). Rank by rank_score. List every proposal you dropped and why. If the board shows agents repeating each other, say so plainly in repetition_note rather than padding. Post the synthesis as ONE board entry (agent "Synthesiser", role "synthesis") with ids S1..S5 and the ranking, then return it in the schema.`, { label: 'synthesise', phase: 'Synthesis', schema: SYNTH, model: 'sonnet' })
const cands = (synth && synth.proposals) || []
log(`synthesised: ${cands.map(c => `${c.id} ${c.title} (${c.rank_score})`).join(' | ')}`)

// ---------------- Phase 4: adversarial judging
phase('Judging')
const LENSES = [
  { name: 'evidence', model: undefined, ask: `Is each proposal's expected effect supported by the facts card's numbers, or extrapolated from one library, one run or a quantity inside the A/A band? Refute any whose claim the evidence does not carry.` },
  { name: 'correctness risk', model: 'fable', ask: `Could each proposal, built as described, break correctness (output equivalence, the combine, the engine's budget and cost caps, reproducibility, the existing tests) or silently change what an existing measure means? Refute any whose risk is not contained by a pre-registered test.` },
  { name: 'reward hacking', model: undefined, ask: `Could each proposal raise the measured numbers without a real gain: gaming the benchmark, the noise floor, the marker, the judges' thresholds, the twin band, selection on noise, more trials counted as more wins, a path-dependent single run read as a gain (the twin's per-library band, ${BAND})? Does it touch a FIXED item directly or indirectly? Refute any that could.` },
]
const judged = await parallel(LENSES.map(L => () => agent(`You are the ${L.name} Judge (role: judge) of emergence round 2, on a model the synthesiser did not use. ${CHARTER} ${LEADNOTES} Try to REFUTE every synthesised proposal; default to refuted if the case is not made. ${SAFETY} ${FIXED} ${BOARDRULE}
Sync point: read the whole board, the facts card and the Synthesiser's entry above all. Your lens: ${L.ask}
The proposals: ${JSON.stringify(cands.map(c => ({ id: c.id, title: c.title, mechanism: c.mechanism, files: c.files, expected_effect: c.expected_effect, measure: c.measure, bar: c.bar, aa_band: c.aa_band, needs_live_to_judge: c.needs_live_to_judge, touches_fixed: c.touches_fixed })))}
For each id: refuted (true/false), a score 0-10 (how well it survives your lens), the reason with evidence, and (O55's mentoring, for a refuted id; 'n/a' otherwise) would_have_saved: the evidence that would have saved it under your lens, concretely (which measure, fixture or run, and its result). The Lead copies these notes into each seat's library file. Post ONE board entry (agent "${L.name} Judge", role "judge") with every verdict, then return them.`, { label: `judge:${L.name}`, phase: 'Judging', schema: VERDICTS, model: L.model })))
const tally = cands.map(c => {
  const vs = judged.filter(Boolean).map(j => (j.verdicts || []).find(v => v.id === c.id)).filter(Boolean)
  const survives = vs.filter(v => !v.refuted).length >= 2
  return { ...c, votes: vs, survives, judge_score: vs.reduce((a, v) => a + (v.score || 0), 0) }
})
const survivors = tally.filter(c => c.survives && !c.touches_fixed).sort((a, b) => (b.rank_score - a.rank_score) || (b.judge_score - a.judge_score))
log(`survivors: ${survivors.map(s => s.id).join(', ') || 'none'}; refuted: ${tally.filter(c => !c.survives).map(c => c.id).join(', ') || 'none'}`)

// ---------------- Phase 5: build the top 2 survivors
const top = survivors.slice(0, 2)
const overlap = top.length === 2 && top[0].files.some(f => top[1].files.includes(f))
if (overlap) log(`top 2 share files (${top[0].files.filter(f => top[1].files.includes(f)).join(', ')}): built one after the other`)
const brief = c => `Emergence round 2 build unit ${c.id} (an ENGINE change under the charter, ${H}/idea-lab/emergence/charter.md): "${c.title}". Mechanism: ${c.mechanism}. Files: ${c.files.join(', ')}. Expected effect: ${c.expected_effect}. Pre-registered measure and bar: ${c.measure}; bar: ${c.bar}; A/A band: ${c.aa_band}. Cost per run: ${c.cost_per_run_usd}. Needs a live run to judge: ${c.needs_live_to_judge}${c.dispatch_plan ? ' (plan: ' + c.dispatch_plan + ')' : ''}. The judges' verdicts: ${JSON.stringify(c.votes)}. Read the whole board ${BOARD} first (the facts card, the proposals ${c.merges.join(', ')}, their critiques and revisions, the synthesis and the judges). ${FIXED} ${SAFETY} Build it test-first in ${W}: red before green, every existing test and golden unchanged unless the unit's purpose changes it (say which and why), new behaviour behind a setting that is off by default so the default path stays byte-identical, 100 % coverage of what you add, the gate (ruff, ruff format, mypy src tests with a private cache dir, pytest chunks with --cov-append including the timed pass -m "timed and not live" -n 0) green in the foreground. A ci.yml change is the Lead's: write it as an exact patch made with git diff --full-index under ${S}/V-lead/ci-E1-${c.id}.patch. Write its dispatch plan into your report (suite, libraries, cap with its need derived from measured rates, the pre-registered bar, the twin's band per library from ${BAND}, and which charter measure it moves) and stop there: never dispatch. Stop at about 400 source lines and report why if you would pass it. Another Builder may work in the same worktree on other files: never touch them. When done, post a short build note to the board (agent "Builder ${c.id}", role "builder"): files, tests, red and green commands, gate lines.`
const results = []
const runUnit = async (c) => {
  const report = await agent(`Read ${RULES} first and follow it exactly. ${brief(c)} Finish with the report the rules require.`, { label: `build:${c.id}`, phase: 'Build' })
  const review = await agent(`You are a fresh-context Reviewer (read-only: do not edit, format, stage or run anything that writes to the worktree; you may run read-only commands and offline tests with COVERAGE_FILE=${S}/cov.em-review-${c.id} and -p no:cacheprovider; never -m live, never a request). Review emergence unit ${c.id} as built in ${W} (uncommitted; another unit's files may also be changed: review only this unit's). The unit: ${brief(c)}
The Builder's report: ${report}
Lenses: correctness against the unit and the board's pre-registered test; that no FIXED item is touched; that the default path is byte-identical; tests that would fail without the feature (no weakened or tautological test; red evidence present); spend safety (no request offline, nothing dispatched); the builder rules in ${RULES}. Post a short review note to the board (agent "Reviewer ${c.id}", role "reviewer"), then report only real findings with evidence and a concrete fix.`, { label: `review:${c.id}`, phase: 'Review', schema: FINDINGS, model: 'fable' })
  const must = ((review && review.findings) || []).filter(f => f.severity !== 'nit')
  const fix = must.length ? await agent(`Read ${RULES} first and follow it exactly. You are the Builder of emergence unit ${c.id} (${brief(c)}). A Reviewer found these issues; fix every blocker and should_fix test-first in your own files (or explain precisely why a finding is wrong), re-run the gate, and finish with the rules' full report for the whole unit: ${JSON.stringify(must)}
Your earlier report: ${report}`, { label: `fix:${c.id}`, phase: 'Fix' }) : null
  return { id: c.id, title: c.title, report, review, fix }
}
phase('Build')
if (overlap) { for (const c of top) results.push(await runUnit(c)) }
else { results.push(...(await parallel(top.map(c => () => runUnit(c)))).filter(Boolean)) }

// ---------------- Phase 6: verification
phase('Verify')
const RUNTOEND = `Run every command in the FOREGROUND and wait for it (use a long timeout; never run anything in the background, never use a monitor, never end your turn while a command you started is still running). Split long pytest runs into chunks with --cov-append so each fits the tool's time limit. Your final message is the finished result, never a progress note: the Lead will not complete your work.`
const verifyUnits = await agent(`You are Verifier A (role: verification) of emergence round 2, on a model the builders did not use: the UNITS. ${CHARTER} ${SAFETY} ${FIXED} ${BOARDRULE} ${RUNTOEND}
Sync point: read the whole round-2 board. For each built unit (${results.map(r => r.id).join(', ') || 'none was built'}): run its own tests and the guards it touches (pytest -m "not live", private COVERAGE_FILE=${S}/cov.em2-verifyA, -p no:cacheprovider), reproduce its pre-registered offline bar, check FIXED is untouched (git status on the judges, anticheat, benchmarks, the libraries' tests and sealed sets) and that the default path sends the same requests. State, with commands and output lines: what is proven offline, what is not, and what needs a live run (with the plan's cap and bar under the round's rule). Post ONE board entry (agent "Verifier A", role "verification") and return the same text.`, { label: 'verify:units', phase: 'Verify', model: 'fable' })
const verifyMeasures = await agent(`You are Verifier B (role: verification) of emergence round 2, on a model the builders did not use: the MEASURES and PLANS. ${CHARTER} ${SAFETY} ${FIXED} ${BOARDRULE} ${RUNTOEND}
Sync point: read the whole round-2 board, Verifier A's entry included. (1) Run the offline reports on the archives (python -m live.ideas_x2_report on ${W}/.claude/handoff/step3/idea-lab/x2/ideas-x2-d1..d8-*.jsonl and the emergence E1/E2 files under ${W}/.claude/handoff/step3/idea-lab/emergence/round-1/live/, output to ${S}/emergence/verify2/ only) and compute the charter's engine measures as they stand, each with its number, command and source, or 'not measurable offline: <what is missing>'. (2) Check every synthesised proposal's live plan against the round's rule (21.08 USD, need 9.35 a run, a dispatch only when the balance covers its need, several runs on fewer libraries) and say which fit. Post ONE board entry (agent "Verifier B", role "verification") and return the same text.`, { label: 'verify:measures', phase: 'Verify', model: 'fable' })
const verify = { units: verifyUnits, measures: verifyMeasures }

return { synth, judged, tally: tally.map(t => ({ id: t.id, title: t.title, survives: t.survives, touches_fixed: t.touches_fixed, rank_score: t.rank_score, judge_score: t.judge_score, votes: t.votes })), built: results, verify }
