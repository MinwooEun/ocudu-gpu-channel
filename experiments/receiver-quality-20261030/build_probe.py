"""Relink only a diagnostic executable; preserve the original objects/binary."""
import pathlib,subprocess as sp,shlex,json,hashlib
base=pathlib.Path('/workspace/gpuch/receiver-quality-20261030');build=pathlib.Path('/workspace/ocudu-spark-ranb/builds/srsran4g-zmq-local');src=pathlib.Path('/workspace/ocudu-spark-ranb/src/srsRAN_4G-local')
sp.run(['cc','-O2','-I'+str(src/'lib/include'),'-I'+str(build/'lib/include'),'-c',str(base/'noise_probe.c'),'-o',str(base/'noise_probe.o')],check=True)
cmd=shlex.split((build/'srsue/src/CMakeFiles/srsue.dir/link.txt').read_text());cmd[cmd.index('-o')+1]=str(base/'srsue-noise-probe');cmd.insert(cmd.index('-o'),str(base/'noise_probe.o'));cmd+=['-Wl,--wrap=srsran_dmrs_sch_estimate'];sp.run(cmd,cwd=build/'srsue/src',check=True)
(base/'noise-probe-build.json').write_text(json.dumps(dict(command=cmd,cwd=str(build/'srsue/src'),sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [base/'srsue-noise-probe',base/'noise_probe.c',build/'srsue/src/srsue',build/'lib/src/phy/libsrsran_phy.a']}),indent=2))
