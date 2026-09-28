"""Summarize one OAI 2x2 run: rank, HARQ-ACK, PUSCH CRC, CSI, throughput.

Reads the gNB internal log (scheduler DL decisions carry `ri=`, PHY PUCCH
lines carry `ack=` bits and `csi1=` payloads, PHY PUSCH lines carry `crc=`)
and the UE-side iperf3 JSON, and writes rank-summary.json next to the run's
other reports.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

STAMP_RE = re.compile(r"^(\S+) \[SCHED\s*\] \[I\] \[\s*(\d+)\.(\d+)\] Slot decisions")
DL_RE = re.compile(r"DL: ue=\d+ c-rnti=\S+ h_id=\d+ .*?cw\[0\]: newtx=(true|false) rv=\d+ tbs=(\d+) ri=(\d+)")
MCS_RE = re.compile(r"mcs=(\d+)")
ACK_RE = re.compile(r"PUCCH: rnti=\S+ format=(\d).*? ack=([01]+)")
CSI_RE = re.compile(r"PUCCH: rnti=\S+ format=2 .*?csi1=([01]+)")
PUSCH_RE = re.compile(r"PUSCH: rnti=0x(?!39)\S+ .*?crc=(OK|KO)")
UL_RE = re.compile(r"UL: ue=\d+ rnti=0x4\S+ h_id=\d+ ss_id=\d+ rb=\[(\d+)\.\.(\d+)\) newtx=(true|false) rv=\d+ tbs=(\d+)")
SRS_RE = re.compile(r"- SRS: ue=\d+ rnti=\S+(?: tpmi_info=\[(.*?)\])?$")
PUSCH_MOD_RE = re.compile(r"PHY .*PUSCH: rnti=0x4\S+ .*?mod=(\S+) .*?tbs=(\d+) crc=(OK|KO)")
UL_RI_RE = re.compile(r" ul_ri=([0-9.]+)")
PDSCH_PHY_RE = re.compile(r"PHY .*PDSCH: rnti=0x4\S+ .*?mod=(\S+) .*?tbs=(\d+)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()

    gnb_log = args.log_dir / "gnb-internal.log"
    dl = collections.Counter()
    dl_tbs = collections.Counter()
    acks = collections.Counter()
    csi = collections.Counter()
    pusch = collections.Counter()
    mods = collections.Counter()
    ul = collections.Counter()
    ul_tbs_per_prb = []
    srs = collections.Counter()
    srs_samples = []
    pusch_mods = collections.Counter()
    ul_ri = []
    # Lock-step ZMQ time is simulated: the slot counter only advances as fast
    # as the slowest process. Track simulated slots against wall time so the
    # wall-clock iperf rate can be put on the air-interface time base.
    stamps = []
    if gnb_log.is_file():
        from datetime import datetime
        for line in gnb_log.open(errors="replace"):
            if (st := STAMP_RE.search(line)) is not None:
                wall = datetime.fromisoformat(st.group(1) + "+00:00").timestamp()
                stamps.append((wall, int(st.group(2)), int(st.group(3))))
            if (m := DL_RE.search(line)) is not None:
                key = f"ri{m.group(3)}_{'new' if m.group(1) == 'true' else 'retx'}"
                dl[key] += 1
                dl_tbs[f"ri{m.group(3)}"] += int(m.group(2))
            elif (m := ACK_RE.search(line)) is not None:
                for bit in m.group(2):
                    acks["ack" if bit == "1" else "nack"] += 1
            if (m := CSI_RE.search(line)) is not None:
                csi[m.group(1)] += 1
            if (m := PUSCH_RE.search(line)) is not None:
                pusch[m.group(1)] += 1
            if (m := PDSCH_PHY_RE.search(line)) is not None:
                mods[m.group(1)] += 1
            if (m := UL_RE.search(line)) is not None:
                ul["newtx" if m.group(3) == "true" else "retx"] += 1
                nprb = int(m.group(2)) - int(m.group(1))
                if m.group(3) == "true" and nprb > 0 and int(m.group(4)) > 1000:
                    ul_tbs_per_prb.append(int(m.group(4)) / nprb)
            if (m := SRS_RE.search(line.rstrip())) is not None:
                srs["with_tpmi" if m.group(1) else "no_tpmi"] += 1
                if m.group(1) and len(srs_samples) < 3:
                    srs_samples.append(m.group(1))
            if (m := UL_RI_RE.search(line)) is not None:
                ul_ri.append(float(m.group(1)))
            if (m := PUSCH_MOD_RE.search(line)) is not None:
                pusch_mods[f"{m.group(1)}_{m.group(3)}"] += 1

    iperf = {}
    iperf_path = args.log_dir / "iperf3-dl.json"
    if iperf_path.is_file() and iperf_path.stat().st_size:
        try:
            data = json.loads(iperf_path.read_text())
            end = data.get("end", {}).get("sum", {})
            iperf = {
                "offered_bits_per_second": end.get("bits_per_second"),
                # UDP -R: `sum` mixes the sender's rate with the receiver's
                # loss; `sum_received` is what actually reached the UE.
                "received_mbps": round(data["end"]["sum_received"]["bits_per_second"] / 1e6, 2)
                if (data.get("end", {}).get("sum_received") or {}).get("bits_per_second") is not None
                else None,
                "lost_percent": end.get("lost_percent"),
                "packets": end.get("packets"),
                "intervals_mbps": [
                    round(i["sum"]["bits_per_second"] / 1e6, 2) for i in data.get("intervals", [])
                ],
            }
        except (ValueError, KeyError, TypeError) as error:
            iperf = {"error": str(error)}

    iperf_ul = {}
    ul_path = args.log_dir / "iperf3-ul.json"
    if ul_path.is_file() and ul_path.stat().st_size:
        try:
            data = json.loads(ul_path.read_text())
            end = data.get("end", {})
            rx = end.get("sum_received") or end.get("sum") or {}
            iperf_ul = {
                "received_mbps": round(rx["bits_per_second"] / 1e6, 2) if rx.get("bits_per_second") else None,
                "lost_percent": (end.get("sum") or {}).get("lost_percent"),
            }
        except (ValueError, KeyError, TypeError) as error:
            iperf_ul = {"error": str(error)}

    window = None
    if iperf_path.is_file() and iperf.get("received_mbps"):
        data = json.loads(iperf_path.read_text())
        start = data["start"]["timestamp"]["timesecs"]
        window = (start, start + data["end"]["sum_received"]["seconds"])
    elif ul_path.is_file() and iperf_ul.get("received_mbps"):
        data = json.loads(ul_path.read_text())
        start = data["start"]["timestamp"]["timesecs"]
        window = (start, start + (data["end"].get("sum") or {}).get("seconds", 0))
    realtime_factor = None
    # Air time in ms from [SFN.slot]: a 30 kHz cell (100 MHz n78) has 20 slots
    # per 10 ms frame, a 15 kHz one 10; any slot index >= 10 marks the former.
    slots_per_frame = 20 if any(st[2] >= 10 for st in stamps) else 10
    selected = [(st[0], st[1] * 10 + st[2] * 10.0 / slots_per_frame) for st in stamps
                if window is None or window[0] <= st[0] <= window[1]]
    if len(selected) > 1 and selected[-1][0] > selected[0][0]:
        sim_ms = sum((b[1] - a[1]) % 10240 for a, b in zip(selected, selected[1:]))
        realtime_factor = round((sim_ms / 1000.0) / (selected[-1][0] - selected[0][0]), 4)
    total_ack = acks["ack"] + acks["nack"]
    summary = {
        "dl_decisions": dict(dl),
        "dl_tbs_bytes_by_rank": dict(dl_tbs),
        "harq_ack": dict(acks),
        "nack_ratio": round(acks["nack"] / total_ack, 4) if total_ack else None,
        "csi1_payloads": dict(csi.most_common(6)),
        "pusch_crc": dict(pusch),
        "pdsch_modulations": dict(mods),
        "ul_decisions": dict(ul),
        "ul_newtx_tbs_bytes_per_prb_p50": sorted(ul_tbs_per_prb)[len(ul_tbs_per_prb) // 2] if ul_tbs_per_prb else None,
        "ul_newtx_tbs_bytes_per_prb_max": max(ul_tbs_per_prb) if ul_tbs_per_prb else None,
        "srs_indications": dict(srs),
        "ul_ri_reports": ul_ri,
        "srs_tpmi_samples": srs_samples,
        "pusch_modulation_crc": dict(pusch_mods),
        "iperf_ul": iperf_ul,
        "iperf_dl": iperf,
        "realtime_factor": realtime_factor,
        "dl_rx_mbps_air_time": round(iperf["received_mbps"] / realtime_factor, 2)
        if iperf.get("received_mbps") and realtime_factor else None,
        "tbs_bytes_per_newtx_by_rank": {
            k: round(v / max(1, dl.get(f"{k}_new", 0) + dl.get(f"{k}_retx", 0)), 1) for k, v in dl_tbs.items()
        },
    }
    out = args.report_dir / "rank-summary.json"
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        "event=oai_2x2_summary "
        f"dl={dict(dl)} nack_ratio={summary['nack_ratio']} pusch={dict(pusch)} "
        f"csi1={dict(csi.most_common(3))} "
        f"dl_rx_mbps={iperf.get('received_mbps')} rt_factor={realtime_factor} "
        f"dl_rx_mbps_air={summary['dl_rx_mbps_air_time']} "
        f"ul_rx_mbps_air={round(iperf_ul['received_mbps'] / realtime_factor, 2) if iperf_ul.get('received_mbps') and realtime_factor else None} "
        f"lost={iperf.get('lost_percent')} ul_rx_mbps={iperf_ul.get('received_mbps')} "
        f"ul_tbs_per_prb_p50={summary['ul_newtx_tbs_bytes_per_prb_p50']} srs={dict(srs)} ul_ri={sorted(set(ul_ri))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
