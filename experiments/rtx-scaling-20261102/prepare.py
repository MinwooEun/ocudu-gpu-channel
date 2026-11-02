import pathlib,tarfile,subprocess as sp,shlex,shutil,json,hashlib
W=pathlib.Path('/home/minwoo/ocudu-work/rtx-scaling-20261102'); E=pathlib.Path(__file__).parent; N=pathlib.Path('/home/minwoo/ocudu-work/ocudu-native-workspace');B=N/'builds/srsran4g-zmq-release'
rf=W/'rf-build';rf.mkdir(exist_ok=True)
with tarfile.open(W/'spark-rf-source.tar.gz') as t:t.extractall(rf,filter='data')
with tarfile.open(W/'runner-configs.tar.gz') as t:t.extractall(W/'ranb',filter='data')
vars={}
for line in (B/'lib/src/phy/rf/CMakeFiles/srsran_rf_zmq.dir/flags.make').read_text().splitlines():
 if ' = ' in line:
  k,v=line.split(' = ',1);vars[k]=v.replace('/home/hyunsoo/ocudu-native-workspace',str(N))
commands=[]
for name in ['rf_zmq_imp','rf_zmq_imp_rx','rf_zmq_imp_tx']:
 cmd=['cc']+shlex.split(vars['C_DEFINES'])+['-I'+str(rf),'-I'+str(N/'src/srsRAN_4G/lib/src/phy/rf')]+shlex.split(vars['C_INCLUDES'])+shlex.split(vars['C_FLAGS'])+['-c',str(rf/(name+'.c')),'-o',str(rf/(name+'.c.o'))];sp.run(cmd,check=True);commands.append(cmd)
cmd=shlex.split((B/'lib/src/phy/rf/CMakeFiles/srsran_rf_zmq.dir/link.txt').read_text().replace('/home/hyunsoo/ocudu-native-workspace',str(N)))
cmd[cmd.index('-o')+1]=str(rf/'libsrsran_rf_zmq.so.23.04.0')
cmd=[str(rf/pathlib.Path(x).name) if x.endswith('.c.o') else x for x in cmd];sp.run(cmd,cwd=B/'lib/src/phy/rf',check=True);commands.append(cmd)
for name in ['libsrsran_rf_zmq.so','libsrsran_rf_zmq.so.0']:(rf/name).symlink_to('libsrsran_rf_zmq.so.23.04.0')
wire=(E.parent/'multi-ue-affinity-20261102/wire_multi.c').read_text();(E/'wire.c').write_text(wire)
ue=pathlib.Path('/home/minwoo/ocudu-work/profiling-20261029-causal/ue_trace.c').read_text().replace('/workspace/ocudu-spark-ranb/builds/srsran4g-zmq-local/lib/src/phy/rf/libsrsran_rf_zmq.so',str(rf/'libsrsran_rf_zmq.so'));(E/'ue_trace.c').write_text(ue)
cmd=['cc','-shared','-fPIC','-O2','-I'+str(rf),'-I'+str(N/'src/srsRAN_4G/lib/src/phy/rf'),'-I'+str(N/'src/srsRAN_4G/lib/include'),str(E/'wire.c'),str(E/'ue_trace.c'),'-o',str(W/'wire.so'),'-Wl,--no-as-needed','-lzmq','-ldl','-pthread'];sp.run(cmd,check=True);commands.append(cmd)
s=(E.parent/'one-ue-realtime-20261030/pipe_broker.py').read_text().replace('/workspace/gpuch/one-ue-realtime-20261030/room-build/ocudu-gpu-channel',str(W/'channel-build/ocudu-gpu-channel')).replace('{0,1,2,3,4}','{20,21,22,23}')
d=W/'pipe-build';d.mkdir(exist_ok=True);(d/'ocudu-gpu-channel').write_text(s);(d/'ocudu-gpu-channel').chmod(0o755)
s=(E.parent/'multi-ue-affinity-20261102/priorities.py').read_text().replace('/dev/shm/ocudu-one-ue-rt-20261030/wire',str(W/'active-wire'));(E/'priorities.py').write_text(s)
(E/'prepare.json').write_text(json.dumps(dict(commands=commands,work=str(W)),indent=2))
print('prepared')
