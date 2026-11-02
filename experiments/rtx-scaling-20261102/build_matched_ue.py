import pathlib,json,subprocess as sp,shlex,tarfile,shutil,os
W=pathlib.Path('/home/minwoo/ocudu-work/rtx-scaling-20261102');N=pathlib.Path('/home/minwoo/ocudu-work/ocudu-native-workspace');E=pathlib.Path(__file__).parent
source=W/'ue-matched-src';shutil.copytree(N/'src/srsRAN_4G',source,ignore=shutil.ignore_patterns('.git'),dirs_exist_ok=True)
diff=json.loads((W/'ue-source-differences.json').read_text())
with (W/'spark-ue-delta.tar').open('wb') as out:sp.run(['ssh','spark-minwoo','tar -C /workspace/ocudu-spark-ranb/src/srsRAN_4G-local -cf - '+shlex.join(diff)],stdout=out,check=True)
with tarfile.open(W/'spark-ue-delta.tar') as t:t.extractall(source,filter='data')
# Compare every original compiled source file, then apply the identical CPU noise fix.
import hashlib
hashes=json.loads((W/'spark-ue-source-hashes.json').read_text());bad=[p for p,h in hashes.items() if (source/p).exists() and hashlib.sha256((source/p).read_bytes()).hexdigest()!=h];assert not bad,bad
sp.run(['patch','-p1','-i',str(E.parent/'receiver-quality-20261030/srsue-dmrs-local-noise.patch')],cwd=source,check=True)
cache={}
for l in (N/'builds/srsran4g-zmq-release/CMakeCache.txt').read_text().splitlines():
 if '=' in l and ':' in l:
  k,v=l.split('=',1);cache[k.split(':')[0]]=v.replace('/home/hyunsoo/ocudu-native-workspace',str(N))
cmd=['cmake','-S',str(source),'-B',str(W/'ue-matched-build'),'-DCMAKE_BUILD_TYPE=Release','-DENABLE_SRSUE=ON','-DENABLE_SRSENB=OFF','-DENABLE_SRSEPC=OFF','-DENABLE_UHD=OFF','-DENABLE_ZEROMQ=ON','-DENABLE_WERROR=OFF','-DENABLE_EXPORT=ON']+['-D'+k+'='+cache[k] for k in ['CMAKE_PREFIX_PATH','CMAKE_INCLUDE_PATH','CMAKE_LIBRARY_PATH'] if cache.get(k)]
env=dict(os.environ,PKG_CONFIG_PATH=str(N/'install/sysroot/usr/lib/x86_64-linux-gnu/pkgconfig'))
sp.run(cmd,env=env,check=True);sp.run(['cmake','--build',str(W/'ue-matched-build'),'--target','srsue','-j10'],env=env,check=True)
(E/'ue-matched-build.json').write_text(json.dumps(dict(source_manifest_total=len(hashes),source_files_present_compared=sum((source/p).exists() for p in hashes),missing_arm_only_files=[p for p in hashes if not (source/p).exists()],different_before_noise=bad,delta_sources=diff,configure=cmd,binary=str(W/'ue-matched-build/srsue/src/srsue')),indent=2))
