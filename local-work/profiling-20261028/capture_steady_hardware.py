from pathlib import Path
import json,subprocess as sp,time
P=Path('/workspace/gpuch/profile-20261028/live/cuda-u16-c1-bw20-a1x1-cpu-sampled')
trigger=P/'perf-steady-02-test2.json'
deadline=time.monotonic()+300
while not trigger.exists() and time.monotonic()<deadline:time.sleep(.5)
if not trigger.exists():raise SystemExit('Second steady-window trigger missing')
r=json.loads(trigger.read_text());out=P/'perf-hardware-steady-02-test2.data'
command=['taskset','-c','0-4','perf','record','-F','49','-g','--call-graph','dwarf,4096','-p',','.join(r['target_pids']),'-o',str(out),'--','sleep','12']
(P/'perf-hardware-steady-02-test2.json').write_text(json.dumps(dict(target_pids=r['target_pids'],trigger=str(trigger),start_monotonic_ns=time.monotonic_ns(),event='default hardware cycles, separate PMUs on heterogeneous CPU'),indent=2))
with (P/'perf-hardware-steady-02-test2.log').open('w') as f:done=sp.run(command,stdout=f,stderr=sp.STDOUT)
raise SystemExit(done.returncode)
