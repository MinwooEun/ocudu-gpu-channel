import pathlib,time,json,sys
d=pathlib.Path(sys.argv[1]);d.mkdir(parents=True,exist_ok=True)
stop=time.monotonic()+600
with (d/'thread-runtime.jsonl').open('w') as out:
 while time.monotonic()<stop and not (d/'result.json').exists():
  rows=[]
  for p in pathlib.Path('/proc').glob('[0-9]*'):
   try:
    name=(p/'comm').read_text().strip()
    if name not in ('gnb','srsue','nr-uesoftmodem','ocudu-gpu-chann'):continue
    for t in (p/'task').iterdir():
     try:
      raw=(t/'stat').read_text();name_t=raw[raw.index('(')+1:raw.rindex(')')];q=raw[raw.rindex(')')+2:].split()
      sched=list(map(int,(t/'schedstat').read_text().split()))
      rows.append([int(p.name),int(t.name),name_t,q[0],int(q[11]),int(q[12]),int(q[36]),*sched])
     except (FileNotFoundError,ProcessLookupError,PermissionError):pass
   except (FileNotFoundError,ProcessLookupError,PermissionError):pass
  out.write(json.dumps(dict(monotonic_ns=time.monotonic_ns(),columns=['pid','tid','comm','state','user_ticks','system_ticks','cpu','runtime_ns','runqueue_ns','timeslices'],threads=rows))+'\n');out.flush();time.sleep(.5)
