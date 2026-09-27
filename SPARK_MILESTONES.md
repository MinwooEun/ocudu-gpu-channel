# DGX Spark(GB10)에서 CUDA 가속 OCUDU 검증 마일스톤

**목표: WG1의 기준 플랫폼(DGX Spark / GB10)에서 벤더 브랜치 `nvcuda_accel_02`를 빌드·자체 검증·라이브 attach까지 확인하고, 5090(C 트랙)·Orin(J 트랙) 결과와 같은 절차로 대조한다.**

[`CUDA_MILESTONES.md`](CUDA_MILESTONES.md)(RTX 5090, 디스크리트), [`JETSON_MILESTONES.md`](JETSON_MILESTONES.md)(Orin, 통합 + CMA 0)와 독립된 트랙이다. 단계 번호는 `S`. 판정 규율(음성 대조군 exit≠0 + 메커니즘 로그 확인, "무엇이 실제로 돌았는가" 판정, 실패 측정 보존)은 C·J 트랙과 같다.

## 왜 Spark인가

WG1이 문서에 적은 검증은 **이 기종**에서 나왔다. 앞의 두 플랫폼은 모두 WG 환경과 어긋났고, 그 어긋남이 결함을 드러냈다(5090: D1–D5, Orin: D6). Spark는 어긋남이 가장 작은 대조군이다.

| 축 | WG 기준 | 이 Spark | 5090 | Orin |
|---|---|---|---|---|
| GPU | GB10 `sm_121` | **GB10 `sm_121`, SM 48** | `sm_120` | `sm_87` |
| CUDA / 드라이버 | 13.0.88 / 580.95.05 | **13.0.88** / 580.178.04 | 12.8.93 / 595.71.05 | 12.6.68 / 540.4.0 |
| CPU | X925/A725 aarch64 | **같음, 20코어** | x86_64 | A78AE |
| managed 속성 CMA/hostPT/direct | 벤더 표 1/1/0 | **1/1/0 실측(09-24)** | 1/0/0 | 0/0/0 |

