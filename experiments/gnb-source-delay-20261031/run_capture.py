import subprocess as sp,os,pathlib,sys
b=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030');tag=sys.argv[1] if len(sys.argv)>1 else 'gnb-root-1031-r1';p=b/'u1'/('original-'+tag);p.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,OCG_ROOM_PROBE='1',OCG_NO_PERF='1',OCG_TEST_SPIN='0',OCG_BROKER_POLL_US='10',OCG_BROKER_CV_REP='1',OCG_ALL_IO_RT='1',OCG_UE_RF_RX_RT='1',OCG_LOG_PIPE='1',OCUDU_LOWER_PHY_TIMING_WARN_US='250',OCUDU_LOWER_PHY_TIMING_WARN_MAX_LOGS_PER_PHASE='10000')
others=[]
if os.environ.get('OCG_GNB_CORE_MODE'):
 with (p/'core-observer.log').open('w') as log:others.append(sp.Popen(['python3','/workspace/gpuch/gnb-source-delay-20261031/core_mode.py',str(p),os.environ['OCG_GNB_CORE_MODE']],stdout=log,stderr=sp.STDOUT))
if os.environ.get('OCG_ANALYZER_INTERFERENCE'):
 with (p/'interference-observer.log').open('w') as log:others.append(sp.Popen(['/workspace/sionna-venv/bin/python','/workspace/gpuch/gnb-source-delay-20261031/interfere.py',str(p),os.environ['OCG_ANALYZER_INTERFERENCE']],stdout=log,stderr=sp.STDOUT))
with (p/'gnb-observer.log').open('w') as log:c=sp.Popen(['/workspace/sionna-venv/bin/python','/workspace/gpuch/gnb-source-delay-20261031/capture_gnb.py',str(p)],stdout=log,stderr=sp.STDOUT)
try:
 r=sp.run(['python3',str(b/'reserve_run.py'),tag],env=env);assert r.returncode==0
 assert c.wait(timeout=90)==0,(p/'gnb-observer.log').read_text()
 for other in others:assert other.wait(timeout=30)==0,(p/'interference-observer.log').read_text()
finally:
 if c.poll() is None:c.terminate();c.wait()
 for other in others:
  if other.poll() is None:other.terminate();other.wait()
