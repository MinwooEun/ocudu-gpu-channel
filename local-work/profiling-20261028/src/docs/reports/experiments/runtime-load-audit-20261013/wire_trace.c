#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>
#include <zmq.h>
// Diagnostic interposition only. Payloads and ZMQ results are unchanged.
// Header: 8 uint64; records: 8 int64; op is committed last.
typedef struct { int64_t op,tid,port,flags,start,end,result,error; } record;
typedef struct { uint64_t magic; _Atomic uint64_t count; uint64_t capacity; _Atomic uint64_t dropped; uint64_t pid,mono,wall,reserved; } header;
static header *head;
static record *records;
static _Atomic(void*) sockets[32];
static int ports[32];
static pthread_mutex_t map_lock=PTHREAD_MUTEX_INITIALIZER;
static _Thread_local int64_t thread_id;
static _Thread_local int64_t last_poll_end[6];
static int port_index(int p) {return p==2000?0:p==2001?1:p-2098;}
static int (*real_send)(void*,const void*,size_t,int);
static int (*real_recv)(void*,void*,size_t,int);
static int (*real_msg_send)(zmq_msg_t*,void*,int);
static int (*real_msg_recv)(zmq_msg_t*,void*,int);
static int (*real_bind)(void*,const char*);
static int (*real_connect)(void*,const char*);
static size_t (*real_fwrite)(const void*,size_t,size_t,FILE*);
static int64_t now_ns(clockid_t clk) { struct timespec ts;clock_gettime(clk,&ts);return (int64_t)ts.tv_sec*1000000000LL+ts.tv_nsec; }
static int socket_port(void *s) { if(!head)return 0;for(int i=0;i<32;i++)if(atomic_load_explicit(&sockets[i],memory_order_acquire)==s)return ports[i];return 0; }
static void add(int64_t op,int64_t port,int flags,int64_t start,int64_t end,int64_t result,int error) {
 if(!head)return;
 if(!thread_id)thread_id=syscall(SYS_gettid);
 uint64_t idx=atomic_fetch_add_explicit(&head->count,1,memory_order_relaxed);
 if(idx>=head->capacity) {atomic_fetch_add(&head->dropped,1);return;}
 records[idx]=(record){0,thread_id,port,flags,start,end,result,error};
 __atomic_store_n(&records[idx].op,op,__ATOMIC_RELEASE);
}
static void remember(void *s,const char *endpoint,int op) {
 int port=0;
 if(sscanf(endpoint,"tcp://127.0.0.1:%d",&port)!=1)return;
 if(port!=2000 && port!=2001 && port!=2100 && port!=2101 && port!=2102 && port!=2103)return;
 pthread_mutex_lock(&map_lock);
 for(int i=0;i<32;i++) if(atomic_load(&sockets[i])==NULL || atomic_load(&sockets[i])==s) {
  ports[i]=port;atomic_store_explicit(&sockets[i],s,memory_order_release);break;
 }
 pthread_mutex_unlock(&map_lock);
 int64_t t=now_ns(CLOCK_MONOTONIC);add(op,port,0,t,t,0,0);
}
__attribute__((constructor)) static void init(void) {
 real_send=dlsym(RTLD_NEXT,"zmq_send");real_recv=dlsym(RTLD_NEXT,"zmq_recv");
 real_msg_send=dlsym(RTLD_NEXT,"zmq_msg_send");real_msg_recv=dlsym(RTLD_NEXT,"zmq_msg_recv");
 real_bind=dlsym(RTLD_NEXT,"zmq_bind");real_connect=dlsym(RTLD_NEXT,"zmq_connect");
 real_fwrite=dlsym(RTLD_NEXT,"fwrite");
 const char *dir=getenv("OCG_WIRE_TRACE_DIR");if(!dir)return;
 char exe[4096]={0};ssize_t n=readlink("/proc/self/exe",exe,sizeof(exe)-1);if(n<0)return;
 char *name=strrchr(exe,'/');name=name?name+1:exe;
 if(strcmp(name,"gnb") && strcmp(name,"srsue") && strcmp(name,"ocudu-gpu-channel") && !getenv("OCG_WIRE_TRACE_ALL"))return;
 if(!real_send || !real_recv || !real_msg_send || !real_msg_recv || !real_bind || !real_connect || !real_fwrite) _exit(119);
 char path[4096];snprintf(path,sizeof(path),"%s/%s-%d.wire",dir,name,getpid());
 int fd=open(path,O_RDWR|O_CREAT|O_TRUNC,0644);if(fd<0)_exit(120);
 uint64_t cap=3000000;size_t bytes=sizeof(header)+cap*sizeof(record);
 if(ftruncate(fd,bytes))_exit(121);
 void *p=mmap(NULL,bytes,PROT_READ|PROT_WRITE,MAP_SHARED|MAP_POPULATE,fd,0);close(fd);if(p==MAP_FAILED)_exit(122);
 head=p;head->magic=0x4f43475749524531ULL;head->capacity=cap;head->pid=getpid();head->mono=now_ns(CLOCK_MONOTONIC);head->wall=now_ns(CLOCK_REALTIME);records=(record*)(head+1);
}
int zmq_bind(void*s,const char*e) {int r=real_bind(s,e);if(r==0 && head)remember(s,e,3);return r;}
int zmq_connect(void*s,const char*e) {int r=real_connect(s,e);if(r==0 && head)remember(s,e,4);return r;}
int zmq_send(void*s,const void*b,size_t n,int flags) {
 int p=socket_port(s);int64_t start=p?now_ns(CLOCK_MONOTONIC):0;
 int r=real_send(s,b,n,flags);int err=errno;
 if(p && (r>=0 || err!=EAGAIN))add(1,p,flags,start,now_ns(CLOCK_MONOTONIC),r,r<0?err:0);
 errno=err;return r;
}
int zmq_recv(void*s,void*b,size_t n,int flags) {
 int p=socket_port(s);int64_t start=p?now_ns(CLOCK_MONOTONIC):0;
 if(p && (flags&ZMQ_DONTWAIT)) {int i=port_index(p);if(last_poll_end[i] && start-last_poll_end[i]>1000000)add(8,p,flags,last_poll_end[i],start,0,0);}
 int r=real_recv(s,b,n,flags);int err=errno;
 if(p) {int64_t end=now_ns(CLOCK_MONOTONIC);
  if(r>=0 || err!=EAGAIN)add(2,p,flags,start,end,r,r<0?err:0);
  else if(end-start>200000)add(9,p,flags,start,end,r,err);
  if(flags&ZMQ_DONTWAIT)last_poll_end[port_index(p)]=end;
 }errno=err;return r;
}
int zmq_msg_send(zmq_msg_t*m,void*s,int flags) {
 int p=socket_port(s);int64_t start=p?now_ns(CLOCK_MONOTONIC):0;
 int r=real_msg_send(m,s,flags);int err=errno;
 if(p && (r>=0 || err!=EAGAIN))add(1,p,flags,start,now_ns(CLOCK_MONOTONIC),r,r<0?err:0);
 errno=err;return r;
}
int zmq_msg_recv(zmq_msg_t*m,void*s,int flags) {
 int p=socket_port(s);int64_t start=p?now_ns(CLOCK_MONOTONIC):0;
 if(p && (flags&ZMQ_DONTWAIT)) {int i=port_index(p);if(last_poll_end[i] && start-last_poll_end[i]>1000000)add(8,p,flags,last_poll_end[i],start,0,0);}
 int r=real_msg_recv(m,s,flags);int err=errno;
 if(p) {int64_t end=now_ns(CLOCK_MONOTONIC);
  if(r>=0 || err!=EAGAIN)add(2,p,flags,start,end,r,r<0?err:0);
  else if(end-start>200000)add(9,p,flags,start,end,r,err);
  if(flags&ZMQ_DONTWAIT)last_poll_end[port_index(p)]=end;
 }errno=err;return r;
}
size_t fwrite(const void*p,size_t size,size_t n,FILE*f) {
 if(!real_fwrite)real_fwrite=dlsym(RTLD_NEXT,"fwrite");
 if(!head)return real_fwrite(p,size,n,f);
 int64_t start=now_ns(CLOCK_MONOTONIC);size_t result=real_fwrite(p,size,n,f);int err=errno;int64_t end=now_ns(CLOCK_MONOTONIC);
 if(end-start>200000)add(7,-fileno(f),0,start,end,result*size,0);
 errno=err;return result;
}
