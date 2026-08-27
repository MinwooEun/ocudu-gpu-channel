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
| V1 | 5 ms 이상치 규명 | **완료** — 계측·재측정 끝. 규명 도중 `max_us`가 상수였음이 드러나 주장 자체를 정정 |
| V2 | 라이브 DL 다중 branch | **srsUE 수정·단위검증 완료 · 라이브 실행 1회 남음** — CSI-on fixture·no-waiver·핀 우회 scaffolding 준비됨 |
| V3 | 브로커 lifecycle | **소스 쪽 완료**(상태 명명 + cold-source admission, opt-in, 테스트) · **싱크 쪽 미해결** |
| V3.1 | `rx_headroom()` 자기 교착 | **완료** |
| V4 | 게이트 바이너리 출처 | **완료** — 라이브 실행에서 해시 독립 재계산 일치 확인 |
| V5 | demo 지원 경로 | **경로 C 완료** (원인 정정·티어별 명시) · A는 규모 판단 필요 · B는 이 호스트에서 검증 불가 |
| V6 | 측정 라벨 규칙 | **완료** |
| V8 | 캡처 트리거 다중포트 정렬 | **미해결 — 내가 만든 결함** (아래) |
| V7 | 게이트 실행 차단 요인 5건 | **4건 수정 · 1건 환경 제약** (아래) |

**닫힌 근거**: `20260827T102900Z` 네이티브 4×1 게이트 — attach + PDU + ping 0% 손실 + strict counter 0,
행렬 판정 `passed`(UL 4행 4.656e-05 / 2.138e-05 / 1.678e-05 / 2.784e-05, DL 5.306e-08), 2026-08-17
원본 수치를 행별로 재현. `ctest 8/8`.

---

## V7 — 게이트를 실제로 돌려보고 나온 것 *(리뷰가 "실행 가능하게 만들었다"고 한 범위)*

리뷰 지적 ①("게이트를 아무도 못 돌린다")에 대응해 실제로 돌려봤고, **게이트에 도달하기까지 다섯 번
막혔다**. 넷은 저장소 결함이라 고쳤고, 하나는 이 호스트의 환경 제약이다. 순서대로:

1. **matrix venv 프로비저닝이 조용히 실패** *(수정 완료)*. `/usr/bin/python3 -m venv`가 `ensurepip`
   부재로 실패해 pip 없는 venv를 남기고, 다음 줄이 없는 pip을 실행한다. 두 줄 다 `>/dev/null 2>&1`이라
   셸의 "No such file or directory"까지 삼켜지고 `set -e`가 **메시지 0줄로** 종료했다. 증상은 "드라이버
   로그 1줄 + 빈 결과 디렉터리"뿐. → `resolve_matrix_python()`으로 교체: 시도 전부 로그, 실패 시 무엇을
   시도했는지 명시, 그리고 **이미 numpy+yaml을 가진 인터프리터로 폴백**(이 호스트에선 conda python).
2. **`probe.sh`가 `docker compose`를 확인하지 않음** *(수정 완료)*. probe는 게이트가 돌 수 있는지
   알려주려고 존재하는데 `docker` 바이너리 유무만 봤다. 그래서 초록불을 준 뒤 게이트가 CUDA 빌드와
   ctest를 마치고 **4분 뒤에** compose에서 죽었다. → probe가 보고하고, compose를 쓰는 게이트 4개가
   빌드 **전에** 검사한다.
3. **이 호스트에서는 Docker 컨테이너가 아예 안 뜬다** *(환경 제약, 미수정)*.
   `docker run hello-world`조차 `runc create failed: ... open sysctl
   net.ipv4.ip_unprivileged_port_start: permission denied`. `systemd-detect-virt` = `lxc`.
   **이것은 이 저장소가 M0부터 문서화해 온 제약이고, 네이티브 rootless-netns 하네스를 만든 이유다.**
   따라서 리뷰가 만든 "지원 경로"(컨테이너)는 이 머신에서 실행 불가능하고, 리뷰가 "재현 불가"로 강등한
   **네이티브 경로가 여기서 유일하게 도는 경로**다. 지적 ①은 절반만 맞다 — 컨테이너 하네스가 일반적으로
   더 재현 가능한 것은 맞지만, 하드웨어에 따라 반대가 된다.
