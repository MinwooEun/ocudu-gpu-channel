import os,pathlib,time,sys,json
W=pathlib.Path('/home/minwoo/ocudu-work/rtx-scaling-20261102');d=pathlib.Path(sys.argv[1]);os.sched_setaffinity(0,{20,21,22,23});meta=json.loads((d/'launch.json').read_text());pbroker=meta['tag'].startswith('pbroker');expected_phy=[0,2,3,4,5,8,9] if pbroker else [0,2,3,4,5,6,7];start=time.monotonic();rows=[];checks=0;bad=[];gnb_seen=False
while time.monotonic()-start<750:
 actors={}
 for f in (W/'active-wire').glob('*.wire'):
  pid=int(f.stem.rsplit('-',1)[1]);p=pathlib.Path('/proc',str(pid))
  try:
   if ('SINGLE_CELL_RUN_ROOT='+str(d/'runtime')).encode() not in (p/'environ').read_bytes().split(b'\0'):continue
   tasks={}
   for t in (p/'task').iterdir():
    name=(t/'comm').read_text().strip();tid=int(t.name);st=(t/'stat').read_text().rsplit(')',1)[1].split()
    tasks[str(tid)]=dict(name=name,cpus=sorted(os.sched_getaffinity(tid)),utime=int(st[11]),stime=int(st[12]),cpu=int(st[36]),policy=os.sched_getscheduler(tid),priority=os.sched_getparam(tid).sched_priority)
   actors[f.name]=tasks
   if f.name.startswith('gnb-') and any(v['name']=='phy_worker' for v in tasks.values()):
    gnb_seen=True;radio=[v for v in tasks.values() if v['name']=='radio'];phy=[v for v in tasks.values() if v['name']=='phy_worker']
    if radio and phy:
     checks+=1
     if radio[0]['cpus']!=[1] or phy[0]['cpus']!=expected_phy:bad.append(dict(mono_ns=time.monotonic_ns(),radio=radio,phy=phy))
  except (FileNotFoundError,ProcessLookupError):pass
 if actors:rows.append(dict(mono_ns=time.monotonic_ns(),actors=actors))
 if (d/'result.json').exists():break
 time.sleep(.5)
(d/'affinity-audit.json').write_text(json.dumps(dict(checks=checks,gnb_seen=gnb_seen,violations=bad,passed=checks>20 and not bad,clock_ticks=os.sysconf('SC_CLK_TCK'),snapshots=rows),indent=2))
