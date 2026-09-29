# 로봇 파이팅 데모 — 실시간 채널 에뮬레이터 검증 마일스톤

**목표: 두 로봇의 두뇌(제어기)를 gNB 뒤에, 몸(물리 시뮬레이터)을 UE 뒤에 두고, 제어 루프 전체가 채널 에뮬레이터를 통과하게 한다. 채널은 Sionna RT가 로봇의 실제 위치로부터 실시간으로 만든다(twin). 에뮬레이터의 실시간이 깨지면 그 결과가 로봇의 승패로 나타나야 한다.**

레퍼런스: J. Duan(@DJiafei, 2026-09-23) — Unitree G1 두 대를 MuJoCo 링에 넣고 2 sim-초마다 `state → LLM → joint targets`로 Opus 5.5와 GPT-6 Astra를 겨루게 한 데모. 거기서 선수는 LLM이고 링은 고정이다. **여기서는 두뇌를 양쪽에 똑같이 두고, 선수는 각 로봇과 두뇌를 잇는 무선 링크 — 즉 그 링크를 만드는 에뮬레이터와 그것이 GPU 시간을 받는 방식이다.**

단계 번호는 `R`. 판정 규율은 C·J·S 트랙과 같다: exit≠0만으로 판정하지 않고 로그에서 메커니즘을 확인한다, 실패 측정을 보존한다.

## 무엇을 검증하는가

지금까지의 실시간 증거는 카운터다(1.0× wall-clock, `rx_starvations ≈ 1`, 브로커 p99). 카운터는 "실시간이 아니면 무엇이 어떻게 되는가"에 답하지 못한다. 이 데모는 실시간 위반을 **되돌릴 수 없는 물리 결과**(밀림, 넘어짐, 링 아웃)로 번역한다. 카운터가 증명이고 로봇이 증거다.

Sionna twin이 붙으면 검증 범위가 IQ 경로(브로커)에서 **채널 갱신 경로**(위치 → Sionna → control plane → 슬롯 경계 적용)까지 넓어진다. 이 경로가 같은 wall-clock에서 제때 도는지는 아직 아무도 시험하지 않았다.

## 불변식 — 아무도 기다리지 않는다

이 시뮬이 실시간 검증이 되려면 모든 구성 요소가 wall-clock 하나에 각자 붙어 있고, **누구도 남을 기다리지 않아야** 한다. 어기면 그 판은 무효다.

| 구성 요소 | 시계 | 늦으면 |
|---|---|---|
| gNB / srsUE | wall-clock 1.0× | 슬롯 버림(원래 동작) |
| 브로커 | `--strict-realtime` **켬** | 늦은 슬롯·늦은 control update는 **드롭**, 지연 아님 |
| Sionna 브리지 | 자기 주기(예: 10–20 Hz) | 그 주기의 갱신을 건너뜀, 브로커는 옛 채널로 계속 |
| 물리 시뮬(MuJoCo) | wall-clock 스텝(sim 시간 = 실제 시간) | 명령 없으면 **마지막 명령 유지 또는 0 토크**, 물리는 계속 |
| 두뇌 | 상태가 오면 계산, 안 오면 옛 상태 | 낡은 상태로 판단 |

- 물리 시뮬이 링크를 기다리는 lock-step 모드는 **검증 경기에서 금지**(디버그 도구로만). 링크가 늦어도 결과가 같아져 실시간이 사라진다.
- 시스템 전체가 0.7×로 같이 느려지는 것도 무효다. 경기마다 real-time factor를 기록하고 1.0이 아니면 그 판은 버린다.
- 제어 주기는 링크가 아플 만큼 빠르게(50–100 Hz) 잡는다. 2 s 주기(LLM)는 지연 수십 ms에 둔감해서 에뮬레이터가 무엇을 하든 결과가 안 바뀐다.

## 설계 요약

```
brain-A ──(N6/tun)── gNB ═══╗
                            ║  ocudu-gpu-channel 브로커 (Sionna twin)
brain-B ──(N6/tun)── gNB ═══╣  links: gnb→ueA, ueA→gnb, gnb→ueB, ueB→gnb, ueA↔ueB crosstalk
                            ║
             ueA (srsUE) ═══╝               ┐
             ueB (srsUE) ═══╝               ├─ MuJoCo 한 인스턴스 (링 + 로봇 2대)
                                            ┘
   ueX tun ⇄ UDP ⇄ robot-X: state 업링크(50–100 Hz), 명령 다운링크, seq + timestamp
   MuJoCo 로봇 위치(10–20 Hz) ──► Sionna 브리지(run_bridge.py) ──► 브로커 control plane
```

- 물리 시뮬은 UDP 소켓 뒤에 있어 교체 가능하다. 측정은 MuJoCo(CPU, 에뮬레이터와 GPU를 다투지 않음), 영상은 필요하면 Isaac.
- 로봇은 처음엔 바퀴형 스모봇(differential drive + 앞판). 밸런스 붕괴 같은 채널 외 잡음이 없어 N을 크게 돌릴 수 있다. G1은 데모용으로 나중에.
- UE 스택은 srsUE(Spark 20 MHz에서 실시간 확인된 조합, 2 UE는 `srsue-ra-contention.patch` 필수). gNB는 R4까지 CPU, R5에서 CUDA gNB를 GPU 경합원으로 추가.
- 비교 축은 **GPU 스케줄링**이다. 장애물 vs 깔끔한 링은 결과가 씬으로 정해져 시스템에 대해 말해 주는 게 없다. 스케줄링 배틀은 물리 채널과 두뇌가 대칭이고 다른 것은 "B의 브로커가 GPU 시간을 제때 받느냐"뿐이다. S9에서 이미 본 인과(CUDA gNB p99 195 → 80 µs, time-slicing → MPS)를 로봇이 밀리는 것으로 번역한다.

## 환경

플랫폼 **DGX Spark**(`ssh spark-minwoo`, 컨테이너 `ocudu-minwoo`, GB10 sm_121, CUDA 13.0.88, 드라이버 580.178.04). 레포 `/workspace/gpuch/int0928`(integration-0928), 네이티브 루트 `/workspace/ocudu-spark`, 채널 빌드 `builds/gpuch-int0928-release`. Sionna venv `/workspace/sionna-venv`(sionna-rt 2.0.1, mitsuba 3.8.0, drjit 1.3.1, variant `cuda_ad_mono_polarized`), OptiX `/usr/lib/aarch64-linux-gnu/libnvoptix.so.1`. 게이트 래퍼 `/workspace/gpuch/r0-sionna-1x1.sh`. GPU는 다른 컨테이너와 공유 — 시간 측정마다 다른 GPU 프로세스가 없었음을 기록한다.

