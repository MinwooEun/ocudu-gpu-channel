"""Frozen Spark-input live-stack UE sweep on RTX; all system operations isolated."""
import pathlib,subprocess as sp,os,json,time,hashlib,shutil,signal,sys
E=pathlib.Path(__file__).parent;W=pathlib.Path('/home/minwoo/ocudu-work/rtx-scaling-20261102');N=pathlib.Path('/home/minwoo/ocudu-work/ocudu-native-workspace');PY='/home/minwoo/ocudu-work/venvs/robot/bin/python'
busy=sp.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip();assert not busy,('GPU occupied',busy)
n=int(sys.argv[1]);tag=sys.argv[2] if len(sys.argv)>2 else 'on-r1';d=W/f'u{n}-{tag}';d.mkdir();ram=pathlib.Path('/dev/shm/ocg-rtx-scaling-20261102');ram.mkdir(exist_ok=True);wire=ram/'wire';wire.mkdir();pace=ram/'pacing';pace.mkdir();(W/'active-wire').symlink_to(wire)
bundle={1:'tagged-profile1028-u1-20261028T075717Z-g160',4:'tagged-profile1028-u4-20261028T080002Z-g161',8:'tagged-cd10-8ue-20261026T124334Z-g120',16:'tagged-cd10-16ue-20261026T124817Z-g121'}[n];f=W/'bundles'/bundle/'bundle'
gnb=W/'gnb-build/gnb';ue=W/'ue-matched-build/srsue/src/srsue';broker=W/'channel-build/ocudu-gpu-channel'
env=dict(os.environ,PYTHONPATH=str(W/'python-deps'),GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=str(N/'src/ocudu'),PATH='/usr/local/cuda-13.0/bin:/usr/bin:/bin',LD_LIBRARY_PATH=':'.join(map(str,[W/'cuda12/nvidia/cuda_runtime/lib',W/'cuda12/nvidia/cuda_nvrtc/lib',E,W/'ue-matched-build/lib/src/phy/rf',N/'builds/srsran4g-zmq-release/lib/src/phy/rf','/usr/local/cuda-13.0/lib64'])),OCUDU_NATIVE_ROOT=str(N),OCUDU_NATIVE_PLATFORM='none',OCUDU_NATIVE_SIONNA_PYTHON=PY,OCUDU_NATIVE_CHANNEL_BUILD=str(W/'pipe-build'),SINGLE_CELL_GNB_BINARY=str(gnb),SINGLE_CELL_UE_BINARY=str(ue),SINGLE_CELL_GNB_ACCELERATION='all',SINGLE_CELL_MPS='on',SINGLE_CELL_BROKER_IN_MPS='1',SINGLE_CELL_GNB_START_TIMEOUT='150',SINGLE_CELL_UE_RX_SLEEP='false',SINGLE_CELL_QUIET_LOGS='1',SINGLE_CELL_PCAP='off',SINGLE_CELL_GNB_SEPARATE_RADIO='0' if tag.startswith('off') else '1',SINGLE_CELL_CPUS_GNB='0-7',SINGLE_CELL_CPUS_BROKER='8-9',SINGLE_CELL_CPUS_UES='10-19',SINGLE_CELL_CPUS_AUX='20-23',SINGLE_CELL_GNB_RU_CPUS='1',SINGLE_CELL_GNB_MAIN_POOL_CPUS='0,2-7',OCG_BROKER_SPIN='0',OCG_BROKER_CV_REP='1',OCG_BROKER_POLL_US='10',OCG_ZMQ_IO_THREADS='2',SINGLE_CELL_BROKER_ENV='0',OCG_RATE_TRACE_DIR=str(pace),OCG_WIRE_TRACE_DIR=str(wire),OCG_LOG_PIPE_META=str(d/'log-pipe.json'),LD_PRELOAD=str(W/'wire.so'))
if tag.startswith('pbroker'):
 env.update(SINGLE_CELL_CPUS_GNB='0-5,8-9',SINGLE_CELL_CPUS_BROKER='6-7',SINGLE_CELL_GNB_MAIN_POOL_CPUS='0,2-5,8-9')
