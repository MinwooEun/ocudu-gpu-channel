from pathlib import Path
import numpy as np,json,sys,collections
base=Path(sys.argv[1]);policy=sys.argv[2];run=sys.argv[3];work=base/'runtime-audit';trace=work/policy
report=json.loads((base/f'ocudu-native-workspace/results/reports/ocudu-scheduler-benchmark/{run}/benchmark-report.json').read_text())
data={};heads={}
for f in trace.glob('*.wire'):
 h=np.fromfile(f,dtype='<u8',count=8);n=int(h[1]);assert h[0]==0x4f43475749524531 and h[3]==0 and n<h[2],str(f)
 if n<1000:continue # preflight gNB processes; every live process must have >100000 records
 a=np.array(np.memmap(f,dtype='<i8',mode='r',offset=64,shape=(n,8)));assert (a[:,0]>0).all();assert (a[:,5]>=a[:,4]).all()
 ports=set(a[(a[:,0]==3)|(a[:,0]==4),2]);name='broker' if f.name.startswith('ocudu-gpu-channel') else 'gnb' if f.name.startswith('gnb-') else 'ue0' if 2100 in ports else 'ue1'
 assert name not in data and n>100000,(name,n);data[name]=a;heads[name]=h
assert set(data)=={'broker','gnb','ue0','ue1'}
h=heads['broker'];offset=int(h[6])-int(h[5]);start=int(report['anchor_unix_ms'])*1000000-offset;end=start+120000000000
transactions={}
out={'run':run,'policy':policy,'start_ns':start,'end_ns':end,'processes':{},'ports':{},'events':[]}
def summary(x):
 if len(x)==0:return {'count':0}
 return {'count':len(x),'median_ms':float(np.median(x)/1e6),'p99_ms':float(np.quantile(x,.99)/1e6),'max_ms':float(x.max()/1e6),'gt_1ms':int(sum(x>1000000)),'gt_5ms':int(sum(x>5000000))}
def select(a,op,port):
 x=a[(a[:,0]==op)&(a[:,2]==port)&(a[:,6]>0)];return x[np.argsort(x[:,5])]
