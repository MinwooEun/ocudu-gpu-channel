"""Keep exact rebase-to-UE-function matches with nested operation durations."""
import json,pathlib,bisect,collections
p=pathlib.Path('/workspace/gpuch/realtime-rate-20261030/u1/original-input-root2-r2')
a=json.loads((p/'ue-functions-analysis.json').read_text());e=json.loads((p/'input-analysis.json').read_text())
calls=a['calls'];works=sorted((c for c in calls if c['name']=='work'),key=lambda c:c['start']);starts=[c['start'] for c in works];bytid=collections.defaultdict(list)
for c in calls:bytid[c['tid']].append(c)
for tid in bytid:bytid[tid].sort(key=lambda c:c['start'])
ts={tid:[c['start'] for c in v] for tid,v in bytid.items()};out=[]
for event in e['events']:
 t=event['times']['ue_rf_tx_enter'];idx=bisect.bisect_right(starts,t)-1
 if idx<0 or works[idx]['end']<t:continue
 w=works[idx];v=bytid[w['tid']];q=ts[w['tid']];children=v[bisect.bisect_left(q,w['start']):bisect.bisect_right(q,w['end'])];children=[c for c in children if c['name']!='work' and c['end']<=w['end']]
 out.append(dict(event=event,work=w,children=children))
r=dict(function_summary=a['summary'],probe_counts=a['counts'],namespace_host_tid=a['pidmap'],matched_rebases=len(out),events=out)
(p/'causal-operation-matches.json').write_text(json.dumps(r,indent=2)+'\n')
for row in sorted(out,key=lambda x:x['event']['shift_us'],reverse=True)[:8]:
 print('SAMPLE',row['event']['sample'],'LOST',row['event']['shift_us'],'WORK',row['work']['wall_us'],'OFF',row['work']['off_us'])
 print([(c['name'],c['wall_us'],c['off_us']) for c in row['children']])
