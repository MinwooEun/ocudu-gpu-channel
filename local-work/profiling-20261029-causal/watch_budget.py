import pathlib,json,time,subprocess as sp,sys
P=pathlib.Path('/workspace/gpuch/profile-20261029-causal');case=sys.argv[1];d=P/'pr10-frozen'/case;ap=d/'runtime/logs/replay-applied.jsonl'
for _ in range(1200):
 if ap.exists():
  with ap.open('rb') as f:f.seek(max(0,ap.stat().st_size-18000));tail=f.read().decode(errors='replace')
  ks=[]
  for ln in tail.splitlines():
   try:r=json.loads(ln)
   except ValueError:continue
   if r.get('record')=='applied':ks.append(r.get('k',-1))
  if ks and 160<=max(ks)<300:
   out=sp.check_output(['python3',str(P/'thread_budget.py'),str(d)],text=True);v=json.loads(out);v['trigger_update_k']=max(ks);(P/f'thread-budget-{case}-steady.json').write_text(json.dumps(v,indent=2));break
 time.sleep(1)
else:raise SystemExit('steady window not observed')
