import pathlib,subprocess as sp,json,shlex,hashlib,shutil
base=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030');old=pathlib.Path('/workspace/gpuch/profile-20261028/build');out=base/'room-build';out.mkdir(exist_ok=True);values={}
for l in (old/'CMakeFiles/ocudu_gpu_channel_lib.dir/flags.make').read_text().splitlines():
 if ' = ' in l:
  k,v=l.split(' = ',1);values[k]=v
obj=out/'broker.cpp.o';cmd=['c++']+shlex.split(values['CXX_DEFINES'])+shlex.split(values['CXX_INCLUDES'])+shlex.split(values['CXX_FLAGS'])+['-I/workspace/gpuch/profile-20261028/src/src','-c',str(base/'broker-room.cpp'),'-o',str(obj)];sp.run(cmd,check=True)
archive=old/'libocudu_gpu_channel_lib.a';new=out/archive.name;shutil.copy2(archive,new);sp.run(['ar','r',str(new),str(obj)],check=True);sp.run(['ranlib',str(new)],check=True)
members=sp.check_output(['ar','t',str(archive)],text=True).splitlines();changed=[]
for m in members:
 if sp.check_output(['ar','p',str(archive),m])!=sp.check_output(['ar','p',str(new),m]):changed.append(m)
assert changed==['broker.cpp.o'],changed
link=json.loads(pathlib.Path('/workspace/gpuch/realtime-rate-20261030/sparse-build/provenance.json').read_text())['link_command'];link=[v.replace('/workspace/gpuch/realtime-rate-20261030/sparse-build',str(out)) for v in link];sp.run(link,check=True)
r=dict(compile_command=cmd,link_command=link,modified_archive_members=changed,unchanged_archive_members=[m for m in members if m not in changed],binary_sha256=hashlib.sha256((out/'ocudu-gpu-channel').read_bytes()).hexdigest(),source_sha256=hashlib.sha256((base/'broker-room.cpp').read_bytes()).hexdigest());(out/'provenance.json').write_text(json.dumps(r,indent=2)+'\n');print('room probe built',flush=True)
