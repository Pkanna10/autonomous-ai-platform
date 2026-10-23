export const meta = {
  name: 'step2-build-wave',
  description: 'Build one wave of Step 2 units: Builder (tests first) -> Reviewer(s) on a different model -> fixer, per unit, on disjoint files',
  phases: [
    { title: 'Build', detail: 'one Builder per unit, tests first, own files only' },
    { title: 'Review', detail: 'read-only Reviewer on a different model (+ security reviewer where flagged)' },
    { title: 'Fix', detail: 'apply blocker and should-fix findings test-first' },
  ],
}

const REPO = '/home/user/autonomous-ai-platform'
const SVC = REPO + '/services/python_agents'
const STEP2 = '/home/user/autonomous-ai-platform/.claude/handoff/step2'
const SPEC = STEP2 + '/spec.md'

const COMMON_RULES = `
CONTEXT: You are on the Step 2 engineering team of ${REPO}. The approved Step 2 spec is ${SPEC} (read sections 0 Decisions, 3 Interfaces, 4 Behaviour, 5 Security, 6 Test plan and 7 Work breakdown, plus anything your unit touches). Verified research facts are in ${STEP2}/research-*.md (read the track relevant to your unit before designing). The service is ${SVC}: Python package autonomous_ai_agents (src layout), uv venv at ${SVC}/.venv, pydantic v2 frozen models (extra="forbid"), mypy strict on src AND tests (config in pyproject.toml; always run mypy from ${SVC}), ruff, pytest with xdist and a 90% coverage gate (currently 100%). Read ${SVC}/CLAUDE.md for the engine conventions (state rules, LangGraph gotchas, testing conventions).
HARD RULES:
- Edit ONLY the files your unit owns (listed below). Other Builders are editing other files in the same working tree at the same time: never edit, format, revert or stage their files, never run 'git checkout', 'git stash', 'git reset' or 'git add', never commit. The Lead commits.
- Use absolute paths in every command (prefix with 'cd ${SVC} &&' when a tool needs the service dir). Never leave a persistent cd.
- TDD: write the failing tests first, run them and see them fail for the right reason, then implement, then refactor. Never weaken, skip or delete an existing test unless the spec explicitly changes that behaviour; then rewrite it to assert the new behaviour and say so in your report.
- Python 3.11 is the CI floor (you run 3.13 locally): no PEP 695 generics syntax, no PEP 701 nested same-quote f-strings, no itertools.batched, typing.override, Path.walk, PurePath.full_match, datetime.UTC alias is fine (3.11+). Code that touches OS behaviour must work on Linux and macOS (Apple M4 Pro is the user's machine) or branch explicitly on an injected platform value.
- No live network or Claude API calls, ever: every pytest command you run must include -m "not live" (-o addopts="" drops the default filter), never select live tests, never construct AnthropicTransport against the real API. This container sets ANTHROPIC_BASE_URL and may expose a key. No secrets in code. Never shell=True; argv lists only. Validate every path. Keep source under about 400 lines for your unit.
- mypy: if errors appear only in files you do not own (another Builder mid-edit), note them and move on; YOUR files must be clean.
- Before reporting, run from ${SVC}: 'uv run ruff check <your files>', 'uv run ruff format <your files>', 'uv run mypy src tests', and 'uv run pytest -o addopts="" -m "not live" -q -p no:cacheprovider <your test files> --cov=autonomous_ai_agents --cov-branch --cov-report=term-missing' and make sure every line and branch of the modules you own is covered (no 'pragma: no cover'). Then run the whole suite once with 'uv run pytest -o addopts="" -m "not live" -q -n 2 -p no:cacheprovider' and report its last line (failures in files you do not own: name them, do not fix them).
SEAMS (the class of bug every earlier review missed; check each that your unit touches, Builders and Reviewers alike):
- Fixtures above you: read every autouse fixture in ${SVC}/tests/conftest.py and in each conftest.py between it and your tests. tests/conftest.py's reset_environment replaces ANTHROPIC_API_KEY with a placeholder for EVERY test; a fixture that patches settings or the environment changes what your code reads.
- Real-vs-fake swap points: wherever a test substitutes the key, base URL, transport, clock, sleep, platform or launcher, ask what the production wiring would do instead. A dry run must use the production wiring and swap only the wire (a mock HTTP transport), never the input under test.
- Root vs non-root: this container runs as root, which ignores mode bits. If your unit touches file modes, permissions or directory walks, also run its tests as the non-root user: su tester -c "cd ${SVC} && .venv/bin/python -m pytest <your test files> -o addopts='' -p no:cacheprovider -m 'not live' -q" (create it with useradd -m tester if missing).
- What only CI, macOS or a live run can prove: name it in your report, and add the offline test that comes closest.
REPORT FORMAT (your final message is the return value): files changed (path, +/- lines), tests added (names), each spec requirement for your unit -> where it is met, deviations from the spec with reasons, open questions for the Lead, and the exact commands you ran with their last lines.`

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['blocker', 'should-fix', 'nit'] },
          location: { type: 'string' },
          problem: { type: 'string' },
          reproduction: { type: 'string' },
          fix: { type: 'string' },
        },
        required: ['severity', 'location', 'problem', 'reproduction', 'fix'],
      },
    },
    spec_coverage: { type: 'string' },
    commands_run: { type: 'string' },
  },
  required: ['findings', 'spec_coverage', 'commands_run'],
}

function buildPrompt(u) {
  return `${COMMON_RULES}

YOUR UNIT: ${u.id} ${u.title}
FILES YOU OWN (source): ${u.files.join(', ')}
TEST FILES YOU OWN: ${u.tests.join(', ')}
LEAD NOTES FOR THIS UNIT:
${u.notes}

Implement the unit exactly as the spec describes (search the spec for "${u.id}" and for every interface your files define). Report as specified.`
}