**첫 번째 수확(09-24):** WG1 제보서(이슈 #2)에 "GB10 값은 벤더 표로 추론했고 실측하지 않았다"고 적은 `1/1/0`을 **실측으로 확인**했다. 따라서 제보서의 결론 — `fully_coherent`(셋 다 1)는 GB10에서도 불만족이라 직접 하향 링크 리더는 GH200급에서만 켜진다 — 은 이제 실측 근거를 갖는다. 라이브에서 실제로 DEGRADED가 나는지는 S4에서 본다.

**예상:** Orin D6은 `ConcurrentManagedAccess=0`에서만 나는 문제라 Spark(1)에서는 재현되지 않아야 한다. 5090 D1–D5 중 D1·D2는 managed 그리드에서는 벤더의 GB10 경로를 타므로 벤더 테스트가 통과할 가능성이 높다. D3·D4는 플랫폼 무관(설정 전달·SINR 대입)이라 벤더 테스트로는 여전히 보이지 않을 것이다.

## 환경

컨테이너 `ocudu-minwoo`(DGX Spark 호스트 `spark-host`, 포트 2202, 워크스테이션에서 `ssh spark-minwoo`). 구성·생성 과정은 [`scripts/cuda/spark/README.md`](scripts/cuda/spark/README.md). 작업 루트 `/workspace/ocudu-spark/{src,builds,install,tools,results}`, 레포 `/workspace/ocudu-cuda-rebuild`. GPU는 user-a·user-b 컨테이너와 **공유**한다 — 시간 측정을 기록할 때는 다른 GPU 프로세스가 없었음을 함께 기록한다.

## 단계

| 단계 | 내용 | Exit 게이트 | 상태 |
|---|---|---|---|
| **S0** | 컨테이너·소스 준비 | netns·TUN·rtprio, GB10 보임, 벤더 소스 `5830c9cb` 깨끗함, 레포 전송 | **완료 2026-09-24** |
| **S1** | **벤더 원본 빌드 + 자체 검증 (패치 없이)** — J1 스크립트를 `CUDA_ARCH=121`로 | 빌드 성공, WG 12 PHY + OFH 판정, 로그 판정기, **WG 문서의 "12/12, 252.53 s"와 대조**. 실패마다 메커니즘 | **완료 2026-09-24 — PHY 9/12, OFH 16/16. 실패 3건 = 5090의 D1·D2와 동일 → 하드웨어 무관 벤더 결함** |
| **S2** | C1 패치(`d2579af2`) 적용 재검증 + 음성 대조군 | PHY 14 / OFH 16, NC-D1–D5가 Spark에서 무엇을 보이는지(managed 경로에서는 D1·D2 대조군이 반응하지 않을 수 있음 — 그 자체가 기록 대상) | **완료 2026-09-24 — PHY 14/14, OFH 16/16, NC-D1–D5 전부 exit≠0 + 메커니즘 확인** |
| **S3** | aarch64 스택 + CPU 기준선 — Open5GS, srsUE, CPU OCUDU, 직결 ZMQ | CPU gNB 3/3, CUDA gNB 전 모드 `disabled` 3/3 | **완료 2026-09-25** — CUDA gNB `disabled` 3/3, `all` 3/3(09-24). CPU gNB(`a1916edc`) 4/4(09-25, 러너에 `cpu` stage 추가) |
| **S4** | 단계별 활성화 + 백엔드 판정 | `verify-stage-backends.py`로 selected/degraded/fallback. **lower-PHY TX가 GB10에서도 DEGRADED인지** 실측 | **완료 2026-09-24** — 5단계 전부 통과, silent fallback 0. TX direct 경로는 GPU PDSCH가 켜진 단계부터만 |
| **S5** | BLER/SINR 정합 + 이슈 6(16QAM CRC 상승) 재현 여부 | CPU 대비 BLER ≤1%p, SINR ≤0.5 dB, 이슈 6 판정 | **완료 2026-09-25** — C1: 할당 일치 PASS지만 합산 BLER 6배 → 원인 D8(1 PRB SINR) + D9(LDPC 계수). **C1+D8+D9: 교차 6회 ΔBLER −0.00%p, ΔSINR −0.19 dB, 16QAM `[0,17)` 1.90 vs 1.89%** |
| **S6** | 측정 — 20 MHz 1-layer와 WG 수치 구성(100 MHz 4-layer) | WG 표의 21.20×(PUSCH) 등 재현 여부. **여기서부터 성능 주장 가능** | **완료 2026-09-25** — 100 MHz 4L: 감도·PDSCH 문서와 일치, **PUSCH 22×(CPU 빅 코어 고정; 미고정 40×는 착시)**. 20 MHz 1L: PDSCH 문서와 일치, PUSCH는 고정 시 1.1×(미고정 2.3×는 착시). 라이브 20 MHz 1L에서는 GPU가 느리다 |
| **S7** | **채널 에뮬레이터 경유 + 멀티 gNB** — CUDA gNB를 emulator에 붙이고, CUDA gNB 프로세스 2개(2셀, 셀 간 간섭)를 한 GPU에서 | CUDA 1×1 emulator 게이트 통과, CPU 2셀 기준선 통과, CUDA 2셀에서 UE마다 자기 셀에 붙어 RRC/PDU/ping, 카운터 0, late 0 | **완료 2026-09-27** — 셋 다 통과. CUDA gNB 1개당 GPU 메모리 9,545 MiB. MPS 없이 시간 분할로 동작. zero-copy 브로커와 조합해도 통과했고(copy·zero-copy 각 2회), 브로커 p50이 30–35 µs, p99가 50–60 µs 줄었다 |

## 진행 기록

### S0 — 2026-09-24

- 컨테이너 생성과 검증은 `scripts/cuda/spark/README.md`.
- 레포: `git bundle`로 `/workspace/ocudu-cuda-rebuild`, HEAD `a247906`(= 워크스테이션 `cuda-rebuild`). J·S 트랙 미커밋 파일은 tar로 복사.
- 벤더 소스: `/workspace/ocudu-spark/src/ocudu-cuda` @ `5830c9cb`, `git status --porcelain` 0줄.
- `scripts/cuda/jetson/j1-build-and-validate.sh`를 `CUDA_ARCH`·`PLATFORM_ROOT`·`STAGE` 환경변수로 받게 바꿨다(기본값은 Jetson 값 그대로). Spark 실행: `CUDA_ARCH=121 PLATFORM_ROOT=/workspace/ocudu-spark STAGE=s1 J1_BUILD_JOBS=16`.

### S1 — 2026-09-24

**첫 시도(09:55, `s1-20260924T095544Z`) configure 실패 — 스크립트 쪽 설정 누락.** `CMake Error at lib/phy/upper/channel_coding/CMakeLists.txt:49: GNU does not support +crypto feature.` 원인 사슬:
1. GCC 13.3은 Cortex-X925/A725를 모른다 → OCUDU 기본 `MCPU=native`의 `-mcpu=native`가 crypto 없는 generic ARMv8로 떨어져 `HAVE_ARM_CRYPTO` 실패(PMULL `vmull_p64` 인라인 실패로 직접 확인).
2. 대안 1 `-mcpu=native+crypto`는 GCC가 거부한다(`unknown value 'native+crypto'`).
3. 대안 2 `-march=armv8-a+crypto`는 실제로 컴파일되지만(직접 확인), CMake가 **같은 캐시 변수 `HAVE_PLUS_CRYPTO`로 다시 검사**하므로 첫 실패 결과가 재사용되어 검사 자체가 돌지 않는다 → FATAL. OCUDU CMake의 잠재 결함(WG 추가분이 아니라 `66ee7ce702 phy: fix +crypto extension` 계열 코드).
4. **WG 문서가 이미 답을 적어 두었다**(`docs/phy_cuda_acceleration.md` 41–47, 155–184): DGX Spark 측정은 `-DMCPU=neoverse-v2`로 했다. 이 값이면 `-mcpu=neoverse-v2+crypto` 검사가 통과한다(직접 확인). C·J 트랙은 x86_64 / Orin(A78AE, GCC가 앎)이라 이 옵션이 필요 없었고, 스크립트가 그 configure를 그대로 옮겨 온 것이 누락의 원인이다.
- GCC 14.2(`g++-14`)로도 `-mcpu=native`에 crypto가 켜지지 않음을 확인했다. 진단용으로 컨테이너에 설치했다가 지웠다(툴체인은 이미지와 같은 GCC 13.3).
- 스크립트: `EXTRA_CMAKE_ARGS`(기본 빈 값)를 추가하고 캐시 기록에 `MCPU`를 넣었다. 실패한 빌드 폴더는 캐시된 검사 결과 때문에 지우고 다시 configure 했다.

**재시작(10:27, `s1-20260924T102751Z`):** `EXTRA_CMAKE_ARGS=-DMCPU=neoverse-v2`. CMake 캐시가 WG 문서의 "Expected DGX Spark values"와 **정확히 일치**: `CMAKE_BUILD_TYPE=Release`, `CMAKE_CUDA_ARCHITECTURES=121`, `ENABLE_CUDA=ON`, `MCPU=neoverse-v2`. 빌드 **2분 58초**(gNB 10:27:57 → 테스트 타깃 10:30:55, `-j16`). gNB `--help`에 `GPU acceleration:` 있음. PHY 12개, OFH 16개 등록.

#### S1 결과 — WG 기준 플랫폼에서도 벤더 자체 검증은 **PHY 9/12**

| # | 테스트 | Spark (GB10) | 5090 C0 | Orin J1 |
|---|---|---|---|---|
| 1 | `ofdm_demodulator_cuda_test` | Passed 5.8 s | Passed | Aborted (D6) |
| 2 | `ofdm_prach_demodulator_cuda_test` | Passed 60.9 s | Passed | Aborted (D6) |
| 3–6 | pdxch / LDPC enc / LDPC dec / PRACH det | Passed | Passed | Passed |
| 7 | `pusch_gpu_cpu_comparison_test` | Passed **237.9 s** | Passed 875.5 s | Passed 3450 s(오염) |
| 8 | `pdsch_gpu_e2e_test` | **Failed** — `:746` `compress_device_symbol()` false | Failed, 같은 지점 (D2) | SegFault (D6) |
| 9–10 | pusch_e2e_pipeline / resident_dematch | Passed | Passed | Passed |
| 11–12 | `srs_estimator_gpu_{latency,sensitivity}_baseline_4x4_n4` | **Aborted** — RX 포트 수 assertion | Aborted, 같은 assertion (D1) | Aborted |

**PHY 9/12, `Total Test time 319.55 s`. OFH 16/16(6.3 s). 로그 판정기 `fail`.** WG 문서(`docs/phy_cuda_acceleration.md:526-527`)의 "12/12, 252.53 s"와 다르다. 7번 하나가 237.9 s로 WG 전체 252.53 s와 같은 규모이므로 **시간은 문서와 맞고, 결과만 다르다.** (측정 중 다른 컨테이너의 GPU 사용 여부는 시작 시점에만 확인했다.)

**실패 3건은 5090과 정확히 같은 테스트·같은 지점이다 → C 트랙의 D1·D2는 "디스크리트 GPU 결함"이 아니라 이 커밋의 벤더 결함이다.** 제보서(이슈 #2)는 둘을 디스크리트 하드웨어에 묶어 설명했으므로 정정이 필요하다.

- **SRS (D1).** ctest 등록 명령이 `-R 1 -W 0 -P baseline_4x4_n4 -G host`이다. `-G host`(staged host grid)로 직접 실행하면 GB10에서도 rc 134, `-G visible`로 실행하면 통과한다(`matrix_rel_error=3.98e-7`, 이 1회 설정에서 GPU 0.375×). 즉 **벤더가 등록한 테스트 자체가 벤더가 제거한 경로를 부른다** — 5090 C0의 메커니즘(호스트/pinned 그리드가 snapshot API를 override하지 않음) 그대로이며 하드웨어와 무관하다. (첫 직접 실행에서 ctest 명령의 따옴표를 그대로 넘겨 인자가 무시되고 기본값 `visible`로 돌아 "통과"로 보였다 — 판정에서 제외.)
- **PDSCH (D2).** `pdsch_gpu_e2e_test.cpp:746`, `transmission=0 port=0 symbol=0`에서 `compress_device_symbol()` false — 5090과 같은 줄·같은 인덱스. GB10은 `DirectManagedMemAccessFromHost=0`이므로 `host_reads_device_memory_directly`가 거짓이고, 테스트가 CPU 비교로 managed 그리드를 호스트로 옮긴 뒤에는 `prepare_device_access()`가 정당하게 거부한다. OFH 압축 호출자에 벤더 주석이 약속한 host-copy 폴백이 없다는 C0 분석이 GB10에도 그대로 적용된다.

**언제 깨졌나 (커밋 날짜로 본 정황, 실행으로 확인한 것은 아님):**
- WG 문서의 검증 블록(526–539행) 마지막 수정: `522e867471` **2026-07-29**.
- 문서가 측정 커밋으로 적은 `9fd4047b43`(2026-06-02)은 `5830c9cb`의 조상이 **아니다**(`git merge-base --is-ancestor` rc 1) — 다른 이력선의 커밋이다.
- SRS의 managed 전용 snapshot 요구를 넣은 `35b27de4d6` "phy: keep host access off live CUDA-visible managed grids"는 **2026-08-27**(주석이 GB10 Xid 31을 이유로 든 바로 그 변경), residency 추적을 바꾼 `f4adba91b5`는 08-10, 핀 `5830c9cb`는 08-30.
- → "12/12"는 이 변경들 **이전**에 측정된 결과이고, 이후 재검증되지 않은 것으로 보인다. 확정하려면 `35b27de4d6^`에서 SRS 테스트를 돌려 보면 된다(S1 후속, 미실행).

#### 최신 WG1 코드에서는 해결됐나 — 2026-09-24

**아니다. 최신 `nvcuda_accel_02` HEAD `900d8d0e`(09-23)도 Spark에서 PHY 9/12, 같은 3건, 같은 지점.**

WG1 저장소 전체 브랜치를 받아 확인했다(`git fetch origin '+refs/heads/*:refs/remotes/origin/*'`).

| 브랜치 | 최신 | 내용 | D1·D2·D6 코드 포함 |
|---|---|---|---|
| `nvcuda_accel_02` | `900d8d0e` 09-23 | 핀 이후 4커밋: PRACH VkFFT 커널 디스크 캐시·plan 빌드를 슬롯 경로 밖으로·테스트·포맷 | 예 — 단 해당 파일 변경은 **공백 정렬 2파일뿐**(`phy_acceleration_runtime_options.h`, `srs_estimator_cuda_impl.cpp`) |
| `nvcuda_mr3_grid` | `40f3508f` 09-21 | OCUDU `main`(`f0642cf2`, 07-09) 위에 CUDA-visible 그리드·PRACH 버퍼를 **새로 쓴** 업스트림 MR 조각 | SRS 추정기·OFH 압축·PDSCH 통합·해당 테스트 **없음** |
| `nvcuda_mr6_ldpc_decoder`, `mr4_dlkernels`, `mr_uci_polar` | 08-25–09-23 | 커널 단위 MR 조각 | 없음 |

**실행 확인** (`s1head-20260924T110624Z`, 별도 체크아웃 `src/ocudu-cuda-head` @ `900d8d0e` 깨끗함, 같은 옵션 `MCPU=neoverse-v2`, gNB `ec8ee619…`, 시작 시 다른 GPU 프로세스 0): PHY **9/12** — `pdsch_gpu_e2e_test.cpp:746` 1건, SRS RX 포트 assertion 2건. OFH 16/16.

**부수 관찰 — 시간은 이제 WG 문서와 거의 같다:** `Total Test time 255.44 s`(WG 문서 252.53 s). 핀(319.55 s)과의 차이는 PRACH 복조 테스트가 60.9 s → 0.79 s로 줄어든 것 — 새 커밋의 VkFFT 커널 캐시 효과다. 즉 **WG 문서의 수치는 현재 코드의 속도와는 맞지만 통과 여부와는 맞지 않는다.**

**`mr3_grid`의 새 그리드 구현이 D6에 주는 것 (코드 읽기, 미실행):** `lib/cuda/adt/managed_vector.cpp`는 prefetch·advise가 `cudaErrorNotSupported`이면 `cudaGetLastError()`로 **오류를 지우고** 성공으로 본다 — D6 지점 3(남는 오류)의 패턴은 고쳐졌다. 팩토리는 `prefer_device_residency`의 기본을 `ConcurrentManagedAccess`로 정한다 — Orin(0)에서는 device 선호를 끈다. 그러나 여전히 `NotSupported`만 예외로 보므로 Orin이 반환하는 **`cudaErrorInvalidDevice`(101)는 오류로 남는다.** 이 구현이 `accel_02`에 들어오지 않았으므로 현재 벤더 브랜치의 D6은 그대로다. Orin에서 `mr3_grid` 단위 테스트를 돌려 보면 판정할 수 있다(미실행).

**결론:** WG1 최신 코드 어디에도 D1·D2(Spark·5090 공통)와 D6(Orin)의 수정은 없다. 업스트림 MR 조각은 문제가 되는 계층(SRS·OFH·PDSCH 통합)을 아직 올리지 않은 상태다. 이슈 #2의 C1 패치(`d2579af2`)가 여전히 유일한 수정이다 — 그것이 Spark에서 12/12를 만드는지가 S2다.

### S2 — C1 패치 적용: **PHY 14/14, OFH 16/16** (2026-09-24)

`scripts/cuda/spark/s2-patched-validate.sh`(신규: C1의 build+validate+negative-controls를 Spark용으로 합친 것), 증거 `/workspace/ocudu-spark/results/s2-20260924T112006Z/`. 패치 sha256 `d2579af2` 확인, 별도 체크아웃 `src/ocudu-cuda-c1`(벤더 트리 무수정), `MCPU=neoverse-v2`, 시작 시 다른 GPU 프로세스 0. 빌드 2분 47초.

- **PHY 14/14** (`phy_ctest_exit=0`, 261.25 s) — S1에서 실패한 `pdsch_gpu_e2e_test`, SRS 2건 모두 통과. 패치가 추가한 회귀 2건(`pusch_gpu_cpu_cfo_interpolation_test` 5.2 s, `pusch_gpu_cpu_sync_sinr_test` 4.1 s) 통과. `pusch_gpu_cpu_comparison_test` 240.4 s.
- **OFH 16/16**, 로그 판정기 `phy_log_verdict=pass`, 두 회귀 마커 출력 확인.
- **즉 WG 문서의 "12/12"는 현재 코드에서 C1 패치로만 재현된다.**

**음성 대조군 (결함 하나씩 되돌림 → 반드시 exit≠0, 그리고 되돌린 메커니즘이 로그에 있어야 함):**

| 대조군 | exit | 메커니즘 | 판정 |
|---|---|---|---|
| NC-D1 SRS host-grid staging 제거 | 8 | RX 포트 수 assertion | CONTROL OK |
| NC-D2 OFH host-copy 폴백·hold 해제 제거 | 8 | 아래 — 자동 판정은 `absent`로 찍혔고 수동으로 확인 | **CONTROL OK (수동 판정)** |
| NC-D3 PUSCH 시간보간 전달 제거 | 8 | `CFO regression CRC or payload mismatch` | CONTROL OK |
| NC-D4 동기 경로 SINR에 EVM 대입 | 8 | `Synchronous GPU post-equalization SINR disagrees with CPU` | CONTROL OK |

대조군 뒤 패치 복원 diff 해시 `85701847…`로 원래와 같음(`restored_diff_sha256`).

**NC-D2는 5090과 다른 절반으로 실패한다 — 그리고 그것이 GB10에서 새로 드러난 사실이다.** D2 수정은 두 부분이다: (a) live read가 거부되면 owned snapshot으로 폴백, (b) **어느 경로든 잡은 read hold를 해제**. 패치된 테스트는 `compare_resource_grids` **전에** live 경로 압축을 한 번 부른다(패치 주석: "Its read hold must be released or that host read hangs").
- GB10에서 D2를 되돌리면 그 live 압축은 **성공**한다(GPU 생산자 직후라 pages가 device-resident). 그런데 벤더 `iq_compression_cuda.cpp`는 `release_device_grid_reading()`을 **한 번도 호출하지 않는다**(grep 확인 — 같은 그리드의 다른 소비자 `pdxch_baseband_modulator_cuda.cpp:155`, `pusch_demodulator_gpu_impl.cpp:2013`은 호출한다). 남은 hold 때문에 이어지는 호스트 비교가 `wait_for_device_read_holds_locked`의 5 ms 한도를 넘겨 거부되고, GPU 그리드를 0으로 읽는다: `pdsch_gpu_e2e_test.cpp:741` `nof_mismatches=53424`, `gpu=(0,0)`.
- 판정 스크립트의 메커니즘 문구가 (a)의 증상(`compress_device_symbol` false)만 찾도록 되어 있어 `absent`로 찍혔다. (b)의 증상(`nof_mismatches`)도 인정하도록 고쳤다(재실행은 안 함 — 이 기록이 수동 판정의 근거).
- **라이브 의미:** 벤더 테스트 원본은 비교 **후에** 압축을 부르므로(pages가 이미 host로 옮겨져 live read가 거부됨) (b)에 닿지 않는다. 하지만 실제 OFH 하향 경로에서는 GPU PDSCH 직후 압축이 live read로 **성공**하고, 그 hold가 남으면 다음 슬롯의 CPU 쓰기(PDCCH·SSB)가 막힌다. 즉 **GB10 라이브 하향에서 hold 누수는 실제로 도달 가능한 결함**일 가능성이 높다 — S4에서 C1 패치 유무로 확인할 항목.

### S3 — 스택 빌드 (진행 중, 2026-09-24)

`scripts/cuda/spark/s3-build-stack.sh`(신규): 워크스테이션 lock과 같은 커밋·옵션으로 CPU OCUDU `a1916edc`, srsRAN_4G `eea87b1d`, Open5GS `d9d3abdd`(+ 서브프로젝트 4개를 lock 커밋으로 체크아웃, `--wrap-mode=nodownload`), MongoDB 6.0.29 aarch64(ubuntu2204 빌드, 공식 sha256 사이드카 OK, noble에서 `mongod --version` 실행 확인).

- **첫 시도 실패 — CPU OCUDU configure, 같은 `+crypto` 오류, 다른 원인.** `a1916edc`의 crypto 재시도는 `-march=${MARCH}+crypto`이고 `MARCH` 기본값이 `native`라 GCC가 `-march=native+crypto`를 거부한다(벤더 브랜치는 `66ee7ce702`에서 재시도를 `-mcpu`로 바꿨다). `-DMARCH=armv9-a`를 추가(neoverse-v2와 같은 ISA, `-mcpu=neoverse-v2 -march=armv9-a+crypto` 경고 0 확인). 캐시 때문에 빌드 폴더를 지우고 재시작(`s3-stack-20260924T120638Z`).
- **감시 스크립트 결함:** 모니터의 `pgrep -f <스크립트 이름>`이 ssh로 넘긴 감시 명령 자신과 매칭되어, 스크립트가 끝나도 "실행 중"으로 보였다. 첫 시도의 실패를 30분 늦게 발견한 원인. S1·S2 모니터도 같은 구조였으나 완료 표시로 먼저 끝나 드러나지 않았다. 이후 감시는 tmux 창의 종료 표시(`S3_EXIT=`)로 판정한다.

**라이브 러너 재사용 준비:** `run-ocudu-cuda-direct-zmq.sh`는 `OCUDU_NATIVE_ROOT` 아래 워크스테이션과 같은 폴더 구조(srsUE·5gc·mongod·add_users.py)를 쓰고, 격리는 `unshare --user --net --mount`다. 걸리는 두 가지:
1. CUDA gNB 선택기 `resolve-cuda-gnb.py`가 5090 lock(`sm_120`, `builds/c1-cuda-patched`)으로 검사 → `OCUDU_CUDA_WORKSPACE_LOCK` 환경변수로 다른 lock을 고를 수 있게 했다(미설정 시 기존과 같음). Spark lock `scripts/cuda/cuda-workspace.spark.lock.json`(소스 `src/ocudu-cuda-c1`, 빌드 `builds/s2-cuda-patched-sm121`, arch 121).
2. `scripts/native/env.sh`가 x86 sysroot·gnutls·bison 폴더의 존재를 검사 → Spark는 의존성이 시스템 apt에 있으므로 빈 폴더(README 포함)로 두었다.

### S3 — 라이브 직결 ZMQ: **`disabled`·`all` 모두 attach/PDU/ping 통과** (2026-09-24)

실행기 `scripts/cuda/spark/live-direct-zmq.sh <stage> [traffic_s]` → 워크스테이션 러너 `run-ocudu-cuda-direct-zmq.sh`(무수정) + Spark lock. gNB = S2의 패치 빌드(`builds/s2-cuda-patched-sm121`, C1 `d2579af2`).

**첫 통과까지 막힌 것 (순서대로):**
1. 선택기가 lock 대조에서 거부 — 패치 diff의 `index` 해시가 10자리(WG1 브랜치 전부를 받은 복제본이라 git 자동 약어가 길어짐)라 7자리 패치 파일과 바이트 불일치, 그리고 gNB 빌드 해시도 10자리(`5830c9cb78`)라 버전 정규식 불일치. `resolve-cuda-gnb.py`가 `core.abbrev=7`로 비교하고 해시 접두어를 받도록 고쳤다(워크스테이션 트리에서도 패치 비교 통과 확인).
2. `unshare: write failed /proc/self/uid_map` — 이 Ubuntu 24.04 호스트는 비특권 사용자의 user namespace를 막는다. 워크스테이션은 `docker exec`(root)로 돌렸다. → 컨테이너 root(sudo)로 실행.
3. `add_users.py`에 `python3-click` 없음 → 설치, `ocudu/Dockerfile`에 추가.
4. srsUE `RF device 'zmq' not found` — `srsue` 타깃만 빌드해 ZMQ 플러그인 `libsrsran_rf_zmq.so`가 없었다 → srsRAN_4G 전체 빌드(`s3-build-stack.sh` 수정).
5. srsUE가 `Waiting PHY to initialize`에서 60 s 안에 못 나옴 — FFTW wisdom이 없으면 GB10에서 **첫 PHY 초기화 260 s**(wisdom 있으면 2 s, 단독 실행으로 측정). 그런데 wisdom을 만들어도 러너 안에서는 안 읽혔다: `sudo -E`로 `HOME=/home/dev`가 유지되는데, user namespace 안의 root에게 dev(미매핑 uid) 소유의 `750` 홈은 **통과 불가**라 `fopen(r+)`가 조용히 실패한다(`nsenter`로 네임스페이스 안에서 `statx: Permission denied` 확인). → `HOME=/root`로 실행(`/root/.srsran_fftwisdom` 사용).
6. (운영 실수) 정리 명령의 `pkill -f <러너 이름>`이 그 명령을 실은 ssh 세션 자신과 매칭되어 세션이 끊겼다 — 모니터의 `pgrep -f` 문제와 같은 부류. 이후 정리는 `pkill -x <정확한 프로세스 이름>`만 쓴다.

**결과 (다른 GPU 프로세스 0에서 시작):**

| 런 | stage | 트래픽 | 결과 | keepalive | PUSCH | BLER | SINR p50 |
|---|---|---|---|---:|---:|---:|---:|
| `direct-zmq-20260924T122719Z` | disabled | 20 s | passed | 100 | 429 | 0.47% | 5.2 dB |
| `direct-zmq-20260924T122842Z` | **all** | 60 s | **passed** | 299 | 1238 | **1.29%** | 4.8 dB |
| `direct-zmq-20260924T123020Z` | disabled | 60 s | passed | 299 | 1229 | 0.49% | 5.2 dB |

`all` 런의 백엔드 판정(`verify-stage-backends.py`): **selected 7**(low-phy-rx, low-phy-tx, prach, PDSCH, PRACH, PUSCH, SRS), degraded 0, host_fallback 0, verdict OK. 매니페스트 4종 모두 `backend=CUDA`, UL/DL 그리드 `requested=managed`, `PDSCH CUDA synchronous executor selected for sequential PHY.`(= D5 수정이 라이브에서 동작; NC-D5 자체는 아직 안 돌림). gNB 기동 6 s(5090은 20–24 s).

**예상과 달랐던 것 1 — lower-PHY TX direct 경로가 GB10에서 탄다.** 로그에 `Lower-PHY TX GPU path selected: direct CUDA-visible downlink resource-grid reader.`와 `... host resource-grid staging fallback.`이 **둘 다** 찍혔다(각각 one-shot 래치라 최소 한 번씩). 5090에서는 direct가 한 번도 없었다. C4 추적의 결론("`fully_coherent` 불만족이면 direct는 GH200급에서만")은 **GB10에는 맞지 않는다** — `pages_device_resident`가 참으로 남는 슬롯(GPU PDSCH 뒤 호스트 쓰기가 없는 슬롯으로 추정)에서는 GB10도 direct로 읽는다. 비율은 로그로 알 수 없다(래치). 업스트림 초안의 해당 서술을 고쳤다.

**예상과 달랐던 것 2 — 이슈 6이 GB10에서도 재현된다.** 16QAM/TBS 528 할당의 CRC 실패율:

| | disabled 60 s | all 60 s |
|---|---|---|
| 16QAM tbs=528 | 6 / 482 = **1.24%** | 16 / 218 = **7.34%** |
| 그 외 할당 | 0 | 0 |

링크 적응이 QPSK로 물러나는 모양(16QAM tbs 528이 482 → 218건, QPSK tbs 528이 399건 등장)까지 5090 직결 관찰(host 0.6–1.6% → 가속 6–10%)과 같다. **이슈 6은 디스크리트 고유가 아니라 PUSCH 가속 경로의 성질**로 보인다. 단 Spark는 한 쌍(각 1회)뿐이다 — 5090처럼 반복 필요.

#### 반복 런 — 2026-09-24 (각 60 s, 시작 시 다른 GPU 프로세스 0)

| 런 | stage | 결과 | PUSCH | BLER | 16QAM tbs=528 CRC 실패 |
|---|---|---|---:|---:|---|
| `…122720Z` | disabled (20 s) | passed | 429 | 0.47% | 2 / 159 = 1.26% |
| `…123020Z` | disabled | passed | 1229 | 0.49% | 6 / 482 = 1.24% |
| `…123910Z` | disabled | passed | 1226 | 0.33% | 4 / 446 = 0.90% |
| `…122842Z` | all | passed | 1238 | 1.29% | 16 / 218 = 7.34% |
| `…124024Z` | all | passed | 1245 | 1.77% | 21 / 201 = 10.45% |
| `…124143Z` | all | passed | 1240 | 1.53% | 19 / 208 = 9.13% |

**S3 CUDA gNB 게이트: `disabled` 3/3, `all` 3/3.** 이슈 6은 세 번 모두 재현: 16QAM tbs=528 실패율 disabled 0.9–1.3% vs all 7.3–10.5%, 16QAM 표본이 ~450 → ~210으로 줄어드는 링크 적응 후퇴도 매번 같다. 5090 직결(0.6–1.6% → 6–10%)과 같은 범위.

### NC-D5 — 2026-09-24

`scripts/cuda/spark/s3-nc-d5.sh`(신규): 5090의 `d5-negative-control.sh`와 같은 편집(대입만 끄고 선언은 남김)으로 gNB를 재빌드하고, 통과한 `all` 런의 렌더 설정(`direct-zmq-20260924T124143Z/configs/gnb.yaml`, `pdsch_acceleration_mode: enabled` 확인)으로 gNB를 **직접** 기동한다. 러너는 쓸 수 없다 — 선택기가 lock과 다른 소스를 거부하는데, 대조군은 일부러 그렇게 만들기 때문이다(5090 NC-D5가 한 번 무효였던 이유와 같다). D5는 상위 PHY 구성 중 발현하므로 코어·UE가 필요 없다.

결과: **exit 134, 콘솔에 `OCUDU FATAL ERROR: Accelerated PDSCH block processor requested but no block-processor capable PDSCH configuration is active` → CONTROL OK.** 복원 후 diff가 lock 패치와 일치(`restored_diff_matches_lock=yes`), gNB 재빌드. 증거 `results/s3-nc-d5-20260924T130840Z/`. → **Spark에서 NC-D1–D5 전부 완료.**

### 이슈 6 위치 좁히기 — 2026-09-24

**라이브 스위치 실험** (`pusch` stage, 각 60 s, `live-direct-zmq.sh`가 진단용 `OCUDU_*` 변수를 넘기고 콘솔 첫 줄에 기록; 로그로 적용 확인):

| arm | 설정 | 16QAM tbs=528 CRC 실패 | BLER |
|---|---|---|---|
| E0 | 기본 | 16/193 = 8.29% | 1.29% |
| E1 | `OCUDU_NOISE_MODE=cv`(이전 잡음 추정) | 20/22 = 90.9% — **링크 붕괴(result=failed)** | 86% |
| E2 | `OCUDU_LDPC_BOXPLUS_ITERS=12` | 16/215 = 7.44% | 1.29% |
| E3 | `OCUDU_LDPC_BOXPLUS=0`(min-sum) | 21/180 = 11.67% | 1.69% |

- 디코더 아님: 반복 2배(E2)로 변화 없음, min-sum(E3)은 예상대로 약간 나쁨. 우리 할당은 코드블록 1개라 `auto`는 이미 boxplus(`nof_cbs < 192`).
- 반복 한도(6)·보간(`interpolate`, CPU·GPU 기본 동일)도 CPU와 같다.
- 이전 잡음 추정 모드는 이 링크에서 동작하지 않는다(해결책 아님, 민감도만 확인).

**오프라인 재현 — 같은 IQ를 CPU·GPU에 (`pusch_gpu_cpu_comparison_test -L -R 400 -P 15 -N 1 -S 3,4,5,6,7`, `-L` = 16QAM MCS 10·interpolate·MMSE·CFO 400 Hz):**

| SINR | CPU BLER | GPU BLER | EVM CPU → GPU |
|---|---|---|---|
| 3 dB | 100% | 100% | 64.0 → 65.4% |
| 4 dB | 100% | 100% | 58.3 → 59.6% |
| **5 dB** | **74.0%** | **88.5%** | 53.9 → 55.0% |
| **6 dB** | **0.2%** | **1.2%** | 50.1 → 50.9% |
| 7 dB | 0% | 0% | 47.0 → 47.6% |

증거 `results/issue6-offline-L.log`.

**판정:** 이슈 6은 라이브 링크·스케줄러가 아니라 **GPU PUSCH 경로의 디코딩 이전 단계**에 있다. GPU의 등화 후 EVM이 모든 SINR에서 CPU보다 0.6–1.5%p 높고, 그 차이는 SINR이 낮을수록 크다 — 추정 잡음에 비례하는 모양으로, **GPU 채널 추정의 잡음 억제(평활)가 CPU보다 약한 것**과 들어맞는다(추정, 커널 수준 미확인). 16QAM 폭포 구간에서 약 0.2–0.3 dB 손실에 해당하고, 가파른 폭포 때문에 6 dB에서 BLER이 6배가 된다 — 라이브의 1% 대 7–10%와 같은 크기.

**벤더 테스트가 못 보는 이유:** 기본 구성이 QPSK(MCS 0)·ZF·반복 10이라 폭포에 닿지 않고, 5 dB에서 BLER +14.5%p 차이도 `[WARN]`으로만 찍히고 통과한다.

다음(미실행): 채널 추정 단계 분리 — GPU 추정 채널 계수를 CPU 추정기와 같은 입력으로 비교, 또는 GPU 채널 추정만 CPU 결과로 대체하는 실험.

### 이슈 6 — 정정: 합산 지표는 할당 구성에 교란되어 있었다 (2026-09-24)

**앞 절들의 "16QAM tbs=528 실패율 1% vs 7–10%"는 교란된 지표다.** 그 수치는 모든 rv와 여러 PRB 할당을 합친 것이고, 가속 여부에 따라 **할당 구성 자체가 달라진다.** 가속 끔에서는 링크 적응이 더 강한 `16QAM [0,19)`(실패 0)를 많이 써서 비율이 희석되고, 가속 켬에서는 그 대신 QPSK로 가서 16QAM 표본이 약한 `[0,17)`에 몰린다.

**같은 할당·첫 전송(rv=0)만 비교** (라이브 5런):

| 할당 | 가속 끔 (2런) | 가속 켬 (3런) |
|---|---|---|
| 16QAM `[0,17)` tbs 528 CRC 실패 | 10 / 429 = 2.3% | 21 / 564 = 3.7% — 차이 작고 표본 대비 유의하지 않음 |

**같은 할당의 보고 SINR** — GPU가 일관되게 낮다:

| 할당 | 끔 평균 | 켬 평균 | 차 |
|---|---|---|---|
| 16QAM `[0,17)` | 4.91 | 4.83 | −0.08 dB |
| QPSK `[0,24)` | 4.59 | 4.50 | −0.09 dB |
| QPSK `[1,6)` (5 PRB) | 6.31 | 5.82 | **−0.49 dB** |
| QPSK `[0,1)` (1 PRB) | p50 8.5, sd 1.5 | p50 10.0, sd 2.8 | 분산 2배 |

**수정된 판정:**
1. 라이브에서 CPU·GPU의 차이는 첫 전송 CRC가 아니라 **보고 SINR**(좁은 할당일수록 큼)과 그로 인한 **링크 적응 경로의 차이**다. GPU FD 평활은 `cfg.nof_prb > 1`일 때만 돈다(`pusch_e2e_api.cu` Phase 1b) — 1 PRB 할당에서 GPU 추정이 평활되지 않는 것과 1 PRB SINR 분산 2배가 들어맞는다(인과 미확인).
2. 오프라인의 GPU 열세(`-L`, 5 dB BLER +14.5%p, EVM +0.6–1.5%p)는 **CFO 400 Hz가 있을 때만** 나타난다. 진단 복사본(`src/ocudu-cuda-diag`, `OCUDU_DIAG_CFO_HZ=0`)으로 CFO를 0으로 두면 CPU·GPU EVM이 **동일**(38.4/38.4%, 35.3/35.3%)하고 BLER도 같다. 둘 다 `compensate_cfo=false`(`td=interpolate`)인 조건에서 GPU가 보상 없는 위상 회전을 덜 따라간다 — 실재하는 차이이지만 CFO≈0인 ZMQ 라이브와는 **다른 현상**이다.
3. 같은 진단으로 배제한 것: FD 평활 커널의 in-place 레이스(스냅샷에서 읽게 바꿔도 변화 없음), FD 평활 자체(양쪽 끄면 차이가 오히려 커짐 — CFO 400 Hz 조건), LDPC 반복·알고리즘(라이브 E2/E3).
4. 5090 원 제보서의 같은 관찰도 같은 교란을 담고 있을 가능성이 높다(재분석 안 함).

진단 복사본 편집(환경변수 게이트, C1 패치 커밋 위): GPU FD 평활 `off|oop`, CPU FD `none`, 테스트 CFO 덮어쓰기. 결과 `results/issue6-diag-20260924T133312Z/`.

### "12/12"는 `35b27de4d6`에서 깨졌다 — 확정 (2026-09-24)

같은 Spark·같은 옵션(`MCPU=neoverse-v2`, 패치 없음)으로 두 커밋에서 벤더 검증을 돌렸다(`j1-build-and-validate.sh`, `SRC_DIR`/`EXPECT_COMMIT` 지정, 별도 체크아웃 `src/ocudu-cuda-bisect`):

| 커밋 | PHY | 실패 | 시간 | 증거 |
|---|---|---|---|---|
| `ca91f27e73` (2026-08-16, `35b27de4d6`의 부모, 핀의 조상) | **12/12**, OFH 16/16, 로그 판정 pass | — | 249.57 s | `results/s1pre35b-*` |
| `35b27de4d6` "phy: keep host access off live CUDA-visible managed grids" | **9/12** | `pdsch_gpu_e2e_test`, SRS 2건 (S1과 같은 3건) | 256.91 s | `results/s1at35b-*` |

WG 문서의 "12/12, 252.53 s"는 이 커밋 **이전** 상태와 정확히 맞는다(12/12, 249.57 s). 이 한 커밋(13파일 +961/−164: SRS 추정기에 owned-snapshot 요구, managed 그리드 host 접근 규칙, `owned_grid_snapshot_copy.cu` 등)이 D1(SRS host-grid 경로)과 D2(OFH 압축 폴백)를 함께 들여왔고, 이후 검증 블록이 갱신되지 않았다.

### S4 — 단계별 사다리 (2026-09-24, 각 60 s, 시작 시 다른 GPU 프로세스 0)

`scripts/cuda/spark/s4-ladder.sh`(신규). 5090 C4와 같은 누적 순서.

| stage | 결과 | gNB 기동 | PUSCH | BLER | SINR p50 | selected | degraded | TX 경로 |
|---|---|---|---:|---:|---:|---|---|---|
| low-phy-rx | passed | 1 s | 1224 | 0.25% | 5.15 | low-phy-rx | — | — |
| low-phy-tx | passed | 1 s | 1224 | 0.25% | 5.2 | low-phy-rx | **low-phy-tx** | staging |
| pusch | passed | 5 s | 1241 | 1.45% | 4.8 | +PUSCH | **low-phy-tx** | staging |
| pdsch | passed | 5 s | 1238 | 1.29% | 4.8 | +low-phy-tx, PDSCH | — | **direct**, staging |
| prach | passed | 5 s | 1240 | 1.45% | 4.8 | +prach, PRACH | — | **direct**, staging |

(`all` = 위 + SRS, S3에서 3/3.) **host fallback은 전 단계 0.**

**lower-PHY TX direct 경로는 GPU PDSCH가 켜진 단계부터만 나타난다.** `low-phy-tx`·`pusch` 단계에서는 DL 그리드를 CPU만 쓰므로 device-resident가 될 일이 없어 staging뿐(DEGRADED), `pdsch`부터 GPU가 그리드를 쓴 슬롯에서 direct가 잡힌다. 5090에서는 `pdsch`·`all`에서도 direct가 없었다(C4) — GB10에서 차이가 나는 조건이 "GPU 생산자 직후, 호스트 쓰기 전"이라는 해석과 맞는다. 비율은 one-shot 래치라 알 수 없다.

SINR p50이 5.15–5.2 → 4.8 dB, BLER 0.25 → 1.3–1.5%로 바뀌는 지점은 **PUSCH 가속을 켜는 단계**다 — 이슈 6 정정(보고 SINR 차이 → 링크 적응 경로 차이)과 일치.

### S6 — 벤더 스윕으로 성능 측정 (2026-09-24)

도구: 벤더 `scripts/cuda_accel/run_type1_dmrs_ul_dl_gpu_cpu_sweeps.sh`를 **WG 문서의 옵션 그대로**(`--quick --mcs 20 --pusch-snr-step 1.0 --pusch-frames 100 --rx-device-grid managed --resource-grid-memory managed --device-grid-memory managed`). 빌드는 S2의 C1 패치 빌드(`builds/s2-cuda-patched-sm121`, `MCPU=neoverse-v2`). 호스트 CPU governor는 20코어 모두 이미 `performance`(문서의 튜닝 스크립트가 하는 일). 시작 시 다른 GPU 프로세스 0. 성능 라벨: DGX Spark GB10 / 드라이버 580.178.04 / CUDA 13.0.88 / 벤치마크 프로그램(라이브 아님) / C1 패치 빌드 / 2026-09-24.

**100 MHz, 273 PRB, 4 layer** (`s6-100mhz-4l-20260924T141353Z`, 지연 반복 10 — 문서와 같음):

| | 문서(GB10, `9fd4047b43`) | 측정 |
|---|---|---|
| PUSCH 감도 10% BLER, 8 RX | CPU 13.1 / GPU 13.0 dB (−0.1) | CPU 13.2 / GPU 13.0 dB (−0.2) |
| PUSCH 지연 평균, 8 RX | 13122.3 / 618.9 µs = 21.20× | 13366.5 / **333.9** µs = **40.03×**, mismatch 0 |
| PDSCH 지연 p50, 4 포트 | 625.0 / 186.0 µs = 3.36× | 581.8 / 171.2 µs = 3.40× (GPU grid `direct`) |

**20 MHz급 1 layer** (`s6-20mhz-1l-20260924T141450Z`, 지연 반복 100; 스크립트는 30 kHz를 가정해 106 PRB를 "40MHz"로 표기 — 라이브 설정은 15 kHz·106 PRB):

| | 문서 | 51 PRB | 106 PRB |
|---|---|---|---|
| PUSCH 감도 CPU/GPU | — | 12.2 / 12.2 dB | 12.1 / 12.1 dB |
| PUSCH 지연 CPU/GPU | 225.8 / 262.3 µs = 0.86× | 401.1 / 172.9 µs = **2.32×** | 495.4 / 166.8 µs = 2.97× |
| PDSCH 지연 p50 CPU/GPU | 29.4 / 79.9 µs = 0.37× | 27.2 / 82.9 µs = 0.33× | 55.1 / 73.8 µs = 0.75× |

**해석:**
- 정확도: 모든 구성에서 GPU 감도가 CPU와 같거나 0.2 dB 이내로 낫다.
- 100 MHz 4L: 문서 수치를 재현하고, PUSCH GPU 지연은 문서의 절반. 문서 측정 커밋(`9fd4047b43`)이 핀의 조상이 아니라 다른 이력선이므로 이후 최적화 차이로 추정(미확인). 반복 10회라 분포는 없다.
- 20 MHz 1L PDSCH: 문서와 같게 GPU가 느리다(0.33×) — 작은 부하에서 GPU 실행 비용이 상쇄되지 않는다는 문서 설명 그대로.
- 20 MHz 1L PUSCH: **문서와 반대로 GPU가 2.3× 빠르다** — *09-25 정정: CPU 미고정의 착시, 빅 코어 고정 시 1.1× (아래 "S6 정정")*. 차이는 CPU 쪽(문서 225.8 µs vs 측정 401.1 µs)이다. 100 MHz CPU는 문서와 2% 이내이므로, 문서의 20 MHz 수치가 다른 조건(MCS·반복·구성)에서 나왔을 가능성이 높다 — 문서에 명령이 없어 확인 불가. **원인 미상으로 기록.**
- 이것은 벤치마크 프로그램의 처리 지연이다. 라이브 gNB 측정은 아래 "라이브 PUSCH 처리 시간"(09-25)에 있고, 20 MHz 1L 라이브에서는 GPU가 더 느리다.

### S3 마무리 — CPU gNB 라이브 기준선 (2026-09-25)

러너 확장: `run-ocudu-cuda-direct-zmq.sh`에 `cpu` stage를 추가했다. `cpu` stage는 가속 블록 없이 렌더링하고(렌더러에 stage를 비워 주면 평이한 렌더와 바이트 단위로 같다), gNB는 lock의 새 `cpu_baseline` 항목(`src/ocudu` @ `a1916edc`, `builds/ocudu-zmq-release`)에서 고른다. 이 gNB는 `resolve-cuda-gnb.py --cpu-baseline`으로 감사한다: 커밋, 트리 무수정, `ENABLE_CUDA`≠ON, ZMQ, 버전 문자열. 백엔드 판정은 `not_applicable`이다. 5090 lock에는 `cpu_baseline`이 없으므로 거기서 `cpu`를 고르면 크게 실패한다.

결과: CPU gNB 직결 ZMQ **4/4 통과**(단독 1회 + S5 배치 3회). attach/PDU/ping, keepalive 299/299, gNB 기동 1 s.

### S5 — CPU gNB 대비 BLER/SINR (2026-09-25, `results/s5-arms-20260925T033304Z`)

`scripts/cuda/spark/s5-arms.sh 3 60`: `cpu` → `disabled` → `all` 순서를 3회 번갈아 돌렸다(각 60 s, 매 런 시작 시 다른 GPU 프로세스 0). 9/9 통과. 판정기는 `s5-compare-arms.py`다. 이슈 6의 교훈대로 첫 전송을 할당(mod, PRB, TBS)이 같은 것끼리 비교하고, 양쪽 모두 30회 이상 나온 할당만 쓴다. 가중치는 두 조건 중 작은 쪽 횟수다.

**정정(09-25 같은 날):** 이 설정에서는 **재전송도 rv=0으로 나간다**(스케줄러 로그 `newtx=false rv=0`). 그래서 처음 판정기의 "rv=0 = 첫 전송"은 틀렸다. 판정기는 이제 같은 슬롯·HARQ의 스케줄러 결정 줄에서 `newtx=true`를 읽는다(매칭 누락 0). 다시 판정한 결과는 아래 수치이고, 결론은 같다(`disabled` +0.07%p/−0.03 dB, `all` +0.20%p/−0.16 dB, PASS). 증거는 `compare-newtx.txt`에 있다.

| 조건 | 전송 | CRC 실패 | 합산 BLER | 평균 SINR | PHY `t` p50/p99/max |
|---|---|---|---|---|---|
| `cpu` (a1916edc) | 3672 | 9 | 0.25% | 5.83 dB | 91 / 295 / 573 µs |
| `disabled` (CUDA gNB, 가속 끔) | 3676 | 11 | 0.30% | 5.81 dB | 92 / 299 / 592 µs |
| `all` | 3721 | 56 | **1.51%** | 5.49 dB | 195 / 503 / 1029 µs |

할당 일치 판정(기준 BLER ≤1%p, SINR ≤0.5 dB):
- `disabled` vs `cpu`: ΔBLER +0.07%p, ΔSINR −0.03 dB, 일치 신규 전송 3363 → **PASS**. 벤더 트리의 CPU 경로는 CPU OCUDU와 구별되지 않는다.
- `all` vs `cpu`: ΔBLER +0.20%p, ΔSINR −0.16 dB, 일치 신규 전송 761 → **PASS**. 16QAM `[0,17)`은 1.40% vs 1.69%다. 할당별로 보면 QPSK `[1,6)`의 ΔSINR이 −0.53 dB로 기준을 넘는다(09-24에 본 좁은 할당의 SINR 저하와 같다).

**합산 BLER이 6배인 이유**: `all`의 CRC 실패 56건 중 47건이 CPU가 한 번도 고르지 않은 할당에서 났다. 16QAM `[0,15)` tbs 528은 **신규 전송 13건이 13건 모두 실패**했다(PHY 로그의 47건은 신규 13건 + 같은 TB의 재전송 34건). 같은 TBS를 더 좁은 PRB에 실은, 부호율이 높은 할당이다. 인과는 아래 "D8"에서 확인했다. GPU가 1 PRB PUSCH의 SINR을 +2.4 dB 높게 보고하고, 스케줄러가 그 값으로 다음 TB의 MCS를 올린다.

→ S5 기준표로는 통과다. 하지만 "가속을 켜도 라이브 BLER이 같다"고 쓰면 틀린다. **합산 BLER이 0.25% → 1.5%로 오른다**고 써야 한다.

### 라이브 PUSCH 처리 시간 — `OCUDU_PUSCH_ACCELERATION_TIMING=1` (2026-09-25)

`all` 3런(각 60 s, 3/3 통과, BLER 1.37–1.53%로 타이밍을 켜지 않은 런과 같다). `PUSCH phase` 2745줄(GPU resident 경로), PHY `t` 3718줄. 20 MHz급 106 PRB, 1 layer, 15 kHz(슬롯 1 ms).

| 구간 | p50 | p99 | max |
|---|---|---|---|
| demod (호출) | 67.6 | 110.9 | 237.5 µs |
| decode (호출) | 161.4 | 423.4 | 926.1 µs |
| └ LDPC (CUDA event) | 113.8 | 336.0 | 866.4 µs |
| └ 완료 대기 | 92.9 | 312.8 | 487.8 µs |
| rate dematch / 설정 / D2H | 13.4 / 9.2 / 3.8 | 20.8 / 15.8 / 4.3 | µs |
| e2e (파이프라인) | 145.8 | 372.2 | 902.2 µs |
| **wall** | **245.3** | **519.3** | **1058.7 µs** |

- 비교: CPU gNB의 PHY `t`는 p50 91 / p99 295 µs다. **라이브 20 MHz 1L에서 GPU PUSCH는 CPU보다 2.2배 느리다.** 벤치마크(S6 20 MHz 1L, GPU 2.3× 빠름)와 방향이 반대다. 라이브 TB는 대부분 1 CB(tbs 11–528)라서, LDPC 커널 실행과 완료 대기가 지배한다.
- 실시간 여유: 1 ms를 넘은 것은 3718건 중 1건(1058.7 µs), 500 µs 초과는 77건이다. gNB 로그에 late/overflow/underflow는 0건이다(S5 `cpu`·`all` 런도 0건). gNB가 기한 초과를 보고하지 않았다. 단 **ZMQ 라디오는 실시간이 아니어서**(샘플 흐름이 처리 속도에 맞춰 늦춰진다) 이것으로 실시간 여유를 판정할 수는 없다(09-25 정정). 다만 p99 기준 처리 시간이 CPU의 1.8배다.
- 성능 라벨: DGX Spark GB10 / 580.178.04 / CUDA 13.0.88 / 라이브 직결 ZMQ / C1 패치 빌드 / 2026-09-25.

### D8 — GPU PUSCH가 1 PRB 할당의 SINR을 ~2.4 dB 높게 보고한다 (2026-09-25)

**라이브 인과** (`s5-la-trace.py`, S5 런 9개): 스케줄러가 새 528비트 TB의 폭(=MCS)을 정하는 시점에 가장 최근에 보고된 PUSCH SINR을 짝지었다. 결정 줄은 k2=4 슬롯 앞서 찍히므로, PHY 로그상의 직전 PUSCH가 아니라 결정 시점 기준으로 맞춰야 한다.

| 조건 | 선택 폭 | 신규 TB | 실패 | 결정 시점 최근 SINR (평균) | 그 SINR이 1 PRB PUSCH에서 온 비율 |
|---|---|---|---|---|---|
| `cpu` | 17 PRB | 641 | 9 | 8.42 dB | 611/641 |
| `all` | 17 PRB | 532 | 9 | 9.99 dB | 532/532 |
| `all` | **15 PRB** | 13 | **13** | **10.00 dB** | 13/13 |

1 PRB PUSCH의 보고 SINR은 결정론적 ZMQ 채널에서 두 값으로 양자화된다. CPU는 8.5 / 5.2 dB, GPU는 **10.0** / 4.3 dB다. 스케줄러 메트릭(`OCUDU_DIRECT_SCHED_METRICS_MS=100`, 러너에 새로 추가한 진단 노브)으로 보면, `all`의 UL OLLA는 평균 −0.54(CPU +0.23)로 끌려 내려가 있다. 그래서 대부분의 TB는 오히려 보수적인 MCS 8–10(QPSK 24/27 PRB)으로 나가고, 1 PRB 보고가 10 dB일 때만 MCS 12–14로 튀어 실패한다.

**오프라인 재현** (`pusch_e2e_pipeline_test`, 1 layer, MCS 4, 50회, CPU vs GPU CSI 비교표):

| PRB | 입력 5 dB | 입력 10 dB | 입력 20 dB |
|---|---|---|---|
| 1 | **+2.23** | **+2.48** | **+2.35** |
| 2 | −0.09 | −0.12 | −0.07 |
| 6 | −0.01 | −0.02 | −0.02 |
| 24 | −0.00 | −0.01 | −0.01 |

(GPU − CPU, dB. 복호는 모두 일치한다.)

**메커니즘:** `pusch_e2e_api.cu` Phase 1b의 FD 평활은 `if (cfg.nof_prb > 1)`일 때만 돈다. 그런데 바로 다음 Phase 2의 교차 검증 잡음 추정은 평활된 추정치를 전제로 맞춰져 있다. 진단 복사본으로 확인했다.
- `OCUDU_DIAG_GPU_FD=off`(모든 폭에서 평활 끔): **모든 폭이 +2.3~2.5 dB**가 된다.
- `OCUDU_DIAG_GPU_FD=all`(1 PRB도 평활, 진단 스위치 신설): 1 PRB가 **−0.11/−0.19/−0.18 dB**가 되고 EVM도 CPU와 같아진다.

평활 커널은 범위를 벗어나는 탭을 건너뛰고 다시 정규화하므로 1 PRB에서도 안전하다.

**수정은 두 단계였다.** 패치는 `scripts/cuda/patches/s-d8-c1-gpu-1prb-sinr.patch`(핀 대비 C1 + D8을 합친 diff)이고, lock은 `cuda-workspace.spark-d8.lock.json`이다. 검증 도구는 두 가지다.
- `s-d8-validate.sh`: PHY 14 + OFH 회귀, 1/2 PRB SINR 비교, S2 빌드를 음성 대조군으로.
- 라이브: `SPARK_LOCK=… S5_ARMS="cpu all" s5-arms.sh 3 60`.

1. **v1** (sha `519935b6`): SISO 경로의 `nof_prb > 1` 조건만 없앴다.
   - 오프라인 AWGN: 1 PRB가 −0.15~−0.19 dB로 맞았다.
   - 라이브(`s5-arms-20260925T042052Z`): `all`의 CRC 실패가 **0/3664**가 됐지만, 이번에는 1 PRB SINR이 CPU보다 **−2.2~−2.7 dB 낮게** 나왔다. 링크 적응이 보수적으로 가서(19/24/27 PRB) 가중 ΔSINR −0.89 dB로 **FAIL**이다.
   - 원인은 오프라인 `--ta-offset 1`(최대 1 µs 무작위 TA)로 재현했다. v1은 1 PRB −2.56 dB, 6 PRB −0.56 dB로, 라이브 값(1 PRB −2.2~−2.7, 5 PRB −0.5)과 같다. CFO(`--cfo-std 600`)는 영향이 없다.
   - 메커니즘: TA는 주파수 방향의 선형 위상 기울기다. GPU 평활은 회전된 탭을 그대로 평균해서 추정치를 줄이고, 그 잔차를 잡음으로 센다. CPU(`port_channel_estimator_helpers.cpp` `apply_fd_smoothing`)는 크기와 펼친 위상으로 외삽한 가상 파일럿을 쓰고 필터를 PRB 수에 맞게 만들기 때문에 이 문제가 없다.
2. **v2** (sha `2c0962bc`, 현재 lock): 평활 커널이 탭 창 안에서 파일럿당 위상 회전(`Σ h[i+1]·conj(h[i])`)을 추정하고, 출력 위치 기준으로 되돌린 뒤 필터링한다. v1의 조건 제거도 포함한다. 결과는 아래와 같다.

| 오프라인 GPU−CPU (dB, 입력 10 dB) | 1 PRB | 2 PRB | 6 PRB | 24 PRB |
|---|---|---|---|---|
| C1 | +2.55 | −0.07 | −0.02 | −0.01 |
| C1 + D8 v2, TA 0 | −0.08 | −0.07 | −0.02 | −0.01 |
| C1 + D8 v2, TA ≤1 µs | +0.62 | +1.81 | +0.06 | +0.09 |
| C1 + D8 v2, CFO σ 600 Hz | −0.16 | −0.07 | −0.02 | −0.01 |

TA가 있을 때의 +값은 CPU 쪽이 떨어진 결과다. TA ≤2 µs에서 CPU는 1 PRB 7.3 dB, GPU는 10.8 dB이고 참값은 10 dB다. EVM도 GPU가 같거나 낮다. 즉 "CPU와 같은가" 기준으로는 넘치지만 참값에는 GPU가 더 가깝다. 복호는 모든 조건에서 일치한다.

v2 검증(`d8-*` 두 번째 런): PHY 14/14, OFH 16/16, 로그 판정 pass, SINR 비교 PASS(1 PRB −0.09~−0.17, 2 PRB −0.00~−0.10). 음성 대조군(C1 빌드)은 1 PRB +2.2~+2.6으로 재현된다.

**라이브 v2** (`s5-arms-20260925T044210Z`, `cpu`/`all` 교차 3회, 6/6 통과):

| `all` 빌드 | `all` 합산 BLER | 같은 배치의 `cpu` | 가중 ΔBLER / ΔSINR | 판정 |
|---|---|---|---|---|
| C1 | 1.51% | 0.25% | +0.20%p / −0.16 dB | PASS (합산 6배) |
| C1 + D8 v1 | 0.00% | 0.22% | +0.00%p / −0.89 dB | FAIL |
| **C1 + D8 v2** | **0.54%** | 0.35% | **+0.21%p / −0.25 dB** | **PASS** |

v2에서는 링크 적응이 CPU와 같은 할당(17/19/24 PRB)을 고른다. 1 PRB 보고 SINR은 평균 7.01 / 최대 8.8 dB로, CPU(7.56 / 8.5)와 비슷하다. 15 PRB 선택은 사라졌다. 할당별로 남은 차이는 16QAM `[0,17)` 3.16% vs 1.95%(n 475/667)와 16QAM `[0,1)`의 ΔSINR −0.78 dB(n 52)다. PHY `t` p50은 198 µs로 v1 전과 같다.

**미해결:** MIMO 경로(`nof_tx_layers > 1`, wide 평활 커널)도 같은 조건이 있고, 2L2P 1 PRB에서 +0.82 dB다. wide 커널이 1 PRB에서 안전한지는 확인하지 않아서 이번 패치에서는 제외했다.

### S6 정정 — 20 MHz 1L PUSCH의 CPU 지연은 코어 배치가 지배한다 (2026-09-25)

S6에서 "원인 미상"으로 남긴 CPU 401.1 µs(문서 225.8 µs)를 같은 명령(`pusch_e2e_pipeline_test --prb 51 --sinr 25 --mcs 20 … --iterations 100`, C1 빌드)으로 `taskset`만 바꿔 2회씩 재현했다. governor는 모든 코어가 `performance`다. GB10의 코어는 A725(cpu 0–4, 10–14, 최대 2.8 GHz)와 X925(cpu 5–9, 15–19, 최대 3.9 GHz)다.

| CPU 배치 | CPU min / mean / max | GPU mean | CPU/GPU |
|---|---|---|---|
| 고정 없음 | 126–142 / 356–365 / 938–1002 µs | 179–184 µs | 2.0× |
| X925 1개(cpu 5) | 143 / **155** / 180 µs | 138–140 µs | **1.1×** |
| A725 1개(cpu 0) | 348 / **388** / 446 µs | 163–165 µs | 0.4× |
| X925 10개 | 108–131 / 305–372 / 1351–1475 µs | 180 µs | 1.7–2.1× |

- 빅 코어 하나에 고정하면 CPU 분포가 좁아지고(143–180 µs), GPU와 거의 같다(1.1×). 문서의 0.86×와 방향이 같다.
- 고정하지 않으면 평균이 리틀 코어 값에 가깝고, 최대가 1 ms에 이른다. 빅 코어 10개로 묶어도 비슷하다. 즉 코어 종류만이 아니라 스레드 이동과 깨어남이 섞인다.
- **따라서 S6의 "20 MHz 1L PUSCH는 문서와 반대로 GPU가 2.3× 빠르다"는 틀렸다.** CPU를 고정하지 않은 측정의 착시다. 이 부하에서 CPU(빅 코어)와 GPU는 비슷하다. 라이브에서 GPU가 느린 것(위 "라이브 PUSCH 처리 시간")과도 모순되지 않는다.
- **100 MHz 4L도 같다**(S6와 같은 명령, 반복 10, 2회씩):

| CPU 배치 | CPU mean | GPU mean | 배율 |
|---|---|---|---|
| 고정 없음 | 12238 / 13038 µs | 369 / 348 µs | 33.2× / 37.5× |
| X925 1개(cpu 5) | 6779 / 6774 µs | 302 / 308 µs | **22.4× / 22.0×** |
| X925 10개 | 7107 / 7139 µs | 347 / 328 µs | 20.5× / 21.8× |

  **S6의 "PUSCH 40× (문서 21.2×)"는 CPU 미고정의 착시였고, CPU를 빅 코어에 두면 20.5–22.4×로 문서 값을 재현한다.** 고정하지 않으면 CPU 평균이 두 배로 늘고 GPU도 약간 느려진다. 문서의 CPU 절대값(13122 µs)은 우리의 미고정 값과 비슷하고 GPU 절대값(618.9 µs)은 두 배다. 배율만 맞는 것은 우연일 수 있다. 앞으로 CPU/GPU 비교는 **`taskset -c 5`(X925 하나)로 고정해서** 잰다.

#### D8 v3 — MIMO 경로까지 (2026-09-25, `d8-20260925T052309Z`, `s5-arms-20260925T053012Z`)

기울기 보정 평활을 `__device__` 도우미 `fd_smooth_pilot_slope_comp()` 하나로 모았다. SISO, MIMO, MIMO wide 세 커널이 이 도우미를 쓰고, MIMO 경로의 `nof_prb > 1` 조건도 없앴다. 패치 sha256은 `10d89610`(현재 lock)이다.
- 오프라인 1 PRB SINR 차이(입력 10 dB): 2L2P는 +0.82 → −0.40 dB, 4L4P는 −0.25 dB다. SISO는 v2와 같다(−0.11).
- 20 dB MIMO 복호: TA가 없으면 모두 0 불일치다. TA ≤1 µs(2L2P)에서는 CRC 불일치가 C1과 D8 모두 1–3건으로, 회귀가 아니다.
- 검증: PHY 14/14, OFH 16/16, 판정 pass, SINR 비교 PASS, 음성 대조군 재현.
- **라이브(cpu/all 3회씩): BLER 0.27% / 0.81%, 가중 ΔBLER +1.01%p → FAIL**(ΔSINR −0.23 dB). 할당 구성은 v2와 같다. 차이는 거의 전부 16QAM `[0,17)`에서 났다(CPU 1.33% vs GPU 6.12%, n 677/474). SISO 계산은 v2와 같은데 v2 런에서는 3.16% vs 1.95%였다.

**이 BLER 차이는 D8 때문이 아니다.** 오프라인에서 17 PRB 16QAM(MCS 12)을 문턱 근처에서 600회씩 돌렸다. CPU/GPU BLER이다.

| | 6.0 dB | 6.5 dB | 6.0 dB, TA ≤1 µs | 6.5 dB, TA ≤1 µs |
|---|---|---|---|---|
| C1 | 30.8 / 28.7% | 0.2 / 0.3% | 34.8 / **45.3%** | 0.3 / **2.0%** |
| C1 + D8 | 33.5 / 32.5% | 0.2 / 0.3% | 31.8 / **36.3%** | 0.2 / **0.8%** |

TA가 없으면 두 빌드 모두 CPU와 같다. TA가 있으면 GPU 복호가 CPU보다 약하다. 이 약점은 **C1부터 있었고, D8이 오히려 줄였다.** 따라서 라이브 16QAM `[0,17)`의 초과 실패는 원래 있던 **"TA에 대한 GPU 복호 약점"**(결함 후보 **D9**)에 런 간 편차가 더해진 것이다. 라이브 S5 판정이 v2에서는 PASS(+0.21%p), v3에서는 FAIL(+1.01%p)로 흔들리는 것도 이 할당에 실패가 몰리기 때문이다.

- D9 추적 방향: GPU 등화와 복조가 TA로 인한 주파수 방향 위상 기울기를 CPU처럼 다루는지 확인한다. CPU는 TA를 추정해서 보간에 쓴다. 이 절의 오프라인 명령(`--prb 17 --mcs 12 --sinr 6.5 --ta-offset 1 --iterations 600`)이 재현 조건이다.
- 2000회(17 PRB, 6.25 dB, CPU/GPU BLER): C1은 TA 없음 4.1/3.8%, **TA 5.2/10.2%**. D8은 TA 없음 4.65/5.3%, **TA 5.25/6.4%**. D8이 TA 조건의 GPU 손해를 +5.0%p에서 +1.15%p로 줄였다. 남은 D9는 작다.
- S5 라이브 판정은 교차 3회로는 이 할당에서 흔들린다. 판정용으로는 반복을 늘리거나(≥6회), D9를 고친 뒤 다시 본다.

#### S5 재판정 — 교차 6회, C1 + D8 v3 (2026-09-25, `s5-arms-20260925T054535Z`)

`cpu`/`all` 6회씩, 12/12 통과. 가중 **ΔBLER +0.52%p, ΔSINR −0.27 dB, 일치 신규 전송 5435건 → PASS**. 합산 BLER은 CPU 0.41%, GPU 0.72%다. PHY `t` p50은 89 vs 224 µs다.

| 할당 | CPU n / BLER | GPU n / BLER | ΔSINR |
|---|---|---|---|
| 16QAM `[0,17)` tbs 528 | 1326 / 2.26% | 923 / **5.31%** | −0.18 |
| QPSK `[0,1)` tbs 21 | 1235 / 0% | 1690 / 0% | −0.60 |
| 16QAM `[0,1)` tbs 21 | 551 / 0% | 103 / 0% | −0.59 |
| 나머지 6개 할당 | 0% | 0% | −0.09 ~ −0.30 |

- 16QAM `[0,17)`의 +3.05%p는 표본이 커도 뚜렷하다. 이 할당의 GPU 복호 열세(D9)는 라이브에서도 실재한다.
- 1 PRB SINR은 여전히 −0.6 dB다(기준 0.5 dB를 할당별로는 넘는다). 가중 판정에서는 통과한다.
- **D9 — 라이브 조건에서 재현했고 범위를 좁혔다 (09-25).** `pusch_gpu_cpu_comparison_test -L`(15 kHz, `interpolate`, MMSE)에 진단 옵션 `-D <TA µs>`(수신 그리드에 선형 위상), `-C <CFO Hz>`, `-M <MCS>`를 추가했다. 별도 체크아웃 `src/ocudu-cuda-d9`(C1 + D8)와 `src/ocudu-cuda-d9c1`(C1만)을 쓰고, live lock 트리는 건드리지 않았다. 17 PRB, MCS 10, CFO 0, 2000회, CPU/GPU BLER이다.

  | | 4 dB | 4.5 dB | 4 dB, TA 1 µs | 4.5 dB, TA 1 µs |
  |---|---|---|---|---|
  | C1 | 45.2 / **56.5%** | 0.3 / **1.8%** | 43.3 / **61.1%** | 0.6 / **2.5%** |
  | C1 + D8 | 44.0 / **58.5%** | 0.3 / **2.1%** | 44.3 / **60.0%** | 0.3 / **1.9%** |

  - **D8과 무관하다**(C1에도 같은 차이). **TA가 없어도 있다**(TA는 조금 키울 뿐). 이 조건에서 **EVM과 보고 SINR은 CPU와 같다**(42.1 / 42.1%). 따라서 채널 추정이 아니라 **등화 이후(LLR 계산 또는 LDPC 복호)**에서 GPU가 문턱 근처 0.1–0.2 dB 약하다.
  - 09-24 이슈 6 진단의 "CFO 0이면 CPU·GPU 동일"은 5 dB에서만 본 것이라 문턱 차이를 놓쳤다.
  - **원인: GPU LDPC의 고정 min-sum 계수.** `pusch_codeblock_decoder_cuda_batch.cpp`는 `auto_scale=false, min_sum_scale=0.75, min_sum_offset=0.10`으로 고정한다. 벤더 주석은 "1L1P PRB/MCS 스윕에서 0.80보다 CPU 곡선에 가깝다"고 적었지만, 라이브 조건(`-L`)에서는 반대다. CPU는 0.8이다. 17 PRB, MCS 10, 2000회, 4 / 4.5 dB의 CPU/GPU BLER이다.

    | GPU 설정 | CPU | GPU |
    |---|---|---|
    | 벤더(0.75, offset 0.10) | 44.2 / 0.2% | **58.2 / 1.6%** |
    | `OCUDU_LDPC_SCALE=0.8`(offset 0) | 46.0 / 0.3% | 51.0 / 0.3% |
    | **`OCUDU_LDPC_SCALE=0.8 OCUDU_LDPC_OFFSET=0.1`** | 43.0 / 0.7% | **40.3 / 0.4%** |
    | `OCUDU_LDPC_SCALE=0.85`(offset 0) | 45.2 / 0.6% | 62.7 / 0.7% |
    | 진단: 계수만 0.8(offset 0.10 유지) | 43.2 / 0.8% | 39.5 / 0.6% |
    | 진단: 계수만 0.7 | 43.5 / 0.4% | 84.1 / 13.1% |

    계수 0.8 + offset 0.10이면 GPU가 CPU와 같거나 낫다. `OCUDU_LDPC_SCALE`은 offset을 0으로 되돌리니까 `OCUDU_LDPC_OFFSET=0.1`을 함께 줘야 한다. 두 변수 모두 벤더 코드에 이미 있고 라이브 러너가 넘기므로, **재빌드 없이 라이브 A/B가 가능하다**(실행 중). 진단 스위치 `OCUDU_DIAG_LDPC_SCALE`/`_PRINT_SCALE`은 `src/ocudu-cuda-d9`에만 있다.
  - 남은 확인: 큰 TB(BG1, 100 MHz 4L)의 감도와 지연에 계수 0.8이 손해를 주지 않는지 본다. 벤더가 0.75를 고른 근거가 그쪽일 수 있다.

### C1 + D8 + D9 통합 패치 (2026-09-25, `s-c1-d8-d9.patch`, lock `cuda-workspace.spark-d8.lock.json`)

D9 수정은 `pusch_codeblock_decoder_cuda_batch.cpp`의 `min_sum_scale`을 0.75에서 **0.80**으로 바꾸는 것이다(offset 0.10 유지, `OCUDU_LDPC_SCALE/OFFSET` 재정의는 그대로 동작). 라이브 A/B(`OCUDU_LDPC_SCALE=0.8 OCUDU_LDPC_OFFSET=0.1`, `s5-arms-20260925T062243Z`, 교차 6회, 12/12 통과) 결과는 다음과 같다.
- **가중 ΔBLER +0.00%p, ΔSINR −0.23 dB → PASS.**
- 16QAM `[0,17)`: CPU 1.90% vs GPU **1.90%**(이전 2.26% vs 5.31%). 합산 BLER은 0.35% / 0.50%다.
- BG1 확인(273 PRB, 4L8P, MCS 20, 150회, 12.5/13/13.5 dB, CPU/GPU BLER): 벤더 52.0/50.0, 33.3/34.0, 20.0/19.3%이고, 0.8+0.1은 51.3/50.7, 33.3/32.7, 21.3/18.0%다. 차이는 표본 편차 안이고 GPU 지연도 같다.

통합 패치 검증(`d8-*` 최신): OFH 16/16, 로그 판정 pass, SINR 비교 PASS, 음성 대조군 재현. **PHY는 13/14**였다. 실패한 `ofdm_demodulator_cuda.gpu_ci16_full_slot_batch_matches_cpu_with_phase_compensation`은 `get_owned_device_snapshot_cbf16()`을 읽는 `cudaMemcpyAsync`가 `cudaErrorInvalidValue`(1)를 돌려준 것이다. 10회 재실행 결과 C1 빌드 1/10, D8 빌드 0/10 실패로, **원래 있던 간헐적 실패**다(D8/D9가 건드린 파일과 무관, 결함 후보 **F1**, 추적 전).

**F1 재현 조건**(09-25, C1 빌드 `ofdm_demodulator_cuda_test`):

| 실행 방식 | 실패 |
|---|---|
| 해당 케이스 단독, 보통 실행 | 0/100 |
| 해당 케이스 단독, `CUDA_LAUNCH_BLOCKING=1` | 0/100 |
| 해당 케이스 단독, compute-sanitizer 아래 | 0/40 |
| 스위트 전체, 원래 순서 | 1/60 |
| 스위트 전체, `--gtest_shuffle` | 3/60 |

실패는 항상 같은 공통 도우미 줄(`:336`, 스냅샷 `cudaMemcpyAsync` → `cudaErrorInvalidValue`)이다. 소유 스냅샷을 읽는 두 케이스(`full_slot_batch…`, `split_slot_tail_batch…`) 중 **앞선 테스트 뒤에 도는 쪽**이 실패한다. 배제한 것(진단 트리 `src/ocudu-cuda-d9`의 테스트에 복사 직전 계측을 넣었고, 섞은 순서 100회 중 실패 5회):
- 복사 직전에 **남아 있던 CUDA 오류는 없다**(`cudaPeekAtLastError()=0`).
- 소스 포인터는 정상적인 장치 메모리다(`cudaPointerGetAttributes`: type 2, device 0).
- 스냅샷 버퍼는 그리드마다 따로 할당된다(전역 풀 없음).
- lower-PHY RX의 호스트 등록 캐시(`low_phy_puxch_rx.cu`, 버퍼보다 오래 남을 수 있음)도 원인이 아니다. `OCUDU_LOWPHY_RX_RUNTIME_HOST_REGISTRATION=0`에서 4/100, `=1`에서 3/100으로 같다.

남은 후보: 복사 대상(페이지 가능 `std::vector`)의 상태, 또는 드라이버 쪽. 추적을 멈춘다. 영향은 벤더 테스트의 간헐적 실패이고, 라이브 경로 영향은 확인하지 않았다.

**통합 패치 라이브**(`s5-arms-20260925T064648Z`, `cpu`/`all` 교차 6회, 12/12 통과):
- **가중 ΔBLER −0.00%p, ΔSINR −0.19 dB, 일치 신규 전송 5900건 → PASS.**
- 16QAM `[0,17)`: CPU 1.90% vs GPU **1.89%**. 합산 BLER은 0.34% / 0.52%다(차이는 할당 구성: GPU가 1 PRB 할당에서 SINR을 −0.3~−0.4 dB 낮게 보고해 조금 더 보수적이다).
- PHY `t` p50은 CPU 89 µs, GPU 226 µs다(20 MHz 1L, GPU가 느림).

**S 트랙 정합 요약**: C1만으로는 `all`의 합산 BLER이 CPU의 6배였다. C1 + D8 + D9를 넣으면 같은 할당에서 CPU와 구별되지 않는다. 남은 차이는 1 PRB SINR −0.3~−0.4 dB(D8 이후 잔여)와 처리 시간이다.

**S4 사다리 재실행, C1+D8+D9**(09-25, `SPARK_LOCK=…spark-d8…` `s4-ladder.sh`): 5단계 모두 attach·keepalive 299 통과. 백엔드 모양은 09-24 C1 사다리와 같다. `low-phy-tx`·`pusch` 단계는 TX가 staging(DEGRADED)이고, `pdsch`부터 direct+staging이다. 호스트 폴백 0. BLER은 0.25–0.73%다. D8/D9로 백엔드 선택이 바뀌지 않았다.

### 최종 빌드 성능 (C1+D8+D9, CPU를 X925 하나에 고정, 2026-09-25, `results/s6-final-*`)

| 부하 | CPU | GPU | 배율 | 문서 |
|---|---|---|---|---|
| PUSCH 100 MHz 273 PRB 4L 8RX, 평균 | 6787 / 6809 µs | 312 / 313 µs | **21.7×** | 21.20× |
| PUSCH 51 PRB 1L, 평균 | 155 / 157 µs | 141 / 140 µs | **1.1×** | 0.86× |
| PUSCH 106 PRB 1L, 평균 | 310 / 310 µs | 141 / 138 µs | **2.2×** | — |
| PDSCH 100 MHz 273 PRB 4L 4P, p50 | 577 / 581 µs | 171 / 171 µs | **3.4×** | 3.36× |

각 칸은 2회 반복이다. PDSCH CPU는 고정해도 미고정(S6 581.8 µs)과 같다. D8/D9는 벤치마크 지연을 바꾸지 않았다(C1 고정 22.0–22.4× → 21.7×, 표본 편차 수준).

### 통합 메모리에서 H2D/D2H는 사라졌나 — PDSCH 다중 UE 측정 (2026-09-25)

`pdsch_gpu_latency_benchmark`, C1+D8+D9 빌드, 100 MHz, 4 layer, 4 port, MCS 20, CPU는 X925(cpu 5–9)에 고정, 50회 p50. UE 수만큼 PDSCH PDU를 두고 272 PRB를 나눠 가진다.

| UE × PRB | CPU | GPU host 경로(복사) | GPU direct 경로 |
|---|---|---|---|
| 1 × 272 | 576 µs | 286 µs | **172 µs** |
| 4 × 68 | 583 µs | 459 µs | 340 µs |
| 16 × 17 | **610 µs** | 1069 µs | 994 µs |

- **복사는 피할 수 있을 뿐 사라지지 않았다.** host 경로의 그리드 복사는 UE 1개일 때 GPU 시간의 약 40%(114 µs)다. direct 경로에서만 없어진다. 라이브 TX는 호스트가 쓴 슬롯에서 staging을 탄다(S4). 포트 수에 따른 변화는 아래 포트 스윕을 보라. "포트 수에 비례해 staging 비용이 는다"는 앞선 추정은 측정으로 뒷받침되지 않는다.
- **UE가 늘면 PDU당 고정 비용이 지배한다.** direct 경로의 PDU당 약 60 µs는 `--sync-after-process=0`에서도 같다(990 vs 995 µs). 16 UE × 17 PRB에서는 GPU가 CPU보다 1.6배 느리다. MU 확장의 병목은 H2D/D2H가 아니라 PDU별 실행이다. 배치 처리가 필요하다.
- 라이브 20 MHz 1L PUSCH의 전송 구간은 H2D p50 8.9 µs(demod phase, `direct_grid=true` 2745/2745), D2H p50 3.8 µs로, 처리 시간(p50 245 µs)의 약 5%다.
- 미측정: PUSCH 다중 UE, 8 포트 이상, 실제 MU-MIMO, 라이브 TX에서 staging 경로가 쓰이는 슬롯 비율.

**포트 수 스윕**(같은 벤치마크, 1 layer, `--precoding=all-ports`, 272 PRB, UE 1개, 30회 p50):

| 포트 | CPU | GPU host 경로 | GPU direct 경로 |
|---|---|---|---|
| 1 | 141 µs | 112 µs | 101 µs |
| 4 | 153 µs | 124 µs | 130 µs |
| 8 | 170 µs | 134 µs | 170 µs |
| 16 | **세그폴트** | 85 µs(비정상) | 324 µs |
| 32, 64 | 세그폴트 | 세그폴트 | 세그폴트 |

- 1 layer를 모든 포트로 복제하는 구성에서는 포트가 늘수록 **direct 경로가 host 경로보다 느려진다**(8 포트 170 vs 134 µs). GPU가 managed 그리드에 직접 쓰는 비용이 포트 수와 함께 커진다. 4 layer 4 port(위 표)에서는 direct가 빨랐으니, 어느 경로가 나은지는 구성에 따라 달라진다.
- 16 포트 host 경로의 85 µs는 1 포트보다 빨라 물리적으로 맞지 않는다. 같은 구성에서 CPU가 세그폴트이므로, 이 벤치마크의 16 포트 이상 결과는 믿지 않는다.
- **결론: 이 벤치마크로는 massive MIMO 규모(≥16 포트)를 잴 수 없다.** 그런 규모에서의 H2D/D2H·그리드 비용은 미확인이다. 세그폴트는 벤치마크(또는 그리드 최대 포트 수)의 한계로 보이며, 추적하지 않았다.

**여러 UE의 배치 처리** (09-25, 같은 벤치마크, 16 UE × 17 PRB, 4L4P, direct 경로):

| 방식 | 전체 p50 | PDU당 |
|---|---|---|
| CPU | 610 µs | 38 µs |
| GPU, PDU별 처리(gNB 경로) | 995 µs | 62 µs |
| GPU, `--encoder-batch=1`(TB 배치 인코딩) | **140 µs** | **8.8 µs** |

- gNB의 PDSCH는 PDU마다 처리기를 하나씩 부른다(`pdsch_processor_pool.h`, 동시성은 `pdsch_acceleration_nof_lanes`, 라이브는 `lanes=1 pool_size=4`). 한 PDU 안의 코드블록은 배치된다(`cb_batch=all`).
- 여러 PDU를 한 번에 인코딩하는 경로(`ldpc_encoder_cuda_batch`, `transport_block.cu`)는 라이브러리에 있지만 **gNB 코드 어디에서도 호출되지 않는다**. 벤치마크만 하위 API를 직접 쓴다. 이 경로가 gNB 처리기의 일을 전부 포함하는지는 확인하지 않았다.
- 결론: 다중 UE에서 GPU가 CPU보다 느린 이유는 교차 PDU 배치가 gNB에 연결되지 않았기 때문이다. 연결하면 7배 가까운 여지가 있다.
- GPU PDSCH를 켜도 DMRS는 CPU가 매핑한다(`pdsch_processor_flexible_impl::map_reference_signals`, D7 스택). 그래서 슬롯마다 그리드 소유권이 CPU와 GPU를 오간다.

### S7 — 채널 에뮬레이터 경유 + 멀티 gNB (2026-09-27)

지금까지 Spark의 CUDA gNB 라이브는 직결 ZMQ(gNB↔srsUE)뿐이었다. 이번에 처음으로 channel emulator를 거쳐 붙였고, 이어서 CUDA gNB 프로세스 2개를 한 GPU에서 돌렸다. 빌드는 C1+D8+D9(`cuda-workspace.spark-d8.lock.json`, `builds/d8-cuda-patched-sm121`), 가속 단계 `all`, emulator 브로커는 `gb10-zero-copy` 트리(`/workspace/gpuch/zc9`)이고 host memory는 `copy`다.

**1×1 (`run-ocudu-cuda-1x1.sh`, 20260927T104658Z): 통과.** `tx_pulls=67097`, `rx_starvations=7`, 카운터 0. gNB 로그에서 GPU 경로 선택을 확인했다: UL 그리드 direct writer, DL 그리드 direct reader, PRACH buffer direct writer. lower-PHY TX는 host staging fallback이다(S4와 같음).

**멀티 gNB 러너.** `scripts/native/run-ocudu-multi-gnb.sh`(+`-inner.sh`, `render-multi-gnb-configs.py`)를 새로 만들었다. Docker 기반 `scripts/remote/ocudu-multi-gnb-smoke.sh`를 native로 옮긴 것이다. 네임스페이스·프로세스 관리는 native 멀티 UE 게이트 것을 그대로 쓴다. 구성은 다음과 같다.
- gNB 프로세스 2개. 셀마다 PCI 1/2, `gnb_id` 411/412, ZMQ 포트 2000–2001/2010–2011이 다르다. N2/N3 bind는 `127.0.0.11`/`.12`로 나눴다(같은 주소면 GTP-U 포트가 충돌한다).
- srsUE 2개, Open5GS 하나.
- 브로커 토폴로지는 `examples/topology.multi-gnb.cuda.yaml`이다: serving 6 dB, intercell 20 dB, 링크 8개.
- `OCUDU_NATIVE_GNB_ACCELERATION`이 있으면 CUDA gNB(두 셀 모두), 없으면 CPU gNB다.
- 판정에 **UE가 자기 셀(PCI)에 붙었는지**를 넣었다. 두 UE가 한 셀에만 붙으면 2셀 시험이 아니기 때문이다.
- aarch64용 노브를 넣었다: `OCUDU_NATIVE_CUDA_ARCH`, `OCUDU_NATIVE_SKIP_WORKSPACE_LOCK`.

| 실행 | gNB | 결과 | UE0 → PCI | UE1 → PCI | rx_starvations | 브로커 p50 / p99 (gNB 노드) | GPU 메모리 |
|---|---|---|---|---|---|---|---|
| 20260927T105015Z | CPU × 2 | **통과** | 1 (기대 1) | 2 (기대 2) | 2 | 120 / 180 µs | — |
| 20260927T105519Z | **CUDA × 2** (`all`) | **통과** | 1 (기대 1) | 2 (기대 2) | 19 | 135 / 235 µs | **gNB당 9,545 MiB** (RSS 4.9 GB) |

- **두 CUDA gNB 모두 GPU 경로를 탔다.** 로그의 경로 선택 줄이 1×1과 같다. 두 gNB 로그 어디에도 late·overflow 이벤트가 없다.
- **MPS 없이 돌았다.** 두 프로세스가 GPU를 시간 분할로 나눴다. 브로커 호출이 CPU gNB 대비 p50 +15 µs, p99 +55 µs 늘었고, rx_starvations가 2 → 19로 늘었다. 셋 다 게이트 기준 안이다. 이 증가가 GPU 경합 때문인지는 분리하지 않았다.
- **GPU 메모리:** nvidia-smi 기준 CUDA gNB 하나가 9,545 MiB를 잡는다. 5090(09-11, 1개)에서 잰 GPU 전체 사용량 10.7 GB와 같은 규모다. GB10(통합 121 GB)에서는 여유가 크다. 32 GB인 5090에서는 3개 이상이 어렵다(추정).

**zero-copy 브로커와 조합 (CUDA gNB × 2, `all`, copy·zero-copy 교대로 2회씩).** 네 번 모두 통과했고, UE는 매번 자기 셀에 붙었다. 카운터는 0이다. zero-copy 실행에서는 브로커 `gpu_timings`의 D2H가 0.8 µs라 zero-copy가 실제로 돌았다. copy 실행은 7.8–7.9 µs다.

| 실행 | 브로커 | gNB 노드 n | gNB p50 / p99 | UE p50 / p99 | rx_starvations | ring 읽기 / emulator / ring 쓰기 (중앙값, µs) |
|---|---|---|---|---|---|---|
| 105519Z | copy | 34만 | 135 / 235 | 130 / 300–305 | 19 | 13.2 / 129.9 / 5.0 |
| 113123Z | **zero-copy** | 34만 | **100 / 175** | **100 / 255** | 20 | 20.9 / 96.1 / 13.4 |
| 113753Z | copy | 65만* | 100* / 225 | 130 / 305–310 | 18 | 12.8 / 113.2 / 4.8 |
| 114423Z | **zero-copy** | 64만* | **75* / 175–180** | **95 / 255** | 22 | 20.5 / 79.0 / 12.6 |

\* 두 번째 쌍은 gNB 노드 호출 수가 약 2배다. 샘플 수가 적은 조각 호출이 섞여 p50이 낮게 나오므로, 같은 쌍 안에서만 비교한다. UE 노드는 네 실행 모두 약 34만 회라 바로 비교할 수 있다.

- **같은 쌍 안에서 zero-copy가 p50 30–35 µs, p99 50–60 µs 짧다.** UE 노드는 p50 130 → 95–100 µs, p99 300–310 → 255 µs다. 1×1 라이브에서 줄어든 폭(p50 약 20 µs, p99 약 25 µs)보다 크다. 이 토폴로지는 노드마다 들어오는 링크가 2개이고, GPU를 CUDA gNB 2개와 나눠 쓴다. 이 두 조건 중 어느 쪽이 폭을 키웠는지는 분리하지 않았다.
- **브로커 한 슬롯(ring 읽기 + emulator + ring 쓰기)은 148 → 130 µs, 131 → 112 µs로 줄었다.** zero-copy에서 ring 단계가 길어지는 현상(Z8에서 본 것)이 여기서도 나타나지만, emulator 호출이 줄어든 폭이 더 크다.
- **rx_starvations는 모드와 무관하게 18–22다.** 브로커 모드가 원인이 아니다. CPU gNB 2셀은 2였으므로 CUDA gNB 쪽 타이밍과 관련 있어 보이지만, 확인하지 않았다.
- **GPU 메모리는 모드와 무관하게 gNB당 9,545 MiB다.**
- **아직 안 한 것:** MPS 켠 비교, 3셀 이상, 트래픽 부하에서 BLER/SINR, 장시간 실행.
