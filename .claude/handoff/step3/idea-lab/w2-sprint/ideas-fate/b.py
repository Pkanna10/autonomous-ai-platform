import json,glob,collections
D='/home/user/step3-emergence-r1/.claude/handoff/step3/idea-lab/w2-sprint/live/'
def key(t): return " ".join(t.split()).casefold()
fate=collections.defaultdict(collections.Counter)
rounds=[]
for f in sorted(glob.glob(D+'ideas-x2-X2-P-*.jsonl')):
    rows=[json.loads(l) for l in open(f)]
    hyps=[r for r in rows if r['experiment']=='ideas-x2-hypothesis']
    for r in rows:
        if r['experiment']!='ideas-x2-round': continue
        order=[v['lane'] for v in r['lane_views']]
        pos=order.index('leap') if 'leap' in order else None
        ideas=[p for p in r['procedures'] if p['outcome']=='idea']
        picked=[p for p in ideas if p['hypothesis_id']]
        earlier={key(h['title']) for h in hyps if h['repo']==r['repo'] and h['round'] is not None and h['round']<r['round']}
        same_round_titles=[key(h['title']) for h in hyps if h['repo']==r['repo'] and h['round']==r['round']]
        outs=collections.Counter(p['outcome'] for p in r['procedures'])
        rounds.append((f[-17:-6],r['repo'],r['round'],pos,len(order),len(ideas),len(picked),dict(outs)))
        for p in ideas:
            if p['hypothesis_id']: continue
            t=p['title'] or ''
            pre=key(t[:-3] if t.endswith('...') else t)
            exact_earlier=any(e.startswith(pre) for e in earlier)
            exact_same=any(e.startswith(pre) for e in same_round_titles)
            cat='f1_slot_taken_by_sibling' if picked else 'f2_no_leap_pick'
            fate[p['framework']][cat]+=1
            if exact_earlier: print('EXACT EARLIER TITLE',p['title'])
            if exact_same: print('EXACT SAME-ROUND TITLE',p['title'])
for x in rounds: print(*x)
print()
tot=collections.Counter()
for fw in ['bentley','per_element','backend','skiena','polya','from_spec','ifr','trim','sit','recall']:
    print(fw, dict(fate[fw]), sum(fate[fw].values())); tot.update(fate[fw])
print(tot, sum(tot.values()))
# leap position vs picked
c=collections.Counter()
for x in rounds:
    if x[5]: c[(x[3]==x[4]-1, x[6]>0)]+=1
print('leap last in rotation?, picked? (rounds with >=1 idea):',c)
