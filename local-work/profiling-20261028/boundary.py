import argparse, csv, json, os, pathlib, signal, subprocess as sp, time
P=pathlib.Path('/workspace/gpuch/profile-20261028'); B=P/'build'
ap=argparse.ArgumentParser(); ap.add_argument('--quick',action='store_true'); ap.add_argument('--nsys',action='store_true'); ap.add_argument('--matched',action='store_true'); ap.add_argument('--io4',action='store_true'); ap.add_argument('--live-budget',action='store_true'); ap.add_argument('--live-budget-blocking',action='store_true'); a=ap.parse_args()
if a.live_budget_blocking:a.live_budget=True
# Bandwidth is the independent variable; sample rate is derived from the live radio recipe.
BW={20:(23040000,15),50:(61440000,15),100:(122880000,30)}
cases=[(n,1,20,1,1) for n in (1,4,8,16,24,32,64)]
cases += [(n,1,bw,1,1) for bw in (50,100) for n in (1,2,4,8)]
cases += [(1,1,bw,p,p) for bw in (20,50,100) for p in (2,4)]
cases += [(4,c,20,1,1) for c in (2,4)]
if a.quick: cases=[(1,1,20,1,1),(16,1,20,1,1)]
if a.nsys: cases=[(16,1,20,1,1),(1,1,100,4,4)]
if a.matched:cases=[(1,1,50,4,4),(1,1,100,4,4),(1,1,100,4,1)]
if a.io4:cases=[(24,1,20,1,1)]
if a.live_budget:cases=[(16,1,20,1,1)]
out=P/('diagnostic-live-budget-blocking' if a.live_budget_blocking else ('diagnostic-live-budget' if a.live_budget else ('diagnostic-io4' if a.io4 else ('matched-boundary' if a.matched else ('nsys-boundary' if a.nsys else ('overhead-release' if a.quick else 'boundary')))))); out.mkdir(exist_ok=True)
duration=12
for n,c,bw,g,u in cases:
 for rep in range(1 if a.nsys else 2):
  # Every sweep point has an uninstrumented throughput reference and an attributed trace run.
  trace_modes=[True] if a.nsys else ([False,True] if a.quick else [bool(rep)])
  for trace in trace_modes:
   label=f'u{n}-c{c}-bw{bw}-a{g}x{u}-r{rep}-trace{int(trace)}'; d=out/label
   if (d/'result.json').exists(): continue
   d.mkdir(exist_ok=True); (d/'trace').mkdir(exist_ok=True)
   if sp.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip():
    raise RuntimeError('GPU is occupied before '+label)
   rate,scs=BW[bw]; y=d/'topology.yaml'
   batch=rate*15//scs//1000; ports=c*(g+n*u); procs=[]; files=[]
   if a.matched:
    import re,hashlib
    original=P/'live'/f'cuda-u1-c1-bw{bw}-a{g}x{u}'/'evidence/report/topology.yaml'
    text=original.read_text();batch=int(re.search(r'^  batch_samples: (\d+)',text,re.M)[1])
    assert set(re.findall(r'sample_rate_hz: (\d+)',text))=={str(rate)}
    for direction,offset in [('tx',0),('rx',1)]:
     counter=iter(range(ports))
     text=re.sub(r'^(    '+direction+r'_endpoint:) .*$',lambda m:m[1]+' tcp://127.0.0.1:'+str(30000+2*next(counter)+offset),text,flags=re.M)
    y.write_text(text);(d/'matched-source.json').write_text(json.dumps(dict(source=str(original),source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),modified_fields=['devices.*.tx_endpoint','devices.*.rx_endpoint'],original_batch_samples=batch),indent=2))
   else:
    sp.run(['python3','/workspace/gpuch/bound/gen.py','--ues',str(n),'--cells',str(c),'--gnb-ports',str(g),'--ue-ports',str(u),'--srate-hz',str(rate),'--scs-khz',str(scs),'--base-port','30000','--out',str(y)],check=True,stdout=(d/'gen.log').open('w'))
   env=dict(os.environ,LD_LIBRARY_PATH='/usr/local/cuda/lib64',OCG_BROKER_SPIN='0',OCG_ZMQ_IO_THREADS='2')
   if a.io4:env['OCG_ZMQ_IO_THREADS']='4'
   if a.live_budget:env['OCG_BROKER_SPIN']='2'
   if a.live_budget_blocking:env['OCG_BROKER_SPIN']='0'
   if trace: env['OCG_PROFILE_DIR']=str(d/'trace')
   def launch(cmd,name,pin=None):
    f=(d/(name+'.log')).open('w'); files.append(f)
    p=sp.Popen((['taskset','-c',pin] if pin else [])+list(map(str,cmd)),stdout=f,stderr=sp.STDOUT,env=env,start_new_session=True); procs.append(p); return p
   print('START',label,flush=True)
   try:
    def radio_pin(i):return ('5-12' if i==0 else str([17,18,19,17,18,19,13,14][(i-1)%8])) if a.live_budget else '15-19'
    for i in range(ports): launch([B/'ocudu-zmq-source','--endpoint',f'tcp://127.0.0.1:{30000+2*i}','--batch-samples',batch,'--duration',f'{duration+12}s'],f'source-{i}',radio_pin(i))
    time.sleep(0.7)
    cmd=[B/'ocudu-gpu-channel','--config',y,'--duration',f'{duration+6}s']
    if a.nsys: cmd=['/usr/local/cuda/bin/nsys','profile','--trace=cuda,nvtx','--sample=none','--cpuctxsw=none','--duration=10','--kill=none','--wait=primary','--force-overwrite=true','-o',d/'timeline']+cmd
    broker=launch(cmd,'broker','15-16' if a.live_budget else '5-14'); time.sleep(1)
    sinks=[launch([B/'ocudu-zmq-sink','--endpoint',f'tcp://127.0.0.1:{30001+2*i}','--duration',f'{duration}s','--request-interval-us',round(batch/rate*1e6)],f'sink-{i}',radio_pin(i)) for i in range(ports)]
    # Low-frequency process/thread evidence, outside the producer's timing path.
    with (d/'cpu.txt').open('w') as f:
     for _ in range(5):
      sp.run(['ps','-eLo','pid,tid,psr,pcpu,stat,comm'],stdout=f); time.sleep(2)
    for p in sinks: p.wait(timeout=20)
    broker.wait(timeout=240 if a.nsys else 35)
    for p in procs: p.wait(timeout=20)
    import re
    ratios=[]
    for i in range(ports):
     t=(d/f'sink-{i}.log').read_text(); m=re.search(r'samples_received=(\d+)',t)
     ratios.append(int(m[1])/(rate*duration) if m else None)
    result=dict(label=label,ues_per_cell=n,cells=c,bandwidth_mhz=bw,gnb_antennas=g,ue_antennas=u,derived_sample_rate_hz=rate,batch_samples=batch,duration_s=duration,trace=trace,ratios=ratios,returncodes=[p.returncode for p in procs],broker_rc=broker.returncode,broker_cpus='15-16' if a.live_budget else '5-14',spin=env['OCG_BROKER_SPIN'],io_threads=env['OCG_ZMQ_IO_THREADS'])
    (d/'result.json').write_text(json.dumps(result,indent=2)); print('END',label,min(x or 0 for x in ratios),'rc',broker.returncode,flush=True)
   finally:
    for p in procs:
     if p.poll() is None: os.killpg(p.pid,signal.SIGTERM)
    for p in procs:
     try:p.wait(timeout=5)
     except sp.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
    for f in files:f.close()
