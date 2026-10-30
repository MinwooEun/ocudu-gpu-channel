"""Partition each observed deschedule into sleeping and runnable time."""
import pathlib,re,json,bisect,collections,csv
p=pathlib.Path('/workspace/gpuch/residual-rate-20261030/u1/original-zero-sched-r6');meta=json.loads((p/'targets.json').read_text());hosts={int(h):int(ns) for ns,h in meta['mapping'].items()};fdmap=json.loads((p/'fdmap.json').read_text());rx=re.compile(r'^\s*(.*?)\s+(\d+)\s+\[(\d+)\]\s+(\d+)\.(\d+):\s+(\S+):\s*(.*)$');events=[];record=None
centers=sorted(e['times']['pace_call'] for e in json.loads((p/'input-analysis.json').read_text())['events'])
all_headers=0;lost_lines=[]
def selected(t):
 i=bisect.bisect_left(centers,t-2000000)
 return i<len(centers) and centers[i]-20000000<=t<=centers[i]+2000000

for line in (p/'sched.txt').open():
 m=None if line.startswith('\t') else rx.match(line)
 if m:
  comm,tid,cpu,sec,ns,kind,rest=m.groups();all_headers+=1;timestamp=int(sec)*10**9+int(ns.ljust(9,'0'))
  if not selected(timestamp):record=None;continue
  record=dict(comm=comm,tid=int(tid),cpu=int(cpu),t=int(sec)*10**9+int(ns.ljust(9,'0')),kind=kind,raw=rest,stack=[]);events.append(record)
 elif record and line.startswith('\t'):record['stack'].append(line.strip())
assert len(events)>100,('no selected scheduler events',len(events),centers[:1])
events.sort(key=lambda e:e['t'])
unique={}
for e in events:
 key=(e['t'],e['kind'],e['raw'])
 if key not in unique:unique[key]=e
 elif e['stack']:unique[key]['stack']=e['stack']
events=list(unique.values())
pending={};intervals=[];writes=[];producer={};states=collections.Counter()
previous_event=None
for e in events:
 if previous_event is not None and e['t']-previous_event>10000000:pending={}
 previous_event=e['t']
 if e['kind']=='syscalls:sys_enter_write':
  z=re.search(r'fd:\s*(?:0x)?([0-9a-f]+)',e['raw'])
  # perf syscall fields may print either fd: 0xNN or fd=NN.
  if z:fd=int(z[1],16)
  else:
   z=re.search(r'fd=(\d+)',e['raw']);fd=int(z[1]) if z else None
  e['fd']=fd;e['file']=fdmap.get(str(fd),'');writes.append(e)
  if '/pacing/' in e['file']:producer[pathlib.Path(e['file']).stem]=e['tid']
 elif e['kind']=='sched:sched_wakeup':
  z=re.search(r'pid=(\d+)',e['raw']);h=int(z[1])
  if h in pending:pending[h]['wakes'].append(e)
 elif e['kind']=='sched:sched_switch':
  z=re.search(r'prev_comm=(.*?) prev_pid=(\d+).*?prev_state=(\S+).*?next_comm=(.*?) next_pid=(\d+)',e['raw']);assert z,e
  prevcomm,prev,state,ncomm,nxt=z.groups();prev=int(prev);nxt=int(nxt)
  if nxt in pending:
   a=pending.pop(nxt);a['end']=e['t'];a['in_comm']=ncomm;a['wall_us']=(e['t']-a['start'])/1000
   if a['state'].startswith('R'):a['runnable_us']=a['wall_us'];a['blocked_us']=0
   elif a['wakes']:
    wake=min(w['t'] for w in a['wakes']);a['blocked_us']=(wake-a['start'])/1000;a['runnable_us']=(e['t']-wake)/1000
   else:a['blocked_us']=None;a['runnable_us']=None
   intervals.append(a)
  if prev in hosts:
   pending[prev]=dict(host_tid=prev,namespace_tid=hosts[prev],comm=prevcomm,start=e['t'],state=state,out=e,wakes=[]);states[state]+=1
intervals.sort(key=lambda x:x['start']);summary={}
for h in hosts:
 a=[x for x in intervals if x['host_tid']==h];summary[str(h)]=dict(namespace_tid=hosts[h],comm=a[0]['comm'] if a else None,intervals=len(a),max_us=max([x['wall_us'] for x in a],default=0))
(p/'sched-analysis.json').write_text(json.dumps(dict(scope='Events within 20 ms before and 2 ms after pacing rebases; gaps are not whole-run off-CPU statistics.',all_perf_headers=all_headers,selected_headers=len(events),producer_tids=producer,summary=summary,states=states,intervals=intervals,writes=writes),separators=(',',':')))
print('producer_tids',producer,'intervals',len(intervals),'states',states,'records',len(events))
for node,tid in producer.items():
 a=[x for x in intervals if x['namespace_tid']==tid]
 print(node,'longest',[(x['wall_us'],x['state'],x['blocked_us'],x['runnable_us']) for x in sorted(a,key=lambda x:x['wall_us'],reverse=True)[:6]])
