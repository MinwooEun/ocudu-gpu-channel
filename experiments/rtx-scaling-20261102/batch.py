import pathlib,subprocess as sp,json,time
E=pathlib.Path(__file__).parent;W=pathlib.Path('/home/minwoo/ocudu-work/rtx-scaling-20261102');results=[]
for n in [1,4,8,16]:
 p=sp.run(['docker','exec','ocg-rtx-scaling-20261102','chroot','/host','/usr/bin/python3',str(E/'run.py'),str(n),'matched-r1'])
 results.append(dict(ues=n,returncode=p.returncode));(E/'batch-status.json').write_text(json.dumps(results,indent=2))
 if p.returncode:break