## 단계

| 단계 | 내용 | Exit 게이트 | 상태 |
|---|---|---|---|
| **R0** | **Spark에서 Sionna 검증** — venv 고정, cuda variant 확인, `run-ocudu-sionna-1x1.sh` 게이트, `channel_generation_ms` 실측 | Sionna 1x1 live gate PASS(rrc/pdu/ping, 카운터 0), 갱신 1회당 solve 시간 | **완료 2026-09-29** — live-ready rrc/pdu/ping 1/1/1, 106 s 동안 Sionna 갱신 10 Hz 적용(control batch 1,043), solve 49–52 ms, 브로커 kernel 23.6 µs, ping RTT 20–39 ms(avg 29) |
| **R1** | **링 씬** — 링 + 기둥/차폐물 Mitsuba XML, gNB 1 + UE 2 + crosstalk 시나리오 JSON, 커버리지 맵으로 LOS/NLOS 비대칭 확인 | 브리지 dry-run에서 링 위치별 탭이 물리적으로 말이 됨, 6링크 solve 시간이 갱신 주기 예산 안 | **완료 2026-09-29** — `scenes/robot_ring` + `robot-ring.json`(4링크, FDD) / `robot-ring-crosstalk.json`(6링크). GB10 solve 46–53 ms(링크 수 무관, 방향당 1회), 10 Hz 예산 안. LOS −0.5…−2.9 dB, 기둥 그림자 −27…−36 dB(refraction on; 끄면 outage). 발견: 4-UE 커밋 이후 Sionna multi-UE 렌더러가 2-UE 시나리오를 거부 → R4 전 수정 필요 |
| **R2** | **로봇 아레나** — MuJoCo 스모봇 2대, ring-out 규칙, 두뇌 프로세스, UDP 프로토콜(seq+timestamp), 위치 PUB. 무선 없음 | 로컬 루프로 경기 완주, MuJoCo wall-clock 스텝, 명령 부재 정책 정의, 동일 두뇌 승률 50±x% 노이즈 플로어(N≥30) | **완료 2026-09-29** — `scripts/robot_fight/` (protocol/arena/brain/fight), 테스트 6개 통과. 30판 노이즈 플로어 5:5:20(승률 0.5, 95% CI 0.24–0.76), RTF 1.000. 핸디캡: +100 ms 편도 → 11:2:5(승률 0.85), +50 ms·손실 10/30% → 잡음 안. **무승부 67–83%가 문제**, R4 전 정책 손질 필요 |
| **R3** | **위치 → Sionna live** — 브리지 `update_positions`를 외부 입력(ZMQ SUB)으로 교체, MuJoCo → 브리지 → 브로커 | 로봇이 기둥 뒤로 가면 KPI 패널의 채널이 따라옴, 위치→적용 지연 < 예산 | **부분 완료 2026-09-29** — 브리지 `--position-endpoint` + 게이트 env 배선, 단위 테스트 11개, Spark dry-run에서 원 궤도 추종 오차 0 m, solve 유지(링 씬 6링크 53 ms). MuJoCo→KPI 실물 연결은 R2/R4에서 |
| **R4** | **무선 폐루프** — srsUE 2대 attach(`run-ocudu-sionna-multi-ue.sh` 기반), 제어 루프가 tun 통과, RTT/손실 로그를 브로커 슬롯 로그와 조인 | strict-realtime on, RTF = 1.0 로그, 경기 완주, RTT 분포, 무효 판 규칙 적용 | **부분 완료 2026-09-29 (R4a 무선 절반)** — 2-UE Sionna 렌더러 수정, 절대 수신 잡음 바닥(`OCUDU_NATIVE_SIONNA_AWGN_SNR_DB`, 기본 40), 게이트 훅(`MUE_UE_EXEC`/`ROOT_EXEC`/duration/strict/핀/캡처/UE metrics CSV). 링 씬 walk 시나리오 PASS: LOS UE 34 dB, 그림자 UE 31→16 dB(r=0.42), ping 32/37 ms. 아레나 절반(R4b)은 미착수 |
| **R5** | **스케줄링 배틀** — 브로커 2개(셀 2개), GPU 경합원(Sionna 버스트 + CUDA gNB), 스케줄링 off vs on, N판 | 스케줄링 유무로 승률이 뒤집히고 p99/starvation/`control_updates_dropped_realtime`가 그 이유를 설명 | |
| **R6** | **데모 패키징** — 영상, KPI 패널 동기 재생, 선택: LLM 두뇌 / G1 / Isaac | 발표용 영상 1편 | |

R0–R2는 서로 독립(병렬 가능), R3부터 직렬.

## 위험

- **Sionna solve 시간 vs 로봇 속도.** 3.5 GHz에서 파장 8.6 cm, 로봇 1 m/s면 채널이 ~40 ms마다 바뀐다. R0 실측 1x1(2링크) 49 ms → 6링크는 ~150 ms(≈6 Hz)로 예상. 줄이는 손잡이: `samples_per_source`(200k) 축소, 같은 주파수면 방향당 재추적 공유, 씬 축소. R1에서 예산을 정한다.
- **한 GPU에 CUDA 세입자 3–4개**(브로커, Sionna, CUDA gNB, [Isaac]). 이것은 위험이 아니라 R5의 주제다. R4까지는 세입자를 브로커 + Sionna로 제한한다.
- srsUE 2 UE는 contention 패치가 있어야 같은 C-RNTI로 합쳐지지 않는다(S16).
- 게이트 tmux를 죽이면 고아가 남는다(S16 관찰). 종료는 exit 마커로 기다린다.

## 진행 기록

### R0 — 2026-09-29 (Spark)

