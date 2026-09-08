# Rootless native gNB–UE live attach

The [8 September 2026 CUDA integration report](../../docs/cuda-ocudu-integration-report.md)
records C0–C2 completion, the final C3 all-enabled MPS comparison, reproducible
commands, and the remaining certification work.

## CUDA gNB build gate (C0)

`build-ocudu-cuda.sh` builds a separate CUDA+ZMQ gNB and runs the documented
12-test CUDA PHY subset plus the PUSCH CFO interpolation and synchronous SINR regressions (14 tests). It requires the existing native dependency overlay,
CUDA 12.8, and WG source commit `5830c9cb7813393b5d518dd5ee2b6641071be4ad`
at `$OCUDU_NATIVE_ROOT/src/ocudu-cuda`. The source URL is
`https://gitlab.com/ocudu/work_groups/wg1_hw_accel/cuda_accelerated_ocudu.git`.

```bash
# After setting OCUDU_NATIVE_ROOT and CUDACXX for the native environment:
bash scripts/native/build-ocudu-cuda.sh
```

The helper applies `patches/ocudu-cuda-host-grid-compat.patch` to that commit.
It accepts a clean source or the exact patched source and rejects unrelated
edits. The patch restores SRS staging for host/pinned grids and supports
single-symbol GPU compression after a host read of a managed grid, including
read-hold release. It also passes the configured time-interpolation strategy
to the resident GPU PUSCH estimator. Regressions cover repeated grid reads
and 400 Hz CFO with 16QAM across changing slots.

Build output is isolated in `builds/ocudu-cuda-zmq-release`; the default target
architecture is locked to 120 and build parallelism defaults to 8. Set
`OCUDU_NATIVE_BUILD_JOBS` to change parallelism; another architecture requires
an explicitly revised lock and validation. PUSCH comparison recreates
GPU processors across 48 conditions and can take many minutes. CTest output is
verbose, with a one-hour per-test limit. `verify-cuda-phy-log.py` also checks the
printed PUSCH verdicts and complete sweep coverage because the upstream test
programs can return zero after printing a failed verdict. Its regression tests
run with `python3 -B tests/test_cuda_phy_log.py`.

This build gate does not change the gNB selected by the live attach scripts.
Results and subsequent integration stages are recorded in
[the CUDA integration plan](../../docs/plans/cuda-ocudu-integration.md).

## gNB profile selection (C1)

`OCUDU_NATIVE_GNB_PROFILE=cpu` (also the unset default) selects the original
CPU gNB. `cuda` selects `builds/ocudu-cuda-zmq-release/apps/gnb/gnb` in the
shared legacy/Sionna runner and `check-workspace.sh`. Unknown values fail.
Bootstrap continues to provision the CPU baseline; use `build-ocudu-cuda.sh`
for the separately checked-out CUDA source.

The lock records both source/build profiles and the reviewed patch SHA256.
CPU checks do not require the optional CUDA checkout. CUDA checks require the
pinned commit plus exactly the approved patch, with no unrelated changes.
`native_gnb_profile.py` checks the selected CMake source directory, ZMQ support,
binary revision and CUDA architecture/help marker. Source evidence records
`gnb_profile`, binary SHA256 and `gnb_provenance`; CUDA provenance additionally
records patch, architecture, compiler/runtime versions and GPU/driver inventory.
The artifact verifier accepts historical CPU evidence and validates the new
profile identity and CUDA fields when present.

```bash
# Read-only CUDA validation and provenance; native dependency environment loaded:
OCUDU_NATIVE_GNB_PROFILE=cuda bash scripts/native/check-workspace.sh
python3 scripts/native/native_gnb_profile.py --root "$OCUDU_NATIVE_ROOT" --profile cuda --hardware
# Existing CPU live regression:
OCUDU_NATIVE_GNB_PROFILE=cpu bash scripts/native/run-ocudu-legacy-1x1.sh
```

