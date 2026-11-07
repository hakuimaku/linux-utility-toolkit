# System Tools

The `lut system` command group provides read-only inspection of host Linux system
resources through a unified CLI and JSON contract.

## Principles and Guarantees

- **Pure CLI**: standard terminal text formatting and structured JSON via `--json`.
- **Read-only**: no modifications to system state, disk configurations, processes,
  or network firewall/sockets.
- **Root-free**: no `sudo` or root privileges required.
- **No systemd dependency**: works seamlessly across systemd, OpenRC, runit, musl, and container environments.
- **Zero external runtime dependencies**: utilizes Python standard library and Linux `/proc`. Network port inspection operates directly via `/proc/net` with automatic detection and acceleration via `ss` (from `iproute2`) when available.
- **Container and Cgroups Aware**: dynamically discovers nested container slices via `/proc/self/cgroup` to detect container CPU quotas (`cpu.max`) and memory limits (`memory.max` in cgroup v2 or `memory.limit_in_bytes` in cgroup v1) to prevent surprise OOM kills.
- **Stale Network Mount Hang Protection**: protects against kernel D-state freezes on unresponsive remote filesystems (NFS, CIFS, SSHFS, FUSE) using non-blocking daemon threads with strict 0.5s timeouts and the `--local-only` flag.
- **High-performance NSS/LDAP Caching**: leverages an LRU cache for UID-to-username resolution, eliminating network latency in enterprise directory environments.
- **Clean Display Filtering**: automatically filters internal systemd credential mounts and Snap loopback images (`/dev/loop*` squashfs).
- **Early-stage Process Filtering**: applies name and user filters before reading process internals or worker threads to eliminate I/O overhead.

---

## 1. System Information: `lut system info`

Inspect operating system distribution, kernel release, CPU model, thread count,
container CPU limits, and system uptime.

### Syntax

```bash
lut system info
lut system info --json
```

### Data Sources

- `/etc/os-release` and `/usr/lib/os-release` (`platform.freedesktop_os_release()`)
- `os.uname()` and `platform`
- `/proc/cpuinfo` (supports x86, ARM, RISC-V, PowerPC, and s390x)
- `os.cpu_count()`, `os.process_cpu_count()` (Python 3.13+), and `os.sched_getaffinity()`
- `/proc/self/cgroup` nested slice mapping to `/sys/fs/cgroup/<slice>/cpu.max` (cgroup v2) and `cpu.cfs_quota_us` (cgroup v1)
- `/proc/uptime`

### Text Output Example

```text
System Information

OS:           Arch Linux
Kernel:       6.12.1-arch1-1
Architecture: x86_64
Hostname:     archlinux
CPU:          12th Gen Intel(R) Core(TM) i5-1235U
CPU Threads:  12 (container quota: 4.0 cores)
Uptime:       1d 11h 39m
```

### JSON Output Example

```json
{
  "command": "system.info",
  "data": {
    "os_name": "Arch Linux",
    "os_version": null,
    "kernel_version": "6.12.1-arch1-1",
    "architecture": "x86_64",
    "hostname": "archlinux",
    "cpu_model": "12th Gen Intel(R) Core(TM) i5-1235U",
    "cpu_threads": 12,
    "usable_cpu_threads": 12,
    "container_cpu_quota": 4.0,
    "uptime_seconds": 128364.12
  }
}
```

---

## 2. Disk Information: `lut system disk`

Inspect filesystem capacity, used space, available space, and mount points.

### Syntax

```bash
lut system disk
lut system disk --path /home
lut system disk --all
lut system disk --all --include-virtual
lut system disk --all --local-only
lut system disk --json
```

### Options

- `-p, --path PATH`: inspect the filesystem containing the specified path (default: current working directory). Uses robust longest-prefix matching with `>= best_len` to ensure active over-mounts (shadowed mounts) are properly selected. Mutually exclusive with `--all`.
- `-a, --all`: display all mounted filesystems. By default, virtual pseudo-filesystems (such as `proc`, `sysfs`, `devtmpfs`, `cgroup2`, `pstore`, `bpf`), internal systemd credentials (`/run/credentials/*`), snap loopback filesystems (`/dev/loop*`), and zero-capacity filesystems are filtered out. Real container root filesystems (`overlay`, `overlayfs`) are preserved.
- `--include-virtual`: when used with `--all`, includes virtual and pseudo-filesystems.
- `--local-only`: skip remote/network filesystems (NFS, CIFS, SSHFS, FUSE rclone/s3fs, Ceph, GlusterFS) when scanning all mounts.
- `--json`: output structured JSON with raw byte counts, floating-point usage percentages, and a uniform `filesystems` array.

### Text Output Example

```text
Disk Usage

Mount Point:     /mnt/Data
Filesystem:      /dev/nvme0n1p5 (ext4)
Total Size:      235.7 GiB
Used:            120.4 GiB (51.1%)
Available:       115.3 GiB
```

Table Output (`--all`):

```text
Mounted Filesystems

FILESYSTEM      TYPE    MOUNT POINT      TOTAL        USED       AVAIL    USE%
/dev/nvme0n1p2  ext4    /             50.0 GiB    22.3 GiB    25.1 GiB   47.0%
/dev/nvme0n1p3  ext4    /home        400.0 GiB   180.2 GiB   199.4 GiB   47.5%
/dev/nvme0n1p5  ext4    /mnt/Data    235.7 GiB   120.4 GiB   115.3 GiB   51.1%
```

