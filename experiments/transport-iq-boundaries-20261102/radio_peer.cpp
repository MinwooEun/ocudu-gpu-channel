#include <zmq.h>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numeric>
#include <string>
#include <thread>
#include <vector>
#include <time.h>
#include <algorithm>
struct IQ{float i,q;};
using Clock=std::chrono::steady_clock;
long long ns(){timespec t{};clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1000000000LL+t.tv_nsec;}
volatile std::sig_atomic_t stopped=0;void signal_handler(int){stopped=1;}
struct Result{uint64_t tx=0,rx=0,measure_rx=0,malformed=0,errors=0;long long first=0,last=0;double power=0;};
int main(int argc,char**argv){
 if(argc<8){std::cerr<<"id base_port ports batch epoch_file ready_file measure_seconds\n";return 2;}
 std::signal(SIGTERM,signal_handler);std::signal(SIGINT,signal_handler);std::string id=argv[1],epoch=argv[5],readyfile=argv[6];int base=std::stoi(argv[2]),ports=std::stoi(argv[3]);size_t batch=std::stoull(argv[4]);long long duration=std::stoll(argv[7])*1000000000LL;
 std::atomic<long long> measure_start=0;std::atomic<int> ready=0;std::atomic<bool> failed=false;std::vector<Result> result(ports);void*ctx=zmq_ctx_new();int io=1;zmq_ctx_set(ctx,ZMQ_IO_THREADS,io);
 size_t cycle=4096/std::gcd(size_t(4096),batch);std::vector<std::vector<IQ>> blocks(cycle,std::vector<IQ>(batch));for(size_t k=0;k<cycle;k++)for(size_t i=0;i<batch;i++){float phase=float((k*batch+i)%4096)/4096.0F*6.283185307F;blocks[k][i]={std::cos(phase),std::sin(phase)};}
 auto socket=[&](int type,int port,bool bind){void*s=zmq_socket(ctx,type);int timeout=2,linger=0;zmq_setsockopt(s,ZMQ_RCVTIMEO,&timeout,sizeof(timeout));zmq_setsockopt(s,ZMQ_SNDTIMEO,&timeout,sizeof(timeout));zmq_setsockopt(s,ZMQ_LINGER,&linger,sizeof(linger));auto ep="tcp://127.0.0.1:"+std::to_string(port);int rc=bind?zmq_bind(s,ep.c_str()):zmq_connect(s,ep.c_str());if(rc){std::cerr<<ep<<":"<<zmq_strerror(zmq_errno())<<"\n";failed=true;}return s;};
 std::vector<std::thread> threads;
 for(int port=0;port<ports;port++){
 threads.emplace_back([&,port]{void*s=socket(ZMQ_REP,base+2*port,true);ready++;uint64_t block=0;while(!stopped&&!failed){uint8_t request=0;int n=zmq_recv(s,&request,1,0);if(n<0){if(zmq_errno()!=EAGAIN&&zmq_errno()!=EINTR){result[port].errors++;failed=true;}continue;}if(n!=1){result[port].malformed++;failed=true;break;}auto &v=blocks[block%cycle];while(!stopped){int sent=zmq_send(s,v.data(),v.size()*sizeof(IQ),0);if(sent>=0){if(size_t(sent)!=v.size()*sizeof(IQ)){result[port].errors++;failed=true;}result[port].tx+=batch;block++;break;}if(zmq_errno()!=EAGAIN&&zmq_errno()!=EINTR){result[port].errors++;failed=true;break;}}}zmq_close(s);});
 threads.emplace_back([&,port]{void*s=socket(ZMQ_REQ,base+2*port+1,false);ready++;bool pending=false;while(!stopped&&!failed){long long start=measure_start.load(std::memory_order_relaxed);if(start&&ns()>start+duration+1000000000LL)break;if(!pending){uint8_t request=0;if(zmq_send(s,&request,1,0)<0){if(zmq_errno()!=EAGAIN&&zmq_errno()!=EINTR){result[port].errors++;failed=true;}continue;}pending=true;}zmq_msg_t msg;zmq_msg_init(&msg);int n=zmq_msg_recv(&msg,s,0);long long end=ns();if(n<0){zmq_msg_close(&msg);if(zmq_errno()!=EAGAIN&&zmq_errno()!=EINTR){result[port].errors++;failed=true;}continue;}pending=false;if(n<=0||size_t(n)%sizeof(IQ)){result[port].malformed++;failed=true;}else{auto count=size_t(n)/sizeof(IQ);auto *iq=static_cast<const IQ*>(zmq_msg_data(&msg));result[port].rx+=count;if(start&&end>=start&&end<start+duration){result[port].measure_rx+=count;if(!result[port].first)result[port].first=end;result[port].last=end;for(size_t i=0;i<count;i++)result[port].power+=double(iq[i].i)*iq[i].i+double(iq[i].q)*iq[i].q;}}zmq_msg_close(&msg);}zmq_close(s);});
 }
 while(ready.load()!=2*ports&&!failed)std::this_thread::sleep_for(std::chrono::milliseconds(1));{std::ofstream f(readyfile);f<<ns()<<"\n";}
 while(!stopped&&!failed){if(!measure_start.load()){std::ifstream f(epoch);long long value=0;if(f>>value)measure_start=value;}else if(ns()>measure_start.load()+duration+1000000000LL)break;std::this_thread::sleep_for(std::chrono::milliseconds(10));}
 stopped=1;for(auto&t:threads)t.join();zmq_ctx_shutdown(ctx);zmq_ctx_term(ctx);
 std::cout<<"mode,synthetic_radio_zmq\nwaveform,cached_legacy_sine_exact_phase\n";
 std::cout<<"port,id,index,tx_samples,rx_samples,measure_samples,first_ns,last_ns,malformed,errors,mean_power\n";
 for(int i=0;i<ports;i++){auto&r=result[i];std::cout<<std::setprecision(12)<<"port,"<<id<<","<<i<<","<<r.tx<<","<<r.rx<<","<<r.measure_rx<<","<<r.first<<","<<r.last<<","<<r.malformed<<","<<r.errors<<","<<(r.measure_rx?r.power/r.measure_rx:0)<<"\n";}
 return failed?1:0;
}
