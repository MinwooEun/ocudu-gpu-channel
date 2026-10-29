# S4 스파이크 노트 — srsUE 20 MHz 캡 해제 (2026-10-27)

작업 트리: 워크스테이션 `~/ocudu-work/ue-gpu-phy/srsRAN_4G-s4` (eea87b1 + 패치), Spark `/workspace/gpuch/s4/srsRAN_4G-s4` (lock 트리 = NEON 포함 복사본 + 같은 패치), 빌드 `build-s4` (-g), `build-s4-asan` (ASan). 패치: `patches/srsue-prb270-s4-2026-10-27.patch` (10-27 시도 + 진단/수정 3건).

## 확인된 것

1. **오프라인 초기화는 전부 통과.** 독립 프로브(`scratchpad/s4/carrier270_test.c`, 워크스테이션 x86 빌드에 링크)로 `ue_dl_nr`/`ue_ul_nr` init+set_carrier(270 PRB), PRACH init/set_cfg(4096), SSB, `ue_sync_nr` 모두 OK. 전제: UE conf의 `max_nof_prb = 270`(ranb BW 패치가 이미 넣음) + 10-27 패치(symbol_sz 4096, PRACH 4097 캡, carrier_to_cell 270).
2. **stock 라이브러리에서 `srsran_ue_dl_nr_set_carrier`는 OFDM 재계획 실패를 무시하고 0을 반환**(ue_dl_nr.c의 `srsran_ofdm_rx_init_cfg` 반환값 미검사). max_nof_prb=106인 채 270 PRB를 넣으면 FFT가 2048에 머문 채 진행된다. S4 패치에서 반환값 검사 추가.
3. **라이브 크래시의 실제 위치(-g 빌드, 세션 g131):**
   - 1차: `srsue::nr::worker_pool::set_config` → `std::lock_guard(cfg_mutex)` → `std::mutex::lock()`이 EINVAL → `std::system_error: Invalid argument` → abort. (phy_nr_sa.cc:271 cmd_worker 람다에서 호출)
   - 2차: sync 스레드 `run_sfn_sync → srsran_ssb_find → ssb_decode_pbch → srsran_pbch_nr_decode(pbch_nr.c:680) → srsran_phy_log_print → phy_nr_sa::srsran_phy_logger(phy_nr_sa.cc:41)`에서 segfault.
   - 둘 다 `phy_nr_sa` 객체(안의 worker_pool 뮤텍스, 로거 참조)가 셀 탐색 중 덮어써진 증상. PHY-lib ERROR는 크래시 전에 하나도 없음(stderr 에코 패치로 확인).
4. **고정 크기 버퍼 후보(61.44 MHz 슬롯 61440 샘플 > 30720):** `lib/src/radio/radio.cc` `zeros`(SRSRAN_SF_LEN_MAX, 미할당 채널 TX에 사용 → S4 패치에서 4배로), `srsue/src/phy/prach.cc` `signal_buffer`(3×30720 → 서브프레임 길이 기반으로 수정), `rf_buffer_t(nof_subframes)` 자체 할당 생성자(SA 경로에서는 LTE phy_common의 `zeros_multi(1)`만 사용). 이 셋을 고쳐도 g131 크래시는 그대로 → 원인은 다른 곳. ASan 빌드로 추적 중.

## 러너 변경 (Spark `/workspace/gpuch/ranb`, root 소유, docker exec로 편집)
- `run-single-cell-policy-inner.sh`: `SINGLE_CELL_UE_BINARY` 노브 추가(기본값 = lock 빌드). 실행 스크립트 `/workspace/gpuch/s4/run-b50.sh <tag> [ENV=VAL]` (1 UE, 50 MHz, 20 s, root로 `docker exec -d ocudu-minwoo`).

## 세션
- g131 `tagged-b50-s4-1ue-20261027T114947Z-g131`: S4 -g 빌드, 크래시 재현(위 3).

# S0 결과 — OCUDU CUDA LDPC 디코더 호스트 왕복 지연 (2026-10-27, GB10 idle, X925 코어 17)

