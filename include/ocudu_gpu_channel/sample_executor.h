#pragma once

#include <cstddef>
#include <functional>
#include <memory>

namespace ocg {

// Persistent CPU workers shared by all receiving nodes of one processor.
// Each call joins its disjoint sample ranges before returning or rethrowing.
class SampleExecutor {
public:
  explicit SampleExecutor(std::size_t threads);
  ~SampleExecutor();
  SampleExecutor(const SampleExecutor&) = delete;
  SampleExecutor& operator=(const SampleExecutor&) = delete;

  void for_each_range(std::size_t count,
                      const std::function<void(std::size_t, std::size_t)>& fn);

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

} // namespace ocg
