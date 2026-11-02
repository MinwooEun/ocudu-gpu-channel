import pathlib,time,json
W=pathlib.Path(__file__).resolve().parent
while not (W/'all-ready-complete.json').exists():time.sleep(2)
import run_case as engine
HOST=engine.HOST
engine.PROFILE='counter-off-radio'
engine.PROBE_ENABLED=False
engine.BROKER_CPUS='5-9' if HOST=='spark' else '0-4'
original=json.loads((W/'boundaries.json').read_text())
ue=next(x for x in original if x['mode']=='radio' and x['axis']=='n')
points=sorted(set([v for v in [ue.get('observed_pass'),ue.get('observed_fail'),16] if v is not None]))
controls=[]
for n in points:
 for rep in [1,2]:
  controls.append(engine.run_case('radio',n=n,rep=rep));(W/'counter-off-check.json').write_text(json.dumps(controls,indent=2))
(W/'final-complete.json').write_text(json.dumps(dict(host=HOST,unix_ns=time.time_ns())))
