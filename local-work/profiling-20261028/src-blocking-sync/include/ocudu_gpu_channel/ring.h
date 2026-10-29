#pragma once

#include "ocudu_gpu_channel/iq.h"
#include <cstdint>
#include <span>
#include <vector>

namespace ocg {

class IqRing {
public:
  explicit IqRing(std::size_t capacity_samples = 0);

  void reset(std::size_t capacity_samples);
  bool push(std::span<const IqSample> samples);
  bool read(std::uint64_t sequence, std::span<IqSample> out) const;
  void discard_before(std::uint64_t sequence);

  // Read-only view of [sequence, sequence + count) straight into the storage,
  // or an empty span when the range wraps or is not buffered. It stays valid
  // until the range is discarded: push() only writes free space.
  std::span<const IqSample> view(std::uint64_t sequence, std::size_t count) const;
  // Writable storage for the next `count` samples when the free space at the
  // tail is contiguous, else an empty span. Nothing is visible to readers
  // until commit(count); the single producer may fill it without the lock.
  std::span<IqSample> reserve(std::size_t count);
  void commit(std::size_t count);

  std::size_t capacity() const { return buffer_.size(); }
  std::size_t size() const { return size_; }
  std::size_t free_capacity() const { return buffer_.size() - size_; }
  std::uint64_t earliest_sequence() const { return next_sequence_ - size_; }
  std::uint64_t next_sequence() const { return next_sequence_; }

private:
  std::vector<IqSample> buffer_;
  std::uint64_t next_sequence_ = 0;
  std::size_t start_ = 0;
  std::size_t size_ = 0;
};

} // namespace ocg
