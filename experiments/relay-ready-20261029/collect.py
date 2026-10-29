"""Read on Spark; emit a compact evidence bundle without copying IQ/log payloads."""
import hashlib,json,pathlib
P=pathlib.Path('/workspace/gpuch/relay-ready-20261029')
result={'schema':'relay-readiness-experiment-v1','cases':{},'cases_8ue':{},'checks':{},'binaries':{},
 'excluded':{'live/*':'Missing sample-indexed controls; link_clock rejected before measurement.',
             'live-pr10/legacy':'A separate build overlapped this first restored-control run.',
             'live-pr10/fd-profile':'Instrumented CPU diagnostic, excluded from clean speed comparisons.',
             'live-pr10/fuse-control':'Relay wedged; measurement did not complete.',
             'live-pr10/fuse-control-repeat':'Relay wedged; measurement did not complete.'}}
for subdir,key in [('live-pr10','cases'),('live-pr10-8ue','cases_8ue')]:
 if not (P/subdir).exists():continue
 for directory in sorted((P/subdir).iterdir()):
  if not directory.is_dir():continue
  item={}
  for name,field in [('launch.json','launch'),('result.json','result'),('scheduler-window.json','scheduler_window'),('capacity-window.json','capacity_window'),('profile-metadata.json','profile_metadata')]:
   f=directory/name
   if f.exists():item[field]=json.loads(f.read_text())
  item['remote_directory']=str(directory)
  if 'result' in item:result[key][directory.name]=item
for name in ['ctest-pr10.log','ctest-mux.log','ctest-v2.log','ctest-async.log','ctest-cpu-baseline.log','ctest-fd.log','ctest-fuse.log','ctest-final-default_core.log','ctest-final-fusion_enabled.log']:
 f=P/name
 if f.exists():result['checks'][name]={'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'tail':f.read_text().splitlines()[-12:]}
for build in ['build','build-mux','build-v2','build-async','build-fd','build-fuse']:
 f=P/build/'ocudu-gpu-channel'
 if f.exists():result['binaries'][str(f)]=hashlib.sha256(f.read_bytes()).hexdigest()
for f in [pathlib.Path('/workspace/ocudu-spark/builds/d10-cuda-patched-sm121/apps/gnb/gnb'),
          pathlib.Path('/workspace/ocudu-spark-ranb/builds/srsran4g-zmq-local/srsue/src/srsue')]:
 result['binaries'][str(f)]=hashlib.sha256(f.read_bytes()).hexdigest()
result['provenance']=dict(pr10='9a33e0c2de17d5e8030ea570f57ba0fc08075fce',
 source_checkpoint='0eb3cf4254cdc62b205bbe5ef706b4b8c049c4b1',source_final_cpp='aba7513',
 sample_rate_hz=23040000,bandwidth_mhz=20,cells=1,antennas='1x1',ue_gpu_used=False,
 cpus=dict(gnb='5-12',broker='15-16',ue='13,14,17-19',auxiliary='0-4'))
for key in ['cases','cases_8ue']:
 hashes=[json.dumps(v['launch']['input_hashes'],sort_keys=True) for v in result[key].values() if 'launch' in v]
 assert len(set(hashes))<=1,('different frozen inputs',key)
result['final_validation']=json.loads((P/'validation-final.json').read_text())
print(json.dumps(result,indent=2))
