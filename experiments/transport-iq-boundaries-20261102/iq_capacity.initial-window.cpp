#include "ocudu_gpu_channel/config.h"
#include "ocudu_gpu_channel/processing.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <memory>
#include <span>
#include <thread>
#include <time.h>
#include <unordered_map>
#include <vector>
using Clock=std::chrono::steady_clock;
long long ns(){return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();}
long long cpu(){timespec t{};clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t);return t.tv_sec*1000000000LL+t.tv_nsec;}
double pct(std::vector<double> a,double q){if(a.empty())return 0;std::sort(a.begin(),a.end());return a[std::min(a.size()-1,size_t(std::ceil(q*a.size())-1))];}
struct Record{long long time,begin,cpuns;double us;};
struct Node{std::string id;uint64_t rate;size_t count,ports;long long period;std::vector<ocg::SuperpositionInput> lanes;std::vector<ocg::IqBuffer> rows;std::vector<std::span<ocg::IqSample>> spans;const ocg::ModelConfig* rx=nullptr;std::vector<Record> records;uint64_t late=0;std::string error;};
int main(int argc,char**argv){
 if(argc<4){std::cerr<<"config warmup_seconds measure_seconds\n";return 2;}
 try{
 auto config=ocg::load_config_file(argv[1]);auto processor=ocg::create_channel_processor(config);auto resolved=ocg::resolve_topology(config);
 std::unordered_map<std::string,ocg::IqBuffer> inputs;
 for(auto &d:config.devices){auto n=ocg::resolve_batch_samples(config.runtime,d.sample_rate_hz);auto &v=inputs[d.id];v.resize(n);for(size_t i=0;i<n;i++)v[i]={float(i%17)/17.0f,float(i%23)/23.0f};}
 std::vector<std::unique_ptr<Node>> nodes;
 for(auto &node:resolved.nodes){auto p=std::make_unique<Node>();p->id=node.id;p->rate=node.sample_rate_hz;p->count=ocg::resolve_batch_samples(config.runtime,node.sample_rate_hz);p->ports=node.rx_ports.size();p->period=p->count*1000000000LL/p->rate;p->rows.assign(p->ports,ocg::IqBuffer(p->count));for(auto &r:p->rows)p->spans.emplace_back(r.data(),r.size());
 for(auto &lane:resolved.lanes)if(lane.dst_node==node.id){auto &v=inputs.at(lane.src_device);p->lanes.push_back({.link_key=lane.key,.model=ocg::find_model(config,lane.model_id),.samples=std::span<const ocg::IqSample>(v.data(),v.size()),.rx_port=lane.rx_port,.tx_port=lane.tx_port});}
 p->rx=node.rx_model.empty()?nullptr:ocg::find_model(config,node.rx_model);p->records.reserve(40000);nodes.push_back(std::move(p));}
 const long long start=ns()+200000000LL,measure_start=start+std::stoll(argv[2])*1000000000LL,finish=measure_start+std::stoll(argv[3])*1000000000LL;std::atomic<bool> failed=false;std::vector<std::thread> workers;
 for(auto &np:nodes)workers.emplace_back([&,p=np.get()]{try{long long due=start;std::this_thread::sleep_until(Clock::time_point(std::chrono::nanoseconds(start)));while(ns()<finish&&!failed){long long begin=ns(),c=cpu();processor->process_superposition(p->id,p->lanes,p->rx,p->rate,p->spans);long long cend=cpu(),end=ns();if(end>=measure_start&&end<finish){p->records.push_back({end,begin,cend-c,double(end-begin)/1000});if(end>due+p->period)p->late++;}due+=p->period;std::this_thread::sleep_until(Clock::time_point(std::chrono::nanoseconds(due)));}}catch(const std::exception&e){p->error=e.what();failed=true;}});
 for(auto&t:workers)t.join();
 std::cout<<"mode,iq_only\npacing,absolute_cadence_unbounded_catchup\ninput,cached_readonly_iq\nmeasurement_start_ns,"<<measure_start<<"\nmeasurement_end_ns,"<<finish<<"\nbackend,"<<processor->backend_name()<<"\nzero_copy,"<<processor->last_timings().zero_copy<<"\n";
 std::cout<<"node,id,ports,lanes,count,period_ns,coverage_ratio,endpoint_ratio,p50_us,p99_us,max_us,cpu_p99_us,late_completions,first_ns,last_ns,finite\n";
 for(auto&p:nodes){std::vector<double>w,c;for(auto&r:p->records){w.push_back(r.us);c.push_back(double(r.cpuns)/1000);}size_t n=w.size();double coverage=double(n)*p->period/double(finish-measure_start),endpoint=n>1?double(n-1)*p->period/(p->records.back().time-p->records.front().time):0;bool finite=true;for(auto&r:p->rows)for(auto&s:r)finite=finite&&std::isfinite(s.i)&&std::isfinite(s.q);
 std::cout<<std::setprecision(12)<<"node,"<<p->id<<","<<p->ports<<","<<p->lanes.size()<<","<<n<<","<<p->period<<","<<coverage<<","<<endpoint<<","<<pct(w,.5)<<","<<pct(w,.99)<<","<<pct(w,1)<<","<<pct(c,.99)<<","<<p->late<<","<<(n?p->records.front().time:0)<<","<<(n?p->records.back().time:0)<<","<<finite<<"\n";if(!p->error.empty())std::cerr<<p->id<<":"<<p->error<<"\n";}
 return failed?1:0;
 }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}
}
