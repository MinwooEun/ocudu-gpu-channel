"""Measure actual gNB functions and radio/PHY scheduling around source-IQ stalls."""
import pathlib,os,time,sys,json,re,subprocess as sp
p=pathlib.Path(sys.argv[1]);ram=pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030');deadline=time.monotonic()+240
while time.monotonic()<deadline:
 f=p/'runtime/logs/replay-applied.jsonl'
 if f.exists() and any('"k":90' in l.replace(' ','') for l in f.read_text().splitlines()):break
 time.sleep(.1)
else:raise RuntimeError('warmup tag not found')
wire=next((ram/'wire').glob('gnb-*.wire'))
pid=None
for f in (ram/'wire').glob('gnb-*.wire'):
 candidate=int(f.stem.rsplit('-',1)[1])
 if pathlib.Path('/proc',str(candidate)).exists():pid=candidate
assert pid
tasks={}
for t in pathlib.Path('/proc',str(pid),'task').iterdir():
 tid=int(t.name);tasks[tid]=dict(comm=(t/'comm').read_text().strip(),priority=os.sched_getparam(tid).sched_priority,policy=os.sched_getscheduler(tid),cpus=sorted(os.sched_getaffinity(tid)))
selected=[t for t,x in tasks.items() if x['comm'] in ['radio','phy_worker']];assert selected,tasks
sp.run(['perf','record','--clockid','mono','-t',','.join(map(str,selected)),'-e','sched:sched_switch','-o',str(ram/'mapping.data'),'--','sleep','.5'],check=True,stdout=sp.DEVNULL,stderr=sp.PIPE)
raw=sp.check_output(['perf','script','--ns','-i',str(ram/'mapping.data')],text=True,stderr=sp.DEVNULL);mapping={}
for l in raw.splitlines():
 m=re.match(r'^\s*.*?\s+(\d+)\s+\[\d+\].*prev_pid=(\d+)',l)
 if m:mapping[int(m[1])]=int(m[2])
assert all(t in mapping for t in selected),(selected,mapping)
(p/'mapping.txt').write_text(raw)
duration='30'
if os.environ.get('OCG_CAPTURE_SHORT')=='1':
 while time.monotonic()<deadline:
  if any('"k":230' in l.replace(' ','') for l in (p/'runtime/logs/replay-applied.jsonl').read_text().splitlines()):break
  time.sleep(.02)
 duration='3'
binary='/workspace/ocudu-spark/builds/d10-cuda-patched-sm121/apps/gnb/gnb';trace=pathlib.Path('/sys/kernel/tracing/uprobe_events');group='ocg1031';probes={'dl':0xb72044,'bb':0xb77d0c,'tx':0xbb25e8,'ul':0xb72868};created=[];children=[]
try:
 for name,addr in ({} if os.environ.get('OCG_NO_FUNCTION_PROBES')=='1' else probes).items():
  for prefix,kind in [('p',name),('r',name+'_ret')]:
   args=' arg=%x1:u64' if prefix=='p' else ''
   fd=os.open(trace,os.O_WRONLY)
   try:os.write(fd,f'{prefix}:{group}/{kind} {binary}:0x{addr:x}{args}\n'.encode())
   finally:os.close(fd)
   created.append(kind)
 host=list(mapping.values());fil=' || '.join(f'prev_pid == {t} || next_pid == {t}' for t in host);wake=' || '.join(f'pid == {t}' for t in host)
 cmd=['perf','record','--clockid','mono','-a','-m','4096']+(['-e',f'{group}:*'] if created else [])+['-e','sched:sched_switch/call-graph=no/','--filter',fil,'-e','sched:sched_wakeup/call-graph=no/','--filter',wake,'-e','sched:sched_switch/call-graph=fp/','--filter','('+' || '.join(f'prev_pid == {t}' for t in host)+') && prev_state != 0','-o',str(ram/'gnb-functions.data'),'--','sleep',duration]
 (p/'gnb-capture.json').write_text(json.dumps(dict(pid=pid,tasks=tasks,selected=selected,mapping=mapping,probes=probes,command=cmd),indent=2))
 with (p/'gnb-cpu-perf.log').open('w') as log:
  cpu=sp.Popen(['perf','record','--clockid','mono','-F','199','-e','cpu-clock','-p',str(pid),'-g','--call-graph','fp','-o',str(ram/'gnb-cpu.data'),'--','sleep',duration],stdout=log,stderr=sp.STDOUT);children.append(cpu)
 with (p/'gnb-functions-perf.log').open('w') as log:r=sp.run(cmd,stdout=log,stderr=sp.STDOUT)
 assert r.returncode==0,(p/'gnb-functions-perf.log').read_text();assert cpu.wait()==0
 for name in ['gnb-functions','gnb-cpu']:
  with (p/(name+'.txt')).open('w') as out:sp.run(['perf','script','--ns','-i',str(ram/(name+'.data'))],stdout=out,stderr=sp.PIPE,check=True)
 print('gnb capture completed',flush=True)
finally:
 for c in children:
  if c.poll() is None:c.terminate();c.wait()
 for name in reversed(created):
  fd=os.open(trace,os.O_WRONLY)
  try:os.write(fd,f'-:{group}/{name}\n'.encode())
  finally:os.close(fd)
