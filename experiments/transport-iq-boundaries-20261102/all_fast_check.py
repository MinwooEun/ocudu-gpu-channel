import pathlib,time,os,json
W=pathlib.Path(__file__).resolve().parent
while not (W/'complete.json').exists():time.sleep(2)
spark=str(W).startswith('/workspace');os.environ.update(BOUND_PROFILE='all-fast-iq',BOUND_CHANNEL_CPUS='5-9,15-19' if spark else '0-7')
from run_case import run_case
results=[]
for rep in [1,2,3]:
 results.append(run_case('iq',n=64,rep=rep));(W/'all-fast-check.json').write_text(json.dumps(results,indent=2))
print('ALL FAST CHECK COMPLETE',flush=True)
