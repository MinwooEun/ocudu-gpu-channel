"""Summarize diagnostic UE traces after warmup, using observed control boundaries.
GPU spans, host waits and total durations overlap; these statistics are not additive.
"""
import argparse,collections,json,pathlib
p=argparse.ArgumentParser();p.add_argument('case_dir',type=pathlib.Path);a=p.parse_args();d=a.case_dir
launch=json.loads((d/'launch.json').read_text());ref=launch['clock_reference'];offset=ref['unix_ns']-ref['monotonic_ns']
control={}
for line in (d/'runtime/logs/replay-applied.jsonl').open():
 r=json.loads(line)
 if r.get('record')=='applied' and r.get('link_id')=='gnb0>ue0:sionna_rt' and r.get('k') in [100,399]:control[r['k']]=r['observed_unix_ns']-offset
assert len(control)==2,control
lo,hi=control[100],control[399]
cols={('ccw','FFT'):[2],('ccw','CSI'):[2],('ccw','PDCCH'):[2],('ccw','PDok'):[2,3,4],('ccw','PDnok'):[2,3,4],('ccw','PU'):[4],('uedl','GFFT'):[2,3],('uedl','GPDSCH'):[2,4],('uedl','GPT'):[2,3,4],('uedl','GPG'):[2,3],('uedl','CHEST'):[2],('uedl','PDEC'):[2],('pdsch','EQ'):[2],('pdsch','DEMOD'):[2],('pdsch','SCH'):[2],('worker','DL'):[2],('worker','UL'):[2],('worker','DU'):[2],('worker','WE'):[2],('sync','WW'):[2],('sync','RX'):[2],('sync','TX'):[2],('schnr','TB'):[2,4]}
all_values=collections.defaultdict(list);by_pid=collections.defaultdict(lambda:collections.defaultdict(list));rows=collections.Counter();pdsch_groups=collections.defaultdict(list);malformed=0
for f in (d/'trace').glob('*.csv'):
 pid,tag=f.stem.split('-',1)
 with f.open() as fh:
  next(fh,None)
  for line in fh:
   try:
    s=line.rstrip().split(',');t=int(s[0])
    if not lo<=t<hi:continue
    key=(tag,s[1]);needed=cols.get(key)
    if needed is None:continue
    v=[t,int(s[2]),int(s[3]),int(s[4]),int(s[5])];rows[pid]+=1
    if key in [('ccw','PDok'),('ccw','PDnok')]:pdsch_groups[f'{v[3]//100}:{v[3]%100}:{v[2]}'].append(v[4])
    for i in needed:
     name=tag+'/'+s[1]+'/'+str(i);all_values[name].append(v[i]);by_pid[pid][name].append(v[i])
   except (ValueError,IndexError):malformed+=1

def stats(v):
 v.sort();n=len(v)
 return dict(n=n,p50=v[n//2],p90=v[min(n-1,int(n*.9))],p99=v[min(n-1,int(n*.99))],max=v[-1],mean=sum(v)/n)
aggregate={k:stats(v) for k,v in all_values.items()}
per_pid={pid:{k:stats(v) for k,v in data.items()} for pid,data in by_pid.items()}
count=lambda name:len(all_values.get(name,[]))
gp=count('uedl/GPDSCH/2');pd=count('ccw/PDok/4')+count('ccw/PDnok/4');fft=all_values.get('uedl/GFFT/3',[])
result=dict(case=d.name,window=dict(monotonic_start_ns=lo,monotonic_end_ns=hi,wall_s=(hi-lo)/1e9,reference='Observed gnb0>ue0 applied updates k=100 to k=399; approximately 29.9 radio seconds after 10-second warmup. Trace records use completion timestamps; control observation and buffering introduce boundary uncertainty.'),trace_processes=len(rows),parsed_rows=sum(rows.values()),malformed_rows=malformed,gpu_pdsch_count=gp,pdsch_total=pd,gpu_pdsch_share=gp/pd if pd else None,gpu_fft_count=len(fft),gpu_fft_fallback=sum(x==0 for x in fft),dl_over_1ms=sum(x>1000 for x in all_values.get('worker/DL/2',[])),aggregate=aggregate,per_pid=per_pid,pdsch_groups_prb_mcs_tbs={k:stats(v) for k,v in pdsch_groups.items()},note='Column 2 is a, 3 is b, 4 is c; units depend on trace producer. GPU GPT: launch, RM+LDPC launch, completion wait (us). GPG: GPU event span, host bit unpack and measurement readout (us); CPU CRC lies outside the unpack timer. GPU span includes stream scheduling intervals; it is not pure arithmetic time. Nested totals overlap; do not sum percentiles. Trace-enabled runs are diagnostic, separate from clean performance comparisons.')
(d/'trace-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ['aggregate','per_pid','pdsch_groups_prb_mcs_tbs']}))
for k in ['ccw/FFT/2','ccw/CSI/2','ccw/PDCCH/2','uedl/GPDSCH/2','uedl/GPT/2','uedl/GPT/3','uedl/GPT/4','uedl/GPG/2','uedl/GPG/3','pdsch/SCH/2','worker/DL/2','sync/WW/2']:
 if k in aggregate:print(k,aggregate[k])
