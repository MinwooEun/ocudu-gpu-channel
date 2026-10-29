from pathlib import Path
import json,hashlib,shutil,datetime,re
base=Path(__file__).resolve().parent.parent;work=base/'pacing-trace';out=work/'evidence';out.mkdir(exist_ok=True)
runs={'rr':'20261013T110621Z','qos':'20261013T111356Z'}
summary=[]
for policy,run in runs.items():
 dest=out/policy;dest.mkdir(exist_ok=True)
 native=base/'ocudu-native-workspace';reportdir=native/'results/reports/ocudu-scheduler-benchmark'/run
 logs=native/'results/logs/ocudu-scheduler-benchmark'/run
 for name in ['analysis.json','gnb0-clips.json','ue0-clips.json','ue1-clips.json']:
  shutil.copy2(work/policy/name,dest/name)
 for name in ['benchmark-report.json','gate-summary.json','run-parameters.json']:
  shutil.copy2(reportdir/name,dest/name)
 report=json.loads((reportdir/'benchmark-report.json').read_text());gate=json.loads((reportdir/'gate-summary.json').read_text())
 assert report['segments_valid']==120 and gate['status']=='passed'
 assert all(f['received']==f['scheduled'] and f['duplicates']==0 for f in report['checks']['flows'].values())
 analysis=json.loads((dest/'analysis.json').read_text())
 assert len(analysis['nodes'])==3
 for n,v in analysis['nodes'].items():
  assert abs(v['lost_progress_ms']-v['discarded_pacing_ms']-v['phase_difference_ms'])<1e-8
 if policy=='qos':assert not any(v['gpu_trace_missing'] for v in analysis['nodes'].values())
 lines=[s for s in (logs/'broker-a.log').read_text().splitlines() if s.startswith(('event=worker_summary ','event=process_latency_summary ','event=stop '))]
 (dest/'broker-summary.log').write_text('\n'.join(lines)+'\n')
 cfg=native/'configs/ocudu-scheduler-benchmark-native'/run
 for name in ['topology-a.yaml','gnb0.yaml','srsue-ue0.conf','srsue-ue1.conf','benchmark.json']:
  shutil.copy2(cfg/name,dest/name)
 rawhash={str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((work/policy).glob('*.bin'))}
 rawhash.update({str((logs/n).relative_to(base)):hashlib.sha256((logs/n).read_bytes()).hexdigest() for n in ['broker-a.log','gnb0-internal.log']})
 (dest/'raw-hashes.json').write_text(json.dumps(rawhash,indent=2)+'\n')
 row={'run':run,'scheduler':policy,'valid_seconds':report['segments_valid'],'gnb_slots_per_s':report['lanes']['a']['metrics']['resource_utilization']['slots_per_s'],'gate_broker':gate['brokers']['a'],'all_scheduled_packets_received':True}
 summary.append(row)
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
for name in ['analyze.py','collect.py','instrumentation.patch','source-hashes.json','clock-map.json','mutation-test.log','fixed-tests.log','instrumentation-v1.patch','reporting-fix.patch','clock-map-end.json']:
 if (work/name).exists():shutil.copy2(work/name,out/name)
shutil.copy2(work/'instrumented/diagnostic_trace.h',out/'diagnostic_trace.h')
# Corroborating gNB scheduler pause, matching the RR trace's output-consumption wait.
f=base/'ocudu-native-workspace/results/logs/ocudu-scheduler-benchmark'/runs['rr']/'gnb0-internal.log'
lines=[s for s in f.open() if s.startswith('2026-10-13T11:07:16.') and '.416'<=s[19:23]<='.425' and 'Slot decisions' in s]
(out/'rr-gnb-pause.log').write_text(''.join(lines))
print(json.dumps(summary,indent=2))
