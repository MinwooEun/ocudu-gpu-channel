"""Partition a UE CUDA stream fence using correlated device activities.
Post-device time includes notification, OS scheduling and CUDA return overhead.
It is not, by itself, a measurement of runnable CPU scheduling delay.
"""
import argparse,bisect,collections,json,pathlib,sqlite3
p=argparse.ArgumentParser();p.add_argument('sqlite',type=pathlib.Path);a=p.parse_args();db=sqlite3.connect(a.sqlite);db.row_factory=sqlite3.Row
strings=dict(db.execute('select id,value from StringIds'));tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
runtime=[dict(r) for r in db.execute('select * from CUPTI_ACTIVITY_KIND_RUNTIME')]
for r in runtime:r['name']=strings[r['nameId']];r['pid']=r['globalTid']&~0xffffff
idx={(r['pid'],r['correlationId']):r for r in runtime}
sync={(r['globalPid'],r['correlationId']):dict(r) for r in db.execute('select * from CUPTI_ACTIVITY_KIND_SYNCHRONIZATION')}
acts=[];unmatched=0
for table in ['CUPTI_ACTIVITY_KIND_KERNEL','CUPTI_ACTIVITY_KIND_MEMCPY','CUPTI_ACTIVITY_KIND_MEMSET']:
 if table not in tables:continue
 for row in db.execute('select * from '+table):
  r=dict(row);api=idx.get((r.get('globalPid'),r.get('correlationId')))
  if api is None:unmatched+=1;continue
  r['api']=api;r['name']=strings.get(r.get('demangledName'),'memcpy' if table.endswith('MEMCPY') else 'memset');acts.append(r)
by_tid=collections.defaultdict(list)
for r in acts:by_tid[r['api']['globalTid']].append(r)
for v in by_tid.values():v.sort(key=lambda r:r['api']['start'])
osrt=collections.defaultdict(list)
for r in db.execute('select * from OSRT_API'):
 r=dict(r);r['name']=strings[r['nameId']];osrt[r['globalTid']].append(r)
for v in osrt.values():v.sort(key=lambda r:r['start'])
osstarts={t:[x['start'] for x in v] for t,v in osrt.items()}
scheduled=collections.defaultdict(list)
if 'SCHED_EVENTS' in tables:
 active={}
 for event in db.execute('select * from SCHED_EVENTS order by start'):
  tid=event['globalTid']
  if event['isSchedIn']:active[tid]=event['start']
  elif tid in active:
   t0=active.pop(tid)
   if event['start']>=t0:scheduled[tid].append((t0,event['start']))
