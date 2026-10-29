from pathlib import Path
import json,re,collections,sys
ROOT=Path('/workspace/gpuch/profile-20261029-deep');P=ROOT/(sys.argv[1] if len(sys.argv)>1 else '');W=json.load(open(P/'capture-window.json'));lo=W['start_ns'];hi=W['end_ns'];targets={'DP-gnb0','DR-gnb0_p0'};ids={};run={};pending={};spans=collections.defaultdict(list);lastcpu={};usage=collections.Counter()
pat=re.compile(r'\[(\d+)\].*? (\d+)\.(\d+): sched_(switch|wakeup|wakeup_new): (.*)')
sw=re.compile(r'prev_comm=(.*?) prev_pid=(\d+) prev_prio=\d+ prev_state=(\S+) ==> next_comm=(.*?) next_pid=(\d+)')
wake=re.compile(r'comm=(.*?) pid=(\d+) ')
def add(name,a,b,kind):
 a=max(a,lo);b=min(b,hi)
 if b>a:spans[name].append([a,b,kind])
with (P/'scheduler.trace').open() as f:
 for line in f:
  if 'sched_' not in line:continue
  m=pat.search(line)
  if not m:continue
  cpu,sec,frac,ev,tail=m.groups();ts=int(sec)*10**9+int(frac.ljust(9,'0'));cpu=int(cpu)
  if ev=='switch':
   m=sw.search(tail)
   if not m:raise RuntimeError(line)
   pc,pi,state,nc,ni=m.groups();pi=int(pi);ni=int(ni)
   if cpu in (15,16):
    if cpu in lastcpu:usage[pc]+=max(0,min(ts,hi)-max(lastcpu[cpu],lo))
    lastcpu[cpu]=ts
   if pc in targets:
    ids[pc]=pi;add(pc,run.pop(pc,lo),ts,'cpu');pending[pc]=(ts,'preempted' if '+' in state else 'yield_runnable' if state=='R' else 'blocked')
   if nc in targets:
    ids[nc]=ni
    if nc in pending:
     a,k=pending.pop(nc);add(nc,a,ts,k)
    else:add(nc,lo,ts,'unknown')
    run[nc]=ts
  else:
   m=wake.search(tail)
   if m:
    name,pid=m.groups()
    if name in targets and name in pending and pending[name][1]=='blocked':
     a,k=pending[name];add(name,a,ts,k);pending[name]=(ts,'wakeup_runnable')
for name in targets:
 if name in run:add(name,run[name],hi,'cpu')
 elif name in pending:a,k=pending[name];add(name,a,hi,k)
for name,v in spans.items():
 v.sort();total=sum(b-a for a,b,k in v);assert abs(total-(hi-lo))<5000,(name,total,hi-lo)
out=dict(window=W,kernel_tids=ids,states=spans,cpu15_16_usage_ns=dict(usage));(P/'scheduler-intervals.json').write_text(json.dumps(out));print({name:dict(collections.Counter({k:sum(b-a for a,b,kk in v if kk==k)/1e6 for k in set(x[2] for x in v)})) for name,v in spans.items()})
