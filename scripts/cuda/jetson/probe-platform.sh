#!/usr/bin/env bash
# Platform record for the J track (JETSON_MILESTONES.md J0-6). Runs inside the
# Jetson container and writes one JSON that every J-stage result directory copies.
#
#   NVP_MODE="$(ssh jetson-host sudo -n nvpmodel -q | head -1)" \
#     bash probe-platform.sh [out_dir]
#
# nvpmodel is host-only, so the mode name comes in through NVP_MODE; everything
# else is read here. Clocks and online cores are read from sysfs so the record
# shows what the mode actually did, not what it is called.
set -euo pipefail

out="${1:-/workspace/ocudu-jetson/results/j0-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$out"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cuda_bin=/usr/local/cuda/bin
cat > "$work/probe.cu" <<'EOF'
#include <cstdio>
static int attr(cudaDeviceAttr a) { int v = -1; cudaDeviceGetAttribute(&v, a, 0); return v; }
int main()
{
  int n = 0;
  cudaError_t e = cudaGetDeviceCount(&n);
  if (e != cudaSuccess) { printf("{\"error\": \"%s\"}\n", cudaGetErrorString(e)); return 1; }
  cudaDeviceProp p;
  cudaGetDeviceProperties(&p, 0);
  int drv = 0, rt = 0;
  cudaDriverGetVersion(&drv);
  cudaRuntimeGetVersion(&rt);
  printf("{\"name\": \"%s\", \"compute_capability\": \"%d.%d\", \"sm_count\": %d, "
         "\"total_global_mem\": %zu, \"driver_api\": %d, \"runtime_api\": %d, "
         "\"integrated\": %d, \"concurrent_managed_access\": %d, "
         "\"pageable_memory_access_uses_host_page_tables\": %d, "
         "\"direct_managed_mem_access_from_host\": %d}\n",
         p.name, p.major, p.minor, p.multiProcessorCount, p.totalGlobalMem, drv, rt,
         attr(cudaDevAttrIntegrated), attr(cudaDevAttrConcurrentManagedAccess),
         attr(cudaDevAttrPageableMemoryAccessUsesHostPageTables),
         attr(cudaDevAttrDirectManagedMemAccessFromHost));
  return 0;
}
EOF
"$cuda_bin/nvcc" -o "$work/probe" "$work/probe.cu"
"$work/probe" > "$work/cuda.json"

netns=fail
if sudo ip netns add j0probe 2>/dev/null; then
  sudo ip netns exec j0probe ip link set lo up && sudo ip netns exec j0probe ping -c1 -W1 127.0.0.1 >/dev/null && netns=ok
  sudo ip netns del j0probe
fi
tun=fail
if sudo ip tuntap add dev j0tun mode tun 2>/dev/null; then tun=ok; sudo ip link del j0tun; fi

dpkg-query -W -f '${Package}\t${Version}\n' > "$out/dpkg.tsv"
"$cuda_bin/nvcc" --version > "$work/nvcc.txt"

NETNS="$netns" TUN="$tun" WORK="$work" OUT="$out" python3 - <<'EOF'
import json, os, pathlib, platform, re, shutil, subprocess, datetime

def read(path, default=None):
    try:
        return pathlib.Path(path).read_text().strip()
    except OSError:
        return default

def status_field(name):
    for line in read("/proc/self/status", "").splitlines():
        if line.startswith(name + ":"):
            return line.split()[1]
    return None

cpu_freq = {}
for d in sorted(pathlib.Path("/sys/devices/system/cpu").glob("cpu[0-9]*")):
    f = d / "cpufreq"
    if f.exists():
        cpu_freq[d.name] = {k: read(f / k) for k in ("scaling_governor", "scaling_max_freq", "scaling_cur_freq", "cpuinfo_max_freq")}

gpu = pathlib.Path("/sys/class/devfreq/17000000.gpu")
nvcc = read(os.environ["WORK"] + "/nvcc.txt", "")
work = os.environ["WORK"]
record = {
    "schema": 1,
    "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "l4t": read("/etc/nv_tegra_release", "").splitlines()[0] if read("/etc/nv_tegra_release") else None,
    "kernel": platform.release(),
    "machine": platform.machine(),
    "hostname": platform.node(),
    "power": {
        "nvpmodel": os.environ.get("NVP_MODE") or "unknown (NVP_MODE not given; nvpmodel is host-only)",
        "cpu_online": read("/sys/devices/system/cpu/online"),
        "cpu_present": read("/sys/devices/system/cpu/present"),
        "cpu_freq": cpu_freq,
        "gpu_cur_freq": read(gpu / "cur_freq"),
        "gpu_max_freq": read(gpu / "max_freq"),
        "gpu_available_freqs": read(gpu / "available_frequencies"),
        "gpu_load_permille": read("/sys/devices/platform/gpu.0/load"),
    },
    "cuda": json.loads(read(work + "/cuda.json")),
    "nvcc": (re.search(r"release ([0-9.]+), (V[0-9.]+)", nvcc) or [None])[0],
    "capabilities": {"CapEff": status_field("CapEff"), "CapBnd": status_field("CapBnd")},
    "netns": os.environ["NETNS"],
    "tun": os.environ["TUN"],
    "ulimit": {
        "rtprio": subprocess.run(["bash", "-c", "ulimit -r"], capture_output=True, text=True).stdout.strip(),
        "memlock": subprocess.run(["bash", "-c", "ulimit -l"], capture_output=True, text=True).stdout.strip(),
    },
    "ip_forward": read("/proc/sys/net/ipv4/ip_forward"),
    "disk_free_bytes": {p: shutil.disk_usage(p).free for p in ("/workspace", "/home/dev") if os.path.exists(p)},
    "tools": {t: shutil.which(t) for t in ("ninja", "cmake", "gcc", "g++", "git", "tmux")},
    "dpkg_list": "dpkg.tsv",
}
out = pathlib.Path(os.environ["OUT"]) / "platform.json"
out.write_text(json.dumps(record, indent=2) + "\n")
print(out)
EOF
