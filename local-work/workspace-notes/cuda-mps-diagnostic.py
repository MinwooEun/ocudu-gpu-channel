#!/usr/bin/env python3
import datetime, importlib.util, json, os, pathlib, re, signal, subprocess, time
root=pathlib.Path(os.environ['OCUDU_NATIVE_ROOT']);repo=pathlib.Path(os.environ['OCUDU_REPO'])
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
out=root/'results/cuda-qualification'/('mps-'+stamp);out.mkdir(parents=True)
pipe=root/'run'/('cuda-mps-'+stamp);pipe.mkdir(parents=True)
env=dict(os.environ, CUDA_MPS_PIPE_DIRECTORY=str(pipe),CUDA_MPS_LOG_DIRECTORY=str(out),CUDA_VISIBLE_DEVICES='0',OCUDU_NATIVE_CUDA_QUALIFICATION='0')
control=['nvidia-cuda-mps-control']
def command(s):
 return subprocess.run(control,input=s+'\n',text=True,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=10).stdout
spec=importlib.util.spec_from_file_location('qualify',repo/'scripts/native/qualify-cuda-stages.py');q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
records=[]
process=None
(out/"experiment.py").write_bytes(pathlib.Path(__file__).read_bytes())
subprocess.run(control+['-d'],env=env,check=True)
try:
 time.sleep(1)
 (out/'startup.txt').write_text(command('start_server -uid '+str(os.getuid())))
 time.sleep(2)
 servers=command('get_server_list');(out/'servers.txt').write_text(servers)
 if not re.search(r'\b[1-9][0-9]*\b', servers):
  raise RuntimeError('isolated MPS server did not start; inspect server.log')
 for n,(profile,acceleration) in enumerate([('cpu','auto'),('cuda','all')]*3):
  runenv=dict(env,OCUDU_NATIVE_GNB_PROFILE=profile,OCUDU_NATIVE_GNB_ACCELERATION=acceleration,OCUDU_NATIVE_CHANNEL_MODE='legacy')
  output=out/f'{n:02d}-{profile}-{acceleration}.log'
  samples=[]
  with output.open('w') as stream:
   process=subprocess.Popen(['bash',str(repo/'scripts/native/run-ocudu-legacy-1x1.sh')],env=runenv,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
   while process.poll() is None:
    samples.append(dict(time=time.time(),clients=command('ps')))
    time.sleep(2)
  (out/f'{n:02d}-clients.json').write_text(json.dumps(samples,indent=2)+'\n')
  stamps=re.findall(r'/reports/ocudu-interop/(\d{8}T\d{6}Z)/attach-summary.json',output.read_text())
  r=dict(profile=profile,acceleration=acceleration,exit_code=process.returncode,mps_clients=str(out/f'{n:02d}-clients.json'))
  if stamps:
   try:r.update(q.extract(root,stamps[-1]))
   except (OSError,ValueError) as e:r['evidence_error']=str(e)
  records.append(r);(out/'runs.json').write_text(json.dumps(records,indent=2)+'\n')
  print(json.dumps({k:r[k] for k in ('profile','acceleration','exit_code','timestamp','p99_us') if k in r}),flush=True)
finally:
 if process is not None and process.poll() is None:
  os.killpg(process.pid,signal.SIGTERM)
  try:process.wait(timeout=45)
  except subprocess.TimeoutExpired:
   os.killpg(process.pid,signal.SIGKILL);process.wait()
 (out/'shutdown.txt').write_text(command('quit'))
print('mps_evidence='+str(out),flush=True)
