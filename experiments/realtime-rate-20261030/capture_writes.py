"""Observe write syscall durations on the two producer TIDs without ptrace."""
import pathlib,time,json,subprocess,csv
p=pathlib.Path('/workspace/gpuch/realtime-rate-20261030/u1/original-profile-r1');deadline=time.monotonic()+240
while time.monotonic()<deadline:
 f=p/'runtime/logs/replay-applied.jsonl';ready=False
 if f.exists():
  with f.open('rb') as h:h.seek(max(0,f.stat().st_size-16384));tail=h.read().decode(errors='replace')
  for line in tail.splitlines():
   try:r=json.loads(line)
   except ValueError:continue
   if r.get('record')=='applied' and r.get('k',-1)>=100:ready=True
 if ready:break
 time.sleep(.2)
else:raise RuntimeError('post-warmup window not found')
targets=[]
for f in (p/'trace').glob('channel-*.csv'):
 with f.open() as h:
  row=next(csv.DictReader(h),None)
 if row:targets.append(dict(pid=int(f.stem.split('-')[1]),tid=int(f.stem.split('-')[2]),node=row['node']))
assert len(targets)==2,targets
fdmap={}
for t in targets:
 for f in pathlib.Path('/proc',str(t['pid']),'fd').iterdir():
  try:fdmap[f.name]=str(f.resolve())
  except FileNotFoundError:pass
(p/'write-targets.json').write_text(json.dumps(dict(targets=targets,fdmap=fdmap,start_monotonic_ns=time.monotonic_ns()),indent=2))
cmd=['perf','record','--clockid','mono','-e','syscalls:sys_enter_write','-e','syscalls:sys_exit_write','-t',','.join(str(t['tid']) for t in targets),'-o',str(p/'writes.data'),'--','sleep','20']
with (p/'writes-perf.log').open('w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
print('perf_rc',r.returncode,flush=True)
if r.returncode:raise RuntimeError((p/'writes-perf.log').read_text())
with (p/'writes.txt').open('w') as out:subprocess.run(['perf','script','--ns','-i',str(p/'writes.data')],stdout=out,stderr=subprocess.PIPE,check=True)