벤치: `scratchpad/s0/ldpc_gpu_bench.cu` (Spark `/workspace/gpuch/s4/ldpc_gpu_bench`), d10 빌드의 `libocudu_phy_cuda.a`에 직접 링크. 생산 경로(`pusch_codeblock_decoder_cuda_batch.cpp`)와 같은 설정: fp16 입력, boxplus, NMS 0.8/0.1, CRC24B 조기 종료(confidence 0.15), clamp 127. CB마다 CRC24B를 붙인 난수 payload, GPU 인코더로 부호화, BPSK-류 LLR(진폭 16) + AWGN. 한 호출 = H2D LLR + decode_batch_half + D2H 출력 + 동기. 데이터: `data/bench-matrix-20261027T1205Z.txt`.
주의: 디코더의 워드 비트 배치는 바이트 단위 MSB-first(`cuda_bit_pos`)라 평범한 비트 인덱스로 넣으면 50% 오류(벤더의 옛 `test_decoder_direct.cu`도 같은 이유로 실패). 조기 종료는 CRC 기반이라 CRC 없는 난수 CB로는 항상 최대 반복을 돈다. 표의 `crc_ok` 열은 0=통과(반전 표기).

| BG1 Z384 (K 8448) | 1 CB | 4 CB | 8 CB | 16 CB | 64 CB |
|---|---|---|---|---|---|
| 2회 반복 (σ 0.5), pinned, 호출 p50 | 124 µs | 134 | 138 | 141 | 291 |
| 2회 반복, **managed(zero-copy)** | 123 | 123 | 123 | 123 | 221 |
| 3회 반복 (σ 0.8), pinned | 183 | 187 | 196 | 252 | 430 |
| 6회 반복 (σ 1.0), pinned | 355 | 358 | 368 | 424 | 782 |
| fp32 `decode_batch` (4회) | 653 | 1180 | 1182 | 1196 | 1463 |
| BG2 Z384 (2회) | 200 | 208 | 212 | 221 | 276 |
| BG1 Z208 (2회) | 122 | 123 | 123 | 135 | 181 |

읽기: 커널 ≈ 57 µs × 반복 횟수(BG1 Z384), 호출 오버헤드 ≈ 10 µs, **16 CB까지 배치가 거의 공짜**. fp32 경로는 5배 느리므로 쓰지 않는다.

**교차점 (CPU = srsUE NEON, CB당 RM 24 + LDPC 28 ≈ 52 µs at 1–2 반복):** 2회 반복에서 GPU 호출 124 µs ≥ CPU 3 CB(156 µs) → **CB 3개부터 동률, 4개부터 GPU 우세**; 3회 반복이면 4~5개. 20 MHz 96 PRB TB(2.6 CB) = 동률(예상대로 이득 없음). 50 MHz 1-layer TB(≈7 CB) 1.8배, 100 MHz(≈20 CB) 5배, 16 UE 배치(16~48 CB) 5~10배. 단, 이 수치는 GPU가 비어 있을 때이며 브로커·gNB 컨텍스트와 공유하면 호출 지연이 커진다(브로커 측정: 4 클라이언트에서 70→190 µs).

## ASan 결과 (세션 g134, 2026-10-27 12:08) — 원인 확정
`srsue/src/phy/nr/slot_sync.cc:27` 생성자 `sfn_sync_buff(1)`: `rf_buffer_t(n)`은 n × SRSRAN_SF_LEN_MAX(30720) 샘플을 할당한다. SFN 동기 수신(`slot_sync::run_sfn_sync → srsran_ue_sync_nr_zerocopy → recv_callback → radio::rx_now → rf_zmq_rx_baseband → ringbuffer memcpy`)이 61.44 MHz 슬롯 61440 샘플(491520 B)을 245760 B 버퍼에 써서 heap-buffer-overflow. 이것이 `worker_pool` 뮤텍스와 `phy_nr_sa` 로거 참조를 덮어 EINVAL/segfault로 나타난 것. 수정: `sfn_sync_buff(4)` (122880 샘플, 122.88 MHz까지). ASan 실행 요령: 러너가 `stdbuf`(LD_PRELOAD)로 띄우므로 `ASAN_OPTIONS=verify_asan_link_order=0`, `log_path`는 쓰지 말 것(EACCES로 죽음) — stderr가 srsue 로그로 간다.

## 수정 후 라이브 (세션 g135, ASan 빌드, 12:14): **attach 성공, 세션 PASS**
PRACH(occasion 0, preamble 0) → RA Complete(c-rnti 0x4601) → RRC Connected → PDU 세션(10.45.1.2); 벤치 게이트 RUN VALID, STRICT FAIR COMPARISON PASS. rt 0.238/0.245 (ASan 오버헤드, 참고용). 남은 결함: `[PHYLIB ERROR] Invalid PUCCH format 1 resource` 반복 → `lib/src/phy/phch/pucch_cfg_nr.c:168,178`이 `SRSRAN_MAX_NRE_NR`(=156, PRB당 RE 수 상수를 오용)로 `starting_prb/second_hop_prb > 155`를 거부. 270 PRB BWP의 공통 PUCCH 두 번째 hop(≈PRB 269)과 상단 대역 끝의 전용 리소스가 전부 거부돼 PUCCH(HARQ-ACK/SR)를 못 보냄(dl_brate 0 관찰). stock srsRAN 4G의 >156 PRB 버그. 수정: `SRSRAN_MAX_PRB_NR - 1`로 비교.

