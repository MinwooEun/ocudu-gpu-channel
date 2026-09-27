# 통합 GPU용 zero-copy channel emulator 마일스톤

**목표: 통합 GPU(DGX Spark GB10, Jetson Orin)에서 channel emulator가 슬롯마다 하는 CPU↔GPU IQ 복사를 없애, emulator 처리 지연(`gpu_process_us`, 라이브 브로커 `process_latency_summary`)을 줄인다. 출력은 복사 경로와 bit 단위로 같아야 한다.**

[`SPARK_MILESTONES.md`](SPARK_MILESTONES.md)(S 트랙), [`JETSON_MILESTONES.md`](JETSON_MILESTONES.md)(J 트랙)와 독립된 트랙이다. 단계 번호는 `Z`, 브랜치는 `gb10-zero-copy`(PR #2 브랜치 `a07b8a9`에서 분기). 판정 규율은 다른 트랙과 같다: 성능 주장은 같은 소스·같은 조건의 A/B로만 하고, 실패 측정도 보존하며, 공유 GPU에서 잰 시간은 다른 GPU 프로세스가 없었음을 함께 기록한다.

## 왜 하는가

emulator의 CUDA 백엔드는 디스크리트 GPU(RTX 5090) 기준으로 짜여 있다. 슬롯마다 pinned 호스트 버퍼(`cudaHostAlloc`)에 IQ를 모은 뒤 `cudaMemcpyAsync`로 H2D 복사하고, 커널이 끝나면 다시 D2H 복사한다. GB10은 CPU와 GPU가 같은 LPDDR5X를 쓰지만 코드가 복사를 직접 요청하므로 복사는 그대로 일어난다(버스 대신 같은 DRAM 안에서).

## Z0 기준선 (2026-09-26, 복사 경로)

같은 소스 `a07b8a9`, CUDA 13.0, 빅 코어 4개 고정, 11개 설정 × 10 s × 3회. 전체 표는 워크스테이션 `~/ocudu-work/perf-platform/compare.md`.

| 설정 | 단계 (p50, µs) | 5090 | GB10 |
|---|---|---|---|
| mvp-2edge | H2D | 14.1 | 8.4 |
| | kernel | 6.6 | 13.3 |
| | D2H | 11.0 | 11.4 |
| | **gpu_process_us** | **44.8** | **43.6** |
| tdl-a | kernel | 51.6 | 64.5 |
| | **gpu_process_us** | **86.2** | **93.5** |
| fanin-N64 | **gpu_process_us** | 47.5 | 54.4 |

라이브 legacy 1×1 브로커는 두 플랫폼 모두 p50 65 µs.

**기대 상한:** GB10 mvp-2edge에서 H2D + D2H ≈ 20 µs가 없앨 수 있는 최대치다 → 44 → 약 24 µs. tdl-a처럼 커널이 무거우면 비중이 작아 약 20%. GB10 커널이 5090의 약 2배인 문제는 이 트랙으로 풀리지 않는다.

## 설계

- **노브:** `runtime.cuda_host_memory: copy | zero_copy | auto`. 기본값은 `copy`로, 현재 동작과 같다. `auto`는 `cudaDevAttrIntegrated=1`이고 `cudaDevAttrCanMapHostMemory=1`일 때만 zero-copy를 쓴다. `zero_copy`를 명시하면 디스크리트에서도 허용해서 음성 대조군으로 잴 수 있다.
- **zero-copy 경로:** 호스트 버퍼를 `cudaHostAllocMapped`로 잡고, 커널은 `cudaHostGetDevicePointer` 포인터로 그 메모리를 직접 읽고 쓴다.
  - `host_source_iq`(원시 IQ, device-channel 경로 입력), `host_next_slot_start`, `host_output`: device 쪽 포인터가 같은 메모리의 별칭이다. H2D·D2H 복사가 없어진다.
  - `host_staged`(host-stage 경로 입력): `mapped_staged` 별칭으로 읽는다. `device_staged`는 device-channel 경로의 GPU 전용 중간 버퍼라 device 메모리로 남긴다.
  - 슬롯 끝의 `cudaStreamSynchronize`는 그대로 둔다. 호스트가 다음 슬롯 입력을 쓰기 전에 GPU가 이번 슬롯을 끝냈음을 보장하는 장치다.
- **아직 남는 복사:** 슬롯마다 올라가는 작은 메타데이터(`steps`, `step_meta`, `rx_steps`; pageable `std::vector`에서 H2D), 호스트가 edge IQ를 `host_source_iq`로 모으는 복사, `host_output` → 호출자 버퍼 `std::copy`. Z4에서 다룬다.
- **관측:** `ProcessorTimings.zero_copy`가 실제로 쓴 모드를 보고한다. zero-copy에서 `h2d_us`는 메타데이터만, `d2h_us`는 약 0이다. 비교 지표는 `gpu_process_us`(호출 전체 벽시계)다.

## 단계

| 단계 | 내용 | Exit 게이트 | 상태 |
|---|---|---|---|
| **Z0** | 기준선 — 복사 경로 5090 vs GB10 | 단계별 시간표, 라이브 p50 | **완료 2026-09-26** (위 표) |
| **Z1** | 프로토타입 — `cuda_host_memory` 노브 + 큰 IQ 버퍼 zero-copy | 로컬(5090) 빌드, ctest 통과, **copy vs zero_copy bit 동일**(device-channel 경로 + host-stage 경로, 4슬롯, 페이딩·CFO·AWGN·rx 잡음 모델 포함) | **완료 2026-09-27 (5090)** — ctest 12/12, bit 동일 통과, 음성 대조군 exit 1. 5090 A/B는 아래 |
| **Z2** | Spark 빌드 + 정확성 | sm_121 빌드, ctest 통과, `gpu-test-sequence.sh` 9단계를 `zero_copy`로 통과, 오류 카운터 0 | **완료 2026-09-27** — ctest 12/12(GB10에서 bit 동일), 9/9 통과, `auto` → zero-copy 확인 |
| **Z3** | **A/B 측정** — 같은 바이너리로 `copy` vs `zero_copy` | GB10 11개 설정 × 3회: `gpu_process_us`·`kernel_us` p50/p99. **커널이 mapped 메모리 때문에 느려지는지**가 핵심 관측. 5090에서 `zero_copy`는 음성 대조군(느려져야 정상) | **완료 2026-09-27** — GB10 11개 설정 전부 `gpu_process_us` p50 **−5~−12 µs(−6~−25%)**, 커널은 +6~+11 µs. 5090은 Z1에서 대조군 확인 |
| **Z4** | 남은 복사 제거 (Z3 결과 보고 결정) | 메타데이터를 mapped 메모리로, 입력 모으기와 출력 `std::copy` 제거 검토(GB10 `pageableMemoryAccessUsesHostPageTables=1`이라 호출자 버퍼 직접 접근 가능성). 단계마다 bit 동일 + A/B | **완료 2026-09-27** — 부분별 분해 측정. 기본값을 `in,out,direct`로(메타데이터 mapped는 역효과라 제외). 기본 2 edge 호출 46.1 → **31.8 µs(−31%)**. 입력 모으기 제거는 미착수(아래 Z8) |
| **Z5** | 라이브 — legacy 1×1 게이트를 `zero_copy`로 | attach·PDU·ping 통과, 카운터 0, 브로커 p50이 65 µs 대비 얼마나 줄었는지(같은 날 `copy` 1회와 짝지어 측정) | **완료 2026-09-27** — copy/zero-copy 짝 측정 2라운드(Z3 코드 4회 + 최종 코드 4회) 전부 통과. 최종 코드: ue0 p50 55–65 → **40–45 µs**, p99 100 → **80–85 µs** |
| **Z6** | Jetson Orin 확인 | Orin은 통합이지만 `ConcurrentManagedAccess=0`(D6). mapped pinned는 managed와 다른 경로라 동작해야 하지만 캐시 동작과 성능은 실측으로 판정. bit 동일 + A/B | 대기 |
| **Z8** | **입력 직접 읽기 + 브로커 ring 복사 제거** (Z4 이후 남은 최대 병목) | 커널이 호출자/ring 버퍼에서 바로 읽어 `host_prep`의 입력 모으기 복사를 없애고, 브로커 ring read/push 복사를 줄임. 사용자 수×대역폭에서 슬롯 예산(500 µs) 안으로 들어오는지 | 제안 |
| **Z7** | 기본값 결정 + 정리 | Z3–Z6 근거로 `auto`를 기본으로 할지 결정, 문서·예제 YAML 갱신, PR 준비(push는 확인받고) | 대기 |

## 위험

1. **커널이 느려질 수 있다.** mapped 메모리를 GPU가 읽고 쓸 때 캐시·일관성 동작이 `cudaMalloc` 메모리와 다르다. 복사 20 µs를 아껴도 커널이 그만큼 느려지면 이득이 없다. Z3에서 `kernel_us`를 따로 본다.
2. **출력 in-place 갱신.** rx 잡음 모델은 `host_output`을 제자리에서 읽고 다시 쓴다. zero-copy에서는 이 읽기·쓰기가 mapped 메모리에서 일어난다.
3. **디스크리트 회귀 금지.** 기본값 `copy`와 `auto`의 통합 GPU 한정으로 5090 경로는 바뀌지 않는다. Z3에서 5090 `copy` 수치가 Z0와 같은지 확인한다.
4. **공유 GPU.** Spark와 Jetson GPU는 다른 사용자 컨테이너와 공유한다. 측정 시점의 다른 GPU 프로세스 유무를 기록한다.

## 진행 기록

### Z1 — 2026-09-27

- 브랜치 `gb10-zero-copy`를 `a07b8a9`에서 분기했다(로컬 worktree `~/ocudu-work/ocudu-cuda-pr`).
- 변경: `include/ocudu_gpu_channel/config.h`(`CudaHostMemory`, `RuntimeConfig::cuda_host_memory`), `src/config.cpp`(파서), `include/ocudu_gpu_channel/processing.h`(`ProcessorTimings::zero_copy`), `src/cuda_backend.cu`(할당·해제·슬롯 경로).
- 테스트: `tests/test_processing.cpp` (h) copy vs zero_copy bit 동일, `tests/test_config.cpp` 노브 파싱.
- 검증(워크스테이션 RTX 5090, CUDA 13.0, sm_120, Release): ctest **12/12**. 새 parity 테스트의 **음성 대조군**: host-stage 경로가 `mapped_staged` 대신 채워지지 않은 `device_staged`를 읽게 일부러 바꾸면 `FAIL: zero-copy parity: host-stage path must be bit-identical to copy`, exit 1. 되돌린 뒤 다시 통과.
- **5090 A/B (음성 대조군, 같은 바이너리, 코어 2-5 고정, 5 s × 2회, p50 µs, 다른 GPU 프로세스 없음):**

| 설정 | 모드 | H2D | kernel | D2H | gpu_process_us |
|---|---|---|---|---|---|
| mvp-2edge | copy | 14.1 | 6.6 | 10.9–11.0 | **44.7** |
| | zero_copy | 1.9 | **34.7–35.1** | 0.35 | **48.5–49.0** |
| tdl-a | copy | 14.1 | 51.4 | 7.7 | **85.7–85.9** |
| | zero_copy | 1.9 | **3697–3711** | 0.6 | **3808–3821** |

  - `copy` 수치가 Z0(44.8 / 86.2)와 같다 → 기본 경로 회귀 없음.
  - 디스크리트에서 zero-copy는 예상대로 느리다. mvp는 복사 25 µs를 없애고 커널이 28 µs 늘었다.
  - **tdl-a는 43배 느려졌다.** `apply_channel_kernel`이 23탭 × 분수 지연 필터 8탭만큼 같은 입력 샘플을 반복해서 읽는데, 그 읽기가 전부 PCIe를 건넌다. **GB10에서도 mapped 메모리 읽기가 GPU 캐시에 잘 안 잡히면 같은 현상이 작게라도 나타날 수 있다 — Z3의 1순위 관측 항목.** 느리면 대안은 입력을 한 번만 읽어 shared memory에 올리는 커널 쪽 변경이다.

### Z2 — 2026-09-27 (Spark `ocudu-minwoo`, GB10 sm_121, CUDA 13.0.88)

- 복사본: `/workspace/gpuch/zc` = `a07b8a9` clone + 로컬 diff(`git diff | sha1sum` = `7511dde3…`, 워크스테이션과 같음). 빌드 `/workspace/gpuch/zc-builds/cuda-release`.
- ctest **12/12** — (h) copy vs zero_copy bit 동일이 GB10에서도 통과.
- **9단계 시퀀스:** 기본값만 `ZeroCopy`로 바꾼 시험용 복사본 `/workspace/gpuch/zc-default`(config.h에 `Z2 TEST-ONLY flip` 표시, 커밋 대상 아님)로 `gpu-seq-body.sh` 실행 → **GPU TEST SEQUENCE PASSED**, 로그 `/workspace/gpuch/zc-gpu-seq-20260927T072836Z.log`. 같은 빌드의 벤치가 YAML에 키 없이 `cuda_zero_copy,1`을 보고해 zero-copy로 돌았음을 확인했다. 수치는 09-26 복사 경로 실행과 같다(TDL-A 3.33, 2×2 상관 9.54, iid 6.96) — bit 동일과 일치.
- 빠른 확인(코어 16-19, 5 s × 2회): `auto`가 GB10에서 zero-copy를 고른다(`cuda_zero_copy,1`).

### Z3 — 2026-09-27 (Spark, 같은 바이너리 A/B)

- 하네스 `/workspace/gpuch/perf-zc-compare.sh`(Z0 하네스에서 CPU 백엔드 대신 `cuda_host_memory` copy/zero_copy를 교차 실행), 코어 5-8(Z0와 같음), 11개 설정 × 10 s × 3회, 66회 모두 ok. 결과 `/workspace/gpuch/perf-zc/perf-zc-20260927T073041Z`, 워크스테이션 사본 `~/ocudu-work/perf-platform/runs/spark-zc/`, 표 `~/ocudu-work/perf-platform/compare-zc.md`(분석 `analyze-zc.py`). 모든 csv가 요청한 모드를 보고했다. nvidia-smi에 다른 GPU 프로세스는 없었다(`gpu_util_before`는 직전 벤치 실행의 잔여값).

| 설정 | copy gpu_process p50 | zero_copy | Δ | H2D | kernel | D2H |
|---|---|---|---|---|---|---|
| mvp-2edge | 43.7 | **34.7** | −9.0 (−21%) | 8.8 → 3.3 | 13.3 → 20.3 | 11.5 → 0.8 |
| multi-ue-4edge | 45.2 | **34.6** | −10.6 (−23%) | 9.8 → 2.8 | 13.3 → 19.3 | 11.2 → 0.8 |
| graph-6edge | 49.1 | **44.4** | −4.7 (−10%) | 13.1 → 4.1 | 17.4 → 27.8 | 7.8 → 0.8 |
| multi-gnb-8edge | 46.6 | **39.8** | −6.9 (−15%) | 13.4 → 2.8 | 13.4 → 24.3 | 8.7 → 0.8 |
| stress-16edge | 47.5 | **35.6** | −11.9 (−25%) | 9.0 → 2.9 | 13.3 → 19.9 | 12.5 → 0.8 |
| tdl-a | 92.3 | **86.3** | −6.0 (−6%) | 8.4 → 3.3 | 64.5 → 71.4 | 8.5 → 0.8 |
| tdl-a-fanin8 | 96.6 | **87.9** | −8.7 (−9%) | 8.9 → 2.9 | 64.5 → 71.6 | 11.0 → 0.8 |
| fanin-N1 | 43.7 | **34.8** | −8.9 (−20%) | 8.4 → 3.3 | 13.4 → 20.4 | 11.5 → 0.8 |
| fanin-N4 | 46.8 | **35.1** | −11.7 (−25%) | 8.8 → 2.8 | 13.4 → 19.6 | 12.5 → 0.8 |
| fanin-N16 | 47.5 | **37.2** | −10.3 (−22%) | 8.7 → 3.2 | 13.7 → 20.4 | 7.8 → 0.8 |
| fanin-N64 | 54.4 | **43.4** | −10.9 (−20%) | 9.1 → 3.9 | 18.3 → 23.8 | 11.8 → 0.8 |

- 반복 간 p50 폭은 대부분 1 µs 이내라 차이는 잡음보다 훨씬 크다. copy 수치는 Z0(mvp 43.6, tdl-a 93.5, N64 54.4)와 맞다.
- **판정:** GB10에서 zero-copy는 모든 설정에서 emulator 호출 시간을 줄인다. 복사 약 17–22 µs가 사라지고, **커널이 +6~+11 µs 늘어** 순이득은 5–12 µs다. 5090에서 본 43배 붕괴(Z1)는 GB10에서는 없다 — mapped 메모리 읽기가 GPU에서 충분히 빠르다.
- 꼬리도 줄었다: fanin-N64 p99 407.6 → 212.7, fanin-N16 116.4 → 74.3, stress-16edge 78.6 → 62.3.
- 남은 H2D ~3 µs는 작은 메타데이터 복사, 커널 증가분은 mapped 메모리 접근 비용이다. 커널 증가분이 설정과 무관하게 거의 일정(+6~+7 µs, 1개 출력 행)한 것으로 보아 출력 쓰기 쪽이 주 원인일 가능성이 있다 — 추정이며 nsys로 확인하지 않았다. Z4의 첫 후보는 출력만 device 메모리 + D2H로 되돌리는 혼합 모드와 메타데이터 mapped화다.
- 벤치의 `model_mix_latency`도 같은 폭으로 줄었다(mvp 58.1 → 49.2).

### Z4 — 2026-09-27 (부분별 zero-copy 분해, Spark)

- 코드: `ZeroCopyParts`(in/out/meta/direct). `in`=`source_iq`·`next_slot_start`·`staged`, `out`=`output`, `meta`=`steps`·`step_meta`·`rx_steps`, `direct`=출력 행이 1개일 때 커널이 **호출자 버퍼에 직접** 쓴다(`cudaDevAttrPageableMemoryAccess=1` 필요; GB10과 이 워크스테이션 5090 모두 1). 측정용 스위치 `OCG_ZC_PARTS`(지원 노브 아님). `ProcessorTimings`에 `host_prep_us`(호출 시작→첫 GPU 명령), `host_out_us`(출력 복사), `call_us`(호출 전체 = 브로커 `process_us`) 추가, 벤치에 같은 행과 `--per-node` 추가.
- parity 테스트가 copy vs {기본, in,out / in,out,meta / in / out / meta / in,out,meta,direct / in,out,direct} 전부를 4슬롯 bit 동일로 검사한다. 5090·GB10 모두 ctest 12/12.
- 실험 드라이버 `~/ocudu-work/perf-platform/zc-scale.py`, `zc-final.py`, 분석 `analyze-zc-scale.py`, 표 `compare-zc-scale.md`. 결과 `/workspace/gpuch/zc-scale-20260927T075744Z`(229회), `/workspace/gpuch/zc-final-20260927T081914Z`(60회), 모두 rc=0, 모드 불일치 0. 코어 5-8, 5 s × 3회, 중앙값. 코드 diff sha1 `e1dae4f6…`(zc4) / `d6b06493…`(zc5, 최종).

**부분별 효과 (mvp-2edge, `call_us` p50):**

| 모드 | call | host_prep | H2D | kernel | D2H | host_out |
|---|---|---|---|---|---|---|
| copy | 46.4 | 2.0 | 8.5 | 13.4 | 11.6 | 4.7 |
| in만 | 42.1 | 2.0 | 2.8 | 18.0 | 8.5 | 4.8 |
| out만 | 38.8 | 2.1 | 10.5 | 15.4 | 0.8 | 5.7 |
| meta만 | **48.4 (악화)** | 2.1 | 7.0 | **21.3** | 7.8 | 4.8 |
| in,out | 36.8 | 2.0 | 3.3 | 20.7 | 0.8 | 5.6 |
| in,out,meta | 37.8 | 2.0 | 0.8 | 24.4 | 0.8 | 5.1 |
| **in,out,direct (최종 기본)** | **31.8** | 1.8 | 3.2 | 20.8 | 1.0 | **0.4** |

- **out이 in보다 이득이 크다:** D2H 복사(−11 µs)를 없애는 대가로 커널은 +2 µs. in은 H2D(−6 µs)를 없애고 커널 +4.6 µs.
- **meta는 역효과:** H2D는 1.5 µs 줄지만 커널이 +8 µs. 모든 GPU 스레드가 스텝 정보를 매번 읽는데, 그 읽기가 mapped 메모리로 간다. 그래서 기본값에서 뺐다.
- **direct:** 출력 `std::copy`(4–30 µs, 대역폭에 비례)가 사라진다.
- 최종 기본값 판정(`zc-final`): `in,out,direct`가 fan-in(N16 gNB 150.1 vs 155.9, N64 708.6 vs 757.2)과 mvp에서 가장 빠르고, tdl-a(83.0 vs 80.9)·122M(64.8 vs 62.7)에서는 meta 포함판보다 약 2 µs 느리다.

### Z5 — 2026-09-27 (라이브 legacy 1×1, Spark)

- 러너가 브로커 빌드 폴더를 `${native_root}/builds/ocudu-gpu-channel-cuda-release`로 고정해 두어, 다른 소스 트리에서는 CMake 캐시 불일치로 실패했다. `OCUDU_NATIVE_CHANNEL_BUILD`로 바꿀 수 있게 했다(Spark 복사본에만 적용, 저장소 반영은 PR 때).
- zero-copy 트리는 기본값만 바꾼 시험용 복사본(`zc-default`, `zc5-default`)이고, 같은 빌드의 벤치가 `cuda_zero_copy,1`을 보고했다. 라이브 로그의 `gpu_timings`에서도 D2H가 0.8–1.0 µs로 zero-copy가 돈 것이 보인다. copy 트리는 2.4–7.6 µs.
- 8회 전부 **통과**(rrc/PDU/ping, 카운터 0, rx_starvations 1–2 — 09-26 기준 게이트와 같은 수준). 최종 코드 전에 9단계 시퀀스도 다시 통과(`zc5-gpu-seq.log`).

| 코드 | 모드 | 실행 | gnb0 p50 / p99 | ue0 p50 / p99 |
|---|---|---|---|---|
| Z3 (in,out) | copy | 075358Z | 65 / 100 | 65 / 105 |
| | zero-copy | 075445Z | 55 / 90 | 55 / 90 |
| | copy | 075531Z | 55 / 100 | 60 / 105 |
| | zero-copy | 075617Z | 55 / 90 | 55 / 90 |
| 최종 (in,out,direct) | copy | 082700Z | 45* / 100 | 55 / 100 |
| | zero-copy | 082748Z | 45 / 80 | **40 / 80** |
| | copy | 082835Z | 45* / 100 | 65 / 100 |
| | zero-copy | 082921Z | 45 / 80 | **45 / 85** |

  \* 이 두 copy 실행의 gnb0은 호출 수가 약 1.6배(n=16.8k vs 10.7k)로, 샘플 수가 적은 조각 호출이 섞여 p50이 낮게 나왔다. 조각이 적은 ue0과 p99로 비교한다. 히스토그램은 5 µs 단위다.
- **판정:** 라이브에서 브로커의 emulator 호출은 p50 약 15–20 µs, p99 약 20 µs 줄었다(ue0 55–65 → 40–45, p99 100 → 80–85).
- **브로커의 다른 단계:** 같은 로그에서 ring 읽기(`read_us`)와 ring 쓰기(`push_us`)는 각각 중앙값 30–40 µs로 모드와 무관하게 그대로다. 둘 다 184 KB IQ를 CPU로 복사하는 단계다. 이제 emulator 호출(약 40 µs)보다 크다 → Z8.

## 무엇을 줄였나 — 슬롯 하나의 IQ 경로 (라이브 브로커, 1 ms = 23,040샘플 = 184 KB, 방향마다)

| # | 단계 | 누가 | copy | zero-copy (최종) |
|---|---|---|---|---|
| 1 | ZMQ 수신 → TX ring | 브로커 puller, CPU 복사 | 있음 | 있음 |
| 2 | TX ring → 입력 창 (`read_us`) | 브로커, CPU 복사 | 있음 | 있음 |
| 3 | 입력 창 → `host_source_iq` (`host_prep_us`) | emulator, CPU 복사 | 있음 | 있음 |
| 4 | `host_source_iq` → GPU 메모리 (H2D) | DMA | **있음** | **없음** — 커널이 mapped 메모리를 직접 읽음 |
| 5 | 커널 (TDL·페이딩·중첩·수신 잡음) | GPU | device 메모리 | mapped 메모리 읽기/쓰기, **+6~8 µs** |
| 6 | GPU 메모리 → `host_output` (D2H) | DMA | **있음** | **없음** — 커널이 호출자 버퍼에 직접 씀 |
| 7 | `host_output` → 호출자 행 (`host_out_us`) | emulator, CPU 복사 | **있음** | **없음** (direct) |
| 8 | 호출자 행 → RX ring (`push_us`) | 브로커, CPU 복사 | 있음 | 있음 |
| 9 | RX ring → ZMQ 응답 | 브로커 REP, CPU 복사 | 있음 | 있음 |

mvp-2edge 호출 하나로 본 이득(−14.3 µs): H2D IQ −5.3, D2H −9.7, 출력 복사 −4.4, 기타 enqueue/이벤트 −2.2, 커널 +7.5. 커널 증가분은 GPU가 자기 메모리 할당(`cudaMalloc`) 대신 호스트 매핑 메모리를 읽고 쓰는 비용이다. 부분별 측정에서 읽기(in +4.6, meta +8)가 쓰기(out +2)보다 비싸다. 원인은 추정이고 nsys나 ncu로 확인하지 않았다.

## 사용자 수·대역폭에 따른 스케일링 (Spark, `call_us` p50, µs)

**대역폭** (1 링크, 1 ms 배치, 샘플 수 = 샘플레이트/1000):

| 샘플레이트 | mvp copy | mvp zero-copy | 절감 | TDL-A copy | TDL-A zero-copy | 절감 |
|---|---|---|---|---|---|---|
| 23.04 MS/s (184 KB) | 46.1 | 31.8 | −14 (−31%) | 95.6 | 83.0 | −13 (−13%) |
| 46.08 MS/s | 58.0 | 37.6† | −20 (−35%) | 119.7 | 94.3† | −25 (−21%) |
| 92.16 MS/s | 98.6 | 52.3† | −46 (−47%) | 182.2 | 126.6† | −56 (−31%) |
| 122.88 MS/s (983 KB) | 120.7 | 64.8 | −56 (−46%) | 215.4 | 145.9† | −70 (−32%) |

† `in,out,meta,direct` 측정값(최종 기본과 1–2 µs 차이, `zc-final`에서 확인한 범위).

- **대역폭이 커질수록 절감이 커진다.** 없앤 복사 세 개(H2D, D2H, 출력 복사)가 모두 바이트 수에 비례하고, 커널 증가분은 그보다 느리게 는다(mvp에서 +7 → +22 µs, 복사 절감은 −19 → −72 µs).

**사용자 수** (gNB 1개 + UE N개; gNB 노드는 N개 UE의 업링크를 한 호출에서 중첩):

| N | gNB 노드 copy | zero-copy | 절감 | 그중 `host_prep`(입력 모으기) | UE 노드 하나 copy → zero-copy |
|---|---|---|---|---|---|
| 1 | 46.8 | 32.8† | −14 | 2 | 46.1 → 33.0† |
| 4 | 77.2 | 59.7† | −18 | 13–19 | 48.8 → 33.8† |
| 16 | 212.4 | 150.1 | −62 (−29%) | 73–100 | 49.5 → 35.1† |
| 64 | 933.7 | 708.6 | −225 (−24%) | **511–526** | 62.6 → 41.4† |

**사용자 × 대역폭** (gNB 노드): N16 @ 92.16 MS/s 924 → 650 µs(−274, `in,out,meta,direct`), N4 @ 92.16 MS/s 222 → 137 µs.

- **사용자가 늘어도 절감(µs)이 커진다.** gNB의 H2D 복사가 N에 비례하기 때문이다(N64에서 209 µs → 0). UE 노드는 각자 −10~−21 µs를 얻고, 브로커는 노드마다 스레드를 따로 돌린다.
- **다만 비율은 줄어든다(−31% → −24%).** 남은 시간의 대부분이 `host_prep`, 즉 N개 UE의 IQ를 CPU로 `host_source_iq`에 모으는 복사이기 때문이다. N64에서 526 µs(호출의 56–72%), N16 @ 92M에서 507 µs다. 이 복사는 zero-copy가 건드리지 않는다. 이 모델에는 샘플 단위 CPU 작업이 이 복사 말고 없다는 것은 코드를 읽고 판단했다.
- **30 kHz 슬롯 예산(500 µs):** N64 gNB(709 µs)와 N16 @ 92M(650 µs)은 zero-copy 후에도 초과한다. `host_prep`만 없애도 둘 다 예산 안으로 들어올 수 있다(추정) → Z8.
