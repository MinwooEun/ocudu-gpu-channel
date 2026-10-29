import json,os,pathlib,signal,subprocess as sp,time,re
P=pathlib.Path('/workspace/gpuch/profile-20261028');B=P/'build';DUR=15
sp.run(['python3',str(P/'boundary.py'),'--matched'],check=True)
sp.run(['python3',str(P/'boundary.py'),'--io4'],check=True)
sp.run(['python3',str(P/'boundary.py'),'--live-budget'],check=True)
for cells in (2,4):
 for rep in (0,1):
  d=P/'multi-broker'/f'c{cells}-u4-bw20-r{rep}';d.mkdir(parents=True,exist_ok=True)
  if (d/'result.json').exists():continue
  if sp.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip():raise RuntimeError('GPU occupied')
  print('START',d.name,flush=True);procs=[];files=[];sinks=[];brokers=[]
  env=dict(os.environ,LD_LIBRARY_PATH='/usr/local/cuda/lib64',OCG_BROKER_SPIN='0',OCG_ZMQ_IO_THREADS='2')
  (d/'trace').mkdir(exist_ok=True);env['OCG_PROFILE_DIR']=str(d/'trace')
  def launch(cmd,name,pin):
   f=(d/(name+'.log')).open('w');files.append(f);p=sp.Popen(['taskset','-c',pin]+list(map(str,cmd)),env=env,stdout=f,stderr=sp.STDOUT,start_new_session=True);procs.append(p);return p
  try:
   for c in range(cells):
    y=d/f'c{c}.yaml';base=32000+100*c
    sp.run(['python3','/workspace/gpuch/bound/gen.py','--ues','4','--base-port',str(base),'--out',str(y)],check=True,stdout=(d/f'gen-{c}.log').open('w'))
    for i in range(5):launch([B/'ocudu-zmq-source','--endpoint',f'tcp://127.0.0.1:{base+2*i}','--batch-samples','23040','--duration',f'{DUR+12}s'],f'c{c}-source-{i}','15-19')
   time.sleep(1)
   for c in range(cells):brokers.append(launch([B/'ocudu-gpu-channel','--config',d/f'c{c}.yaml','--duration',f'{DUR+5}s'],f'c{c}-broker','5-14'))
   time.sleep(1)
   for c in range(cells):
    for i in range(5):sinks.append(launch([B/'ocudu-zmq-sink','--endpoint',f'tcp://127.0.0.1:{32001+100*c+2*i}','--duration',f'{DUR}s','--request-interval-us','1000'],f'c{c}-sink-{i}','15-19'))
   for p in sinks:p.wait(timeout=DUR+20)
   for p in procs:p.wait(timeout=20)
   ratios=[]
   for f in sorted(d.glob('*-sink-*.log')):
    m=re.search(r'samples_received=(\d+)',f.read_text());ratios.append(int(m[1])/(23040000*DUR) if m else None)
   (d/'result.json').write_text(json.dumps(dict(cells=cells,broker_processes=cells,ues_per_cell=4,bandwidth_mhz=20,mps=False,ratios=ratios,broker_rc=[p.returncode for p in brokers]),indent=2));print('END',d.name,min(x or 0 for x in ratios),flush=True)
  finally:
   for p in procs:
    if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
   for p in procs:
    try:p.wait(timeout=5)
    except sp.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
   for f in files:f.close()