- Sionna는 Spark에 **설치돼 있지 않았다**(검증 전무). `/workspace/sionna-venv`에 프로젝트 핀 `sionna-rt==2.0.1` 설치 → mitsuba 3.8.0 / drjit 1.3.1 aarch64 휠로 해결, `mi.variant()` = `cuda_ad_mono_polarized`, `dr.has_backend(CUDA)` = 1. `jitc_llvm_init(): LLVM API initialization failed` 경고는 LLVM CPU 백엔드 부재이고 CUDA 경로에는 무해.
- 내장 street-canyon, 1 TX/1 RX, depth 3, 200k samples: 첫 solve 0.96 s(JIT), 이후 **18 ms**, 경로 11개.
- 프로젝트 브리지 dry-run(`examples/sionna/ocudu-docker.json`, 10 Hz, 8 s): `channel_generation` **48.6 / 48.9 / 49.7 ms(min/median/max)**, 방향당 24 ms(downlink·uplink 순차, 1842.5 / 1747.5 MHz). 10 Hz 갱신에 맞는다.
- Spark 트리를 `c786ad8` → `9043202`(integration-0928 HEAD)로 올림. 이전 미커밋 diff(S14 부분, 이미 `91c581c`로 커밋된 내용)는 `/workspace/gpuch/int0928-uncommitted-0929.diff`에 보관.
- 라이브 게이트 `r0-sionna-1x1.sh`(tmux `r0`, 결과 `results/{logs,reports}/ocudu-sionna-1x1/20260929T122820Z`): **PASS**. `live-ready.json` rrc_connected/pdu_session_established/ping_ok = 1/1/1, ping 3/3 RTT 20.2/29.5/38.7 ms. 106 s 라이브 동안 브리지 iteration ~1,040(10 Hz), 라이브 solve 52 ms(방향당 25–26 ms), `control_transaction` 0.48 ms, generate→ack 52.7 ms. 브로커 `gpu_timings` h2d 7.1 / kernel 23.6 / d2h 1.0 µs, rx_ring peak_one_way 1,000 µs, room_stall 0. GPU 세입자는 브로커(176 MiB) + Sionna(731 MiB)뿐.
- `node_stall`(ue0/gnb0 input_data 2–5.7 s)은 t=1–4 s, 즉 첫 atomic profile update 이후 라디오가 뜨는 attach 구간에서만 났고 이후 없음. `rx_starvations=7` 한 줄 관측 — 같은 구간으로 추정, R4에서 슬롯 로그와 조인해 확인.
- 관찰: 브로커 로그에 `control_warmup_begin/end`가 갱신마다 찍힌다(1,825회). 브리지가 `profile_swap` 경로를 쓰므로 갱신마다 delay line이 zero-fill되고 warmup에 들어간다 — [sionna-live-channel.md](docs/plans/sionna-live-channel.md)가 지적한 S0 호환 경로 그대로다. 10 Hz에서는 attach·ping에 문제가 없었지만, 로봇 제어 루프(50–100 Hz)에서 갱신마다 채널이 끊기는 것이 BLER에 보이는지 R4에서 본다.
- 하네스 교훈: sionna 모드 게이트는 duration 없이 Ctrl-C까지 돈다. `tmux send-keys C-c`는 래퍼 셸까지 죽여 exit 마커가 안 남고 게이트의 종료 요약(`event=stats`)도 안 나온다. 다음부터는 게이트 PID에 `kill -INT`를 보내고 마커는 래퍼가 아니라 폴링 쪽에서 남긴다. 고아 프로세스는 없었다(cleanup trap 정상).

### R1 — 2026-09-29 (링 씬, Spark GB10)

