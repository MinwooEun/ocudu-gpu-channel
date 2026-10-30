"""Use the other sweep's existing GPU-busy wait, only between finished cases."""
import pathlib,subprocess as sp,os,time,json,signal,sys,select
base=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030');tag=sys.argv[1];case=base/'u1'/('original-'+tag);case.mkdir(parents=True,exist_ok=True)
def busy():return sp.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).split()
def sources():
 r=sp.run(['pgrep','-f','^/workspace/gpuch/profile-20261028/build/ocudu-zmq-(source|sink) '],stdout=sp.PIPE);return bool(r.stdout.strip())
start=time.monotonic();print('waiting for finished external case',flush=True)
while busy() or sources():time.sleep(.2)
while True:
 lease=sp.Popen(['python3',str(base/'hold_context.py')],stdout=sp.PIPE,text=True,start_new_session=True)
 assert select.select([lease.stdout],[],[],10)[0],'reservation init timeout';leasepid=lease.stdout.readline().strip();assert leasepid.isdigit(),leasepid
 time.sleep(1.2)
 if all(pid==leasepid for pid in busy()) and not sources():break
 lease.terminate();lease.wait(timeout=10)
 while busy() or sources():time.sleep(.2)
env=dict(os.environ,OCG_TEST_LEASE_PID=leasepid);meta=dict(reservation_pid=int(leasepid),wait_s=time.monotonic()-start,reserved_monotonic_ns=time.monotonic_ns(),external_sweep='/workspace/gpuch/bound1030/run-all.sh',method='Waited for no compute process and no synthetic sources/sinks; idle CUDA context causes sweep to wait at its existing busy check. Released after this benchmark broker starts, before attach/measurement.');(case/'reservation.json').write_text(json.dumps(meta,indent=2))
observer=None;priority=None;proc=None
try:
 priority=sp.Popen(['python3',str(base/'raise_ue_io.py'),str(case)],stdout=(case/'priority-observer.log').open('w'),stderr=sp.STDOUT)
 if os.environ.get('OCG_NO_PERF')!='1':observer=sp.Popen(['/workspace/sionna-venv/bin/python',str(base/'capture_output.py'),str(case)],stdout=(case/'capture-observer.log').open('w'),stderr=sp.STDOUT)
 proc=sp.Popen(['python3',str(base/'live_trace.py'),'--ues','1','--tag',tag,'original'],env=env)
 deadline=time.monotonic()+45
 while time.monotonic()<deadline:
  log=case/'runtime/logs/broker.log'
  if log.exists() and 'event=control_start ' in log.read_text():break
  if proc.poll() is not None:raise RuntimeError('benchmark exited before broker ready')
  time.sleep(.1)
 else:raise RuntimeError('broker not ready')
 lease.terminate();lease.wait(timeout=10);meta['released_monotonic_ns']=time.monotonic_ns();(case/'reservation.json').write_text(json.dumps(meta,indent=2));print('lease released; benchmark owns device',flush=True)
 rc=proc.wait(timeout=800);assert rc==0,rc
 assert priority.wait(timeout=10)==0,'priority failed'
 if observer is not None:assert observer.wait(timeout=90)==0,'capture failed'
finally:
 for child in [lease,priority,observer,proc]:
  if child is not None and child.poll() is None:
   child.terminate()
   try:child.wait(timeout=15)
   except sp.TimeoutExpired:child.kill();child.wait()
