from pathlib import Path
import re,json
P=Path(__file__).parent;s=(P.parent/'profiling-20261029-causal/broker-cpu-trace.cpp').read_text();s='#include "deep_trace.h"\n'+s
sites=[]
def sub(m):
 sites.append(dict(site=len(sites)+1,expression=m[1]));return f'deep_trace::Lock lk({m[1]}, {len(sites)});'
s=re.sub(r'std::lock_guard<std::mutex> lk\(([^;]+)\);',sub,s)
s=s.replace('    HopTrace& trace = producer_trace[n];','    HopTrace& trace = producer_trace[n];\n    prctl(PR_SET_NAME, ("DP-"+nodes[n].id).c_str());',1)
s=s.replace('    HopTrace& trace = rep_trace[p];','    HopTrace& trace = rep_trace[p];\n    prctl(PR_SET_NAME, ("DR-"+ports[p]->config->id).c_str());',1)
s=s.replace('        const auto t_align_start = std::chrono::steady_clock::now();','        const auto t_align_start = std::chrono::steady_clock::now();\n        deep_trace::phase(0,std::chrono::duration_cast<std::chrono::nanoseconds>(t_room_start.time_since_epoch()).count(),std::chrono::duration_cast<std::chrono::nanoseconds>(t_align_start.time_since_epoch()).count(),0);',1)
s=s.replace('        const auto t_read_start = std::chrono::steady_clock::now();','        const auto t_read_start = std::chrono::steady_clock::now();\n        deep_trace::phase(1,std::chrono::duration_cast<std::chrono::nanoseconds>(t_data_start.time_since_epoch()).count(),std::chrono::duration_cast<std::chrono::nanoseconds>(t_read_start.time_since_epoch()).count(),count);',1)
s=s.replace('        const auto t_send_start = std::chrono::steady_clock::now();','        const auto t_send_start = std::chrono::steady_clock::now();\n        deep_trace::phase(2,std::chrono::duration_cast<std::chrono::nanoseconds>(t_pop_start.time_since_epoch()).count(),std::chrono::duration_cast<std::chrono::nanoseconds>(t_send_start.time_since_epoch()).count(),take);',1)
(P/'broker-deep.cpp').write_text(s);(P/'mutex-sites.json').write_text(json.dumps(sites,indent=2))
s=(P.parent/'profiling-20261029-causal/build_broker_cpu.py').read_text().replace("profile-20261029-causal","profile-20261029-deep").replace("broker-cpu-trace","broker-deep");s=s.replace("'-I/workspace/gpuch/profile-20261028/src/src'","'-I/workspace/gpuch/profile-20261028/src/src','-I'+str(P)");(P/'build.py').write_text(s)
