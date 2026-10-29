#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace ocg {

// Exact call/slot counts with elapsed-time percentiles grouped into 1 us
// buckets. The producer thread is the sole writer, so no synchronization is
// needed here.
struct TimingDistribution {
  static constexpr std::size_t kOverflowBucket = 20'000;

  std::vector<std::uint64_t> histogram =
      std::vector<std::uint64_t>(kOverflowBucket + 1, 0);
  std::uint64_t count = 0;
  std::uint64_t deadline_misses = 0;
  double max_us = 0.0;
  double p95_us = 0.0;
  double p99_us = 0.0;

  double percentile(double quantile) const
  {
    if (count == 0) return 0.0;
    const auto target = static_cast<std::uint64_t>(
        std::ceil(quantile * static_cast<double>(count)));
    std::uint64_t cumulative = 0;
    for (std::size_t bucket = 0; bucket < histogram.size(); ++bucket) {
      cumulative += histogram[bucket];
      if (cumulative >= target) {
        return bucket == kOverflowBucket ? max_us : static_cast<double>(bucket + 1);
      }
    }
    return max_us;
  }

  void observe(double elapsed_us, double deadline_us)
  {
    ++count;
    if (deadline_us > 0.0 && elapsed_us > deadline_us) {
      ++deadline_misses;
    }
    max_us = std::max(max_us, elapsed_us);
    const auto bucket = elapsed_us >= static_cast<double>(kOverflowBucket)
                            ? kOverflowBucket
                            : static_cast<std::size_t>(
                                  std::max(0.0, std::floor(elapsed_us)));
    ++histogram[bucket];
    if (count == 1 || count % 50 == 0) {
      p95_us = percentile(0.95);
      p99_us = percentile(0.99);
    }
  }
};

// Reconstructs fixed-duration nominal slots from arbitrary contiguous
// process_superposition() fragments. When a call crosses a slot boundary, its
// measured wall time is apportioned by the number of samples on each side of
// that boundary. This preserves the full measured call cost, but is explicitly
// an estimate because fixed CUDA launch overhead cannot be physically split.
class ReceiverTimingAccumulator {
public:
  ReceiverTimingAccumulator(std::uint64_t nominal_samples, std::uint64_t sample_rate_hz) :
    nominal_samples_(std::max<std::uint64_t>(1, nominal_samples)),
    sample_rate_hz_(std::max<std::uint64_t>(1, sample_rate_hz))
  {
  }

  void observe(std::uint64_t samples, double elapsed_us)
  {
    if (samples == 0) return;

    const double call_deadline_us =
        static_cast<double>(samples) * 1'000'000.0 / static_cast<double>(sample_rate_hz_);
    calls.observe(elapsed_us, call_deadline_us);

    const bool aligned_full_call = pending_samples == 0 && samples == nominal_samples_;
    if (samples != nominal_samples_) {
      ++fragment_calls;
      fragment_samples += samples;
      fragment_min_samples = std::min(fragment_min_samples, samples);
      fragment_max_samples = std::max(fragment_max_samples, samples);
    }

    std::uint64_t remaining = samples;
    double attributed_us = 0.0;
    while (remaining > 0) {
      const std::uint64_t needed = nominal_samples_ - pending_samples;
      const std::uint64_t take = std::min(remaining, needed);
      const bool final_piece = take == remaining;
      const double piece_us = final_piece
                                  ? elapsed_us - attributed_us
                                  : elapsed_us * static_cast<double>(take) /
                                        static_cast<double>(samples);
      attributed_us += piece_us;
      pending_samples += take;
      pending_estimated_us += piece_us;
      pending_fragmented = pending_fragmented || !aligned_full_call;
      remaining -= take;

      if (pending_samples == nominal_samples_) {
        const double nominal_deadline_us =
            static_cast<double>(nominal_samples_) * 1'000'000.0 /
            static_cast<double>(sample_rate_hz_);
        nominal_slots.observe(pending_estimated_us, nominal_deadline_us);
        latest_nominal_estimated_us = pending_estimated_us;
        if (pending_fragmented) ++fragmented_nominal_slots;
        pending_samples = 0;
        pending_estimated_us = 0.0;
        pending_fragmented = false;
      }
    }
  }

  std::uint64_t nominal_samples() const { return nominal_samples_; }
  std::uint64_t sample_rate_hz() const { return sample_rate_hz_; }
  double nominal_deadline_us() const
  {
    return static_cast<double>(nominal_samples_) * 1'000'000.0 /
           static_cast<double>(sample_rate_hz_);
  }
  std::uint64_t fragment_min() const
  {
    return fragment_calls == 0 ? 0 : fragment_min_samples;
  }

  TimingDistribution calls;
  TimingDistribution nominal_slots;
  std::uint64_t pending_samples = 0;
  double pending_estimated_us = 0.0;
  double latest_nominal_estimated_us = 0.0;
  std::uint64_t fragment_calls = 0;
  std::uint64_t fragment_samples = 0;
  std::uint64_t fragment_min_samples = std::numeric_limits<std::uint64_t>::max();
  std::uint64_t fragment_max_samples = 0;
  std::uint64_t fragmented_nominal_slots = 0;

private:
  std::uint64_t nominal_samples_;
  std::uint64_t sample_rate_hz_;
  bool pending_fragmented = false;
};

} // namespace ocg
