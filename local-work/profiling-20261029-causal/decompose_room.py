import pathlib,sys,csv,json,collections,numpy as np
from wire_sources import load
P=pathlib.Path(sys.argv[1]);r=json.load(open(P/'runtime/report/run-report.json'));lo=r['epoch']['s0']+10*23040000;hi=r['epoch']['s0']+40*23040000
A=collections.defaultdict(list)
with (P/'hop/hop-trace.csv').open() as f:
 for x in csv.DictReader(f):
  ev=int(x['event'])
  if x['id'] in ('gnb0','gnb0_p0') and ev in (10,11,20,21,22):A[x['role'],ev].append((int(x['t_ns']),int(x['samples'])))
A={k:np.array(v,dtype='i8') for k,v in A.items()};rows=None
for f in (P/'trace').glob('broker*'):
 with f.open() as z:
  rr=list(csv.DictReader(z))
 if rr and rr[0]['node']=='gnb0':rows=rr;break
assert rows
counts=np.array([int(x['samples']) for x in rows]);seq=np.cumsum(counts)-counts;ready=A['producer',10];assert np.array_equal(ready[:,1],counts)
end=ready[:,0]-1000*np.array([float(x['data_us'])+float(x['align_us']) for x in rows]);begin=end-1000*np.array([float(x['room_us']) for x in rows]);sel=(seq>=lo)&(seq<hi)
sent=A['rep',22];cum=np.cumsum(sent[:,1]);ix=np.searchsorted(cum,seq-23040,side='right');ix=np.minimum(ix,len(sent)-1)
req=None
for f in (P/'wire').glob('gnb*'):
 a=load(f);q=a[(a['op']==1)&(a['port']==2001)&(a['result']==1)]
 if len(q)>100:req=q;break
assert req is not None
release=sent[ix,0];qs=req['start'][ix];qr=A['rep',20][ix,0];pop=A['rep',21][ix,0]
# Before the first full ring, it already has room; these startup calls are outside measurement.
points=[begin,np.clip(qs,begin,end),np.clip(qr,begin,end),np.clip(pop,begin,end),np.clip(release,begin,end),end]
parts=np.diff(np.array(points),axis=0);ms=counts[sel].sum()/23040
out=dict(radio_ms=float(ms),room_us_per_radio_ms=float((end-begin)[sel].sum()/1000/ms),parts_us_per_radio_ms={k:float(v[sel].sum()/1000/ms) for k,v in zip(['before_gnb_request','request_to_broker_receive','request_received_to_row_pop','row_pop_to_send_and_release','room_released_to_producer_observed'],parts)},negative_parts=[int((v[sel]<-1000).sum()) for v in parts],max_release_timestamp_race_us=float(np.maximum(release[sel]-end[sel],0).max()/1000))
print(json.dumps(out,indent=2))
