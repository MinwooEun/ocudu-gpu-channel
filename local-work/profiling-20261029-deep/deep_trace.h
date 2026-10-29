#pragma once
#include <dlfcn.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/prctl.h>
#include <mutex>
#include <ctime>
#include <cstdlib>
namespace deep_trace {
using Fn=void(*)(long long,long long,int,long long,long long,long long,int);
inline long long now(){timespec t{};clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1000000000LL+t.tv_nsec;}
inline Fn writer(){static auto f=reinterpret_cast<Fn>(dlsym(RTLD_DEFAULT,"ocg_causal_event"));return f;}
inline volatile unsigned* gate(){static auto p=[]()->volatile unsigned*{const char*s=getenv("OCG_DEEP_GATE");if(!s)return nullptr;int fd=open(s,O_RDONLY);if(fd<0)std::abort();void*v=mmap(nullptr,4096,PROT_READ,MAP_SHARED,fd,0);close(fd);if(v==MAP_FAILED)std::abort();return static_cast<volatile unsigned*>(v);}();return p;}
inline bool on(){auto g=gate();return g&&*g;}
inline void phase(int stage,long long start,long long end,long long samples){if(on())if(auto f=writer())f(60,stage,0,start,end,samples,0);}
struct Lock {
 std::mutex&m;int site;bool capture;long long acquired;
 Lock(std::mutex&v,int s):m(v),site(s),capture(on()),acquired(0){long long begin=capture?now():0;m.lock();if(capture){acquired=now();if(auto f=writer())f(50,reinterpret_cast<long long>(&m),site,begin,acquired,0,0);}}
 ~Lock(){long long before=capture?now():0;m.unlock();if(capture)if(auto f=writer())f(51,reinterpret_cast<long long>(&m),site,acquired,before,0,0);}
};
}