C1 verified selection, configuration dry-runs and CPU live regression.
The subsequent live startup fix starts CUDA PHY initialization before the
broker's 15-second clock, allowing up to 120 seconds for the radio-factory
marker. CPU startup order is unchanged. `OCUDU_NATIVE_GNB_ACCELERATION=auto`
(the default) retains upstream settings and original rendered bytes. The first
live auto run after the startup fix reached RRC but failed PDU establishment
with repeated PUSCH CRC failures. The reviewed patch now fixes the cause:
the resident GPU estimator used averaging instead of the configured time
interpolation. The normal gNB default is interpolation with CFO compensation
off, so ignoring that setting broke decoding on the CFO-impaired live channel.
Two runs with the patched binary and default acceleration passed attach/PDU/ping:
`20260908T121121Z` and `20260908T121232Z`.

Run accelerated gNB without an interpolation override:

```bash
OCUDU_NATIVE_GNB_PROFILE=cuda bash scripts/native/run-ocudu-legacy-1x1.sh
```

The log now reports `PUSCH GPU channel estimator: time_interpolation=interpolate`
and `PUSCH acceleration manifest: ... backend=CUDA resident_decode=true`.
On this discrete GPU, `pdsch_acceleration_mode: auto` still selects host PDSCH
by upstream policy. These results prove connectivity, not CPU-equivalent
BLER/latency or strict realtime behavior. The measured broker starvations
were 8 and 5; overflow, sequence-gap and ZMQ-error counts were zero.

For the verified all-host comparison using the CUDA binary:

```bash
OCUDU_NATIVE_GNB_PROFILE=cuda OCUDU_NATIVE_GNB_ACCELERATION=disabled \
  bash scripts/native/run-ocudu-legacy-1x1.sh
```

This explicit option disables seven lower/upper-PHY acceleration modes and
uses pinned host grids. It passed attach/PDU/ping; the channel broker still
runs on CUDA. It is not a successful accelerated-gNB claim or completion of
the C2 performance comparison. Existing expert config sections are rejected
rather than overwritten. The requested mode is recorded in gNB provenance. Run profile regression tests with
`python3 -B tests/test_native_gnb_profile.py` and artifact provenance tests with
`python3 scripts/native/verify-legacy-1x1-artifacts.py --self-test`.

## Live attach

This directory contains the Docker-free 1×1 live gate:

```text
OCUDU gNB (ZMQ) <-> current ocudu-gpu-channel broker <-> srsUE
                         |
                     Open5GS 5GC
```

It is intentionally a single-gNB, single-UE path. No multi-antenna engine is
required or enabled by this harness.

## Why it does not need host-wide privileges

The runner starts with the invoking user's normal permissions and creates a
user, network, and mount namespace with:

```bash
unshare --user --map-root-user --net --mount
```

`CAP_NET_ADMIN` and `CAP_SYS_ADMIN` exist only inside that disposable user
namespace. The runner creates `ogstun` and the nested `ue1` network namespace
there, then removes them during cleanup. It does not invoke `sudo`, Docker, or
modify the host network namespace.

The host must still permit unprivileged user namespaces and expose
`/dev/net/tun` to the user. Test the first requirement with:

```bash
unshare --user --map-root-user --net --mount --fork /bin/true
test -c /dev/net/tun
```

## Required native workspace

Set `OCUDU_NATIVE_ROOT` to the dedicated workspace containing the pinned OCUDU
gNB, srsUE, Open5GS, MongoDB, and user-space runtime libraries described by
`native-workspace.lock.json`. The default is
`/home/ubuntu/ocudu-native-workspace`.

Provision it without sudo or Docker from the repository root:

```bash
export OCUDU_NATIVE_ROOT=/home/ubuntu/ocudu-native-workspace
./scripts/native/bootstrap-workspace.sh \
  --root "$OCUDU_NATIVE_ROOT" --jobs "$(nproc)"
```

The bootstrap downloads hash-locked inputs, extracts the user-space dependency
overlay, checks out the exact audited revisions, and builds every binary and
Open5GS module used by the live gate. To validate an existing workspace without
downloading or rebuilding it:

