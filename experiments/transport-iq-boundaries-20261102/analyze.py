import pathlib,json,csv,collections,statistics,hashlib,gzip
E=pathlib.Path(__file__).resolve().parent
allrows=[];provenance={}
for h in ['rtx','spark']:
 d=json.loads((E/'evidence'/h/'summary.json').read_text());allrows+=d['rows'];provenance[h]=json.loads((E/'evidence'/h/'provenance.json').read_text())
primary=[r for r in allrows if r['primary']];assert len(primary)==168;assert all(r['health'] and r['initialized_before_window'] for r in primary)
# Compare common topology bytes across both hosts, separately from binary architecture.
configs={}
for host in ['rtx','spark']:
 v={}
 for f in (E/'evidence'/host).glob('*.json.gz'):
  with gzip.open(f,'rt') as fp:d=json.load(fp)
  m=d['launch'];key=(m['ues_per_cell'],m['cells'],m['bandwidth_mhz'],m['ports']);v[key]=m['config_sha256']
 configs[host]=v
common=set(configs['rtx'])&set(configs['spark']);assert all(configs['rtx'][k]==configs['spark'][k] for k in common)
checks=dict(primary_cases=len(primary),total_retained_cases=len(allrows),all_primary_application_protocol_health=True,all_primary_initialized_before_window=True,common_topology_configurations=len(common),common_topology_sha256_identical=True,backend_members_unchanged={h:p['unchanged_backend_members'] for h,p in provenance.items()},changed_archive_members={h:p['changed_archive_members'] for h,p in provenance.items()},iq_zero_copy={h:sorted({r['cuda_zero_copy'] for r in primary if r['host']==h and r['mode']=='iq'}) for h in ['rtx','spark']})
(E/'identity-and-validity.json').write_text(json.dumps(checks,indent=2))
fields=['host','mode','resource_profile','ues_per_cell','cells','bandwidth_mhz','sample_rate_hz','ports','label','min_coverage','min_endpoint_ratio','min_completed_batches','expected_batches','cadence_covered_with_one_boundary_batch','strict_deadline_clean','initialized_before_window','measured_rebases']
with (E/'measurements.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore',lineterminator='\n');w.writeheader();w.writerows(primary)

def dimension(r,axis):
 if axis=='ues' and r['cells']==1 and r['bandwidth_mhz']==20 and r['ports']==1:return r['ues_per_cell']
 if axis=='cells' and r['ues_per_cell']==4 and r['bandwidth_mhz']==20 and r['ports']==1:return r['cells']
 if axis=='bandwidth' and r['ues_per_cell']==4 and r['cells']==1 and r['ports']==1:return r['bandwidth_mhz']
 if axis=='ports' and r['ues_per_cell']==1 and r['cells']==1 and r['bandwidth_mhz']==20:return r['ports']
 return None
curves={};replicated=[]
for h in ['rtx','spark']:
 for mode in ['iq','radio']:
  for axis in ['ues','cells','bandwidth','ports']:
   grouped=collections.defaultdict(list)
   for r in primary:
    x=dimension(r,axis)
    if r['host']==h and r['mode']==mode and x is not None:grouped[x].append(r)
   data=[]
   for x,rr in sorted(grouped.items()):
    vals=[r['min_coverage'] for r in rr];item=dict(x=x,replicates=len(rr),minimum=min(vals),median=statistics.median(vals),maximum=max(vals),cadence_passes=sum(r['cadence_covered_with_one_boundary_batch'] for r in rr),zero_deadline_miss_runs=sum(bool(r['strict_deadline_clean']) for r in rr),labels=[r['label'] for r in rr]);data.append(item)
    if len(rr)>=3:replicated.append(dict(host=h,mode=mode,axis=axis,**item))
   curves[(h,mode,axis)]=data