## S4 판정 (2026-10-27 12:29): **풀린다.** srsUE 50 MHz(270 PRB, 15 kHz, 61.44 MS/s) 라이브 동작
| 세션 | 구성 | rt | UE 상태 |
|---|---|---|---|
| g137 `tagged-b50-s4-1ue3-…` | 50 MHz 1 UE, S4 -g 빌드(PUCCH 수정 포함), CPU gNB | **0.909 / 0.934** | PUCCH/PHY-lib 오류 0, DL 19.8 Mb/s(MCS 14.2, SNR 19.5 dB, BLER 1.1 %), UL 2.15 Mb/s, PASS |
| g136 `…-1ue2-…` | 같은 빌드, PUCCH 수정 전 | 0.885 / 0.917 | PUCCH 오류 203회, DL 25 Mb/s(MCS 15–16) |
| g138 `tagged-b20-s4-4ue-…` | **20 MHz 4 UE 무회귀**, S4 빌드 | **0.9945 / 0.9934** | 오류 0, 4 UE 전부 attach, DL 5.8 Mb/s/UE (기존 NEON plain 0.993/0.995와 동일) |

패치 내용(`patches/srsue-prb270-s4-2026-10-27.patch`, 10-27 시도 포함, 10 파일): symbol_sz/nof_prb 4096·270 매핑, PRACH 4097 캡, carrier_to_cell 270, `ue_dl_nr.c` OFDM 반환값 검사, `slot_sync.cc` sfn_sync_buff(4), `radio.cc` zeros 4×, `prach.cc` signal_buffer 서브프레임 길이 기반, `pucch_cfg_nr.c` PRB 상한 SRSRAN_MAX_PRB_NR, `phy_logger.c` stderr 에코(진단). 이제 srsUE로 50 MHz 다중 UE 격자(S1~S3)를 돌릴 수 있다. 100 MHz(15 kHz 불가, 30 kHz SCS 필요)는 srsUE SA가 30 kHz를 지원하는지 별도 확인 필요.

# S1 1차 라이브 (2026-10-27 12:30–12:44, 빌드 `build-s1` = S4 + CUDA 백엔드, `SRSRAN_LDPC_DECODER=cuda`)
구현: `lib/src/phy/fec/ldpc/ldpc_dec_cuda.{h,cpp}` (OCUDU `libocudu_phy_cuda.a`, fp16 boxplus, CRC ET, managed 버퍼, TB의 모든 CB를 한 `decode_batch_half`), `sch_nr.c`에 `sch_nr_decode_cuda_cbs`(RM 전부 → GPU 배치 → `srsran_crc_match`로 CPU와 같은 CRC 판정 → 비트 패킹), CMake 옵션 `SRSRAN_LDPC_CUDA{,_ROOT,_LIB}`, `SRSRAN_SCH_TIMING=1` 디코드 구간 타이밍. 패치 `patches/srsue-s4-s1-2026-10-27.patch`.

| 세션 | 구성 | rt | SCH 구간 p50 (RM+LDPC+CRC, TB당) | ue0 DL |
|---|---|---|---|---|
| g139 | 50 MHz 1 UE, CPU(NEON) | 0.883 / 0.876 | 191–287 µs (C=3–5) | 30.8 Mb/s, MCS 20.6, BLER 4.5 % |
| g140 | 50 MHz 1 UE, CUDA, MPS 없음 | 0.825 / 0.799 | 324–331 µs (C=2–4) | 19.1 Mb/s, **MCS 13.9**, BLER 1.1 % |
| g141 | 50 MHz 1 UE, CUDA + MPS(브로커 포함) | 0.846 / 0.818 | 250–360 µs | 19.2 Mb/s, MCS 13.8 |
| g142 | 20 MHz 4 UE, CPU | 0.994 / 0.995 | 101–197 µs (C=1–3) | 5.0 Mb/s |
| g143 | 20 MHz 4 UE, CUDA + MPS | 0.994 / 0.993 | 210–300 µs | — |