4. **네이티브 게이트 3개가 트립와이어에 걸려 시동 불가** *(수정 완료)*. `bc88865` 대비
   `scripts/remote/ocudu-attach-smoke.sh`·`common.sh` 무변경을 요구하는데, **`9eb2658`이 바로 그 파일을
   재작성했다.** 즉 "make every live rank-1 gate runnable" 커밋이 같은 자리에서 네이티브 게이트를
   못 돌게 만들었고, 같은 커밋이 네이티브를 "기록용"으로 강등해 아무도 재실행하지 않아 드러나지 않았다.
   게다가 네이티브 게이트는 그 파일을 **쓰지도 않는다**(가드 줄이 유일한 언급). → fixture 핀은 `bc88865`
   유지, 드라이버 핀은 재핀하고 **무엇을 잃는지 주석에 명시**.
5. **캡처 창이 두 시계 사이에서 흔들림** *(수정 완료)*. attach가 통과하고 ping이 0% 손실인 실행이
   `matrix_capture_status=failed`("captured only zeros")로 두 번 떨어졌다. 브로커 `acquired=` 카운터로
   측정: **모든 포트가 wall t=7 s까지 0 샘플**(마지막 라디오가 붙어야 노드가 전진한다), 20 s 런이
   도달하는 샘플 시간은 10.6 s뿐. UL은 샘플 시간 0~6 s에만 존재하는데 기본 skip은 6.00 s에 열린다.
   → `--wire-capture-trigger-port`: 그 포트의 **첫 유효 샘플**에 창을 앵커링. 무장 오프셋을 한 번
   원자적으로 공표해 포트 간 정렬을 보존(검사기는 자체 정렬을 하지 않는다). `test_broker` 회귀 테스트를
   양방향으로 검증(트리거 有 → 전부 유효 / 無 → 전부 무음, 실패).

기본값은 다섯 건 모두 **불변**이다 — 공개 수치가 측정된 조건을 바꾸지 않는다.

---

## V8 — 캡처 트리거의 다중포트 정렬은 증명되지 않았다 *(내가 만든 결함)*

캡처 창을 활동에 앵커링하면서(`--wire-capture-trigger-port`) 커밋 메시지에
*"무장 오프셋을 한 번 원자적으로 공표하므로 포트 간 정렬이 보존된다"* 고 적었다. **그 주장은
검증되지 않았고, 아마 틀렸다.**

각 포트는 공유된 오프셋을 **자기 카운터**에 적용한다. 그런데 카운터들이 서로 같지 않다 —
같은 런의 heartbeat에서 `gnb0_p0=239,823,660`, `ue0_p0=239,846,412`로 약 1 배치 차이다.
공유 오프셋은 카운터가 이미 일치하는 만큼만 정렬을 보존한다. 그것은 가정이지 보장이 아니다.

**관측 (2026-08-27, CSI-on 4T4R, 트리거 `ue0_p0`)**: UL 4행은 통과(4.6e-05 / 1e-04)했는데
DL 행이 `max|y−Hx| = 0.9316`으로 실패했다. 샘플의 93.5%는 **정확히** 일치하고, 어긋난 6.55%는
DL 듀티사이클(6.0%)과 같다 — 즉 **신호가 실린 샘플만** 어긋난다. `row=0`인데 `expected≠0`인
지점이 있고, lag를 −8 ~ +8 배치로 훑어도 오차가 무너지지 않는다(최소 0.3157). 단순 시프트가
아니다. UL 쌍은 트리거 포트 자신의 카운터를 쓰고 DL 쌍은 쓰지 않는다는 비대칭이 정황이지만,
**규명되지 않았다.**

`test_broker`의 `scenario_capture_trigger`는 **단일 포트만** 덮는다. 다중포트 정렬을 판정하는
테스트가 없었기 때문에 이 결함이 커밋을 통과했다.

**해야 할 일.**
1. 행렬 캡처는 당분간 **고정 skip으로 채점**한다(트리거 금지). 헤더 주석에 그렇게 적었다.
2. 트리거를 쓰는 다중포트 캡처가 정렬되는지 판정하는 테스트를 만든다 — 합성 토폴로지에서
   포트마다 다른 알려진 파형을 넣고, 캡처된 열들이 서로, 그리고 행과 정렬되는지 본다.
3. 정렬되지 않으면 무장 오프셋을 포트별 카운터가 아니라 **노드의 공통 슬롯 인덱스**로 표현해야
   한다. 그것이 브로커가 실제로 공유하는 유일한 시계다.

