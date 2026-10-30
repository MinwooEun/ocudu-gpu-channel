"""Observe write syscall durations on the two producer TIDs without ptrace."""
import pathlib,time,json,subprocess,csv
p=pathlib.Path('/workspace/gpuch/realtime-rate-20261030/u1/original-input-root2-r2');deadline=time.monotonic()+240
while time.monotonic()<deadline:
 f=p/'runtime/logs/replay-applied.jsonl';ready=False
 if f.exists():
  with f.open('rb') as h:h.seek(max(0,f.stat().st_size-16384));tail=h.read().decode(errors='replace')
  for line in tail.splitlines():
   try:r=json.loads(line)
   except ValueError:continue
   if r.get('record')=='applied' and r.get('k',-1)>=100:ready=True
 if ready:break
 time.sleep(.2)
else:raise RuntimeError('post-warmup window not found')
cmd=['perf','record','--clockid','mono','-a','-C','17','-e','sched:sched_switch']
for name in ['dl','ul','work','end']:
 for suffix in ['', '_ret__return']:cmd+=['-e','probe_srsue:ocudurate_'+name+suffix]
cmd+=['-o',str(p/'ue-functions.data'),'--','sleep','20']
with (p/'ue-functions-perf.log').open('w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
assert r.returncode==0,(p/'ue-functions-perf.log').read_text()
with (p/'ue-functions.txt').open('w') as out:subprocess.run(['perf','script','--ns','-i',str(p/'ue-functions.data')],stdout=out,stderr=subprocess.PIPE,check=True)
print('capture complete',flush=True)
