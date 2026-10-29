# DGX Spark dev containers

Three containers on the DGX Spark (`spark-host`, <spark-ip>), created 2026-09-24 with
`create-containers.sh` from this directory (copied to `~spark-admin/spark-containers/` on the host).

## Host (surveyed 2026-09-24)

| | |
|---|---|
| System | NVIDIA DGX Spark, DGX OS 7.5.0, Ubuntu 24.04.5, kernel 7.0.0-1019-nvidia, aarch64 |
| GPU | GB10, `sm_121`, 48 SMs, integrated |
| CUDA / driver | 13.0.88 (`/usr/local/cuda-13.0`) / 580.178.04 — WG1 reference is 13.0.88 / 580.95.05 |
| Managed-memory attributes (CMA / host PT / direct) | **1 / 1 / 0**, measured — the WG1 report stated this from the vendor table only |
| CPU / memory / disk | Cortex-X925 + A725, 20 cores / 121 GB / NVMe 3.7 TB |
| Container runtime | Docker 29.6.2, NVIDIA Container Toolkit 1.20.1, CDI spec `/var/run/cdi/nvidia.yaml` |

## Containers

| container | image | ssh | broker ctrl / telemetry | extra |
|---|---|---|---|---|
| `ocudu-user-a` | `ocudu-spark-base:1` | 2201 | 5559 / 5560 | — |
| `ocudu-minwoo` | `ocudu-spark-ocudu:1` | 2202 | 5561 / 5562 | NET_ADMIN, SYS_ADMIN, SYS_NICE, `/dev/net/tun`, rtprio 99, memlock ∞, ip_forward, AppArmor unconfined |
| `ocudu-user-b` | `ocudu-spark-base:1` | 2203 | 5563 / 5564 | — |

All three: GPU via CDI (`--device nvidia.com/gpu=all`), host CUDA 13.0 mounted read-only,
named volumes `<user>-home` → `/home/dev` and `<user>-workspace` → `/workspace`, bridge
network, `--restart unless-stopped`, per-container ssh host keys. Login user `dev`
(NOPASSWD sudo); passwords are set on the host with `docker exec -it ocudu-<user> passwd dev`.

- `base/Dockerfile`: Ubuntu 24.04 + build tools + libzmq + sshd. CUDA is not in the image.
- `ocudu/Dockerfile`: base + the workstation's noble debian overlay list
  (`scripts/native/locks/ubuntu-noble-amd64.debs.lock.tsv`) minus `libfftw3-quad3`
  (x86-only) + iptables.

## Problems hit while creating them

1. `libfftw3-quad3` has no arm64 package → dropped (OCUDU uses single-precision FFTW).
2. All three containers first shared one ssh host key: the openssh-server package
   generates keys at image build. The base image now deletes them so each container
   generates its own on first start.
3. `ip netns add` failed in `ocudu-minwoo` despite SYS_ADMIN:
   `mount --make-shared /run/netns failed: Permission denied`. Docker's default AppArmor
   profile on this host denies it (throwaway container: default → denied, `apparmor=unconfined` → OK).
   Only `ocudu-minwoo` runs unconfined.
4. `nvcc` was missing in non-login ssh sessions (`ssh host cmd`); PATH is now also set in
   `/etc/environment`.

## Verification (2026-09-24, final containers)

- Zhouyou Gu's skeleton `github.com/zhouyou-gu/ocudu-gpu-channel` @ `3bae52c`, built in each
  container's `/tmp` (removed afterwards) with `-DOCUDU_GPU_CHANNEL_CUDA_ARCHITECTURES=121`:
  GCC 13.3.0, libzmq 4.3.5, NVIDIA 13.0.88 → **12/12 tests passed in all three containers.**
- In an earlier run of the three builds **concurrently**, `matrix_profile_history` failed in two
  containers; run one container at a time it passed 3/3 in every container. It is probably
  timing-sensitive under shared GPU/CPU load — relevant once three people use the GPU at once. Not traced.
- `ocudu-minwoo`: netns create + `lo` up + delete OK, TUN create/delete OK, rtprio 99, ip_forward 1,
  `nvidia-smi -L` shows GB10, `nvcc` on PATH over plain `ssh spark-minwoo cmd`.
