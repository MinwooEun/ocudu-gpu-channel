"""Collect completed captures; all heavy aggregation runs after GPU measurements."""
import pathlib,json,csv,re,gzip,hashlib,subprocess as sp,os,time,collections
W=pathlib.Path(__file__).resolve().parent;HOST='spark' if str(W).startswith('/workspace') else 'rtx';aux={0,1,2,3,4} if HOST=='spark' else {20,21,22,23};os.sched_setaffinity(0,aux);out=W/'evidence';out.mkdir(exist_ok=True);rows=[]
for d in sorted((W/'cases').iterdir()):
 if not (d/'result.json').exists():continue
 r=json.loads((d/'result.json').read_text());m=json.loads((d/'launch.json').read_text());cpu=json.loads((d/'cpu.json').read_text());mode=r['mode'];label=r['label'];variant=m.get('resource_profile','matched-five-fast-cores');primary=(mode=='iq' and variant=='ready-start-iq') or (mode=='radio' and variant=='matched-five-fast-cores' and '-r0' not in label)
 initialized=r.get('details',{}).get('all_workers_initialized_before_measurement');log=(d/'broker.log').read_text(errors='replace') if (d/'broker.log').exists() else '';first_ready={}
 if mode=='radio':
  for line in log.splitlines():
   match=re.search(r'event=heartbeat t=(\d+) dev=(\S+).*producer\[state=\S+ slots=(\d+)',line)
   if match and int(match[1])<=2 and int(match[3])>0:first_ready[match[2]]=int(match[1])
  initialized=len(first_ready)==sum(x['ports'] for x in m['nodes'])
 begin=r.get('details',{}).get('measurement_start_ns');end=r.get('details',{}).get('measurement_end_ns')
 if mode=='iq' and (d/'iq.log').exists():
  iqlog=(d/'iq.log').read_text()
  for line in iqlog.splitlines():
   if line.startswith('measurement_start_ns,'):begin=int(line.split(',')[1])
   if line.startswith('measurement_end_ns,'):end=int(line.split(',')[1])
 selected=[s for s in cpu['samples'] if begin is not None and begin<=s['time_ns']<=end];usage={}
 if len(selected)>1:
  a,b=selected[0],selected[-1];wall=(b['time_ns']-a['time_ns'])/1e9
  for pid,x in b['pids'].items():
   old=a['pids'].get(pid)
   if old:
    seconds=(x['utime']+x['stime']-old['utime']-old['stime'])/cpu['clock_ticks'];usage[pid]=dict(comm=x['comm'],cpus=x['cpus'],cpu_seconds=seconds,window_wall_seconds=wall,average_cores=seconds/wall)
 row={k:r.get(k) for k in ['label','host','mode','ues_per_cell','cells','bandwidth_mhz','sample_rate_hz','ports','period_ns','health','error','min_coverage','min_endpoint_ratio','min_completed_batches','expected_batches','cadence_covered_with_one_boundary_batch','strict_deadline_clean','wall_s']};row.update(resource_profile=variant,primary=primary,initialized_before_window=initialized,cpu_usage=usage)
 node_summaries=[]
 if mode=='radio':
  for x in r.get('details',{}).get('producer_counters',[]):
   calls=int(x['calls']);node_summaries.append(dict(node=x['node'],calls=calls,rebases=int(x['rebases']),debt_ms=int(x['debt_ns'])/1e6,process_p99_us=float(x['process_p99_upper_us']),process_max_us=float(x['process_max_us']),process_over_budget=int(x['process_over_budget']),process_mean_us=float(x['process_us_sum'])/calls if calls else None,process_cpu_mean_us=int(x['process_cpu_ns'])/1000/calls if calls else None,room_mean_us=float(x['room_us_sum'])/calls if calls else None,data_mean_us=float(x['data_us_sum'])/calls if calls else None,read_mean_us=float(x['read_us_sum'])/calls if calls else None))
 else:
  node_summaries=[dict(node=x['id'],calls=int(x['count']),call_p99_us=float(x['p99_us']),call_max_us=float(x['max_us']),cpu_p99_us=float(x['cpu_p99_us']),late_completions=int(x['late_completions']),initialized_ns=int(x.get('initialized_ns',0)),prime_us=int(x.get('prime_us',0))) for x in r.get('details',{}).get('nodes',[])]
 row['cuda_zero_copy']=(next((int(l.split(',')[1]) for l in (d/'iq.log').read_text().splitlines() if l.startswith('zero_copy,')),None) if mode=='iq' else None)
 row['nodes']=node_summaries;row['measured_rebases']=sum(x.get('rebases',0) for x in node_summaries) if mode=='radio' and node_summaries else None
 row['all_workers_initialization_certified']=initialized is True
 # API/protocol health and zero-drop checks remain separate from speed.
 stop=r.get('details',{}).get('broker_stop',[]);row['broker_stop']=stop
 archive=dict(summary=row,launch=m,result=r,cpu_usage=usage,first_heartbeat_production=first_ready,source_locations=dict(root=str(d),broker_log=str(d/'broker.log') if mode=='radio' else None),raw_files=[dict(file=str(f.relative_to(d)),bytes=f.stat().st_size) for f in d.rglob('*') if f.is_file()])
 with gzip.open(out/(label+'.json.gz'),'wt') as f:json.dump(archive,f)
 rows.append(row)
(out/'summary.json').write_text(json.dumps(dict(host=HOST,rows=rows,raw_root=str(W),collection_time_unix_ns=time.time_ns()),indent=2))
# Cross-platform source/binary provenance and archive-member identity.
source_files=['iq_capacity.cpp','iq_capacity.ready.cpp','radio_peer.cpp','broker-probe.cpp','gen.py','run_case.py','campaign.py','ready_campaign.py','counter_controls.py']
provenance=dict(host=HOST,files={f:hashlib.sha256((W/f).read_bytes()).hexdigest() for f in source_files+['iq-capacity','iq-capacity-ready','radio-peer','ocudu-gpu-channel'] if (W/f).exists()},gpu=sp.check_output(['nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader'],text=True).strip(),cpu=sp.check_output(['lscpu'],text=True),clock_pair=dict(unix_ns=time.time_ns(),monotonic_ns=time.monotonic_ns()))
old=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030/room-build/libocudu_gpu_channel_lib.a') if HOST=='spark' else pathlib.Path('/home/minwoo/ocudu-work/rtx-scaling-20261102/channel-build/libocudu_gpu_channel_lib.a');new=W/'libocudu_gpu_channel_lib.a';members=sp.check_output(['ar','t',str(old)],text=True).splitlines();members2=sp.check_output(['ar','t',str(new)],text=True).splitlines();assert members==members2
changed=[member for member in members if sp.check_output(['ar','p',str(old),member])!=sp.check_output(['ar','p',str(new),member])];assert changed==['broker.cpp.o'],changed;provenance['changed_archive_members']=changed;provenance['unchanged_backend_members']=len(members)-1
(out/'provenance.json').write_text(json.dumps(provenance,indent=2));print(HOST,'cases',len(rows),'primary',sum(x['primary'] for x in rows),'radio_uninitialized',[(x['label'],x['min_coverage']) for x in rows if x['primary'] and x['mode']=='radio' and not x['initialized_before_window']],flush=True)
