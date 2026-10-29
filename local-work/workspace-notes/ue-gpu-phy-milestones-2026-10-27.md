# UE PHY GPU 오프로드 마일스톤 (초안 2026-10-27)

미션: 브로커(CUDA 채널)·CUDA gNB와 같은 GB10 위에서 **UE 수신 PHY를 GPU에서 처리**하고, 그것이 실제로 실시간 비율을 올리는 스케일을 측정으로 확정한다. `CUDA_MILESTONES.md`(gNB 쪽)와 같은 규칙으로 진행한다.

## 사전 분석이 고정한 결정 (2026-10-27)

| 결정 | 근거 |
|---|---|
| **1차 대상은 OAI nrUE, srsUE는 보조 트랙** | srsUE는 20 MHz·1 RX·1 layer 고정(PRACH 2048 FFT 제한)이라 GPU가 이기는 영역에 못 간다. OAI nrUE는 100 MHz·4 RX·2 layer까지 되고 LDPC가 플러그인(`libldpc<ver>.so`, `--loader.ldpc.shlibversion`)이라 **OAI 트리 무수정**으로 백엔드를 바꿀 수 있다 |
| **디코더는 OCUDU `lib/phy/cuda` 재사용** | 독립 static lib(`ocudu_phy_cuda`, C API, cudart만 필수). `ldpc_decoder_decode_batch_half*`, device CRC, rate-matched fp16 입력 경로가 이미 있다. 새 커널을 쓰지 않는다 |
| **단계 순서: 플러그인(LDPC만) → 수신 체인 전체 → 다중 UE 배치 서비스** | 각 단계 끝에 "다음 단계로 갈 가치가 있는가"를 측정 표로 판정한다 |
| **20 MHz 1-layer에서는 GPU가 진다고 선언하고 시작** | WG 자체 수치 PDSCH 29 vs 80 µs, PUSCH 226 vs 262 µs; 우리 호출 플로어 40–60 µs; srsUE NEON 이후 SCH 190 µs/TB. 이 구성의 무회귀가 게이트이고 속도 주장은 U3 이후에만 한다 |
| **GPU 클라이언트가 2개 이상이면 MPS는 전제조건** | CUDA gNB를 MPS 없이 붙이면 8 UE 0.91→0.71, 브로커 5컨텍스트에서 호출 70→544 µs(측정) |

## 절대 제약 (CUDA_MILESTONES와 동일)

1. **기존 파일 무수정.** OAI·OCUDU·ehs0 트리의 기존 파일은 바이트 동일. 신규 기능은 새 파일(플러그인 .so, 새 러너, 새 lock)로만. 부득이한 벤더 수정은 단일 패치 + sha256 lock + 제보.
2. **CPU가 기본값.** 환경변수 없이 돌리면 기존 게이트는 그대로 CPU 경로.
3. **백엔드 선택을 런타임 로그로 증명.** 조용한 CPU 폴백은 실패로 친다.
4. **수정·주장마다 음성 대조군**(exit≠0 또는 지표 이탈)을 둔다.
5. **"live"의 정의**는 실제 OCUDU gNB + 실제 UE가 브로커에 ZMQ로 붙은 것. 합성 라디오 수치는 boundary로 쓰지 않는다.

## 단계

| 단계 | 내용 | Exit 게이트 | 예상 |
|---|---|---|---|
| **U0** | **기준선·예산 (코드 없음)** | 단계별 CPU 비용 표 + GPU 디코더 배치별 지연 표 + 교차점 | 2일 |
| **U1** | **OAI LDPC 플러그인 `libldpc_cuda.so`** (LDPC만 GPU, OAI 무수정) | 오프라인 BLER 동일, 음성 대조군 fail, 플러그인 로드 로그 | 3–4일 |
| **U2** | **라이브 무회귀** 1x1 20/50/100 MHz, CPU gNB·CUDA gNB 양쪽, MPS 한 서버 | attach/PDU/ping 3/3, rt 20 MHz ±0.01, BLER ≤+1 %p, late slot 0 | 2일 |
| **U3** | **이득이 나는 행 측정** 2x2 50/100 MHz 로드, 4 RX, OAI 4 UE 50/100 | 표. ≥+0.05 rt 행이 있을 때만 속도 주장. **없으면 여기서 종료** | 2–3일 |
| **U4** | **수신 체인 전체 GPU** (채널추정→등화→LLR→dematch→LDPC, 단일 그래프) | 같은 IQ에서 LLR/CRC 패리티, 100 MHz 2x2 rt 표 | 2–3주 |
| **U5** | **다중 UE 배치 서비스** (단일 CUDA 컨텍스트, 공유메모리 클라이언트) | 컨텍스트 1개 증명, 브로커 호출 p99 무변화, 4/8/16 UE 표 | 2주 |
| **U6** | **srsUE 보조 트랙** `SRSRAN_LDPC_DECODER=cuda` (같은 shim) | 20 MHz 4/8/16 UE NEON 대비 표. 무이득이면 그대로 기록 | 2일 |
| **U7** | **보고·업스트림** ehs0 docs/reports 패턴, Claude Doc, WG1 노트 | PR + 패치 격리 + 재현 절차 | 2일 |

