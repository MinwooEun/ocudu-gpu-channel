#!/usr/bin/env python3
"""Transmit/receive level of a broker wire capture, per port and direction.

Reads the `wire-capture.json` manifest the broker writes with
`--wire-capture-dir` and prints, for every `<port>.tx_in.cf32` (what the peer
put on the wire) and `<port>.rx_out.cf32` (what the broker handed back), the
mean |x|^2 over all samples, the mean over the *active* samples only (those
above 1e-3 of the peak instantaneous power, i.e. idle slots excluded), the
active fraction and the peak amplitude. The active mean is the reference the
Sionna receiver noise floor is sized against (render-sionna-multi-ue-configs.py
TX_POWER_DL / TX_POWER_UL), so it is the number to quote.

Stdlib only: the capture can be large and the Spark's system Python has no
numpy.
"""

from __future__ import annotations

import argparse
import array
import json
import math
import pathlib
import sys


def level(path: pathlib.Path, slot_samples: int) -> dict:
    samples = array.array("f")
    count = path.stat().st_size // 4
    with path.open("rb") as handle:
        samples.fromfile(handle, count)
    powers = [samples[i] * samples[i] + samples[i + 1] * samples[i + 1] for i in range(0, count - 1, 2)]
    if not powers:
        return {"samples": 0}
    peak = max(powers)
    threshold = 1e-3 * peak
    active = [p for p in powers if p > threshold]
    slots = [sum(powers[k:k + slot_samples]) / slot_samples
             for k in range(0, len(powers) - slot_samples + 1, slot_samples)]
    slots.sort()

    def db(value: float) -> float | None:
        return round(10.0 * math.log10(value), 2) if value > 0.0 else None

    mean = sum(powers) / len(powers)
    active_mean = sum(active) / len(active) if active else 0.0
    return {
        "samples": len(powers),
        "mean_power": mean,
        "mean_power_db": db(mean),
        "active_fraction": round(len(active) / len(powers), 4),
        "active_mean_power": active_mean,
        "active_mean_power_db": db(active_mean),
        "peak_amplitude": round(math.sqrt(peak), 4),
        "slot_power_db_p10_p50_p90": [db(slots[len(slots) // 10]), db(slots[len(slots) // 2]),
                                      db(slots[9 * len(slots) // 10])] if slots else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("capture_dir", type=pathlib.Path)
    parser.add_argument("--slot-samples", type=int, default=23040, help="samples per slot (1 ms at 23.04 MS/s)")
    parser.add_argument("--json", type=pathlib.Path, help="write the table as JSON here too")
    args = parser.parse_args()
    manifest = json.loads((args.capture_dir / "wire-capture.json").read_text(encoding="utf-8"))
    report = {"capture_dir": str(args.capture_dir), "manifest": manifest, "ports": {}}
    for port in manifest["ports"]:
        for direction in ("tx_in", "rx_out"):
            path = args.capture_dir / f"{port['id']}.{direction}.cf32"
            if not path.exists():
                continue
            entry = level(path, args.slot_samples)
            report["ports"][f"{port['id']}.{direction}"] = entry
            print(f"{port['id']:10s} {direction:6s} samples={entry.get('samples', 0):9d} "
                  f"mean={entry.get('mean_power_db')} dB active_frac={entry.get('active_fraction')} "
                  f"active_mean={entry.get('active_mean_power', 0.0):.4g} ({entry.get('active_mean_power_db')} dB) "
                  f"peak_amp={entry.get('peak_amplitude')} slot_p10/50/90={entry.get('slot_power_db_p10_p50_p90')}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
