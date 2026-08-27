# Demo environment requirements

Everything the three demos (`run-demo.sh` :8080, `run-simo-demo.sh` :8081,
`native/run-live-demo.sh` :8082) assume about the machine, consolidated.
Recorded from the working setup on 2026-08-24; the version numbers are what
was actually measured there, not minimums.

**Not all of this is a supported path.** `:8080` and `:8081` need only this
repository plus a CUDA build of the broker and two Python packages. `:8082`
needs a `~/ocudu-native-workspace` that this repository cannot provision — the
native harness the 2026-08 review classified as a record of the original run,
not a reproducible one. The per-tier breakdown is in
[`README.md`](README.md#what-is-reproducible-from-this-repository); everything
below is the union of what all three need.

## Hardware / OS

- NVIDIA GPU with a current driver — working setup: **RTX 5090 (sm_120),
  driver 570.211.01** on **Ubuntu 24.04.3 LTS**. The broker binary in use was
  built with `-DOCUDU_GPU_CHANNEL_CUDA_ARCHITECTURES=120`; other GPUs need a
  rebuild with their arch.
- `/dev/net/tun` present and rootless user namespaces allowed
  (`unshare --user --map-root-user` must work) — the live tier needs both;
  no sudo is used anywhere.

## Toolchain

- **CUDA 12.8** — the gate and demo scripts default to
  `CUDACXX=/opt/conda/envs/cuda128/bin/nvcc` (12.8.93 here). Override with
  `CUDACXX=` if nvcc lives elsewhere.
- Standard tools the scripts check at startup: `cmake`, `ss`, `flock`,
  `setsid`, `stdbuf`, `taskset`, and for the live tier `unshare`, `nsenter`,
  `ip`, `mount`, `timeout`.

## Python

Two interpreters matter:

| Interpreter | Used by | Needs |
|---|---|---|
| `python3` on PATH (here: `/opt/conda/bin/python`, 3.13.5) | bridge, meters, pilot source, supervisor, tailer | **pyzmq** (27.2.0), **numpy** (2.5.1) |
| whichever python can `import bson` (here also the conda one) | live tier's Open5GS subscriber insert (`add_users.py`) | **pymongo** (4.17.0) |

Install once: `python3 -m pip install --user pyzmq numpy pymongo`.
Note: on this box `/usr/bin/python3` (3.12.3) has **no pip and no pymongo**;
`run-live-demo.sh` auto-selects an interpreter that can import `bson`, so
having pymongo on the conda python is sufficient. The scripts also honor
`PYTHON=` to force an interpreter.

## Repo builds (synthetic demos, :8080/:8081)

- `build-cuda/` in this repo with the CUDA backend ON — provides
  `ocudu-gpu-channel`, `ocudu-zmq-source`, `ocudu-zmq-sink`,
  `ocudu-control-req`. Build:

  ```bash
  cmake -S . -B build-cuda -DCMAKE_BUILD_TYPE=Release \
    -DOCUDU_GPU_CHANNEL_ENABLE_CUDA=ON -DCMAKE_CUDA_COMPILER="$CUDACXX"
  cmake --build build-cuda -j"$(nproc)"
  ```

## Native workspace (live tier, :8082)

`OCUDU_NATIVE_ROOT` (default `/home/ubuntu/ocudu-native-workspace`, and the
default is overridable) must be a workspace that **already exists**.
`scripts/native/bootstrap-workspace.sh` does not create one: its build mode
exits at line 228, so only `--verify-only` runs, against a tree provisioned
some other way. `scripts/native/native-workspace.lock.json` pins what that tree
must contain. The live runner expects these to already exist:

- `builds/ocudu-zmq-release/apps/gnb/gnb` — OCUDU gNB, ZMQ radio ON
- `builds/srsran4g-zmq-release/srsue/src/srsue` — srsUE (release_23_11)
- `builds/open5gs-v2.7.6/tests/app/5gc` — Open5GS 5GC
- `builds/ocudu-gpu-channel-rank1-cuda-release/ocudu-gpu-channel` — broker
  build WITH the v3.0 control/telemetry plane (this repo's source)
- `install/mongodb-6.0.29/bin/mongod`
- `install/sysroot`, `install/gnutls-3.7.3` — runtime libs (libtalloc etc.);
  `run-live-demo.sh` sources `scripts/native/env.sh` to put them on
  `LD_LIBRARY_PATH`, so no system-wide installs are needed.

## Network / ports

- Host-facing (open these if a laptop on the same subnet should connect):
  **8080** (2×2 page), **8081** (SIMO page), **8082** (live page). Everything
  else stays on loopback or inside the netns. `ufw` is inactive on this box.
- Loopback-only: 5559-5561 (2×2 control/telemetry/meter), 5562-5565 (SIMO),
  5566 (live-tier meter), 162xx / 163xx (synthetic IQ). The live tier's RAN
  ports (2000-2007, 2100-2101, 27017, Open5GS 127.0.0.x) exist only inside
  the demo's network namespace and cannot clash with the host.
- Viewing from a machine NOT on the box's subnet (typical SSH workflow):

  ```bash
  ssh -L 8080:localhost:8080 -L 8081:localhost:8081 -L 8082:localhost:8082 <box>
  ```

  then browse `http://localhost:808{0,1,2}`.

## Operational notes

- Run the long-lived stacks inside tmux; Ctrl-C in the pane tears each stack
  down completely (verified: no leftover processes or ports).
- Only one live tier (2x1 OR 4x1) at a time — enforced by a lock file; the
  three demos otherwise run concurrently.
- Browsers never speak ZMQ: keep the bridge processes; they are what the
  pages talk to.
