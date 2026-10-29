import pathlib,subprocess as sp,sqlite3,json,statistics,math,sys
P=pathlib.Path('/workspace/gpuch/profile-20261028')
def stats(v):
 if not v:return {}
 v=sorted(v);return dict(count=len(v),mean=statistics.mean(v),p50=v[(len(v)-1)//2],p99=v[max(0,math.ceil(.99*len(v))-1)],max=v[-1],sum=sum(v))
def union(intervals):
 last=None;total=0
 for a,b in sorted(intervals):
  if last is None or a>last:total+=b-a;last=b
  elif b>last:total+=b-last;last=b
 return total
results=[]
for report in P.glob('**/*.nsys-rep'):
 if report.name=='nsys-smoke.nsys-rep':continue
 target=report.with_suffix('.sqlite')
 if not target.exists():
  done=sp.run(['/usr/local/cuda/bin/nsys','export','--type','sqlite','--output',str(target),str(report)],stdout=sp.PIPE,stderr=sp.STDOUT,text=True)
  report.with_suffix('.export.log').write_text(done.stdout)
  if done.returncode:print('EXPORT FAILED',report);continue
 db=sqlite3.connect(target);db.row_factory=sqlite3.Row
 tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
 schema={t:[dict(x) for x in db.execute('pragma table_info('+t+')')] for t in tables if t.startswith(('CUPTI','NVTX','THREAD','TARGET'))}
 report.with_suffix('.schema.json').write_text(json.dumps(schema,indent=2))
 entry=dict(report=str(report),tables=sorted(tables))
 strings=dict(db.execute('select id,value from StringIds')) if 'StringIds' in tables else {}
 if 'CUPTI_ACTIVITY_KIND_KERNEL' in tables:
  kernels=[dict(r) for r in db.execute('select * from CUPTI_ACTIVITY_KIND_KERNEL')]
  by={}
  for r in kernels:
   name=strings.get(r.get('demangledName',r.get('shortName')),str(r.get('demangledName')))
   by.setdefault(name,[]).append((r['end']-r['start'])/1000)
  entry['kernels']={k:stats(v) for k,v in by.items()};entry['kernel_count']=len(kernels)
  if kernels:
   start=min(r['start'] for r in kernels);end=max(r['end'] for r in kernels)
   entry['kernel_activity_window_s']=(end-start)/1e9
   entry['kernel_union_busy_s']=union([(r['start'],r['end']) for r in kernels])/1e9
   entry['kernel_union_fraction']=entry['kernel_union_busy_s']/entry['kernel_activity_window_s']
  if 'CUPTI_ACTIVITY_KIND_RUNTIME' in tables:
   runtime=[dict(r) for r in db.execute('select * from CUPTI_ACTIVITY_KIND_RUNTIME')];apis={}
   for r in runtime:apis.setdefault(strings.get(r.get('nameId'),str(r.get('nameId'))),[]).append((r['end']-r['start'])/1000)
   entry['runtime_apis']={k:stats(v) for k,v in apis.items()}
   # Keep the explicit process identity; correlation IDs alone are ambiguous across MPS clients.
   idx={}
   for r in runtime:idx[(r.get('correlationId'),r.get('globalTid',0)&~0xffffff)]=r
   delays=[];matched=0
   for k in kernels:
    r=idx.get((k.get('correlationId'),k.get('globalPid')))
    if r is not None:
     matched+=1;delays.append(max(0,k['start']-r['end'])/1000)
   entry['kernel_runtime_correlation_matched']=matched
   entry['post_api_return_to_kernel_start_us']=stats(delays)
 if 'CUPTI_ACTIVITY_KIND_MEMCPY' in tables:
  copies=[dict(r) for r in db.execute('select * from CUPTI_ACTIVITY_KIND_MEMCPY')];by={}
  for r in copies:
   key=str(r.get('copyKind'));by.setdefault(key,dict(count=0,bytes=0,activity_us=0));by[key]['count']+=1;by[key]['bytes']+=r['bytes'];by[key]['activity_us']+=(r['end']-r['start'])/1000
  entry['memcpy_by_kind']=by
 results.append(entry);db.close()
 print(report.parent.name,'kernels',entry.get('kernel_count'),'busy',entry.get('kernel_union_fraction'),'corr',entry.get('kernel_runtime_correlation_matched'))
(P/'nsys-summary.json').write_text(json.dumps(results,indent=2))
