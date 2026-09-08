# Plan — CUDA 가속 OCUDU gNB 통합

Status: **C0 완료 2026-09-08** — CUDA 12.8 gNB 빌드 및 호환 패치 적용 PHY 12/12 통과 · **C1 완료 2026-09-08** (lock/선택자/CPU 회귀 게이트)

## 한 줄 결론

CUDA OCUDU는 **26.04 + CUDA**라 소스 교체 자체는 저위험이지만, **이 프로젝트의 현재 구성(20 MHz · rank-1 · 1-layer)에서는 지연이 줄지 않고 오히려 늘어난다**는 것이 공식 문서의 실측이다. 따라서 통합의 목적은 "빨라진다"가 아니라 **GPU 상주 PHY 파이프라인(에뮬레이터 → gNB lower/upper PHY → LLR)을 한 GPU 위에 확보**하는 것으로 잡고, 성능 주장은 100 MHz / 다중 layer 확장 이후로 미룬다.


## C0 실행 기록 — 2026-09-08

- 기존 `ocudu-minwoo` 컨테이너를 재시작했다. host workspace는 `/home/minwoo/ocudu-work/ocudu-native-workspace`, 컨테이너 경로는 기존 RUNPATH에 맞춘 `/home/hyunsoo/ocudu-native-workspace`다.
- WG 소스는 별도 `src/ocudu-cuda`에 내려받았고 전체 커밋은 `5830c9cb7813393b5d518dd5ee2b6641071be4ad`다.
- CUDA 12.8.93 / GCC 13.3.0 / CMake 3.28.3 / RTX 5090 (sm_120)에서 `ENABLE_CUDA=ON`, `ENABLE_ZEROMQ=ON`, `BUILD_TESTING=ON`, `CMAKE_POSITION_INDEPENDENT_CODE=ON` 구성이 통과했다. `ocudu_phy_cuda`와 gNB 최종 링크까지 통과했다. `--version`은 `26.04.0 (5830c9c)`이며 CUDA 활성 여부는 `--help`의 `GPU acceleration:` 항목으로 확인했다.
- 재현 스크립트: `scripts/native/build-ocudu-cuda.sh`. 기존 CPU 프로파일과 독립적으로 CUDA gNB와 공식 PHY 테스트 12개를 빌드·실행한다. CUDA 라이브러리 타겟과 테스트 개수를 명시적으로 검사한다.

```bash
docker exec ocudu-minwoo bash -lc '
  source /home/minwoo/ocudu-env.sh
  bash /home/minwoo/ocudu-work/ocudu-gpu-channel/scripts/native/build-ocudu-cuda.sh
'
```

이 스크립트는 위 커밋의 `src/ocudu-cuda` checkout과 기존 native 의존성 overlay를 요구한다. 깨끗한 checkout에 `scripts/native/patches/ocudu-cuda-host-grid-compat.patch`를 적용하며, 재실행 시 전체 diff가 해당 패치와 정확히 일치해야 한다. CPU 게이트의 gNB 선택자는 아직 추가하지 않았다. 빌드 성공, GPU 테스트 통과, 라이브 검증은 각각 별도 판정한다.

첫 실행은 **8개 통과 / 3개 실패 / 1개 중단**, 총 447.70초다. 전체 PUSCH 비교는 초기화 반복으로 오래 걸리는 것을 멈춤으로 오판해 423.44초에 수동 종료했다. 로그에서는 PRB=3/RX=1의 여섯 SINR 조건을 마치고 RX=2로 진행하고 있었다. 단일 조건 재검증(`-R 1 -P 3 -S 20 -N 1`)은 통과했으나 전체 sweep을 대체하지 않는다.

| 첫 실행 항목 | 확인된 증상 |
|---|---|
| PUSCH 비교 | 전체 sweep 재실행 필요. 단일 조건 SINR 차 0.1 dB, BLER 차 0%, decode agreement 100% |
| PDSCH E2E | 57개 내부 사례 중 56개 통과. `ManagedGridMatchesHostAcrossHarqRvsAndRepeatedSlots`의 transmission=0/port=0/symbol=0에서 device-grid 압축 호출이 false 반환 |
| SRS latency / sensitivity | 두 테스트 모두 CPU/GPU channel-matrix 수신 포트 수 불일치로 abort. `-G visible` 진단도 동일 실패. estimator가 빈 결과를 반환하는 여러 조건 중 정확한 원인은 아직 미확인 |

