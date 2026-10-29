from pathlib import Path
p=Path(__file__).parent
header='''#include <dlfcn.h>
#include <ctime>
namespace causal_trace {
using Fn = void(*)(long long,long long,int,long long,long long,long long,int);
inline Fn writer() { static auto fn=reinterpret_cast<Fn>(dlsym(RTLD_DEFAULT,"ocg_causal_event")); return fn; }
inline long long now() { timespec t{}; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec*1000000000LL+t.tv_nsec; }
inline void emit(int op,int lane,long long start,long long samples) { if(auto fn=writer()) fn(op,40000+lane,0,start,now(),samples,0); }
}
'''
for side in ('tx','rx'):
 name=f'radio_zmq_{side}_channel.cpp';s=(p/'gnb-original'/name).read_text();s=header+s
 if side=='tx':
  s=s.replace('  unsigned count = 0;\n  while (state_fsm.is_running() && (count != data.size())) {','  const auto causal_start = causal_trace::writer() ? causal_trace::now() : 0;\n  unsigned count = 0;\n  while (state_fsm.is_running() && (count != data.size())) {',1)
  s=s.replace('    unsigned pushed = circular_buffer.try_push(data.begin() + count, data.end());','    unsigned pushed = circular_buffer.try_push(data.begin() + count, data.end());\n    if (pushed) causal_trace::emit(41,channel_id,causal_start,pushed);',1)
  s=s.replace('  // Increment timestamp count.','  causal_trace::emit(40,channel_id,causal_start,count);\n  // Increment timestamp count.',1)
 else:
  s=s.replace('    unsigned pushed = circular_buffer.try_push(buffer.begin() + count, buffer.begin() + nsamples);','    unsigned pushed = circular_buffer.try_push(buffer.begin() + count, buffer.begin() + nsamples);\n    if (pushed) causal_trace::emit(42,channel_id,0,pushed);',1)
  s=s.replace('void radio_zmq_rx_channel::receive(span<cf_t> data)\n{','void radio_zmq_rx_channel::receive(span<cf_t> data)\n{\n  const auto causal_start = causal_trace::writer() ? causal_trace::now() : 0;',1)
  s=s.replace('  if (!state_fsm.is_running()) {\n    ocuduvec::zero(data);','  causal_trace::emit(43,channel_id,causal_start,count);\n  if (!state_fsm.is_running()) {\n    ocuduvec::zero(data);',1)
 (p/'gnb-instrumented'/name).write_text(s)
