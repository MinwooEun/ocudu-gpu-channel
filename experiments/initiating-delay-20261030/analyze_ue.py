"""Pair original UE function probes and integrate scheduler off-CPU intervals."""
import pathlib,re,json,collections,bisect,numpy as np
p=pathlib.Path('/workspace/gpuch/realtime-rate-20261030/u1/original-input-root2-r2')
rx=re.compile(r'^\s*(.*?)\s+(\d+)\s+\[(\d+)\]\s+(\d+)\.(\d+):\s+(\S+):\s*(.*)$')
active={};calls=[];switches=[];pidmap={};counts=collections.Counter()
for line in (p/'ue-functions.txt').open():
 m=rx.match(line)
 if not m:continue
 comm,tid,cpu,sec,ns,event,rest=m.groups();tid=int(tid);t=int(sec)*10**9+int(ns.ljust(9,'0'))
 if event=='sched:sched_switch':
  z=re.search(r'prev_pid=(\d+).*?prev_state=(\S+).*?next_comm=(.*?) next_pid=(\d+)',rest)
  assert z,rest
  prev,state,ncomm,nxt=z.groups();prev=int(prev);nxt=int(nxt);pidmap[tid]=prev;switches.append((t,prev,nxt,state,ncomm));continue
 if event.startswith('probe_srsue:ocudurate_'):
  name=event.split('ocudurate_')[1];counts[name]+=1
  ret=name.endswith('_ret__return');name=name.removesuffix('_ret__return');key=(tid,name)
  if ret:
   if key in active:calls.append(dict(tid=tid,name=name,start=active.pop(key),end=t))
  else:
   assert key not in active,key
   active[key]=t
# A scheduler switch out is followed by the next switch in for that host TID.
off=collections.defaultdict(list);pending={}
for t,prev,nxt,state,ncomm in switches:
 if nxt in pending:
  start,st,other=pending.pop(nxt);off[nxt].append((start,t,st,other))
 pending[prev]=(t,state,ncomm)
offstarts={h:[x[0] for x in v] for h,v in off.items()}
for c in calls:
 h=pidmap.get(c['tid']);c['host_tid']=h;c['wall_us']=(c['end']-c['start'])/1000
 cuts=[]
 lo=max(0,bisect.bisect_right(offstarts.get(h,[]),c['start'])-1);hi=bisect.bisect_left(offstarts.get(h,[]),c['end'])
 for a,b,state,other in off[h][lo:hi]:
  overlap=max(0,min(b,c['end'])-max(a,c['start']))
  if overlap:cuts.append(dict(start=max(a,c['start']),end=min(b,c['end']),state=state,next_comm=other,us=overlap/1000))
 c['off_us']=sum(x['us'] for x in cuts);c['on_us']=c['wall_us']-c['off_us'];c['off_intervals']=cuts
summary={}
for name in ['dl','ul','work','end']:
 a=[c for c in calls if c['name']==name]
 summary[name]={k:dict(zip(['p50','p95','max'],np.percentile([c[k] for c in a],[50,95,100]).tolist())) for k in ['wall_us','on_us','off_us']};summary[name]['count']=len(a)
(p/'ue-functions-analysis.json').write_text(json.dumps(dict(counts=counts,pidmap=pidmap,summary=summary,calls=calls),indent=2))
print(json.dumps(summary,indent=2))
