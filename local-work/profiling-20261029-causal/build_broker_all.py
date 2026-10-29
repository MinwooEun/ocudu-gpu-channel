from pathlib import Path
import subprocess as sp,shlex,json
P=Path('/workspace/gpuch/profile-20261029-causal');B=Path('/workspace/gpuch/profile-20261028/build');O=P/'broker-all-notify';O.mkdir(exist_ok=True)
flags={}
for l in (B/'CMakeFiles/ocudu_gpu_channel_lib.dir/flags.make').read_text().splitlines():
 if ' = ' in l:k,v=l.split(' = ',1);flags[k]=v
cmd=['/usr/bin/c++']+sum([shlex.split(flags[k]) for k in ('CXX_DEFINES','CXX_INCLUDES','CXX_FLAGS')],[])+['-I/workspace/gpuch/profile-20261028/src/src','-c',str(P/'broker-all-notify.cpp'),'-o',str(O/'broker.cpp.o')]
sp.run(cmd,cwd=B,check=True);sp.run(['cp',str(B/'libocudu_gpu_channel_lib.a'),str(O/'libocudu_gpu_channel_lib.a')],check=True);sp.run(['ar','r',str(O/'libocudu_gpu_channel_lib.a'),str(O/'broker.cpp.o')],check=True)
for target in ('ocudu-gpu-channel','test_broker'):
 args=shlex.split((B/f'CMakeFiles/{target}.dir/link.txt').read_text());args=[str(O/x) if x=='libocudu_gpu_channel_lib.a' else x for x in args];args[args.index('-o')+1]=str(O/target);sp.run(args,cwd=B,check=True)
(P/'broker-all-build-command.json').write_text(json.dumps(cmd))
