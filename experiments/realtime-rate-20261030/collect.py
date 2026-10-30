"""Collect exact rate windows, sparse pacer shifts and syscall-write evidence."""
import pathlib,json,subprocess
root=pathlib.Path(__file__).resolve().parent
program=r"""import pathlib,json,re,hashlib
b=pathlib.Path('/workspace/gpuch/realtime-rate-20261030');out={};windows=[];raw=[]
for p in (b/'u1').iterdir():
 if not p.is_dir():continue
 for name in ['launch.json','result.json','runtime/report/run-report.json','runtime/report/gate-summary.json','write-targets.json','write-analysis.json','sparse-analysis.json']:
  f=p/name
  if f.exists():out[str(f.relative_to(b))]=json.loads(f.read_text())
 log=p/'runtime/logs/broker.log'
 if log.exists():
  a=[]
  for line in log.open():
   if line.startswith('event=control_sample_applied link_id=ue0>gnb0:sionna_rt ') and 'tag=attach;' not in line:
    d=dict(re.findall(r'(\w+)=([^ ]+)',line));a.append((int(d['sample']),int(d['unix_ns'])))
  if len(a)>=101:
   def span(v):
    radio=(v[-1][0]-v[0][0])/23040000;wall=(v[-1][1]-v[0][1])/1e9
    return dict(radio_s=radio,wall_s=wall,ratio=radio/wall,lost_us=(wall-radio)*1e6)
   windows.append(dict(case=p.name,points=len(a),whole_span=span(a),post_warmup_span=span(a[100:])))
 for f in [p/'writes.data',p/'writes.txt',p/'gnb0-sparse.csv',p/'ue0-sparse.csv']:
  if f.exists():raw.append(dict(path=str(f),bytes=f.stat().st_size,sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
out['rate-windows.json']=windows;out['raw-manifest.json']=raw
f=b/'sparse-build/provenance.json'
if f.exists():out['sparse-build-provenance.json']=json.loads(f.read_text())
print(json.dumps(out))
"""
r=subprocess.run(['ssh','spark-minwoo','sudo','-n','python3','-'],input=program,text=True,capture_output=True,check=True)
for rel,data in json.loads(r.stdout).items():
 p=root/'evidence'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2)+'\n')
print('Rate and syscall evidence collected')
