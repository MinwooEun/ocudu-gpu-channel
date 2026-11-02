"""Qualified RTX results: radio speed, deadline debt and communication health."""
import pathlib,json,csv,re,shutil,collections,hashlib,numpy as np
E=pathlib.Path(__file__).parent;W=pathlib.Path('/home/minwoo/ocudu-work/rtx-scaling-20261102');out=E/'evidence';out.mkdir(exist_ok=True);rows=[]
dtype=np.dtype([(k,'<i8') for k in ['op','tid','port','flags','start','end','result','error']])
for n,tag in [(n,'matched-r1') for n in [1,4,8,16]]+[(n,'pbroker-r1') for n in [8,16]]:
 p=W/f'u{n}-{tag}'
 if not (p/'result.json').exists():continue
 result=json.loads((p/'result.json').read_text());report=result.get('report') or {};meta=json.loads((p/'launch.json').read_text());gatepath=p/'runtime/report/gate-summary.json';gate=json.loads(gatepath.read_text()) if gatepath.exists() else {};audit=json.loads((p/'affinity-audit.json').read_text()) if (p/'affinity-audit.json').exists() else {};prio=json.loads((p/'priorities.json').read_text()) if (p/'priorities.json').exists() else {}
 broker=(p/'runtime/logs/broker.log').read_text();tags=[]
 for l in broker.splitlines():
  if 'event=control_sample_applied link_id=ue0>gnb0:sionna_rt tag=k=' in l:
   v=dict(re.findall(r'(\w+)=([^ ]+)',l));tags.append((int(v['sample']),int(v['unix_ns'])))
 pacepath=p/'raw/pacing/gnb0.csv';pace=list(csv.DictReader(pacepath.open())) if pacepath.exists() else [];rate={}
 if len(tags)==400:
  for name,start in [('including_warmup',0),('post_warmup',100)]:
   a,b=tags[start],tags[-1];radio=(b[0]-a[0])/23040000;wall=(b[1]-a[1])/1e9;events=[x for x in pace if a[0]<=int(x['sample'])<b[0]]
   rate[name]=dict(radio_s=radio,wall_s=wall,ratio=radio/wall,loss_us=(wall-radio)*1e6,rebase_count=len(events),rebase_sum_us=sum(int(x['shift_ns']) for x in events)/1000,largest_rebases=sorted(events,key=lambda x:int(x['shift_ns']),reverse=True)[:10])
 integrity=[]
 for f in (p/'raw/wire').glob('*.wire'):
  h=np.fromfile(f,dtype='<u8',count=8);count=min(int(h[1]),int(h[2]));v=np.memmap(f,mode='r',dtype=dtype,offset=64,shape=(count,));integrity.append(dict(file=f.name,count=int(h[1]),capacity=int(h[2]),dropped=int(h[3]),uncommitted=int(np.sum(v['op']==0))))
 lifecycle={};assertions={}
 for f in (p/'runtime/logs').glob('srsue-ue*-internal.log'):
  matches=[l.strip() for l in f.open(errors='replace') if 'SR:' in l and 'Releasing PUCCH/SRS resources' in l]
  if matches:lifecycle[f.name]=dict(sr_exhaustion_count=len(matches),first=matches[0],last=matches[-1])
 for f in (p/'runtime/logs').glob('*console.log'):
  matches=[l.strip() for l in f.open(errors='replace') if 'FATAL' in l or 'Assertion' in l or 'assertion' in l]
  if matches:assertions[f.name]=matches
 for f in (p/'runtime/logs').glob('srsue-ue*.log'):
  if 'internal' in f.name:continue
  matches=[l.strip() for l in f.open(errors='replace') if 'Assertion' in l or 'assertion' in l]
  if matches:assertions[f.name]=matches
 snaps=audit.get('snapshots',[]);cpu={}
 # Difference only within the post-warmup window; ticks are CPU time, not wall waits.
 if snaps and len(tags)==400:
  # audit has monotonic timestamps; actor header has the realtime/monotonic clock pair.
  headerfile=next(iter((p/'raw/wire').glob('gnb-*.wire')),None)
  if headerfile:
   h=np.fromfile(headerfile,dtype='<u8',count=8);lo=tags[100][1]-int(h[6])+int(h[5]);hi=tags[-1][1]-int(h[6])+int(h[5]);selected=[s for s in snaps if lo<=s['mono_ns']<=hi]
   if len(selected)>=2:
    first,last=selected[0],selected[-1];elapsed=(last['mono_ns']-first['mono_ns'])/1e9;ticks=audit['clock_ticks']
    for actor,tasks in last['actors'].items():
     old=first['actors'].get(actor,{});groups=collections.defaultdict(float)
     for tid,v in tasks.items():
      if tid in old:groups[v['name']]+=(v['utime']+v['stime']-old[tid]['utime']-old[tid]['stime'])/ticks
     cpu[actor]=dict(wall_s=elapsed,cpu_seconds=sum(groups.values()),average_cores=sum(groups.values())/elapsed,by_thread_name_cpu_seconds=dict(groups))
 invalid_reasons=dict(collections.Counter(reason for segment in report.get('segments',[]) if 10<=segment.get('k',-1)<40 and not segment.get('valid',False) for reason in segment.get('reasons',[])))
 row=dict(invalid_kpi_reasons=invalid_reasons,ue_count=n,layout=tag,cpu_mapping=meta['cpu_mapping'],case=p.name,configuration_verified=audit.get('passed',False) and len(prio.get('rf_rx_by_pid',{}))==n,returncode=result['returncode'],valid_kpi_windows=report.get('segments_valid'),expected_kpi_windows=30,full_ratio=report.get('runtime',{}).get('real_time_ratio'),rate=rate,gate=gate,trace_integrity=dict(dropped=sum(x['dropped'] for x in integrity),uncommitted=sum(x['uncommitted'] for x in integrity),files=integrity),broker_terminal_events=[l for l in broker.splitlines() if l.startswith(('event=relay_wedged ','event=stop '))],sr_exhaustion_whole_run=lifecycle,assertions=assertions,post_warmup_cpu_time=cpu,affinity_checks=audit.get('checks'),tags=len(tags))
 rows.append(row);d=out/p.name;d.mkdir(exist_ok=True)
 for name in ['launch.json','result.json','priorities.json','log-pipe.json']:
  if (p/name).exists():shutil.copy2(p/name,d/name)
 (d/'rate-analysis.json').write_text(json.dumps(rate,indent=2));(d/'affinity-audit-summary.json').write_text(json.dumps({k:v for k,v in audit.items() if k!='snapshots'},indent=2));(d/'row.json').write_text(json.dumps(row,indent=2));(d/'raw-index.json').write_text(json.dumps(dict(path=str(p),files=[dict(file=str(f.relative_to(p)),size=f.stat().st_size) for f in (p/'raw').rglob('*') if f.is_file()]),indent=2))
 for name in ['run-report.json','gate-summary.json','run-parameters.json']:
  if (p/'runtime/report'/name).exists():shutil.copy2(p/'runtime/report'/name,d/name)
