"""Render round 2's per-agent briefs (phases 0-2) into round-2/briefs/, so every
agent gets the same rules word for word. The shared constants (FIXED, SAFETY,
NOFAST, BAND, CHARTER) are read from round-2/tail.js, the tail workflow's script.
Run: EMERGENCE_W=<emergence worktree> EMERGENCE_SCRATCH=<scratch dir> python3 gen_briefs.py"""
import json
import re
from pathlib import Path

import os
# Paths: a fresh session sets these two (the defaults are the session that ran round 2's launch).
S = os.environ.get('EMERGENCE_SCRATCH', '/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad')
W = os.environ.get('EMERGENCE_W', '/home/user/step3-emergence-r1')
H = W + '/.claude/handoff/step3'
EM = H + '/idea-lab/emergence'
BOARD = EM + '/round-2/board.md'
BOARD1 = EM + '/round-1/board.md'
POST = EM + '/round-2/post.sh'
PY = 'services/python_agents'
OUT = Path(EM + '/round-2/briefs')
OUT.mkdir(exist_ok=True)

v3 = Path(EM + '/round-2/tail.js').read_text()  # FIXED, SAFETY, NOFAST, BAND and CHARTER, word for word


def const(name: str) -> str:
    m = re.search(r'^const ' + name + r' = `(.*?)`\s*$', v3, re.M | re.S)
    assert m, name
    t = m.group(1)
    return t.replace('${W}', W).replace('${H}', H).replace('${BOARD}', BOARD).replace('${POST}', POST)


FIXED, SAFETY, NOFAST, BAND = const('FIXED'), const('SAFETY'), const('NOFAST'), const('BAND')
CHARTER = const('CHARTER') + (
    ' Society rules (O55, O57, O58): ten seats; each seat reads its own library file, the top scorers\' files'
    f' ({EM}/library/bounds-first.md and pre-mortem.md, tied) and the university pack ({EM}/round-2/university-pack.md)'
    ' before posting; points from verified outcomes only (from round 2: +1 survives the judges, +3 built, reviewed and gated,'
    ' +5 a record-only live pass, +10 a gain-bearing live pass, +2 a critique that led to a withdrawal or a kept merge,'
    ' -3 a fabricated number or a FIXED touch).')
BOARDRULE = (
    f'The board is {BOARD} (round 2). Round 1\'s board {BOARD1} and report {EM}/round-1.md are read-only reference: '
    'cite round-1 entries as "r1[n]". Communicate only through the round-2 board: read the WHOLE round-2 board at each '
    'sync point (now, at the start of your task) and do not rely on any other channel; you may read the repository '
    f'read-only to ground your claims. Post each message as ONE entry with exactly: bash {POST} "<agent name>" "<role>" '
    "<<'MSG'\\n<message>\\nMSG . Never edit the board any other way. Keep each entry self-contained and concrete; "
    'numbers only with their sources.')
LIVE = ('Live plans (O58): the balance is 21.08 USD for the whole round; a run costs about 2-3 USD and its cap need is '
        '9.35 USD; a dispatch goes only when the balance covers its need, so at most 2 runs fit one dispatch and about 3 '
        'runs fit the round. Plans must handle variance: several runs on fewer libraries (for example the same library '
        'two or three times), each read against that library\'s own twin gap and O52\'s arm call. Nothing is dispatched '
        'without the owner\'s approval.')
COMMON = (
    'Every proposal targets the ENGINE (what lanes see, what they must produce, how ideas are selected, realised, '
    'compounded or judged; shadow judges and the marker may be proposed on, frozen judges may not) and carries these '
    'headed parts, so it can be synthesised and judged: Mechanism; Engine files it changes (by repo path); Expected '
    'effect and its size, on which charter measure; Pre-registered measure and bar, naming the twin\'s band it is read '
    f'against ({BAND}); Record-only or gain-bearing (O58); Cost per run (USD) and its live plan under the rule ({LIVE}); '
    'Strongest reason it fails; Fixed items touched (none, or which, in which case say it stops here). Every local timing '
    'names its interpreter; CI judges on Python 3.11.')
OFFICE = (
    'Office hours (O55): in this wave you may ask the Facts agent ONE factual question (a number or fact from the '
    'archives, STATUS or the code, not an opinion). To ask: post ONE entry (role "question") starting "QUESTION for '
    'Facts:", then end your task at once, returning exactly "QUESTION [<entry number>]". You will be resumed with the '
    'answer\'s entry number and then do the task. If you need no question, do the task now.')
HANDBACK = ('Your final message is ONE line only, no report: the ids and the board entry numbers you posted, in the '
            'form the task asks for.')
