import html,json,pathlib
P=pathlib.Path(__file__).parent
r=json.loads((P/'evidence.json').read_text()); prof=json.loads((P/'cpu-profile-summary.json').read_text())
labels=[('legacy-clean','기존 실행 방식'),('ready2','준비 큐만 · 계산 2개'),('mux2','단일 통신 루프 · 계산 2개'),('mux2-v2','조건별 알림·활성 포트 확인 · 계산 2개'),('mux4-v2','동일 구조 · 계산 4개'),('async2','GPU 완료 알림 · 계산 2개'),('async1','GPU 완료 알림 · 계산 1개'),('fd-sync2','ZMQ FD · 동기 GPU · 계산 2개'),('fd-async2','ZMQ FD · GPU 완료 알림 · 계산 2개'),('fuse-rx','기존 실행 구조 + 수신기 커널 통합'),('fused-fd-async1','FD + GPU 완료 알림 + 커널 통합 · 계산 1개')]

def table(cases,names):
 rows=[]
 for key,label in names:
  item=cases.get(key)
  if not item:continue
  result=item['result'];m=result.get('metrics')
  if not m or result['returncode']!=0:continue
  rate=m['real_time_ratio'];b=m['broker'];bad=sum(b[k] for k in ['tx_queue_overflows','tx_sequence_gaps','zmq_errors'])
  rows.append(f'<tr><td>{html.escape(label)}</td><td><b>{rate:.4f}</b><div class="bar"><i style="width:{min(rate,1)*100:.2f}%"></i></div></td><td>{result["valid_segments"]}/30</td><td>{b["rx_starvations"]}</td><td>{bad}</td></tr>')
 return '<table><tr><th>실행 방식</th><th>무선/벽시계<br>1.0 = 실시간</th><th>유효 구간</th><th>전체 실행<br>starvation</th><th>overflow + gap<br>+ ZMQ error</th></tr>'+''.join(rows)+'</table>'

def ratio(cases,key):return cases[key]['result']['metrics']['real_time_ratio']
rows=[]
for count,cases,key in [(8,r.get('cases_8ue',{}),'fuse-control'),(16,r['cases'],'legacy-clean')]:
 if key not in cases or 'fused-fd-async1' not in cases:continue
 a,b=ratio(cases,key),ratio(cases,'fused-fd-async1')
 rows.append(f'<tr><td>{count} UE</td><td>{a:.4f}</td><td>{b:.4f}</td><td>{(b/a-1)*100:+.1f}%</td></tr>')
summary='<table><tr><th>UE 수</th><th>기존 실행</th><th>변경을 합친 후보</th><th>속도 변화</th></tr>'+''.join(rows)+'</table>'
failed=[]
for name in ['fuse-control','fuse-control-repeat']:
 q=r['cases'].get(name)
 if q and q['result']['returncode']!=0:failed.append(f'<li><code>{name}</code>: 측정 중 relay wedge로 종료. 30초 완료 비교에서 제외하며, 부분 실행의 속도는 개선 근거로 사용하지 않는다.</li>')
profile_rows=''.join(f'<tr><td><code>{x["function"]}</code></td><td>{x["share_percent"]:.2f}%</td><td>{x["samples"]}</td></tr>' for x in prof['costs'])
copy_rows=''.join(f'<tr><td><code>{x["function"]}</code></td><td>{x["share_percent"]:.2f}%</td></tr>' for x in prof['copy_callers'] if x['function']!='other copy caller')
capacity=[]
for count,cases,keys in [(8,r.get('cases_8ue',{}),['fuse-control','fused-fd-async1']),(16,r['cases'],['fuse-control-repeat','fused-fd-async1'])]:
 for key in keys:
  q=cases.get(key,{}).get('capacity_window')
  if not q:continue
  workers=sum(v for k,v in q['ue_roles_cpu_s'].items() if k.startswith('WORKER'))
  label='기존 모드' if key.startswith('fuse-control') else '합친 후보'
  capacity.append(f'<tr><td>{count} UE · {label}</td><td>{q["wall_s"]:.2f}초</td><td>{q["radio_s"]:.3f}초</td><td>{q["ue_scheduled_cores"]:.2f} / 5</td><td>{q["ue_cpu_seconds_per_radio_second"]:.2f}</td><td>{workers:.2f} CPU초</td></tr>')
