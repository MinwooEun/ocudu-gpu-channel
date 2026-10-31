"""Replay the previous analyzer workload, with explicitly recorded CPU affinity."""
import pathlib,sys,json,os,time,subprocess as sp
p=pathlib.Path(sys.argv[1]);mode=sys.argv[2];assert mode in ['unrestricted','aux'];src=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030/u1/original-cv-ue-sched-r3');work=p/'analysis-workload';work.mkdir(exist_ok=True)
for name in ['raw','sched.txt','room','downlink-analysis.json']:
 link=work/name
 if not link.exists():link.symlink_to(src/name,target_is_directory=(src/name).is_dir())
deadline=time.monotonic()+240
while time.monotonic()<deadline:
 f=p/'runtime/logs/replay-applied.jsonl'
 if f.exists() and any('"k":240' in line.replace(' ','') for line in f.read_text().splitlines()):break
 time.sleep(.02)
else:raise RuntimeError('target tag not found')
mask='0-19' if mode=='unrestricted' else '0-4';cmd=['sudo','-n','taskset','-c',mask,'/workspace/sionna-venv/bin/python','/workspace/gpuch/one-ue-realtime-20261030/analyze_causes.py',str(work)];start=time.monotonic_ns();start_wall=time.time_ns()
with (p/'analysis-workload.log').open('w') as log:
 proc=sp.Popen(cmd,stdout=log,stderr=sp.STDOUT);threads={}
 while proc.poll() is None:
  for task in pathlib.Path('/proc',str(proc.pid),'task').glob('*'):
   try:threads[int(task.name)]=dict(cpus=sorted(os.sched_getaffinity(int(task.name))),comm=(task/'comm').read_text().strip())
   except (ProcessLookupError,FileNotFoundError):pass
  time.sleep(.005)
assert proc.returncode==0,(p/'analysis-workload.log').read_text()
(p/'interference.json').write_text(json.dumps(dict(mode=mode,mask=mask,pid=proc.pid,start_mono_ns=start,end_mono_ns=time.monotonic_ns(),start_unix_ns=start_wall,command=cmd,threads=threads,original_analyzer_output_mtime_ns=(src/'causes.json').stat().st_mtime_ns),indent=2)+'\n')
