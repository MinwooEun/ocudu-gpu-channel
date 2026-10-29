import pathlib,time,subprocess as sp
P=pathlib.Path('/workspace/gpuch/profile-20261029-causal')
for _ in range(1800):
 if (P/'pr10-frozen/baseline-repeat/result.json').exists():
  if not sp.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip():break
 time.sleep(1)
else:raise SystemExit('preceding campaign did not finish')
with (P/'pr10-frozen-repeat.log').open('w') as f:
 sp.run(['python3',str(P/'pr10_frozen.py'),'trace-repeat'],stdout=f,stderr=f,check=True)
