import pathlib,time,subprocess as sp,json
P=pathlib.Path('/workspace/gpuch/profile-20261029-causal');active=pathlib.Path('/workspace/ocudu-spark-ranb/results/single-cell-scheduler-benchmark/active')
for _ in range(300):
 files=list(active.glob('policy_runs/01-test1/logs/replay-applied.jsonl'))
 if files:
  tail=files[0].read_text()[-20000:]
  ready=False
  for ln in tail.splitlines():
   try:r=json.loads(ln)
   except ValueError:continue
   if r.get('record')=='applied' and 130<=r.get('k',-1)<300:ready=True
  if ready:
   d=P/'scheduler-full';d.mkdir(exist_ok=True)
   (d/'start.json').write_text(json.dumps({'mono_ns':time.monotonic_ns(),'real_ns':time.time_ns(),'trigger':'first policy, applied k >= 130'}))
   with (d/'perf.log').open('w') as f:rc=sp.run(['perf','record','-a','-C','15,16','-e','sched:sched_switch','-o',str(d/'sched.data'),'--','sleep','4'],stdout=f,stderr=f).returncode
   (d/'end.json').write_text(json.dumps({'mono_ns':time.monotonic_ns(),'returncode':rc}))
   break
 time.sleep(1)
else:raise SystemExit('No steady window found')
