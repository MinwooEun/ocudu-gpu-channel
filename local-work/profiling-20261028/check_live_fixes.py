"""Paired single-policy live trials, reusing identical immutable channel/traffic bundles."""
import argparse,json,os,pathlib,subprocess as sp,time,signal,hashlib
P=pathlib.Path('/workspace/gpuch/profile-20261028'); OUT=P/'fixes'
FROZEN=pathlib.Path('/workspace/ocudu-spark-ranb/results/single-cell-scheduler-benchmark/tagged-profile1028-u16-20261028T083551Z-g165')/'bundle'
ap=argparse.ArgumentParser();ap.add_argument('cases',nargs='*',default=['baseline','sleep','poll10','broker4','ue5big']);a=ap.parse_args()
template=json.loads((P/'live/cuda-u16-c1-bw20-a1x1-control/launch.json').read_text())['env']
cases={
 'baseline':{},
 'sleep':{'OCG_BROKER_SPIN':'0'},
 'poll10':{'OCG_BROKER_SPIN':'0','OCG_BROKER_POLL_US':'10'},
 'broker4':{'OCG_BROKER_SPIN':'0','OCG_ZMQ_IO_THREADS':'4','SINGLE_CELL_CPUS_GNB':'5-7,10-12','SINGLE_CELL_CPUS_BROKER':'8-9,15-16'},
 'ue5big':{'OCG_BROKER_SPIN':'0','SINGLE_CELL_CPUS_GNB':'5-7,10-14','SINGLE_CELL_CPUS_UES':'8-9,17-19',**{f'SINGLE_CELL_CPUS_UE{i}':str([8,9,17,18,19][i%5]) for i in range(16)}}
}
cases['ue5big-shared']={'OCG_BROKER_SPIN':'0','SINGLE_CELL_CPUS_GNB':'5-7,10-14','SINGLE_CELL_CPUS_UES':'8-9,17-19',**{f'SINGLE_CELL_CPUS_UE{i}':'8-9,17-19' for i in range(16)}}
cases['cuda-blocking-poll10']={'OCG_BROKER_SPIN':'0','OCG_BROKER_POLL_US':'10','OCG_CUDA_BLOCKING_SYNC':'1','OCUDU_NATIVE_CHANNEL_BUILD':str(P/'build-blocking-sync')}
cases['cuda-blocking-sleep']={'OCG_BROKER_SPIN':'0','OCG_CUDA_BLOCKING_SYNC':'1','OCUDU_NATIVE_CHANNEL_BUILD':str(P/'build-blocking-sync')}
cases['broker4-spin']={**cases['broker4'],'OCG_BROKER_SPIN':'2'}
cases['ue5big-spin']={**cases['ue5big'],'OCG_BROKER_SPIN':'2'}
cases['baseline-repeat'] = dict(cases['baseline'])
cases['ue5big-spin-repeat'] = dict(cases['ue5big-spin'])
OUT.mkdir(exist_ok=True)
for name in a.cases:
 d=OUT/name
 if (d/'result.json').exists():continue
 if sp.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip():raise RuntimeError('GPU occupied before '+name)
 d.mkdir(exist_ok=True)
 env=dict(os.environ,**template);env.update(LD_LIBRARY_PATH='/usr/local/cuda/lib64',PATH='/usr/local/cuda/bin:'+os.environ['PATH'],OCUDU_NATIVE_ROOT='/workspace/ocudu-spark-ranb',OCUDU_NATIVE_SIONNA_PYTHON='/workspace/sionna-venv/bin/python');env.update(cases[name])
 for key in ('OCG_PROFILE_DIR','OCG_HOP_TRACE_DIR','OCG_BROKER_POLL_US','CUDA_MPS_PIPE_DIRECTORY','CUDA_MPS_LOG_DIRECTORY'):
  if key not in cases[name]:env.pop(key,None)
 cmd=['python3','scripts/cuda/with-cuda-mps.py','--','bash','use_cases/ran_benchmark/run-single-cell-policy.sh',
      '--run-root',str(d/'runtime'),'--scenario',str(FROZEN/'scenario.json'),'--channel-bundle',str(FROZEN/'channel'),'--traffic-bundle',str(FROZEN/'traffic'),
      '--policy','rr','--link-adaptation','harq_olla','--ue-count','16','--profile','mixed','--seed','20261016','--attach-timeout','240',
      '--awgn-snr-db','40','--tx-power-ul','300','--gnb-rx-gain','-55','--warmup-seconds','10','--channel-build',env.get('OCUDU_NATIVE_CHANNEL_BUILD',str(P/'build'))]
 metadata=dict(case=name,changes=cases[name],command=cmd,env={k:v for k,v in env.items() if k.startswith(('OC','SINGLE'))},
   frozen_bundle=str(FROZEN),input_hashes={str(f.relative_to(FROZEN)):hashlib.sha256(f.read_bytes()).hexdigest() for f in FROZEN.glob('*/manifest.json')})
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
