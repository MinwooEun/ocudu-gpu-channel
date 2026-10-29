from pathlib import Path
root = Path(__file__).parent / 'src'
header = r'''#pragma once
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
'''
(root/'src/profile_trace.h').write_text(header)
p=root/'src/cuda_backend.cu'; s=p.read_text(); s='#include "profile_trace.h"\n'+s
old='    const auto call_start = std::chrono::steady_clock::now();'
assert s.count(old)==1
s=s.replace(old,old+'\n    ocg_profile::Range profile_range(dst_key.c_str());\n    const double profile_cpu_start = ocg_profile::enabled() ? ocg_profile::cpu_us() : 0;\n    const long long profile_start_ns = ocg_profile::enabled() ? ocg_profile::now_ns() : 0;')
old='    // M4.2 -- one snap per LINK per slot'
s=s.replace(old,'    const auto profile_pack_end = std::chrono::steady_clock::now();\n'+old)
old='    // Every edge of this node has now been staged'
s=s.replace(old,'    const auto profile_model_end = std::chrono::steady_clock::now();\n'+old)
old='    check(cudaStreamSynchronize(sp.stream), "cudaStreamSynchronize superpose");'
s=s.replace(old,'    const auto profile_submit_end = std::chrono::steady_clock::now();\n'+old)
needle='                   sp.use_device_channel, sp.zc_in || sp.zc_out || sp.zc_meta || sp.zc_direct_in);'
assert s.count(needle)==1
s=s.replace(needle,needle+r'''
    if (ocg_profile::enabled()) {
      const auto end = std::chrono::steady_clock::now();
      const auto us=[](auto d){return std::chrono::duration<double,std::micro>(d).count();};
      float h=0,k=0,d=0;
      cudaEventElapsedTime(&h,sp.h2d_start,sp.h2d_done);
      cudaEventElapsedTime(&k,sp.h2d_done,sp.kernel_done);
      cudaEventElapsedTime(&d,sp.kernel_done,sp.d2h_done);
      thread_local ocg_profile::Writer w("channel","start_ns,node,samples,rate_hz,lanes,sources,rows,direct_in,zero_in,zero_out,entry_pack_us,model_control_us,rx_prep_us,submit_us,sync_wait_us,output_record_us,call_us,thread_cpu_us,h2d_event_us,kernel_event_us,d2h_event_us");
      fprintf(w.f,"%lld,%s,%zu,%llu,%d,%zu,%zu,%d,%d,%d,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f\n",
        profile_start_ns,dst_key.c_str(),count,(unsigned long long)sample_rate_hz,link_count,sp.num_sources,sp.rows,direct_in,sp.zc_in,sp.zc_out,
        us(profile_pack_end-call_start),us(profile_model_end-profile_pack_end),us(total_start-profile_model_end),
        us(profile_submit_end-total_start),us(out_start-profile_submit_end),us(end-out_start),us(end-call_start),
        ocg_profile::cpu_us()-profile_cpu_start,h*1000.,k*1000.,d*1000.);
    }
''')
p.write_text(s)
p=root/'src/broker.cpp'; s=p.read_text(); s='#include "profile_trace.h"\n'+s
needle='        store_us(diag.stage_us_bits[kProducerStageRoom], room_us);'
assert s.count(needle)==1
s=s.replace(needle,r'''        if (ocg_profile::enabled()) {
          thread_local ocg_profile::Writer w("broker","end_ns,node,samples,rate_hz,room_us,align_us,data_us,read_us,process_us,commit_pace_us,push_us");
          fprintf(w.f,"%lld,%s,%zu,%llu,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f\n",ocg_profile::now_ns(),node.id.c_str(),count,(unsigned long long)rate,room_us,align_us,data_us,read_us,process_us,throttle_us,push_us);
        }
'''+needle)
p.write_text(s)