PUSCH pipeline은 100회 디코딩과 byte mismatch 0을 실제 로그로 확인했다. LDPC의 510개 skip은 filler 조합에 따른 업스트림 명시적 제외다. PUSCH 비교·pipeline 테스트는 실패 문구를 출력해도 exit 0이 가능하므로 재현 스크립트에 별도 로그 판정기 `verify-cuda-phy-log.py`를 연결했다. 이 첫 실행은 C0 통과 결과가 아니다. 아래 호환 패치 후 전체 재검증이 최종 C0 결과이며, 라이브 통합은 아직 검증하지 않았다.


### 호환 패치 및 재검증

- **PDSCH 원인:** CPU 결과 비교가 managed grid를 host로 옮긴 뒤 `prepare_device_grid_reading()`이 live GPU 재읽기를 거부한다. 압축 경로가 private owned snapshot을 사용할 수 있게 하고, 동기 압축 완료 후 read hold를 해제했다. 기존 반복 슬롯 테스트에 CPU 비교 전 live GPU 읽기를 추가해 두 경로와 hold 해제를 함께 확인했다. PDSCH 57개 내부 사례 전부 통과.
- **SRS 원인:** 일반 host grid와 discrete-GPU pinned grid에는 owned-snapshot API가 없는데 estimator가 이를 필수로 요구해 빈 결과를 반환했다. 기존 private device staging adapter를 복구하고 managed grid의 snapshot 경로는 유지했다. 두 baseline 테스트 재통과; 행렬 상대 오차는 약 3.82e-7 / 4.07e-7.
- 패치는 업스트림 소스 변경 2개와 PDSCH 회귀 사례 확장으로 구성한다. 깨끗한 임시 worktree에서 패치 적용, 멱등 재실행, 무관한 수정 거부를 검증했다.
- **최종 C0: 12/12 통과, 866.94초.** PUSCH 48조건 × 10회 비교 완료: 최대 SINR 차 0.1 dB, 최대 BLER 차 0%p, decode agreement 100%. PUSCH pipeline 100회 디코딩, byte mismatch 0. 별도 로그 판정기 통과.
- 환경: RTX 5090 (sm_120), 드라이버 595.71.05, CUDA 12.8.93, GCC 13.3.0, CMake 3.28.3. 합성 PHY 검증 결과이며 라이브 gNB 슬롯 지연 측정이 아니다.
- 결과: native `builds/ocudu-cuda-zmq-release/{c0-validation-patched.log,c0-result.json,Testing/Temporary/LastTest.log}`. JSON에 바이너리·패치·로그 SHA256 기록.
- 패치 SHA256: `a51cbbeeb78748a254cb8478e01451837c0e2d332bf8bc19a90a6a025050f0a8`. CPU gNB를 사용하는 기존 라이브 게이트 유지. C1에서 lock/프로파일 선택자 통합 및 CPU 회귀 게이트까지 완료.


## 1. 조사 요약 (근거)

| 항목 | 사실 |
|---|---|
| OCUDU | srsRAN Project가 2025-12에 개명. Linux Foundation, GitLab, BSD-3-Clause-Open-MPI. 첫 릴리스 26.04 = 이 워크스페이스의 핀 `a1916edc` |
| CUDA 가속판 | OCUDU **하드웨어 가속 WG1**(DeepSig 주도) 산출물. 레포 `gitlab.com/ocudu/work_groups/wg1_hw_accel/cuda_accelerated_ocudu`, 브랜치 `nvcuda_accel_02` (최신 커밋 2026-08-30). 논문 arXiv 2608.04338 |
| 업스트림 상태 | 메인 `ocudu/ocudu`(2026-09-04)에는 `ENABLE_CUDA` 옵션 + `lib/cuda/` 스캐폴드 + **PRACH 검출기 1개**만 들어감. 실제 가속 코드(`.cu` 69개)는 WG 브랜치에만 있음 |
| 베이스 차이 | WG 브랜치 vs 로컬 핀: non-CUDA diff는 `mac_cell_pcap_writer`, `ru_dummy`, ntn 예제 수준. **ZMQ 라디오 코드 동일** |
| 설계 | OCUDU 팩토리 패턴 뒤에 CUDA 구현. 블록별 `auto/enabled/disabled`, 전 경로 CPU 폴백. NVIDIA Aerial/cuPHY와 무관한 독립 구현, FFT는 VkFFT(벤더링) |
| 가속 범위 | PUSCH(GPU 상주, 복조→LDPC), PDSCH(fused 인코딩→그리드), SRS, PRACH(lower 복조+upper 검출), **split-8 lower-PHY OFDM TX/RX**, O-FH BFP 압축 |
| CPU 잔류 | **PUCCH 전부**, **HARQ 재전송**(host LDPC로 soft-combine), CSI Part 2, NIC/라디오 패킷 경계, 좁은 1-layer PDSCH |
| 메모리 모델 | 디스크리트 GPU(=5090) → `pinned` + 명시적 H2D/D2H. 통합 GPU → `managed`. 런타임 선택 불가(하드웨어 결정) |
| 빌드 | `-DENABLE_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=120`(RTX 50xx). `ENABLE_ZEROMQ=ON`과 공존. VkFFT 설치 불필요 |
| 검증 환경 | 문서/논문: DGX Spark GB10(aarch64) + **CUDA 13.0.88**. 우리: x86 + **CUDA 12.8.93** → 빌드 성공, 호환 패치 후 PHY 12/12 통과 |

