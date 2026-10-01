# X 트랙 — UE↔UE "crosstalk" 수정 (2026-10-01)

## 왜

멀티-UE 토폴로지에 UE↔UE 엣지(`ue1.tx → ue0.rx`, 이름 `crosstalk`)를 넣으면 UE가
붙지 않거나 30 s 안에 떨어진다는 보고가 있었다. 원인은 브로커가 아니라 두 입력이었다.

1. **존재하지 않는 경로.** 네이티브 fixture는 FDD band 3(DL 1842.5 / UL 1747.5 MHz)이다.
   한 UE의 상향 반송파는 다른 UE의 하향 수신기에 들어올 수 없다. 에뮬레이터의 포트는
   "한 반송파의 베이스밴드"이고 브로커는 반송파를 모르므로, 토폴로지에 그어진 선은
   무조건 더해진다. `topology.graph.cuda.yaml`(5-18, 업스트림), `topology.sionna-2gnb-2ue.cuda.yaml`
   (8-21), `multi-gnb-sutd.json`, `sionna_SUTD_test.json`, `robot-ring-crosstalk.json`(9-29, R1)이
   같은 선을 적었다.
2. **송신 스케일 64 dB.** srsUE ZMQ 드라이버는 `[rf] tx_gain = 50`을 수치로 곱한다
   (`rf_zmq_send_timed_multi`, 피크 313, 활성 평균 +44 dB). OCUDU gNB 하향은 −19.8 dB.
   gNB 수신은 UE 송신만, UE 수신은 gNB 송신만 보므로 평소엔 드러나지 않고, 송신기 종류를
   한 수신기에서 섞는 crosstalk 엣지에서만 터진다.

## 재현 (Spark GB10, srsUE 2대, 잡음 바닥 40 dB 기준)

| 런 | 기하 | 링크 | crosstalk 탭 | 피해 UE rx 활성 전력 | 결과 |
|---|---|---|---|---|---|
| 단일 셀 `ocudu-multi-ue/20261001T065827Z` | 링 씬, UE 간 4 m | 4 | — | −21 dB | 유지 |
| 단일 셀 `…/20261001T070229Z` | 〃 | 6 | +18 dB | **+62 dB** | 둘 다 tti 3054에 SR 실패 → release, PRACH 7회 무응답. 게이트는 `passed` |
| 2셀 `ocudu-multi-gnb/20261001T084057Z` (A3) | 거리 캐니언, 10 m 사이트, 셀 간 150 m | 8 | — | −16 dB | 유지, 각자 셀, ping 0 % 손실 |
| 2셀 `…/20261001T084550Z` (B3) | 〃 | 10 | −19 dB | **+17 dB** | 유지(상대 UE 송신 duty 0.8 %, ping만). 가짜 간섭이 33 dB 위에 있어도 안 깨진 경우 |

A3/B3를 만드는 과정에서 2-gNB 게이트의 별개 결함 둘을 고쳤다: 4-UE 커밋 이후 렌더러가
항상 실패(`validate_subscriber` 시그니처), 두 셀이 같은 PRACH 루트라 lock-step 동시 PRACH를
양쪽 gNB가 검출해 유령 UE가 생김(A2 `…/20261001T083425Z`, gnb0에 rnti 0x4602 PUSCH crc=KO).

## 수정 (X0–X2)