교훈 하나를 남긴다: **"보존된다"는 주장을 테스트 없이 커밋 메시지에 쓰지 말 것.** 단일 포트
테스트를 다중포트 주장의 근거로 삼은 것이 이 결함의 원인이다.

---

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

**진행: 소스 쪽 완료(opt-in) · 싱크 쪽 미해결.**

### 상태에 이름을 붙였다

토폴로지는 모든 peer를 **선언**하지만, peer가 실제로 말하기 전까지 브로커는 링만 보고
"선언됐고 아직 연결 안 됨"과 "연결됐고 잠깐 밀림"을 구분할 수 없다 — 둘 다 avail 0이다.
그 모호함이 이 항목의 전부다. `PortRuntime`에 두 상태를 두고 heartbeat에 노출했다:

- `tx_live` — 이 포트의 peer가 샘플을 **한 번이라도** 보냈다
- `rx_live` — 이 포트의 라디오가 응답을 **한 번이라도** 요청했다

`event=heartbeat ... live[tx=1 rx=0] ...` 로 매초 보인다. 이전에는 스톨이 어느 쪽인지
로그만 보고는 알 수 없었다.

### 소스 쪽: cold-source admission *(구현 · 테스트 완료 · 기본 off)*

`--admit-cold-sources` / `Broker::set_admit_cold_sources()`. 선언됐지만 `tx_live`가 아닌 lane은
`min(avail)`을 0으로 묶는 대신 **무음으로 기여**한다. 모든 lane이 cold면 노드는 페이싱된 무음
배치를 낸다(incoming이 없는 노드와 같은 모양). cold lane의 **커서는 움직이지 않으므로**, peer가
나중에 말하면 그 peer의 **첫 샘플부터** 읽는다 — 라디오가 보낸 것은 하나도 건너뛰지 않고,
존재하기 전의 무음만 건너뛴다.

`test_broker`의 `scenario_cold_source`가 계약을 못 박는다. gnb0에 ue0·ue1 두 lane을 두고 ue1은
**선언만 하고 연결하지 않는다**. 같은 토폴로지를 플래그만 바꿔 두 번 돌린 결과:

| | gnb0 수신 샘플 |
|---|---|
| `--admit-cold-sources` 없음 | **0** — 노드가 끝까지 전진하지 못함 |
| 있음 | **30,643,200** |

즉 플래그가 유일한 차이다. 라이브에서 이것이 만드는 차이는 "마지막 UE가 뜰 때까지 셀이 아무것도
내보내지 못한다" → "이미 뜬 라디오부터 셀이 돈다" 이다.

**기본 off인 이유**: 셀이 언제부터 생산을 시작하는지를 바꾼다. 공개된 게이트 수치는 전부 off로
측정되었고, 켤지는 게이트별 판단이다.

### 싱크 쪽: 미해결 — 그리고 왜 다음 추측을 하지 않는가

리뷰가 네 가지 브로커 변형을 만들고 각각을 죽인 측정과 함께 되돌렸다
(`docs/live-gate-results.md` "What was measured while trying to remove it").
남은 것은 대칭 문제다: 라디오가 아직 붙지 않은 포트가 **DL 히스토리를 쌓고**, 그 라디오가
뜨면 수분 묵은 공기를 받는다(실제로 늦은 UE가 앞 UE의 RAR을 백로그에서 복호해
`c-rnti=0x4601, ta=0`을 찍고 재시도를 멈췄다). 그리고 아무것도 안 듣는 싱크에서 그냥 버리는
수정은 `test_broker`가 *"broker served no RX requests"* 로 **올바르게** 거절한다.

`rx_live`가 이제 그 상태를 이름 붙이므로 설계는 표현 가능해졌다 — 후보는
"`rx_live`가 아닌 포트의 출력 링을 **최신 우선·상한 있는** 창으로 유지하고, 첫 요청이 오는 순간
FIFO로 전환" 이다. 버리는 것이 아니라 **가장 신선한 것을 상한 안에서 보관**하므로,
리뷰의 4번째 변형(전부 버림)이 깬 계약을 깨지 않는다.

