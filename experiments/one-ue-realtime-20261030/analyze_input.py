"""Split needed uplink IQ into UE send, broker receive, ring push and processing."""
import pathlib,csv,json,sys,numpy as np
p=pathlib.Path(sys.argv[1]);raw=p/'raw';dt=np.dtype([(s,'<i8') for s in ['op','tid','port','flags','start','end','result','error']]);actors={}
for f in (raw/'wire').glob('*.wire'):
 h=np.fromfile(f,dtype='<u8',count=8);assert h[3]==0,(f,int(h[3]))
 v=np.memmap(f,dtype=dt,offset=64,shape=(int(h[1]),));assert not np.any(v['op']==0)
 if len(v):actors[f.name.split('-')[0]]=v
u=actors['srsue'];b=actors['ocudu'];snd=u[(u['op']==1)&(u['port']==2101)&(u['result']>=8)];rcv=b[(b['op']==2)&(b['port']==2101)&(b['result']>=8)]
push=np.array([(int(r['t_ns']),int(r['samples'])) for r in csv.DictReader((p/'hop/hop-trace.csv').open()) if (r['role'],r['id'],r['event'])==('puller','ue0_p0','2')]);cum=np.cumsum(push[:,1]);n=min(len(snd),len(rcv),len(push));assert max(len(snd),len(rcv),len(push))-n<=1
assert np.array_equal(snd[:n]['result'],rcv[:n]['result']) and np.array_equal(snd[:n]['result']//8,push[:n,1])
out=[]
for e in json.loads((p/'rate-analysis.json').read_text())['post_warmup']['largest_rebases']:
 j=int(np.searchsorted(cum,int(e['sample']),side='right'));assert j<n
 out.append(dict(rebase=e,message=j,ue_send_start_ns=int(snd[j]['start']),ue_send_end_ns=int(snd[j]['end']),broker_recv_end_ns=int(rcv[j]['end']),input_pushed_ns=int(push[j,0]),send_to_push_us=(int(push[j,0])-int(snd[j]['end']))/1000,push_to_pacer_charge_us=(int(e['now_ns'])-int(push[j,0]))/1000))
(p/'input-analysis.json').write_text(json.dumps(dict(matched_messages=n,events=out,limitation='First needed input sample identifies earliest possible progress. UE send lateness does not identify which UE PHY, synchronization, or scheduling operation caused it.'),indent=2)+'\n')
print(json.dumps(out[:2],indent=2))