---

## 3. Memory Information: `lut system memory`

Inspect RAM, available memory, estimated used memory, buffers/cached, swap space,
and container memory limits.

### Syntax

```bash
lut system memory
lut system memory --json
```

### Data Sources

- `/proc/meminfo`
- `/proc/self/cgroup` nested container slice mapping to `/sys/fs/cgroup/<slice>/memory.max` and `memory.current` (cgroup v2)
- `/sys/fs/cgroup/<slice>/memory.limit_in_bytes` and `memory.usage_in_bytes` (cgroup v1)

### Text Output Example

```text
Memory

RAM Total:        15.3 GiB
RAM Available:     9.8 GiB
RAM Used:          5.5 GiB (estimated, 35.9%)
RAM Buffers:     256.0 MiB
RAM Cached:        4.2 GiB
Container Limit: 512.0 MiB
Container Used:  128.0 MiB (25.0%)

Swap Total:        4.0 GiB
Swap Used:       512.0 MiB (12.5%)
Swap Free:         3.5 GiB
```

---

## 4. Process Information: `lut system process`

Inspect running processes, lifetime CPU usage (aggregating all worker threads),
RSS memory, and command lines.

### Syntax

```bash
lut system process
lut system process --sort cpu
lut system process --sort memory
lut system process --sort pid
lut system process --sort name
lut system process --name python
lut system process --user root
lut system process --limit 10
lut system process --pid 1234
lut system process --json
```

### Options

- `-s, --sort FIELD`: sort processes by `cpu`, `memory`, `pid`, or `name` (default: `cpu`).
- `-l, --limit N`: maximum number of processes to display (default: `20`).
- `-n, --name SUBSTRING`: early filter processes whose name or command line contains the substring.
- `-u, --user USERNAME_OR_UID`: early filter processes by username or UID.
- `--pid PID`: inspect a specific process by PID, displaying complete command line and thread count.
- `--json`: output structured JSON.

### Optimizations and CPU Semantics

1. **Self-PID Exclusion**: When listing all processes, `lut` excludes its own PID (`os.getpid()`) so the inspection tool itself never pollutes the Top 1 CPU slot.
2. **Early-Stage Filtering**: When `--name` or `--user` is specified, non-matching processes are skipped before opening `/proc/<pid>/status` or `/proc/<pid>/task`, preventing massive I/O overhead.
3. **Smart Command Resolution**: For scripts executed via interpreters (`python3`, `node`, `bash`), the `COMMAND` column intelligently displays `python3 script.py` rather than just the generic interpreter name.
4. **Transient Spike Protection**: Sub-second processes are protected against artificial division spikes by dampening denominators for processes born $< 0.5$s ago.
5. **Lifetime CPU Average**: CPU% measures average resource consumption across all worker threads since process inception:

$$\text{CPU\%} = \frac{\sum (\text{utime} + \text{stime}) / \text{SC\_CLK\_TCK}}{\max(0.5, \text{uptime} - (\text{starttime} / \text{SC\_CLK\_TCK}))} \times 100$$

### Text Output Example

```text
Processes (sorted by cpu, limit 5) [CPU% is lifetime average]

   PID   PPID  USER          STATE   CPU%       RSS  COMMAND
  1234      1  alice           S     45.2   1.2 GiB  chrome
  5678   1234  alice           S     30.5 850.0 MiB  java app.jar
  9101      1  root            S     12.1 210.0 MiB  dockerd
  1122      1  systemd+        S      1.5  45.0 MiB  systemd-resolved
  3344   1000  alice           S      0.8  15.0 MiB  python3 worker.py
```

---

## 5. Network Ports: `lut system ports`

Inspect listening network sockets and open ports with canonical IPv6 normalization.

### Syntax

```bash
lut system ports
lut system ports --protocol tcp
lut system ports --protocol udp
lut system ports --port 8080
lut system ports --all
lut system ports --json
```

### Options

- `-p, --protocol PROTO`: filter by protocol (`tcp` or `udp`). Default: all listening TCP and active UDP sockets.
- `--port PORT`: filter by local port number (1–65535).
- `-a, --all`: display all sockets, including non-listening connections (e.g. `ESTAB`, `TIME-WAIT`).
- `--json`: output structured JSON.

### Canonical Address & Dual Backend Guarantees

- **Canonical IPv6 Representation**: Addresses from both `ss` (`[::]`) and `/proc/net` (`::`) are normalized to standard canonical form (`::`), ensuring zero schema drift across Linux distributions.
- **Deterministic Protocol Queries**: `ss` is queried separately per protocol (`-tlpn` / `-ulpn`), completely eliminating guessing of protocol columns.
- **Permission Boundary Guidance**: When executed as non-root, missing PID and process names for privileged system sockets are accompanied by a helpful notice in text mode.

### Text Output Example

```text
Open Network Ports

PROTO  STATE   LOCAL ADDRESS               PORT      PID  PROCESS
tcp    LISTEN  0.0.0.0                       22      800  sshd
tcp    LISTEN  127.0.0.1                   5037  1015195  adb
tcp    LISTEN  127.0.0.1                   8080     1234  server
udp    UNCONN  0.0.0.0                     5353      500  avahi-daemon

Note: Run with root/sudo or CAP_NET_ADMIN to view all process names.
```
