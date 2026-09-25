#!/usr/bin/env python3
"""Sample thread affinity and GPU occupancy while a gate run is in flight.

C5 asks that MPS and P-core pinning be applied identically to the baseline, the
accelerated run and the shared services, and that the *actual* thread affinity
be recorded. Passing `taskset` is not that record: it states an intent. This
reads `/proc/<pid>/task/<tid>/status` for the mask each thread really carries
and field 39 of `.../stat` for the CPU it last ran on, so a thread that escaped
the mask -- or a service that was never inside it -- shows up as a fact rather
than as an assumption.

Run it alongside the gate; it exits when the named processes are all gone or
the deadline passes. Output is one JSON object per sample in a .jsonl, plus a
summary with the union of masks and CPUs actually used per process.
"""
from __future__ import annotations
import argparse, json, os, subprocess, time
from pathlib import Path

PROC = Path('/proc')
# The gate's own processes plus every shared service it starts. All of them
# have to be inside the same envelope for a paired comparison to mean anything.
DEFAULT_NAMES = ('gnb', 'ocudu-gpu-channel', 'srsue', '5gc', 'mongod')


def parse_cpu_list(text: str) -> set[int]:
    cpus: set[int] = set()
    for part in text.strip().split(','):
        if not part:
            continue
        if '-' in part:
            lo, hi = part.split('-', 1)
            cpus.update(range(int(lo), int(hi) + 1))
        else:
            cpus.add(int(part))
    return cpus


def read_threads(pid: int) -> list[dict]:
    threads = []
    task = PROC / str(pid) / 'task'
    try:
        tids = os.listdir(task)
    except OSError:
        return threads
    for tid in tids:
        try:
            status = (task / tid / 'status').read_text()
            stat = (task / tid / 'stat').read_text()
        except OSError:
            continue
        allowed = ''
        for line in status.splitlines():
            if line.startswith('Cpus_allowed_list:'):
                allowed = line.split(':', 1)[1].strip()
                break
        # Field 39 is `processor`, the CPU this thread last executed on. The
        # comm field can contain spaces and parentheses, so split after it.
        try:
            fields = stat[stat.rindex(')') + 2:].split()
            last_cpu = int(fields[36])
        except (ValueError, IndexError):
            last_cpu = -1
        name = ''
        try:
            name = (task / tid / 'comm').read_text().strip()
        except OSError:
            pass
        threads.append({'tid': int(tid), 'comm': name, 'cpus_allowed': allowed, 'last_cpu': last_cpu})
    return threads


def find_pids(names: tuple[str, ...], started_after: float | None = None) -> dict[str, list[int]]:
    """Live processes only, and by default only ones this run started.

    A reaped-but-not-waited process keeps its /proc entry and its task dir, so a
    zombie left by an earlier run is indistinguishable from a running one by
    name alone -- we counted two days' worth of them into an affinity summary
    before this filter existed. `started_after` additionally excludes the
    long-lived services that happen to share a name with the ones the gate
    starts for itself.
    """
    found: dict[str, list[int]] = {n: [] for n in names}
    # /proc/<pid>/comm is truncated to TASK_COMM_LEN-1 = 15 characters, so the
    # broker -- `ocudu-gpu-channel`, 17 characters -- never matched by its real
    # name and dropped out of the envelope entirely. Match on the truncation.
    by_comm = {n[:15]: n for n in names}
    boot = boot_time()
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / 'comm').read_text().strip()
            name = by_comm.get(comm)
            if name is None:
                continue
            status = (entry / 'status').read_text()
        except OSError:
            continue
        state = ''
        for line in status.splitlines():
            if line.startswith('State:'):
                state = line.split(':', 1)[1].strip()
                break
        if state.startswith(('Z', 'X')):
            continue
        if started_after is not None and boot is not None:
            start = process_start_unix(entry, boot)
            if start is None or start < started_after:
                continue
        found[name].append(int(entry.name))
    return found


def boot_time() -> float | None:
    try:
        for line in (PROC / 'stat').read_text().splitlines():
            if line.startswith('btime '):
                return float(line.split()[1])
    except OSError:
        pass
    return None


