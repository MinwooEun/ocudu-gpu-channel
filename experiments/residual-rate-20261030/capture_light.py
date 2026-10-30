"""Record target switch-out stacks and wakeups using resolved host TIDs."""
import pathlib,time,json,subprocess as sp,re
base=pathlib.Path('/workspace/gpuch/residual-rate-20261030');p=base/'u1/original-fixed-light-r1';ram=pathlib.Path('/dev/shm/ocudu-residual-rate-20261030');deadline=time.monotonic()+240
while time.monotonic()<deadline:
 f=p/'runtime/logs/replay-applied.jsonl'
 if f.exists():
  tail=f.read_bytes()[-16384:].decode(errors='replace');ready=False
  for line in tail.splitlines():
   try:r=json.loads(line)
   except ValueError:continue
   if r.get('record')=='applied' and r.get('k',-1)>=90:ready=True
  if ready:break
 time.sleep(.2)
else:raise RuntimeError('no measurement')
actors={};targets=[]
for f in (ram/'wire').glob('*.wire'):
 pid=int(f.stem.rsplit('-',1)[1]);proc=pathlib.Path('/proc',str(pid))
 if not proc.exists():continue
 tasks=[int(t.name) for t in (proc/'task').iterdir()];actors[str(pid)]=dict(name=f.name,tasks=tasks,exe=str((proc/'exe').resolve()));targets+=(tasks if not f.name.startswith('gnb-') else []);(p/f'maps-{pid}.txt').write_text((proc/'maps').read_text())
assert len(actors)==3,actors
sp.run(['perf','record','--clockid','mono','-t',','.join(map(str,targets)),'-e','sched:sched_switch','-o',str(ram/'mapping.data'),'--','sleep','.3'],check=True,stdout=sp.DEVNULL,stderr=sp.PIPE)
raw=sp.check_output(['perf','script','--ns','-i',str(ram/'mapping.data')],text=True,stderr=sp.DEVNULL);(p/'mapping.txt').write_text(raw);mapping={}
for line in raw.splitlines():
 m=re.match(r'^\s*.*?\s+(\d+)\s+\[\d+\].*prev_pid=(\d+)',line)
 if m:mapping[int(m[1])]=int(m[2])
host=sorted(set(mapping.values()));assert len(host)>10,mapping
fdmap={}
for pid in actors:
 if 'ocudu-gpu-channel' in actors[pid]['name']:
  for f in pathlib.Path('/proc',pid,'fd').iterdir():
   try:fdmap[f.name]=str(f.resolve())
   except FileNotFoundError:pass
(p/'fdmap.json').write_text(json.dumps(fdmap,indent=2))
(p/'targets.json').write_text(json.dumps(dict(actors=actors,mapping=mapping,start_mono_ns=time.monotonic_ns()),indent=2))
fil=' || '.join(f'prev_pid == {t} || next_pid == {t}' for t in host);wake=' || '.join(f'pid == {t}' for t in host)
cmd=['perf','record','--clockid','mono','-a','-e','sched:sched_switch/call-graph=no/','--filter',fil,'-e','sched:sched_wakeup/call-graph=no/','--filter',wake,'-e','sched:sched_switch/call-graph=fp/','--filter','('+' || '.join(f'prev_pid == {t}' for t in host)+') && prev_state == 2','-e','syscalls:sys_enter_write/call-graph=no/','--filter',' || '.join(f'common_pid == {t}' for t in host),'-o',str(ram/'sched.data'),'--','sleep','30']
(p/'perf-command.json').write_text(json.dumps(cmd,indent=2))
with (p/'perf.log').open('w') as log:r=sp.run(cmd,stdout=log,stderr=sp.STDOUT)
assert r.returncode==0,(p/'perf.log').read_text()
with (p/'sched.txt').open('w') as out:sp.run(['perf','script','--ns','-i',str(ram/'sched.data')],stdout=out,stderr=sp.PIPE,check=True)
print('capture done',flush=True)
