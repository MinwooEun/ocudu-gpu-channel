// S10 (SPARK_MILESTONES.md): keep one core out of CPU idle states without
// delaying wakeups. It loops on sched_yield(), so a thread woken on this core
// runs at the next yield. A plain SCHED_IDLE spinner delayed woken threads by
// about 6 ms on GB10 (kernel built with PREEMPT_LAZY). Run nice 19, pinned.
// Build: gcc -O2 s10-yieldspin.c   usage: s10-yieldspin <seconds>
#include <sched.h>
#include <stdlib.h>
#include <time.h>
int main(int argc, char** argv)
{
  const time_t end = time(NULL) + (argc > 1 ? atoi(argv[1]) : 60);
  while (time(NULL) < end) {
    for (int i = 0; i < 1000; ++i) {
      sched_yield();
    }
  }
  return 0;
}
