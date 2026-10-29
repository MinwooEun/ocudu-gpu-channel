from pathlib import Path
import json
P=Path(__file__).parent
D={k:json.loads((P/f'gap-{k}-attribution.json').read_text()) for k in ('yield','eight')};E=json.loads((P/'one-input-example.json').read_text());C=json.loads((P/'event-counts.json').read_text())
rows=[]
for key,lab in [('input_after_ready','입력 버퍼 준비 → producer 확인'),('reply_after_request','요청 수신 → 출력 row 확보'),('room_after_release','출력 공간 반환 → producer 확인')]:
 v=D['yield']['attribution'][key];d=v['us_per_radio_ms'];y=sum(x for n,x in d.items() if n.startswith('sched_yield_call:'));m=sum(x for n,x in d.items() if n.startswith('mutex_acquire:'));rows.append(dict(label=lab,total=v['total_us_per_radio_ms'],yield_call=y,mutex=m,pct=100*y/v['total_us_per_radio_ms']))
lines=['실제 함수 호출과 OS 이벤트를 연결한 추가 프로파일링','2026-10-29 / Spark / PR 원본 입력 / CUDA gNB + CPU srsUE','',
'결론: 재측정한 세 준비 후 지연에서는 wait_tick() → sched_yield() 호출의 복귀 지연이 약 95~97%였다. 해당 호출 내부의 OS 상태도 대부분 runnable 대기였다. mutex 획득이나 채널 계산이 이 세 구간의 주된 비용은 아니었다.','',
'이전 540/281/325 µs는 전체 측정 창의 경계 사이 시간이었다. 그 과거 기록에는 개별 mutex·scheduler 이벤트가 없어 사후에 원인을 정확히 복원할 수 없다. 이번에는 같은 PR 조건을 재실행하면서 함수 호출, mutex, scheduler를 동시에 계측했다. 아래 수치는 새 실행의 2초 관측 창에서 나온 값이며 과거 숫자에 원인을 소급해서 붙인 값이 아니다.','',
'실제 사례 — 설명용 모델이 아닌 원시 기록에서 복원한 한 번의 대기',
f'  0.000 µs: wait_tick()의 sched_yield() 호출 진입',
f'  {E["ready_us_from_yield"]:.3f} µs: 마지막 필요한 IQ가 입력 버퍼에 반영됐다는 marker',
f'  {E["return_us_from_yield"]:.3f} µs: sched_yield() 복귀',
f'  {E["confirm_us_from_yield"]:.3f} µs: producer가 처리 가능한 입력을 확인',
'따라서 IQ 입력 완료 기록 뒤 약 538 µs는 아직 sched_yield() 호출 안이었다. 복귀 후 확인까지 약 3 µs였다. 이 사례는 실제 벽시계 시간이며 무선 1 ms당 정규화 평균과 다른 단위다. 정확한 원시 monotonic 시각은 one-input-example.json에 있다.','',
'함수별 시간 분해 — 16 UE, 무선 시간 1 ms당 누적 µs',
'구간 / 전체 / sched_yield 호출 내부 / mutex 획득 / 호출 내부 비중']
for r in rows:lines.append(f'{r["label"]} / {r["total"]:.3f} / {r["yield_call"]:.3f} / {r["mutex"]:.3f} / {r["pct"]:.1f}%')
lines+=['mutex 획득은 lock() 진입부터 실제 획득까지다. mutex를 가진 채 버퍼 메타데이터를 검사한 시간은 별도 context로 기록했다. sched_yield 호출 안의 CPU 실행 시간, runnable 대기, blocked 상태도 별도 분해했다. 전체 교차표는 gap-yield-attribution.json에 있다.','',
'어떤 코드가 실행되는가?',
'  입력이 부족하면: 입력 ring별 mutex 획득 → next sequence/cursor 검사 → 공통 입력이 없으면 wait_tick() → sched_yield().',
'  응답 row가 없으면: 출력 mutex 획득 → rx_slots 확인 → 비어 있으면 wait_tick() → sched_yield().',
'  출력 공간이 없으면: 출력 mutex 획득 → occupancy/high-water 확인 → 공간이 없으면 wait_tick() → sched_yield().',
'기준 구현은 이 세 경로에서 데이터 도착을 기다리는 notification을 등록하지 않는다. sched_yield()는 CPU를 양보하고도 runnable 상태에 남는 동작을 이 실행에서 보였다. 그 사이 입력이나 공간이 준비돼도 다음 확인은 해당 스레드가 CPU를 다시 받아 호출에서 복귀한 뒤에 한다.','',
'무엇 때문에 복귀가 지연됐는가?',
'같은 시계의 sched_switch와 sched_wakeup에서 실제로 CPU를 받지 못한 runnable 구간을 확인했다. CPU 15/16에서는 다른 receiver의 producer, reply worker, ZMQ I/O 등이 실행됐다. 두 CPU는 이 2초 창에서 합계 약 4 CPU초를 사용했다.',
'이 창의 CPU 실행 분배: producer 합계 1.542 CPU초, reply 0.480, ZMQ I/O 1.321, 나머지 0.657. 모두 두 CPU의 합계다. 특정 스레드 하나의 지연과 더하면 안 된다. 나머지를 전부 control 연산이라고 부르지는 않는다.',
'CPU에서 실제로 수행한 연산과 준비 후 실행 대기를 구분할 수 있으며, 적어도 위 세 구간의 대부분은 무거운 IQ 연산이나 오래 걸린 mutex 획득이 아니라 sched_yield 복귀 대기였다.','',
'UE 수에 따른 경계 비교 — 동일한 계측과 PR 당시 각 UE 수의 원본 입력',
'8 UE: 진행률 0.913269, KPI 유효 30/30. 16 UE: 진행률 0.432455, KPI 유효 5/30.',
'입력 준비 후 지연:']
for key,lab in [('eight','8 UE'),('yield','16 UE')]:
 d=D[key];v=d['attribution']['input_after_ready'];y=sum(x for n,x in v['us_per_radio_ms'].items() if n.startswith('sched_yield_call:'));sw=sum(C[key]['switches'].values());lines.append(f'  {lab}: 전체 {v["total_us_per_radio_ms"]:.3f} µs, sched_yield 내부 {y:.3f} µs/무선 ms. 관측된 처리량 {d["radio_ms"]:.3f} radio ms. 두 CPU의 스케줄 전환 {sw}건, 무선 ms당 {sw/d["radio_ms"]:.1f}건.')
