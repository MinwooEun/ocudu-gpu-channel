"""Same channel backend/topology, with or without raw cf32 REQ/REP transport."""
import pathlib,subprocess as sp,os,sys,json,time,signal,csv,hashlib,threading,math
W=pathlib.Path(__file__).resolve().parent
HOST=os.environ.get('BOUND_HOST','spark' if str(W).startswith('/workspace') else 'rtx')
PROBE_ENABLED=os.environ.get('BOUND_COUNTERS','1')=='1'
IQ_NAME=os.environ.get('BOUND_IQ_BINARY','iq-capacity')
PROFILE=os.environ.get('BOUND_PROFILE','matched-five-fast-cores')
BROKER_CPUS=os.environ.get('BOUND_CHANNEL_CPUS', '5-9' if HOST=='spark' else '0-4');PEER_CPUS='15-19' if HOST=='spark' else '5-19';AUX_CPUS='0-4' if HOST=='spark' else '20-23'
def cpus(s):
 out=set()
 for x in s.split(','):
  a=x.split('-');out.update(range(int(a[0]),int(a[-1])+1))
 return out
os.sched_setaffinity(0,cpus(AUX_CPUS))
BW={20:(23040000,15),50:(61440000,15),100:(122880000,30)}
def parse_rows(path,kind):
 lines=path.read_text().splitlines();header=next((l for l in lines if l.startswith(kind+',id,')),None)
 return list(csv.DictReader([header]+[l for l in lines if l.startswith(kind+',') and l!=header])) if header else []