CARRY = (f'Round 1\'s three carry-forwards are in the university pack ({EM}/round-2/university-pack.md): S5 the stacked '
         'step rebuilt on S2\'s records, S1\'s acting parts (count contract and gated re-entry), and SHP-3\'s off-shape '
         'check without observe mode. Any seat may take one up as its own proposal, crediting it.')

E12 = f'{EM}/round-1/live/ideas-x2s-e1-42264126014.jsonl and ideas-x2s-e2-42272888210.jsonl'
X2 = f'{H}/idea-lab/x2/ideas-x2-d1..d8-*.jsonl and the report {H}/idea-lab/x2/report/x2.md'

SEATS = [
    dict(name='Bounds first', tag='BND', file='bounds-first', model='fable',
         pack=f'the X1 profiles ({PY}/tests/fixtures/ideas_probe/facts.jsonl, views.jsonl), S1\'s unit counts and realisation records from E1 and E2 ({E12}: the counted work at base and trial per anchor), X2 ({X2}), and Amdahl.',
         shape='For 3 hot paths: the physical floor (what an ideal implementation must still do: bytes, allocations, C-level calls, each with its basis and interpreter), the gap to today now that S1 counts it, and the engine change that makes lanes compute the gap before proposing.'),
    dict(name='Pre-mortem', tag='PRM', file='pre-mortem', model='fable',
         pack=f'every reject, inconclusive and undelivered keep in X2 and E1/E2 ({X2}; {E12}), with S1\'s labels (fired, weak, not_fired, reversed, uncounted) and S2\'s skip records, and the editor and retry code.',
         shape='The ways the next best idea fails at trial or at combine, the engine check that catches each before a trial is spent, and which past wins it would wrongly have caught (replayed on the archives).'),
    dict(name='Expert prior', tag='EXP', file='expert-prior', model=None,
         pack=f'the development corpus\'s reference fixes ({PY}/tests/fixtures/live_corpus_discovery/_solutions), V9\'s manifest METADATA ONLY (never _keys or _notes: O53), the X1, X2 and E1/E2 keeps, and your own knowledge of public, pre-cutoff upstream performance fixes.',
         shape='The families of mechanism experts use that the engine still does not propose (count them in X2 and E1/E2), and the engine change that makes lanes search those families on purpose.'),
    dict(name='Inversion', tag='INV', file='inversion', model=None,
         pack=f'the X2 and E1/E2 idea lists and verdicts ({X2}; {E12}).',
         shape='For each library you take on: how you would make it slower without changing output (each is a hidden cost already paid), the reverse of each, and the engine change that asks the question this way.'),
    dict(name='Analogy transfer', tag='ANA', file='analogy-transfer', model=None,
         pack=f'the hot functions\' roles ({PY}/tests/fixtures/ideas_probe/facts.jsonl), your knowledge of the fastest known implementations of those roles, and the harness\'s aimed hypotheses ({PY}/tests/live/oss.py): check every structure against them and the archives before betting on it (round 1\'s lesson, r1[105]).',
         shape='The cross-domain prior lanes should carry (role, structure, the cost model that says when it wins on CPython 3.11), and the engine change that gives lanes this prior.'),
    dict(name='Scaling', tag='SCL', file='scaling', model=None,
         pack=f'the scaling judge (G6b, in {PY}/src/autonomous_ai_agents/optimization/judges.py, shadow), the benchmarks\' input sizes (fixed: benchmarks are FIXED, so no size variable may be added to them), round 1\'s growth findings (r1[84], r1[85], r1[109], r1[110]), and the X2 keeps\' mechanisms.',
         shape='For 3 hot paths: today\'s growth term per input unit, which archived keeps changed the slope and which only the constant, and the engine change that measures slope in shadow without touching a benchmark (e.g. engine-perturbed or engine-scaled copies under r1[62]\'s four conditions).'),
    dict(name='Contrarian', tag='CON', file='contrarian', model='fable', after_wave1=True,
         pack=f'ALL of this round\'s wave-1 proposals on the round-2 board, the superseded round 0 ({EM}/library/round-0.md), and round 1\'s board and report.',
         shape='The ONE belief most of the wave-1 proposals share that is most likely wrong; the evidence for and against it from the archives; the cheapest test that settles it, with its cost; and the engine change if it is wrong. Then a second such belief, or "none".'),
    dict(name='Memory & allocation', tag='MEM', file='memory-allocation', model=None,
         pack=f'the charter\'s default objective (runtime AND peak memory, CLAUDE.md "Define better"), what the engine measures of memory today (the judges and the measure/launcher code in {PY}/src/autonomous_ai_agents/execution and optimization), X2\'s keep rate for allocation_or_copying ideas (0 of 5), and allocation behaviour you can count offline (tracemalloc, sys.getallocatedblocks) at the pins on python3.11.',
         shape='Per hot path: allocations and bytes per unit of work today, what an ideal still allocates, and the engine change that makes memory a measured axis in shadow and gives lanes allocation facts.'),
    dict(name='Verifier-designer', tag='VER', file='verifier-designer', model=None,
         pack=f'the frozen judges (read-only: {PY}/src/autonomous_ai_agents/optimization/judges.py), what the output-equivalence judge actually checks on each benchmark input, round 1\'s off-shape findings (r1[60], r1[84]), S2\'s combine records, and the libraries\' test suites as verifiers.',
         shape='For each class of keep: what today\'s verifiers cannot catch, the SHADOW verifier that would (never a change to a frozen judge), and which archived keeps it would have flagged, replayed offline.'),
    dict(name='Interpreter specialist', tag='INT', file='interpreter-specialist', model=None,
         pack=f'your library file ({EM}/library/interpreter-specialist.md: uncountable trials kept at 64 % against 33 % countable), S1\'s shim ({PY}/src/autonomous_ai_agents/execution/_opcount_shim.py, _profile_shim.py), E1/E2\'s uncounted trials ({E12}), and CPython 3.11\'s adaptive interpreter (specialisation, inline caches, the cost of calls, generators and C builtins).',
         shape='Why the uncountable trials keep at 64 %: what work they change at the bytecode or C level; the engine change that counts or prices it (the shim or a price card on the judged interpreter); and a test on the archived trials.'),
]
N = len(SEATS)
WAVE1 = [s for s in SEATS if not s.get('after_wave1')]