- **씬** `examples/sionna/scenes/robot_ring/`(생성기 `build_robot_ring.py`, stdlib만; `scene.xml` + `meshes/*.ply` + `manifest.json` + `README.md`): 60×60 m 콘크리트 바닥, 내경 4 m·높이 0.3 m 금속 펜스(48분할), 0.8×0.8×3 m 콘크리트 기둥 3개(x=0, y=−1.6/0/+1.6), 15 m 동쪽의 7.5 m 금속 마스트. gNB 안테나 (15, 0, 8). 로봇 UE 안테나 높이 0.4 m(펜스 위). `resolve_scene("robot_ring")`으로 잡힌다.
- **함정 하나:** 처음엔 마스트를 8 m로 만들고 gNB를 그 윗면(z=8.0)에 놓았더니 **gNB 링크 전부 ray 0개(outage)**, UE↔UE만 경로가 있었다. 메시 면 위에 놓인 소스는 아무 경로도 못 만든다. 마스트를 7.5 m로 낮춰 안테나가 0.5 m 뜨게 한 뒤 정상.
- **시나리오** `examples/sionna/robot-ring.json`: gnb0 고정, ue0(+x, LOS 쪽)·ue1(−x, 그림자 쪽) 각각 y 방향 5 m pingpong 1 m/s(dry-run·커버리지용, R3가 실제 위치로 교체), DL/UL 4링크. `robot-ring-crosstalk.json`은 UE↔UE crosstalk 양방향을 더한 6링크 변형. **crosstalk를 기본에서 뺀 이유:** 네이티브 fixture는 FDD band 3(DL 1842.5 / UL 1747.5 MHz)라 한 UE의 상향이 다른 UE의 하향 대역에 들어올 수 없는데, 에뮬레이터의 crosstalk는 베이스밴드 주입이고 2–4 m 거리의 UE↔UE 경로는 물리 −47 dB → 어댑터 클램프 **+20 dB**(gNB 신호보다 20 dB 이상 큼)라 켜면 하향을 통째로 재밍한다. TDD 단일 캐리어 실험에서만 쓴다.
- **solve 시간(GB10, dry-run 10 Hz, `channel_generation` min/med/max ms, 정상 상태):** 200k/d3 47.9/55.9/113 · 100k/d3 42.8/46.0/68.7 · 50k/d3 43.1/45.3/86.6 · 20k/d3 45.7/49.6/86.6 · 200k/d2 47.1/48.7/82.6 · 50k/d2 44.8/49.8/64.8. **`samples_per_source`·`max_depth`는 씬이 작아 시간에 거의 영향이 없고**, 링크 수도 무관하다 — Sionna는 (주파수, 배열) 그룹당 한 번 풀고(DL 그룹 ~25 ms + UL 그룹 ~25 ms) 링크는 후처리라 6링크 = 2링크 시간. 위험 항목의 "6링크 ~150 ms" 예상은 빗나갔다(좋은 쪽). 기본값은 **200k / depth 3 유지**(시간 이득이 없으니 경로 수를 줄일 이유가 없다). 첫 solve는 JIT 때문에 0.1–1.6 s.
- **그림자를 outage가 아니라 감쇠로 만드는 방법(sweep2, ue1을 기둥 0 뒤 (−2, −1.6)에 고정):** LOS+specular만: ue1 ray 0(−100 dB). diffuse_reflection on: 그대로 0. **diffraction on: −26.7 dB(DL)/−22 dB(UL)이지만 solve 69 ms(d1)–88 ms(d2)로 10 Hz 예산 초과.** **refraction(투과) on: solve 그대로(47.7 ms)에 콘크리트 기둥 −27.1/−25.6 dB** — 이걸 기본으로 채택(`propagation.refraction: true`). 기둥 재질로 핸디캡 깊이를 정할 수 있다: glass −15.2, wood −20.7, concrete −27.1, plasterboard −28.4, brick −39.9 dB(DL 최강 탭, LOS −2.4 기준).
- **커버리지(`scenes/robot_ring/coverage_grid.py`, 0.5 m 격자 177점, 브리지와 같은 trace, 결과 Spark `/workspace/gpuch/r1/ring-coverage-refr.{csv,json,png}`):** LOS(+x) 66점 −0.54…−2.88 dB(중앙값 −1.6), 그림자(−x) 최악 −35.6 dB, 기둥 사이 틈은 LOS(−2.7…−3.4). 즉 **동쪽 절반 ≈ −2 dB, 서쪽은 기둥 뒤 0.8 m 폭 띠 세 줄이 −27…−36 dB이고 그 사이는 LOS** — 피켓 무늬. refraction 끈 첫 실행에서는 그 띠 31점이 outage였다. LOS/NLOS 차 **≈25–33 dB**.
- **이 차이가 20 MHz srsUE 링크에 의미가 있으려면 잡음 바닥이 있어야 한다.** Sionna 모드 토폴로지는 `sionna_rt` 모델 체인에 tdl 탭만 있고 AWGN 단계가 없다(fixed-TDL multi-UE 토폴로지는 `awgn snr_db 30/15`가 있음). 잡음이 없으면 −27 dB 탭도 float IQ 경로에서는 그냥 디코딩된다. **R4에서 sionna 모델 체인에 `awgn` 단계를 넣어 LOS에서 SNR ~25 dB, 그림자에서 ~0 dB가 되게 잡는다.** 절대 레벨 자체는 검증 범위 안: 브리지 기본 `--gain-offset-db 60`에서 LOS 최강 탭 −0.5…−3 dB는 legacy fixture(−3 dB)와 같고, 마스트를 15 m 밖에 둔 이유가 이것이다(펜스 옆이면 0 dB를 넘는다).
- **발견(스코프 밖, R4 차단 요인):** `scripts/native/render-sionna-multi-ue-configs.py`가 4-UE 옵션 커밋 `9043202` 이후 `legacy.UES` 전체(ue0–ue3)와 비교해서 **2-UE Sionna 시나리오를 거부한다** — 기존 `sionna-multi-ue-sutd.json`도 같은 이유로 거부됨(`run-ocudu-sionna-multi-ue.sh`는 `OCUDU_NATIVE_MUE_UE_COUNT=2` 고정인데 렌더러는 그 슬라이스를 안 본다). `tests/test_robot_ring_scene.py`는 2-UE 슬라이스로 형태 검사를 통과시키고 이 사실을 주석에 남겼다.
- 테스트: `tests/test_robot_ring_scene.py`(시나리오 링크 집합·refraction·씬 해석·지오메트리·생성기 결정성·렌더러 형태) + 기존 `test_sionna_launcher/test_sionna_rt_adapter/test_build_osm_scene/test_demo_topology` 모두 `/usr/bin/python3 -m unittest`로 OK. 워크스테이션 5090 대조 실행은 Sionna venv가 호스트에도 컨테이너에도 없어 생략.

### R2 — 2026-09-29 (로봇 아레나, 워크스테이션 로컬)

**만든 것.** `scripts/robot_fight/` — `protocol.py`(와이어 포맷), `arena.py`(MuJoCo 월드 + 심판 + 로봇별 UDP 서버 + 위치 PUB), `brain.py`(로봇당 제어기 프로세스), `fight.py`(N판 러너 + 핸디캡 프록시 + 요약), `README.md`. 테스트 `tests/test_robot_fight_protocol.py`(5) + `tests/test_robot_fight_smoke.py`(5 s 헤드리스 1판, RTF 0.9–1.1 확인) — venv `~/ocudu-work/venvs/robot`(mujoco 3.14.0, numpy 2.5.3, pyzmq 27.2, pytest)에서 6/6 통과.

**프로토콜 (R3·R4 공유).**
- UDP 제어면: 32 B 헤더 `magic RF, version 1, kind(1 STATE/2 CMD), robot_id, seq u32, t_send_us u64, echo_seq u32, t_echo_us u64`. STATE(로봇→두뇌, 100 Hz, 92 B): sim time, 내 pose/속도, 상대 pose/속도(심판이 주는 전역 관측), 링 반지름, 가장자리까지 거리, flags(running/over/won/lost). CMD(두뇌→로봇, 50 Hz, 44 B): 좌/우 바퀴 각속도 + `ttl_ms`. 아레나는 STATE마다 가장 새 CMD를 echo하므로 **RTT = now − t_echo_us**를 시계 동기 없이 양쪽에서 잰다. 편도는 같은 시계일 때만 유효.
- 위치면: ZMQ PUB(아레나 bind, 브리지 connect), 기본 `tcp://127.0.0.1:5570`, 20 Hz, `{"event":"positions","t_unix_ms","frame":"arena","nodes":{"ue0":{"position_m":[x,y,z],"velocity_mps":[..]},"ue1":…}}`. 링 중심 원점, z 위, 미터, z = 안테나 높이 0.3 m. SUB 쪽으로 실측 19 Hz, R3의 `parse` 계약과 일치. `ipc://` 엔드포인트도 그대로 됨(R3 게이트 배선).

