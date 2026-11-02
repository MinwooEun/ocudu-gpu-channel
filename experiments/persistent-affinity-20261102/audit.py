"""Audit native affinity through the entire cold start and live measurement."""
import pathlib,time,os,json,sys
p=pathlib.Path(sys.argv[1]);deadline=time.monotonic()+180;root=None
while time.monotonic()<deadline:
 for f in pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030/wire').glob('gnb-*.wire'):
  candidate=pathlib.Path('/proc',f.stem.rsplit('-',1)[1]);tasks=candidate/'task'
  if tasks.exists() and any((t/'comm').read_text().strip()=='phy_worker' for t in tasks.iterdir()):root=candidate;break
 if root:break
 time.sleep(.05)
assert root,'gNB PHY worker not found'
snapshots=[];first=None;last=None;count=0
while (root/'task').exists():
 found={}
 for t in (root/'task').glob('*'):
  try:
   name=(t/'comm').read_text().strip()
   if name in ['phy_worker','radio'] or name.startswith('main_pool#'):found[name]=dict(tid=int(t.name),cpus=sorted(os.sched_getaffinity(int(t.name))))
  except (FileNotFoundError,ProcessLookupError):pass
 if 'phy_worker' in found and 'radio' in found:
  assert found['radio']['cpus']==[6],found
  assert found['phy_worker']['cpus']==[5,7,8,9,10,11,12],found
  assert len([name for name in found if name.startswith('main_pool#')])==5,found
  assert all(6 not in r['cpus'] for name,r in found.items() if name!='radio'),found
  now=time.monotonic_ns();first=first or now;last=now;count+=1
  if not snapshots or found!=snapshots[-1]['tasks']:snapshots.append(dict(time_ns=now,tasks=found))
 time.sleep(.2)
assert count>=150,(count,first,last)
(p/'affinity-audit.json').write_text(json.dumps(dict(pid=int(root.name),checks=count,first_ns=first,last_ns=last,duration_s=(last-first)/1e9,snapshots=snapshots,status='passed'),indent=2)+'\n')
