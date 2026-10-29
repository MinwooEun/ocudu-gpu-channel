ocudu-gpu-channel 패치: prepare() 업로드와 첫 슬롯의 경쟁 조건 수정
======================================================================

한 줄 요약
----------
GPU를 다른 프로세스(예: Sionna)와 같이 쓸 때, 채널 에뮬레이터의 한 링크가
시작하자마자 gain 0 상태에 갇히고 이후 채널 갱신을 무시할 수 있는 버그를 고칩니다.
UE가 가끔 안 붙는 문제의 원인일 가능성이 있습니다(확정은 아님).

무엇이 문제였나
---------------
src/cuda_backend.cu 의 prepare() 는 링크 초기 상태(device_link_states),
행 오프셋(device_row_begin), correlation 그룹을 cudaMemcpy 로 GPU에 올립니다.

- 이 cudaMemcpy 는 기본(legacy) 스트림에서 돌고, 원본이 일반(pageable) 메모리라
  함수가 돌아와도 실제 전송이 아직 안 끝났을 수 있습니다.
- 슬롯 처리는 sp.stream 에서 도는데, 이 스트림은 cudaStreamNonBlocking 이라
  기본 스트림 작업이 끝나기를 기다리지 않습니다.
- GPU가 한가하면 전송이 금방 끝나서 문제가 안 보입니다. 다른 CUDA 프로세스가
  GPU를 쓰고 있으면 전송이 늦어지고, 첫 슬롯이 전부 0인 상태(gain=0, has_tdl=0)를
  읽습니다. 그 링크는 이후 gain/phase/profile 갱신(Sionna 갱신 포함)을 건너뛰고,
  늦게 도착한 전송이 갱신된 상태를 다시 덮어씁니다.
- 결과: 오류 메시지 없이 그 링크의 신호가 사라지거나 틀린 계수로 남습니다.

실제 관측과의 연결 (추정)
------------------------
results/logs/ocudu-multi-gnb/20260928T130208Z 에서 ue0 이 PRACH 를 6번 넘게
보냈고 브로커는 ue0 샘플을 정상적으로 주고받았는데, gNB 로그에는 ue0 의
프리앰블(idx=0)이 한 번도 검출되지 않았습니다(ue1 의 idx=1 만 검출).
브로커와 Sionna 가 같은 RTX 5090 을 쓰는 구성이라 위 버그의 발생 조건과 같습니다.
그 실행에서 링크가 실제로 gain 0 이었는지는 로그에 남아 있지 않아 직접 확인은 못 했습니다.

무엇을 바꿨나
-------------
세 업로드를 sp.stream 에서 cudaMemcpyAsync 로 보내고, prepare() 끝에서
cudaStreamSynchronize(sp.stream) 로 전송 완료를 기다립니다. 변경은 이 파일 하나,
세 군데뿐이고 슬롯 처리 경로와 출력 값은 바뀌지 않습니다.

검증
----
- 우리 트리(같은 코드 계열)에서: 다른 프로세스가 1-block busy 커널로 GPU를 계속
  점유하는 조건에서 ctest 전체가 수정 전 0/30, 수정 후 30/30 통과
  (실패하던 테스트: matrix_profile_history "long-delay CUDA echo must match CPU",
  processing). GPU가 비었을 때는 수정 전후 모두 통과.
- 이 패치 파일: 현재 /home/hyunsoo/OCUDU/ocudu-gpu-channel/src/cuda_backend.cu 에
  git apply --check 통과, 적용한 사본으로 전체 빌드 통과(CUDA arch 120, Release).
  라이브 실행이 GPU를 쓰고 있어서 이 트리로 GPU 테스트는 아직 안 돌렸습니다.

적용 방법
---------
  cd /home/hyunsoo/OCUDU/ocudu-gpu-channel
  git apply --check 0001-cuda-prepare-stream-race-fix.patch   # 먼저 확인
  git am 0001-cuda-prepare-stream-race-fix.patch              # 커밋으로 적용
  # 또는 커밋 없이: git apply 0001-cuda-prepare-stream-race-fix.patch

그다음 평소처럼 브로커를 다시 빌드하세요
(예: /home/hyunsoo/OCUDU/builds/ocudu-gpu-channel/cuda-release 에서 cmake --build .).

적용 후 확인 권장
-----------------
1. GPU가 비었을 때 ctest.
2. 가능하면 GPU를 같이 쓰는 조건(Sionna 가 돌 때)에서 ctest 몇 번 반복:
   수정 전에는 matrix_profile_history 가 간헐적으로 실패하고 수정 후에는 통과해야 합니다.
3. multi-gNB/Sionna 라이브 실행을 여러 번 돌려 UE attach 실패율 비교.

패치 파일 sha256:
  cf1a5c6e62ef3cf96cb79624eb465d1c772ab7e0282bf3667f643b1c28f8a907
