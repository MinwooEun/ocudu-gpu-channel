import pathlib,subprocess as sp,json,time,sys
P=pathlib.Path('/workspace/gpuch/profile-20261029-causal');B=pathlib.Path('/workspace/gpuch/profile-20261028/ranb/use_cases/ran_benchmark');out=[]
for d in sorted((P/'pr10-frozen').iterdir()):
 if not (d/'result.json').exists():continue
 l=json.load(open(d/'launch.json'));f=pathlib.Path(l['frozen_bundle']);r=d/'runtime';report=r/'report/run-report.json'
 if not report.exists():
  with (d/'analysis.log').open('w') as log:sp.run(['python3',str(B/'single_cell_analyze.py'),'--run-root',str(r),'--channel-bundle',str(f/'channel'),'--traffic-bundle',str(f/'traffic'),'--live','--warmup-seconds','10'],stdout=log,stderr=log,check=True)
 a=json.load(open(report));item=dict(case=d.name,ratio=a['runtime']['real_time_ratio'],valid_segments=a['segments_valid'],complete_segments=a['segments_complete'],faults=a['runtime']['broker'],epoch=a['epoch'],gate=json.load(open(r/'report/gate-summary.json')))
 out.append(item)
(P/'pr10-summary.json').write_text(json.dumps(out,indent=2))
for a in out:print(a['case'],a['ratio'],a['valid_segments'],a['faults'].get('rx_starvations'),flush=True)
