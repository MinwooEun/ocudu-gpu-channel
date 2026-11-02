"""Apply the same existing IO/RF RX policy to every owned CPU UE."""
import pathlib,os,time,json,sys,mmap,struct
p=pathlib.Path(sys.argv[1]);expected=int(sys.argv[2]);deadline=time.monotonic()+300;changes={};rf={};stable=None
def raise_io(tid,actor,kind):
 if tid in changes:return
 before=dict(policy=os.sched_getscheduler(tid),priority=os.sched_getparam(tid).sched_priority,cpus=sorted(os.sched_getaffinity(tid)))
 os.sched_setscheduler(tid,os.SCHED_FIFO,os.sched_param(95));after=dict(policy=os.sched_getscheduler(tid),priority=os.sched_getparam(tid).sched_priority,cpus=sorted(os.sched_getaffinity(tid)));assert before['cpus']==after['cpus'];changes[tid]=dict(actor=actor,kind=kind,before=before,after=after)
while time.monotonic()<deadline:
 updated=False;ues=set()
 for wf in pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030/wire').glob('*.wire'):
  pid=int(wf.stem.rsplit('-',1)[1]);root=pathlib.Path('/proc',str(pid))
  try:
   if not root.exists():continue
   if ('SINGLE_CELL_RUN_ROOT='+str(p/'runtime')).encode() not in (root/'environ').read_bytes().split(b'\0'):continue
   is_ue=wf.name.startswith('srsue-')
   if is_ue:ues.add(pid)
   for t in (root/'task').iterdir():
    if (t/'comm').read_text().strip().startswith('ZMQbg/IO/'):
     tid=int(t.name)
     if tid not in changes:raise_io(tid,wf.name,'ZMQ IO');updated=True
   if is_ue and pid not in rf:
    with wf.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm:
     count=min(struct.unpack_from('<Q',mm,8)[0],20000);found=set()
     for i in range(count):
      op,tid,port,flags,start,end,result,error=struct.unpack_from('<8q',mm,64+64*i)
      if op==1 and result==1 and 1024<=port<40000:found.add(tid)
    assert len(found)<=1,(pid,found)
    if found:
     tid=found.pop();raise_io(tid,wf.name,'RF RX request');rf[pid]=tid;updated=True
  except (FileNotFoundError,ProcessLookupError):continue
 if updated:stable=time.monotonic()
 if len(rf)==expected and len(ues)==expected and stable and time.monotonic()-stable>=1:
  (p/'priorities.json').write_text(json.dumps(dict(expected_ues=expected,rf_rx_by_pid=rf,changes=changes),indent=2)+'\n');print('configured all',expected,'UEs',flush=True);break
 time.sleep(.1)
else:raise RuntimeError(('missing UE policy',expected,rf))
