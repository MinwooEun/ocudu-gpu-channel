"""Join long producer writes to switch-out state and captured kernel stacks."""
import pathlib,re,json,bisect
p=pathlib.Path('/workspace/gpuch/realtime-rate-20261030/u1/original-profile-write-root-r1')
func=[]
for line in pathlib.Path('/sys/kernel/tracing/available_filter_functions_addrs').read_text().splitlines():
 x=line.split()
 if len(x)>=2:
  try:func.append((int(x[0],16),x[1]))
  except ValueError:pass
func.sort();addresses=[x[0] for x in func]
def resolve(stack):
 out=[]
 for line in stack:
  m=re.match(r'\s*(ffff[0-9a-f]+) ',line)
  if not m:continue
  addr=int(m[1],16);i=bisect.bisect_right(addresses,addr)-1
  out.append(dict(address=m[1],nearest_ftrace_function=func[i][1] if i>=0 else None,offset=addr-func[i][0] if i>=0 else None))
 return out
blocks=[];current=[]
for line in (p/'kernel-writes.txt').read_text().splitlines():
 if not line.strip():
  if current:blocks.append(current);current=[]
 else:current.append(line)
if current:blocks.append(current)
pending={};long=[];maps={};count=0
for b in blocks:
 m=re.search(r'\s(\d+)\s+\[\d+\]\s+(\d+)\.(\d+):\s+(syscalls:sys_enter_write|syscalls:sys_exit_write|sched:sched_switch):\s+(.*)',b[0])
 if not m:continue
 tid=int(m[1]);t=int(m[2])*10**9+int(m[3].ljust(9,'0'));ev=m[4]
 if ev=='syscalls:sys_enter_write':pending[tid]=dict(tid=tid,start_ns=t,fd=int(re.search(r'fd=(\d+)',m[5])[1]),switches=[])
 elif ev=='sched:sched_switch':
  prev=int(re.search(r'prev_pid=(\d+)',m[5])[1]);maps[tid]=prev
  if tid in pending:pending[tid]['switches'].append(dict(time_ns=t,event=m[5],kernel_stack=resolve(b[1:]),raw_stack=b[1:]))
 elif tid in pending:
  x=pending.pop(tid);x.update(end_ns=t,us=(t-x['start_ns'])/1000);count+=1
  if x['us']>1000:long.append(x)
result=dict(paired_writes=count,long_writes=long,namespace_to_host_tid=maps,note='Function names are nearest entries from available_filter_functions_addrs; missing uninstrumented symbols are not guessed. Switch-out state distinguishes blocking from preemption. Raw addresses and user frames are preserved.')
(p/'kernel-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
print('paired',count,'long',len(long))
for x in long:
 print('WRITE',x['tid'],x['fd'],x['us'],'switches',len(x['switches']))
 for s in x['switches']:
  print(s['event']);print([(y['nearest_ftrace_function'],y['offset']) for y in s['kernel_stack']])
