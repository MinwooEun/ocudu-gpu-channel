import csv,json,sys,pathlib,collections,numpy as np
P=pathlib.Path(sys.argv[1]);hop=pathlib.Path(sys.argv[2]);pid=sys.argv[3]
events=collections.defaultdict(list)
with hop.open() as f:
 for r in csv.DictReader(f):
  ev=int(r['event'])
  if (r['role']=='puller' and ev in (0,1,2)) or (r['role']=='producer' and ev==10):events[(r['role'],r['id'],ev)].append((int(r['t_ns']),int(r['samples'])))
A={k:np.array(v,dtype=np.int64) for k,v in events.items()};out=[]
files=list((P/'trace').glob(f'broker-{pid}-*.csv'));assert files, ('no broker trace',pid)
for f in files:
 rows=list(csv.DictReader(f.open()));node=rows[0]['node'];ready=A['producer',node,10];n=min(len(rows),len(ready));rows=rows[:n];ready=ready[:n]
 counts=np.array([int(r['samples']) for r in rows]);assert np.array_equal(counts,ready[:,1]);sample=np.cumsum(counts)-counts
 sources=sorted(k[1] for k in A if k[0]=='puller' and k[2]==2 and ((node=='gnb0' and k[1].startswith('ue')) or (node!='gnb0' and k[1]=='gnb0_p0')))
 arrival=[];recv=[];req=[]
 for src in sources:
  a=A['puller',src,2];c=np.cumsum(a[:,1]);ix=np.searchsorted(c,sample,side='right');ix=np.minimum(ix,len(a)-1);arrival.append(a[ix,0])
  b=A['puller',src,1];assert np.array_equal(a[:,1],b[:len(a),1]);recv.append(b[ix,0])
  q=A['puller',src,0];req.append(q[ix,0])
 arrival=np.array(arrival);recv=np.array(recv);req=np.array(req);critical=np.argmax(arrival,axis=0);col=np.arange(n);available=arrival[critical,col];received=recv[critical,col];requested=req[critical,col]
 duration=np.array([float(r['data_us'])*1000 for r in rows]);end=ready[:,0];begin=end-duration
 # Prefer the actual gate's post-warmup measurement sample epoch.
 if len(sys.argv)>4:
  epoch=json.load(open(sys.argv[4]))['epoch'];lo=epoch['s0']+10*23040000;hi=epoch['s0']+40*23040000
 else:lo,hi=25*23040000,45*23040000
 good=(sample>=lo)&(sample<hi)
 cuts=[begin,np.clip(requested,begin,end),np.clip(received,begin,end),np.clip(available,begin,end),end]
 parts=np.diff(np.array(cuts),axis=0);assert parts[:,good].min()>-50000,parts[:,good].min()
 radio_ms=counts[good].sum()/23040
 detail={}
 if '--wire' in sys.argv:
  from wire_sources import source_stages
  ws,checks=source_stages(P,A,sources,sample)
  st=ws[critical,:,col].T
  # Request and production can overlap. Attribute only the portion inside the observed wait.
  milestones=[begin,np.clip(st[0],begin,end),np.clip(np.maximum(st[0],st[1]),begin,end),np.clip(st[2],begin,end),np.clip(st[3],begin,end),np.clip(available,begin,end),end]
  detailed=np.diff(np.array(milestones),axis=0)
  detail=dict(wire_checks=checks,wire_parts_us_per_radio_ms={k:float(v[good].sum()/1000/radio_ms) for k,v in zip(['before_request','source_not_yet_at_send_boundary','source_ready_to_send','send_to_receiver_return','receiver_return_to_ring','ring_ready_to_producer'],detailed)},negative_wire_parts={k:int((v[good]<-1000).sum()) for k,v in zip(['request','ready','send','receive','ring','producer'],detailed)})
 out.append(dict(**detail,node=node,calls=int(good.sum()),radio_ms=float(radio_ms),data_us_per_radio_ms=float(duration[good].sum()/1000/radio_ms),parts_us_per_radio_ms={k:float(v[good].sum()/1000/radio_ms) for k,v in zip(['before_request','request_until_receive','receive_until_ring_push','ring_ready_until_producer_observed'],parts)},critical_source_counts=dict(collections.Counter(np.array(sources)[critical[good]])),negative_ready_intervals=int((available[good]>end[good]).sum()),max_ring_timestamp_race_us=float(np.maximum(available[good]-end[good],0).max()/1000),sample_window=[int(lo),int(hi)]))
print(json.dumps(out,indent=2))