def run_case(mode,n=1,c=1,bw=20,a=1,rep=1,warmup=2,measure=8):
 label=f'{mode}-u{n}-c{c}-bw{bw}-a{a}x{a}-r{rep}'+('' if PROFILE=='matched-five-fast-cores' else '-'+PROFILE);d=W/'cases'/label
 if (d/'result.json').exists():return json.loads((d/'result.json').read_text())
 busy=sp.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip();assert not busy,('GPU occupied',busy)
 d.mkdir(parents=True,exist_ok=True);(d/'counters').mkdir(exist_ok=True)
 rate,scs=BW[bw];batch=rate*15//scs//1000;period=batch*1000000000//rate;config=d/'topology.yaml'
 sp.run([sys.executable,str(W/'gen.py'),'--ues',str(n),'--cells',str(c),'--gnb-ports',str(a),'--ue-ports',str(a),'--srate-hz',str(rate),'--scs-khz',str(scs),'--base-port','30000','--out',str(config)],check=True,stdout=sp.DEVNULL)
 nodes=[];port=30000
 for cell in range(c):
  nodes.append(dict(id=f'gnb{cell}',base=port,ports=a));port+=2*a
  for u in range(n):nodes.append(dict(id=f'c{cell}ue{u}' if c>1 else f'ue{u}',base=port,ports=a));port+=2*a
 env=dict(os.environ,LD_LIBRARY_PATH='/usr/local/cuda/lib64',PATH='/usr/local/cuda/bin:/usr/bin:/bin',OCG_BROKER_CV_REP='1',OCG_BROKER_SPIN='0',OCG_BROKER_POLL_US='10',OCG_ZMQ_IO_THREADS='2',OCG_WINDOW_EPOCH_FILE=str(d/'epoch.txt'),OCG_COUNTER_DIR=str(d/'counters'),OCG_WINDOW_NS=str(measure*1000000000))
 if not PROBE_ENABLED:
  env.pop('OCG_COUNTER_DIR',None);env.pop('OCG_WINDOW_EPOCH_FILE',None);env.pop('OCG_WINDOW_NS',None)
 for k in ['LD_PRELOAD','OCG_PROFILE_DIR','OCG_HOP_TRACE_DIR','OCG_RATE_TRACE_DIR','OCG_ROOM_DIAG_DIR','CUDA_MPS_PIPE_DIRECTORY','CUDA_MPS_LOG_DIRECTORY']:env.pop(k,None)
 meta=dict(label=label,host=HOST,mode=mode,resource_profile=PROFILE,counters_enabled=PROBE_ENABLED,ues_per_cell=n,cells=c,bandwidth_mhz=bw,sample_rate_hz=rate,ports=a,batch_samples=batch,period_ns=period,taps=8,channel='static deterministic8-tap TDL, AWGN per receiver; independent cells; no channel-control replay',warmup_seconds=warmup,measure_seconds=measure,cpus=dict(channel=BROKER_CPUS,peers=PEER_CPUS,auxiliary=AUX_CPUS),nodes=nodes,config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),binary_sha256={x:hashlib.sha256((W/x).read_bytes()).hexdigest() for x in [IQ_NAME,'ocudu-gpu-channel','radio-peer']},started_unix_ns=time.time_ns())
 (d/'launch.json').write_text(json.dumps(meta,indent=2));print('START',HOST,label,flush=True);procs=[];files=[];drainer=None;cpu=[];start=time.monotonic();result=None
 def launch(cmd,name,pin,pipe=False):
  f=(d/(name+'.log')).open('wb');files.append(f)
  p=sp.Popen(['taskset','-c',pin]+list(map(str,cmd)),env=env,stdout=sp.PIPE if pipe else f,stderr=f,start_new_session=True);procs.append(p)
  return p,f
 def sample():
  snapshot={}
  for p in procs:
   try:
    v=pathlib.Path('/proc',str(p.pid),'stat').read_text().rsplit(')',1)[1].split();snapshot[str(p.pid)]=dict(utime=int(v[11]),stime=int(v[12]),comm=pathlib.Path('/proc',str(p.pid),'comm').read_text().strip(),cpus=sorted(os.sched_getaffinity(p.pid)))
   except (FileNotFoundError,ProcessLookupError):pass
  cpu.append(dict(time_ns=time.monotonic_ns(),pids=snapshot))
 try:
  if mode=='iq':
   p,_=launch([W/IQ_NAME,config,warmup,measure],'iq',BROKER_CPUS)
   deadline=time.monotonic()+120
   while p.poll() is None:
    sample()
    if time.monotonic()>deadline:raise TimeoutError('IQ harness')
    time.sleep(.5)
   rows=parse_rows(d/'iq.log','node');ready_epoch=next((int(l.split(',')[1]) for l in (d/'iq.log').read_text().splitlines() if l.startswith('measurement_start_ns,')),0);initialized=(all(0<int(x.get('initialized_ns',0))<ready_epoch for x in rows) if IQ_NAME=='iq-capacity-ready' else None);counts=[int(x['count']) for x in rows];ratios=[float(x['coverage_ratio']) for x in rows];endpoint=[float(x['endpoint_ratio']) for x in rows];health=p.returncode==0 and len(rows)==len(nodes) and all(x['finite']=='1' for x in rows) and initialized is not False;deadline_clean=all(int(x['late_completions'])==0 for x in rows)
   details=dict(nodes=rows,all_workers_initialized_before_measurement=initialized,pacing='absolute cadence, unbounded catch-up; cached read-only source IQ',strict_measured_deadline_clean=deadline_clean)
  else:
   peers=[]
   for node in nodes:
    p,_=launch([W/'radio-peer',node['id'],node['base'],a,batch,d/'epoch.txt',d/(node['id']+'.ready'),measure],node['id'],PEER_CPUS);peers.append(p)
   deadline=time.monotonic()+60
   while not all((d/(x['id']+'.ready')).exists() for x in nodes):
    if any(p.poll() is not None for p in peers):raise RuntimeError('peer startup failure')
    if time.monotonic()>deadline:raise TimeoutError('peer readiness')
    time.sleep(.05)
   broker,log=launch(['stdbuf','-oL','-eL',W/'ocudu-gpu-channel','--config',config,'--duration','0s'],'broker',BROKER_CPUS,True)
   def drain():
    while True:
     chunk=os.read(broker.stdout.fileno(),65536)
     if not chunk:break
     log.write(chunk);log.flush()
   drainer=threading.Thread(target=drain);drainer.start();deadline=time.monotonic()+90
   while not any(line.startswith('event=cpu_stage_timings ') for line in (d/'broker.log').read_text(errors='replace').splitlines()):
    if broker.poll() is not None:raise RuntimeError('broker startup failure')
    if time.monotonic()>deadline:raise TimeoutError('broker not producing IQ')
    time.sleep(.1)
   begin=time.monotonic_ns()+warmup*1000000000;(d/'epoch.tmp').write_text(str(begin)+'\n');(d/'epoch.tmp').replace(d/'epoch.txt')
   finish=begin+measure*1000000000
   while time.monotonic_ns()<finish:
    if broker.poll() is not None:raise RuntimeError('broker stopped during measurement')
    sample();time.sleep(.25)
   os.killpg(broker.pid,signal.SIGTERM);broker.wait(timeout=15);drainer.join(timeout=5)
   for p in peers:
    if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
   for p in peers:p.wait(timeout=5)
   rows=[]
   for node in nodes:rows+=parse_rows(d/(node['id']+'.log'),'port')
   counts=[int(x['measure_samples'])//batch for x in rows];ratios=[int(x['measure_samples'])/(rate*measure) for x in rows];endpoint=[(int(x['measure_samples'])-batch)*1000000000/(rate*(int(x['last_ns'])-int(x['first_ns']))) if int(x['last_ns'])>int(x['first_ns']) else 0 for x in rows]
   counters=[list(csv.DictReader(f.open()))[0] for f in sorted((d/'counters').glob('*.csv'))]
   health=broker.returncode==0 and len(rows)==len(nodes)*a and (len(counters)==len(nodes) if PROBE_ENABLED else True) and all(p.returncode==0 for p in peers) and all(int(x['errors'])==0 and int(x['malformed'])==0 for x in rows)
   deadline_clean=(len(counters)==len(nodes) and all(int(x['rebases'])==0 and int(x['process_over_budget'])==0 for x in counters)) if PROBE_ENABLED else None
   stop=[x for x in (d/'broker.log').read_text().splitlines() if x.startswith(('event=stop ','event=relay_wedged '))]
   details=dict(ports=rows,producer_counters=counters,broker_stop=stop,pacing='same live broker bounded catch-up; synthetic peers have no extra rate limit',strict_measured_deadline_clean=deadline_clean,measurement_start_ns=begin,measurement_end_ns=finish)
  target=math.floor(measure*1000000000/period);covered=health and bool(counts) and min(counts)>=target-1
  result=dict(**{k:meta[k] for k in ['label','host','mode','ues_per_cell','cells','bandwidth_mhz','sample_rate_hz','ports','period_ns','warmup_seconds','measure_seconds','config_sha256']},health=health,expected_batches=target,min_completed_batches=min(counts) if counts else 0,min_coverage=min(ratios) if ratios else 0,min_endpoint_ratio=min(endpoint) if endpoint else 0,cadence_covered_with_one_boundary_batch=covered,strict_deadline_clean=health and deadline_clean,wall_s=time.monotonic()-start,returncodes=[p.returncode for p in procs],details=details)
 except Exception as e:
  result=dict(label=label,host=HOST,mode=mode,ues_per_cell=n,cells=c,bandwidth_mhz=bw,ports=a,health=False,error=repr(e),wall_s=time.monotonic()-start,cadence_covered_with_one_boundary_batch=False,strict_deadline_clean=False,min_coverage=0)
 finally:
  for p in procs:
   if p.poll() is None:
    try:os.killpg(p.pid,signal.SIGTERM)
    except ProcessLookupError:pass
  for p in procs:
   try:p.wait(timeout=8)
   except sp.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
  if drainer:drainer.join(timeout=3)
  for f in files:f.close()
  (d/'cpu.json').write_text(json.dumps(dict(clock_ticks=os.sysconf('SC_CLK_TCK'),samples=cpu),indent=2))
  if result is not None:(d/'result.json').write_text(json.dumps(result,indent=2))
 print('END',HOST,label,'coverage',result.get('min_coverage'),'cadence',result.get('cadence_covered_with_one_boundary_batch'),'health',result.get('health'),result.get('error',''),flush=True)
 return result
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['iq','radio']);p.add_argument('--ues',type=int,default=1);p.add_argument('--cells',type=int,default=1);p.add_argument('--bw',type=int,default=20);p.add_argument('--ports',type=int,default=1);p.add_argument('--rep',type=int,default=1);p.add_argument('--warmup',type=int,default=2);p.add_argument('--measure',type=int,default=8);a=p.parse_args();r=run_case(a.mode,a.ues,a.cells,a.bw,a.ports,a.rep,a.warmup,a.measure);raise SystemExit(0 if r['health'] else 1)