def head(seat: dict, role: str, phase: str) -> str:
    return (f'You are the {seat["name"]} agent (role: {role}) in emergence round 2, {phase}. {CHARTER} {SAFETY} {FIXED} '
            f'{BOARDRULE} Read first: your seat file {EM}/library/{seat["file"]}.md (it may be new), the top scorers\' files, '
            f'and the university pack {EM}/round-2/university-pack.md. {CARRY}')


briefs = {}
for i, s in enumerate(SEATS):
    phase = 'Phase 1, proposals' if not s.get('after_wave1') else 'Phase 1c, the Contrarian (after the other nine have posted)'
    briefs[f'propose_{s["file"]}'] = (
        f'{head(s, "proposer", phase)}\nYour framework: {s["name"]}. Your evidence pack (yours alone in this phase): {s["pack"]}\n'
        f'Your output shape: {s["shape"]}\n{COMMON}\n{NOFAST}\n{OFFICE}\n'
        f'Sync point: read the whole round-2 board now, the Lead\'s opening entry and the facts card first. Then post EXACTLY 2 '
        f'proposals, ONE board entry each (agent "{s["name"]}", role "proposer"), each starting "ID: {s["tag"]}-<n>", in your '
        f'output shape followed by the common parts. Ground every number in the facts card, round 1\'s report or your pack '
        f'(cite the file). {HANDBACK} Form: IDS: <ids> ENTRIES: <entry numbers>.')
    others = ' || '.join(f'{o["name"]}: {o["pack"]}' for o in SEATS if o is not s)
    briefs[f'cross_{s["file"]}'] = (
        f'{head(s, "proposer", "Phase 1b, cross-pollination")}\nSync point: read the whole round-2 board once now. Post ONE more '
        f'proposal that combines YOUR framework ({s["name"]}: {s["shape"]}) with a DIFFERENT seat\'s evidence pack. The packs: '
        f'{others}\nThe entry (agent "{s["name"]}", role "proposer") starts "ID: {s["tag"]}-X", then "Combines: {s["name"]} '
        f'framework x <other seat>\'s evidence pack", then your output shape and the common parts. {COMMON} {NOFAST}\n{OFFICE}\n'
        f'If you cannot honestly combine your framework with another pack into a proposal that is not a duplicate of one '
        f'already on the board, post instead a ONE-LINE entry: "ID: {s["tag"]}-X: cannot: <why>". {HANDBACK} Form: IDS: <id or none> ENTRIES: <entry numbers>.')
    t1, t2 = SEATS[(i + 1) % N]['name'], SEATS[(i + 3) % N]['name']
    briefs[f'critique_{s["file"]}'] = (
        f'{head(s, "critic", "debate round 1 of 2")}\nYour framework: {s["name"]} ({s["shape"]}).\n{OFFICE}\n'
        f'Sync point: read the whole round-2 board now. Critique exactly two other seats\' proposals, those of the {t1} agent '
        f'and of the {t2} agent (all of each one\'s proposals, the cross-pollinated one included). Post one board entry per '
        f'target (agent "{s["name"]}", role "critic"), starting "CRITIQUE of <target agent>:", and for each proposal id: the '
        f'strongest objection (including, if it applies, that it is really a local fast path, caching or hoisting, or that '
        f'its live plan breaks the variance rule or the 21.08 USD balance); what evidence would settle it (a measure, a '
        f'fixture, a live run, with its cost); whether you would merge it with one of your own proposals (name the id) or '
        f'not. Do not repeat another critic\'s objection already on the board unless you add evidence. {HANDBACK} Form: CRITIQUED: <ids> ENTRIES: <entry numbers>.')
    briefs[f'revise_{s["file"]}'] = (
        f'{head(s, "proposer", "debate round 2 of 2 (the last: no new proposals)")}\nSync point: read the whole round-2 board '
        f'now, especially the critiques of your proposals. For each of your own proposals ({s["tag"]}-1, {s["tag"]}-2 and '
        f'{s["tag"]}-X if you posted one) post one board entry (agent "{s["name"]}", role "proposer"), starting "REVISION <id>:" '
        f'with exactly one of: KEPT (unchanged, and why the objection does not hold), REVISED (the changed parts in full: '
        f'mechanism, engine files, measure and bar with the twin\'s band, record-only or gain-bearing, cost and live plan '
        f'under the rule, strongest failure), WITHDRAWN (why), or MERGED INTO <other id> (why, and what of yours it must keep). '
        f'Do not post new proposals. No office-hours question in this wave. {HANDBACK} Form: KEPT: <ids> REVISED: <ids> WITHDRAWN: <ids> MERGED: <id -> into> ENTRIES: <entry numbers>.')

