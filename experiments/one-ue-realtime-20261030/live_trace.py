"""Frozen PR10 CUDA gNB and repaired CPU srsUE: residual rate diagnostics."""
import argparse,hashlib,json,os,pathlib,signal,subprocess as sp,time
P=pathlib.Path('/workspace/gpuch/profile-20261028');BASE=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030')
ap=argparse.ArgumentParser();ap.add_argument('cases',nargs='+',choices=['original','original-profile']);ap.add_argument('--ues',type=int,choices=[1,4,8,16],default=16);ap.add_argument('--tag',default='r1');a=ap.parse_args()
bundle={1:'tagged-profile1028-u1-20261028T075717Z-g160',4:'tagged-profile1028-u4-20261028T080002Z-g161',8:'tagged-cd10-8ue-20261026T124334Z-g120',16:'tagged-cd10-16ue-20261026T124817Z-g121'}[a.ues]
F=pathlib.Path('/workspace/ocudu-spark-ranb/results/single-cell-scheduler-benchmark')/bundle/'bundle'
BUILD=(BASE/'pipe-build') if os.environ.get('OCG_LOG_PIPE')=='1' else ((BASE/'room-build') if os.environ.get('OCG_ROOM_PROBE')=='1' else pathlib.Path('/workspace/gpuch/realtime-rate-20261030/sparse-build'));GPU_UE=pathlib.Path('/workspace/gpuch/s4/build-s1/srsue/src/srsue');CPU_UE=pathlib.Path('/workspace/gpuch/receiver-quality-20261030/local-noise-build/srsue');GNB=pathlib.Path('/workspace/ocudu-spark/builds/d10-cuda-patched-sm121/apps/gnb/gnb')
expected={str(GNB):'ec2b1338a702f0646af07492fa65c284c945e484d399c1fbba6c58ca3b18e0be',str(GPU_UE):'b1d962efc430e4793e6241f60a4b83456004c8a12097d334d3aa0e3229fafa21',str(CPU_UE):json.loads(pathlib.Path('/workspace/gpuch/receiver-quality-20261030/local-noise-build.json').read_text())['sha256'][str(CPU_UE)],str(BUILD/'ocudu-gpu-channel'):(json.loads((BUILD/'provenance.json').read_text())['binary_sha256'])}
actual={f:hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest() for f in expected};assert actual==expected,actual
template=json.loads((P/'live/cuda-u16-c1-bw20-a1x1-control/launch.json').read_text())['env']
for case in a.cases:
 d=BASE/f'u{a.ues}'/f'{case}-{a.tag}';d.mkdir(parents=True,exist_ok=True)
 if (d/'result.json').exists():raise RuntimeError('refusing to overwrite '+str(d))
 busy=sp.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).split();allowed=os.environ.get('OCG_TEST_LEASE_PID');assert all(pid==allowed for pid in busy),('GPU occupied',busy,allowed)
 env=dict(os.environ,**template)
 for k in list(env):
  if k.startswith(('SRSRAN_','SRSUE_SLOT_TRACE','OCG_HOP_TRACE','OCG_PROFILE_DIR','OCG_BROKER_READY','OCG_BROKER_MULTIPLEX','OCG_BROKER_ASYNC','OCG_BROKER_FD','OCG_CUDA_FUSE','CUDA_MPS_PIPE','CUDA_MPS_LOG')):env.pop(k,None)
 env.update(OCG_DIAG_ZERO_NOISE='0',LD_LIBRARY_PATH='/usr/local/cuda/lib64',PATH='/usr/local/cuda/bin:'+os.environ['PATH'],OCUDU_NATIVE_ROOT='/workspace/ocudu-spark-ranb',OCUDU_NATIVE_SIONNA_PYTHON='/workspace/sionna-venv/bin/python',OCUDU_NATIVE_CHANNEL_BUILD=str(BUILD),SINGLE_CELL_GNB_BINARY=str(GNB),SINGLE_CELL_GNB_ACCELERATION='all',SINGLE_CELL_MPS='on',SINGLE_CELL_BROKER_IN_MPS='1',SINGLE_CELL_UE_BINARY=str(CPU_UE if case.startswith('original') else GPU_UE),SRSRAN_UE_DL_CUDA='0')
 if os.environ.get('OCG_BROKER_CV_REP')=='1':env['OCG_BROKER_CV_REP']='1'
 if os.environ.get('OCG_BROKER_POLL_US') is not None:env['OCG_BROKER_POLL_US']=os.environ['OCG_BROKER_POLL_US']
 if os.environ.get('OCG_TEST_SPIN') is not None:env['OCG_BROKER_SPIN']=os.environ['OCG_TEST_SPIN'];env['SINGLE_CELL_BROKER_ENV']='0'
 if os.environ.get('OCG_LOG_PIPE')=='1':env['OCG_LOG_PIPE_META']=str(d/'log-pipe.json')
 if os.environ.get('OCG_ROOM_PROBE')=='1':
  (d/'room').mkdir(exist_ok=True);env['OCG_ROOM_DIAG_DIR']=str(d/'room')
 if case.startswith('gpu'):env.update(SRSRAN_UE_DL_CUDA='all',SRSRAN_LDPC_DECODER='cuda',SRSRAN_LDPC_CUDA_SYNC='spin' if case=='gpu-spin' else 'block',SRSRAN_LDPC_CUDA_VERBOSE='1')
 pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030/wire').mkdir(parents=True,exist_ok=True);pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030/pacing').mkdir(parents=True,exist_ok=True)
 env.update(OCG_RATE_TRACE_DIR='/dev/shm/ocudu-one-ue-rt-20261030/pacing',OCG_WIRE_TRACE_DIR='/dev/shm/ocudu-one-ue-rt-20261030/wire',OCG_HOP_TRACE_DIR=str(d/'hop'),LD_PRELOAD='/workspace/gpuch/one-ue-realtime-20261030/wire-yield.so');(d/'hop').mkdir(exist_ok=True)
 if case=='original-profile':
  (d/'trace').mkdir(exist_ok=True);(d/'hop').mkdir(exist_ok=True);env.update(OCG_PROFILE_DIR=str(d/'trace'),OCG_HOP_TRACE_DIR=str(d/'hop'))
 if case.endswith('trace'):
  (d/'trace').mkdir(exist_ok=True);env['SRSUE_SLOT_TRACE_DIR']=str(d/'trace')
 cmd=['python3','scripts/cuda/with-cuda-mps.py','--','bash','use_cases/ran_benchmark/run-single-cell-policy.sh','--run-root',str(d/'runtime'),'--scenario',str(F/'scenario.json'),'--channel-bundle',str(F/'channel'),'--traffic-bundle',str(F/'traffic'),'--policy','rr','--link-adaptation','harq_olla','--ue-count',str(a.ues),'--profile','mixed','--seed','20261016','--attach-timeout','240','--awgn-snr-db','40','--tx-power-ul','300','--gnb-rx-gain','-55','--warmup-seconds','10','--channel-build',str(BUILD)]
 meta=dict(case=case,ue_count=a.ues,tag=a.tag,binary_hashes=actual,active_ue_binary=env['SINGLE_CELL_UE_BINARY'],command=cmd,environment={k:v for k,v in env.items() if k.startswith(('OC','SINGLE','SRSRAN','SRSUE_'))},frozen_bundle=str(F),input_hashes={str(f.relative_to(F)):hashlib.sha256(f.read_bytes()).hexdigest() for f in F.rglob('*') if f.is_file()},diagnostic_trace=case.endswith('trace'))
 meta['diagnostic_zero_noise']=False;meta['local_noise_candidate']=True;meta['candidate_build_provenance']=json.loads((BUILD/'provenance.json').read_text());meta['reservation_pid']=os.environ.get('OCG_TEST_LEASE_PID');meta['interposer_sha256']=hashlib.sha256(pathlib.Path(env['LD_PRELOAD']).read_bytes()).hexdigest();meta['clock_reference']={'unix_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns()};(d/'launch.json').write_text(json.dumps(meta,indent=2));print('START',a.ues,case,a.tag,flush=True);start=time.monotonic()
 with (d/'runner.log').open('w') as log:
  proc=sp.Popen(cmd,cwd=P/'ranb',env=env,stdout=log,stderr=sp.STDOUT,start_new_session=True)
  try:rc=proc.wait(timeout=750)
  except sp.TimeoutExpired:
   os.killpg(proc.pid,signal.SIGTERM)
   try:rc=proc.wait(timeout=20)
   except sp.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);rc=proc.wait()
 report=d/'runtime/report/run-report.json';gate=d/'runtime/report/gate-summary.json'
 r=json.loads(report.read_text()) if report.exists() else None;g=json.loads(gate.read_text()) if gate.exists() else None
 result=dict(case=case,ue_count=a.ues,tag=a.tag,returncode=rc,wall_s=time.monotonic()-start,metrics=r.get('runtime') if r else None,valid_segments=r.get('segments_valid') if r else None,gate=g,report_exists=bool(r),diagnostic_trace=case.endswith('trace'))
 (d/'result.json').write_text(json.dumps(result,indent=2));print('END',json.dumps(result),flush=True)
