import subprocess as s,json,pathlib,shutil
b="/workspace/ocudu-spark-ranb/builds/srsran4g-zmq-local/srsue/src/srsue"
res=[]
for name,offset in [("fft",0x341744),("dldci",0x341990),("uldci",0x341bf0),("pdsch",0x341f80),("ldpc",0x360970)]:
 for suffix,tail in [("",""),("_ret","%return")]:
  event="ocudurate_"+name+suffix
  if event+" " in s.check_output(["perf","probe","-l"],text=True):continue
  cmd=["perf","probe","-x",b,"-a",f"{event}=0x{offset:x}{tail}"]
  r=s.run(cmd,capture_output=True,text=True);res.append(dict(cmd=cmd,rc=r.returncode,out=r.stdout,err=r.stderr));print(res[-1],flush=True)
  assert r.returncode==0
pathlib.Path("/workspace/gpuch/realtime-rate-20261030/ue-detail-probes.json").write_text(json.dumps(res,indent=2))