briefs['facts'] = (
    f'You are the Facts agent (role: facts) of emergence round 2, read-only. {CHARTER} {SAFETY} {BOARDRULE}\n'
    f'Build ONE facts card and post it to the round-2 board as a single entry (agent "Facts", role "facts"). Numbers only, '
    f'each with its source (file and section or row); no opinions, no recommendations. Sources: {W}/STATUS.md (O53-O58, '
    f'the ledger rows for X2 and emergence E1/E2), {EM}/round-1.md (sections 3, 7, 9 and 12), the university pack, round 1\'s '
    f'board where needed, {X2}, and {E12}. Cover at least: round 1\'s builds and their settings now (S1 record; S2 record, '
    f'not on, O58); E1/E2 per library against X2-0 with each library\'s band, O52\'s arm call, X2-S\'s own sqlparse A/A gap; '
    f'the bars that passed and the no-harm bar that failed, and the note that three of four failures are fewer keeps '
    f'before the combine; S1\'s labels on 73 trials with keep rates (fired 12/36, not_fired 0/11, uncounted 7/11, weak 2/8, '
    f'reversed 1/7) recomputed from the archives; the floor check (X2-S against X2-0 per library); the charter measures as '
    f'they stand (round-1.md section 7 updated with E1/E2 where computable, measure 5 now readable); the twin gaps; the '
    f'balance (21.08 USD) and the variance rule; the points table (O58). Then return ONE line: FACTS: <entry number>.')
briefs['facts_answer'] = (
    f'You are the Facts agent (role: facts) of emergence round 2, read-only, answering office-hours questions (O55). '
    f'{SAFETY} {BOARDRULE}\nRead the whole round-2 board. Answer each open "QUESTION for Facts:" entry listed here: '
    '{QUESTIONS}. Post ONE board entry per question (agent "Facts", role "facts"), starting "ANSWER to [<n>]:", with the '
    'number or fact and its source (file and row or line, or the command you ran read-only and its output). If the '
    'question asks for an opinion or cannot be answered from the archives, STATUS or the code, say so in one line. '
    'Return ONE line: ANSWERS: <question entry> -> <answer entry>, ...')

for k, v in briefs.items():
    (OUT / f'{k}.md').write_text(v)
models = {s['file']: s['model'] for s in SEATS}
(OUT / 'seats.json').write_text(json.dumps([{**{k: s[k] for k in ('name', 'tag', 'file', 'model')}, 'after_wave1': bool(s.get('after_wave1'))} for s in SEATS], indent=1))
print(len(briefs), 'briefs;', 'models:', models)
print('critique targets:', [(s['name'], SEATS[(i + 1) % N]['name'], SEATS[(i + 3) % N]['name']) for i, s in enumerate(SEATS)])
