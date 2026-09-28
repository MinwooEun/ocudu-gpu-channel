// S9: does a GPU touch of pageable host memory make the next CPU memcpy of it
// slower on GB10? Mirrors the broker: ring -> input window (CPU write, then GPU
// reads it: direct_in), and output row (GPU writes it: direct) -> RX ring (CPU read).
#include <cuda_runtime.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <vector>

__global__ void gpu_read(const float2* p, size_t n, float* sink) {
  float acc = 0;
  for (size_t i = blockIdx.x * blockDim.x + threadIdx.x; i < n; i += gridDim.x * blockDim.x) acc += p[i].x;
  if (acc == 12345.f) *sink = acc;
}
__global__ void gpu_write(float2* p, size_t n) {
  for (size_t i = blockIdx.x * blockDim.x + threadIdx.x; i < n; i += gridDim.x * blockDim.x) p[i] = make_float2(i, -1.f * i);
}
static double us(std::chrono::steady_clock::time_point a, std::chrono::steady_clock::time_point b) {
  return std::chrono::duration<double, std::micro>(b - a).count();
}
static void report(const char* name, std::vector<double>& v) {
  std::sort(v.begin(), v.end());
  printf("%-44s p50=%7.2f p90=%7.2f p99=%7.2f us\n", name, v[v.size() / 2], v[v.size() * 9 / 10], v[v.size() * 99 / 100]);
}
int main(int argc, char** argv) {
  const size_t n = argc > 1 ? strtoul(argv[1], nullptr, 10) : 122880;  // samples (100 MHz, 1 ms)
  const int iters = 2000;
  std::vector<float2> ring(n), win(n), row(n), rxring(n);
  for (size_t i = 0; i < n; ++i) ring[i] = make_float2(i, i);
  float* sink; cudaMalloc(&sink, 4);
  cudaStream_t s; cudaStreamCreate(&s);
  printf("samples=%zu bytes=%zu\n", n, n * sizeof(float2));
  for (int mode = 0; mode < 2; ++mode) {  // 0 = CPU only, 1 = GPU touches the buffer between CPU copies
    std::vector<double> rd, ps;
    for (int it = 0; it < iters; ++it) {
      // "read_us": ring -> input window (CPU writes win)
      auto a = std::chrono::steady_clock::now();
      memcpy(win.data(), ring.data(), n * sizeof(float2));
      auto b = std::chrono::steady_clock::now();
      if (mode) {  // direct_in: GPU reads win; direct: GPU writes row
        gpu_read<<<48, 256, 0, s>>>(win.data(), n, sink);
        gpu_write<<<48, 256, 0, s>>>(row.data(), n);
      }
      cudaStreamSynchronize(s);
      // "push_us": output row -> RX ring (CPU reads row)
      auto c = std::chrono::steady_clock::now();
      memcpy(rxring.data(), row.data(), n * sizeof(float2));
      auto d = std::chrono::steady_clock::now();
      if (it >= 100) { rd.push_back(us(a, b)); ps.push_back(us(c, d)); }
    }
    report(mode ? "gpu-touched: ring->window (CPU write)" : "cpu-only:    ring->window (CPU write)", rd);
    report(mode ? "gpu-touched: row->rx ring (CPU read)" : "cpu-only:    row->rx ring (CPU read)", ps);
  }
  printf("err=%s\n", cudaGetErrorString(cudaGetLastError()));
}
