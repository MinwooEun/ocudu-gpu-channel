from pathlib import Path
import json,sys,statistics,hashlib,re,shutil,math
base=Path(sys.argv[1]);w=base/'priority-load-20261014';n=base/'ocudu-native-workspace';out=w/'evidence';out.mkdir(exist_ok=True)
old=[];runs=sorted(p.name for p in (n/'results/reports/ocudu-scheduler-benchmark').iterdir() if p.name>=(w/'start-cutoff.txt').read_text().strip() and (p/'benchmark-report.json').exists())
obs=[json.loads(x) for x in (w/'iq-observed.jsonl').read_text().splitlines()];result=[];grids=[];configs=[];params=[]
def mean(v):return statistics.mean(x for x in v if x is not None)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for run in old+runs:
 rp=n/'results/reports/ocudu-scheduler-benchmark'/run;lp=n/'results/logs/ocudu-scheduler-benchmark'/run;cp=n/'configs/ocudu-scheduler-benchmark-native'/run
 report=json.loads((rp/'benchmark-report.json').read_text());par=json.loads((rp/'run-parameters.json').read_text());cfg=json.loads((cp/'benchmark.json').read_text());gate=json.loads((rp/'gate-summary.json').read_text());policy=report['lanes']['a']['scheduler'];cells=[s['cells']['a'] for s in report['segments'] if s['valid']]
 assert report['segments_valid']==120 and gate['status']=='passed';assert par['active_cells']==['a'] and par['ue_rx_sleep'] is False
 assert not (lp/'broker-b.log').exists() and not (lp/'gnb1-internal.log').exists();assert gate['policy_check']['ok']
 vals={}
 for ue,f in [('ue0','dl_bulk'),('ue1','dl_control'),('ue1','dl_video'),('ue0','ul_bulk'),('ue1','ul_control')]:
  delay=[c['ues'][ue]['flows'][f]['delay_ms']['p99'] for c in cells];check=report['checks']['flows'][ue+'.'+f];check={**check,'missing':check['sent']-check['received']}
  vals[f]={'mean_per_second_p99_ms':mean(delay),'seconds_with_packets':sum(x is not None for x in delay),'mean_per_second_p99_series_ms':delay,'delivery':check,'received_payload_mbps':check['received']*next(v['size_bytes'] for u in cfg['cells']['a']['ues'] if u['device_id']==ue for v in u['flows'] if v['name']==f)*8/120/1e6}
 row={'run':run,'policy':policy,'previous':run in old,'anchor_unix_ms':report['anchor_unix_ms'],'valid_seconds':report['segments_valid'],'flows':vals,'dl_prb_util_mean':mean(c['dl_prb_util'] for c in cells),'dl_prb_util_min':min(c['dl_prb_util'] for c in cells),'dl_prb_util_max':max(c['dl_prb_util'] for c in cells),'reported_slots_per_s':report['lanes']['a']['metrics']['resource_utilization']['slots_per_s'],'broker_counters':gate['brokers']['a'],'observed_iq':{}}
 for dev in ['gnb0_p0','ue0_p0','ue1_p0']:
  pts=[x for x in obs if x['run']==run and x['device']==dev and 60<=x['heartbeat_elapsed_s']<=130]
  if len(pts)>=30:
   a,b=pts[0],pts[-1];dt=(b['observed_monotonic_ns']-a['observed_monotonic_ns'])/1e9;cnt=b['acquired_samples']-a['acquired_samples'];row['observed_iq'][dev]={'first':a,'last':b,'elapsed_s':dt,'sample_delta':cnt,'samples_per_s':cnt/dt,'fraction_nominal':cnt/dt/23040000}
 result.append(row)
 if run in old:continue
 dest=out/run;dest.mkdir(exist_ok=True)
 for name in ['benchmark-report.json','run-parameters.json','gate-summary.json']:shutil.copy2(rp/name,dest/name)
 shutil.copy2(lp/'policy-check.json',dest/'policy-check.json')
 (dest/'config-hashes.json').write_text(json.dumps({name:sha(cp/name) for name in ['gnb0.yaml','topology-a.yaml','srsue-ue0.conf','srsue-ue1.conf','scenario-source.json','scenario.json','benchmark.json']},indent=2)+'\n')
 configs.append((run,cp,cfg));params.append(par)
 p={}
 for line in (lp/'sionna-status.jsonl').open():
  x=json.loads(line);t=x.get('timeline',{})
  if t.get('phase')=='run' and 0<=t['grid_index']<1200:p[t['grid_index']]={'positions':x['positions'],'hash':x['profile_sha256'],'channels':[{k:c[k] for k in ['link_id','taps']} for c in x['channels']]}
 assert set(p)==set(range(1200));grids.append(p)