**성능 실측 (문서, DGX Spark GB10)**

| 워크로드 | CPU | GPU | 배수 |
|---|---:|---:|---:|
| PUSCH 100 MHz 273 PRB 4-layer 8 RX | 13122 µs | 619 µs | 21.2× |
| PDSCH 100 MHz 4-layer 4-port | 625 µs | 186 µs | 3.4× |
| O-FH BFP9 RX 100 MHz 4-port | 1336 µs | 18 µs | 72.6× |
| **PUSCH 20 MHz 1-layer** | **225.8 µs** | **262.3 µs** | **0.86×** |
| **PDSCH 20 MHz 1-layer** | **29.4 µs** | **79.9 µs** | **0.37×** |

마지막 두 행이 이 프로젝트의 게이트 구성(23.04 MS/s = 20 MHz, srsUE 1-layer)이다. 논문도 "narrow one-layer PDSCH remains below CPU parity (0.50–0.88×)"를 알려진 한계로 명시한다.

## 2. 이 프로젝트에 미칠 기대효과

### 얻는 것

1. **GPU 상주 end-to-end 파이프라인.** 지금은 채널 에뮬레이터(브로커 CUDA 커널)만 GPU고, gNB는 ZMQ로 받은 IQ를 CPU에서 처리한다. CUDA gNB를 붙이면 `브로커 CUDA 채널 → (host IQ, ZMQ) → CUDA lower-PHY OFDM → CUDA PUSCH 등화/LDPC → LLR`이 한 GPU 위에 놓인다. 이는 `docs/plans/sionna-live-channel.md` "GPU placement" 절이 이미 전제로 둔 형태다.
2. **AI-RAN 진입점.** WG의 명시적 목표가 "GPU-resident tensors를 AI-RAN 앱에 노출"이다. PUSCH가 상주하면 등화 후 심볼/LLR을 device에서 직접 읽어 신경 수신기·학습 채널추정 실험을 붙일 수 있다. Sionna RT가 이미 GPU에 있으므로 "학습된 채널 → 에뮬레이션 → 상주 수신기"가 프로세스 경계 없이 이어질 수 있는 후보다.
3. **스케일 상한 확장.** 100 MHz·4-layer·다중 셀로 가면 위 표의 20×급 이득이 나온다. 현재 1×1/rank-1 게이트는 그 영역이 아니지만, 채널 에뮬레이터의 브로커는 이미 23040샘플/1 ms 슬롯에서 p99 ~1.3 ms(`AGENT_PROGRESS.md`)라 gNB 쪽 CPU가 아니라 브로커가 병목이 되는 구간을 먼저 만난다. gNB를 GPU로 옮겨두면 이후 브로커 최적화와 함께 100 MHz 목표를 세울 수 있다.
4. **CSI/링크어댑테이션 연구의 관측점 추가.** 상주 PUSCH는 device LLR을 fp16으로 유지하고 CRC 실패 시 export한다. 현재 CSI-RS off 환경에서 UL 링크어댑테이션 이상(`pusch.max_ue_mcs: 9` 캡의 근거)을 분석할 때 등화 후 데이터를 직접 볼 수 있다.

### 얻지 못하는 것 (정직하게)

