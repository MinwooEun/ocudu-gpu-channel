import time,pathlib,json,sys,os
out=pathlib.Path(sys.argv[1]);duration=float(sys.argv[2]);end=time.monotonic()+duration
processes={};last_discovery=0;seen=set()
with (out/'runtime-samples.jsonl').open('w') as target,(out/'processes.jsonl').open('w') as info:
 while time.monotonic()<end and not (out/'STOP').exists():
  begin=time.monotonic_ns();wall=time.time_ns();now=time.monotonic()
  if now-last_discovery>=1:
   processes={}
   for p in pathlib.Path('/proc').glob('[0-9]*'):
    try:
     comm=(p/'comm').read_text().strip()
     if comm not in ['gnb','srsue','ocudu-gpu-chann']:continue
     cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode();pid=int(p.name)
     if '/work/' not in cmd or '--help' in cmd:continue
     tids=[int(t.name) for t in (p/'task').iterdir()];processes[pid]=tids
     if pid not in seen:
      seen.add(pid);info.write(json.dumps({'pid':pid,'comm':comm,'cmd':cmd,'mono_ns':begin,'status':(p/'status').read_text()})+'\n');info.flush()
    except (FileNotFoundError,ProcessLookupError,PermissionError):pass
   last_discovery=now
  rows=[]
  for pid,tids in processes.items():
   for tid in tids:
    p=pathlib.Path(f'/proc/{pid}/task/{tid}')
    try:
     stat=(p/'stat').read_text().rsplit(')',1)[1].split();sched=list(map(int,(p/'schedstat').read_text().split()));comm=(p/'comm').read_text().strip()
     rows.append([pid,tid,comm,stat[0],int(stat[36]),*sched])
    except (FileNotFoundError,ProcessLookupError,PermissionError):pass
  target.write(json.dumps({'mono_ns':begin,'wall_ns':wall,'rows':rows,'read_ns':time.monotonic_ns()-begin})+'\n');target.flush()
  time.sleep(max(0,.05-(time.monotonic_ns()-begin)/1e9))
