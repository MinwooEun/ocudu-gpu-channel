import json, os, pathlib, signal, subprocess as sp, time, argparse, sys
P=pathlib.Path('/workspace/gpuch/profile-20261028'); G='/workspace/ocudu-spark/builds/d10-cuda-patched-sm121/apps/gnb/gnb'
G=os.environ.get('CAUSAL_GNB',G)
CHANNEL_BUILD=os.environ.get('CAUSAL_CHANNEL_BUILD',str(P/'build'))
ap=argparse.ArgumentParser(); ap.add_argument('--kind',choices=['ue','antenna','cell'],default='ue'); ap.add_argument('--one',action='store_true'); ap.add_argument('--nsys',action='store_true'); ap.add_argument('--control',action='store_true'); ap.add_argument('--no-perf',action='store_true'); ap.add_argument('--cpu-only',action='store_true'); ap.add_argument('--ues',type=int); a=ap.parse_args()
base=dict(os.environ,LD_LIBRARY_PATH='/usr/local/cuda/lib64',PATH='/usr/local/cuda/bin:'+os.environ['PATH'],OCUDU_NATIVE_CUDA_ARCH='121',OCUDU_NATIVE_SKIP_WORKSPACE_LOCK='1',OCG_PROFILE_PREBUILT='1',OCUDU_NATIVE_CHANNEL_BUILD=CHANNEL_BUILD,OCUDU_NATIVE_GNB_BINARY=G,OCUDU_NATIVE_GNB_ACCELERATION='all',OCUDU_NATIVE_GNB_START_TIMEOUT_SECONDS='150')
def run(label,cmd,env,cwd):
 if a.nsys:label+='-nsys'
 if a.control:label+='-control'
 elif a.cpu_only:label+='-cpu-sampled'
 elif a.no_perf:label+='-trace-only'
 d=pathlib.Path('/workspace/gpuch/profile-20261029-causal')/(label+os.environ.get('CAUSAL_SUFFIX',''));d.mkdir(parents=True,exist_ok=True);(d/'trace').mkdir(exist_ok=True)
 if (d/'result.json').exists():return
 if sp.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip():raise RuntimeError('GPU occupied')
 env=dict(base,**env,OCG_PROFILE_DIR=str(d/'trace'),OCG_HOP_TRACE_DIR=str(d/'hop'));(d/'hop').mkdir(exist_ok=True)
 if not a.control:
  env['LD_PRELOAD']=os.environ.get('CAUSAL_INTERPOSER','/workspace/gpuch/profile-20261029-causal/wire_trace-v2.so')
  env['OCG_WIRE_TRACE_DIR']=str(d/'wire');(d/'wire').mkdir(exist_ok=True)
 if a.control or a.cpu_only:env.pop('OCG_PROFILE_DIR',None);env.pop('OCG_HOP_TRACE_DIR',None)
 (d/'launch.json').write_text(json.dumps(dict(command=cmd,cwd=str(cwd),env={k:v for k,v in env.items() if k.startswith(('OC','SINGLE','OAI','SB_','RANB'))}),indent=2))
 if a.nsys:
  cmd=['/usr/local/cuda/bin/nsys','profile','--trace=cuda,nvtx','--sample=none','--cpuctxsw=none','--delay=55','--duration=20','--kill=none','--wait=primary','-o',str(d/'timeline')]+cmd
 (d/'clock-pair.json').write_text(json.dumps(dict(realtime_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())))
 print('START',label,flush=True); f=(d/'runner.log').open('w'); start=time.monotonic()
 p=sp.Popen(cmd,cwd=cwd,env=env,stdout=f,stderr=sp.STDOUT,start_new_session=True)
 samples=(d/'threads.txt').open('w'); profilers=[]; profiled=set()
 try:
  while p.poll() is None:
   if time.monotonic()-start>900:os.killpg(p.pid,signal.SIGTERM);break
   sp.run(['ps','-eLo','pid,tid,psr,pcpu,stat,comm'],stdout=samples)
   # Attach once after each real radio has existed for 35 seconds; no synthetic substitute.
   listing=sp.check_output(['ps','-eo','pid,etimes,comm'],text=True)
   if a.cpu_only:
    active=pathlib.Path('/workspace/ocudu-spark-ranb/results/single-cell-scheduler-benchmark/active')
    for applied in active.glob('policy_runs/*/logs/replay-applied.jsonl'):
     policy=applied.parent.parent
     if policy.name in profiled:continue
     with applied.open('rb') as af:
      af.seek(max(0,applied.stat().st_size-32768));tail=af.read().decode(errors='replace')
     ready=False
     for line in tail.splitlines():
      try:rr=json.loads(line)
      except ValueError:continue
      if rr.get('record')=='applied' and rr.get('k',-1)>=120:ready=True
     if not ready:continue
     targets=[]
     for proc in pathlib.Path('/proc').glob('[0-9]*'):
      try:
       comm=(proc/'comm').read_text().strip();cmdline=(proc/'cmdline').read_bytes().decode(errors='replace')
       if comm in ('gnb','srsue','ocudu-gpu-chann') and str(policy) in cmdline:targets.append(proc.name)
      except (FileNotFoundError,ProcessLookupError,PermissionError):pass
     if targets:
      pf=(d/f'perf-steady-{policy.name}.log').open('w')
      profilers.append((sp.Popen(['taskset','-c','0-4','perf','record','-F','49','-g','--call-graph','dwarf,4096','-p',','.join(targets),'-o',str(d/f'perf-steady-{policy.name}.data'),'--','sleep','12'],stdout=pf,stderr=pf),pf));profiled.add(policy.name)
      (d/f'perf-steady-{policy.name}.json').write_text(json.dumps(dict(target_pids=targets,start_monotonic_ns=time.monotonic_ns(),trigger='applied update k >= 120 (12 radio seconds, beyond 10 radio seconds warmup)')))
   for line in listing.splitlines()[1:]:
    q=line.split()
    if len(q)!=3:continue
    pid,age,name=q
    if not a.nsys and not a.control and not a.no_perf and not a.cpu_only and name in ('gnb','srsue','nr-uesoftmodem','ocudu-gpu-chann') and int(age)>35 and pid not in profiled:
     pf=(d/f'perf-{name}-{pid}.log').open('w')
     profilers.append((sp.Popen(['taskset','-c','0-4','perf','record','-F','99','-g','--call-graph','dwarf,4096','-p',pid,'-o',str(d/f'perf-{name}-{pid}.data'),'--','sleep','15'],stdout=pf,stderr=pf),pf));profiled.add(pid)
   time.sleep(3)
  p.wait(timeout=30)
 finally:
  if p.poll() is None:os.killpg(p.pid,signal.SIGKILL);p.wait()
  for pp,pf in profilers:
   pp.wait(timeout=30);pf.close()
  f.close();samples.close()
 (d/'result.json').write_text(json.dumps(dict(label=label,rc=p.returncode,wall_s=time.monotonic()-start),indent=2));print('END',label,p.returncode,flush=True)
