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
| **R1** | **링 씬** — 링 + 기둥/차폐물 Mitsuba XML, gNB 1 + UE 2 + crosstalk 시나리오 JSON, 커버리지 맵으로 LOS/NLOS 비대칭 확인 | 브리지 dry-run에서 링 위치별 탭이 물리적으로 말이 됨, 6링크 solve 시간이 갱신 주기 예산 안 | |
| **R2** | **로봇 아레나** — MuJoCo 스모봇 2대, ring-out 규칙, 두뇌 프로세스, UDP 프로토콜(seq+timestamp), 위치 PUB. 무선 없음 | 로컬 루프로 경기 완주, MuJoCo wall-clock 스텝, 명령 부재 정책 정의, 동일 두뇌 승률 50±x% 노이즈 플로어(N≥30) | |
| **R3** | **위치 → Sionna live** — 브리지 `update_positions`를 외부 입력(ZMQ SUB)으로 교체, MuJoCo → 브리지 → 브로커 | 로봇이 기둥 뒤로 가면 KPI 패널의 채널이 따라옴, 위치→적용 지연 < 예산 | |
| **R4** | **무선 폐루프** — srsUE 2대 attach(`run-ocudu-sionna-multi-ue.sh` 기반), 제어 루프가 tun 통과, RTT/손실 로그를 브로커 슬롯 로그와 조인 | strict-realtime on, RTF = 1.0 로그, 경기 완주, RTT 분포, 무효 판 규칙 적용 | |
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
