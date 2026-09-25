#!/usr/bin/env python3
"""Check that an acceleration rung actually engaged the backends it asked for.

C4's exit gate is not satisfied by a passing attach. A gNB that quietly runs a
requested path on the host still attaches, pings and reports every counter
clean, so the run has to be scored against what the runtime log says was
selected -- not against whether it survived.

Three outcomes, kept distinct because they mean different things:

  selected   the accelerated path the rung asked for is the one that ran
  degraded   a GPU path ran, but not the one the rung asked for. The lower-PHY
             TX host-grid staging fallback is this: still CUDA, but reading a
             host-staged copy instead of the device-resident grid. It is not a
             failure, and it is not a pass either -- keeping the data on the
             device is the point of the integration, so it is named.
  fallback   the path ran on the host. This is the silent-fallback case C4
             exists to exclude, and it fails the rung.

Rungs are cumulative: `pdsch` must still show everything `pusch` showed.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

STAGES = ('disabled', 'low-phy-rx', 'low-phy-tx', 'pusch', 'pdsch', 'prach', 'all')

# Marker introduced by each rung, checked cumulatively from that rung upward.
SELECTED = {
    'low-phy-rx': ('Lower-PHY RX GPU path selected: direct CUDA-visible uplink resource-grid writer.',),
    'low-phy-tx': ('Lower-PHY TX GPU path selected: direct CUDA-visible downlink resource-grid reader.',),
    'prach': ('Lower-PHY PRACH demodulation GPU path selected: direct CUDA-visible PRACH buffer writer.',),
}
# A GPU path that is not the one asked for.
DEGRADED = {
    'low-phy-tx': ('Lower-PHY TX GPU path selected: host resource-grid staging fallback.',),
}
# Anything matching these means a requested path did not run on the GPU at all.
UNAVAILABLE = re.compile(r'Lower-PHY .* GPU path unavailable: (?P<why>.*)')
# `<NAME> acceleration manifest: requested=<r> ... backend=<b>`
MANIFEST = re.compile(r'(?P<name>[A-Z]+) acceleration manifest: requested=(?P<requested>\w+).*?backend=(?P<backend>\w+)')
# Which upper-PHY manifests each rung turns on, cumulatively.
UPPER = {'pusch': 'PUSCH', 'pdsch': 'PDSCH', 'prach': 'PRACH', 'all': 'SRS'}


def check(stage: str, log: Path) -> dict:
    if stage not in STAGES:
        raise SystemExit(f'unknown stage: {stage}')
    index = STAGES.index(stage)
    active = STAGES[1:index + 1]
    text = log.read_text(errors='replace')

    result: dict = {'stage': stage, 'log': str(log), 'selected': [], 'degraded': [],
                    'missing': [], 'host_fallback': [], 'unavailable': []}

    for rung in active:
        for marker in SELECTED.get(rung, ()):
            if marker in text:
                result['selected'].append(rung)
                break
        else:
            if any(m in text for m in DEGRADED.get(rung, ())):
                result['degraded'].append(rung)
            elif rung in SELECTED:
                result['missing'].append(rung)

    for match in UNAVAILABLE.finditer(text):
        result['unavailable'].append(match.group('why'))

    # An upper-PHY mode this rung enabled must report backend=CUDA. A manifest
    # saying requested=enabled backend=host is the silent fallback itself.
    wanted = {UPPER[r] for r in active if r in UPPER}
    seen = {}
    for match in MANIFEST.finditer(text):
        seen[match.group('name')] = (match.group('requested'), match.group('backend'))
    for name in sorted(wanted):
        if name not in seen:
            result['missing'].append(f'{name} manifest')
        else:
            requested, backend = seen[name]
            if backend.upper() == 'CUDA':
                result['selected'].append(name)
            else:
                result['host_fallback'].append(f'{name} requested={requested} backend={backend}')
    result['manifests'] = {k: {'requested': v[0], 'backend': v[1]} for k, v in sorted(seen.items())}

    if result['host_fallback'] or result['missing']:
        result['verdict'] = 'FAIL'
    elif result['unavailable']:
        result['verdict'] = 'FAIL'
    elif result['degraded']:
        result['verdict'] = 'DEGRADED'
    else:
        result['verdict'] = 'OK'
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('stage')
    parser.add_argument('log', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if not args.log.is_file():
        raise SystemExit(f'no such log: {args.log}')
    data = check(args.stage, args.log)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        bits = [data['verdict']]
        for key in ('selected', 'degraded', 'missing', 'host_fallback', 'unavailable'):
            if data[key]:
                bits.append(f'{key}={",".join(map(str, data[key]))}')
        print(' '.join(bits))
    raise SystemExit({'OK': 0, 'DEGRADED': 1, 'FAIL': 2}[data['verdict']])


if __name__ == '__main__':
    main()
