from pathlib import Path
import json,csv,re,sys,collections,datetime,numpy as np
base=Path(sys.argv[1]);run=sys.argv[2];policy=sys.argv[3]
native=base/'ocudu-native-workspace';logs=native/'results/logs/ocudu-scheduler-benchmark'/run;report=json.loads((native/'results/reports/ocudu-scheduler-benchmark'/run/'benchmark-report.json').read_text());start=report['anchor_unix_ms'];end=start+120000
metrics=[];mac=[];rows=0
for line in (logs/'gnb-metrics-a.jsonl').open():
 x=json.loads(line);t=x['rx_unix_ms'];p=x['payload']
 if not start+1000<=t<=end:continue
 for cell in p.get('cells',[]):metrics.append(cell.get('cell_metrics',{}))
 mac.extend(p.get('du',{}).get('du_high',{}).get('mac',{}).get('dl',[]))
assert len(metrics)>=110 and len(mac)>=110
keys=['error_indication_count','late_dl_harqs','late_ul_harqs','failed_dl_pdcch','failed_ul_pdcch','nof_failed_uci_allocs']
out={'run':run,'policy':policy,'gnb':{'metric_reports':len(metrics),'interval_counters':{k:sum(m.get(k,0) for m in metrics) for k in keys},'scheduler_mean_reported_us':float(np.mean([m['average_latency'] for m in metrics])),'scheduler_max_reported_us':max(m['max_latency'] for m in metrics),'mac_dl_mean_reported_us':float(np.mean([m['average_latency_us'] for m in mac])),'mac_dl_max_reported_us':max(m['max_latency_us'] for m in mac)},'logs':{},'ue_metrics':{},'broker':{}}
for name in ['gnb0-internal.log','srsue-ue0-internal.log','srsue-ue1-internal.log']:
 counts=collections.Counter();examples={};latencies=[]
 # Timestamped runtime-only events; startup warnings recorded separately.
 lower=datetime.datetime.fromtimestamp(start/1000,datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','')
 upper=datetime.datetime.fromtimestamp(end/1000,datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','')
 for line in (logs/name).open(errors='replace'):
  if not lower<=line[:23]<upper:continue
  for key,pattern in [('warning',r'\[W\]'),('error',r'\[E\]'),('rf_failure',r'Real-time failure in RF'),('overflow',r'\boverflow\b'),('underflow',r'\bunderflow\b'),('late',r'\blate\b'),('queue_failure',r'Unable to (enqueue|initiate).*task')]:
   if re.search(pattern,line,re.I):counts[key]+=1;examples.setdefault(key,line[:240].rstrip())
  if 'Stack latency:' in line:
   m=re.search(r'Stack latency: (\d+) us',line)
   if m:latencies.append(int(m[1]))
 v={'runtime_event_counts':dict(counts),'examples':examples}
 if latencies:v['gateway_stack_latency_us']={'count':len(latencies),'median':float(np.median(latencies)),'p99':float(np.quantile(latencies,.99)),'max':max(latencies),'above_1ms':sum(t>1000 for t in latencies)}
 out['logs'][name]=v
for ue in ['ue0','ue1']:
 with (logs/f'srsue-metrics-{ue}.csv').open() as f:
  values=[r for r in csv.DictReader(f,delimiter=';') if r.get('rf_o') is not None]
 assert len(values)>120
 out['ue_metrics'][ue]={'reports':len(values),'whole_run_rf_counts':{k:sum(float(r[k]) for r in values) for k in ['rf_o','rf_u','rf_l']},'coverage_limit':'ZMQ register_error_handler is a no-op: these zero RF counters cannot establish absence of underruns/overruns.'}
for line in (logs/'broker-a.log').open():
 if line.startswith('event=stop '):out['broker']['stop']={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
 if line.startswith('event=heartbeat '):
  m=re.search(r't=(\d+) dev=(\S+) ring=(\d+)/(\d+).* acquired=(\d+).*starvations_total=(\d+)',line)
  if m:
   out['broker'].setdefault('heartbeats',{}).setdefault(m[2],[]).append({'t':int(m[1]),'ring':int(m[3]),'capacity':int(m[4]),'acquired':int(m[5]),'starvations_total':int(m[6])})
out['traffic_checks']=report['checks']['flows'];out['valid_seconds']=report['segments_valid']
path=base/'runtime-audit'/policy/'stack-counters.json';path.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k not in ['broker','traffic_checks']},indent=2))
