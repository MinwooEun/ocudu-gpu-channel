#pragma once
#include <array>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>
#include <ctime>
inline long long trace_ns(std::chrono::steady_clock::time_point t) {
 return std::chrono::duration_cast<std::chrono::nanoseconds>(t.time_since_epoch()).count();
}
inline long long trace_cpu_ns() {
 timespec ts{}; clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts);
 return ts.tv_sec * 1000000000LL + ts.tv_nsec;
}
template<std::size_t N> struct DiagnosticTrace {
 std::string path;
 std::vector<std::array<long long,N>> records;
 DiagnosticTrace(const std::string& name) {
  const char* dir=std::getenv("OCG_DIAG_TRACE_DIR");
  if (dir) { path=std::string(dir)+"/"+name+".bin"; records.reserve(500000); }
 }
 void add(std::array<long long,N> r) {
  if (!path.empty() && records.size()<records.capacity()) records.push_back(r);
 }
 ~DiagnosticTrace() {
  if (!path.empty()) {
   std::ofstream f(path,std::ios::binary);
   f.write(reinterpret_cast<const char*>(records.data()),records.size()*sizeof(records[0]));
  }
 }
};