- **현 게이트 구성에서 지연 감소 없음.** 20 MHz 1-layer는 GPU 런치/동기화 비용이 커널 이득을 상회한다. `result=pass` 게이트의 슬롯 타이밍이 나빠질 가능성이 더 크다.
- **PUCCH·HARQ 재전송은 CPU.** UL BLER 재전송 통계는 host LDPC가 만든다. "GPU에서 디코딩한 BLER"이라고 주장하려면 첫 전송만 해당된다.
- **에뮬레이터 자체는 변하지 않는다.** 채널 커널·y=Hx 판정·strict counter는 gNB와 무관하다.

## 3. 고려사항 / 리스크

| # | 항목 | 내용 | 대응 |
|---|---|---|---|
| R1 | **GPU 경합** | 5090 한 장에 브로커 CUDA 커널 + Sionna RT(OptiX) + CUDA gNB 세 컨텍스트. 브로커의 1 ms 슬롯 예산이 이미 빠듯. `sionna-live-channel.md:343`이 "CUDA gNB와 에뮬레이터가 GPU를 공유하면 Sionna는 별도 GPU"를 권고 | C4에서 세 프로세스 동시 구동 시 `process_latency_summary` p99와 gNB 슬롯 late 카운트를 함께 측정. 스트림 우선순위(`OCUDU_PUSCH_CUDA_STREAM_PRIORITY`)로 A/B |
| R2 | **CUDA 12.8 미검증** | 문서는 13.0.88. 코드에 13 전용 가드는 없고 VkFFT는 ≥11.3 요구. 12.8은 sm_120을 지원 | C0에서 컴파일 + CUDA ctest 12개로 확정. 실패 시 컨테이너 이미지를 `nvidia/cuda:13.x`로 올리되 `host_contract.cuda`(lock)와 `create-ocudu-minwoo.sh`의 nvcc 검증값 갱신 필요 |
| R3 | **디스크리트 GPU 정책** | `pdsch_acceleration_mode: auto`는 디스크리트에서 **host 선호**. `ul_cuda_visible_grid_mode: auto` → pinned | 게이트 config에 명시값 사용. PDSCH GPU 강제는 `enabled` 또는 `OCUDU_PDSCH_AUTO_ENABLE_DISCRETE=1` |
| R4 | **감사 해시·lock** | `run-ocudu-legacy-1x1.sh:47` `audited_ocudu=a1916edc…`, `native-workspace.lock.json` `git_sources[ocudu].commit`, `source-evidence.json` 스키마가 소스 커밋을 검증 | 별도 빌드 프로파일(`ocudu-cuda-zmq-release`)과 별도 lock 엔트리로 추가하고, 기존 CPU 게이트는 손대지 않음. `claim_boundary`에 CUDA 빌드는 hermetic 주장에서 제외(GPU 드라이버 의존)를 명시 |
| R5 | **결정론/parity 게이트** | 기존 게이트는 CPU↔CUDA parity를 브로커에 대해 증명했지 gNB에 대해선 아님. GPU LDPC의 `auto` 알고리즘 선택은 배치 크기에 따라 boxplus/min_sum이 바뀜 | 첫 라이브 실행은 **전 모드 `disabled`**로 CPU 빌드와 동일 결과(attach/PDU/ping/y=Hx) 확인. 이후 한 경로씩 켜며 BLER·SINR을 KPI 패널로 비교. LDPC는 `boxplus` 고정으로 재현성 확보 |
| R6 | **지원 경계** | validator: Type-1 DM-RS normal CP만. 상주 PUSCH 1–4 layer, 1/2/4/8 RX 포트. transform-precoded는 1-layer. PDSCH direct device-grid는 1-layer 또는 layer=port | 현 fixture 전부 범위 안(srsUE Type-1, 1-layer, 4 RX). 4T4R 게이트의 `nof_antennas_ul: 4`는 8 포트 상한 안 |
| R7 | **업스트림 이동** | WG → main 병합 진행 중. 6개월 내 브랜치명/키 이름이 바뀔 수 있음 | lock에 WG 커밋 해시를 핀. 문서에 "WG 브랜치 기준 2026-08-30 커밋" 명시. 메인에 merge되면 lock만 갱신 |
| R8 | **우회 훅 남용** | `OCUDU_*` 환경변수 20여 개가 정책을 덮어씀(`OCUDU_LOWPHY_TX_ACCELERATION`, `OCUDU_CUDA_VISIBLE_GRID` 등) | 게이트는 YAML 키만 쓰고 env 훅은 `inner.sh`에서 `unset`. 실험용 훅은 로그 매니페스트에 기록 |
| R9 | **컨테이너 RUNPATH** | 워크스페이스 바이너리는 `/home/hyunsoo/ocudu-native-workspace` 절대 RUNPATH. CUDA 빌드도 같은 규칙 필요 | `bootstrap-workspace.sh`의 `cmake_common`(RUNPATH/sysroot) 재사용 |