def process_start_unix(entry: Path, boot: float) -> float | None:
    """Field 22 of /proc/<pid>/stat is starttime, in clock ticks since boot."""
    try:
        stat = (entry / 'stat').read_text()
        fields = stat[stat.rindex(')') + 2:].split()
        return boot + float(fields[19]) / os.sysconf('SC_CLK_TCK')
    except (OSError, ValueError, IndexError):
        return None


def gpu_sample() -> dict:
    out: dict = {}
    try:
        text = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=utilization.gpu,utilization.memory,memory.used,power.draw,clocks.sm',
             '--format=csv,noheader,nounits'], text=True, timeout=5).strip()
        gpu, mem, used, power, sm = (v.strip() for v in text.split(','))
        out['gpu'] = {'util_pct': gpu, 'mem_util_pct': mem, 'mem_used_mib': used,
                      'power_w': power, 'sm_clock_mhz': sm}
    except (subprocess.SubprocessError, OSError, ValueError):
        out['gpu'] = None
    try:
        text = subprocess.check_output(
            ['nvidia-smi', '--query-compute-apps=pid,process_name,used_memory',
             '--format=csv,noheader,nounits'], text=True, timeout=5).strip()
        out['compute_apps'] = [line.strip() for line in text.splitlines() if line.strip()]
    except (subprocess.SubprocessError, OSError):
        out['compute_apps'] = None
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', required=True, type=Path, help='directory for the samples')
    parser.add_argument('--label', required=True, help='which arm of the pair this is')
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--deadline-seconds', type=float, default=600.0)
    parser.add_argument('--names', default=','.join(DEFAULT_NAMES))
    parser.add_argument('--settle-seconds', type=float, default=30.0,
                        help='keep waiting this long for the processes to appear before giving up')
    parser.add_argument('--include-pre-existing', action='store_true',
                        help='also count processes that were already running when sampling began')
    args = parser.parse_args()
    names = tuple(n for n in args.names.split(',') if n)
    args.out.mkdir(parents=True, exist_ok=True)
    samples = args.out / f'{args.label}.telemetry.jsonl'

    masks: dict[str, set[str]] = {}
    used: dict[str, set[int]] = {}
    seen_any = False
    started = time.monotonic()
    started_after = None if args.include_pre_existing else time.time()
    with samples.open('w') as stream:
        while time.monotonic() - started < args.deadline_seconds:
            pids = find_pids(names, started_after)
            alive = {n: p for n, p in pids.items() if p}
            if alive:
                seen_any = True
            elif seen_any:
                break  # the run finished
            elif time.monotonic() - started > args.settle_seconds:
                break  # nothing ever showed up
            record = {'unix_seconds': time.time(), 'processes': {}}
            for name, pid_list in alive.items():
                entries = []
                for pid in pid_list:
                    threads = read_threads(pid)
                    entries.append({'pid': pid, 'threads': threads})
                    for thread in threads:
                        if thread['cpus_allowed']:
                            masks.setdefault(name, set()).add(thread['cpus_allowed'])
                        if thread['last_cpu'] >= 0:
                            used.setdefault(name, set()).add(thread['last_cpu'])
                record['processes'][name] = entries
            record.update(gpu_sample())
            stream.write(json.dumps(record) + '\n')
            stream.flush()
            time.sleep(args.interval)

    summary = {
        'label': args.label,
        'observed': sorted(masks),
        'affinity_masks': {k: sorted(v) for k, v in sorted(masks.items())},
        'cpus_actually_used': {k: sorted(v) for k, v in sorted(used.items())},
        'samples': str(samples),
    }
    # One mask across every process is the whole point; say so explicitly
    # rather than making a reader diff the lists.
    all_masks = {m for v in masks.values() for m in v}
    summary['single_mask'] = sorted(all_masks)[0] if len(all_masks) == 1 else None
    summary['uniform_envelope'] = len(all_masks) == 1
    (args.out / f'{args.label}.affinity.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: summary[k] for k in ('label', 'uniform_envelope', 'single_mask',
                                              'affinity_masks', 'cpus_actually_used')}, indent=2))


if __name__ == '__main__':
    main()
