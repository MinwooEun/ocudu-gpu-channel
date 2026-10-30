"""Tie long sched_yield calls to producer progress and peer arrival events."""
import pathlib,json,csv,sys,subprocess as sp,re,numpy as np,collections
p=pathlib.Path(sys.argv[1]);raw=p/'raw' if (p/'raw').exists() else pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030');f=next((raw/'wire').glob('ocudu-*.wire'));h=np.fromfile(f,dtype='<u8',count=8);assert h[3]==0;dt=np.dtype([(s,'<i8') for s in ['op','tid','port','flags','start','end','result','error']]);a=np.memmap(f,dtype=dt,offset=64,shape=(int(h[1]),),mode='r');assert not np.any(a['op']==0)
y=a[a['op']==40];order=np.argsort(y['end']-y['start'])[::-1];hop=collections.defaultdict(list)
for r in csv.DictReader((p/'hop/hop-trace.csv').open()):hop[r['role'],r['id'],int(r['event'])].append((int(r['t_ns']),int(r['samples'])))
for k in hop:hop[k]=np.array(hop[k],dtype=np.int64)
roles={}
for r in csv.DictReader((p/'room/gnb0-room.csv').open()):
 mask=(y['start']>=int(r['start_ns']))&(y['end']<=int(r['end_ns']))
 for t in np.unique(y[mask]['tid']):roles[int(t)]='gnb0'
assert len(roles)==1,roles
producer_ips=np.unique(y[np.isin(y['tid'],list(roles))]['result'])
for tid in np.unique(y[np.isin(y['result'],producer_ips)]['tid']):roles.setdefault(int(tid),'ue0')
rep_nodes={}
for port,node in [(2001,'gnb0'),(2100,'ue0')]:
 tids=np.unique(a[(a['op']==1)&(a['port']==port)&(a['result']>=8)]['tid']);assert len(tids)==1,tids
 rep_nodes[int(tids[0])]=(node,port)
source_for={'gnb0':'ue0_p0','ue0':'gnb0_p0'};out=[]
report=json.loads((p/'runtime/report/run-report.json').read_text());ready=hop['producer','gnb0',10];starts=np.cumsum(ready[:,1])-ready[:,1];s0=report['epoch']['s0'];lo_time=int(ready[np.searchsorted(starts,s0+230400000),0]);hi_time=int(ready[np.searchsorted(starts,s0+report['epoch']['measure_samples']-2304000),0]);valid=[i for i in order if int(y[i]['start'])>=lo_time and int(y[i]['end'])<=hi_time]
for x in y[valid[:25]]:
 tid=int(x['tid']);node=roles.get(tid);lo=int(x['start']);hi=int(x['end']);r=dict(tid=tid,role='producer' if node else 'rep',node=node,start_ns=lo,end_ns=hi,yield_us=(hi-lo)/1000,caller=int(x['result']),cpu_before=int(x['flags'])>>16,cpu_after=int(x['flags'])&65535)
 if node:
  ready=hop['producer',node,10];j=int(np.searchsorted(ready[:,0],hi));assert j<len(ready);sample=int(ready[:j,1].sum());r.update(next_data_ready_ns=int(ready[j,0]),next_window_sample=sample,next_window_count=int(ready[j,1]))
  pushes=hop['puller',source_for[node],2];cum=np.cumsum(pushes[:,1]);i=int(np.searchsorted(cum,sample,side='right'));assert i<len(pushes);arrival=int(pushes[i,0]);r.update(first_needed_input_pushed_ns=arrival,needed_input_relative_to_yield_start_us=(arrival-lo)/1000,input_wait_after_available_us=(hi-arrival)/1000)
 if tid in rep_nodes:
  node,port=rep_nodes[tid];r['node']=node
  sends=a[(a['op']==1)&(a['port']==port)&(a['result']>=8)];requests=a[(a['op']==2)&(a['port']==port)&(a['result']==1)];j=int(np.searchsorted(sends['start'],hi));assert j<len(sends)
  pub=hop['producer',node,11];assert np.array_equal(pub[:len(sends),1]*8,sends['result'])
  r.update(request_received_ns=int(requests[j]['end']),output_published_ns=int(pub[j,0]),iq_send_start_ns=int(sends[j]['start']),output_available_to_yield_return_us=(hi-int(pub[j,0]))/1000)
 out.append(r)
binary=pathlib.Path(json.loads((p/'launch.json').read_text())['environment']['OCUDU_NATIVE_CHANNEL_BUILD'])/'ocudu-gpu-channel';assembly=sp.check_output(['objdump','-d','--no-show-raw-insn',str(binary)],text=True);calls=[]
for line in assembly.splitlines():
 m=re.match(r'\s*([0-9a-f]+):\s+bl\s+.*<sched_yield@plt>',line)
 if m:calls.append(int(m[1],16)+4)
resolved={}
for pc in set(r['caller'] for r in out):
 candidates=[v for v in calls if v&65535==pc&65535];resolved[str(pc)]=[dict(file_return_pc=hex(v),symbol=sp.check_output(['addr2line','-C','-f','-i','-e',str(binary),hex(v-4)],text=True).strip()) for v in candidates]
r=dict(producer_tids=roles,long_yields=len(y),events=out,resolved_callers=resolved,limitations='Arrival calculation uses one incoming source per receiver and the producer cumulative sample epoch. It identifies when progress first became possible, not when the full eventually-selected block arrived.');(p/'yield-analysis.json').write_text(json.dumps(r,indent=2)+'\n')
print('roles',roles)
for e in out[:5]:print(e)
print('callers',resolved)
