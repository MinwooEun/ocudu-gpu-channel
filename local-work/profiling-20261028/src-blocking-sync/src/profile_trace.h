#pragma once
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <unistd.h>
#include <sys/syscall.h>
#include <nvtx3/nvToolsExt.h>
namespace ocg_profile {
inline bool enabled() { static bool v = std::getenv("OCG_PROFILE_DIR") != nullptr; return v; }
inline double cpu_us() { timespec t{}; clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t); return t.tv_sec*1e6+t.tv_nsec/1e3; }
inline long long now_ns() { timespec t{}; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec*1000000000LL+t.tv_nsec; }
struct Writer {
 FILE* f=nullptr;
 Writer(const char* kind, const char* columns) {
  if (!enabled()) return;
  char path[2048]; snprintf(path,sizeof(path),"%s/%s-%d-%ld.csv",std::getenv("OCG_PROFILE_DIR"),kind,getpid(),syscall(SYS_gettid));
  f=fopen(path,"w"); if (!f) { perror(path); std::abort(); }
  setvbuf(f,nullptr,_IOFBF,1024*1024); fprintf(f,"%s\n",columns);
 }
 ~Writer() { if(f) fclose(f); }
};
struct Range { bool on; explicit Range(const char* n):on(enabled()) {if(on) nvtxRangePushA(n);} ~Range(){if(on)nvtxRangePop();} };
}
