# Rank-1 리뷰 대응 마일스톤 (V0–V6)

리뷰 대상 브랜치: `zhouyou-gu/ocudu-gpu-channel` `minwooeun-rank1-miso-simo-review-fixes`
(기준 HEAD `d00e84e`). 이 문서는 **상사 리뷰가 지적한 사항과 리뷰가 열어둔 항목만** 다룬다.
rank-1 로드맵 본체는 [`RANK1_MILESTONES.md`](RANK1_MILESTONES.md), 실행 기록은
[`docs/live-gate-results.md`](docs/live-gate-results.md), 대외 보고서는
[`docs/rank1-feasibility-report.md`](docs/rank1-feasibility-report.md).

## 현재 상태 (2026-08-27)

| | 항목 | 상태 |
|---|---|---|
| V0 | 문서를 현재 코드와 일치 | **완료** |
| V1 | 5 ms 이상치 귀속 | **계측 완료 · 라이브 재실행 대기** — 규명 도중 `max_us`가 상수였음이 드러나 이상치 주장 자체를 철회 |
| V2 | 라이브 DL 다중 branch | **미착수** — 결함 3건을 소스에서 특정, srsUE 패치 + 라이브 실행 필요 |
| V3 | 브로커 lifecycle | **미착수** (설계 결정 필요) |
| V3.1 | `rx_headroom()` 자기 교착 | **완료** |
| V4 | 게이트 바이너리 출처 | **완료** — 라이브 실행으로 산출물 1회 확인 필요 |
| V5 | demo 지원 경로 | **경로 B 완료** (티어별 재현 가능성 명시) · 경로 A 미착수 |
| V6 | 측정 라벨 규칙 | **완료** |

남은 것은 전부 **GPU 워크스테이션에서의 라이브 실행**이 필요하다. 여기까지는 저장소 안에서
빌드·테스트로 닫을 수 있는 것만 닫았고, `ctest 8/8`로 확인했다.

## 리뷰가 지적한 것 (커밋 `9eb2658`)

> *"결과가 이 브랜치를 받은 누구도 실행할 수 없는 하네스에서 보고됐고, 공개된 주장 중 두 개는
> 검증을 통과하지 못했다."*

| # | 지적 | 리뷰에서의 처분 | 남은 일 |
|---|---|---|---|
| ① | 라이브 게이트가 저장소만으로 실행 불가 (`/home/ubuntu`·`/opt/conda` 하드코딩, 프로비저닝 비활성) | 컨테이너 하네스로 이식 완료 (`scripts/remote/ocudu-rank1-{2x1,4x1}-smoke.sh`) | **V4**(게이트 바이너리 출처), **V5**(demo가 아직 구 경로) |
| ② | p50/p99를 heartbeat 표본 n=18에서 계산 — 2만 슬롯 중 18개, 사실상 최대값 | 전 슬롯 5 µs 히스토그램 + `event=process_latency_summary` 도입, 수치 양방향 정정 | **V1**(5 ms 이상치 미규명), **V6**(재발 방지 규칙) |
| ③ | DL을 무조건부 "Yes"로 기술 — srsRAN은 port 0에만 방사, 라이브 DL 판정은 스칼라 검사로 축약 | 판정표를 "UL은 다중 branch Yes / DL은 절차만 Yes"로 한정 | **V2**(DL 다중 branch 라이브 증명) |

## 리뷰가 스스로 열어둔 것 (multi-UE 시리즈 `44bfdc3`…`d00e84e`)

- 브로커 lifecycle: `declared but not yet connected`가 1급 상태가 아니다 → **V3**
- `rx_headroom()` 재진입 자기 교착 → **V3.1**
- `docs/live-gate-results.md`가 `aedf56d` 시점에서 멈춰 있어 이후 3커밋과 모순 → **V0**

---

## V0 — 문서를 현재 코드와 일치시킨다 *(선행, 저비용)*

**문제.** `docs/live-gate-results.md`의 마지막 갱신은 `aedf56d`인데, 그 뒤 `7c97b33`→`6a6e136`→`d00e84e`
세 커밋이 결론을 바꿨다. 현재 문서에는 다음이 남아 있다.

