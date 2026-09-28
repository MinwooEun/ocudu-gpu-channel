# M6 — rank-2 SU-MIMO 라이브 acceptance 상세 설계

상위 문서: [`MIMO_MILESTONES.md`](https://github.com/zhouyou-gu/ocudu-gpu-channel/blob/5ffd73ea4afa2295b9a588b0b03a411329e81d9b/MIMO_MILESTONES.md) §2 M6 · 미션: [`AGENT_GOAL.md`](../../AGENT_GOAL.md)
선행: [`m5-live-integration.md`](m5-live-integration.md) · 배경: [`why-radionode-and-srsue-rank1-ko.md`](../why-radionode-and-srsue-rank1-ko.md)

---

## 0. 이 마일스톤이 존재하는 이유

M0~M5는 성공 기준을 **transport 수준**으로 정의했다. 그 결과 전 게이트가 green이면서도 "선언한 `H`가 실제로 rank-2 전송을 나르는가"를 요구하는 게이트가 하나도 없었다.

더 근본적인 실패는 그 위에 있다. **rank-2 acceptance를 수행할 UE가 존재하는지를 M0 착수 전에 정찰하지 않았다.** 한 시간짜리 조사였고, 다섯 마일스톤이 끝난 뒤에야 물었다. M6은 그 격차를 닫고, 이후 마일스톤은 최종 acceptance 경로를 먼저 정찰한다.

---

## 1. 확인한 사실 — 전부 소스 (2026-08-16)

### 1.1 막힌 계층은 UE 하나다

| 계층 | rank 2 | 근거 |
|---|---|---|
| gNB (OCUDU `a1916edcd`) | **가능** | `pdsch`/`pusch` `max_rank` CLI 옵션, `ue_channel_state_manager::get_nof_dl_layers()`; 상류 srsRAN Project가 2×2 DL 공식 지원(4×4 릴리스 존재) |
| 에뮬레이터 (이 저장소) | **가능** | M5.5가 라이브에서 측정: `max │y − Hx│` = 4.1e−08(DL) / 1.5e−07(UL), 허용 1e−04. 행별 교차항 기여 0.12~0.77 |
| UE (srsUE `eea87b1`) | **불가** | §1.2 |

에뮬레이터는 레이어 개념 자체가 코드에 없다 — 포트 도메인 IQ에 `H`만 적용하므로 **rank에 대해 불가지론적이고, 따라서 이미 rank-2-capable이다.** OCUDU의 DL ZMQ IQ는 precoding 이후 port-domain이라 `H` 적용 경계가 물리적으로 맞다.

### 1.2 srsUE가 정확히 어디서 막히는가 — 두 층이 동시에

| 위치 | 사실 | 결과 |
|---|---|---|
| `srsue/src/stack/rrc_nr/rrc_nr.cc:105` | `phy_cfg.carrier.max_mimo_layers = 1;` **하드코딩** | UE capability가 1 레이어 → **gNB가 애초에 rank 2를 스케줄하지 않는다.** 복호 이전 문제 |
| `lib/src/phy/phch/pdsch_nr.c:537` | 주석 그대로 `// Antenna port demapping ... Not implemented` | 포트 디매핑 부재 |
| `pdsch_nr.c:541` | `srsran_predecoding_single(q->x[0], channel->ce[0][0], ...)` | 단일 포트 등화. `ce[MAX_PORTS][MAX_PORTS]` 배열은 선언돼 있으나 NR 경로가 채우지 않는다 |
| `lib/src/phy/ue/ue_dl_nr.c:234,300,581,624,636` | 추정/복호가 전부 `sf_symbols[0]` | 두 번째 포트 샘플이 추정기에 진입조차 못 한다 |

`srsran_layerdemap_nr`은 **존재한다**(`pdsch_nr.c:543`). 즉 layer demapping은 있는데 그 위(capability)와 아래(포트 디매핑·등화)가 막혀 있어 도달하지 못한다. **어느 한쪽만 고쳐서 우회할 수 있는 종류가 아니다.**

> `max_mimo_layers = 1`은 [`why-radionode-and-srsue-rank1-ko.md`](../why-radionode-and-srsue-rank1-ko.md) §2.2가 "재확인하지 않았다"고 표시한 항목이다. 2026-08-16에 소스에서 확인했다.

### 1.3 OAI nrUE는 되는가 — 핀 커밋에서 직접 읽었다

**핀: `2026.w33` = `2b69bde6aeafe892cda1531a0f0cbba2e37792cd`.** 이 커밋은 조사 시점의 `develop` tip과 동일하므로, **아래 근거는 전부 핀된 커밋 자체에서 나온 것이다.**

| 확인 항목 | 결과 | 소스 |
|---|---|---|
| ZMQ 라디오 다채널 | **지원.** `tx_channels`/`rx_channels`가 주소 **목록**(`STRINGLISTPARAM`), `AssertFatal(num_configured_tx_channels == openair0_cfg->tx_num_channels)`로 채널 수 = 안테나 수 강제, **채널당 독립 폴 스레드** | `radio/zmq/zmq_radio.cpp`, `radio/zmq/README.md` |
| 와이어 프로토콜 | **바이트 수준 동일.** REP: `zmq_recv(&dummy,1)` → `zmq_msg_send(msg)`. REQ: 초기 요청 후 매 수신마다 `zmq_send(&dummy,1)` | `zmq_radio.cpp` |
| 페이로드 | **헤더 없는 cf32 인터리브.** `zmq_msg_init_size(total_samples * sizeof(cf_t))`, 0번지부터 `cf_t` | `zmq_imported.cpp` `zmq_tx_channel::transmit` |
| 수신 버퍼 | `rx_buffer_size = sample_size * 300000` — 우리 배치 23,040 대비 **13배 여유** | `zmq_radio.cpp:56` |
| nrUE DL rank 2 | **한다.** `dl_ch_estimates[(l * fp->nb_antennas_rx) + aarx]`(=[layer][rx] 2차원 채널추정), `nr_dlsch_mmse`(주석: *"For 2x2 MIMO matrix, we compute"*), `nr_dlsch_layer_demapping(Nl, ..., llr_layers[..][Nl][..])` | `openair1/PHY/NR_UE_TRANSPORT/nr_dlsch_demodulation.c` |
| OCUDU 연동 | OCUDU 공식 튜토리얼 존재. OAI 2026.w17이 호환 ZMQ 라디오 도입, **2026.w25 이상** 권장(그 이전은 CSI-RS 켠 상태의 상향에 CSI-PUSCH 다중화 문제) | `docs.ocudu.org/tutorials/oaiue/` |

우리 브로커가 상대에게 요구하는 규약은 **1바이트 더미 요청 → 헤더 없는 cf32 페이로드**가 전부이고(`recv_samples_into`는 `nbytes % sizeof(IqSample)`만 검사), 위 표가 그것을 충족한다.

### 1.4 부수 소득 — M5.4의 교착 구조가 UE 쪽에는 없다

OCUDU/srsRAN은 세션의 **모든** TX/RX 채널을 단일 `radio` 워커로 서비스하고(`create_prio_worker` → `single_worker`), 가득 찬 버퍼에서 **제자리 재시도**를 돌린다. 그 조합이 M5.4의 교착이었다.

OAI는 **채널마다 폴 스레드가 따로**이고, TX는 `queue_.push(msg)`로 큐에 넣어 폴 스레드가 pop한다 — **제자리 재시도가 없다.** 즉 M5.4형 자기 교착이 UE 쪽에서는 구조적으로 발생할 수 없다. massive MIMO(M7)로 갈 때 확장성 벽은 gNB 쪽에만 남는다.

### 1.5 워크스페이스 델타는 작다

| 항목 | 상태 |
|---|---|
| `git_sources` | OAI 항목 없음 → 추가 (현재 7개) |
| `build_profiles` | OAI 없음 → 추가 (현재 bison/gnutls/ocudu/srsran4g/open5gs) |
| deb 오버레이 (89행, `apt-get download` → user-space sysroot, `closure: user-space-overlay-only`) | libconfig-dev, libconfig9, libsctp-dev, libsctp1, libssl-dev, libyaml-cpp-dev, zlib1g-dev, ninja-build **이미 있음**. 부족: **libreadline-dev, libtool** 2개 (libtool은 cmake 빌드에 불필요할 수 있음) |

sudo 없이 user-space로 추가된다 — 하네스의 "의존성 부트스트랩은 user-space 우선" 규칙과 충돌 없다.

---

## 2. 설계

### 2.1 교체가 아니라 **추가**

srsUE를 걷어내지 않는다. `native-workspace.lock.json`의 `git_sources`는 배열이므로 OAI를 **추가**하고, **1×1 srsUE attach 게이트는 회귀 안전망으로 그대로 유지**한다. 지금까지 쌓은 게이트를 하나도 잃지 않는다.

### 2.2 왜 1×1을 먼저 거치는가 — 변수 분리

UE 교체와 rank 2를 한 번에 올리면 실패했을 때 원인이 (a) UE 교체 자체 (b) 다채널 ZMQ (c) rank-2 PHY 중 어디인지 분리할 수 없다. M5.4가 정확히 그 대가를 치렀다(격리 실험 하나가 무효였고 결론이 세 번 바뀌었다).

**M6.2에서 OAI를 1T1R로 먼저 붙여 attach/PDU/ping을 통과시킨다.** 그 지점을 통과하면 이후 실패는 다채널 또는 rank-2로 범위가 좁혀진다.

### 2.3 에뮬레이터가 왜 안 바뀌는가

RadioNode는 "ZMQ 엔드포인트 쌍 N개가 한 라디오"라고만 말하고, 그 N개를 **몇 개의 프로세스가 종단하는지 모르며 알 필요도 없다.** 그래서 UE 교체는 재설계가 아니라 실행 구성 변경이다.

감사 결과: 에뮬레이터 코어(`src/`, `include/`, `apps/`, `tests/`)에 srsUE 결합 **0건** — 매치되는 것은 srsRAN GRC 브로커 설계를 언급한 **주석 4줄**뿐이다. 2-port MIMO 게이트와 `gpu-test-sequence`는 합성 peer/도구를 쓰므로 무관하다. **결합은 1×1 라이브 attach 하네스 한 곳에만 있다.**

### 2.4 무엇을 주장하고 무엇을 주장하지 않는가

- **주장한다**: 실제 OCUDU gNB가 rank 2로 송신하고, 이 에뮬레이터가 선언된 2×2 `H`를 적용하며, 실제 UE PHY가 두 레이어를 공동 추정·등화·복호해 attach와 사용자 평면이 성립한다.
- **주장하지 않는다**: massive MIMO(M7), MU-MIMO, 빔포밍, 4 레이어 이상. 그리고 **처리량 수치는 하드웨어·대역폭·MCS·실행 시간을 명시하지 않으면 결과가 아니다**(하네스의 measured-envelope 규칙).

---

## 3. 작업 순서 (커밋 단위)

| 단계 | 내용 | 산출물 |
|---|---|---|
| **M6.1** | OAI 소스 핀 + 빌드 프로파일 + deb 2개 추가, `nr-uesoftmodem` 빌드(UHD off, ZMQ 라디오 on) | `native-workspace.lock.json` 갱신, `builds/oai-zmq-release`, `check-workspace.sh` 통과 |
| **M6.2** | **1×1 OAI 회귀 게이트** — OCUDU gNB 1T1R ↔ 브로커 ↔ OAI nrUE 1R | `scripts/native/run-oai-1x1.sh` + 검증 스크립트. srsUE 게이트는 그대로 유지 |
| **M6.3** | 2포트 승격 — gNB 2T2R ↔ 2×2 `H` ↔ OAI nrUE 2R, `maxMIMO_layers = 2` | 신규 fixture(gNB conf, OAI conf, 토폴로지), 게이트 스크립트 — **완료 2026-09-28** (§8) |
| **M6.4** | **rank-2 acceptance** + M5.5 행렬 검증 동시 통과 | acceptance 리포트, 뮤테이션 프로브 결과 — **완료 2026-09-28, 조건부** (§8.4) |

각 단계는 exit 게이트를 통과하기 전에 다음으로 넘어가지 않는다.

---

## 4. Exit 게이트

| 게이트 | 판정 |
|---|---|
| OAI 빌드가 핀에서 재현 | `git_sources`의 커밋과 빌드 산출물 해시가 리포트에 기록됨 |
| **1×1 OAI attach** | `rrc_connected` / `pdu_session_established` / `ping_ok` 전부 1, 브로커 strict counter 0 |
| **srsUE 1×1 무회귀** | 기존 게이트 재실행 `status=passed` (UE 추가가 기존 경로를 건드리지 않음) |
| 2포트 해석 | `event=radio_node_resolved id=ue0 ... implicit=false`, OAI가 채널 2개로 기동 |
| gNB가 rank 2를 스케줄 | gNB 로그/메트릭에 **`ri = 2`** 관측 |
| **UE가 2 레이어를 복호** | 2포트 구성에서 attach + PDU + ping 성립, UE 로그에 2-layer 복호 흔적 |
| **행렬이 동시에 맞다** | 같은 실행에서 `verify-mimo-matrix-capture.py` 통과 (`max │y − Hx│` ≤ 1e−04, 행별 교차항 기여 > 0) |
| 처리량 | rank 1 대비 유의한 증가. **하드웨어·대역폭·MCS·실행 시간을 함께 기록** |
| gNB 실시간 위반 없음 | gNB 로그에 `Real-time failure in RF` **0건** |

**행렬 검증과 rank-2 acceptance를 같은 실행에서 동시에 요구하는 것이 핵심이다.** 둘을 분리하면 "rank 2가 돌았지만 우리 행렬이 아닐 수도" 또는 "행렬은 맞지만 rank 1이었다"가 통과한다.

---

## 5. 뮤테이션 프로브 (FAIL 확인 후에만 게이트로 인정)

| 프로브 | 기대 |
|---|---|
| `maxMIMO_layers = 1`로 되돌림 | `ri = 2` 관측 실패 → acceptance FAIL |
| 행렬을 대각으로(교차항 0) | 행렬 게이트 FAIL (M5.5에서 이미 확인: 네 행 전부 0.052~0.284) |
| 행렬을 특이(singular)에 가깝게 | rank 2 유지 실패 또는 처리량 붕괴 — **분리 가능성이 실제로 측정되고 있다는 증거** |
| 형제 포트 epoch를 1샘플 어긋냄 | 행렬 게이트 FAIL (M5.5에서 확인: 네 행 전부 0.066~0.428) |

---

## 6. 리스크

| 리스크 | 대응 |
|---|---|
| OAI nrUE가 OCUDU gNB와 1×1조차 붙지 않는다 | M6.2가 그 지점이다. 붙지 않으면 rank 2로 올라가지 않는다. 핀을 w25까지 내리며 이분 탐색 |
| OAI ZMQ 라디오가 2채널에서 우리 브로커와 어긋난다 | 프로토콜은 소스로 확인했으나 **2채널 동시 동작은 미검증**. M6.3의 첫 실패 지점 |
| gNB가 rank 2를 스케줄하지 않는다 | CSI-RS/RI 보고 경로 문제일 수 있다. `max_rank` 설정과 CSI 설정을 먼저 확인 |
| OAI 빌드가 무겁다 | UHD/SIMD 옵션을 끄고 `nr-uesoftmodem` + ZMQ 라디오만 빌드 |
| 처리량 이득이 미미하다 | 실패가 아니라 **측정**이다. 채널 조건(`H`의 조건수)과 함께 기록한다 |

---

## 7. 이 마일스톤이 닫지 않는 것

- **massive MIMO** — M7. 3GPP는 한 UE에 DL 최대 8 레이어이고, massive MIMO는 MU-MIMO + 빔포밍이라 별개 문제다. 그리고 end-to-end로 되는 오픈소스 스택이 현재 없다.
- **MU-MIMO** — OCUDU 스케줄러에 co-scheduling 경로가 없다.
- **4 레이어 이상** — gNB `pusch_constants::MAX_NOF_LAYERS = 4`, srsRAN_4G `SRSRAN_MAX_LAYERS 4`.
- **srsUE의 MIMO 확장** — 하지 않는다. srsUE는 1×1 회귀 안전망으로만 남는다. 선회하려면 미션 개정이 필요하다.
- **M0의 라이브 부채 2건**(multi-UE / multi-gNB) — 환경 차단이며 M6과 무관하다.

---

## 8. M6.3 / M6.4 결과 (2026-09-28, 워크스테이션 RTX 5090)

브랜치 `oai-2x2`(워크트리 `~/ocudu-work/ocudu-oai-mimo`, `gb10-zero-copy`에서 분기). OAI `2b69bde6`(2026.w33), OCUDU `a1916edc`, 컨테이너 `ocudu-minwoo`. 셀: band 3 FDD, 20 MHz, 106 PRB, 15 kHz, 23.04 MS/s, `mcs_table: qam64`. 핀 트리(OAI·OCUDU)는 한 줄도 바꾸지 않았다.

### 8.1 8월의 차단 요인은 규약 차이가 아니라 OAI 2-layer 등화기의 int16 오버플로다

8월 정찰은 "UE가 ri=2 PDSCH의 93–96%를 NACK, QPSK도 동일, 채널 추정은 샘플 수준까지 정확"에서 멈췄다. 남은 용의는 MMSE / LLR / 디매핑 입력 3단계였다. 이번에 워크스테이션 direct 대조(브로커 없음)에서 똑같이 재현했다(`20260928T055037Z`: ri=2 568건, NACK 96%). 그 뒤 계측 빌드로 원인을 확정했다.

- **계측:** 임시 패치(`docs/evidence/m6.3/oai-zf-compare.debug.patch`, 별도 클론 `~/ocudu-work/oai-debug`에서 빌드, 핀 트리는 그대로)로 OAI가 쓰는 추출 샘플 `y`와 채널 추정 `H`를 받아 float zero-forcing을 따로 계산하고, OAI의 고정소수점 출력과 나란히 찍었다.
- **결과:** float ZF는 깨끗한 64QAM 점(±0.15/0.46/0.77/1.08)을 낸다. 즉 추정과 샘플은 맞다. OAI 출력은 같은 점에 약 48.8k를 곱한 값이라 int16을 넘어 감긴다(1.08 → −12.9k, −0.77 → +27.8k). `docs/evidence/m6.3/zf-vs-oai-equaliser.txt`.
- **메커니즘(소스):** `nr_dlsch_mmse`는 `inv(HᴴH)`가 아니라 **adjugate**를 곱하고 행렬식으로 나누지 않는다(행렬식은 LLR 문턱 `dl_ch_mag`로 넘긴다). 그래서 출력은 `det(G)·x / 2^(log2_maxh−1)`이다(G = HᴴH ≫ log2_maxh). 이 크기는 수신 진폭의 4제곱에 비례하고 `log2_maxh`(≈ log2|H|²/2, 정수)가 한 칸 오를 때마다 1/8로 떨어지는 톱니 모양이다. 진폭이 옥타브 안 어디에 걸리느냐에 따라 멀쩡하기도 하고 감기기도 한다.
- **왜 QPSK도 실패했나:** QPSK 점 0.707 × 48.8k = 34.5k도 넘친다. MCS를 낮춰도 소용없던 이유다.
- **왜 OAI 자체 시뮬레이터(dlsim)는 통과했나:** OAI gNB의 송신 진폭이 작아 톱니의 안전 구간에 있다. OAI의 OCUDU 2×2 CI 설정(`ci-scripts/yaml_files/5g_zmq_radio_2x2_ocudu/ocudu.yml`)에 `amplitude_control.tx_gain_backoff: 22`가 들어 있는 것과 맞아떨어진다. 다만 그 CI는 CSI-RS가 꺼져 있어 rank 2를 스케줄하지 않는다.

**조치:** 코드 수정 없이 gNB 설정 `ru_sdr.amplitude_control.tx_gain_backoff`(OCUDU 기본 12 dB)만 올린다. direct 28 dB에서 ri=2 3103건, NACK 0%(`20260928T055557Z`). 출력 크기는 약 15.9k로 감기지 않는다.

**진폭 창은 토폴로지마다 다르다(실측).** 브로커, 유니터리 H, DL UDP 60M, NACK 비율:

| back-off | 12 (기본) | 16 | 20 | 24 | 28 |
|---|---|---|---|---|---|
| 기준 H(조건수 1.6) | 2.7%(MCS 강하) | – | – | – | 0% |
| 유니터리 H | – | 1.3% | **57–60%** | **0%** | 0% |
| direct(항등 H) | **96%** | – | – | – | 0% |

20 dB 실패의 원인은 계측 빌드의 누적 통계(`docs/evidence/m6.3/equaliser-sign-errors.txt`)로 확인했다. PDSCH마다 `log2_maxh`가 10과 11 사이를 오가고, 10인 PDSCH에서 출력이 포화(|max| 31.4k)해 성분의 4–14%가 부호를 잃는다. 24 dB에서는 `log2_maxh`가 10으로 고정되고 |max| 5.6k, 부호 오류 0이다. **back-off는 토폴로지 이득과 함께 골라야 하는 운영 조건이고, 근본 수정은 OAI 쪽이다**(adjugate 출력을 행렬식이나 추가 시프트로 정규화). 상류 제보 후보로 기록한다.

### 8.2 M6.3 — 2포트 승격: 통과

`scripts/native/run-ocudu-oai-2x2.sh`(+ `-inner.sh`, `render-oai-2x2-configs.py`, `summarize-oai-2x2-run.py`). gNB 설정은 OAI 1×1 게이트의 렌더에서 안테나 2/2, 포트 2쌍, `pdsch.max_rank`, MAC pcap off, TX back-off만 바꾼다. OAI는 `--ue-nb-ant-rx 2 --ue-nb-ant-tx 2`, `uecap_ports2.xml`, ZMQ 채널 2개씩이다. 토폴로지 `examples/native/topology.ocudu.oai-2x2*.cuda.yaml`에서 gNB와 UE는 모두 2포트 radio node다.

- 2포트 해석: `radio_node_resolved id=ue0 tx[0]=ue0_p0 tx[1]=ue0_p1 ... implicit=false`
- gNB가 UE의 RI=2 CSI 보고(PUCCH F2 `csi1=1…`)를 따라 **ri=2를 스케줄**한다. 로그에서 CSI 보고가 바뀌는 슬롯에 맞춰 ri가 바뀌는 것을 확인했다.
- attach + PDU + ping 10/10, `Real-time failure` 0건(이번 세션 전 실행)
- UE 2-layer 복호: ri=2 PDSCH의 HARQ-ACK가 전부 ACK였고, 슬롯당 TBS는 18.9 kB로 rank 1 최대치(9.4 kB)의 2배다. 계측 빌드에서는 `nl == 2` 경로의 등화 출력을 직접 확인했다.

### 8.3 하네스 수리 (OAI 1×1 게이트, 워크스테이션 재가동)

8월 이후 이 호스트에서 처음 돌렸다. 네 가지를 고쳤고, 같은 날 OAI 1×1 `result=pass`(`20260928T054330Z`)와 srsUE 1×1 무회귀 `result=pass`(`ocudu-interop/20260928T063339Z`)를 확인했다.

1. 고정 기준 커밋 `bc88865`이 이 이력에 없다. fixture 바이트가 같은 `0c13a1a`(M6.2)로 바꿨다.
2. gNB 버전 문자열이 `OCUDU gNB (commit a1916ed)` 형식이다. 두 형식을 모두 받도록 했다.
3. `start_group` pgid 경쟁을 고쳤다. Spark에서 쓰던 패치를 inner 스크립트 4개에 적용했다.
4. OAI UE는 작업 디렉터리에 `nrL1_UE_stats-0.log`를 만들지 못하면 assert로 죽는다. userns에서는 cwd가 매핑되지 않은 uid 소유일 수 있어 로그 디렉터리에서 기동한다.

추가로 이 호스트는 자체 MongoDB/Open5GS를 띄우고 있다. 스택은 별도 netns라 충돌하지 않으므로, 이 경우 `OCUDU_NATIVE_ALLOW_HOST_PORTS=1`로 포트 사전검사를 끈다. OAI 빌드에는 sysroot의 `libtoolize` 경로 재배치와 컨테이너의 `xxd`가 필요했다(워크스페이스 쪽 조치이며 저장소 변경은 없다).

### 8.4 M6.4 — rank-2 acceptance: 통과 (조건 명시)

유니터리 2×2 H(`topology.ocudu.oai-2x2-unitary.cuda.yaml`, 이득 0.8, 조건수 1, 교차항 에너지 0.18), back-off 24 dB, 창 75 s, DL UDP 15 s @ 60 Mbit/s(벽시계) 제시. rank 1과 rank 2를 번갈아 2쌍 측정했다.

| 실행 | max_rank | ri=2 / ri=1 PDSCH | NACK | 슬롯당 TBS | 수신(벽시계) | 수신(공중 시간) | 행렬 검증 |
|---|---|---|---|---|---|---|---|
| `062227Z` | 2 | 4506 / 11 | 0% | 18.9 kB | 41.05 Mb/s | **148.4 Mb/s** | 통과 |
| `062350Z` | 1 | 0 / 4819 | 0% | 9.4 kB | 20.41 | **74.4** | 통과 |
| `062514Z` | 2 | 4501 / 10 | 0% | 18.9 kB | 40.93 | **148.6** | 통과 |
| `062637Z` | 1 | 0 / 4847 | 0% | 9.4 kB | 20.46 | **74.4** | 통과 |

- **처리량: rank 2 / rank 1 = 2.00×.** 두 쌍의 차이는 0.2 Mb/s 이내다. ZMQ 락스텝은 벽시계의 약 0.275배로 흐른다. 그래서 공중 시간 처리량은 iperf 수신 구간의 시뮬레이션 슬롯 수로 환산했다(`realtime_factor`). 두 모드 모두 셀 용량에서 포화한다(유실 24%/50%).
- **행렬이 같은 실행에서 맞다:** 브로커 wire capture(SFN 300–310, 100 ms)에서 `verify-mimo-matrix-capture.py` 통과. DL 두 행 `max|y−Hx|` ≤ 3.1e−08(허용 1e−04), 교차항 몫 0.416/0.429. 그 100 ms 안의 PDSCH는 rank-2 실행에서 100/100이 ri=2였다. UL은 행 오차가 7.9e−10 이하로 맞지만, **OAI UE는 1-layer PUSCH를 포트 0으로만 보내서 UE TX 포트 1이 0이다.** `--allow-silent-source ue0->gnb0:1`로 기록했고, UL 2×2는 주장하지 않는다.
- **direct 대조(항등 H):** rank 2 144.9 Mb/s(공중 시간). 에뮬레이터 2×2 H를 거쳐도 rank-2 처리량이 줄지 않는다.

**뮤테이션 프로브:**

| 프로브 | 결과 | 판정 |
|---|---|---|
| `max_rank: 1` | ri=2 0건, 74.4 Mb/s | 기대대로 |
| 거의 특이한 H(조건수 107, `-near-singular`) | UE가 여전히 RI=2를 보고(PUCCH F2 461/489) → ri=2 PDSCH NACK 94%, ping 실패(`062800Z`) | 분리 가능성이 실제로 측정되고 있다(처리량 붕괴). 단 **OAI UE의 RI 판정은 이 진폭에서 특이 채널을 걸러내지 못한다** |
| back-off 12(OCUDU 기본), direct | NACK 96% | 8월 증상 재현 = 원인이 진폭임을 확인 |
| back-off 20, 유니터리 H | NACK 57–60%, 부호 오류 4–14% | 톱니 창 확인(§8.1) |

**조건과 한계:**
- back-off 24 dB는 **이 토폴로지 이득(0.8)에 맞춘 값**이다. 다른 H나 경로 손실을 쓰면 NACK와 RI 안정성을 다시 확인해야 한다. 기준 H(조건수 1.6)와 유니터리 H @28 dB에서는 OAI의 RI 판정(CSI-RS 조건수 < 5 dB, `csi_rx.c`)이 RI 1/2를 오가서, rank 2는 102–106 Mb/s에 그쳤다.
- 실시간이 아니다(락스텝 0.275배). 브로커 `rx_starvations`는 75 s마다 약 12.3k로 두 모드가 같다(M6.2의 soft 신호와 같은 성격).
- UL MIMO, 64QAM 초과(qam256), 페이딩 채널에서의 rank 2는 이번 범위 밖이다.

**재현:**

```bash
docker exec ocudu-minwoo bash -c 'cd ~minwoo/ocudu-work/ocudu-oai-mimo && env HOME=/root \
  OCUDU_NATIVE_ROOT=/home/hyunsoo/ocudu-native-workspace CUDACXX=/usr/local/cuda/bin/nvcc \
  OAI2X2_PATH=broker OAI2X2_MAX_RANK=2 OAI2X2_TX_BACKOFF_DB=24 \
  OAI2X2_TOPOLOGY=$PWD/examples/native/topology.ocudu.oai-2x2-unitary.cuda.yaml \
  "OAI2X2_BROKER_EXTRA=--wire-capture-dir WIRECAP --wire-capture-samples 2304000 --wire-capture-skip 69120000" \
  bash scripts/native/run-ocudu-oai-2x2.sh'
# 행렬 검증(호스트 /usr/bin/python3에 numpy·yaml 있음)
/usr/bin/python3 scripts/native/verify-mimo-matrix-capture.py --capture-dir <log>/wire-capture \
  --topology <report>/topology.yaml --allow-silent-source 'ue0->gnb0:1'
```
