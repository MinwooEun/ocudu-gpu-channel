"""Collect compact experiment evidence without modifying Spark runs."""
import collections,json,pathlib,subprocess
BASE='/workspace/gpuch/gpu-ue-live-20261030'
program="""import json,pathlib,hashlib
b=pathlib.Path(%r);out={}
for n in [8,16]:
 for p in (b/('u'+str(n))).glob('*'):
  if not p.is_dir():continue
  for f in ['launch.json','result.json','capacity-window.json','trace-summary.json','trace-audit.json','connection-loss-evidence.json','runtime/report/run-report.json','runtime/report/gate-summary.json']:
   q=p/f
   if q.exists():out[str(q.relative_to(b))]=json.loads(q.read_text())
  lifecycle={}
  for q in (p/'runtime/logs').glob('srsue-ue*.log'):
   raw=q.read_bytes();matches=[dict(line=i,text=x) for i,x in enumerate(raw.decode(errors='replace').splitlines(),1) if any(k in x for k in ['[ue_dl_cuda] mode=','[ldpc_cuda] backend=','RRC Connected','PDU Session Establishment','Scheduling request failed','out-of-sync','Received RRC Release'])]
   lifecycle[str(q.relative_to(p))]=dict(sha256=hashlib.sha256(raw).hexdigest(),matches=matches)
  out[str(p.relative_to(b))+'/ue-lifecycle.json']=lifecycle
print(json.dumps(out))
""" % BASE
raw=subprocess.run(['ssh','spark-minwoo','python3','-'],input=program,text=True,check=True,capture_output=True)
files=json.loads(raw.stdout);root=pathlib.Path(__file__).resolve().parent;summary=[]
for rel,data in files.items():
 p=root/'evidence'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2)+'\n')
 if rel.endswith('/run-report.json'):
  case=rel.split('/runtime/')[0];segments=[s for s in data['segments'] if not s.get('warmup')]
  item=dict(case=case,runtime=data['runtime'],segments_complete=data['segments_complete'],segments_valid=data['segments_valid'],invalid_reasons=dict(collections.Counter(r for s in segments for r in s.get('reasons',[]))),all_measured_segment_app_dl_mbps=sum(s['dl_mbps'] for s in segments)/len(segments),per_ue_link={u:v.get('link') for u,v in data['metrics']['per_ue'].items()})
  capacity=files.get(case+'/capacity-window.json')
  if capacity:item['four_second_observation']={k:capacity[k] for k in ['wall_s','radio_s','radio_wall_ratio','ue_scheduled_cores','ue_cpu_seconds_per_radio_second','ue_roles_cpu_s']}
  summary.append(item)
(root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
for s in summary:print(s['case'],s['runtime']['real_time_ratio'],s['segments_valid'],'valid segments')