- 제목 *"Why three and four UEs do not attach"* — `d00e84e`에서 **4/4 전원 첫 시도 attach**로 해소됨.
- *"Distinct propagation delay separates UEs"*를 "확인된 사실"로 기술 — `6a6e136`이 그 전제를
  **철회**했다. srsUE가 `preamble_index = 0`을 하드코딩하던 것이 진짜 원인이었고, 지연 분리는
  quad fixture에서 identity로 되돌려졌다(지연된 carrier는 identity carrier가 아니어서
  행렬 게이트를 `max|y−Hx| = 4.4e+02`로 깨뜨렸다).
- `RANK1_MILESTONES.md`의 다중 UE 절은 **2 UE까지만** 기록한다(3·4 UE 게이트와 preamble 근본원인 누락).

**Exit 게이트.**
1. `docs/live-gate-results.md`가 `d00e84e` 기준 사실만 단정하고, 폐기된 세 설명은 기존
   *"Corrections to earlier explanations"* 절로 이동해 **반증한 측정과 함께** 보존된다.
2. `RANK1_MILESTONES.md`에 3 UE·4 UE 게이트와 그 실측치가 들어간다.
3. `grep -n "do not attach\|distinct delays separate" docs/live-gate-results.md`가 현재형 단정으로
   걸리지 않는다.

**주의.** 반증된 설명을 **지우지 않는다**. 이 브랜치의 가치 절반은 "무엇이 왜 틀렸는지"의 기록이고,
리뷰 자신이 그 규칙으로 쓰여 있다.

---

## V1 — 5 ms 오버플로 이상치를 귀속시킨다 *(지적 ② 잔여)*

**문제.** 재측정은 p99.9까지 1 ms 예산 안이지만(4×1 gnb0 675 µs), **두 구성 모두 관측 최대값이
5 ms 오버플로 버킷에 걸린다**. 현재 히스토그램(`src/broker.cpp` `WorkerDiag::process_hist`,
1001 버킷 × 5 µs)은 **카운트만** 남기므로 그 슬롯이 *언제* *어느 단계에서* 발생했는지 알 수 없다.
문서는 "런 시작/종료 구간으로 보이나 귀속되지 않음"이라고 정직하게 열어두었다 —
그 상태로는 8포트 확장 시 예산 논의를 할 수 없다.

**해야 할 일.**
- 오버플로 슬롯(≥ 5 ms)에 한해 슬롯 인덱스와 단계 분해(`room`/`align`/`data`/`read`/`process`/
  `throttle`/`push`)를 rate-limited 1줄로 남긴다. 핫 경로 비용은 오버플로 빈도(전체의 <0.1%)에
  비례하므로 무시 가능하다.
- "런 시작/종료 가설"을 판정한다: 참이면 워밍업/티어다운 슬롯의 제외 기준을 **수치로 정의**하고
  정상 구간 max를 별도 열로 보고한다. 거짓이면 그것이 새 결함이다.

**Exit 게이트.** 2×1·4×1 각각에서 오버플로 슬롯 전부가 (a) 슬롯 인덱스 구간과 (b) 지배적 단계로
분류되고, 보고서 §5.3과 `docs/live-gate-results.md`의 "미해결" 문구가 그 분류로 교체된다.

**하지 말 것.** 오버플로 버킷 상한을 올려 이상치를 안 보이게 만드는 것. 지적 ②의 재발이다.

---

## V2 — 라이브 DL 다중 branch를 증명한다 *(지적 ③ 정면 해소, 최우선)*

리뷰가 축소한 유일한 **과학적** 주장이고, 이미 실측 근거가 있다.

**현재 baseline이 DL 단일 branch인 이유(소스 확인됨).** srsRAN은 SSB·PDCCH·SIB·RAR·페이징을 무조건
port 0에 싣는다. PDSCH의 포트 수는 물리 안테나 수가 아니라 **CSI-MeasConfig에서 유도**된다
(`ue_configuration.cpp:632`, `nof_dl_ports = csi_meas_cfg ? … : 1`). CSI가 꺼져 있으면 스케줄러가
셀을 1포트로 보고 omnidirectional 코드북 `make_one_layer_one_port(nof_ports, 0)` = `[1,0,…]`을
집는다. 그래서 tx1..3의 RMS가 정확히 0.0이고, 게이트는 그것을 `--allow-silent-source`로
**선언**한다(검사 완화가 아니라 실측 사실의 기록).

