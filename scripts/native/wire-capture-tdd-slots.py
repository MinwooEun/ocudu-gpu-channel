#!/usr/bin/env python3
"""Per-TDD-slot power of a broker wire capture (X4 UE<->UE evidence).

For a TDD cell the question "where does the other UE's energy land?" is a
per-slot one: the victim UE only ever receives in DL slots, so energy that a
UE<->UE edge adds to its RX in the *UL* slots is harmless, while energy in the
DL slots would be interference. This tool cuts every `<port>.tx_in.cf32` /
`<port>.rx_out.cf32` of a `--wire-capture-dir` into slots (11520 samples =
0.5 ms at 23.04 MS/s / 30 kHz), finds the TDD period phase from the gNB's own
TX (the gNB radiates in DL slots and is silent in UL slots; every port's
capture starts at the same broker sample index), and prints the median power
per slot-in-period for every port and direction, with the slot kind
(D / S / U) from the pattern (default: OCUDU 10-slot 7 DL / special / 2 UL).

Stdlib only (the Spark's system Python has no numpy).
"""

from __future__ import annotations

import argparse
import array
import json
import math
import pathlib
import statistics
import sys


def slot_powers(path: pathlib.Path, slot_samples: int) -> list[float]:
    samples = array.array("f")
    count = path.stat().st_size // 4
    with path.open("rb") as handle:
        samples.fromfile(handle, count)
    slots = []
    for start in range(0, count - 2 * slot_samples + 1, 2 * slot_samples):
        acc = 0.0
        for i in range(start, start + 2 * slot_samples, 2):
            acc += samples[i] * samples[i] + samples[i + 1] * samples[i + 1]
        slots.append(acc / slot_samples)
    return slots


def db(value: float) -> float | None:
    return round(10.0 * math.log10(value), 2) if value > 0.0 else None


def find_phase(gnb_slots: list[float], period: int, dl_slots: int) -> int:
    """Phase p such that slots (p + k) % period < dl_slots are the loud DL ones."""

    best, best_score = 0, -math.inf
    for phase in range(period):
        dl = [v for i, v in enumerate(gnb_slots) if (i - phase) % period < dl_slots]
        ul = [v for i, v in enumerate(gnb_slots) if (i - phase) % period >= dl_slots + 1]
        if not dl or not ul:
            continue
        score = statistics.median(dl) / (statistics.median(ul) + 1e-30)
        if score > best_score:
            best, best_score = phase, score
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("capture_dir", type=pathlib.Path)
    parser.add_argument("--slot-samples", type=int, default=11520, help="samples per slot (0.5 ms at 23.04 MS/s)")
    parser.add_argument("--period", type=int, default=10, help="TDD period in slots")
    parser.add_argument("--dl-slots", type=int, default=7, help="full DL slots per period (then one special, then UL)")
    parser.add_argument("--gnb-port", default="gnb0", help="port whose tx_in fixes the period phase")
    parser.add_argument("--json", type=pathlib.Path, help="write the table as JSON here too")
    args = parser.parse_args()

    manifest = json.loads((args.capture_dir / "wire-capture.json").read_text(encoding="utf-8"))
    series: dict[str, list[float]] = {}
    for port in manifest["ports"]:
        for direction in ("tx_in", "rx_out"):
            path = args.capture_dir / f"{port['id']}.{direction}.cf32"
            if path.exists():
                series[f"{port['id']}.{direction}"] = slot_powers(path, args.slot_samples)
    gnb_key = f"{args.gnb_port}.tx_in"
    if gnb_key not in series:
        sys.exit(f"no {gnb_key} in the capture; cannot fix the TDD phase")
    phase = find_phase(series[gnb_key], args.period, args.dl_slots)

    def kind(slot: int) -> str:
        return "D" if slot < args.dl_slots else ("S" if slot == args.dl_slots else "U")

    report = {"capture_dir": str(args.capture_dir), "slot_samples": args.slot_samples, "period": args.period,
              "dl_slots": args.dl_slots, "phase": phase, "slots_total": len(series[gnb_key]), "per_slot": {}}
    header = f"{'port':16s} " + " ".join(f"{kind(s)}{s}".rjust(7) for s in range(args.period)) + "   D-med   U-med"
    print(f"phase={phase} (slot index of the first DL slot), {len(series[gnb_key])} slots, "
          f"{args.slot_samples} samples/slot")
    print(header)
    for key, values in series.items():
        per_slot = []
        for slot in range(args.period):
            picked = [v for i, v in enumerate(values) if (i - phase) % args.period == slot]
            per_slot.append(statistics.median(picked) if picked else 0.0)
        d_med = statistics.median(per_slot[: args.dl_slots])
        u_med = statistics.median(per_slot[args.dl_slots + 1:]) if args.period > args.dl_slots + 1 else 0.0
        report["per_slot"][key] = {"median_power_db": [db(v) for v in per_slot], "dl_median_db": db(d_med),
                                   "ul_median_db": db(u_med)}
        cells = " ".join(f"{(db(v) if db(v) is not None else float('nan')):7.1f}" for v in per_slot)
        print(f"{key:16s} {cells}   {db(d_med) if db(d_med) is not None else 'nan':>6} {db(u_med) if db(u_med) is not None else 'nan':>7}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
