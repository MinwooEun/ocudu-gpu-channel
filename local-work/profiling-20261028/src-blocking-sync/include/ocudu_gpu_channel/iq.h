#pragma once

#include <cmath>
#include <cstddef>
#include <vector>

namespace ocg {

struct IqSample {
  float i = 0.0F;
  float q = 0.0F;
};

static_assert(sizeof(IqSample) == 8, "OCUDU ZMQ cf32 IQ samples must be 8 bytes");

using IqBuffer = std::vector<IqSample>;

inline IqSample operator+(IqSample lhs, IqSample rhs)
{
  return {lhs.i + rhs.i, lhs.q + rhs.q};
}

inline IqSample& operator+=(IqSample& lhs, IqSample rhs)
{
  lhs.i += rhs.i;
  lhs.q += rhs.q;
  return lhs;
}

inline IqSample scale(IqSample value, float factor)
{
  return {value.i * factor, value.q * factor};
}

inline IqSample rotate(IqSample value, double phase_rad)
{
  const auto c = static_cast<float>(std::cos(phase_rad));
  const auto s = static_cast<float>(std::sin(phase_rad));
  return {value.i * c - value.q * s, value.i * s + value.q * c};
}

inline double power(IqSample value)
{
  return static_cast<double>(value.i) * value.i + static_cast<double>(value.q) * value.q;
}

} // namespace ocg
