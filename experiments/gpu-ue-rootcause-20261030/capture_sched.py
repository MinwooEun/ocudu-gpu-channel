"""Capture one benchmark UE's wakeups and CPU 17 switches in private ftrace instances."""
import json,pathlib,time,os
base=pathlib.Path('/workspace/gpuch/gpu-ue-rootcause-20261030/u8/gpu-cpu-nsys-r1');out=base/'sched';out.mkdir(parents=True,exist_ok=True)
pidfile=base/'nsys/ue.pid';deadline=time.monotonic()+300
while not pidfile.exists():
 if time.monotonic()>deadline:raise RuntimeError('UE launch not observed')
 time.sleep(.2)
pid=int(pidfile.read_text());time.sleep(30)
threads={}
for t in pathlib.Path(f'/proc/{pid}/task').iterdir():
 status=dict(x.split(':',1) for x in (t/'status').read_text().splitlines() if ':' in x)
 sched=dict(x.split(':',1) for x in (t/'sched').read_text().splitlines() if ':' in x)
 threads[int(t.name)]=dict(comm=(t/'comm').read_text().strip(),cpus=status.get('Cpus_allowed_list','').strip(),policy=sched.get('policy','').strip(),prio=sched.get('prio','').strip())
root=pathlib.Path('/sys/kernel/tracing/instances');instances=[]
try:
 for name in ['switch','wake']:
  p=root/f'ocudu_ue_{pid}_{name}';p.mkdir();instances.append(p)
  (p/'tracing_on').write_text('0');(p/'trace_clock').write_text('mono');(p/'buffer_size_kb').write_text('8192');(p/'trace').write_text('')
  if name=='switch':
   (p/'tracing_cpumask').write_text('20000');(p/'events/sched/sched_switch/enable').write_text('1')
  else:
   filt=' || '.join(f'pid == {tid}' for tid in threads)
   for ev in ['sched_waking','sched_wakeup']:
    (p/f'events/sched/{ev}/filter').write_text(filt);(p/f'events/sched/{ev}/enable').write_text('1')
 refs=[]
 for _ in range(5):
  a=time.monotonic_ns();w=time.time_ns();b=time.monotonic_ns();refs.append(dict(unix_ns=w,monotonic_ns=(a+b)//2,uncertainty_ns=(b-a)//2))
 for p in instances:(p/'tracing_on').write_text('1')
 begin=time.monotonic_ns();print('SCHED_START',pid,flush=True);time.sleep(20)
 for p in instances:(p/'tracing_on').write_text('0')
 end=time.monotonic_ns();metadata=dict(pid=pid,threads=threads,start_monotonic_ns=begin,end_monotonic_ns=end,clock_references=refs,instances={})
 for p in instances:
  name=p.name.rsplit('_',1)[1];(out/f'{name}.txt').write_text((p/'trace').read_text());metadata['instances'][name]={}
  for stat in (p/'per_cpu').glob('cpu*/stats'):
   metadata['instances'][name][stat.parent.name]=stat.read_text()
 (out/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n');print('SCHED_END',flush=True)
finally:
 for p in instances:
  (p/'tracing_on').write_text('0');(p/'events/enable').write_text('0');p.rmdir()
