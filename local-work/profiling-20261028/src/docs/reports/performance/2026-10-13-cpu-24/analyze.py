from pathlib import Path
from statistics import median
import csv,json,hashlib,shutil,subprocess,re
repo=Path(__file__).resolve().parents[2]; raw=repo/'tmp/cpu-24/results'; report=repo/'docs/reports/performance/2026-10-13-cpu-24';report.mkdir(parents=True,exist_ok=True)
summary={'date':'2026-10-13','source_base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'source_changes':'source.patch','measurement':'model_mix_latency','unit':'microseconds','aggregation':'median of three run-level p99 values, calls from all nine receiving nodes','duration_seconds_per_run':30,'runs_per_variant':3,'separate_warmup_seconds':5,'backend_runs':{}}
for variant in ['cpu1','cpu24','cuda']:
 runs=[]
 for i in range(1,4):
  rows=list(csv.reader((raw/f'{variant}.{i}.csv').open()));m=next(r for r in rows if r and r[0]=='model_mix_latency');iterations=int(next(r[1] for r in rows if r and r[0]=='iterations'))
  assert int(m[1])==iterations and iterations>0
  outputs=[r for r in rows if r and r[0]=='rx_output' and r[1]!='device_id'];assert len(outputs)==9 and all(float(r[2])>0 and int(r[7])>0 for r in outputs)
  assert next(r[1] for r in rows if r and r[0]=='backend')==('cuda' if variant=='cuda' else 'cpu')
  assert int(next(r[1] for r in rows if r and r[0]=='cpu_sample_workers'))==(24 if variant=='cpu24' else 1)
  assert not (raw/f'{variant}.{i}.stderr').read_text().strip()
  t=dict(line.split('=',1) for line in (raw/f'{variant}.{i}.cpu-time.txt').read_text().splitlines());cores=(float(t['user_seconds'])+float(t['system_seconds']))/float(t['wall_seconds'])
  d={'run':i,'count':int(m[1]),'p50_us':float(m[2]),'p95_us':float(m[3]),'p99_us':float(m[4]),'max_us':float(m[6]),'mean_cpu_core_equivalents':cores}
  if variant=='cpu24':
   threadrows=(raw/f'{variant}.{i}.threads-end.txt').read_text().splitlines()[1:];assert len(threadrows)==25
   workers=[r.split() for r in threadrows if r.split()[0]!=r.split()[1]];assert len(workers)==24 and all(float(r[3])>0 for r in workers)
   d['active_sample_workers']=24
  runs.append(d)
 summary['backend_runs'][variant]=runs;summary[f'{variant}_p99_median_us']=median(r['p99_us'] for r in runs)
summary['cpu_parallel_p99_speedup']=summary['cpu1_p99_median_us']/summary['cpu24_p99_median_us']
summary['gpu_over_cpu24_p99_speedup']=summary['cpu24_p99_median_us']/summary['cuda_p99_median_us']
for p in raw.iterdir():
 if p.is_file():
  if p.name=='environment.txt':
   text=p.read_text();text=re.sub(r'([0-9a-f]{64})  .*/([^/\n]+)',r'\1  \2',text);(report/p.name).write_text(text)
  else:shutil.copy2(p,report/p.name)
for p in (repo/'tmp/cpu-24/validation').iterdir():
 if p.is_file():(report/p.name).write_text(re.sub(r'/home/[^\s]+/cpu-24-20261013/', '<isolated-build>/',p.read_text()))
for p in ['baseline_probe.cpp','run-remote.sh','fingerprint-remote.sh','build-remote.sh','analyze.py']:
 shutil.copy2(repo/'tmp/cpu-24'/p, report/p)
files=['CMakeLists.txt','apps/ocudu_gpu_channel_bench.cpp','include/ocudu_gpu_channel/config.h','include/ocudu_gpu_channel/cpu_backend.h','include/ocudu_gpu_channel/delay.h','src/config.cpp','src/cpu_backend.cpp','tests/core/test_config.cpp','tests/core/test_broker.cpp','docs/reference/configuration.md','docs/reference/backends.md']
patch=subprocess.check_output(['git','diff','--binary','--',*files],cwd=repo)
for file in ['include/ocudu_gpu_channel/sample_executor.h','src/sample_executor.cpp','tests/core/test_cpu_parallel.cpp']:
 patch+=subprocess.run(['git','diff','--no-index','--binary','/dev/null',file],cwd=repo,stdout=subprocess.PIPE).stdout
(report/'source.patch').write_bytes(patch)
summary['source_patch_sha256']=hashlib.sha256(patch).hexdigest()
(report/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='backend_runs'},indent=2))
