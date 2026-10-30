"""Separate actual full-buffer time from producer reaction/scheduling time."""
import pathlib,csv,json,sys,numpy as np
p=pathlib.Path(sys.argv[1]);hop={}
for r in csv.DictReader((p/'hop/hop-trace.csv').open()):
 key=(r['role'],r['id'],int(r['event']))
 if key in [('rep','gnb0_p0',22),('producer','gnb0',11)]:hop.setdefault(key,[]).append((int(r['t_ns']),int(r['samples'])))
release=np.array(hop['rep','gnb0_p0',22],dtype=np.int64);push=np.array(hop['producer','gnb0',11],dtype=np.int64)
rep=json.loads((p/'runtime/report/run-report.json').read_text());s0=rep['epoch']['s0'];lo=s0+230400000;hi=s0+rep['epoch']['measure_samples'];rows=[]
for r in csv.DictReader((p/'room/gnb0-room.csv').open()):
 r={k:int(v) for k,v in r.items()}
 if not lo<=r['sample']<hi:continue
 t0=r['start_ns'];t1=r['end_ns'];j=int(np.searchsorted(release[:,0],t0));r['wall_us']=(t1-t0)/1000;r['cpu_us']=r['cpu_ns']/1000;r['off_cpu_or_clock_difference_us']=r['wall_us']-r['cpu_us'];r['scenario_s']=(r['sample']-s0)/23040000
 r['first_release_after_start_ns']=int(release[j,0]) if j<len(release) else None;r['release_before_end']=bool(j<len(release) and release[j,0]<=t1);r['release_to_room_exit_us']=(t1-int(release[j,0]))/1000 if j<len(release) else None
 r['queue_samples_at_start_estimate']=int(push[push[:,0]<t0,1].sum()-release[release[:,0]<t0,1].sum());r['queue_samples_at_end_estimate']=int(push[push[:,0]<t1,1].sum()-release[release[:,0]<t1,1].sum())
 rows.append(r)
out=dict(note='Thread CPU time distinguishes running from sleeping/descheduling, but does not separate those off-CPU causes. ReplySent is after the ring release and can lag it if the REP thread is descheduled; its timestamp is an upper bound.',events=rows);(p/'room-analysis.json').write_text(json.dumps(out,indent=2)+'\n')
for r in sorted(rows,key=lambda r:r['wall_us'],reverse=True)[:10]:print(r)