# Match complete ordered REQ/REP transactions by stream order, checking every byte count.
for port,peer in [(2000,'gnb'),(2001,'gnb'),(2100,'ue0'),(2101,'ue0'),(2102,'ue1'),(2103,'ue1')]:
 tx=port in [2000,2101,2103];requester='broker' if tx else peer;responder=peer if tx else 'broker'
 rs=select(data[requester],1,port);rr=select(data[responder],2,port);ds=select(data[responder],1,port);dr=select(data[requester],2,port)
 # Shutdown can leave the final transaction incomplete; compare all completed prefixes.
 n=min(map(len,[rs,rr,ds,dr]));assert n>100000,(port,n)
 assert max(map(len,[rs,rr,ds,dr]))-n<=1,(port,list(map(len,[rs,rr,ds,dr])))
 rs,rr,ds,dr=[x[:n] for x in [rs,rr,ds,dr]]
 assert (rs[:,6]==1).all() and (rr[:,6]==1).all();assert np.array_equal(ds[:,6],dr[:,6]);assert (ds[:,6]%8==0).all()
 assert (ds[:,4]>=rr[:,5]).all() and (dr[:,5]>=rs[:,4]).all()
 m=(rs[:,5]>=start)&(dr[:,5]<end);idx=np.flatnonzero(m)
 turn=ds[:,4]-rr[:,5];request_delivery=np.maximum(0,rr[:,5]-rs[:,5]);reply_delivery=np.maximum(0,dr[:,5]-ds[:,5]);rtt=dr[:,5]-rs[:,4]
 # The next request can start after consuming the preceding reply; this is a separate wait.
 request_gap=np.r_[0,rs[1:,4]-dr[:-1,5]];assert (request_gap[1:]>=0).all()
 transactions[port]=(rs,rr,ds,dr)
 stages={'responder_pre_reply':turn,'request_delivery':request_delivery,'reply_delivery':reply_delivery,'round_trip':rtt,'requester_next_request_gap':request_gap}
 out['ports'][str(port)]={'peer':peer,'direction':'stack_tx_to_broker' if tx else 'broker_to_stack_rx','requester':requester,'responder':responder,'matched_full_run_transactions':n,'matched_full_run_iq_samples':int(ds[:,6].sum()//8),'measurement_transactions':len(idx),'stages':{k:summary(v[m]) for k,v in stages.items()},'identical_message_lengths':True}
 for k in ['responder_pre_reply','requester_next_request_gap']:
  for i in idx[stages[k][idx]>5000000]:
   out['events'].append({'port':port,'peer':peer,'stage':k,'start_ns':int(rr[i,5] if k=='responder_pre_reply' else dr[i-1,5]),'end_ns':int(ds[i,4] if k=='responder_pre_reply' else rs[i,4]),'ms':float(stages[k][i]/1e6),'samples':int(ds[i,6]//8),'owner':responder if k=='responder_pre_reply' else requester})
for peer,tx_port,rx_port in [('ue0',2101,2100),('ue1',2103,2102)]:
 rs,rr,ds,dr=transactions[tx_port];dreq,_,_,drecv=transactions[rx_port]
 candidates=np.flatnonzero((rr[:,5]-rs[:,5]>5000000)&(rs[:,5]>=start)&(rr[:,5]<end))
 correlations=[]
 for i in candidates:
  a,b=rs[i,5],rr[i,5];j=np.searchsorted(drecv[:,5],a,side='right');overlap=0
  while j<len(dreq) and dreq[j,5]<b:
   overlap+=max(0,min(b,drecv[j,5])-max(a,dreq[j,5]));j+=1
  correlations.append({'start_ns':int(a),'end_ns':int(b),'tx_request_acceptance_delay_ms':float((b-a)/1e6),'overlap_with_pending_downlink_reply_fraction':float(overlap/(b-a)),'ue_called_request_recv_after_broker_request_ms':float(max(0,rr[i,4]-a)/1e6)})
 out.setdefault('ue_delay_correlations',{})[peer]=correlations
for name,a in data.items():
 m=(a[:,4]>=start)&(a[:,5]<end);slowwrite=a[m&(a[:,0]==7)];errors=a[m&(a[:,0]<=2)&(a[:,6]<0)]
 out['processes'][name]={'pid':int(heads[name][4]),'trace_records':len(a),'trace_dropped':int(heads[name][3]),'nonblocking_poll_gaps':summary(a[m&(a[:,0]==8),5]-a[m&(a[:,0]==8),4]),'slow_nonblocking_calls':summary(a[m&(a[:,0]==9),5]-a[m&(a[:,0]==9),4]),'poll_gap_events':[{'port':int(v[2]),'tid':int(v[1]),'start_ns':int(v[4]),'end_ns':int(v[5]),'ms':float((v[5]-v[4])/1e6)} for v in a[m&(a[:,0]==8)]],'transport_errors':errors.tolist(),'slow_fwrite':summary(slowwrite[:,5]-slowwrite[:,4]),'slow_fwrite_events':[{'tid':int(v[1]),'fd':int(-v[2]),'start_ns':int(v[4]),'end_ns':int(v[5]),'ms':float((v[5]-v[4])/1e6),'bytes':int(v[6])} for v in slowwrite]}
# Per-thread CPU runtime remains meaningful when Linux scheduler-wait statistics are disabled.
prev={};cpu=collections.defaultdict(list);samples=0;readcost=[]
for line in (trace/'runtime-samples.jsonl').open():
 v=json.loads(line);t=v['mono_ns'];samples+=start<=t<end;readcost.append(v['read_ns'])
 for row in v['rows']:
  pid,tid,comm,state,processor,exec_ns,wait_ns,slices=row;key=(pid,tid,comm)
  if key in prev:
   pt,pe,pw=prev[key];dt=t-pt
   if start<=pt<t<end and dt<200000000:
    cpu[key].append(((exec_ns-pe)/dt,(wait_ns-pw)/dt,dt,processor,state))
  prev[key]=(t,exec_ns,wait_ns)
for name,v in out['processes'].items():
 threads=[]
 for (pid,tid,comm),rows in cpu.items():
  if pid!=v['pid']:continue
  a=np.array([r[:3] for r in rows]);d=a[:,2];util=a[:,0]
  threads.append({'tid':tid,'comm':comm,'samples':len(rows),'cpu_core_fraction_mean':float((util*d).sum()/d.sum()),'cpu_core_fraction_p99':float(np.quantile(util,.99)),'cpu_core_fraction_max':float(util.max()),'samples_over_90pct':int(sum(util>.9)),'wait_core_fraction_mean':float((a[:,1]*d).sum()/d.sum()),'observed_cpus':sorted(set(r[3] for r in rows)),'observed_states':dict(collections.Counter(r[4] for r in rows))})
 v['threads']=sorted(threads,key=lambda x:-x['cpu_core_fraction_mean']);v['cpu_cores_mean']=sum(x['cpu_core_fraction_mean'] for x in threads)
out['observer']={'sample_count_in_measurement':samples,'read_cost_ms':summary(np.array(readcost)),'scheduler_wait_statistics_enabled':(work/'schedstats-enabled.txt').read_text().strip()=='1','note':'Wait counters unavailable when kernel sched_schedstats is disabled; zero is not proof of no scheduler delay.'}
(trace/'wire-analysis.json').write_text(json.dumps(out,indent=2)+'\n')
print('RUN',run)
for p,v in out['ports'].items(): print(p,v['direction'],{k:(x['p99_ms'],x['max_ms'],x['gt_5ms']) for k,x in v['stages'].items()})
for n,v in out['processes'].items():print(n,'CPU cores',v['cpu_cores_mean'],'slow fwrite',v['slow_fwrite'],'errors',len(v['transport_errors']),'threads',[(t['comm'],round(t['cpu_core_fraction_mean'],3)) for t in v['threads'][:4]])
print('Long events',len(out['events']))
