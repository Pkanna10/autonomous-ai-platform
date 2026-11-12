import json,glob,collections,sys
D='/home/user/step3-emergence-r1/.claude/handoff/step3/idea-lab/w2-sprint/live/'
tot=collections.Counter()
allp=[]
for f in sorted(glob.glob(D+'ideas-x2-X2-P-*.jsonl')):
    rows=[json.loads(l) for l in open(f)]
    hyps={r['hypothesis_id']:r for r in rows if r['experiment']=='ideas-x2-hypothesis'}
    for r in rows:
        if r['experiment']!='ideas-x2-round': continue
        for p in r['procedures']:
            tot['dealt']+=1; tot[p['outcome']]+=1
            if p['outcome']!='idea': continue
            hid=p['hypothesis_id']
            h=hyps.get(hid) if hid else None
            st='hid+row' if h else ('hid-norow' if hid else 'nohid')
            tot[st]+=1
            allp.append((f.split('-')[-1][:11],r['repo'],r['round'],p['deal_round'],p['framework'],p['idea_id'],st,(h or {}).get('verdict'),p['title']))
print(tot)
for a in allp: print(*a,sep=' | ')