**아레나 설계.** 링 반지름 **2.0 m**(4 m 링에선 40 s 안에 아무도 못 밀어냄), 스폰 ±0.5R 마주 보기 + 시드 지터. 봇: 30×24×8 cm 섀시 4 kg(2 kg은 바닥 밸러스트), 반지름 6 cm 구동 바퀴 2개(속도 액추에이터 ±30 rad/s → 1.8 m/s), 캐스터는 바닥에서 4 mm 띄움(**처음엔 캐스터가 무게를 받아 바퀴가 헛돌았다** — 6 s에 0.5 m), 앞판은 낮고(섀시 중심 아래 1 cm) 미끄럽게(μ 0.05; 그전엔 접촉이 걸려 상대가 뒤집혔다). 심판: 몸 중심이 링 밖 → ring_out, 기울기 up<0.3 → fall, 시간 제한(60 s) → draw. **Wall-clock 스텝**: 1 ms 루프마다 물리를 `sim0 + 경과 wall`까지 전진, `rtf`/`late_loops`(>2 ms 뒤처짐)/`max_lag_ms` 기록. `--lockstep`은 디버그 전용, 결과 JSON에 `lockstep: true`로 남는다. 명령 부재 정책 `--stale-policy` **coast**(기본, 모터 드라이버 off = 바퀴가 자유 회전, 밀리는 상태) / zero(제동) / hold(마지막 명령 유지) — 처음 fresh 명령 이후부터 stale 구간을 센다.

**두뇌.** `pusher`: 같은 봇끼리 정면 밀기는 교착이라(head-on 프로브: 6 s 동안 둘 다 제자리) **측면 돌아가 옆구리 밀기** — 상대 진행 방향에 수직인 0.7 m 지점으로 간 뒤 상대 heading에서 55° 이상 벗어나면 돌진, 접촉 1.5 s 지나면 0.6 s 후진하며 반대 측면으로. 가장자리 0.45 m 안에서 바깥 방향이면 감속. 시드로 파라미터 ±10 % 지터 + heading 잡음. `--policy module:callable` 훅(LLM은 나중). 수신 스레드 분리(도착 시각이 틱에 양자화되지 않게), RTT 샘플은 명령당 첫 echo만.

**측정 (워크스테이션, 6판 병렬, 각 프로세스 wall-clock).**

| 배치 | 설정 | ue0:ue1:draw | ue0 승률(결정된 판) | 이유 | ue1 RTT p50 |
|---|---|---|---|---|---|
| 노이즈 플로어 | 링 2.5 m, v 1.2, 60 s, N=30 | 5:5:20 | 0.50 (CI 0.24–0.76) | ring_out 10, timeout 20 | 10 ms |
| +50 ms 편도 (ue1) | 같은 설정, N=12 | 1:1:10 | 0.50 | | 106 ms |
| +100 ms 편도 (ue1) | 같은 설정, N=12 | 3:0:9 | 1.00 (CI 0.44–1) | | 206 ms |
| 손실 10 % (ue1) | 같은 설정, N=12 | 3:1:8 | 0.75 | | 6 ms, cmd gap 257 |
| 손실 30 % (ue1) | 같은 설정, N=12 | 1:2:9 | 0.33 | stale 4.2회/0.13 s | 7 ms, cmd gap 812 |
| 노이즈 플로어 t2 | **링 2.0 m, v 1.6**(현재 기본값), N=18 | 2:1:15 | 0.67 (CI 0.21–0.94) | | 5.5 ms |
| +50 ms t2 | N=18 | 1:2:15 | 0.33 | | 106 ms |
| +100 ms t2 | N=18 | **11:2:5** | **0.85 (CI 0.58–0.96)** | ring_out 13 | 206 ms |

- RTF 모든 판 1.000(min 0.9999), late_loops 판당 13–62(1 ms 루프가 2 ms 넘게 밀린 횟수, max_lag 10–60 ms — 6판 병렬 시 OS 스케줄링), 두뇌 deadline miss ≤0.3회/판. CPU: 아레나 ~12 %/프로세스, 두뇌 ~4 %, 6판 병렬 전체 부하 ~30 %(24코어).
- 로컬 루프 RTT p50 5.5–10 ms = STATE 주기(10 ms) 양자화 + 두뇌 틱(20 ms)의 합이고 링크 자체는 0.6 ms(편도 p50). 즉 무선 없이 제어 루프의 기본 지연이 ~10 ms — R4에서 무선 RTT(R0 ping 29 ms)가 그 위에 얹힌다.
- **정책이 링크에 민감한가**: +100 ms 편도(RTT 206 ms)에서 승률 0.85로 명확히 뒤집힘. +50 ms(RTT 106 ms)와 손실 30 %는 잡음 안. 50 Hz 제어에서 이 정책의 민감도 문턱은 RTT 100–200 ms 사이 — R4의 무선 RTT ~30 ms는 이 정책으로는 그대로 보이지 않는다. 링크 차이를 보이려면 (a) 정책을 더 빠른 반응에 의존하게(회피/카운터, 저속 마찰), (b) 제어 주기를 100 Hz로, (c) 스케줄링 배틀(R5)에서 드롭·starvation을 유도해 stale 구간을 만들기 — 셋 중 R4 착수 전에 결정.
- **무승부 67–83 %가 가장 큰 결함.** 동등한 봇은 대부분 60 s 안에 결판이 안 난다. 승률 통계의 N을 잡아먹으므로 R4 전에 정책 손질(측면 진입 각·후진 규칙) 또는 규칙 변경(제한 시간 뒤 가장자리 거리로 판정) 필요. 후자는 한 줄이고 잡음이 적어 추천.
- 결과: `results/robot-fight/r2-{noise-floor,handicap-d50,handicap-d100,handicap-l10,handicap-l30,t2-nf,t2-d50,t2-d100}/` (fight별 arena/brain JSONL + summary.json/md; git 제외).

**R4가 알아야 할 것.** 아레나는 UE 쪽(로봇마다 소켓 하나, `--robot-bind ue0=<ue0 tun ip>:6000,ue1=<ue1 tun ip>:6001` — srsUE 둘이 각자 netns면 아레나를 둘로 쪼개거나 두 netns에 닿는 곳에서 bind), 두뇌는 gNB/N6 쪽에서 `--robot <ue ip>:port`로 보낸다. 아레나는 첫 CMD에서 두뇌 주소를 배우므로 NAT/tun 뒤여도 된다(`--state-dest`로 고정 가능). 위치 PUB `--positions-endpoint`는 브리지가 있는 netns에서 닿는 `ipc://` 경로로. 편도 지연 로그는 아레나·두뇌가 같은 호스트 시계일 때만 의미 있다. 두뇌는 STATE의 over 플래그에서 종료.

### R3 — 2026-09-29 (브리지 외부 위치 입력, Spark dry-run)