cap_table='<table><tr><th>관찰 대상</th><th>벽시계</th><th>진행한<br>무선 시간</th><th>UE 실행 CPU<br>평균 코어 수</th><th>UE CPU초 /<br>무선 1초</th><th>그중 PHY<br>WORKER 실행</th></tr>'+''.join(capacity)+'</table>'
css='''body{font:17px/1.65 system-ui,sans-serif;color:#203047;background:#f3f5f9;max-width:1120px;margin:auto;padding:30px}section{background:white;border-radius:14px;padding:26px;margin:20px 0}h1,h2{line-height:1.3}code{background:#edf1f5;padding:2px 5px}table{border-collapse:collapse;width:100%;font-size:15px}td,th{text-align:left;border-bottom:1px solid #dce1e8;padding:11px}code,td,th{overflow-wrap:anywhere}.flow{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.box{padding:14px;border:2px solid #5580ba;border-radius:10px;flex:1;min-width:150px}.wait{border-color:#cf6840;background:#fff5ef}.good{border-color:#27866b;background:#eef9f5}.note{border-left:4px solid #cf6840;padding:12px;background:#fff5ef}small{color:#526176}.bar{height:6px;background:#edf1f5}.bar i{display:block;height:6px;background:#5383b2}nav a{margin-right:18px}blockquote{margin:15px 0;padding:18px;background:#f1f5fa;border-left:4px solid #5383b2}@media(max-width:600px){body{padding:14px;font-size:15px}section{padding:16px}td,th{padding:6px;font-size:12px}table{table-layout:fixed}.box{min-width:180px}}'''
s=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Spark 스케일링 패치 실측</title><style>{css}</style>
<h1>Spark 스케일링 패치: 구현과 실측 결과</h1>
<p><b>정확성 검사는 통과했지만, 이번 후보들은 라이브 스택의 속도를 높이지 못했다.</b> 기존 실행을 기본값으로 유지하고, 새 경로는 실험 브랜치의 선택 설정으로 보존했다.</p>
<nav><a href="#verdict">실측 결론</a><a href="#location">문제가 생기는 위치</a><a href="#implementation">구현한 변경</a><a href="#cpu">실제 CPU 함수</a><a href="#capacity">UE CPU 수요</a></nav>
<section id="verdict"><h2>같은 PR10 입력으로 비교한 결과</h2>
<p>대상은 <b>DGX Spark · CUDA gNB · 기존 CPU srsUE · GPU 채널 에뮬레이터</b>다. 1 cell, 20 MHz, 23.04 MS/s, 1×1과 원본 channel/traffic bundle을 고정했다. UE GPU 구현은 사용하지 않았다.</p>{summary}
<p>합친 후보는 <b>준비 큐 + 단일 ZMQ 통신 루프 + GPU 완료 알림 + 수신기 커널 통합</b>을 켜고 계산 작업자 하나를 사용한 버전이다. 8 UE는 동일한 바이너리의 설정만 바꾼 비교다. 16 UE의 표는 앞서 30초를 완료한 기존 실행을 대조로 쓴다. 최종 바이너리의 기존 모드 대조 두 번은 중간에 멈춰 별도로 기록했다.</p>
<p class="note">새 경로를 구현한 것, IQ가 같은 것, 실제 무선 시간이 빨라진 것은 각각 다른 검증이다. 이번에는 앞의 두 가지를 확인했고, 속도 개선에는 실패했다. 엄격한 실시간·zero-starvation 통과도 아니다.</p></section>
<section id="location"><h2>한 흐름 안에서 어디를 보고 있는가</h2><div class="flow"><div class="box wait">기존 CPU srsUE<br>PHY 작업·스택·ZMQ</div><b>⇄</b><div class="box wait">에뮬레이터 CPU<br>IQ 버퍼·실행 순서·CUDA 제출</div><b>⇄</b><div class="box">에뮬레이터 GPU<br>채널 합산·수신기 잡음</div><b>⇄</b><div class="box">기존 ZMQ<br>↔ CUDA gNB</div></div>
<p>기존 깊은 프로파일에서 gNB 방향 producer가 입력 준비를 확인하기까지의 <b>541.443 µs</b> 중 <b>515.593 µs</b>는 실제 <code>sched_yield()</code> 호출 안의 시간이었다. 그중 514.582 µs는 실행 가능한 상태에서 CPU 차례를 기다린 시간이고, mutex 획득은 3.058 µs였다. 이는 <b>그 세부 대기 구간의 원인</b>을 특정한 결과다. 전체 라이브 스케일링 한계가 이것 하나 때문이라는 증거는 아니다.</p>
<p>수치는 해당 receiver가 표현한 무선 시간 1 ms당 합계다. 이전 함수 단위 증거는 <a href="../../local-work/profiling-20261029-causal/scaling-and-ue-phy.ko.html#function-proof">기존 프로파일 설명</a>에 있다. 이후 구현에서 실행 차례 대기를 줄여도 전체 속도가 개선되지 않아, CPU가 하는 다른 작업과 UE 자체 CPU 수요를 추가 측정했다.</p></section>
<section id="implementation"><h2>실제로 구현한 변경</h2><table><tr><th>변경</th><th>실행 방식</th><th>남겨 둔 규칙</th></tr><tr><td>준비 큐</td><td>IQ나 출력 공간이 없는 노드는 실행에서 빼고, 필요한 조건의 알림을 받으면 이어 실행한다.</td><td>노드별 샘플 번호·입력 cursor·버퍼·pacer는 하나의 상태가 소유한다.</td></tr><tr><td>통신 루프</td><td>포트별 대기 스레드 대신 한 루프가 nonblocking ZMQ를 처리한다. FD 버전은 바뀐 포트만 확인한다.</td><td>UE/gNB가 보는 ZMQ 주소·REQ/REP·cf32 IQ는 그대로다.</td></tr><tr><td>GPU 완료 알림</td><td>GPU가 끝나기를 기다리며 계산 작업자를 점유하지 않고, 완료 알림 뒤 출력을 정리한다.</td><td>입력·출력 버퍼는 GPU 완료까지 살아 있고, 중단 때도 완료를 기다린 뒤 해제한다.</td></tr><tr><td>수신기 커널 통합</td><td>합산 뒤 별도로 실행하던 수신기 잡음·위상 처리를 합산 커널 안에서 이어 실행한다.</td><td>잡음은 합산 후 row당 한 번, 같은 seed·counter·연산 순서로 적용한다.</td></tr></table>
<p><b>producer</b>는 한 수신 노드의 공통 IQ 구간을 골라 채널을 계산하고 결과를 게시하는 작업이다. <b>준비 큐</b>는 지금 실행할 수 있는 producer의 목록이다. 16 UE에서는 기존 입력 17 + producer 17 + 응답 17 = <b>51개 작업 스레드</b>를, 최종 후보의 통신 1 + 계산 1 = <b>2개 작업 스레드</b>로 바꿨다. ZMQ·CUDA 내부 스레드와 메인·제어 스레드는 이 수에 포함하지 않는다.</p>
<div class="flow"><div class="box">기존 1×1 수신기<br>합산 커널 → 잡음 커널</div><b>→</b><div class="box good">통합한 1×1 수신기<br>합산 + 잡음을 한 커널에서</div></div>
<p>수신기 커널 통합은 복사/zero-copy, 두 출력 row, 가변 길이, CFO·위상·AWGN·잡음 counter reset에서 <b>791,104개 복소 IQ 출력을 비트 단위로 비교</b>했다. 실행 순서 변경과 커널 통합 모두 MIMO의 공통 시작 샘플·길이, 부분 구간 진행, 기존 pacing과 한 배치의 지연 부채 한도를 유지한다. IQ drop·빈 IQ 채움으로 진행률을 높이지 않는다.</p></section>
<section id="results"><h2>16 UE: 변경별 전체 결과</h2>{table(r['cases'],labels)}
<p><small>유효 구간은 분석기의 판정이며 실행 스크립트의 <code>gate=passed</code>와 별개다. 위 속도 표에는 30 무선초 측정을 완료한 실행만 넣었다. Starvation은 시작·측정·종료를 포함한 전체 실행 카운터이므로, 서로 같은 길이의 구간 오류율로 해석하지 않는다.</small></p>
<h2>8 UE: 같은 바이너리에서 기존 모드와 최종 후보</h2>{table(r.get('cases_8ue',{}),[('fuse-control','기존 모드'),('fused-fd-async1','변경을 합친 후보')])}
<h3>제외한 실행도 남겼다</h3><ul>{''.join(failed)}<li>최초 두 실행은 샘플 기준 제어 패치가 빠져 <code>link_clock</code> 요청을 거부했다. 별도 복원 커밋 <code>c66de51</code> 이후 다시 비교했다.</li><li>초기 기존 모드 한 번은 별도 빌드가 겹쳤다. CPU 스택 샘플링 실행도 진단 전용이며, 둘 다 깨끗한 속도 비교에서 제외했다.</li></ul></section>
<section id="cpu"><h2>스레드를 줄인 뒤에도 CPU가 실제로 한 작업</h2><p>실패한 FD/동기 GPU/계산 작업자 2개 버전에서 3초 동안 <b>userspace 하드웨어 사이클 1,024개 표본</b>을 수집했다. lost sample은 0개다. AArch64의 서명된 복귀 주소를 기록된 LR·FP·stack 범위로 복원하고, 실행 바이너리와 동일 build-id의 라이브러리 심볼을 확인했다.</p>
<table><tr><th>식별한 CUDA API 경로</th><th>표본 사이클 비중</th><th>표본 수</th></tr>{profile_rows}</table>
<p>위 수치는 <b>GPU 커널 실행 시간도, 전체 벽시계 지연 비중도 아니다.</b> CPU가 해당 API 경로 안에서 실행한 사이클의 식별 비중이다. CUDA 드라이버의 mutex 해제 경로도 약 {prof['driver_mutex_unlock']['share_percent']:.2f}%에서 확인됐으며, 이는 위 API 비용의 일부이므로 다시 더하면 안 된다.</p>
<table><tr><th>별도로 확인한 CPU 메모리 복사 호출자</th><th>표본 사이클 비중</th></tr>{copy_rows}</table>
<p><code>IqRing::push</code>는 받은 IQ를 입력 ring에 넣는 복사, <code>IqRing::read</code>는 ring 구간이 이어지지 않을 때의 읽기 복사, <code>zmq::msg_t::init_buffer</code>는 전송할 IQ를 ZMQ 메시지 버퍼로 옮기는 복사다. 이들은 CPU 버퍼 사이의 복사이며, GPU의 H2D 이벤트 시간과 같은 수치가 아니다. 자세한 수치와 원본 해시는 <a href="cpu-profile-summary.json">CPU 프로파일 요약</a>에 있다.</p></section>
<section id="capacity"><h2>채널 바깥에도 있는 CPU UE의 처리량 제약</h2><p>같은 CPU srsUE 바이너리를 유지한 채, 약 4초의 두 스냅샷 사이에서 실행 CPU 시간과 CPU 차례 대기를 읽었다. 실제 <code>link_clock</code>을 두 번 읽어 진행한 무선 시간도 확인했다. UE에 배정된 코어는 <b>13·14·17·18·19의 다섯 개</b>다.</p>{cap_table}
<p>16 UE의 기존 모드 관찰에서 UE는 평균 <b>4.53 / 5 코어</b>를 사용했고, 각 코어 사용률은 약 90–96%였다. 같은 처리량을 무선 1초로 환산한 UE CPU 실행은 약 <b>10.2 CPU초</b>였다. 계산 작업자는 대기 중 condition variable에서 멈추며, PHY의 <code>work_imp()</code>에서 DL/UL 일을 실행하는 구조다. 실제 관찰에서는 WORKER0/1만 9.31 CPU초를 썼다.</p>
<p class="note">CPU초는 여러 스레드의 실제 실행 시간을 더한 값이다. 벽시계 10.2초를 기다렸다는 뜻이 아니다. 다섯 코어가 벽시계 1초에 제공할 수 있는 실행량은 최대 5 CPU초다. 현재 관찰 작업량을 그대로 실시간으로 처리한다고 외삽하면 UE 쪽 CPU 수요가 이 배정량을 크게 넘는다. 다른 CPU 종류·배치까지 아우르는 절대 최소 코어 수를 측정한 것은 아니다.</p>
<p>따라서 현재 결과는 <b>에뮬레이터의 특정 yield 구간만 바꾸면 전체 스케일링이 해결된다</b>는 해석을 지지하지 않는다. 채널 내부의 CUDA 제출·복사 비용과, 기존 CPU UE가 무선 시간당 실제로 쓰는 실행량을 함께 봐야 한다. 여기서 UE GPU 패치를 실행하거나 UE/gNB 바이너리를 교체하지는 않았다.</p>
<p><small>클록 RPC는 CPU 스냅샷 두 개를 둘러싸므로 CPU초/무선초는 짧은 관찰창의 근사치다. 기존 16-UE 모드의 CPU 관찰은 샘플이 진행하던 구간이며, 그 실행 전체가 나중에 멈춘 사실은 별도로 남겼다.</small></p></section>
<section><h2>서로 다른 시간 수치를 섞지 않는다</h2><table><tr><th>측정</th><th>범위와 단위</th></tr><tr><td>기존 515.593 µs</td><td>한 receiver의 무선 1 ms당 실제 sched_yield 호출 시간 합.</td></tr><tr><td>44.7초 → 5.5초</td><td>기존/첫 통신 루프의 서로 다른 2초 시점에서 모든 broker 스레드의 runnable 대기 합. 동시 대기를 더해 벽시계보다 클 수 있다. 같은 radio 구간 반복이나 전체 지연 분포가 아니다.</td></tr><tr><td>CUDA API 사이클 비중</td><td>진단 전용 3초 CPU 표본. GPU 실행 시간이 아니다.</td></tr><tr><td>무선/벽시계 비율</td><td>30 무선초 측정의 실제 샘플 진행 속도. 최종 라이브 성능 판정에 쓴다.</td></tr></table></section>
<section><h2>검증 상태와 적용 범위</h2><p>최종 backend/core 검사는 <b>17/18 통과</b>했다. 실패한 CPU 참조 <code>cpu_parallel</code>은 비동기 변경 전 빌드에서도 동일하게 실패했다. 수신기 통합을 켠 processing·runtime control·history 검사도 <b>3/3 통과</b>했다. IQ 비트 동일성, MIMO lock-step, 알림 경합·timer·중단 및 wedge 검사를 포함한다.</p>
<p>라이브 비교는 <b>8/16 UE · 1 cell · 20 MHz · 1×1</b>이다. 새 구현으로 cell 수·bandwidth·안테나 수의 한계가 확장됐다고 판정하지 않는다. sample rate를 따로 sweep하지 않았다. CUDA gNB와 CPU srsUE 해시는 원래 PR10 조건과 같고, CPU 배치·MPS·원본 channel/traffic 입력도 유지했다.</p>
<p>새 실행 경로는 선택 설정이며 <b>PR10 본체에 성공 패치로 반영하지 않았다.</b> 준비 큐는 <code>OCG_BROKER_READY_WORKERS</code>, 통신 루프는 <code>OCG_BROKER_MULTIPLEX</code>, GPU 완료 알림은 <code>OCG_BROKER_ASYNC_CUDA</code>, FD 통신은 <code>OCG_BROKER_FD_POLLER</code>, 수신기 통합은 <code>OCG_CUDA_FUSE_RX</code>로 각각 구분한다.</p>
<p>GPU 완료 CPU 함수는 CUDA API를 호출하지 않고 알림만 보낸다. 이후 출력 복사·타이밍 조회와 중단 시 자원 회수는 작업자가 수행한다. <a href="https://docs.nvidia.com/cuda/cuda-programming-guide/02-basics/asynchronous-execution.html">NVIDIA 완료 함수 규칙</a>과 <a href="https://zeromq.github.io/libzmq/zmq_getsockopt.html">ZMQ FD/EVENTS 규칙</a>을 따른다.</p></section>
<section><h2>재현 자료</h2><p>명령·환경·입력 SHA-256·바이너리 해시·완료 여부·오류·CPU 관찰은 <a href="evidence.json">evidence.json</a>, 실행은 <a href="live.py">live.py</a>, 수집은 <a href="collect.py">collect.py</a>에 있다. 3초 원본 perf 파일과 전체 로그는 Spark의 <code>/workspace/gpuch/relay-ready-20261029/</code>에 보존했다. 이전 세이브 지점은 <code>0eb3cf4</code>다.</p>
<p>예: Spark에서 <code>sudo -n python3 /workspace/gpuch/relay-ready-20261029/live.py --ues 8 fuse-control fused-fd-async1</code>. 이미 결과가 있는 이름은 덮어쓰지 않는다. 각 실행의 실제 원본 명령은 해당 <code>launch.json</code>을 기준으로 한다.</p></section>
<section><h2>보고할 수 있는 결론</h2><blockquote>I reproduced the limit with the PR10 CUDA-gNB / CPU-srsUE setup. The broker changes reduced runnable contention but did not improve the live sample rate. The 16 CPU UEs also used about 10 CPU-seconds per radio-second on their fixed five-core allocation. The changes remain experimental; the scaling issue is not fixed.</blockquote></section></html>'''
(P/'report.html').write_text(s)