읽기: (1) S0 예측대로 C≤5에서는 GPU 경로가 TB당 60–130 µs 느리고(호출 ≈125 µs + fp16 변환 + RM은 CPU 그대로) 50 MHz 1 UE rt가 0.88→0.80–0.85로 내려간다. 20 MHz 4 UE는 양쪽 0.994(UE 디코드가 병목이 아님). (2) **CUDA 런에서 DL MCS가 20.6→13.9로 떨어짐** = GPU 디코더의 복호 감도가 CPU보다 나빠 OLLA가 물러선 것. 후보: int8 LLR(±127)→fp16 그대로 넣은 스케일/오프셋(0.8/0.1는 OCUDU LLR 범위용), CRC ET confidence 0.15, filler 처리. 단위 패리티 테스트로 SNR별 cpu_ok/gpu_ok 비교 중. (3) 이 트래픽(mixed, ue0 bulk)에서 할당이 C=2–5 CB에 머물러 GPU 우세 영역(C≥6)에 못 들어간다 → 전대역 고MCS 할당이 나오는 부하가 필요.

## S1 원인 추적과 수정 (12:50)
- **재구성 스톨**: `[ldpc_cuda] configured` 13,255회/20 s(g140), 13,208회(g141), 7,291회(g143). (ls, F) 조합이 TB마다 바뀌어 `ldpc_decoder_configure`(ms 단위)를 매번 호출 → SCH max 9.6 ms → NACK → OLLA가 MCS를 내림. 수정: (bg, ls, F, crc)별 디코더 핸들 캐시(최대 64, LRU, 워크스페이스 32 CB 선할당·필요 시 152). 빌드 `build-s1` 재빌드.
- **복호 감도(단위 패리티 테스트 `ldpc_dec_cuda_test`, NEON CPU vs GPU, 16 CB, 10회 반복, CRC ET 없음, `data/ldpc-parity-2026-10-27.txt`)**: 고SNR(5 dB)에서 전 Z 비트 동일 16/16; 워터폴(BG1 Z384 3 dB) CPU 0/16 vs GPU 16/16, BG2 Z384 2 dB CPU 0/16 vs GPU 16/16 → GPU(boxplus, NMS 0.8+0.1)가 CPU(NMS 0.8)보다 감도가 좋다. 라이브 MCS 하락은 감도 문제가 아님. 테스트의 FAIL 2건은 Z=2(K 44비트)의 통계 요동.

## S1 체인 2 (핸들 캐시 빌드, 12:48–12:59)
| 세션 | 구성 | rt | 비고 |
|---|---|---|---|
| g144 | 50 MHz 1 UE(코어 17 하나), CUDA+MPS, scale 1 | 0.720 / 0.852 | **MCS 20.4, DL 31.9 Mb/s로 회복**(= CPU 수준), 재구성 270/148회(조합당 1회). SCH p50 343–383 µs(C=8), 그러나 p99 5–8 ms, max 8–25 ms 스파이크 = 새 (ls,F) 조합의 create+configure+preallocate 비용이 런 중에 흩어져 발생 |
| g145 | CPU, scale 5 | 0.543 / 0.525 | 과부하 붕괴: MCS 2.0, DL 1.4 Mb/s. UE 1코어(PHY+스택+ZMQ)가 5× 트래픽을 못 받음 |
| g146 | CUDA+MPS, scale 5 | 0.93 / 0.95 UNQUALIFIED | 트래픽 거의 없음(rows 13) — 무의미 |
| g147 | CUDA(MPS 없음), scale 5 | 0.540 / 0.527 | g145와 동일 붕괴 |

교훈: (1) 50 MHz 1 UE의 rt 한계(0.88–0.93)는 **UE 한 코어**(4096 FFT·스택·ZMQ)이고, 동기 GPU 호출은 그 코어를 비워 주지 않는다(`cudaStreamSynchronize` 기본 = 스핀) → `cudaDeviceScheduleBlockingSync`로 바꿈. (2) 핸들 생성 비용을 런타임에 내지 않으려면 선할당을 8/32/152 단계로 줄이고(수정), 조합 선예열이 필요하면 추가. (3) 고부하 테스트는 UE에 3코어(17-19)를 주고 scale 2–3으로.

