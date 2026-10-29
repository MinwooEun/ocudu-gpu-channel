# GPU 채널 에뮬레이터 논문 기여 정리

작성 2026-10-02. 기준 트리 `integration-0928` (cb04f6c).

## 메인 기여

**실제 5G NR 스택을 끼운 채로, 다중 안테나·다중 링크 채널 에뮬레이션을 상용 GPU 한 대(통합 GPU 에지 박스 포함)에서 슬롯 데드라인 안에 돌리는 시스템.** 이를 가능하게 한 설계 원칙은 처리 단위를 포트나 링크가 아니라 **수신 노드**로 잡는 것이다.

기여는 아래 다섯 축의 교집합이다. 어느 축도 단독으로는 새롭지 않고, 다섯을 동시에 만족하는 시스템이 없다는 것이 주장이다.

| 축 | 이미 하는 선행연구 | 그 선행연구가 못 하는 것 |
|---|---|---|
| 실제 스택 in-loop | Tiny-Twin, ACHEM, rfsimulator, OWDT | CPU라서 포트 수 × 대역폭 × tap 수가 커지면 데드라인을 놓침 |
| GPU 채널 연산 | Triply Selective MIMO GPU (2018), CUDA 3GPP (2023) | 오프라인 계산. 실제 스택도 데드라인도 없음 |
| GPU + 실제 스택 | Sionna Research Kit | OAI 안에 박힌 모듈이고 공식 범위가 SISO |
| 다중 포트 + 실제 스택 + 실시간 | Colosseum / MCHEM (FPGA, 256×256) | 공유 테스트베드. 가져다 쓸 수 없고 상용 GPU 한 대로 재현 불가 |
| 상용 한 대 + 통합 GPU | Sionna RK (Spark, Jetson 공유 메모리) | SISO, 외부 broker 구조 아님 |

주의: ACHEM도 MIMO를 주장하므로 "다중 포트"만으로는 차별이 안 된다. 각 축을 단독으로 주장하지 말고 항상 "다중 포트를 데드라인 안에, GPU로, 한 대에서"로 묶어서 말한다.

## 선행연구 비교

가장 위협적인 두 줄은 Tiny-Twin(CPU로 전체 스택)과 Colosseum/MCHEM(FPGA로 다중 포트 실시간)이다. 전자에겐 "CPU가 무너지는 영역"을, 후자에겐 "상용 한 대"를 대어야 한다.