U3가 분기점이다. U3에서 이득 행이 없으면 U4·U5는 "GPU 상주 RAN PHY" 논문 스토리용으로만 가치가 있고, 그 결정은 사용자가 한다.

## 단계별 상세

### U0 — 기준선·예산

**목적:** 무엇을 GPU로 보낼지, 어느 배치 크기부터 이기는지 숫자로 고정한다.

1. **OAI nrUE 단계별 CPU 비용.** 1x1 20/50/100 MHz, 2x2 50/100 MHz 200 Mb/s에서 OAI 자체 `time_stats`(`ts_deinterleave`, `ts_rate_unmatch`, `ts_ldpc_decode`, PDSCH 채널추정/등화 측정치)와 `perf record`로 슬롯당 µs를 뽑는다. 기존 측정(100 MHz 2x2: LDPC 25 %, DL 액터 36 %, 1.55코어)을 단계 단위로 쪼갠다.
2. **srsUE는 완료.** 2026-10-27 슬롯 트레이스: FFT 32 / CSI 42 / PDCCH 37 µs 매 슬롯, PDSCH 250 µs(CHEST 27, EQ 39, DEMOD 5, SCH 187; LDPC 28 µs/CB), PUSCH 인코드 100–200 µs, little core는 2배. 스크립트 Spark `/tmp/stagestat.py`.
3. **GPU 디코더 마이크로벤치.** `ocudu_phy_cuda`를 독립 CMake 프로젝트로 sm_121 빌드(`lib/phy/cuda/CMakeLists.txt`는 단독 빌드를 지원한다). BG1/BG2 × Z(384, 208, 112) × 배치(1, 2, 4, 8, 16, 32, 64 CB) × 반복(5, 10)에서 **호스트 호출 왕복**(H2D 포함, unified memory 두 가지: managed vs pinned staging) p50/p99를 잰다. 브로커 커널과 같이 돌 때(MPS 안/밖)도 1점 잰다.
4. **교차점 산출.** CPU 경로(OAI segment 디코더 = NEON through SIMDe, srsUE NEON 28 µs/CB)와 GPU 왕복을 겹쳐 "배치 N CB 이상이면 GPU" 표를 만든다. 100 MHz 2x2 한 슬롯의 CB 수(≈ 2 TB × 20 CB)가 그 위에 있는지 확인하는 것이 핵심.

**Exit:** 두 표와 교차점. 100 MHz 2x2 슬롯이 교차점 아래면 U1을 건너뛰고 U4(체인 전체)로 바로 갈지 결정.

### U1 — OAI LDPC 플러그인

**구현 (신규 파일만, 작업 트리 `~/ocudu-work/ue-gpu-phy/`):**