(E/'curves.json').write_text(json.dumps([dict(host=h,mode=m,axis=a,points=v) for (h,m,a),v in curves.items()],indent=2))
(E/'replicated-points.json').write_text(json.dumps(replicated,indent=2))
# A measured transition interval, rather than a fictitious integer maximum.
transitions={
 'rtx':{'iq':{'ues':'31–32','cells':'7–8','bandwidth':'100 MHz까지 확인','ports':'15–16'},'radio':{'ues':'10–11 (mixed)','cells':'2–3 (2도 mixed)','bandwidth':'50–100 MHz','ports':'8–9 (9 mixed)'}},
 'spark':{'iq':{'ues':'56–57 (mixed)','cells':'12–13 (13 mixed)','bandwidth':'100 MHz까지 확인','ports':'10–11'},'radio':{'ues':'7–8 (mixed)','cells':'2–3 (2도 mixed)','bandwidth':'50–100 MHz (50도 mixed)','ports':'5–6 (6 mixed)'}}}
fast=[r for r in allrows if r['resource_profile']=='all-fast-iq-ready'];controls=[r for r in allrows if r['resource_profile']=='counter-off-radio']
conclusion=dict(configuration=dict(channel='static deterministic8-tap TDL+receiver AWGN',measurement_s=8,warmup_s=2,channel_cpus='5 fast cores on each host',default='1cell,20MHz,1x1',cells_axis='4UEs/cell,1broker',bandwidth_axis='4UEs,1cell,1x1;20/50/100MHz→23.04/61.44/122.88MS/s,1/1/0.5ms batch',ports_axis='1UE,1cell,20MHz; raw symmetric radio port matrix, not NR rank/layers'),counts=dict(primary=len(primary),controls=len(fast)+len(controls),preflight=len(allrows)-len(primary)-len(fast)-len(controls)),transition_intervals=transitions,all_fast_64={h:dict(cpus='P0-7' if h=='rtx' else 'X9255-9,15-19',ratios=[r['min_coverage'] for r in fast if r['host']==h]) for h in ['rtx','spark']},definitions={'progress':'Completed IQ samples / (nominal sample rate × measured wall duration), worst RX port/node. Not success/attempt counts.','cadence_coverage':'Expected publications minus one finite-window boundary batch (one batch can straddle the window edge); exact ratios are retained.','deadline_misses':'IQ late completion or radio pacer rebase/call exceeding its batch budget, reported separately. Cadence coverage does not imply zero deadline misses.','transition':'Repeated-run turnover region under the stated hardware/CPU/model/window; mixed results are not a hard maximum.'},limitations=['Synthetic ZMQ peers do not execute OCUDU radio_zmq or srsUE RF/PHY/MAC; live-stack validation remains the earlier, separately indexed experiment.','Static TDL isolation workload differs from the live moving Sionna control replay.','CPU masks allow execution on those cores; cores were not reserved from OS/desktop/background tasks.','Different host architectures, peer CPU pools,drivers and automatic GPU host-memory routes; not an isolated GPU-silicon comparison.','No device-kernel or scheduler-stack causal attribution is claimed from process call/wait-region wall times.'],artifacts=['measurements.csv','curves.json','scaling-curves.png','radio-stage-comparison.png','evidence/'])
(E/'conclusions.json').write_text(json.dumps(conclusion,indent=2))
# Plots use only initialization-certified primary cases, with every observed range.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
colors={('rtx','iq'):'#1261a0',('rtx','radio'):'#14a3b8',('spark','iq'):'#df8a18',('spark','radio'):'#c3423f'}
labels={('rtx','iq'):'RTX 5090 · IQ only',('rtx','radio'):'RTX 5090 · ZMQ only',('spark','iq'):'Spark GB10 · IQ only',('spark','radio'):'Spark GB10 · ZMQ only'}
fig,axs=plt.subplots(2,2,figsize=(12,8.4));titles={'ues':'UEs per cell · 20 MHz, 1 cell, 1×1','cells':'Independent cells · 4 UEs/cell, 20 MHz, 1×1','bandwidth':'Bandwidth workload · 4 UEs, 1 cell, 1×1','ports':'Ports at both radios · 1 UE, 20 MHz'}
for ax,axis in zip(axs.flat,['ues','cells','bandwidth','ports']):
 for h in ['rtx','spark']:
  for mode in ['iq','radio']:
   d=curves[(h,mode,axis)];x=[v['x'] for v in d];y=[v['median'] for v in d];lo=[v['minimum'] for v in d];hi=[v['maximum'] for v in d];ax.plot(x,y,marker='o',markersize=3,linewidth=1.5,color=colors[(h,mode)],linestyle='-' if mode=='iq' else '--',label=labels[(h,mode)]);ax.fill_between(x,lo,hi,color=colors[(h,mode)],alpha=.13)
 ax.axhline(1,color='#606060',linewidth=.8,linestyle=':');ax.set_ylim(0,1.045);ax.set_title(titles[axis],fontsize=10);ax.grid(alpha=.17);ax.set_ylabel('Worst RX sample progress / wall time')
 if axis in ['ues','cells']:ax.set_xscale('log',base=2);ticks=[1,4,8,16,32,64] if axis=='ues' else [1,2,4,8,16];ax.set_xticks(ticks,[str(x) for x in ticks])
 if axis=='bandwidth':ax.set_xticks([20,50,100]);ax.set_xlabel('MHz → corresponding live-radio sample/batch recipe')
 if axis=='ports':ax.set_xticks([1,2,4,8,12,16]);ax.set_xlabel('Raw channel matrix ports; not NR spatial layers')