**이미 확보한 반증 (산출물에서 직접 확인).**
`~/ocudu-native-workspace/results/reports/rank1-4x1/20260818T063911Z/matrix-report.csi-on.no-waiver.json`

| 항목 | baseline (CSI-off) | **CSI-on 4T4R** |
|---|---|---|
| DL tx1/tx2/tx3 RMS | 정확히 0.0 | **0.00305 / 0.003076 / 0.00305** |
| `--allow-silent-source` | 필요 | **불필요** |
| DL row0 max abs error | — | **4.771e-08** (허용 1e-04) |
| off-diagonal share | — | **0.08238** (기준 0.05) |
| 행렬 판정 | passed (waiver 있음) | **passed (waiver 없음)** |

즉 **gNB가 네 branch를 실제로 합성해 방사했고 에뮬레이터가 그것을 정확히 통과시켰다.**
2포트가 안 되는 이유도 규명되어 있다 — TS 38.211 표 7.4.1.5.3-1에서 2포트는 row 3(주파수 할당 6비트
→ ASN.1 `other`)이라 srsUE 화이트리스트에 없고, 4포트는 row 4(3비트 → `row4`, FD-CDM2)로 srsUE가 아는 형태다.

**막고 있는 것 — 결함은 하나가 아니라 셋이다 (소스에서 직접 확인,
`~/ocudu-native-workspace/src/srsRAN_4G`, `lib/src/phy/ch_estimation/csi_rs.c`).**
초판 기술은 "PRB당 RE 1개 가정 한 줄"이었으나, 소스를 읽으면 row 4가 걸리는 지점이 세 곳이다.

1. **기대 RE 수가 density만으로 유도된다** (`csi_rs.c:611` NZP, `:962` ZP).
   `nof_re = csi_rs_count(density, rb_end - rb_begin)`인데 `csi_rs_count`는 density만 본다 —
   `density_three → 3·nprb`, `density_one → nprb`. 그런데 추출 루프는 row의 k-list 길이만큼
   뽑는다(`for k_idx < nof_k`). row 1은 density_three ↔ `nof_k = 3`으로 우연히 일치하고,
   row 2는 density_one ↔ `nof_k = 1`로 일치한다. **row 4만 density_one ↔ `nof_k = 2`(FD-CDM2)로
   어긋난다** → `count_re = 2·106 = 212`, `nof_re = 106` → `Unmatched number of RE (212 != 106)`.
   이것이 실제로 뜨는 오류다.
2. **스크램블 시퀀스 정렬도 같은 가정을 쓴다** (`csi_rs.c:631`).
   `srsran_sequence_state_advance(&sequence_state, 2 * csi_rs_count(density, rb_begin))` —
   rb_begin 아래 PRB들의 r(m)을 건너뛰는 코드인데, row 4는 PRB당 r 값이 2개이므로
   `2 · rb_begin · nof_k`만큼 넘겨야 한다. **기대 개수만 고쳐도 시퀀스가 절반 어긋난 채
   역확산되어 LSE가 무의미해진다.** 1번만 고치고 "통과했다"고 판단하면 안 되는 이유다.
3. **CDM 그룹이 0으로 고정되어 있다** (`csi_rs.c:577`, `:928` — `// Force CDM group to 0`).
   row 4의 4포트는 CDM 그룹 2개(j=0: 포트 0/1, j=1: 포트 2/3)에 나뉘어 있으므로, 1·2를 고쳐도
   srsUE의 CSI 측정은 **배열의 절반만** 본다. attach를 막지는 않지만, 그 실행에서 나오는 CSI
   리포트의 의미에 경계를 긋는다 — 리포트를 "4포트 측정"이라 부르면 안 된다.

**증상 재확인.** 위 1번 때문에 srsUE가 `Error measuring, aborting work DL`로 **그 슬롯의 DL을
통째로 폐기**한다 → PDSCH 복호 0건 → DL NAS 미수신 → `UE did not request a PDU session after
3000ms` → release. 두 실행 모두 `attach-summary.json`의 `"status": "ue_stack_blocker_no_attach"`.

