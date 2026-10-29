import pathlib,json,time,re,sys
path=pathlib.Path(sys.argv[1]); out=pathlib.Path(sys.argv[2]); duration=float(sys.argv[3]); end=time.monotonic()+duration
while not path.exists():
 if time.monotonic()>end:raise SystemExit('broker log absent')
 time.sleep(.002)
with path.open() as source,out.open('w') as target:
 source.seek(0,2)
 while time.monotonic()<end:
  start=source.tell(); line=source.readline()
  if not line or not line.endswith('\n'):
   source.seek(start);time.sleep(.002);continue
  seen=time.monotonic_ns()
  m=re.search(r'^event=heartbeat t=(\d+) dev=(\S+).*? acquired=(\d+)',line)
  if m:
   target.write(json.dumps({'heartbeat_elapsed_s':int(m[1]),'device':m[2],'acquired_samples':int(m[3]),'observed_monotonic_ns':seen})+'\n');target.flush()
  if line.startswith('event=stop '):break