## S1 체인 3 (블로킹 동기 + 선할당 8/32/152 빌드, 13:00–13:12)
| 세션 | 구성 | rt | ue0 DL | SCH p50 / p99 |
|---|---|---|---|---|
| g148 | 1코어, CUDA+MPS, scale 1, **blocking sync** | **0.939 / 0.936** (CPU g139 0.883/0.876) | MCS 13.7, 19.0 Mb/s | 300–385 / ~1000 µs (C=2–4) |
| g149 | 3코어(17-19), CPU, scale 2 | 0.993 / **0.540**(test2 붕괴) | MCS 20.1, 31.9 Mb/s | 290 / 500 (C=4–5) |
| g150 | 3코어, CUDA+MPS, scale 2 | 0.963 / 0.994 | MCS 6.7, 8.7 Mb/s | 220–320 / 360–1300 (C=1) |
| g151/g152 | 3코어, scale 3, CPU / CUDA | 0.84/0.94, 0.64/0.88 UNQUALIFIED | MCS 5 / 2 | — |
create+configure = 99 µs, preallocate(8) ≈ 1 ms per new handle (런당 135–195개).
읽기: (1) blocking sync는 UE 코어를 비워 **rt +0.05**(0.88→0.94)를 주지만 인터럽트 깨우기 지연으로 디코드 p99 ≈ 1 ms → HARQ 기한을 넘겨 NACK → OLLA가 MCS를 13.7로 내림(스핀 g144는 MCS 20.4 유지, rt 0.72–0.85). 해법: 40 µs 스핀 후 `cudaStreamQuery`+`sched_yield` 폴링(기본값 `SRSRAN_LDPC_CUDA_SYNC=yield`). (2) `RANB_TRAFFIC_SCALE` 2–3은 하네스 쪽 붕괴(CPU LDPC에서도 test2 rt 0.54, MCS 1)라 고부하 축으로 못 쓴다. (3) scale 1·2 모두 DL이 ~32 Mb/s에서 캡 → gNB 설정/스케줄러 제한 확인 필요(큰 C를 보려면 전대역 할당이 필요).

## srsUE의 TB 크기 상한 (13:15 확인)
gNB fixture: `pdcch.dedicated.ss2_type: common`, `dci_format_0_1_and_1_1: false`, `coreset0_index: 12` → srsUE 23.04 NR은 DCI 1_0/0_0만 지원하므로 PDSCH 주파수 할당이 CORESET0 대역(15 kHz, idx 12 = **96 PRB**)을 넘지 못한다. 50 MHz 셀에서도 TB ≤ 96 PRB → C ≤ 8–9, 실측 C=1–8, DL ≈ 32 Mb/s 캡(MCS 20, 96 PRB). 따라서 **srsUE로는 TB당 GPU 우세 영역(C ≥ 6–20)에 구조적으로 못 간다**(OLLA target BLER 1 %도 MCS를 보수적으로 만든다). srsUE에서 GPU LDPC가 줄 수 있는 것은 TB 지연이 아니라 코어 점유(yield/blocking 동기로 UE 코어를 비움)와 S3의 다중 UE 배치뿐. 100 MHz/전대역 TB는 OAI nrUE(DCI 1_1) 경로의 몫.

## S1 체인 4 (yield 동기 빌드, 13:14–13:20) — 50 MHz 1 UE scale 1
| 세션 | 구성 | rt | SCH p50 (C=3) | ue0 DL |
|---|---|---|---|---|
| g139 | 1코어, CPU | 0.883 / 0.876 | 191–287 µs | MCS 20.6, 30.8 Mb/s |
| g144 | 1코어, CUDA spin | 0.720 / 0.852 | 343–383 | MCS 20.4, 31.9 |
| g148 | 1코어, CUDA **block** | **0.939 / 0.936** | 300–385 | MCS 13.7, 19.0 |
| g153 | 1코어, CUDA yield | 0.871 / 0.845 | 250–256 | MCS 14.0, 19.3 |
| g154 | 3코어, CPU | **0.998 / 0.999** | 193–198 | MCS 14.2, 19.3 |
| g155 | 3코어, CUDA yield | 0.989 / 0.979 | 256–369 | MCS 14.0 / 20.0 |

**MCS 14 vs 20은 디코더와 무관한 세션 간 양봉(bimodal) 잡음**이다(CPU 3코어 g154도 14.2; CUDA g155 test2는 20.0). rt와 SCH 타이밍만 비교에 쓴다. 판정: TB당 GPU 경로는 CPU보다 60 µs 느리고(C=3, 호출 125 + fp16 변환 + 대기), 코어가 모자랄 때(1코어)만 blocking 동기가 코어를 비워 rt +0.05; 코어가 충분하면(3코어) −0.01~−0.02. yield 폴링은 block만큼 코어를 못 비웠다(RT 우선순위 스레드 간 sched_yield 효과 제한).

