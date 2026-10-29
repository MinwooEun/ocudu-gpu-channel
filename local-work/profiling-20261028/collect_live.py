import pathlib,json,re,shutil,csv,statistics,math
P=pathlib.Path('/workspace/gpuch/profile-20261028')
def pct(v,p):return sorted(v)[max(0,math.ceil(len(v)*p)-1)]
summaries=[]
for d in (P/'live').iterdir():
 if not (d/'runner.log').exists() or not (d/'result.json').exists():continue
 evidence=d/'evidence';evidence.mkdir(exist_ok=True);text=(d/'runner.log').read_text()
 m=re.search(r'saved (/[^\n]+)',text)
 if m:
  s=pathlib.Path(m[1])
  if (s/'reports').exists():shutil.copytree(s/'reports',evidence/'reports',dirs_exist_ok=True)
  for r in s.glob('policy_runs/*'):
   e=evidence/r.name;e.mkdir(exist_ok=True)
   for sub in ('report','configs'):
    if (r/sub).exists():shutil.copytree(r/sub,e/sub,dirs_exist_ok=True)
   for name in ('replay-applied.jsonl','replay-bridge.log','broker.log','local-knobs.log'):
    if (r/'logs'/name).exists():shutil.copy2(r/'logs'/name,e/name)
  continue
 matches=re.findall(r'report=(/workspace/ocudu-spark/results/reports/oai-2x2/\w+)',text)
 if not matches:continue
 report=pathlib.Path(matches[-1]);ts=report.name;logs=pathlib.Path('/workspace/ocudu-spark/results/logs/oai-2x2')/ts
 shutil.copytree(report,evidence/'report',dirs_exist_ok=True)
 for name in ('iperf3-dl.json','broker.log','gate-defaults.log'):
  if (logs/name).exists():shutil.copy2(logs/name,evidence/name)
 rank=json.loads((report/'rank-summary.json').read_text());run=json.loads((report/'run-summary.json').read_text())
 entry=dict(label=d.name,report=str(report),rank=rank,run=run,receivers=[])
 if not (logs/'iperf3-dl.json').exists():continue
 ip=json.loads((logs/'iperf3-dl.json').read_text());t0=ip['start']['timestamp']['timesecs'];duration=ip['end']['sum_received']['seconds']
 cp=json.loads((d/'clock-pair.json').read_text());off=cp['realtime_ns']-cp['monotonic_ns'];lo=t0*1e9-off;hi=(t0+duration)*1e9-off
 entry['timing_window']=dict(start_monotonic_ns=lo,end_monotonic_ns=hi,definition='iperf timestamp (integer wall seconds) and measured iperf duration; at most 1 second start resolution')
 for f in (d/'trace').glob('*.csv'):
  kind=f.name.split('-')[0]
  if kind not in ('channel','broker'):continue
  tc='start_ns' if kind=='channel' else 'end_ns';rows=[]
  for r in csv.DictReader(f.open()):
   if None in r or any(v is None for v in r.values()):continue
   if lo<=int(r[tc])<=hi:rows.append(r)
  if not rows:continue
  metrics={k:dict(mean=statistics.mean(v:=[float(r[k]) for r in rows]),p50=pct(v,.5),p99=pct(v,.99),max=max(v)) for k in rows[0] if k.endswith('_us')}
  rate=float(rows[0]['rate_hz']);radio_ms=sum(int(r['samples']) for r in rows)/rate*1000
  entry['receivers'].append(dict(kind=kind,node=rows[0]['node'],calls=len(rows),sample_counts=sorted(set(int(r['samples']) for r in rows)),represented_radio_ms=radio_ms,calls_per_radio_ms=len(rows)/radio_ms,metrics=metrics))
 summaries.append(entry)
(P/'oai-summary.json').write_text(json.dumps(summaries,indent=2))
for r in summaries:print(r['label'],r['rank'].get('realtime_factor'),r['rank'].get('health'))