**인터페이스.** `scripts/sionna_rt/run_bridge.py`에 `--position-endpoint <zmq>`(SUB, connect), `--position-frame-offset x,y,z`(아레나 원점을 씬 미터로; 모든 라이브 위치에 더함), `--position-timeout-s`(기본 1.0) 추가. 플래그가 없으면 `update_positions`는 이전과 같은 코드 경로(스크립트 Motion)를 탄다. 메시지는 R2가 정한 그대로:

```json
{"event":"positions","t_unix_ms":1790000000000,"frame":"arena",
 "nodes":{"ue0":{"position_m":[x,y,z],"velocity_mps":[vx,vy,vz]},"ue1":{...}}}
```

- 갱신마다 소켓을 **끝까지 비우고 가장 새 프레임만** 쓴다(latest-wins). 느린 trace 뒤에 낡은 위치가 줄줄이 재생되는 일이 없다. 밀려난 프레임은 `messages_dropped`로 센다.
- 프레임에 없는 노드는 그대로(스크립트 경로), 시나리오에 없는 노드 id는 무시하고 한 번만 경고. `velocity_mps`가 없으면 정지로 본다(도플러 0). 속도는 기존 `velocity_at`과 같은 경로로 Sionna tx/rx `.velocity`에 들어간다.
- 타임아웃이 지나면 **마지막 위치를 유지**하고 `stale: true`로 표시한다. 갱신 루프는 어떤 경우에도 피드를 기다리지 않는다(불변식 "아무도 기다리지 않는다"). 첫 프레임 전에는 `pending: true`이고 스크립트 위치를 쓴다.
- `sionna_rt_update` 레코드에 `position_source`("scripted"|"external") 와 `position_status`(endpoint, offset, `messages_received/invalid/dropped`, `last_sample_t_unix_ms`, `last_sample_age_ms`(poll 이후), `last_sample_publish_age_ms`(퍼블리셔 시각 기준 — 피드 지연), `stale`, `pending`, `ignored_nodes`, `node_sources`)가 추가됐다. `environment`에는 `position_endpoint/frame_offset_m/timeout_s`.

**게이트 배선.** `run-ocudu-legacy-1x1.sh`(→ `run-ocudu-sionna-1x1.sh`)와 `run-ocudu-multi-ue.sh`(→ `run-ocudu-sionna-multi-ue.sh`)에 `OCUDU_NATIVE_SIONNA_POSITION_ENDPOINT`, `OCUDU_NATIVE_SIONNA_POSITION_OFFSET`(`x,y,z`), `OCUDU_NATIVE_SIONNA_POSITION_TIMEOUT_S` → inner `--sionna-position-{endpoint,offset,timeout-s}` → 브리지 인자. 비어 있으면 브리지 명령줄은 이전과 동일. **브리지는 `unshare --net` 안에서 돌므로 `tcp://127.0.0.1`은 그 네임스페이스의 loopback이라 호스트 퍼블리셔에 닿지 않는다.** 그래서 게이트는 endpoint가 `ipc:///…` 절대 경로일 때만 받는다 — control/telemetry 소켓과 같은 규칙. 마운트 네임스페이스는 `/run/netns`만 bind-mount하므로 나머지 파일시스템은 공유되고, **아레나가 바깥에서 `ipc://` 소켓을 bind**하면 안쪽 브리지가 connect한다(connect가 bind보다 먼저여도 ZMQ가 재접속). 권장 경로: `ipc://${OCUDU_NATIVE_ROOT}/run/arena/positions.sock`(예: Spark `ipc:///workspace/ocudu-spark/run/arena/positions.sock`). `scripts/native/README.md`에 기록.

**테스트.** `tests/test_sionna_positions.py`(11개, Sionna·pyzmq 없이 가짜 transport로): 피드 없음→스크립트+pending, offset 적용·속도 전달·gNB는 스크립트 유지, latest-wins와 dropped 카운트, 타임아웃→마지막 위치 유지+stale, 미지 노드 1회 경고, 깨진 프레임 6종이 마지막 샘플을 덮지 않음, 인자 기본값/환경 레코드/타임아웃 검증. 워크스테이션 `python3 -m unittest tests.test_sionna_positions tests.test_sionna_rt_adapter tests.test_sionna_launcher` → 44 OK; Spark venv에서도 OK. 게이트 스크립트 4개 `bash -n` 통과.

**Spark dry-run(GB10, venv, 다른 GPU 프로세스 없음).** 퍼블리셔 `/workspace/gpuch/r3_publisher.py`: ue0가 반경 3 m 원을 0.5 rad/s로, ue1 정지, 미지 노드 `robotX` 포함, 20 Hz. 브리지 10 Hz `--dry-run`, 판정 `/workspace/gpuch/r3_check.py`(퍼블리셔 로그의 `t_unix_ms`와 레코드의 `last_sample_t_unix_ms`를 맞춰 위치 비교).

| 런 | 시나리오 | 갱신 | external | 위치 오차 max | solve 중앙/최대 | received/dropped/invalid | 비고 |
|---|---|---|---|---|---|---|---|
| A (10 s) | `ocudu-docker-multi-ue.json`, offset `-70,0,1.5` | 97 | 96 | **0.0 m** (96 매칭) | 43.5 / 463 ms(첫 갱신 JIT) | 196 / 100 / 0 | 첫 갱신만 scripted(SUB 접속 전), `robotX` 1회 경고, stale 없음 |
| B (8 s, 피드 3 s 후 중단) | 같음 | 80 | 79 | — | — | 48 | 3 s 이후 `stale: true`, age 5.6 s까지 증가, ue0 마지막 위치 유지 |
| C (6 s) | **R1 `robot-ring.json`**(링 씬, gNB 1 + UE 2, 6링크) | 61 | 60 | **0.0 m** (60 매칭) | **52.9 / 109 ms** | 119 / 59 / 0 | 방향별 17.3 / 33.6 ms, `publish_age` 44 ms |

