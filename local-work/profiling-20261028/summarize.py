import csv,json,math,pathlib,statistics,sys
P=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '/workspace/gpuch/profile-20261028')
def pct(v,p):
 v=sorted(v);return v[max(0,math.ceil(len(v)*p)-1)] if v else None
records=[]
groups=sys.argv[2:] or ['*']
for d in sorted(set(d for group in groups for d in P.glob(group+'/**/trace'))):
 if not d.is_dir():continue
 for kind,timecol in [('channel','start_ns'),('broker','end_ns')]:
  by={}
  for f in d.glob(kind+'-*.csv'):
   with f.open() as stream:
    for r in csv.DictReader(stream):
     try:
      if None in r or any(v is None for v in r.values()):continue
      by.setdefault((r['node'],f.name),[]).append(r)
     except (ValueError,KeyError):continue
  for (node,filename),rows in by.items():
   t=[int(r[timecol]) for r in rows]; lo=min(t)+2e9;hi=max(t)-1e9
   # Interior steady window, reported explicitly; initial JIT and final drain are retained in raw data.
   rows=[r for r in rows if lo<=int(r[timecol])<=hi]
   if not rows:continue
   rate=float(rows[0]['rate_hz']); counts=[int(r['samples']) for r in rows]
   entry=dict(run=str(d.parent.relative_to(P)),file=filename,kind=kind,node=node,calls=len(rows),window_ns=[int(lo),int(hi)],sample_rate_hz=rate,sample_counts=sorted(set(counts)),represented_radio_s=sum(counts)/rate,window_wall_s=(hi-lo)/1e9)
   if kind=='broker':entry['interior_completion_ratio']=entry['represented_radio_s']/entry['window_wall_s']
   keys=[k for k in rows[0] if k.endswith('_us')]
   entry['timing']={k:dict(mean=statistics.mean(v:= [float(r[k]) for r in rows]),p50=pct(v,.5),p95=pct(v,.95),p99=pct(v,.99),max=max(v)) for k in keys}
   cost='call_us' if kind=='channel' else 'process_us'
   entry['call_deadline_miss_fraction']=sum(float(r[cost])>float(r['samples'])/rate*1e6 for r in rows)/len(rows)
   if kind=='channel':entry['direct_in_values']=sorted(set(r['direct_in'] for r in rows))
   records.append(entry)
(P/'timing-summary.json').write_text(json.dumps(records,indent=2))
with (P/'timing-summary.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['run','kind','node','calls','radio_s','wall_s','metric','mean_us','p50_us','p99_us','max_us','call_miss_fraction'])
 for r in records:
  for k,v in r['timing'].items():w.writerow([r['run'],r['kind'],r['node'],r['calls'],r['represented_radio_s'],r['window_wall_s'],k,v['mean'],v['p50'],v['p99'],v['max'],r['call_deadline_miss_fraction']])
print('receiver summaries',len(records))
for r in records:
 if r['kind']=='channel' and r['node'].startswith('gnb'):
  print(r['run'],r['node'],'call p50/p99',r['timing']['call_us']['p50'],r['timing']['call_us']['p99'],'prep',sum(r['timing'][k]['mean'] for k in ('entry_pack_us','model_control_us','rx_prep_us')),'submit/sync',r['timing']['submit_us']['mean'],r['timing']['sync_wait_us']['mean'])
