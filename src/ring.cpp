#include "ocudu_gpu_channel/ring.h"
#include <algorithm>

namespace ocg {

IqRing::IqRing(std::size_t capacity_samples)
{
  reset(capacity_samples);
}

void IqRing::reset(std::size_t capacity_samples)
{
  buffer_.assign(capacity_samples, {});
  next_sequence_ = 0;
  start_ = 0;
  size_ = 0;
}

bool IqRing::push(std::span<const IqSample> samples)
{
  if (samples.empty()) {
    return true;
  }
  if (samples.size() > buffer_.size() || size_ + samples.size() > buffer_.size()) {
    return false;
  }

  // At most two contiguous block copies (before and after the wrap) instead
  // of a per-sample modulo: a 1 ms slot is 23k+ samples, and the per-sample
  // loop was the whole cost of the broker's ring stages.
  const std::size_t tail = (start_ + size_) % buffer_.size();
  const std::size_t first = std::min(samples.size(), buffer_.size() - tail);
  std::copy(samples.begin(), samples.begin() + static_cast<std::ptrdiff_t>(first), buffer_.begin() + static_cast<std::ptrdiff_t>(tail));
  std::copy(samples.begin() + static_cast<std::ptrdiff_t>(first), samples.end(), buffer_.begin());
  size_ += samples.size();
  next_sequence_ += samples.size();
  return true;
}

bool IqRing::read(std::uint64_t sequence, std::span<IqSample> out) const
{
  if (out.empty()) {
    return true;
  }
  if (sequence < earliest_sequence() || sequence + out.size() > next_sequence_ || buffer_.empty()) {
    return false;
  }

  const auto offset = static_cast<std::size_t>(sequence - earliest_sequence());
  const std::size_t head = (start_ + offset) % buffer_.size();
  const std::size_t first = std::min(out.size(), buffer_.size() - head);
  std::copy(buffer_.begin() + static_cast<std::ptrdiff_t>(head),
            buffer_.begin() + static_cast<std::ptrdiff_t>(head + first), out.begin());
  std::copy(buffer_.begin(), buffer_.begin() + static_cast<std::ptrdiff_t>(out.size() - first),
            out.begin() + static_cast<std::ptrdiff_t>(first));
  return true;
}

void IqRing::discard_before(std::uint64_t sequence)
{
  const std::uint64_t earliest = earliest_sequence();
  if (sequence <= earliest || size_ == 0) {
    return;
  }

  if (sequence >= next_sequence_) {
    start_ = 0;
    size_ = 0;
    return;
  }

  const auto discard_count = static_cast<std::size_t>(sequence - earliest);
  start_ = (start_ + discard_count) % buffer_.size();
  size_ -= discard_count;
}

} // namespace ocg
