import numpy as np, pathlib, json, sys
root=pathlib.Path(sys.argv[1]); streams={}; meta=[]
names=['op','tid','port','flags','start','end','result','error']; dt=np.dtype([(x,'<i8') for x in names])
for f in sorted((root/'wire').glob('*.wire')):
 h=np.fromfile(f,dtype='<u8',count=8);n=min(int(h[1]),int(h[2]));a=np.memmap(f,dtype=dt,offset=64,shape=(n,),mode='r');a=a[a['op']!=0]
 meta.append(dict(file=f.name,n=n,dropped=int(h[3]),ports=np.unique(a['port']).tolist()))
 for port in np.unique(a['port']):
  if port<1024:continue
  z=a[a['port']==port]
  for op in (1,2):
   for kind in ('request','iq'):
    b=z[(z['op']==op)&((z['result']==1) if kind=='request' else (z['result']>=8))]
    if len(b):streams.setdefault(int(port),{}).setdefault((op,kind),[]).append((f.name,b.copy()))
def stats(v):return dict(mean_us=float(np.mean(v)/1e3),p50_us=float(np.median(v)/1e3),p95_us=float(np.percentile(v,95)/1e3))
results=[]
for port,s in streams.items():
 keys=[(1,'request'),(2,'request'),(1,'iq'),(2,'iq')]
 if any(k not in s for k in keys):continue
 # Multiple cold runs have different PIDs. Match overlapping process lifetimes.
 for request_file,q in s[keys[0]]:
  matches=[]
  for k in keys[1:]:
   cand=[(fn,a) for fn,a in s[k] if a['end'][-1]>=q['start'][0] and a['start'][0]<=q['end'][-1]]
   if len(cand)!=1:break
   matches.append(cand[0])
  if len(matches)!=3:continue
  (rf,r),(sf,t),(df,d)=matches
  # IQ payloads pair by ordered message bytes; requests pair by successful REQ/REP order.
  nt=min(len(t),len(d));t=t[:nt];d=d[:nt]
  ri=np.searchsorted(r['end'],t['start'],side='right')-1
  valid=(ri>=0)&(ri<len(q)-1)
  t=t[valid];d=d[valid];ri=ri[valid];r=r[ri];next_requests=q['start'][ri+1];q=q[ri];n=len(t)
  if n<100:continue
  assert np.array_equal(t['result'][:n],d['result'][:n]), (port,'IQ byte mismatch')
  # Fixed sample interval after startup: use last 10 seconds, excluding final 1 second.
  low=max(q['start'][0]+20e9,q['start'][n-1]-11e9);high=q['start'][n-1]-1e9
  sel=(q['start'][:n]>=low)&(q['start'][:n]<high)
  if sel.sum()<100:continue
  a=q[:n][sel];b=r[:n][sel];c=t[:n][sel];e=d[:n][sel];nextq=next_requests[sel]
  times=dict(request_to_responder=b['end']-a['start'],responder_to_iqsend=c['start']-b['end'],iqsend_to_recv=e['end']-c['start'],recv_to_nextrequest=nextq-e['end'],cycle=nextq-a['start'],responder_late_enter=np.maximum(0,b['start']-a['start']),send_call=c['end']-c['start'])
  results.append(dict(port=port,requester=request_file,responder=sf,count=int(sel.sum()),samples=int(c['result'].sum()/8),start_ns=int(a['start'][0]),end_ns=int(nextq[-1]),metrics={k:stats(v) for k,v in times.items()},negative_intervals={k:int((v<0).sum()) for k,v in times.items()}))
print(json.dumps(dict(files=meta,links=results),indent=2))