if a.cpu_only:
 sp.run([sys.executable,__file__,'--kind','cell','--control'],check=True)
 sp.run([sys.executable,str(P/'boundary.py'),'--live-budget-blocking'],check=True)
 sp.run([sys.executable,str(P/'boundary.py'),'--nsys'],check=False)
if a.kind=='cell':
 # Establish whether the 16-UE control timeout persists without profilers.
 sp.run([sys.executable,__file__,'--kind','ue','--ues','16','--control'],check=True)
 sp.run([sys.executable,__file__,'--kind','ue','--ues','16','--no-perf'],check=True)
if a.kind=='ue':
 for n in ([a.ues] if a.ues else ([8] if a.nsys or a.control else ([1] if a.one else [1,4,8,16]))):
  req=dict(ue_count=n,gnb_antennas=1,mobility='pedestrian',placement='uniform',traffic_profile='mixed',tests=[dict(scheduler='rr',link_adaptation='harq_olla'),dict(scheduler='rr',link_adaptation='harq_olla')],seed=20261016,measure_seconds=30,warmup_seconds=10,repeat_count=1,comparison_order='abba')
  env=dict(SB_ALLOW_UNVALIDATED='1',SINGLE_CELL_CPUS_AUX='0-4',SINGLE_CELL_UE_RX_SLEEP='false',SINGLE_CELL_QUIET_LOGS='1',SINGLE_CELL_PCAP='off',SINGLE_CELL_CPUS_GNB='5-12',SINGLE_CELL_CPUS_BROKER='15-16',SINGLE_CELL_CPUS_UES='17-19',OCG_BROKER_SPIN='2',OCG_ZMQ_IO_THREADS='2',SINGLE_CELL_GNB_BINARY=G,SINGLE_CELL_GNB_ACCELERATION='all',SINGLE_CELL_GNB_START_TIMEOUT='150',SINGLE_CELL_MPS='on',SINGLE_CELL_BROKER_IN_MPS='1',RANB_REQ=json.dumps(req))
  for i in range(n):env[f'SINGLE_CELL_CPUS_UE{i}']=str([17,18,19,17,18,19,13,14][i%8])
  kv=[f'{k}={v}' for k,v in dict(env,OCUDU_NATIVE_CHANNEL_BUILD=CHANNEL_BUILD).items()]
  run(f'cuda-u{n}-c1-bw20-a1x1',['bash','/workspace/gpuch/profile-20261029-causal/ranb-run.sh',f'causal1029-u{n}'+os.environ.get('CAUSAL_SUFFIX','')+('-control' if a.control else '-wire')]+kv,env,P/'ranb')
