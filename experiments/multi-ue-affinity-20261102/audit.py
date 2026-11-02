import pathlib,time,os,json,sys
p=pathlib.Path(sys.argv[1]);enabled=sys.argv[2]=='on';deadline=time.monotonic()+300;root=None
while time.monotonic()<deadline:
 for f in pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030/wire').glob('gnb-*.wire'):
  r=pathlib.Path('/proc',f.stem.rsplit('-',1)[1])
  try:
   if (r/'task').exists() and any((t/'comm').read_text().strip()=='phy_worker' for t in (r/'task').iterdir()):root=r;break
  except FileNotFoundError:pass
 if root:break
 time.sleep(.05)
assert root,'gNB worker not found'
snapshots=[];count=0;first=None;last=None
while (root/'task').exists():
 found={}
 for t in (root/'task').glob('*'):
  try:
   name=(t/'comm').read_text().strip()
   if name in ['radio','phy_worker'] or name.startswith('main_pool#'):found[name]=dict(tid=int(t.name),cpus=sorted(os.sched_getaffinity(int(t.name))))
  except (FileNotFoundError,ProcessLookupError):pass
 if 'radio' in found and 'phy_worker' in found:
  assert found['radio']['cpus']==([6] if enabled else list(range(5,13))),found
  assert found['phy_worker']['cpus']==([5,7,8,9,10,11,12] if enabled else list(range(5,13))),found
  if enabled:assert all(6 not in v['cpus'] for k,v in found.items() if k!='radio'),found
  now=time.monotonic_ns();first=first or now;last=now;count+=1
  if not snapshots or found!=snapshots[-1]['tasks']:snapshots.append(dict(time_ns=now,tasks=found))
 time.sleep(.5)
assert count>20,count
(p/'affinity-audit.json').write_text(json.dumps(dict(enabled=enabled,checks=count,duration_s=(last-first)/1e9,snapshots=snapshots,status='passed'),indent=2)+'\n')
