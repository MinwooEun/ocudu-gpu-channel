"""Match each sparse pacing rebase to UE IQ readiness and broker receive/dispatch."""
import pathlib,json,csv,collections,numpy as np
p=pathlib.Path('/workspace/gpuch/realtime-rate-20261030/u1/original-input-root2-r2');wire=pathlib.Path('/dev/shm/ocudu-input-root2-20261030/wire');names=['op','tid','port','flags','start','end','result','error'];dt=np.dtype([(x,'<i8') for x in names]);actors={};files=[]
for f in wire.glob('*.wire'):
 h=np.fromfile(f,dtype='<u8',count=8);assert h[3]==0,(f,int(h[3]));a=np.memmap(f,dtype=dt,offset=64,shape=(int(h[1]),),mode='r');assert not np.any(a['op']==0),f
 files.append(dict(file=f.name,records=int(h[1]),dropped=int(h[3])));
 if len(a):actors[f.name.split('-')[0]]=a
print('files',files)
u=actors['srsue'];b=actors['ocudu'];g=actors['gnb']
# A filename beginning ocudu-gpu-channel splits to ocudu; only one broker exists.
ports,cnt=np.unique(u[(u['op']==1)&(u['result']>=8)]['port'],return_counts=True);port=int(ports[np.argmax(cnt)])
t=u[(u['op']==1)&(u['port']==port)&(u['result']>=8)];r=b[(b['op']==2)&(b['port']==port)&(b['result']>=8)];q=b[(b['op']==1)&(b['port']==port)&(b['result']==1)];ur=u[(u['op']==2)&(u['port']==port)&(u['result']==1)]
assert np.array_equal(t['result'],r['result']),(len(t),len(r));pending_request=len(q)-len(r);assert pending_request in [0,1] and len(ur)==len(r),(len(q),len(r),len(ur))
if pending_request:assert q[-1]['start']>=r[-1]['end']
q=q[:len(r)]
cum=np.cumsum(r['result']//8)
hop=collections.defaultdict(list)
for x in csv.DictReader((p/'hop/hop-trace.csv').open()):hop[x['role'],x['id'],int(x['event'])].append((int(x['t_ns']),int(x['samples'])))
for k in hop:hop[k]=np.array(hop[k],dtype=np.int64)
print('hop keys',[(k,len(v)) for k,v in hop.items()])
rb=hop['puller','ue0_p0',1];push=hop['puller','ue0_p0',2];ready=hop['producer','gnb0',10];starts=np.cumsum(ready[:,1])-ready[:,1]
assert np.array_equal(rb[:,1]*8,r['result']);assert len(push)==len(rb)
rep=json.loads((p/'runtime/report/run-report.json').read_text());lo=rep['epoch']['s0']+230400000;hi=rep['epoch']['s0']+rep['epoch']['measure_samples'];events=[x for x in csv.DictReader(pathlib.Path('/dev/shm/ocudu-input-root2-20261030/pacing/gnb0.csv').open()) if lo<=int(x['sample'])<hi]
rf=u[np.isin(u['op'],[30,32])];rf=rf[np.argsort(rf['start'])];rx=u[u['op']==35];rx=rx[np.argsort(rx['end'])]
out=[]
for e in events:
 sample=int(e['sample']);i=int(np.searchsorted(cum,sample,side='right'));j=int(np.searchsorted(starts,sample));assert starts[j]==sample
 candidates=rf[(rf['tid']==t[i]['tid'])&(rf['start']<=t[i]['start'])&(rf['end']>=t[i]['end'])];assert len(candidates)==1,(i,len(candidates));f=candidates[0]
 expected=int(e['expected_due_ns']);txready=int(f['start']);rxidx=int(np.searchsorted(rx['end'],txready,side='right'))-1
 times=dict(request_start=int(q[i]['start']),ue_rf_tx_enter=txready,ue_request_poll_start=int(ur[i]['start']),ue_request_recv_end=int(ur[i]['end']),ue_iq_send_start=int(t[i]['start']),ue_iq_send_end=int(t[i]['end']),broker_iq_recv_end=int(r[i]['end']),broker_ring_pushed=int(push[i,0]),producer_data_ready=int(ready[j,0]),pace_call=int(e['now_ns']))
 later=max(times,key=times.get)
 row=dict(sample=sample,shift_us=int(e['shift_ns'])/1000,expected_due_ns=expected,data_us=float(e['data_us']),times=times,relative_to_due_us={k:(v-expected)/1000 for k,v in times.items()},rf_op=int(f['op']),matched_bytes=int(r[i]['result']),latest_rx_end_ns=int(rx[rxidx]['end']) if rxidx>=0 else None,rx_to_txready_us=(txready-int(rx[rxidx]['end']))/1000 if rxidx>=0 else None)
 if txready>expected:row['first_late_stage']='UE IQ preparation / pre-send entry'
 elif times['request_start']>expected:row['first_late_stage']='broker pull request start'
 elif times['ue_request_recv_end']>expected:row['first_late_stage']='request transport / UE polling'
 elif times['ue_iq_send_start']>expected:row['first_late_stage']='UE request-to-send handling'
 elif times['broker_iq_recv_end']>expected:row['first_late_stage']='IQ transport / broker receiving'
 elif times['broker_ring_pushed']>expected:row['first_late_stage']='broker receive-to-ring'
 else:row['first_late_stage']='broker producer readiness dispatch'
 out.append(row)
result=dict(files=files,port=port,matched_messages=len(t),terminal_pending_request=pending_request,rebase_events=len(out),by_first_late_stage=dict(collections.Counter(x['first_late_stage'] for x in out)),events=out,note='Classification uses the expected producer pacing deadline, not a reconstructed RF deadline. A late upstream API entry can be propagated backpressure rather than expensive PHY computation; upstream RX timing is retained for further attribution.')
(p/'input-analysis.json').write_text(json.dumps(result,indent=2)+'\n');print('events',len(out),'groups',result['by_first_late_stage'])
for x in sorted(out,key=lambda x:x['shift_us'],reverse=True)[:10]:print(x)
