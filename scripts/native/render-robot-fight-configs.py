#!/usr/bin/env python3
"""Render the native robot-fight configs: two cells, two brokers, one core.

The scheduling-battle layout of ROBOT_FIGHT_MILESTONES.md R5: robot A's cell
(gnb0 <-> ue0) and robot B's cell (gnb1 <-> ue1) are served by two SEPARATE
broker processes on one GPU, each driven by its own Sionna bridge from the
same scene and the same position feed. The physical channel of both cells is
the same by construction; what differs between them is only how each broker
is scheduled, which the gate decides per broker (plain or protected).

Everything reused is reused unchanged: the gNB identities and N2/N3 addresses
of `render-multi-gnb-configs.py` (two gNBs in one namespace need distinct
PCIs, gnb_ids and GTP-U binds), the Open5GS, subscriber and srsUE rendering of
`render-multi-ue-configs.py`, and the scenario-driven topology with the
receiver noise floor of `render-sionna-multi-ue-configs.py`. This file only
splits one four-node scenario into two two-node cells.

There is deliberately no link between the cells: a broker only sees its own
topology, so inter-cell interference cannot be emulated here. Placing gnb1 on
gnb0's mast therefore costs nothing and makes the two links statistically
identical, which is what a scheduling comparison needs.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: the Sionna renderer's frozen dataclasses
    # resolve their annotations through sys.modules[__module__].
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


multi_gnb = load("render_multi_gnb_configs", HERE / "render-multi-gnb-configs.py")
sionna = load("render_sionna_multi_ue_configs", HERE / "render-sionna-multi-ue-configs.py")
legacy = multi_gnb.multi_ue
fail = legacy.fail

# Cell i = gNB i + UE i. The gNB identities are the multi-gNB gate's; the UE
# records (ports, IMSI, netns, address) are the multi-UE gate's first two.
CELLS = tuple(
    {"name": name, "gnb": dict(gnb), "ue": dict(ue), "cuda_stream_priority": "default"}
    for name, gnb, ue in zip(("a", "b"), multi_gnb.CELLS, legacy.UES[:2])
)
PRIORITIES = ("default", "high", "low")


def split_scenario(root: dict, cell: dict) -> dict:
    """The one-gNB, one-UE scenario of a cell, with everything else copied."""
    gnb_id = cell["gnb"]["device_id"]
    ue_id = cell["ue"]["device_id"]
    nodes = root.get("nodes")
    if not isinstance(nodes, dict):
        fail("scenario.nodes must be an object")
    for node_id in (gnb_id, ue_id):
        if node_id not in nodes:
            fail(f"scenario must define nodes.{node_id}")
    links = root.get("links")
    if not isinstance(links, list):
        fail("scenario.links must be an array")
    kept = [link for link in links if {link.get("from"), link.get("to")} <= {gnb_id, ue_id}]
    directions = {(link.get("from"), link.get("to")) for link in kept}
    if (gnb_id, ue_id) not in directions or (ue_id, gnb_id) not in directions:
        fail(f"scenario is missing the {gnb_id}<->{ue_id} link pair")
    out = copy.deepcopy(root)
    out["name"] = f"{root.get('name', 'robot-fight')}-cell-{cell['name']}"
    out["nodes"] = {node_id: copy.deepcopy(nodes[node_id]) for node_id in (gnb_id, ue_id)}
    out["links"] = copy.deepcopy(kept)
    return out


def check_scenario(root: dict) -> None:
    nodes = root.get("nodes")
    if not isinstance(nodes, dict):
        fail("scenario.nodes must be an object")
    expected = {cell["gnb"]["device_id"] for cell in CELLS} | {cell["ue"]["device_id"] for cell in CELLS}
    if set(nodes) != expected:
        fail(f"robot-fight scenario must name exactly {', '.join(sorted(expected))}; "
             f"it names {', '.join(sorted(nodes)) or 'none'}")
    pairs = {frozenset((cell["gnb"]["device_id"], cell["ue"]["device_id"])) for cell in CELLS}
    for index, link in enumerate(root.get("links") or []):
        if frozenset((link.get("from"), link.get("to"))) not in pairs:
            fail(f"links[{index}] {link.get('from')}->{link.get('to')} crosses cells; two brokers "
                 "cannot carry it (no inter-cell link in the robot-fight layout)")


def cell_shape(cell: dict, scenario: dict) -> sionna.LiveShape:
    gnb_id = cell["gnb"]["device_id"]
    ue_id = cell["ue"]["device_id"]

    def ports(node_id: str) -> sionna.NodePorts:
        node = scenario["nodes"][node_id]
        return sionna.NodePorts(node_id, sionna._array_count(node, "tx_array", node_id),
                                sionna._array_count(node, "rx_array", node_id))

    gnb = ports(gnb_id)
    ue = ports(ue_id)
    if (gnb.tx, gnb.rx) != (1, 1) or (ue.tx, ue.rx) != (1, 1):
        fail(f"cell {cell['name']}: the gNB fixture and srsUE are single-port; "
             f"{gnb_id} asks {gnb.tx}x{gnb.rx}, {ue_id} asks {ue.tx}x{ue.rx}")
    links = tuple(
        sionna.ShapeLink(link["from"], link["to"], link.get("model", "sionna_rt"))
        for link in scenario["links"]
    )
    return sionna.LiveShape(gnb, (ue,), links)


def render_cell_topology(cell: dict, shape: sionna.LiveShape, rx_noise: dict) -> str:
    text = sionna.render_topology(shape, rx_noise, (cell["gnb"]["tx_port"], cell["gnb"]["rx_port"]))
    priority = cell["cuda_stream_priority"]
    if priority not in PRIORITIES:
        fail(f"cell {cell['name']}: cuda_stream_priority must be one of {PRIORITIES}")
    if priority != "default":
        text = legacy.replace_exact(text, "runtime:\n", f"runtime:\n  cuda_stream_priority: {priority}\n",
                                    1, "broker stream priority")
    return text


def self_test() -> None:
    import tempfile

    # `fail` prints and exits; the refusal cases below want the message.
    global fail

    def raising(message: str) -> None:
        raise ValueError(message)

    fail = raising
    one = {"rows": 1, "cols": 1}
    good = {
        "name": "t",
        "solver": {"max_depth": 2},
        "nodes": {"gnb0": {"array": one}, "gnb1": {"array": one},
                  "ue0": {"array": one}, "ue1": {"array": one}},
        "links": [
            {"from": "gnb0", "to": "ue0", "model": "sionna_rt"},
            {"from": "ue0", "to": "gnb0", "model": "sionna_rt"},
            {"from": "gnb1", "to": "ue1", "model": "sionna_rt"},
            {"from": "ue1", "to": "gnb1", "model": "sionna_rt"},
        ],
    }
    check_scenario(good)
    a = split_scenario(good, CELLS[0])
    b = split_scenario(good, CELLS[1])
    assert set(a["nodes"]) == {"gnb0", "ue0"} and len(a["links"]) == 2, a
    assert set(b["nodes"]) == {"gnb1", "ue1"} and len(b["links"]) == 2, b
    assert a["solver"] == {"max_depth": 2}, "solver block is copied into each cell"
    shape_a = cell_shape(CELLS[0], a)
    shape_b = cell_shape(CELLS[1], b)
    floors_a = sionna.rx_noise_powers(shape_a, 40.0)
    floors_b = sionna.rx_noise_powers(shape_b, 40.0)
    topo_a = render_cell_topology(CELLS[0], shape_a, floors_a)
    cell_b = dict(CELLS[1], cuda_stream_priority="high")
    topo_b = render_cell_topology(cell_b, shape_b, floors_b)
    for token in ("tx_endpoint: tcp://127.0.0.1:2000\n", "rx_endpoint: tcp://127.0.0.1:2001\n",
                  "tx_endpoint: tcp://127.0.0.1:2101\n", "rx_model: rx_noise_ue0\n"):
        assert token in topo_a, token
    for token in ("tx_endpoint: tcp://127.0.0.1:2010\n", "rx_endpoint: tcp://127.0.0.1:2011\n",
                  "tx_endpoint: tcp://127.0.0.1:2103\n", "rx_endpoint: tcp://127.0.0.1:2102\n",
                  "  cuda_stream_priority: high\n", "rx_model: rx_noise_gnb1\n"):
        assert token in topo_b, token
    assert "cuda_stream_priority" not in topo_a, "default priority leaves the topology unchanged"
    assert "gnb0" not in topo_b and "ue0" not in topo_b, "cell b carries nothing of cell a"
    assert topo_a.count("  - from: ") == 2 and topo_b.count("  - from: ") == 2
    for bad, expected in (
        ({**good, "nodes": {k: v for k, v in good["nodes"].items() if k != "gnb1"}}, "must name exactly"),
        ({**good, "links": good["links"] + [{"from": "gnb0", "to": "ue1"}]}, "crosses cells"),
        ({**good, "links": good["links"][:3]}, "missing the gnb1<->ue1"),
    ):
        try:
            check_scenario(bad)
            for cell in CELLS:
                split_scenario(bad, cell)
        except ValueError as error:
            assert expected in str(error), (expected, str(error))
        else:
            raise AssertionError(f"should have been refused: {expected}")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "s.json"
        path.write_text(json.dumps(good), encoding="utf-8")
        assert json.loads(path.read_text())["name"] == "t"
    fail = legacy.fail
    print("event=native_robot_fight_config_renderer_self_test result=pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--native-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--scenario-config", type=Path)
    parser.add_argument("--awgn-snr-db", type=float, default=None)
    parser.add_argument("--tx-power-dl", type=float, default=sionna.TX_POWER_DL)
    parser.add_argument("--tx-power-ul", type=float, default=sionna.TX_POWER_UL)
    parser.add_argument("--stream-priority-a", choices=PRIORITIES, default="default")
    parser.add_argument("--stream-priority-b", choices=PRIORITIES, default="default")
    parser.add_argument("--gnb-acceleration", default=None,
                        help="OCUDU CUDA acceleration stage appended to both gNB configs")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    render_args = (args.repo_root, args.native_root, args.output_dir, args.log_dir, args.scenario_config)
    if args.self_test:
        if any(render_args):
            parser.error("--self-test cannot be combined with render arguments")
        self_test()
        return 0
    if not all(render_args):
        parser.error("render mode requires repo/native/output/log/scenario arguments")

    repo_root = args.repo_root.resolve(strict=True)
    native_root = args.native_root.resolve(strict=True)
    scenario_path = args.scenario_config.resolve(strict=True)
    output_dir = legacy.safe_directory(args.output_dir, "output directory")
    log_dir = legacy.safe_directory(args.log_dir, "log directory")
    if (repo_root != args.repo_root or native_root != args.native_root or scenario_path != args.scenario_config):
        fail("repo, native, and scenario paths must already be canonical")

    try:
        root = json.loads(scenario_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot load scenario {scenario_path}: {error}")
    if not isinstance(root, dict):
        fail("scenario must be an object")
    check_scenario(root)

    cells = [dict(CELLS[0], cuda_stream_priority=args.stream_priority_a),
             dict(CELLS[1], cuda_stream_priority=args.stream_priority_b)]
    gnb_source = legacy.read_regular(repo_root / "examples/ocudu/gnb_zmq_b210_fdd_srsue.yaml", "gNB fixture")
    open5gs_source = legacy.read_regular(native_root / "src/ocudu/docker/open5gs/open5gs-5gc.yml",
                                         "pinned OCUDU Open5GS template")
    srsue_source = legacy.read_regular(repo_root / "examples/native/srsran/srsue_zmq_multi_ue.conf.in",
                                       "native srsUE template")
    subscriber_source = legacy.read_regular(repo_root / legacy.LAYOUTS[2][1], "native subscriber template")

    rendered = {
        "open5gs.yaml": legacy.render_open5gs(open5gs_source, native_root),
        "subscriber.csv": legacy.validate_subscriber(subscriber_source, legacy.UES[:2]),
    }
    metadata = {"scenario": str(scenario_path), "cells": {}, "rx_noise": {
        "awgn_snr_db": args.awgn_snr_db, "tx_power_dl": args.tx_power_dl, "tx_power_ul": args.tx_power_ul}}
    for cell in cells:
        name = cell["name"]
        scenario = split_scenario(root, cell)
        shape = cell_shape(cell, scenario)
        try:
            rx_noise = sionna.rx_noise_powers(shape, args.awgn_snr_db, args.tx_power_dl, args.tx_power_ul)
        except ValueError as error:
            fail(str(error))
        gnb_text = multi_gnb.render_gnb(gnb_source, cell["gnb"], log_dir)
        if args.gnb_acceleration:
            gnb_text = multi_gnb.add_acceleration(gnb_text, args.gnb_acceleration)
        rendered[f"{cell['gnb']['device_id']}.yaml"] = gnb_text
        rendered[f"topology-{name}.yaml"] = render_cell_topology(cell, shape, rx_noise)
        rendered[f"scenario-{name}.json"] = json.dumps(scenario, indent=2) + "\n"
        rendered[f"srsue-{cell['ue']['device_id']}.conf"] = legacy.render_srsue(srsue_source, cell["ue"], log_dir)
        metadata["cells"][name] = {
            "gnb": cell["gnb"], "ue": {k: cell["ue"][k] for k in ("device_id", "tx_port", "rx_port", "netns", "ipv4")},
            "cuda_stream_priority": cell["cuda_stream_priority"],
            "links": [{"from": l.source, "to": l.destination, "model": l.model} for l in shape.links],
            "noise_power": rx_noise,
        }
    for name, text in rendered.items():
        if name.endswith((".yaml", ".conf", ".csv")) and legacy.PLACEHOLDER_RE.search(text):
            fail(f"unresolved placeholder in {name}")
        legacy.write_new(output_dir / name, text)
    legacy.write_new(output_dir / "robot-fight-shape.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print("event=native_robot_fight_configs_rendered cells=2 "
          f"priorities={args.stream_priority_a},{args.stream_priority_b} "
          f"rx_noise={'on' if args.awgn_snr_db is not None else 'off'} "
          f"acceleration={args.gnb_acceleration or 'none'} output_dir=\"{output_dir}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
