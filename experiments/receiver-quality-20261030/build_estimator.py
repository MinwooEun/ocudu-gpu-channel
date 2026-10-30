"""Compile one replacement object and relink an isolated UE candidate."""
import pathlib,subprocess as sp,shlex,json,hashlib
base=pathlib.Path('/workspace/gpuch/receiver-quality-20261030');build=pathlib.Path('/workspace/ocudu-spark-ranb/builds/srsran4g-zmq-local');src=build/'lib/src/phy/CMakeFiles/srsran_phy.dir/flags.make';vars={}
for line in src.read_text().splitlines():
 if ' = ' in line:
  k,v=line.split(' = ',1);vars[k]=v
out=base/'local-noise-build';out.mkdir(exist_ok=True);obj=out/'dmrs_sch.c.o';archive=build/'lib/src/phy/libsrsran_phy.a';new=out/archive.name
cmd=['/usr/bin/cc']+shlex.split(vars['C_DEFINES'])+shlex.split(vars['C_INCLUDES'])+shlex.split(vars['C_FLAGS'])+['-c',str(base/'dmrs_sch.local-noise.c'),'-o',str(obj)];sp.run(cmd,check=True)
import shutil
shutil.copy2(archive,new);sp.run(['ar','r',str(new),str(obj)],check=True);sp.run(['ranlib',str(new)],check=True)
oldmembers=sp.check_output(['ar','t',str(archive)],text=True).splitlines();newmembers=sp.check_output(['ar','t',str(new)],text=True).splitlines();assert oldmembers==newmembers
changed=[]
for member in oldmembers:
 a=sp.check_output(['ar','p',str(archive),member]);b=sp.check_output(['ar','p',str(new),member]);
 if a!=b:changed.append(member)
assert changed==['dmrs_sch.c.o'],changed
link=shlex.split((build/'srsue/src/CMakeFiles/srsue.dir/link.txt').read_text());link[link.index('-o')+1]=str(out/'srsue');link=[str(new) if v=='../../lib/src/phy/libsrsran_phy.a' else v for v in link];sp.run(link,cwd=build/'srsue/src',check=True)
r=dict(compile=cmd,link=link,link_cwd=str(build/'srsue/src'),changed_archive_members=changed,unchanged_members=len(oldmembers)-len(changed),sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [base/'dmrs_sch.local-noise.c',obj,new,out/'srsue',archive,build/'srsue/src/srsue']});(base/'local-noise-build.json').write_text(json.dumps(r,indent=2)+'\n')
print('built',out/'srsue',flush=True)