```bash
export OCUDU_NATIVE_ROOT=/home/ubuntu/ocudu-native-workspace
./scripts/native/bootstrap-workspace.sh \
  --verify-only --root "$OCUDU_NATIVE_ROOT"
```

The relevant pinned binaries are:

- `builds/ocudu-zmq-release/apps/gnb/gnb`
- `builds/srsran4g-zmq-release/srsue/src/srsue`
- `builds/open5gs-v2.7.6/tests/app/5gc`
- `install/mongodb-6.0.29/bin/mongod`

The broker is not taken from a stale workspace build. The live gate configures
and builds the current checkout into
`builds/ocudu-gpu-channel-cuda-release`, probes that exact binary, and passes
the same path to the runtime namespace.

## Run the 1×1 attach gate

From the repository root:

```bash
export OCUDU_NATIVE_ROOT=/home/ubuntu/ocudu-native-workspace
# This host's installed CUDA compiler. Override it if CUDA is elsewhere.
export CUDACXX=/opt/conda/envs/torch/bin/nvcc
export OCUDU_NATIVE_GPU_DEVICE=0

./scripts/native/run-ocudu-legacy-1x1.sh
```

The gate performs these checks in order:

1. Verifies pinned source revisions, cached inputs, native binaries, ZMQ, SCTP,
   `/dev/net/tun`, and rootless namespace support.
2. Renders loopback-only gNB, broker, Open5GS, subscriber, and srsUE configs.
3. Builds and tests the current broker with CUDA enabled.
4. Probes CUDA and the new broker inside an isolated user/network/mount
   namespace.
5. Starts MongoDB, Open5GS, the broker, OCUDU gNB, and srsUE.
6. Requires RRC connection, PDU-session establishment, and three successful
   pings from `tun_srsue` to `10.45.1.1`.

A successful run ends with:

```text
event=native_legacy_1x1_attach_gate result=pass ...
```

Run evidence is stored under:

```text
$OCUDU_NATIVE_ROOT/results/logs/ocudu-interop/<UTC timestamp>/
$OCUDU_NATIVE_ROOT/results/reports/ocudu-interop/<UTC timestamp>/
```

The report includes the exact source manifest, binary/configuration SHA-256
hashes, Broker counters, and attach summary. Any process or namespace created
by the gate is terminated on normal exit, failure, or Ctrl-C.

## Run gNB–UE with Sionna RT and the Web UI

The Sionna path uses the same Docker-free 1×1 gNB–UE stack. It adds a
low-rate Sionna RT controller and the read-only Web UI; it does not enable a
multi-antenna topology. Only one terminal is required:

```bash
export OCUDU_NATIVE_ROOT=/home/ubuntu/ocudu-native-workspace
export CUDACXX=/opt/conda/envs/torch/bin/nvcc
export OCUDU_NATIVE_GPU_DEVICE=0

./scripts/native/run-ocudu-sionna-1x1.sh
```

The launcher discovers the locally installed OptiX library and uses
`../venvs/sionna/bin/python` by default. Override the Python executable with
`OCUDU_NATIVE_SIONNA_PYTHON` when needed. It prints the Web UI URL after the
HTTP server starts and prints `event=native_sionna_1x1_live_ready` only after
all of these conditions hold:

1. The OCUDU gNB and srsUE establish RRC and a PDU session.
2. The UE namespace successfully pings `10.45.1.1` through `tun_srsue`.
3. Sionna RT atomically updates both directed 1×1 channel profiles.
4. The Web UI receives both the Sionna JSONL feed and Broker telemetry.

Open <http://127.0.0.1:8080> while the command is running. The default live
run continues until Ctrl-C. For an automatically terminating evidence run,
set a duration in seconds before starting it:

```bash
export OCUDU_NATIVE_SIONNA_DURATION_SECONDS=150
./scripts/native/run-ocudu-sionna-1x1.sh
```

Optional settings are `OCUDU_NATIVE_WEB_PORT` (default `8080`),
`OCUDU_NATIVE_SIONNA_UPDATE_HZ` (default `10`), and
`OCUDU_NATIVE_SIONNA_READY_SECONDS` (default `120`). The Web server is
restricted to loopback. A remote browser can use SSH port forwarding:

