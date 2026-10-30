"""One-run causal intervention: IO above STACK, below WORKER/SYNC; same CPU mask."""
import pathlib,os,time,json
base=pathlib.Path('/workspace/gpuch/receiver-quality-20261030');target=base/'local-noise-build/srsue';out=pathlib.Path('/workspace/gpuch/residual-rate-20261030/u1/original-io-pacer-r1');deadline=time.monotonic()+180
while time.monotonic()<deadline:
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   try:exe=(p/'exe').resolve()
   except PermissionError:continue
   if exe!=target:continue
   for t in (p/'task').iterdir():
    if not (t/'comm').read_text().strip().startswith('ZMQbg/IO/'):continue
    tid=int(t.name);before=dict(policy=os.sched_getscheduler(tid),priority=os.sched_getparam(tid).sched_priority,cpus=sorted(os.sched_getaffinity(tid)))
    os.sched_setscheduler(tid,os.SCHED_FIFO,os.sched_param(95));after=dict(policy=os.sched_getscheduler(tid),priority=os.sched_getparam(tid).sched_priority,cpus=sorted(os.sched_getaffinity(tid)));assert before['cpus']==after['cpus']
    out.mkdir(parents=True,exist_ok=True);(out/'io-priority.json').write_text(json.dumps(dict(pid=int(p.name),tid=tid,before=before,after=after,monotonic_ns=time.monotonic_ns()),indent=2));print('applied',tid,before,after,flush=True);raise SystemExit(0)
  except (FileNotFoundError,ProcessLookupError):continue
 time.sleep(.2)
raise RuntimeError('UE IO thread was not found')
