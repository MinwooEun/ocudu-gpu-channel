import subprocess as s,json,pathlib,shutil
b="/workspace/ocudu-spark-ranb/builds/srsran4g-zmq-local/srsue/src/srsue"
res=[]
for name,offset in [("dl",0xa5494),("ul",0xa1420),("work",0xa7860),("end",0xdbbe0)]:
 for suffix,tail in [("",""),("_ret","%return")]:
  event="ocudurate_"+name+suffix
  if event+" " in s.check_output(["perf","probe","-l"],text=True):continue
  cmd=["perf","probe","-x",b,"-a",f"{event}=0x{offset:x}{tail}"]
  r=s.run(cmd,capture_output=True,text=True);res.append(dict(cmd=cmd,rc=r.returncode,out=r.stdout,err=r.stderr));print(res[-1],flush=True)
  assert r.returncode==0
pathlib.Path("/workspace/gpuch/realtime-rate-20261030/ue-probes.json").write_text(json.dumps(res,indent=2))
a="/workspace/gpuch/realtime-rate-20261030/archives/input-root-r1-memory-traces.tar.gz"
s.run(["gzip","-t",a],check=True)
shutil.rmtree("/dev/shm/ocudu-input-root-20261030")
