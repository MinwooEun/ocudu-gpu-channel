"""Audit completed captures and keep speed, data validity and connectivity separate."""
import pathlib,json,hashlib,re,collections,shutil,datetime,numpy as np
b=pathlib.Path('/workspace/gpuch/multi-ue-affinity-20261102');e=b/'evidence';e.mkdir(exist_ok=True);rows=[];dt=np.dtype([(s,'<i8') for s in ['op','tid','port','flags','start','end','result','error']])
for r in json.loads((b/'batch-results.json').read_text()):
 p=pathlib.Path(r['case']);out=e/f'u{r["ues"]}'/p.name;out.mkdir(parents=True,exist_ok=True);result=r.get('result',{});gate=result.get('gate') or {};rate=r.get('rate',{});meta=json.loads((p/'launch.json').read_text());audit=json.loads((p/'affinity-audit.json').read_text()) if (p/'affinity-audit.json').exists() else None;prio=json.loads((p/'priorities.json').read_text()) if (p/'priorities.json').exists() else None
 qualified=(r.get('verification',{}).get('audit_returncode')==0 and prio is not None and len(prio['rf_rx_by_pid'])==r['ues'])
 broker=(p/'runtime/logs/broker.log').read_text();tags=[]
 for line in broker.splitlines():
  if 'event=control_sample_applied link_id=ue0>gnb0:sionna_rt tag=k=' in line:
   v=dict(re.findall(r'(\w+)=([^ ]+)',line));tags.append(int(v['unix_ns']))
 files=[];yield_groups=collections.defaultdict(list)
 for f in (p/'raw/wire').glob('*.wire'):
  h=np.fromfile(f,dtype='<u8',count=8);n=min(int(h[1]),int(h[2]));v=np.memmap(f,dtype=dt,offset=64,shape=(n,));uncommitted=int(np.sum(v['op']==0));files.append(dict(file=f.name,records=int(h[1]),capacity=int(h[2]),dropped=int(h[3]),uncommitted=uncommitted))
  if f.name.startswith('gnb-') and n and len(tags)==400:
   lo=tags[100]-int(h[6])+int(h[5]);hi=tags[-1]-int(h[6])+int(h[5]);y=v[(v['op']==40)&(v['start']>=lo)&(v['end']<=hi)]
   offsets={0x222c:0x1b6222c,0x0868:0x18e0868};bases=collections.Counter(int(x['result'])-offsets[int(x['result'])&65535] for x in y if int(x['result'])&65535 in offsets)
   if bases:
    bias=bases.most_common(1)[0][0]
    for x in y:
     off=int(x['result'])-bias
     if off in offsets.values():yield_groups[hex(off)].append((int(x['end'])-int(x['start']))/1000)
 integrity=dict(files=files,dropped=sum(f['dropped'] for f in files),uncommitted=sum(f['uncommitted'] for f in files));(p/'wire-integrity.json').write_text(json.dumps(integrity,indent=2)+'\n')
 ue_cpus=collections.defaultdict(list)
 if prio:
  for pid,tid in prio['rf_rx_by_pid'].items():ue_cpus[','.join(map(str,prio['changes'][str(tid)]['after']['cpus']))].append(int(pid))
 lifecycle={k:v for k,v in gate.get('per_ue',{}).items() if any(v.get(x,0) for x in ['rrc_release','out_of_sync','crashed'])}
 runner=(p/'runner.log').read_text();start_match=re.search(r'event=measure_release unix_ms=(\d+)',runner);end_match=re.search(r'event=measure_end status=completed unix_ms=(\d+)',runner);sr_events={}
 if start_match and end_match:
  start_ms=int(start_match[1]);end_ms=int(end_match[1])
  for ue in lifecycle:
   f=p/f'runtime/logs/srsue-{ue}-internal.log'
   if not f.exists():continue
   selected=[]
   for line in f.open(errors='replace'):
    if 'SR:' not in line or 'Releasing PUCCH/SRS resources' not in line:continue
    ts=datetime.datetime.fromisoformat(line[:26]).replace(tzinfo=datetime.timezone.utc);ms=ts.timestamp()*1000
    if start_ms<=ms<=end_ms:selected.append(line.strip())
   if selected:sr_events[ue]=selected
 row=dict(ues=r['ues'],patch=r['patch'],case=p.name,configuration_verified=qualified,application_completed=result.get('returncode')==0,gate=gate.get('status'),valid_segments=result.get('valid_segments'),full_ratio=(result.get('metrics') or {}).get('real_time_ratio'),post=rate.get('post_warmup'),lifecycle_events=lifecycle,scheduling_request_exhaustion_during_measurement=sr_events,affinity_audit=audit,ue_cpu_occupancy={k:len(v) for k,v in ue_cpus.items()},trace_integrity=dict(dropped=integrity['dropped'],uncommitted=integrity['uncommitted']),gnb_cuda_wait_yields_over_100us={k:dict(count=len(v),max_us=max(v),sum_us=sum(v)) for k,v in yield_groups.items()},binary_hashes=meta['binary_hashes'],input_hashes=meta['input_hashes'])
 rows.append(row)
 for name in ['launch.json','result.json','verification.json','rate-analysis.json','priorities.json','affinity-audit.json','wire-integrity.json']:
  f=p/name
  if f.exists():shutil.copy2(f,out/name)
 for name in ['logs/gnb-affinity.json','configs/gnb0.yaml','report/run-report.json']:
  f=p/'runtime'/name
  if f.exists():shutil.copy2(f,out/f.name)
 (out/'raw-index.json').write_text(json.dumps(dict(remote_case=str(p),files=[dict(file=str(f.relative_to(p)),size=f.stat().st_size) for f in (p/'raw').rglob('*') if f.is_file()]),indent=2)+'\n')
 (out/'lifecycle-evidence.json').write_text(json.dumps(dict(whole_run_counters=lifecycle,scheduling_request_exhaustion_during_measurement=sr_events),indent=2)+'\n')
 stop_lines=[line for line in broker.splitlines() if line.startswith(('event=relay_wedged ','event=stop '))]
 (out/'relay-stop.txt').write_text('\n'.join(stop_lines)+'\n')
 for ue,v in lifecycle.items():
  if v.get('crashed'):
   f=p/f'runtime/logs/srsue-{ue}.log'
   if f.exists():(out/f'{ue}-crash.txt').write_text('\n'.join(f.read_text(errors='replace').splitlines()[-45:])+'\n')
