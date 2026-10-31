"""Co-locate or separate only gNB PHY/radio, within their original CPU allocation."""
import pathlib,time,sys,json,os
p=pathlib.Path(sys.argv[1]);mode=sys.argv[2];assert mode in ['shared','separate'];deadline=time.monotonic()+240
while time.monotonic()<deadline:
 f=p/'runtime/logs/replay-applied.jsonl'
 if f.exists() and any('"k":240' in l.replace(' ','') for l in f.read_text().splitlines()):break
 time.sleep(.01)
else:raise RuntimeError('target tag not found')
tasks={}
for f in pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030/wire').glob('gnb-*.wire'):
 pid=int(f.stem.rsplit('-',1)[1]);root=pathlib.Path('/proc',str(pid),'task')
 if not root.exists():continue
 for t in root.iterdir():
  comm=(t/'comm').read_text().strip()
  if comm in ['radio','phy_worker']:tasks[comm]=int(t.name)
assert set(tasks)=={'radio','phy_worker'},tasks
start=time.monotonic_ns();changes=[]
for name,tid in tasks.items():
 old=sorted(os.sched_getaffinity(tid));target=[6] if mode=='shared' or name=='radio' else [7];assert set(target)<=set(old)
 os.sched_setaffinity(tid,target);changes.append(dict(comm=name,tid=tid,before=old,after=sorted(os.sched_getaffinity(tid))))
applied=time.monotonic_ns();time.sleep(.25)
for c in changes:os.sched_setaffinity(c['tid'],c['before'])
(p/'core-mode.json').write_text(json.dumps(dict(mode=mode,start_mono_ns=start,applied_mono_ns=applied,restored_mono_ns=time.monotonic_ns(),changes=changes,policy='No priority or CPU allocation increase; affinity restored after 250 ms'),indent=2)+'\n')
