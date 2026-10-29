#pragma once

#include <chrono>
#include <cstdint>
#include <string>
#include <vector>

namespace ocg {

struct LatencySummary {
  std::uint64_t count = 0;
  double p50_us = 0.0;
  double p95_us = 0.0;
  double p99_us = 0.0;
  double p999_us = 0.0;
  double max_us = 0.0;
};

class LatencyRecorder {
public:
  void add(std::chrono::nanoseconds value);
  LatencySummary summarize() const;
  void clear();

private:
  std::vector<std::uint64_t> samples_ns_;
};

std::string feasibility_color(double p99_added_us, double slot_duration_us, bool stable);
double nr_slot_duration_us(unsigned scs_khz);

} // namespace ocg
