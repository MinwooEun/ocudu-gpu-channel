"""Render configs for the native OAI nrUE 2x2 SU-MIMO gate (M6.3).

Starts from the OAI 1x1 render (same immutable legacy gNB fixture, the same
OAI adaptation, the same Open5GS / subscriber / UE fixture) and changes only
what 2x2 needs:

  gNB   2 DL / 2 UL antennas, two ZMQ port pairs, `pdsch.max_rank`, MAC pcap
        off (OCUDU rejects MAC pcap with more than one DL antenna), and an
        optional `pdsch.max_ue_mcs` cap. CSI-RS stays at the OCUDU default
        (enabled): the OAI nrUE measures 2-port CSI-RS and reports RI/PMI,
        which is how the gNB learns that rank 2 is possible at all.
  UL    `--ul-max-rank 2`: 2-layer codebook PUSCH. The gNB gets
        `pusch.max_rank: 2` and periodic SRS (OCUDU picks the UL rank and TPMI
        from the SRS channel matrix), and the UE gets a capability file derived
        from OAI's own uecap_ports2.xml that (a) lists band 3 -- the stock file
        only lists band 78, so OCUDU fell back to its 1-layer / 1-SRS-port
        defaults for this band-3 cell -- and (b) advertises twoLayers on every
        codebook PUSCH per-CC entry, because the OAI UE MAC takes its PUSCH
        layer capability from the last per-CC entry matching the cell SCS and
        bandwidth, and all 15 kHz entries said oneLayer.
  path  `broker`: the gNB talks to the CUDA broker on loopback and the UE on
        the veth pair, through the 2x2 topology fixture.
        `direct`: no broker; the gNB binds its TX on the veth host side and
        connects its RX to the UE, so the two stacks see an identity channel.
        This is the control that removes the emulator as a variable.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def load_module(name: str, filename: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load renderer module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


oai = load_module("render_oai_1x1_configs", "render-oai-1x1-configs.py")
bw_configs = load_module("render_1x1_bw_configs", "render-1x1-bw-configs.py")
legacy = oai.legacy

VETH_HOST_IP = oai.VETH_HOST_IP
VETH_UE_IP = oai.VETH_UE_IP

LEGACY_DEVICE_ARGS = (
    "  device_args: tx_port=tcp://127.0.0.1:2000,rx_port=tcp://127.0.0.1:2001,base_srate=23.04e6\n"
)
BROKER_DEVICE_ARGS = (
    "  device_args: tx_port0=tcp://127.0.0.1:2000,tx_port1=tcp://127.0.0.1:2002,"
    "rx_port0=tcp://127.0.0.1:2001,rx_port1=tcp://127.0.0.1:2003,base_srate=23.04e6\n"
)
DIRECT_DEVICE_ARGS = (
    f"  device_args: tx_port0=tcp://{VETH_HOST_IP}:2100,tx_port1=tcp://{VETH_HOST_IP}:2102,"
    f"rx_port0=tcp://{VETH_UE_IP}:2101,rx_port1=tcp://{VETH_UE_IP}:2103,base_srate=23.04e6\n"
)


def render_gnb_2x2(
    source: str,
    log_dir: Path,
    path: str,
    max_rank: int,
    max_ue_mcs: int | None,
    csi_rs: bool,
    tx_backoff_db: float | None,
    ul_max_rank: int | None = None,
    srs_period_ms: float = 10.0,
) -> str:
    rendered = oai.render_gnb_oai(source, log_dir)
    rendered = legacy.replace_exact(
        rendered,
        LEGACY_DEVICE_ARGS,
        BROKER_DEVICE_ARGS if path == "broker" else DIRECT_DEVICE_ARGS,
        1,
        "gNB 2-port ZMQ endpoints",
    )
    if tx_backoff_db is not None:
        # The OAI nrUE's 2-layer equaliser is fixed point and its output
        # scale grows with the received amplitude (see M6.3 in
        # MIMO_MILESTONES.md); at OCUDU's default 12 dB back-off it overflows
        # int16. The back-off lowers the digital TX level of every DL channel.
        rendered = legacy.replace_exact(
            rendered,
            "  tx_gain: 0\n  rx_gain: 0\n\ncell_cfg:\n",
            f"  tx_gain: 0\n  rx_gain: 0\n  amplitude_control:\n    tx_gain_backoff: {tx_backoff_db}\n\ncell_cfg:\n",
            1,
            "gNB TX back-off",
        )
    rendered = legacy.replace_exact(
        rendered,
        "cell_cfg:\n  dl_arfcn: 368500\n",
        "cell_cfg:\n  nof_antennas_dl: 2\n  nof_antennas_ul: 2\n  dl_arfcn: 368500\n",
        1,
        "gNB 2T2R antenna count",
    )
    block = f"  pdsch:\n    mcs_table: qam64\n    max_rank: {max_rank}\n"
    if max_ue_mcs is not None:
        block += f"    max_ue_mcs: {max_ue_mcs}\n"
    if not csi_rs:
        block += "  csi:\n    csi_rs_enabled: false\n  pucch:\n    nof_cell_csi_res: 0\n"
    rendered = legacy.replace_exact(
        rendered,
        "  pdsch:\n    mcs_table: qam64\n  pusch:\n",
        block + "  pusch:\n",
        1,
        "gNB PDSCH rank / CSI-RS",
    )
    if ul_max_rank is not None:
        # OCUDU selects the PUSCH rank and TPMI from the SRS channel matrix
        # (ue_channel_state_manager::get_nof_ul_layers); without SRS it stays
        # at rank 1 whatever max_rank says.
        rendered = legacy.replace_exact(
            rendered,
            "  pusch:\n    mcs_table: qam64\n\n",
            f"  pusch:\n    mcs_table: qam64\n    max_rank: {ul_max_rank}\n"
            f"  srs:\n    type_enabled: periodic\n    period_ms: {srs_period_ms:g}\n\n",
            1,
            "gNB PUSCH rank / SRS",
        )
        # Per-UE scheduler metrics in the gNB log carry ul_ri (the mean UL rank
        # the scheduler derived from SRS); the PHY PUSCH line prints the layer
        # count only at debug level.
        rendered = rendered.rstrip("\n") + (
            "\n\nmetrics:\n  enable_log: true\n  layers:\n    enable_sched: true\n"
            "  periodicity:\n    du_report_period: 1000\n"
        )
    rendered = legacy.replace_exact(
        rendered, "  mac_enable: enable\n", "  mac_enable: disable\n", 1, "gNB MAC pcap off (>1 DL antenna)"
    )
    return rendered


def render_uecap_ul2(source: str, band: int = 3) -> str:
    """Copy of OAI's uecap_ports2.xml for `band` with 2-layer codebook PUSCH everywhere.

    The FDD cells are band 3; the 100 MHz TDD cell (S12) is n78, the stock band.
    """
    if source.count("<bandNR>78</bandNR>") != 3:
        legacy.fail("uecap_ports2.xml: expected exactly three band-78 entries")
    rendered = source.replace("<bandNR>78</bandNR>", f"<bandNR>{band}</bandNR>")
    one = "<maxNumberMIMO-LayersCB-PUSCH><oneLayer/></maxNumberMIMO-LayersCB-PUSCH>"
    if rendered.count(one) == 0:
        legacy.fail("uecap_ports2.xml: no oneLayer codebook PUSCH entries to raise")
    rendered = rendered.replace(one, "<maxNumberMIMO-LayersCB-PUSCH><twoLayers/></maxNumberMIMO-LayersCB-PUSCH>")
    if "<maxNumberSRS-Ports-PerResource><n2/></maxNumberSRS-Ports-PerResource>" not in rendered:
        legacy.fail("uecap_ports2.xml: no 2-port SRS feature set")
    return rendered


def validate_topology(source: str) -> str:
    for required in (
        "  - id: gnb0\n    tx_ports:\n      - gnb0_p0\n      - gnb0_p1\n",
        "  - id: ue0\n    tx_ports:\n      - ue0_p0\n      - ue0_p1\n",
        f"    tx_endpoint: tcp://{VETH_UE_IP}:2101\n",
        f"    tx_endpoint: tcp://{VETH_UE_IP}:2103\n",
        f"    rx_endpoint: tcp://{VETH_HOST_IP}:2100\n",
        f"    rx_endpoint: tcp://{VETH_HOST_IP}:2102\n",
        "    tx_endpoint: tcp://127.0.0.1:2000\n",
        "    tx_endpoint: tcp://127.0.0.1:2002\n",
    ):
        if source.count(required) != 1:
            legacy.fail(f"2x2 topology invariant is missing or ambiguous: {required!r}")
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--path", choices=("broker", "direct"), required=True)
    parser.add_argument("--max-rank", type=int, choices=(1, 2), required=True)
    parser.add_argument("--max-ue-mcs", type=int)
    parser.add_argument("--csi-rs", choices=("on", "off"), default="on")
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--tx-backoff-db", type=float)
    # S12: the same per-bandwidth rewrite as the OAI 1x1 gate
    # (render-1x1-bw-configs.py apply_bandwidth), applied to the 2x2 render.
    parser.add_argument("--bw-mhz", type=int, default=20)
    parser.add_argument("--cuda-host-memory", choices=bw_configs.HOST_MEMORY)
    parser.add_argument("--ul-max-rank", type=int, choices=(1, 2))
    parser.add_argument("--srs-period-ms", type=float, default=10.0)
    parser.add_argument("--gnb-phy-log", choices=("info", "debug"), default="info")
    args = parser.parse_args()
    if args.bw_mhz not in bw_configs.BANDWIDTHS and args.bw_mhz != 100:
        legacy.fail(f"--bw-mhz must be one of {sorted(bw_configs.BANDWIDTHS) + [100]}")

    repo_root = args.repo_root.resolve(strict=True)
    native_root = args.native_root.resolve(strict=True)
    output_dir = legacy.safe_output_directory(args.output_dir)
    log_dir = legacy.safe_log_directory(args.log_dir)

    gnb_source = legacy.read_regular(
        repo_root / "examples/ocudu/gnb_zmq_b210_fdd_srsue.yaml", "immutable legacy gNB fixture"
    )
    open5gs_source = legacy.read_regular(
        native_root / "src/ocudu/docker/open5gs/open5gs-5gc.yml", "pinned OCUDU Open5GS template"
    )
    nrue_source = legacy.read_regular(
        repo_root / "examples/native/oai/nrue_zmq_1x1.conf", "native OAI nrUE fixture"
    )
    subscriber_source = legacy.read_regular(
        repo_root / "examples/native/open5gs/subscriber-legacy-1x1.csv", "native subscriber template"
    )
    topology_source = legacy.read_regular(args.topology.resolve(strict=True), "2x2 topology fixture")

    rendered = {
        "gnb.yaml": render_gnb_2x2(
            gnb_source,
            log_dir,
            args.path,
            args.max_rank,
            args.max_ue_mcs,
            args.csi_rs == "on",
            args.tx_backoff_db,
            args.ul_max_rank,
            args.srs_period_ms,
        ),
        "topology.yaml": validate_topology(topology_source),
        "open5gs.yaml": legacy.render_open5gs(open5gs_source, native_root),
        "nrue.conf": oai.validate_nrue(nrue_source),
        "subscriber.csv": legacy.validate_subscriber(subscriber_source),
    }
    if args.ul_max_rank is not None:
        rendered["uecap.xml"] = render_uecap_ul2(
            legacy.read_regular(
                native_root / "src/oai/targets/PROJECTS/GENERIC-NR-5GC/CONF/uecap_ports2.xml",
                "pinned OAI 2-port UE capability",
            ),
            band=78 if args.bw_mhz == 100 else 3,
        )
    if args.gnb_phy_log == "debug":
        # Diagnosis only: PUSCH/PDSCH PDU fields such as nof_layers and ports are
        # printed at debug level.
        rendered["gnb.yaml"] = legacy.replace_exact(
            rendered["gnb.yaml"], "\nlog:\n  filename:", "\nlog:\n  phy_level: debug\n  filename:", 1, "gNB PHY debug log"
        )
    for name, text in rendered.items():
        if legacy.PLACEHOLDER_RE.search(text):
            legacy.fail(f"unresolved placeholder in {name}")
        legacy.write_new(output_dir / name, text)
    prb, srate = bw_configs.apply_bandwidth(
        output_dir, args.bw_mhz, "oai", args.cuda_host_memory or "", native_root,
        sample_rate_entries=4, uecap_name="uecap_ports2.xml",
    )
    print(f'event=native_oai_2x2_configs_rendered output_dir="{output_dir}" path={args.path} max_rank={args.max_rank} '
          f'ul_max_rank={args.ul_max_rank} bw_mhz={args.bw_mhz} prb={prb} srate_msps={srate} cuda_host_memory={args.cuda_host_memory or "default"}')
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError) as error:
        print(f"config rendering failed: {error}", file=sys.stderr)
        raise SystemExit(2)