## 4. 필요한 것

**환경 (있음)**
- RTX 5090 compute_cap 12.0 → `CMAKE_CUDA_ARCHITECTURES=120`
- 컨테이너 `ocudu-minwoo`: nvcc 12.8.93, `libcufft-12-8`, Ubuntu 24.04 gcc 13.3 — host_contract 일치
- VkFFT: WG 레포 `lib/phy/cuda/external/vkfft`에 벤더링 → 설치 불필요

**소스**
- `https://gitlab.com/ocudu/work_groups/wg1_hw_accel/cuda_accelerated_ocudu.git` 브랜치 `nvcuda_accel_02`, 커밋 `5830c9cb`(2026-08-30) — 조사 시 얕은 클론 완료
- 워크스페이스에 `src/ocudu-cuda`로 병치 (기존 `src/ocudu`는 유지)

**C0에서 확인한 항목**
- CUDA 12.8로 WG 커널 컴파일 및 gNB 링크 성공
- `ENABLE_EXPORT=ON` + `CMAKE_POSITION_INDEPENDENT_CODE=ON`에서 CUDA 정적 라이브러리와 gNB 링크 성공
- 컨테이너의 GPU 컨텍스트 생성과 연산을 PHY 테스트로 확인. 실제 gNB 라이브 구동은 C2 이후 검증

## 5. 마일스톤

| 단계 | 내용 | Exit 게이트 | 상태 |
|---|---|---|---|
| C0 | **빌드 확정** — 별도 `src/ocudu-cuda`, `build-ocudu-cuda.sh`의 `ocudu-cuda-zmq-release` 빌드와 호환 패치 | gNB 링크 성공, 문서의 CUDA PHY 테스트 12개 통과, 버전 커밋 및 CUDA 전용 도움말 확인 | 완료 (호환 패치, 12/12) |
| C1 | **lock/감사 확장** — lock에 `git_sources[ocudu-cuda]`, `build_profiles[ocudu-cuda-zmq-release]` 추가. `run-ocudu-legacy-1x1.sh`에 `OCUDU_NATIVE_GNB_PROFILE={cpu,cuda}` 선택자와 lock 기반 커밋 검사. `source-evidence.json`에 `gnb_profile`, CUDA 아키/드라이버 기록 | `verify-workspace-lock.py` 통과. CPU 프로파일 게이트 **바이트 동일 무회귀**(렌더 결과·result=pass) | 완료 (CPU attach pass, 설정 5개 동일) |
| C2 | **Parity 라이브** — CUDA gNB로 1×1 legacy 게이트, 단 `expert_phy.*_acceleration_mode: disabled`, `ru_sdr.expert_cfg.low_phy_*: disabled` | attach+PDU+ping 3/3, strict counter 0, `verify-legacy-1x1-artifacts.py` 통과. 브로커 `process_latency_summary` p99가 CPU 프로파일 대비 ±5% | 완료: 1µs 통계, 3쌍 모두 ±5% 이내 |
| C3 | **경로별 활성화** — `low_phy_rx` → `low_phy_tx` → `pusch` → `pdsch(enabled)` → `prach` 순. 각 단계는 별 run | 각 단계 C2 게이트 재통과. KPI 패널(`OCUDU_NATIVE_GNB_METRICS=1`)의 UL/DL BLER·PUSCH SINR·MCS가 CPU 대비 BLER 차 ≤1%p, SINR 차 ≤0.5 dB(문서 기준 0.06 dB). gNB 로그의 late/dropped slot 0 | 전체 가속 대표 경로 통과(MPS). 최종 6단계 전체 재검증은 남음 |
| C4 | **rank-1 4×1 + Sionna + CUDA gNB 동시 구동** — `run-ocudu-sionna-rank1.sh`를 CUDA 프로파일로 | `live_ready`, y=Hx UL 4행 ≤1e-4(기존 기준), 세 GPU 프로세스 동시 구동 시 브로커 p99 < 1 ms 슬롯 유지 또는 초과분과 원인(nsys 타임라인) 기록 | 미착수 |
| C5 | **관측점 노출(선택)** — 상주 PUSCH의 등화 후 심볼/LLR을 device에서 읽는 실험 훅, 또는 `OCUDU_PUSCH_ACCELERATION_TIMING`으로 단계별 타이밍을 Web UI에 추가 | 1 run에서 device LLR 덤프와 CPU 디코더 재현 일치. Web UI에 GPU 단계 타이밍 패널 | 미착수 |