## S1 체인 5 (13:21–13:32) — 코어가 모자란 다중 UE
| 세션 | 구성 | rt | 비고 |
|---|---|---|---|
| g156 | 20 MHz **8 UE** 레시피(3 big + 2 little), CPU | 0.947 / 0.930 (ue3 무트래픽 flake로 UNQUALIFIED) | SCH p50 44–406 µs(little 코어 UE 400 µs) |
| g157 | 20 MHz 8 UE, CUDA **block** + MPS(브로커 포함) | **0.869 / 0.891** | SCH p50 282–440, p99 0.8–5.4 ms. 8 CUDA 컨텍스트 + 깨우기 지연 → **−0.06** |
| g158 | 50 MHz 1 UE 3코어, CUDA block + MPS | 0.993 / 0.996 (CPU 0.998/0.999) | 동률 |

## S1 판정 (2026-10-27)
- **동작**: srsUE에 OCUDU CUDA LDPC 배치 백엔드가 붙고, 비트 패리티·감도(GPU ≥ NEON)·attach·게이트 PASS 모두 확인. 재구성 스톨(핸들 캐시), 동기 모드(spin/block/yield) 등 실무 결함 해결.
- **성능**: TB당 디코드 구간은 GPU가 CPU보다 60–130 µs 느리다(C=1–8). 실시간 비율: 1코어 UE 50 MHz에서만 block 동기로 +0.05(0.88→0.94); 3코어 −0.00~−0.02; 20 MHz 4 UE 동일; **8 UE −0.06**. 즉 S0의 교차점 예측(CB 3–4개)과 "프로세스별 컨텍스트는 UE가 늘수록 불리" 예측이 라이브에서 그대로 확인됐다.
- **구조적 한계**: srsUE는 DCI 1_0만 지원해 PDSCH ≤ CORESET0 폭(96 PRB) → C ≤ 9 → TB당 GPU 우세 영역에 못 간다. 이 한계는 50/100 MHz 캡 해제(S4)로도 안 풀린다.
- **다음 레버**: (a) S3 단일 컨텍스트 배치 서비스는 8/16 UE에서 UE PHY가 병목일 때만 의미가 있는데, 8 UE는 gNB·little 코어 배치가 상한(CPU 0.93–0.94)이고 16 UE는 gNB 비-PHY가 상한(0.46) → S3도 rt를 못 올린다. (b) TB당 이득을 보려면 DCI 1_1(전대역 할당)이 되는 UE, 즉 OAI nrUE 경로(변형 A). (c) srsUE 쪽에서 남은 유일한 CPU 레버는 S2(수신 체인 전체 GPU: FFT 4096·채널추정·등화를 코어에서 빼는 것)이며, 50 MHz 1코어 UE 같은 "코어 부족" 구성에서만 가치가 있다.

## 단계별 프로파일링 (2026-10-28, 라이브 스택, 세션 g169–g175)

도구: 10-26 슬롯 트레이스 패치(`/workspace/gpuch/srsue-slot-trace.patch`, sch_nr.c 헝크 제외)를 `srsRAN_4G-s4`에 적용 + `edit-prof.py`로 CUDA 경로 세부 단계(GCFG 핸들 조회, GFILL int8→fp16 변환, GLNCH 호출 반환, GWAIT 완료 대기, GGPU cudaEvent 커널 구간, GUNPK 비트 풀기, GCRC CRC+패킹)와 CPU 경로(RM, LDPC per CB), TB 합계(TB) 이벤트 추가. `SRSUE_SLOT_TRACE_DIR=<dir>` 로 켬. 분석 `profstat.py`, 세션 요약 `sessions.py`. 체인 `prof-chain.sh`(build-s1 바이너리 하나로 CPU/CUDA 전환). 트레이스 `data/prof-20261028/` (831 MB), pid↔UE 매핑 `pidmap.txt`.

| 세션 | 구성 | rt | ue0 DL Mb/s / MCS |
|---|---|---|---|
| g169 | 50 MHz 1코어 CPU | 0.905 / 0.901 | 21.7 / 13.8 |
| g170 | 50 MHz 1코어 CUDA spin+MPS | 0.841 / 0.852 | 21.6 / 13.8 |
| g171 | 50 MHz 1코어 CUDA block+MPS | 0.916 / 0.924 | 21.8 / 13.8 |
| g172 | 50 MHz 3코어 CPU | 0.998 / 0.997 | 21.5 / 13.7 |
| g173 | 50 MHz 3코어 CUDA block+MPS | 0.993 / 0.987 | 27.9 / 17.5, 38.8 / 22.9 (양봉 잡음) |
| g174 | 20 MHz 4 UE CPU | 0.993 / 0.993 | 5.7 / 12.8 |
| g175 | 20 MHz 4 UE CUDA block+MPS | 0.978 / 0.977 | 6.3 / 14.1 |