```bash
ssh -L 8080:127.0.0.1:8080 ubuntu@GPU_HOST
```

### Keeping the RAN KPI panel populated

`OCUDU_NATIVE_GNB_METRICS=1` turns on the per-UE scheduler KPI panel. Two
further switches decide whether that panel has anything to show, and both are
off by default so every gate renders and runs exactly as before:

| Variable | Default | Effect |
| --- | --- | --- |
| `OCUDU_NATIVE_UE_INACTIVITY_SECONDS` | unset (gNB default, 120 s) | Renders `cu_cp.inactivity_timer`, accepted range 1-7200. Without it the gNB releases an idle UE about two minutes after the acceptance ping and the panel correctly reports no connected UEs. |
| `OCUDU_NATIVE_UE_KEEPALIVE_SECONDS` | `0` (off) | Ping interval in the UE namespace, accepted range 0.2-60 s, fractional. Started only on an unbounded run and only after the acceptance verdict is written, logging to `ue-keepalive.log`. |

Set the keepalive interval well under the scheduler's report period
(`metrics.periodicity.du_report_period`, 1 s as rendered). The KPIs are sums
over one report period, so an interval at or above that period leaves the
periods in between reporting zero throughput, zero HARQ counts and no SINR --
truthfully, since nothing was transmitted in them. `0.2` puts five packets in
every report and keeps the row continuously populated:

```bash
OCUDU_NATIVE_GNB_METRICS=1 \
OCUDU_NATIVE_UE_INACTIVITY_SECONDS=7200 \
OCUDU_NATIVE_UE_KEEPALIVE_SECONDS=0.2 \
./scripts/native/run-ocudu-sionna-rank1.sh
```

The CQI and DL RI columns stay empty regardless: this configuration runs with
`csi_rs_enabled: false`, so the scheduler reports `cqi = -1` ("no CSI report")
for the whole run.

Sionna mode stores logs and reports separately from the legacy gate:

```text
$OCUDU_NATIVE_ROOT/results/logs/ocudu-sionna-1x1/<UTC timestamp>/
$OCUDU_NATIVE_ROOT/results/reports/ocudu-sionna-1x1/<UTC timestamp>/
```

The runtime uses Unix-domain ZeroMQ endpoints under the native workspace for
Sionna control and Web UI telemetry. They cross the disposable mount/network
namespace through the shared filesystem without exposing a host TCP control
port or requiring host networking privileges.

## Run scenario-sized rank-1 MISO/SIMO with Sionna and the Web UI

The rank-1 launcher reads the gNB transmit and receive port counts from the
Sionna scenario instead of carrying a separate 2x1 or 4x1 shell setting. The
default scenario resolves to 4 gNB TX ports, 4 gNB RX ports, and a one-port UE
(4x1 DL MISO and 1x4 UL SIMO):

```bash
export OCUDU_NATIVE_ROOT=/home/ubuntu/ocudu-native-workspace
export CUDACXX=/opt/conda/envs/torch/bin/nvcc
export OCUDU_NATIVE_GPU_DEVICE=0
export OCUDU_NATIVE_SIONNA_PYTHON=/home/ubuntu/OCUDU/venvs/sionna/bin/python

./scripts/native/run-ocudu-sionna-rank1.sh
```

To change the live dimensions, point the launcher at an absolute scenario
path and edit `nodes.gnb0.tx_array` / `nodes.gnb0.rx_array`. The native OCUDU
gate accepts 1, 2, or 4 ports in each direction; the srsUE arrays must remain
1x1. The scenario links must remain the single `gnb0 -> ue0` downlink and
`ue0 -> gnb0` uplink:

```bash
export OCUDU_NATIVE_SIONNA_SCENARIO=/absolute/path/to/scenario.json
./scripts/native/run-ocudu-sionna-rank1.sh
```

