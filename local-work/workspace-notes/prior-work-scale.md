# 선행연구 실측 규모 — ACHEM, Tiny-Twin

작성 2026-10-02. 두 논문 PDF 본문과 그림을 직접 읽어 정리했다. "그림에서 읽음"은 축 눈금에서 읽은 근사값이다.
- ACHEM: arXiv 2604.04742v1 (14쪽)
- Tiny-Twin: arXiv 2601.08217v1 (8쪽)

## 한눈에

| | ACHEM | Tiny-Twin | 우리 (integration-0928) |
|---|---|---|---|
| 처리 장치 | CPU, AMD EPYC 9534 64코어, 512 GB RAM, RT 커널 | CPU, AMD Ryzen 9 7900X 24코어 (시스템 $1,528) | GPU 한 대: RTX 5090 / Jetson Orin / DGX Spark GB10 |
| 안테나 / 포트 | 프레임워크는 "V-USRP당 다중 MIMO RX/TX 스트림" 지원 명시. **실험은 전부 1 TX / 1 RX** ("명확성을 위해") | **언급 없음, 전부 단일 안테나** | OAI nrUE 2×2 rank-2 DL/UL, gNB 4포트 rank-1 |
| 실제 스택 라이브 검증 | srsRAN LTE 10 MHz (50 PRB, 11.52 MS/s) UAV 1 + BS 1 · LTE handover BS 2 + UE 1 · OAI 5G TDD 20 MHz (23.04 MS/s) 2 노드 | OAI rfsim 개조, UE 1~16 (최적화 후 10 UE "실시간"), 대역폭·샘플레이트 **본문에 없음** | OAI 1×1 20~100 MHz, 2×2 20 MHz rank-2, srsUE 다중 UE, 2-gNB, Sionna 10 Hz |
| 채널 모델 | FIR tap (CIR 1/10/20 tap 벤치), 경로손실, 안테나 패턴, 잡음, 주파수 오프셋. 검증은 two-ray | UE당 time-varying CIR trace 1 ms 갱신, 상위 n tap sparse convolution, "20 tap/UE" | TDL-A..E, Jakes/Rician, 공간 상관, Sionna RT 행렬, 1023 샘플 지연 |
| 데드라인 정의 | 프레임 drop = 의도 전송 시각 + **5 ms** 초과. 통과 = drop ≤ 10 % | 슬롯 1 ms (3GPP TTI 선), **90th percentile ≈ 2 ms**를 "실시간"으로 간주 | 30 kHz 슬롯 500 µs, strict-realtime은 늦은 슬롯 drop, late 카운터 0 |
| 최대 규모 (수치) | 1 수신기 ← 16 소스 < 1 ms, 64 소스 < 2 ms · N×N: 20 MHz/0.5 ms 는 **L≈25~36 (N=5~6)에서 drop 10 % 초과**, 40 MHz/0.5 ms 는 **L≈9~16 (N=3~4)** | 10 UE × 20 tap, 슬롯 p90 2 ms. vanilla는 4 UE × 10 tap 이상이면 RTT 수백 ms | GB10 합성 N=64 fan-in 177 µs, 라이브 p50 40 µs, Spark 2×2 20 MHz NACK 0 |

## ACHEM 상세

**단일 링크 (Table I, L=1, 평균 µs)**

| 구성 | 샘플레이트 | 프레임 | end-to-end | 그중 잡음 생성·주입 | CIR |
|---|---|---|---|---|---|
| LTE-10MHz | 11.52 MS/s | 1 ms | 82.09 | 58.49 | 2.77 |
| LTE-20MHz | 23.04 MS/s | 1 ms | 161.44 | 123.10 | 5.49 |
| NR-20MHz | 23.04 MS/s | 0.5 ms | 84.66 | 58.45 | 2.77 |
| NR-40MHz | 46.08 MS/s | 0.5 ms | 167.21 | 124.33 | 5.49 |

- 처리 시간의 70 % 이상이 잡음 생성·주입이다. CIR convolution은 3~6 µs. 즉 ACHEM 단일 링크 비용은 채널이 아니라 잡음 샘플 셔플이다.
- 처리량 948~953 (1 ms) / 1894~1896 (0.5 ms) frames/s. drop 0.

**V-USRP 수신기 fan-in (Fig. 16)** — 수신기 1개가 N 소스를 받아 정렬·중첩. N = 1~64. "16 소스까지 < 1 ms, 64 소스까지 < 2 ms". 500 µs 슬롯 기준으로는 16 소스 이전에 초과한다.