- 20 Hz 피드를 10 Hz로 소비하니 절반이 dropped로 찍히는 게 정상이다(latest-wins). R4에서 피드 주기는 브리지 갱신 주기와 같거나 약간 높게 둔다.
- 링 씬 6링크가 53 ms로 1x1(49 ms)과 거의 같다 — Sionna는 방향(주파수)당 한 번 풀고 링크 수는 후처리라, 위험 항목의 "6링크 ~150 ms" 예상은 **빗나갔다(좋은 쪽으로)**. 10 Hz 예산 안.
- 위치→채널 적용 지연의 R3 몫은 poll 직후 resolve라 <1 ms; 전체 지연은 피드 주기 + solve(~50 ms) + control ack(0.5 ms) + 슬롯 경계. R4에서 브로커 `control_update` 슬롯과 조인해 측정.
- 남은 것(R2/R4): 실제 MuJoCo 아레나가 `ipc://` 소켓을 bind해 위 메시지를 보내고, 게이트 env로 브리지에 연결한 뒤 KPI 패널에서 채널이 따라오는 것을 확인. 게이트에는 이미 `OCUDU_NATIVE_SIONNA_DURATION_SECONDS`가 있어 sionna 1x1 게이트를 자동 종료시킬 수 있다(R0 교훈의 Ctrl-C 문제 회피).

### R4a — 2026-09-29 (무선 절반: 2-UE Sionna 게이트를 링 씬에서, Spark GB10)

R4의 무선 쪽 준비다. 아레나·두뇌(R2)를 붙이는 R4b는 별도. 결과 디렉터리는 전부 Spark `/workspace/ocudu-spark/results/{logs,reports}/ocudu-multi-ue/<ts>`, 래퍼 `/workspace/gpuch/r4a-run.sh <tag> [ENV=..]`, 분석 JSON `/workspace/gpuch/r4a-*-analysis.json`. GPU에 다른 프로세스 없음(런마다 `r4a-<tag>.gpu-before` 기록).

**고친 것 두 가지(R1이 찾은 차단 요인).**
1. `render-sionna-multi-ue-configs.py`가 4-UE 커밋 `9043202` 이후 2-UE 시나리오를 거부했다(테이블 전체 ue0–ue3와 비교, 그리고 `validate_subscriber`를 옛 시그니처로 호출해 TypeError). 이제 `--ue-count`(게이트의 `OCUDU_NATIVE_MUE_UE_COUNT`) 슬라이스와 비교하고 그 슬라이스의 가입자 fixture를 쓴다. 4-UE Sionna도 시나리오가 ue0–ue3를 이름 짓기만 하면 통과한다(self-test + `tests/test_sionna_multi_ue_renderer.py`).
2. Sionna 모드 토폴로지에 잡음이 없어 −27 dB 그림자도 무잡음으로 디코딩됐다. **`awgn snr_db` 스텝으로는 못 고친다** — 두 백엔드 모두 σ를 *현재(페이딩 후) 입력 전력*에서 유도하므로(`cpu_backend.cpp` Awgn, `cuda_backend.cu` build_steps) 그림자 UE도 같은 SNR을 받는다. 그래서 노드마다 `rx_model`(합산 수신 신호에 한 번 적용)에 **절대 `noise_power`** 를 둔다. `profile_swap`은 링크의 선행 tdl만 갈아끼우므로 바닥은 갱신 후에도 남는다(라이브 2,391회 갱신 동안 유지 확인). 코드 변경 없음(`noise_power`는 YAML-only 절대값으로 이미 있었다; `topology.sionna-multi-gnb.cuda.yaml`의 "reference power 1.0으로 SNR 변환" 주석은 코드와 맞지 않는다 — config.cpp는 부호 검사만 한다).

**잡음 바닥의 근거.** `noise = tx_power / 10^(ref_snr/10)`, ref_snr = 0 dB 탭 링크가 보는 SNR(`OCUDU_NATIVE_SIONNA_AWGN_SNR_DB`), tx_power는 **wire capture로 잰 실제 송신 레벨**(새 `OCUDU_NATIVE_MUE_WIRE_CAPTURE_SAMPLES`, `wire-capture-power.py`; 활성 샘플 = 피크 전력의 1e-3 초과, 유휴 슬롯 제외). 보정 런 `20260929T130021Z`(잡음 off, capture 4.6M 샘플 @100 s):

| 포트 | 방향 | 활성 비율 | 활성 평균 |x|² | 피크 진폭 |
|---|---|---|---|---|
| gnb0 | tx_in (OCUDU gNB 송신) | 5.0 % | **1.12e-2 (−19.5 dB)** | 0.39 |
| ue0 / ue1 | tx_in (srsUE 송신) | 0.7 % | **2.8e4 / 3.3e4 (+44/+45 dB)** | 313 |
| ue0 (LOS, −2.5 dB) | rx_out | 5.0 % | 1.13e-2 (−19.5 dB) | 0.39 |
| ue1 (그림자, −27 dB) | rx_out | 3.6 % | 1.9e-5 (−47.2 dB) | 0.015 |

srsUE의 ZMQ 라디오는 `[rf] tx_gain = 50`을 수치로 곱한다(10^(50/20) ≈ 316 = 피크 313), 그래서 UL은 DL보다 64 dB 크다. 워크스테이션 c4 캡처(CUDA gNB 4T4R)의 gNB 송신 −20.2 dB와 일치. 렌더러 상수 `TX_POWER_DL = 1.12e-2`, `TX_POWER_UL = 3.0e4`, env로 덮어쓸 수 있다. UL 기준은 ping만 있는 런의 PUCCH/SRS/작은 PUSCH 활동이라 광대역 PUSCH 기준으로는 보수적(잡음이 상대적으로 큼)일 수 있다 — R4b에서 트래픽이 생기면 gNB 쪽 UL BLER로 재확인.

**ref_snr 선택 — 실측(같은 링 씬, srsUE가 보고한 `dl_snr`).** 처음 목표(LOS 25 / 그림자 0 dB)는 srsUE가 못 버틴다.

| 런 | ref | 경로 | ue0 (LOS −2.5 dB) | ue1 (기둥 쪽) | 판정 |
|---|---|---|---|---|---|
| `130021Z` cal | off | robot-ring 1 m/s | 38 (포화) | 38, 그림자에서도 38 | PASS, 무잡음 |
| `130540Z` n1 | 26.6 | 〃 | **27** (공칭 24) | RRC만, PDU 실패, snr −10…+10 | FAIL |
| `131059Z` n2 | 34.6 | 〃 | 31 (공칭 32) | RRC 없음. gNB는 preamble 8을 검출(metric 45, 15 dB)해 RAR을 보냈지만 UE가 못 받음 — 첫 1 s 안에 기둥 그림자로 들어가며 RAR/Msg3이 그림자에 떨어진다(1 m/s면 LOS 틈이 레그당 ~0.5 s) | FAIL |
| `131640Z` n3 | 40 | 〃 | 34 (공칭 37.5) | RRC 없음(같은 이유) | FAIL |
| `132216Z` w1 | 34.6 | **robot-ring-walk** 0.2 m/s, LOS에서 출발 | 31 | attach 됨. LOS 틈 중앙 6.9 / 그림자 9.5 (재동기 상태가 섞임), out-of-sync 5,540줄(10 s마다 60–390), RRC Release 1회, ping 863 ms | PASS지만 불건전 |
| `132714Z` w2 | **40** | 〃 | **34** | **LOS 중앙 31 / 그림자 중앙 16, r(gain, snr) = 0.42**, out-of-sync 1,500줄(가장 깊은 −40…−44 dB 지점에서만 버스트), Release 없음, ping 37 ms, dl_bler 그림자 평균 3.2 % | **PASS — 기본값** |

