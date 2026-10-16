import pathlib,json,time,re,sys
b=pathlib.Path(sys.argv[1]);root=b/'ocudu-native-workspace/results/logs/ocudu-scheduler-benchmark';out=b/'bursty-load-20261014';end=time.monotonic()+1800;opened={};scan=0
with (out/'iq-observed.jsonl').open('w') as target:
 while time.monotonic()<end:
  now=time.monotonic()
  if now>=scan:
   for d in root.iterdir():
    if d.name<'20261013T165804Z' or d.name in opened:continue
    p=d/'broker-a.log'
    if p.exists():
     f=p.open();f.seek(0,2);opened[d.name]=f
   scan=now+1
  for run,f in list(opened.items()):
   if f.closed:continue
   while True:
    pos=f.tell();line=f.readline()
    if not line or not line.endswith('\n'):f.seek(pos);break
    t=time.monotonic_ns();m=re.search(r'^event=heartbeat t=(\d+) dev=(\S+).*? acquired=(\d+)',line)
    if m:target.write(json.dumps({'run':run,'heartbeat_elapsed_s':int(m[1]),'device':m[2],'acquired_samples':int(m[3]),'observed_monotonic_ns':t})+'\n');target.flush()
    if line.startswith('event=stop '):f.close();break
  if (out/'observer-stop').exists():break
  time.sleep(.002)
