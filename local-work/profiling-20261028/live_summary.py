import csv,json,pathlib,re,statistics,math
P=pathlib.Path('/workspace/gpuch/profile-20261028')
clock=json.loads((P/'clock-pair.json').read_text());offset=clock['realtime_ns']-clock['monotonic_ns']
def pct(a,p):return sorted(a)[max(0,math.ceil(len(a)*p)-1)]
result=[]
for d in (P/'live').glob('cuda-u*-c1-bw20-a1x1*'):
 log=(d/'runner.log').read_text();m=re.search(r'saved (/[^\n]+)',log)
 if not m:continue
 session=pathlib.Path(m[1]); reports=[]
 for report in sorted(session.glob('policy_runs/*/report/run-report.json')):
  r=json.loads(report.read_text());e=r.get('epoch')
  if not e:continue
  warm=r.get('warmup_seconds',10);rate=e['sample_rate_hz'];start=e['s0']+int(warm*rate);end=e['s0']+e['measure_samples']
  applied=[json.loads(l) for l in (report.parent.parent/'logs/replay-applied.jsonl').read_text().splitlines()]
  timestamps=[x['observed_unix_ns'] for x in applied if x.get('record')=='applied']
  reports.append(dict(run=report.parent.parent.name,path=str(report),runtime=r['runtime'],segments_valid=r.get('segments_valid'),decision_latency=r['metrics'].get('decision_latency_us'),start_sample=start,end_sample=end,rate=rate,first_wall_ns=min(timestamps),last_wall_ns=max(timestamps)))
 record=dict(label=d.name,session=str(session),runs=reports,receivers=[])
 for f in sorted((d/'trace').glob('*.csv')):
  kind=f.name.split('-')[0]
  if kind not in ('channel','broker'):continue
  rows=list(csv.DictReader(f.open()));rows=[r for r in rows if None not in r and all(v is not None for v in r.values())]
  if not rows:continue
  timecol='start_ns' if kind=='channel' else 'end_ns'
  first=int(rows[0][timecol])+offset;last=int(rows[-1][timecol])+offset
  matches=[r for r in reports if first<r['first_wall_ns'] and last>r['last_wall_ns']-1e9]
  if len(matches)!=1:
   record['receivers'].append(dict(file=f.name,error='No unique full measurement window',first=first,last=last));continue
  report=matches[0];cur=0;selected=[]
  for r in rows:
   count=int(r['samples']);begin=cur;cur+=count
   if begin>=report['start_sample'] and cur<=report['end_sample']:selected.append(r)
  if not selected:
   record['receivers'].append(dict(file=f.name,error='No rows in reconstructed sample window',total_samples=cur));continue
  metrics={}
  for k in [k for k in selected[0] if k.endswith('_us')]:
   v=[float(r[k]) for r in selected];metrics[k]=dict(mean=statistics.mean(v),p50=pct(v,.5),p99=pct(v,.99),max=max(v))
  first_ns=int(selected[0][timecol]);last_ns=int(selected[-1][timecol]);radio_samples=sum(int(r['samples']) for r in selected)
  cost='call_us' if kind=='channel' else 'process_us'
  record['receivers'].append(dict(kind=kind,file=f.name,run=report['run'],node=rows[0]['node'],calls=len(selected),radio_samples=radio_samples,total_samples=cur,expected_end_sample=report['end_sample'],window_complete=cur>=report['end_sample'],wall_s=(last_ns-first_ns)/1e9,metrics=metrics,miss_fraction=sum(float(r[cost])>int(r['samples'])/report['rate']*1e6 for r in selected)/len(selected)))
 result.append(record)
(P/'live-summary.json').write_text(json.dumps(result,indent=2))
for r in result:
 print(r['label'],'ratios',[q['runtime']['real_time_ratio'] for q in r['runs']])
 for q in r['receivers']:
  if q.get('node')=='gnb0' and q.get('kind')=='channel':print(' ',q['run'],'complete',q['window_complete'],'call',q['metrics']['call_us'],'CPU',q['metrics']['thread_cpu_us']['mean'])
