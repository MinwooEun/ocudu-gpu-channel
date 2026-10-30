"""Join CPU17 scheduler ownership and synchronous log writes to measured misses."""
import pathlib,json,csv,re,sys,collections,numpy as np
p=pathlib.Path(sys.argv[1]);dt=np.dtype([(s,'<i8') for s in ['op','tid','port','flags','start','end','result','error']]);actors={}
for f in (p/'raw/wire').glob('*.wire'):
 h=np.fromfile(f,dtype='<u8',count=8);assert h[3]==0
 v=np.memmap(f,dtype=dt,offset=64,shape=(int(h[1]),))
 if len(v):actors[f.name.split('-')[0]]=v
u=actors['srsue'];b=actors['ocudu'];req=u[(u['op']==1)&(u['port']==2100)&(u['result']==1)];switch=[];mapping={};outs=collections.defaultdict(list)
pat=re.compile(r'\s*.*?\s+(\d+)\s+\[\d+\]\s+(\d+)\.(\d+): sched:sched_switch: prev_comm=(.*?) prev_pid=(\d+) prev_prio=(\d+) prev_state=(.*?) ==> next_comm=(.*?) next_pid=(\d+)')
for line in (p/'sched.txt').open():
 m=pat.match(line)
 if not m:continue
 a=m.groups();t=int(a[1])*10**9+int(a[2].ljust(9,'0'));mapping[int(a[0])]=int(a[4]);switch.append((t,int(a[8]),a[7]));outs[int(a[4])].append(dict(time_ns=t,state=a[6],priority=int(a[5])))
events=[]
for e in json.loads((p/'downlink-analysis.json').read_text())['events']:
 r=req[e['last_dl_message']];lo=e['dl_output_published_ns'];hi=int(r['start'])
 if hi<=lo:continue
 who=collections.Counter()
 for a,c in zip(switch,switch[1:]):
  if c[0]<=lo or a[0]>=hi:continue
  who[a[1],a[2]]+=max(0,min(c[0],hi)-max(a[0],lo))/1000
 host=mapping[int(r['tid'])];before=[x for x in outs[host] if x['time_ns']<=lo]
 events.append(dict(sample=e['sample'],rebase_us=e['shift_us'],iq_published_ns=lo,ue_request_start_ns=hi,ready_to_request_us=(hi-lo)/1000,rf_rx_tid=int(r['tid']),host_tid=host,last_switch_out_before_publish=before[-1] if before else None,cpu_occupants=[dict(host_tid=t,comm=c,cpu_us=v) for (t,c),v in who.most_common()]))
process=[]
for r in csv.DictReader((p/'room/gnb0-process.csv').open()):
 lo=int(r['start_ns']);hi=int(r['end_ns']);writes=b[(b['op']==41)&(b['start']>=lo)&(b['end']<=hi)]
 if not len(writes):continue
 process.append(dict(sample=int(r['sample']),wall_us=(hi-lo)/1000,cpu_us=int(r['cpu_ns'])/1000,count=int(r['count']),writes=[dict(tid=int(w['tid']),start_ns=int(w['start']),end_ns=int(w['end']),wall_us=(int(w['end'])-int(w['start']))/1000,bytes=int(w['result'])) for w in writes]))
(p/'causes.json').write_text(json.dumps(dict(cpu17_switches=len(switch),ue_receive_request_delays=events,process_with_stdout_write=process,limitations='CPU17 scheduling capture is diagnostic and perturbs execution. Write duration includes all time between intercepted write entry/return; native-log kernel blocking versus descheduling inside the call is not separated.'),indent=2)+'\n')
print(json.dumps(dict(ue_events=len(events),process_with_write=len(process)),indent=2))
