import pathlib,re,json,datetime,sys,statistics,hashlib
base=pathlib.Path(sys.argv[1]);native=base/'ocudu-native-workspace';results=[]
# Conservative timing bound: heartbeat t is steady-clock elapsed seconds truncated
# to an integer. Each endpoint therefore represents an unknown fraction in [0,1).
for run in sys.argv[2:]:
 log=native/'results/logs/ocudu-scheduler-benchmark'/run
 report=json.loads((native/'results/reports/ocudu-scheduler-benchmark'/run/'benchmark-report.json').read_text());anchor=report['anchor_unix_ms']/1000;end=anchor+120
 row={'scheduler': report['lanes']['a']['scheduler'], 'segments_valid': report['segments_valid'], 'run':run,'measurement_anchor_unix_ms':report['anchor_unix_ms'],'measurement_seconds':120,'cells':{}}
 for cell,gnb in [('a','gnb0')]:
  broker=log/f'broker-{cell}.log';ports={};excerpts=[];stages=[]
  for line in broker.open():
   m=re.search(r'^event=heartbeat t=(\d+) dev=(\S+).*? acquired=(\d+).*?starvations_total=(\d+)',line)
   if m:
    t=int(m[1]);ports.setdefault(m[2],{})[t]={'samples':int(m[3]),'starvations_total':int(m[4])}
    if t in [60,130]:excerpts.append(line.strip())
  iq={}
  for dev,points in ports.items():
   a,b=points[60],points[130];count=b['samples']-a['samples'];rate=count/70
   iq[dev]={'from_elapsed_s':60,'to_elapsed_s':130,'from_samples':a['samples'],'to_samples':b['samples'],'sample_delta':count,'samples_per_s':rate,'fraction_of_realtime':rate/23040000,'conservative_fraction_bounds':[count/71/23040000,count/69/23040000],'input_waits_over_5_ms_in_window':b['starvations_total']-a['starvations_total']}
  first=None;last=None;base_slot=0;prev=None;count=0;reordered=0
  for line in (log/f'{gnb}-internal.log').open(errors='replace'):
   if 'Slot decisions' not in line:continue
   m=re.match(r'(\S+) \[SCHED\s*\] \[\w\] \[\s*(\d+)\.(\d+)\] Slot decisions',line)
   if not m:continue
   wall=datetime.datetime.fromisoformat(m[1]).replace(tzinfo=datetime.timezone.utc).timestamp();raw=int(m[2])*10+int(m[3])
   if prev is not None and raw<prev-5120:base_slot+=10240
   unwrapped=base_slot+raw
   if prev is not None and raw>prev+5120:unwrapped-=10240;reordered+=1
   else:prev=raw
   if anchor<=wall<=end:
    point={'wall_unix_s':wall,'absolute_slot':unwrapped,'line':line[:200].strip()};first=first or point;last=point;count+=1
  assert first and last
  dt=last['wall_unix_s']-first['wall_unix_s'];dn=last['absolute_slot']-first['absolute_slot']
  console=(log/f'{gnb}-console.log').read_text();warnings=[s for s in console.splitlines() if 'Scheduling priority' in s]
  row['cells'][cell]={'iq_sample_progress':iq,'heartbeat_excerpts':excerpts,'independent_slot_progress':{'first':first,'last':last,'elapsed_wall_seconds':dt,'slot_delta':dn,'slots_per_s':dn/dt,'logged_decisions':count,'wrapped_late_lines':reordered},'reported_slots_per_s':report['lanes'][cell]['metrics']['resource_utilization']['slots_per_s'],'priority_warnings':warnings,'log_sha256':{'broker':hashlib.sha256(broker.read_bytes()).hexdigest()}}
 row['bulk_delay_per_second_p99_ms']=[s['cells']['a']['ues']['ue0']['flows']['dl_bulk']['delay_ms']['p99'] for s in report['segments'] if s['valid']]
 row['mean_bulk_delay_p99_ms']=statistics.mean(row['bulk_delay_per_second_p99_ms'])
 row['gate']=json.loads((native/'results/reports/ocudu-scheduler-benchmark'/run/'gate-summary.json').read_text())
 row['traffic_checks']=report['checks']['flows']
 row['sionna']=report['sionna']
 results.append(row)
out={'sample_rate_hz':23040000,'samples_per_radio_slot':23040,'method':'IQ acquired counter counts cf32 samples successfully copied from each radio TX into its broker ring. Compare samples at monotonic heartbeat t=60 and t=130; per-port counts, not message or producer-call counts. Independently unwrap gNB SFN.slot and divide endpoint slot progress by wall time inside each 120-second measurement. Heartbeat comparison uses an interior window rather than exactly the same 120-second endpoints.','heartbeat_timing_bound':'Integer seconds imply conservative 69–71 s elapsed for the selected nominal 70 s window; both bounds remain below nominal rate.','runs':results}
path=base/'single-cell'/'radio-speed-audit.json';path.write_text(json.dumps(out,indent=2)+'\n');print(path)
for row in results:
 for cell,c in row['cells'].items():print(row['run'],cell,'slot/s',round(c['independent_slot_progress']['slots_per_s'],3),'IQ MS/s',[round(x['samples_per_s']/1e6,6) for x in c['iq_sample_progress'].values()])