scheduled_ends={t:[y for x,y in v] for t,v in scheduled.items()}
previous={};rows=[]
for api in sorted(runtime,key=lambda r:r['start']):
 if not api['name'].startswith('cudaStreamSynchronize'):continue
 s=sync.get((api['pid'],api['correlationId']))
 if s is None:continue
 key=(api['globalTid'],s['contextId'],s['streamId']);lo=previous.get(key,-1);previous[key]=api['end']
 selected=[x for x in by_tid.get(api['globalTid'],[]) if lo<x['api']['start']<api['start'] and x['contextId']==s['contextId'] and x['streamId']==s['streamId']]
 if not selected:continue
 selected.sort(key=lambda r:r['start']);first=selected[0];last=max(x['end'] for x in selected)
 names=[r['name'] for r in selected];kind='FFT' if any('k_gather(' in n for n in names) else 'PDSCH' if any('ldpc_decode' in n for n in names) else 'other'
 busy=0;tail=None
 for x in selected:
  if tail is None or x['start']>tail:busy+=x['end']-x['start'];tail=x['end']
  elif x['end']>tail:busy+=x['end']-tail;tail=x['end']
 tr=osrt.get(api['globalTid'],[]);st=osstarts.get(api['globalTid'],[]);i=bisect.bisect_left(st,api['start']);nested=[x for x in tr[i:bisect.bisect_right(st,api['end'])] if x['end']<=api['end']+2000]
 block=max((x for x in nested if x['name'] in ['sem_wait','pthread_cond_wait','pthread_cond_timedwait','poll','ppoll']),key=lambda x:x['end']-x['start'],default=None)
 row=dict(kind=kind,globalTid=api['globalTid'],stream=s['streamId'],start_ns=api['start'],end_ns=api['end'],device_last_end_ns=last,kernel_names=names,api_wait_us=(api['end']-api['start'])/1000,device_remaining_at_sync_us=max(0,last-api['start'])/1000,post_device_return_us=max(0,api['end']-max(api['start'],last))/1000,device_activity_us=busy/1000,device_span_us=(last-first['start'])/1000,first_dispatch_after_api_us=max(0,first['start']-first['api']['end'])/1000,submit_api_us=sum({x['api']['correlationId']:x['api']['end']-x['api']['start'] for x in selected}.values())/1000,activities=len(selected),last_end_before_return=last<=api['end']+5000,blocking_osrt=block and dict(name=block['name'],duration_us=(block['end']-block['start'])/1000,post_device_to_osrt_return_us=max(0,block['end']-max(block['start'],last))/1000,osrt_to_cuda_return_us=(api['end']-block['end'])/1000))
 if scheduled:
  begin=max(api['start'],last);end=api['end'];seq=scheduled.get(api['globalTid'],[]);ends=scheduled_ends.get(api['globalTid'],[]);i=bisect.bisect_right(ends,begin);run=0
  for x,y in seq[i:]:
   if x>=end:break
   run+=max(0,min(y,end)-max(x,begin))
  row['post_device_scheduled_cpu_us']=run/1000;row['post_device_off_cpu_us']=max(0,end-begin-run)/1000
 rows.append(row)
def stats(v):
 v=sorted(v);n=len(v)
 return dict(n=n,mean=sum(v)/n,p50=v[n//2],p90=v[min(n-1,int(n*.9))],p99=v[min(n-1,int(n*.99))],max=v[-1]) if n else None
summary={}
for kind in ['FFT','PDSCH','other']:
 v=[r for r in rows if r['kind']==kind and r['last_end_before_return']];summary[kind]={k:stats([r[k] for r in v]) for k in ['api_wait_us','device_remaining_at_sync_us','post_device_return_us','device_activity_us','device_span_us','first_dispatch_after_api_us','submit_api_us']};summary[kind]['blocking_osrt_names']=dict(collections.Counter(r['blocking_osrt']['name'] for r in v if r['blocking_osrt']));summary[kind]['post_device_to_osrt_return_us']=stats([r['blocking_osrt']['post_device_to_osrt_return_us'] for r in v if r['blocking_osrt']]);summary[kind]['bad_last_end_count']=sum(not r['last_end_before_return'] for r in rows if r['kind']==kind)
 if scheduled:
  summary[kind]['post_device_scheduled_cpu_us']=stats([r['post_device_scheduled_cpu_us'] for r in v]);summary[kind]['post_device_off_cpu_us']=stats([r['post_device_off_cpu_us'] for r in v])
result=dict(sqlite=str(a.sqlite),runtime_records=len(runtime),matched_device_activities=len(acts),unmatched_device_activities=unmatched,matched_fences=len(rows),summary=summary,limits='Only UE0 is captured; other GPU clients remain uninstrumented. Device activity is observed elapsed execution, not arithmetic-only cycles. Post-device interval includes CUDA signaling/cleanup and CPU scheduling. In-stream gaps can include host submission gaps and other GPU clients; first dispatch after API is not an SM occupancy measurement.')
a.sqlite.with_suffix('.analysis.json').write_text(json.dumps(result,indent=2)+'\n');a.sqlite.with_suffix('.fences.json').write_text(json.dumps(rows)+'\n');print(json.dumps(result,indent=2))
