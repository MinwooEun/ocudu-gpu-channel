import pathlib,subprocess as sp,shlex,json,hashlib
b=pathlib.Path('/workspace/gpuch/rlc-overlap-20261102');old=pathlib.Path('/workspace/ocudu-spark-ranb/builds/srsran4g-zmq-local');src=pathlib.Path('/workspace/ocudu-spark-ranb/src/srsRAN_4G-local');values={}
for l in (old/'lib/test/rlc/CMakeFiles/rlc_am_nr_test.dir/flags.make').read_text().splitlines():
 if ' = ' in l:
  k,v=l.split(' = ',1);values[k]=v
obj=b/'replay.o';compile=['c++']+shlex.split(values['CXX_DEFINES'])+shlex.split(values['CXX_INCLUDES'])+shlex.split(values['CXX_FLAGS'])+['-I'+str(src/'lib/test/rlc'),'-c',str(b/'replay.cc'),'-o',str(obj)];sp.run(compile,check=True)
link=shlex.split((old/'lib/test/rlc/CMakeFiles/rlc_am_nr_test.dir/link.txt').read_text());link=[str(obj) if v=='CMakeFiles/rlc_am_nr_test.dir/rlc_am_nr_test.cc.o' else str(b/'replay') if v=='rlc_am_nr_test' else v for v in link];sp.run(link,cwd=old/'lib/test/rlc',check=True)
(b/'build.json').write_text(json.dumps(dict(compile=compile,link=link,cwd=str(old/'lib/test/rlc'),rlc_archive_sha256=hashlib.sha256((old/'lib/src/rlc/libsrsran_rlc.a').read_bytes()).hexdigest()),indent=2)+'\n')
