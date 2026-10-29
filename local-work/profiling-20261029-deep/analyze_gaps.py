from pathlib import Path
import numpy as np,json,csv,collections,bisect,sys
ROOT=Path('/workspace/gpuch/profile-20261029-deep');sub=sys.argv[1] if len(sys.argv)>1 else '';P=ROOT/sub;case={'':'deep16','yield':'deep16-yield','eight':'deep8-yield','cpu7':'deep16-cpu7'}[sub];R=ROOT/'runs'/case;W=json.load(open(P/'capture-window.json'));lo=W['start_ns'];hi=W['end_ns'];S=json.load(open(P/'scheduler-intervals.json'))
M=json.load(open(P/'thread-map.json'));tids={x['comm']:x['tid'] for x in M};names=['op','tid','port','flags','start','end','result','error'];dt=np.dtype([(x,'<i8') for x in names])
f=next((R/'wire').glob('ocudu*'));h=np.fromfile(f,dtype='<u8',count=8);assert h[3]==0,h[:4];a=np.memmap(f,dtype=dt,offset=64,shape=(int(h[1]),));a=a[np.isin(a['op'],[50,51,52,60])]
A=collections.defaultdict(list)
with (R/'hop/hop-trace.csv').open() as z:
 for r in csv.DictReader(z):
  ev=int(r['event'])
  if (r['role']=='puller' and ev==2) or (r['id']=='gnb0' and ev==10) or (r['id']=='gnb0_p0' and r['role']=='rep' and ev in (20,21,22)):A[r['role'],r['id'],ev].append((int(r['t_ns']),int(r['samples'])))
A={k:np.array(v,dtype='i8') for k,v in A.items()};ready=A['producer','gnb0',10];seq=np.cumsum(ready[:,1])-ready[:,1];sources=sorted(k for k in A if k[0]=='puller' and k[1].startswith('ue'))
arrival=[]
for k in sources:
 b=A[k];ix=np.minimum(np.searchsorted(np.cumsum(b[:,1]),seq,side='right'),len(b)-1);arrival.append(b[ix,0])
last_arrival=np.array(arrival).max(axis=0);q=A['rep','gnb0_p0',20];pop=A['rep','gnb0_p0',21];sent=A['rep','gnb0_p0',22];sentseq=np.cumsum(sent[:,1]);prod=tids['DP-gnb0'];reply=tids['DR-gnb0_p0'];gaps=collections.defaultdict(list);ms=0
phase=a[(a['op']==60)&(a['tid']==prod)];rooms=phase[phase['port']==0];rooms=rooms[np.argsort(rooms['end'])]
for v in phase[phase['port']==1]:
 i=np.searchsorted(ready[:,0],v['end'],side='right')-1;assert ready[i,1]==v['result'];ri=np.searchsorted(rooms['end'],v['start'],side='right')-1
 if ri<0:continue
 room=rooms[ri]
 if room['start']<lo+5_000_000 or v['end']>hi-5_000_000:continue
 ms+=v['result']/23040
 gaps['input_after_ready'].append((prod,max(v['start'],last_arrival[i]),v['end']))
 j=min(np.searchsorted(sentseq,seq[i]-23040,side='right'),len(sent)-1)
 gaps['reply_after_request'].append((reply,max(room['start'],q[j,0]),min(room['end'],pop[j,0])))
 gaps['room_after_release'].append((prod,max(room['start'],sent[j,0]),room['end']))
# Partition scheduler intervals by code context. Acquisition/hold boundaries are actual per-call records.
out={};examples=[]
for label,G in gaps.items():
 totals=collections.Counter();sites=collections.Counter();count=0
 tid0=prod if label!='reply_after_request' else reply
 ownall=a[(a['tid']==tid0)&(a['op']!=60)];ownall=ownall[np.argsort(ownall['end'])];ownends=ownall['end']
 name0='DP-gnb0' if tid0==prod else 'DR-gnb0_p0';stateends=[r[1] for r in S['states'][name0]]
 for tid,start,end in G:
  if end<=start:continue
  count+=1;name='DP-gnb0' if tid==prod else 'DR-gnb0_p0';states=S['states'][name]
  if '_index' not in out:pass
  own=ownall[np.searchsorted(ownends,start,side='right'):np.searchsorted(ownends,end,side='right')+1];own=own[own['start']<end]
  ranges=[]
  for r in own:
   aa=max(start,int(r['start']));bb=min(end,int(r['end']));kind='mutex_acquire' if r['op']==50 else 'mutex_held' if r['op']==51 else 'sched_yield_call';ranges.append((aa,bb,kind,int(r['flags']),int(r['port'])))
  bounds={int(start),int(end)}
  for aa,bb,*_ in ranges:bounds.update((aa,bb))
  ix=bisect.bisect_left(stateends,start)
  selected=[]
  for aa,bb,state in states[max(0,ix-1):]:
   if aa>=end:break
   if bb>start:aa=max(aa,int(start));bb=min(bb,int(end));selected.append((aa,bb,state));bounds.update((aa,bb))
  bounds=sorted(bounds)
  for aa,bb in zip(bounds,bounds[1:]):
   if bb<=aa:continue
   mid=(aa+bb)//2;context=next(((kind,site,ptr) for x,y,kind,site,ptr in ranges if x<=mid<y),('outside_mutex',0,0));state=next((k for x,y,k in selected if x<=mid<y),'unknown');totals[context[0]+':'+state]+=bb-aa
   if context[1]:sites[str(context[1])+':'+context[0]]+=bb-aa
  if len(examples)<10 and end-start>500_000:examples.append(dict(gap=label,tid=int(tid),start_ns=int(start),end_ns=int(end),mutex_records=[{n:int(r[n]) for n in names} for r in own]))
 out[label]=dict(calls=count,us_per_radio_ms={k:v/1000/ms for k,v in totals.items()},total_us_per_radio_ms=sum(totals.values())/1000/ms,mutex_sites_us_per_radio_ms={k:v/1000/ms for k,v in sites.items()})
report=dict(window=W,radio_ms=ms,attribution=out,examples=examples,wire_records=int(h[1]),wire_dropped=int(h[3]));(P/'gap-attribution.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='examples'},indent=2))
