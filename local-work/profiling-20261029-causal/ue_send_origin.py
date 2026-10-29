import pathlib,sys,numpy as np,json
from wire_sources import load
P=pathlib.Path(sys.argv[1]);report=json.load(open(sys.argv[2]));e=report['epoch'];lo=e['s0']+10*23040000;hi=e['s0']+40*23040000
out=[]
for f in (P/'wire').glob('srsue*'):
 a=load(f);t=a[(a['op']==1)&(a['result']>=8)];samples=t['result']//8;seq=np.cumsum(samples)-samples;sel=(seq>=lo)&(seq<hi)
 if sel.sum()<100:continue
 # Discard other cold execution using report release wall timestamp and file clock pair.
 h=np.fromfile(f,dtype='<u8',count=8);release_mono=e['release_unix_ns']-int(h[6])+int(h[5]);
 if not (t['start'][0]<release_mono<t['end'][-1]):continue
 t=t[sel];samples=samples[sel];kind=np.zeros(len(t),dtype=int)
 for op in (30,32):
  z=a[a['op']==op];z=z[np.argsort(z['start'])]
  for tid in np.unique(t['tid']):
   ids=np.where(t['tid']==tid)[0];v=z[z['tid']==tid]
   if not len(v):continue
   ix=np.searchsorted(v['start'],t['start'][ids],side='right')-1;good=(ix>=0);ix=np.maximum(ix,0);good&=v['end'][ix]>=t['end'][ids];kind[ids[good]]=op
 out.append(dict(file=f.name,counts={str(op):int((kind==op).sum()) for op in (0,30,32)},sample_fraction={str(op):float(samples[kind==op].sum()/samples.sum()) for op in (0,30,32)}))
print(json.dumps(out,indent=2))
