"""Collect rates and exact remaining clock loss without rounding it away."""
import pathlib,json,re,csv,shutil
b=pathlib.Path('/workspace/gpuch/residual-rate-20261030');q=pathlib.Path('/workspace/gpuch/receiver-quality-20261030');out=[]
for p in [q/'u1/original-fixed-noise-r1',q/'u1/original-io-prio-r1',b/'u1/original-io-pacer-r1',b/'u1/original-zero-sched-r6',b/'u1/original-fixed-light-r1']:
 a=[]
 for l in (p/'runtime/logs/broker.log').open():
  if l.startswith('event=control_sample_applied link_id=ue0>gnb0:sionna_rt ') and 'tag=attach;' not in l:
   r=dict(re.findall(r'(\w+)=([^ ]+)',l));a.append((int(r['sample']),int(r['unix_ns'])))
 assert len(a)==400,(p,len(a))
 row=dict(case=str(p),result=json.loads((p/'result.json').read_text()),windows={})
 for name,v in [('full',a),('post_warmup',a[100:])]:
  radio=(v[-1][0]-v[0][0])/23040000;wall=(v[-1][1]-v[0][1])/1e9;row['windows'][name]=dict(radio_s=radio,wall_s=wall,ratio=radio/wall,lost_us=(wall-radio)*1e6,start_sample=v[0][0],end_sample=v[-1][0])
 if p.name=='original-io-pacer-r1':
  shutil.copy2('/dev/shm/ocudu-io-pacer-20261030/pacing/gnb0.csv',p/'gnb0-pacing.csv');e=[r for r in csv.DictReader((p/'gnb0-pacing.csv').open()) if a[100][0]<=int(r['sample'])<a[-1][0]];row['rebases']=e;row['sum_rebase_us']=sum(int(r['shift_ns']) for r in e)/1000;row['endpoint_residual_us']=row['windows']['post_warmup']['lost_us']-row['sum_rebase_us'];row['priority']=json.loads((p/'io-priority.json').read_text())
 out.append(row)
(b/'rate-reconciliation.json').write_text(json.dumps(out,indent=2)+'\n')
p=b/'u1/original-fixed-light-r1';a=json.loads((p/'sched-analysis.json').read_text());e=max(json.loads((p/'input-analysis.json').read_text())['events'],key=lambda x:x['shift_us']);lo=e['times']['ue_iq_send_end'];hi=e['times']['broker_iq_recv_end'];interval=next(x for x in a['intervals'] if x['comm']=='ZMQbg/IO/0' and x['namespace_tid']==3111823 and x['start']<lo and x['end']>lo and x['runnable_us']>5000);switches=[dict(t=x['start'],raw=x['out']['raw']) for x in a['intervals'] if x['out']['cpu']==17 and lo-100000<x['start']<hi+100000]
critical=dict(note='Direct scheduler evidence from an instrumented run. The profiler increases disturbance; this event is not retroactively assigned to an earlier clean run.',event=e,io_off_cpu=interval,cpu17_switches=switches,stack_cpu_interval_us=(switches[1]['t']-switches[0]['t'])/1000)
(b/'critical-io-starvation.json').write_text(json.dumps(critical,indent=2)+'\n')