checks=[]
for idx in range(1,len(configs)):
 run,cp,cfg=configs[idx];ref,rc,rg=configs[0];assert cfg['cells']['a']['ues']==rg['cells']['a']['ues']
 assert params[idx]['cpus']==params[0]['cpus'];assert params[idx]['sionna']==params[0]['sionna']
 for name in ['topology-a.yaml','srsue-ue0.conf','srsue-ue1.conf','scenario-source.json','scenario.json']:
  assert (cp/name).read_text().replace(run,'RUN')==(rc/name).read_text().replace(ref,'RUN'),name
 strip=lambda s:re.sub(r'(?ms)^  scheduler:\n.*?(?=^  [^\s])','',s)
 assert strip((cp/'gnb0.yaml').read_text().replace(run,'RUN'))==strip((rc/'gnb0.yaml').read_text().replace(ref,'RUN'))
 count=0;mg=mp=md=0.
 for k in range(1200):
  a,b=grids[0][k],grids[idx][k];assert a['positions']==b['positions'];count+=a['hash']==b['hash'];aa={c['link_id']:c['taps'] for c in a['channels']};bb={c['link_id']:c['taps'] for c in b['channels']};assert aa.keys()==bb.keys()
  for link,taps in aa.items():
   assert len(taps)==len(bb[link])
   for x,y in zip(taps,bb[link]):mg=max(mg,abs(x['gain_db']-y['gain_db']));mp=max(mp,abs(math.remainder(x['phase_rad']-y['phase_rad'],2*math.pi)));md=max(md,abs(x['delay_samples']-y['delay_samples']))
 checks.append({'reference_run':ref,'run':run,'traffic_and_resources_identical':True,'gnb_configuration_only_scheduler_differs':True,'positions_and_tap_counts_identical':True,'grid_points':1200,'identical_profile_hashes':count,'max_gain_difference_db':mg,'max_phase_difference_rad':mp,'max_delay_difference_samples':md})
summary={'metric':'Mean of valid one-second p99 delivered-packet one-way UDP delay, averaged equally across runs; not a pooled p99. Loss is reported separately.','runs':result,'matched_checks':checks,'aggregate':{}}
for policy in ['rr','qos']:
 rows=[x for x in result if not x['previous'] and x['policy']==policy]
 if rows:summary['aggregate'][policy]={'runs':len(rows),'flows':{f:{'mean_ms':mean(r['flows'][f]['mean_per_second_p99_ms'] for r in rows),'run_values_ms':[r['flows'][f]['mean_per_second_p99_ms'] for r in rows],'sent':sum(r['flows'][f]['delivery']['sent'] for r in rows),'received':sum(r['flows'][f]['delivery']['received'] for r in rows)} for f in rows[0]['flows']},'dl_prb_util_mean':mean(r['dl_prb_util_mean'] for r in rows)}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({'runs':[{'run':r['run'],'policy':r['policy'],'prb':r['dl_prb_util_mean'],'delays':{k:round(v['mean_per_second_p99_ms'],3) for k,v in r['flows'].items()},'missing':{k:v['delivery']['missing'] for k,v in r['flows'].items()},'slots_per_s':r['reported_slots_per_s'],'starvations':r['broker_counters']['rx_starvations']} for r in result],'matched_checks':checks},indent=2))
