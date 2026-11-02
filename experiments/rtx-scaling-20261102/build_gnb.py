"""Relink an isolated x86 gNB with the exact three missing Spark source fixes."""
import pathlib,tarfile,subprocess as sp,shlex,shutil,json,hashlib
E=pathlib.Path(__file__).parent;W=pathlib.Path('/home/minwoo/ocudu-work/rtx-scaling-20261102');N=pathlib.Path('/home/minwoo/ocudu-work/ocudu-native-workspace');B=N/'builds/c1-d10-cuda-patched';D=W/'gnb-build';D.mkdir(exist_ok=True)
def fix(s):return s.replace('/home/hyunsoo/ocudu-native-workspace',str(N)).replace('/usr/local/cuda-12.8/targets/x86_64-linux/lib','/usr/local/cuda-13.0/lib64')
def variables(p):
 out={}
 for l in p.read_text().splitlines():
  if ' = ' in l:
   k,v=l.split(' = ',1);out[k]=fix(v)
 return out
commands=[]
with tarfile.open(W/'spark-gnb-modified.tar') as t:t.extractall(D/'source',filter='data')
cd=B/'lib/phy/cuda';v=variables(cd/'CMakeFiles/ocudu_phy_cuda.dir/flags.make');inc=fix((cd/'CMakeFiles/ocudu_phy_cuda.dir/includes_CUDA.rsp').read_text());(D/'includes.rsp').write_text(inc)
for name in ['pusch_e2e.cu','pusch_e2e_api.cu']:
 cmd=['/usr/local/cuda-13.0/bin/nvcc']+shlex.split(v['CUDA_DEFINES'])+['--options-file',str(D/'includes.rsp'),'-I'+str(N/'src/ocudu-cuda-c1d10/lib/phy/cuda/src')]+shlex.split(v['CUDA_FLAGS'])+['-c',str(D/'source/lib/phy/cuda/src'/name),'-o',str(D/(name+'.o'))];
 if not (D/(name+'.o')).exists():sp.run(cmd,check=True)
 commands.append(cmd)
ld=B/'lib/phy/upper/channel_coding/ldpc/cuda';v=variables(ld/'CMakeFiles/ocudu_ldpc_cuda.dir/flags.make');name='pusch_codeblock_decoder_cuda_batch.cpp';cmd=['c++']+shlex.split(v['CXX_DEFINES'])+shlex.split(v['CXX_INCLUDES'])+shlex.split(v['CXX_FLAGS'])+['-c',str(D/'source/lib/phy/upper/channel_coding/ldpc/cuda'/name),'-o',str(D/(name+'.o'))];
if not (D/(name+'.o')).exists():sp.run(cmd,check=True)
commands.append(cmd)
for old,names in [(cd/'libocudu_phy_cuda.a',['pusch_e2e.cu','pusch_e2e_api.cu']),(ld/'libocudu_ldpc_cuda.a',[name])]:
 target=D/old.name;shutil.copy2(old,target);sp.run(['ar','r',str(target)]+[str(D/(n+'.o')) for n in names],check=True);sp.run(['ranlib',str(target)],check=True)
cmd=shlex.split(fix((B/'apps/gnb/CMakeFiles/gnb.dir/link.txt').read_text()));cmd[cmd.index('-o')+1]=str(D/'gnb');cmd=[str(W/'cuda12/nvidia/cuda_runtime/lib/libcudart.so.12') if x=='/usr/local/cuda-13.0/lib64/libcudart.so' else str(D/pathlib.Path(x).name) if pathlib.Path(x).name in ['libocudu_phy_cuda.a','libocudu_ldpc_cuda.a'] else x for x in cmd];cmd=[x for x in cmd if x not in ['-lcudart_static','-lcudadevrt']];sp.run(cmd,cwd=B/'apps/gnb',check=True);commands.append(cmd)
(E/'gnb-build.json').write_text(json.dumps(dict(commands=commands,binary=str(D/'gnb'),sha256=hashlib.sha256((D/'gnb').read_bytes()).hexdigest(),source='exact Spark modified source files; all other x86 archive members unchanged; CUDA13 rebuild'),indent=2))
print('built',D/'gnb',flush=True)
