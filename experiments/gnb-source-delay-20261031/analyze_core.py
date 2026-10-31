"""Join CUDA-wait yields to the peer that actually consumed the same CPU."""
import pathlib,json,csv,re,sys,collections,numpy as np
p=pathlib.Path(sys.argv[1]);meta=json.loads((p/'gnb-capture.json').read_text());mode=json.loads((p/'core-mode.json').read_text());roles={v['comm']:int(k) for k,v in meta['tasks'].items() if v['comm'] in ['radio','phy_worker']};host={name:int(meta['mapping'][str(tid)]) for name,tid in roles.items()};lo=mode['applied_mono_ns'];hi=mode['restored_mono_ns'];dt=np.dtype([(s,'<i8') for s in ['op','tid','port','flags','start','end','result','error']]);a=None
for f in (p/'raw/wire').glob('gnb-*.wire'):
 h=np.fromfile(f,dtype='<u8',count=8);assert h[3]==0
 if h[1]:a=np.memmap(f,dtype=dt,offset=64,shape=(int(h[1]),));assert not np.any(a['op']==0)
assert a is not None
cpu=(p/'gnb-cpu.txt').read_text();m=re.search(r'([0-9a-f]+)\s+ocudu::radio_zmq_rx_channel::run_async\(\)\+0x([0-9a-f]+)',cpu);assert m,'load bias not found';bias=int(m[1],16)-0xbaa7ec-int(m[2],16);assert bias%65536==0,hex(bias)
y=a[(a['op']==40)&(a['tid']==roles['phy_worker'])&(a['start']>=lo)&(a['end']<=hi)];y=y[np.argsort(y['end']-y['start'])[::-1]]
switch=[];pat=re.compile(r'.*?\[(\d+)\]\s+(\d+)\.(\d+):\s+sched:sched_switch: prev_comm=(.*?) prev_pid=(\d+) prev_prio=(\d+) prev_state=(.*?) ==> next_comm=(.*?) next_pid=(\d+)')
for line in (p/'gnb-functions.txt').open():
 if 'sched:sched_switch:' not in line:continue
 m=pat.match(line)
 if not m:continue
 v=m.groups();t=int(v[1])*10**9+int(v[2].ljust(9,'0'))
 if lo-1000000<=t<=hi+1000000:
  r=dict(cpu=int(v[0]),time_ns=t,prev_comm=v[3],prev_pid=int(v[4]),prev_prio=int(v[5]),prev_state=v[6],next_comm=v[7],next_pid=int(v[8]));
  if not switch or r!=switch[-1]:switch.append(r)
functions={0x1b6222c:'flush_pending_output -> wait_event_yielding',0x18e0868:'cudaEventSynchronizeYielding (PUSCH)'};events=[]
for e in y[:20]:
 start=int(e['start']);end=int(e['end']);core=int(e['flags'])>>16;rows=[r for r in switch if r['cpu']==core and start<=r['time_ns']<=end];who=collections.Counter();t=start;current=host['phy_worker']
 for r in rows:
  who[current]+=(r['time_ns']-t)/1000;current=r['next_pid'];t=r['time_ns']
 who[current]+=(end-t)/1000
 events.append(dict(start_ns=start,end_ns=end,yield_us=(end-start)/1000,cpu_before=core,cpu_after=int(e['flags'])&65535,caller_return_pc=hex(int(e['result'])),elf_return_offset=hex(int(e['result'])-bias),function=functions.get(int(e['result'])-bias,'other'),radio_cpu_us=who[host['radio']],phy_cpu_us=who[host['phy_worker']],other_cpu_us=sum(v for k,v in who.items() if k not in host.values()),scheduler_events=rows))
rate=json.loads((p/'rate-analysis.json').read_text());rebases=list(csv.DictReader((p/'raw/pacing/gnb0.csv').open()));local=[r for r in rebases if lo<=int(r['now_ns'])<=hi+20000000];sends=a[(a['op']==1)&(a['port']==2000)&(a['result']>=8)];gaps=[dict(previous_send_end_ns=int(x['end']),next_send_start_ns=int(z['start']),gap_us=(int(z['start'])-int(x['end']))/1000) for x,z in zip(sends,sends[1:]) if lo<=int(z['start'])<=hi+20000000]
out=dict(mode=mode,namespace_tids=roles,host_tids=host,elf_load_bias=hex(bias),long_phy_yields_in_window=len(y),largest_yields=events,largest_source_iq_gaps=sorted(gaps,key=lambda r:r['gap_us'],reverse=True)[:10],rebases_in_window_and_20ms_tail=len(local),rebase_sum_us_in_window_and_tail=sum(int(r['shift_ns']) for r in local)/1000,post_warmup=rate['post_warmup'],limitation='The scheduler join measures which CPU thread ran during the CUDA-wait yield; GPU completion time itself is not measured. Affinity is a controlled intervention within the original gNB allocation, not a new core allocation.')
(p/'core-analysis.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(dict(mode=mode['mode'],long_phy_yields=len(y),rebases=out['rebases_in_window_and_20ms_tail'],rebase_sum_us=out['rebase_sum_us_in_window_and_tail'],largest_yields=[{k:v for k,v in e.items() if k!='scheduler_events'} for e in events[:2]]),indent=2))