| 연구 | 구현과 주요 목적 | 검증의 중심 | 우리와 구별되는 점 |
|---|---|---|---|
| **우리 (ocudu-gpu-channel)** | 외부 ZMQ broker에서 GPU로 다중 링크·다중 포트 IQ 처리. Sionna RT 실시간 채널 갱신 | 합성 규모 실험, 플랫폼별 메모리 경로(RTX 5090 / Orin / GB10), OAI nrUE 2×2 rank-2 DL·UL, 100 MHz TDD attach, 2-gNB Sionna 모드 | 노드 단위 공통 샘플 구간, 링크별 상태 공유, GPU history 유지, 플랫폼별 데이터 경로 |
| [Colosseum / MCHEM](https://arxiv.org/abs/2110.10617), DySPAN 2021 | 128 SRN(서버 + USRP X310) → 256 RF 채널, 64개 Virtex-7 FPGA가 모든 송수신 쌍에 4-tap TDL FIR을 1 ms마다 갱신 | 실제 스택(srsRAN, OAI) 다수 노드 실시간 시나리오 재현 | **다중 포트 + 실제 스택 + 실시간은 이미 함.** 차이는 전용 FPGA 공유 테스트베드 vs 상용 GPU 한 대, 4-tap 고정 vs 임의 TDL/ray-traced |
| [Colosseum as a Digital Twin](https://arxiv.org/abs/2303.17063), TMC 2024 | 실제 환경 계측 → MCHEM 재현 | 실제 실험실 vs 에뮬레이션 통신 결과 일치 | 물리 환경 재현성 근거가 강함. 우리는 구현 비용·접근성 축 |
| [Tiny-Twin](https://arxiv.org/abs/2601.08217), 2026 | CPU 기반 OAI 전체 스택 에뮬레이션, UE당 최대 20 tap, 1 ms 갱신 | 10 UE 실시간, TTI p90 2 ms(1 ms 슬롯 초과). MIMO 언급 없음, 전부 단일 안테나 | **UE 수 축의 CPU baseline.** 포트×대역폭 축에서는 비교 데이터가 없으므로 우리가 재야 함 |
| [ACHEM](https://arxiv.org/abs/2604.04742), 2026 프리프린트 | CPU(EPYC 64코어) 가상 USRP, FIR tap 채널, 다중 노드. 프레임워크는 MIMO 스트림 지원 명시 | 실비행 재현, handover, 파이프라인 성능. **실험은 전부 1 TX/1 RX, 2 노드, ≤40 MHz.** 1 링크 85–167 µs, 16 소스 1 ms, 64 소스 2 ms | MIMO를 실제 스택과 데드라인 안에서 보인 적 없음. 수신기당 스레드 구조라 소스 수에서 500 µs를 넘김. 가장 중요한 직접 비교 대상 |
| OWDT, 2025 프리프린트 | 사전 ray tracing + OAI CPU 채널 + 상용 UE | 도시 이동에 따른 실제 5G 반응 | SISO, 100 ms CIR 갱신 vs 우리 다중 포트·실시간 Sionna 갱신 |
| Sionna Research Kit, 공식 자료 | OAI 내부 CUDA 채널 모듈, 온라인 CIR | 단위 테스트, 5G 연결 데모 | GPU·ray tracing·공유 메모리는 이미 있음. 외부 broker 구조와 다중 포트 범위가 비교점 |
| OAI rfsimulator | OAI 안 CPU 시뮬레이터 | AWGN, ray-tracing 채널 | 가장 쉽게 돌릴 수 있는 외부 baseline |
| CaST, WiNTECH 2022 | Colosseum 시나리오 생성·계측 | 설정 CIR vs 출력 CIR 일치 | 속도 경쟁이 아니라 **채널 정확도 검증 방법의 기준** |
| ColosSUMO, VNC 2024 | SUMO 차량 이동 + Colosseum 폐루프 | 통신 악화가 차량 제어에 미치는 영향 | 응용 폐루프. 우리 로봇 데모의 선행 사례로 인용 |
| Triply Selective MIMO GPU Simulator, 2018 | GPU 시간·주파수·공간 선택적 MIMO 채널 | 채널 특성, CPU 대비 가속 | **GPU MIMO·공간 상관 계산 자체는 선행기술.** 오프라인 |
| CUDA-Optimized 3GPP Channel Model, 2023 | CUDA CDL 계수 생성·FIR | CPU/GPU/FPGA 성능·전력 | 가속만. 실제 스택·데드라인 없음 |
| Low-Latency PC/USRP, 2022 | CPU·DPDK 저지연 신호 처리 | RF 입력부터 출력까지 지연 | 지연 측정 구간 설계에 참고 |
| GPU OTFS 시스템, 2026 프리프린트 | GPU OTFS 통신·채널 | BER 비교, 가속 요인 분해 | 경쟁자 아님. 검증 방법 참고 |

참고: 리포 README는 Colosseum 논문을 MobiCom 2021로 적었는데, arXiv 2110.10617은 IEEE DySPAN 2021 논문이다. README도 고쳐야 한다.

## 구현 아이디어: 노드 단위 설계

처리와 데이터 이동의 단위를 포트나 링크가 아니라 수신 노드로 잡는다. 세 메커니즘은 모두 이 원칙에서 파생되고, 논문 설계 섹션 세 개가 된다.

1. **공통 샘플 창 (시간·채널 상태 정합).** SISO 에뮬레이터를 여러 개 돌린다고 다중 안테나 에뮬레이터가 되지 않는다. 포트마다 요청에 따라 따로 처리하면 포트별로 다른 입력 구간을 소비하거나 채널 갱신 시점이 어긋난다. 수신 노드마다 producer 하나가 공통 샘플 창을 정하고, 한 번의 채널 처리로 계산해 각 수신 포트에 출력한다. 같은 물리 링크의 안테나 경로들은 채널 시간과 제어 상태를 공유하고, 갱신을 처리 경계에서 함께 적용한다. (`src/broker.cpp`)
2. **입력과 계수 재사용.** 채널 경로 수와 서로 다른 입력 수는 다르다. 송신 2 포트 × 수신 4 포트는 경로 8개지만 입력 IQ 스트림은 2개다. 노드 안에서 고유 송신 입력을 한 번만 준비하고 경로들이 참조한다. 페이딩 계수 생성을 채널 적용에서 분리해 같은 grid를 여러 block이 반복 생성하지 않게 하고, 같은 링크의 안테나 경로 grid를 모아 공간 상관을 적용한 뒤 convolution에 쓴다. 이전 입력 history는 GPU에 유지한다. (`src/device_channel.cu`)
3. **플랫폼별 데이터 경로.** GPU 연산이 빨라진 뒤에는 입력 준비와 복사가 지배한다. 노드 단위 버퍼를 장치 특성에 맞게 넘긴다.

| 플랫폼 | 데이터 경로 | 없애는 병목 |
|---|---|---|
| RTX 5090 (분리 GPU) | 입력을 device memory로 복사 후 처리 | GPU의 반복적인 host memory 접근 |
| Jetson Orin (통합, CMA 0) | mapped host memory | 별도 host-device 전송 |
| DGX Spark GB10 (통합, pageable access) | 호출자의 입력·출력 버퍼를 커널이 직접 읽고 쓴다 (`direct_in`) | host-device 전송과 CPU가 입력을 모으던 복사까지 |

지금 인용할 수 있는 수치 (ZERO_COPY_MILESTONES Z8, Spark GB10, 합성 N=64 gNB 노드):

| 항목 | copy | direct_in |
|---|---|---|
| 호출시간 p50 (µs) | 934.4 | 176.7 |
| 그중 CPU 입력 준비 (µs) | 523.7 | 7.1 |
| 라이브 브로커 p50 (µs) | 60–65 | 40 |

이 수치는 자체 copy 경로 대비이다. 외부 에뮬레이터보다 빠르다는 근거도, UE 64대를 실제로 지원한다는 근거도 아니다.

## 평가 계획

헤드라인 그림은 **"p99.9 데드라인 미스 0을 유지하는 링크 × 포트 × MHz를 CPU 백엔드, CUDA copy, 통합 GPU direct로 비교"** 한 장이다. 이 그림이 논문의 존재 이유인데 아직 없다. 지금 있는 수치들은 이 그림의 부품이다.

| 평가 축 | 무엇을 보이나 | baseline | 현재 상태 |
|---|---|---|---|
| 1. 스케일링 벽 | 포트 수 × 대역폭 × tap 수를 키울 때 CPU가 데드라인을 놓치는 지점과 GPU가 버티는 지점 | 같은 broker의 CPU 백엔드(GPU 기여를 깨끗하게 분리), rfsimulator, 가능하면 Tiny-Twin | 없음. 가장 먼저 할 일 |
| 2. 데이터 경로 ablation | copy / mapped / direct가 호출시간을 어디서 줄이는가 | 자체 copy 경로 | RTX / Orin / GB10 측정 있음 (Z 트랙) |
| 3. 정확성 | 채널이 의도한 행렬대로 적용되는가 | CPU/CUDA parity, y=Hx, 2×2 rank-2 처리량, CaST 방식 CIR 계측 | parity·y=Hx·rank-2 148/112 Mb/s 있음. CIR 계측 없음 |
| 4. 닫힌 루프 사례 | 실시간 위반이 물리 결과(로봇 승패)로 나타나는가 | 없음 (방법론 제시) | R 트랙 R0–R4a 통과. Sionna solve 50 ms / 10 Hz |

스케일링 실험 설계 주의: Tiny-Twin은 UE 수로는 CPU로 잘 버틸 가능성이 크다. UE 수가 아니라 **2×2 이상 포트와 50–100 MHz를 먼저** 밀어야 한다. 슬롯 예산은 30 kHz SCS 기준 500 µs.

## 보조 기여 후보

둘 다 섹션 하나 분량이고, 메인 기여에 "왜 GPU 에뮬레이터인가"를 보태는 역할이다.

- **Sionna RT 실시간 twin 루프 (R 트랙).** 로봇 위치 → Sionna RT solve → control plane → 슬롯 경계 적용까지 닫힌 경로가 같은 wall-clock에서 도는지는 아직 아무도 시험하지 않았다. 불변식 "아무도 기다리지 않는다"(strict-realtime broker, wall-clock MuJoCo, RTF 1.0 아니면 무효)가 실시간 검증 방법론으로 쓸 수 있다. OWDT의 100 ms 사전 CIR 갱신과 직접 대비된다.
- **포트 기반 에뮬레이터의 물리 일관성 (X 트랙 교훈).** 포트가 "한 반송파의 베이스밴드"일 뿐 broker가 반송파를 모르면, FDD에서 UE↔UE 엣지처럼 물리적으로 없는 간섭이 더해진다. srsUE ZMQ 송신 스케일이 gNB보다 64 dB 높아 이 가짜 간섭이 +62 dB까지 갔고 게이트는 통과로 나왔다. 수정은 포트에 carrier 의미 부여, 장치별 tx_scale 정규화, strict attach 판정. "에뮬레이터가 빠르기만 하면 되는 게 아니다"는 교훈 섹션으로 적합하다.
- **여러 플랫폼에서의 검증 규율.** 음성 대조군(exit≠0 확인), 메커니즘 로그 확인, 실패 측정 보존. 리뷰어가 실시간 주장을 믿게 만드는 장치로 평가 섹션 앞에 짧게 넣는다.

## 제출 전 체크리스트

지금 상태에서 리뷰어가 바로 찾아낼 구멍들이다. 위에서부터 치명적인 순서.

- [ ] **헤드라인 그림이 없다.** CPU 백엔드 vs CUDA 스케일링 곡선을 같은 broker로 뽑는다.
- [ ] **외부 baseline 비교가 하나도 없다.** rfsimulator 하나라도 같은 tap 수·대역폭에서 돌린다.
- [ ] **README가 "연속 2-UE 이동 트래픽과 strict zero-miss 실패"라고 적고 있다.** 실시간이 핵심 주장인데 자기 문서가 반증한다. 원인이 OCUDU gNB lower-PHY 스레드 정체(X6 계획)라도 리뷰어는 누구 탓인지 묻지 않는다. 고치거나 주장 범위를 좁힌다.
- [ ] **S10: 100 MHz 실시간을 막은 건 GPU가 아니라 CPU 배치였다.** 솔직히 쓰면 오히려 강점이 된다. "GPU 연산 뒤에 남는 병목은 lock-step 고리와 복사"라는 서사로 3번 메커니즘과 연결한다.
- [ ] **CUDA gNB PDSCH 2-port 결함(D10)과 50 MHz rank-2 비율.** 수정된 것과 열린 것을 갈라 적는다.
- [ ] **Delay/layout 변경 시 history 초기화.** "모든 채널 갱신의 연속성"으로 확대 주장하지 않는다. gain/phase 갱신만 연속.
- [ ] **저자·소유 정리.** 리포 리드는 Zhouyou Gu이고 broker 코어 일부는 선행 작업이다. 논문 기여는 본인이 만든 부분(C/J/S, Z, R, X, M 트랙)으로 잡고 리드와 초기에 합의한다.
- [ ] **README의 Colosseum 출처 수정.** MobiCom 2021이 아니라 DySPAN 2021.

학회는 SIGCOMM보다 MobiCom 또는 MobiSys가 맞다. 시간이 빠듯하면 MobiCom 워크숍 WiNTECH에 먼저 내고 본학회로 확장한다.

## Sources

- [Colosseum: Large-Scale Wireless Experimentation Through Hardware-in-the-Loop Network Emulation (arXiv 2110.10617)](https://arxiv.org/abs/2110.10617)
- [Colosseum as a Digital Twin (arXiv 2303.17063)](https://arxiv.org/abs/2303.17063)
- [Colosseum Wireless Network Emulator docs](https://colosseumwireless.readthedocs.io/en/latest/)
- 리포: `README.md`, `ZERO_COPY_MILESTONES.md`, `SPARK_MILESTONES.md`, `ROBOT_FIGHT_MILESTONES.md`, `CROSSTALK_MILESTONES.md` (integration-0928, cb04f6c)