C2까지가 "교체해도 아무것도 안 깨진다"의 증명이고, C3부터가 실제 가속이다. C3의 `pdsch`는 디스크리트 정책 때문에 반드시 `enabled`로 강제해야 켜진다.

### C1 검증 결과 — 2026-09-08

- 기본값/명시적 CPU/CUDA 프로파일 모두 기존 렌더러 HEAD 기준 설정 5개와 바이트 동일. CPU/CUDA gNB의 legacy 설정 dry-run 및 CUDA 2-port no-core 설정 dry-run 통과.
- CPU lock: 기존 Git 소스 8개, CUDA lock: 승인 패치가 적용된 추가 소스까지 9개 통과. Debian 94개와 archive 3개 검증 유지.
- CPU 라이브 회귀: `20260908T113811Z`, attach/PDU/ping 3/3, `result=pass`. `tx_pulls=19171`, `rx_requests=20155`, `rx_starvations=1`, queue overflow/sequence gap/ZMQ error=0. 기존 gate는 starvation을 strict-realtime 성공으로 간주하지 않으며 C1도 strict-realtime을 주장하지 않음.
- 브로커 CTest 11/11, 프로파일 음성/양성 테스트 6개, 기존 PHY 로그 테스트 5개 및 CUDA provenance 변조 거부 self-test 통과.
- `builds/ocudu-cuda-zmq-release/`의 `c1-cpu-gate.log`, `c1-cuda-preflight.log`, `c1-cuda-provenance.json`, `c1-config-check.json`, `c1-result.json`에 검증 근거 저장. CPU 실행 증거는 `results/reports/ocudu-interop/20260908T113811Z/`에 보존.
- CUDA PHY 소스/바이너리는 C0 결과 그대로이며 14분 PHY 테스트는 반복하지 않음. C1 당시 CUDA 라이브 접속 및 가속 모드 제어는 미검증 상태였음. 후속 사용자 실행에서 15초 초기화 타임아웃을 수정. `auto` 실행 `20260908T115039Z`는 RRC 후 PUSCH CRC 실패(165 KO/1 OK)로 PDU 실패. 명시적 `OCUDU_NATIVE_GNB_ACCELERATION=disabled` 실행 `20260908T115306Z`는 CUDA 바이너리의 host PHY로 attach/PDU/ping 통과. 이후 PUSCH 가속 실패 원인은 아래와 같이 해결. C2/C3 전체 성능 게이트는 미완료.

### 가속 접속 실패 수정 — 2026-09-08

- 원인: gNB는 `pusch_channel_estimator_td_strategy=interpolate`, CFO compensation off가 기본이나 resident GPU PUSCH는 설정을 전달받지 못해 `average` 사용. CFO가 있는 채널에서 등화가 달라짐.
- 소스 수정: upper-PHY → accelerated factory → GPU demodulator로 시간 보간 enum 전달. 실제 적용 모드를 PHY 로그에 기록. CUDA 커널 및 CPU gNB 설정은 변경하지 않음.
- 재현: 400 Hz CFO·16QAM·15 kHz SCS·PRB offset 8·슬롯 변경 조건에서 CPU는 10/10 성공. GPU 평균 방식은 10/10 실패, 보간 설정 전달 후 CRC/페이로드 10/10 일치. 음성 대조군은 exit=1.
- 추가 환경변수 없이 `OCUDU_NATIVE_GNB_PROFILE=cuda` 실행 `20260908T121121Z`, `20260908T121232Z`가 연속 attach/PDU/ping 통과. PUSCH manifest는 `backend=CUDA resident_decode=true`; CPU fallback 경고 없음. PDSCH auto는 이 GPU에서 기존 host 정책 유지.
- broker starvations 8/5, overflow/gap/ZMQ errors=0. 첫 고정 실행의 PUSCH CRC는 OK 27/KO 10으로, CPU 동등 BLER나 실시간 성능을 주장하지 않음. 기존 C2/C3의 성능 기준은 별도 검증 대상.
- 현행 호환 패치 SHA256: `3ec929ccb5614b1ff91a059c09f05224ae764612852ecc0994806428e34211c7`. 기존 C0/C1 해시는 당시 아티팩트의 이력이며 현행 lock과 다름. 기존 12개+신규 CFO 회귀의 **13개 PHY 게이트 모두 통과 (883.18 s)**. 전체 PUSCH 48조건 및 strict 출력 검증 통과. 최종 결과·해시는 native `builds/ocudu-cuda-zmq-release/accelerated-fix-result.json`, 보존 CTest 로그는 `accelerated-fix-LastTest.log`에 기록.