CSI-RS 주기를 규격 최댓값 80 ms로 늘리면 폐기 681→170, PDSCH 복호 0→3으로 NAS가 인증 응답까지
진행하지만 포트 1~3의 에너지도 같은 비율로 얇아져 share가 **0.046376으로 기준 미달**
(`20260818T071217Z`, `matrix-report.csi80.no-waiver.json` → `status: failed`).
**증거와 완주가 배타적**이다.

**경로 A (권장) — srsUE를 고친다.** 이전 판단은 *"통합 상대는 패치하지 않는다"*였다.
**그 전제는 리뷰가 이미 깼다**: `6a6e136`이 preamble index 때문에 srsUE를 `release_23_11`에서
`zhouyou-gu/srsRAN_4G` master로 옮기고 `SRSUE_PRACH_PREAMBLE_INDEX`·`SRSRAN_4G_REPO`/`SRSRAN_4G_REF`
override를 도입했다. 즉 **패치 가능한 fork와 그 주입 경로가 이미 브랜치 안에 있다.**
수정 범위는 위 1·2 (`nof_re`를 루프가 실제로 방문하는 PRB 수 × `nof_k`로, 시퀀스 advance를
`2 · rb_begin · nof_k`로) 이며, 3은 **고치지 않고 경계로 기록**한다 — attach를 막지 않고, 손대면
포트 2/3용 두 번째 CDM 그룹 측정 경로를 새로 만드는 일이 된다.

**검증 순서 (이 순서를 지킬 것).** 통합 상대를 패치하므로 게이트 통과만으로 판단하지 않는다:
(a) srsRAN 자체 단위테스트 `lib/src/phy/ch_estimation/test/csi_rs_test.c`가 row 1·row 2에서
**회귀 없이** 통과 — 우연히 맞던 두 row를 깨뜨리지 않았는지 먼저 확인,
(b) row 4에서 `Unmatched number of RE`가 사라지고 `epre`가 유한하며 선언 전력과 일치,
(c) 그 다음에야 라이브 게이트.

**경로 B (A가 막히면).** CSI-on 실행을 **별도의 증거 전용 게이트**로 고정하고
(attach 완주를 요구하지 않되 그 사실을 게이트 이름과 산출물에 박아둔다), 판정표는 리뷰가 정한
"DL은 절차만 Yes"를 유지한다. 이 경우에도 V2는 **닫히지 않는다** — 열린 채로 정확히 기술된다.

**Exit 게이트 (경로 A).** 4T4R 라이브 게이트 1회 실행 안에서 동시에 성립:
1. `--allow-silent-source` **없이** DL 행 판정 `passed`, off-diagonal share ≥ 0.05
2. 같은 실행에서 PDU 세션 성립 + ping 250발 0% 손실 + strict counter 0
3. srsUE 패치가 `SRSRAN_4G_REF`로 핀되고 `source-evidence.json`에 기록

그때 보고서 판정표의 DL 행을 **"절차만 Yes" → "Yes (다중 branch)"**로 되돌릴 수 있다.
그 전에는 되돌리지 않는다.

---

## V3 — 브로커 lifecycle: `declared but not connected`를 1급 상태로

**문제.** `d00e84e`의 4-UE 통과는 preamble index 분리로 **우회**한 것이고, 리뷰가 규명한 근본 결함은
그대로 남아 있다.

- **소스 쪽**: 노드가 슬롯을 `common = min(avail)`로 잡는데, `avail == 0`이 "잠깐 밀린 peer"와
  "존재한 적 없는 peer"를 구분하지 못한다. 그래서 셀은 **마지막 UE의 라디오가 뜰 때까지** 아무것도
  내보내지 못하고, 먼저 뜬 UE는 구조적으로 attach할 수 없다.
- **싱크 쪽 (대칭 벽)**: 리스너 없는 싱크에서 "아직 요청 안 함"과 "영원히 요청 안 함"은 ring만으로
  판별 불가. 순진한 discard 수정은 `test_broker`가 *"broker served no RX requests"*로 올바르게
  거절했다 — **그 계약은 지킬 가치가 있다.**
