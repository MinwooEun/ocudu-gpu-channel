import pathlib,subprocess as sp,shlex,json
P=pathlib.Path('/workspace/gpuch/profile-20261029-causal');B=pathlib.Path('/workspace/ocudu-spark/builds/d10-cuda-patched-sm121');S=pathlib.Path('/workspace/ocudu-spark/src/ocudu-cuda-d10/lib/radio/zmq')
commands=[]
for side in ('tx','rx'):
 name=f'radio_zmq_{side}_channel.cpp';target=f'lib/radio/zmq/CMakeFiles/ocudu_radio_zmq.dir/{name}.o'
 cmd=sp.check_output(['ninja','-C',str(B),'-t','commands',target],text=True).strip().splitlines()[-1]
 args=shlex.split(cmd);args=[str(P/'gnb-instrumented'/name) if x==str(S/name) else x for x in args]
 for flag in ('-o','-MF','-MT'):
  i=args.index(flag)+1;args[i]=str(P/'gnb-instrumented'/pathlib.Path(args[i]).name)
 args+=['-I'+str(S)];commands.append(args);sp.run(args,cwd=B,check=True)
lib=P/'gnb-instrumented/libocudu_radio_zmq.a'
sp.run(['cp',str(B/'lib/radio/zmq/libocudu_radio_zmq.a'),str(lib)],check=True)
sp.run(['ar','r',str(lib),str(P/'gnb-instrumented/radio_zmq_tx_channel.cpp.o'),str(P/'gnb-instrumented/radio_zmq_rx_channel.cpp.o')],check=True)
cmd=sp.check_output(['ninja','-C',str(B),'-t','commands','apps/gnb/gnb'],text=True).strip().splitlines()[-1]
# Ninja emits a leading/trailing no-op around the linker. Only substitute the two exact paths.
assert ' -o apps/gnb/gnb ' in cmd
cmd=cmd.replace(' -o apps/gnb/gnb ',' -o '+str(P/'gnb-instrumented/gnb')+' ')
cmd=cmd.replace('lib/radio/zmq/libocudu_radio_zmq.a',str(lib));commands.append(cmd)
(P/'gnb-build-commands.json').write_text(json.dumps(commands,indent=2));sp.run(cmd,cwd=B,shell=True,check=True)
