"""Collect compact root-cause evidence and index raw remote profiling artifacts."""
import json,pathlib,subprocess
root=pathlib.Path(__file__).resolve().parent
program="""import pathlib,json,hashlib
b=pathlib.Path('/workspace/gpuch/gpu-ue-rootcause-20261030');out={};manifest=[]
for p in (b/'u8').iterdir():
 if not p.is_dir():continue
 for name in ['launch.json','result.json','runtime/report/run-report.json','runtime/report/gate-summary.json','nsys/timeline.analysis.json','sched/metadata.json']:
  f=p/name
  if f.exists():out[str(f.relative_to(b))]=json.loads(f.read_text())
 for f in list((p/'nsys').glob('timeline.*'))+list((p/'nsys/trace').glob('*.csv'))+list((p/'sched').glob('*.txt')):
  manifest.append(dict(path=str(f),bytes=f.stat().st_size,sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
out['raw-manifest.json']=manifest
print(json.dumps(out))
"""
r=subprocess.run(['ssh','spark-minwoo','python3','-'],input=program,text=True,capture_output=True,check=True)
for rel,data in json.loads(r.stdout).items():
 p=root/'evidence'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2)+'\n')
print('Evidence collected')
