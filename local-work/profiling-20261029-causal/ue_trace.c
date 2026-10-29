#include "rf_zmq_imp_trx.h"
#include <dlfcn.h>
#include <time.h>
#include <stdlib.h>
extern void ocg_causal_event(long long,long long,int,long long,long long,long long,int);
static long long ts(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1000000000LL+t.tv_nsec;}
static void* lookup(const char*name){
 static void*h; if(!h)h=dlopen("/workspace/ocudu-spark-ranb/builds/srsran4g-zmq-local/lib/src/phy/rf/libsrsran_rf_zmq.so",RTLD_LAZY|RTLD_NOLOAD);
 void*p=h?dlsym(h,name):NULL;if(!p)abort();return p;
}
int rf_zmq_tx_baseband(rf_zmq_tx_t*q,cf_t*b,uint32_t n){
 static int(*fn)(rf_zmq_tx_t*,cf_t*,uint32_t);if(!fn)fn=lookup("rf_zmq_tx_baseband");
 long long st=ts();int r=fn(q,b,n);ocg_causal_event(30,41000,0,st,ts(),n,r);return r;
}
int rf_zmq_tx_align(rf_zmq_tx_t*q,uint64_t n){
 static int(*fn)(rf_zmq_tx_t*,uint64_t);if(!fn)fn=lookup("rf_zmq_tx_align");
 long long st=ts();int r=fn(q,n);ocg_causal_event(32,41000,0,st,ts(),n,r);return r;
}
int rf_zmq_rx_baseband(rf_zmq_rx_t*q,cf_t*b,uint32_t n){
 static int(*fn)(rf_zmq_rx_t*,cf_t*,uint32_t);if(!fn)fn=lookup("rf_zmq_rx_baseband");
 long long st=ts();int r=fn(q,b,n);ocg_causal_event(35,41000,0,st,ts(),n,r);return r;
}
