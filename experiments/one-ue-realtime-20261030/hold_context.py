"""Idle reservation, released before measurement; no CUDA kernels submitted."""
import ctypes,os,time,sys
c=ctypes.CDLL('/usr/local/cuda/lib64/libcudart.so');assert c.cudaSetDevice(0)==0
ptr=ctypes.c_void_p();assert c.cudaMalloc(ctypes.byref(ptr),1)==0
print(os.getpid(),flush=True)
try:
 for _ in range(1200):time.sleep(.2)
finally:c.cudaFree(ptr)
