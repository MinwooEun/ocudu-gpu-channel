"""Sequential frozen-input multi-UE qualification; no analysis during measurement."""
import pathlib,subprocess as sp,os,sys,json,time,shutil
b=pathlib.Path('/workspace/gpuch/multi-ue-affinity-20261102');ram=pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030');ues=int(sys.argv[1]);mode=sys.argv[2];tag=sys.argv[3];assert mode in ['on','off'];p=b/f'u{ues}'/('original-'+tag);p.mkdir(parents=True,exist_ok=True)
assert not ram.exists(),'archive previous memory capture before another run'
env=dict(os.environ,OCG_ROOM_PROBE='0',OCG_NO_PERF='1',OCG_TEST_SPIN='0',OCG_BROKER_POLL_US='10',OCG_BROKER_CV_REP='1',OCG_LOG_PIPE='1',SINGLE_CELL_GNB_SEPARATE_RADIO='1' if mode=='on' else '0')
with (p/'audit-observer.log').open('w') as log:audit=sp.Popen(['python3',str(b/'audit.py'),str(p),mode],stdout=log,stderr=sp.STDOUT)
start=time.monotonic()
try:
 r=sp.run(['python3',str(b/'reserve.py'),str(ues),tag],env=env);audit_rc=audit.wait(timeout=15)
 (p/'verification.json').write_text(json.dumps(dict(ues=ues,patch=mode,reserve_returncode=r.returncode,audit_returncode=audit_rc,wall_s=time.monotonic()-start),indent=2)+'\n')
finally:
 if audit.poll() is None:audit.terminate();audit.wait()
 if ram.exists():shutil.move(str(ram),p/'raw')
print('DONE',ues,mode,'result',p,flush=True)