## 6. 코드 변경 지점

| 파일 | 변경 |
|---|---|
| `scripts/native/bootstrap-workspace.sh` | `ocudu_cuda_build="${native_root}/builds/ocudu-cuda-zmq-release"` 블록 추가. `cmake_common` 재사용 + `-DENABLE_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=${OCUDU_NATIVE_CUDA_ARCH:-120}`. `--verify-only`에 CUDA 바이너리 존재 검사 |
| `scripts/native/native-workspace.lock.json` | `git_sources`에 ocudu-cuda 엔트리, `build_profiles`에 cuda 프로파일, `host_contract.cuda` 유지 |
| `scripts/native/verify-workspace-lock.py` | 새 엔트리 검증 |
| `scripts/native/run-ocudu-legacy-1x1.sh` | `OCUDU_NATIVE_GNB_PROFILE` 파싱 → `gnb` 경로 선택, `audited_ocudu_cuda` 해시, source-evidence에 프로파일 기록 |
| `scripts/native/run-ocudu-legacy-1x1-inner.sh` | `--gnb-binary` 인자. `OCUDU_*` 가속 env 훅 `unset`(R8) |
| `scripts/native/render-legacy-1x1-configs.py`, `render-sionna-rank1-configs.py`, `render-rank1-{2x1,4x1}-configs.py` | `OCUDU_NATIVE_GNB_ACCEL_*` env → `expert_phy` / `ru_sdr.expert_cfg` 가속 키 렌더. 미설정 시 **바이트 동일**(기존 메트릭 블록과 같은 규칙). 공용 헬퍼로 빼서 렌더러 4개가 공유 |
| `examples/native/ocudu/*.yaml` | 변경 없음 (가속 키는 렌더러가 붙임) |
| `scripts/native/verify-*-artifacts.py` | `gnb_profile`을 리포트에 기록, CUDA일 때 late-slot 카운트 검사 추가 |
| `create-ocudu-minwoo.sh` (홈) | 7단계 검증에 `nvcc` 아키 지원(`--list-gpu-arch`에 `sm_120`) 확인 |
| `scripts/web_ui/server.py`, `index.html` (C5) | GPU 단계 타이밍 패널 |
| `docs/live-gate-results.md` | CPU/CUDA 프로파일 결과 병기 |

## 7. 측정 계획

- **동일 run 쌍 비교**: 같은 fixture·같은 시드로 CPU 프로파일 1회, CUDA 프로파일 1회. 비교 지표는 KPI 패널 값(1초 리포트 60개 평균)과 브로커 `process_latency_summary`.
- **gNB 측 지표**: `OCUDU_PUSCH_ACCELERATION_TIMING=1`의 단계별 µs, gNB 로그 `late`/`dropped`, `du_report_period` 내 처리 시간.
- **GPU 측**: `nvidia-smi dmon`(sm/mem %), C4는 `nsys` 타임라인으로 브로커·Sionna·gNB 커널 인터리빙 확인.
- **판정 규칙**: 20 MHz 1-layer에서 GPU가 느린 것은 **예상된 결과**로 기록하고 실패로 치지 않는다. 실패는 (a) attach/PDU/ping 게이트 깨짐, (b) BLER/SINR 정합 이탈, (c) late slot 발생.

## 8. 열린 질문

1. CUDA 12.8 컴파일 실패 시 컨테이너를 CUDA 13으로 올릴지, WG에 12.x 호환 패치를 낼지.
2. 100 MHz 목표를 세울 경우 브로커(23040샘플/1 ms)의 확장이 선행 과제 — gNB 가속과 어느 쪽을 먼저 할지.
3. C5의 device LLR 노출은 WG의 "AI-RAN tensors" 인터페이스가 나오면 그것을 쓸지, 자체 훅을 만들지.
4. Sionna RT를 별도 GPU로 분리할 하드웨어 여부(R1).

