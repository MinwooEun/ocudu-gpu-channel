// A synthetic GPU tenant for scheduling experiments (ROBOT_FIGHT_MILESTONES.md
// R5a/R5b): it keeps the GPU busy with back-to-back kernels of a chosen length
// so a broker sharing the device sees what a Sionna solve, a CUDA gNB or any
// other context does to its kernel start times. Nothing about it is
// representative of real work except the one property that matters here --
// the SMs are occupied when the broker's slot kernel arrives.
//
// Without MPS the hog has its own context and the GPU time-slices between it
// and the broker; with MPS (CUDA_MPS_PIPE_DIRECTORY set for both) the two
// share a context and the broker's stream priority decides who goes first.
//
//   ocudu-gpu-hog --duration-s 120 --kernel-us 2000 --duty 1.0 [--blocks N] [--threads 256]
//                 [--streams S] [--queue-depth K]
//
// duty < 1 sleeps between kernels for (1 - duty) / duty of the kernel length,
// so the fraction of wall time the hog occupies the GPU is about `duty`.
//
// --streams S / --queue-depth K (R5b) keep K kernels queued on each of S
// streams instead of one synchronous kernel at a time. Inside a shared MPS
// context a default-priority kernel from another client lines up behind
// everything already queued (up to S*K*kernel_us), while a high-priority
// stream only waits for the blocks that are running (about one kernel_us):
// the queue depth is the lever that separates a protected broker from a
// plain one without changing how long each hog kernel runs.
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

using clock_type = std::chrono::steady_clock;

// One kernel queued on a stream: the event that marks its completion and the
// host time it was launched, so the queue latency (launch -> retire) can be
// reported. That latency is what a default-priority kernel from another
// client of the same MPS context also experiences.
struct Slot {
  cudaEvent_t done = nullptr;
  clock_type::time_point launched_at{};
};

struct StreamState {
  cudaStream_t stream = nullptr;
  std::vector<Slot> slots;
  std::size_t head = 0;  // oldest in-flight slot
  std::size_t inflight = 0;
  clock_type::time_point next_launch_allowed{};
};

}  // namespace