The renderer derives `nof_antennas_dl`, `nof_antennas_ul`, every ZMQ port,
Broker radio-node ordering, and both control link ids from that scenario. It
does not declare `fixed_mimo`; Sionna supplies a complete matrix profile for
each direction before the gNB and srsUE start. Readiness is reported as
`event=native_sionna_rank1_live_ready`, and run artifacts are stored under
`results/{logs,reports}/ocudu-sionna-rank1/`.

## Common blockers

- `unshare: ... Operation not permitted`: the containing host, VM, LXC, or
  command sandbox disables unprivileged user namespaces.
- `/dev/net/tun is absent`: expose the TUN device to the environment running
  the gate.
- `CUDA hardware probe failed`: check the NVIDIA device/driver visibility and
  `OCUDU_NATIVE_GPU_DEVICE`.
- `workspace lock` or revision mismatch: use the pinned native workspace; the
  gate fails closed instead of silently using different RAN/core binaries.

### CUDA stage qualification

`OCUDU_NATIVE_GNB_ACCELERATION` accepts cumulative stages `low-phy-rx`,
`low-phy-tx`, `pusch`, `pdsch`, `prach`, and `all`, plus `auto` and the
all-host control `disabled`. Forced lower-PHY stages select managed grids
because pinned grids do not expose the required device mapping interface.
PDSCH is explicitly enabled from its stage onward; `auto` retains upstream
backend policy. SRS backend construction does not prove scheduled SRS traffic.

Run campaigns sequentially inside the native environment:

```bash
python3 scripts/native/qualify-cuda-stages.py --stage c2
python3 scripts/native/qualify-cuda-stages.py --stage c3
python3 scripts/native/qualify-cuda-stages.py --stage c3 --metrics
```

The first two commands preserve the 15-second legacy traffic fixture. The
metrics command uses a separate 90-second `ocudu-cuda-kpi` result family,
starts 0.2-second gateway pings after attach acceptance, and records 60
consecutive one-second scheduler notifications with their original JSON.
Missing traffic, missing SINR, UE changes, and gaps fail measurement validation.
KPI summaries average per-report BLER and SINR; comparison uses the original
1 percentage point BLER and 0.5 dB SINR limits. Campaign evidence retains all
runs, including failures; a measurement pass alone is not a C3 parity pass.

Broker process-latency histograms now use 1 us buckets. Earlier 5 us evidence
is retained with its original measurement resolution. Nonzero starvation
counters still preclude a strict-realtime claim.

### Qualified shared-GPU execution

On this RTX 5090, an isolated CUDA MPS server brought the 15-second all-enabled
profile within ±5% of the CPU reference in three interleaved pairs. The final
90-second CPU/all-enabled pair also passed: broker p99 82/82 versus 83/82 us
(gNB/UE), UL/DL BLER difference 0 percentage points, and SINR difference 0.336 dB.
These measurements use 23.04 MS/s, rank-1 1×1, the legacy single-tap -3 dB channel
with 0.125 rad phase and 125 Hz CFO, and 60 one-second scheduler reports. Nonzero
starvation counts preclude strict-realtime certification.

After loading the native environment, run from the project root:

```bash
OCUDU_NATIVE_GNB_PROFILE=cuda OCUDU_NATIVE_GNB_ACCELERATION=all \
  python3 scripts/native/with-cuda-mps.py -- bash scripts/native/run-ocudu-legacy-1x1.sh

# Reproduce the final CPU/all-enabled KPI comparison:
python3 scripts/native/with-cuda-mps.py -- \
  python3 scripts/native/qualify-cuda-stages.py --stage c3 --metrics --acceleration all
```

The wrapper creates a private MPS control socket, records daemon/client
connections, and stops its server after the command exits. It supports the
qualified physical GPU 0 and does not change GPU compute modes. Evidence is
under `results/cuda-qualification/mps-*`.

The final comparison certifies the selected `all` stage. The initial six-stage
campaign was preserved; a complete six-stage campaign after the last SINR fix
has not been repeated. `full_c3_kpi_qualified` remains false until that campaign
passes. The newly registered 14-test PHY suite was not fully rerun; the affected
PUSCH CFO/synchronous-SINR and PDSCH tests passed, with negative controls for
both identified defects.
