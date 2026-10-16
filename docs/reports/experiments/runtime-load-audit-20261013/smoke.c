#include <zmq.h>
#include <pthread.h>
#include <assert.h>
#include <string.h>
static void *ctx;
static void *server(void *arg) {void*s=zmq_socket(ctx,ZMQ_REP);assert(zmq_bind(s,"tcp://127.0.0.1:2103")==0);for(int i=0;i<100;i++){char b[8];assert(zmq_recv(s,b,8,0)==1);assert(zmq_send(s,"abcdefgh",8,0)==8);}zmq_close(s);return 0;}
int main(void) {ctx=zmq_ctx_new();pthread_t t;pthread_create(&t,0,server,0);void*s=zmq_socket(ctx,ZMQ_REQ);assert(zmq_connect(s,"tcp://127.0.0.1:2103")==0);for(int i=0;i<100;i++){char b[8];assert(zmq_send(s,"x",1,0)==1);assert(zmq_recv(s,b,8,0)==8);assert(memcmp(b,"abcdefgh",8)==0);}zmq_close(s);pthread_join(t,0);zmq_ctx_term(ctx);return 0;}
