import pathlib,os,time
_wait_root=pathlib.Path(__file__).resolve().parent
while not (_wait_root/'complete.json').exists():time.sleep(2)
os.environ.update(BOUND_PROFILE='ready-start-iq',BOUND_IQ_BINARY='iq-capacity-ready')
"""Four one-factor scaling axes, common static channel, then boundary repeats."""
import pathlib,json,time
from run_case import run_case,W,HOST
inventory=[];slices=[]
def trial(mode,n=1,c=1,bw=20,a=1,rep=1):
 r=run_case(mode,n,c,bw,a,rep);key=r['label']
 if not any(x['label']==key for x in inventory):inventory.append({k:v for k,v in r.items() if k!='details'})
 (W/'inventory-ready.json').write_text(json.dumps(inventory,indent=2));return r
def good(r):return r.get('cadence_covered_with_one_boundary_batch',False)
def search(mode,axis,values,extra=None):
 extra=extra or {};points={}
 def evaluate(v,rep=1):
  kw=dict(extra);kw[axis]=v;return trial(mode,rep=rep,**kw)
 for v in values:
  points[v]=evaluate(v)
 # Refine only the integer gap adjoining an observed passing/failing pair.
 passes=[v for v,r in points.items() if good(r)];lo=max(passes) if passes else None
 fails=[v for v,r in points.items() if not good(r) and (lo is None or v>lo)];hi=min(fails) if fails else None
 if lo is not None and hi is not None:
  while hi-lo>1:
   mid=(hi+lo)//2;points[mid]=evaluate(mid)
   if good(points[mid]):lo=mid
   else:hi=mid
 # Repeat both sides; keep every miss instead of treating an average as a zero-miss proof.
 repeat=[]
 for v in [lo,hi]:
  if v is not None:
   for rep in [2,3]:repeat.append(evaluate(v,rep))
 result=dict(host=HOST,mode=mode,axis=axis,fixed=extra,observed_pass=lo,observed_fail=hi,scanned=sorted(points),replicates=[{k:v for k,v in r.items() if k!='details'} for r in repeat],interpretation='Cadence coverage counts expected batches minus one finite-window boundary batch; every pacing rebase/deadline miss is reported separately. Observed boundary is conditional on CPU placement and this finite window.')
 slices.append(result);(W/'boundaries-ready.json').write_text(json.dumps(slices,indent=2))
for mode in ['iq']:
 search(mode,'n',[1,4,8,16,32,64])
 # Extend a passing UE upper bound; avoid calling64 a maximum when it still fits.
 if good(trial(mode,n=64)):
  r=trial(mode,n=128)
  if good(r):trial(mode,n=256)
 for bw in [20,50,100]:trial(mode,n=4,bw=bw)
 search(mode,'a',[1,2,4,8,16])
 search(mode,'c',[1,2,4,8,16],extra=dict(n=4))
print('CAMPAIGN COMPLETE',HOST,flush=True)
(W/'complete-ready.json').write_text(json.dumps(dict(host=HOST,completed_unix_ns=time.time_ns(),cases=len(inventory)),indent=2))

import run_case as engine
engine.PROFILE='all-fast-iq-ready'
engine.BROKER_CPUS='5-9,15-19' if HOST=='spark' else '0-7'
results=[]
for rep in [1,2,3]:
 results.append(engine.run_case('iq',n=64,rep=rep));(W/'all-fast-check-ready.json').write_text(json.dumps(results,indent=2))
(W/'all-ready-complete.json').write_text(json.dumps(dict(host=HOST,cases=len(inventory),unix_ns=time.time_ns())))
