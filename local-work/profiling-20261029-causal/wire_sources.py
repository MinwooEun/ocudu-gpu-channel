import numpy as np,pathlib
names=['op','tid','port','flags','start','end','result','error'];dt=np.dtype([(x,'<i8') for x in names])
_cache={}
_requests={}
def load(f):
 if str(f) in _cache:return _cache[str(f)]
 h=np.fromfile(f,dtype='<u8',count=8)
 if h[3]:raise RuntimeError(f'trace dropped {h[3]}: {f}')
 a=np.memmap(f,dtype=dt,offset=64,shape=(int(h[1]),),mode='r');_cache[str(f)]=a;return a
def source_stages(P,A,sources,sample):
 files=list((P/'wire').glob('*.wire'));stages=[];checks=[]
 for src in sources:
  port=2000 if src=='gnb0_p0' else 2101+2*int(src.split('_')[0][2:])
  b=A['puller',src,1];q=A['puller',src,0];c=np.cumsum(b[:,1]);ix=np.searchsorted(c,sample,side='right')
  candidates=[]
  for f in files:
   if not f.name.startswith('gnb-' if src=='gnb0_p0' else 'srsue-'):continue
   a=load(f);t=a[(a['op']==1)&(a['port']==port)&(a['result']>=8)]
   if len(t) and t['start'][0]<=b[0,0] and t['end'][-1]>=b[0,0]:candidates.append((f,a,t))
  assert len(candidates)==1,(src,[f.name for f,_,_ in candidates])
  f,a,t=candidates[0];n=min(len(t),len(b),len(A['puller',src,2]));assert np.array_equal(t['result'][:n]//8,b[:n,1]),(src,'sample mismatch')
  ix=np.minimum(ix,n-1);send=t['start'][ix]
  if src=='gnb0_p0':
   p=a[a['op']==41];p=p[np.argsort(p['end'])];cum=np.cumsum(p['result']);pi=np.searchsorted(cum,sample,side='right');pi=np.minimum(pi,len(p)-1)
   ready=p['start'][pi];ready_end=p['end'][pi];readiness='gnb transmit_samples entry (IQ already generated)'
  else:
   r=a[(a['op']==2)&(a['port']==port)&(a['result']==1)];ri=np.searchsorted(r['end'],t['start'],side='right')-1;assert (ri>=0).all()
   ready=r['start'][ri[ix]];ready_end=r['end'][ri[ix]];readiness='UE TX request-receive entry (inside baseband send, IQ prepared)'
  key=(str(P),port,int(b[0,0]))
  if key not in _requests:
   found=[]
   for bf in files:
    if not bf.name.startswith('ocudu-gpu-channel-'):continue
    ba=load(bf);bq=ba[(ba['op']==1)&(ba['port']==port)&(ba['result']==1)]
    if len(bq) and bq['start'][0]<=b[0,0] and bq['end'][-1]>=b[0,0]:found.append(bq)
   assert len(found)==1,(port,'broker request stream')
   _requests[key]=found[0]
  qw=_requests[key];assert len(qw)>=n
  stages.append(np.array([qw['start'][ix],ready,send,b[ix,0]]))
  checks.append(dict(source=src,file=f.name,matched_iq_messages=n,readiness=readiness,ready_after_send=int((ready>send).sum()),ring_insert_before_recv=int((A['puller',src,2][:n,0]<b[:n,0]).sum())))
 return np.array(stages),checks
