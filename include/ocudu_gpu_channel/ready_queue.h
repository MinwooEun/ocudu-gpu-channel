#pragma once

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <coroutine>
#include <cstdint>
#include <deque>
#include <exception>
#include <mutex>
#include <utility>
#include <vector>

namespace ocg {

// A node keeps its buffers, sample epoch and pacer in one coroutine frame.
// Suspending releases the worker, never the node's ownership of that state.
class ProducerTask {
public:
  struct promise_type {
    std::exception_ptr error;
    ProducerTask get_return_object() { return ProducerTask{Handle::from_promise(*this)}; }
    std::suspend_always initial_suspend() noexcept { return {}; }
    std::suspend_always final_suspend() noexcept { return {}; }
    void return_void() noexcept {}
    void unhandled_exception() noexcept { error = std::current_exception(); }
    using Handle = std::coroutine_handle<promise_type>;
  };
  using Handle = std::coroutine_handle<promise_type>;
  explicit ProducerTask(Handle h) : handle_(h) {}
  ProducerTask(ProducerTask&& other) noexcept : handle_(std::exchange(other.handle_, {})) {}
  ProducerTask(const ProducerTask&) = delete;
  ~ProducerTask() { if (handle_) handle_.destroy(); }
  Handle handle() const { return handle_; }
private:
  Handle handle_;
};

// Generation is sampled BEFORE checking ring readiness. An event between the
// check and suspension is remembered, including while resume() is unwinding.
// Only the worker returning from resume() may release running: no notification
// or timer is allowed to resume a frame concurrently with that worker.
class ProducerReadyQueue {
public:
  using Clock = std::chrono::steady_clock;
  enum class Event : std::size_t { Input = 0, Room = 1, Gpu = 2 };
  explicit ProducerReadyQueue(std::size_t nodes) : entries_(nodes) {}

  void attach(std::size_t node, ProducerTask::Handle handle)
  {
    std::lock_guard lock(mutex_);
    entries_[node].handle = handle;
    enqueue(node);
  }
  std::uint64_t generation(std::size_t node, Event event = Event::Input)
  {
    std::lock_guard lock(mutex_);
    return entries_[node].generation[static_cast<std::size_t>(event)];
  }
  struct Metrics {
    std::uint64_t signals = 0;
    std::uint64_t dispatches = 0;
    double queue_us = 0;
    double max_queue_us = 0;
  };
  // Read after all workers join; queue time starts when a node becomes queued,
  // not when it first starts waiting for IQ. It excludes channel execution.
  Metrics metrics(std::size_t node) const { return entries_[node].metrics; }
  void notify(std::size_t node, Event event = Event::Input)
  {
    std::lock_guard lock(mutex_);
    auto& e = entries_[node];
    ++e.generation[static_cast<std::size_t>(event)];
    ++e.metrics.signals;
    if (e.waiting && !e.running && e.event_wait && e.event == event) {
      enqueue(node);
      cv_.notify_one();
    }
  }
  struct Wait {
    ProducerReadyQueue& queue;
    std::size_t node;
    std::uint64_t observed;
    Clock::time_point deadline;
    bool event_wait;
    Event event;
    bool await_ready() const noexcept { return false; }
    void await_suspend(std::coroutine_handle<>) const
    {
      std::lock_guard lock(queue.mutex_);
      auto& e = queue.entries_[node];
      e.waiting = true;
      e.observed = observed;
      e.deadline = deadline;
      e.event_wait = event_wait;
      e.event = event;
    }
    void await_resume() const noexcept {}
  };
  Wait wait(std::size_t node, std::uint64_t observed, Clock::time_point deadline, Event event = Event::Input)
  {
    return {*this, node, observed, deadline, true, event};
  }
  Wait until(std::size_t node, Clock::time_point deadline)
  {
    return {*this, node, 0, deadline, false, Event::Input};
  }
  void stop()
  {
    std::lock_guard lock(mutex_);
    stopped_ = true;
    cv_.notify_all();
  }
  template<class OnError> void run(OnError on_error)
  {
    std::unique_lock lock(mutex_);
    while (!stopped_) {
      const auto now = Clock::now();
      auto next = Clock::time_point::max();
      for (std::size_t n = 0; n < entries_.size(); ++n) {
        auto& e = entries_[n];
        if (!e.waiting || e.running || e.queued) continue;
        if (e.deadline <= now || (e.event_wait && e.generation[static_cast<std::size_t>(e.event)] != e.observed)) enqueue(n);
        else next = std::min(next, e.deadline);
      }
      if (ready_.empty()) {
        cv_.wait_until(lock, next);
        continue;
      }
      const auto n = ready_.front();
      ready_.pop_front();
      auto& e = entries_[n];
      e.queued = false;
      e.running = true;
      e.waiting = false;
      const auto handle = e.handle;
      const double queue_us = std::chrono::duration<double, std::micro>(Clock::now() - e.queued_at).count();
      ++e.metrics.dispatches;
      e.metrics.queue_us += queue_us;
      e.metrics.max_queue_us = std::max(e.metrics.max_queue_us, queue_us);
      lock.unlock();
      handle.resume();
      const auto error = handle.done() ? handle.promise().error : std::exception_ptr{};
      if (error) on_error(error);
      lock.lock();
      e.running = false;
      if (e.waiting && (e.deadline <= Clock::now() ||
                        (e.event_wait && e.generation[static_cast<std::size_t>(e.event)] != e.observed))) enqueue(n);
      cv_.notify_one();
    }
  }
private:
  struct Entry {
    ProducerTask::Handle handle{};
    Metrics metrics;
    Clock::time_point queued_at{};
    std::uint64_t generation[3] = {};
    Event event = Event::Input;
    std::uint64_t observed = 0;
    Clock::time_point deadline = Clock::time_point::max();
    bool running = false;
    bool queued = false;
    bool waiting = false;
    bool event_wait = true;
  };
  void enqueue(std::size_t node)
  {
    auto& e = entries_[node];
    if (!e.queued) {
      e.queued = true;
      e.queued_at = Clock::now();
      ready_.push_back(node);
    }
  }
  std::mutex mutex_;
  std::condition_variable cv_;
  std::vector<Entry> entries_;
  std::deque<std::size_t> ready_;
  bool stopped_ = false;
};

} // namespace ocg
