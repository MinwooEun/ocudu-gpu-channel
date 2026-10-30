#!/usr/bin/python3
"""Drain broker evidence through a bounded pipe on auxiliary CPUs; preserve every byte."""
import os,sys,subprocess as sp,signal,pathlib,json,fcntl,time
real='/workspace/gpuch/one-ue-realtime-20261030/room-build/ocudu-gpu-channel'
child=sp.Popen([real]+sys.argv[1:],stdout=sp.PIPE,bufsize=0,pipesize=1048576)
# Child inherits the requested broker affinity before the reader moves away.
os.sched_setaffinity(0,{0,1,2,3,4})
meta=dict(pid=os.getpid(),child_pid=child.pid,reader_cpus=sorted(os.sched_getaffinity(0)),pipe_bytes=fcntl.fcntl(child.stdout.fileno(),fcntl.F_GETPIPE_SZ),start_mono_ns=time.monotonic_ns(),real_binary=real)
p=pathlib.Path(os.environ['OCG_LOG_PIPE_META']);p.write_text(json.dumps(meta,indent=2))
# The native runner signals the entire process group, including the child.
for sig in [signal.SIGTERM,signal.SIGINT,signal.SIGHUP]:signal.signal(sig,lambda *_:None)
read_bytes=0;written_bytes=0
try:
 while True:
  data=os.read(child.stdout.fileno(),65536)
  if not data:break
  read_bytes+=len(data);view=memoryview(data)
  while view:
   n=os.write(1,view)
   if n<=0:raise RuntimeError('evidence sink write failed')
   view=view[n:];written_bytes+=n
 rc=child.wait();assert read_bytes==written_bytes
 meta.update(read_bytes=read_bytes,written_bytes=written_bytes,child_exit_code=rc,end_mono_ns=time.monotonic_ns());p.write_text(json.dumps(meta,indent=2))
 sys.exit(rc if rc>=0 else 128-rc)
finally:
 if child.poll() is None:
  child.terminate()
  try:child.wait(timeout=15)
  except sp.TimeoutExpired:child.kill();child.wait()
