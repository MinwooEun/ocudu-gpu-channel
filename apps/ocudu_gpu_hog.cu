// A synthetic GPU tenant for scheduling experiments (ROBOT_FIGHT_MILESTONES.md
// R5a): it keeps the GPU busy with back-to-back kernels of a chosen length so
// a broker sharing the device sees what a Sionna solve, a CUDA gNB or any
// other context does to its kernel start times. Nothing about it is
// representative of real work except the one property that matters here --
// the SMs are occupied when the broker's slot kernel arrives.
//
// Without MPS the hog has its own context and the GPU time-slices between it
// and the broker; with MPS (CUDA_MPS_PIPE_DIRECTORY set for both) the two
// share a context and the broker's stream priority decides who goes first.
//
//   ocudu-gpu-hog --duration-s 120 --kernel-us 2000 --duty 1.0 [--blocks N] [--threads 256]
//
// duty < 1 sleeps between kernels for (1 - duty) / duty of the kernel length,
// so the fraction of wall time the hog occupies the GPU is about `duty`.
#include <cuda_runtime.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

namespace {

__global__ void spin_kernel(long long cycles, float* sink)
{
  const long long start = clock64();
  float acc = 0.0f;
  while (clock64() - start < cycles) {
    acc = acc * 0.999f + static_cast<float>(threadIdx.x) * 1e-3f;
  }
  if (acc == -1.0f) {
    sink[blockIdx.x] = acc;  // never true; keeps the loop from being optimised away
  }
}

void check(cudaError_t status, const char* what)
{
  if (status != cudaSuccess) {
    std::fprintf(stderr, "event=fatal what=%s error=\"%s\"\n", what, cudaGetErrorString(status));
    std::exit(1);
  }
}

}  // namespace

int main(int argc, char** argv)
{
  double duration_s = 60.0;
  double kernel_us = 2000.0;
  double duty = 1.0;
  int blocks = 0;
  int threads = 256;
  double report_s = 5.0;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto next = [&](double& into) {
      if (i + 1 >= argc) {
        std::fprintf(stderr, "missing value for %s\n", arg.c_str());
        std::exit(2);
      }
      into = std::atof(argv[++i]);
    };
    if (arg == "--duration-s") {
      next(duration_s);
    } else if (arg == "--kernel-us") {
      next(kernel_us);
    } else if (arg == "--duty") {
      next(duty);
    } else if (arg == "--report-s") {
      next(report_s);
    } else if (arg == "--blocks") {
      double v = 0;
      next(v);
      blocks = static_cast<int>(v);
    } else if (arg == "--threads") {
      double v = 0;
      next(v);
      threads = static_cast<int>(v);
    } else {
      std::fprintf(stderr, "usage: %s [--duration-s S] [--kernel-us US] [--duty 0..1] [--blocks N] [--threads N]\n",
                   argv[0]);
      return 2;
    }
  }
  if (duty <= 0.0 || duty > 1.0 || kernel_us <= 0.0 || duration_s <= 0.0) {
    std::fprintf(stderr, "invalid arguments\n");
    return 2;
  }

  int device = 0;
  check(cudaGetDevice(&device), "cudaGetDevice");
  cudaDeviceProp prop{};
  check(cudaGetDeviceProperties(&prop, device), "cudaGetDeviceProperties");
  int clock_khz = 0;
  check(cudaDeviceGetAttribute(&clock_khz, cudaDevAttrClockRate, device), "cudaDevAttrClockRate");
  if (blocks <= 0) {
    // Two blocks per SM: enough to occupy every SM even while one block is
    // being scheduled out, not so many that a single kernel outlives its
    // requested length by queueing.
    blocks = 2 * prop.multiProcessorCount;
  }
  const long long cycles = static_cast<long long>(kernel_us * 1e-6 * clock_khz * 1e3);
  float* sink = nullptr;
  check(cudaMalloc(&sink, sizeof(float) * static_cast<std::size_t>(blocks)), "cudaMalloc");
  cudaStream_t stream = nullptr;
  check(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking), "cudaStreamCreate");
  const char* mps = std::getenv("CUDA_MPS_PIPE_DIRECTORY");
  std::printf("event=hog_start device=%d name=\"%s\" sms=%d clock_khz=%d blocks=%d threads=%d kernel_us=%.0f "
              "cycles=%lld duty=%.2f duration_s=%.0f mps=%s\n",
              device, prop.name, prop.multiProcessorCount, clock_khz, blocks, threads, kernel_us, cycles, duty,
              duration_s, mps != nullptr ? "on" : "off");
  std::fflush(stdout);

  using clock = std::chrono::steady_clock;
  const auto t0 = clock::now();
  auto last_report = t0;
  long long launched = 0;
  long long launched_at_report = 0;
  double busy_us = 0.0;
  std::vector<double> lengths;
  const double idle_us = kernel_us * (1.0 - duty) / duty;
  while (std::chrono::duration<double>(clock::now() - t0).count() < duration_s) {
    const auto k0 = clock::now();
    spin_kernel<<<blocks, threads, 0, stream>>>(cycles, sink);
    check(cudaGetLastError(), "launch");
    check(cudaStreamSynchronize(stream), "sync");
    const double took = std::chrono::duration<double, std::micro>(clock::now() - k0).count();
    ++launched;
    busy_us += took;
    lengths.push_back(took);
    if (idle_us > 0.0) {
      std::this_thread::sleep_for(std::chrono::microseconds(static_cast<long long>(idle_us)));
    }
    if (std::chrono::duration<double>(clock::now() - last_report).count() >= report_s) {
      std::sort(lengths.begin(), lengths.end());
      const double p50 = lengths[lengths.size() / 2];
      const double p99 = lengths[std::min(lengths.size() - 1, static_cast<std::size_t>(lengths.size() * 0.99))];
      const double elapsed = std::chrono::duration<double>(clock::now() - t0).count();
      std::printf("event=hog t=%.0f launched=%lld rate_per_s=%.1f kernel_p50_us=%.0f kernel_p99_us=%.0f "
                  "gpu_share=%.2f\n",
                  elapsed, launched, (launched - launched_at_report) / report_s, p50, p99,
                  busy_us / (elapsed * 1e6));
      std::fflush(stdout);
      launched_at_report = launched;
      lengths.clear();
      last_report = clock::now();
    }
  }
  std::printf("event=hog_stop launched=%lld busy_s=%.1f\n", launched, busy_us / 1e6);
  cudaStreamDestroy(stream);
  cudaFree(sink);
  return 0;
}
