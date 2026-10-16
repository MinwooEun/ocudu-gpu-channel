from pathlib import Path
import numpy as np,json,sys
base=Path(sys.argv[1]);trace=base/'runtime-audit';policy=sys.argv[2];run=sys.argv[3]
report=json.loads((base/f'ocudu-native-workspace/results/reports/ocudu-scheduler-benchmark/{run}/benchmark-report.json').read_text())
clock=json.loads((trace/'clock-map.json').read_text());offset=clock['unix_ns']-clock['monotonic_ns']
start=int(report['anchor_unix_ms']*1000000-offset);end=start+120000000000
output={'run':run,'policy':policy,'window_start_monotonic_ns':start,'window_end_monotonic_ns':end,'nodes':{}}
def dist(x):
 return {k:float(v) for k,v in zip(['min','median','p95','p99','p999','max'],np.quantile(x,[0,.5,.95,.99,.999,1]))}
for node in ['gnb0','ue0','ue1']:
 p=np.fromfile(trace/policy/f'producer-{node}.bin',dtype='<i8').reshape(-1,13)
 gp=trace/policy/f'gpu-{node}.bin'
 g=np.fromfile(gp,dtype='<i8').reshape(-1,8) if gp.exists() else None
 g_missing=g is None or len(g)!=len(p) or not np.array_equal(p[:,0],g[:,7])
 if not g_missing:
  assert len(g)<500000
  assert np.all((g[:,0]>=p[:,5])&(g[:,3]<=p[:,6]))
 assert len(p)<500000 and len(p)>120000
 # Exact algebra: charge advances due by prior count duration unless clipping.
 duration=p[:,0]*1000000000//23040000
 clipped=np.r_[0,p[1:,8]-p[:-1,8]-duration[:-1]]
 assert np.all(clipped>=0);assert np.all(clipped[1:]==np.maximum(0,p[1:,7]-p[:-1,8]-duration[:-1]-1000000))
 selected=np.where((p[:,7]>=start)&(p[:,7]<end))[0];a,b=selected[0],selected[-1]
 q=p[selected];h=None if g_missing else g[selected];clip=clipped[selected]
 # due(b)-due(a) = radio duration charged a..b-1 + discarded delay a+1..b
 elapsed=p[b,7]-p[a,7];radio=duration[a:b].sum();debt=clipped[a+1:b+1].sum();phase=(p[b,7]-p[b,8])-(p[a,7]-p[a,8])
 assert elapsed-radio==debt+phase
 stage={
 'output_room':q[:,2]-q[:,1],'align':q[:,3]-q[:,2],'input_wait':q[:,4]-q[:,3],
 'read':q[:,5]-q[:,4],'process':q[:,6]-q[:,5],'commit_telemetry':q[:,7]-q[:,6],
 'pacing_sleep':q[:,9]-q[:,7],'publish':q[:,10]-q[:,9],
 'process_thread_cpu':q[:,12]-q[:,11],
 'process_non_cpu':np.maximum(0,(q[:,6]-q[:,5])-(q[:,12]-q[:,11])),
 }
 if h is not None:
  stage.update({'gpu_h2d_event':h[:,4],'gpu_kernel_event':h[:,5],'gpu_d2h_event':h[:,6],
    'host_prepare':h[:,1]-h[:,0],'gpu_submit_wait':h[:,2]-h[:,1],'host_output':h[:,3]-h[:,2]})
 # Estimate processing cost per 23040 contiguous samples, respecting fragment boundaries.
 nominal=[]; pending=0;cost=0.
 for count,ns in zip(q[:,0],stage['process']):
  remain=int(count)
  while remain:
   take=min(remain,23040-pending); cost+=ns*take/count;pending+=take;remain-=take
   if pending==23040:nominal.append(cost);pending=0;cost=0.
 nominal=np.asarray(nominal)
 clips=[]
 for i in selected[clip>0]:
  # Charge interval leading to adjustment: previous throttle/push + loop gap + current stages.
  pieces={'previous_pacing_sleep':int(p[i-1,9]-p[i-1,7]),'previous_publish':int(p[i-1,10]-p[i-1,9]),'loop_gap':int(p[i,1]-p[i-1,10]),'output_room':int(p[i,2]-p[i,1]),'input_wait':int(p[i,4]-p[i,3]),'read_align':int(p[i,3]-p[i,2]+p[i,5]-p[i,4]),'process':int(p[i,6]-p[i,5]),'commit_telemetry':int(p[i,7]-p[i,6])}
  clips.append({'time_ns':int(p[i,7]),'discarded_us':float(clipped[i]/1000),'count':int(p[i,0]),'stages_us':{k:v/1000 for k,v in pieces.items()},'largest_stage':max(pieces,key=pieces.get),'process_cpu_us':float((p[i,12]-p[i,11])/1000),'gpu_event_us':None if g_missing else list(g[i,4:7]/1000)})
 bystage={}
 for x in clips:
  d=bystage.setdefault(x['largest_stage'],{'count':0,'discarded_us':0});d['count']+=1;d['discarded_us']+=x['discarded_us']
 out={'gpu_trace_missing':g_missing,'calls':len(selected),'elapsed_s':float(elapsed/1e9),'radio_s':float(radio/1e9),'fraction_realtime':float(radio/elapsed),'lost_progress_ms':float((elapsed-radio)/1e6),'discarded_pacing_ms':float(debt/1e6),'phase_difference_ms':float(phase/1e6),'clip_count':len(clips),'clip_largest_stage':bystage,'stage_us':{k:dist(v/1000) for k,v in stage.items()},'process_calls_gt_1ms':int(np.sum(stage['process']>1000000)),'process_calls_gt_5ms':int(np.sum(stage['process']>5000000)),'process_gt_own_sample_duration':int(np.sum(stage['process']>duration[selected])),'gpu_kernel_gt_1ms':None if g_missing else int(np.sum(h[:,5]>1000000)), 'nominal_process_us':dist(nominal/1000),'nominal_process_gt_1ms':int(np.sum(nominal>1000000)),'full_batch_calls':int(np.sum(q[:,0]==23040)),'total_process_s':float(stage['process'].sum()/1e9),'largest_clips':sorted(clips,key=lambda x:-x['discarded_us'])[:20]}
 out['slow_process_calls']=[]
 for j in np.where(stage['process']>1000000)[0]:
  out['slow_process_calls'].append({'time_ns':int(q[j,5]),'samples':int(q[j,0]),'stages_us':{k:float(v[j]/1000) for k,v in stage.items()}})
 output['nodes'][node]=out
 (trace/policy/f'{node}-clips.json').write_text(json.dumps(clips,indent=2)+'\n')
 print(node,'real time',out['fraction_realtime'],'lost ms',out['lost_progress_ms'],'clipped ms',out['discarded_pacing_ms'],'calls>1ms',out['process_calls_gt_1ms'])
 print('process',out['stage_us']['process'],'kernel',out['stage_us'].get('gpu_kernel_event'));print(bystage)
(trace/policy/'analysis.json').write_text(json.dumps(output,indent=2)+'\n')
