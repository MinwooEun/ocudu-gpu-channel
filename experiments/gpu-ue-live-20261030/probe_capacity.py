"""Four-second scheduler demand observation with two actual link-clock reads.
No tracing/sampling is enabled in the measured processes; run this on aux CPUs.
"""
import argparse,collections,json,pathlib,re,time,zmq
p=argparse.ArgumentParser();p.add_argument('case');p.add_argument('--ues',type=int,choices=(8,16),default=16);a=p.parse_args()
P=pathlib.Path('/workspace/gpuch/gpu-ue-live-20261030')/f'u{a.ues}'/a.case
launch=json.loads((P/'launch.json').read_text()) if (P/'launch.json').exists() else None
log=P/'runner.log';deadline=time.monotonic()+240
while time.monotonic()<deadline:
 if log.exists() and 'event=measure_release ' in log.read_text():break
 if (P/'result.json').exists():raise RuntimeError('case ended before measurement')
 time.sleep(.25)
else:raise RuntimeError('measurement release not found')
launch=json.loads((P/'launch.json').read_text());ue_binary=launch['active_ue_binary']
brokers=[];ues=[]
for proc in pathlib.Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:cmd=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode()
 except (OSError,UnicodeError):continue
 if '/ocudu-gpu-channel ' in cmd and str(P) in cmd and cmd.startswith('/workspace/gpuch/profile-20261028/build/'):brokers.append(proc)
 if cmd.startswith(ue_binary+' '):ues.append(proc)
assert len(brokers)==1,len(brokers)
assert len(ues)==a.ues,len(ues)
broker=brokers[0]
endpoint=re.search(r'event=control_start endpoint="([^"]+)"',(P/'runtime/logs/broker.log').read_text()[:100000]).group(1)
assert endpoint.startswith('ipc://'),endpoint
endpoint='ipc:///proc/'+broker.name+'/root'+endpoint[len('ipc://'):]
ctx=zmq.Context();req=ctx.socket(zmq.REQ);req.setsockopt(zmq.LINGER,0);req.setsockopt(zmq.RCVTIMEO,2000);req.setsockopt(zmq.SNDTIMEO,2000);req.connect(endpoint)

def clock():
 t0=time.monotonic_ns();req.send_json({'type':'link_clock'});r=req.recv_json();t1=time.monotonic_ns()
 assert r['ok']
 links=[x for x in r['links'] if '>gnb0:' in x['link_id']]
 assert len(links)==a.ues,len(links)
 return dict(midpoint_ns=(t0+t1)//2,roundtrip_ns=t1-t0,sample=links[0]['sample'],link=links[0]['link_id'])

def snapshot():
 data={}
 for proc in [broker]+ues:
  for thread in (proc/'task').iterdir():
   try:
    s=list(map(int,(thread/'schedstat').read_text().split()))
    fields={x.split(':',1)[0]:x.split(':',1)[1].strip() for x in (thread/'status').read_text().splitlines() if ':' in x}
    data[thread.name]=dict(pid=proc.name,comm=(thread/'comm').read_text().strip(),schedstat=s,cpus=fields['Cpus_allowed_list'])
   except FileNotFoundError:pass
 return dict(monotonic_ns=time.monotonic_ns(),threads=data,
             cores={l.split()[0]:list(map(int,l.split()[1:])) for l in pathlib.Path('/proc/stat').read_text().splitlines() if re.match(r'cpu\d+ ',l)})
activation=[]
for proc in ues:
 env=dict(x.decode().split('=',1) for x in (proc/'environ').read_bytes().split(b'\0') if b'=' in x)
 activation.append(dict(pid=proc.name,binary=str((proc/'exe').resolve()),environment={k:env.get(k) for k in ['SRSRAN_UE_DL_CUDA','SRSRAN_LDPC_DECODER','SRSRAN_LDPC_CUDA_SYNC','CUDA_MPS_PIPE_DIRECTORY']}))
first_clock=clock();first=snapshot();time.sleep(4);last=snapshot();last_clock=clock();req.close();ctx.term()
wall=(last['monotonic_ns']-first['monotonic_ns'])/1e9
radio=(last_clock['sample']-first_clock['sample'])/23040000
assert radio>0
by_process=collections.defaultdict(lambda:dict(cpu_s=0,runqueue_s=0,roles=collections.defaultdict(float)))
for tid,b in first['threads'].items():
 assert tid in last['threads'],('thread ended',tid)
 e=last['threads'][tid];delta=[(x-y)/1e9 for x,y in zip(e['schedstat'][:2],b['schedstat'][:2])]
 s=by_process[b['pid']];s['cpu_s']+=delta[0];s['runqueue_s']+=delta[1];s['roles'][b['comm']]+=delta[0]
ue_cpu=sum(v['cpu_s'] for k,v in by_process.items() if k!=broker.name)
ue_roles=collections.defaultdict(float)
for pid,v in by_process.items():
 if pid!=broker.name:
  for role,cpu in v['roles'].items():ue_roles[role]+=cpu
cores={}
for core in [13,14,17,18,19]:
 k='cpu'+str(core);delta=[x-y for x,y in zip(last['cores'][k],first['cores'][k])];total=sum(delta[:8]);idle=delta[3]+delta[4]
 cores[k]=dict(busy_fraction=(total-idle)/total,total_ticks=total)
result=dict(case=a.case,activation=activation,wall_s=wall,radio_s=radio,radio_wall_ratio=radio/((last_clock['midpoint_ns']-first_clock['midpoint_ns'])/1e9),
 ue_cpu_s=ue_cpu,ue_scheduled_cores=ue_cpu/wall,ue_cpu_seconds_per_radio_second=ue_cpu/radio,ue_roles_cpu_s=dict(ue_roles),ue_cores=cores,
 broker_pid=broker.name,first_clock=first_clock,last_clock=last_clock,processes=by_process,
 note='Four-second observation; scheduler running time includes that thread user and system execution. CPU roles alone do not identify individual arithmetic functions.',before=first,after=last)
(P/'capacity-window.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['before','after','processes']}))
