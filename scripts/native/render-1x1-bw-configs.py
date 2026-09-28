#!/usr/bin/env python3
"""Render the 1x1 fixtures at a wider cell bandwidth (Spark S8).

Runs an audited 1x1 renderer unchanged -- the srsUE legacy one by default, or
the OAI nrUE one with OCUDU_NATIVE_BW_BASE=oai -- then rewrites only the
values that follow from the channel bandwidth: the gNB
`channel_bandwidth_MHz`, `srate` and ZMQ `base_srate`, the srsUE
`srate`/`base_srate`/`nof_prb`/`ssb_nr_arfcn` (legacy base only), and the
broker's per-device sample rate and 1 ms batch. Everything else (band n3 FDD,
dl_arfcn, SCS 15 kHz, channel chain, core, subscriber) stays the audited one,
so the bandwidth is the only variable. srsUE NR is 15 kHz SCS only
(`rrc_nr_procedures.cc` rejects any other MIB SCS), so the steps stay at
15 kHz: 20 / 30 / 40 / 50 MHz. The OAI nrUE takes its PRB count and SSB
offset (and whether to use 3/4 sampling) on the command line; the gate reads
them from OCUDU_NATIVE_OAI_UE_PRB, OCUDU_NATIVE_OAI_UE_SSB and
OCUDU_NATIVE_OAI_UE_SAMPLING, and `oai_ue_args <MHz>` below prints them.

100 MHz needs 30 kHz SCS, so OCUDU_NATIVE_BW_MHZ=100 turns the cell into a TDD
n78 one (OAI base only): `oai_tdd100_args <SSB ARFCN>` prints the nrUE radio
arguments for it. `oai_uecap <src> <dst> <MHz>` writes the UE capability file
the 50 MHz cell needs (see `oai_uecap_with_bw`).

Select with OCUDU_NATIVE_BW_MHZ (default 20, which leaves the configs
byte-identical to the base renderer). OCUDU_NATIVE_CUDA_HOST_MEMORY
(copy | zero_copy | auto), when set, is written as the broker's
`runtime.cuda_host_memory`, so one build serves both modes.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

# bandwidth MHz -> (PRB at 15 kHz, sample rate in MS/s as written in configs,
# SSB ARFCN the gNB derives for dl_arfcn 368500 and prints at start-up).
# srsUE does not search for the SSB; it tunes to rat.nr.ssb_nr_arfcn, whose
# default 368410 is the 20 MHz value.
BANDWIDTHS = {
    20: (106, "23.04", 368410),
    30: (160, "30.72", 367450),
    40: (216, "46.08", 366490),
    50: (270, "61.44", 365530),
}
# 100 MHz needs 30 kHz SCS, so it is a TDD n78 cell (OAI base only; srsUE is
# 15 kHz only). dl_arfcn 637212 is the one OCUDU's own 100 MHz n78 example
# (configs/gnb_ru_ran550_tdd_n78_100mhz_4x2.yml) uses, and PRACH index 159
# is that example's TDD PRACH. The SSB ARFCN is the gNB-printed value.
# 634464 is the SSB ARFCN the gNB derives for that cell and prints at start-up
# (S8/S10 runs); the renderer uses it for the nrUE --ssb offset.
TDD_100 = {"prb": 273, "srate": "122.88", "dl_arfcn": 637212, "ssb_arfcn": 634464}
BASES = {
    "legacy": "render-legacy-1x1-configs.py",
    "oai": "render-oai-1x1-configs.py",
}
HOST_MEMORY = ("copy", "zero_copy", "auto")
DL_CENTER_HZ = 1842.5e6


def oai_ssb_offset(bw: int) -> int:
    """OAI `--ssb`: first SSB subcarrier counted from point A (15 kHz)."""
    prb, _, ssb_arfcn = BANDWIDTHS[bw]
    point_a_hz = DL_CENTER_HZ - prb * 12 * 15e3 / 2
    ssb_start_hz = ssb_arfcn * 5e3 - 120 * 15e3
    return round((ssb_start_hz - point_a_hz) / 15e3)


def nr_arfcn_hz(arfcn: int) -> float:
    return arfcn * 5e3 if arfcn < 600000 else 3000e6 + (arfcn - 600000) * 15e3


def oai_tdd100_args(ssb_arfcn: int) -> str:
    """nrUE radio arguments for the 100 MHz n78 cell (30 kHz, no -E, no UL offset)."""
    center_hz = nr_arfcn_hz(TDD_100["dl_arfcn"])
    point_a_hz = center_hz - TDD_100["prb"] * 12 * 30e3 / 2
    ssb_start_hz = nr_arfcn_hz(ssb_arfcn) - 120 * 30e3
    ssb = round((ssb_start_hz - point_a_hz) / 30e3)
    return f"-r {TDD_100['prb']} --numerology 1 --band 78 -C {int(center_hz)} --ssb {ssb}"


def oai_sampling_flag(bw: int) -> str:
    """`-E` (3/4 sampling) when that is the rate the gNB uses, else `-`.

    The nrUE derives its rate from the PRB count: the smallest FFT that fits,
    times 3/4 with `-E`. 106 PRB -E -> 1536 (23.04 MS/s) and 216 PRB -E -> 3072
    (46.08) match the gNB; 160 and 270 PRB with -E land on 3072 / 6144
    (46.08 / 92.16, measured) against the gNB's 30.72 / 61.44, so those two
    run without it (2048 / 4096).
    """
    prb, srate, _ = BANDWIDTHS[bw]
    three_quarter_fft = {106: 1536, 160: 3072, 216: 3072, 270: 6144}[prb]
    return "-E" if abs(three_quarter_fft * 15e3 - float(srate) * 1e6) < 1 else "-"


def oai_uecap_with_bw(src: Path, dst: Path, bw: int) -> None:
    """Copy an OAI UE capability file, adding a 15 kHz DL per-CC feature set for `bw`.

    The nrUE takes its PDSCH max MIMO layers from the per-CC feature set whose
    SCS and bandwidth equal the cell's exactly (`supported_bw_comparison`); with
    none it asserts `max_mimo_layers > 0` at the first DCI 1_1. OAI's
    uecap_ports1.xml has 15 kHz entries for 15/20/30/40 MHz only, so the 50 MHz
    cell needs one. It is a copy of the 15 kHz 40 MHz entry with the bandwidth
    changed.
    """
    text = src.read_text(encoding="utf-8")
    blocks = re.findall(r"            <FeatureSetDownlinkPerCC>.*?</FeatureSetDownlinkPerCC>\n", text, re.S)
    if any("<kHz15/>" in b and f"<mhz{bw}/>" in b for b in blocks):
        raise ValueError(f"capability already has a 15 kHz {bw} MHz DL feature set")
    b40 = [b for b in blocks if "<kHz15/>" in b and "<mhz40/>" in b]
    if len(b40) != 1:
        raise ValueError("expected exactly one 15 kHz 40 MHz DL feature set")
    text = text.replace(b40[0], b40[0] + b40[0].replace("<mhz40/>", f"<mhz{bw}/>"), 1)
    dst.write_text(text, encoding="utf-8")


def load_base(name: str, repo_root: Path):
    for candidate in (
        Path(__file__).resolve().parent / name,
        repo_root / "scripts/native" / name,
    ):
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("base_renderer", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise ValueError(f"base renderer not found: {name}")


def replace_exact(text: str, old: str, new: str, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise ValueError(f"{label}: expected {count} source token(s), found {actual}")
    return text.replace(old, new)


def rewrite(path: Path, pairs) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new, count, label in pairs:
        text = replace_exact(text, old, new, count, label)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    argv = sys.argv[1:]
    if argv[:1] == ["oai_uecap"]:
        oai_uecap_with_bw(Path(argv[1]), Path(argv[2]), int(argv[3]))
        return 0
    if argv[:1] == ["oai_tdd100_args"]:
        print(oai_tdd100_args(int(argv[1])))
        return 0
    if argv[:1] == ["oai_ue_args"]:
        bw = int(argv[1])
        print(BANDWIDTHS[bw][0], oai_ssb_offset(bw), oai_sampling_flag(bw))
        return 0
    bw = int(os.environ.get("OCUDU_NATIVE_BW_MHZ", "20"))
    base = os.environ.get("OCUDU_NATIVE_BW_BASE", "legacy")
    host_memory = os.environ.get("OCUDU_NATIVE_CUDA_HOST_MEMORY", "")
    if bw not in BANDWIDTHS and bw != 100:
        raise ValueError(f"OCUDU_NATIVE_BW_MHZ must be one of {sorted(BANDWIDTHS) + [100]}")
    if bw == 100 and base != "oai":
        raise ValueError("100 MHz is a 30 kHz TDD cell; srsUE is 15 kHz only, use OCUDU_NATIVE_BW_BASE=oai")
    if base not in BASES:
        raise ValueError(f"OCUDU_NATIVE_BW_BASE must be one of {sorted(BASES)}")
    if host_memory and host_memory not in HOST_MEMORY:
        raise ValueError(f"OCUDU_NATIVE_CUDA_HOST_MEMORY must be one of {HOST_MEMORY}")

    repo_root = Path(argv[argv.index("--repo-root") + 1]) if "--repo-root" in argv else Path(".")
    renderer = load_base(BASES[base], repo_root)
    sys.argv = [sys.argv[0]] + argv
    rc = renderer.main()
    if rc != 0 or "--self-test" in argv:
        return rc
    out = Path(argv[argv.index("--output-dir") + 1])

    if bw == 100:
        prb, srate, ssb_arfcn = TDD_100["prb"], TDD_100["srate"], None
    else:
        prb, srate, ssb_arfcn = BANDWIDTHS[bw]
    samples = int(round(float(srate) * 1000))
    # The broker queue must exceed OCUDU's fixed ZMQ stream buffer (614400
    # samples) at any rate; the audited 2457600 already does.
    if bw != 20:
        rewrite(out / "gnb.yaml", [
            ("base_srate=23.04e6", f"base_srate={srate}e6", 1, "gNB base_srate"),
            ("  srate: 23.04\n", f"  srate: {srate}\n", 1, "gNB srate"),
            ("  channel_bandwidth_MHz: 20\n", f"  channel_bandwidth_MHz: {bw}\n", 1, "gNB bandwidth"),
        ])
        if bw == 100:
            rewrite(out / "gnb.yaml", [
                ("  dl_arfcn: 368500\n", f"  dl_arfcn: {TDD_100['dl_arfcn']}\n", 1, "gNB n78 ARFCN"),
                ("  band: 3\n", "  band: 78\n", 1, "gNB band"),
                ("  common_scs: 15\n", "  common_scs: 30\n", 1, "gNB SCS"),
                # CORESET#0 12 / SS#0 0 are 15 kHz FDD table entries; let the
                # gNB pick them for the 30 kHz cell.
                ("  pdcch:\n    common:\n      ss0_index: 0\n      coreset0_index: 12\n", "", 1,
                 "gNB 15 kHz CORESET#0 removal"),
                ("    prach_config_index: 1\n", "    prach_config_index: 159\n", 1, "gNB TDD PRACH"),
            ])
        if base == "legacy":
            rewrite(out / "srsue.conf", [
                ("srate = 23.04e6\n", f"srate = {srate}e6\n", 1, "srsUE srate"),
                ("base_srate=23.04e6", f"base_srate={srate}e6", 1, "srsUE base_srate"),
                ("max_nof_prb = 106\n", f"max_nof_prb = {prb}\n", 1, "srsUE max_nof_prb"),
                ("\nnof_prb = 106\n", f"\nnof_prb = {prb}\nssb_nr_arfcn = {ssb_arfcn}\n", 1, "srsUE nof_prb"),
            ])
        rewrite(out / "topology.yaml", [
            ("  batch_samples: 23040\n", f"  batch_samples: {samples}\n", 1, "broker batch"),
            ("    sample_rate_hz: 23040000\n", f"    sample_rate_hz: {samples * 1000}\n", 2, "broker sample rate"),
        ])
    if host_memory:
        topology = out / "topology.yaml"
        text = topology.read_text(encoding="utf-8")
        if text.count("\n  gpu_device: 0\n") != 1 or "cuda_host_memory" in text:
            raise ValueError("broker host memory: runtime anchor missing or knob already set")
        text = text.replace("\n  gpu_device: 0\n", f"\n  gpu_device: 0\n  cuda_host_memory: {host_memory}\n")
        topology.write_text(text, encoding="utf-8")
    if base == "oai" and bw != 20:
        # S11: the gate reads the nrUE radio arguments and, where the stock
        # capability lacks the cell's bandwidth, the capability file from the
        # rendered configs, so a run needs no per-bandwidth environment.
        if bw == 100:
            radio = oai_tdd100_args(TDD_100["ssb_arfcn"])
        else:
            sampling = oai_sampling_flag(bw)
            radio = (("-E " if sampling == "-E" else "") +
                     f"-r {prb} --numerology 0 --band 3 -C {int(DL_CENTER_HZ)} "
                     f"--ssb {oai_ssb_offset(bw)} --CO -95000000")
        (out / "nrue-radio.args").write_text(radio + "\n", encoding="utf-8")
        if bw in BANDWIDTHS:
            native_root = Path(argv[argv.index("--native-root") + 1])
            stock = native_root / "src/oai/targets/PROJECTS/GENERIC-NR-5GC/CONF/uecap_ports1.xml"
            per_cc = re.findall(r"<FeatureSetDownlinkPerCC>.*?</FeatureSetDownlinkPerCC>",
                                stock.read_text(encoding="utf-8"), re.S)
            if not any("<kHz15/>" in b and f"<mhz{bw}/>" in b for b in per_cc):
                oai_uecap_with_bw(stock, out / "uecap.xml", bw)
    print(f"event=native_bw_configs_rendered base={base} bw_mhz={bw} prb={prb} srate_msps={srate} "
          f"cuda_host_memory={host_memory or 'default'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError) as error:
        print(f"config rendering failed: {error}", file=sys.stderr)
        raise SystemExit(2)
