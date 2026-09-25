#!/usr/bin/env python3
"""Turn the L4T kernel's net/sctp sources into an out-of-tree module for a
kernel built without CONFIG_IP_SCTP (Jetson R36.4.4, 5.15.148-tegra).

Such a kernel's `struct net` has no `sctp` member (net_namespace.h only adds it
when IP_SCTP is configured), so the per-namespace state moves to net_generic()
storage registered through sctp_defaults_ops (.id/.size):

  - every `net->sctp.` / `sock_net(sk)->sctp.` becomes `sctp_pernet(...)->`;
  - the SCTP_*_STATS macros (include/net/sctp/sctp.h, used only from the .c
    files) are renamed SCTP_OOT_*_STATS in the sources and defined, with
    sctp_pernet(), in sctp_oot.h, force-included by Kbuild. The kernel headers
    stay untouched: kbuild puts them ahead of any module -I;
  - sysctl.c's static table points into a module-local template instead of
    init_net.sctp and is relocated against sctp_pernet(net).

    prepare-sctp-oot.py <kernel-src net/sctp dir> <kernel headers dir> <out dir>
"""
import re, shutil, sys
from pathlib import Path

src, kdir, out = map(Path, sys.argv[1:4])
if out.exists():
    shutil.rmtree(out)
shutil.copytree(src, out)
(out / 'sctp_oot.h').write_text('''/* Force-included (Kbuild). Out-of-tree SCTP for a kernel without
 * CONFIG_IP_SCTP: struct net has no sctp member, so the per-namespace state
 * lives in net_generic() storage (see prepare-sctp-oot.py). */
#ifndef SCTP_OOT_H
#define SCTP_OOT_H
#include <net/net_namespace.h>
#include <net/netns/generic.h>
#include <net/netns/sctp.h>
#include <net/snmp.h>
extern unsigned int sctp_net_id;
/* The pernet storage keeps a back-pointer: the address-work timer callback
 * recovered its struct net with from_timer(net, t, sctp.addr_wq_timer). */
struct sctp_oot_pernet {
	struct netns_sctp sctp;
	struct net *net;
};
static inline struct netns_sctp *sctp_pernet(const struct net *net)
{
	return &((struct sctp_oot_pernet *)net_generic(net, sctp_net_id))->sctp;
}
#define SCTP_OOT_INC_STATS(net, field)   SNMP_INC_STATS(sctp_pernet(net)->sctp_statistics, field)
#define __SCTP_OOT_INC_STATS(net, field) __SNMP_INC_STATS(sctp_pernet(net)->sctp_statistics, field)
#define SCTP_OOT_DEC_STATS(net, field)   SNMP_DEC_STATS(sctp_pernet(net)->sctp_statistics, field)
#endif
''')
n_h = 0

total = 0
for c in sorted(out.glob('*.c')):
    s = c.read_text()
    s, n1 = re.subn(r'\bsock_net\(sk\)->sctp\.', 'sctp_pernet(sock_net(sk))->', s)
    # Any member path ending in a struct net pointer: net->sctp., asoc->base.net->sctp., ...
    s, n2 = re.subn(r'\b([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)->sctp\.', r'sctp_pernet(\1)->', s)
    s, n3 = re.subn(r'\b(__)?SCTP_(INC|DEC)_STATS\(', lambda m: f"{m.group(1) or ''}SCTP_OOT_{m.group(2)}_STATS(", s)
    total += n1 + n2
    n_h += n3
    if c.name == 'sysctl.c':
        s = s.replace('init_net.sctp.', 'sctp_sysctl_template.')
        old = 'table[i].data += (char *)(&net->sctp) - (char *)&init_net.sctp;'
        assert s.count(old) == 1, 'sysctl relocation'
        s = s.replace(old, 'table[i].data += (char *)sctp_pernet(net) - (char *)&sctp_sysctl_template;')
        first = s.index('static struct ctl_table sctp_net_table[]')
        s = s[:first] + ('/* Static table target; relocated per namespace in sctp_sysctl_net_register(). */\n'
                         'static struct netns_sctp sctp_sysctl_template;\n\n') + s[first:]
    if c.name == 'protocol.c':
        old = 'static struct pernet_operations sctp_defaults_ops = {\n\t.init = sctp_defaults_init,\n'
        assert s.count(old) == 1, 'pernet ops'
        s = s.replace(old, old + '\t.id   = &sctp_net_id,\n\t.size = sizeof(struct sctp_oot_pernet),\n')
        old = '\tstruct net *net = from_timer(net, t, sctp.addr_wq_timer);'
        assert s.count(old) == 1, 'addr_wq timer'
        s = s.replace(old, '\tstruct net *net = container_of(t, struct sctp_oot_pernet, sctp.addr_wq_timer)->net;')
        m = re.search(r'static int __net_init sctp_defaults_init\(struct net \*net\)\n\{\n(\t[^\n]*;\n)*', s)
        assert m, 'sctp_defaults_init'
        s = s[:m.end()] + ('\n\tcontainer_of(sctp_pernet(net), struct sctp_oot_pernet, sctp)->net = net;\n') + s[m.end():]
        s = 'unsigned int sctp_net_id __read_mostly;\n' + s
    c.write_text(s)

left = [f'{c.name}:{i}' for c in out.glob('*.c') for i, l in enumerate(c.read_text().splitlines(), 1)
        if re.search(r'->sctp\.|init_net\.sctp', l)]
if left:
    raise SystemExit(f'unconverted accesses: {left}')
(out / 'Kbuild').write_text('''obj-m += sctp.o sctp_diag.o
sctp-y := sm_statetable.o sm_statefuns.o sm_sideeffect.o \\
	  protocol.o endpointola.o associola.o \\
	  transport.o chunk.o sm_make_chunk.o ulpevent.o \\
	  inqueue.o outqueue.o ulpqueue.o \\
	  tsnmap.o bind_addr.o socket.o primitive.o \\
	  output.o input.o debug.o stream.o auth.o \\
	  offload.o stream_sched.o stream_sched_prio.o \\
	  stream_sched_rr.o stream_interleave.o proc.o sysctl.o ipv6.o
sctp_diag-y := diag.o
ccflags-y += -DCONFIG_SCTP_DEFAULT_COOKIE_HMAC_SHA1 -include $(src)/sctp_oot.h
''')
print(f'converted {total} net->sctp accesses and {n_h} stats macro uses; out={out}')
