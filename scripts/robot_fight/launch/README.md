# launch — robot fight over the emulated link (R4b)

Glue between the native multi-UE gate's side-process hooks and the arena
package. Nothing here changes the arena, brains or modem; it only starts them
in the right namespaces, in the right order, and keeps fights running
back-to-back for the length of the gate.

| File | Hook | Runs where | Does |
|---|---|---|---|
| `root_exec.sh` | `OCUDU_NATIVE_MUE_ROOT_EXEC` | the stack namespace (ogstun 10.45.1.1, broker, bridge) | publishes the two spawn positions on the bridge's ipc endpoint while the UEs attach (`RF_PREPUB`), waits for both modems, then loops: one `arena.py` per fight (unix socket per robot, positions PUB) + one `brain.py` per robot bound to the gateway address; appends `fights/summary.jsonl` |
| `ue_exec.sh` | `OCUDU_NATIVE_MUE_UE_EXEC` | the UE's network namespace, after its ping passed | `modem.py` bound to the UE's tun address (`RF_PORT_BASE`+index), relaying to the arena's unix socket |
| `../analyze_run.py` | — | anywhere | joins a run's `fights/`, `sionna-status.jsonl`, `broker.log`, srsUE metrics/logs into a per-fight table (markdown + JSON) |

## Spark recipe (what R4b ran)

```
sudo env HOME=/root PATH=$PATH OCUDU_NATIVE_ROOT=/workspace/ocudu-spark \
  OCUDU_NATIVE_CHANNEL_BUILD=/workspace/ocudu-spark/builds/gpuch-r4b-release CUDACXX=/usr/local/cuda/bin/nvcc \
  OCUDU_NATIVE_SKIP_WORKSPACE_LOCK=1 \
  OCUDU_NATIVE_SIONNA_PYTHON=/workspace/sionna-venv/bin/python \
  DRJIT_LIBOPTIX_PATH=/usr/lib/aarch64-linux-gnu/libnvoptix.so.1 \
  OCUDU_NATIVE_SIONNA_SCENARIO=$tree/examples/sionna/robot-ring-walk.json \
  OCUDU_NATIVE_SIONNA_POSITION_ENDPOINT=ipc:///workspace/ocudu-spark/run/arena/positions.sock \
  OCUDU_NATIVE_SIONNA_POSITION_OFFSET=2.0,0,0 \
  OCUDU_NATIVE_SIONNA_TX_POWER_UL=3.0e2 \
  OCUDU_NATIVE_MUE_DURATION_SECONDS=300 OCUDU_NATIVE_MUE_STRICT_REALTIME=0 \
  OCUDU_NATIVE_MUE_ROOT_EXEC="RF_PYTHON=/workspace/robot-venv/bin/python RF_TIME_LIMIT=20 \
      RF_POS_ENDPOINT=ipc:///workspace/ocudu-spark/run/arena/positions.sock \
      bash $tree/scripts/robot_fight/launch/root_exec.sh {run_dir} {log_dir} '{ue_ids}' '{ue_ips}' {ue_gateway}" \
  OCUDU_NATIVE_MUE_UE_EXEC="bash $tree/scripts/robot_fight/launch/ue_exec.sh {ue_id} {ue_ip} {ue_index} {run_dir} {log_dir}" \
  bash scripts/native/run-ocudu-sionna-multi-ue.sh
```

Notes.

- The position endpoint must be `ipc://` (the bridge runs in the gate's
  network namespace); `root_exec.sh` binds it in the stack namespace, which
  shares the filesystem. Bridge offset `2.0,0,0` puts the 4 m ring east of the
  ring scene's pillars, in line of sight of the mast; `0,0,0` centres it on
  the pillars and the robots then cross the shadow (see the R4b record for
  what that does to the link).
- `RF_BOT` / `RF_POLICY` pass `--bot` / `--policy` through unchanged (unset =
  package defaults). The robot venv on the Spark is `/workspace/robot-venv`
  (mujoco, numpy, pyzmq, pytest); `modem.py` runs on the system python3.
- Modem sockets live under `{run_dir}/arena/` (short paths: AF_UNIX limit).
  Each fight is a new arena process; the modems and brains re-learn addresses
  from the first datagram, so nothing needs restarting between fights.
- Teardown: the gate stops `ue-exec-*` and `root-exec` groups; `root_exec.sh`
  forwards TERM to the running arena and brains. After a run
  `pgrep -af "arena.py|brain.py|modem.py"` should print nothing.
- Analyse: `python3 scripts/robot_fight/analyze_run.py --log-dir <log_dir>
  --report r.json --markdown r.md`.