# Keep one UE pinned to one E-core; above ten UEs share the same fixed budget.
for i in range(n):env[f'SINGLE_CELL_CPUS_UE{i}']=str(10+i%10)
if tag.startswith('off'):
 env.pop('SINGLE_CELL_GNB_RU_CPUS');env.pop('SINGLE_CELL_GNB_MAIN_POOL_CPUS')
cmd=['/usr/bin/python3','scripts/cuda/with-cuda-mps.py','--','bash','use_cases/ran_benchmark/run-single-cell-policy.sh','--run-root',str(d/'runtime'),'--scenario',str(f/'scenario.json'),'--channel-bundle',str(f/'channel'),'--traffic-bundle',str(f/'traffic'),'--policy','rr','--link-adaptation','harq_olla','--ue-count',str(n),'--profile','mixed','--seed','20261016','--attach-timeout','240','--awgn-snr-db','40','--tx-power-ul','300','--gnb-rx-gain','-55','--warmup-seconds','10','--channel-build',str(W/'pipe-build')]
meta=dict(ue_count=n,tag=tag,command=cmd,env={k:v for k,v in env.items() if k.startswith(('OC','SINGLE','LD_'))},binary_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [gnb,ue,broker,W/'wire.so',W/'ue-matched-build/lib/src/phy/rf/libsrsran_rf_zmq.so.23.04.0']},frozen_input_hashes={str(p.relative_to(f)):hashlib.sha256(p.read_bytes()).hexdigest() for p in f.rglob('*') if p.is_file()},started_unix_ns=time.time_ns(),started_mono_ns=time.monotonic_ns(),cpu_mapping=('gNB P0-5+E8-9; broker P6-7; CPU UEs E10-19; auxiliary E20-23; same role core counts' if tag.startswith('pbroker') else 'gNB P0-7; broker E8-9; CPU UEs E10-19; auxiliary E20-23; fixed allocation across UE sweep'),execution='dedicated privileged container, host filesystem tools, separate net/mount namespace; root user namespace omitted')
(d/'launch.json').write_text(json.dumps(meta,indent=2));print('START',n,tag,flush=True)
with (d/'priorities.log').open('w') as log:prio=sp.Popen(['/usr/bin/python3',str(E/'priorities.py'),str(d),str(n)],stdout=log,stderr=sp.STDOUT)
audit=sp.Popen(['/usr/bin/python3',str(E/'audit.py'),str(d)])
start=time.monotonic()
try:
 with (d/'runner.log').open('w') as log:
  proc=sp.Popen(cmd,cwd=W/'ranb',env=env,stdout=log,stderr=sp.STDOUT,start_new_session=True)
  try:rc=proc.wait(timeout=750)
  except sp.TimeoutExpired:
   os.killpg(proc.pid,signal.SIGTERM)
   try:rc=proc.wait(timeout=30)
   except sp.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);rc=proc.wait()
 if prio.poll() is None:
  try:prio.wait(timeout=3)
  except sp.TimeoutExpired:prio.terminate();prio.wait()
 r=d/'runtime/report/run-report.json';report=json.loads(r.read_text()) if r.exists() else None
 result=dict(ue_count=n,tag=tag,returncode=rc,wall_seconds=time.monotonic()-start,priorities_returncode=prio.returncode,report=report)
 (d/'result.json').write_text(json.dumps(result,indent=2));print('END',n,tag,rc,'report',bool(report),'priorities',prio.returncode,flush=True)
finally:
 if prio.poll() is None:prio.terminate();prio.wait()
 audit.wait(timeout=10)
 (W/'active-wire').unlink();shutil.move(str(ram),d/'raw')

if rc:raise SystemExit(rc)