- `plugin/nrLDPC_coding_cuda.c`: OAI 인터페이스 4개 진입점 `nrLDPC_coding_init(max_num_pxsch)` / `shutdown` / `decoder(nrLDPC_slot_decoding_parameters_t*)` / `encoder`. 디코더는 슬롯의 모든 TB·세그먼트를 한 배치로 모은다(인터페이스가 이미 슬롯 단위라 코드 변경 없이 배치가 된다). 인코더는 1차로 OAI segment 인코더에 위임(호출 전달), 2차로 `ldpc_encoder_cuda_batch`.
- 데이터 경로: OAI `llr`은 int16 host 배열 → pinned staging에 복사 → int16→fp16 변환 커널 → `ldpc_decoder_decode_batch_half_from_rate_matched`(BG1/Z384 한정) 또는 CPU rate-dematch(OAI `nr_rate_matching.c` 재사용) + `decode_batch_half`. CRC는 device 결과(`ldpc_decoder_get_crc_results_host`)로 `decodeSuccess[r]` 채움. HARQ 결합(`d`, `d_to_be_cleared`)은 1차 CPU 유지, 2차 device 상주.
- 빌드: `libldpc_cuda.so` MODULE, `ocudu_phy_cuda` static 링크, OAI 헤더만 include(트리 무수정). 로드: `--loader.ldpc.shlibversion _cuda`. init 로그에 `backend=cuda device=GB10 sm_121 batch_max=…` 출력(제약 3).
- 벤더 패치가 필요해지면(예: `from_rate_matched`의 Z 제한 완화) `patches/ocudu-cuda-ldpc-*.patch` + sha256 lock.

**검증 (오프라인):** OAI `nr_dlsim`(또는 `ldpctest`)로 같은 SNR 격자에서 CPU 플러그인 대 CUDA 플러그인 BLER 비교, MCS 4/16/27, 20/100 MHz. 허용: BLER 곡선 0.1 dB 이내. 음성 대조군: LLR 부호 반전 → CRC 전부 실패(exit≠0로 판정하는 스크립트).

**Exit:** BLER 표, 음성 대조군, 로드 로그, `git diff --stat` 빈 출력(OAI·OCUDU 트리).

### U2 — 라이브 무회귀

- 러너: 기존 `run1x1.sh`/`run-ocudu-oai-1x1.sh`는 무수정. 새 래퍼 `scripts/run-oai-1x1-cuda-ue.sh`가 `OAIUE_LDPC_BACKEND=cuda`일 때만 shlibversion과 `LD_LIBRARY_PATH=/usr/local/cuda/lib64`를 주입한다(NVRTC 함정 재발 방지).
- 격자: 20/50/100 MHz 1x1 × {CPU gNB, D10 CUDA gNB} × {CPU UE, CUDA UE}. 모든 CUDA 런은 `with-cuda-mps.py` 한 서버에 브로커·gNB·UE를 넣는다(브로커 바깥은 무의미, 10-26 교훈).
- 기록: rt(브로커 heartbeat 중앙값), UE CPU %, BLER, late/dropped, 브로커 `cpu_stage_timings`의 process p99(UE가 GPU를 같이 쓸 때 브로커 호출이 느려지는지가 **이 단계의 진짜 질문**).

**Exit:** attach/PDU/ping 3/3 전 조합, 20 MHz rt ±0.01, 브로커 process p99 증가 ≤ 50 µs, BLER ≤ +1 %p. 속도 주장 없음.

### U3 — 이득이 나는 행

이미 CPU로 측정된 느린 행만 다시 잰다.

| 행 | CPU UE 현재 | 기대 |
|---|---|---|
| 2x2 200 Mb/s 50 MHz | 0.37–0.38 | LDPC 25 % 제거 → +0.05–0.1 |
| 2x2 200 Mb/s 100 MHz | 0.28–0.29 | 같음. DL 액터가 남아 1.0 불가 |
| 4 RX 100 MHz (4x4, 2x4) | 0.33–0.44 | 소폭 |
| OAI 4 UE 50/100 MHz | 0.79 / 0.50 | 4 컨텍스트 + MPS. **악화 가능** |

**Exit:** 표. ≥ +0.05인 행이 하나라도 있으면 U4 진행 권고, 없으면 U7(기록)로 종료 권고. 4 UE 행이 악화되면 U5의 필요성 증거로 기록.

### U4 — 수신 체인 전체 GPU

여기서부터 OAI 트리 수정이 불가피하다(채널추정·등화는 `phy_procedures_nr_ue.c`의 DL 액터 안에 있다). 단일 패치 + lock.

