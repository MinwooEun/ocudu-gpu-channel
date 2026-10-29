from pathlib import Path
import json,sys
ROOT=Path('/workspace/gpuch/profile-20261029-deep');case=sys.argv[1] if len(sys.argv)>1 else 'deep16';P=ROOT/({'deep16':'','deep16-yield':'yield','deep8-yield':'eight','deep16-cpu7':'cpu7'}[case]);P.mkdir(exist_ok=True);out=[]
for f in (ROOT/'runs'/case/'wire').glob('ocudu*'):
 pid=int(f.stem.split('-')[-1])
 for t in Path(f'/proc/{pid}/task').glob('*'):
  out.append(dict(pid=pid,tid=int(t.name),comm=(t/'comm').read_text().strip()))
(P/'thread-map.json').write_text(json.dumps(out,indent=2))