**이 문서는 그것을 구현하지 않는다.** 리뷰가 네 번 시도한 자리이고, 판정하려면 네이티브 multi-UE
게이트(`scripts/native/run-ocudu-multi-ue.sh` — 컨테이너 게이트는 이 호스트에서 못 돈다, V7-3)를
before/after로 돌려야 한다. 그 측정 없이 다섯 번째 추측을 얹지 않는다.

**Exit 게이트 (변경 없음).**
1. `test_broker`의 multi-device relay 계약이 그대로 통과한다(약화 금지).
2. UE를 순차 기동해도 첫 UE가 마지막 UE 기동 전에 PDU 세션까지 도달한다.
3. 늦게 합류한 라디오가 받는 백로그가 **선언된 상한 이내**임을 게이트가 판정한다.
4. 4-UE 게이트가 UE별 preamble override와 무관하게 회귀 없이 통과한다.

1은 지금 통과한다. 2는 소스 쪽 수정이 필요조건을 만들었으나 싱크 쪽이 남아 미검증이다.

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

`demo/`는 티어별로 사정이 다르다. 실측:

| 티어 | 필요한 것 | 이 저장소만으로 |
|---|---|---|
| `:8080` 2×2 correlation | `build-cuda/ocudu-gpu-channel` + pyzmq/numpy | **가능** |
| `:8081` 1×4 SIMO steering | 위와 동일 | **가능** |
| `:8082` 라이브 | `~/ocudu-native-workspace` 전체 | **불가** |

**`:8082`가 불가인 진짜 이유 (정정)**. 초판은 리뷰 표현을 그대로 옮겨 "`/home/ubuntu`·`/opt/conda`가
하드코딩되어 있다"고 적었다. 세어보니 **그렇지 않다**:

- `OCUDU_NATIVE_ROOT`, `CUDACXX`는 이미 `${VAR:-기본값}` 형태이고 `bootstrap-workspace.sh`는
  `--root PATH`를 받는다 → **override 가능한 기본값**이지 하드코딩이 아니다.
- `scripts/native/`의 나머지 `/home/ubuntu` 출현은 **거부 조건**이다:
  `[[ "${native_root}" != "/home/ubuntu" ]] || usage_error "invalid native root"`.
  워크스페이스에 쓰고 지우는 게이트가 홈 디렉터리를 가리키는 것을 막는다. **지우면 이식성이 아니라
  위험이 는다.**

진짜 이유는 `scripts/native/bootstrap-workspace.sh:228` **한 줄**이다:

```bash
die "build provisioning is intentionally disabled: use --verify-only; no workspace changes were made"
```

usage가 왜인지도 적어둔다 — *"Build mode exits before mutation until every download/extract/build phase
is implemented and audited against the committed lock."* 즉 **아무도 워크스페이스를 처음부터 만들 수
없다.** 있는 것을 검증만 할 수 있다. lock이 핀하는 대상은 deb 94개 · 아카이브 3개 · git 소스 8개다.

**선택지 (셋 다 성격이 다르다).**

- **A — 프로비저닝을 구현한다.** 진짜 해결책이고 재현성을 실제로 만든다. 규모는 별도 프로젝트급:
  94개 deb와 8개 git 소스의 다운로드·추출·빌드를 단계별로 구현하고 lock에 대조해야 한다.
- **B — demo 라이브 티어를 컨테이너 하네스로 이식한다.** **이 호스트에서는 검증할 수 없다** —
  unprivileged LXC라 `docker run hello-world`조차 실패한다(V7-3). 검증 못 한 이식본을 지원 경로라고
  부르는 것은 리뷰가 지적한 그 문제의 반복이다. 다른 호스트가 있을 때의 선택지다.
- **C — 기록을 실측대로 고친다.** 완료. `demo/README.md`, `demo/ENVIRONMENT.md`, `HANDOVER.md`,
  보고서 §7이 이제 "경로 하드코딩"이 아니라 "프로비저닝 미구현"을 이유로 든다. 다음 사람이 경로를
  손보는 데 시간을 쓰지 않게 하는 것이 이 항목의 값이다.

**함께 처리한 것**: demo가 표시하는 S1 수치(9.53 / 7.01)에 창 크기와 단일 관측이라는 라벨을 붙였다.
SIMO 티어의 A↔B 재조향은 아직 브로커 재시작(~0.3 s)이며, 컨트롤 메시지 제안은
`docs/plans/fixed-mimo-swap.md`에 있고 리뷰 대기 중이다.

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
