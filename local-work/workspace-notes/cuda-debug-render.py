import os,runpy,sys
from pathlib import Path
repo=Path('/home/minwoo/ocudu-work/ocudu-gpu-channel')
try:runpy.run_path(str(repo/'scripts/native/render-legacy-1x1-configs.py'),run_name='__main__')
except SystemExit as e:
 if e.code:raise
p=Path(sys.argv[sys.argv.index('--output-dir')+1])/'gnb.yaml'
s=p.read_text()
v=os.environ['CUDA_DEBUG_VARIANT']
if v=='no-pusch':s+='\nexpert_phy:\n  pusch_acceleration_mode: disabled\n'
elif v=='only-pusch':
 sys.path.insert(0,str(repo/'scripts/native'))
 import importlib
 m=importlib.import_module('disable-gnb-cuda');s=m.disable(s).replace('pusch_acceleration_mode: disabled','pusch_acceleration_mode: enabled')
else:raise ValueError(v)
p.write_text(s)
