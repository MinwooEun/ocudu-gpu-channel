"""Short /proc-only broker scheduler observation; run on auxiliary CPUs."""
import argparse, json, os, pathlib, time
p=argparse.ArgumentParser();p.add_argument('case');p.add_argument('--seconds',type=float,default=2);a=p.parse_args()
root=pathlib.Path('/workspace/gpuch/relay-ready-20261029/live-pr10')/a.case

def locate():
 for proc in pathlib.Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:cmd=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode()
  except (OSError,UnicodeError):continue
  if cmd.startswith('/workspace/gpuch/relay-ready-20261029/build-') and '/ocudu-gpu-channel ' in cmd and str(root) in cmd:return proc,cmd
 raise RuntimeError('expected active broker not found')

def snapshot(proc):
 threads={}
 for t in (proc/'task').iterdir():
  try:
   stat=(t/'stat').read_text().rsplit(')',1)[1].split()
   fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in (t/'status').read_text().splitlines() if ':' in line}
   threads[t.name]=dict(comm=(t/'comm').read_text().strip(),state=stat[0],cpu_ticks=int(stat[11])+int(stat[12]),
      schedstat=list(map(int,(t/'schedstat').read_text().split())),voluntary=int(fields['voluntary_ctxt_switches']),
      involuntary=int(fields['nonvoluntary_ctxt_switches']),cpus=fields['Cpus_allowed_list'])
  except FileNotFoundError:pass
 return dict(monotonic_ns=time.monotonic_ns(),threads=threads)
proc,cmd=locate();before=snapshot(proc);time.sleep(a.seconds);after=snapshot(proc)
common=before['threads'].keys() & after['threads'].keys()
elapsed=(after['monotonic_ns']-before['monotonic_ns'])/1e9
keys=('cpu_ticks','voluntary','involuntary')
totals={k:sum(after['threads'][t][k]-before['threads'][t][k] for t in common) for k in keys}
totals['cpu_core_seconds']=totals['cpu_ticks']/os.sysconf('SC_CLK_TCK')
totals['cpu_cores_average']=totals['cpu_core_seconds']/elapsed
for idx,key in enumerate(('run_ns','runqueue_ns','timeslices')):
 totals[key]=sum(after['threads'][t]['schedstat'][idx]-before['threads'][t]['schedstat'][idx] for t in common)
totals['scheduled_cores_average']=totals['run_ns']/1e9/elapsed
result=dict(case=a.case,pid=int(proc.name),command=cmd,elapsed_s=elapsed,threads_before=len(before['threads']),threads_after=len(after['threads']),
 note='Diagnostic two-second window, not whole-run percentiles. A zero runqueue counter may mean scheduler statistics disabled.',totals=totals,before=before,after=after)
(root/'scheduler-window.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('before','after','command')}))