int main(int argc, char** argv)
{
  double duration_s = 60.0;
  double kernel_us = 2000.0;
  double duty = 1.0;
  int blocks = 0;
  int threads = 256;
  int streams = 1;
  int queue_depth = 1;
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
    auto next_int = [&](int& into) {
      double v = 0;
      next(v);
      into = static_cast<int>(v);
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
      next_int(blocks);
    } else if (arg == "--threads") {
      next_int(threads);
    } else if (arg == "--streams") {
      next_int(streams);
    } else if (arg == "--queue-depth") {
      next_int(queue_depth);
    } else {
      std::fprintf(stderr,
                   "usage: %s [--duration-s S] [--kernel-us US] [--duty 0..1] [--blocks N] [--threads N] "
                   "[--streams S] [--queue-depth K]\n",
                   argv[0]);
      return 2;
    }
  }
  if (duty <= 0.0 || duty > 1.0 || kernel_us <= 0.0 || duration_s <= 0.0 || streams < 1 || queue_depth < 1 ||
      streams > 64 || queue_depth > 1024) {
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
  std::vector<StreamState> states(static_cast<std::size_t>(streams));
  for (auto& state : states) {
    check(cudaStreamCreateWithFlags(&state.stream, cudaStreamNonBlocking), "cudaStreamCreate");
    state.slots.resize(static_cast<std::size_t>(queue_depth));
    for (auto& slot : state.slots) {
      check(cudaEventCreateWithFlags(&slot.done, cudaEventDisableTiming), "cudaEventCreate");
    }
    state.next_launch_allowed = clock_type::now();
  }
  const char* mps = std::getenv("CUDA_MPS_PIPE_DIRECTORY");
  std::printf("event=hog_start device=%d name=\"%s\" sms=%d clock_khz=%d blocks=%d threads=%d kernel_us=%.0f "
              "cycles=%lld duty=%.2f duration_s=%.0f streams=%d queue_depth=%d mps=%s\n",
              device, prop.name, prop.multiProcessorCount, clock_khz, blocks, threads, kernel_us, cycles, duty,
              duration_s, streams, queue_depth, mps != nullptr ? "on" : "off");
  std::fflush(stdout);

  const auto t0 = clock_type::now();
  auto last_report = t0;
  long long launched = 0;
  long long completed = 0;
  long long completed_at_report = 0;
  std::vector<double> latencies;  // launch -> retire, host clock, µs
  const double idle_us = kernel_us * (1.0 - duty) / duty;
  const auto idle = std::chrono::microseconds(static_cast<long long>(idle_us));
  std::size_t inflight_sum = 0;
  long long inflight_samples = 0;
  while (std::chrono::duration<double>(clock_type::now() - t0).count() < duration_s) {
    bool progressed = false;
    const auto now = clock_type::now();
    for (auto& state : states) {
      // Retire finished kernels from the head of the stream's queue.
      while (state.inflight > 0) {
        Slot& slot = state.slots[state.head];
        const cudaError_t status = cudaEventQuery(slot.done);
        if (status == cudaErrorNotReady) {
          break;
        }
        check(status, "cudaEventQuery");
        latencies.push_back(std::chrono::duration<double, std::micro>(now - slot.launched_at).count());
        state.head = (state.head + 1) % state.slots.size();
        --state.inflight;
        ++completed;
        progressed = true;
        if (idle_us > 0.0) {
          state.next_launch_allowed = now + idle;
        }
      }
      // Keep the queue full.
      while (state.inflight < state.slots.size() && now >= state.next_launch_allowed) {
        const std::size_t tail = (state.head + state.inflight) % state.slots.size();
        Slot& slot = state.slots[tail];
        spin_kernel<<<blocks, threads, 0, state.stream>>>(cycles, sink);
        check(cudaGetLastError(), "launch");
        check(cudaEventRecord(slot.done, state.stream), "cudaEventRecord");
        slot.launched_at = clock_type::now();
        ++state.inflight;
        ++launched;
        progressed = true;
        if (idle_us > 0.0) {
          break;  // one launch per idle period when duty < 1
        }
      }
      inflight_sum += state.inflight;
    }
    ++inflight_samples;
    if (!progressed) {
      // Nothing to launch or retire: wait for the oldest kernel instead of
      // burning a host core (the pinned broker cores may be neighbours).
      StreamState& first = states.front();
      if (first.inflight > 0) {
        check(cudaEventSynchronize(first.slots[first.head].done), "cudaEventSynchronize");
      } else {
        std::this_thread::sleep_for(std::chrono::microseconds(20));
      }
    }
    if (std::chrono::duration<double>(clock_type::now() - last_report).count() >= report_s) {
      double p50 = 0.0;
      double p99 = 0.0;
      if (!latencies.empty()) {
        std::sort(latencies.begin(), latencies.end());
        p50 = latencies[latencies.size() / 2];
        p99 = latencies[std::min(latencies.size() - 1, static_cast<std::size_t>(latencies.size() * 0.99))];
      }
      const double elapsed = std::chrono::duration<double>(clock_type::now() - t0).count();
      const double mean_inflight =
          inflight_samples > 0 ? static_cast<double>(inflight_sum) / static_cast<double>(inflight_samples) : 0.0;
      std::printf("event=hog t=%.0f launched=%lld completed=%lld rate_per_s=%.1f kernel_p50_us=%.0f "
                  "kernel_p99_us=%.0f queued_mean=%.2f gpu_share=%.2f\n",
                  elapsed, launched, completed, (completed - completed_at_report) / report_s, p50, p99,
                  mean_inflight, std::min(1.0, completed * kernel_us / (elapsed * 1e6)));
      std::fflush(stdout);
      completed_at_report = completed;
      latencies.clear();
      inflight_sum = 0;
      inflight_samples = 0;
      last_report = clock_type::now();
    }
  }
  for (auto& state : states) {
    check(cudaStreamSynchronize(state.stream), "final sync");
  }
  std::printf("event=hog_stop launched=%lld completed=%lld\n", launched, completed);
  for (auto& state : states) {
    for (auto& slot : state.slots) {
      cudaEventDestroy(slot.done);
    }
    cudaStreamDestroy(state.stream);
  }
  cudaFree(sink);
  return 0;
}