resources=[]
for name in ['resource-snapshots.jsonl','resource-observed.jsonl']:
 if not (w/name).exists():continue
 for line in (w/name).read_text().splitlines():
  v=json.loads(line);procs=v['processes'];ids=set();clean=[]
  for p in procs:
   rr=re.search(r'/([0-9]{8}T[0-9]{6}Z)/',p['command'])
   if rr:ids.add(rr[1])
   expect='20' if p['name']=='ocudu-gpu-chann' else '0-7' if p['name']=='gnb' else '8-19'
   assert p['cpus']==expect,(p['name'],p['cpus']);assert p['diagnostic_environment']==['LD_PRELOAD=/usr/libexec/coreutils/libstdbuf.so'],p
   clean.append({k:p[k] for k in ['name','cpus']})
  assert len(ids)<=1 and sum(p['name']=='gnb' for p in procs)<=1 and sum(p['name']=='ocudu-gpu-chann' for p in procs)<=1 and sum(p['name']=='srsue' for p in procs)<=2
  resources.append({'unix_ns':v['unix_ns'],'run_ids':sorted(ids),'processes':clean})
(out/'resource-check.json').write_text(json.dumps({'single_cell_only':True,'no_diagnostic_interposer':True,'cpu_sets_match':True,'snapshots':resources},indent=2)+'\n')
summary['resource_check']={'single_cell_only':True,'no_diagnostic_interposer':True,'cpu_sets_match':True,'run_ids_observed':sorted({x for v in resources for x in v['run_ids']})}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
shutil.copy2(w/'sequence-status.log',out/'sequence-status.log')
for f in ['collect.py','observe.py','resources.py']:shutil.copy2(w/f,out/f)
(out/'source-hashes.json').write_text(json.dumps({str(f.relative_to(base/'repo')):sha(f) for f in [base/'repo/src/broker.cpp',base/'repo/src/cuda_backend.cu',base/'repo/use_cases/scheduler_benchmark/traffic.py',base/'repo/use_cases/scheduler_benchmark/analyze.py',base/'repo/use_cases/scheduler_benchmark/definitions.py']},indent=2)+'\n')
# Verify the change against the earlier 70/12 Mb/s run.
prior_run='20261013T154902Z'
prior_cfg=json.loads((n/'configs/ocudu-scheduler-benchmark-native'/prior_run/'benchmark.json').read_text())
prior_par=json.loads((n/'results/reports/ocudu-scheduler-benchmark'/prior_run/'run-parameters.json').read_text())
for run,cp,cfg in configs:
 u=json.loads(json.dumps(cfg['cells']['a']['ues']))
 f=next(f for f in u[1]['flows'] if f['name']=='dl_video');assert f['rate_mbps']==40;f['rate_mbps']=12
 assert u==prior_cfg['cells']['a']['ues']
 par=json.loads((n/'results/reports/ocudu-scheduler-benchmark'/run/'run-parameters.json').read_text())
 assert par['cpus']==prior_par['cpus'] and par['sionna']==prior_par['sionna']
for r in summary['runs']:
 assert all(r['broker_counters'][k]==0 for k in ['tx_queue_overflows','tx_sequence_gaps','zmq_errors'])
summary['setup_change']={'reference_run':prior_run,'only_traffic_change':'ue1.dl_video.rate_mbps: 12 to 40','cpu_and_sionna_settings_unchanged':True}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
queue=[];raw={}
for row in summary['runs']:
 run=row['run'];lp=n/'results/logs/ocudu-scheduler-benchmark'/run
 for name in ['gnb0-internal.log','broker-a.log','tx-dl.csv','rx-dl-ue0.bin','rx-dl-ue1.bin','sionna-status.jsonl','host-load.jsonl']:
  raw[f'{run}/{name}']=sha(lp/name)
 count=0;examples=[]
 for line in (lp/'gnb0-internal.log').open(errors='replace'):
  if 'RLC SDU queue is full' in line:
   count+=1
   if len(examples)<3:examples.append(line.strip())
 queue.append({'run':run,'policy':row['policy'],'logged_full_rlc_queue_events':count,'examples':examples})
(out/'queue-log-examples.json').write_text(json.dumps(queue,indent=2)+'\n')
(out/'raw-hashes.json').write_text(json.dumps(raw,indent=2)+'\n')