handles,lab=axs[0,0].get_legend_handles_labels();fig.legend(handles,lab,loc='lower center',ncol=2,frameon=False,bbox_to_anchor=(.5,.035));fig.suptitle('Channel-emulator scaling: processing vs synthetic ZMQ transport',fontsize=14);fig.text(.5,.014,'5 fast CPU cores for channel · static 8-tap TDL · 2 s warmup + 8 s measurement · bands show repeated-run ranges · deadline misses separate',ha='center',fontsize=8);fig.tight_layout(rect=(0,.11,1,.95));fig.savefig(E/'scaling-curves.png',dpi=180);fig.savefig(E/'scaling-curves.pdf');plt.close(fig)
fig,ax=plt.subplots(figsize=(10,5));stages=[('room_mean_us','Output-space interval','#2677a4'),('data_mean_us','Input-ready interval','#e2aa3b'),('read_mean_us','Read/copy from input rings','#9474b9'),('process_mean_us','Channel function call','#54a877')];bases=[0.,0.];stage_rows=[]
for h in ['rtx','spark']:
 r=next(r for r in primary if r['host']==h and r['mode']=='radio' and r['ues_per_cell']==32 and r['cells']==1 and r['ports']==1 and r['bandwidth_mhz']==20 and '-r1' in r['label']);g=next(x for x in r['nodes'] if x['node']=='gnb0');stage_rows.append((h,r,g))
for key,label,color in stages:
 v=[g[key]/1000 for h,r,g in stage_rows];ax.bar([0,1],v,bottom=bases,label=label,color=color);bases=[a+b for a,b in zip(bases,v)]