TB당 p50 분해 (50 MHz 1코어, C=3, µs): CPU = RM 3×31 + LDPC 3×27(1회 반복) ≈ 174 (TB 192). GPU = RM 93 + fp16 변환 49 + 호출 반환 12 + 완료 대기 64(spin)/115(block) + 비트 풀기 12 + CRC 16 ≈ 248(spin)/300(block) (TB 260/312). 커널 구간(cudaEvent) p50 73 µs = CPU LDPC 3개(81)와 동급. 즉 GPU가 절약한 CPU 시간(81)을 변환·풀기·CRC(77)가 그대로 먹고, 대기 시간이 순손실. host−kernel 오버헤드 spin 5 µs, block 53 µs(p90 178, p99 719 = 깨우기 지연).
커널 구간 p99 300–670 µs, max 10 ms (gNB CUDA·채널 에뮬레이터와 GPU 공유; 1코어 1.6 %, 3코어 5–9 %, 4 UE 2–5 %가 >200 µs). 핸들 생성(새 (ls,F) 조합) 115–317회/런, 1–20 ms씩, 합 0.25–0.8 s/런(여전히 남은 스파이크 원인).
슬롯 예산(DL 작업 >1 ms 비율): CPU 1코어 0.07 %, spin 0.7 %, block 4.5–4.9 %; CPU 3코어 0.12 %, block 3코어 4–8 % (>800 µs 30–42 %); 4 UE block 0.6–1.2 % (CPU 0.1–0.2 %). sync 스레드 "빈 워커 대기" >200 µs: CPU 15회 → block 3코어 158–379회. 1코어 block의 +0.015는 CPU 시간이 같은데(DL 648 − 대기 115 = 533 = CPU 533) 대기 중 sync 스레드가 돌 수 있어 생기는 것. 4 UE는 UE당 CUDA 컨텍스트 4개 + 대기 꼬리로 −0.015.

# S2 — 단말 수신 체인 GPU 이식 (2026-10-29)

사용자 요청: "LDPC까지밖에 안 구현되어 있는데, 여러 PHY 단계 다 GPU 구현해봐". 설계는 OCUDU CUDA 라이브러리의 기지국용 커널을 재사용하는 쪽을 택했다(PDSCH의 DMRS 시드·데이터 스크램블링 공식이 PUSCH와 같아서 `pusch_e2e` 융합 수신기를 그대로 쓸 수 있음).

**구현 파일 (srsRAN_4G-s4 트리, 패치 `patches/srsue-s4-s1-s2-2026-10-29.patch`, 적용 스크립트 `edit-s2.py`):**
- `lib/include/srsran/phy/ue/ue_dl_cuda.h`, `lib/src/phy/ue/ue_dl_cuda.cu` (신규). ① OFDM 복조: CP 제거/윈도 오프셋 gather 커널 → cuFFT(14×N 배치) → shift·DC·윈도 위상·위상 보상 post 커널이 float 그리드(= `ue_dl.sf_symbols[0]`, managed 메모리라 CPU의 PDCCH/CSI가 그대로 읽음)와 cbf16 그리드를 동시에 씀. 입력은 워커 rx 버퍼를 `cudaHostRegister`(GB10은 pageableMemoryAccess=1이라 그냥 호스트 포인터도 됨). ② PDSCH: `pusch_e2e_process_full_gpu_optimized`(DMRS 채널추정·MMSE 등화·연판정·디스크램블 → fp16 LLR) → 자체 `k_dematch` 커널(srsran_ldpc_rm_rx_c와 같은 비트 디인터리브·원형버퍼 선택·필러·반복 누적, 출력 N_full/CB) → 기존 LDPC 핸들 캐시(`srsran_ldpc_cuda_select`)로 `ldpc_decoder_decode_batch_half` → CPU에서 비트 풀기·CRC·TB 조립(`srsran_dlsch_nr_decode_device`, sch_nr.c).
- `ue_dl_nr.c`: `srsran_ue_dl_nr_estimate_fft`/`srsran_ue_dl_nr_decode_pdsch`에 GPU 경로 + 자동 CPU 복귀. GPU PDSCH 적격 조건: C-RNTI, 1 레이어, DMRS type 1, mapping A, reference_point_k_rb=0, 연속 PRB, rv=0이고 softbuffer의 CB가 전부 미복호(재전송 soft combining은 CPU 경로), 안테나 1. 환경변수 `SRSRAN_UE_DL_CUDA=fft|pdsch|all` (pdsch는 `SRSRAN_LDPC_DECODER=cuda` 필요), 동기 모드는 `SRSRAN_LDPC_CUDA_SYNC` 공유. 트레이스 이벤트 `uedl/GFFT`, `uedl/GPDSCH`, `GPT`(e2e 런치, rm+ldpc 런치, 대기), `GPG`(cudaEvent 커널 구간, 풀기+CRC).
- CMake: `enable_language(CUDA)`, sm_121, cuFFT 링크. 빌드 `build-s1`(기존 CUDA 빌드 그대로, `s2-build.sh`).