**CHEM N×N 스케일링 (Fig. 17, 그림에서 읽음)** — N 송신 × N 수신, L = N², N = 1~10, CIR tap 1/10/20, 네 구성.

| 구성 | N=1 지연 | 지연이 500 µs를 넘는 N | drop 10 % 초과 지점 (L) |
|---|---|---|---|
| 11.52 MS/s, 1 ms | ≈80 µs | N≈7 (CIR 1), N≈6 (CIR 10/20) | L≈60 (CIR 1), L≈45 (CIR 10/20) |
| 23.04 MS/s, 1 ms | ≈150 µs | N≈5 (CIR 10/20), N≈8 (CIR 1) | L≈36 (CIR 10/20), L≈90 (CIR 1) |
| 23.04 MS/s, 0.5 ms | ≈80 µs | N≈5 (CIR 10/20), CIR 1은 N=10에서 ≈380 µs | L≈25~36 (CIR 10/20), CIR 1은 100까지 통과 |
| 46.08 MS/s, 0.5 ms | ≈160 µs (CIR 1), ≈500 µs (CIR 10/20) | CIR 10/20은 **N=1부터** ≈500 µs | L≈9~16 |

- 병렬화는 "수신기(CHEM-RX)마다 스레드 하나". 64코어 EPYC에서 N=10이면 스레드 10개.
- drop 기준이 5 ms라 500 µs 슬롯보다 10배 느슨하다. 같은 조건을 우리 기준(슬롯 안)으로 다시 재면 ACHEM 통과 영역은 더 좁아진다.
- 한계(§IV-E): 모든 V-USRP가 같은 호스트에 있어야 시간 동기 가능. PA 비선형, AGC, 위상 잡음 미모델.

## Tiny-Twin 상세

- **구성:** OAI rfsim을 개조해 UE 컨테이너 안에서 UL/DL convolution 수행. 채널은 외부 CIR trace 파일(1 ms 해상도). 대역폭, PRB, SCS, 샘플레이트는 본문에 없다. 안테나 언급 없음(단일).
- **vanilla (Fig. 2):** 5 UE에서 tap 0/1/5/9/13/17/20/50/100, 슬롯 계산 CCDF가 10 ms까지. 10 tap에서 p90 8 ms. UE 1/4/7/10/13/16, tap 1~20에서 CPU 사용률 최대 ≈1,800 % (18코어). ping RTT는 UE 수·tap 수에 따라 100~1,000 ms.
- **최적화 후 (Fig. 3):** UE 컨테이너당 2코어 핀, sparse convolution(상위 n tap). 5 UE × tap 1~20 슬롯 p90 ≈ 2 ms. 1 tap × UE 1/4/7/10 TTI CCDF가 ≈3 ms까지. ping RTT 45~70 ms로 tap 수와 무관. "20 tap/UE", "10 UE 실시간"이 주장치.
- **실시간 정의:** 그림에 "3GPP TTI = 1 ms" 선을 긋고도 p90 2 ms를 "타이밍 제약 충족 4배 개선"으로 쓴다. 엄밀한 데드라인 기준으로는 미달이다.
- **future work:** 다중 기지국·셀 간 간섭, 클러스터 분산. GPU·MIMO 언급 없음.

## 우리 주장에 쓰는 법

1. **포트 축은 비어 있다.** 두 논문 다 다중 안테나를 실험한 적이 없다. "2×2 rank-2를 실제 스택과 데드라인 안에서 입증"은 그대로 선다.
2. **대역폭 축에서 ACHEM은 40 MHz에서 이미 500 µs다.** 10/20 tap이면 단일 링크부터. 우리 100 MHz TDD attach와 직접 대비된다. 단 ACHEM 비용의 대부분이 잡음 생성이라, 공정하게는 "같은 impairment 세트"로 재야 한다.
3. **링크 축에서 ACHEM은 20 MHz/0.5 ms 에서 L≈25~36 링크가 한계다** (5 ms drop 기준). 우리 GB10 N=64 fan-in 177 µs와 같은 축이다. 하드웨어가 다르므로 CPU 백엔드를 같은 박스에서 돌려 재는 것이 정석이다.
4. **UE 축은 Tiny-Twin 영역이다.** 10 UE × 20 tap을 CPU 24코어로 p90 2 ms. 여기서 이기려 하지 말고, 같은 UE 수에서 포트·대역폭을 올렸을 때의 차이를 보인다.
5. **데드라인 정의를 통일해서 다시 그려야 한다.** ACHEM 5 ms drop, Tiny-Twin p90 2 ms, 우리 500 µs late 0. 한 그림에 넣으려면 "슬롯 안에 든 비율" 하나로 환산한다.