- 설계: OAI DL 액터가 슬롯 IQ(또는 FFT 후 RE)를 managed 버퍼에 두고 한 번의 CUDA 그래프로 DMRS 채널추정 → MMSE 등화 → 복조 LLR → descramble → dematch → LDPC → CRC를 돌린다. 커널은 OCUDU 상주 PUSCH 파이프라인(`pusch_processor` CUDA, `pusch_resident_dematch_scramble`)을 PDSCH 파라미터로 재구성한다. transform precoding은 없고 DMRS 타입·스크램블 시드만 다르다.
- 패리티: 같은 IQ를 CPU 경로와 GPU 경로에 넣어 LLR 상관·CRC 일치(기존 `pusch_gpu_cpu_comparison_test` 방식; 16QAM·CFO≠0 포함, 이슈 6의 교훈).
- 측정: U3 격자 재실행 + 100 MHz 2x2에서 UE 코어 2→5 비교(지금은 0.24→0.35).

**Exit:** 패리티 표, rt 표, 패치 lock, 음성 대조군.

### U5 — 다중 UE 배치 서비스

UE 수 축을 노릴 때만. 전제: gNB 비-PHY 턴어라운드(16 UE 1.05–1.10 ms)와 브로커 ZMQ 전송(16–24 UE)이 먼저 풀려 있어야 의미가 있다.

- 구조: `ue-phy-server`(단일 CUDA 컨텍스트, 브로커와 같은 자리 배치) + 플러그인은 공유메모리 링 클라이언트. 배치 창 ≤ 100 µs(UE들이 lock-step으로 거의 같은 시각에 요청하므로 창이 작아도 모인다; 측정으로 확인).
- srsUE도 같은 클라이언트(U6)로 붙일 수 있다.

**Exit:** `nvidia-smi`/MPS 로그로 컨텍스트 1개, 브로커 호출 p99 무변화, 20 MHz 4/8/16 UE와 50/100 MHz 4 UE 표.

### U6 — srsUE 보조 트랙

NEON 패치와 같은 자리(`sch_nr.c` 디코더 선택, env `SRSRAN_LDPC_DECODER=cuda`)에 같은 shim을 꽂는다. 기대치는 "20 MHz에서 NEON에 진다"이며, 16 UE little core 행에서만 확인 가치가 있다. 결과가 무이득이면 그대로 기록하고 닫는다.

### U7 — 보고

ehs0 `docs/reports/performance/<date>-gb10-ue-gpu-phy/` 패턴(README + CSV + tools + patches), 보고 순서는 [[feedback-local-patches-report-last]]대로 맨 끝. 상위 제안서 `spark-scaling-proposal-2026-10-22.md` §8의 "UE 쪽 GPU 경로" 항목을 결과로 갱신.

## 알려진 함정 (이 작업에 바로 적용)

- 비로그인 셸은 `LD_LIBRARY_PATH=/usr/local/cuda/lib64`가 없다(NVRTC). LDPC만 쓰면 cudart로 충분하지만 U4의 VkFFT 경로부터 필요.
- 첫 슬롯 커널 JIT → 첫 세션 첫 테스트 타임아웃. 플러그인 init에서 워밍업 디코드 1회.
- 컨테이너 파일 캐시 ~100 GB 후 CUDA 컨텍스트 생성 실패(`kgrctxAllocCtxBuffers`). 48 GB 익명 할당으로 회수.
- 합성 라디오·UE는 X925 코어에. A725는 100 MHz 배치를 못 받는다.
- `pkill -f` 패턴이 docker exec 명령줄에 있으면 자기 셸을 죽인다.
- 세션 중 플러그인 재빌드 금지. 타임아웃된 세션의 cleanup이 다음 세션을 죽인다(마커 프로세스 소멸 대기).
- 외부 GPU 테넌트(다른 컨테이너)가 돌면 그 phase는 무효. 런마다 `nvidia-smi --query-compute-apps` 기록.

## 변형 B — srsUE 우선 (2026-10-27 사용자 질문 "srsUE로 하면 안 되나")

**가능하고, 시작은 더 쉽다.** 패치·lock(`integrations/srsran/patches/srsue-ldpc-neon.patch` 방식)·ranb 러너·16 UE 오케스트레이션이 있고, 수신 체인이 `srsran_ue_dl_nr_decode_pdsch`(`lib/src/phy/ue/ue_dl_nr.c`) 한 함수로 떨어진다. 단점은 하나: srsUE는 20 MHz·1 RX·1 layer라 GPU가 이기는 영역에 못 간다. 따라서 **S4(대역폭 제한 해제)가 플랜의 분기점**이다.