lines+=['8→16 UE에서 relay 작업자는 27→51개로 늘지만 broker는 같은 두 big core를 사용한다. 이 관측 창에서는 무선 시간당 스케줄 전환이 약 229→431건으로 증가했고 입력 준비 후 yield 복귀 지연도 커졌다. 이 결과는 UE 수 축의 host-side handoff 병목을 뒷받침한다. 대역폭·안테나·셀 수의 모든 경계를 같은 원인으로 확정한 것은 아니다.','',
'검증 방법과 조건',
'PR 원본 g121(16 UE) / g120(8 UE) bundle을 재생했다. UE GPU 구현은 사용하지 않았다. CUDA gNB 가속 옵션, MPS, UE·gNB CPU 배치, 채널·트래픽·샘플 속도는 해당 기준과 동일하다.',
'CLOCK_MONOTONIC 기반의 코드 marker와 독립 tracefs instance의 mono clock으로 sched_switch/wakeup을 수집했다. producer/reply 이름과 /proc thread map으로 namespace TID와 kernel TID를 연결했다.',
'각 source mutex의 lock() 전후와 소유 구간을 계측하고, wait_tick의 실제 sched_yield 호출 전후를 추가로 계측했다. prepare/room/pop 단계와 같은 IQ 누적 샘플 번호에 대응시켰다.',
'스케줄러 기록은 per-CPU overrun와 dropped events 0, wire 기록도 dropped 0이다. 수집 경계에서 잘린 첫·마지막 구간을 제외하고 계산했다. 계측·기록 자체의 CPU 사용은 실행 중 코드 시간에 포함된다.',
'첫 16 UE 재측정은 0.433759, 직접 yield 호출 계측 반복은 0.432455로 기존 약 0.45 저하를 재현했다. 관측 창은 2초이므로 전체 30 radio seconds의 평균과 수치가 달라질 수 있다.','',
'개선 실험과 한계',
'이전에 시행한 알림 방식 probe는 실제 live 성능 개선에 실패했다. 이번에 특정한 호출을 바꾸면 곧바로 실시간이 된다는 뜻은 아니다. 작업자 수와 실행 배정, I/O와 GPU 완료 처리의 CPU 예산을 함께 검증해야 한다.',
'추가 혼합-core 배치 탐색은 broker 허용 CPU를 0–4,15–16으로 넓혔으나 진행률 0.203505로 악화했다. 새 core들은 little core이고 보조 작업·분석 프로세스와 공유했으므로 순수 core 수만의 통제 실험으로 사용하지 않는다. 해당 결과와 raw 기록을 제외하지 않고 보존했다.',
'16 UE에는 UE별 KPI 누락과 starvation이 남는다. 정상 16 UE 실시간 운용을 입증하는 결과가 아니라 실패하는 PR 조건에서 지연 메커니즘을 특정한 결과다.',
'459 µs 송수신 구간 내부의 복사·I/O 처리 등을 모두 개별 함수로 분해했다는 주장은 하지 않는다. 이번 추가 작업의 직접 검증 대상은 사용자가 지목한 세 준비 후 지연이다.','',
'근거와 재현',
'broker-deep-yield.cpp: 원본 broker에 직접 호출·mutex 계측과 스레드 식별만 추가한 별도 빌드.',
'deep_trace.h / mutex-sites.json: 기록 형식과 각 mutex source 위치.',
'gap-yield-attribution.json / gap-eight-attribution.json: 코드 context × OS 상태 교차표.',
'one-input-example.json: 실제 한 지연의 네 경계 시각.',
'event-counts.json / *scheduler-stats.json: 호출 수·스케줄 전환·기록 손실.',
'capture*.py / analyze_sched.py / analyze_gaps.py / run.py: 수집·분석·PR 입력 재생 코드.',
'원시 기록은 spark-minwoo:/workspace/gpuch/profile-20261029-deep 에 보존한다. production 소스와 기본 설정은 바꾸지 않았다.']
(P/'function-attribution.ko.txt').write_text('\n'.join(lines)+'\n');(P/'function-summary.json').write_text(json.dumps({'rows':rows,'example':E,'eight_radio_ms':D['eight']['radio_ms'],'sixteen_radio_ms':D['yield']['radio_ms']},ensure_ascii=False,indent=2))