- **stale air**: 라디오가 붙기 전 포트가 DL 히스토리를 쌓아, 늦게 뜬 라디오가 수분 묵은 공기를 받는다.
  실제로 늦은 UE가 앞 UE의 RAR을 백로그에서 복호해 `c-rnti=0x4601, ta=0`을 찍고 재시도를 멈췄다.

리뷰가 시도하고 되돌린 브로커 변형 4종과 각각을 죽인 측정은
`docs/live-gate-results.md` "What was measured while trying to remove it"에 있다. **다시 추측하지 말 것.**
리뷰의 결론은 *"토폴로지가 이미 모든 peer를 선언하므로, 브로커에 기대할 엔드포인트를 알려주고
`declared but not yet connected`를 `connected and briefly idle`과 구분되는 1급 상태로 두면 된다 —
window 계산 패치가 아니라 lifecycle·schema 변경"*이다.

**Exit 게이트.**
1. `test_broker`의 multi-device relay 계약이 그대로 통과한다(약화 금지).
2. UE를 **순차 기동**해도 첫 UE가 마지막 UE 기동 전에 PDU 세션까지 도달한다.
3. 늦게 합류한 라디오가 받는 백로그가 **선언된 상한 이내**임을 게이트가 판정한다
   (stale RAR 재사용이 불가능함을 C-RNTI로 확인).
4. 4-UE 게이트가 UE별 preamble override **와 무관하게** 회귀 없이 통과한다.

### V3.1 — `rx_headroom()` 자기 교착 *(작고 확실함, 선행 가능)*

`rx_headroom()`이 `rx_mutex`를 잡으므로 그 락을 이미 쥔 상태에서의 headroom 검사는 자기 교착한다
(리뷰의 `test_broker` 런 하나가 여기서 멈췄다). 인라인 계산으로 분리하고 **회귀 테스트를 붙인다**.
V3 본체와 독립적으로 먼저 닫을 수 있다.

---

## V4 — 게이트의 바이너리 출처 기록을 복구한다 *(지적 ① 잔여)*

두 경로 모두 문제가 있고, **문제의 방향이 서로 반대다.**

**native 경로 — 기록과 실행이 다르다.** `scripts/native/run-ocudu-rank1-2x1-inner.sh:304`와
`run-ocudu-legacy-1x1-inner.sh:298`은 둘 다
`builds/ocudu-gpu-channel-cuda-release/ocudu-gpu-channel`을 **실행**하지만, 상위 게이트는
`builds/ocudu-gpu-channel-rank1-cuda-release/`를 빌드·ctest하고 그 SHA-256을
`source-evidence.json`에 기록한다. 해당 기간에 프로덕션 C++ 변경이 없어 두 빌드는 기능상 같았으나,
**기록된 해시는 실제 실행된 바이너리를 가리키지 않는다.**

**remote(지원) 경로 — 기록 자체가 없다.** `scripts/remote/ocudu-attach-smoke.sh`는 하나의
`cuda_build`(`:190`)에서 빌드(`:251`)·ctest(`:257`)·실행(`:529`)을 모두 하므로 **불일치는 없다**.
대신 `grep -rl "source-evidence\|sha256sum\|hashlib" scripts/remote/`가 **0건**이다 —
게이트를 지원 경로로 옮기면서 native 경로가 갖고 있던 출처 증거(바이너리·설정 SHA-256, 소스 커밋 핀,
채널 소스 manifest)가 함께 오지 않았다. 보고서 §7이 증거로 인용하는 산출물의 절반이
지원 경로에서는 생성되지 않는다.

**Exit 게이트.**
1. `scripts/remote/`의 라이브 게이트가 **실제 실행 대상 경로를 실행 직전에 해싱**해
   `source-evidence.json`을 남긴다(스키마는 native 판을 재사용).
2. 빌드 대상과 실행 대상이 다르면 게이트가 **실패**한다(native 판의 불일치가 구조적으로 불가능해진다).
3. 보고서 §7의 증거 표가 지원 경로 산출물 경로를 가리킨다.

## V5 — demo 스택을 지원 경로로 올린다 *(지적 ①의 demo 판)*