elif a.kind=='antenna':
 for bw,g,u in ([(100,4,1)] if a.one else [(20,2,2),(50,2,2),(100,2,2),(20,4,4),(50,4,4),(100,4,4),(100,4,1)]):
  topology='/workspace/gpuch/bound/nxm/topology.oai-'+str(g)+'x'+str(u)+'.yaml' if (g,u)!=(2,2) else str(P/'br15/examples/native/topology.ocudu.oai-2x2-unitary.cuda.yaml')
  env=dict(OCUDU_NATIVE_ROOT='/workspace/ocudu-spark',OCUDU_CUDA_WORKSPACE_LOCK=str(P/'br15/scripts/cuda/cuda-workspace.spark-d10.lock.json'),OAI2X2_PATH='broker',OAI2X2_BW_MHZ=str(bw),OAI2X2_CUDA_HOST_MEMORY='zero_copy',OAI2X2_TOPOLOGY=topology,OAI2X2_GNB_ANT=str(g),OAI2X2_UE_ANT=str(u),OAI2X2_IPERF_RATE='1M',OAI2X2_IPERF_SECONDS='30',OAI2X2_ALLOW_UNHEALTHY='1')
  run(f'cuda-u1-c1-bw{bw}-a{g}x{u}',['bash',str(P/'br15/scripts/native/run-ocudu-oai-2x2.sh')],env,P/'br15')
else:
 env=dict(OCUDU_NATIVE_ROOT='/workspace/ocudu-spark-ranb',OCUDU_NATIVE_SIONNA_PYTHON='/workspace/sionna-venv/bin/python',OCUDU_NATIVE_SB_WEB_UI='0',OCUDU_NATIVE_SB_SKIP_CTEST='1',OCUDU_NATIVE_SB_MEASURE_SECONDS='30',OCUDU_NATIVE_SB_UE_RX_SLEEP='false',OCUDU_NATIVE_SB_SEED='1',OCG_BROKER_SPIN='2',OCG_ZMQ_IO_THREADS='2',OCUDU_NATIVE_SB_GNB_ACCELERATION='all',OCUDU_NATIVE_SB_BROKER_IN_MPS='1',OCUDU_NATIVE_SB_SCHED_A='rr',OCUDU_NATIVE_SB_SCHED_B='rr')
 run('cuda-two-cell',['python3','scripts/cuda/with-cuda-mps.py','--','bash','use_cases/ran_benchmark/run-ocudu-scheduler-benchmark.sh'],env,P/'ranb')
