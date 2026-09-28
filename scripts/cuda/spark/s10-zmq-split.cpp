// S10 (SPARK_MILESTONES.md): split one ZMQ REQ(1 B) -> REP(N B) round trip into
// request flight, server app time and reply flight, using CLOCK_MONOTONIC stamps
// from both processes. Build: g++ -O2 -std=c++17 s10-zmq-split.cpp -lzmq
// usage: s10-zmq-split server <ep> <bytes> <iters> <out.bin> | client <ep> <iters> <out.bin>
#include <zmq.h>
#include <sys/resource.h>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <string>
#include <vector>

static long long now_ns()
{
  timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

int main(int argc, char** argv)
{
  void* ctx = zmq_ctx_new();
  const std::string mode = argv[1];
  if (mode == "server") {
    void* s = zmq_socket(ctx, ZMQ_REP);
    zmq_bind(s, argv[2]);
    std::vector<char> buf(std::strtoul(argv[3], nullptr, 10), 1);
    const int iters = std::atoi(argv[4]);
    std::vector<long long> t(2 * iters);
    char req[16];
    for (int i = 0; i < iters; ++i) {
      zmq_recv(s, req, sizeof(req), 0);
      t[2 * i] = now_ns();
      zmq_send(s, buf.data(), buf.size(), 0);
      t[2 * i + 1] = now_ns();
    }
    FILE* f = std::fopen(argv[5], "wb");
    std::fwrite(t.data(), sizeof(long long), t.size(), f);
    std::fclose(f);
    return 0;
  }
  void* s = zmq_socket(ctx, ZMQ_REQ);
  zmq_connect(s, argv[2]);
  const int iters = std::atoi(argv[3]);
  std::vector<char> buf(8 << 20);
  std::vector<long long> t(2 * iters);
  for (int i = 0; i < iters; ++i) {
    char one = 0;
    t[2 * i] = now_ns();
    zmq_send(s, &one, 1, 0);
    zmq_recv(s, buf.data(), buf.size(), 0);
    t[2 * i + 1] = now_ns();
  }
  rusage ru{};
  getrusage(RUSAGE_SELF, &ru);
  std::printf("client minflt=%ld per_msg=%.1f\n", ru.ru_minflt, double(ru.ru_minflt) / iters);
  FILE* f = std::fopen(argv[4], "wb");
  std::fwrite(t.data(), sizeof(long long), t.size(), f);
  std::fclose(f);
  return 0;
}
