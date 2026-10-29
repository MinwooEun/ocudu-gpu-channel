#include "ocudu_gpu_channel/latency.h"
#include <algorithm>
#include <cmath>

namespace ocg {

void LatencyRecorder::add(std::chrono::nanoseconds value)
{
  samples_ns_.push_back(static_cast<std::uint64_t>(value.count()));
}

LatencySummary LatencyRecorder::summarize() const
{
  LatencySummary summary;
  if (samples_ns_.empty()) {
    return summary;
  }

  auto sorted = samples_ns_;
  std::sort(sorted.begin(), sorted.end());
  auto percentile = [&](double p) {
    const double idx = std::ceil((p / 100.0) * static_cast<double>(sorted.size())) - 1.0;
    const auto clamped = static_cast<std::size_t>(std::clamp(idx, 0.0, static_cast<double>(sorted.size() - 1)));
    return static_cast<double>(sorted[clamped]) / 1000.0;
  };

  summary.count = sorted.size();
  summary.p50_us = percentile(50.0);
  summary.p95_us = percentile(95.0);
  summary.p99_us = percentile(99.0);
  summary.p999_us = percentile(99.9);
  summary.max_us = static_cast<double>(sorted.back()) / 1000.0;
  return summary;
}

void LatencyRecorder::clear()
{
  samples_ns_.clear();
}

std::string feasibility_color(double p99_added_us, double slot_duration_us, bool stable)
{
  if (!stable || p99_added_us > slot_duration_us) {
    return "red";
  }
  if (p99_added_us <= slot_duration_us * 0.25) {
    return "green";
  }
  return "yellow";
}

double nr_slot_duration_us(unsigned scs_khz)
{
  if (scs_khz == 0 || scs_khz % 15 != 0) {
    return 1000.0;
  }
  unsigned ratio = scs_khz / 15;
  return 1000.0 / static_cast<double>(ratio);
}

} // namespace ocg