pair_checks=[]
for n in [8,16]:
 pair=[r for r in rows if r['ues']==n];off=[r for r in pair if r['patch']=='off']
 if off:
  for on in [r for r in pair if r['patch']=='on']:
   assert off[0]['binary_hashes']==on['binary_hashes'];assert off[0]['input_hashes']==on['input_hashes'];pair_checks.append(dict(ues=n,on_case=on['case'],identical_binaries=True,identical_frozen_inputs=True))
for row in rows:row.pop('binary_hashes');row.pop('input_hashes')
original=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030/wire_yield.c').read_text();assert (b/'wire_multi.c').read_text()==original.replace('1500000','6000000')
report=dict(configuration=dict(hardware='Spark GB10',cells=1,bandwidth_mhz=20,sample_rate_hz=23040000,antennas='1x1',gnb='CUDA all, MPS',ue='CPU srsUE with existing local pilot-noise repair',warmup_radio_s=10,measure_radio_s=30,gnb_cpu_budget='5-12',broker_cpus='15-16',aux_cpus='0-4',ue_cpus='same frozen per-UE assignments on 13,14,17,18,19',io_policy='Existing IO/RF RX FIFO95 applied to every UE in both comparison modes'),rows=rows,pair_identity_checks=pair_checks,metric='Radio-time / wall-time; not success rate. Post-warmup tag endpoints span 29.9 radio seconds.',limitations=['One cold run per configuration, with one repeated 16-UE ON trial after a crash; adaptive scheduling changes actual transported work.','The first multi-u1-on-r1 attempt failed its priority observer and is excluded.','No scheduler or device-kernel profiling; long CUDA-wait yield intervals are call-boundary observations, not measured kernel time.','rrc_release is a console-derived counter, not proof of an RRC state transition: the SR failure message calls release_pucch_srs, which is empty in this NR implementation, clears pending PHY grants and starts MAC random access.'],instrumentation=dict(change='Only broker capture capacity enlarged 1.5M to 6M records; source equivalence asserted',wire_sha256=hashlib.sha256((b/'wire-multi.so').read_bytes()).hexdigest()))
(b/'comparison.json').write_text(json.dumps(report,indent=2)+'\n');(e/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
src=pathlib.Path('/workspace/ocudu-spark-ranb/src/srsRAN_4G-local');sources={}
for rel,lo,hi in [('srsue/src/stack/mac_nr/proc_sr_nr.cc',110,132),('srsue/src/stack/rrc_nr/rrc_nr.cc',2308,2318),('lib/src/rlc/rlc_am_nr.cc',1765,1783)]:
 f=src/rel;sources[rel]=dict(sha256=hashlib.sha256(f.read_bytes()).hexdigest(),first_line=lo,text='\n'.join(f.read_text().splitlines()[lo-1:hi]))
(e/'ue-source-evidence.json').write_text(json.dumps(sources,indent=2)+'\n')
for row in rows:print(row['ues'],row['patch'],row['configuration_verified'],row['valid_segments'],row['post']['ratio'] if row['post'] else None,row['trace_integrity'])