print(json.dumps([dict(ues=x['ue_count'],layout=x['layout'],verified=x['configuration_verified'],rc=x['returncode'],valid=x['valid_kpi_windows'],ratio=x['rate'].get('post_warmup',{}).get('ratio'),rebases=x['rate'].get('post_warmup',{}).get('rebase_count'),sr_ues=len(x['sr_exhaustion_whole_run']),drops=x['trace_integrity']['dropped']) for x in rows],indent=2))
(E/'comparison.json').write_text(json.dumps(dict(hardware='RTX5090 + Core Ultra9 285K',configuration=dict(cells=1,bandwidth_mhz=20,sample_rate_hz=23040000,antenna_ports='1x1',gnb='CUDA all with Spark UL fixes',ue='CPU srsUE with Spark access/RF patches and local pilot-noise repair',cpu_budget='gNB P0-7, radio P1 separated; broker E8-9; UE E10-19 one core per UE modulo10; aux E20-23'),metric='radio seconds / wall seconds, not success fraction; post-warmup endpoints span29.9 radio seconds',rows=rows,limitations=['One run per UE count and CPU placement; results are not a repeated-run distribution.','Different CPU architecture/core budget and toolchain from Spark; this compares whole hosts, not GPU silicon in isolation.','CPU utilization and API waits do not by themselves establish the causal instruction/kernel that caused a missed deadline.','SR failure console wording alone is not proof of an RRC state release.']),indent=2))
