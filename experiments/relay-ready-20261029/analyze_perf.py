"""Recover AArch64 leaf callers from recorded LR/FP, stripping PAC code bits.
For this capture only: asserts the recorded perf sample layout before decoding.
No process memory is read; all stack bytes are from the three-second perf file.
"""
import argparse,collections,json,pathlib,re,struct
p=argparse.ArgumentParser();p.add_argument('data');p.add_argument('script');p.add_argument('--symbols');a=p.parse_args()
b=pathlib.Path(a.data).read_bytes();assert b[:8]==b'PERFILE2'
attr_off,attr_size,data_off,data_size=struct.unpack_from('<QQQQ',b,24)
attr=b[attr_off:attr_off+144];sample_type=struct.unpack_from('<Q',attr,24)[0]
assert sample_type==0x13127,hex(sample_type)
mask=struct.unpack_from('<Q',attr,80)[0];regids=[i for i in range(64) if mask>>i&1]
assert all(x in regids for x in [1,29,30,31,32])
maps=[]
for l in pathlib.Path(a.script).read_text().splitlines():
 m=re.search(r'PERF_RECORD_MMAP2 .*?\[0x([a-f0-9]+)\(0x([a-f0-9]+)\) @ (0x[a-f0-9]+|0) .*?\]: (\S+) (.+)',l)
 if m:maps.append((int(m[1],16),int(m[2],16),int(m[3],0),m[5]))
PAC=(1<<48)-1

def locate(ip):
 ip &= PAC
 for start,size,offset,path in maps:
  if start<=ip<start+size:return path,ip-start+offset
 return 'unmapped',ip

def fmt(ip):
 path,offset=locate(ip);return pathlib.Path(path).name+'+'+hex(offset)

pos=data_off;events=[]
while pos<data_off+data_size:
 typ,misc,size=struct.unpack_from('<IHH',b,pos);assert size>=8
 if typ==9:
  end=pos+size;q=pos+8
  def u64():
   global q
   v=struct.unpack_from('<Q',b,q)[0];q+=8;return v
  ident=u64();ip=u64();pid,tid=struct.unpack_from('<II',b,q);q+=8
  timestamp=u64();period=u64();nr=u64();q+=8*nr
  abi=u64();regs={i:u64() for i in regids} if abi else {}
  stack_size=u64();stack=b[q:q+stack_size];q+=stack_size
  dyn_size=u64() if stack_size else 0
  assert q==end,(q,end)
  frames=[]
  if regs and stack_size:
   fp=regs[29]&PAC;sp=regs[31]&PAC
   for _ in range(24):
    off=fp-sp
    if fp%16 or off<0 or off+16>min(dyn_size,stack_size):break
    previous,ret=struct.unpack_from('<QQ',stack,off);frames.append(ret&PAC)
    previous &=PAC
    if previous<=fp:break
    fp=previous
  events.append(dict(ip=ip,tid=tid,period=period,regs=regs,frames=frames))
 pos+=size
assert len(events)==1024,len(events)
total=sum(e['period'] for e in events)
groups=collections.defaultdict(lambda:[0,0])
for e in events:
 path,off=locate(e['ip'])
 if path.endswith('/libc.so.6') and 0x140684<=off<0x141000:
  # For the hot outlined exchange called by pthread_mutex_unlock, the
  # caller's frame holds the broker/CUDA caller of that libc helper.
  lr=e['regs'].get(30,0)&PAC
  key=(fmt(lr),tuple(fmt(ip) for ip in e['frames'][:3]))
  groups[key][0]+=1;groups[key][1]+=e['period']
rows=[dict(lr=k[0],frame_callers=list(k[1]),samples=v[0],period=v[1],share_percent=100*v[1]/total)
      for k,v in sorted(groups.items(),key=lambda x:-x[1][1])]
out=dict(samples=len(events),period_total=total,atomic_callers=rows)
if a.symbols:
 api_names={'cudaEventRecord','cudaEventElapsedTime','cudaMemcpyAsync','cudaStreamSynchronize','cudaLaunchKernel','cudaGetLastError','cudaLaunchHostFunc'}
 api=[]
 for line in pathlib.Path(a.symbols).read_text().splitlines():
  fields=line.split(None,3)
  if len(fields)==4 and fields[2] in {'t','T','w','W'} and fields[3] in api_names:
   api.append((int(fields[0],16),int(fields[1],16),fields[3]))
 counts=collections.defaultdict(lambda:[0,0]);copies=collections.defaultdict(lambda:[0,0]);driver=[0,0]
 sites={('ocudu-gpu-channel',0x620d4):'IqRing::push',('ocudu-gpu-channel',0x621f0):'IqRing::read',('libzmq.so.5.2.5',0x33798):'zmq::msg_t::init_buffer'}
 for e in events:
  hits=set()
  for ip in [e['ip']]+e['frames']:
   path,off=locate(ip)
   if path.endswith('/ocudu-gpu-channel'):
    hits.update(name for start,size,name in api if start<=off<start+size)
  for name in hits:counts[name][0]+=1;counts[name][1]+=e['period']
  path,off=locate(e['ip']);lr=e['regs'].get(30,0)&PAC;caller,ret=locate(lr)
  if path.endswith('/libc.so.6') and 0xa1940<=off<0xa1d40:
   name=sites.get((pathlib.Path(caller).name,ret),'other copy caller')
   copies[name][0]+=1;copies[name][1]+=e['period']
  if path.endswith('/libc.so.6') and 0x140684<=off<0x141000 and ret==0x8a4c4 and e['frames'] and locate(e['frames'][0])[0].endswith('/libcuda.so.580.178.04'):
   driver[0]+=1;driver[1]+=e['period']
 def summary(mapping):
  return [dict(function=name,samples=v[0],period=v[1],share_percent=100*v[1]/total) for name,v in sorted(mapping.items(),key=lambda x:-x[1][1])]
 out['cpu_api_costs']=summary(counts);out['copy_callers']=summary(copies)
 out['driver_mutex_unlock']=dict(samples=driver[0],period=driver[1],share_percent=100*driver[1]/total)
print(json.dumps(out,indent=2))
