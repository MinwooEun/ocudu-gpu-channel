"""Paired single-policy live trials, reusing identical immutable channel/traffic bundles."""
import argparse,json,os,pathlib,subprocess as sp,time,signal,hashlib
P=pathlib.Path('/workspace/gpuch/profile-20261028'); OUT=pathlib.Path('/workspace/gpuch/profile-20261029-deep/runs')
FROZEN=pathlib.Path('/workspace/ocudu-spark-ranb/results/single-cell-scheduler-benchmark/tagged-cd10-16ue-20261026T124817Z-g121')/'bundle'
ap=argparse.ArgumentParser();ap.add_argument('cases',nargs='*',default=['baseline','sleep','poll10','broker4','ue5big']);a=ap.parse_args()
template=json.loads((P/'live/cuda-u16-c1-bw20-a1x1-control/launch.json').read_text())['env']
Q=pathlib.Path('/workspace/gpuch/profile-20261029-causal')
cases={'baseline':{},'baseline-repeat':{},'trace':{'SINGLE_CELL_GNB_BINARY':str(Q/'gnb-instrumented/gnb')},'trace-repeat':{'SINGLE_CELL_GNB_BINARY':str(Q/'gnb-instrumented/gnb'),'OCUDU_NATIVE_CHANNEL_BUILD':str(Q/'broker-cpu-trace')},'notify':{'SINGLE_CELL_GNB_BINARY':str(Q/'gnb-instrumented/gnb'),'OCUDU_NATIVE_CHANNEL_BUILD':str(Q/'broker-probe'),'OCG_CAUSAL_REP_NOTIFY':'1','OCG_CAUSAL_PRODUCER_NOTIFY':'1'},'notify-control':{'OCUDU_NATIVE_CHANNEL_BUILD':str(Q/'broker-probe'),'OCG_CAUSAL_REP_NOTIFY':'1','OCG_CAUSAL_PRODUCER_NOTIFY':'1'}}
cases['notify-all-control']={'OCUDU_NATIVE_CHANNEL_BUILD':str(Q/'broker-all-notify'),'OCG_CAUSAL_REP_NOTIFY':'1','OCG_CAUSAL_PRODUCER_NOTIFY':'1','OCG_CAUSAL_ROOM_NOTIFY':'1'}
cases['deep16']={'SINGLE_CELL_GNB_BINARY':str(Q/'gnb-instrumented/gnb'),'OCUDU_NATIVE_CHANNEL_BUILD':'/workspace/gpuch/profile-20261029-deep/broker-deep','OCG_DEEP_GATE':'/workspace/gpuch/profile-20261029-deep/capture.gate'}
cases['deep16-yield']={**cases['deep16'],'OCUDU_NATIVE_CHANNEL_BUILD':'/workspace/gpuch/profile-20261029-deep/broker-deep-yield','OCG_DEEP_GATE':'/workspace/gpuch/profile-20261029-deep/capture-yield.gate'}
cases['deep8-yield']={**cases['deep16-yield'],'OCG_DEEP_GATE':'/workspace/gpuch/profile-20261029-deep/capture-eight.gate'}
cases['deep16-cpu7']={**cases['deep16-yield'],'SINGLE_CELL_CPUS_BROKER':'0-4,15-16','OCG_DEEP_GATE':'/workspace/gpuch/profile-20261029-deep/capture-cpu7.gate'}
OUT.mkdir(exist_ok=True)
for name in a.cases:
 N=8 if name=='deep8-yield' else 16
 FROZEN=pathlib.Path('/workspace/ocudu-spark-ranb/results/single-cell-scheduler-benchmark/'+('tagged-cd10-8ue-20261026T124334Z-g120' if N==8 else 'tagged-cd10-16ue-20261026T124817Z-g121'))/'bundle'
 d=OUT/name
 if (d/'result.json').exists():continue
 if sp.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip():raise RuntimeError('GPU occupied before '+name)
 d.mkdir(exist_ok=True)
 env=dict(os.environ,**template);env.update(LD_LIBRARY_PATH='/usr/local/cuda/lib64',PATH='/usr/local/cuda/bin:'+os.environ['PATH'],OCUDU_NATIVE_ROOT='/workspace/ocudu-spark-ranb',OCUDU_NATIVE_SIONNA_PYTHON='/workspace/sionna-venv/bin/python');env.update(cases[name])
 for key in ('OCG_PROFILE_DIR','OCG_HOP_TRACE_DIR','OCG_BROKER_POLL_US','CUDA_MPS_PIPE_DIRECTORY','CUDA_MPS_LOG_DIRECTORY'):
  if key not in cases[name]:env.pop(key,None)
 if name in ('trace','trace-repeat','notify','deep16','deep16-yield','deep8-yield','deep16-cpu7'):
  for sub in ('wire','hop','trace'):(d/sub).mkdir(exist_ok=True)
  env.update(LD_PRELOAD=str(Q/'wire_trace-v2.so'),OCG_WIRE_TRACE_DIR=str(d/'wire'),OCG_HOP_TRACE_DIR=str(d/'hop'),OCG_PROFILE_DIR=str(d/'trace'))
 cmd=['python3','scripts/cuda/with-cuda-mps.py','--','bash','use_cases/ran_benchmark/run-single-cell-policy.sh',
      '--run-root',str(d/'runtime'),'--scenario',str(FROZEN/'scenario.json'),'--channel-bundle',str(FROZEN/'channel'),'--traffic-bundle',str(FROZEN/'traffic'),
      '--policy','rr','--link-adaptation','harq_olla','--ue-count',str(N),'--profile','mixed','--seed','20261016','--attach-timeout','240',
      '--awgn-snr-db','40','--tx-power-ul','300','--gnb-rx-gain','-55','--warmup-seconds','10','--channel-build',env.get('OCUDU_NATIVE_CHANNEL_BUILD',str(P/'build'))]
 metadata=dict(case=name,changes=cases[name],command=cmd,env={k:v for k,v in env.items() if k.startswith(('OC','SINGLE'))},
   frozen_bundle=str(FROZEN),input_hashes={str(f.relative_to(FROZEN)):hashlib.sha256(f.read_bytes()).hexdigest() for f in FROZEN.rglob('*') if f.is_file()})
 (d/'launch.json').write_text(json.dumps(metadata,indent=2));print('START',name,flush=True);start=time.monotonic()
 with (d/'runner.log').open('w') as log:
  p=sp.Popen(cmd,cwd=P/'ranb',env=env,stdout=log,stderr=sp.STDOUT,start_new_session=True)
  try:rc=p.wait(timeout=650)
  except sp.TimeoutExpired:
   os.killpg(p.pid,signal.SIGTERM)
   try:rc=p.wait(timeout=20)
   except sp.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);rc=p.wait()
 report=d/'runtime/report/run-report.json';gate=d/'runtime/report/gate-summary.json'
 r=json.loads(report.read_text()) if report.exists() else None;g=json.loads(gate.read_text()) if gate.exists() else None
 result=dict(case=name,returncode=rc,wall_s=time.monotonic()-start,metrics=r.get('runtime') if r else None,
             valid_segments=r.get('segments_valid') if r else None,gate=g,report_exists=bool(r))
 (d/'result.json').write_text(json.dumps(result,indent=2));print('END',name,'rc',rc,'ratio',result['metrics'].get('real_time_ratio') if result['metrics'] else None,'valid_segments',result['valid_segments'],'gate',g.get('status') if g else None,flush=True)
