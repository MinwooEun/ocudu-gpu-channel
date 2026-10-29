from pathlib import Path
import subprocess as sp
P=Path('/workspace/gpuch/profile-20261028')
for f in (P/'live').glob('*/perf-*.data'):
 target=f.with_suffix('.report.txt')
 if target.exists():continue
 with target.open('w') as out:
  p=sp.run(['perf','report','-i',str(f),'--stdio','--no-children','-g','none','--sort','comm,dso,symbol','--field-separator','|','--percent-limit','0.3'],stdout=out,stderr=sp.PIPE,text=True)
 if p.returncode: target.unlink(); print(f.name,p.stderr[-300:])
