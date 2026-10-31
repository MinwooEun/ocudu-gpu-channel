import pathlib,json,numpy as np,collections,hashlib,shutil
base=pathlib.Path('/workspace/gpuch/gnb-source-delay-20261031');root=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030/u1');e=base/'evidence';e.mkdir(exist_ok=True);old=root/'original-cv-rx-logger-r4';dt=np.dtype([(s,'<i8') for s in ['op','tid','port','flags','start','end','result','error']]);pcs={0x1b6222c:'flush_pending_output -> wait_event_yielding',0x18e0868:'cudaEventSynchronizeYielding (PUSCH)'};bias=0xb48143f40000;events=[]
for f in (old/'raw/wire').glob('gnb-*.wire'):
 h=np.fromfile(f,dtype='<u8',count=8);assert h[3]==0
 if not h[1]:continue
 a=np.memmap(f,dtype=dt,offset=64,shape=(int(h[1]),))
 for y in a[(a['op']==40)&(a['start']>=3113585630000000)&(a['start']<=3113585700000000)]:
  offset=int(y['result'])-bias
  if offset not in pcs:continue
  events.append(dict(tid=int(y['tid']),start_ns=int(y['start']),end_ns=int(y['end']),yield_us=(int(y['end'])-int(y['start']))/1000,cpu_before=int(y['flags'])>>16,cpu_after=int(y['flags'])&65535,caller_return_pc=hex(int(y['result'])),elf_offset=hex(offset),function=pcs[offset]))
(e/'historical-43ms-yields.json').write_text(json.dumps(dict(load_bias=hex(bias),events=events,counts=dict(collections.Counter(v['function'] for v in events)),total_yield_us=sum(v['yield_us'] for v in events),limitation='This historical run captured yield intervals and caller PCs, but not scheduler ownership. Peer ownership is established by the new controlled co-location experiment.'),indent=2)+'\n')
paths=['lib/phy/cuda/src/low_phy_tx.cu','lib/phy/upper/channel_processors/pusch/pusch_demodulator_gpu_impl.cpp','lib/phy/upper/channel_coding/ldpc/cuda/cuda_rt_utils.h','apps/services/worker_manager/worker_manager.cpp'];src=pathlib.Path('/workspace/ocudu-spark-ranb/src/ocudu-cuda-d10');out={}
for rel in paths:
 f=src/rel;s=f.read_text();lines=s.splitlines();matches=[i for i,l in enumerate(lines) if 'wait_event_yielding(' in l or 'inline cudaError_t cudaEventSynchronizeYielding(' in l or 'create_prio_worker("phy_worker"' in l];out[rel]=dict(sha256=hashlib.sha256(f.read_bytes()).hexdigest(),excerpts=[dict(line=i+1,text='\n'.join(lines[max(0,i-2):i+18])) for i in matches[:4]])
(e/'source-evidence.json').write_text(json.dumps(out,indent=2)+'\n')
for name in ['original-gnb-root-1031-r1','original-gnb-root-1031-r2','original-gnb-root-1031-unrestricted-r3','original-gnb-root-1031-shared-r4','original-gnb-root-1031-separate-r5']:
 p=root/name;d=e/name;d.mkdir(exist_ok=True)
 for item in ['launch.json','result.json','rate-analysis.json','gnb-capture.json','core-mode.json','core-analysis.json','interference.json','gnb-observer.log','gnb-functions-perf.log','gnb-cpu-perf.log']:
  f=p/item
  if f.exists():shutil.copy2(f,d/(item[:-4]+'.txt' if item.endswith('.log') else item))
 (d/'raw-index.json').write_text(json.dumps(dict(remote_case=str(p),files=[dict(file=str(f.relative_to(p)),size=f.stat().st_size) for f in (p/'raw').rglob('*') if f.is_file()]),indent=2)+'\n')
print('Historical yield count',len(events),'sum_us',sum(v['yield_us'] for v in events))
