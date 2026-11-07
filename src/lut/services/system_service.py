"""System service implementing info, disk, memory, process, and network port queries."""

import functools
import ipaddress
import json
import os
import platform
import pwd
import re
import shutil
import socket
import struct
import sys
import threading
from pathlib import Path
from typing import Any

from lut.core.dependencies import DependencyError
from lut.core.errors import InputError, OutputError, UsageError
from lut.core.process import run_process


def _format_size(size_bytes: int | float) -> str:
    """Format bytes into human-readable binary representation (KiB, MiB, GiB, TiB)."""
    if size_bytes < 1024:
        return f"{int(size_bytes)} B"
    val = float(size_bytes)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        val /= 1024.0
        if val < 1024.0 or unit == "TiB":
            return f"{val:.1f} {unit}"
    return f"{val:.1f} PiB"


def _format_uptime(seconds: float) -> str:
    """Format uptime seconds into a human-readable string (e.g. 3h 24m, 2d 5h 12m)."""
    total_sec = int(seconds)
    days, rem = divmod(total_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0 or days > 0:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


def _decode_mount_path(escaped: str) -> str:
    """Decode octal escape sequences in /proc/mounts and /proc/self/mountinfo."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), escaped)


# =====================================================================
# 1. System Info & Cgroup Resolution
# =====================================================================


def _get_os_release() -> dict[str, str]:
    """Parse /etc/os-release or /usr/lib/os-release without external tools."""
    try:
        return platform.freedesktop_os_release()
    except (OSError, AttributeError):
        pass

    release_info: dict[str, str] = {}
    for candidate in ("/etc/os-release", "/usr/lib/os-release"):
        path = Path(candidate)
        if path.is_file():
            try:
                with open(path, encoding="utf-8", errors="replace") as stream:
                    for line in stream:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("\"'")
                        if key:
                            release_info[key] = val
                if release_info:
                    return release_info
            except OSError:
                continue
    return release_info


def _get_cpu_model() -> str | None:
    """Read CPU model name from /proc/cpuinfo across diverse architectures."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                line = line.strip()
                if not line or ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                # x86 / ARM / RISC-V / PowerPC / s390x variants
                if key in ("model name", "Processor", "Hardware", "cpu model", "Machine", "cpu"):
                    if val:
                        return val
    except OSError:
        pass
    return None


def _get_uptime_seconds() -> float | None:
    """Read system uptime in seconds from /proc/uptime."""
    try:
        with open("/proc/uptime", encoding="utf-8", errors="replace") as stream:
            first_line = stream.readline().strip()
            if first_line:
                first_token = first_line.split()[0]
                return float(first_token)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _get_cgroup_candidate_paths(controller: str) -> list[Path]:
    """Resolve cgroup directory paths considering /proc/self/cgroup nested container slices."""
    candidates: list[Path] = []
    self_cgroup = Path("/proc/self/cgroup")
    if self_cgroup.is_file():
        try:
            with open(self_cgroup, encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(":", 2)
                    if len(parts) == 3:
                        sub_path = parts[2].lstrip("/")
                        # cgroup v2 unified hierarchy (id '0' and empty controller field)
                        if parts[0] == "0" and not parts[1] and sub_path:
                            candidates.append(Path("/sys/fs/cgroup") / sub_path)
                        # cgroup v1 per-controller hierarchy
                        elif controller in parts[1].split(",") and sub_path:
                            candidates.append(Path(f"/sys/fs/cgroup/{parts[1]}") / sub_path)
                            candidates.append(Path(f"/sys/fs/cgroup/{controller}") / sub_path)
        except OSError:
            pass

    # Standard root cgroup locations as fallback
    candidates.append(Path(f"/sys/fs/cgroup/{controller}"))
    candidates.append(Path("/sys/fs/cgroup"))
    return candidates


def _get_cgroup_cpu_quota() -> float | None:
    """Read container CPU quota if restricted by cgroup v2 or v1."""
    # 1. cgroup v2: cpu.max has "<quota> <period>"
    for candidate in _get_cgroup_candidate_paths("cpu"):
        p = candidate / "cpu.max"
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8").strip()
                parts = content.split()
                if len(parts) >= 2 and parts[0] != "max":
                    quota = int(parts[0])
                    period = int(parts[1])
                    if period > 0 and quota > 0:
                        return round(quota / period, 2)
            except (OSError, ValueError, PermissionError):
                pass

    # 2. cgroup v1: cpu.cfs_quota_us and cpu.cfs_period_us
    for candidate in _get_cgroup_candidate_paths("cpu"):
        quota_p = candidate / "cpu.cfs_quota_us"
        period_p = candidate / "cpu.cfs_period_us"
        if quota_p.is_file() and period_p.is_file():
            try:
                quota = int(quota_p.read_text(encoding="utf-8").strip())
                period = int(period_p.read_text(encoding="utf-8").strip())
                if quota > 0 and period > 0:
                    return round(quota / period, 2)
            except (OSError, ValueError, PermissionError):
                pass

    return None


def _get_cpu_counts() -> tuple[int | None, int | None, float | None]:
    """Return logical CPU count, usable CPU count (respecting affinity), and container quota."""
    logical_cores = os.cpu_count()
    usable_cores: int | None = None

    if hasattr(os, "process_cpu_count"):
        try:
            usable_cores = os.process_cpu_count()
        except Exception:
            pass
    elif hasattr(os, "sched_getaffinity"):
        try:
            usable_cores = len(os.sched_getaffinity(0))
        except (OSError, AttributeError):
            pass

    container_quota = _get_cgroup_cpu_quota()
    return logical_cores, usable_cores, container_quota


def system_info(*, as_json: bool = False, stdout_stream=None) -> int:
    """Inspect and display system identity, architecture, CPU, and uptime."""
    out = sys.stdout if stdout_stream is None else stdout_stream

    release = _get_os_release()
    os_name = release.get("NAME") or release.get("PRETTY_NAME") or platform.system() or "Linux"
    os_version = release.get("VERSION_ID") or release.get("VERSION")

    uname = os.uname()
    kernel_version = uname.release
    architecture = uname.machine
    hostname = uname.nodename

    cpu_model = _get_cpu_model()
    cpu_threads, usable_threads, container_quota = _get_cpu_counts()
    uptime_sec = _get_uptime_seconds()

    if as_json:
        payload = {
            "command": "system.info",
            "data": {
                "os_name": os_name,
                "os_version": os_version,
                "kernel_version": kernel_version,
                "architecture": architecture,
                "hostname": hostname,
                "cpu_model": cpu_model,
                "cpu_threads": cpu_threads,
                "usable_cpu_threads": usable_threads,
                "container_cpu_quota": container_quota,
                "uptime_seconds": uptime_sec,
            },
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write("System Information\n\n")
        out.write(f"OS:           {os_name}\n")
        if os_version:
            out.write(f"OS Version:   {os_version}\n")
        out.write(f"Kernel:       {kernel_version}\n")
        out.write(f"Architecture: {architecture}\n")
        out.write(f"Hostname:     {hostname}\n")
        out.write(f"CPU:          {cpu_model or 'Unknown'}\n")

        if container_quota is not None and (
            cpu_threads is None or container_quota < float(cpu_threads)
        ):
            cpu_str = f"{cpu_threads or 'Unknown'} (container quota: {container_quota} cores)"
        elif (
            usable_threads is not None and cpu_threads is not None and usable_threads < cpu_threads
        ):
            cpu_str = f"{cpu_threads} (usable: {usable_threads})"
        else:
            cpu_str = str(cpu_threads) if cpu_threads is not None else "Unknown"
        out.write(f"CPU Threads:  {cpu_str}\n")

        uptime_display = _format_uptime(uptime_sec) if uptime_sec is not None else "Unknown"
        out.write(f"Uptime:       {uptime_display}\n")

    return 0


# =====================================================================
# 2. Disk Information
# =====================================================================

VIRTUAL_FILESYSTEM_TYPES = {
    "proc",
    "sysfs",
    "devtmpfs",
    "devpts",
    "cgroup",
    "cgroup2",
    "pstore",
    "bpf",
    "autofs",
    "mqueue",
    "hugetlbfs",
    "fusectl",
    "tracefs",
    "configfs",
    "debugfs",
    "securityfs",
    "efivarfs",
    "binfmt_misc",
    "ramfs",
}

NETWORK_FILESYSTEM_KEYWORDS = (
    "nfs",
    "cifs",
    "smb",
    "sshfs",
    "rclone",
    "s3fs",
    "juicefs",
    "davfs",
    "gluster",
    "ceph",
    "lustre",
    "afp",
    "gpfs",
    "pvfs",
)


def _is_network_filesystem(fs_type: str, device: str) -> bool:
    """Determine whether a filesystem is a remote/network mount (NFS/CIFS/FUSE)."""
    fst = fs_type.lower()
    dev = device.lower()
    if any(kw in fst for kw in NETWORK_FILESYSTEM_KEYWORDS):
        return True
    if any(kw in dev for kw in NETWORK_FILESYSTEM_KEYWORDS):
        return True
    if fst.startswith("fuse.") and any(kw in fst for kw in NETWORK_FILESYSTEM_KEYWORDS):
        return True
    if ":" in device and not device.startswith("/dev/"):
        return True
    return False


def _stat_with_daemon_thread(
    target_path: str | Path, timeout: float = 0.5
) -> tuple[int, int, int, int] | None:
    """Stat target path using a daemon thread with timeout to avoid kernel D-state freeze."""
    result: list[tuple[int, int, int, int]] = []

    def _worker():
        try:
            st = os.statvfs(target_path)
            frsize = st.f_frsize or st.f_bsize
            result.append((st.f_blocks, st.f_bfree, st.f_bavail, frsize))
        except (OSError, PermissionError):
            pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive() or not result:
        return None
    return result[0]


def _parse_mountinfo() -> list[dict[str, str]]:
    """Parse /proc/self/mountinfo with octal decoding, falling back to /proc/mounts."""
    mounts: list[dict[str, str]] = []
    mountinfo_path = Path("/proc/self/mountinfo")
    if mountinfo_path.is_file():
        try:
            with open(mountinfo_path, encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    tokens = line.split()
                    if len(tokens) < 7:
                        continue
                    try:
                        sep_idx = tokens.index("-")
                    except ValueError:
                        continue
                    if sep_idx + 2 >= len(tokens):
                        continue

                    mount_point = _decode_mount_path(tokens[4])
                    fs_type = tokens[sep_idx + 1]
                    device = _decode_mount_path(tokens[sep_idx + 2])
                    mounts.append(
                        {
                            "mount_point": mount_point,
                            "filesystem_type": fs_type,
                            "device": device,
                        }
                    )
            if mounts:
                return mounts
        except OSError:
            pass

    # Fallback to /proc/mounts
    mounts_path = Path("/proc/mounts")
    if mounts_path.is_file():
        try:
            with open(mounts_path, encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    tokens = line.split()
                    if len(tokens) >= 3:
                        device = _decode_mount_path(tokens[0])
                        mount_point = _decode_mount_path(tokens[1])
                        fs_type = tokens[2]
                        mounts.append(
                            {
                                "mount_point": mount_point,
                                "filesystem_type": fs_type,
                                "device": device,
                            }
                        )
        except OSError:
            pass
    return mounts


def _stat_filesystem(
    target_path: str | Path,
    mount_point: str | None = None,
    device: str | None = None,
    fs_type: str | None = None,
) -> dict[str, Any] | None:
    """Calculate filesystem usage stats safely without modifying disks."""
    dev_str = device or "Unknown"
    fst_str = fs_type or "Unknown"

    if _is_network_filesystem(fst_str, dev_str):
        net_stats = _stat_with_daemon_thread(target_path, timeout=0.5)
        if net_stats is None:
            return None
        blocks, bfree, bavail, frsize = net_stats
    else:
        try:
            st = os.statvfs(target_path)
            frsize = st.f_frsize or st.f_bsize
            blocks = st.f_blocks
            bfree = st.f_bfree
            bavail = st.f_bavail
        except (OSError, PermissionError):
            return None

    total_bytes = blocks * frsize
    available_bytes = bavail * frsize
    used_bytes = (blocks - bfree) * frsize

    user_space = used_bytes + available_bytes
    if total_bytes <= 0 or user_space <= 0:
        usage_percent = 0.0
    else:
        usage_percent = round(min(100.0, max(0.0, (used_bytes / user_space) * 100)), 1)

    return {
        "mount_point": mount_point or str(target_path),
        "device": dev_str,
        "filesystem_type": fst_str,
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "available_bytes": available_bytes,
        "usage_percent": usage_percent,
    }


def system_disk(
    *,
    path: str | Path | None = None,
    all_filesystems: bool = False,
    include_virtual: bool = False,
    local_only: bool = False,
    as_json: bool = False,
    stdout_stream=None,
) -> int:
    """Inspect disk capacity, used space, available space, and mount points."""
    out = sys.stdout if stdout_stream is None else stdout_stream

    # Validate mutually exclusive and dependent arguments
    if path is not None and all_filesystems:
        raise UsageError(
            "Cannot combine --path and --all. Choose either a specific path or all filesystems."
        )
    if include_virtual and not all_filesystems:
        raise UsageError("--include-virtual can only be used in combination with --all.")

    if path is not None:
        target = Path(path)
        if not target.exists():
            raise InputError(f"Path not found: {path}")
        resolved = target.resolve()

        # Find best matching mount point using longest prefix matching
        # (use >= to ensure latest active over-mount / shadowed mount wins)
        mounts = _parse_mountinfo()
        best_match: dict[str, str] | None = None
        best_len = -1
        resolved_str = str(resolved)
        for m in mounts:
            mp = m["mount_point"]
            matches = (
                resolved_str == mp or resolved_str.startswith(mp.rstrip("/") + "/") or mp == "/"
            )
            if matches and len(mp) >= best_len:
                best_len = len(mp)
                best_match = m

        dev = best_match["device"] if best_match else "Unknown"
        fst = best_match["filesystem_type"] if best_match else "Unknown"
        mp = best_match["mount_point"] if best_match else resolved_str

        stat_info = _stat_filesystem(resolved, mount_point=mp, device=dev, fs_type=fst)
        if stat_info is None:
            raise OutputError(f"Cannot inspect disk usage for path: {path}")

        if as_json:
            payload = {
                "command": "system.disk",
                "data": {
                    **stat_info,
                    "total_filesystems": 1,
                    "filesystems": [stat_info],
                },
            }
            out.write(json.dumps(payload, indent=2) + "\n")
        else:
            out.write("Disk Usage\n\n")
            out.write(f"Mount Point:     {stat_info['mount_point']}\n")
            out.write(f"Filesystem:      {stat_info['device']} ({stat_info['filesystem_type']})\n")
            out.write(f"Total Size:      {_format_size(stat_info['total_bytes'])}\n")
            used_str = _format_size(stat_info["used_bytes"])
            out.write(f"Used:            {used_str} ({stat_info['usage_percent']}%)\n")
            out.write(f"Available:       {_format_size(stat_info['available_bytes'])}\n")
        return 0

    if all_filesystems:
        raw_mounts = _parse_mountinfo()
        # Preserve latest entry for shadowed mounts
        deduped: dict[str, dict[str, str]] = {}
        for m in raw_mounts:
            deduped[m["mount_point"]] = m

        results: list[dict[str, Any]] = []
        for mp, m in sorted(deduped.items()):
            fs_type = m["filesystem_type"]
            device = m["device"]

            if not include_virtual:
                # Filter virtual pseudo-filesystems
                if fs_type in VIRTUAL_FILESYSTEM_TYPES:
                    continue
                # Filter snap squashfs loop mounts (/dev/loop*) and systemd credentials
                if fs_type == "squashfs" and device.startswith("/dev/loop"):
                    continue
                if mp.startswith("/run/credentials/") or mp.startswith("/run/systemd/unit-root"):
                    continue

            if local_only and _is_network_filesystem(fs_type, device):
                continue

            stat_info = _stat_filesystem(mp, mount_point=mp, device=device, fs_type=fs_type)
            if stat_info is None:
                continue
            if not include_virtual and stat_info["total_bytes"] == 0:
                continue
            results.append(stat_info)

        if as_json:
            payload = {
                "command": "system.disk",
                "data": {
                    "total_filesystems": len(results),
                    "filesystems": results,
                },
            }
            out.write(json.dumps(payload, indent=2) + "\n")
        else:
            out.write("Mounted Filesystems\n\n")
            if not results:
                out.write("No filesystems found.\n")
                return 0

            headers = ("FILESYSTEM", "TYPE", "MOUNT POINT", "TOTAL", "USED", "AVAIL", "USE%")
            rows: list[tuple[str, str, str, str, str, str, str]] = []
            for item in results:
                rows.append(
                    (
                        item["device"],
                        item["filesystem_type"],
                        item["mount_point"],
                        _format_size(item["total_bytes"]),
                        _format_size(item["used_bytes"]),
                        _format_size(item["available_bytes"]),
                        f"{item['usage_percent']}%",
                    )
                )

            col_widths = [len(h) for h in headers]
            for row in rows:
                for idx, cell in enumerate(row):
                    col_widths[idx] = max(col_widths[idx], len(cell))

            header_str = (
                f"{headers[0]:<{col_widths[0]}}  "
                f"{headers[1]:<{col_widths[1]}}  "
                f"{headers[2]:<{col_widths[2]}}  "
                f"{headers[3]:>{col_widths[3]}}  "
                f"{headers[4]:>{col_widths[4]}}  "
                f"{headers[5]:>{col_widths[5]}}  "
                f"{headers[6]:>{col_widths[6]}}"
            )
            out.write(header_str + "\n")
            for row in rows:
                row_str = (
                    f"{row[0]:<{col_widths[0]}}  "
                    f"{row[1]:<{col_widths[1]}}  "
                    f"{row[2]:<{col_widths[2]}}  "
                    f"{row[3]:>{col_widths[3]}}  "
                    f"{row[4]:>{col_widths[4]}}  "
                    f"{row[5]:>{col_widths[5]}}  "
                    f"{row[6]:>{col_widths[6]}}"
                )
                out.write(row_str + "\n")
        return 0

    # Default: inspect filesystem of current working directory
    cwd = Path.cwd().resolve()
    mounts = _parse_mountinfo()
    best_match = None
    best_len = -1
    cwd_str = str(cwd)
    for m in mounts:
        mp = m["mount_point"]
        matches = cwd_str == mp or cwd_str.startswith(mp.rstrip("/") + "/") or mp == "/"
        if matches and len(mp) >= best_len:
            best_len = len(mp)
            best_match = m

    dev = best_match["device"] if best_match else "Unknown"
    fst = best_match["filesystem_type"] if best_match else "Unknown"
    mp = best_match["mount_point"] if best_match else cwd_str

    stat_info = _stat_filesystem(cwd, mount_point=mp, device=dev, fs_type=fst)
    if stat_info is None:
        raise OutputError("Cannot inspect disk usage for current working directory.")

    if as_json:
        payload = {
            "command": "system.disk",
            "data": {
                **stat_info,
                "total_filesystems": 1,
                "filesystems": [stat_info],
            },
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write("Disk Usage\n\n")
        out.write(f"Mount Point:     {stat_info['mount_point']}\n")
        out.write(f"Filesystem:      {stat_info['device']} ({stat_info['filesystem_type']})\n")
        out.write(f"Total Size:      {_format_size(stat_info['total_bytes'])}\n")
        used_str = _format_size(stat_info["used_bytes"])
        out.write(f"Used:            {used_str} ({stat_info['usage_percent']}%)\n")
        out.write(f"Available:       {_format_size(stat_info['available_bytes'])}\n")

    return 0


# =====================================================================
# 3. Memory Information
# =====================================================================


def _get_cgroup_memory_limit() -> tuple[int | None, int | None]:
    """Check cgroup v2 or v1 memory limit and current usage (nested container aware)."""
    # 1. cgroup v2
    for candidate in _get_cgroup_candidate_paths("memory"):
        max_file = candidate / "memory.max"
        cur_file = candidate / "memory.current"
        if max_file.is_file():
            try:
                content = max_file.read_text(encoding="utf-8").strip()
                if content and content != "max":
                    limit = int(content)
                    usage = None
                    if cur_file.is_file():
                        try:
                            usage = int(cur_file.read_text(encoding="utf-8").strip())
                        except (ValueError, OSError, PermissionError):
                            pass
                    return limit, usage
            except (ValueError, OSError, PermissionError):
                pass

    # 2. cgroup v1
    for candidate in _get_cgroup_candidate_paths("memory"):
        v1_limit_file = candidate / "memory.limit_in_bytes"
        v1_usage_file = candidate / "memory.usage_in_bytes"
        if v1_limit_file.is_file():
            try:
                val = int(v1_limit_file.read_text(encoding="utf-8").strip())
                # Values close to 2^63 - 1 mean unlimited
                if 0 < val < 0x7FFFFFFFFFFFF000:
                    usage = None
                    if v1_usage_file.is_file():
                        try:
                            usage = int(v1_usage_file.read_text(encoding="utf-8").strip())
                        except (ValueError, OSError, PermissionError):
                            pass
                    return val, usage
            except (ValueError, OSError, PermissionError):
                pass

    return None, None


def _parse_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into integer byte values keyed by field name."""
    mem: dict[str, int] = {}
    try:
        with open("/proc/meminfo", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                line = line.strip()
                if not line or ":" not in line:
                    continue
                key, val_str = line.split(":", 1)
                key = key.strip()
                parts = val_str.strip().split()
                if not parts:
                    continue
                try:
                    num = int(parts[0])
                except ValueError:
                    continue
                if num < 0:
                    raise OutputError("Negative value encountered in /proc/meminfo.")
                multiplier = 1024 if (len(parts) > 1 and parts[1].lower() == "kb") else 1
                mem[key] = num * multiplier
    except OSError as err:
        raise OutputError(f"Cannot read /proc/meminfo: {err}") from None
    return mem


def system_memory(*, as_json: bool = False, stdout_stream=None) -> int:
    """Inspect RAM, available memory, estimated used memory, and swap space."""
    out = sys.stdout if stdout_stream is None else stdout_stream

    mem = _parse_meminfo()
    total_bytes = mem.get("MemTotal", 0)
    free_bytes = mem.get("MemFree", 0)
    buffers_bytes = mem.get("Buffers", 0)
    cached_bytes = mem.get("Cached", 0)

    if "MemAvailable" in mem:
        available_bytes = mem["MemAvailable"]
    else:
        available_bytes = min(total_bytes, free_bytes + buffers_bytes + cached_bytes)

    used_estimated_bytes = max(0, total_bytes - available_bytes)
    ram_usage_pct = round((used_estimated_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0.0

    swap_total_bytes = mem.get("SwapTotal", 0)
    swap_free_bytes = mem.get("SwapFree", 0)
    swap_used_bytes = max(0, swap_total_bytes - swap_free_bytes)
    swap_usage_pct = (
        round((swap_used_bytes / swap_total_bytes) * 100, 1) if swap_total_bytes > 0 else 0.0
    )

    cgroup_limit, cgroup_usage = _get_cgroup_memory_limit()
    has_cgroup_limit = cgroup_limit is not None and total_bytes > 0 and cgroup_limit < total_bytes

    if as_json:
        payload = {
            "command": "system.memory",
            "data": {
                "ram": {
                    "total_bytes": total_bytes,
                    "available_bytes": available_bytes,
                    "used_estimated_bytes": used_estimated_bytes,
                    "usage_percent": ram_usage_pct,
                    "free_bytes": free_bytes,
                    "buffers_bytes": buffers_bytes,
                    "cached_bytes": cached_bytes,
                },
                "swap": {
                    "total_bytes": swap_total_bytes,
                    "used_bytes": swap_used_bytes,
                    "free_bytes": swap_free_bytes,
                    "usage_percent": swap_usage_pct,
                },
                "cgroup": (
                    {
                        "limit_bytes": cgroup_limit,
                        "usage_bytes": cgroup_usage,
                    }
                    if has_cgroup_limit
                    else None
                ),
            },
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write("Memory\n\n")
        out.write(f"RAM Total:      {_format_size(total_bytes):>10}\n")
        out.write(f"RAM Available:  {_format_size(available_bytes):>10}\n")
        used_ram_str = _format_size(used_estimated_bytes)
        out.write(f"RAM Used:       {used_ram_str:>10} (estimated, {ram_usage_pct}%)\n")
        if buffers_bytes > 0:
            out.write(f"RAM Buffers:    {_format_size(buffers_bytes):>10}\n")
        if cached_bytes > 0:
            out.write(f"RAM Cached:     {_format_size(cached_bytes):>10}\n")

        if has_cgroup_limit and cgroup_limit is not None:
            out.write(f"Container Limit:{_format_size(cgroup_limit):>10}\n")
            if cgroup_usage is not None:
                cgroup_pct = round((cgroup_usage / cgroup_limit) * 100, 1)
                out.write(f"Container Used: {_format_size(cgroup_usage):>10} ({cgroup_pct}%)\n")

        out.write("\n")
        if swap_total_bytes > 0:
            out.write(f"Swap Total:     {_format_size(swap_total_bytes):>10}\n")
            swap_used_str = _format_size(swap_used_bytes)
            out.write(f"Swap Used:      {swap_used_str:>10} ({swap_usage_pct}%)\n")
            out.write(f"Swap Free:      {_format_size(swap_free_bytes):>10}\n")
        else:
            out.write("Swap Total:            0 B (no swap configured)\n")

    return 0


# =====================================================================
# 4. Process Information & Early Filtering
# =====================================================================

COMMON_INTERPRETERS = {
    "python",
    "python3",
    "node",
    "bash",
    "sh",
    "zsh",
    "ruby",
    "perl",
    "php",
    "java",
}


def _parse_proc_stat_line(line: str) -> tuple[int, str, str, int, int, int, int] | None:
    """Parse /proc/<pid>/stat safely handling process names with spaces and parens."""
    left = line.find("(")
    right = line.rfind(")")
    if left == -1 or right == -1 or left >= right:
        return None

    try:
        pid = int(line[:left].strip())
        comm = line[left + 1 : right]
        rest = line[right + 1 :].split()
        if len(rest) < 20:
            return None

        state = rest[0]
        ppid = int(rest[1])
        utime = int(rest[11])
        stime = int(rest[12])
        starttime = int(rest[19])
        return pid, comm, state, ppid, utime, stime, starttime
    except (ValueError, IndexError):
        return None


def _get_process_status(pid: int) -> tuple[int | None, int | None, int]:
    """Read UID, VmRSS (in bytes), and thread count from /proc/<pid>/status."""
    uid: int | None = None
    rss_bytes: int | None = None
    threads: int = 1
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                line = line.strip()
                if line.startswith("Uid:"):
                    parts = line.split()
                    if len(parts) > 1:
                        uid = int(parts[1])
                elif line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) > 1:
                        rss_bytes = int(parts[1]) * 1024
                elif line.startswith("Threads:"):
                    parts = line.split()
                    if len(parts) > 1:
                        threads = int(parts[1])
    except (OSError, ProcessLookupError, PermissionError):
        pass
    return uid, rss_bytes, threads


def _get_process_cpu_times(
    pid: int, main_utime: int, main_stime: int, thread_count: int, max_threads: int = 64
) -> tuple[int, int]:
    """Sum utime and stime across worker threads with thread limit to prevent I/O storm."""
    if thread_count <= 1:
        return main_utime, main_stime

    total_utime = 0
    total_stime = 0
    task_dir = f"/proc/{pid}/task"
    try:
        tids = os.listdir(task_dir)[:max_threads]
        for tid in tids:
            try:
                with open(f"{task_dir}/{tid}/stat", encoding="utf-8", errors="replace") as s:
                    t_line = s.readline()
                right = t_line.rfind(")")
                if right != -1:
                    tokens = t_line[right + 1 :].split()
                    if len(tokens) >= 13:
                        total_utime += int(tokens[11])
                        total_stime += int(tokens[12])
            except (OSError, ProcessLookupError, PermissionError, ValueError, IndexError):
                continue
    except (OSError, ProcessLookupError, PermissionError):
        return main_utime, main_stime

    return (total_utime, total_stime) if (total_utime or total_stime) else (main_utime, main_stime)


def _get_process_cmdline(pid: int, comm: str) -> tuple[str, str]:
    """Read command line from /proc/<pid>/cmdline, resolving binary and script name."""
    cmdline_path = f"/proc/{pid}/cmdline"
    try:
        with open(cmdline_path, "rb") as s:
            raw = s.read(4096)
        if raw:
            if isinstance(raw, bytes):
                parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\x00") if p]
            else:
                parts = [p for p in raw.split("\x00") if p]
            if parts:
                full_cmd = " ".join(parts)
                first_arg = parts[0]
                first_token = first_arg.split()[0] if first_arg.strip() else first_arg
                bin_name = first_token.rpartition("/")[2] or first_token

                # If binary is an interpreter (python, node, bash...), display script name
                all_tokens: list[str] = []
                for p in parts:
                    all_tokens.extend(p.split())

                if bin_name in COMMON_INTERPRETERS and len(all_tokens) > 1:
                    script_name = None
                    for candidate in all_tokens[1:]:
                        if not candidate.startswith("-"):
                            script_name = candidate.rpartition("/")[2] or candidate
                            break
                    if script_name:
                        return f"{bin_name} {script_name}", full_cmd
                return bin_name, full_cmd
    except (OSError, ProcessLookupError, PermissionError):
        pass
    return comm, f"[{comm}]"


@functools.lru_cache(maxsize=1024)
def _get_username(uid: int | None) -> str:
    """Resolve numeric UID to username with caching to prevent NSS/LDAP bottlenecks."""
    if uid is None:
        return "Unknown"
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OSError):
        return str(uid)


def system_process(
    *,
    sort_by: str = "cpu",
    limit: int = 20,
    pid: int | None = None,
    name_filter: str | None = None,
    user_filter: str | None = None,
    as_json: bool = False,
    stdout_stream=None,
) -> int:
    """Inspect running processes, their lifetime CPU usage, and RSS memory."""
    out = sys.stdout if stdout_stream is None else stdout_stream

    sort_field = sort_by.lower()
    valid_sorts = ("cpu", "memory", "pid", "name")
    if sort_field not in valid_sorts:
        raise UsageError(f"Invalid sort field: {sort_by}. Choose from: {', '.join(valid_sorts)}")

    if limit < 1:
        raise UsageError("Limit must be an integer greater than or equal to 1.")

    if pid is not None and pid < 1:
        raise UsageError("PID must be a positive integer.")

    uptime_sec = _get_uptime_seconds() or 0.0
    try:
        clk_tck = os.sysconf("SC_CLK_TCK")
    except (AttributeError, ValueError, OSError):
        clk_tck = 100

    pids_to_scan: list[int] = []
    if pid is not None:
        pids_to_scan.append(pid)
    else:
        try:
            for entry in os.listdir("/proc"):
                if entry.isdigit():
                    pids_to_scan.append(int(entry))
        except OSError as err:
            raise OutputError(f"Cannot read /proc: {err}") from None

    current_pid = os.getpid()
    processes: list[dict[str, Any]] = []

    for p in pids_to_scan:
        # Avoid the "LUT always Top 1 CPU" paradox by excluding self when scanning all
        if pid is None and p == current_pid:
            continue

        stat_file = f"/proc/{p}/stat"
        try:
            with open(stat_file, encoding="utf-8", errors="replace") as stream:
                line = stream.readline().strip()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        except OSError:
            continue

        parsed = _parse_proc_stat_line(line)
        if parsed is None:
            continue
        proc_pid, comm, state, ppid, utime, stime, starttime = parsed

        # Early filtering by name before opening status or task files
        short_cmd, full_command = _get_process_cmdline(proc_pid, comm)
        if name_filter:
            nf = name_filter.lower()
            if (
                nf not in comm.lower()
                and nf not in short_cmd.lower()
                and nf not in full_command.lower()
            ):
                continue

        status_res = _get_process_status(proc_pid)
        if len(status_res) >= 3:
            uid, rss_bytes, thread_count = status_res[0], status_res[1], status_res[2]
        else:
            uid, rss_bytes = status_res[0], status_res[1]
            thread_count = 1

        user_str = _get_username(uid)
        if user_filter:
            uf = user_filter.lower()
            if user_str.lower() != uf and str(uid) != user_filter:
                continue

        # Only scan worker threads when sorting by CPU or inspecting single PID
        if sort_field == "cpu" or pid is not None:
            total_utime, total_stime = _get_process_cpu_times(proc_pid, utime, stime, thread_count)
        else:
            total_utime, total_stime = utime, stime

        # Calculate lifetime CPU with race condition & sub-second spike protection
        uptime_now = _get_uptime_seconds() or uptime_sec
        start_sec = starttime / clk_tck
        elapsed_sec = uptime_now - start_sec

        if elapsed_sec <= 0.05:
            cpu_percent = 0.0
        else:
            total_time_sec = (total_utime + total_stime) / clk_tck
            # Use max(0.5, elapsed_sec) to avoid transient CPU spikes on processes born < 0.5s ago
            raw_pct = (total_time_sec / max(0.5, elapsed_sec)) * 100
            cpu_percent = round(max(0.0, raw_pct), 1)

        processes.append(
            {
                "pid": proc_pid,
                "ppid": ppid,
                "name": short_cmd,
                "comm": comm,
                "command": full_command,
                "user": user_str,
                "uid": uid,
                "state": state,
                "threads": thread_count,
                "cpu_percent": cpu_percent,
                "memory_rss_bytes": rss_bytes or 0,
            }
        )

    if pid is not None and not processes:
        raise InputError(f"Process not found with PID: {pid}")

    total_count = len(processes)

    # Sort processes
    if sort_field == "cpu":
        processes.sort(key=lambda x: (x["cpu_percent"], x["memory_rss_bytes"]), reverse=True)
    elif sort_field == "memory":
        processes.sort(key=lambda x: (x["memory_rss_bytes"], x["cpu_percent"]), reverse=True)
    elif sort_field == "pid":
        processes.sort(key=lambda x: x["pid"])
    elif sort_field == "name":
        processes.sort(key=lambda x: (x["name"].lower(), x["pid"]))

    displayed = processes[:limit]

    if as_json:
        payload = {
            "command": "system.process",
            "data": {
                "total_processes": total_count,
                "returned_processes": len(displayed),
                "sort_by": sort_field,
                "process": displayed[0] if pid is not None and displayed else None,
                "processes": displayed,
            },
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        if pid is not None and displayed:
            # Single process detail view
            target_proc = displayed[0]
            out.write(f"Process Details (PID {target_proc['pid']})\n\n")
            out.write(f"PID:          {target_proc['pid']}\n")
            out.write(f"PPID:         {target_proc['ppid']}\n")
            out.write(f"Name:         {target_proc['name']}\n")
            out.write(f"Command:      {target_proc['command']}\n")
            out.write(f"User:         {target_proc['user']} (UID: {target_proc['uid']})\n")
            out.write(f"Threads:      {target_proc['threads']}\n")
            out.write(f"State:        {target_proc['state']}\n")
            out.write(f"CPU%:         {target_proc['cpu_percent']:.1f}% (lifetime average)\n")
            out.write(f"Memory RSS:   {_format_size(target_proc['memory_rss_bytes'])}\n")
            return 0

        out.write(
            f"Processes (sorted by {sort_field}, limit {limit}) [CPU% is lifetime average]\n\n"
        )
        if not displayed:
            out.write("No matching processes found.\n")
            return 0

        headers = ("PID", "PPID", "USER", "STATE", "CPU%", "RSS", "COMMAND")
        rows: list[tuple[str, str, str, str, str, str, str]] = []
        for p_info in displayed:
            rows.append(
                (
                    str(p_info["pid"]),
                    str(p_info["ppid"]),
                    p_info["user"][:12],
                    p_info["state"],
                    f"{p_info['cpu_percent']:.1f}",
                    _format_size(p_info["memory_rss_bytes"]),
                    p_info["name"],
                )
            )

        col_widths = [len(h) for h in headers]
        for row in rows:
            for idx, cell in enumerate(row):
                col_widths[idx] = max(col_widths[idx], len(cell))

        header_str = (
            f"{headers[0]:>{col_widths[0]}}  "
            f"{headers[1]:<{col_widths[1]}}  "
            f"{headers[2]:<{col_widths[2]}}  "
            f"{headers[3]:^{col_widths[3]}}  "
            f"{headers[4]:>{col_widths[4]}}  "
            f"{headers[5]:>{col_widths[5]}}  "
            f"{headers[6]}"
        )
        out.write(header_str + "\n")
        for row in rows:
            row_str = (
                f"{row[0]:>{col_widths[0]}}  "
                f"{row[1]:<{col_widths[1]}}  "
                f"{row[2]:<{col_widths[2]}}  "
                f"{row[3]:^{col_widths[3]}}  "
                f"{row[4]:>{col_widths[4]}}  "
                f"{row[5]:>{col_widths[5]}}  "
                f"{row[6]}"
            )
            out.write(row_str + "\n")

    return 0


# =====================================================================
# 5. Network Ports (Canonical IPv6 & Zero-Guessing Protocols)
# =====================================================================


def _normalize_network_address(raw_addr: str) -> str:
    """Normalize IPv4/IPv6 addresses into canonical form across ss and /proc/net."""
    clean = raw_addr.replace("[", "").replace("]", "")
    if clean in ("*", "0.0.0.0"):
        return "0.0.0.0"
    if clean == "::":
        return "::"
    try:
        ip = ipaddress.ip_address(clean)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ip)
    except ValueError:
        return clean


def _parse_ss_process_field(line: str) -> tuple[str | None, int | None]:
    """Parse process name and PID from ss user column (e.g. users:(("app",pid=123,fd=4)))."""
    match = re.search(r'\("([^"]+)",pid=(\d+)', line)
    if match:
        return match.group(1), int(match.group(2))
    return None, None


def _parse_ss_address_port(addr_port_str: str) -> tuple[str, int | None]:
    """Split address and port using rpartition to safely handle IPv6 addresses."""
    addr_part, sep, port_part = addr_port_str.rpartition(":")
    if not sep:
        return _normalize_network_address(addr_port_str), None
    port_val: int | None = None
    if port_part.isdigit():
        port_val = int(port_part)
    return _normalize_network_address(addr_part), port_val


def _parse_proc_net_ip_port(raw_ip_port: str) -> tuple[str, int | None]:
    """Parse hex IP:PORT from /proc/net/tcp and /proc/net/udp into canonical format."""
    parts = raw_ip_port.split(":")
    if len(parts) != 2:
        return _normalize_network_address(raw_ip_port), None
    hex_ip, hex_port = parts
    try:
        port = int(hex_port, 16)
    except ValueError:
        port = None

    try:
        if len(hex_ip) == 8:
            ip_str = socket.inet_ntoa(struct.pack("<I", int(hex_ip, 16)))
        elif len(hex_ip) == 32:
            words = struct.unpack("<4I", bytes.fromhex(hex_ip))
            ip_str = socket.inet_ntop(socket.AF_INET6, struct.pack(">4I", *words))
        else:
            ip_str = hex_ip
    except (OSError, ValueError):
        ip_str = hex_ip

    return _normalize_network_address(ip_str), port


PROC_NET_STATES = {
    "01": "ESTAB",
    "02": "SYN-SENT",
    "03": "SYN-RECV",
    "04": "FIN-WAIT-1",
    "05": "FIN-WAIT-2",
    "06": "TIME-WAIT",
    "07": "CLOSE",
    "08": "CLOSE-WAIT",
    "09": "LAST-ACK",
    "0A": "LISTEN",
    "0B": "CLOSING",
}


def _get_socket_inodes_map() -> dict[int, tuple[int, str]]:
    """Map socket inode to (pid, comm) by scanning /proc/*/fd."""
    inode_map: dict[int, tuple[int, str]] = {}
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            proc_pid = int(entry)
            fd_dir = f"/proc/{proc_pid}/fd"
            try:
                for fd in os.listdir(fd_dir):
                    try:
                        target = os.readlink(f"{fd_dir}/{fd}")
                        if target.startswith("socket:[") and target.endswith("]"):
                            inode_str = target[8:-1]
                            if inode_str.isdigit():
                                inode = int(inode_str)
                                if inode not in inode_map:
                                    comm = "Unknown"
                                    try:
                                        with open(f"/proc/{proc_pid}/comm", encoding="utf-8") as s:
                                            comm = s.readline().strip()
                                    except OSError:
                                        pass
                                    inode_map[inode] = (proc_pid, comm)
                    except (OSError, ProcessLookupError, PermissionError):
                        continue
            except (OSError, ProcessLookupError, PermissionError):
                continue
    except OSError:
        pass
    return inode_map


def _scan_ports_proc_net(
    proto_clean: str | None, port: int | None, all_sockets: bool
) -> list[dict[str, Any]]:
    """Scan open ports purely via Linux /proc/net without requiring external binaries."""
    files_to_scan: list[tuple[str, str]] = []
    if proto_clean in (None, "tcp"):
        files_to_scan.append(("/proc/net/tcp", "tcp"))
        files_to_scan.append(("/proc/net/tcp6", "tcp"))
    if proto_clean in (None, "udp"):
        files_to_scan.append(("/proc/net/udp", "udp"))
        files_to_scan.append(("/proc/net/udp6", "udp"))

    inode_map = _get_socket_inodes_map()
    entries: list[dict[str, Any]] = []

    for file_path, proto in files_to_scan:
        p = Path(file_path)
        if not p.is_file():
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as stream:
                lines = stream.readlines()
        except OSError:
            continue

        for line in lines[1:]:
            tokens = line.strip().split()
            if len(tokens) < 10:
                continue
            local_raw = tokens[1]
            st_hex = tokens[3].upper()
            inode_raw = tokens[9]

            state = PROC_NET_STATES.get(st_hex, st_hex)

            if not all_sockets:
                if proto == "tcp" and st_hex != "0A":
                    continue
                if proto == "udp" and st_hex not in ("07", "01"):
                    continue

            local_addr, local_port = _parse_proc_net_ip_port(local_raw)
            if local_port is None:
                continue

            if port is not None and local_port != port:
                continue

            inode_val = int(inode_raw) if inode_raw.isdigit() else None
            proc_pid, proc_name = (None, None)
            if inode_val and inode_val in inode_map:
                proc_pid, proc_name = inode_map[inode_val]

            entries.append(
                {
                    "protocol": proto,
                    "local_address": local_addr,
                    "local_port": local_port,
                    "state": "UNCONN" if (proto == "udp" and state == "CLOSE") else state,
                    "pid": proc_pid,
                    "process": proc_name,
                }
            )

    return entries


def system_ports(
    *,
    protocol: str | None = None,
    port: int | None = None,
    all_sockets: bool = False,
    as_json: bool = False,
    stdout_stream=None,
) -> int:
    """Inspect open network ports and listening sockets (via ss or /proc/net fallback)."""
    out = sys.stdout if stdout_stream is None else stdout_stream

    if protocol is not None:
        proto_clean = protocol.lower()
        if proto_clean not in ("tcp", "udp"):
            raise UsageError(f"Invalid protocol: {protocol}. Supported protocols: tcp, udp")
    else:
        proto_clean = None

    if port is not None:
        if port < 1 or port > 65535:
            raise UsageError("Port must be an integer between 1 and 65535.")

    ss_bin = shutil.which("ss")
    entries: list[dict[str, Any]] = []

    if ss_bin:
        # Query protocols deterministically in separate invocations to avoid column guessing
        protocols_to_query: list[str] = []
        if proto_clean in (None, "tcp"):
            protocols_to_query.append("tcp")
        if proto_clean in (None, "udp"):
            protocols_to_query.append("udp")

        for current_proto in protocols_to_query:
            if current_proto == "tcp":
                flag = "-tan" if all_sockets else "-tln"
            else:
                flag = "-uan" if all_sockets else "-uln"

            args = [ss_bin, "-p", "-n", "-H", flag]
            proc_result = run_process(args, timeout=10)
            lines = proc_result.stdout.splitlines()

            for line in lines:
                line_clean = line.strip()
                if not line_clean or line_clean.startswith("Netid"):
                    continue

                tokens = line_clean.split()
                if len(tokens) < 4:
                    continue

                # Handle column layout differences across ss versions:
                # In single protocol queries, column 0 is State and column 3 is Address:Port.
                # In mixed protocol queries, column 0 is Netid and column 4 is Address:Port.
                if tokens[0].lower() in ("tcp", "udp", "tcp6", "udp6"):
                    line_proto = "tcp" if tokens[0].lower().startswith("tcp") else "udp"
                    if line_proto != current_proto:
                        continue
                    state = tokens[1]
                    local_raw = tokens[4] if len(tokens) >= 5 else tokens[3]
                else:
                    state = tokens[0]
                    local_raw = tokens[3]

                local_addr, local_port = _parse_ss_address_port(local_raw)
                if local_port is None:
                    continue

                if port is not None and local_port != port:
                    continue

                proc_name, proc_pid = _parse_ss_process_field(line_clean)

                entries.append(
                    {
                        "protocol": current_proto,
                        "local_address": local_addr,
                        "local_port": local_port,
                        "state": state,
                        "pid": proc_pid,
                        "process": proc_name,
                    }
                )
    elif Path("/proc/net/tcp").is_file() or Path("/proc/net/udp").is_file():
        # Fallback to pure Python /proc/net scan
        entries = _scan_ports_proc_net(proto_clean, port, all_sockets)
    else:
        raise DependencyError("Missing dependency: ss (iproute2) and /proc/net is unavailable.")

    # Sort ports by port number, then protocol, then address
    entries.sort(key=lambda x: (x["local_port"], x["protocol"], x["local_address"]))

    has_hidden_procs = any(p["pid"] is None for p in entries)
    is_non_root = hasattr(os, "geteuid") and os.geteuid() != 0

    if as_json:
        payload = {
            "command": "system.ports",
            "data": {
                "total_ports": len(entries),
                "ports": entries,
            },
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write("Open Network Ports\n\n")
        if not entries:
            out.write("No matching open ports found.\n")
            return 0

        headers = ("PROTO", "STATE", "LOCAL ADDRESS", "PORT", "PID", "PROCESS")
        rows: list[tuple[str, str, str, str, str, str]] = []
        for p in entries:
            rows.append(
                (
                    p["protocol"],
                    p["state"],
                    p["local_address"],
                    str(p["local_port"]),
                    str(p["pid"]) if p["pid"] is not None else "Unknown",
                    p["process"] if p["process"] is not None else "Unknown",
                )
            )

        col_widths = [len(h) for h in headers]
        for row in rows:
            for idx, cell in enumerate(row):
                col_widths[idx] = max(col_widths[idx], len(cell))

        header_str = (
            f"{headers[0]:<{col_widths[0]}}  "
            f"{headers[1]:<{col_widths[1]}}  "
            f"{headers[2]:<{col_widths[2]}}  "
            f"{headers[3]:>{col_widths[3]}}  "
            f"{headers[4]:>{col_widths[4]}}  "
            f"{headers[5]:<{col_widths[5]}}"
        )
        out.write(header_str + "\n")
        for row in rows:
            row_str = (
                f"{row[0]:<{col_widths[0]}}  "
                f"{row[1]:<{col_widths[1]}}  "
                f"{row[2]:<{col_widths[2]}}  "
                f"{row[3]:>{col_widths[3]}}  "
                f"{row[4]:>{col_widths[4]}}  "
                f"{row[5]:<{col_widths[5]}}"
            )
            out.write(row_str + "\n")

        if is_non_root and has_hidden_procs:
            out.write("\nNote: Run with root/sudo or CAP_NET_ADMIN to view all process names.\n")

    return 0
