import pathlib,subprocess as sp,time,json
E=pathlib.Path(__file__).parent;W=pathlib.Path('/home/minwoo/ocudu-work/rtx-scaling-20261102');deadline=time.monotonic()+900
while not (W/'u16-matched-r1/result.json').exists() or (W/'active-wire').is_symlink():
 if time.monotonic()>deadline:raise RuntimeError('baseline not finished')
 time.sleep(1)
results=[]
for n in [8,16]:
 p=sp.run(['docker','exec','ocg-rtx-scaling-20261102','chroot','/host','/usr/bin/python3',str(E/'run.py'),str(n),'pbroker-r1'])
 results.append(dict(ues=n,returncode=p.returncode));(E/'placement-status.json').write_text(json.dumps(results,indent=2))
 if p.returncode:break
