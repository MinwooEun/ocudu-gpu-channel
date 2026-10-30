"""Pair raw perf write entry/exit events and correlate long calls with sample-clock phase."""
import bisect,csv,json,pathlib,re,statistics
p=pathlib.Path('/workspace/gpuch/realtime-rate-20261030/u1/original-profile-r1');target=json.loads((p/'write-targets.json').read_text());pending={};rows=[];unmatched_exit=0
for line in (p/'writes.txt').open():
 m=re.search(r'\s(\d+)\s+\[\d+\]\s+(\d+)\.(\d+):\s+syscalls:(sys_enter_write|sys_exit_write):\s+(.*)',line)
 if not m:continue
 tid=int(m[1]);t=int(m[2])*10**9+int(m[3].ljust(9,'0'));ev=m[4]
 if ev=='sys_enter_write':
  fd=re.search(r'fd=(\d+)',m[5]);pending[tid]=(t,int(fd[1]) if fd else None)
 elif tid in pending:
  start,fd=pending.pop(tid);rows.append(dict(tid=tid,start_ns=start,end_ns=t,us=(t-start)/1000,fd=fd,file=target['fdmap'].get(str(fd))))
 else:unmatched_exit+=1
big=[r for r in rows if r['us']>1000]
for t in target['targets']:
 f=p/'trace'/f"broker-{t['pid']}-{t['tid']}.csv";records=[];sample=0
 for r in csv.DictReader(f.open()):
  records.append(dict(end_ns=int(r['end_ns']),phase_us=(int(r['end_ns'])-sample/23040000*1e9)/1000,sample=sample));sample+=int(r['samples'])
 stamps=[r['end_ns'] for r in records]
 for event in big:
  if event['tid']!=t['tid']:continue
  i=bisect.bisect_left(stamps,event['start_ns']);j=bisect.bisect_left(stamps,event['end_ns'])
  before=records[max(0,i-20):max(0,i-5)];after=records[j+5:j+20]
  if before and after:event['settled_phase_increment_us']=statistics.median(r['phase_us'] for r in after)-statistics.median(r['phase_us'] for r in before)
result=dict(targets=target['targets'],paired_writes=len(rows),unmatched_exit=unmatched_exit,unmatched_enter=len(pending),long_writes=big,note='Perf trace text reports FAILED TO PARSE for an optional buffer field; tid/timestamp/fd/count and exit events remain present. Durations are reconstructed from raw entry/exit timestamps. No IQ contents are used. Phase increment compares 15 nearby producer samples before/after a write, not a complete causal partition.')
(p/'write-analysis.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