function reviewPrompt(u, report, lens) {
  return `${COMMON_RULES}

You are the ${lens === 'security' ? 'SECURITY REVIEWER' : 'REVIEWER'} for unit ${u.id} ${u.title}. READ-ONLY: do not edit, format, create or delete any file in the repo (you may write scratch files only under /tmp/aip-review/${u.id}-${lens}/, never inside the repo; pass -p no:cacheprovider to pytest, set COVERAGE_FILE=/tmp/aip-review/${u.id}-${lens}/.coverage when you measure coverage, and never run ruff format), never run git commands that change state. You did not write this code; review it with fresh eyes.
Files under review: ${u.files.concat(u.tests).join(', ')}
Lead notes given to the Builder:
${u.notes}
Builder's report:
${report}

${lens === 'security'
    ? 'Review for exploitable weaknesses only, against spec section 5 and the OWASP LLM list: command injection, path traversal and symlink escapes, writes outside the worktree, network escape, secrets reaching child processes or logs, git config/hook injection, prompt injection reaching tools, cost-cap bypass, anything a trial or a malicious repo could use to change how it is judged or to touch the user\'s checkout or default branch. Give a concrete reproduction (input, command, or test) for every finding; confirm by running it where you can.'
    : 'Review for: correctness bugs with a concrete failing input; deviations from the spec that change behaviour; missing behaviour from the spec for this unit; tests that are tautological, weakened, assert on the wrong object, or miss a spec requirement; Python 3.11 incompatibilities; macOS incompatibilities; mypy strictness holes (Any leaks, ignores); files edited outside the unit. Run the unit tests and mypy yourself.'}
severity: blocker (wrong behaviour, security hole, spec violation, or broken test) | should-fix (real but minor) | nit. Report only real findings with reproductions; no praise. Scope: the files under review and their direct callers and fixtures (the SEAMS list); do not re-review unchanged modules.`
}

function fixPrompt(u, report, findings) {
  return `${COMMON_RULES}

YOUR UNIT: ${u.id} ${u.title}
FILES YOU OWN (source): ${u.files.join(', ')}
TEST FILES YOU OWN: ${u.tests.join(', ')}
LEAD NOTES: ${u.notes}
The Builder's report (the code is already in the working tree):
${report}

Independent reviewers found the issues below. Fix every blocker and should-fix finding, test-first (a failing test that reproduces it, then the fix). If you are sure a finding is wrong, do not change code for it: explain why with evidence. Nits: fix only when trivial and inside your files.
FINDINGS:
${JSON.stringify(findings, null, 1)}

Report: per finding -> fixed (test name) or rejected (evidence), then the full command list with last lines as in the report format.`
}

// Usage guard: before every agent launch, refuse to start one once this turn's
// output tokens reach args.maxOutputTokens (or the user's "+N" turn budget).
// After every agent, log the running total so it can be compared with the plan meter.
// budget.spent() is cumulative across the session, so the ceiling applies to
// what THIS workflow has spent since it started.
const CEILING = args.maxOutputTokens ?? null
let halted = null
function spent() { return (typeof budget !== 'undefined' && budget.spent) ? budget.spent() : 0 }
const START = spent()
function used() { return spent() - START }
async function guarded(prompt, opts) {
  if (halted) return null
  if (CEILING !== null && used() >= CEILING) {
    halted = `usage ceiling reached before ${opts.label}: ${used()} >= ${CEILING} output tokens`
    log('HALT: ' + halted)
    return null
  }
  const r = await agent(prompt, opts)
  log(`${opts.label} done; output tokens used by this workflow: ${used()}`)
  return r
}

const units = args.units
const results = await pipeline(
  units,
  u => guarded(buildPrompt(u), { label: 'build:' + u.id, phase: 'Build' }),
  (report, u) => {
    if (!report) return { report: null, reviews: [], missing: [] }
    const lenses = u.security ? ['correctness', 'security'] : ['correctness']
    return parallel(lenses.map(lens => () =>
      guarded(reviewPrompt(u, report, lens), {
        label: 'review:' + u.id + (lens === 'security' ? ':sec' : ''), phase: 'Review', schema: REVIEW_SCHEMA, model: 'fable',
      }).then(r => ({ lens, r })))).then(reviews => ({
        report,
        reviews: reviews.filter(x => x && x.r),
        missing: lenses.filter((lens, i) => !reviews[i] || !reviews[i].r),
      }))
  },
  (prev, u) => {
    if (!prev.report) return { unit: u.id, report: null, findings: [], fix: null, halted }
    // Missing-review guard: a null review (agent died, model unavailable, ceiling) must never read as "no findings".
    if (prev.missing.length) {
      const msg = `MISSING REVIEW(S) for ${u.id}: ${prev.missing.join(', ')}; fixer not started` + (halted ? ` (${halted})` : '')
      log('HALT: ' + msg)
      return { unit: u.id, report: prev.report, findings: [], fix: null, halted: msg }
    }
    const findings = prev.reviews.flatMap(x => (x.r?.findings ?? []).map(f => ({ ...f, lens: x.lens })))
    const actionable = findings.filter(f => f.severity !== 'nit')
    if (!actionable.length) return { unit: u.id, report: prev.report, findings, fix: null, halted }
    return guarded(fixPrompt(u, prev.report, findings), { label: 'fix:' + u.id, phase: 'Fix' })
      .then(fix => ({ unit: u.id, report: prev.report, findings, fix, halted }))
  },
)
return results
