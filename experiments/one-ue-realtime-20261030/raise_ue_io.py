"""One-run causal intervention: IO above STACK, below WORKER/SYNC; same CPU mask."""
import pathlib,os,time,json
base=pathlib.Path('/workspace/gpuch/receiver-quality-20261030');target=base/'local-noise-build/srsue';import sys
out=pathlib.Path(sys.argv[1]);deadline=time.monotonic()+180
while time.monotonic()<deadline:
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   try:exe=(p/'exe').resolve()
   except PermissionError:continue
   if exe!=target:continue
   for t in (p/'task').iterdir():
    if not (t/'comm').read_text().strip().startswith('ZMQbg/IO/'):continue
    tid=int(t.name);before=dict(policy=os.sched_getscheduler(tid),priority=os.sched_getparam(tid).sched_priority,cpus=sorted(os.sched_getaffinity(tid)))
    os.sched_setscheduler(tid,os.SCHED_FIFO,os.sched_param(95));after=dict(policy=os.sched_getscheduler(tid),priority=os.sched_getparam(tid).sched_priority,cpus=sorted(os.sched_getaffinity(tid)));assert before['cpus']==after['cpus']
    out.mkdir(parents=True,exist_ok=True)
    if os.environ.get('OCG_ALL_IO_RT')=='1':
     changes=[]
     for wf in pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030/wire').glob('*.wire'):
      actor_pid=int(wf.stem.rsplit('-',1)[1]);root=pathlib.Path('/proc',str(actor_pid))
      if not root.exists():continue
      for task in (root/'task').iterdir():
       try:
        if not (task/'comm').read_text().strip().startswith('ZMQbg/IO/'):continue
        t=int(task.name);old=dict(policy=os.sched_getscheduler(t),priority=os.sched_getparam(t).sched_priority,cpus=sorted(os.sched_getaffinity(t)));os.sched_setscheduler(t,os.SCHED_FIFO,os.sched_param(95));new=dict(policy=os.sched_getscheduler(t),priority=os.sched_getparam(t).sched_priority,cpus=sorted(os.sched_getaffinity(t)));assert old['cpus']==new['cpus'];changes.append(dict(actor=wf.name,tid=t,before=old,after=new))
       except (FileNotFoundError,ProcessLookupError):continue
     (out/'all-io-priority.json').write_text(json.dumps(changes,indent=2))
    (out/'io-priority.json').write_text(json.dumps(dict(pid=int(p.name),tid=tid,before=before,after=after,monotonic_ns=time.monotonic_ns()),indent=2))
    if os.environ.get('OCG_UE_RF_RX_RT')=='1':
     import mmap,struct
     wf=pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030/wire')/f'srsue-{p.name}.wire';found=None
     until=time.monotonic()+30
     while time.monotonic()<until and found is None:
      if wf.exists():
       with wf.open('rb') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm:
        count=struct.unpack_from('<Q',mm,8)[0]
        for i in range(count):
         op,rtid,port,flags,start,end,result,error=struct.unpack_from('<8q',mm,64+64*i)
         if (op,port,result)==(1,2100,1):found=rtid;break
      if found is None:time.sleep(.05)
     assert found is not None,'RF RX request thread not observed'
     old=dict(policy=os.sched_getscheduler(found),priority=os.sched_getparam(found).sched_priority,cpus=sorted(os.sched_getaffinity(found)));os.sched_setscheduler(found,os.SCHED_FIFO,os.sched_param(95));new=dict(policy=os.sched_getscheduler(found),priority=os.sched_getparam(found).sched_priority,cpus=sorted(os.sched_getaffinity(found)));assert old['cpus']==new['cpus'];(out/'rf-rx-priority.json').write_text(json.dumps(dict(tid=found,before=old,after=new,identified_by='UE ZMQ request send on port 2100'),indent=2))
    print('applied',tid,before,after,flush=True);raise SystemExit(0)
  except (FileNotFoundError,ProcessLookupError):continue
 time.sleep(.2)
raise RuntimeError('UE IO thread was not found')