ax.axhline(1,color='#a82424',linestyle='--',linewidth=1,label='1 ms publication period');ax.set_xticks([0,1],['RTX 5090','Spark GB10']);ax.set_ylabel('Mean interval per gNB RX block (ms)');ax.set_title('32 UEs · synthetic ZMQ · one 8 s trial · gNB producer stages');ax.legend(loc='upper right',fontsize=8);ax.set_ylim(0,4.5);ax.grid(axis='y',alpha=.15);fig.text(.5,.025,'Intervals include descheduling; channel call includes CPU preparation, transfers, GPU work and synchronization. Excludes pacing/push/bookkeeping.',ha='center',fontsize=8);fig.tight_layout(rect=(0,.06,1,1));fig.savefig(E/'radio-stage-comparison.png',dpi=180);fig.savefig(E/'radio-stage-comparison.pdf');plt.close(fig)
# Plain-language standalone report, with no private milestone shorthand.
lines=['채널 에뮬레이터 격리 스케일링 검증 — RTX 5090 / Spark GB10','',f'정식 {len(primary)}회, 추가 대조 {len(fast)+len(controls)}회. 초기 측정창/동작 확인 자료 {conclusion["counts"]["preflight"]}회는 별도 보존했다.','', '이번에 비교한 세 가지 실행 범위','라이브 스택: 이전 실험의 실제 CUDA gNB + CPU srsUE + 코어/트래픽.','ZMQ-only: PHY/MAC 없이 가상 IQ 송수신기가 raw cf32 REQ/REP로 같은 채널 에뮬레이터에 연결된다. OCUDU radio_zmq 클래스나 srsUE RF 구현 자체를 분리 실행한 결과는 아니다.','IQ-only: 메모리 IQ를 같은 ChannelProcessor 함수에 전달한다. CPU 준비, CPU↔GPU 전달, GPU 처리와 반환·동기화를 포함한다.','', '비교 조건','채널 처리 CPU는 장비마다 빠른 코어5개로 고정했다. RTX P0-4, Spark X9255-9. 코어는 OS/다른 작업으로부터 예약하지 않았다.','IQ와 ZMQ는 같은 정적8-tap TDL/수신 AWGN, 토폴로지와 CUDA backend object를 쓴다. 라이브 moving-Sionna replay와는 다른 격리 부하다.','기본1cell/20MHz/1×1. 셀 축은4UE/cell·단일broker·셀 간 간섭 없음. BW 축은4UE, 안테나 축은1UE에서 양쪽 동일 raw포트 수를 늘린다.','20/50/100MHz는 라이브 레시피에 대응하는23.04/61.44/122.88MS/s와1/1/0.5ms 배치를 쓴다. 독립 샘플레이트 sweep은 하지 않았다.','모든 정식 IQ worker는 실제 첫 CUDA 호출 완료를 확인한 뒤2초 워밍업과8초 측정을 시작했다. ZMQ는 모든 포트가 워밍업 중 IQ를 생산했음을 로그로 확인했다.','', '처리량 전이 구간 — 확정된 최대값으로 읽지 않는다','축 | RTX IQ-only | RTX ZMQ-only | Spark IQ-only | Spark ZMQ-only']
for axis,name in [('ues','UE 수'),('cells','셀 수'),('bandwidth','대역폭'),('ports','양쪽 포트 수')]:lines.append(name+' | '+' | '.join(transitions[h][m][axis] for h,m in [('rtx','iq'),('rtx','radio'),('spark','iq'),('spark','radio')]))
lines+=['','mixed는 같은 점의 반복 실행에서 처리량 판정이 갈렸다는 뜻이다. 정확한 비율과 통과 횟수는 replicated-points.json에 전부 남겼다.','UE 축에서3회 모두 처리량 기준을 만족한 확인점: RTX IQ31UE, RTX ZMQ8UE, Spark IQ48UE, Spark ZMQ4UE. 이것을 최대값 또는 deadline0회 보장으로 확대하지 않는다.','', '진행률과 deadline을 구분하는 이유','진행률 = 완료한 IQ 샘플 / (샘플레이트 × 측정 wall time), 모든 RX 중 최저값이다. 성공횟수/시도횟수가 아니다.','8초 공통 창의 시작/끝에 한 배치가 걸칠 수 있으므로 처리량 판정은 expected_batches-1을 명시적으로 허용한다. 20MHz에서는7999/8000=0.999875다. 이 값은 부동소수점 오차가 아니다.','별도로 IQ의 예정 시각 초과 완료, ZMQ producer의 pacing rebase와1배치 예산 초과 함수 호출을 기록했다. 처리량1.000과 deadline위반0회는 서로 다른 결과다.','', '64UE 확인 — 모든 수신 노드를 함께 처리','추가로 RTX의 P코어8개와 Spark의 X92510개를 사용해64UE IQ-only를3회씩 실행했다.']
for h in ['rtx','spark']:lines.append(h+': '+', '.join(f'{r["min_coverage"]:.9f}' for r in fast if r['host']==h))
lines+=['이번64UE 구성은 전체65개 RX노드를 함께 처리한다. 예전 fan-in 자료의 gNB 단일 호출 P99 그래프는 전체 노드가 매 주기 처리되었다는 증거가 아니다.','참고 원문: /home/minwoo/ocudu-work/ocudu-upstream-main/docs/reports/performance/2026-10-13-fanin/README.md — sequential calling, per-gNB call latency,1ms reference is not a passed deadline test를 명시한다.','', '32UE ZMQ에서 실제로 시간이 걸린 위치','아래는 gNB producer의 측정 구간 평균이며, 순수 GPU 커널 시간이 아니다.']
for h,r,g in stage_rows:
 brokercpu=sum(v['average_cores'] for v in r['cpu_usage'].values() if v['comm'].startswith('ocudu'))
 lines.append(f'{h}: 출력공간 확보 구간 {g["room_mean_us"]:.3f}us, 입력준비 구간 {g["data_mean_us"]:.3f}us, 링 읽기 {g["read_mean_us"]:.3f}us, 채널 함수 {g["process_mean_us"]:.3f}us. 함수 내부 thread CPU {g["process_cpu_mean_us"]:.3f}us. Broker 평균 CPU {brokercpu:.3f}/5코어.')
