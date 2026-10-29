from pathlib import Path
import time,json,subprocess as sp,mmap,struct
P=Path('/workspace/gpuch/profile-20261029-deep');d=P/'runs/deep16';gate=P/'capture.gate';gate.write_bytes(bytes(4096));trace=Path('/sys/kernel/tracing/instances/ocg_deep_20261029');trace.mkdir(exist_ok=True)
def put(n,v):(trace/n).write_text(str(v))
put('tracing_on',0);put('trace_clock','mono');put('buffer_size_kb',32768)
for event in ('sched_switch','sched_wakeup','sched_wakeup_new'):put('events/sched/'+event+'/enable',1)
(trace/'trace').write_text('')
try:
 for _ in range(600):
  f=d/'runtime/logs/replay-applied.jsonl'
  if f.exists():
   with f.open('rb') as q:q.seek(max(0,f.stat().st_size-18000));tail=q.read().decode(errors='replace')
   ks=[]
   for ln in tail.splitlines():
    try:r=json.loads(ln)
    except ValueError:continue
    if r.get('record')=='applied':ks.append(r.get('k',-1))
   if ks and 160<=max(ks)<300:break
  time.sleep(.5)
 else:raise RuntimeError('no steady window')
 with gate.open('r+b') as f:
  g=mmap.mmap(f.fileno(),4096);put('tracing_on',1);a=time.monotonic_ns();g[:4]=struct.pack('I',1);time.sleep(2);g[:4]=struct.pack('I',0);b=time.monotonic_ns();put('tracing_on',0);g.close()
 (P/'capture-window.json').write_text(json.dumps(dict(start_ns=a,end_ns=b,trigger_k=max(ks),clock='CLOCK_MONOTONIC',trace_clock=(trace/'trace_clock').read_text()),indent=2))
 with (P/'scheduler.trace').open('wb') as f:
  sp.run(['cat',str(trace/'trace')],stdout=f,check=True)
 (P/'scheduler-stats.json').write_text(json.dumps({str(p.parent.name):p.read_text() for p in (trace/'per_cpu').glob('*/stats')},indent=2))
finally:
 put('tracing_on',0)
 for event in ('sched_switch','sched_wakeup','sched_wakeup_new'):put('events/sched/'+event+'/enable',0)
