import pathlib,sys,time,json,struct,collections
P=pathlib.Path(sys.argv[1]);roles={};pids=set()
for f in (P/'trace').glob('broker-*.csv'):
 try:
  _,row=f.open().readline(),None
  with f.open() as z:z.readline();row=z.readline().strip().split(',')
  pid,tid=map(int,f.stem.split('-')[1:]);pids.add(pid)
  if len(row)>1:roles[tid]='producer:'+row[1]
 except (OSError,ValueError):pass
for f in (P/'wire').glob('*.wire'):
 with f.open('rb') as z:
  h=struct.unpack('8Q',z.read(64));pid=h[4]
  if not pathlib.Path(f'/proc/{pid}').exists():continue
  pids.add(pid)
  for _ in range(min(h[1],20000)):
   op,tid,port,flags,st,en,res,err=struct.unpack('8q',z.read(64))
   if port<2000 or port>2131 or op not in (1,2):continue
   if f.name.startswith('ocudu-'):roles.setdefault(tid,('puller:' if port==2000 or port>=2101 and port%2 else 'reply:')+str(port))
   elif f.name.startswith('gnb-'):roles.setdefault(tid,'gnb:radio')
   else:roles.setdefault(tid,'ue:radio:'+str(port))
def snap():
 rows={}
 for pid in pids:
  for t in pathlib.Path(f'/proc/{pid}/task').glob('*'):
   try:
    tid=int(t.name);stat=list(map(int,(t/'schedstat').read_text().split()));rows[tid]=dict(pid=pid,comm=(t/'comm').read_text().strip(),cpu_ns=stat[0],runnable_ns=stat[1],timeslices=stat[2],role=roles.get(tid,'other'))
   except (OSError,ValueError):pass
 return rows
st=time.monotonic_ns();a=snap();time.sleep(4);b=snap();en=time.monotonic_ns();out=[]
for tid,v in a.items():
 if tid not in b:continue
 out.append(dict(tid=tid,pid=v['pid'],comm=v['comm'],role=v['role'],**{k:b[tid][k]-v[k] for k in ('cpu_ns','runnable_ns','timeslices')}))
print(json.dumps(dict(start_ns=st,end_ns=en,threads=out),indent=2))