`demo/`(커밋 `858dcdb`, `d97ec52`, `a63088a` — 이 브랜치로 이식됨)는 `scripts/native/env.sh`와
`scripts/native/render-rank1-*.py`에 의존한다. **그 경로가 바로 리뷰가 "재현 불가"로 분류한 경로다.**
지금 상태로 상사에게 demo를 내면 지적 ①을 그대로 반복한다.

**Exit 게이트 (택1, 정직하게 표시).**
- **A**: `demo/native/run-live-demo.sh`를 `scripts/remote/` 컨테이너 하네스 위로 이식 —
  저장소 + GPU 워크스테이션만으로 세 티어(:8080/:8081/:8082)가 뜬다.
- **B**: 이식이 이번 범위 밖이면 `demo/README.md`와 `demo/ENVIRONMENT.md` 첫 줄에
  **"지원 경로 아님 — native 워크스페이스 전제"**를 명시하고, 필요한 전제를 리뷰 기준
  (저장소만으로 무엇이 부족한지)으로 열거한다.

**함께 처리할 것.**
- demo가 표시하는 게이트 수치(S0/S1/S3: 9.53/7.01 vs 해석치 9.71/6.94 등)에 **n과 실행 ID를 병기**한다(V6).
- SIMO 티어의 A↔B 재조향이 아직 브로커 재시작(~0.3 s)으로 되어 있다. 컨트롤 메시지 제안은
  `docs/plans/fixed-mimo-swap.md`에 있고 **리뷰 대기 중**이다. 채택되면 재시작 없는 재조향으로 교체한다.

---

## V6 — 측정 라벨 규칙을 상시화한다 *(지적 ② 재발 방지)*

지적 ②는 코드 결함이 아니라 **보고 규율**의 결함이었다. 규칙으로 고정한다.

1. 백분위 수치는 **n을 병기하지 않으면 쓰지 않는다.**
2. **heartbeat 표본으로 백분위를 말하지 않는다.** `event=cpu_stage_timings`는 마지막 슬롯 1개다.
   백분위는 `event=process_latency_summary`에서만 인용한다.
3. 단일 런의 p50은 "대표값"이 아니라 **라벨된 관측**이다(h2d는 게이트 런 간 7.7–32.1 µs로 흔들리고
   커널만 안정적이다).
4. "관측 최대치 포함 예산 내" 류의 문장은 **오버플로 버킷이 비어 있을 때만** 쓴다.

**Exit 게이트.** 위 4항이 `AGENT_HARNESS`의 writing rules에 들어가고, 보고서 3판(ko/html/en)에서
n 없는 백분위가 0건이다.

---

## 남은 순서

```
V2 (DL 다중 branch)   ← 최우선. 근거는 이미 있고, 막는 결함 3건의 위치가 특정되어 있다
V1 (재실행)           ← 게이트 1회 재실행이면 최대값이 채워진다. V2 실행에 얹어도 된다
V4 (산출물 확인)      ← 같은 실행에서 source-evidence.json이 나오는지 보면 끝
V5 경로 A (demo 이식) ← 다음 제출 전에
V3 (브로커 lifecycle) ← 가장 크고 설계 결정이 필요하다. 추측으로 네 번째 시도를 하지 말 것
```

**한 번의 라이브 실행으로 V1·V4가 함께 닫힌다.** 4T4R 게이트를 한 번 돌리면
`event=process_latency_summary`의 실제 최대값과 `overflow_n`, 그리고 `source-evidence.json`이
동시에 생성된다. V2를 시도한다면 그 실행에 얹는 것이 가장 싸다.

## 주장 경계 (변경 없음)

모든 결과는 **"2×1/4×1 DL MISO, 1×2/1×4 UL SIMO"**로 기술한다. `end-to-end 4×4 MIMO`, rank>1,
UE 수신 빔포밍, PMI 폐루프, MU-MIMO를 주장하지 않는다. 다중 UE는 시간축을 공유하는 단일 레이어
사용자들이며 **동일-PRB MU-MIMO가 아니다**. V2가 닫혀도 이 경계는 그대로다 — V2가 바꾸는 것은
"DL 다중 branch가 라이브로 증명되었는가" 한 줄뿐이다.
