"""Trace the final received DL message preceding each delayed UE RF TX entry."""
import pathlib,json,csv,sys,collections,numpy as np
p=pathlib.Path(sys.argv[1]);dt=np.dtype([(s,'<i8') for s in ['op','tid','port','flags','start','end','result','error']]);actors={}
for f in (p/'raw/wire').glob('*.wire'):
 h=np.fromfile(f,dtype='<u8',count=8);assert h[3]==0
 v=np.memmap(f,dtype=dt,offset=64,shape=(int(h[1]),))
 if len(v):actors[f.name.split('-')[0]]=v
u=actors['srsue'];b=actors['ocudu'];g=actors['gnb'];rx=u[u['op']==35];rx=rx[np.argsort(rx['end'])];rcv=u[(u['op']==2)&(u['port']==2100)&(u['result']>=8)];snd=b[(b['op']==1)&(b['port']==2100)&(b['result']>=8)];req=b[(b['op']==2)&(b['port']==2100)&(b['result']==1)]
hop=collections.defaultdict(list)
for r in csv.DictReader((p/'hop/hop-trace.csv').open()):hop[r['role'],r['id'],int(r['event'])].append((int(r['t_ns']),int(r['samples'])))
pub=np.array(hop['producer','ue0',11]);ready=np.array(hop['producer','ue0',10]);starts=np.cumsum(pub[:,1])-pub[:,1];push=np.array(hop['puller','gnb0_p0',2]);cum=np.cumsum(push[:,1]);gnb_snd=g[(g['op']==1)&(g['port']==2000)&(g['result']>=8)]
n=min(len(snd),len(rcv));assert abs(len(snd)-len(rcv))<=1 and np.array_equal(snd[:n]['result'],rcv[:n]['result']);assert np.array_equal(pub[:len(snd),1]*8,snd['result'])
out=[]
for e in json.loads((p/'rf-analysis.json').read_text())['events']:
 tx=e['times']['ue_rf_tx_enter'];rf=rx[int(np.searchsorted(rx['end'],tx,side='right'))-1];j=int(np.searchsorted(rcv['end'],int(rf['end']),side='right'))-1;k=int(np.searchsorted(cum,int(starts[j]),side='right'))
 out.append(dict(sample=e['sample'],shift_us=e['shift_us'],ue_rf_rx_start_ns=int(rf['start']),ue_rf_rx_end_ns=int(rf['end']),ue_rx_to_tx_us=(tx-int(rf['end']))/1000,last_dl_message=j,last_dl_receive_end_ns=int(rcv[j]['end']),last_dl_send_end_ns=int(snd[j]['end']),last_dl_request_received_ns=int(req[j]['end']),dl_output_published_ns=int(pub[j,0]),dl_input_ready_ns=int(ready[j,0]),gnb_source_send_end_ns=int(gnb_snd[k]['end']),gnb_source_pushed_ns=int(push[k,0]),gnb_send_to_push_us=(int(push[k,0])-int(gnb_snd[k]['end']))/1000,source_push_to_dl_ready_us=(int(ready[j,0])-int(push[k,0]))/1000,publish_to_send_us=(int(snd[j]['start'])-int(pub[j,0]))/1000,send_to_ue_recv_us=(int(rcv[j]['end'])-int(snd[j]['end']))/1000))
(p/'downlink-analysis.json').write_text(json.dumps(dict(events=out,limitation='The last RF RX completion before TX is a temporal boundary, not a decoded slot or HARQ association. Input matching identifies the first needed source sample, not full-block availability.'),indent=2)+'\n')
print(json.dumps(sorted(out,key=lambda x:x['shift_us'],reverse=True)[:2],indent=2))
