from pathlib import Path
import json,html
P=Path(__file__).parent
load=lambda n:json.loads((P/n).read_text())
g=next(x for x in load('decompose-pr10-trace-repeat.json') if x['node']=='gnb0');w=g['wire_parts_us_per_radio_ms'];r=load('room-pr10-trace-repeat.json')['parts_us_per_radio_ms'];b=next(x for x in load('budgets-pr10-trace-repeat.json') if x['node']=='gnb0')['us_per_radio_ms'];s=load('thread-budget-trace-repeat-steady.json');t=next(x for x in s['threads'] if x['role']=='producer:gnb0');cases=load('pr10-summary.json')
internal=w['ring_ready_to_producer']+r['request_received_to_row_pop']+r['room_released_to_producer_observed'];total=sum(v for k,v in b.items() if k not in ('data_cpu_us','room_cpu_us'))
lines=['PR10 Spark 16 UE: IQ 생성·전달·소비 경로의 병목 분석','2026-10-29 / 최종 근거: pr10-frozen/trace-repeat','',
'이번에 특정한 큰 병목은 emulator 내부 CPU 실행 및 IQ 전달 지연이다. GPU 채널 함수가 빠르다는 사실만으로 emulator 프로세스 전체에 병목이 없다고 판단할 수 없었다.',
'필요한 IQ, 수신 요청, 출력 공간이 이미 준비된 뒤에도 내부 작업이 이어지지 않는 시간이 이 producer의 측정 시간 중 약 절반을 차지했다. ZMQ 라이브러리 자체가 모든 지연의 원인이라는 결론은 성립하지 않는다.','',
'1. 실제 PR 조건 확인',
'기준은 PR10의 g121(tagged-cd10-16ue-20261026T124817Z-g121)이다. gNB는 5830c9cb + C1/D8/D9/D10, CUDA all, sm_121, broker와 같은 MPS 서버이다. UE는 CPU srsUE eea87b1d8 + NEON LDPC/RA/RAR/rx_sleep 패치이며 UE GPU 구현을 사용하지 않았다.',
'현재 CPU srsUE SHA-256은 PR 실험 전 빌드 로그와 동일하다: 0e32b703176460d387b1abdeac7984fa983062448203064144e83768ea3fff74. gNB 패치의 해시와 reverse-check도 lock과 일치한다.',
'20 MHz, 23.04 MS/s, 1 cell, 1×1, 16 UE, mixed traffic, RR/HARQ-OLLA, seed 20261016. CPU 배치는 gNB 5–12, broker 15–16, UE 13/14/17–19이며 개별 UE 배치도 PR과 같다. warm-up 10 radio seconds와 측정 30 radio seconds를 유지했다.',
'최종 비교에서는 같은 시드로 생성한 새 채널 대신 PR g121의 보존된 채널·트래픽 bundle을 그대로 재생했다. 모든 입력 파일의 해시를 검증했다. 로그 출력 경로와 동등한 숫자 표기(-55/-55.0), 설명용 benchmark metadata 추가는 RF 동작 차이가 아니다.','',
'2. 시간의 단위와 계측 방법',
'이하 µs는 별도 표시가 없으면 gNB-bound producer에서 무선 시간 1 ms를 진행시키는 데 누적된 시간이다. 한 GPU 호출의 시간이 아니다. 최종 반복에서는 30,000 radio ms를 56,669회에 나누어 처리했다.',
'모든 프로세스는 같은 Spark의 CLOCK_MONOTONIC을 사용했다. 성공한 ZMQ 메시지를 endpoint와 순서, IQ 바이트 수로 대응시키고, 누적 샘플 번호를 broker의 ring push와 producer window에 연결했다. warm-up 뒤의 실제 measurement sample 구간만 집계했다.',
'wire 기록 손실 0, 16 UE 입력 메시지 샘플 수 대응, broker sequence gap 0, 시간 분해 합계를 검증했다. 이는 IQ 샘플 내용의 독립적 RF 정확성 검증을 새로 수행했다는 뜻은 아니다.',
'UE 송신 준비 경계는 rf_zmq의 송신 함수 안에서 TX request receive에 진입한 시점이다. 실제 파형이 준비된 이후의 경계이며, 이전 구간을 순수 PHY 계산 시간으로 부를 수 없다. 이전 DL 수신 대기, PHY 처리와 스케줄링 등이 포함될 수 있다.','',
'3. 입력 대기 분해 — 이전에 하나로 묶였던 대기',
]
for label,key in [('UE가 송신 준비 경계에 도달하기 전','source_not_yet_at_send_boundary'),('준비 경계 이후 send 진입까지','source_ready_to_send'),('IQ send 진입 → broker receive 반환','send_to_receiver_return'),('receive 반환 → 입력 ring 반영','receiver_return_to_ring'),('모든 필요한 입력 ring 준비 → producer 확인','ring_ready_to_producer')]:lines.append(f'  {label}: {w[key]:.3f} µs')
lines += [f'  합계 입력 대기: {b["data_us"]:.3f} µs',
'마지막 540 µs에서는 필요한 입력이 이미 도착해 있었다. 따라서 이 시간을 UE 계산이나 ZMQ 전송 시간으로 설명할 수 없다.',
'send→receive의 459 µs는 ZMQ 큐·I/O 처리·TCP loopback·수신 스레드 스케줄링을 포함한 구간이다. memcpy 또는 순수 wire 시간만을 따로 측정한 값이 아니다.','',
'4. 출력 공간 대기 분해',]
for label,key in [('gNB가 요청을 보내기 전','before_gnb_request'),('요청 send → broker 요청 receive','request_to_broker_receive'),('요청 수신 후 출력 row를 꺼내기까지','request_received_to_row_pop'),('row 꺼냄 → 송신 및 공간 반환','row_pop_to_send_and_release'),('공간 반환 → producer 확인','room_released_to_producer_observed')]:lines.append(f'  {label}: {r[key]:.3f} µs')
lines += [f'  합계 출력 공간 대기: {b["room_us"]:.3f} µs',
'출력 공간이 찬 상태에서 이미 존재하던 row를 처리하는 구간을 추적했다. gNB가 요청을 늦게 보낸 시간은 약 1 µs였다. 대부분은 broker 내부 응답·재개 지연이었다.',
'ring 해제 후 hop marker를 기록하기 전에 스레드가 선점될 수 있다. 분석은 marker가 producer 확인보다 늦으면 경계에서 잘라서 사용하므로, 반환 후 지연은 보수적인 귀속이다. 원시 marker race와 clipping은 JSON에 남겼다.','',
'5. 계산인가, CPU 실행 대기인가?',
f'입력 대기 {b["data_us"]:.3f} µs 중 해당 스레드의 실제 CPU 사용은 {b["data_cpu_us"]:.3f} µs였다. 출력 공간 대기 {b["room_us"]:.3f} µs 중 CPU 사용은 {b["room_cpu_us"]:.3f} µs였다.',
f'정상 측정 구간의 독립적인 /proc schedstat 관측 창은 {(s["end_ns"]-s["start_ns"])/1e9:.6f}초이다. 같은 gNB-bound producer는 CPU 실행 {t["cpu_ns"]/1e9:.6f}초, runnable 상태의 CPU 차례 대기 {t["runnable_ns"]/1e9:.6f}초를 기록했다.',
'CPU를 쓰지 않은 시간에는 잠든 시간과 mutex 대기도 포함될 수 있다. schedstat의 runnable 대기는 그중 실제로 실행 가능했지만 CPU를 받지 못한 시간을 독립적으로 보여준다. 여러 스레드의 runnable 대기를 합친 수치는 한 IQ의 지연 시간이 아니므로 서로 더하지 않는다.',
'16 UE·1×1에서 relay 작업자는 puller 17 + producer 17 + reply 17 = 51개다. 여기에 ZMQ I/O·control·CUDA 관련 스레드가 더해진다. broker에 할당된 big core는 두 개다. 실제 steady snapshot에는 broker 스레드 63개가 있었고, 4.03초 동안 broker 전체 CPU 사용은 약 8.04 CPU초로 두 코어를 거의 채웠다.',
'OCG_BROKER_SPIN=2는 socket 수신을 block하지만 내부 데이터·출력 공간·응답 row 대기는 sched_yield를 반복한다. 데이터가 없는 작업자도 runnable로 남아 CPU 차례를 경쟁한다. 필요한 IQ가 도착해도 생산·응답 담당 작업자가 즉시 실행되지 못하는 동작이 샘플 추적과 CPU 대기 양쪽에서 관측됐다.',
f'이 producer에서 확인된 입력 준비 후 지연과 출력 처리·공간 확인 지연만 합쳐도 {internal:.1f} µs/무선 1 ms이다. 전체 측정 구간 {total:.1f} µs 중 약 {internal/total*100:.1f}%다. 채널 처리 전체는 {b["process_us"]:.1f} µs였다. 이 합계는 한 receiver의 순차적인 구간이며 여러 UE의 동시 작업을 합친 수치가 아니다.','',
'6. 반복과 변경 실험',
'case / 실시간 진행률 / KPI 유효 구간 / starvation / 결과']
for c in cases:lines.append(f'{c["case"]} / {c["ratio"]:.6f} / {c["valid_segments"]}/30 / {c["faults"].get("rx_starvations")} / {c["gate"].get("measure_status")}')
lines += ['기준 실행은 0.4462와 0.4483으로 PR의 약 0.45를 재현했다. 계측 실행은 0.4430과 0.4363이다. 계측이 진행률에 미치는 부담도 위 수치에 포함된다.',
'KPI 누락(주로 UE12가 metrics/gNB report에 없는 구간)은 계측을 끈 반복에서도 나타났다. 따라서 16개의 IQ stream이 전진했다는 사실과 16 UE가 전 구간 정상 트래픽을 유지했다는 판정은 구분해야 한다. 이번 결과는 실패하는 PR 조건의 지연 분석이며 정상 16 UE 운용 자격을 입증하지 않는다.',
'알림 방식 probe는 ZMQ·IQ·pacing을 유지하며 내부 대기를 condition variable로 바꿨다. 입력/응답 대기를 바꾼 uninstrumented run은 0.4300, 출력 공간 대기까지 바꾼 run은 0.3878 도중 중단이었다. probe의 broker correctness tests는 통과했지만 실제 live 개선에는 실패했다. 패치를 해결책으로 채택하지 않았다.',
'이번에 입증한 것은 내부 CPU 실행·전달 지연의 큰 비중이다. 단순한 condition variable 치환이 이 문제를 해결한다는 주장은 실험에서 지지되지 않았다. 전체 원인을 한 종류의 대기 함수나 ZMQ 라이브러리 결함으로 축약하면 안 된다.','',
'7. 구현 방향에 대한 의미',
'ZMQ 호환성을 유지한 채 broker의 runnable 작업자 수, 응답·생산 작업 배정, I/O와 GPU 완료 처리의 CPU 예산을 함께 다루는 개선이 근거 있는 방향이다. 다음 구현이 실시간 성능을 회복할지는 별도의 검증 대상이다.',
'UE PHY GPU화는 UE 준비 구간을 줄일 가능성이 있지만 broker 내부 지연을 직접 제거하는 변경은 아니다. 현재 UE 코어와 broker 코어도 분리되어 있어 UE CPU를 비우는 것만으로 broker가 더 많은 코어를 받지는 않는다.',
'ZMQ 인터페이스를 제거해야 한다는 근거는 이번 측정에서 나오지 않았다. 현재 모듈 호환성을 보존하면서 내부 handoff 구조를 개선할 이유가 먼저 확인됐다.','',
'8. 재현 및 근거',
'pr10-audit.json: PR source·patch·binary·설정 대조 및 원본 입력 해시.',
'pr10-summary.json: 성공·실패·KPI 제외를 포함한 모든 최종 실행.',
'decompose-pr10-trace*.json, room-pr10-trace*.json, budgets-pr10-trace*.json: 샘플 시간 기준 분해.',
'evidence-validation.json: 최종 wire 기록의 손실·해시·메시지 대응 검증.',
'pr10-raw-evidence.tar.gz: 최종 7개 실행의 raw trace·실행 로그·설정·보고서 및 계측 바이너리. MongoDB 내부 데이터와 런타임 socket은 제외.',
'pr10_frozen.py, instrument_gnb.py, build_gnb.py, decompose_wait.py, wire_sources.py, decompose_room.py, receiver_budgets.py: 실행·계측·분석 코드.',
'production 소스와 기본 동작은 바꾸지 않았다. 모든 probe는 별도 빌드이며, 측정 종료 뒤 GPU 실행 프로세스는 없다.',
]
(P/'report.ko.txt').write_text('\n'.join(lines)+'\n')
# Standalone, quantitative visualization. All bar widths use one scale.
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1160" height="750" viewBox="0 0 1160 750"><rect width="1160" height="750" fill="#f6f8fc"/><style>text{font-family:sans-serif;fill:#182438}.h{font-size:25px;font-weight:bold}.s{font-size:17px}.n{font-size:14px}</style>']
def text(x,y,v,cl='s'):svg.append(f'<text x="{x}" y="{y}" class="{cl}">{html.escape(v)}</text>')
text(45,45,'PR10 · Spark · CUDA gNB + CPU srsUE · 16 UE','h');text(45,76,'무선 1 ms당 누적 시간 — 최종 반복 계측. 한 번의 GPU 호출 시간이 아님.','s')
colors=['#5478d1','#8658b9','#e89b38','#c74456','#4b9b86']
parts=[('입력 대기',b['data_us'],colors[0]),('출력 공간 대기',b['room_us'],colors[1]),('채널 처리',b['process_us'],colors[4]),('기타',total-b['data_us']-b['room_us']-b['process_us'],'#b8c1d1')]
x=45
for lab,v,col in parts:
 width=v/2500*1060;svg.append(f'<rect x="{x}" y="105" width="{width}" height="45" fill="{col}"/>');x+=width
