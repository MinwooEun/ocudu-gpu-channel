#include <cuda_runtime_api.h>
#include <cstdio>
int main() {
  int integrated=-1, mapped=-1;
  auto a=cudaDeviceGetAttribute(&integrated,cudaDevAttrIntegrated,0);
  auto b=cudaDeviceGetAttribute(&mapped,cudaDevAttrCanMapHostMemory,0);
  std::printf("{\"integrated\":%d,\"can_map_host_memory\":%d,\"cuda_status_integrated\":%d,\"cuda_status_mapping\":%d}\n",integrated,mapped,int(a),int(b));
  return (a==cudaSuccess && b==cudaSuccess) ? 0 : 1;
}
