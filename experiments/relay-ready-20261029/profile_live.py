"""Instrumented diagnostic only: sample actual broker CPU stacks after attach."""
import json,os,pathlib,subprocess as sp,time
P=pathlib.Path('/workspace/gpuch/relay-ready-20261029');case=P/'live-pr10/fd-profile'
if case.exists():raise RuntimeError('profile case already exists')
with (P/'live-profile.log').open('w') as log:
 run=sp.Popen(['python3',str(P/'live.py'),'fd-profile'],stdout=log,stderr=sp.STDOUT)
 # Pin only this observer after launch; preserve the runtime/MPS affinity.
 os.sched_setaffinity(0,set(range(5)))
 deadline=time.monotonic()+300
 while time.monotonic()<deadline:
  if run.poll() is not None:raise RuntimeError('run exited before capture')
  output=case/'runner.log'
  if output.exists() and 'event=measure_release ' in output.read_text():break
  time.sleep(.25)
 else:raise RuntimeError('measurement release timed out')
 candidates=[]
 for proc in pathlib.Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:cmd=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode()
  except (OSError,UnicodeError):continue
  if cmd.startswith(str(P/'build-fd/ocudu-gpu-channel')+' ') and str(case) in cmd:candidates.append(int(proc.name))
 if len(candidates)!=1:raise RuntimeError(f'broker PID candidates {candidates}')
 command=['perf','record','-e','cycles:u','-F','199','--call-graph','dwarf,8192','-p',str(candidates[0]),'-o',str(case/'perf.data'),'--','sleep','3']
 (case/'profile-metadata.json').write_text(json.dumps(dict(command=command,diagnostic_only=True,performance_comparison_excluded=True),indent=2))
 with (case/'perf-record.log').open('w') as perf_log:sp.run(command,stdout=perf_log,stderr=sp.STDOUT,check=True)
 with (case/'perf-report.txt').open('w') as report:sp.run(['perf','report','--stdio','--no-children','--sort','dso,symbol','-i',str(case/'perf.data')],stdout=report,stderr=sp.STDOUT,check=True)
 print('PROFILE_CAPTURED',flush=True)
 rc=run.wait();print('RUN_END',rc,flush=True)
