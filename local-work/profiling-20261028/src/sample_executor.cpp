#include "ocudu_gpu_channel/sample_executor.h"
#include <algorithm>
#include <condition_variable>
#include <exception>
#include <list>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <vector>

namespace ocg {

struct SampleExecutor::Impl {
  struct Job {
    std::function<void(std::size_t, std::size_t)> fn;
    std::mutex mutex;
    std::condition_variable done;
    std::size_t remaining = 0;
    std::exception_ptr error;
  };
  struct Task {
    std::shared_ptr<Job> job;
    std::size_t begin, end;
  };
  std::size_t threads;
  std::mutex mutex;
  std::condition_variable ready;
  std::list<Task> queue;
  bool stopping = false;
  std::vector<std::thread> workers;

  explicit Impl(std::size_t n) : threads(n)
  {
    if (n == 0) throw std::invalid_argument("CPU worker count must be positive");
    if (n == 1) return;
    try {
      for (std::size_t i = 0; i < n; ++i) {
        workers.emplace_back([this] {
          for (;;) {
            Task task;
            {
              std::unique_lock lock(mutex);
              ready.wait(lock, [this] { return stopping || !queue.empty(); });
              if (queue.empty()) return;
              task = std::move(queue.front());
              queue.pop_front();
            }
            std::exception_ptr error;
            try { task.job->fn(task.begin, task.end); }
            catch (...) { error = std::current_exception(); }
            {
              std::lock_guard lock(task.job->mutex);
              if (error && !task.job->error) task.job->error = error;
              if (--task.job->remaining == 0) task.job->done.notify_one();
            }
          }
        });
      }
    } catch (...) {
      stop();
      throw;
    }
  }
  void stop()
  {
    {
      std::lock_guard lock(mutex);
      stopping = true;
    }
    ready.notify_all();
    for (auto& worker : workers) if (worker.joinable()) worker.join();
  }
  ~Impl() { stop(); }
};

SampleExecutor::SampleExecutor(std::size_t threads) : impl_(std::make_unique<Impl>(threads)) {}
SampleExecutor::~SampleExecutor() = default;

void SampleExecutor::for_each_range(
    std::size_t count, const std::function<void(std::size_t, std::size_t)>& fn)
{
  if (count == 0) return;
  if (impl_->threads == 1) { fn(0, count); return; }
  auto job = std::make_shared<Impl::Job>();
  job->fn = fn;
  const std::size_t ranges = std::min(count, impl_->threads);
  job->remaining = ranges;
  std::list<Impl::Task> tasks;
  const std::size_t chunk = count / ranges, extra = count % ranges;
  std::size_t begin = 0;
  for (std::size_t i = 0; i < ranges; ++i) {
    const auto end = begin + chunk + (i < extra ? 1 : 0);
    tasks.push_back({job, begin, end});
    begin = end;
  }
  {
    std::lock_guard lock(impl_->mutex);
    impl_->queue.splice(impl_->queue.end(), tasks);
  }
  impl_->ready.notify_all();
  std::unique_lock lock(job->mutex);
  job->done.wait(lock, [&] { return job->remaining == 0; });
  if (job->error) std::rethrow_exception(job->error);
}

} // namespace ocg
