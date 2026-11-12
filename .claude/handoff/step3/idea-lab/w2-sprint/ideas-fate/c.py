import json,glob,collections,re
D='/home/user/step3-emergence-r1/.claude/handoff/step3/idea-lab/w2-sprint/live/'
FW=['bentley','per_element','backend','skiena','polya','from_spec','ifr','trim','sit','recall']
tab=collections.defaultdict(collections.Counter)
chk=0
for f in sorted(glob.glob(D+'ideas-x2-X2-P-*.jsonl')):
    rows=[json.loads(l) for l in open(f)]
    hyps=[r for r in rows if r['experiment']=='ideas-x2-hypothesis']
    hid={h['hypothesis_id']:h for h in hyps}
    for r in rows:
        if r['experiment']!='ideas-x2-round': continue
        ideas=[p for p in r['procedures'] if p['outcome']=='idea']
        picked=any(p['hypothesis_id'] for p in ideas)
        same=[h for h in hyps if h['repo']==r['repo'] and h['round']==r['round']]
        earlier=[h for h in hyps if h['repo']==r['repo'] and h['round'] is not None and h['round']<r['round']]
        for p in ideas:
            if p['hypothesis_id']:
                h=hid[p['hypothesis_id']]; chk+= h['framework']==p['framework'] and h['round']==r['round']
                continue
            names={fn.split('::')[-1].split('.')[-1] for fn in (p['functions'] or '').split(';') if fn}
            def hit(hs): return [h for h in hs if any(re.search(r'\b'+re.escape(n)+r'\b',h['title']) for n in names)]
            s=hit(same); e=hit(earlier)
            cat='f1' if picked else 'f2'
            tw='twin_same_round' if s else ('twin_earlier_round_only' if e else 'no_twin')
            tab[p['framework']][cat]+=1; tab[p['framework']][tw]+=1
            print(f[-17:-6],r['repo'],r['round'],p['framework'],cat,tw,'|',p['functions'],'|',p['title'][:70],'|',[ (h['lane'],h['title'][:50]) for h in (s or e)][:2])
print('join check (hid rows with same framework and round):',chk)
for fw in FW: print(fw,dict(tab[fw]))
t=collections.Counter()
for v in tab.values(): t.update(v)
print(t)