## 참고

- 논문: [GPU-Resident CUDA Acceleration for OCUDU 5G PHY and O-RAN Fronthaul (arXiv 2608.04338)](https://arxiv.org/html/2608.04338v1)
- WG 레포: [cuda_accelerated_ocudu](https://gitlab.com/ocudu/work_groups/wg1_hw_accel/cuda_accelerated_ocudu) — `docs/phy_cuda_acceleration.md`, `lib/phy/cuda/README.md`
- 메인: [ocudu/ocudu](https://gitlab.com/ocudu/ocudu)
- DeepSig: [Building an Open Platform for AI-Native RAN with OCUDU](https://www.deepsig.ai/building-an-open-platform-for-ai-native-ran-with-ocudu/)
- 배경: [From srsRAN to OCUDU](https://srs.io/from-srsran-to-ocudu/), [OCUDU 26.04 press release](https://www.srsran.com/press_releases/srsran_becomes_ocudu/)
- 이 레포: `docs/plans/sionna-live-channel.md` (GPU placement), `RANK1_MILESTONES.md` (srsUE 제약·MCS 캡 근거), `scripts/native/README.md` (KPI 패널)

### C2 반복 비교와 C3 초기 측정 (2026-09-08)

환경: RTX 5090, 23.04 MS/s, rank-1 1×1, CUDA 채널 브로커;
단일 0-sample/-3 dB TDL tap → 0.125 rad phase → 125 Hz CFO.
C2는 기존 15초 fixture, C3 KPI는 별도 90초 실행에서 1초 scheduler report 60개를 수집했다.

- C2 `c2-20260908T125913Z`: CPU p99(gNB/UE) 81/81, 82/81, 83/83 µs;
  CUDA-disabled 80/84, 81/81, 81/82 µs. 3쌍 모두 ±5% 이내이며 접속/PDU/핑과
  overflow/gap/ZMQ-error 검사를 통과했다. Starvation은 별도 기록하며 strict realtime을 주장하지 않는다.
- 최초 5µs histogram 비교는 1쌍에서 -5.88%로 실패했다. 해당 원본을 보존했고,
  80µs 부근의 ±5% 비교가 가능하도록 통계 해상도를 1µs로 바꾼 뒤 3쌍을 다시 측정했다.
- C3 `c3-20260908T130332Z`: CPU 및 6단계 모두 90초 접속/트래픽/60-report 수집을 통과했다.
  RX/TX까지 CPU 대비 SINR 차이는 0.004/-0.062 dB였으나, PUSCH 이후 약 +1.6 dB로 기준을 넘었다.
  동기/UCI 경로가 EVM 환산값을 post-equalization SINR에 대입하는 오류를 확인하고 회귀 테스트를 추가했다.
- 이 초기 C3 캠페인의 broker p99는 CPU 82/82 µs, 가속 단계 113–124/127–139 µs였다.
  1 ms보다 짧지만 기존 ±5% 비교 기준은 통과하지 못했다. 이 결과를 성능 동등성으로 해석하지 않는다.
- C4의 Sionna 동시 실행은 현재 `AGENT_GOAL.md`의 Sionna RT 제외 조건과 충돌하므로,
  명시적인 목표 범위 변경 없이 시작하지 않는다.

### 최종 전체 가속 비교

SINR 동기 경로 수정 후 `c3-20260908T133003Z`에서 MPS를 사용한 CPU/전체가속
90초 비교를 수행했다. 접속/PDU/핑, 60-report 수집, backend 및 무결성 검사가 통과했고,
UL/DL BLER 차이 0%p, SINR 차이 +0.336 dB, MCS 차이 UL +0.75 / DL 0이었다.
브로커 p99는 CPU82/82µs, CUDA83/82µs로 +1.22%/0%였다. 환경/채널 조건은 위와 같다.
MPS 서버 및 동시 gNB/브로커 클라이언트 증거는 `mps-20260908T133003.211558Z`에 있다.

이는 `all` 대표 경로의 최종 통과다. 마지막 수정 후 6단계 전체 캠페인과 전체14개 PHY
테스트를 반복하지 않았으므로 C3 전체 인증은 아직 완료로 표시하지 않는다. 수정 관련
PUSCH CFO/SINR 및 PDSCH 테스트3개는 통과했고, 수정 전 동작의 음성 대조군은 실패했다.
