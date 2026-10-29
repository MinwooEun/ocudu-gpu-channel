#include "ocudu_gpu_channel/ready_queue.h"
#include <atomic>
#include <cstdlib>
#include <iostream>
#include <thread>

using Queue = ocg::ProducerReadyQueue;
using Clock = Queue::Clock;
using namespace std::chrono_literals;

void require(bool ok, const char* message)
{
  if (!ok) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}

template<class Predicate> void wait_for(Predicate ready)
{
  const auto deadline = Clock::now() + 3s;
  while (!ready() && Clock::now() < deadline) std::this_thread::sleep_for(1ms);
  require(ready(), "queue progress timed out");
}

int main()
{
  Queue queue(3);
  std::atomic<int> completed{0}, iterations{0};
  std::atomic<bool> timer_waiting{false}, timer_done{false};
  Clock::time_point due;
  // The event occurs after the readiness version is read, BEFORE suspension.
  // Every iteration must resume exactly once without another external event.
  auto raced = [&]() -> ocg::ProducerTask {
    for (int i = 0; i < 10000; ++i) {
      const auto observed = queue.generation(0);
      queue.notify(0);
      co_await queue.wait(0, observed, Clock::time_point::max());
      require(iterations.fetch_add(1) == i, "node resumed concurrently or out of order");
    }
    ++completed;
  };
  // Block one node indefinitely. Other nodes must still execute.
  auto blocked = [&]() -> ocg::ProducerTask {
    const auto observed = queue.generation(1);
    ++completed;
    co_await queue.wait(1, observed, Clock::time_point::max());
    require(false, "stopping a queue unexpectedly resumed a cancelled node");
  };
  // IQ/room events must never bypass a pacing deadline.
  auto paced = [&]() -> ocg::ProducerTask {
    due = Clock::now() + 100ms;
    timer_waiting = true;
    co_await queue.until(2, due);
    require(Clock::now() >= due, "notification bypassed pacing timer");
    timer_done = true;
    ++completed;
  };
  auto a = raced(); auto b = blocked(); auto c = paced();
  queue.attach(0, a.handle()); queue.attach(1, b.handle()); queue.attach(2, c.handle());
  std::vector<std::thread> workers;
  for (int i = 0; i < 4; ++i) workers.emplace_back([&] {
    queue.run([](std::exception_ptr) { require(false, "coroutine exception"); });
  });
  wait_for([&] { return timer_waiting.load(); });
  while (!timer_done) { queue.notify(2); std::this_thread::yield(); }
  wait_for([&] { return completed.load() == 3; });
  queue.stop();
  for (auto& t : workers) t.join();
  require(a.handle().done() && c.handle().done() && !b.handle().done(), "incorrect task lifetime");
  require(iterations == 10000, "notification lost or frame resumed twice");
  std::cout << "test_ready_queue OK\n";
}
