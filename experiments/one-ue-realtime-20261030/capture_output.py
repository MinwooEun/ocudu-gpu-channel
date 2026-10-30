"""Trace gNB/REP/IO scheduling; exclude producer yield loops from ordinary traces."""
import pathlib,time,json,subprocess as sp,re,os,sys
import numpy as np
p=pathlib.Path(sys.argv[1]);ram=pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030');deadline=time.monotonic()+260
while time.monotonic()<deadline:
 f=p/'runtime/logs/replay-applied.jsonl';ready=False
 if f.exists():
  for l in f.read_bytes()[-16384:].decode(errors='replace').splitlines():
   try:r=json.loads(l)
   except ValueError:continue
   if r.get('record')=='applied' and r.get('k',-1)>=90:ready=True
 if ready:break
 time.sleep(.2)
else:raise RuntimeError('measurement not found')
actors={};tasks={};records={}
dt=np.dtype([(s,'<i8') for s in ['op','tid','port','flags','start','end','result','error']])
for f in (ram/'wire').glob('*.wire'):
 pid=int(f.stem.rsplit('-',1)[1]);proc=pathlib.Path('/proc',str(pid))
 if not proc.exists():continue
 h=np.fromfile(f,dtype='<u8',count=8)
 if not h[1]:continue
 actor=f.name.split('-')[0];a=np.memmap(f,dtype=dt,offset=64,shape=(int(h[1]),),mode='r');records[actor]=a;actors[actor]=pid
 tids=[]
 for t in (proc/'task').iterdir():
  tid=int(t.name);tasks[tid]=dict(pid=pid,actor=actor,comm=(t/'comm').read_text().strip(),policy=os.sched_getscheduler(tid),priority=os.sched_getparam(tid).sched_priority,cpus=sorted(os.sched_getaffinity(tid)));tids.append(tid)
 (p/f'maps-{pid}.txt').write_text((proc/'maps').read_text())
assert set(actors)=={'gnb','srsue','ocudu'},actors
if os.environ.get('OCG_CAPTURE_UE_ONLY')=='1':
 chosen=[t for t,x in tasks.items() if x['actor']=='srsue']
 (p/'targets.json').write_text(json.dumps(dict(actors=actors,tasks=tasks,start_mono_ns=time.monotonic_ns()),indent=2))
 cmd=['perf','record','--clockid','mono','-C','17','-e','sched:sched_switch','-o',str(ram/'sched.data'),'--','sleep','30']
 with (p/'perf.log').open('w') as log:r=sp.run(cmd,stdout=log,stderr=sp.STDOUT)
 assert r.returncode==0,(p/'perf.log').read_text()
 with (p/'sched.txt').open('w') as out:sp.run(['perf','script','--ns','-i',str(ram/'sched.data')],stdout=out,stderr=sp.PIPE,check=True)
 print('UE CPU17 capture completed',flush=True);raise SystemExit(0)
broker=records['ocudu'];rep=np.unique(broker[(broker['op']==1)&(broker['port']==2001)&(broker['result']>=8)]['tid']);assert len(rep)==1,rep
chosen=[t for t,x in tasks.items() if x['actor']=='gnb' or (x['actor']=='ocudu' and ('ZMQbg/IO/' in x['comm'] or t==int(rep[0]))) or (x['actor']=='srsue' and 'ZMQbg/IO/' in x['comm'])]
print('chosen',[(t,tasks[t]['actor'],tasks[t]['comm']) for t in chosen],flush=True)
sp.run(['perf','record','--clockid','mono','-t',','.join(map(str,chosen)),'-e','sched:sched_switch','-o',str(ram/'mapping.data'),'--','sleep','.3'],check=True,stdout=sp.DEVNULL,stderr=sp.PIPE)
raw=sp.check_output(['perf','script','--ns','-i',str(ram/'mapping.data')],text=True,stderr=sp.DEVNULL);(p/'mapping.txt').write_text(raw);mapping={}
for l in raw.splitlines():
 m=re.match(r'^\s*.*?\s+(\d+)\s+\[\d+\].*prev_pid=(\d+)',l)
 if m:mapping[int(m[1])]=int(m[2])
assert int(rep[0]) in mapping,('REP never scheduled',rep,mapping)
host=sorted(set(mapping.values()));(p/'targets.json').write_text(json.dumps(dict(actors=actors,tasks=tasks,mapping=mapping,broker_rep_tid=int(rep[0]),start_mono_ns=time.monotonic_ns()),indent=2))
fil=' || '.join(f'prev_pid == {t} || next_pid == {t}' for t in host);wake=' || '.join(f'pid == {t}' for t in host)
radio=[t for t in chosen if tasks[t]['actor']=='gnb' and 'radio' in tasks[t]['comm'].lower()];stacks=[mapping[t] for t in radio+[int(rep[0])] if t in mapping]
stackfil=' || '.join(f'prev_pid == {t}' for t in stacks)
cmd=['perf','record','--clockid','mono','-a','-e','sched:sched_switch/call-graph=no/','--filter',fil,'-e','sched:sched_wakeup/call-graph=no/','--filter',wake,'-e','sched:sched_switch/call-graph=fp/','--filter',f'({stackfil}) && prev_state != 0','-o',str(ram/'sched.data'),'--','sleep','30']
(p/'perf-command.json').write_text(json.dumps(cmd,indent=2));samples=None
cpu_tids=radio or [t for t in chosen if tasks[t]['actor']=='gnb']
with (p/'cpu-perf.log').open('w') as log:samples=sp.Popen(['perf','record','--clockid','mono','-e','cpu-clock','-F','499','-t',','.join(map(str,cpu_tids)),'-g','--call-graph','fp','-o',str(ram/'cpu.data'),'--','sleep','30'],stdout=log,stderr=sp.STDOUT)
with (p/'perf.log').open('w') as log:r=sp.run(cmd,stdout=log,stderr=sp.STDOUT)
assert r.returncode==0,(p/'perf.log').read_text();assert samples.wait()==0,(p/'cpu-perf.log').read_text()
for name in ['sched','cpu']:
 with (p/f'{name}.txt').open('w') as out:sp.run(['perf','script','--ns','-i',str(ram/f'{name}.data')],stdout=out,stderr=sp.PIPE,check=True)
print('capture completed',flush=True)
