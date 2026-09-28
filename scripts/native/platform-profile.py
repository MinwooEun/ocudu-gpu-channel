#!/usr/bin/env python3
"""Resolve the CPU placement a native gate applies on this host.

OCUDU_NATIVE_PLATFORM selects the profile: `auto` (default) matches the host
against platform-profiles.json, `none` applies nothing, any other value must be
a profile name. An unknown host resolves to no placement, so the gates behave
exactly as before there. A per-process OCUDU_NATIVE_{GNB,BROKER,NRUE}_CPUS that
is already set wins over the profile.

usage: platform-profile.py --shell   (prints shell assignments to eval)
       platform-profile.py --json    (prints the resolution record)
"""
import json
import os
from pathlib import Path
import subprocess
import sys

PROFILES = Path(__file__).resolve().parent / 'platform-profiles.json'
ROLES = ('gnb', 'broker', 'nrue')


def cpu_list(cpus):
    out = []
    for part in cpus.split(','):
        low, _, high = part.partition('-')
        out.extend(range(int(low), int(high or low) + 1))
    return out


def fastest_cpus():
    freqs = {}
    for path in Path('/sys/devices/system/cpu').glob('cpu[0-9]*/cpufreq/cpuinfo_max_freq'):
        freqs[int(path.parent.parent.name[3:])] = int(path.read_text())
    if not freqs:
        return []
    top = max(freqs.values())
    return sorted(cpu for cpu, freq in freqs.items() if freq == top)


def online_cpus():
    try:
        return cpu_list(Path('/sys/devices/system/cpu/online').read_text().strip())
    except OSError:
        return []


def gpu_names():
    try:
        out = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=20)
        return [line.strip() for line in out.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def resolve():
    profiles = json.loads(PROFILES.read_text())['profiles']
    wanted = os.environ.get('OCUDU_NATIVE_PLATFORM', 'auto')
    record = {'requested': wanted, 'profile': None, 'cpus': {}, 'source': {}}
    if wanted == 'none':
        record['reason'] = 'OCUDU_NATIVE_PLATFORM=none'
    elif wanted == 'auto':
        host = {'gpu_names': gpu_names(), 'fastest_cpus': fastest_cpus(), 'online_cpus': online_cpus()}
        record['host'] = host
        for name, profile in profiles.items():
            detect = profile['detect']
            # online_cpus is optional: it tells power modes that take cores offline
            # apart (Orin MODE_30W runs 8 of 12 cores).
            online_ok = 'online_cpus' not in detect or cpu_list(detect['online_cpus']) == host['online_cpus']
            if (detect['gpu_name'] in host['gpu_names'] and cpu_list(detect['fastest_cpus']) == host['fastest_cpus']
                    and online_ok):
                record['profile'] = name
                break
        else:
            record['reason'] = 'no profile matches this host'
    elif wanted in profiles:
        record['profile'] = wanted
    else:
        sys.exit(f'error: OCUDU_NATIVE_PLATFORM={wanted} is not a profile in {PROFILES.name}')
    for role in ROLES:
        key = f'OCUDU_NATIVE_{role.upper()}_CPUS'
        if os.environ.get(key):
            record['cpus'][role] = os.environ[key]
            record['source'][role] = 'env'
        elif record['profile']:
            record['cpus'][role] = profiles[record['profile']]['cpus'][role]
            record['source'][role] = 'profile'
    for role, cpus in record['cpus'].items():
        cpu_list(cpus)  # reject a malformed list before any process starts
    return record


def main():
    if sys.argv[1:] not in (['--shell'], ['--json']):
        sys.exit(__doc__)
    record = resolve()
    if sys.argv[1] == '--json':
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    print(f"OCUDU_NATIVE_PLATFORM_PROFILE='{record['profile'] or 'none'}'")
    for role in ROLES:
        print(f"OCUDU_NATIVE_{role.upper()}_CPUS='{record['cpus'].get(role, '')}'")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
