#!/bin/bash
# Local S2: apply the GPU DL front end to the Spark tree and rebuild srsue (build-s1) + the parity test.
set -e
cd /workspace/gpuch/s4
python3 edit-s2.py srsRAN_4G-s4
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64
cd build-s1
cmake -S ../srsRAN_4G-s4 -B . -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS=-g -DCMAKE_CXX_FLAGS=-g \
  -DENABLE_ZEROMQ=ON -DENABLE_UHD=OFF -DENABLE_SOAPYSDR=ON -DENABLE_SRSENB=OFF -DENABLE_SRSEPC=OFF \
  -DENABLE_TESTS=OFF -DENABLE_GUI=OFF -DSRSRAN_LDPC_SIMDE=ON -DENABLE_WERROR=OFF \
  -DSRSRAN_LDPC_CUDA=ON -DSRSRAN_LDPC_CUDA_ROOT=/workspace/ocudu-spark/src/ocudu-cuda-d10/lib/phy/cuda \
  -DSRSRAN_LDPC_CUDA_LIB=/workspace/ocudu-spark/builds/d10-cuda-patched-sm121/lib/phy/cuda/libocudu_phy_cuda.a > cmake-s2.log 2>&1 || { tail -30 cmake-s2.log; exit 1; }
grep -n "SRSRAN_LDPC_CUDA on\|CUDA" cmake-s2.log | head -5
make -j10 srsue > build-s2.log 2>&1; echo "exit=$?" >> build-s2.log
tail -1 build-s2.log; grep -n -B2 -A6 "error" build-s2.log | head -60
cd /workspace/gpuch/s4; S=srsRAN_4G-s4; B=build-s1
gcc -O2 -g -o ue_dl_cuda_test ue_dl_cuda_test.c -I$S/lib/include -I$B/lib/include $B/lib/src/phy/libsrsran_phy.a /workspace/ocudu-spark/builds/d10-cuda-patched-sm121/lib/phy/cuda/libocudu_phy_cuda.a -L/usr/local/cuda/lib64 -lcudart -lcuda -lnvrtc -lcufft -lfftw3f -lm -lpthread -lstdc++ 2>&1 | grep -v warning | head -10
ls -la ue_dl_cuda_test $B/srsue/src/srsue
