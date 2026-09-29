#!/usr/bin/env python3
"""Join srsUE link quality with the Sionna positions of a multi-UE gate run.

For every UE the gate started, the per-second srsUE metrics CSV
(`srsue-metrics-<ue>.csv`, clock = seconds since that UE started, start
recorded in `srsue-<ue>.start_unix_ms`) is aligned by wall clock with the
bridge's `sionna-status.jsonl` (`update_started_unix_ms`, the traced positions
and per-link tap gains). Each metrics row then carries the UE's position and
the downlink gain Sionna gave it at that moment, and rows are classed as
`los` (within 6 dB of the link's best gain in the run) or `shadow` (15 dB or
more below it). The report says whether the UE's reported SNR, MCS and BLER
differ between the two -- the R4 evidence that the ring's geometry reaches
the decoder -- and the correlation between the Sionna gain and the reported
SNR over the whole run.

Stdlib only.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import pathlib
import statistics
import sys


def load_bridge(status_jsonl: pathlib.Path) -> list[dict]:
    updates = []
    for line in status_jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"sionna_rt_update"' not in line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") != "sionna_rt_update" or "update_started_unix_ms" not in record:
            continue
        gains = {}
        for channel in record.get("channels") or []:
            link_id = channel.get("link_id", "")
            gain = channel.get("strongest_tap_gain_db")
            total = channel.get("total_path_power_db")
            if link_id:
                gains[link_id] = {"strongest_tap_gain_db": gain, "total_path_power_db": total,
                                  "ray_count": channel.get("ray_count")}
        updates.append({
            "t_ms": int(record["update_started_unix_ms"]),
            "positions": record.get("positions") or {},
            "gains": gains,
            "position_source": record.get("position_source"),
        })
    updates.sort(key=lambda u: u["t_ms"])
    return updates


def load_metrics(csv_path: pathlib.Path, start_unix_ms: int) -> list[dict]:
    rows = []
    with csv_path.open(encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for raw in reader:
            try:
                row = {
                    "t_ms": start_unix_ms + int(float(raw["time"])),
                    "rsrp": float(raw["rsrp"]), "dl_mcs": float(raw["dl_mcs"]),
                    "dl_snr": float(raw["dl_snr"]), "dl_bler": float(raw["dl_bler"]),
                    "dl_brate": float(raw["dl_brate"]), "ul_mcs": float(raw["ul_mcs"]),
                    "ul_bler": float(raw["ul_bler"]), "ul_brate": float(raw["ul_brate"]),
                    "rf_o": float(raw["rf_o"]), "rf_u": float(raw["rf_u"]), "rf_l": float(raw["rf_l"]),
                    "is_attached": raw.get("is_attached", "").strip(),
                }
            except (KeyError, ValueError):
                continue
            rows.append(row)
    return rows


def nearest(updates: list[dict], keys: list[int], t_ms: int, max_gap_ms: int) -> dict | None:
    index = bisect.bisect_left(keys, t_ms)
    candidates = [i for i in (index - 1, index) if 0 <= i < len(updates)]
    if not candidates:
        return None
    best = min(candidates, key=lambda i: abs(keys[i] - t_ms))
    return updates[best] if abs(keys[best] - t_ms) <= max_gap_ms else None


def summarize(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"n": len(values), "mean": round(statistics.fmean(values), 2),
            "median": round(statistics.median(values), 2),
            "min": round(min(values), 2), "max": round(max(values), 2)}


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0.0 or syy == 0.0:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy), 3)


def analyse_ue(ue: str, gnb: str, rows: list[dict], updates: list[dict], keys: list[int],
               max_gap_ms: int, los_within_db: float, shadow_below_db: float) -> dict:
    dl_link = f"{gnb}>{ue}:sionna_rt"
    joined = []
    for row in rows:
        update = nearest(updates, keys, row["t_ms"], max_gap_ms)
        if update is None:
            continue
        gain = (update["gains"].get(dl_link) or {}).get("strongest_tap_gain_db")
        joined.append({**row, "position": update["positions"].get(ue), "dl_gain_db": gain})
    attached = [j for j in joined if j["dl_gain_db"] is not None and j["dl_snr"] != 0.0]
    gains = [j["dl_gain_db"] for j in attached]
    report = {"ue": ue, "metrics_rows": len(rows), "joined_rows": len(joined), "attached_rows": len(attached)}
    if not attached:
        return report
    best = max(gains)
    los = [j for j in attached if j["dl_gain_db"] >= best - los_within_db]
    shadow = [j for j in attached if j["dl_gain_db"] <= best - shadow_below_db]
    report.update({
        "best_dl_gain_db": round(best, 2), "worst_dl_gain_db": round(min(gains), 2),
        "gain_snr_pearson": pearson(gains, [j["dl_snr"] for j in attached]),
        "gain_mcs_pearson": pearson(gains, [j["dl_mcs"] for j in attached]),
        "rf_overflow_underflow_late": [sum(j["rf_o"] for j in attached), sum(j["rf_u"] for j in attached),
                                       sum(j["rf_l"] for j in attached)],
    })
    for label, subset in (("los", los), ("shadow", shadow), ("all", attached)):
        report[label] = {
            "rows": len(subset),
            "dl_gain_db": summarize([j["dl_gain_db"] for j in subset]),
            "dl_snr": summarize([j["dl_snr"] for j in subset]),
            "dl_mcs": summarize([j["dl_mcs"] for j in subset]),
            "dl_bler": summarize([j["dl_bler"] for j in subset]),
            "ul_mcs": summarize([j["ul_mcs"] for j in subset]),
            "ul_bler": summarize([j["ul_bler"] for j in subset]),
            "rsrp": summarize([j["rsrp"] for j in subset]),
        }
    report["timeline"] = [
        {"t_s": round((j["t_ms"] - attached[0]["t_ms"]) / 1000.0, 1),
         "xy": [round(v, 2) for v in (j["position"] or [0, 0])[:2]],
         "gain_db": round(j["dl_gain_db"], 1), "dl_snr": j["dl_snr"], "dl_mcs": j["dl_mcs"],
         "dl_bler": j["dl_bler"], "ul_bler": j["ul_bler"]}
        for j in attached[::5]
    ]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--log-dir", type=pathlib.Path, required=True)
    parser.add_argument("--gnb", default="gnb0")
    parser.add_argument("--max-gap-ms", type=int, default=1500)
    parser.add_argument("--los-within-db", type=float, default=6.0)
    parser.add_argument("--shadow-below-db", type=float, default=15.0)
    parser.add_argument("--report", type=pathlib.Path)
    args = parser.parse_args()

    status = args.log_dir / "sionna-status.jsonl"
    if not status.exists():
        print(f"error: no sionna-status.jsonl in {args.log_dir}", file=sys.stderr)
        return 2
    updates = load_bridge(status)
    keys = [u["t_ms"] for u in updates]
    report = {"log_dir": str(args.log_dir), "bridge_updates": len(updates),
              "position_source": updates[-1]["position_source"] if updates else None, "ues": {}}
    for csv_path in sorted(args.log_dir.glob("srsue-metrics-*.csv")):
        ue = csv_path.stem[len("srsue-metrics-"):]
        start_file = args.log_dir / f"srsue-{ue}.start_unix_ms"
        if not start_file.exists():
            report["ues"][ue] = {"error": "no start time"}
            continue
        rows = load_metrics(csv_path, int(start_file.read_text().strip()))
        report["ues"][ue] = analyse_ue(ue, args.gnb, rows, updates, keys, args.max_gap_ms,
                                       args.los_within_db, args.shadow_below_db)
    for ue, entry in report["ues"].items():
        print(f"== {ue}: rows={entry.get('metrics_rows')} joined={entry.get('joined_rows')} "
              f"attached={entry.get('attached_rows')} gain {entry.get('worst_dl_gain_db')}..{entry.get('best_dl_gain_db')} dB "
              f"r(gain,snr)={entry.get('gain_snr_pearson')} r(gain,mcs)={entry.get('gain_mcs_pearson')} "
              f"rf_o/u/l={entry.get('rf_overflow_underflow_late')}")
        for label in ("los", "shadow"):
            block = entry.get(label)
            if block:
                print(f"   {label:6s} rows={block['rows']:4d} gain={block['dl_gain_db']} snr={block['dl_snr']} "
                      f"mcs={block['dl_mcs']} dl_bler={block['dl_bler']} ul_bler={block['ul_bler']}")
        for point in entry.get("timeline", [])[:200]:
            print(f"   t={point['t_s']:6.1f}s xy={point['xy']} gain={point['gain_db']:6.1f} snr={point['dl_snr']:5.1f} "
                  f"mcs={point['dl_mcs']:4.1f} dl_bler={point['dl_bler']:.3f} ul_bler={point['ul_bler']:.3f}")
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