**오프라인 패리티 테스트 `ue_dl_cuda_test.c`** (srsRAN TX: PDSCH 인코드 + DMRS + OFDM TX → 평탄 채널 + AWGN → 같은 `srsran_ue_dl_nr_t`로 CPU 경로/GPU 경로 각각 복호, GB10 idle, 코어 17):
| 구성 | CPU ok / GPU ok (reps) | FFT CPU→GPU µs | PDSCH(chest+decode) CPU→GPU µs |
|---|---|---|---|
| 20 MHz 96 PRB QPSK mcs4 2 dB | 13 / 24 (60) | 41→20 | 808→672 |
| 96 PRB 16QAM mcs10 8 dB | 45 / 60 | 41→20 | 785→474 |
| 96 PRB 64QAM mcs20 16 dB | 60 / 60 | 40→19 | 834→539 |
| 96 PRB mcs27 22 dB | 59 / 60 | 40→19 | 956→535 |
| 96 PRB mcs10 20 dB, add_pos 0/1, cdm=1 | 30/30 모두 | 40→21 | 387→188, 418→194, 405→193 |
| 48 PRB@30 / 5 PRB@100 / 1 PRB | 30/30 모두 | — | 261→173 / 98→140 / 70→116 |
| 50 MHz(N=4096) 96 PRB@0 / @150 | 30/30 | 86→26/29 | 401→182 / 383→186 |
| 50 MHz 270 PRB mcs20 (C≈13) / mcs27 (C≈21) | 30/30 | 87→30/32 | 1337→447 / 1468→523 |
GPU 경로는 CPU가 복호한 블록을 전부 복호했고 워터폴에서는 더 민감(MMSE+잡음 추정 LLR). 그리드 오차 최대 3e-5 상대. 작은 할당(≤5 PRB)에서는 GPU가 느림(호출 고정비).

**라이브 결과 (`s2-chain.sh`, 세션 g180–g186, 트레이스 `data/s2-20261029/`, `sessions.txt`):** GPU 경로 적중률: PDSCH TB의 99.2 %가 GPU(나머지 254/UE는 SIB·RAR·재전송 → CPU 복귀), FFT 복귀 0, BLER 0.8 % 동일, MCS 동일.
| 구성 | CPU rt | GPU 전체 체인 rt | 비고 |
|---|---|---|---|
| 50 MHz 1코어 (g180/g181/g182) | 0.905/0.913 | **block 0.992/0.990**, spin 0.986/0.973 | +0.08. 슬롯 DL work p50 533→515(block)/413(spin), FFT 80→63/30, CSI 90→67/38, PDSCH 292→223/182 µs |
| 50 MHz 3코어 (g183/g184) | 0.994/0.993 | 0.980/0.986 | −0.01 (GPU 세션 MCS 19, 31.7 Mb/s; 양봉 잡음) |
| 20 MHz 4 UE (g185/g186) | 0.991/0.987 | 0.963/0.969 | −0.025. DL work 127→240 (대기 포함), FFT 33→55, PDSCH 295→280, DL>1 ms 80→500–690/UE, 커널 p99 2.3–2.6 ms |
GPU PDSCH 호스트 분해 (1코어 block/spin, p50): e2e 런치 29/26 + rm·ldpc 런치 10/9 + 대기 134/99 + 풀기·CRC 13 = 213/173 µs; cudaEvent 커널 구간 131/129 µs (= CPU chest 25 + eq 39 + demod 7 + sch 199 = 270 µs 대체). 슬롯당 PDSCH CPU 일 ≈ 52 µs. 꼬리: DL>1 ms 슬롯 CPU 67 → block 1500 (3.5 %)/spin 152; 최대 10–27 ms = 새 (Z,F) 조합 핸들 생성(rm+ldpc 런치 max 9.8–17.7 ms) + GPU 공유. 판정: 코어가 모자란 구성(50 MHz 1코어)에서는 전체 체인 이식이 LDPC 단독(+0.015)보다 훨씬 크게(+0.08) 듣고 거의 실시간에 도달; 코어가 충분하거나 UE가 많으면(스트림 12개 공유) 호출당 대기와 꼬리로 손해. 남은 레버: 핸들 사전 생성, 슬롯당 한 번의 동기(FFT 대기와 PDSCH 대기 합치기), UE 공용 서비스.