- 보고값과 공칭값: 26.6 → 27(+3), 34.6 → 31(−1), 40 → 34(−3.5). srsUE의 추정이 고 SNR에서 눌린다. 그림자(공칭 ref − 27)는 40에서 16 dB로 읽힌다.
- **왜 1 m/s 시나리오로는 안 되나.** x = −2 선을 따라 기둥 그림자(|y| ∈ [1.5, 2.0], [−0.25, 0.25]…)와 LOS 틈이 ~1 m마다 번갈아 든다(R1 coverage: −27 ↔ −2.9 dB). srsUE의 초기 접속(PRACH → RAR → Msg3 → RRC)은 25 dB 계단을 몇 초마다 맞으면 끝나지 않는다. 그래서 `examples/sionna/robot-ring-walk.json`(R1 씬 그대로, 두 UE가 LOS 끝 y = ±3.4에서 출발해 0.2 m/s로 왕복)을 만들었다. R4b의 아레나는 로봇을 LOS에서 스폰하면 된다.
- 잡음 바닥이 GPU에 주는 비용: 브로커 kernel p50 19.6 → 23.9 µs(노드 3개 × AddNoise), p90 26 µs. `rx_starvations`는 cal 5 / w2 51(전부 attach 구간, heartbeat idle 52–53으로 세 장치가 같음).
- 회귀: 이전 기본 시나리오 `sionna-multi-ue-sutd.json`을 새 기본값(40)으로 `133230Z` — **PASS**(두 UE attach·ping, 카운터 0, starvation 5). ue0(차량) gain −16…−7.5 dB ↔ snr 20–30, r = 0.84. ue1(보행자)은 Sionna가 경로를 못 주는 구간(−100 dB)에서 out-of-sync — 바닥이 없을 때는 그 −100 dB 탭도 무잡음으로 디코딩됐으니, 이제 "통과"의 뜻이 물리적으로 맞아졌다.

**게이트 확장(`run-ocudu-multi-ue.sh` / `-inner.sh`, 기본값은 이전과 동일).** `OCUDU_NATIVE_SIONNA_AWGN_SNR_DB`(40, `off`), `OCUDU_NATIVE_SIONNA_TX_POWER_DL/UL`, `OCUDU_NATIVE_MUE_DURATION_SECONDS`(240, ≥160), `OCUDU_NATIVE_MUE_STRICT_REALTIME`, `OCUDU_NATIVE_MUE_UE_EXEC`(UE netns 안, ping 통과 직후, `{ue_id} {ue_ip} {ue_index} {ue_netns} {ue_gateway} {log_dir} {run_dir} {config_dir}`), `OCUDU_NATIVE_MUE_ROOT_EXEC`(스택 루트 ns, ogstun 직후, `{ue_ids} {ue_ips} …`), `OCUDU_NATIVE_MUE_WIRE_CAPTURE_SAMPLES/_SKIP_SECONDS`, `OCUDU_NATIVE_MUE_PIN_UES`. OAI 게이트와 같은 `platform-profile.py` 배치(spark-gb10: gNB 5-9 / 브로커 15-17 + `OCG_BROKER_SPIN=1` / srsUE 2대 18,19 공유 — 여섯 런 모두 rf_o/u/l = 0). srsUE마다 `--general.metrics_csv_enable`로 초당 metrics(`srsue-metrics-<ue>.csv` + `srsue-<ue>.start_unix_ms`). `attach-summary.json`에 control 카운터, 장치별 마지막 heartbeat, Sionna 갱신 수·position_source, rx_noise, `run-parameters.json`을 기록(판정은 그대로). 새 도구 `analyze-sionna-multi-ue-run.py`(metrics CSV ↔ 브리지 위치·링크 gain 조인, LOS/그림자 통계·상관), `wire-capture-power.py`. 문서 `scripts/native/README.md`.

**R4b가 쓸 것.** 아레나는 스택 루트 ns에서 `OCUDU_NATIVE_MUE_ROOT_EXEC`로(브로커·브리지·ogstun 10.45.1.1과 같은 netns → 위치 PUB는 `tcp://127.0.0.1`도 되지만 게이트는 `ipc://` 절대경로만 받는다: `OCUDU_NATIVE_SIONNA_POSITION_ENDPOINT=ipc:///workspace/ocudu-spark/run/arena/positions.sock`, offset은 링 원점이 씬 원점이라 `0,0,0`), 로봇 쪽 모뎀/릴레이는 `OCUDU_NATIVE_MUE_UE_EXEC`로 UE netns 안에서 `{ue_ip}`(10.45.1.2/.3)에 bind하고 두뇌는 `{ue_gateway}` 10.45.1.1. 시나리오는 `robot-ring-walk.json`을 외부 위치 입력으로 덮어쓰는 형태(스폰은 LOS 쪽). 브로커 ping RTT 기준선 30–37 ms.

**열린 것.** (1) legacy 1x1 Sionna 게이트는 "immutable legacy topology"를 그대로 profile_swap하므로 잡음 바닥 env를 받지 않는다 — 필요하면 렌더 후 `rx_model` 패치로. (2) 기둥 가장자리의 −40…−44 dB 지점에서는 40 dB 기준으로도 srsUE가 잠깐 동기를 잃는다; 더 부드러운 대비가 필요하면 R1의 재질 손잡이(glass −15 dB) 또는 ref 45. (3) 그림자에서의 BLER·MCS 저하는 트래픽이 있어야 보인다(지금은 ping뿐이라 MCS 0) — R4b의 50–100 Hz 제어 루프가 그 트래픽이다. (4) UL 잡음 기준의 보수성(위).