| 단계 | 내용 | Exit 게이트 | 예상 |
|---|---|---|---|
| **S4 스파이크 (먼저)** — **완료 10-27, 풀림** (`ue-gpu-phy/S4-NOTES.md`: 원인 = slot_sync 30720-샘플 고정 버퍼 heap overflow + PUCCH PRB 상한 156; 50 MHz 1 UE rt 0.91–0.93, 20 MHz 4 UE 0.994 무회귀) | 20 MHz 캡 해제 타당성. 10-27 시도(`share/srsue-prb270-attempt-2026-10-27.patch`)는 PRACH 송수신까지 되고 `srsran_ue_dl_nr_set_carrier → ofdm_init_mbsfn_` ERROR 경로에서 죽음. PHY 로거 segfault(`phy_nr_sa::srsran_phy_logger`, PHY_CMD 스레드)가 진짜 메시지를 가림 | 로거 우회 후 진짜 에러 특정, 4096 FFT 정적 버퍼 목록, "풀린다/안 풀린다" 판정. 상한 2–3일 | 2–3일 |
| **S0** — **완료 10-27** (`S4-NOTES.md` S0 절: fp16 boxplus+CRC ET 경로 1 CB 124 µs, 16 CB 141 µs, managed 123 µs 평탄; 교차점 CB 3~4개) | GPU 디코더 마이크로벤치 | 교차점 표 | 1일 |
| **S1** — **구현·측정 완료 10-27** (`S4-NOTES.md` S1 절): `ldpc_dec_cuda.{h,cpp}` + `sch_nr.c` 배치 경로, 핸들 캐시, 동기 모드 spin/block/yield; 패리티 테스트 GPU 감도 ≥ NEON; 라이브 50 MHz 1 UE: TB당 +60 µs, 1코어 block 동기 rt 0.88→0.94, 3코어 −0.01; 20 MHz 4 UE 동일; srsUE는 DCI 1_0 때문에 TB ≤ 96 PRB(C ≤ 9)라 TB당 GPU 우세 영역 도달 불가 | `SRSRAN_LDPC_DECODER=cuda` 배치 백엔드 | BG1/BG2 전 lifting size 통과, 라이브 표 | 3일 |
| **S2** | PDSCH 체인 전체: `srsran_ue_dl_nr_decode_pdsch`를 managed `sf_symbols` 입력의 단일 CUDA 그래프(DMRS 추정→등화→복조→dematch→LDPC→CRC)로 교체, env 스위치. FFT(`srsran_ofdm_rx_sf`→cuFFT)는 선택 | 같은 IQ에서 CPU/GPU LLR·CRC 패리티, 라이브 무회귀 | 2주 |
| **S3** | 다중 srsUE 배치 서비스(U5와 동일 구조). srsUE 프로세스는 공유메모리 클라이언트 | 컨텍스트 1개, 브로커 호출 p99 무변화, 20 MHz 8/16 UE 표(16 UE little core 행이 유일한 기대 이득, gNB 한계로 상한 ≈0.5) | 2주 |
| **S5** | 보고(U7과 동일) | | 2일 |

**10-27 결과 요약:** S4 풀림, S0/S1 완료. S1 라이브: TB당 GPU +60–130 µs, rt는 1코어 50 MHz에서만 +0.05, 8 UE에서 −0.06 (`ue-gpu-phy/S4-NOTES.md` S1 판정). srsUE의 DCI 1_0 제한(TB ≤ 96 PRB)으로 TB당 GPU 우세 영역 도달 불가 → **S2/S3 진행 여부는 사용자 결정**(S2는 코어 부족 구성 전용, S3는 현 8/16 UE 상한이 gNB라 rt 이득 없음; 전대역 TB는 변형 A(OAI nrUE)로).

**판정 규칙:** S4가 풀리면 S0→S1→S2를 50/100 MHz 다중 UE에서 측정한다(이 경우 srsUE가 OAI보다 나은 선택이다). S4가 안 풀리면 S0→S1까지 하고 숫자를 기록한 뒤 OAI(변형 A)로 갈지 결정한다. S3는 어느 쪽이든 gNB 비-PHY·브로커 전송 한계가 먼저 풀려야 의미가 있다.
