"""Match output-room rebases to gNB request, broker service and receive timings."""
import pathlib,json,csv,numpy as np,collections,bisect,sys
p=pathlib.Path(sys.argv[1]);ram=p/'raw' if (p/'raw').exists() else pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030');dt=np.dtype([(s,'<i8') for s in ['op','tid','port','flags','start','end','result','error']]);actors={};files=[]
for f in (ram/'wire').glob('*.wire'):
 h=np.fromfile(f,dtype='<u8',count=8);assert h[3]==0,(f,int(h[3]));n=int(h[1]);a=np.memmap(f,dtype=dt,offset=64,shape=(n,),mode='r');assert not np.any(a['op']==0),(f,'uncommitted');files.append(dict(file=f.name,records=n,dropped=0))
 if n:actors[f.name.split('-')[0]]=a
b=actors['ocudu'];g=actors['gnb'];send=b[(b['op']==1)&(b['port']==2001)&(b['result']>=8)];recv=g[(g['op']==2)&(g['port']==2001)&(g['result']>=8)];req=g[(g['op']==1)&(g['port']==2001)&(g['result']==1)];accepted=b[(b['op']==2)&(b['port']==2001)&(b['result']==1)]
assert abs(len(send)-len(recv))<=1,(len(send),len(recv));n=min(len(send),len(recv));assert np.array_equal(send[:n]['result'],recv[:n]['result']);assert n<=len(req)<=n+2 and n<=len(accepted)<=n+2,(n,len(req),len(accepted))
starts=np.cumsum(send['result']//8)-send['result']//8;ends=starts+send['result']//8
hop=collections.defaultdict(list)
for r in csv.DictReader((p/'hop/hop-trace.csv').open()):hop[r['role'],r['id'],int(r['event'])].append((int(r['t_ns']),int(r['samples'])))
for k in hop:hop[k]=np.array(hop[k],dtype=np.int64)
rowpop=hop['rep','gnb0_p0',21];reply=hop['rep','gnb0_p0',22];ready=hop['producer','gnb0',10];publish=hop['producer','gnb0',11]
assert len(rowpop) in [len(send),len(send)+1] and len(reply) in [len(send),len(send)+1],(len(rowpop),len(reply),len(send));assert np.array_equal(rowpop[:len(send),1]*8,send['result'])
report=json.loads((p/'runtime/report/run-report.json').read_text());s0=report['epoch']['s0'];lo=s0+230400000;hi=s0+report['epoch']['measure_samples'];rows=list(csv.DictReader((ram/'pacing/gnb0.csv').open()));events=[e for e in rows if lo<=int(e['sample'])<hi];out=[]
for e in events:
 sample=int(e['sample']);idx=int(np.searchsorted(starts,sample));assert starts[idx]==sample,(sample,starts[idx-1:idx+2]);assert idx>0
 # The previous publication must be drained before this high-water-limited producer can run.
 prev=idx-1;indices=range(max(0,prev-2),min(n,idx+2));timeline=[]
 for j in indices:
  timeline.append(dict(message=j,start_sample=int(starts[j]),end_sample=int(ends[j]),gnb_request_tid=int(req[j]['tid']),broker_rep_tid=int(send[j]['tid']),gnb_request_start=int(req[j]['start']),gnb_request_end=int(req[j]['end']),broker_request_received=int(accepted[j]['end']),broker_row_popped=int(rowpop[j,0]),broker_iq_send_start=int(send[j]['start']),broker_iq_send_end=int(send[j]['end']),gnb_iq_recv_start=int(recv[j]['start']),gnb_iq_recv_end=int(recv[j]['end']),request_transport_us=(int(accepted[j]['end'])-int(req[j]['end']))/1000,broker_receive_to_pop_us=(int(rowpop[j,0])-int(accepted[j]['end']))/1000))
 out.append(dict(sample=sample,scenario_s=(sample-s0)/23040000,rebase=e,previous_output_message=prev,timeline=timeline))
r=dict(files=files,matched_iq_messages=n,terminal_counts=dict(send=len(send),recv=len(recv),request=len(req),accepted=len(accepted)),events=out);(p/'output-analysis.json').write_text(json.dumps(r,indent=2)+'\n')
for e in sorted(out,key=lambda e:float(e['rebase']['room_us']),reverse=True)[:5]:
 print('EVENT',e['sample'],'room_us',e['rebase']['room_us'],'data_us',e['rebase']['data_us'],'shift_us',int(e['rebase']['shift_ns'])/1000)
 for t in e['timeline']:print(t)