| # | 내용 | 파일 | 상태 |
|---|---|---|---|
| X0 | 게이트 판정 엄격화: SR 실패 0, attach 후 PRACH 재시도 0, RLF 0, ping 전부 응답. `OCUDU_NATIVE_ATTACH_STRICT` (기본 1) | `run-ocudu-multi-ue-inner.sh`, `run-ocudu-multi-gnb-inner.sh` | 구현, 합성 로그 테스트 통과 |
| X1 | 장치별 `tx_scale_db`(브로커 `type: gain` 스텝으로 선행 tdl 뒤에 접혀 profile_swap에도 남음; 링크 키는 선언 모델명 `declared_model` 유지). Sionna 렌더러가 UE 포트에 `ue_tx_scale_db = (23−30) − 10log10(3e4/1.12e-2) ≈ −71.3 dB`를 쓰고 gNB 잡음 바닥을 스케일 후 UL로 잡음. 노브 `OCUDU_NATIVE_SIONNA_UL_POWER_OFFSET_DB`. srsUE `tx_gain`으로는 불가(음수 = 자동, 실측 40 dB 적용; 하한 0) | `config.{h,cpp}`, 백엔드, `render-sionna-multi-ue-configs.py`, `run-ocudu-multi-ue.sh`, `topology.sionna-2gnb-2ue.cuda.yaml` | 구현, ctest 12/12 |
| X2 | 포트 반송파 라벨 `tx_carrier`/`rx_carrier`(TDD 단축 `carrier`), 라벨이 다른 포트를 잇는 엣지는 시작 전에 거부(라디오 노드는 lane 단위). FDD 예제에서 UE↔UE 엣지 제거, 렌더러·예제에 라벨, 브리지 기본 `CROSSTALK_LINKS=()`, `check_feed` 기본 8링크, `robot-ring-crosstalk.json` 삭제. `graph.yaml`은 `carrier: shared`(단일 반송파 예제)로 유지 | 위 파일들 + tests | 구현, ctest 12/12, 파이썬 테스트 통과 |

## 검증 (Spark GB10, 트리 `/workspace/gpuch/xtree` = integration-0928 `442513f` + 이 변경, 빌드 `gpuch-xt-release`, strict 판정)

| 런 | 게이트 | 결과 | 비고 |
|---|---|---|---|
| V1 `ocudu-multi-ue/20261001T094515Z` | Sionna multi-UE, robot-ring-walk 4링크, 잡음 40 dB | **pass**, 두 UE clean, ping 3/3, starvation 37 | UE 포트 `tx_scale_db −71.279`. gNB rx 활성 −28.9 dB(이전 +48.9), gNB 잡음 바닥 −66.5 dB(= 2.2e-7). UE 쪽은 변화 없음(−21.4 dB) |
| V2 `ocudu-multi-ue/20261001T094830Z` | 같은 게이트 + UE↔UE 링크 시나리오 | **시작 전 거부** | 브로커 `event=fatal … link ue0->ue1 (port ue0_p0->ue1_p0) connects tx carrier "n3-ul" to rx carrier "n3-dl"`. 어제처럼 조용히 돌지 않음 |
| V3 `ocudu-multi-gnb/20261001T094844Z` | 2-gNB Sionna, 저사이트 8링크, 예제 토폴로지 기본값 | **pass**, 각자 셀, clean, starvation 2 | gNB rx 활성 −22.2 dB, 바닥 −66.5 dB |
| V4a `ocudu-multi-ue/20261001T095340Z` | legacy multi-UE(고정 TDL) | **pass**, clean | 라벨만 추가된 토폴로지 회귀 |
| V4b `ocudu-multi-gnb/20261001T095655Z` | legacy 2-gNB(고정 TDL) | **pass**, clean | PRACH 루트 분리 적용 |
| V5 `ocudu-multi-ue/20261001T100228Z` | V1 재실행, outer 게이트 수정 후 | **pass**, `result=pass` 출력, exit 0 | |
| ctest (워크스테이션 5090, CUDA 13.0) | 12/12 | tx_scale CPU=CUDA 1e-3 이내, profile_swap 후에도 −20 dB 유지, carrier 거부 테스트 포함 |
| 파이썬 unittest / 렌더러 self-test | 37 + self-test pass | |
| 예제 토폴로지 26개 | 새 브로커가 전부 파싱 | `carrier`/`tx_carrier` 키 포함 |

덤으로 고친 것: Sionna 모드 멀티-UE 게이트가 통과해도 결과 줄 없이 exit 143으로 끝나던 버그
(`set -e` 아래 `[[ -n web_pid ]] && wait`의 마지막 명령은 면제가 아님). 브로커가 토폴로지를
거부하면 게이트가 `event=fatal` 줄을 그대로 보여준다.

## 남은 것 (X3–X5)

UE↔UE가 물리적으로 존재하는 배치(TDD, 셀 간 패턴 상이 = CLI)에서의 검증. srsUE는 15 kHz
FDD만 버티므로 OAI nrUE(n78 TDD) 멀티-UE 게이트가 먼저 필요하다. OAI UE의 wire 레벨도
같은 방식으로 재서 `tx_scale_db`로 맞춰야 한다.
