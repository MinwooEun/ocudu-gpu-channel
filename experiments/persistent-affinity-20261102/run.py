import pathlib,subprocess as sp,os,sys
base=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030');tag=sys.argv[1];case=base/'u1'/('original-'+tag);case.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,OCG_ROOM_PROBE='1',OCG_NO_PERF='1',OCG_TEST_SPIN='0',OCG_BROKER_POLL_US='10',OCG_BROKER_CV_REP='1',OCG_ALL_IO_RT='1',OCG_UE_RF_RX_RT='1',OCG_LOG_PIPE='1')
with (case/'affinity-observer.log').open('w') as log:audit=sp.Popen(['python3','/workspace/gpuch/persistent-affinity-20261102/audit.py',str(case)],stdout=log,stderr=sp.STDOUT)
try:
 r=sp.run(['python3',str(base/'reserve_run.py'),tag],env=env);assert r.returncode==0
 assert audit.wait(timeout=15)==0,(case/'affinity-observer.log').read_text()
finally:
 if audit.poll() is None:audit.terminate();audit.wait()