lines+=['구간 wall time에는 스레드가 실행되지 못한 시간도 들어간다. 출력 버퍼가 그 시간 내내 차 있었다거나, GPU 커널이 함수 전체 시간을 썼다고 바꿔 읽지 않는다.','확인된 점은 PHY/MAC이 없는 조건에서도 처리량 손실이 생기고,32UE에서 emulator CPU할당이 거의 찼다는 것이다. RTX는 채널 함수 구간이1ms를 넘고, Spark는 출력공간/입력준비 구간이 큰 비중을 차지했다.','CUDA 자동 host-memory 모드는 RTX copy, Spark zero-copy로 실제 실행됐음을 IQ 로그에서 확인했다. 이를 GPU 코어 성능만의 비교로 읽지 않는다.','', '계측 영향 확인','같은 broker 실행파일에서 메모리 카운터를 끈 UE 경계 양쪽 및16UE 실행을 장비마다6회 진행했다. 작은 손실은 반복 변동이 있었고,16UE 처리량 손실은 카운터OFF에서도 유지됐다.']
for h in ['rtx','spark']:
 lines.append(h+' counter-OFF: '+', '.join(f'{r["ues_per_cell"]}UE={r["min_coverage"]:.9f}' for r in controls if r['host']==h))
lines+=['','보존/검증','기존 라이브 검증 실행파일·상위 소스·HTML은 수정하지 않았다. Broker 계측은 broker.cpp.o만 교체했고, CUDA backend를 포함한 나머지12개 archive member가 동일함을 검증했다.','가상 송신 IQ의 캐시화는 실제 ZMQ로 기존 송신기와16,220,160bytes를 비교해 일치했다.','정식 실행은 전부 application/peer health와 초기화 확인을 통과했다. Broker의 ZMQ 오류/queue overflow/sequence gap0은 원본 stop counter에 남아 있다.','measurements.csv: 정식 전체 수치. curves.json / replicated-points.json: 반복 범위. evidence/{rtx,spark}/*.json.gz: 회차별 설정/결과/CPU요약/원본 경로.','로컬 원본: /home/minwoo/ocudu-work/transport-iq-boundaries-20261102','Spark 원본: /workspace/gpuch/transport-iq-boundaries-20261102','원본 source-call / GPU kernel / scheduler 세부 원인의 분리는 별도 계측이 필요한 범위이며 이번 처리량 경계 결과와 구분한다.']
(E/'findings.ko.txt').write_text('\n'.join(lines)+'\n')
print(json.dumps(checks,indent=2));print('exported plots, CSV and report')
