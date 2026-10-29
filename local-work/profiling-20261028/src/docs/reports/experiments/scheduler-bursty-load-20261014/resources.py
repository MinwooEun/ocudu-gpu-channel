import pathlib,json,time,sys
p=pathlib.Path('/work/bursty-load-20261014');end=time.monotonic()+1800
with (p/'resource-observed.jsonl').open('w') as f:
 while time.monotonic()<end and not (p/'observer-stop').exists():
  rows=[]
  for d in pathlib.Path('/proc').iterdir():
   if not d.name.isdigit():continue
   try:
    name=(d/'comm').read_text().strip()
    if name not in ['gnb','srsue','ocudu-gpu-chann']:continue
    cmd=(d/'cmdline').read_bytes().replace(b'\0',b' ').decode();status=(d/'status').read_text();aff=next(x.split(':',1)[1].strip() for x in status.splitlines() if x.startswith('Cpus_allowed_list:'));env=(d/'environ').read_bytes().split(b'\0')
    rows.append({'pid':int(d.name),'name':name,'cpus':aff,'command':cmd,'diagnostic_environment':[v.decode() for v in env if v.startswith((b'LD_PRELOAD=',b'OCG_DIAG_TRACE_DIR=',b'OCG_WIRE_TRACE_DIR='))]})
   except (FileNotFoundError,ProcessLookupError):pass
  f.write(json.dumps({'unix_ns':time.time_ns(),'processes':rows})+'\n');f.flush();time.sleep(10)