text(45,182,f'입력 {b["data_us"]:.0f} µs  +  출력 공간 {b["room_us"]:.0f} µs  +  채널 {b["process_us"]:.0f} µs  +  기타 = {total:.0f} µs')
text(45,231,'입력 대기 안에서 실제로 생긴 일','h')
for i,(label,v,col) in enumerate([('UE 송신 준비 경계 이전',w['source_not_yet_at_send_boundary'],colors[0]),('send → broker receive (I/O·스케줄링 포함)',w['send_to_receiver_return'],colors[1]),('입력 도착 후 producer가 확인할 때까지',w['ring_ready_to_producer'],colors[3])]):
 y=258+i*47;text(45,y+20,label);svg.append(f'<rect x="600" y="{y}" width="{v/600*390}" height="26" fill="{col}"/>');text(1005,y+20,f'{v:.0f} µs')
text(45,424,'CPU 실행 기록으로 확인한 대기','h');text(45,459,f'producer 입력 대기 {b["data_us"]:.0f} µs 중 실제 CPU 사용 {b["data_cpu_us"]:.0f} µs')
window=(s['end_ns']-s['start_ns'])/1e9;cpu=t['cpu_ns']/1e9;queue=t['runnable_ns']/1e9
text(45,490,f'같은 producer의 {window:.2f}초 관측: CPU 실행 {cpu:.3f}초 / runnable 대기 {queue:.3f}초')
x=45
for v,col in [(cpu,colors[4]),(queue,colors[3]),(max(0,window-cpu-queue),'#ccd3df')]:
 width=v/window*1060;svg.append(f'<rect x="{x}" y="510" width="{width}" height="35" fill="{col}"/>');x+=width
text(45,582,'51개 relay 작업자 + I/O·control 등이 broker의 두 CPU 코어를 공유한다.')
text(45,618,'입력·출력 준비 뒤 내부 지연 약 1.15 ms. GPU 채널 계산만 봐서는 이 병목이 보이지 않았다.')
text(45,661,'기준 0.446 / 0.448배. 알림 방식 probe는 개선 실패. 실시간 해결은 아직 검증되지 않았다.','n')
text(45,691,'IQ 진행 분석과 UE별 KPI 유효성은 별도 판정이다. 상세 수치·제외 구간·원시 근거: report.ko.txt','n');svg.append('</svg>');(P/'causal-breakdown.svg').write_text(''.join(svg))
